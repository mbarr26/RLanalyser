// Share cards: draws a 1200x630 picture of a match or of your progress on a canvas and saves it as a PNG
// (and copies it to the clipboard when the browser lets us). Colours match the tokens in styles.css; a canvas
// can't read CSS variables, so they're repeated here.

const share = (() => {
  const W = 1200, H = 630;
  const INK = "#f4f4f7", SECONDARY = "#b4b4c0", MUTED = "#868695", ACCENT = "#a78bfa";
  const GOOD = "#4ade80", BAD = "#ec835a", SURFACE = "#15151b";
  const FONT = '"Segoe UI", system-ui, sans-serif';

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function text(ctx, str, x, y, size, color, weight = 400, align = "left") {
    ctx.font = `${weight} ${size}px ${FONT}`;
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.fillText(str, x, y);
  }

  // spec: { kicker, title, titleColour, subtitle, stats: [{ label, value, note, good }], footer }
  function draw(spec) {
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d");
    const bg = ctx.createLinearGradient(0, 0, W, H);
    bg.addColorStop(0, "#050507"); bg.addColorStop(1, "#1a1030");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    const glow = ctx.createRadialGradient(W - 120, 60, 10, W - 120, 60, 480);
    glow.addColorStop(0, "rgba(124,58,237,0.35)"); glow.addColorStop(1, "rgba(124,58,237,0)");
    ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);

    text(ctx, spec.kicker.toUpperCase(), 64, 82, 22, ACCENT, 600);
    text(ctx, spec.title, 64, 170, 84, spec.titleColour || INK, 700);
    text(ctx, spec.subtitle, 64, 218, 28, SECONDARY);

    const stats = spec.stats.slice(0, 6);
    const cols = Math.min(3, stats.length) || 1, gap = 20, cw = (W - 128 - gap * (cols - 1)) / cols, ch = 150;
    stats.forEach((s, i) => {
      const x = 64 + (i % cols) * (cw + gap), y = 262 + Math.floor(i / cols) * (ch + gap);
      ctx.fillStyle = SURFACE; roundRect(ctx, x, y, cw, ch, 18); ctx.fill();
      text(ctx, s.label, x + 24, y + 38, 22, SECONDARY);
      text(ctx, s.value, x + 24, y + 98, 56, s.good === false ? BAD : s.good ? GOOD : INK, 700);
      if (s.note) text(ctx, s.note, x + 24, y + 132, 20, MUTED);
    });

    text(ctx, spec.footer || "", 64, H - 30, 20, MUTED);
    text(ctx, "RL Analyser", W - 64, H - 30, 22, ACCENT, 600, "right");
    return canvas;
  }

  async function output(canvas, name) {
    const url = canvas.toDataURL("image/png");
    const saved = await pywebview.api.save_file(name, url);
    if (saved && saved.error) { $("status").textContent = saved.error; return; }
    let copied = false;
    try {
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      copied = true;
    } catch (e) { /* clipboard images aren't available everywhere; the saved file is enough */ }
    if (saved) $("status").textContent = `Saved ${saved.path}${copied ? " and copied to the clipboard" : ""}`;
  }

  function match(path) {
    const record = state.records.get(path);
    if (!record || !state.me) { $("status").textContent = "Pick which player you are first (This is me)"; return; }
    const s = record.summary, me = s.players.find(p => p.player_id === state.me);
    if (!me) { $("status").textContent = "You weren't in this match"; return; }
    const result = computeResult(s, state.me);
    const frame = (record.players || {})[me.name] || {};
    const stats = [
      { label: "Goals", value: String(me.goals) }, { label: "Assists", value: String(me.assists) },
      { label: "Saves", value: String(me.saves) },
    ];
    for (const [col, label] of [["pct_behind_ball", "% Behind ball"], ["avg_speed", "Avg speed"], ["touches", "Touches"]]) {
      const meta = statMeta(col);
      if (frame[col] !== undefined && frame[col] !== null && meta) stats.push({ label, value: fmtPy(meta[2], frame[col]) });
    }
    const mine = me.team === 0 ? s.team0Score : s.team1Score, theirs = me.team === 0 ? s.team1Score : s.team0Score;
    const canvas = draw({
      kicker: `${me.name} · ${s.teamSize}v${s.teamSize}`,
      title: `${result ? result.toUpperCase() + " " : ""}${mine}–${theirs}`,
      titleColour: result === "Win" ? GOOD : result === "Loss" ? BAD : INK,
      subtitle: `${s.mapName} · ${record.playedAt}`, stats, footer: "Analysed on my own PC",
    });
    output(canvas, `rl-match-${path.split(/[\\/]/).pop().replace(/\.replay$/i, "").slice(0, 24)}.png`);
  }

  function progress() {
    const d = state.homeProgress;
    if (!d || !d.count) { $("status").textContent = "No games to share yet"; return; }
    const known = computeKnownPlayers().find(p => p.id === state.me);
    const rate = (d.wins + d.losses) ? Math.round(d.wins / (d.wins + d.losses) * 100) : 0;
    const stats = HOME_STATS.map(([col, label, higher]) => {
      const meta = statMeta(col), values = (d.chart[col] || []);
      const recent = mean(values.slice(-10)), all = mean(values);
      if (!meta || recent === null) return null;
      const ranked = d.rank && d.rank.rows.find(r => r.stat === col);
      const diff = all === null ? 0 : recent - all;
      return {
        label, value: fmtPy(meta[2], recent),
        note: ranked ? `${ranked.percentile}${ordinalSuffix(ranked.percentile)} percentile for ${d.rank.band}` : "last 10 games",
        good: ranked ? ranked.percentile >= 50 : Math.abs(diff) < 1e-9 ? undefined : (diff > 0) === higher,
      };
    }).filter(Boolean);
    const mode = $("home-mode").value;
    const canvas = draw({
      kicker: `${known ? known.name : "My"} progress${mode !== "All" ? " · " + mode : ""}`,
      title: `${rate}% wins`, subtitle: `${d.count} games · ${d.wins} W · ${d.losses} L`, stats,
      footer: d.rank ? `Compared with ${d.rank.band} players` : "Last 10 games",
    });
    output(canvas, "rl-progress.png");
  }

  return { match, progress };
})();
