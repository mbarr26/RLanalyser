"""RL Analyser - browse every Rocket League replay in a folder and track your stats over time.

The UI is an HTML/CSS/JS page (ui/) shown in a native window via pywebview; this
module hosts it, runs the background scanning/analysis, and exposes an `Api` the
page calls into (`window.pywebview.api`). Results are pushed back to the page with
`window.evaluate_js`, calling methods on the page's `window.app` object - the same
one-way "background thread -> UI" flow the previous Tkinter version used with its
message queue, just targeting a page instead of Tk widgets.
"""

import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import webview

import benchmarks
import coach
import updater
from analysis import STAT_GROUPS
from frame_data import load_game_frames
from paths import bundled, user_data
from pitch_viewer import build_track
from progress import PROGRESS_STATS, RECENT_GAMES, comparison, guess_me, player_games
from postgame import current_session, game_row, headline_stats
from replay_library import LibraryScanner, ReplayWatcher, analyse, list_replays
from replay_parser import ReplayParseError
from version import APP_VERSION

CONFIG_PATH = user_data("config.json")
UI_DIR = bundled("ui")

# Where Rocket League usually saves replays (Epic/Steam, with or without OneDrive)
DEFAULT_REPLAY_DIRS = [
    documents / "My Games" / "Rocket League" / "TAGame" / demos
    for documents in (Path.home() / "Documents", Path.home() / "OneDrive" / "Documents")
    for demos in ("DemosEpic", "Demos")
]


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def guess_replay_dir():
    """Return the saved folder, else the first default location that exists."""
    saved = load_config().get("replay_dir")
    if saved and Path(saved).is_dir():
        return Path(saved)
    for folder in DEFAULT_REPLAY_DIRS:
        if folder.is_dir():
            return folder
    return None


def _num(value):
    return None if pd.isna(value) else float(value)


def update_source():
    return updater.update_source(load_config().get("update_url"))


def coach_tier():
    tier = load_config().get("coach_tier")
    return tier if tier in coach.TIERS else coach.DEFAULT_TIER


# ---------- app state (mirrors the old App instance's fields) ----------

WINDOW = None
REPLAY_DIR = guess_replay_dir()
CHOSEN_ME = load_config().get("me")   # player id of "you", once picked
GUESSED_ME = None                     # used until then (see progress.guess_me)
RECORDS = {}                          # path -> ReplayRecord
SCANNER = None
WATCHER = None                        # notices replays saved while the app is open
ANALYSING = set()                     # replay paths being analysed because they were opened

# AI coach state. Facts (moments, insights, frame data) and chats are kept for the few most
# recently opened replays only, since each holds a whole match's frame tables.
COACH_KEEP = 3
COACH_FACTS = {}                      # path -> coach.analyse_for_coach result, plus "game"
COACH_CHATS = {}                      # path -> coach.CoachChat
COACH_BUSY = set()                    # ("report" | "chat", path) currently running
DOWNLOAD_CANCEL = None                # threading.Event while a model download runs

# Updates (see updater.py)
UPDATE_INFO = None                    # the newer release found by the last check
UPDATE_CHECKING = False
UPDATE_CANCEL = None                  # threading.Event while an update downloads
PENDING_INSTALLER = None              # a verified installer to start once the app has closed


def effective_me():
    return CHOSEN_ME or GUESSED_ME


def push(method, *args):
    """Call window.app.<method>(...args) on the page. Safe to call from any thread."""
    if WINDOW is None:
        return
    payload = json.dumps(list(args))
    WINDOW.evaluate_js(f"window.app && window.app.{method} && window.app.{method}(...{payload})")


def record_payload(record):
    s = record.summary
    return {
        "path": str(record.path),
        "playedAt": record.played_at.strftime("%d %b %y %H:%M"),
        "playedAtIso": record.played_at.isoformat(),
        "analysed": record.analysed,
        "error": record.error,
        "summary": {
            "name": s.name,
            "mapName": s.map_name,
            "matchType": s.match_type,
            "date": s.date,
            "teamSize": s.team_size,
            "team0Score": s.team0_score,
            "team1Score": s.team1_score,
            "secondsPlayed": s.seconds_played,
            "recordedBy": s.recorded_by,
            "winningTeam": s.winning_team,
            "players": [asdict(p) for p in s.players],
            "goals": [asdict(g) for g in s.goals],
        },
        "players": record.players,
        "match": record.match,
    }


def maybe_update_guessed_me():
    global GUESSED_ME
    guess = guess_me(RECORDS.values())
    if guess != GUESSED_ME:
        GUESSED_ME = guess
        if not CHOSEN_ME:
            push("onMe", effective_me())


def handle_scan_message(scanner, kind, *data):
    if scanner is not SCANNER:
        return  # a message from a folder that's no longer the one selected
    if kind == "record":
        (record,) = data
        RECORDS[record.path] = record
        push("onRecord", record_payload(record))
        maybe_update_guessed_me()
    elif kind == "progress":
        (text,) = data
        push("onStatus", text)
    elif kind == "done":
        (unreadable,) = data
        analysed = sum(1 for r in RECORDS.values() if r.analysed)
        text = f"{len(RECORDS)} replays, {analysed} analysed"
        if unreadable:
            text += f"  ·  {unreadable} couldn't be read"
        push("onStatus", text)
        push("onDone")


def start_scan_and_list():
    """(Re)list the folder, start background loading, and return the ordered paths."""
    global SCANNER, RECORDS, WATCHER
    if SCANNER:
        SCANNER.stop()
    if WATCHER:
        WATCHER.stop()
        WATCHER = None
    RECORDS = {}
    if not REPLAY_DIR:
        return []
    try:
        paths = list_replays(REPLAY_DIR)
    except OSError as e:
        push("onError", f"Could not read folder:\n{e}")
        SCANNER = None
        return []
    WATCHER = ReplayWatcher(REPLAY_DIR, paths, handle_new_replay)   # also when empty: the first game may arrive later
    WATCHER.start()
    if not paths:
        push("onStatus", "No .replay files found in this folder")
        SCANNER = None
        return []
    scanner = LibraryScanner(paths, lambda message: handle_scan_message(scanner, *message))
    SCANNER = scanner
    scanner.start()
    return [str(p) for p in paths]


def is_onboarded():
    """Anyone who already chose a folder or a player before the welcome guide existed skips it."""
    config = load_config()
    return bool(config.get("onboarded") or config.get("me") or config.get("replay_dir"))


def rank_for(mode):
    """The rank band the player said they play at in this mode (None if not set)."""
    return load_config().get("ranks", {}).get(mode)


def flash_window():
    """Flash the taskbar button until the window is brought to the front (best effort, Windows only)."""
    try:
        import ctypes
        from ctypes import wintypes

        class FlashInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        hwnd = wintypes.HWND(WINDOW.native.Handle.ToInt64())
        info = FlashInfo(ctypes.sizeof(FlashInfo), hwnd, 0x3 | 0xC, 0, 0)   # FLASHW_ALL | FLASHW_TIMERNOFG
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def postgame_card(record):
    """What the page shows right after a game: result, standout stats, the top finding. None if you weren't in it."""
    me_id = effective_me()
    s = record.summary
    me = s.player(me_id) if me_id else None
    if me is None or me.name not in (record.players or {}):
        return None
    mode = f"{s.team_size}v{s.team_size}"
    games = player_games(list(RECORDS.values()), me_id)
    before = games[games.path != record.path]
    stats = headline_stats(game_row(me, record.players[me.name]), before, mode, rank_for(mode))
    mine, theirs = (s.team0_score, s.team1_score) if me.team == 0 else (s.team1_score, s.team0_score)
    return {
        "path": str(record.path), "result": "Win" if mine > theirs else "Loss" if mine < theirs else "Draw",
        "scoreLine": f"{mine}-{theirs}", "mapName": s.map_name, "mode": mode, "stats": stats, "finding": None,
    }


def handle_new_replay(path):
    """A replay appeared while the app was open: analyse it, show the post-game card, start the AI report."""
    try:
        record, _game = analyse(path)
    except (ReplayParseError, OSError):
        return
    RECORDS[path] = record
    push("onRecord", record_payload(record))
    maybe_update_guessed_me()
    if record.error:
        return
    card = postgame_card(record)
    if card is None:
        return
    facts = API.get_coach(str(path))          # the rule-based findings; also primes the AI chat
    if "insights" in facts:
        bad = [i for i in facts["insights"] if i["kind"] == "bad"] or facts["insights"]
        card["finding"] = bad[0]["text"] if bad else None
    push("onNewMatch", card)
    flash_window()
    if "insights" in facts and coach.model_ready(coach_tier()):
        API.coach_generate(str(path))         # so the written report is ready by the time they open it


def progress_payload(player_id, mode):
    games = player_games(list(RECORDS.values()), player_id, mode or None)
    headings, rows = comparison(games)
    wins = int((games.result == "Win").sum())
    losses = int((games.result == "Loss").sum())
    game_rows = [
        {
            "path": str(g.path),
            "played": g.played.strftime("%d %b %Y %H:%M"),
            "mode": g["mode"], "map": g["map"], "result": g.result, "scoreLine": g.score_line,
            "score": _num(g.score), "goals": _num(g.goals), "assists": _num(g.assists),
            "saves": _num(g.saves), "shots": _num(g.shots),
            "avgSpeed": _num(g.avg_speed), "pctBehindBall": _num(g.pct_behind_ball), "avgBoost": _num(g.avg_boost),
        }
        for _, g in games.iloc[::-1].iterrows()
    ]
    band = rank_for(mode) if mode else None
    rank = benchmarks.profile(games.tail(RECENT_GAMES), mode, band, PROGRESS_STATS) if band else None
    return {
        "rank": rank,
        "count": int(len(games)),
        "wins": wins,
        "losses": losses,
        "compare": {"headings": headings, "rows": [[col, heading, values] for col, heading, values in rows]},
        "games": game_rows,
        "chart": {col: [_num(v) for v in games[col]] for col, _, _ in PROGRESS_STATS},
        "chartLabels": [
            f"{g.played:%d %b %Y}\n{g.result} {g.score_line} · {g['map']}" for _, g in games.iterrows()
        ],
    }


class Api:
    def get_meta(self):
        return {
            "version": APP_VERSION,
            "updatesConfigured": bool(update_source()),
            "onboarded": is_onboarded(),
            "config": {"replayDir": str(REPLAY_DIR) if REPLAY_DIR else None, "me": CHOSEN_ME,
                       "ranks": load_config().get("ranks", {})},
            "rankBands": benchmarks.BANDS,
            "rankModes": benchmarks.modes(),
            "statGroups": {group: [[c, h, f] for c, h, f in stats] for group, stats in STAT_GROUPS.items()},
            "progressStats": [[c, h, f] for c, h, f in PROGRESS_STATS],
        }

    def choose_folder(self):
        global REPLAY_DIR
        result = WINDOW.create_file_dialog(
            webview.FOLDER_DIALOG, directory=str(REPLAY_DIR) if REPLAY_DIR else str(Path.home())
        )
        if not result:
            return {"replayDir": str(REPLAY_DIR) if REPLAY_DIR else None, "paths": []}
        REPLAY_DIR = Path(result[0])
        save_config({**load_config(), "replay_dir": str(REPLAY_DIR)})
        return {"replayDir": str(REPLAY_DIR), "paths": start_scan_and_list()}

    def refresh(self):
        return {"replayDir": str(REPLAY_DIR) if REPLAY_DIR else None, "paths": start_scan_and_list()}

    def analyse_now(self, path):
        path = Path(path)
        if path in ANALYSING:
            return None
        ANALYSING.add(path)

        def work():
            try:
                record, _game = analyse(path)
                RECORDS[path] = record
                push("onRecord", record_payload(record))
                maybe_update_guessed_me()
            except (ReplayParseError, OSError) as e:
                push("onAnalyseFailed", str(path), str(e))
            finally:
                ANALYSING.discard(path)

        threading.Thread(target=work, daemon=True).start()
        return None

    def set_me(self, player_id):
        global CHOSEN_ME
        CHOSEN_ME = player_id
        save_config({**load_config(), "me": player_id})
        push("onMe", effective_me())
        return None

    def finish_onboarding(self):
        save_config({**load_config(), "onboarded": True})
        return None

    def get_session(self, player_id):
        """Tonight's games and whether it's going badly (None if they haven't played recently)."""
        return current_session(RECORDS.values(), player_id) if player_id else None

    def set_rank(self, mode, band):
        """Remember which rank band the player is in for a mode (None clears it)."""
        config = load_config()
        ranks = config.setdefault("ranks", {})
        if band in benchmarks.BANDS:
            ranks[mode] = band
        else:
            ranks.pop(mode, None)
        save_config(config)
        return ranks

    def get_progress(self, player_id, mode):
        return progress_payload(player_id, mode)

    def get_track(self, path):
        path = Path(path)
        record = RECORDS.get(path)
        if record is None:
            return {"error": "Replay not loaded"}
        try:
            game = load_game_frames(path)
        except Exception as e:  # shown to the user rather than lost
            return {"error": str(e) or type(e).__name__}
        return build_track(game, record.summary.goals)

    # ---------- AI coach ----------

    def coach_status(self):
        return coach.status(coach_tier())

    def coach_set_tier(self, tier):
        if tier in coach.TIERS:
            save_config({**load_config(), "coach_tier": tier})
        return coach.status(coach_tier())

    def coach_download(self):
        """Download the chosen model in the background; progress arrives as onCoachDownload."""
        global DOWNLOAD_CANCEL
        if DOWNLOAD_CANCEL is not None:
            return None
        tier, cancel = coach_tier(), threading.Event()
        DOWNLOAD_CANCEL = cancel

        def work():
            global DOWNLOAD_CANCEL
            try:
                coach.download_model(
                    tier, lambda done, total, phase: push("onCoachDownload", {"done": done, "total": total, "phase": phase}), cancel)
                push("onCoachDownload", {"finished": True})
            except coach.CoachError as e:
                push("onCoachDownload", {"error": str(e)})
            except Exception as e:
                push("onCoachDownload", {"error": f"Unexpected error: {e}"})
            finally:
                DOWNLOAD_CANCEL = None

        threading.Thread(target=work, daemon=True).start()
        return None

    def coach_cancel_download(self):
        if DOWNLOAD_CANCEL is not None:
            DOWNLOAD_CANCEL.set()
        return None

    def get_coach(self, path):
        """Moments and rule-based findings for a match (no AI needed), plus any saved AI report."""
        path = Path(path)
        record = RECORDS.get(path)
        if record is None or not record.analysed or record.error:
            return {"error": "This match hasn't been analysed yet."}
        try:
            game = load_game_frames(path)
            mode = f"{record.summary.team_size}v{record.summary.team_size}"
            facts = coach.analyse_for_coach(record, game, effective_me(), list(RECORDS.values()), rank_for(mode))
        except coach.CoachError as e:
            return {"error": str(e)}
        except Exception as e:  # shown to the user rather than lost
            return {"error": str(e) or type(e).__name__}
        # The chat needs the frame data to look up positions at a given time; keep a few matches only
        COACH_FACTS.pop(path, None)
        COACH_FACTS[path] = {**facts, "game": game}
        while len(COACH_FACTS) > COACH_KEEP:
            COACH_FACTS.pop(next(iter(COACH_FACTS)))
        # Keep the conversation only if the match data it was based on is unchanged
        chat = COACH_CHATS.get(path)
        chat_kept = chat is not None and chat.dossier == facts["dossier"]
        if not chat_kept:
            COACH_CHATS.pop(path, None)
        return {
            "path": str(path), "me": facts["me"], "team": facts["team"], "moments": facts["moments"],
            "insights": facts["insights"], "report": coach.load_report(path, coach_tier(), facts["me"]),
            "chatKept": chat_kept,
        }

    def coach_generate(self, path):
        """Write the AI analysis in the background; the result arrives as onCoachReport."""
        path = Path(path)
        facts = COACH_FACTS.get(path)
        key = ("report", path)
        if facts is None or key in COACH_BUSY:
            return None
        COACH_BUSY.add(key)
        tier = coach_tier()

        def work():
            try:
                coach.ensure_server(tier, lambda state: push("onCoachState", str(path), state))
                push("onCoachState", str(path), "writing")
                report = coach.generate_report(facts["dossier"], facts["moments"], facts["me"], facts["team"], tier)
                coach.save_report(path, tier, facts["me"], report)
                push("onCoachReport", str(path), report)
            except coach.CoachError as e:
                push("onCoachError", str(path), str(e))
            except Exception as e:
                push("onCoachError", str(path), f"Unexpected error: {e}")
            finally:
                COACH_BUSY.discard(key)

        threading.Thread(target=work, daemon=True).start()
        return None

    def coach_ask(self, path, question):
        """Answer a question about a match; the reply streams in as onChatDelta, then onChatDone."""
        path = Path(path)
        facts = COACH_FACTS.get(path)
        key = ("chat", path)
        if facts is None or key in COACH_BUSY or not question.strip():
            return None
        COACH_BUSY.add(key)
        tier = coach_tier()
        chat = COACH_CHATS.get(path)
        if chat is None or chat.tier != tier:
            chat = COACH_CHATS[path] = coach.CoachChat(
                facts["dossier"], facts["moments"], facts["me"], facts["team"], facts["game"], tier)

        def work():
            try:
                coach.ensure_server(tier, lambda state: push("onCoachState", str(path), state))
                pending, last_push = [], time.monotonic()
                for piece in chat.ask(question.strip()):
                    pending.append(piece)
                    if time.monotonic() - last_push > 0.08:   # batch tiny pieces so the page isn't flooded
                        push("onChatDelta", str(path), "".join(pending))
                        pending, last_push = [], time.monotonic()
                if pending:
                    push("onChatDelta", str(path), "".join(pending))
                push("onChatDone", str(path))
            except coach.CoachError as e:
                push("onChatError", str(path), str(e))
            except Exception as e:
                push("onChatError", str(path), f"Unexpected error: {e}")
            finally:
                COACH_BUSY.discard(key)

        threading.Thread(target=work, daemon=True).start()
        return None

    def coach_reset(self, path):
        COACH_CHATS.pop(Path(path), None)
        return None

    # ---------- updates ----------

    def check_for_update(self):
        """Look for a newer release in the background; the answer arrives as onUpdate."""
        global UPDATE_CHECKING
        source = update_source()
        if not source:
            push("onUpdate", {"state": "unconfigured"})
            return None
        if UPDATE_CHECKING or UPDATE_CANCEL is not None:
            return None
        UPDATE_CHECKING = True

        def work():
            global UPDATE_INFO, UPDATE_CHECKING
            try:
                info = updater.check(source)
                UPDATE_INFO = info
                push("onUpdate", {"state": "available", "info": asdict(info)} if info
                     else {"state": "none", "version": APP_VERSION})
            except updater.UpdateError as e:
                push("onUpdate", {"state": "error", "error": str(e)})
            except Exception as e:
                push("onUpdate", {"state": "error", "error": f"Unexpected error: {e}"})
            finally:
                UPDATE_CHECKING = False

        threading.Thread(target=work, daemon=True).start()
        return None

    def update_install(self, force=False):
        """Download and verify the update, then close the app so the installer can run.

        Returns {"busy": True} (without doing anything) if an AI task is running and force is
        false, so the page can ask first. Progress arrives as onUpdateProgress, failures as
        onUpdateFailed; on success the window closes and main() starts the installer.
        """
        global UPDATE_CANCEL
        info = UPDATE_INFO
        if info is None or UPDATE_CANCEL is not None:
            return {"started": False}
        if COACH_BUSY and not force:
            return {"busy": True}
        cancel = UPDATE_CANCEL = threading.Event()

        def work():
            global UPDATE_CANCEL, PENDING_INSTALLER
            try:
                path = updater.download(
                    info, lambda done, total, phase: push("onUpdateProgress", {"done": done, "total": total, "phase": phase}), cancel)
            except updater.UpdateCancelled:
                push("onUpdateFailed", {"cancelled": True})
            except updater.UpdateError as e:
                push("onUpdateFailed", {"error": str(e)})
            except Exception as e:
                push("onUpdateFailed", {"error": f"Unexpected error: {e}"})
            else:
                PENDING_INSTALLER = path
                push("onUpdateProgress", {"phase": "installing"})
                WINDOW.destroy()
            finally:
                UPDATE_CANCEL = None

        threading.Thread(target=work, daemon=True).start()
        return {"started": True}

    def update_cancel(self):
        if UPDATE_CANCEL is not None:
            UPDATE_CANCEL.set()
        return None


def dark_title_bar(window):
    """Best effort: a dark Windows title bar to match the page (Windows 10 20H1+ and 11).

    Anything that goes wrong (older Windows, a different window backend) is ignored: the window
    just keeps the normal title bar.
    """
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(window.native.Handle.ToInt64())
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute

        def apply(attribute, value):
            number = ctypes.c_int(value)
            set_attribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))

        apply(20, 1)               # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on early Windows 10 builds)
        apply(19, 1)
        apply(35, 0x00070505)      # DWMWA_CAPTION_COLOR (Windows 11): #050507 as 0x00BBGGRR
        apply(34, 0x00070505)      # DWMWA_BORDER_COLOR
        apply(36, 0x00F7F4F4)      # DWMWA_TEXT_COLOR: #f4f4f7
    except Exception:
        pass


API = None   # the one Api instance (set in main), so background code can call its methods


def main():
    global WINDOW, API
    API = Api()
    updater.cleanup_old()
    WINDOW = webview.create_window(
        "RL Analyser",
        str(UI_DIR / "index.html"),
        js_api=API,
        width=1440,
        height=900,
        min_size=(1100, 700),
        background_color="#050507",   # matches the page, so there is no white flash while it loads
    )
    WINDOW.events.shown += lambda: dark_title_bar(WINDOW)
    webview.start()
    coach.stop_server()   # the AI engine is a separate process; don't leave it running
    if PENDING_INSTALLER is not None:
        # An update was downloaded and checked: start its installer now that nothing of ours is running
        try:
            updater.launch_installer(PENDING_INSTALLER)
        except updater.UpdateError as e:
            user_data("update-error.txt").write_text(str(e), encoding="utf-8")


if __name__ == "__main__":
    main()
