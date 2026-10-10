import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev_tools"))

import validate  # noqa: E402


def detail():
    return {"blue": {"players": [{"name": "A", "stats": {"movement": {"avg_speed": 1400.0},
                                                         "boost": {"count_stolen_big": 2}}}]},
            "orange": {"players": [{"name": "B", "stats": {"movement": {"avg_speed": 1500.0}}}]}}


def test_pairs_match_by_team_and_name():
    ours = {"A": {"team": 0, "avg_speed": 1380.0, "stolen_big_pads": 2},
            "B": {"team": 0, "avg_speed": 1500.0},        # wrong team: not matched
            "C": {"team": 1, "avg_speed": 1}}
    rows = validate.pairs_for_replay(detail(), ours)
    assert sorted(rows) == [("A", "avg_speed", 1380.0, 1400.0), ("A", "stolen_big_pads", 2.0, 2.0)]


def test_pairs_skip_missing_and_nan():
    assert validate.pairs_for_replay(detail(), {"A": {"team": 0, "avg_speed": float("nan")}}) == []


def test_summary_correlation_bias_and_worst():
    samples = [("r", f"p{i}", "avg_speed", 1000.0 + i * 100 + 10, 1000.0 + i * 100) for i in range(5)]
    s = validate.summarise(samples)["avg_speed"]
    assert s["n"] == 5 and s["r"] > 0.999 and abs(s["bias"] - 10) < 1e-9 and abs(s["mae"] - 10) < 1e-9


def test_summary_correlation_undefined_when_constant_or_tiny():
    assert validate.summarise([("r", "a", "x", 1.0, 2.0)])["x"]["r"] is None
    flat = [("r", str(i), "x", 5.0, float(i)) for i in range(4)]
    assert validate.summarise(flat)["x"]["r"] is None


def test_goal_scorer_check():
    touches = pd.DataFrame({"time": [1.0, 2.0, 5.0], "player": ["A", "B", "A"]})
    assert validate.goal_scorer_check(touches, [("A", 5.5), ("B", 2.5), ("A", 2.5)]) == (2, 3)
    assert validate.goal_scorer_check(touches, [("A", 0.5)]) == (0, 1)


def test_shots_saves_check_flags_players_with_too_few_touches():
    touches = pd.DataFrame({"player": ["A", "A", "A", "B"]})
    players = [type("P", (), {"name": "A", "shots": 2, "saves": 1})(),
               type("P", (), {"name": "B", "shots": 3, "saves": 0})()]
    ok, total, flagged = validate.shots_saves_check(touches, players)
    assert (ok, total) == (1, 2) and "B" in flagged[0]


def test_monotonic_check_reports_dips():
    def t(*medians):
        return {b: {"stats": {"avg_speed": [0, 0, m, 0, 0]}} for b, m in zip(("Bronze", "Silver", "Gold"), medians)}
    assert validate.monotonic_check({"2v2": t(1000, 1100, 1050)}, stats=["avg_speed"]) == \
        [("2v2", "avg_speed", ["Silver->Gold"])]
    assert validate.monotonic_check({"2v2": t(1, 2, 3)}, stats=["avg_speed"]) == []


def test_report_renders():
    summary = validate.summarise([("r", f"p{i}", "avg_speed", 1000.0 + i, 1000.0 + 2 * i) for i in range(5)])
    text = validate.fmt_report(summary, (26, 34), (7, 8, ["B (1 touches, 3 shots + 0 saves)"]),
                               {"n": 8, "bad": 0, "median": 7.5}, 2)
    assert "26/34" in text and "avg_speed" in text and "7.5" in text
