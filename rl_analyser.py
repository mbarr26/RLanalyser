"""RL Analyser - browse every Rocket League replay in a folder and track your stats over time."""

import json
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from analysis import STAT_GROUPS
from frame_data import load_game_frames
from pitch_viewer import PitchViewer
from progress import guess_me
from progress_view import ProgressPanel
from replay_library import LibraryScanner, analyse, list_replays
from replay_parser import ReplayParseError

CONFIG_PATH = Path(__file__).with_name("config.json")
PROGRESS_REFRESH_SECONDS = 2  # while scanning, redraw the progress tab at most this often

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


def fmt_stat(fmt, value):
    return "-" if value is None else fmt.format(value)


def guess_replay_dir():
    """Return the saved folder, else the first default location that exists."""
    saved = load_config().get("replay_dir")
    if saved and Path(saved).is_dir():
        return Path(saved)
    for folder in DEFAULT_REPLAY_DIRS:
        if folder.is_dir():
            return folder
    return None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RL Analyser")
        self.geometry("1280x800")

        self.replay_dir = guess_replay_dir()
        self.chosen_me = load_config().get("me")  # player id of "you", once picked
        self.guessed_me = None     # used until then (see progress.guess_me)
        self.records = {}          # replay path -> ReplayRecord
        self.scanner = None
        self.current = None        # replay path shown in the Matches tab
        self.game = None           # frame data for self.current, loaded for the viewer
        self.analysing = set()     # replay paths being analysed because they were opened
        self.inbox = queue.Queue()  # messages from background threads, handled on the UI thread
        self.progress_dirty = False
        self.progress_refreshed_at = 0.0

        top = tk.Frame(self)
        top.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(top, text="Replay folder:", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.folder_var = tk.StringVar()
        tk.Label(top, textvariable=self.folder_var).pack(side="left", padx=6)
        tk.Button(top, text="Choose folder...", command=self.choose_folder).pack(side="left", padx=(6, 0))
        tk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=6)
        self.status_var = tk.StringVar()
        tk.Label(top, textvariable=self.status_var, fg="#666").pack(side="right")

        self.pages = ttk.Notebook(self)
        self.pages.pack(fill="both", expand=True, padx=12, pady=10)
        matches = ttk.PanedWindow(self.pages, orient="horizontal")
        self.pages.add(matches, text="Matches")
        self.progress = ProgressPanel(self.pages, self.open_replay, self.set_me)
        self.pages.add(self.progress, text="My progress")
        self.pages.bind("<<NotebookTabChanged>>", lambda e: self.refresh_progress())

        matches.add(self.build_replay_list(matches), weight=0)
        matches.add(self.build_match_panel(matches), weight=1)

        self.after(100, self.check_inbox)
        self.refresh()

    # ---------- layout ----------

    def build_replay_list(self, parent):
        frame = tk.Frame(parent)
        columns = [("Date", 115), ("Mode", 45), ("Map", 95), ("Score", 50), ("Result", 55)]
        self.replay_list = ttk.Treeview(frame, columns=[h for h, _ in columns], show="headings")
        for heading, width in columns:
            self.replay_list.heading(heading, text=heading)
            self.replay_list.column(heading, width=width, anchor="w" if heading == "Map" else "center")
        self.replay_list.tag_configure("pending", foreground="#999")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.replay_list.yview)
        self.replay_list.configure(yscrollcommand=scroll.set)
        self.replay_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.replay_list.bind("<<TreeviewSelect>>", self.on_replay_selected)
        return frame

    def build_match_panel(self, parent):
        panel = tk.Frame(parent)
        header = tk.Frame(panel)
        header.pack(fill="x", padx=(12, 0))
        self.match_var = tk.StringVar()
        tk.Label(header, textvariable=self.match_var, justify="left").pack(side="left", anchor="w")
        self.watch_button = tk.Button(header, text="Watch match", state="disabled", command=self.open_viewer)
        self.watch_button.pack(side="right")

        self.score_var = tk.StringVar()
        tk.Label(panel, textvariable=self.score_var, font=("Segoe UI", 16, "bold")).pack(pady=(4, 8))

        self.tabs = ttk.Notebook(panel)
        self.tabs.pack(fill="both", expand=True, padx=(12, 0))

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

        self.analysis_var = tk.StringVar()
        tk.Label(panel, textvariable=self.analysis_var, fg="#666").pack(anchor="w", padx=12, pady=(4, 0))
        return panel

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

    # ---------- replay folder & background scanning ----------

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
        """Re-list the folder and (re)start loading every replay in the background."""
        if self.scanner:
            self.scanner.stop()
        self.scanner = None
        self.records = {}
        self.replay_list.delete(*self.replay_list.get_children())
        self.show_replay(None)
        self.progress_dirty = True

        if not self.replay_dir:
            self.folder_var.set("No folder selected")
            return
        self.folder_var.set(str(self.replay_dir))
        try:
            paths = list_replays(self.replay_dir)
        except OSError as e:
            messagebox.showerror("RL Analyser", f"Could not read folder:\n{e}")
            return
        if not paths:
            self.status_var.set("No .replay files found in this folder")
            return

        # Rows appear straight away (filename only) and fill in as each replay loads
        for path in paths:
            self.replay_list.insert("", "end", iid=str(path), values=(path.stem[:14], "", "", "", ""),
                                    tags=("pending",))
        scanner = LibraryScanner(paths, lambda message: self.inbox.put((scanner, *message)))
        self.scanner = scanner
        scanner.start()
        self.replay_list.selection_set(str(paths[0]))  # newest replay

    def check_inbox(self):
        """Handle messages from background threads (tkinter must only be used on this thread)."""
        try:
            while True:
                source, kind, *data = self.inbox.get_nowait()
                if source is self.scanner or source == "open":
                    getattr(self, f"on_{kind}")(*data)
        except queue.Empty:
            pass
        if self.progress_dirty and time.monotonic() - self.progress_refreshed_at > PROGRESS_REFRESH_SECONDS:
            self.refresh_progress()
        self.after(100, self.check_inbox)

    @property
    def me(self):
        return self.chosen_me or self.guessed_me

    def on_record(self, record):
        self.records[record.path] = record
        self.update_list_row(record)
        self.progress_dirty = True
        if record.path == self.current:
            self.show_replay(self.current)

    def on_progress(self, text):
        self.status_var.set(text)

    def on_done(self, unreadable):
        self.update_guessed_me()
        self.refresh_progress()
        analysed = sum(r.analysed for r in self.records.values())
        text = f"{len(self.records)} replays, {analysed} analysed"
        if unreadable:
            text += f"  ·  {unreadable} couldn't be read"
        self.status_var.set(text)

    def update_list_row(self, record):
        s = record.summary
        me = s.player(self.me) if self.me else None
        result = ""
        if me and s.winning_team is not None:
            result = "Win" if s.winning_team == me.team else "Loss"
        self.replay_list.item(str(record.path), tags=() if record.analysed else ("pending",), values=(
            f"{record.played_at:%d %b %y %H:%M}", f"{s.team_size}v{s.team_size}", s.map_name,
            f"{s.team0_score}-{s.team1_score}", result,
        ))

    def update_guessed_me(self):
        guess = guess_me(self.records.values())
        if guess != self.guessed_me:
            self.guessed_me = guess
            if not self.chosen_me:
                for record in self.records.values():
                    self.update_list_row(record)
                if self.current:
                    self.show_replay(self.current)  # re-mark "(you)" on the scoreboard

    def set_me(self, player_id):
        self.chosen_me = player_id
        save_config({**load_config(), "me": player_id})
        for record in self.records.values():
            self.update_list_row(record)
        if self.current:
            self.show_replay(self.current)
        self.refresh_progress()

    def refresh_progress(self):
        if self.pages.index("current") != 1:
            return
        if not self.chosen_me:
            self.update_guessed_me()
        self.progress_dirty = False
        self.progress_refreshed_at = time.monotonic()
        self.progress.refresh(list(self.records.values()), self.me)

    # ---------- the selected replay ----------

    def open_replay(self, path):
        """Show a replay in the Matches tab (used by the progress tab's game list)."""
        self.pages.select(0)
        self.replay_list.selection_set(str(path))
        self.replay_list.see(str(path))

    def on_replay_selected(self, event):
        selection = self.replay_list.selection()
        if selection and Path(selection[0]) != self.current:
            self.show_replay(Path(selection[0]))

    def show_replay(self, path):
        if path != self.current:
            self.game = None
        self.current = path
        record = self.records.get(path)
        self.show_summary(record.summary if record else None)
        self.watch_button.configure(state="normal" if record and not record.error else "disabled")
        if record is None:
            self.analysis_var.set("Loading..." if path else "")
        elif record.error:
            self.analysis_var.set(f"Frame analysis failed: {record.error}")
        elif record.players is None:
            self.analysis_var.set("Analysing frame data...")
            if path not in self.analysing:
                self.start_analysis(path)
        else:
            self.show_analysis(record.players, record.match)
            self.analysis_var.set("Frame stats count live play only (kickoffs included)")

    def start_analysis(self, path):
        """Analyse the selected replay now rather than waiting for its turn in the scan."""
        self.analysing.add(path)

        def work():
            try:
                record, game = analyse(path)
                self.inbox.put(("open", "analysed", record, game))
            except (ReplayParseError, OSError) as e:
                self.inbox.put(("open", "failed", path, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def on_analysed(self, record, game):
        self.analysing.discard(record.path)
        if not self.replay_list.exists(str(record.path)):
            return  # a different folder was loaded meanwhile
        if record.path == self.current:
            self.game = game
        self.on_record(record)

    def on_failed(self, path, message):
        self.analysing.discard(path)
        if path == self.current:
            self.analysis_var.set(f"Could not analyse replay: {message}")

    def on_frames(self, path, game):
        if path != self.current:
            return
        self.watch_button.configure(state="normal")
        if isinstance(game, Exception):
            self.analysis_var.set(f"Could not load match: {game}")
            return
        self.game = game
        self.analysis_var.set("")
        self.open_viewer()

    def open_viewer(self):
        summary = self.records[self.current].summary
        if self.game is None:
            # Frame data isn't cached (it's large), so load it now
            self.watch_button.configure(state="disabled")
            self.analysis_var.set("Loading match...")
            path = self.current

            def work():
                try:
                    game = load_game_frames(path)
                except Exception as e:  # shown to the user rather than lost in the thread
                    game = e
                self.inbox.put(("open", "frames", path, game))

            threading.Thread(target=work, daemon=True).start()
            return
        PitchViewer(self, self.game, summary.goals, title=f"Match viewer - {summary.name}")

    def show_analysis(self, players, match):
        for group, stats in STAT_GROUPS.items():
            table = self.stat_tables[group]
            rows = sorted(players.items(), key=lambda item: (item[1]["team"], -(item[1]["avg_speed"] or 0)))
            for name, row in rows:
                values = [fmt_stat(fmt, row.get(col)) for col, _, fmt in stats]
                self.fill_row(table, int(row["team"]), name, values)

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
        for table in (self.scoreboard, *self.stat_tables.values()):
            table.delete(*table.get_children())
        self.match_stats_var.set("")
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
                if p.player_id == self.me:
                    name += "  (you)"
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
