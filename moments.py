"""Key moments in a match, found with plain rules (no AI), plus short rule-based insights.

The AI coach (coach.py) only *explains* what is found here: every time, position and
boost figure comes from the frame data, so the AI never has to guess facts. The moments
and insights are also shown on their own, for people who don't run the AI model.

`time` on a moment is the replay time used by the match viewer, so a moment can be
opened straight in "Watch match".
"""

import numpy as np
import pandas as pd

from analysis import GROUND_HEIGHT, PITCH_HALF_LENGTH, THIRD_LINE
from frame_data import GameFrames

TEAM_NAMES = {0: "Blue", 1: "Orange"}
MAX_MOMENTS = 20            # goals are always kept; the rest are the most severe
GOAL_LOOKBACK = 3.0         # seconds before a goal that the defence is checked
NOBODY_BACK_SECONDS = 1.5   # whole team ahead of a ball that is in its own half
DOUBLE_COMMIT_SECONDS = 0.5
DOUBLE_COMMIT_DISTANCE = 700
CLOSING_SPEED = 300         # uu/s towards the ball counts as "going for it"
NO_BOOST_SECONDS = 4.0
LOW_BOOST = 15
FAR_FROM_NET = 3500
AIRBORNE = 300
GOAL_FOLLOW_SECONDS = 6.0   # a goal this soon after a mistake is blamed on it
MERGE_GAP = 4.0             # same mistake repeating within this many seconds is one moment


def fmt_clock(seconds):
    if seconds is None:
        return ""
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _live_table(game: GameFrames):
    """One row per player per live frame, with ball-relative columns. Orange is flipped so
    that for everyone negative own_y = their own half (same convention as analysis.py)."""
    live = game.frames.loc[game.frames.live, ["frame", "duration", "kickoff"]]
    ball = game.ball[["frame", "x", "y", "z"]].rename(columns={"x": "bx", "y": "by", "z": "bz"})
    p = game.players.merge(live, on="frame").merge(ball, on="frame", how="inner")
    if p.empty:
        return p
    flip = np.where(p.team == 1, -1, 1)
    p["own_y"] = p.y * flip
    p["ball_own_y"] = p.by * flip
    p["ahead"] = p.own_y > p.ball_own_y
    dx, dy, dz = p.bx - p.x, p.by - p.y, p.bz - p.z
    p["dist_to_ball"] = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    closing = (p.vx * dx + p.vy * dy + p.vz * dz) / p.dist_to_ball.replace(0, np.nan)
    p["committed"] = (p.dist_to_ball < DOUBLE_COMMIT_DISTANCE) & (closing > CLOSING_SPEED)
    return p.sort_values(["frame", "player"], ignore_index=True)


def _runs(frames: pd.DataFrame, mask, min_seconds):
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


def _merge_close(moments):
    """Keep only the most severe of same-type, same-team/player moments that are close in time."""
    kept = []
    for m in sorted(moments, key=lambda m: m["time"]):
        prev = next((k for k in reversed(kept)
                     if k["type"] == m["type"] and k["team"] == m["team"] and k["players"] == m["players"]), None)
        if prev and m["time"] - prev["time"] < MERGE_GAP:
            if m["severity"] > prev["severity"]:
                kept[kept.index(prev)] = m
        else:
            kept.append(m)
    return kept


def detect_moments(game: GameFrames, summary) -> list[dict]:
    """Key moments of a match, oldest first. Each is a dict:
        id, time, clock (seconds on the game clock or None), clock_text, type, team,
        players, title, detail, seconds, severity, flags
    flags (goals only) maps each defender's name to what was wrong with their position.
    """
    p = _live_table(game)
    if p.empty:
        return []
    frames = game.frames
    clock_of = dict(zip(frames.frame, frames.seconds_remaining))
    moments = []

    def add(kind, title, time, frame, team, players, detail, seconds=0.0, severity=0.0, flags=None):
        clock = clock_of.get(frame)
        clock = None if clock is None or pd.isna(clock) else int(clock)
        moments.append({
            "type": kind, "title": title, "time": float(time), "clock": clock, "clock_text": fmt_clock(clock),
            "team": int(team), "players": list(players), "detail": detail,
            "seconds": round(float(seconds), 1), "severity": float(severity), "flags": flags or {},
        })

    # ---- goals, with the conceding team's positions a few seconds earlier ----
    goal_times = []
    score = [0, 0]
    for goal in summary.goals:
        if not 0 <= goal.frame < len(frames):
            continue
        t_goal = float(frames.time.iloc[goal.frame])
        goal_times.append((t_goal, goal.team))
        score[goal.team] += 1
        conceding = 1 - goal.team
        before = p[(p.team == conceding) & (p.time >= t_goal - GOAL_LOOKBACK) & (p.time <= t_goal)]
        flags, notes = {}, []
        if not before.empty:
            first = before[before.frame == before.frame.min()]
            for _, d in first.iterrows():
                problems = []
                if d.ahead:
                    problems.append("ahead of the ball")
                if d.boost is not None and not pd.isna(d.boost) and d.boost < LOW_BOOST:
                    problems.append(f"low on boost ({d.boost:.0f})")
                if d.z > AIRBORNE:
                    problems.append("in the air")
                net_dist = float(np.hypot(d.x, d.own_y + PITCH_HALF_LENGTH))
                if net_dist > FAR_FROM_NET:
                    problems.append(f"far from their net ({net_dist:.0f}uu)")
                flags[d.player] = problems
                if problems:
                    notes.append(f"{d.player} {', '.join(problems)}")
        else:
            notes.append("no defence data available")
        detail = (f"{goal.scorer} scored for {TEAM_NAMES[goal.team]} ({score[0]}-{score[1]}). "
                  f"{GOAL_LOOKBACK:.0f}s earlier, {TEAM_NAMES[conceding]}: "
                  + ("; ".join(notes) if notes else "defenders were in reasonable position") + ".")
        add("goal", f"Goal: {goal.scorer}", t_goal, goal.frame, goal.team, [goal.scorer], detail,
            severity=100.0, flags=flags)

    def goal_after(t_end, team):
        """Seconds until the other team scores, if soon after t_end (else None)."""
        for t_goal, scorer in goal_times:
            if scorer != team and 0 <= t_goal - t_end <= GOAL_FOLLOW_SECONDS:
                return t_goal - t_end
        return None

    # ---- team-level mistakes ----
    for team in (0, 1):
        t = p[p.team == team]
        if t.empty:
            continue
        g = t.groupby("frame")
        per_frame = pd.DataFrame({
            "time": g.time.first(), "duration": g.duration.first(), "kickoff": g.kickoff.first(),
            "n": g.size(), "all_ahead": g.ahead.all(), "ball_own_y": g.ball_own_y.first(),
            "min_own_y": g.own_y.min(), "committed": g.committed.sum(),
        }).reset_index()
        names = sorted(t.player.unique())

        if per_frame.n.max() >= 2:
            mask = per_frame.all_ahead & (per_frame.ball_own_y < 0) & (per_frame.n >= 2) & ~per_frame.kickoff
            for run in _runs(per_frame, mask, NOBODY_BACK_SECONDS):
                rows = per_frame[(per_frame.frame >= run["frame"]) & (per_frame.frame <= run["last_frame"])]
                everyone_forward = bool((rows.min_own_y > THIRD_LINE).any())
                detail = (f"{TEAM_NAMES[team]} had every player ahead of the ball for {run['seconds']:.1f}s "
                          f"while it was in their own half"
                          + (" (all in the offensive third)" if everyone_forward else "") + ".")
                late = goal_after(run["end"], team)
                if late is not None:
                    detail += f" {TEAM_NAMES[1 - team]} scored {late:.0f}s later."
                add("nobody_back", "Nobody back", run["start"], run["frame"], team, names, detail,
                    run["seconds"], run["seconds"] * 2 + (10 if late is not None else 0))

            mask = (per_frame.committed >= 2) & ~per_frame.kickoff
            for run in _runs(per_frame, mask, DOUBLE_COMMIT_SECONDS):
                window = t[(t.frame >= run["frame"]) & (t.frame <= run["last_frame"]) & t.committed]
                who = sorted(window.player.unique())
                detail = (f"{' and '.join(who)} both went for the ball at once for {run['seconds']:.1f}s, "
                          f"leaving less cover behind.")
                late = goal_after(run["end"], team)
                if late is not None:
                    detail += f" {TEAM_NAMES[1 - team]} scored {late:.0f}s later."
                add("double_commit", "Double commit", run["start"], run["frame"], team, who, detail,
                    run["seconds"], run["seconds"] * 3 + (10 if late is not None else 0))

    # ---- out of boost, per player ----
    for name, d in p.groupby("player"):
        d = d.sort_values("frame")
        mask = d.boost.notna() & (d.boost < 1)
        for run in _runs(d[["frame", "time", "duration"]], mask, NO_BOOST_SECONDS):
            add("no_boost", "Out of boost", run["start"], run["frame"], d.team.iloc[0], [name],
                f"{name} had no boost for {run['seconds']:.1f}s.", run["seconds"], run["seconds"] / 2)

    # ---- keep the goals and the most severe mistakes, oldest first ----
    goals = [m for m in moments if m["type"] == "goal"]
    others = sorted(_merge_close([m for m in moments if m["type"] != "goal"]),
                    key=lambda m: -m["severity"])[:max(0, MAX_MOMENTS - len(goals))]
    result = sorted(goals + others, key=lambda m: m["time"])
    for i, m in enumerate(result, 1):
        m["id"] = f"m{i}"
    return result


def insights(summary, players, moments, me_name, usual=None) -> list[dict]:
    """Short rule-based findings about one player: [{kind: good|bad|info, text}].

    players: record.players (name -> frame stats). usual: that player's average of each
    stat over all their games ({column: value}), or None.
    """
    me = (players or {}).get(me_name)
    if me is None:
        return []
    out = []

    def add(kind, text):
        out.append({"kind": kind, "text": text})

    my_team = me["team"]
    conceded = [m for m in moments if m["type"] == "goal" and m["team"] != my_team and me_name in m["flags"]]
    if conceded:
        ahead = sum("ahead of the ball" in m["flags"][me_name] for m in conceded)
        if ahead:
            add("bad", f"You were ahead of the ball on {ahead} of the {len(conceded)} goals you conceded.")
        else:
            add("good", f"You were never ahead of the ball when you conceded ({len(conceded)} goals).")

    def compare(col, label, higher_is_better, unit="%", margin=5.0):
        value, base = me.get(col), (usual or {}).get(col)
        if value is None or base is None or pd.isna(base):
            return
        diff = value - base
        if abs(diff) < margin:
            return
        better = (diff > 0) == higher_is_better
        add("good" if better else "bad",
            f"{label}: {value:.0f}{unit} this game vs your usual {base:.0f}{unit}.")

    compare("pct_behind_ball", "Time behind the ball", True)
    compare("pct_zero_boost", "Time on empty boost", False)
    compare("pct_supersonic", "Time supersonic", True)

    if me["pct_zero_boost"] > 15 and not any("empty boost" in i["text"] for i in out):
        add("bad", f"You spent {me['pct_zero_boost']:.0f}% of the game on 0 boost.")
    if me["stolen_big_pads"] >= 2:
        add("good", f"You stole {me['stolen_big_pads']:.0f} big boost pads from the opponent's half.")

    back = [m for m in moments if m["type"] == "nobody_back" and m["team"] == my_team]
    if back:
        add("bad", f"Your team had nobody behind the ball {len(back)} time(s).")
    double = [m for m in moments if m["type"] == "double_commit" and me_name in m["players"]]
    if double:
        add("bad", f"You and a teammate both challenged the ball {len(double)} time(s).")
    empty = [m for m in moments if m["type"] == "no_boost" and me_name in m["players"]]
    if empty:
        add("bad", f"You had {len(empty)} stretch(es) of 4+ seconds with no boost.")
    return out
