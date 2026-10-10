"""Turn rrrocket's network frames into per-frame tables for the ball and every player.

Coordinates are Unreal units (uu). Blue (team 0) defends the -y goal, orange
(team 1) defends +y. The standard pitch is x in [-4096, 4096], y in [-5120, 5120].
"""

import math
from dataclasses import dataclass

import pandas as pd

from replay_parser import decode_replay

GROUND_HEIGHT = 20               # a car resting on the floor sits at z ~17
GOAL_HEIGHT = 642                # crossbar height; above this counts as "high air"
PITCH_HALF_LENGTH = 5120
THIRD_LINE = PITCH_HALF_LENGTH / 3   # thirds split at y = +/-1707

BOOST_MAX_RAW = 255              # replicated boost is 0-255; displayed as 0-100
BOOST_DRAIN_PER_SEC = 255 / 3    # a full tank lasts 3 seconds of boosting

# Big boost pad locations on standard soccar maps (x, y)
BIG_PADS = [(-3584, 0), (3584, 0), (-3072, 4096), (3072, 4096), (-3072, -4096), (3072, -4096)]
BIG_PAD_RADIUS = 400


@dataclass
class GameFrames:
    frames: pd.DataFrame    # one row per network frame: time, duration, game state, kickoff, clock
    ball: pd.DataFrame      # one row per frame the ball exists: position + velocity
    players: pd.DataFrame   # one row per frame per player with a car: position, velocity, boost
    pickups: pd.DataFrame   # one row per boost pad pickup


def _vec(v):
    return (v["x"], v["y"], v["z"]) if v else (0.0, 0.0, 0.0)


def _is_big_pad(x, y):
    return any(math.hypot(x - px, y - py) < BIG_PAD_RADIUS for px, py in BIG_PADS)


def extract_frames(decoded):
    """Build GameFrames from rrrocket JSON produced with network parsing on."""
    objects = decoded["objects"]
    names = decoded["names"]
    net_frames = decoded["network_frames"]["frames"]

    actor_type = {}      # actor id -> object name (what kind of actor it is)
    car_pri = {}         # car actor -> player (PRI) actor
    pri_name = {}        # PRI actor -> player name
    pri_team_actor = {}  # PRI actor -> team actor
    comp_car = {}        # car component actor (boost etc.) -> car actor
    rigid_body = {}      # actor -> latest RigidBody state
    boost_raw = {}       # boost component actor -> current boost (0-255)
    boost_active = {}    # boost component actor -> currently boosting
    move_active = {}     # jump / double jump / dodge component actor -> currently active
    pad_counter = {}     # boost pad actor -> last picked_up counter seen
    ball_actor = None
    hit_team = None      # team of the last car to touch the ball, as the game reports it
    state = ""
    seconds_remaining = None
    ball_hit = False     # False from each countdown until the kickoff touch

    frame_rows, ball_rows, player_rows, pickup_rows = [], [], [], []

    def team_of(pri):
        team_actor = pri_team_actor.get(pri)
        kind = actor_type.get(team_actor, "")
        if kind.endswith("Team0"):
            return 0
        if kind.endswith("Team1"):
            return 1
        return None

    def forget(actor):
        for d in (actor_type, car_pri, pri_name, pri_team_actor, comp_car,
                  rigid_body, boost_raw, boost_active, move_active, pad_counter):
            d.pop(actor, None)

    for i, frame in enumerate(net_frames):
        time = frame["time"]
        # How long this frame lasts = gap until the next frame
        duration = net_frames[i + 1]["time"] - time if i + 1 < len(net_frames) else 0.0

        for actor in frame["deleted_actors"]:
            if actor == ball_actor:
                ball_actor = None
            forget(actor)

        for new in frame["new_actors"]:
            actor, kind = new["actor_id"], objects[new["object_id"]]
            # Keyframes re-announce existing actors; only reset if the id was reused
            if actor_type.get(actor) not in (None, kind):
                forget(actor)
            actor_type[actor] = kind
            if kind.startswith("Archetypes.Ball."):
                ball_actor = actor

        for upd in frame["updated_actors"]:
            actor, attr_name, attr = upd["actor_id"], objects[upd["object_id"]], upd["attribute"]
            prop = attr_name.rsplit(":", 1)[-1]

            if prop == "ReplicatedRBState":
                rigid_body[actor] = attr["RigidBody"]
            elif prop == "PlayerReplicationInfo" and attr_name.startswith("Engine.Pawn"):
                car_pri[actor] = attr["ActiveActor"]["actor"]
            elif prop == "PlayerName":
                pri_name[actor] = attr["String"]
            elif prop == "Team" and attr_name.startswith("Engine.PlayerReplicationInfo"):
                pri_team_actor[actor] = attr["ActiveActor"]["actor"]
            elif prop == "Vehicle" and attr_name.startswith("TAGame.CarComponent_TA"):
                comp_car[actor] = attr["ActiveActor"]["actor"]
            elif prop == "ReplicatedBoost":
                boost_raw[actor] = attr["ReplicatedBoost"]["boost_amount"]
            elif prop == "ReplicatedActive":
                # Counter that increments on each toggle: odd = active
                kind = actor_type.get(actor, "")
                if "Boost" in kind:
                    boost_active[actor] = attr["Byte"] % 2 == 1
                elif "CarComponent_Jump" in kind or "CarComponent_DoubleJump" in kind or "CarComponent_Dodge" in kind:
                    move_active[actor] = attr["Byte"] % 2 == 1
            elif prop == "HitTeamNum":
                hit_team = attr.get("Byte")
            elif prop == "ReplicatedStateName":
                state = names[attr["Int"]]
                if state == "Countdown":
                    ball_hit = False
            elif prop == "bBallHasBeenHit":
                ball_hit = attr["Boolean"]
            elif prop == "SecondsRemaining":
                seconds_remaining = attr["Int"]
            elif prop == "NewReplicatedPickupData":
                data = attr["PickupNew"]
                car, counter = data["instigator"], data["picked_up"]
                # Counter 255 = pad respawned; repeated counters are keyframe resends
                if car is not None and counter != 255 and pad_counter.get(actor) != counter:
                    pri = car_pri.get(car)
                    loc = _vec(rigid_body.get(car, {}).get("location"))
                    pickup_rows.append((i, time, pri_name.get(pri), team_of(pri),
                                        loc[0], loc[1], _is_big_pad(loc[0], loc[1])))
                pad_counter[actor] = counter

        live = state == "Active"
        frame_rows.append((i, time, duration, state, live, live and not ball_hit, seconds_remaining))

        if ball_actor in rigid_body:
            rb = rigid_body[ball_actor]
            ball_rows.append((i, time, *_vec(rb["location"]), *_vec(rb.get("linear_velocity")), hit_team))

        boost_comp_of_car = {car: comp for comp, car in comp_car.items() if comp in boost_raw}
        moves_of_car = {}    # car -> {"jump": bool, "double_jump": bool, "dodge": bool}
        for comp, car in comp_car.items():
            kind = actor_type.get(comp, "")
            slot = ("double_jump" if "DoubleJump" in kind else "jump" if "Jump" in kind
                    else "dodge" if "Dodge" in kind else None)
            if slot and comp in move_active:
                moves_of_car.setdefault(car, {})[slot] = move_active[comp]
        for car, pri in car_pri.items():
            if car not in rigid_body or pri not in pri_name:
                continue
            rb = rigid_body[car]
            comp = boost_comp_of_car.get(car)
            boosting = boost_active.get(comp, False)
            if comp is not None and boosting:
                # The server only sends boost occasionally; drain it ourselves in between
                boost_raw[comp] = max(0.0, boost_raw[comp] - BOOST_DRAIN_PER_SEC * duration)
            boost = boost_raw.get(comp)
            vx, vy, vz = _vec(rb.get("linear_velocity"))
            rot = rb.get("rotation") or {}
            moves = moves_of_car.get(car, {})
            player_rows.append((
                i, time, pri_name[pri], team_of(pri),
                *_vec(rb["location"]), vx, vy, vz, math.sqrt(vx * vx + vy * vy + vz * vz),
                rot.get("x"), rot.get("y"), rot.get("z"), rot.get("w"),
                None if boost is None else boost / BOOST_MAX_RAW * 100, boosting,
                moves.get("jump", False), moves.get("double_jump", False), moves.get("dodge", False),
            ))

    game = GameFrames(
        frames=pd.DataFrame(frame_rows, columns=[
            "frame", "time", "duration", "state", "live", "kickoff", "seconds_remaining",
        ]),
        ball=pd.DataFrame(ball_rows, columns=["frame", "time", "x", "y", "z", "vx", "vy", "vz", "hit_team"]),
        players=pd.DataFrame(player_rows, columns=[
            "frame", "time", "player", "team", "x", "y", "z", "vx", "vy", "vz", "speed",
            "qx", "qy", "qz", "qw", "boost", "boosting", "jumping", "double_jumping", "dodging",
        ]),
        pickups=pd.DataFrame(pickup_rows, columns=["frame", "time", "player", "team", "x", "y", "big"]),
    )
    restore_censored_names(game, decoded.get("properties", {}).get("PlayerStats", []))
    return game


def restore_censored_names(game, header_players):
    """Give players the name the replay header has when the frame data masks it.

    Rocket League's profanity filter replicates some names as "******" in the network data while the
    header keeps the real one. Per team, when exactly one frame name and one header name are left
    unmatched they are the same player, so the frame name is replaced everywhere. More than one
    unmatched name on a team is ambiguous (which '******' is which?) and is left alone.
    """
    renames = {}
    for team in (0, 1):
        frame_names = set(game.players.loc[game.players.team == team, "player"])
        header_names = {p.get("Name") for p in header_players if p.get("Team", 0) == team and p.get("Name")}
        extra, missing = frame_names - header_names, header_names - frame_names
        if len(extra) == 1 and len(missing) == 1:
            renames[(team, extra.pop())] = missing.pop()
    for (team, old), new in renames.items():       # per team: both teams can have a "******"
        for table in (game.players, game.pickups):
            table.loc[(table.team == team) & (table.player == old), "player"] = new
    return {old: new for (_, old), new in renames.items()}


def load_game_frames(replay_path):
    """Decode a replay with full network data and extract its frame tables."""
    return extract_frames(decode_replay(replay_path, network_parse=True))
