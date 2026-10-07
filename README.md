# RL Analyser

A Windows desktop app for your Rocket League replays: browse every match in your
replay folder, see detailed per-player stats, watch a top-down 2D playback, and
track how your own stats change over time. The window is a native app (via
pywebview) whose UI is an HTML/CSS/JS page — a clean, black-and-white design with
layered cards and soft shadows.

## Features

### Matches tab
- **Replay list** – every replay in the folder, newest first, with date, mode, map,
  score and whether *you* won or lost. Click one to open it. Rows stay grey until the
  replay has been fully analysed.
- **Scoreboard** – score, goals, assists, saves and shots for every player (you're
  marked "(you)"), plus the goal sequence with the running score.
- **Movement** – average speed, % supersonic / boost speed / slow, % on the ground /
  low air / high air.
- **Positioning** – % in defensive / middle / offensive third, % behind the ball,
  average distance to the ball, % closest / farthest from the ball on their team.
- **Boost** – average boost, boost used and collected, big/small pads, stolen big
  pads, % time at 0 and at 100 boost.
- **Match** – live play time, average ball speed, and how long the ball spent in each
  half and third.
- **Watch match** – opens a top-down pitch viewer that replays every car and the ball
  moving in real time, with play/pause, seek, speed control and a "skip goal
  replays" toggle.

### My progress tab
- **Player picker** – defaults to you. Choose anyone you've played with to view their
  stats; **This is me** saves that player as you.
- **Mode filter** – All, 1v1, 2v2, 3v3...
- **Record** – games played, wins, losses, win rate.
- **Averages table** – every stat averaged over all games, your last 10 games, wins
  only and losses only, so you can see what changes when you win.
- **Trend chart** – click any stat in the table to chart it game by game (dots) with a
  5-game rolling average (line). Hover a dot for that game's details.
- **Games list** – your games with the key stats; double-click one to open it in the
  Matches tab.

### AI Coach (sub-tab of a match)
- **Findings** – short rule-based notes about *you* in this game, compared with your usual
  averages ("you were ahead of the ball on 2 of the 3 goals you conceded"). No AI needed.
- **Key moments** – goals (with where the defenders were 3 seconds earlier), "nobody
  back" spells, double commits and long stretches out of boost, each with the game clock.
  **Watch** opens the replay viewer a few seconds before that moment. No AI needed.
- **AI analysis** – a small language model that runs **on your own PC** (free, private,
  offline) reads those measured facts and writes a summary, strengths, things to improve,
  coaching advice per key moment and what to practise.
- **Ask the coach** – a chat about the match. Mention a game clock ("what went wrong at
  2:30?") or a goal ("the second goal") and the coach is given exactly where everyone was.
- **Python measures, the AI explains.** All times, positions and boost numbers come from
  the replay data (`moments.py`), never from the model, so the AI can't invent them.
- **First use:** the tab offers a one-off model download (Lite ≈ 2.7 GB for most laptops,
  Standard ≈ 5.7 GB for 8 GB+ graphics cards). It is saved in `%LOCALAPPDATA%\RLAnalyser\models`
  and checked against a pinned SHA-256. Reports are cached in `cache/*.coach.json`.

### How "you" are identified
Players are tracked by account ID (Epic account ID, or PlayStation/Xbox/Switch/Steam ID),
not by name, so stats follow you across name changes. Until you press **This is me**,
the app guesses: some replays record who saved them, otherwise it picks whoever
played the most games.

### Speed and caching
Each replay is analysed once (about 1 second) in the background and the results are
saved in `cache/`, so after the first run everything opens instantly. The list fills in
first from the quick header data, then frame stats are worked out replay by replay.
Opening a replay that hasn't been analysed yet jumps it to the front.

Frame-based stats only count live play (kickoffs included, replays/goal celebrations
excluded).

## How it works

The Python side does all the replay parsing, analysis and caching, exactly as
before. The window itself is a [pywebview](https://pywebview.flowrx.dev/) native
window showing `ui/index.html`; Python and the page talk to each other in both
directions:

- **Page → Python**: the page calls `window.pywebview.api.*` (the `Api` class in
  `rl_analyser.py`) to choose a folder, refresh, request a replay's frame stats,
  fetch a player's progress, or load a match's playback track.
- **AI engine**: `coach.py` starts the bundled llama.cpp server (`tools/llama-server/`)
  as a hidden process on a random localhost port (protected by a random key) the first
  time the coach is used, talks to its OpenAI-style HTTP API, and stops it when the app
  closes. Its log is `%LOCALAPPDATA%\RLAnalyser\llama-server.log`.
- **Python → page**: background threads (scanning the folder, analysing a replay)
  push results to the page with `window.evaluate_js`, calling methods on the page's
  `window.app` object as they complete — the same one-way flow the previous Tkinter
  version used with its message queue, just targeting a page instead of widgets.

| File | Purpose |
|------|---------|
| `rl_analyser.py` | Native window + `Api`: hosts the page, runs the background scan/analysis threads, and exposes the methods the page calls into. |
| `ui/index.html` | Page structure: the Matches and My progress tabs, and the Watch match overlay. |
| `ui/styles.css` | The design system — monochrome palette, shadows, cards, typography. |
| `ui/app.js` | Page controller: renders every table/list, talks to `pywebview.api`, and handles the pushes from Python (`window.app.*`). |
| `ui/coach.js` | The AI Coach tab: findings, key-moment cards, model download, AI report and chat. |
| `ui/chart.js` | Canvas-drawn trend chart (per-game dots + rolling average, with hover). |
| `ui/pitch.js` | Canvas-drawn "Watch match" viewer: playback, pitch geometry, cars and ball. |
| `replay_library.py` | Lists replays in a folder, analyses them (`analyse`), caches results as JSON in `cache/`, and `LibraryScanner` (background thread that loads/analyses a whole folder). |
| `replay_parser.py` | Runs `tools/rrrocket.exe` on a replay and turns the header into a `ReplaySummary` (scores, players with stable `player_id`, goals, who recorded it). |
| `frame_data.py` | Runs rrrocket with `--network-parse` and converts the network frames into pandas tables: `frames`, `ball`, `players`, `pickups` (`GameFrames`). |
| `analysis.py` | Computes per-player stats (`player_stats`) and match stats (`team_stats`) from `GameFrames`. `STAT_GROUPS` defines which stats appear in which tab (sent to the page so it can build the tables generically). |
| `progress.py` | Cross-replay stats for one player: `player_games` (one row per game), `comparison` (all / last 10 / wins / losses averages), `known_players`, `guess_me`. |
| `pitch_viewer.py` | `build_track`: turns a match's frame data into the JSON-serialisable track `ui/pitch.js` plays back. |
| `moments.py` | Rule-based key-moment detection (`detect_moments`) and findings about a player (`insights`). Pure measurement, no AI. |
| `coach.py` | The AI layer: model download, llama.cpp server management, the match "dossier" given to the model, report generation, and chat. Also a CLI: `python coach.py match.replay --me "Name"`. |
| `paths.py` | Where files live: `bundled()` for shipped files, `user_data()` for config/cache, `models_dir()` for AI models. Works from source and from a packaged build. |
| `tools/rrrocket.exe` | Third-party [rrrocket](https://github.com/nickbabcock/rrrocket) replay decoder used by the parsers (MIT, see `tools/LICENSE-rrrocket`). |
| `tools/llama-server/` | Third-party [llama.cpp](https://github.com/ggml-org/llama.cpp) server (build b11435, Windows Vulkan: NVIDIA/AMD/Intel GPUs with CPU fallback; MIT, see `LICENSE-llama.cpp`). Runs the AI model. |
| `config.json` | Local settings: replay folder and which player is you. Not committed to git. |
| `cache/` | Per-replay analysis results. Safe to delete (it's rebuilt). Not committed to git. |

**If you change how stats are calculated**, bump `CACHE_VERSION` in
`replay_library.py` so every replay is re-analysed with the new code.

Coordinates are Unreal units: blue (team 0) defends the −y goal, orange (team 1) the +y
goal; the pitch is x ∈ [−4096, 4096], y ∈ [−5120, 5120].

## Known issues

- Replays from a brand-new Rocket League update can fail frame analysis until rrrocket
  learns the new replay data (the Season 24 update added `TAGame.PRI_TA:PlayerStatus`,
  which rrrocket v0.11.5 couldn't decode). Their scoreboard still shows; frame stats
  appear as "-" and Watch match is disabled.
- **Current status:** `tools/rrrocket.exe` is v0.11.6 (released 28 Sept 2026, includes
  [boxcars PR #296](https://github.com/nickbabcock/boxcars/pull/296) Season 24 support).
- **Upgrading rrrocket in future:** download the `x86_64-pc-windows-msvc` zip from the
  [rrrocket releases](https://github.com/nickbabcock/rrrocket/releases), drop its
  `rrrocket.exe` into `tools/`, then press Refresh. A changed rrrocket.exe automatically
  invalidates the cache, so every replay is re-analysed. The exe is committed to git, so
  commit and push it after upgrading.
- The AI coach has only been tested against a synthetic match so far (no real replays were
  available during development): the Lite model's report and chat both worked end to end. The
  key-moment rules are first-draft thresholds (constants at the top of `moments.py`) that need
  tuning against real games.
- On a PC without a usable GPU the model runs on the CPU: about 7 words/second on a 10-thread
  CPU, so the AI analysis takes around 2 minutes and chat answers about a minute. The findings and
  key moments are instant either way. The Lite model sometimes pads its strengths or misreads a
  stat; Standard is better but needs a stronger PC.

## AI models and packaging

- **Models** are Qwen3.5 (Apache-2.0) GGUF files from Hugging Face, defined in `TIERS` in
  `coach.py`. To change or upgrade one, edit that entry (repo, file, size, SHA-256) and bump
  `COACH_VERSION` so saved reports are rewritten.
- **Packaging roadmap:** the code is ready to be built into a single installed app
  (PyInstaller + an installer). Still to do for a public release: build that installer,
  code-sign it, and add an auto-updater. The model is downloaded by each user on first use, so
  the installer itself stays small.

## Requirements

- Windows (rrrocket is bundled as a Windows `.exe`; the window uses the Edge WebView2
  runtime, which ships with Windows 11 / is auto-installed on Windows 10)
- Python 3.10+
- `pandas`, `numpy` and `pywebview` (`pip install pandas numpy pywebview`); no other
  UI toolkit needed

## Running

```
python rl_analyser.py
```

Quick command-line check of a single replay:

```
python replay_parser.py path\to\match.replay
```
