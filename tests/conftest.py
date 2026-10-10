"""Shared helpers: tiny hand-made games so each rule can be tested on its own."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from frame_data import GameFrames  # noqa: E402

FPS = 30


def make_game(seconds, ball, cars):
    """A GameFrames with every frame live.

    ball: f(t) -> dict(x, y, z, vx, vy, vz) (missing keys are 0).
    cars: {name: (team, f(t) -> dict(x, y, z, vx, vy, vz, dodging, ...))}.
    """
    n = int(seconds * FPS)
    times = [i / FPS for i in range(n)]
    frames = pd.DataFrame({"frame": range(n), "time": times, "duration": 1 / FPS, "state": "Active",
                           "live": True, "kickoff": False, "seconds_remaining": 300})
    b = pd.DataFrame([{"frame": i, "time": t, "hit_team": None,
                       **{k: 0.0 for k in ("x", "y", "z", "vx", "vy", "vz")}, **ball(t)}
                      for i, t in enumerate(times)])
    rows = []
    for name, (team, fn) in cars.items():
        for i, t in enumerate(times):
            row = {"frame": i, "time": t, "player": name, "team": team,
                   **{k: 0.0 for k in ("x", "y", "z", "vx", "vy", "vz", "speed", "qx", "qy", "qz")},
                   "qw": 1.0, "boost": 50.0, "boosting": False,
                   "jumping": False, "double_jumping": False, "dodging": False, **fn(t)}
            rows.append(row)
    players = pd.DataFrame(rows)
    pickups = pd.DataFrame(columns=["frame", "time", "player", "team", "x", "y", "big"])
    return GameFrames(frames=frames, ball=b, players=players, pickups=pickups)


@pytest.fixture
def game_factory():
    return make_game
