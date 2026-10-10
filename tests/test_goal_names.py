from replay_parser import Goal, PlayerStats, resolve_goal_scorers


def player(name, team, goals):
    return PlayerStats(name, team, 0, goals, 0, 0, 0, "Epic", False, name)


def test_single_owed_teammate_gets_the_censored_goal():
    players = [player("oh4fuk", 1, 2), player("Ant", 1, 0), player("A", 0, 1)]
    goals = [Goal(10, "oh4fuk", 1), Goal(20, "******", 1), Goal(30, "A", 0)]
    resolve_goal_scorers(goals, players)
    assert [g.scorer for g in goals] == ["oh4fuk", "oh4fuk", "A"]


def test_partially_masked_name():
    players = [player("P Diddy6708", 0, 1), player("B", 0, 0)]
    goals = [Goal(10, "P *********", 0)]
    resolve_goal_scorers(goals, players)
    assert goals[0].scorer == "P Diddy6708"


def test_ambiguous_goal_is_left_alone():
    players = [player("X", 0, 1), player("Y", 0, 1)]
    goals = [Goal(10, "******", 0)]
    resolve_goal_scorers(goals, players)
    assert goals[0].scorer == "******"


def test_known_scorers_untouched():
    players = [player("X", 0, 1)]
    goals = [Goal(10, "X", 0)]
    resolve_goal_scorers(goals, players)
    assert goals[0].scorer == "X"
