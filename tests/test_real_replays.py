"""Sanity checks on real replays. Skipped when none are available (replays aren't committed).

Set RLA_TEST_REPLAYS to a folder of .replay files, or it falls back to the folder saved in config.json.
These check invariants that must hold for any real match, not exact numbers, so threshold tuning
doesn't break them unless it makes the output implausible.
"""

import json
import os
from pathlib import Path

import pytest

from analysis import player_stats
from frame_data import load_game_frames
from paths import user_data
from replay_parser import parse_replay


def replay_files(limit=3):
    folder = os.environ.get("RLA_TEST_REPLAYS")
    if not folder:
        try:
            folder = json.loads(Path("config.json").read_text()).get("replay_dir")
        except (OSError, ValueError):
            folder = None
    if not folder or not Path(folder).is_dir():
        return []
    return sorted(Path(folder).glob("*.replay"))[:limit]


FILES = replay_files()
pytestmark = pytest.mark.skipif(not FILES, reason="no real replays available")


@pytest.fixture(scope="module", params=FILES, ids=lambda p: p.name[:8])
def analysed(request):
    summary = parse_replay(request.param)
    game = load_game_frames(request.param)
    return summary, player_stats(game)


def test_touch_rate_is_plausible(analysed):
    _, stats = analysed
    assert stats.touches_per_min.between(0.5, 20).all()


def test_percentages_stay_in_range(analysed):
    _, stats = analysed
    for col in ("pct_supersonic", "pct_zero_boost", "pct_behind_ball", "pct_possession"):
        assert stats[col].between(0, 100).all(), col


def test_thirds_add_up(analysed):
    _, stats = analysed
    total = stats.pct_def_third + stats.pct_mid_third + stats.pct_off_third
    assert ((total - 100).abs() < 1).all()


def test_header_players_all_have_frame_stats(analysed):
    summary, stats = analysed
    assert {p.name for p in summary.players if not p.is_bot} <= set(stats.index)
