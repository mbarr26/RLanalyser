"""Top-down 2D playback of a match: every player and the ball moving on the pitch in real time."""

import math
import sys
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

from frame_data import BIG_PADS, GameFrames, load_game_frames

# Pitch geometry in Unreal units (standard soccar)
HALF_WIDTH = 4096        # x
HALF_LENGTH = 5120       # y; blue defends -y, orange defends +y
CORNER_CUT = 1152
GOAL_HALF_WIDTH = 893
GOAL_DEPTH = 880
CENTRE_CIRCLE = 1000
THIRD_LINE = HALF_LENGTH / 3
BALL_RADIUS = 93
CAR_RADIUS = 110
HEADING_LENGTH = 260
BALL_TRAIL_SECONDS = 1.5
GOAL_REPLAY_KEEP = 2.0   # when skipping replays, still show this many seconds after a goal

TEAM_COLOURS = {0: "#3b82f6", 1: "#f97316"}
TEAM_LIGHT = {0: "#bfdbfe", 1: "#fed7aa"}
PITCH_BG = "#1f3a2b"
PITCH_LINE = "#5f8f73"
SPEEDS = ["0.25x", "0.5x", "1x", "2x", "4x", "8x"]
FRAME_MS = 16


class MatchTrack:
    """Frame data rearranged into per-frame arrays for fast lookup at any playback time."""

    def __init__(self, game: GameFrames, goals=()):
        frames = game.frames
        self.times = frames.time.to_numpy()
        self.states = frames.state.to_numpy()
        self.clock = frames.seconds_remaining.to_numpy()
        n = len(frames)

        self.ball = np.full((n, 3), np.nan)
        self.ball[game.ball.frame.to_numpy()] = game.ball[["x", "y", "z"]].to_numpy()

        p = game.players
        yaw = np.arctan2(2 * (p.qw * p.qz + p.qx * p.qy), 1 - 2 * (p.qy ** 2 + p.qz ** 2))
        p = p.assign(yaw=yaw)
        self.players = []
        for (team, name), g in p.groupby(["team", "player"]):
            data = np.full((n, 6), np.nan)
            data[g.frame.to_numpy()] = g[["x", "y", "z", "yaw", "boost", "speed"]].to_numpy(dtype=float)
            self.players.append({"name": name, "team": int(team), "data": data})

        self.goals = [(g.frame, g.team, g.scorer) for g in goals]

        # Stretches after goals (post-goal celebration + replay) that "skip replays" jumps over
        self.dead = []
        dead = np.isin(self.states, ["PostGoalScored", "ReplayPlayback"])
        i = 0
        while i < n:
            if dead[i]:
                j = i
                while j < n and dead[j]:
                    j += 1
                start = self.times[i] + GOAL_REPLAY_KEEP
                end = self.times[j] if j < n else self.times[-1]
                if end > start:
                    self.dead.append((start, end))
                i = j
            else:
                i += 1

    @property
    def start(self):
        return float(self.times[0])

    @property
    def end(self):
        return float(self.times[-1])

    def index_at(self, t):
        return int(np.clip(np.searchsorted(self.times, t, side="right") - 1, 0, len(self.times) - 1))

    def _interp(self, arr, i, t):
        """Linear interpolation between frame i and i+1 (falls back to frame i across gaps)."""
        a = arr[i]
        if i + 1 >= len(self.times):
            return a
        b = arr[i + 1]
        if np.isnan(b).any():
            return a
        span = self.times[i + 1] - self.times[i]
        alpha = (t - self.times[i]) / span if span > 0 else 0.0
        return a + (b - a) * alpha

    def ball_at(self, t):
        i = self.index_at(t)
        return self._interp(self.ball, i, t)

    def player_at(self, player, t):
        i = self.index_at(t)
        row = self._interp(player["data"], i, t)
        row[3] = player["data"][i, 3]  # don't interpolate yaw across the +/-pi wrap
        return row

    def score_at(self, i):
        blue = sum(1 for frame, team, _ in self.goals if frame <= i and team == 0)
        orange = sum(1 for frame, team, _ in self.goals if frame <= i and team == 1)
        return blue, orange

    def last_goal_before(self, i, within):
        for frame, team, scorer in reversed(self.goals):
            if frame <= i and self.times[i] - self.times[frame] <= within:
                return team, scorer
        return None

    def skip_dead(self, t):
        for start, end in self.dead:
            if start <= t < end:
                return end
        return t


class PitchViewer(tk.Toplevel):
    def __init__(self, master, game: GameFrames, goals=(), title="Match viewer"):
        super().__init__(master)
        self.title(title)
        self.geometry("1150x700")
        self.configure(bg="#111")

        self.track = MatchTrack(game, goals)
        self.t = self.track.start
        self.playing = False
        self.dragging = False
        self.last_tick = None

        self._build_ui()
        self.bind("<space>", lambda e: self.toggle_play())
        self.bind("<Left>", lambda e: self.seek(self.t - 5))
        self.bind("<Right>", lambda e: self.seek(self.t + 5))
        self.after(50, self.toggle_play)
        self.tick()

    # ---------- layout ----------

    def _build_ui(self):
        top = tk.Frame(self, bg="#111")
        top.pack(fill="x", padx=10, pady=(8, 0))
        self.score_var = tk.StringVar()
        self.clock_var = tk.StringVar()
        self.state_var = tk.StringVar()
        tk.Label(top, textvariable=self.score_var, fg="white", bg="#111", font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(top, textvariable=self.clock_var, fg="white", bg="#111", font=("Consolas", 18, "bold")).pack(side="left", padx=24)
        self.state_label = tk.Label(top, textvariable=self.state_var, fg="#facc15", bg="#111", font=("Segoe UI", 15, "bold"))
        self.state_label.pack(side="left")

        middle = tk.Frame(self, bg="#111")
        middle.pack(fill="both", expand=True, padx=10, pady=8)

        self.canvas = tk.Canvas(middle, bg="#111", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_pitch())

        side = tk.Frame(middle, bg="#111", width=230)
        side.pack(side="right", fill="y", padx=(10, 0))
        side.pack_propagate(False)
        self.player_rows = []
        for team in (0, 1):
            for player in (p for p in self.track.players if p["team"] == team):
                row = tk.Frame(side, bg="#111")
                row.pack(fill="x", pady=4)
                tk.Label(row, text=player["name"], fg=TEAM_LIGHT[team], bg="#111", anchor="w",
                         font=("Segoe UI", 10, "bold")).pack(fill="x")
                bar = tk.Canvas(row, height=12, bg="#333", highlightthickness=0)
                bar.pack(fill="x")
                fill = bar.create_rectangle(0, 0, 0, 12, fill=TEAM_COLOURS[team], width=0)
                info = tk.StringVar()
                tk.Label(row, textvariable=info, fg="#aaa", bg="#111", anchor="w", font=("Consolas", 9)).pack(fill="x")
                self.player_rows.append((player, bar, fill, info))

        controls = tk.Frame(self, bg="#111")
        controls.pack(fill="x", padx=10, pady=(0, 10))
        self.play_button = tk.Button(controls, text="Play", width=7, command=self.toggle_play)
        self.play_button.pack(side="left")
        self.speed_var = tk.StringVar(value="1x")
        ttk.Combobox(controls, textvariable=self.speed_var, values=SPEEDS, width=6, state="readonly").pack(side="left", padx=6)
        self.skip_var = tk.BooleanVar(value=True)
        tk.Checkbutton(controls, text="Skip goal replays", variable=self.skip_var, fg="white", bg="#111",
                       selectcolor="#333", activebackground="#111", activeforeground="white").pack(side="left", padx=6)
        self.time_var = tk.StringVar()
        tk.Label(controls, textvariable=self.time_var, fg="#aaa", bg="#111", font=("Consolas", 10)).pack(side="right")

        self.slider_var = tk.DoubleVar(value=self.t)
        self.slider = ttk.Scale(controls, from_=self.track.start, to=self.track.end, variable=self.slider_var,
                                command=self._on_slider)
        self.slider.pack(side="left", fill="x", expand=True, padx=10)
        self.slider.bind("<ButtonPress-1>", lambda e: setattr(self, "dragging", True))
        self.slider.bind("<ButtonRelease-1>", self._on_slider_release)

    # ---------- coordinates ----------

    def _layout(self):
        """Fit the pitch (plus goals) to the canvas. Field y runs left->right, field x bottom->top."""
        w, h = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        total_len = 2 * (HALF_LENGTH + GOAL_DEPTH)
        total_wid = 2 * HALF_WIDTH
        self.scale = min((w - 20) / total_len, (h - 20) / total_wid)
        self.cx, self.cy = w / 2, h / 2

    def to_canvas(self, x, y):
        return self.cx + y * self.scale, self.cy - x * self.scale

    # ---------- drawing ----------

    def _draw_pitch(self):
        self._layout()
        c = self.canvas
        c.delete("all")

        outline = [
            (HALF_WIDTH, -HALF_LENGTH + CORNER_CUT), (HALF_WIDTH, HALF_LENGTH - CORNER_CUT),
            (HALF_WIDTH - CORNER_CUT, HALF_LENGTH), (-HALF_WIDTH + CORNER_CUT, HALF_LENGTH),
            (-HALF_WIDTH, HALF_LENGTH - CORNER_CUT), (-HALF_WIDTH, -HALF_LENGTH + CORNER_CUT),
            (-HALF_WIDTH + CORNER_CUT, -HALF_LENGTH), (HALF_WIDTH - CORNER_CUT, -HALF_LENGTH),
        ]
        c.create_polygon([v for x, y in outline for v in self.to_canvas(x, y)], fill=PITCH_BG, outline=PITCH_LINE, width=2)

        for team, sign in ((0, -1), (1, 1)):
            x0, y0 = self.to_canvas(GOAL_HALF_WIDTH, sign * HALF_LENGTH)
            x1, y1 = self.to_canvas(-GOAL_HALF_WIDTH, sign * (HALF_LENGTH + GOAL_DEPTH))
            c.create_rectangle(x0, y0, x1, y1, fill=TEAM_COLOURS[team], stipple="gray50", outline=TEAM_COLOURS[team], width=2)

        c.create_line(*self.to_canvas(HALF_WIDTH, 0), *self.to_canvas(-HALF_WIDTH, 0), fill=PITCH_LINE, width=2)
        for y in (-THIRD_LINE, THIRD_LINE):
            c.create_line(*self.to_canvas(HALF_WIDTH, y), *self.to_canvas(-HALF_WIDTH, y), fill=PITCH_LINE, dash=(4, 6))
        r = CENTRE_CIRCLE * self.scale
        c.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r, outline=PITCH_LINE, width=2)
        pad = 160 * self.scale
        for x, y in BIG_PADS:
            px, py = self.to_canvas(x, y)
            c.create_oval(px - pad, py - pad, px + pad, py + pad, fill="#eab308", outline="")

        # Moving items, repositioned every tick
        self.trail = c.create_line(0, 0, 0, 0, fill="#ffffff", width=2, stipple="gray50", smooth=True)
        self.car_items = []
        for player in self.track.players:
            colour = TEAM_COLOURS[player["team"]]
            body = c.create_oval(0, 0, 0, 0, fill=colour, outline="white", width=1)
            nose = c.create_line(0, 0, 0, 0, fill="white", width=3)
            label = c.create_text(0, 0, text=player["name"], fill=TEAM_LIGHT[player["team"]], font=("Segoe UI", 9, "bold"))
            self.car_items.append((player, body, nose, label))
        self.ball_shadow = c.create_oval(0, 0, 0, 0, fill="#0b1f14", outline="")
        self.ball_item = c.create_oval(0, 0, 0, 0, fill="white", outline="#999")
        self._render()

    def _render(self):
        if not hasattr(self, "ball_item"):
            return
        c, track, t = self.canvas, self.track, self.t
        i = track.index_at(t)

        # Ball: shadow on the floor, ball grows with height
        bx, by, bz = track.ball_at(t)
        if np.isnan(bx):
            for item in (self.ball_item, self.ball_shadow, self.trail):
                c.itemconfigure(item, state="hidden")
        else:
            px, py = self.to_canvas(bx, by)
            shadow = max(BALL_RADIUS * self.scale, 4)
            r = shadow * (1 + max(bz - BALL_RADIUS, 0) / 1500)
            c.coords(self.ball_shadow, px - shadow, py - shadow, px + shadow, py + shadow)
            c.coords(self.ball_item, px - r, py - r, px + r, py + r)
            c.itemconfigure(self.ball_item, state="normal")
            c.itemconfigure(self.ball_shadow, state="normal")

            first = track.index_at(t - BALL_TRAIL_SECONDS)
            pts = [v for x, y in track.ball[first:i + 1, :2] if not np.isnan(x) for v in self.to_canvas(x, y)]
            pts += [px, py]
            if len(pts) >= 4:
                c.coords(self.trail, *pts)
                c.itemconfigure(self.trail, state="normal")
            else:
                c.itemconfigure(self.trail, state="hidden")

        # Cars (hidden while demolished)
        car_r = max(CAR_RADIUS * self.scale, 5)
        for player, body, nose, label in self.car_items:
            x, y, z, yaw, boost, speed = track.player_at(player, t)
            if np.isnan(x):
                for item in (body, nose, label):
                    c.itemconfigure(item, state="hidden")
                continue
            px, py = self.to_canvas(x, y)
            r = car_r * (1 + max(z - 20, 0) / 2500)
            hx, hy = self.to_canvas(x + HEADING_LENGTH * math.cos(yaw), y + HEADING_LENGTH * math.sin(yaw))
            c.coords(body, px - r, py - r, px + r, py + r)
            c.coords(nose, px, py, hx, hy)
            c.coords(label, px, py - r - 9)
            for item in (body, nose, label):
                c.itemconfigure(item, state="normal")
        c.tag_raise(self.ball_shadow)
        c.tag_raise(self.ball_item)

        # Side panel: boost + speed
        for player, bar, fill, info in self.player_rows:
            _, _, _, _, boost, speed = track.player_at(player, t)
            width = bar.winfo_width()
            if np.isnan(boost):
                bar.coords(fill, 0, 0, 0, 12)
                info.set("demolished" if track.states[i] == "Active" else "")
            else:
                bar.coords(fill, 0, 0, width * boost / 100, 12)
                info.set(f"boost {boost:3.0f}   speed {speed:4.0f}")

        # Header: score, clock, phase
        blue, orange = track.score_at(i)
        self.score_var.set(f"Blue {blue} – {orange} Orange")
        clock = track.clock[i]
        self.clock_var.set("" if clock is None or np.isnan(clock) else f"{int(clock) // 60}:{int(clock) % 60:02d}")
        state = track.states[i]
        goal = track.last_goal_before(i, within=GOAL_REPLAY_KEEP + 1)
        if goal and state in ("PostGoalScored", "ReplayPlayback"):
            team, scorer = goal
            self.state_var.set(f"GOAL — {scorer}")
            self.state_label.configure(fg=TEAM_COLOURS[team])
        else:
            self.state_var.set({"Countdown": "Kickoff", "ReplayPlayback": "Goal replay"}.get(state, ""))
            self.state_label.configure(fg="#facc15")

        elapsed, total = t - track.start, track.end - track.start
        self.time_var.set(f"{int(elapsed) // 60}:{int(elapsed) % 60:02d} / {int(total) // 60}:{int(total) % 60:02d}")

    # ---------- playback ----------

    def toggle_play(self):
        if self.t >= self.track.end:
            self.t = self.track.start
        self.playing = not self.playing
        self.last_tick = time.perf_counter()
        self.play_button.configure(text="Pause" if self.playing else "Play")

    def seek(self, t):
        self.t = float(np.clip(t, self.track.start, self.track.end))
        self.slider_var.set(self.t)
        self._render()

    def _on_slider(self, value):
        if self.dragging:
            self.t = float(value)
            self._render()

    def _on_slider_release(self, event):
        self.dragging = False
        self.seek(self.slider_var.get())

    def tick(self):
        if not self.winfo_exists():
            return
        now = time.perf_counter()
        if self.playing and not self.dragging:
            speed = float(self.speed_var.get().rstrip("x"))
            self.t += (now - (self.last_tick or now)) * speed
            if self.skip_var.get():
                self.t = self.track.skip_dead(self.t)
            if self.t >= self.track.end:
                self.t = self.track.end
                self.playing = False
                self.play_button.configure(text="Play")
            self.slider_var.set(self.t)
            self._render()
        self.last_tick = now
        self.after(FRAME_MS, self.tick)


if __name__ == "__main__":
    # Standalone: python pitch_viewer.py path\to\file.replay
    from replay_parser import parse_replay

    path = sys.argv[1]
    root = tk.Tk()
    root.withdraw()
    viewer = PitchViewer(root, load_game_frames(path), parse_replay(path).goals, title=path)
    viewer.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
