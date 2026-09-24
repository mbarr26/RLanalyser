// Watch match: top-down 2D playback. Canvas port of the app's original Tkinter pitch viewer.
// Pitch geometry is Unreal units (standard soccar); blue defends -y, orange defends +y.

const PITCH = (() => {
  const HALF_WIDTH = 4096, HALF_LENGTH = 5120, CORNER_CUT = 1152;
  const GOAL_HALF_WIDTH = 893, GOAL_DEPTH = 880, CENTRE_CIRCLE = 1000;
  const THIRD_LINE = HALF_LENGTH / 3;
  const BALL_RADIUS = 93, CAR_RADIUS = 110, HEADING_LENGTH = 260;
  const BALL_TRAIL_SECONDS = 1.5, GOAL_REPLAY_KEEP = 2.0;
  const BIG_PADS = [[-3584, 0], [3584, 0], [-3072, 4096], [3072, 4096], [-3072, -4096], [3072, -4096]];

  const TEAM_COLOURS = { 0: "#2a78d6", 1: "#eb6834" };
  const TEAM_LIGHT = { 0: "#a9c9f2", 1: "#f3bd98" };
  const PITCH_BG = "#111110";
  const PITCH_LINE = "rgba(255,255,255,0.34)";
  const SPEEDS = ["0.25x", "0.5x", "1x", "2x", "4x", "8x"];
  const FRAME_MS = 16;

  class MatchTrack {
    constructor(track) {
      this.times = track.times;
      this.states = track.states;
      this.clock = track.clock;
      this.ball = track.ball;          // [[x,y,z]|null, ...]
      this.players = track.players;    // [{name, team, data: [[x,y,z,yaw,boost,speed]|null,...]}]
      this.goals = track.goals;        // [[frame, team, scorer], ...]
      this.dead = track.dead;          // [[start,end], ...]
    }

    get start() { return this.times[0]; }
    get end() { return this.times[this.times.length - 1]; }

    indexAt(t) {
      // Rightmost insertion point minus one, clamped.
      let lo = 0, hi = this.times.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (this.times[mid] <= t) lo = mid + 1; else hi = mid;
      }
      return Math.min(Math.max(lo - 1, 0), this.times.length - 1);
    }

    interp(arr, i, t) {
      const a = arr[i];
      if (a === null) return null;
      if (i + 1 >= this.times.length) return a;
      const b = arr[i + 1];
      if (b === null) return a;
      const span = this.times[i + 1] - this.times[i];
      const alpha = span > 0 ? (t - this.times[i]) / span : 0;
      return a.map((v, k) => v + (b[k] - v) * alpha);
    }

    ballAt(t) { return this.interp(this.ball, this.indexAt(t), t); }

    playerAt(player, t) {
      const i = this.indexAt(t);
      const row = this.interp(player.data, i, t);
      if (row && player.data[i]) row[3] = player.data[i][3]; // don't interpolate yaw across +/-pi wrap
      return row;
    }

    scoreAt(i) {
      let blue = 0, orange = 0;
      for (const [frame, team] of this.goals) {
        if (frame <= i) { if (team === 0) blue++; else orange++; }
      }
      return [blue, orange];
    }

    lastGoalBefore(i, within) {
      for (let k = this.goals.length - 1; k >= 0; k--) {
        const [frame, team, scorer] = this.goals[k];
        if (frame <= i && this.times[i] - this.times[frame] <= within) return { team, scorer };
      }
      return null;
    }

    skipDead(t) {
      for (const [start, end] of this.dead) {
        if (start <= t && t < end) return end;
      }
      return t;
    }
  }

  class PitchViewer {
    constructor(els, track) {
      this.canvas = els.canvas;
      this.ctx = this.canvas.getContext("2d");
      this.sideEl = els.side;
      this.scoreEl = els.score;
      this.clockEl = els.clock;
      this.stateEl = els.state;
      this.playBtn = els.playBtn;
      this.speedSel = els.speedSel;
      this.skipChk = els.skipChk;
      this.slider = els.slider;
      this.timeEl = els.time;

      this.track = new MatchTrack(track);
      this.t = this.track.start;
      this.playing = false;
      this.dragging = false;
      this.lastTick = null;
      this.rafId = null;

      this.slider.min = this.track.start;
      this.slider.max = this.track.end;
      this.slider.value = this.t;

      this.buildSide();
      this.resizeObserver = new ResizeObserver(() => this.render());
      this.resizeObserver.observe(this.canvas);

      this.playBtn.onclick = () => this.togglePlay();
      this.slider.addEventListener("mousedown", () => { this.dragging = true; });
      this.slider.addEventListener("input", () => {
        if (this.dragging) { this.t = parseFloat(this.slider.value); this.render(); }
      });
      this.slider.addEventListener("mouseup", () => { this.dragging = false; this.seek(parseFloat(this.slider.value)); });

      this.onKey = (e) => {
        if (e.code === "Space") { e.preventDefault(); this.togglePlay(); }
        else if (e.code === "ArrowLeft") this.seek(this.t - 5);
        else if (e.code === "ArrowRight") this.seek(this.t + 5);
      };
      window.addEventListener("keydown", this.onKey);

      this.render();
      this.tick();
    }

    destroy() {
      this.playing = false;
      if (this.rafId) cancelAnimationFrame(this.rafId);
      this.resizeObserver.disconnect();
      window.removeEventListener("keydown", this.onKey);
    }

    buildSide() {
      this.sideEl.innerHTML = "";
      this.rows = [];
      const order = [...this.track.players].sort((a, b) => a.team - b.team);
      for (const player of order) {
        const row = document.createElement("div");
        row.className = "side-row";
        row.innerHTML = `
          <div class="side-name" style="color:${TEAM_LIGHT[player.team]}">${escapeHtml(player.name)}</div>
          <div class="side-bar"><div class="side-bar-fill"></div></div>
          <div class="side-info"></div>`;
        this.sideEl.appendChild(row);
        this.rows.push({ player, fill: row.querySelector(".side-bar-fill"), info: row.querySelector(".side-info") });
      }
    }

    layout() {
      const rect = this.canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(rect.width, 100), h = Math.max(rect.height, 100);
      if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
        this.canvas.width = Math.round(w * dpr);
        this.canvas.height = Math.round(h * dpr);
      }
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const totalLen = 2 * (HALF_LENGTH + GOAL_DEPTH), totalWid = 2 * HALF_WIDTH;
      this.scale = Math.min((w - 20) / totalLen, (h - 20) / totalWid);
      this.cx = w / 2; this.cy = h / 2;
      this.w = w; this.h = h;
    }

    toCanvas(x, y) { return [this.cx + y * this.scale, this.cy - x * this.scale]; }

    render() {
      this.layout();
      const c = this.ctx;
      c.clearRect(0, 0, this.w, this.h);
      c.fillStyle = "#0a0a0a";
      c.fillRect(0, 0, this.w, this.h);

      // Pitch outline (octagon)
      const outline = [
        [HALF_WIDTH, -HALF_LENGTH + CORNER_CUT], [HALF_WIDTH, HALF_LENGTH - CORNER_CUT],
        [HALF_WIDTH - CORNER_CUT, HALF_LENGTH], [-HALF_WIDTH + CORNER_CUT, HALF_LENGTH],
        [-HALF_WIDTH, HALF_LENGTH - CORNER_CUT], [-HALF_WIDTH, -HALF_LENGTH + CORNER_CUT],
        [-HALF_WIDTH + CORNER_CUT, -HALF_LENGTH], [HALF_WIDTH - CORNER_CUT, -HALF_LENGTH],
      ];
      c.beginPath();
      outline.forEach(([x, y], i) => {
        const [px, py] = this.toCanvas(x, y);
        i === 0 ? c.moveTo(px, py) : c.lineTo(px, py);
      });
      c.closePath();
      c.fillStyle = PITCH_BG;
      c.fill();
      c.strokeStyle = PITCH_LINE;
      c.lineWidth = 2;
      c.stroke();

      // Goals
      for (const [team, sign] of [[0, -1], [1, 1]]) {
        const [x0, y0] = this.toCanvas(GOAL_HALF_WIDTH, sign * HALF_LENGTH);
        const [x1, y1] = this.toCanvas(-GOAL_HALF_WIDTH, sign * (HALF_LENGTH + GOAL_DEPTH));
        c.fillStyle = TEAM_COLOURS[team] + "33";
        c.strokeStyle = TEAM_COLOURS[team];
        c.lineWidth = 2;
        c.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
        c.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
      }

      // Halfway + thirds
      c.strokeStyle = PITCH_LINE;
      c.lineWidth = 2;
      c.beginPath();
      c.moveTo(...this.toCanvas(HALF_WIDTH, 0));
      c.lineTo(...this.toCanvas(-HALF_WIDTH, 0));
      c.stroke();
      c.setLineDash([4, 7]);
      for (const y of [-THIRD_LINE, THIRD_LINE]) {
        c.beginPath();
        c.moveTo(...this.toCanvas(HALF_WIDTH, y));
        c.lineTo(...this.toCanvas(-HALF_WIDTH, y));
        c.stroke();
      }
      c.setLineDash([]);

      // Centre circle
      c.beginPath();
      c.arc(this.cx, this.cy, CENTRE_CIRCLE * this.scale, 0, Math.PI * 2);
      c.stroke();

      // Boost pads
      const pad = 130 * this.scale;
      c.fillStyle = "rgba(255,255,255,0.75)";
      for (const [x, y] of BIG_PADS) {
        const [px, py] = this.toCanvas(x, y);
        c.beginPath();
        c.arc(px, py, pad, 0, Math.PI * 2);
        c.fill();
      }

      this.renderMoving();
    }

    renderMoving() {
      const c = this.ctx, track = this.track, t = this.t;
      const i = track.indexAt(t);

      // Ball trail + shadow + ball
      const ballXY = track.ballAt(t);
      if (ballXY) {
        const [bx, by, bz] = ballXY;
        const [px, py] = this.toCanvas(bx, by);
        const shadowR = Math.max(BALL_RADIUS * this.scale, 4);
        const r = shadowR * (1 + Math.max(bz - BALL_RADIUS, 0) / 1500);

        const first = track.indexAt(t - BALL_TRAIL_SECONDS);
        const pts = [];
        for (let k = first; k <= i; k++) {
          const p = track.ball[k];
          if (p) pts.push(this.toCanvas(p[0], p[1]));
        }
        pts.push([px, py]);
        if (pts.length >= 2) {
          c.beginPath();
          c.moveTo(...pts[0]);
          for (const p of pts.slice(1)) c.lineTo(...p);
          c.strokeStyle = "rgba(255,255,255,0.35)";
          c.lineWidth = 2;
          c.stroke();
        }

        c.beginPath();
        c.arc(px, py, shadowR, 0, Math.PI * 2);
        c.fillStyle = "rgba(0,0,0,0.55)";
        c.fill();
        c.beginPath();
        c.arc(px, py, r, 0, Math.PI * 2);
        c.fillStyle = "#ffffff";
        c.fill();
        c.strokeStyle = "rgba(0,0,0,0.4)";
        c.lineWidth = 1;
        c.stroke();
      }

      // Cars
      const carR = Math.max(CAR_RADIUS * this.scale, 5);
      for (const player of track.players) {
        const row = track.playerAt(player, t);
        if (!row) continue;
        const [x, y, z, yaw] = row;
        const [px, py] = this.toCanvas(x, y);
        const r = carR * (1 + Math.max(z - 20, 0) / 2500);
        const hx = x + HEADING_LENGTH * Math.cos(yaw), hy = y + HEADING_LENGTH * Math.sin(yaw);
        const [hpx, hpy] = this.toCanvas(hx, hy);

        c.beginPath();
        c.arc(px, py, r, 0, Math.PI * 2);
        c.fillStyle = TEAM_COLOURS[player.team];
        c.fill();
        c.strokeStyle = "#ffffff";
        c.lineWidth = 1.5;
        c.stroke();
        c.beginPath();
        c.moveTo(px, py);
        c.lineTo(hpx, hpy);
        c.strokeStyle = "#ffffff";
        c.lineWidth = 3;
        c.stroke();

        c.font = "700 11px var(--font, 'Segoe UI'), sans-serif";
        c.textAlign = "center";
        c.fillStyle = TEAM_LIGHT[player.team];
        c.fillText(player.name, px, py - r - 8);
      }

      // Side panel
      for (const { player, fill, info } of this.rows) {
        const row = track.playerAt(player, t);
        if (!row) {
          fill.style.width = "0%";
          info.textContent = track.states[i] === "Active" ? "demolished" : "";
        } else {
          const [, , , , boost, speed] = row;
          fill.style.width = Math.max(0, Math.min(100, boost)) + "%";
          info.textContent = `boost ${boost.toFixed(0).padStart(3)}   speed ${speed.toFixed(0).padStart(4)}`;
        }
      }

      // Header
      const [blue, orange] = track.scoreAt(i);
      this.scoreEl.innerHTML = `<span style="color:${TEAM_COLOURS[0]}">Blue ${blue}</span> &ndash; <span style="color:${TEAM_COLOURS[1]}">${orange} Orange</span>`;
      const clock = track.clock[i];
      this.clockEl.textContent = clock === null ? "" : `${Math.floor(clock / 60)}:${String(clock % 60).padStart(2, "0")}`;
      const state = track.states[i];
      const goal = track.lastGoalBefore(i, GOAL_REPLAY_KEEP + 1);
      if (goal && (state === "PostGoalScored" || state === "ReplayPlayback")) {
        this.stateEl.textContent = `GOAL — ${goal.scorer}`;
        this.stateEl.style.color = TEAM_COLOURS[goal.team];
      } else {
        this.stateEl.textContent = { Countdown: "Kickoff", ReplayPlayback: "Goal replay" }[state] || "";
        this.stateEl.style.color = "#eda100";
      }

      const elapsed = t - track.start, total = track.end - track.start;
      this.timeEl.textContent = `${fmtClock(elapsed)} / ${fmtClock(total)}`;
      if (!this.dragging) this.slider.value = t;
    }

    togglePlay() {
      if (this.t >= this.track.end) this.t = this.track.start;
      this.playing = !this.playing;
      this.lastTick = performance.now();
      this.playBtn.textContent = this.playing ? "Pause" : "Play";
    }

    seek(t) {
      this.t = Math.min(Math.max(t, this.track.start), this.track.end);
      this.slider.value = this.t;
      this.render();
    }

    tick() {
      const now = performance.now();
      if (this.playing && !this.dragging) {
        const speed = parseFloat(this.speedSel.value);
        this.t += ((now - (this.lastTick || now)) / 1000) * speed;
        if (this.skipChk.checked) this.t = this.track.skipDead(this.t);
        if (this.t >= this.track.end) {
          this.t = this.track.end;
          this.playing = false;
          this.playBtn.textContent = "Play";
        }
        this.render();
      }
      this.lastTick = now;
      this.rafId = requestAnimationFrame(() => this.tick());
    }
  }

  function fmtClock(s) {
    s = Math.max(0, Math.floor(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  return { MatchTrack, PitchViewer, SPEEDS };
})();
