"""What to practise for a weak stat: plain drills plus a few community training packs.

The pack codes were checked against the pages that publish them (ggrecon.com's training-code guide and
ginx.tv's defending-packs list) when this was written. They are community-made, so one may be removed
by its author later; the in-game Custom training browser can also be searched by the pack's name.
A pack whose code differed between two sources ("Uncomfortable Saves") is deliberately left out.
"""

SHADOW_DEFENCE = {"name": "[Why You Suck] Shadow Defense", "creator": "OrangePie", "code": "5CCE-FB29-7B05-A0B1"}
AERIAL_CONTROL = {"name": "Aerial Car Control", "creator": "Kevpert", "code": "A3E1-92C2-8757-4195"}
BASIC_MECHANICS = {"name": "Basic Mechanics Training", "creator": None, "code": "20DF-6522-E79F-D098"}
WARM_UP = {"name": "The Ultimate Warm Up", "creator": "Hinata", "code": "FA24-B2B7-2E8E-193B"}

# stat column -> {"title", "drills": [...], "packs": [...]}
TRAINING = {
    "pct_zero_boost": {
        "title": "Run out of boost less",
        "drills": ["In free play, collect every small pad on one side of the pitch as you rotate, instead of only the big ones.",
                   "Play a few games where you must never boost while the ball is far away; use it only for challenges and shots."],
        "packs": [],
    },
    "pct_behind_ball": {
        "title": "Stay behind the ball",
        "drills": ["After every touch in the opponent's half, rotate back before going for the next ball.",
                   "Shadow practice: stay between the ball and your goal while a friend (or the AI in free play) dribbles."],
        "packs": [SHADOW_DEFENCE],
    },
    "pct_shadowing": {
        "title": "Shadow defend better",
        "drills": ["Back off the attacker instead of challenging; stay a car-length or two behind the ball's path to your goal.",
                   "Aim to make them pass or shoot early, then clear the rebound."],
        "packs": [SHADOW_DEFENCE],
    },
    "times_beaten": {
        "title": "Stop being beaten to the ball",
        "drills": ["Only commit to a challenge when a teammate is back or you can reach the ball first; otherwise delay.",
                   "Practise 50/50s in free play: time your jump so you hit the ball with the front of the car."],
        "packs": [BASIC_MECHANICS],
    },
    "last_man_beaten": {
        "title": "Defend better as last man",
        "drills": ["As last man, hold your position and wait: let the attacker commit first, then challenge or save.",
                   "Practise recovering to goal with a half-flip after a lost challenge."],
        "packs": [SHADOW_DEFENCE],
    },
    "fifty_win_pct": {
        "title": "Win more 50/50s",
        "drills": ["Free play: roll the ball to midfield, race a bot to it, and practise a flip into the ball at the right height.",
                   "Choose to challenge with a purpose: block it, or poke it to a teammate."],
        "packs": [BASIC_MECHANICS],
    },
    "clears": {
        "title": "Clear the danger",
        "drills": ["Practise clearing to the corners or the sides, not straight back to the middle.",
                   "When the ball is above you in your third, aim to hit it up and out of play rather than to the other team."],
        "packs": [SHADOW_DEFENCE],
    },
    "high_aerials": {
        "title": "Take more high aerials",
        "drills": ["Practise fast aerials: jump, tilt back and boost at once, then double-jump to adjust.",
                   "Do ten aerials from different angles in free play before each session."],
        "packs": [AERIAL_CONTROL],
    },
    "aerial_touches": {
        "title": "Get airborne more",
        "drills": ["Practise reading the bounce so you can jump early; air control matters more than speed.",
                   "Do ten aerials from different angles in free play before each session."],
        "packs": [AERIAL_CONTROL],
    },
    "touches_per_min": {
        "title": "Be more involved",
        "drills": ["Be the one who takes the next ball whenever you're closest and have boost, then rotate out.",
                   "Look for small boost on your way to the ball, not only big pads."],
        "packs": [WARM_UP],
    },
}


def for_stat(stat):
    """Training advice for a stat column, or None if we have none."""
    return TRAINING.get(stat)


def drill_line(stat):
    """One line for the AI coach's notes: the first drill for a stat, or None."""
    entry = TRAINING.get(stat)
    return f"{entry['title']}: {entry['drills'][0]}" if entry else None
