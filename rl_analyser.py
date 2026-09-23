"""RL Analyser - pick a Rocket League replay folder and load the most recent replay."""

import json
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from analysis import STAT_GROUPS, player_stats, team_stats
from frame_data import load_game_frames
from pitch_viewer import PitchViewer
from replay_parser import ReplayParseError, parse_replay

CONFIG_PATH = Path(__file__).with_name("config.json")
REPLAY_EXTENSION = ".replay"

# Where Rocket League usually saves replays (Epic/Steam, with or without OneDrive)
DEFAULT_REPLAY_DIRS = [
    documents / "My Games" / "Rocket League" / "TAGame" / demos
    for documents in (Path.home() / "Documents", Path.home() / "OneDrive" / "Documents")
    for demos in ("DemosEpic", "Demos")
]


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def guess_replay_dir():
    """Return the saved folder, else the first default location that exists."""
    saved = load_config().get("replay_dir")
    if saved and Path(saved).is_dir():
        return Path(saved)
    for folder in DEFAULT_REPLAY_DIRS:
        if folder.is_dir():
            return folder
    return None


def find_latest_replay(folder):
    """Return the most recently modified .replay file in folder, or None."""
    replays = [
        entry for entry in Path(folder).iterdir()
        if entry.is_file() and entry.suffix.lower() == REPLAY_EXTENSION
    ]
    if not replays:
        return None
    return max(replays, key=lambda p: p.stat().st_mtime)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RL Analyser")
        self.geometry("900x600")

        self.replay_dir = guess_replay_dir()
        self.latest_replay = None
        self.summary = None

        self.folder_var = tk.StringVar()
        self.replay_var = tk.StringVar()

        tk.Label(self, text="Replay folder:", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 0))
        tk.Label(self, textvariable=self.folder_var, wraplength=590, justify="left").pack(anchor="w", padx=12)

        buttons = tk.Frame(self)
        buttons.pack(anchor="w", padx=12, pady=8)
        tk.Button(buttons, text="Choose folder...", command=self.choose_folder).pack(side="left")
        tk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left", padx=6)
        self.watch_button = tk.Button(buttons, text="Watch match", state="disabled", command=self.open_viewer)
        self.watch_button.pack(side="left")

        tk.Label(self, text="Most recent replay:", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12)
        tk.Label(self, textvariable=self.replay_var, wraplength=590, justify="left").pack(anchor="w", padx=12)

        ttk.Separator(self).pack(fill="x", padx=12, pady=10)

        self.match_var = tk.StringVar()
        self.score_var = tk.StringVar()
        tk.Label(self, textvariable=self.match_var, justify="left").pack(anchor="w", padx=12)
        tk.Label(self, textvariable=self.score_var, font=("Segoe UI", 16, "bold")).pack(pady=(4, 8))

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        scoreboard_tab = tk.Frame(self.tabs)
        self.tabs.add(scoreboard_tab, text="Scoreboard")
        self.scoreboard = self.make_table(
            scoreboard_tab, [("Score", 70), ("Goals", 60), ("Assists", 60), ("Saves", 60), ("Shots", 60)]
        )
        self.goals_var = tk.StringVar()
        tk.Label(scoreboard_tab, textvariable=self.goals_var, justify="left", wraplength=820).pack(anchor="w", pady=8)

        # One tab per group of frame-by-frame stats
        self.stat_tables = {}
        for group, stats in STAT_GROUPS.items():
            tab = tk.Frame(self.tabs)
            self.tabs.add(tab, text=group)
            self.stat_tables[group] = self.make_table(tab, [(heading, 95) for _, heading, _ in stats])

        match_tab = tk.Frame(self.tabs)
        self.tabs.add(match_tab, text="Match")
        self.match_stats_var = tk.StringVar()
        tk.Label(match_tab, textvariable=self.match_stats_var, justify="left", font=("Consolas", 10)).pack(
            anchor="w", padx=8, pady=8
        )

        self.status_var = tk.StringVar()
        tk.Label(self, textvariable=self.status_var, fg="#666").pack(anchor="w", padx=12, pady=(0, 8))

        self.analysis_result = None  # (player stats, match stats) or an Exception
        self.analysis_for = None     # replay path the current analysis belongs to

        self.refresh()

    def make_table(self, parent, stat_columns):
        """Treeview with Team + Player columns followed by stat_columns [(heading, width)]."""
        columns = [("Team", 70), ("Player", 160)] + stat_columns
        table = ttk.Treeview(parent, columns=[h for h, _ in columns], show="headings", height=7)
        for heading, width in columns:
            table.heading(heading, text=heading)
            table.column(heading, width=width, anchor="w" if heading == "Player" else "center")
        table.tag_configure("blue", background="#dbe9ff")
        table.tag_configure("orange", background="#ffe6cc")
        table.pack(fill="x")
        return table

    def choose_folder(self):
        folder = filedialog.askdirectory(
            title="Select your Rocket League replay folder",
            initialdir=str(self.replay_dir) if self.replay_dir else str(Path.home()),
        )
        if not folder:
            return
        self.replay_dir = Path(folder)
        save_config({**load_config(), "replay_dir": str(self.replay_dir)})
        self.refresh()

    def refresh(self):
        self.latest_replay = None
        self.analysis_for = None
        self.game = None
        self.watch_button.configure(state="disabled")
        self.show_summary(None)

        if not self.replay_dir:
            self.folder_var.set("No folder selected")
            self.replay_var.set("-")
            return

        self.folder_var.set(str(self.replay_dir))
        try:
            self.latest_replay = find_latest_replay(self.replay_dir)
        except OSError as e:
            messagebox.showerror("RL Analyser", f"Could not read folder:\n{e}")
            self.latest_replay = None

        if not self.latest_replay:
            self.replay_var.set("No .replay files found in this folder")
            return

        modified = datetime.fromtimestamp(self.latest_replay.stat().st_mtime)
        size_kb = self.latest_replay.stat().st_size / 1024
        self.replay_var.set(
            f"{self.latest_replay.name}\n"
            f"Saved {modified:%d %b %Y %H:%M}  ·  {size_kb:,.0f} KB"
        )

        try:
            self.summary = parse_replay(self.latest_replay)
        except ReplayParseError as e:
            messagebox.showerror("RL Analyser", f"Could not parse replay:\n{e}")
            return
        self.show_summary(self.summary)
        self.start_analysis(self.latest_replay)

    def start_analysis(self, replay):
        """Decode the full frame data in the background so the window stays responsive."""
        self.analysis_for = replay
        self.analysis_result = None
        self.status_var.set("Analysing frame data...")

        def work():
            try:
                game = load_game_frames(replay)
                result = (game, player_stats(game), team_stats(game))
            except Exception as e:  # shown to the user rather than lost in the thread
                result = e
            if self.analysis_for == replay:  # drop results a newer refresh has replaced
                self.analysis_result = result

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self.check_analysis, replay)

    def check_analysis(self, replay):
        if self.analysis_for != replay:
            return  # a newer refresh has its own polling loop
        if self.analysis_result is None:
            self.after(100, self.check_analysis, replay)
            return
        result = self.analysis_result
        if isinstance(result, Exception):
            self.status_var.set(f"Frame analysis failed: {result}")
            return
        self.game = result[0]
        self.show_analysis(*result[1:])
        self.watch_button.configure(state="normal")
        self.status_var.set("Frame analysis complete (live play only, kickoffs included)")

    def open_viewer(self):
        PitchViewer(self, self.game, self.summary.goals, title=f"Match viewer - {self.summary.name}")

    def show_analysis(self, players, match):
        for group, stats in STAT_GROUPS.items():
            table = self.stat_tables[group]
            for name, row in players.iterrows():
                values = [fmt.format(row[col]) for col, _, fmt in stats]
                self.fill_row(table, int(row.team), name, values)

        minutes, seconds = divmod(int(match["live_seconds"]), 60)
        self.match_stats_var.set(
            f"Live play time          {minutes}:{seconds:02d}\n"
            f"Ball avg speed          {match['ball_avg_speed']:.0f} uu/s\n\n"
            f"Ball in blue half       {match['ball_pct_blue_half']:.1f}%\n"
            f"Ball in orange half     {match['ball_pct_orange_half']:.1f}%\n\n"
            f"Ball in blue third      {match['ball_pct_blue_third']:.1f}%\n"
            f"Ball in middle third    {match['ball_pct_mid_third']:.1f}%\n"
            f"Ball in orange third    {match['ball_pct_orange_third']:.1f}%"
        )

    def fill_row(self, table, team, name, values):
        label, tag = ("Blue", "blue") if team == 0 else ("Orange", "orange")
        table.insert("", "end", tags=(tag,), values=(label, name, *values))

    def show_summary(self, summary):
        self.summary = summary
        for table in (self.scoreboard, *self.stat_tables.values()):
            table.delete(*table.get_children())
        self.match_stats_var.set("")
        self.status_var.set("")
        if not summary:
            self.match_var.set("")
            self.score_var.set("")
            self.goals_var.set("")
            return

        minutes, seconds = divmod(int(summary.seconds_played), 60)
        self.match_var.set(
            f"{summary.name}\n"
            f"{summary.team_size}v{summary.team_size} {summary.match_type}  ·  Map: {summary.map_name}  ·  "
            f"{summary.date}  ·  Length: {minutes}:{seconds:02d}"
        )
        self.score_var.set(f"Blue {summary.team0_score}  –  {summary.team1_score} Orange")

        for team in (0, 1):
            for p in summary.team(team):
                name = f"{p.name} (bot)" if p.is_bot else p.name
                self.fill_row(self.scoreboard, team, name, (p.score, p.goals, p.assists, p.saves, p.shots))

        # Goals in order, with the running score after each one
        blue = orange = 0
        lines = []
        for g in summary.goals:
            if g.team == 0:
                blue += 1
            else:
                orange += 1
            lines.append(f"{blue}-{orange}  {g.scorer}")
        self.goals_var.set("Goals:  " + "   ·   ".join(lines) if lines else "No goals")


if __name__ == "__main__":
    App().mainloop()
