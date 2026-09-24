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
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import webview

from analysis import STAT_GROUPS
from frame_data import load_game_frames
from pitch_viewer import build_track
from progress import PROGRESS_STATS, comparison, guess_me, player_games
from replay_library import LibraryScanner, analyse, list_replays
from replay_parser import ReplayParseError

CONFIG_PATH = Path(__file__).with_name("config.json")
UI_DIR = Path(__file__).with_name("ui")

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


# ---------- app state (mirrors the old App instance's fields) ----------

WINDOW = None
REPLAY_DIR = guess_replay_dir()
CHOSEN_ME = load_config().get("me")   # player id of "you", once picked
GUESSED_ME = None                     # used until then (see progress.guess_me)
RECORDS = {}                          # path -> ReplayRecord
SCANNER = None
ANALYSING = set()                     # replay paths being analysed because they were opened


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
    global SCANNER, RECORDS
    if SCANNER:
        SCANNER.stop()
    RECORDS = {}
    if not REPLAY_DIR:
        return []
    try:
        paths = list_replays(REPLAY_DIR)
    except OSError as e:
        push("onError", f"Could not read folder:\n{e}")
        SCANNER = None
        return []
    if not paths:
        push("onStatus", "No .replay files found in this folder")
        SCANNER = None
        return []
    scanner = LibraryScanner(paths, lambda message: handle_scan_message(scanner, *message))
    SCANNER = scanner
    scanner.start()
    return [str(p) for p in paths]


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
    return {
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
            "config": {"replayDir": str(REPLAY_DIR) if REPLAY_DIR else None, "me": CHOSEN_ME},
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


def main():
    global WINDOW
    WINDOW = webview.create_window(
        "RL Analyser",
        str(UI_DIR / "index.html"),
        js_api=Api(),
        width=1320,
        height=840,
        min_size=(1000, 640),
        background_color="#f7f7f5",
    )
    webview.start()


if __name__ == "__main__":
    main()
