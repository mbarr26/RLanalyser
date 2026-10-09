// RL Analyser - page controller. Talks to the Python side through window.pywebview.api
// and receives push updates on window.app (called via window.evaluate_js from Python).
//
// Three views, switched by showView(): "home" (progress strip + replay tiles), "match" (the
// replay, stat tabs and the AI panel for one replay) and "progress" (the full progress page).

const state = {
  me: null,
  statGroups: {},
  progressStats: [],
  rankBands: [],        // rank names, lowest first
  rankModes: [],        // modes we have rank benchmark data for
  ranks: {},            // mode -> the rank the player chose
  records: new Map(),   // path -> record payload
  order: [],            // paths, in list order (newest first)
  view: "home",
  currentPath: null,    // the replay open in the match view
  analysing: new Set(),
  chartStat: "avg_speed",   // full progress page
  homeStat: "goals",        // home strip
  viewing: null,            // player id shown in the full progress page
  lastProgress: null,
  homeProgress: null,
  viewer: null,
  pendingSeek: null,        // a key-moment time to jump to once the viewer has loaded
  chart: null,
  homeChart: null,
  cardValues: {},           // home stat cards: the number last shown, so a change counts up
};

// Key stats on the home strip: [column, label, higher is better]
const HOME_STATS = [
  ["score", "Score", true],
  ["goals", "Goals", true],
  ["saves", "Saves", true],
  ["fifty_win_pct", "50/50 win %", true],
  ["pct_behind_ball", "% Behind ball", true],
  ["times_beaten", "Times beaten", false],
];

let homeDirty = false;
let progressDirty = false;
let lastRefresh = 0;
let viewerToken = 0;
let homeToken = 0;

const $ = id => document.getElementById(id);

// ---------- helpers ----------

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtPy(pattern, value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const m = pattern.match(/\.(\d+)f/);
  const digits = m ? parseInt(m[1], 10) : 0;
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtNum(v, digits = 0) {
  return v === null || v === undefined ? "-" : Number(v).toFixed(digits);
}

function computeResult(summary, me) {
  if (!me) return "";
  const mine = summary.players.find(p => p.player_id === me);
  if (!mine || summary.winningTeam === null || summary.winningTeam === undefined) return "";
  return summary.winningTeam === mine.team ? "Win" : "Loss";
}

function mean(values) {
  const v = values.filter(x => x !== null && x !== undefined && !Number.isNaN(x));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

// ---------- init ----------

async function init() {
  const meta = await pywebview.api.get_meta();
  state.me = meta.config.me;
  state.statGroups = meta.statGroups;
  state.progressStats = meta.progressStats;
  state.rankBands = meta.rankBands || [];
  state.rankModes = meta.rankModes || [];
  state.ranks = meta.config.ranks || {};
  if (meta.version) $("app-version").textContent = "v" + meta.version;
  $("folder-label").textContent = meta.config.replayDir || "No folder selected";
  state.chart = new CHART.TrendChart($("trend-chart"));
  state.homeChart = new CHART.TrendChart($("home-chart"));
  bindUi();
  await doRefresh();
  if (!meta.onboarded) welcome.start();
  setInterval(() => {
    if (Date.now() - lastRefresh < 2000) return;
    if (homeDirty && state.view === "home") reloadHome();
    else if (progressDirty && state.view === "progress") reloadProgressLists();
  }, 500);
}

if (window.pywebview) init(); else window.addEventListener("pywebviewready", init);

function bindUi() {
  $("choose-folder-btn").onclick = chooseFolder;
  $("refresh-btn").onclick = doRefresh;
  $("back-btn").onclick = goHome;
  document.querySelectorAll(".back-home").forEach(b => b.addEventListener("click", goHome));
  $("setup-btn").onclick = () => welcome.start();
  $("see-all-btn").onclick = () => { showView("progress"); reloadProgressLists(); };
  $("home-mode").addEventListener("change", loadHomeProgress);
  $("home-rank").addEventListener("change", async e => {
    const mode = $("home-mode").value;
    state.ranks = await pywebview.api.set_rank(mode, e.target.value || null);
    loadHomeProgress();
  });

  const grid = $("tile-grid");
  const openTile = e => {
    const tile = e.target.closest(".tile");
    if (tile && !tile.classList.contains("loading")) openMatch(tile.dataset.path);
  };
  grid.addEventListener("click", openTile);
  grid.addEventListener("keydown", e => { if (e.key === "Enter") openTile(e); });

  document.querySelectorAll(".sub-tab").forEach(btn => btn.addEventListener("click", () => switchSubTab(btn.dataset.sub)));
  $("player-select").addEventListener("change", e => {
    state.viewing = e.target.value || null;
    updateMeButton();
    loadProgress();
  });
  $("mode-select").addEventListener("change", loadProgress);
  $("me-btn").addEventListener("click", () => {
    if (state.viewing) pywebview.api.set_me(state.viewing);
  });
}

function showView(name) {
  state.view = name;
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === `view-${name}`));
  if (name !== "match") stopViewer();
}

function goHome() {
  state.currentPath = null;
  showView("home");
  homeDirty = true;
}

function switchSubTab(name) {
  document.querySelectorAll(".sub-tab").forEach(b => b.classList.toggle("active", b.dataset.sub === name));
  document.querySelectorAll(".sub-page").forEach(p => p.classList.toggle("active", p.id === `sub-${name}`));
}

// ---------- folder & replay tiles ----------

async function chooseFolder() {
  applyFolderResult(await pywebview.api.choose_folder());
}

async function doRefresh() {
  applyFolderResult(await pywebview.api.refresh());
}

function applyFolderResult(res) {
  $("folder-label").textContent = res.replayDir || "No folder selected";
  state.records = new Map();
  state.order = res.paths || [];
  state.analysing = new Set();
  if (state.view !== "home" && state.view !== "welcome") goHome();
  state.currentPath = null;
  renderTiles(true);
  homeDirty = progressDirty = true;
}

function tileHtml(path, index = -1) {
  const enter = index >= 0 ? ` enter" style="--i:${Math.min(index, 14)}` : "";
  const record = state.records.get(path);
  if (!record) {
    const stem = path.split(/[\\/]/).pop().replace(/\.replay$/i, "").slice(0, 26);
    return `<div class="tile loading pending${enter}" data-path="${escapeHtml(path)}">
      <div class="tile-top"><span>Loading&hellip;</span></div>
      <div class="tile-score">&nbsp;</div>
      <div class="tile-map">${escapeHtml(stem)}</div>
    </div>`;
  }
  const s = record.summary;
  const result = computeResult(s, state.me);
  const mine = state.me ? s.players.find(p => p.player_id === state.me) : null;
  const line = mine ? `${mine.goals} G &middot; ${mine.assists} A &middot; ${mine.saves} Sv &middot; ${mine.shots} Sh` : "&nbsp;";
  const status = record.error ? "No frame data" : record.analysed ? "" : "Analysing&hellip;";
  return `<div class="tile${record.analysed ? "" : " pending"}${enter}" data-path="${escapeHtml(path)}" data-result="${result}" tabindex="0" role="button">
    <div class="tile-top"><span>${escapeHtml(record.playedAt)}</span><span class="tile-result">${result ? result.toUpperCase() : ""}</span></div>
    <div class="tile-score"><span class="blue">${s.team0Score}</span><span class="vs">&ndash;</span><span class="orange">${s.team1Score}</span></div>
    <div class="tile-map">${escapeHtml(s.mapName)} &middot; ${s.teamSize}v${s.teamSize}</div>
    <div class="tile-line">${status || line}</div>
  </div>`;
}

function renderTiles(animate = false) {
  const grid = $("tile-grid");
  grid.innerHTML = state.order.length
    ? state.order.map((path, i) => tileHtml(path, animate ? i : -1)).join("")
    : '<div class="placeholder">No replays loaded yet</div>';
}

function updateTile(path) {
  const el = $("tile-grid").querySelector(`[data-path="${CSS.escape(path)}"]`);
  if (!el) { renderTiles(); return; }
  el.outerHTML = tileHtml(path);
}

// ---------- match view ----------

function openMatch(path, startTime) {
  const record = state.records.get(path);
  if (!record) return;
  state.currentPath = path;
  showView("match");
  renderMatchData(path);
  startViewer(path, startTime);
  coachUi.open(path);
}

// Header, scoreboard and stat tables; safe to call again when the record is updated.
function renderMatchData(path) {
  const record = state.records.get(path);
  if (!record) return;
  renderMatchHeader(record);
  clearStatTables();
  if (record.error) {
    setAnalysisNote(`Frame analysis failed: ${record.error}`);
  } else if (!record.analysed) {
    setAnalysisNote("Analysing frame data...");
    if (!state.analysing.has(path)) {
      state.analysing.add(path);
      pywebview.api.analyse_now(path);
    }
  } else {
    renderStatTables(record);
    setAnalysisNote("Frame stats count live play only (kickoffs included)");
  }
}

function setAnalysisNote(text) { $("analysis-note").textContent = text; }

function clearStatTables() {
  for (const group of Object.keys(state.statGroups)) {
    const body = document.querySelector(`#table-${group.toLowerCase()} tbody`);
    if (body) body.innerHTML = "";
  }
  $("match-kv").innerHTML = "";
}

function renderMatchHeader(record) {
  const s = record.summary;
  $("match-title").textContent = s.name;
  const mins = Math.floor(s.secondsPlayed / 60), secs = Math.floor(s.secondsPlayed % 60);
  $("match-subtitle").textContent =
    `${s.teamSize}v${s.teamSize} ${s.matchType}  ·  ${s.mapName}  ·  ${s.date}  ·  ${mins}:${String(secs).padStart(2, "0")}`;
  $("match-score").innerHTML =
    `<span class="team-blue">Blue ${s.team0Score}</span><span class="vs">&ndash;</span><span class="team-orange">${s.team1Score} Orange</span>`;
  renderScoreboard(s);
}

function teamRowHtml(team, name, cells) {
  const label = team === 0 ? "Blue" : "Orange";
  return `<tr><td><span class="team-tag"><span class="team-dot t${team}"></span>${label}</span></td><td>${escapeHtml(name)}</td>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`;
}

function renderScoreboard(summary) {
  const rows = [];
  for (const team of [0, 1]) {
    const players = summary.players.filter(p => p.team === team).sort((a, b) => b.score - a.score);
    for (const p of players) {
      let name = p.name + (p.is_bot ? " (bot)" : "");
      if (p.player_id === state.me) name += "  (you)";
      rows.push(teamRowHtml(team, name, [p.score, p.goals, p.assists, p.saves, p.shots]));
    }
  }
  document.querySelector("#scoreboard-table tbody").innerHTML = rows.join("");

  let blue = 0, orange = 0;
  const parts = [];
  for (const g of summary.goals) {
    if (g.team === 0) blue++; else orange++;
    parts.push(`${blue}-${orange}  ${escapeHtml(g.scorer)}`);
  }
  $("goals-line").innerHTML = parts.length
    ? "Goals:&nbsp;&nbsp;" + parts.join("&nbsp;&nbsp;&middot;&nbsp;&nbsp;")
    : "No goals";
}

function renderStatTables(record) {
  for (const [group, stats] of Object.entries(state.statGroups)) {
    const table = $(`table-${group.toLowerCase()}`);
    if (!table) continue;
    table.querySelector("thead").innerHTML =
      `<tr><th>Team</th><th>Player</th>${stats.map(([, h]) => `<th>${escapeHtml(h)}</th>`).join("")}</tr>`;
    const rows = Object.entries(record.players || {}).sort((a, b) => {
      if (a[1].team !== b[1].team) return a[1].team - b[1].team;
      return (b[1].avg_speed || 0) - (a[1].avg_speed || 0);
    });
    table.querySelector("tbody").innerHTML = rows
      .map(([name, row]) => teamRowHtml(row.team, name, stats.map(([col, , fmt]) => fmtPy(fmt, row[col]))))
      .join("");
  }
  renderMatchKv(record.match);
}

function renderMatchKv(match) {
  const el = $("match-kv");
  if (!match) { el.innerHTML = ""; return; }
  const mins = Math.floor(match.live_seconds / 60), secs = Math.floor(match.live_seconds % 60);
  const row = (k, v) => `<div class="k">${k}</div><div class="v">${v}</div>`;
  el.innerHTML = [
    row("Live play time", `${mins}:${String(secs).padStart(2, "0")}`),
    row("Ball avg speed", `${match.ball_avg_speed.toFixed(0)} uu/s`),
    '<div class="spacer"></div><div class="spacer"></div>',
    row("Ball in blue half", `${match.ball_pct_blue_half.toFixed(1)}%`),
    row("Ball in orange half", `${match.ball_pct_orange_half.toFixed(1)}%`),
    '<div class="spacer"></div><div class="spacer"></div>',
    row("Ball in blue third", `${match.ball_pct_blue_third.toFixed(1)}%`),
    row("Ball in middle third", `${match.ball_pct_mid_third.toFixed(1)}%`),
    row("Ball in orange third", `${match.ball_pct_orange_third.toFixed(1)}%`),
  ].join("");
}

// ---------- the embedded replay ----------

function resetViewerLabels() {
  for (const id of ["viewer-score", "viewer-clock", "viewer-state", "viewer-time"]) $(id).textContent = "";
  $("viewer-side").innerHTML = "";
}

function stopViewer() {
  viewerToken++;   // abandon a track that is still loading
  if (state.viewer) { state.viewer.destroy(); state.viewer = null; }
  state.pendingSeek = null;
}

async function startViewer(path, startTime) {
  stopViewer();
  resetViewerLabels();
  const token = viewerToken;
  const msg = $("viewer-msg");
  msg.textContent = "Loading replay…";
  if (typeof startTime === "number") state.pendingSeek = startTime;

  const track = await pywebview.api.get_track(path);
  if (token !== viewerToken || state.currentPath !== path) return;   // the user moved on
  if (track && track.error) {
    msg.textContent = `Can't show this replay: ${track.error}`;
    return;
  }
  msg.textContent = "";
  state.viewer = new PITCH.PitchViewer({
    canvas: $("pitch-canvas"),
    side: $("viewer-side"),
    score: $("viewer-score"),
    clock: $("viewer-clock"),
    state: $("viewer-state"),
    playBtn: $("viewer-play"),
    speedSel: $("viewer-speed"),
    skipChk: $("viewer-skip"),
    slider: $("viewer-slider"),
    time: $("viewer-time"),
  }, track, { autoplay: true });
  if (state.pendingSeek !== null) {
    state.viewer.seek(state.pendingSeek - 3);
    state.pendingSeek = null;
  }
}

// A key moment's Watch button: jump to a few seconds before it and play
function watchMoment(time) {
  if (!state.viewer) { state.pendingSeek = time; return; }
  state.viewer.seek(time - 3);
  if (!state.viewer.playing) state.viewer.togglePlay();
}

// ---------- home: progress strip ----------

function renderModeSelects() {
  const modes = [...new Set(
    [...state.records.values()].filter(r => r.summary).map(r => `${r.summary.teamSize}v${r.summary.teamSize}`)
  )].sort();
  for (const id of ["mode-select", "home-mode"]) {
    const sel = $(id);
    const current = sel.value || "All";
    sel.innerHTML = ["All", ...modes].map(m => `<option${m === current ? " selected" : ""}>${m}</option>`).join("");
  }
}

function reloadHome() {
  renderModeSelects();
  loadHomeProgress();
  homeAlerts.loadSession();
  lastRefresh = Date.now();
  homeDirty = false;
}

async function loadHomeProgress() {
  const token = ++homeToken;
  if (!state.me) {
    $("home-summary").innerHTML = '<span class="sub">Your stats appear here once replays have loaded</span>';
    $("home-cards").innerHTML = "";
    state.homeChart.setData("", [], [], v => v);
    return;
  }
  const mode = $("home-mode").value;
  renderRankPicker(mode);
  const data = await pywebview.api.get_progress(state.me, mode === "All" ? null : mode);
  if (token !== homeToken) return;
  state.homeProgress = data;
  renderRankNote(data.rank);
  const rate = (data.wins + data.losses) ? `  ·  ${Math.round(data.wins / (data.wins + data.losses) * 100)}% win rate` : "";
  const known = computeKnownPlayers().find(p => p.id === state.me);
  $("home-summary").innerHTML = data.count
    ? `${escapeHtml(known ? known.name : "You")} <span class="sub">&middot; ${data.count} games &middot; ${data.wins} W &middot; ${data.losses} L${rate}</span>`
    : '<span class="sub">No games for this mode yet</span>';
  renderHomeCards(data);
  drawHomeChart();
}

// The "Your rank" dropdown only appears for a single mode that we have benchmark data for.
function renderRankPicker(mode) {
  const wrap = $("home-rank-wrap");
  wrap.hidden = !state.rankModes.includes(mode);
  if (wrap.hidden) return;
  const chosen = state.ranks[mode] || "";
  $("home-rank").innerHTML = `<option value="">Not set</option>` +
    state.rankBands.map(b => `<option${b === chosen ? " selected" : ""}>${escapeHtml(b)}</option>`).join("");
}

function ordinalSuffix(n) {
  const v = n % 100;
  return (v >= 11 && v <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
}

// One line above the cards: the biggest gap to the chosen rank, and the best thing to point at.
function renderRankNote(rank) {
  const note = $("home-rank-note");
  note.hidden = !rank;
  if (!rank) return;
  const name = col => (statMeta(col) || [col, col])[1];
  const weak = rank.weaknesses[0], strong = rank.strengths[0];
  note.innerHTML = `Compared with typical <b>${escapeHtml(rank.band)}</b> players` +
    (weak ? ` &middot; <span class="bad">weakest: ${escapeHtml(name(weak))}</span>` : "") +
    (strong ? ` &middot; <span class="good">strongest: ${escapeHtml(name(strong))}</span>` : "");
}

function statMeta(col) {
  return state.progressStats.find(([c]) => c === col);
}

const REDUCED_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// A tiny trend line for the last 12 games. The stroke gradient uses user-space units because a
// perfectly flat line has no height, and a bounding-box gradient would not paint it at all.
function sparkline(values, id) {
  const v = values.filter(x => x !== null && x !== undefined && !Number.isNaN(x)).slice(-12);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const W = 100, H = 24, pad = 2;
  const pts = v.map((x, i) => [(i / (v.length - 1)) * W, H - pad - ((x - lo) / span) * (H - pad * 2)]);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <linearGradient id="sg-${id}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="${W}" y2="0">
        <stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#3987e5"/></linearGradient>
      <linearGradient id="sa-${id}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="${H}">
        <stop offset="0" stop-color="#7c3aed" stop-opacity=".38"/><stop offset="1" stop-color="#7c3aed" stop-opacity="0"/></linearGradient>
    </defs>
    <polygon class="area" points="0,${H} ${line} ${W},${H}" fill="url(#sa-${id})"/>
    <polyline class="line" points="${line}" stroke="url(#sg-${id})"/>
  </svg>`;
}

// Count a number up (or down) to its new value; a repeat render with the same value stays still.
function countTo(el, from, to, fmt) {
  if (REDUCED_MOTION || from === to) { el.textContent = fmtPy(fmt, to); return; }
  const start = performance.now(), duration = 650;
  const step = now => {
    const t = Math.min(1, (now - start) / duration);
    el.textContent = fmtPy(fmt, from + (to - from) * (1 - Math.pow(1 - t, 3)));
    if (t < 1 && el.isConnected) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderHomeCards(data) {
  const box = $("home-cards");
  box.innerHTML = "";
  for (const [col, label, higherIsBetter] of HOME_STATS) {
    const meta = statMeta(col);
    if (!meta) continue;
    const fmt = meta[2];
    const values = data.chart[col] || [];
    const all = mean(values), recent = mean(values.slice(-10));
    const shown = recent ?? all;
    const card = document.createElement("button");
    card.className = "stat-card" + (col === state.homeStat ? " selected" : "");
    let trend = all === null ? "" : `avg ${fmtPy(fmt, all)}`, trendClass = "";
    if (all !== null && recent !== null && values.length >= 3) {
      const diff = recent - all;
      const arrow = Math.abs(diff) < 1e-9 ? "" : diff > 0 ? "▲ " : "▼ ";
      trend = `${arrow}${fmtPy(fmt, Math.abs(diff))} vs avg ${fmtPy(fmt, all)}`;
      if (arrow) trendClass = (diff > 0) === higherIsBetter ? " good" : " bad";
    }
    const ranked = data.rank && data.rank.rows.find(r => r.stat === col);
    const rankLine = ranked
      ? `<div class="stat-rank" title="Where your last 10 games sit among ${escapeHtml(data.rank.band)} players">
           <span class="rank-bar"><i style="width:${ranked.percentile}%"></i></span>
           ${ranked.percentile}${ordinalSuffix(ranked.percentile)} pctl &middot; plays like ${escapeHtml(ranked.playsLike || "?")}</div>`
      : "";
    card.innerHTML = `<div class="stat-label">${escapeHtml(label)}</div>
      <div class="stat-value">${fmtPy(fmt, shown)}</div>
      <div class="stat-trend${trendClass}">${escapeHtml(trend)}</div>
      ${rankLine}
      ${sparkline(values, col)}`;
    card.title = `Last 10 games${higherIsBetter ? "" : " (lower is better)"} - click to chart`;
    if (shown !== null && shown !== undefined) {
      const previous = state.cardValues[col];
      countTo(card.querySelector(".stat-value"), previous ?? 0, shown, fmt);
      state.cardValues[col] = shown;
    }
    card.addEventListener("click", () => {
      state.homeStat = col;
      renderHomeCards(data);
      drawHomeChart();
    });
    box.appendChild(card);
  }
}

function drawHomeChart() {
  if (!state.homeProgress) return;
  const meta = statMeta(state.homeStat);
  if (!meta) return;
  const [, heading, fmt] = meta;
  state.homeChart.setData(
    heading, state.homeProgress.chart[state.homeStat] || [], state.homeProgress.chartLabels || [], v => fmtPy(fmt, v));
}

// ---------- full progress page ----------

function computeKnownPlayers() {
  const recs = [...state.records.values()]
    .filter(r => r.summary)
    .sort((a, b) => (a.playedAtIso || "").localeCompare(b.playedAtIso || ""));
  const counts = new Map(), latest = new Map();
  for (const r of recs) {
    for (const p of r.summary.players) {
      if (p.is_bot) continue;
      counts.set(p.player_id, (counts.get(p.player_id) || 0) + 1);
      latest.set(p.player_id, p.name);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([id, count]) => ({ id, name: latest.get(id), count }));
}

function renderPlayerSelect() {
  const players = computeKnownPlayers();
  state.knownPlayers = players;
  const sel = $("player-select");
  sel.innerHTML = players.map(p =>
    `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}  (${p.count} game${p.count !== 1 ? "s" : ""})${p.id === state.me ? "  - you" : ""}</option>`
  ).join("");
  if (!players.find(p => p.id === state.viewing)) {
    const meIn = players.find(p => p.id === state.me);
    state.viewing = meIn ? meIn.id : (players[0] ? players[0].id : null);
  }
  if (state.viewing) sel.value = state.viewing;
  updateMeButton();
}

function updateMeButton() {
  $("me-btn").disabled = !state.viewing || state.viewing === state.me;
}

function reloadProgressLists() {
  renderPlayerSelect();
  renderModeSelects();
  loadProgress();
  lastRefresh = Date.now();
  progressDirty = false;
}

async function loadProgress() {
  if (!state.viewing) {
    $("progress-summary").innerHTML = '<span class="sub">No replays loaded yet</span>';
    document.querySelector("#compare-table tbody").innerHTML = "";
    document.querySelector("#games-table tbody").innerHTML = "";
    state.chart.setData("", [], [], v => v);
    return;
  }
  const modeSel = $("mode-select").value;
  const data = await pywebview.api.get_progress(state.viewing, modeSel === "All" ? null : modeSel);
  state.lastProgress = data;
  renderProgressSummary(data);
  renderCompare(data.compare, state.viewing === state.me ? data.rank : null);
  renderGamesTable(data.games);
  drawChart();
}

function renderProgressSummary(data) {
  const rate = (data.wins + data.losses) ? `  ·  ${Math.round(data.wins / (data.wins + data.losses) * 100)}% win rate` : "";
  $("progress-summary").innerHTML = data.count
    ? `${data.count} games <span class="sub">&middot; ${data.wins} W &middot; ${data.losses} L${rate}</span>`
    : '<span class="sub">No games for this player/mode yet</span>';
}

function renderCompare(compare, rank) {
  const rankCols = rank ? [`${rank.band} median`, "Your percentile"] : [];
  document.querySelector("#compare-table thead tr").innerHTML =
    "<th>Stat</th>" + [...compare.headings, ...rankCols].map(h => `<th>${escapeHtml(h)}</th>`).join("");
  const tbody = document.querySelector("#compare-table tbody");
  tbody.innerHTML = "";
  for (const [col, heading, values] of compare.rows) {
    const tr = document.createElement("tr");
    tr.className = col === state.chartStat ? "selected" : "";
    const r = rank && rank.rows.find(x => x.stat === col);
    const extra = rank ? [r ? fmtPy(statMeta(col)[2], r.median) : "-", r ? `${r.percentile}${ordinalSuffix(r.percentile)}` : "-"] : [];
    tr.innerHTML = `<td>${escapeHtml(heading)}</td>` + [...values, ...extra].map(v => `<td>${escapeHtml(v)}</td>`).join("");
    tr.addEventListener("click", () => {
      state.chartStat = col;
      tbody.querySelectorAll("tr").forEach(r => r.classList.remove("selected"));
      tr.classList.add("selected");
      drawChart();
    });
    tbody.appendChild(tr);
  }
}

function renderGamesTable(games) {
  const tbody = document.querySelector("#games-table tbody");
  tbody.innerHTML = games.map(g => `
    <tr data-path="${escapeHtml(g.path)}">
      <td>${escapeHtml(g.played)}</td><td>${g.mode}</td><td style="text-align:left">${escapeHtml(g.map)}</td>
      <td>${g.result}</td><td>${g.scoreLine}</td>
      <td>${fmtNum(g.score)}</td><td>${fmtNum(g.goals)}</td><td>${fmtNum(g.assists)}</td><td>${fmtNum(g.saves)}</td><td>${fmtNum(g.shots)}</td>
      <td>${fmtNum(g.avgSpeed)}</td><td>${fmtNum(g.pctBehindBall, 1)}</td><td>${fmtNum(g.avgBoost)}</td>
    </tr>`).join("");
  tbody.querySelectorAll("tr").forEach(tr => tr.addEventListener("dblclick", () => openMatch(tr.dataset.path)));
}

function drawChart() {
  if (!state.lastProgress) return;
  const meta = statMeta(state.chartStat);
  if (!meta) return;
  const [, heading, fmt] = meta;
  const values = state.lastProgress.chart[state.chartStat] || [];
  const labels = state.lastProgress.chartLabels || [];
  state.chart.setData(heading, values, labels, v => fmtPy(fmt, v));
}

// ---------- pushes from Python ----------

window.app = {
  onRecord(payload) {
    if (!state.order.includes(payload.path)) state.order.unshift(payload.path);
    state.records.set(payload.path, payload);
    state.analysing.delete(payload.path);
    updateTile(payload.path);
    if (state.view === "match" && payload.path === state.currentPath) {
      renderMatchData(payload.path);
      coachUi.open(payload.path);   // no-op if already loaded; retries if it was waiting for the analysis
    }
    homeDirty = progressDirty = true;
    welcome.refresh();
  },
  onNewMatch(card) {
    homeAlerts.newMatch(card);
  },
  onStatus(text) {
    $("status").textContent = text;
  },
  onDone() {
    homeDirty = progressDirty = true;
    welcome.refresh();
  },
  onMe(me) {
    state.me = me;
    renderTiles();
    if (state.currentPath) {
      const r = state.records.get(state.currentPath);
      if (r) renderScoreboard(r.summary);
    }
    homeDirty = progressDirty = true;
    welcome.refresh();
    coachUi.invalidate();   // the coach talks to "you", so a new "you" means new findings
  },
  onError(message) {
    alert(message);
  },
  onAnalyseFailed(path, message) {
    state.analysing.delete(path);
    if (path === state.currentPath) setAnalysisNote(`Could not analyse replay: ${message}`);
  },
};
