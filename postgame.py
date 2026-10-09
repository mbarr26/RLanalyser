"""What to say right after a game and about tonight's session. Pure measurement, no AI, no UI.

`headline_stats` picks the few numbers from one game that stand out (against the player's rank if
they've set one, otherwise against their own usual); `current_session` groups the latest games into
one sitting and spots a losing run.
"""

from datetime import datetime, timedelta

import pandas as pd

import benchmarks
from progress import PROGRESS_STATS, player_games

# Stats worth showing on the card: (column, heading, higher is better)
HEADLINE = [
    ("score", "Score", True), ("goals", "Goals", True), ("saves", "Saves", True), ("shots", "Shots", True),
    ("pct_behind_ball", "% Behind ball", True), ("fifty_win_pct", "50/50 win %", True),
    ("times_beaten", "Times beaten", False), ("pct_zero_boost", "% at 0 boost", False),
    ("pct_shadowing", "% Shadowing", True), ("touches_per_min", "Touches/min", True),
]
FORMATS = {col: fmt for col, _, fmt in PROGRESS_STATS}
COUNTS = {"score", "goals", "assists", "saves", "shots"}      # whole numbers in a single game


def fmt_value(col, value, average=False):
    """A stat for display: counts are whole numbers in one game, but averages of them need a decimal."""
    if col in COUNTS:
        return "{:.1f}".format(value) if average else "{:.0f}".format(value)
    return FORMATS[col].format(value)
SESSION_GAP = timedelta(minutes=30)       # a longer break starts a new session
SESSION_FRESH = timedelta(hours=6)        # a session older than this isn't "tonight" any more
MIN_USUAL_GAMES = 3
TILT_LOSSES = 3


def game_row(summary_player, frame_stats):
    """One player's header stats plus frame stats as a single dict (like a row of player_games)."""
    row = {"score": summary_player.score, "goals": summary_player.goals, "assists": summary_player.assists,
           "saves": summary_player.saves, "shots": summary_player.shots}
    row.update(frame_stats or {})
    return row


def headline_stats(row, games_before, mode, band, count=3):
    """The `count` stats that stand out most in this game.

    row: this game (see game_row). games_before: DataFrame of the player's earlier games.
    Each result: {label, value, note, good}. Standing out = furthest from typical for their rank
    (percentile far from 50) or, with no rank, from their own usual (relative change).
    """
    usual = None
    if games_before is not None and len(games_before) >= MIN_USUAL_GAMES:
        usual = games_before.mean(numeric_only=True)
    scored = []
    for col, label, higher in HEADLINE:
        value = row.get(col)
        if value is None or pd.isna(value):
            continue
        pct = benchmarks.percentile(mode, band, col, float(value)) if band else None
        if pct is not None:
            dev, note = pct - 50, f"{round(pct)}{_ordinal(round(pct))} percentile for {band}"
        elif usual is not None and col in usual and pd.notna(usual[col]):
            base = float(usual[col])
            rel = (float(value) - base) / max(abs(base), 1.0) * 100
            dev = rel if higher else -rel
            note = f"usually {fmt_value(col, base, average=True)}"
        else:
            continue
        scored.append((abs(dev), {"label": label, "value": fmt_value(col, float(value)), "note": note,
                                  "good": bool(dev >= 0)}))
    scored.sort(key=lambda item: -item[0])
    return [item for _, item in scored[:count]]


def _ordinal(n):
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def current_session(records, player_id, now=None):
    """The player's latest sitting, or None if they haven't played recently.

    {games, wins, losses, results: ["Win", ...] oldest first, stats: [{label, session, usual, good}], tilt}.
    `tilt` is True after TILT_LOSSES losses in a row at the end of the session.
    """
    games = player_games(list(records), player_id)
    if games.empty:
        return None
    now = now or datetime.now()
    start = len(games) - 1
    while start > 0 and games.played[start] - games.played[start - 1] <= SESSION_GAP:
        start -= 1
    session, before = games.iloc[start:], games.iloc[:start]
    if now - session.played.iloc[-1] > SESSION_FRESH:
        return None
    results = list(session.result)
    tail = results[-TILT_LOSSES:]
    stats = []
    if len(before) >= MIN_USUAL_GAMES:
        for col, label, higher in HEADLINE[:4]:
            mine, usual = session[col].mean(), before[col].mean()
            if pd.notna(mine) and pd.notna(usual):
                stats.append({"label": label, "session": fmt_value(col, mine, average=True),
                              "usual": fmt_value(col, usual, average=True), "good": bool((mine >= usual) == higher)})
    return {
        "games": len(session), "wins": results.count("Win"), "losses": results.count("Loss"), "results": results,
        "stats": stats, "tilt": len(tail) == TILT_LOSSES and all(r == "Loss" for r in tail),
    }
