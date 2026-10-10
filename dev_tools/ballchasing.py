"""Shared ballchasing.com helpers for the developer tools (not shipped).

Needs BALLCHASING_TOKEN (free: ballchasing.com -> Upload -> API token). Replay files and their
ballchasing stat JSON are kept in benchmark_cache/ so an interrupted run resumes.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://ballchasing.com/api"
CACHE = ROOT / "benchmark_cache"
PLAYLISTS = {"1v1": "ranked-duels", "2v2": "ranked-doubles", "3v3": "ranked-standard"}
# band name -> (min-rank, max-rank) as ballchasing spells them
RANK_IDS = {
    "Bronze": ("bronze-1", "bronze-3"), "Silver": ("silver-1", "silver-3"), "Gold": ("gold-1", "gold-3"),
    "Platinum": ("platinum-1", "platinum-3"), "Diamond": ("diamond-1", "diamond-3"),
    "Champion": ("champion-1", "champion-3"), "Grand Champion": ("grand-champion-1", "grand-champion-3"),
    "Supersonic Legend": ("supersonic-legend", "supersonic-legend"),
}
PAUSE = 1.0     # seconds between API calls (free tier is a few requests per second at most)


def token_or_exit():
    token = os.environ.get("BALLCHASING_TOKEN")
    if not token:
        sys.exit("Set BALLCHASING_TOKEN first (ballchasing.com -> Upload -> API token).")
    CACHE.mkdir(exist_ok=True)
    return token


def call(path, token, binary=False):
    request = urllib.request.Request(path if path.startswith("http") else API + path,
                                     headers={"Authorization": token})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            time.sleep(PAUSE)
            return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429:                       # rate limited: wait and retry
                time.sleep(10 * (attempt + 1))
                continue
            raise
    raise RuntimeError("ballchasing kept rate-limiting us; try again later")


def replay_ids(token, mode, band, want):
    low, high = RANK_IDS[band]
    ids, url = [], (f"/replays?playlist={PLAYLISTS[mode]}&min-rank={low}&max-rank={high}"
                    f"&count=200&sort-by=created&sort-dir=desc")
    while url and len(ids) < want:
        page = call(url, token)
        ids += [r["id"] for r in page.get("list", [])]
        url = page.get("next")
    return ids[:want]


def download(token, replay_id):
    path = CACHE / f"{replay_id}.replay"
    if not path.exists():
        path.write_bytes(call(f"/replays/{replay_id}/file", token, binary=True))
    return path


def details(token, replay_id):
    """ballchasing's own stats for a replay (teams -> players -> stats), cached next to the file."""
    path = CACHE / f"{replay_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = call(f"/replays/{replay_id}", token)
    path.write_text(json.dumps(data))
    return data
