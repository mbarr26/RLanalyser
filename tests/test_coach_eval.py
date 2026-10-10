import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev_tools"))

import coach_eval as ce  # noqa: E402

DOSSIER = "MATCH ... length 5:00. [m1] 2:30 Goal: A - boost 44, speed 1350, score 412. Possession 47.5"


def test_numbers_in_dossier_are_fine_and_small_ones_ignored():
    assert ce.invented_numbers(["You scored 3 goals with speed 1350 and boost 44."], DOSSIER) == []


def test_invented_numbers_are_caught():
    assert ce.invented_numbers(["Your speed was 1800 and possession 61.2%."], DOSSIER) == ["1800", "61.2"]


def test_clocks_must_be_in_dossier():
    assert ce.invented_clocks(["At 2:30 you were late, and at 4:10 too."], DOSSIER) == ["4:10"]


def test_check_flags_padding_and_shape():
    report = {"summary": "ok", "strengths": ["a", "b", "c"], "weaknesses": [], "key_moments": [], "focus_for_next_games": []}
    problems = ce.check(report, DOSSIER, [{"kind": "good"}])
    assert any("3 strengths" in p for p in problems)
    assert ce.check({"summary": ""}, DOSSIER, []) [0] == "empty summary"


def test_clean_report():
    report = {"summary": "Solid game, 2:30 goal.", "strengths": ["boost 44"], "weaknesses": [], "key_moments": [],
              "focus_for_next_games": []}
    assert ce.check(report, DOSSIER, [{"kind": "good"}]) == []
