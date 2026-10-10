# RL Analyser

A Windows desktop app for your Rocket League replays. The home page shows how your
stats are trending with every replay as a tile; opening a replay plays the whole match
in 2D while a local AI coach analyses it and answers your questions. The window is a
native app (via pywebview) whose UI is an HTML/CSS/JS page — a dark design: near-black
layered surfaces, one electric-violet accent and soft glows. It ships as a Windows installer (see
[Building the installer](#building-the-installer)).

## Features

### Home
- **Your progress** (top) – your record (games, wins, losses, win rate) and six key stat
  cards showing your last 10 games against your all-time average (▲/▼ = better/worse than
  usual), with a trend chart. Click a card to chart that stat; filter by mode (1v1, 2v2...).
  **See all stats →** opens the full progress page.
- **Replay tiles** – every replay in the folder, newest first, as a clickable tile: score,
  win/loss edge, map, mode, date and your goals/assists/saves/shots. Tiles stay grey until
  the replay has been analysed. Click one to open the match screen.

- **Rank benchmarks** – pick **Your rank** (shown when one mode is selected) and every stat card shows
  where your last 10 games sit among players of that rank ("62nd pctl · plays like Gold"), with a line
  naming your weakest and strongest stat for your rank. The full progress page gets a rank-median
  and percentile column, and the AI coach is told how the game ranks so its advice is rank-relative.
  Needs `benchmarks.json` (see [Rank benchmarks](#rank-benchmarks)); without it the picker is hidden.

- **Welcome guide** – the first time the app runs (or from the title bar's **Setup guide**) it walks
  through: your replay folder (with a reminder to turn on Rocket League's **Auto-save replays** if the
  folder is empty), which player is you, your rank per mode (when `benchmarks.json` exists), and then
  "here's what we found": your biggest weaknesses for your rank, or findings from your latest game.
  Anyone who already had a folder or player saved skips it.
- **After every game** – the app watches the replay folder (checks every 5 s). When a match is saved it
  is analysed straight away, the taskbar button flashes, and a **Just finished** card appears on Home
  with the result, the three stats that stood out (against your rank, or your own usual), and the top
  finding. If the AI model is installed its report is written in the background so it's ready to open.
- **Tonight** – games less than 30 minutes apart form a session. The card shows the session's record
  and score/goals/saves/shots against your usual, and after three losses in a row it gently suggests
  a break. It disappears 6 hours after your last game.

- **Weekly goals** – the app suggests up to two goals from your weakest stats for your rank (or the
  stats slipping most lately if no rank is set), with a target halfway to that rank's median. You can
  edit the target before pressing **Set goal**. Progress counts games played since you set it (at least
  3 must count) and a goal lasts 7 days; **Collect** it when met or expired, and the home card keeps a
  streak of goals met in a row. The post-game card says whether the game met each goal.
- **How to practise** – each goal expands into drills and, where we have them, community training packs
  with a **Copy code** button. The AI coach's "focus for your next games" now draws on the same drills
  for your weakest stats instead of inventing its own.
- **Share cards** – **Share** on the Home strip (your progress) and the match screen (that game) saves a
  1200×630 PNG (and copies it to the clipboard when possible).
- **Clips** – **Clip** on a key moment records the 8 seconds around it from the 2D replay and saves it as
  a WebM video you can post.

### Match screen
- **Replay (left)** – the full match as a top-down 2D playback with every car and the ball,
  boost and speed per player. It **starts playing as soon as you open the match**, with
  play/pause (Space), seek, speed control and a "skip goal replays" toggle.
- **AI analysis (right)** – a small language model that runs **on your own PC** (free,
  private, offline) reads the measured facts about the match and writes a summary, strengths,
  things to improve and what to practise. It **starts by itself** when you open a match
  (finished reports are saved and open instantly). Below it is **Ask the coach**, a chat about
  the match: mention a game clock ("what went wrong at 2:30?") or a goal ("the second goal")
  and the coach is given exactly where everyone was.
- **Tabs (below the replay)**:
  - **Scoreboard** – score, goals, assists, saves and shots for every player (you're marked
    "(you)"), plus the goal sequence with the running score.
  - **Key moments** – goals (with where the defenders were 3 seconds earlier), "nobody back"
    spells, double commits, long stretches out of boost, 50/50s lost just before a goal, last
    men beaten just before a goal, plus good plays (aerial goals, big clears), each with the
    game clock and the AI's advice. **Watch** jumps the replay above to a few seconds before it, and
    👍 / 👎 record whether the moment was detected correctly (saved to `labels.jsonl`, used to tune the rules
    with `python dev_tools/label_report.py`).
  - **Findings** – short rule-based notes about *you* in this game, compared with your usual
    averages ("you were ahead of the ball on 2 of the 3 goals you conceded"). No AI needed.
  - **Movement** – average speed, % supersonic / boost speed / slow, % on the ground / low
    air / high air.
  - **Positioning** – % in defensive / middle / offensive third, % behind the ball, average
    distance to the ball, % closest / farthest from the ball on their team.
  - **Boost** – average boost, boost used and collected, big/small pads, stolen big pads, % time
    at 0 and at 100 boost.
  - **Challenges** – touches (and per minute), % possession (time as the last player to touch
    the ball), 50/50s and your win rate in them, and times you were beaten (you went for the
    ball, an opponent got it first and it went past you towards your goal).
  - **Mechanics** – aerial touches (and high ones above crossbar height), wall touches, flip
    touches, hardest hit, dribbles (ball carried on the roof for 1 s+), flips, double jumps,
    half-flips and wave dashes.
  - **Defence** – clears out of your defensive third, % shadowing (back between the ball and
    your goal at a sensible distance while it heads your way), % as last man, and times beaten
    as last man.
  - **Match** – live play time, average ball speed, and how long the ball spent in each half
    and third.
- **Python measures, the AI explains.** All times, positions and boost numbers come from the
  replay data (`moments.py`, `touches.py`), never from the model, so the AI can't invent them.
- **First use:** the AI panel offers a one-off model download (Lite ≈ 2.7 GB for most laptops,
  Standard ≈ 5.7 GB for 8 GB+ graphics cards). It is saved in `%LOCALAPPDATA%\RLAnalyser\models`
  and checked against a pinned SHA-256; the analysis starts automatically once it is installed.
  Reports are cached in `cache/*.coach.json`.

### Full progress page
- **Player picker** – defaults to you. Choose anyone you've played with to view their stats;
  **This is me** saves that player as you.
- **Mode filter**, **record**, and an **averages table** – every stat averaged over all games,
  your last 10 games, wins only and losses only, so you can see what changes when you win.
- **Trend chart** – click any stat in the table to chart it game by game (dots) with a 5-game
  rolling average (line). Hover a dot for that game's details.
- **Games list** – your games with the key stats; double-click one to open its match screen.

### Updates
The title bar has a **Check for updates** button, and the app checks quietly a few seconds after
it starts. When a newer version has been released, a banner shows what's new with **Install &
restart**: the app downloads the installer, checks it, closes, installs and reopens by itself.
Nothing is installed without that click. See [Updating](#updating).

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
- **Views**: one page, three views switched in JS (`showView` in `ui/app.js`): Home, Match
  and Progress.
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
| `ui/index.html` | Page structure: the Home, Match (replay + tabs + AI panel) and full Progress views. |
| `ui/styles.css` | The dark design system: colour tokens at the top, then every component, plus the motion. See [Design](#design). |
| `ui/app.js` | Page controller: view switching, home strip and replay tiles, match header/tables, the embedded replay, the progress page; talks to `pywebview.api` and handles the pushes from Python (`window.app.*`). |
| `ui/coach.js` | The AI panel and the Findings / Key moments tabs: model download, the AI report (started automatically), and the chat. |
| `ui/chart.js` | Canvas-drawn trend chart (per-game dots + rolling average, with hover). |
| `ui/pitch.js` | Canvas-drawn replay viewer embedded in the match screen: playback, pitch geometry, cars and ball, and `recordClip` (MediaRecorder on the canvas). |
| `replay_library.py` | Lists replays in a folder, analyses them (`analyse`), caches results as JSON in `cache/`, `LibraryScanner` (background thread that loads/analyses a whole folder) and `ReplayWatcher` (polls the folder for replays saved while the app is open). |
| `replay_parser.py` | Runs `tools/rrrocket.exe` on a replay and turns the header into a `ReplaySummary` (scores, players with stable `player_id`, goals, who recorded it). |
| `frame_data.py` | Runs rrrocket with `--network-parse` and converts the network frames into pandas tables (censored `******` names are replaced with the header's real names, `restore_censored_names`): `frames`, `ball` (with the game's last-touch team), `players` (with jump / double-jump / dodge states), `pickups` (`GameFrames`). Also holds the shared pitch constants. |
| `analysis.py` | Computes per-player stats (`player_stats`) and match stats (`team_stats`) from `GameFrames`. `STAT_GROUPS` defines which stats appear in which tab (sent to the page so it can build the tables generically). |
| `benchmarks.py` | Rank benchmarks: loads `benchmarks.json`, `percentile`, `closest_band`, and `profile` (your recent form vs a rank, with strengths and weaknesses). Pure measurement. |
| `benchmarks.json` | Per mode and rank band, the 10/25/50/75/90th percentile of every stat. Built by `dev_tools/build_benchmarks.py`; bundled into the installer if present. |
| `dev_tools/ballchasing.py` | Developer-only: shared ballchasing.com helpers (API calls with rate-limit retry, rank bands, replay and stats download cache in `benchmark_cache/`). |
| `dev_tools/validate.py` | Developer-only: checks our stats against ballchasing's for the same replays (correlation, bias, worst outliers), plus header checks that need no token (`--local`: was the scorer the last toucher, do touches cover shots+saves, plausible touches/min) and `--benchmarks` (do medians rise with rank). Writes `validation_report.md`. |
| `dev_tools/build_benchmarks.py` | Developer-only: downloads public ballchasing.com replays by rank, runs `analyse()` on them and writes `benchmarks.json`. Not shipped. |
| `postgame.py` | Post-game card and session logic: `headline_stats` (the stats that stood out in one game), `current_session` (tonight's record and losing-streak check). Pure measurement. |
| `ui/welcome.js` | The first-run guide (`welcome`) and the Home cards for the game just played and tonight's session (`homeAlerts`). |
| `goals.py` | Weekly goals: `suggestions`, `target_for`, `progress` (met / expired / active), `met_in_game`, `streak`. Stored in `config.json` under `"goals"` and `"goal_history"`. Pure logic. |
| `training.py` | Drills and community training-pack codes per weak stat (`TRAINING`, `for_stat`, `drill_line`). Codes were checked against ggrecon.com and ginx.tv; see the file header. |
| `ui/goals.js` | The goals card on Home: progress bars, suggestions, "how to practise". |
| `ui/share.js` | Draws share-card PNGs on a canvas and saves them via `Api.save_file`. |
| `progress.py` | Cross-replay stats for one player: `player_games` (one row per game), `comparison` (all / last 10 / wins / losses averages), `known_players`, `guess_me`. |
| `pitch_viewer.py` | `build_track`: turns a match's frame data into the JSON-serialisable track `ui/pitch.js` plays back. |
| `touches.py` | Ball touches (the ball's velocity jumps while a car is next to it), 50/50s, beaten-to-the-ball events, dribbles, half-flips / wave dashes, last man, and `skill_stats` (the Challenges / Mechanics / Defence columns). Also the shared per-frame table `live_table` and `find_runs`. Pure measurement, no AI. |
| `moments.py` | Rule-based key-moment detection (`detect_moments`) and findings about a player (`insights`). Pure measurement, no AI. |
| `coach.py` | The AI layer: model download, llama.cpp server management, the match "dossier" given to the model, report generation, and chat. Also a CLI: `python coach.py match.replay --me "Name"`. |
| `version.py` | `APP_VERSION`: shown in the title bar and used to name the installer. |
| `rl_analyser.spec` | PyInstaller recipe: a windowed one-folder build with `ui/` and `tools/` bundled. |
| `updater.py` | In-app updates: reads the release manifest, compares versions, downloads and SHA-256-checks the installer, starts it. No UI. |
| `ui/update.js` | The title-bar button and update banner (progress, release notes, errors). |
| `release.ps1` | Makes a release: builds the installer and writes `dist\release\latest.json` next to it. |
| `build.ps1` | One command that builds the app and the installer (see below). |
| `installer/RLAnalyser.iss` | Inno Setup script for the per-user installer (Start menu / desktop shortcuts, uninstaller). |
| `assets/` | `icon.ico` (app icon) and `make_icon.py`, which generates it. |
| `paths.py` | Where files live: `bundled()` for shipped files, `user_data()` for config/cache, `models_dir()` for AI models. Works from source and from a packaged build. |
| `tools/rrrocket.exe` | Third-party [rrrocket](https://github.com/nickbabcock/rrrocket) replay decoder used by the parsers (MIT, see `tools/LICENSE-rrrocket`). |
| `tools/llama-server/` | Third-party [llama.cpp](https://github.com/ggml-org/llama.cpp) server (build b11435, Windows Vulkan: NVIDIA/AMD/Intel GPUs with CPU fallback; MIT, see `LICENSE-llama.cpp`). Runs the AI model. |
| `labels.py` | "Was this right?" votes (`labels.jsonl` in the data folder): `add`, `load` (latest vote per event), `precision` per event kind. |
| `dev_tools/label_report.py` | Developer-only: precision per event kind from `labels.jsonl`, and the replay/time of every "wrong" vote to re-watch. |
| `tests/` | pytest suite. Synthetic mini-matches (`conftest.make_game`) test touches, 50/50s, beaten, dribbles, key moments and findings; `test_goals.py`, `test_benchmarks.py` and `test_postgame.py` cover the pure logic; `test_real_replays.py` sanity-checks real replays from your replay folder (or `RLA_TEST_REPLAYS`) and is skipped if there are none. |
| `config.json` | Local settings: replay folder and which player is you. Not committed to git. |
| `cache/` | Per-replay analysis results. Safe to delete (it's rebuilt). Not committed to git. |

**If you change how stats are calculated**, bump `CACHE_VERSION` in
`replay_library.py` so every replay is re-analysed with the new code, then rebuild `benchmarks.json`.

Coordinates are Unreal units: blue (team 0) defends the −y goal, orange (team 1) the +y
goal; the pitch is x ∈ [−4096, 4096], y ∈ [−5120, 5120].

## Validating the numbers

```
python dev_tools/validate.py --local                    # no token: header checks on your own replay folder
python dev_tools/validate.py --per-band 10              # with BALLCHASING_TOKEN: also compares with ballchasing
python dev_tools/validate.py --benchmarks               # after building benchmarks.json
```
Targets: correlation of at least 0.9 with ballchasing on the movement / positioning / boost stats, and the
scorer being the last toucher on as many goals as possible (73 of 88 on the first 14 local replays).
`python -m pytest tests` runs the unit tests (`tests/test_validate.py` covers this tool's maths).

## Rank benchmarks

The tables must come from our own analysis code (ballchasing's stat numbers are measured differently),
so they are built by analysing public replays of each rank:

```
set BALLCHASING_TOKEN=<free token from ballchasing.com -> Upload -> API token>
python dev_tools/build_benchmarks.py --mode 2v2 --per-band 60      # repeat --mode / --band as needed
```

Downloads are kept in `benchmark_cache/` (not committed) so an interrupted run resumes, and
`benchmarks.json` is saved after every band. **Rebuild whenever `CACHE_VERSION` changes**, because the
stats then mean something different. Commit `benchmarks.json` so releases include it. Your chosen rank
per mode is stored in `config.json` under `"ranks"`.

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
- The touch, 50/50, beaten, dribble, half-flip, wave-dash and shadowing rules are first-draft
  thresholds (constants at the top of `touches.py`). On real replays the scorer was the last
  toucher on 26 of 34 goals (the rest are mostly deflections off a defender or shots longer
  than 4 s), and touches came out at roughly 6-9 per player per minute. Treat half-flips and
  wave dashes as best-effort; "times beaten" looks high and may need a stricter rule.
- The AI coach has only been tested against a synthetic match so far (no real replays were
  available during development): the Lite model's report and chat both worked end to end. The
  key-moment rules are first-draft thresholds (constants at the top of `moments.py`) that need
  tuning against real games.
- On a PC without a usable GPU the model runs on the CPU: about 7 words/second on a 10-thread
  CPU, so the AI analysis takes around 2 minutes and chat answers about a minute. The findings and
  key moments are instant either way. The Lite model sometimes pads its strengths or misreads a
  stat; Standard is better but needs a stronger PC.
- The installer is **unsigned**, so Windows SmartScreen shows "Unknown publisher" the first time
  it is run (More info → Run anyway) until it is code-signed. Updates started from inside the app
  don't show it (the app downloads the file itself).
- Versions before 1.1.0 have no updater, so install 1.1.0 by hand once; later versions update
  themselves.

## AI models

- **Models** are Qwen3.5 (Apache-2.0) GGUF files from Hugging Face, defined in `TIERS` in
  `coach.py`. To change or upgrade one, edit that entry (repo, file, size, SHA-256) and bump
  `COACH_VERSION` so saved reports are rewritten.
- The model is downloaded by each user on first use, so the installer itself stays small (~47 MB).
- **Still to do for a public release:** code-sign the installer, and sign the update manifest (see
  [Updating](#updating)).

## Requirements

- Windows (rrrocket is bundled as a Windows `.exe`; the window uses the Edge WebView2
  runtime, which ships with Windows 11 / is auto-installed on Windows 10)
- Python 3.10+
- `pandas`, `numpy` and `pywebview` (`pip install pandas numpy pywebview`); no other
  UI toolkit needed
- To run the tests: `pip install pytest`, then `python -m pytest tests`

## Running

```
python rl_analyser.py
```

## Design

The whole UI is dark (near-black page, slightly lighter cards) with **one accent, electric violet**,
used for chrome only: buttons, selected tabs/cards/rows, focus rings, the AI panel and glows. **Team
blue and orange are reserved for data** (which team), so the accent is never either of them, and the
trend chart's data colour is the categorical blue, not the violet.

- **Tokens** live at the top of `ui/styles.css` (`--paper`, `--surface`, `--surface-2/3`, `--ink*`,
  `--accent*`, `--blue`, `--orange`...). Change a value there and the whole UI follows.
- **Canvas colours** can't read CSS variables, so the two canvases keep matching constants:
  `ui/chart.js` (the constants at the top: ink, grid, surface, data blue, tooltip) and `ui/pitch.js`
  (`TEAM_COLOURS`, `TEAM_LIGHT`, `TEAM_GLOW`, pitch/pad colours). Retune those together with the CSS.
- **Contrast:** every text token is at least 4.5:1 on all four surfaces, the accent fill takes white text at
  4.8:1 or better, and the team pair passes the dataviz skill's colour-blind and contrast checks on the dark
  surface (the dark chart steps come from that skill).
- **Motion** (tile entrance, count-up numbers, the AI orb, typing dots, view fades) is switched off under the
  system's "reduce motion" setting. Glows are static CSS, so they cost nothing while the app runs.
- **Native bits:** `color-scheme: dark` (dropdowns, scrollbars, sliders), the window background (no white flash
  at start-up) and, on Windows 10/11, a dark title bar (`dark_title_bar` in `rl_analyser.py`; if it isn't
  supported the normal title bar is kept).

## Updating

**Releasing a new version** (you):
1. Raise `APP_VERSION` in `version.py` (e.g. `1.2.0`).
2. `powershell -ExecutionPolicy Bypass -File release.ps1 -Notes "What's new"` (or `-NotesFile notes.txt`).
   This builds the app and installer and writes two files to `dist\release\`:
   `RLAnalyser-Setup-<version>.exe` and `latest.json`. Add `-BaseUrl https://example.com/rla/` to
   write an absolute download address into `latest.json`.
3. Upload both files to the place the app looks (below), or let the script do it for a folder:
   add `-PublishTo <folder>` (it copies the installer first and `latest.json` last, so an app never reads a
   manifest whose installer isn't there yet), and `-SkipBuild` to re-publish what is already in `dist\`
   without rebuilding. Every installed copy offers the update the next time it checks.

**Where the app looks** – the address of `latest.json`; the first of these that is set wins:
1. the `RLA_UPDATE_URL` environment variable (for testing),
2. `"update_url"` in `config.json` (`%LOCALAPPDATA%\RLAnalyser\config.json` once installed),
3. `UPDATE_URL` in `version.py` (empty for now; put your website address here once it exists, e.g.
   `https://example.com/rla/latest.json`, and ship that in a release).

It can be an `https://` address **or a folder / network path / `file://` URL**, so updates work
before there is a website: point it at a shared folder that holds the two files. Plain `http://`
is refused (except to this PC, for testing). With nothing set, the button reads "Updates not set up".

**`latest.json`**:
```json
{ "version": "1.2.0", "url": "RLAnalyser-Setup-1.2.0.exe", "sha256": "<64 hex characters>",
  "size": 49123456, "notes": "What's new, as plain text.", "released": "2026-10-20" }
```
`url` is either a full `https://` address or relative to `latest.json`'s own location.
`release.ps1` writes this file for you, including the checksum.

**What the app does** – checks the manifest (at start-up and on the button), offers the update only if
`version` is newer than the running one, then on **Install & restart** downloads the installer to
`%LOCALAPPDATA%\RLAnalyser\updates`, refuses it unless its SHA-256 (and size) match the manifest, closes
the app and the AI engine, runs the installer with `/SILENT` (a small progress window) and the installer
reopens the app. Settings, cache and AI models are not touched. If an AI analysis is running the app asks first.

**Security:** HTTPS plus the SHA-256 check protects against corrupted downloads and tampering on the
network. It does **not** protect against someone who takes over the website that hosts `latest.json`,
because they could publish a manifest for their own installer. The next steps for a wide release are
code-signing the installer (and having the app verify the publisher) and signing `latest.json`.

**Testing an update without touching a real install:** build test installers with a different app id
(`ISCC /DAppIdGuid={{<your own guid>} ...`, see `installer/RLAnalyser.iss`) and install them to a scratch
folder with `/DIR=...`. The installer's app id is what makes a new version replace the old one in place, so
never reuse the real one for tests.

## Building the installer

One-off setup: `pip install pyinstaller` and `winget install JRSoftware.InnoSetup`. Then:

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

This runs PyInstaller (`rl_analyser.spec` → `dist\RL Analyser\RL Analyser.exe`) and Inno Setup
(`installer\RLAnalyser.iss` → `dist\RLAnalyser-Setup-<version>.exe`). Bump `APP_VERSION` in
`version.py` first for a new release. `build/` and `dist/` are not committed. The installer
installs per user (no admin rights) to `%LOCALAPPDATA%\Programs\RL Analyser`. Settings, the
replay cache and AI models live in `%LOCALAPPDATA%\RLAnalyser`, so updates and uninstalls keep them.

On a fresh install no replay folder is known yet unless Rocket League's default one is found
(`Documents\My Games\Rocket League\TAGame\DemosEpic` / `Demos`); otherwise press **Choose folder…**.

Quick command-line check of a single replay:

```
python replay_parser.py path\to\match.replay
```
