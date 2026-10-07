// RL Analyser - page controller. Talks to the Python side through window.pywebview.api
// and receives push updates on window.app (called via window.evaluate_js from Python).

const state = {
  me: null,
  statGroups: {},
  progressStats: [],
  records: new Map(),   // path -> record payload
  order: [],            // paths, in list order (newest first)
  currentPath: null,
  analysing: new Set(),
  chartStat: "avg_speed",
  viewing: null,         // player id shown in "My progress"
  lastProgress: null,
  viewer: null,
  chart: null,
};

let progressDirty = false;
let lastProgressRefresh = 0;

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

// ---------- init ----------

async function init() {
  const meta = await pywebview.api.get_meta();
  state.me = meta.config.me;
  state.statGroups = meta.statGroups;
  state.progressStats = meta.progressStats;
  document.getElementById("folder-label").textContent = meta.config.replayDir || "No folder selected";
  state.chart = new CHART.TrendChart(document.getElementById("trend-chart"));
  bindUi();
  await doRefresh();
  setInterval(() => {
    if (progressDirty && isProgressActive() && Date.now() - lastProgressRefresh > 2000) {
      reloadProgressLists();
    }
  }, 500);
}

if (window.pywebview) init(); else window.addEventListener("pywebviewready", init);

function bindUi() {
  document.getElementById("choose-folder-btn").onclick = chooseFolder;
  document.getElementById("refresh-btn").onclick = doRefresh;
  document.querySelectorAll(".page-tab").forEach(btn => btn.addEventListener("click", () => {
    switchPage(btn.dataset.page);
    if (btn.dataset.page === "progress") reloadProgressLists();
  }));
  document.querySelectorAll(".sub-tab").forEach(btn => btn.addEventListener("click", () => switchSubTab(btn.dataset.sub)));
  document.getElementById("player-select").addEventListener("change", e => {
    state.viewing = e.target.value || null;
    updateMeButton();
    loadProgress();
  });
  document.getElementById("mode-select").addEventListener("change", loadProgress);
  document.getElementById("me-btn").addEventListener("click", () => {
    if (state.viewing) pywebview.api.set_me(state.viewing);
  });
  document.getElementById("watch-btn").addEventListener("click", openViewer);
  document.getElementById("viewer-close").addEventListener("click", closeViewer);
}

function switchPage(name) {
  document.querySelectorAll(".page-tab").forEach(b => b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.id === `page-${name}`));
}

function switchSubTab(name) {
  document.querySelectorAll(".sub-tab").forEach(b => b.classList.toggle("active", b.dataset.sub === name));
  document.querySelectorAll(".sub-page").forEach(p => p.classList.toggle("active", p.id === `sub-${name}`));
  if (name === "coach" && state.currentPath) coachUi.open(state.currentPath);
}

function isProgressActive() {
  return document.getElementById("page-progress").classList.contains("active");
}

// ---------- folder & replay list ----------

async function chooseFolder() {
  applyFolderResult(await pywebview.api.choose_folder());
}

async function doRefresh() {
  applyFolderResult(await pywebview.api.refresh());
}

function applyFolderResult(res) {
  document.getElementById("folder-label").textContent = res.replayDir || "No folder selected";
  state.records = new Map();
  state.order = res.paths || [];
  state.currentPath = null;
  state.analysing = new Set();
  showMatchEmpty("Select a replay to see its stats");
  renderReplayList();
  if (state.order.length) selectReplay(state.order[0]); // newest replay
  progressDirty = true;
}

function replayRowHtml(path) {
  const record = state.records.get(path);
  const selected = path === state.currentPath ? " selected" : "";
  if (!record) {
    const stem = path.split(/[\\/]/).pop().replace(/\.replay$/i, "").slice(0, 26);
    return `<div class="replay-row pending${selected}" data-path="${escapeHtml(path)}">
      <div class="replay-result"></div>
      <div class="replay-info"><div class="replay-date">Loading&hellip;</div>
      <div class="replay-meta"><span class="replay-map">${escapeHtml(stem)}</span></div></div>
    </div>`;
  }
  const s = record.summary;
  const result = computeResult(s, state.me);
  const pending = record.analysed ? "" : " pending";
  return `<div class="replay-row${pending}${selected}" data-path="${escapeHtml(path)}" data-result="${result}">
    <div class="replay-result"></div>
    <div class="replay-info">
      <div class="replay-date">${escapeHtml(record.playedAt)}</div>
      <div class="replay-meta">
        <span class="replay-map">${escapeHtml(s.mapName)}</span>
        <span class="replay-mode">${s.teamSize}v${s.teamSize}</span>
      </div>
      <div class="replay-score">
        ${s.team0Score}&ndash;${s.team1Score}
        ${result ? `<span class="replay-result-tag">&nbsp;&middot;&nbsp;${result}</span>` : ""}
      </div>
    </div>
  </div>`;
}

function renderReplayList() {
  const container = document.getElementById("replay-list");
  if (!state.order.length) {
    container.innerHTML = '<div class="placeholder">No replays loaded yet</div>';
    return;
  }
  container.innerHTML = state.order.map(replayRowHtml).join("");
  bindReplayRowClicks();
}

function bindReplayRowClicks() {
  document.querySelectorAll("#replay-list .replay-row").forEach(el => {
    el.addEventListener("click", () => selectReplay(el.dataset.path));
  });
}

function updateReplayRow(path) {
  const container = document.getElementById("replay-list");
  const el = container.querySelector(`[data-path="${CSS.escape(path)}"]`);
  if (!el) { renderReplayList(); return; }
  el.outerHTML = replayRowHtml(path);
  container.querySelector(`[data-path="${CSS.escape(path)}"]`).addEventListener("click", () => selectReplay(path));
}

function selectReplay(path) {
  const container = document.getElementById("replay-list");
  const prev = container.querySelector(".replay-row.selected");
  if (prev) prev.classList.remove("selected");
  const el = container.querySelector(`[data-path="${CSS.escape(path)}"]`);
  if (el) el.classList.add("selected");
  state.currentPath = path;
  showReplay(path);
}

// ---------- match detail ----------

function showMatchEmpty(text) {
  document.getElementById("match-content").style.display = "none";
  const empty = document.getElementById("match-empty");
  empty.style.display = "block";
  empty.textContent = text;
}

function showReplay(path) {
  const record = state.records.get(path);
  if (!record) { showMatchEmpty("Loading…"); return; }
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
  if (coachUi.isActive()) coachUi.open(path);
}

function setAnalysisNote(text) { document.getElementById("analysis-note").textContent = text; }

function clearStatTables() {
  ["movement", "positioning", "boost"].forEach(id => {
    document.querySelector(`#table-${id} tbody`).innerHTML = "";
  });
  document.getElementById("match-kv").innerHTML = "";
}

function renderMatchHeader(record) {
  document.getElementById("match-empty").style.display = "none";
  document.getElementById("match-content").style.display = "flex";
  const s = record.summary;
  document.getElementById("match-title").textContent = s.name;
  const mins = Math.floor(s.secondsPlayed / 60), secs = Math.floor(s.secondsPlayed % 60);
  document.getElementById("match-subtitle").textContent =
    `${s.teamSize}v${s.teamSize} ${s.matchType}  ·  Map: ${s.mapName}  ·  ${s.date}  ·  Length: ${mins}:${String(secs).padStart(2, "0")}`;
  document.getElementById("match-score").innerHTML =
    `<span class="team-blue">Blue ${s.team0Score}</span><span class="vs">&ndash;</span><span class="team-orange">${s.team1Score} Orange</span>`;
  renderScoreboard(s);
  const watchBtn = document.getElementById("watch-btn");
  watchBtn.disabled = !!record.error;
  watchBtn.textContent = "Watch match";
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
  document.getElementById("goals-line").innerHTML = parts.length
    ? "Goals:&nbsp;&nbsp;" + parts.join("&nbsp;&nbsp;&middot;&nbsp;&nbsp;")
    : "No goals";
}

function renderStatTables(record) {
  for (const [group, stats] of Object.entries(state.statGroups)) {
    const table = document.getElementById(`table-${group.toLowerCase()}`);
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
  const el = document.getElementById("match-kv");
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

// ---------- watch match ----------

async function openViewer(startTime) {
  if (!state.currentPath) return;
  const btn = document.getElementById("watch-btn");
  btn.disabled = true;
  btn.textContent = "Loading…";
  document.getElementById("viewer-overlay").classList.add("active");

  const track = await pywebview.api.get_track(state.currentPath);
  if (track && track.error) {
    alert(track.error);
    document.getElementById("viewer-overlay").classList.remove("active");
  } else {
    if (state.viewer) state.viewer.destroy();
    state.viewer = new PITCH.PitchViewer({
      canvas: document.getElementById("pitch-canvas"),
      side: document.getElementById("viewer-side"),
      score: document.getElementById("viewer-score"),
      clock: document.getElementById("viewer-clock"),
      state: document.getElementById("viewer-state"),
      playBtn: document.getElementById("viewer-play"),
      speedSel: document.getElementById("viewer-speed"),
      skipChk: document.getElementById("viewer-skip"),
      slider: document.getElementById("viewer-slider"),
      time: document.getElementById("viewer-time"),
    }, track);
    // Jumping in from an AI Coach moment: start a few seconds before it, paused
    if (typeof startTime === "number") state.viewer.seek(startTime - 3);
  }
  btn.textContent = "Watch match";
  const record = state.records.get(state.currentPath);
  btn.disabled = !!(record && record.error);
}

function closeViewer() {
  document.getElementById("viewer-overlay").classList.remove("active");
  if (state.viewer) { state.viewer.destroy(); state.viewer = null; }
}

// ---------- my progress ----------

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
  const sel = document.getElementById("player-select");
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

function renderModeSelect() {
  const modes = [...new Set(
    [...state.records.values()].filter(r => r.summary).map(r => `${r.summary.teamSize}v${r.summary.teamSize}`)
  )].sort();
  const sel = document.getElementById("mode-select");
  const current = sel.value || "All";
  sel.innerHTML = ["All", ...modes].map(m => `<option${m === current ? " selected" : ""}>${m}</option>`).join("");
}

function updateMeButton() {
  document.getElementById("me-btn").disabled = !state.viewing || state.viewing === state.me;
}

function reloadProgressLists() {
  renderPlayerSelect();
  renderModeSelect();
  loadProgress();
  lastProgressRefresh = Date.now();
  progressDirty = false;
}

async function loadProgress() {
  if (!state.viewing) {
    document.getElementById("progress-summary").innerHTML = '<span class="sub">No replays loaded yet</span>';
    document.querySelector("#compare-table tbody").innerHTML = "";
    document.querySelector("#games-table tbody").innerHTML = "";
    state.chart.setData("", [], [], v => v);
    return;
  }
  const modeSel = document.getElementById("mode-select").value;
  const data = await pywebview.api.get_progress(state.viewing, modeSel === "All" ? null : modeSel);
  state.lastProgress = data;
  renderProgressSummary(data);
  renderCompare(data.compare);
  renderGamesTable(data.games);
  drawChart();
}

function renderProgressSummary(data) {
  const rate = (data.wins + data.losses) ? `  ·  ${Math.round(data.wins / (data.wins + data.losses) * 100)}% win rate` : "";
  document.getElementById("progress-summary").innerHTML = data.count
    ? `${data.count} games <span class="sub">&middot; ${data.wins} W &middot; ${data.losses} L${rate}</span>`
    : '<span class="sub">No games for this player/mode yet</span>';
}

function renderCompare(compare) {
  document.querySelector("#compare-table thead tr").innerHTML =
    "<th>Stat</th>" + compare.headings.map(h => `<th>${escapeHtml(h)}</th>`).join("");
  const tbody = document.querySelector("#compare-table tbody");
  tbody.innerHTML = "";
  for (const [col, heading, values] of compare.rows) {
    const tr = document.createElement("tr");
    tr.className = col === state.chartStat ? "selected" : "";
    tr.innerHTML = `<td>${escapeHtml(heading)}</td>` + values.map(v => `<td>${escapeHtml(v)}</td>`).join("");
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
  tbody.querySelectorAll("tr").forEach(tr => tr.addEventListener("dblclick", () => openReplay(tr.dataset.path)));
}

function drawChart() {
  if (!state.lastProgress) return;
  const meta = state.progressStats.find(([c]) => c === state.chartStat);
  if (!meta) return;
  const [, heading, fmt] = meta;
  const values = state.lastProgress.chart[state.chartStat] || [];
  const labels = state.lastProgress.chartLabels || [];
  state.chart.setData(heading, values, labels, v => fmtPy(fmt, v));
}

function openReplay(path) {
  switchPage("matches");
  selectReplay(path);
  const el = document.querySelector(`#replay-list [data-path="${CSS.escape(path)}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

// ---------- pushes from Python ----------

window.app = {
  onRecord(payload) {
    if (!state.order.includes(payload.path)) state.order.unshift(payload.path);
    state.records.set(payload.path, payload);
    state.analysing.delete(payload.path);
    updateReplayRow(payload.path);
    if (payload.path === state.currentPath) showReplay(payload.path);
    progressDirty = true;
  },
  onStatus(text) {
    document.getElementById("status").textContent = text;
  },
  onDone() {
    progressDirty = true;
  },
  onMe(me) {
    state.me = me;
    renderReplayList();
    if (state.currentPath) {
      const r = state.records.get(state.currentPath);
      if (r) renderScoreboard(r.summary);
    }
    progressDirty = true;
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
