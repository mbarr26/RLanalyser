# RL Analyser

A Windows desktop app (Python + Tkinter) that loads your most recent Rocket League
replay and shows the scoreboard, detailed per-player stats, and a top-down 2D playback
of the match.

## Features

- **Auto-finds your replays.** Looks in the usual Rocket League folders
  (`Documents\My Games\Rocket League\TAGame\DemosEpic` or `Demos`, including OneDrive
  Documents). You can pick a different folder; your choice is saved to `config.json`.
- **Scoreboard tab** – score, goals, assists, saves and shots for every player, plus the
  goal sequence with the running score.
- **Movement tab** – average speed, % supersonic / boost speed / slow, % on the ground /
  low air / high air.
- **Positioning tab** – % in defensive / middle / offensive third, % behind the ball,
  average distance to the ball, % closest / farthest from the ball on their team.
- **Boost tab** – average boost, boost used and collected, big/small pads, stolen big
  pads, % time at 0 and at 100 boost.
- **Match tab** – live play time, average ball speed, and how long the ball spent in each
  half and third.
- **Watch match** – opens a top-down pitch viewer that replays every car and the ball
  moving in real time.

Frame-based stats only count live play (kickoffs included, replays/goal celebrations
excluded).

## How it works

| File | Purpose |
|------|---------|
| `rl_analyser.py` | Main app / entry point. The Tkinter window, folder picking, tabs, and background analysis thread. |
| `replay_parser.py` | Runs `tools/rrrocket.exe` on a replay and turns the header into a `ReplaySummary` (scores, players, goals). |
| `frame_data.py` | Runs rrrocket with `--network-parse` and converts the network frames into pandas tables: `frames`, `ball`, `players`, `pickups` (`GameFrames`). |
| `analysis.py` | Computes per-player stats (`player_stats`) and match stats (`team_stats`) from `GameFrames`. `STAT_GROUPS` defines which stats appear in which tab. |
| `pitch_viewer.py` | `PitchViewer` window: 2D top-down playback of the match. |
| `tools/rrrocket.exe` | Third-party [rrrocket](https://github.com/nickbabcock/rrrocket) replay decoder used by the parsers. |
| `config.json` | Local settings (saved replay folder). Not committed to git. |

Coordinates are Unreal units: blue (team 0) defends the −y goal, orange (team 1) the +y
goal; the pitch is x ∈ [−4096, 4096], y ∈ [−5120, 5120].

## Requirements

- Windows (rrrocket is bundled as a Windows `.exe`)
- Python 3.10+
- `pandas` and `numpy` (`pip install pandas numpy`); Tkinter ships with Python

## Running

```
python rl_analyser.py
```

Quick command-line check of a single replay:

```
python replay_parser.py path\to\match.replay
```
