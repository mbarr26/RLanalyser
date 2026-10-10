import coach


def m(kind, team):
    return {"type": kind, "team": team}


def test_goal_labels_follow_the_players_team():
    assert coach.moment_label(m("goal", 0), 0) == "YOUR TEAM SCORED"
    assert coach.moment_label(m("goal", 1), 0) == "YOUR TEAM CONCEDED"


def test_mistakes_and_good_plays_are_labelled():
    assert coach.moment_label(m("last_man_beaten", 0), 0) == "MISTAKE BY YOUR TEAM"
    assert coach.moment_label(m("nobody_back", 1), 0) == "MISTAKE BY THE OPPONENTS"
    assert coach.moment_label(m("aerial_goal", 0), 0) == "GOOD PLAY BY YOUR TEAM"
    assert coach.moment_label(m("clear", 1), 0) == "GOOD PLAY BY THE OPPONENTS"
