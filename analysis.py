"""Per-player stats computed from frame data. Only live play (state Active) is counted."""

import numpy as np
import pandas as pd

from frame_data import GameFrames

SUPERSONIC_SPEED = 2200
BOOST_SPEED = 1410        # max speed without boosting
GROUND_HEIGHT = 20        # a car resting on the floor sits at z ~17
GOAL_HEIGHT = 642         # above crossbar height counts as "high air"
PITCH_HALF_LENGTH = 5120
THIRD_LINE = PITCH_HALF_LENGTH / 3   # thirds split at y = +/-1707
BOOST_USE_PER_SEC = 100 / 3          # % of a full tank used per second of boosting
SMALL_PAD_BOOST = 12
BIG_PAD_BOOST = 100

# Stat groups shown in the UI: (column, heading, format)
STAT_GROUPS = {
    "Movement": [
        ("avg_speed", "Avg speed", "{:.0f}"),
        ("pct_supersonic", "% Supersonic", "{:.1f}"),
        ("pct_boost_speed", "% Boost speed", "{:.1f}"),
        ("pct_slow", "% Slow", "{:.1f}"),
        ("pct_ground", "% Ground", "{:.1f}"),
        ("pct_low_air", "% Low air", "{:.1f}"),
        ("pct_high_air", "% High air", "{:.1f}"),
    ],
    "Positioning": [
        ("pct_def_third", "% Def third", "{:.1f}"),
        ("pct_mid_third", "% Mid third", "{:.1f}"),
        ("pct_off_third", "% Off third", "{:.1f}"),
        ("pct_behind_ball", "% Behind ball", "{:.1f}"),
        ("avg_dist_to_ball", "Avg dist to ball", "{:.0f}"),
        ("pct_closest_to_ball", "% Closest (team)", "{:.1f}"),
        ("pct_farthest_from_ball", "% Farthest (team)", "{:.1f}"),
    ],
    "Boost": [
        ("avg_boost", "Avg boost", "{:.0f}"),
        ("boost_used", "Boost used", "{:.0f}"),
        ("boost_collected", "Collected", "{:.0f}"),
        ("big_pads", "Big pads", "{:.0f}"),
        ("small_pads", "Small pads", "{:.0f}"),
        ("stolen_big_pads", "Stolen big", "{:.0f}"),
        ("pct_zero_boost", "% at 0", "{:.1f}"),
        ("pct_full_boost", "% at 100", "{:.1f}"),
    ],
}


def _pct(mask, weights):
    total = weights.sum()
    return float((weights[mask]).sum() / total * 100) if total else 0.0


def player_stats(game: GameFrames) -> pd.DataFrame:
    """One row per player (index = name) with every stat in STAT_GROUPS plus team and live time."""
    live_frames = game.frames.loc[game.frames.live, ["frame", "duration"]]
    ball = game.ball[["frame", "x", "y", "z"]].rename(columns={"x": "bx", "y": "by", "z": "bz"})

    p = game.players.merge(live_frames, on="frame").merge(ball, on="frame", how="left")

    # Flip orange so that for everyone, negative y = own half and positive y = attacking
    flip = np.where(p.team == 1, -1, 1)
    p["own_y"] = p.y * flip
    p["ball_own_y"] = p.by * flip
    p["dist_to_ball"] = np.sqrt((p.x - p.bx) ** 2 + (p.y - p.by) ** 2 + (p.z - p.bz) ** 2)

    # Rank players within their team each frame by distance to the ball
    rank = p.groupby(["frame", "team"]).dist_to_ball
    p["closest"] = p.dist_to_ball == rank.transform("min")
    p["farthest"] = (p.dist_to_ball == rank.transform("max")) & (rank.transform("size") > 1)

    pickups = game.pickups.copy()
    pickups["own_y"] = pickups.y * np.where(pickups.team == 1, -1, 1)

    rows = {}
    for name, g in p.groupby("player"):
        w = g.duration
        live_seconds = float(w.sum())
        has_ball = g.bx.notna()
        wb = w[has_ball]
        pk = pickups[pickups.player == name]
        big = pk[pk.big]
        small_count, big_count = int((~pk.big).sum()), len(big)

        rows[name] = {
            "team": int(g.team.iloc[0]),
            "live_seconds": live_seconds,
            # Movement
            "avg_speed": float(np.average(g.speed, weights=w)) if live_seconds else 0.0,
            "pct_supersonic": _pct(g.speed >= SUPERSONIC_SPEED, w),
            "pct_boost_speed": _pct((g.speed >= BOOST_SPEED) & (g.speed < SUPERSONIC_SPEED), w),
            "pct_slow": _pct(g.speed < BOOST_SPEED, w),
            "pct_ground": _pct(g.z <= GROUND_HEIGHT, w),
            "pct_low_air": _pct((g.z > GROUND_HEIGHT) & (g.z <= GOAL_HEIGHT), w),
            "pct_high_air": _pct(g.z > GOAL_HEIGHT, w),
            # Positioning
            "pct_def_third": _pct(g.own_y < -THIRD_LINE, w),
            "pct_mid_third": _pct(g.own_y.abs() <= THIRD_LINE, w),
            "pct_off_third": _pct(g.own_y > THIRD_LINE, w),
            "pct_behind_ball": _pct(g.own_y[has_ball] < g.ball_own_y[has_ball], wb),
            "avg_dist_to_ball": float(np.average(g.dist_to_ball[has_ball], weights=wb)) if wb.sum() else 0.0,
            "pct_closest_to_ball": _pct(g.closest[has_ball], wb),
            "pct_farthest_from_ball": _pct(g.farthest[has_ball], wb),
            # Boost ("collected" is the pad value, ignoring any overflow past a full tank)
            "avg_boost": float(np.average(g.boost, weights=w)) if live_seconds else 0.0,
            "boost_used": float(w[g.boosting].sum() * BOOST_USE_PER_SEC),
            "boost_collected": float(small_count * SMALL_PAD_BOOST + big_count * BIG_PAD_BOOST),
            "big_pads": big_count,
            "small_pads": small_count,
            "stolen_big_pads": int((big.own_y > 0).sum()),
            "pct_zero_boost": _pct(g.boost < 1, w),
            "pct_full_boost": _pct(g.boost > 99, w),
        }

    return pd.DataFrame.from_dict(rows, orient="index").sort_values(["team", "avg_speed"], ascending=[True, False])


def team_stats(game: GameFrames) -> dict:
    """Match-level stats: how long the ball spent in each half/third (percent of live time)."""
    live = game.frames.loc[game.frames.live, ["frame", "duration"]]
    b = game.ball.merge(live, on="frame")
    w = b.duration
    return {
        "live_seconds": float(live.duration.sum()),
        "ball_pct_blue_half": _pct(b.y < 0, w),
        "ball_pct_orange_half": _pct(b.y >= 0, w),
        "ball_pct_blue_third": _pct(b.y < -THIRD_LINE, w),
        "ball_pct_mid_third": _pct(b.y.abs() <= THIRD_LINE, w),
        "ball_pct_orange_third": _pct(b.y > THIRD_LINE, w),
        "ball_avg_speed": float(np.average(np.sqrt(b.vx ** 2 + b.vy ** 2 + b.vz ** 2), weights=w)) if w.sum() else 0.0,
    }
