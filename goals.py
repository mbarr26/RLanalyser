"""Weekly goals: pick a stat to improve, set a target, and track the games played since.

Pure logic over a games table (progress.player_games); `rl_analyser.py` stores the goals in config.json.
A goal lasts GOAL_DAYS from when it was accepted. It is *met* once the average of the games since
then (at least MIN_GAMES of them) reaches the target; it is *expired* if the time runs out first.
"""

from datetime import datetime, timedelta

import pandas as pd

import benchmarks
import training

GOAL_DAYS = 7
MIN_GAMES = 3          # a goal can't be met by one lucky game
MAX_GOALS = 2

# stats a goal can be about: column -> (heading, lower is better, format)
GOAL_STATS = {
    "pct_zero_boost": ("% at 0 boost", True, "{:.1f}"),
    "times_beaten": ("Times beaten", True, "{:.1f}"),
    "last_man_beaten": ("Beaten as last man", True, "{:.1f}"),
    "pct_behind_ball": ("% Behind ball", False, "{:.1f}"),
    "pct_shadowing": ("% Shadowing", False, "{:.1f}"),
    "fifty_win_pct": ("50/50 win %", False, "{:.0f}"),
    "clears": ("Clears", False, "{:.1f}"),
    "high_aerials": ("High aerials", False, "{:.1f}"),
    "touches_per_min": ("Touches/min", False, "{:.1f}"),
}


def _mean(games, col):
    return float(games[col].mean()) if col in games and games[col].notna().any() else None


def target_for(stat, baseline, median=None):
    """A realistic target: halfway to the rank median if that is better, otherwise 10% better than now."""
    _, lower, _ = GOAL_STATS[stat]
    if median is not None and ((median < baseline) if lower else (median > baseline)):
        target = baseline + (median - baseline) / 2
    else:
        target = baseline * (0.9 if lower else 1.1)
    return round(max(target, 0), 1)


def suggestions(games, mode=None, band=None, taken=()):
    """Up to MAX_GOALS goals worth trying: the player's weakest stats for their rank.

    Without a rank (or its data) it falls back to the stats that have slipped most lately against the
    player's own average. Stats they already have a goal for are skipped.
    """
    recent = games.tail(10)
    candidates = []
    profile = benchmarks.profile(recent, mode, band, [(c, h, f) for c, (h, _, f) in GOAL_STATS.items()]) if band else None
    if profile:
        candidates = [(r["percentile"], r["stat"], r["median"]) for r in profile["rows"] if r["stat"] in GOAL_STATS]
    else:
        for stat, (_, lower, _) in GOAL_STATS.items():
            now, usual = _mean(recent, stat), _mean(games, stat)
            if now is None or usual is None or len(games) < 5:
                continue
            slip = (now - usual) / max(abs(usual), 1.0) * (-1 if not lower else 1) * 100   # bigger = worse
            candidates.append((-slip, stat, None))
    out = []
    for _, stat, median in sorted(candidates, key=lambda c: c[0]):
        baseline = _mean(recent, stat)
        if stat in taken or baseline is None or stat not in GOAL_STATS:
            continue
        out.append(describe(stat, baseline, target_for(stat, baseline, median), band))
        if len(out) >= MAX_GOALS:
            break
    return out


def describe(stat, baseline, target, band=None):
    heading, lower, fmt = GOAL_STATS[stat]
    return {"stat": stat, "heading": heading, "lowerBetter": lower, "baseline": round(baseline, 1), "target": target,
            "text": f"{heading} {'at or below' if lower else 'at or above'} {fmt.format(target)}"
                    f" (now {fmt.format(baseline)})", "band": band}


def new_goal(stat, baseline, target, now=None, mode=None):
    """The record kept in config.json."""
    now = now or datetime.now()
    return {"id": f"{stat}-{now:%Y%m%d%H%M%S}", "stat": stat, "baseline": round(float(baseline), 1),
            "target": float(target), "started": now.isoformat(timespec="seconds"), "mode": mode}


def reached(stat, value, target):
    return value <= target if GOAL_STATS[stat][1] else value >= target


def progress(goal, games, now=None):
    """Where a stored goal stands, with its training advice, ready to send to the page."""
    now = now or datetime.now()
    stat, target = goal["stat"], goal["target"]
    heading, lower, fmt = GOAL_STATS[stat]
    started = datetime.fromisoformat(goal["started"])
    since = games[games.played >= started]
    if goal.get("mode"):
        since = since[since["mode"] == goal["mode"]]
    value = _mean(since, stat)
    n = int(since[stat].notna().sum()) if stat in since else 0
    met = value is not None and n >= MIN_GAMES and reached(stat, value, target)
    ends = started + timedelta(days=GOAL_DAYS)
    status = "met" if met else "expired" if now > ends else "active"
    base = goal["baseline"]
    span = abs(target - base) or 1.0
    fraction = 0.0 if value is None else min(max((base - value if lower else value - base) / span, 0.0), 1.0)
    return {
        "id": goal["id"], "stat": stat, "heading": heading, "lowerBetter": lower, "status": status,
        "target": fmt.format(target), "baseline": fmt.format(base), "current": None if value is None else fmt.format(value),
        "games": n, "needed": MIN_GAMES, "fraction": round(fraction, 3), "daysLeft": max(0, (ends - now).days),
        "training": training.for_stat(stat),
    }


def met_in_game(goals, row):
    """For the post-game card: [{heading, met}] for each active goal, judged on this one game."""
    out = []
    for goal in goals:
        value = row.get(goal["stat"])
        if value is None or pd.isna(value):
            continue
        out.append({"heading": GOAL_STATS[goal["stat"]][0], "met": bool(reached(goal["stat"], float(value), goal["target"]))})
    return out


def streak(history):
    """How many goals in a row (most recent first) were met. history: [{"met": bool}, ...] oldest first."""
    count = 0
    for item in reversed(history):
        if not item.get("met"):
            break
        count += 1
    return count
