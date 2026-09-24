// Trend chart: one stat per game (dots) with a rolling average (line) and a hover tooltip.
// Canvas port of the app's original Tkinter chart. Tokens match styles.css / analysis chrome
// so the chart reads as part of the same system (see dataviz skill's chart-chrome tokens).

const CHART = (() => {
  const ROLLING_GAMES = 5;
  const INK = "#0b0b0b";
  const INK_SECONDARY = "#52514e";
  const GRID = "#e1e0d9";
  const SURFACE = "#ffffff";
  const GAME_DOT = "#86b6ef";     // sequential step 250 - de-emphasised
  const AVERAGE_LINE = "#2a78d6"; // categorical slot 1 - the accent
  const PAD_LEFT = 54, PAD_RIGHT = 20, PAD_TOP = 40, PAD_BOTTOM = 32;

  function niceTicks(lo, hi, count = 5) {
    if (hi <= lo) { lo -= 1; hi += 1; }
    const raw = (hi - lo) / count;
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= raw);
    const start = Math.floor(lo / step) * step;
    const ticks = [start];
    while (ticks[ticks.length - 1] < hi - 1e-9) ticks.push(ticks[ticks.length - 1] + step);
    return { ticks, step };
  }

  class TrendChart {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.title = "";
      this.values = [];
      this.labels = [];
      this.fmt = v => String(v);
      this.dots = [];
      this.dpr = window.devicePixelRatio || 1;

      new ResizeObserver(() => this.draw()).observe(canvas);
      canvas.addEventListener("mousemove", e => this.onMotion(e));
      canvas.addEventListener("mouseleave", () => this.hideHover());
    }

    setData(title, values, labels, fmt) {
      this.title = title;
      this.values = values;
      this.labels = labels;
      this.fmt = fmt;
      this.draw();
    }

    size() {
      const rect = this.canvas.getBoundingClientRect();
      const width = Math.max(rect.width, 50);
      const height = Math.max(rect.height || 260, 200);
      const dpr = window.devicePixelRatio || 1;
      if (this.canvas.width !== Math.round(width * dpr) || this.canvas.height !== Math.round(height * dpr)) {
        this.canvas.width = Math.round(width * dpr);
        this.canvas.height = Math.round(height * dpr);
      }
      this.canvas.style.height = height + "px";
      this.dpr = dpr;
      return { width, height };
    }

    draw() {
      const { width, height } = this.size();
      const ctx = this.ctx;
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = SURFACE;
      ctx.fillRect(0, 0, width, height);
      this.dots = [];

      ctx.textBaseline = "middle";
      ctx.fillStyle = INK;
      ctx.font = "700 12.5px var(--font, 'Segoe UI'), sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(this.title, PAD_LEFT, 16);

      const points = this.values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined && !Number.isNaN(v));
      if (!points.length) {
        ctx.fillStyle = INK_SECONDARY;
        ctx.textAlign = "center";
        ctx.font = "12px var(--font, 'Segoe UI'), sans-serif";
        ctx.fillText("No data for this stat yet", width / 2, height / 2);
        return;
      }

      this.drawLegend(width);

      const vals = points.map(([, v]) => v);
      const { ticks, step } = niceTicks(Math.min(...vals), Math.max(...vals));
      const lo = ticks[0], hi = ticks[ticks.length - 1];
      const left = PAD_LEFT, right = width - PAD_RIGHT;
      const top = PAD_TOP, bottom = height - PAD_BOTTOM;
      const count = this.values.length;

      const xOf = i => count === 1 ? (left + right) / 2 : left + (right - left) * i / (count - 1);
      const yOf = v => bottom - (bottom - top) * (v - lo) / (hi - lo);

      const tickFmt = Number.isInteger(step) ? v => v.toLocaleString(undefined, { maximumFractionDigits: 0 })
                                              : v => v.toLocaleString(undefined, { maximumFractionDigits: 1 });

      ctx.strokeStyle = GRID;
      ctx.lineWidth = 1;
      ctx.fillStyle = INK_SECONDARY;
      ctx.font = "11px var(--font, 'Segoe UI'), sans-serif";
      ctx.textAlign = "right";
      for (const tick of ticks) {
        const y = yOf(tick);
        ctx.beginPath();
        ctx.moveTo(left, y + 0.5);
        ctx.lineTo(right, y + 0.5);
        ctx.stroke();
        ctx.fillText(tickFmt(tick), left - 8, y);
      }

      // Date labels at the ends of the x axis
      ctx.fillStyle = INK_SECONDARY;
      ctx.font = "11px var(--font, 'Segoe UI'), sans-serif";
      const first = (this.labels[0] || "").split("\n")[0];
      const last = (this.labels[this.labels.length - 1] || "").split("\n")[0];
      ctx.textAlign = "left";
      ctx.fillText(first, left, bottom + 18);
      if (count > 1) {
        ctx.textAlign = "right";
        ctx.fillText(last, right, bottom + 18);
      }

      // Dots (each game)
      for (const [i, v] of points) {
        const x = xOf(i), y = yOf(v);
        ctx.beginPath();
        ctx.arc(x, y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = GAME_DOT;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = SURFACE;
        ctx.stroke();
        this.dots.push({ x, y, i });
      }

      // Rolling average line
      const average = [];
      let window_ = [];
      for (const [i, v] of points) {
        window_ = [...window_, v].slice(-ROLLING_GAMES);
        average.push([xOf(i), yOf(window_.reduce((a, b) => a + b, 0) / window_.length)]);
      }
      if (average.length > 1) {
        ctx.beginPath();
        ctx.moveTo(average[0][0], average[0][1]);
        for (const [x, y] of average.slice(1)) ctx.lineTo(x, y);
        ctx.strokeStyle = AVERAGE_LINE;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.stroke();

        const [ex, ey] = average[average.length - 1];
        const latest = window_.reduce((a, b) => a + b, 0) / window_.length;
        ctx.beginPath();
        ctx.arc(ex, ey, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = AVERAGE_LINE;
        ctx.fill();
        ctx.strokeStyle = SURFACE;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = INK;
        ctx.font = "700 11px var(--font, 'Segoe UI'), sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(this.fmt(latest), ex - 8, ey - 12);
      }
    }

    drawLegend(width) {
      const ctx = this.ctx;
      const y = 16;
      ctx.font = "11px var(--font, 'Segoe UI'), sans-serif";
      ctx.fillStyle = INK_SECONDARY;
      ctx.textAlign = "right";
      let x = width - PAD_RIGHT;
      const label = `${ROLLING_GAMES}-game average`;
      ctx.fillText(label, x, y);
      x -= ctx.measureText(label).width + 6;
      ctx.beginPath();
      ctx.moveTo(x - 18, y);
      ctx.lineTo(x, y);
      ctx.strokeStyle = AVERAGE_LINE;
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.stroke();
      x -= 34;
      ctx.fillText("Each game", x, y);
      const w2 = ctx.measureText("Each game").width;
      x -= w2 + 10;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = GAME_DOT;
      ctx.fill();
    }

    hideHover() {
      const tip = this._tip;
      if (tip) tip.style.display = "none";
    }

    onMotion(e) {
      if (!this.dots.length) return;
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      let best = null, bestDist = Infinity;
      for (const d of this.dots) {
        const dist = Math.abs(d.x - mx);
        if (dist < bestDist) { bestDist = dist; best = d; }
      }
      if (!best || bestDist > 16) { this.hideHover(); return; }
      this.showHover(best, rect);
    }

    showHover(dot, rect) {
      if (!this._tip) {
        const tip = document.createElement("div");
        tip.style.cssText = "position:fixed;pointer-events:none;background:#fff;border:1px solid #e1e0d9;" +
          "border-radius:6px;padding:6px 9px;font-size:11.5px;color:#0b0b0b;box-shadow:0 6px 16px -4px rgba(11,11,11,.18);" +
          "white-space:pre;z-index:100;line-height:1.5;";
        document.body.appendChild(tip);
        this._tip = tip;
      }
      const tip = this._tip;
      const text = `${this.labels[dot.i]}\n${this.title}: ${this.fmt(this.values[dot.i])}`;
      tip.textContent = text;
      tip.style.display = "block";
      let left = rect.left + dot.x + 12;
      const top = rect.top + dot.y - 10;
      if (left + tip.offsetWidth + 8 > window.innerWidth) left = rect.left + dot.x - tip.offsetWidth - 12;
      tip.style.left = left + "px";
      tip.style.top = Math.max(4, top) + "px";
    }
  }

  return { TrendChart, niceTicks };
})();
