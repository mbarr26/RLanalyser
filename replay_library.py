"""Every replay in a folder, analysed once and cached to disk so reopening is instant.

Each replay gets a JSON file in cache/ holding its header summary plus the per-player
and match stats from analysis.py. A cache file is ignored if the replay file or
rrrocket.exe changed, or CACHE_VERSION was bumped.
"""

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from analysis import player_stats, team_stats
from frame_data import load_game_frames
from paths import user_data
from replay_parser import RRROCKET_PATH, Goal, PlayerStats, ReplayParseError, ReplaySummary, parse_replay

CACHE_DIR = user_data("cache")
# Bump whenever parsing or stats change, so every replay is re-analysed with the new code
CACHE_VERSION = 2
REPLAY_EXTENSION = ".replay"


@dataclass
class ReplayRecord:
    path: Path
    summary: ReplaySummary
    players: dict | None = None   # player name -> frame stats (columns of analysis.player_stats)
    match: dict | None = None     # analysis.team_stats
    error: str = ""               # why frame analysis failed, if it did

    @property
    def analysed(self):
        """True once frame analysis has run (whether or not it succeeded)."""
        return self.players is not None or bool(self.error)

    @property
    def played_at(self):
        try:
            return datetime.strptime(self.summary.date, "%Y-%m-%d %H-%M-%S")
        except ValueError:
            return datetime.fromtimestamp(self.path.stat().st_mtime)


def list_replays(folder):
    """Replay files in folder, most recently saved first."""
    replays = [
        entry for entry in Path(folder).iterdir()
        if entry.is_file() and entry.suffix.lower() == REPLAY_EXTENSION
    ]
    return sorted(replays, key=lambda p: p.stat().st_mtime, reverse=True)


def _cache_path(replay):
    return CACHE_DIR / f"{Path(replay).stem}.json"


def _fingerprint(replay):
    stat = Path(replay).stat()
    # A new rrrocket.exe may decode replays the old one couldn't, so it invalidates the cache too
    decoder = RRROCKET_PATH.stat().st_size if RRROCKET_PATH.is_file() else 0
    return {"version": CACHE_VERSION, "mtime": stat.st_mtime, "size": stat.st_size, "decoder": decoder}


def load_cached(replay):
    """The cached record for a replay, or None if there isn't an up-to-date one."""
    try:
        data = json.loads(_cache_path(replay).read_text(encoding="utf-8"))
        if data["fingerprint"] != _fingerprint(replay):
            return None
        s = data["summary"]
        summary = ReplaySummary(**{
            **s,
            "players": [PlayerStats(**p) for p in s["players"]],
            "goals": [Goal(**g) for g in s["goals"]],
        })
        return ReplayRecord(Path(replay), summary, data["players"], data["match"], data["error"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_cached(record):
    summary = asdict(record.summary)
    summary.pop("raw")
    data = {
        "fingerprint": _fingerprint(record.path),
        "summary": summary,
        "players": record.players,
        "match": record.match,
        "error": record.error,
    }
    CACHE_DIR.mkdir(exist_ok=True)
    target = _cache_path(record.path)
    # Write then rename, so a half-written file is never read (two threads may save the same replay)
    temp = target.with_name(f"{target.name}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temp, target)


def read_header(replay):
    """Header-only record (fast: scores and players, no frame stats). Cached."""
    summary = parse_replay(replay)
    summary.raw = {}
    record = ReplayRecord(Path(replay), summary)
    save_cached(record)
    return record


def analyse(replay):
    """Fully analyse a replay and cache it. Returns (record, game frames).

    Game frames are None if frame analysis failed; record.error says why.
    Raises ReplayParseError if even the header can't be read.
    """
    summary = parse_replay(replay)
    summary.raw = {}
    record = ReplayRecord(Path(replay), summary)
    game = None
    try:
        game = load_game_frames(replay)
        record.players = json.loads(player_stats(game).to_json(orient="index"))
        record.match = team_stats(game)
    except ReplayParseError:
        # Usually a Rocket League update added replay data rrrocket doesn't understand yet
        record.error = "rrrocket couldn't decode the frame data (try a newer rrrocket release)"
    except Exception as e:  # kept on the record so the UI can show it
        record.error = str(e) or type(e).__name__
    save_cached(record)
    return record, game


class LibraryScanner(threading.Thread):
    """Background thread that loads every replay in a list and analyses any not yet cached.

    Pass 1 loads each replay's cache or header (fast) so the whole list fills in quickly;
    pass 2 runs full frame analysis on whatever still needs it. Progress is reported by
    calling send(message) with tuples:
        ("record", record)          a replay was loaded or analysed
        ("progress", text)          status text
        ("done", unreadable_count)  finished
    send is called from this thread, so it should just put the message on a queue.
    """

    def __init__(self, paths, send):
        super().__init__(daemon=True)
        self.paths = paths
        self.send = send
        self.stopped = False

    def stop(self):
        self.stopped = True

    def run(self):
        records, unreadable = [], 0
        for i, path in enumerate(self.paths):
            if self.stopped:
                return
            try:
                record = load_cached(path) or read_header(path)
            except (ReplayParseError, OSError):
                unreadable += 1
                continue
            records.append(record)
            self.send(("record", record))
            if i % 20 == 0:
                self.send(("progress", f"Loading replays {i + 1}/{len(self.paths)}..."))

        pending = [r for r in records if not r.analysed]
        for i, record in enumerate(pending):
            if self.stopped:
                return
            self.send(("progress", f"Analysing replays {i + 1}/{len(pending)}..."))
            if (cached := load_cached(record.path)) and cached.analysed:
                continue  # analysed meanwhile because it was opened
            try:
                self.send(("record", analyse(record.path)[0]))
            except (ReplayParseError, OSError):
                unreadable += 1
        self.send(("done", unreadable))


class ReplayWatcher(threading.Thread):
    """Background thread that notices replays saved after it started and passes each to on_new(path).

    Polls the folder (no extra dependency). Rocket League writes a replay at the end of a match, so
    a new file is only reported once its size has stopped changing between two polls.
    `known` is the set of paths that already existed; it is updated as new ones are reported.
    """

    def __init__(self, folder, known, on_new, interval=5.0):
        super().__init__(daemon=True)
        self.folder = folder
        self.known = set(known)
        self.on_new = on_new
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        sizes = {}
        while not self._stop_event.wait(self.interval):
            try:
                paths = list_replays(self.folder)
            except OSError:
                continue            # folder briefly unavailable (e.g. a network drive); try again
            for path in paths:
                if path in self.known:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size and sizes.get(path) == size:
                    self.known.add(path)
                    sizes.pop(path, None)
                    try:
                        self.on_new(path)
                    except Exception:   # one bad replay must not stop the watching
                        pass
                else:
                    sizes[path] = size
