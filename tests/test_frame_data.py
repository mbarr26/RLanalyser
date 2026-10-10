import pandas as pd

from frame_data import GameFrames, restore_censored_names


def game(players, pickups=()):
    p = pd.DataFrame([{"player": n, "team": t} for n, t in players])
    k = pd.DataFrame([{"player": n, "team": t} for n, t in pickups], columns=["player", "team"])
    return GameFrames(frames=pd.DataFrame(), ball=pd.DataFrame(), players=p, pickups=k)


def header(*names):
    return [{"Name": n, "Team": t} for n, t in names]


def test_single_censored_name_is_restored_everywhere():
    g = game([("******", 1), ("A", 1), ("B", 0)], pickups=[("******", 1)])
    renames = restore_censored_names(g, header(("oh4fuk", 1), ("A", 1), ("B", 0)))
    assert renames == {"******": "oh4fuk"}
    assert set(g.players.player) == {"oh4fuk", "A", "B"}
    assert list(g.pickups.player) == ["oh4fuk"]


def test_one_censored_name_per_team():
    g = game([("******", 0), ("******", 1)])
    restore_censored_names(g, header(("x", 0), ("y", 1)))
    assert sorted(g.players.player) == ["x", "y"]


def test_ambiguous_censored_names_are_left_alone():
    g = game([("******", 1), ("******", 1)])
    assert restore_censored_names(g, header(("x", 1), ("y", 1))) == {}
    assert set(g.players.player) == {"******"}


def test_matching_names_untouched():
    g = game([("A", 0), ("B", 1)])
    assert restore_censored_names(g, header(("A", 0), ("B", 1))) == {}
