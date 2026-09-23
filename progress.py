"""One player's stats across many replays: game history, averages, and win/loss comparisons."""

from collections import Counter

import pandas as pd

from analysis import STAT_GROUPS

# (column, heading, format) for every stat tracked over time
HEADER_STATS = [
    ("score", "Score", "{:.0f}"),
    ("goals", "Goals", "{:.2f}"),
    ("assists", "Assists", "{:.2f}"),
    ("saves", "Saves", "{:.2f}"),
    ("shots", "Shots", "{:.2f}"),
]
PROGRESS_STATS = HEADER_STATS + [stat for stats in STAT_GROUPS.values() for stat in stats]
RECENT_GAMES = 10


def known_players(records):
    """[(player_id, latest name, games played)] for everyone seen, most games first."""
    games, latest = Counter(), {}
    for record in sorted(records, key=lambda r: r.played_at):
        for p in record.summary.players:
            if not p.is_bot:
                games[p.player_id] += 1
                latest[p.player_id] = p.name
    return [(pid, latest[pid], count) for pid, count in games.most_common()]


def guess_me(records):
    """Best guess at which player owns these replays.

    Some replay headers name the player who saved them; failing that, whoever
    played the most games.
    """
    recorders = Counter()
    for record in records:
        for p in record.summary.players:
            if record.summary.recorded_by and p.name == record.summary.recorded_by:
                recorders[p.player_id] += 1
    if recorders:
        return recorders.most_common(1)[0][0]
    players = known_players(records)
    return players[0][0] if players else None


def mode_of(summary):
    return f"{summary.team_size}v{summary.team_size}"


def player_games(records, player_id, mode=None):
    """One row per game the player was in, oldest first. Frame stats are NaN if not analysed."""
    rows = []
    for record in records:
        s = record.summary
        me = s.player(player_id)
        if me is None or (mode and mode_of(s) != mode):
            continue
        mine, theirs = (s.team0_score, s.team1_score) if me.team == 0 else (s.team1_score, s.team0_score)
        row = {
            "path": record.path,
            "played": record.played_at,
            "mode": mode_of(s),
            "map": s.map_name,
            "name": me.name,
            "result": "Win" if mine > theirs else "Loss" if mine < theirs else "-",
            "score_line": f"{mine}-{theirs}",
            "score": me.score, "goals": me.goals, "assists": me.assists, "saves": me.saves, "shots": me.shots,
        }
        row.update((record.players or {}).get(me.name, {}))
        rows.append(row)

    columns = ["path", "played", "mode", "map", "name", "result", "score_line"] + [c for c, _, _ in PROGRESS_STATS]
    games = pd.DataFrame(rows).reindex(columns=columns)
    stat_columns = [c for c, _, _ in PROGRESS_STATS]
    games[stat_columns] = games[stat_columns].apply(pd.to_numeric, errors="coerce")  # missing -> NaN
    return games.sort_values("played", ignore_index=True)


def comparison(games):
    """Average of every stat over: all games, the last few, wins only, losses only.

    Returns (column headings, [(stat column, stat heading, [formatted averages])]).
    """
    groups = {
        "All games": games,
        f"Last {RECENT_GAMES}": games.tail(RECENT_GAMES),
        "Wins": games[games.result == "Win"],
        "Losses": games[games.result == "Loss"],
    }
    rows = []
    for col, heading, fmt in PROGRESS_STATS:
        values = [fmt.format(g[col].mean()) if g[col].notna().any() else "-" for g in groups.values()]
        rows.append((col, heading, values))
    return list(groups), rows
