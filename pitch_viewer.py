"""Match playback data: frame data rearranged into arrays for the "Watch match" viewer.

The viewer itself is drawn in the UI (ui/pitch.js); this module only builds the
JSON-serialisable track it plays back, `build_track`.
"""

import numpy as np

from frame_data import GameFrames


class MatchTrack:
    """Frame data rearranged into per-frame arrays for fast lookup at any playback time."""

    def __init__(self, game: GameFrames, goals=()):
        frames = game.frames
        self.times = frames.time.to_numpy()
        self.states = frames.state.to_numpy()
        self.clock = frames.seconds_remaining.to_numpy()
        n = len(frames)

        self.ball = np.full((n, 3), np.nan)
        self.ball[game.ball.frame.to_numpy()] = game.ball[["x", "y", "z"]].to_numpy()

        p = game.players
        yaw = np.arctan2(2 * (p.qw * p.qz + p.qx * p.qy), 1 - 2 * (p.qy ** 2 + p.qz ** 2))
        p = p.assign(yaw=yaw)
        self.players = []
        for (team, name), g in p.groupby(["team", "player"]):
            data = np.full((n, 6), np.nan)
            data[g.frame.to_numpy()] = g[["x", "y", "z", "yaw", "boost", "speed"]].to_numpy(dtype=float)
            self.players.append({"name": name, "team": int(team), "data": data})

        self.goals = [(g.frame, g.team, g.scorer) for g in goals]

        # Stretches after goals (post-goal celebration + replay) that "skip replays" jumps over
        self.dead = []
        dead = np.isin(self.states, ["PostGoalScored", "ReplayPlayback"])
        i = 0
        while i < n:
            if dead[i]:
                j = i
                while j < n and dead[j]:
                    j += 1
                start = self.times[i] + 2.0  # GOAL_REPLAY_KEEP, kept in sync with ui/pitch.js
                end = self.times[j] if j < n else self.times[-1]
                if end > start:
                    self.dead.append((start, end))
                i = j
            else:
                i += 1


def _row_or_none(row):
    return None if np.isnan(row[0]) else [float(v) for v in row]


def _clock_value(c):
    if c is None or (isinstance(c, float) and np.isnan(c)):
        return None
    return int(c)


def build_track(game: GameFrames, goals=()):
    """A JSON-safe dict of everything ui/pitch.js needs to play back a match."""
    track = MatchTrack(game, goals)
    return {
        "times": [float(t) for t in track.times],
        "states": [str(s) for s in track.states],
        "clock": [_clock_value(c) for c in track.clock],
        "ball": [_row_or_none(row) for row in track.ball],
        "players": [
            {"name": player["name"], "team": player["team"], "data": [_row_or_none(row) for row in player["data"]]}
            for player in track.players
        ],
        "goals": [[int(frame), int(team), scorer] for frame, team, scorer in track.goals],
        "dead": [[float(start), float(end)] for start, end in track.dead],
    }
