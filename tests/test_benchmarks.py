import pandas as pd
import pytest

import benchmarks

STATS = {
    "Gold": {"touches_per_min": [4, 5, 6, 7, 8], "pct_zero_boost": [5, 8, 10, 14, 20]},
    "Diamond": {"touches_per_min": [6, 7, 8, 9, 10], "pct_zero_boost": [3, 5, 7, 9, 12]},
}


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    data = {"modes": {"2v2": {b: {"n": 40, "stats": s} for b, s in STATS.items()}}}
    monkeypatch.setattr(benchmarks, "_DATA", data)


def test_percentile_interpolates_between_quantiles():
    assert benchmarks.percentile("2v2", "Gold", "touches_per_min", 6) == 50
    assert benchmarks.percentile("2v2", "Gold", "touches_per_min", 6.5) == pytest.approx(62.5)


def test_percentile_is_clamped_at_the_ends():
    assert benchmarks.percentile("2v2", "Gold", "touches_per_min", 100) == 95
    assert benchmarks.percentile("2v2", "Gold", "touches_per_min", 0) == 5


def test_percentile_flipped_for_lower_is_better():
    assert benchmarks.percentile("2v2", "Gold", "pct_zero_boost", 10) == 50
    assert benchmarks.percentile("2v2", "Gold", "pct_zero_boost", 5) == 90     # low zero-boost time is good


def test_percentile_unknown_returns_none():
    assert benchmarks.percentile("2v2", "Gold", "nope", 1) is None
    assert benchmarks.percentile("3v3", "Gold", "touches_per_min", 1) is None
    assert benchmarks.percentile("2v2", "Gold", "touches_per_min", float("nan")) is None


def test_closest_band_uses_nearest_median():
    assert benchmarks.closest_band("2v2", "touches_per_min", 7.9) == "Diamond"
    assert benchmarks.closest_band("2v2", "touches_per_min", 6.2) == "Gold"


def test_profile_lists_weaknesses_weakest_first():
    games = pd.DataFrame({"touches_per_min": [4.0, 4.0], "pct_zero_boost": [10.0, 10.0]})
    prof = benchmarks.profile(games, "2v2", "Gold", [("touches_per_min", "Touches/min", "{:.1f}"),
                                                     ("pct_zero_boost", "% at 0", "{:.1f}")])
    assert prof["weaknesses"][0] == "touches_per_min"
    assert prof["strengths"][0] == "pct_zero_boost"


def test_profile_none_without_data():
    assert benchmarks.profile(pd.DataFrame({"touches_per_min": [4.0]}), "1v1", "Gold", []) is None
