"""The "My progress" tab: one player's stats across every replay, with a trend chart."""

import math
import tkinter as tk
from tkinter import ttk

import pandas as pd

from progress import PROGRESS_STATS, comparison, known_players, player_games

ROLLING_GAMES = 5

# Chart colours: light surface, recessive grid/axis ink, blue for the data
SURFACE = "#fcfcfb"
GRID = "#e6e5e1"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GAME_DOT = "#86b6ef"     # each game: lighter step, de-emphasised
AVERAGE_LINE = "#2a78d6"  # rolling average: the accent


def nice_ticks(lo, hi, count=5):
    """Round-numbered tick values covering lo..hi."""
    if hi <= lo:
        lo, hi = lo - 1, hi + 1
    raw = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.floor(lo / step) * step
    ticks = [start]
    while ticks[-1] < hi - 1e-9:
        ticks.append(ticks[-1] + step)
    return ticks, step


class TrendChart(tk.Canvas):
    """A stat per game (dots) with its rolling average (line), with a hover tooltip."""

    PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 56, 20, 44, 34

    def __init__(self, master):
        super().__init__(master, bg=SURFACE, highlightthickness=0, height=260)
        self.title = ""
        self.values = []      # per-game values (None where missing)
        self.labels = []      # tooltip text per game
        self.fmt = "{}"
        self.dots = []        # (x, y, index) of drawn dots
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Motion>", self.on_motion)
        self.bind("<Leave>", lambda e: self.delete("hover"))

    def set_data(self, title, values, labels, fmt):
        self.title, self.values, self.labels, self.fmt = title, values, labels, fmt
        self.draw()

    def draw(self):
        self.delete("all")
        self.dots = []
        width, height = self.winfo_width(), self.winfo_height()
        self.create_text(self.PAD_LEFT, 14, text=self.title, anchor="w", fill=TEXT_PRIMARY,
                         font=("Segoe UI", 11, "bold"))

        points = [(i, v) for i, v in enumerate(self.values) if v is not None]
        if not points:
            self.create_text(width / 2, height / 2, text="No data for this stat yet", fill=TEXT_SECONDARY,
                             font=("Segoe UI", 10))
            return

        self._draw_legend(width)
        ticks, step = nice_ticks(min(v for _, v in points), max(v for _, v in points))
        lo, hi = ticks[0], ticks[-1]
        left, right = self.PAD_LEFT, width - self.PAD_RIGHT
        top, bottom = self.PAD_TOP, height - self.PAD_BOTTOM
        count = len(self.values)

        def x_of(i):
            return (left + right) / 2 if count == 1 else left + (right - left) * i / (count - 1)

        def y_of(v):
            return bottom - (bottom - top) * (v - lo) / (hi - lo)

        tick_fmt = "{:,.0f}" if float(step).is_integer() else "{:,.1f}"
        for tick in ticks:
            y = y_of(tick)
            self.create_line(left, y, right, y, fill=GRID, width=1)
            self.create_text(left - 8, y, text=tick_fmt.format(tick), anchor="e", fill=TEXT_SECONDARY,
                             font=("Segoe UI", 9))

        # Game dates at the ends of the x axis
        first, last = self.labels[0].split("\n")[0], self.labels[-1].split("\n")[0]
        self.create_text(left, bottom + 16, text=first, anchor="w", fill=TEXT_SECONDARY, font=("Segoe UI", 9))
        if count > 1:
            self.create_text(right, bottom + 16, text=last, anchor="e", fill=TEXT_SECONDARY, font=("Segoe UI", 9))

        for i, v in points:
            x, y = x_of(i), y_of(v)
            self.create_oval(x - 5, y - 5, x + 5, y + 5, fill=GAME_DOT, outline=SURFACE, width=2)
            self.dots.append((x, y, i))

        # Rolling average over the last few games that have a value
        average, window = [], []
        for i, v in points:
            window = (window + [v])[-ROLLING_GAMES:]
            average.append((x_of(i), y_of(sum(window) / len(window))))
        if len(average) > 1:
            self.create_line(*[c for xy in average for c in xy], fill=AVERAGE_LINE, width=2,
                             capstyle="round", joinstyle="round")
        # End label: latest average value
        end_x, end_y = average[-1]
        latest = sum(window) / len(window)
        self.create_oval(end_x - 5, end_y - 5, end_x + 5, end_y + 5, fill=AVERAGE_LINE, outline=SURFACE, width=2)
        self.create_text(end_x - 8, end_y - 12, text=self.fmt.format(latest), anchor="e", fill=TEXT_PRIMARY,
                         font=("Segoe UI", 9, "bold"))

    def _draw_legend(self, width):
        x = width - self.PAD_RIGHT
        label = f"{ROLLING_GAMES}-game average"
        text = self.create_text(x, 14, text=label, anchor="e", fill=TEXT_SECONDARY, font=("Segoe UI", 9))
        x = self.bbox(text)[0] - 6
        self.create_line(x - 18, 14, x, 14, fill=AVERAGE_LINE, width=2, capstyle="round")
        x -= 34
        text = self.create_text(x, 14, text="Each game", anchor="e", fill=TEXT_SECONDARY, font=("Segoe UI", 9))
        x = self.bbox(text)[0] - 10
        self.create_oval(x - 4, 10, x + 4, 18, fill=GAME_DOT, outline="")

    def on_motion(self, event):
        self.delete("hover")
        if not self.dots:
            return
        x, y, i = min(self.dots, key=lambda d: abs(d[0] - event.x))
        if abs(x - event.x) > 16:
            return
        self.create_oval(x - 7, y - 7, x + 7, y + 7, outline=AVERAGE_LINE, width=2, tags="hover")
        text = f"{self.labels[i]}\n{self.title}: {self.fmt.format(self.values[i])}"
        label = self.create_text(0, 0, text=text, anchor="nw", fill=TEXT_PRIMARY, font=("Segoe UI", 9), tags="hover")
        x0, y0, x1, y1 = self.bbox(label)
        w, h = x1 - x0, y1 - y0
        tx = x + 12 if x + 12 + w + 8 < self.winfo_width() else x - 12 - w - 8
        ty = max(4, min(y - h / 2, self.winfo_height() - h - 12))
        self.coords(label, tx + 4, ty + 4)
        box = self.create_rectangle(tx, ty, tx + w + 8, ty + h + 8, fill="white", outline=GRID, tags="hover")
        self.tag_raise(label, box)


class ProgressPanel(tk.Frame):
    """Pick a player (defaults to you) and see their stats over every replay."""

    GAME_COLUMNS = [("Date", 120), ("Mode", 50), ("Map", 120), ("Result", 60), ("Score", 60),
                    ("Pts", 50), ("G", 40), ("A", 40), ("Sv", 40), ("Sh", 40),
                    ("Avg speed", 80), ("% Behind ball", 100), ("Avg boost", 80)]

    def __init__(self, master, on_open_replay, on_player_chosen):
        super().__init__(master)
        self.on_open_replay = on_open_replay
        self.on_player_chosen = on_player_chosen
        self.records = []
        self.player_ids = []
        self.me = None
        self.viewing = None   # player id whose stats are shown
        self.games = None
        self.chart_stat = "avg_speed"

        controls = tk.Frame(self)
        controls.pack(fill="x", pady=(8, 4))
        tk.Label(controls, text="Player:").pack(side="left")
        self.player_box = ttk.Combobox(controls, state="readonly", width=34)
        self.player_box.pack(side="left", padx=4)
        self.player_box.bind("<<ComboboxSelected>>", self.on_player_selected)
        self.me_button = tk.Button(controls, text="This is me", command=self.on_me_clicked)
        self.me_button.pack(side="left", padx=(4, 16))
        tk.Label(controls, text="Mode:").pack(side="left")
        self.mode_box = ttk.Combobox(controls, state="readonly", width=8, values=["All"])
        self.mode_box.set("All")
        self.mode_box.pack(side="left", padx=4)
        self.mode_box.bind("<<ComboboxSelected>>", lambda e: self.update_view())

        self.summary_var = tk.StringVar()
        tk.Label(self, textvariable=self.summary_var, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(4, 6))

        middle = tk.Frame(self)
        middle.pack(fill="both", expand=True)
        left = tk.Frame(middle)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Averages per game (click a stat to chart it)", fg=TEXT_SECONDARY).pack(anchor="w")
        self.compare_table = ttk.Treeview(left, columns=["Stat", "c1", "c2", "c3", "c4"], show="headings", height=11)
        self.compare_table.heading("Stat", text="Stat")
        self.compare_table.column("Stat", width=130, anchor="w")
        for col in ("c1", "c2", "c3", "c4"):
            self.compare_table.column(col, width=78, anchor="center")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.compare_table.yview)
        self.compare_table.configure(yscrollcommand=scroll.set)
        self.compare_table.pack(side="left", fill="y")
        scroll.pack(side="left", fill="y")
        self.compare_table.bind("<<TreeviewSelect>>", self.on_stat_selected)

        self.chart = TrendChart(middle)
        self.chart.pack(side="left", fill="both", expand=True, padx=(12, 0))

        tk.Label(self, text="Games (double-click to open)", fg=TEXT_SECONDARY).pack(anchor="w", pady=(8, 0))
        games_frame = tk.Frame(self)
        games_frame.pack(fill="both", expand=True)
        self.games_table = ttk.Treeview(games_frame, columns=[h for h, _ in self.GAME_COLUMNS], show="headings",
                                        height=7)
        for heading, width in self.GAME_COLUMNS:
            self.games_table.heading(heading, text=heading)
            self.games_table.column(heading, width=width, anchor="w" if heading == "Map" else "center")
        scroll = ttk.Scrollbar(games_frame, orient="vertical", command=self.games_table.yview)
        self.games_table.configure(yscrollcommand=scroll.set)
        self.games_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.games_table.bind("<Double-1>", self.on_game_opened)

    def refresh(self, records, me):
        """Redraw everything from the given replay records, with `me` as the default player."""
        self.records = records
        self.me = me
        players = known_players(records)
        self.player_ids = [pid for pid, _, _ in players]
        self.player_box.configure(values=[
            f"{name}  ({count} game{'s' if count != 1 else ''}){'  - you' if pid == me else ''}"
            for pid, name, count in players
        ])
        if self.viewing not in self.player_ids:
            self.viewing = me if me in self.player_ids else (self.player_ids or [None])[0]
        if self.viewing:
            self.player_box.current(self.player_ids.index(self.viewing))
        modes = sorted({f"{r.summary.team_size}v{r.summary.team_size}" for r in records})
        self.mode_box.configure(values=["All"] + modes)
        self.update_view()

    def selected_player(self):
        return self.viewing

    def on_player_selected(self, event):
        index = self.player_box.current()
        self.viewing = self.player_ids[index] if index >= 0 else None
        self.update_view()

    def on_me_clicked(self):
        if self.viewing:
            self.on_player_chosen(self.viewing)  # the app saves it as "you" and calls refresh

    def update_view(self):
        player = self.selected_player()
        mode = None if self.mode_box.get() == "All" else self.mode_box.get()
        for table in (self.compare_table, self.games_table):
            table.delete(*table.get_children())
        self.me_button.configure(state="disabled" if player in (None, self.me) else "normal")
        if player is None:
            self.summary_var.set("No replays loaded yet")
            self.chart.set_data("", [], [], "{}")
            return

        self.games = games = player_games(self.records, player, mode)
        wins, losses = (games.result == "Win").sum(), (games.result == "Loss").sum()
        rate = f"  ·  {wins / (wins + losses):.0%} win rate" if wins + losses else ""
        self.summary_var.set(f"{len(games)} games  ·  {wins} W  {losses} L{rate}")

        headings, rows = comparison(games)
        for col, heading in zip(("c1", "c2", "c3", "c4"), headings):
            self.compare_table.heading(col, text=heading)
        for col, heading, values in rows:
            self.compare_table.insert("", "end", iid=col, values=(heading, *values))

        def fmt(value, pattern="{:.0f}"):
            return "-" if pd.isna(value) else pattern.format(value)

        for i, g in games.iloc[::-1].iterrows():
            self.games_table.insert("", "end", iid=str(i), values=(
                f"{g.played:%d %b %Y %H:%M}", g["mode"], g["map"], g.result, g.score_line,
                g.score, g.goals, g.assists, g.saves, g.shots,
                fmt(g.avg_speed), fmt(g.pct_behind_ball, "{:.1f}"), fmt(g.avg_boost),
            ))

        self.compare_table.selection_set(self.chart_stat)
        self.draw_chart()

    def on_stat_selected(self, event):
        selection = self.compare_table.selection()
        if selection and selection[0] != self.chart_stat:
            self.chart_stat = selection[0]
            self.draw_chart()

    def draw_chart(self):
        if self.games is None:
            return
        col, heading, fmt = next(s for s in PROGRESS_STATS if s[0] == self.chart_stat)
        games = self.games[self.games[col].notna()]  # e.g. frame stats of replays rrrocket couldn't decode
        values = [float(v) for v in games[col]]
        labels = [f"{g.played:%d %b %Y}\n{g.result} {g.score_line} · {g['map']}" for _, g in games.iterrows()]
        self.chart.set_data(heading, values, labels, fmt)

    def on_game_opened(self, event):
        row = self.games_table.identify_row(event.y)
        if row and self.games is not None:
            self.on_open_replay(self.games.loc[int(row), "path"])
