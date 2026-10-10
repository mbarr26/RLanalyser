from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import benchmarks
import postgame
from replay_parser import PlayerStats, ReplaySummary


def record(played, my_score, their_score, pid="me", players=None):
    me = PlayerStats("Me", 0, 300, 1, 0, 0, 2, "Epic", False, pid)
    them = PlayerStats("Them", 1, 200, 0, 0, 1, 1, "Epic", False, "other")
    s = ReplaySummary("m", "Map", "Ranked", "", 2, my_score, their_score, 300, [me, them], [])
    return SimpleNamespace(summary=s, path=f"{played:%H%M}", played_at=played, players=players or {})


NOW = datetime(2026, 10, 10, 22, 0)


def test_session_groups_games_less_than_30_minutes_apart():
    records = [record(NOW - timedelta(hours=5), 3, 1),                      # earlier sitting
               record(NOW - timedelta(minutes=50), 3, 1),
               record(NOW - timedelta(minutes=20), 1, 3)]
    s = postgame.current_session(records, "me", now=NOW)
    assert s["games"] == 2 and s["wins"] == 1 and s["losses"] == 1
    assert s["results"] == ["Win", "Loss"]


def test_session_gone_after_six_hours():
    assert postgame.current_session([record(NOW - timedelta(hours=7), 3, 1)], "me", now=NOW) is None


def test_session_none_for_stranger():
    assert postgame.current_session([record(NOW, 3, 1)], "nobody", now=NOW) is None


def test_tilt_after_three_losses_in_a_row():
    records = [record(NOW - timedelta(minutes=10 * (4 - i)), 0, 2) for i in range(3)]
    assert postgame.current_session(records, "me", now=NOW)["tilt"] is True
    records[-1] = record(NOW, 2, 0)
    assert postgame.current_session(records, "me", now=NOW)["tilt"] is False


def test_headline_stats_against_own_usual_without_rank():
    before = pd.DataFrame({"score": [300.0] * 4, "goals": [1.0] * 4, "saves": [1.0] * 4, "shots": [2.0] * 4})
    row = {"score": 600, "goals": 1, "saves": 1, "shots": 2}
    out = postgame.headline_stats(row, before, "2v2", None, count=1)
    assert out[0]["label"] == "Score" and out[0]["good"] is True


def test_headline_stats_nothing_to_compare_with():
    assert postgame.headline_stats({"score": 100}, None, "2v2", None) == []


def test_headline_stats_percentile_note_with_rank(monkeypatch):
    data = {"modes": {"2v2": {"Gold": {"n": 10, "stats": {"touches_per_min": [4, 5, 6, 7, 8]}}}}}
    monkeypatch.setattr(benchmarks, "_DATA", data)
    out = postgame.headline_stats({"touches_per_min": 7.0}, None, "2v2", "Gold")
    assert out[0]["note"] == "75th percentile for Gold"


@pytest.mark.parametrize("n,word", [(1, "st"), (2, "nd"), (3, "rd"), (4, "th"), (11, "th"), (12, "th"), (21, "st")])
def test_ordinal_suffix(n, word):
    assert postgame._ordinal(n) == word
