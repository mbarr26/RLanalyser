"""Ball touches, 50/50s, dribbles, mechanics and last-man play, found with plain rules (no AI).

Everything here is measured from the frame data. `skill_stats` turns it into the per-player
columns shown in the Challenges / Mechanics / Defence tabs; `find_events` exposes the raw
events so moments.py can turn the important ones into key moments.

Thresholds are first-draft constants (see the top of the file) and need tuning against real games.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from frame_data import GOAL_HEIGHT, GROUND_HEIGHT, THIRD_LINE, GameFrames

# ---- touches ----
TOUCH_DELTA = 150          # uu/s change of ball velocity between two frames that counts as a hit
TOUCH_RADIUS = 300         # a car must be this close (centre to centre) to have hit the ball
TOUCH_MISMATCH_RADIUS = 200  # ...or this close if the game says the other team touched last
TOUCH_MERGE = 0.15         # seconds: repeat touches by one player inside this are one touch
AERIAL_Z = 300             # car height for an aerial touch
WALL_X, WALL_Y, WALL_Z = 3800, 4800, 150   # car this close to a side/back wall and this high = on the wall
HIT_WINDOW = 8             # frames (~0.27 s) in which a dodge still counts as "a flick" for a touch

# ---- challenges ----
FIFTY_WINDOW = 0.3         # opposing touches this close together are a 50/50
FIFTY_NEXT_TOUCH = 2.0     # the next touch within this many seconds decides who won
FIFTY_BALL_MOVE = 300      # otherwise the ball must travel this far toward a goal within 1 s
DOUBLE_COMMIT_DISTANCE = 700
CLOSING_SPEED = 300        # uu/s towards the ball counts as "going for it"
BEATEN_WINDOW = 0.5        # committed this long before the opponent's touch...
BEATEN_AFTER = 0.4         # ...and the ball is past you this long after it
BEATEN_BALL_SPEED = 500    # ball heads for your goal at least this fast
BEATEN_GAP = 2.0           # seconds between two "beaten" events for one player

# ---- mechanics ----
DRIBBLE_MIN_SECONDS = 1.0
DRIBBLE_HEIGHT = (100, 260)    # ball centre above car centre
DRIBBLE_DISTANCE = 200         # horizontal distance
DRIBBLE_CAR_Z = 40             # car must be on the ground
HALF_FLIP_SPEED = 500
HALF_FLIP_BACKWARDS = -0.3     # dot(car nose, travel direction) below this = moving backwards
HALF_FLIP_YAW = np.radians(135)
HALF_FLIP_SECONDS = 1.0
WAVEDASH_Z = 70                # dodge started this close to the floor...
WAVEDASH_AIR_Z = 150           # ...after being at least this high in the last 0.8 s

# ---- defence ----
SHADOW_DISTANCE = (800, 2500)
SHADOW_BALL_SPEED = 200        # ball moving toward your goal at least this fast
CLEAR_SECONDS = 1.0            # ball must have left your defensive third this soon after your touch


def find_runs(frames: pd.DataFrame, mask, min_seconds):
    """Stretches where mask is true on consecutive frames, lasting at least min_seconds.

    frames: one row per frame (columns frame, time, duration), sorted. Returns dicts with
    start/end replay time, seconds, and the frame range.
    """
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    frame = frames.frame.to_numpy()
    new = np.r_[True, (np.diff(frame) != 1) | (m[1:] != m[:-1])]
    group = np.cumsum(new)
    runs = []
    for _, g in frames[m].groupby(group[m]):
        seconds = float(g.duration.sum())
        if seconds >= min_seconds:
            last = g.iloc[-1]
            runs.append({
                "start": float(g.time.iloc[0]), "end": float(last.time + last.duration),
                "seconds": seconds, "frame": int(g.frame.iloc[0]), "last_frame": int(last.frame),
            })
    return runs


def live_table(game: GameFrames):
    """One row per player per live frame, with ball-relative columns. Orange is flipped so
    that for everyone negative own_y = their own half (same convention as analysis.py)."""
    live = game.frames.loc[game.frames.live, ["frame", "duration", "kickoff"]]
    ball = game.ball[["frame", "x", "y", "z", "vx", "vy", "vz"]].rename(
        columns={c: "b" + c for c in ("x", "y", "z", "vx", "vy", "vz")})
    p = game.players.merge(live, on="frame").merge(ball, on="frame", how="inner")
    if p.empty:
        return p
    p = p.sort_values(["frame", "player"], ignore_index=True)
    flip = np.where(p.team == 1, -1, 1)
    p["own_y"] = p.y * flip
    p["ball_own_y"] = p.by * flip
    p["ball_own_vy"] = p.bvy * flip      # negative = ball heading for this player's own goal
    p["ahead"] = p.own_y > p.ball_own_y
    dx, dy, dz = p.bx - p.x, p.by - p.y, p.bz - p.z
    p["dist_to_ball"] = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    closing = (p.vx * dx + p.vy * dy + p.vz * dz) / p.dist_to_ball.replace(0, np.nan)
    p["committed"] = (p.dist_to_ball < DOUBLE_COMMIT_DISTANCE) & (closing > CLOSING_SPEED)
    p["dodge_recent"] = (p.groupby("player").dodging
                         .transform(lambda s: s.rolling(HIT_WINDOW, min_periods=1).max()).astype(bool))
    team_n = p.groupby(["frame", "team"]).player.transform("size")
    p["last_man"] = (team_n >= 2) & (p.own_y == p.groupby(["frame", "team"]).own_y.transform("min"))
    return p


@dataclass
class Events:
    p: pd.DataFrame        # live_table
    ball: pd.DataFrame     # ball frames with live / kickoff flags
    touches: pd.DataFrame  # see detect_touches
    fifty: list            # 50/50s: dicts with time, frame, players, teams, winner (team or None)
    beaten: list           # times a committed player was beaten: dicts with time, frame, player, team, toucher
    dribbles: dict         # player -> list of runs (see find_runs)


def _ball_at(ball, t):
    """Ball row (as a Series) at replay time t, or None when the match has no ball data there."""
    i = int(np.searchsorted(ball.time.to_numpy(), t))
    return ball.iloc[min(i, len(ball) - 1)] if len(ball) else None


def detect_touches(game: GameFrames, p: pd.DataFrame) -> pd.DataFrame:
    """Every ball touch: the ball's velocity jumps while a car is next to it.

    Columns: frame, time, player, team, bx, by, bz (ball), car_z, speed_before, speed_after,
    to_opp_before / to_opp_after (ball y-speed, positive = towards the toucher's attacking goal),
    on_wall, aerial, high_aerial, dodge, own_y (toucher), ball_own_y.
    """
    columns = ["frame", "time", "player", "team", "bx", "by", "bz", "car_z", "speed_before", "speed_after",
               "to_opp_before", "to_opp_after", "on_wall", "aerial", "high_aerial", "dodge", "own_y", "ball_own_y"]
    empty = pd.DataFrame(columns=columns)
    ball = game.ball.merge(game.frames[["frame", "live"]], on="frame").sort_values("frame", ignore_index=True)
    if len(ball) < 2 or p.empty:
        return empty

    v = ball[["vx", "vy", "vz"]].to_numpy(dtype=float)
    speed = np.linalg.norm(v, axis=1)
    dv = np.r_[0.0, np.linalg.norm(np.diff(v, axis=0), axis=1)]
    consecutive = np.r_[False, np.diff(ball.frame.to_numpy()) == 1]
    ball["speed_before"] = np.r_[0.0, speed[:-1]]
    ball["speed_after"] = speed
    ball["vy_before"] = np.r_[0.0, v[:-1, 1]]
    cand = ball[(dv > TOUCH_DELTA) & consecutive & ball.live.to_numpy()]
    cand = cand.rename(columns={"x": "bx", "y": "by", "z": "bz"})
    if cand.empty:
        return empty

    cars = p[p.dist_to_ball < TOUCH_RADIUS][["frame", "player", "team", "z", "x", "y", "own_y", "ball_own_y",
                                              "dist_to_ball", "dodge_recent"]]
    m = cand.merge(cars, on="frame", suffixes=("_ball", ""))
    if m.empty:
        return empty
    m["mismatch"] = m.hit_team.notna() & (m.team != m.hit_team)
    m = m.sort_values(["frame", "mismatch", "dist_to_ball"]).drop_duplicates("frame")
    m = m[~m.mismatch | (m.dist_to_ball < TOUCH_MISMATCH_RADIUS)].sort_values("time")
    # one touch per player per TOUCH_MERGE seconds
    m = m[(m.groupby("player").time.diff().fillna(np.inf) > TOUCH_MERGE)]

    sign = np.where(m.team == 1, -1, 1)
    near_wall = ((m.x.abs() > WALL_X) | (m.y.abs() > WALL_Y)) & (m.z > WALL_Z)
    out = pd.DataFrame({
        "frame": m.frame, "time": m.time, "player": m.player, "team": m.team.astype(int),
        "bx": m.bx, "by": m.by, "bz": m.bz, "car_z": m.z,
        "speed_before": m.speed_before, "speed_after": m.speed_after,
        "to_opp_before": m.vy_before * sign, "to_opp_after": m.vy * sign,
        "on_wall": near_wall, "aerial": (m.z > AERIAL_Z) & ~near_wall, "high_aerial": m.z > GOAL_HEIGHT,
        "dodge": m.dodge_recent, "own_y": m.own_y, "ball_own_y": m.ball_own_y,
    })
    return out[columns].reset_index(drop=True)


def detect_fifty(touches: pd.DataFrame, ball: pd.DataFrame) -> list:
    """Opposing touches within FIFTY_WINDOW of each other. winner = the team that came out with
    the ball (the next touch, else where the ball went over the next second), or None."""
    out = []
    t = touches.reset_index(drop=True)
    i = 0
    while i < len(t) - 1:
        a, b = t.iloc[i], t.iloc[i + 1]
        if a.team == b.team or b.time - a.time > FIFTY_WINDOW:
            i += 1
            continue
        winner = None
        if i + 2 < len(t) and t.time.iloc[i + 2] - b.time <= FIFTY_NEXT_TOUCH:
            winner = int(t.team.iloc[i + 2])
        else:
            start, later = _ball_at(ball, b.time), _ball_at(ball, b.time + 1.0)
            if start is not None and abs(later.y - start.y) >= FIFTY_BALL_MOVE:
                winner = 0 if later.y > start.y else 1   # blue attacks +y
        out.append({"time": float(a.time), "frame": int(a.frame), "players": [a.player, b.player],
                    "teams": [int(a.team), int(b.team)], "winner": winner})
        i += 2
    return out


def detect_beaten(touches: pd.DataFrame, p: pd.DataFrame) -> list:
    """A player who went for the ball, lost the touch to an opponent and was left behind it
    while it heads for their own goal."""
    out = []
    if touches.empty:
        return out
    times = p.time.to_numpy()
    last_seen = {}
    for _, t in touches.iterrows():
        lo = np.searchsorted(times, t.time - BEATEN_WINDOW)
        mid = np.searchsorted(times, t.time, side="right")
        hi = np.searchsorted(times, t.time + BEATEN_AFTER, side="right")
        before, window = p.iloc[lo:mid], p.iloc[lo:hi]
        for name in before[(before.team != t.team) & before.committed].player.unique():
            if t.time - last_seen.get(name, -np.inf) < BEATEN_GAP:
                continue
            mine = window[window.player == name]
            now = mine.iloc[-1]
            if now.ball_own_vy < -BEATEN_BALL_SPEED and now.own_y > now.ball_own_y:
                last_seen[name] = t.time
                out.append({"time": float(t.time), "frame": int(t.frame), "player": name,
                            "team": int(now.team), "toucher": t.player, "last_man": bool(now.last_man)})
    return out


def detect_dribbles(p: pd.DataFrame) -> dict:
    """player -> runs of at least DRIBBLE_MIN_SECONDS with the ball carried on the car's roof."""
    out = {}
    lift = p.bz - p.z
    horizontal = np.hypot(p.bx - p.x, p.by - p.y)
    mask = ((p.z <= DRIBBLE_CAR_Z) & (lift >= DRIBBLE_HEIGHT[0]) & (lift <= DRIBBLE_HEIGHT[1])
            & (horizontal <= DRIBBLE_DISTANCE))
    for name, d in p.groupby("player"):
        runs = find_runs(d[["frame", "time", "duration"]], mask[d.index].to_numpy(), DRIBBLE_MIN_SECONDS)
        if runs:
            out[name] = runs
    return out


def find_events(game: GameFrames) -> Events:
    p = live_table(game)
    ball = game.ball.merge(game.frames[["frame", "live", "kickoff"]], on="frame").sort_values("frame", ignore_index=True)
    if p.empty:
        return Events(p, ball, detect_touches(game, p), [], [], {})
    touches = detect_touches(game, p)
    return Events(p, ball, touches, detect_fifty(touches, ball), detect_beaten(touches, p), detect_dribbles(p))


def _forward_xy(d):
    """Horizontal part of each car's nose direction, from its rotation quaternion."""
    fx = 1 - 2 * (d.qy ** 2 + d.qz ** 2)
    fy = 2 * (d.qx * d.qy + d.qw * d.qz)
    return fx.to_numpy(dtype=float), fy.to_numpy(dtype=float)


def _rising(flag: pd.Series):
    """Indices (positions) where a boolean series turns on."""
    f = flag.to_numpy(dtype=bool)
    return np.flatnonzero(f & ~np.r_[False, f[:-1]])


def _count_moves(d):
    """(dodges, double jumps, half-flips, wave-dashes) for one player's live frames."""
    dodge_starts = _rising(d.dodging)
    time, z = d.time.to_numpy(), d.z.to_numpy()
    fx, fy = _forward_xy(d)
    vx, vy, speed = d.vx.to_numpy(), d.vy.to_numpy(), d.speed.to_numpy()
    half_flips = wave_dashes = 0
    for k in dodge_starts:
        horizontal = np.hypot(vx[k], vy[k])
        if speed[k] > HALF_FLIP_SPEED and horizontal > 1 and np.isfinite(fx[k]):
            if (fx[k] * vx[k] + fy[k] * vy[k]) / (horizontal * np.hypot(fx[k], fy[k])) < HALF_FLIP_BACKWARDS:
                end = np.searchsorted(time, time[k] + HALF_FLIP_SECONDS, side="right")
                turn = np.abs(np.angle(np.exp(1j * (np.arctan2(fy[k:end], fx[k:end]) - np.arctan2(fy[k], fx[k])))))
                if turn.size and np.nanmax(turn) >= HALF_FLIP_YAW:
                    half_flips += 1
        recent = z[np.searchsorted(time, time[k] - 0.8):k + 1]
        if z[k] < WAVEDASH_Z and recent.size and recent.max() > WAVEDASH_AIR_Z:
            wave_dashes += 1
    return len(dodge_starts), len(_rising(d.double_jumping)), half_flips, wave_dashes


def possession_seconds(ev: Events) -> dict:
    """Seconds each player was the last to touch the ball (live play after the kickoff touch)."""
    if ev.touches.empty:
        return {}
    frames = ev.p.groupby("frame").agg(duration=("duration", "first"), kickoff=("kickoff", "first")).reset_index()
    frames = frames[~frames.kickoff]
    held = pd.merge_asof(frames, ev.touches[["frame", "player"]], on="frame")
    return held.groupby("player").duration.sum().to_dict()


def skill_stats(game: GameFrames, ev: Events | None = None) -> dict:
    """player name -> the Challenges / Mechanics / Defence columns (see analysis.STAT_GROUPS)."""
    ev = ev or find_events(game)
    p, touches = ev.p, ev.touches
    if p.empty:
        return {}
    possession = possession_seconds(ev)
    out = {}
    for name, d in p.groupby("player"):
        live = float(d.duration.sum())
        w = d.duration

        def pct(mask):
            return float(w[mask].sum() / live * 100) if live else 0.0

        mine = touches[touches.player == name]
        fifty = [f for f in ev.fifty if name in f["players"]]
        decided = [f for f in fifty if f["winner"] is not None]
        team = int(d.team.iloc[0])
        own_goal_side = d.own_y < 0

        # Clears: a touch in your defensive third that gets the ball out of it
        clears = 0
        for _, t in mine[mine.ball_own_y < -THIRD_LINE].iterrows():
            later = _ball_at(ev.ball, t.time + CLEAR_SECONDS)
            if later is not None and later.y * (-1 if team == 1 else 1) > -THIRD_LINE:
                clears += 1

        dodges, double_jumps, half_flips, wave_dashes = _count_moves(d)
        dribble_runs = ev.dribbles.get(name, [])

        out[name] = {
            # Challenges
            "touches": len(mine),
            "touches_per_min": len(mine) / live * 60 if live else 0.0,
            "pct_possession": float(possession.get(name, 0.0) / live * 100) if live else 0.0,
            "fifty_fifties": len(fifty),
            "fifty_win_pct": len([f for f in decided if f["winner"] == team]) / len(decided) * 100 if decided else None,
            "times_beaten": sum(b["player"] == name for b in ev.beaten),
            # Mechanics
            "aerial_touches": int(mine.aerial.sum()),
            "high_aerials": int(mine.high_aerial.sum()),
            "wall_touches": int(mine.on_wall.sum()),
            "dodge_touches": int(mine.dodge.sum()),
            "hardest_hit": float(mine.speed_after.max()) if len(mine) else None,
            "dribbles": len(dribble_runs),
            "dribble_seconds": float(sum(r["seconds"] for r in dribble_runs)),
            "dodges": dodges,
            "double_jumps": double_jumps,
            "half_flips": half_flips,
            "wave_dashes": wave_dashes,
            # Defence
            "clears": clears,
            "pct_shadowing": pct(own_goal_side & (d.own_y < d.ball_own_y)
                                 & d.dist_to_ball.between(*SHADOW_DISTANCE) & (d.ball_own_vy < -SHADOW_BALL_SPEED)),
            "pct_last_man": pct(d.last_man),
            "last_man_beaten": sum(b["player"] == name and b["last_man"] for b in ev.beaten),
        }
    return out
