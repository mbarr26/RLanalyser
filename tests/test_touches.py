import touches
from conftest import make_game


def still_ball(t):
    return {"x": 0, "y": 0, "z": 100}


def hit_ball(hit_at, z=100):
    """Stationary until hit_at, then moving towards +y at 1500."""
    def f(t):
        return {"x": 0, "y": 0 if t < hit_at else 1500 * (t - hit_at), "z": z,
                "vy": 0 if t < hit_at else 1500}
    return f


def car_at(x, y, z=17):
    return lambda t: {"x": x, "y": y, "z": z}


def test_touch_detected_for_nearby_car():
    game = make_game(2, hit_ball(1.0), {"A": (0, lambda t: {"x": 0, "y": -150 if t < 1 else -150 + 1500 * (t - 1) * .5, "z": 17})})
    ev = touches.find_events(game)
    assert len(ev.touches) == 1
    assert ev.touches.player.iloc[0] == "A"
    assert ev.touches.team.iloc[0] == 0


def test_no_touch_when_car_far_away():
    game = make_game(2, hit_ball(1.0), {"A": (0, car_at(3000, -3000))})
    assert touches.find_events(game).touches.empty


def test_aerial_touch_flagged():
    game = make_game(2, hit_ball(1.0, z=400), {"A": (0, car_at(0, -150, z=400))})
    t = touches.find_events(game).touches
    assert len(t) == 1 and bool(t.aerial.iloc[0]) and not bool(t.high_aerial.iloc[0])


def test_fifty_fifty_needs_opposing_touches_close_together():
    import pandas as pd
    t = pd.DataFrame({"frame": [10, 14], "time": [1.0, 1.13], "player": ["A", "B"], "team": [0, 1]})
    ball = pd.DataFrame({"time": [0.0, 1.13, 2.5], "y": [0, 0, 600]})
    result = touches.detect_fifty(t, ball)
    assert len(result) == 1 and result[0]["winner"] == 0      # ball went towards +y: blue attacks +y

    far = t.assign(time=[1.0, 2.0])
    assert touches.detect_fifty(far, ball) == []
    same_team = t.assign(team=[0, 0])
    assert touches.detect_fifty(same_team, ball) == []


def test_dribble_requires_one_second_of_carrying():
    def ball(t):
        return {"x": 0, "y": 0, "z": 17 + 150}
    cars = {"A": (0, car_at(0, 0, z=17))}
    ev = touches.find_events(make_game(3, ball, cars))
    assert "A" in ev.dribbles and ev.dribbles["A"][0]["seconds"] >= 1.0

    brief = touches.find_events(make_game(0.8, ball, cars))
    assert brief.dribbles == {}


def test_find_runs_ignores_short_stretches():
    import numpy as np
    import pandas as pd
    frames = pd.DataFrame({"frame": range(10), "time": np.arange(10) / 30, "duration": 1 / 30})
    mask = [False, True, True, False, True, True, True, True, True, False]
    runs = touches.find_runs(frames, mask, min_seconds=0.15)
    assert len(runs) == 1 and runs[0]["frame"] == 4 and runs[0]["last_frame"] == 8


def test_beaten_when_committed_player_loses_ball_heading_for_own_goal():
    # Blue A charges the ball at y=0 (toward +y); orange B hits it towards -y (blue's goal) at t=1.
    # A ends up ahead of the ball (own_y > ball_own_y) while it heads for A's goal.
    def ball(t):
        return {"x": 0, "y": 0 if t < 1 else -1500 * (t - 1), "z": 100, "vy": 0 if t < 1 else -1500}

    def a(t):    # blue, running up the pitch at 1400 uu/s, passing 400 uu to the side of the ball at t=1
        return {"x": 400, "y": -1400 * (1 - t), "z": 17, "vy": 1400}

    def b(t):    # orange, sitting right on the ball at the hit
        return {"x": 0, "y": 100, "z": 17}

    ev = touches.find_events(make_game(2, ball, {"A": (0, a), "B": (1, b)}))
    assert [e["player"] for e in ev.beaten] == ["A"]
    assert ev.beaten[0]["toucher"] == "B"


def test_not_beaten_if_ball_goes_the_other_way():
    def ball(t):
        return {"x": 0, "y": 0 if t < 1 else 1500 * (t - 1), "z": 100, "vy": 0 if t < 1 else 1500}

    def a(t):
        return {"x": 400, "y": -1400 * (1 - t), "z": 17, "vy": 1400}

    def b(t):
        return {"x": 0, "y": 100, "z": 17}

    assert touches.find_events(make_game(2, ball, {"A": (0, a), "B": (1, b)})).beaten == []
