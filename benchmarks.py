"""Rank benchmarks: how a player's stats compare with typical players at each rank.

`benchmarks.json` (built offline by tools/build_benchmarks.py from public replays, analysed
with this app's own code so the numbers are comparable) holds, per mode and rank band, the
10th/25th/50th/75th/90th percentile of every stat. Nothing here touches the network.
"""

import json

import numpy as np

from paths import bundled

BANDS = ["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Champion", "Grand Champion", "Supersonic Legend"]
QUANTILES = [10, 25, 50, 75, 90]

# Stats where a smaller number is the better one
LOWER_IS_BETTER = {"pct_zero_boost", "times_beaten", "last_man_beaten", "avg_dist_to_ball", "pct_slow",
                   "pct_farthest_from_ball"}
# Stats that say how a player plays rather than how well, so they aren't "strengths" or "weaknesses"
STYLE_ONLY = {"pct_def_third", "pct_mid_third", "pct_off_third", "pct_ground", "pct_low_air", "pct_high_air",
              "boost_collected", "boost_used", "dodges", "double_jumps", "half_flips", "wave_dashes"}

_DATA = None


def _load():
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.loads(bundled("benchmarks.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            _DATA = {}
    return _DATA


def available():
    return bool(_load().get("modes"))


def modes():
    return list(_load().get("modes", {}))


def table(mode, band):
    """{stat: [p10, p25, p50, p75, p90]} for a mode and band, or {} if we have no data for it."""
    return _load().get("modes", {}).get(mode, {}).get(band, {}).get("stats", {})


def sample_size(mode, band):
    return _load().get("modes", {}).get(mode, {}).get(band, {}).get("n", 0)


def percentile(mode, band, stat, value):
    """0-100: how this value ranks among players of that band (100 = better than nearly all).

    Interpolates between the stored quantiles; beyond p10/p90 it is clamped to 5 / 95 so a
    single outlier doesn't read as a perfect or a hopeless score. Lower-is-better stats are flipped.
    """
    q = table(mode, band).get(stat)
    if not q or value is None or np.isnan(value):
        return None
    pct = float(np.interp(value, q, QUANTILES, left=5, right=95))
    return 100 - pct if stat in LOWER_IS_BETTER else pct


def median(mode, band, stat):
    q = table(mode, band).get(stat)
    return q[2] if q else None


def closest_band(mode, stat, value):
    """The rank band whose median for this stat is nearest to the value."""
    best, gap = None, None
    for band in BANDS:
        m = median(mode, band, stat)
        if m is not None and (gap is None or abs(m - value) < gap):
            best, gap = band, abs(m - value)
    return best


def profile(games, mode, band, stats):
    """Compare a player's recent form with their rank.

    games: DataFrame from progress.player_games. stats: [(column, heading, format)].
    Returns {"band", "n", "rows": [...], "strengths": [...], "weaknesses": [...]}, or None
    when there is no benchmark data for that mode and band. Each row has the player's average,
    the band median, a percentile within the band and the band they play like.
    """
    if not table(mode, band) or games.empty:
        return None
    rows = []
    for col, heading, fmt in stats:
        if col not in games or not games[col].notna().any():
            continue
        value = float(games[col].mean())
        pct = percentile(mode, band, col, value)
        if pct is None:
            continue
        rows.append({
            "stat": col, "heading": heading, "value": value, "median": median(mode, band, col),
            "percentile": round(pct), "playsLike": closest_band(mode, col, value), "lowerBetter": col in LOWER_IS_BETTER,
        })
    ranked = sorted((r for r in rows if r["stat"] not in STYLE_ONLY), key=lambda r: r["percentile"])
    return {
        "band": band, "n": sample_size(mode, band), "rows": rows,
        "weaknesses": [r["stat"] for r in ranked[:3]],
        "strengths": [r["stat"] for r in ranked[::-1][:3]],
    }
