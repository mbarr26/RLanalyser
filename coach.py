"""AI coach: explains a match's key moments with a small language model that runs on the user's PC.

Python measures, the AI explains: every fact (times, positions, boost, mistakes) is computed in
moments.py / analysis.py and handed to the model as text, so it only has to turn numbers into
advice. The model runs in a bundled llama.cpp `llama-server.exe` (tools/llama-server/) that this
module starts on a random localhost port when first needed and stops when the app exits. The
model file (GGUF) is downloaded once, on request, to %LOCALAPPDATA%\\RLAnalyser\\models.

Command line, for trying it on one replay:
    python coach.py path\\to\\match.replay [--me "Player name"] [--tier lite|standard] [--no-ai]
"""

import atexit
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from analysis import THIRD_LINE
from moments import detect_moments, fmt_clock, insights
from paths import LOCAL_DIR, bundled, models_dir, user_data

# Bump when prompts, the dossier or the report format change, so old saved reports are redone
COACH_VERSION = 1

SERVER_EXE = bundled("tools", "llama-server", "llama-server.exe")
CTX_SIZE = 8192
REPLY_RESERVE = 1200        # tokens kept free for the model's answer when trimming chat history
CHARS_PER_TOKEN = 3.0       # pessimistic, so trimmed history really fits

# Models are downloaded on demand from Hugging Face (Apache-2.0). Pinned by size and SHA-256.
TIERS = {
    "lite": {
        "label": "Lite", "hint": "Works on most laptops (about 4 GB of free RAM or graphics memory)",
        "repo": "unsloth/Qwen3.5-4B-GGUF", "file": "Qwen3.5-4B-Q4_K_M.gguf",
        "size": 2740937888, "sha256": "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
    },
    "standard": {
        "label": "Standard", "hint": "Better advice. Wants a graphics card with 8 GB+, or 16 GB of RAM (slower)",
        "repo": "unsloth/Qwen3.5-9B-GGUF", "file": "Qwen3.5-9B-Q4_K_M.gguf",
        "size": 5680522464, "sha256": "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
    },
}
DEFAULT_TIER = "lite"
DOWNLOAD_RETRIES = 8        # consecutive failed attempts (with no progress) before giving up


class CoachError(Exception):
    """A problem the user can be told about (missing model, engine not starting, ...)."""


# ---------- model files ----------

def model_path(tier):
    return models_dir() / TIERS[tier]["file"]


def model_ready(tier):
    path = model_path(tier)
    return path.is_file() and path.stat().st_size == TIERS[tier]["size"]


def status(tier):
    """What the UI needs to show the setup state."""
    return {
        "engine": SERVER_EXE.is_file(),
        "tier": tier,
        "ready": model_ready(tier),
        "running": _server is not None and _server.proc.poll() is None,
        "tiers": {
            name: {"label": spec["label"], "hint": spec["hint"], "sizeGb": round(spec["size"] / 1e9, 1),
                   "downloaded": model_ready(name)}
            for name, spec in TIERS.items()
        },
    }


def _sha256(path, on_progress=None):
    digest, done, total = hashlib.sha256(), 0, path.stat().st_size
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            digest.update(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total, "verify")
    return digest.hexdigest()


def download_model(tier, on_progress=None, cancel=None):
    """Download a tier's model (resumable) and check it. on_progress(done, total, phase)."""
    spec = TIERS[tier]
    if model_ready(tier):
        return
    models_dir().mkdir(parents=True, exist_ok=True)
    target = model_path(tier)
    part = target.with_name(target.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > spec["size"]:
        part.unlink()
        have = 0
    last_report = 0.0

    def report(done, total, phase):
        nonlocal last_report
        now = time.monotonic()
        if on_progress and (now - last_report > 0.25 or done >= total):
            last_report = now
            on_progress(done, total, phase)

    url = f"https://huggingface.co/{spec['repo']}/resolve/main/{spec['file']}"
    failures = 0
    while have < spec["size"]:
        headers = {"User-Agent": "RLAnalyser"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                if have and resp.status != 206:
                    have = 0  # the server ignored the range: start again
                with open(part, "ab" if have else "wb") as f:
                    while chunk := resp.read(1 << 20):
                        if cancel and cancel.is_set():
                            raise CoachError("Download cancelled")
                        try:
                            f.write(chunk)
                        except OSError as e:
                            raise CoachError(f"Couldn't save the model (is the disk full?): {e}") from e
                        have += len(chunk)
                        failures = 0   # still making progress
                        report(have, spec["size"], "download")
        except OSError as e:   # includes URLError: a dropped connection resumes where it stopped
            failures += 1
            if failures > DOWNLOAD_RETRIES:
                raise CoachError(f"Couldn't download the model ({getattr(e, 'reason', e)}). "
                                 "Check your connection and try again; it will carry on where it stopped.") from e
            have = part.stat().st_size if part.exists() else 0
            time.sleep(min(2 * failures, 10))

    if _sha256(part, report) != spec["sha256"]:
        part.unlink(missing_ok=True)
        raise CoachError("The downloaded model file was damaged. Please download it again.")
    os.replace(part, target)


# ---------- the local model server ----------

class _Server:
    def __init__(self, proc, port, key, tier):
        self.proc, self.port, self.key, self.tier = proc, port, key, tier


_server = None
_server_lock = threading.Lock()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stop_server():
    global _server
    with _server_lock:
        server, _server = _server, None
    if server and server.proc.poll() is None:
        server.proc.terminate()
        try:
            server.proc.wait(5)
        except subprocess.TimeoutExpired:
            server.proc.kill()


atexit.register(stop_server)


def ensure_server(tier, on_state=None):
    """Start llama-server for this tier if it isn't already running. Blocks until it is ready."""
    global _server
    with _server_lock:
        if _server and _server.proc.poll() is None and _server.tier == tier:
            return _server
    stop_server()
    if not SERVER_EXE.is_file():
        raise CoachError(f"The AI engine is missing ({SERVER_EXE}).")
    if not model_ready(tier):
        raise CoachError("The AI model hasn't been downloaded yet.")
    if on_state:
        on_state("starting")

    port, key = _free_port(), secrets.token_hex(16)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOCAL_DIR / "llama-server.log"
    command = [
        str(SERVER_EXE), "-m", str(model_path(tier)), "--host", "127.0.0.1", "--port", str(port),
        "--api-key", key, "--ctx-size", str(CTX_SIZE), "-ngl", "99", "-np", "1",
        "--reasoning", "off",
    ]
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + 300   # a big model can take a while to load from disk
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text(errors="replace")[-600:].strip()
            raise CoachError(f"The AI engine stopped while starting.\n{tail}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                if resp.status == 200:
                    break
        except OSError:
            pass  # still loading (503) or not listening yet
        time.sleep(0.5)
    else:
        proc.kill()
        raise CoachError("The AI engine took too long to start.")
    with _server_lock:
        _server = _Server(proc, port, key, tier)
    return _server


def _chat_request(server, payload, timeout):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {server.key}"},
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise CoachError(f"The AI engine rejected the request ({e.code}): {e.read()[:300].decode('utf-8', 'replace')}") from e
    except OSError as e:
        raise CoachError(f"The AI engine isn't responding ({e}).") from e


def _complete_json(tier, messages, schema, max_tokens=1600):
    server = ensure_server(tier)
    payload = {
        "messages": messages, "temperature": 0.3, "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": {"name": "report", "strict": True, "schema": schema}},
    }
    with _chat_request(server, payload, timeout=900) as resp:
        body = json.load(resp)
    choice = body["choices"][0]
    try:
        return json.loads(choice["message"]["content"])
    except (ValueError, TypeError) as e:
        raise CoachError("The AI's answer was cut off or malformed. Please try again.") from e


def _stream_chat(tier, messages, max_tokens=700):
    """Yield the reply text piece by piece."""
    server = ensure_server(tier)
    payload = {"messages": messages, "temperature": 0.4, "max_tokens": max_tokens, "stream": True}
    with _chat_request(server, payload, timeout=900) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
            except (ValueError, KeyError, IndexError):
                continue
            if delta:
                yield delta


# ---------- what the model is told ----------

# (column, label) for the stats given to the model, from analysis.player_stats
DOSSIER_STATS = [
    ("avg_speed", "avg speed"), ("pct_supersonic", "% supersonic"), ("pct_behind_ball", "% behind ball"),
    ("pct_def_third", "% in own third"), ("pct_off_third", "% in attacking third"),
    ("avg_dist_to_ball", "avg dist to ball"), ("pct_closest_to_ball", "% closest to ball on team"),
    ("avg_boost", "avg boost"), ("pct_zero_boost", "% at 0 boost"), ("boost_used", "boost used"),
    ("big_pads", "big pads"), ("stolen_big_pads", "stolen big pads"),
]
TEAM = {0: "Blue", 1: "Orange"}

SYSTEM_PROMPT = """You are a friendly, honest Rocket League coach. You analyse one match for the player named {me}, who is on the {team} team.

You are given measured facts about the match: stats, a list of key moments (each has an id like m3), and rule-based findings. Rules:
- Use ONLY the facts you are given. Never invent times, scores, stats, players or events. If something isn't in the data, say you can't tell.
- Talk to the player as "you". Be specific and brief: short sentences, concrete advice (rotation, boost management, challenging, shadow defending, positioning).
- Refer to key moments by their id.
- Only call something a strength or weakness if the RULE-BASED FINDINGS or KEY MOMENTS say so, or if it clearly differs from the player's USUAL AVERAGES. Never judge a raw stat on its own.
- How to read the stats: "% behind ball" higher = better defensive positioning; "% at 0 boost" lower = better; "% closest to ball on team" is just involvement, not good or bad; "avg dist to ball" is context only."""

REPORT_TASK = """Write the match analysis for {me} as JSON.
- summary: 2-3 sentences on how the game went and why.
- strengths and weaknesses: 2-4 short points each, taken from the rule-based findings and key moments (mention the numbers they give). If the data shows no real strength, return an empty strengths list instead of inventing praise.
- key_moments: pick the most important moments for {me} (at most 8). For each: what happened, and one piece of advice.
- focus_for_next_games: 2-3 specific things to practise."""


def build_dossier(record, moments, me_name, usual=None, rule_insights=None):
    """The facts about one match as compact text for the model (roughly 1.5-3K tokens)."""
    s = record.summary
    mins, secs = divmod(int(s.seconds_played), 60)
    lines = [
        f"MATCH: {s.team_size}v{s.team_size} {s.match_type} on {s.map_name}, {s.date}, length {mins}:{secs:02d}",
        f"FINAL SCORE: Blue {s.team0_score} - {s.team1_score} Orange",
        f"THE PLAYER YOU COACH: {me_name}",
        "",
        "PLAYERS (scoreboard):",
    ]
    for p in sorted(s.players, key=lambda p: (p.team, -p.score)):
        lines.append(f"- {p.name} ({TEAM[p.team]}): score {p.score}, goals {p.goals}, assists {p.assists}, "
                     f"saves {p.saves}, shots {p.shots}")
    lines += ["", "PLAYER STATS (live play only; positions are relative to each player's own goal):"]
    for name, row in sorted((record.players or {}).items(), key=lambda kv: kv[1]["team"]):
        stats = ", ".join(f"{label} {row[col]:.0f}" for col, label in DOSSIER_STATS if row.get(col) is not None)
        lines.append(f"- {name} ({TEAM[row['team']]}): {stats}")
    if record.match:
        m = record.match
        lines += ["", f"BALL: {m['ball_pct_blue_half']:.0f}% of live play in Blue's half, "
                      f"{m['ball_pct_orange_half']:.0f}% in Orange's half; average ball speed {m['ball_avg_speed']:.0f}"]
    if usual:
        pairs = ", ".join(f"{label} {usual[col]:.0f}" for col, label in DOSSIER_STATS if usual.get(col) is not None)
        lines += ["", f"{me_name}'S USUAL AVERAGES over previous games: {pairs}"]
    lines += ["", "KEY MOMENTS (times are the game clock, counting down):"]
    for m in moments:
        clock = f"{m['clock_text']} " if m["clock_text"] else ""
        lines.append(f"[{m['id']}] {clock}{m['title']} - {m['detail']}")
    if not moments:
        lines.append("(none detected)")
    if rule_insights:
        lines += ["", "RULE-BASED FINDINGS ABOUT THE PLAYER:"] + [f"- {i['text']}" for i in rule_insights]
    return "\n".join(lines)


def _report_schema(moment_ids):
    text = {"type": "string"}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "strengths", "weaknesses", "key_moments", "focus_for_next_games"],
        "properties": {
            "summary": text,
            "strengths": {"type": "array", "items": text, "maxItems": 4},
            "weaknesses": {"type": "array", "items": text, "maxItems": 4},
            "key_moments": {
                "type": "array", "maxItems": min(8, len(moment_ids)),
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["moment_id", "title", "what_happened", "advice"],
                    "properties": {
                        "moment_id": {"type": "string", "enum": moment_ids or ["none"]},
                        "title": text, "what_happened": text, "advice": text,
                    },
                },
            },
            "focus_for_next_games": {"type": "array", "items": text, "maxItems": 3},
        },
    }


def generate_report(dossier, moments, me_name, team, tier):
    """Ask the model for the match analysis. Times and clocks come from our moments, never the model."""
    ids = [m["id"] for m in moments]
    system = SYSTEM_PROMPT.format(me=me_name, team=TEAM[team])
    user = f"MATCH DATA\n{dossier}\n\n{REPORT_TASK.format(me=me_name)}"
    raw = _complete_json(tier, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                         _report_schema(ids))
    by_id = {m["id"]: m for m in moments}
    seen, key_moments = set(), []
    for item in raw.get("key_moments", []):
        moment = by_id.get(item.get("moment_id"))
        if moment is None or moment["id"] in seen:
            continue
        seen.add(moment["id"])
        key_moments.append({
            "id": moment["id"], "time": moment["time"], "clock_text": moment["clock_text"], "type": moment["type"],
            "title": str(item.get("title", moment["title"])), "what_happened": str(item.get("what_happened", "")),
            "advice": str(item.get("advice", "")),
        })
    key_moments.sort(key=lambda k: k["time"])

    def strings(name):
        return [str(x) for x in raw.get(name, []) if str(x).strip()]

    return {
        "summary": str(raw.get("summary", "")), "strengths": strings("strengths"),
        "weaknesses": strings("weaknesses"), "key_moments": key_moments,
        "focus_for_next_games": strings("focus_for_next_games"),
    }


# ---------- saved reports ----------

def _report_path(replay):
    return user_data("cache", f"{Path(replay).stem}.coach.json")


def _report_key(replay, tier, me_name):
    stat = Path(replay).stat()
    return {"version": COACH_VERSION, "tier": tier, "me": me_name, "mtime": stat.st_mtime, "size": stat.st_size}


def load_report(replay, tier, me_name):
    try:
        data = json.loads(_report_path(replay).read_text(encoding="utf-8"))
        return data["report"] if data["key"] == _report_key(replay, tier, me_name) else None
    except (OSError, ValueError, KeyError):
        return None


def save_report(replay, tier, me_name, report):
    path = _report_path(replay)
    path.parent.mkdir(exist_ok=True)
    temp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps({"key": _report_key(replay, tier, me_name), "report": report}), encoding="utf-8")
    os.replace(temp, path)


# ---------- chat ----------

CLOCK_RE = re.compile(r"\b(\d{1,2}):([0-5]\d)\b")
GOAL_RE = re.compile(r"\b(?:(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+goal|goal\s+(?:number\s+|#)?(\d+))\b", re.I)
MOMENT_RE = re.compile(r"\bm(\d{1,2})\b", re.I)
ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1}
MAX_SNAPSHOTS = 3

CHAT_SYSTEM = SYSTEM_PROMPT + """
- The player will ask you questions about this match. Answer from the data below; if they mention a time or goal, a REPLAY DATA block with exact positions is attached to their message - use it.
- Keep answers under about 150 words unless asked for more.

MATCH DATA
{dossier}"""


def snapshot_text(game, t):
    """Where everyone was at replay time t, as text."""
    frames = game.frames
    i = int(np.clip(np.searchsorted(frames.time.to_numpy(), t), 0, len(frames) - 1))
    frame = int(frames.frame.iloc[i])
    clock = frames.seconds_remaining.iloc[i]
    clock_text = "" if clock is None or np.isnan(clock) else f" (game clock {fmt_clock(int(clock))})"
    ball = game.ball[game.ball.frame == frame]
    lines = [f"At replay time {frames.time.iloc[i]:.1f}s{clock_text}, game state {frames.state.iloc[i]}:"]
    ball_own = {}
    if not ball.empty:
        b = ball.iloc[0]
        lines.append(f"- Ball at ({b.x:.0f}, {b.y:.0f}, height {b.z:.0f}), speed "
                     f"{float(np.sqrt(b.vx ** 2 + b.vy ** 2 + b.vz ** 2)):.0f}")
        ball_own = {0: b.y, 1: -b.y}
    for _, p in game.players[game.players.frame == frame].iterrows():
        own_y = p.y if p.team == 0 else -p.y
        third = "own third" if own_y < -THIRD_LINE else "attacking third" if own_y > THIRD_LINE else "middle third"
        parts = [f"{third}", f"speed {p.speed:.0f}", "airborne" if p.z > 150 else "on the ground"]
        if p.boost is not None and not np.isnan(p.boost):
            parts.append(f"boost {p.boost:.0f}")
        if ball_own:
            dist = float(np.sqrt((p.x - b.x) ** 2 + (p.y - b.y) ** 2 + (p.z - b.z) ** 2))
            parts.append("behind the ball" if own_y < ball_own[p.team] else "ahead of the ball")
            parts.append(f"{dist:.0f} from the ball")
        lines.append(f"- {p.player} ({TEAM[p.team]}) at ({p.x:.0f}, {p.y:.0f}): " + ", ".join(parts))
    return "\n".join(lines)


def referenced_times(question, moments, game):
    """[(label, replay time)] for clocks, goals and moment ids mentioned in a question."""
    found = []
    goals = [m for m in moments if m["type"] == "goal"]
    for match in CLOCK_RE.finditer(question):
        want = int(match.group(1)) * 60 + int(match.group(2))
        rows = game.frames[game.frames.live & (game.frames.seconds_remaining == want)]
        if not rows.empty:
            found.append((f"game clock {match.group(0)}", float(rows.time.iloc[0])))
    for match in GOAL_RE.finditer(question):
        n = ORDINALS.get(match.group(1).lower()) if match.group(1) else int(match.group(2))
        if n and goals and -len(goals) <= n <= len(goals) and n != 0:
            goal = goals[n - 1] if n > 0 else goals[n]
            found.append((f"3s before the goal by {goal['players'][0]}", max(0.0, goal["time"] - 3.0)))
            found.append((f"the goal by {goal['players'][0]}", goal["time"]))
    by_id = {m["id"]: m for m in moments}
    for match in MOMENT_RE.finditer(question):
        m = by_id.get(f"m{int(match.group(1))}")
        if m:
            found.append((f"{m['id']} ({m['title']})", m["time"]))
    return found[:MAX_SNAPSHOTS]


class CoachChat:
    """A conversation about one match. ask() yields the reply as it is written."""

    def __init__(self, dossier, moments, me_name, team, game, tier):
        self.moments, self.game, self.tier, self.dossier = moments, game, tier, dossier
        self.system = CHAT_SYSTEM.format(me=me_name, team=TEAM[team], dossier=dossier)
        self.turns = []   # [(role, text)]

    def _messages(self):
        """System prompt plus as much recent history as fits the context window."""
        budget = (CTX_SIZE - REPLY_RESERVE) * CHARS_PER_TOKEN - len(self.system)
        kept, used = [], 0
        for role, text in reversed(self.turns):
            used += len(text)
            if used > budget and kept:
                break
            kept.append({"role": role, "content": text})
        return [{"role": "system", "content": self.system}] + kept[::-1]

    def ask(self, question):
        extra = [f"[{label}]\n{snapshot_text(self.game, t)}"
                 for label, t in referenced_times(question, self.moments, self.game)]
        message = question + ("\n\nREPLAY DATA for what you mentioned:\n" + "\n\n".join(extra) if extra else "")
        self.turns.append(("user", message))
        reply = []
        try:
            for piece in _stream_chat(self.tier, self._messages()):
                reply.append(piece)
                yield piece
        except BaseException:
            self.turns.pop()  # don't keep a question that got no answer
            raise
        self.turns.append(("assistant", "".join(reply)))


# ---------- helpers shared with the app ----------

def usual_stats(records, player_id, exclude=None):
    """The player's average of each dossier stat over their other games, or None if too few."""
    from progress import player_games
    games = player_games([r for r in records if r.path != exclude], player_id)
    cols = [c for c, _ in DOSSIER_STATS]
    games = games.dropna(subset=["pct_behind_ball"])
    if len(games) < 3:
        return None
    return {c: float(games[c].mean()) for c in cols if games[c].notna().any()}


def analyse_for_coach(record, game, me_id, records):
    """Moments, rule-based insights and the dossier for one analysed replay (no AI involved)."""
    me = record.summary.player(me_id) if me_id else None
    if me is None or me.name not in (record.players or {}):
        raise CoachError("Your player wasn't found in this match. Open My progress and press \"This is me\".")
    moments = detect_moments(game, record.summary)
    usual = usual_stats(records, me_id, exclude=record.path)
    rule_insights = insights(record.summary, record.players, moments, me.name, usual)
    dossier = build_dossier(record, moments, me.name, usual, rule_insights)
    return {"me": me.name, "team": me.team, "moments": moments, "insights": rule_insights,
            "dossier": dossier, "usual": usual}


def _main():
    import argparse

    from frame_data import load_game_frames
    from replay_library import analyse

    ap = argparse.ArgumentParser(description="Analyse one replay with the AI coach")
    ap.add_argument("replay")
    ap.add_argument("--me", help="your player name in this match (default: the player who saved the replay)")
    ap.add_argument("--tier", default=DEFAULT_TIER, choices=list(TIERS))
    ap.add_argument("--no-ai", action="store_true", help="only print the rule-based moments and insights")
    args = ap.parse_args()

    record, game = analyse(args.replay)
    if game is None:
        raise SystemExit(f"Frame analysis failed: {record.error}")
    name = args.me or record.summary.recorded_by
    me = next((p for p in record.summary.players if p.name == name), None)
    if me is None:
        raise SystemExit("Pass --me with your player name; the players are: "
                         + ", ".join(p.name for p in record.summary.players))
    facts = analyse_for_coach(record, game, me.player_id, [])
    print(facts["dossier"], "\n")
    print(f"(dossier is about {len(facts['dossier']) / CHARS_PER_TOKEN:.0f}-{len(facts['dossier']) / 4:.0f} tokens)")
    if args.no_ai:
        return
    if not model_ready(args.tier):
        print(f"Downloading the {args.tier} model...")
        download_model(args.tier, lambda d, t, phase: print(f"\r{phase} {d / t:.0%}", end="", flush=True))
        print()
    started = time.time()
    report = generate_report(facts["dossier"], facts["moments"], facts["me"], facts["team"], args.tier)
    print(json.dumps(report, indent=2))
    print(f"\nReport took {time.time() - started:.0f}s")


if __name__ == "__main__":
    _main()
