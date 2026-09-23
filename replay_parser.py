"""Decode Rocket League .replay files using the rrrocket command-line tool."""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RRROCKET_PATH = Path(__file__).with_name("tools") / "rrrocket.exe"


class ReplayParseError(Exception):
    pass


@dataclass
class PlayerStats:
    name: str
    team: int
    score: int
    goals: int
    assists: int
    saves: int
    shots: int
    platform: str
    is_bot: bool


@dataclass
class Goal:
    frame: int
    scorer: str
    team: int


@dataclass
class ReplaySummary:
    name: str
    map_name: str
    match_type: str
    date: str
    team_size: int
    team0_score: int
    team1_score: int
    seconds_played: float
    players: list[PlayerStats] = field(default_factory=list)
    goals: list[Goal] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    def team(self, team):
        """Players on a team (0 = blue, 1 = orange), highest score first."""
        return sorted((p for p in self.players if p.team == team), key=lambda p: -p.score)


def decode_replay(replay_path, network_parse=False):
    """Run rrrocket on a replay and return its decoded JSON as a dict.

    Header-only parsing is fast and includes scores and player stats. Pass
    network_parse=True for frame-by-frame data (positions, boost, etc.),
    which is much slower and produces a very large result.
    """
    if not RRROCKET_PATH.is_file():
        raise ReplayParseError(f"rrrocket not found at {RRROCKET_PATH}")

    args = [str(RRROCKET_PATH)]
    if network_parse:
        args.append("--network-parse")
    args.append(str(replay_path))

    result = subprocess.run(
        args,
        capture_output=True,
        encoding="utf-8",
        # Don't flash a console window when run from the GUI
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if result.returncode != 0:
        raise ReplayParseError(result.stderr.strip() or "rrrocket failed to parse the replay")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ReplayParseError(f"rrrocket returned invalid JSON: {e}") from e


def _platform_name(value):
    # e.g. {"kind": "OnlinePlatform", "value": "OnlinePlatform_Epic"} -> "Epic"
    if isinstance(value, dict):
        value = value.get("value", "")
    return str(value).replace("OnlinePlatform_", "") or "Unknown"


def parse_replay(replay_path):
    """Decode a replay's header into a ReplaySummary."""
    data = decode_replay(replay_path)
    props = data.get("properties", {})

    players = [
        PlayerStats(
            name=p.get("Name", "?"),
            team=p.get("Team", 0),
            score=p.get("Score", 0),
            goals=p.get("Goals", 0),
            assists=p.get("Assists", 0),
            saves=p.get("Saves", 0),
            shots=p.get("Shots", 0),
            platform=_platform_name(p.get("Platform")),
            is_bot=p.get("bBot", False),
        )
        for p in props.get("PlayerStats", [])
    ]

    goals = [
        Goal(frame=g.get("frame", 0), scorer=g.get("PlayerName", "?"), team=g.get("PlayerTeam", 0))
        for g in props.get("Goals", [])
    ]

    return ReplaySummary(
        name=props.get("ReplayName", Path(replay_path).stem),
        map_name=props.get("MapName", "?"),
        match_type=props.get("MatchType", "?"),
        date=props.get("Date", "?"),
        team_size=props.get("TeamSize", 0),
        team0_score=props.get("Team0Score", 0),
        team1_score=props.get("Team1Score", 0),
        seconds_played=props.get("TotalSecondsPlayed", 0.0),
        players=players,
        goals=goals,
        raw=data,
    )


if __name__ == "__main__":
    # Quick check from the command line: python replay_parser.py some.replay
    summary = parse_replay(sys.argv[1])
    print(f"{summary.name}  |  {summary.map_name}  |  {summary.match_type}  |  {summary.date}")
    print(f"Blue {summary.team0_score} - {summary.team1_score} Orange")
    for team, label in ((0, "Blue"), (1, "Orange")):
        print(f"\n{label}:")
        for p in summary.team(team):
            print(f"  {p.name:<20} score {p.score:>4}  G {p.goals}  A {p.assists}  Sv {p.saves}  Sh {p.shots}")
