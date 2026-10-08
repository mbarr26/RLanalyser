// Trend chart: one stat per game (dots) with a rolling average (line) and a hover tooltip.
// Canvas port of the app's original Tkinter chart. The colours below are the dark chart chrome
// from the dataviz skill and match styles.css, so the chart reads as part of the same system.
// The data colour is the categorical blue (not the violet UI accent): colour in a chart means data.

const CHART = (() => {
  const ROLLING_GAMES = 5;
  const INK = "#f4f4f7";
  const INK_SECONDARY = "#b4b4c0";
  const GRID = "#26262d";
  const SURFACE = "#0d0d11";        // the card the canvas sits on
  const GAME_DOT = "#3987e5";       // categorical slot 1, dark-mode step
  const GAME_DOT_ALPHA = 0.6;       // de-emphasised against the average line
  const AVERAGE_LINE = "#3987e5";
  const AVERAGE_GLOW = "rgba(57, 135, 229, 0.75)";
  const AREA_TOP = "rgba(57, 135, 229, 0.30)";
  const TOOLTIP_BG = "#15151b";
  const TOOLTIP_BORDER = "rgba(255, 255, 255, 0.16)";
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

      // Rolling average (computed first so its area can sit under the dots)
      const average = [];
      let window_ = [];
      for (const [i, v] of points) {
        window_ = [...window_, v].slice(-ROLLING_GAMES);
        average.push([xOf(i), yOf(window_.reduce((a, b) => a + b, 0) / window_.length)]);
      }
      if (average.length > 1) {
        const fill = ctx.createLinearGradient(0, top, 0, bottom);
        fill.addColorStop(0, AREA_TOP);
        fill.addColorStop(1, "rgba(57, 135, 229, 0)");
        ctx.beginPath();
        ctx.moveTo(average[0][0], bottom);
        for (const [x, y] of average) ctx.lineTo(x, y);
        ctx.lineTo(average[average.length - 1][0], bottom);
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
      }

      // Dots (each game)
      for (const [i, v] of points) {
        const x = xOf(i), y = yOf(v);
        const hot = this.hoverIndex === i;
        ctx.save();
        if (hot) { ctx.shadowColor = AVERAGE_GLOW; ctx.shadowBlur = 14; }
        ctx.beginPath();
        ctx.arc(x, y, hot ? 6 : 4.5, 0, Math.PI * 2);
        ctx.globalAlpha = hot ? 1 : GAME_DOT_ALPHA;
        ctx.fillStyle = GAME_DOT;
        ctx.fill();
        ctx.restore();
        ctx.beginPath();
        ctx.arc(x, y, hot ? 6 : 4.5, 0, Math.PI * 2);
        ctx.lineWidth = 2;
        ctx.strokeStyle = hot ? INK : SURFACE;
        ctx.stroke();
        this.dots.push({ x, y, i });
      }

      // Rolling average line
      if (average.length > 1) {
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(average[0][0], average[0][1]);
        for (const [x, y] of average.slice(1)) ctx.lineTo(x, y);
        ctx.strokeStyle = AVERAGE_LINE;
        ctx.lineWidth = 2.25;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.shadowColor = AVERAGE_GLOW;
        ctx.shadowBlur = 10;
        ctx.stroke();
        ctx.restore();

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
      ctx.globalAlpha = GAME_DOT_ALPHA;
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    hideHover() {
      const tip = this._tip;
      if (tip) tip.style.display = "none";
      if (this.hoverIndex !== null && this.hoverIndex !== undefined) {
        this.hoverIndex = null;
        this.draw();
      }
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
      if (this.hoverIndex !== best.i) {
        this.hoverIndex = best.i;
        this.draw();
      }
      this.showHover(best, rect);
    }

    showHover(dot, rect) {
      if (!this._tip) {
        const tip = document.createElement("div");
        tip.style.cssText = `position:fixed;pointer-events:none;background:${TOOLTIP_BG};border:1px solid ${TOOLTIP_BORDER};` +
          `border-radius:8px;padding:7px 10px;font-size:11.5px;color:${INK};box-shadow:0 12px 32px -8px rgba(0,0,0,.85),0 0 0 1px rgba(124,58,237,.18);` +
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
