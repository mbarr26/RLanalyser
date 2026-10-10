from datetime import datetime, timedelta

import pandas as pd
import pytest

import benchmarks
import goals


@pytest.fixture
def no_benchmarks(monkeypatch):
    monkeypatch.setattr(benchmarks, "_DATA", {})


@pytest.fixture
def fake_benchmarks(monkeypatch):
    stats = {"clears": [1, 2, 3, 4, 5], "pct_zero_boost": [5, 8, 10, 14, 20]}
    monkeypatch.setattr(benchmarks, "_DATA", {"modes": {"2v2": {"Gold": {"n": 50, "stats": stats}}}})


def games(**cols):
    n = len(next(iter(cols.values())))
    start = datetime(2026, 10, 1)
    return pd.DataFrame({"played": [start + timedelta(hours=i) for i in range(n)], "mode": "2v2", **cols})


def test_target_halfway_to_median_when_median_is_better():
    assert goals.target_for("clears", 2.0, median=4.0) == 3.0
    assert goals.target_for("pct_zero_boost", 20.0, median=10.0) == 15.0


def test_target_ten_percent_when_already_beating_median():
    assert goals.target_for("clears", 5.0, median=3.0) == 5.5
    assert goals.target_for("pct_zero_boost", 10.0) == 9.0


def test_reached_respects_direction():
    assert goals.reached("clears", 3, 3) and not goals.reached("clears", 2.9, 3)
    assert goals.reached("pct_zero_boost", 9, 9) and not goals.reached("pct_zero_boost", 9.1, 9)


def test_suggestions_pick_weakest_for_rank(fake_benchmarks):
    g = games(clears=[1.0] * 6, pct_zero_boost=[10.0] * 6)       # clears: ~p10, boost: median
    out = goals.suggestions(g, "2v2", "Gold")
    assert out[0]["stat"] == "clears"
    assert out[0]["target"] == 2.0                                 # halfway from 1 to median 3


def test_suggestions_skip_taken_and_cap_at_two(fake_benchmarks):
    g = games(clears=[1.0] * 6, pct_zero_boost=[18.0] * 6)
    assert [s["stat"] for s in goals.suggestions(g, "2v2", "Gold", taken=("clears",))] == ["pct_zero_boost"]
    assert len(goals.suggestions(g, "2v2", "Gold")) <= goals.MAX_GOALS


def test_suggestions_without_rank_need_five_games(no_benchmarks):
    assert goals.suggestions(games(clears=[1.0, 2.0, 3.0]), "2v2", None) == []


def test_progress_met_needs_min_games():
    start = datetime(2026, 10, 1, 12)
    goal = goals.new_goal("clears", 2.0, 3.0, now=start, mode="2v2")
    g = games(clears=[5.0, 5.0, 5.0, 5.0])
    g["played"] = [start + timedelta(hours=i + 1) for i in range(4)]
    assert goals.progress(goal, g.iloc[:2], now=start + timedelta(days=1))["status"] == "active"
    assert goals.progress(goal, g.iloc[:3], now=start + timedelta(days=1))["status"] == "met"


def test_progress_expires_after_a_week():
    start = datetime(2026, 10, 1, 12)
    goal = goals.new_goal("clears", 2.0, 3.0, now=start)
    g = games(clears=[0.0])
    g["played"] = [start + timedelta(hours=1)]
    assert goals.progress(goal, g, now=start + timedelta(days=8))["status"] == "expired"


def test_progress_ignores_games_before_the_goal_and_other_modes():
    start = datetime(2026, 10, 1, 12)
    goal = goals.new_goal("clears", 2.0, 3.0, now=start, mode="2v2")
    g = games(clears=[9.0, 9.0, 9.0, 9.0])
    g["played"] = [start - timedelta(hours=1), start + timedelta(hours=1), start + timedelta(hours=2), start + timedelta(hours=3)]
    g.loc[3, "mode"] = "3v3"
    assert goals.progress(goal, g, now=start + timedelta(days=1))["games"] == 2


def test_streak_counts_trailing_met_goals():
    assert goals.streak([{"met": False}, {"met": True}, {"met": True}]) == 2
    assert goals.streak([{"met": True}, {"met": False}]) == 0
    assert goals.streak([]) == 0


def test_met_in_game_skips_missing_values():
    out = goals.met_in_game([{"stat": "clears", "target": 3}, {"stat": "pct_behind_ball", "target": 50}],
                            {"clears": 4})
    assert out == [{"heading": "Clears", "met": True}]
