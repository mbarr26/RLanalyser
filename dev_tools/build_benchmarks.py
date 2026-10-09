"""Build benchmarks.json from public ballchasing.com replays. Developer tool, not shipped.

    set BALLCHASING_TOKEN=<your token>        (free: ballchasing.com -> Upload -> API token)
    python dev_tools/build_benchmarks.py --mode 2v2 --per-band 60

For each rank band it lists ranked replays whose players are all in that band, downloads them,
runs this app's own analyse() on each, and stores the 10/25/50/75/90th percentiles of every
stat per player. Downloads are kept in benchmark_cache/ so an interrupted run resumes.
Re-run whenever replay_library.CACHE_VERSION changes, because the stats then mean something else.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import benchmarks  # noqa: E402
from progress import PROGRESS_STATS  # noqa: E402
from replay_library import CACHE_VERSION, analyse  # noqa: E402

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


def collect(token, mode, band, want):
    """One {stat: value} dict per player-game in the band."""
    rows = []
    for i, replay_id in enumerate(replay_ids(token, mode, band, want), 1):
        try:
            record, _ = analyse(download(token, replay_id))
        except Exception as e:                      # a bad replay shouldn't end a long run
            print(f"  skipped {replay_id}: {e}")
            continue
        if record.error or not record.players:
            continue
        for player in record.players.values():
            rows.append({col: player.get(col) for col, _, _ in PROGRESS_STATS})
        print(f"  {band} {mode}: replay {i}, {len(rows)} player-games", end="\r")
    print()
    return rows


def quantiles(rows):
    stats = {}
    for col, _, _ in PROGRESS_STATS:
        values = [r[col] for r in rows if r[col] is not None and not np.isnan(r[col])]
        if len(values) >= 20:
            stats[col] = [round(float(v), 3) for v in np.percentile(values, benchmarks.QUANTILES)]
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", action="append", choices=PLAYLISTS, help="repeatable; default all modes")
    parser.add_argument("--per-band", type=int, default=60, help="replays per rank band")
    parser.add_argument("--band", action="append", choices=RANK_IDS, help="repeatable; default all bands")
    args = parser.parse_args()

    token = os.environ.get("BALLCHASING_TOKEN")
    if not token:
        sys.exit("Set BALLCHASING_TOKEN first (ballchasing.com -> Upload -> API token).")
    CACHE.mkdir(exist_ok=True)

    out = ROOT / "benchmarks.json"
    try:
        data = json.loads(out.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    modes = data.setdefault("modes", {})
    data["cache_version"] = CACHE_VERSION

    for mode in args.mode or PLAYLISTS:
        for band in args.band or RANK_IDS:
            rows = collect(token, mode, band, args.per_band)
            modes.setdefault(mode, {})[band] = {"n": len(rows), "stats": quantiles(rows)}
            out.write_text(json.dumps(data, indent=1))      # saved after every band so nothing is lost
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
