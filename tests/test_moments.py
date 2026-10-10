from types import SimpleNamespace

import moments
from conftest import make_game
from replay_parser import Goal


def ball_in_blue_half(t):
    return {"x": 0, "y": -2000, "z": 100}


def stay(x, y, boost=50.0):
    return lambda t: {"x": x, "y": y, "z": 17, "boost": boost}


def summary(goals=()):
    return SimpleNamespace(goals=list(goals))


def test_clock_formatting():
    assert moments.fmt_clock(None) == ""
    assert moments.fmt_clock(65) == "1:05"
    assert moments.fmt_clock(0) == "0:00"


def test_nobody_back_when_whole_team_is_ahead_of_ball_in_own_half():
    cars = {"A": (0, stay(0, 1000)), "B": (0, stay(500, 1500)), "C": (1, stay(0, 3000))}
    found = moments.detect_moments(make_game(4, ball_in_blue_half, cars), summary())
    back = [m for m in found if m["type"] == "nobody_back"]
    assert len(back) == 1 and back[0]["team"] == 0 and back[0]["players"] == ["A", "B"]


def test_no_nobody_back_when_one_defender_is_behind_the_ball():
    cars = {"A": (0, stay(0, 1000)), "B": (0, stay(500, -4000)), "C": (1, stay(0, 3000))}
    found = moments.detect_moments(make_game(4, ball_in_blue_half, cars), summary())
    assert not [m for m in found if m["type"] == "nobody_back"]


def test_goal_moment_flags_defender_ahead_of_ball_and_low_boost():
    cars = {"A": (0, stay(0, 1000, boost=5)), "B": (1, stay(0, 3000))}
    game = make_game(4, ball_in_blue_half, cars)
    found = moments.detect_moments(game, summary([Goal(frame=100, scorer="B", team=1)]))
    goal = next(m for m in found if m["type"] == "goal")
    assert goal["team"] == 1 and goal["players"] == ["B"]
    assert "ahead of the ball" in goal["flags"]["A"]
    assert any(f.startswith("low on boost") for f in goal["flags"]["A"])


def test_merge_close_keeps_the_most_severe_of_repeats():
    a = {"type": "no_boost", "team": 0, "players": ["A"], "time": 10.0, "severity": 1.0}
    b = {"type": "no_boost", "team": 0, "players": ["A"], "time": 12.0, "severity": 5.0}
    c = {"type": "no_boost", "team": 0, "players": ["A"], "time": 30.0, "severity": 1.0}
    assert moments._merge_close([a, b, c]) == [b, c]


ME = {"team": 0, "pct_zero_boost": 20.0, "stolen_big_pads": 3, "fifty_fifties": 4, "fifty_win_pct": 25.0}


def test_insights_unknown_player_is_empty():
    assert moments.insights(summary(), {}, [], "Me") == []


def test_insights_report_boost_and_fifties():
    texts = [i["text"] for i in moments.insights(summary(), {"Me": ME}, [], "Me")]
    assert any("0 boost" in t for t in texts)
    assert any("stole 3 big boost pads" in t for t in texts)
    assert any("won 25% of your 4 50/50s" in t for t in texts)


def test_insights_compare_with_usual_only_beyond_margin():
    me = dict(ME, pct_behind_ball=40.0, pct_supersonic=10.0)
    usual = {"pct_behind_ball": 55.0, "pct_supersonic": 11.0}
    texts = [i["text"] for i in moments.insights(summary(), {"Me": me}, [], "Me", usual)]
    assert any("behind the ball: 40%" in t for t in texts)
    assert not any("supersonic" in t for t in texts)


def test_insights_conceded_while_ahead():
    goal = {"type": "goal", "team": 1, "flags": {"Me": ["ahead of the ball"]}, "players": ["B"]}
    texts = [i["text"] for i in moments.insights(summary(), {"Me": ME}, [goal], "Me")]
    assert "You were ahead of the ball on 1 of the 1 goals you conceded." in texts
