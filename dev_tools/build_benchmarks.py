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
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmarks  # noqa: E402
from ballchasing import PLAYLISTS, RANK_IDS, download, replay_ids, token_or_exit  # noqa: E402
from progress import PROGRESS_STATS  # noqa: E402
from replay_library import CACHE_VERSION, analyse  # noqa: E402


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

    token = token_or_exit()

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
