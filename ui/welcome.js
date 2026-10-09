// First-run guide (also opened by the title bar's "Setup guide"): replay folder -> who you are ->
// your rank -> what we found. Plus the Home cards for the game you just played and tonight's session.
// Uses the globals from app.js (state, $, escapeHtml, ...).

const welcome = (() => {
  let step = 0;
  let pickedMe = null;
  let touched = false;            // has the user chosen a player themselves?
  let findingsToken = 0;

  const AUTOSAVE_TIP = `<p class="sub">Rocket League only keeps replays if <b>Auto-save replays</b> is on:
    <b>Settings &rarr; Gameplay &rarr; Auto-save replays</b>. Turn it on, play a match, and it appears here by itself.</p>`;

  function steps() {
    return ["Replays", "You", ...(state.rankModes.length ? ["Rank"] : []), "Your game"];
  }

  function start() {
    step = 0;
    touched = false;
    pickedMe = state.me;
    showView("welcome");
    render();
  }

  function refresh() {            // replays are still loading in the background; redraw the step that shows them
    if (state.view === "welcome" && step <= 1) render();
  }

  function next() { step++; render(); }

  async function finish(openLatest) {
    await pywebview.api.finish_onboarding();
    if (openLatest) {
      const latest = state.order.find(p => (state.records.get(p) || {}).analysed);
      if (latest) { openMatch(latest); return; }
    }
    goHome();
  }

  function render() {
    const names = steps();
    $("welcome-steps").innerHTML = names.map((n, i) =>
      `<span class="welcome-step${i === step ? " active" : i < step ? " done" : ""}"><i>${i < step ? "&check;" : i + 1}</i>${n}</span>`).join("");
    const body = $("welcome-body");
    const name = names[step];
    if (name === "Replays") renderFolder(body);
    else if (name === "You") renderMe(body);
    else if (name === "Rank") renderRank(body);
    else renderFindings(body);
  }

  function renderFolder(body) {
    const count = state.order.length;
    body.innerHTML = `<h2>Welcome to RL Analyser</h2>
      <p>Your replays, analysed by a coach that runs on your own PC. First, where are your replays?</p>
      <div class="welcome-folder"><span class="field-label">Folder</span> <b>${escapeHtml($("folder-label").textContent)}</b></div>
      ${count
        ? `<p class="good">&check; Found ${count} replay${count === 1 ? "" : "s"}.</p>`
        : `<p class="bad">No replays in that folder yet.</p>${AUTOSAVE_TIP}`}
      <div class="welcome-actions">
        <button class="btn" id="w-choose">Choose a different folder&hellip;</button>
        <button class="btn" id="w-recheck">Check again</button>
        <button class="btn btn-primary" id="w-next">${count ? "Continue" : "Continue anyway"}</button>
      </div>
      ${count ? AUTOSAVE_TIP : ""}`;
    $("w-choose").onclick = async () => { await chooseFolder(); showView("welcome"); render(); };
    $("w-recheck").onclick = async () => { await doRefresh(); showView("welcome"); render(); };
    $("w-next").onclick = next;
  }

  function renderMe(body) {
    const players = computeKnownPlayers().slice(0, 8);
    if (!touched && players.length) pickedMe = state.me || players[0].id;
    body.innerHTML = `<h2>Which player are you?</h2>
      <p>Pick yourself so every stat is about <b>you</b>. We've guessed from your replays; change it if it's wrong.</p>
      ${players.length ? `<div class="welcome-list">${players.map(p => `
        <label class="welcome-option"><input type="radio" name="w-me" value="${escapeHtml(p.id)}"${p.id === pickedMe ? " checked" : ""}>
          <span>${escapeHtml(p.name)}</span><span class="sub">${p.count} game${p.count === 1 ? "" : "s"}</span></label>`).join("")}</div>`
        : '<p class="sub">No players yet &mdash; the folder is empty or replays are still loading. You can continue and set this later with <b>This is me</b> on the progress page.</p>'}
      <div class="welcome-actions">
        <button class="btn" id="w-back">Back</button>
        <button class="btn btn-primary" id="w-next">Continue</button>
      </div>`;
    body.querySelectorAll("input[name=w-me]").forEach(r => r.onchange = () => { pickedMe = r.value; touched = true; });
    $("w-back").onclick = () => { step--; render(); };
    $("w-next").onclick = async () => {
      if (pickedMe) await pywebview.api.set_me(pickedMe);
      next();
    };
  }

  function renderRank(body) {
    body.innerHTML = `<h2>What's your rank?</h2>
      <p>We compare your stats with players of that rank, so you can see what to work on. Skip any you don't know.</p>
      <div class="welcome-list">${state.rankModes.map(mode => `
        <div class="welcome-option"><span>${escapeHtml(mode)}</span>
          <select class="select w-rank" data-mode="${escapeHtml(mode)}">
            <option value="">Not set</option>
            ${state.rankBands.map(b => `<option${state.ranks[mode] === b ? " selected" : ""}>${escapeHtml(b)}</option>`).join("")}
          </select></div>`).join("")}</div>
      <div class="welcome-actions">
        <button class="btn" id="w-back">Back</button>
        <button class="btn btn-primary" id="w-next">Continue</button>
      </div>`;
    body.querySelectorAll(".w-rank").forEach(sel => sel.onchange = async () => {
      state.ranks = await pywebview.api.set_rank(sel.dataset.mode, sel.value || null);
    });
    $("w-back").onclick = () => { step--; render(); };
    $("w-next").onclick = next;
  }

  async function renderFindings(body) {
    const token = ++findingsToken;
    const paths = state.order.filter(p => state.records.get(p));
    const analysed = paths.filter(p => state.records.get(p).analysed);
    const pending = paths.length - analysed.length;
    body.innerHTML = `<h2>Here's what we found</h2><p class="sub" id="w-found">Looking at your games&hellip;</p>
      <div id="w-findings"></div>
      <div class="welcome-actions">
        <button class="btn" id="w-back">Back</button>
        <button class="btn" id="w-home">Go to my dashboard</button>
        <button class="btn btn-primary" id="w-latest">Open my latest game</button>
      </div>
      <p class="sub">For written coaching, open a match and install the free offline AI coach (a one-off download).</p>`;
    $("w-back").onclick = () => { step--; render(); };
    $("w-home").onclick = () => finish(false);
    $("w-latest").onclick = () => finish(true);
    $("w-latest").disabled = !analysed.length;
    if (!analysed.length) {
      $("w-found").textContent = paths.length
        ? `Analysing your replays (${pending} to go)… this takes about a second each.`
        : "No replays yet. Play a match with Auto-save replays on and it will show up here with a summary.";
      if (paths.length) setTimeout(() => { if (token === findingsToken && state.view === "welcome") render(); }, 1500);
      return;
    }
    const me = state.me;
    if (!me) { $("w-found").textContent = "Pick which player you are (the previous step) to see findings about you."; return; }
    const modes = {};
    for (const p of analysed) { const s = state.records.get(p).summary; const m = `${s.teamSize}v${s.teamSize}`; modes[m] = (modes[m] || 0) + 1; }
    const mode = Object.entries(modes).sort((a, b) => b[1] - a[1])[0][0];
    const data = await pywebview.api.get_progress(me, mode);
    if (token !== findingsToken) return;
    $("w-found").textContent = `${data.count} ${mode} game${data.count === 1 ? "" : "s"} · ${data.wins} W · ${data.losses} L` +
      (pending ? ` (${pending} more still being analysed)` : "");
    let html = "";
    if (data.rank && data.rank.weaknesses.length) {
      const name = col => (statMeta(col) || [col, col])[1];
      const item = (col, cls) => {
        const r = data.rank.rows.find(x => x.stat === col);
        return r ? `<li class="${cls}"><b>${escapeHtml(name(col))}</b> &mdash; ${r.percentile}${ordinalSuffix(r.percentile)} percentile for ${escapeHtml(data.rank.band)}</li>` : "";
      };
      html = `<h3>Biggest weaknesses for ${escapeHtml(data.rank.band)}</h3><ul class="welcome-findings">${data.rank.weaknesses.map(c => item(c, "bad")).join("")}</ul>
              <h3>Strengths</h3><ul class="welcome-findings">${data.rank.strengths.slice(0, 2).map(c => item(c, "good")).join("")}</ul>`;
    } else {
      const coachData = await pywebview.api.get_coach(analysed[0]);
      if (token !== findingsToken) return;
      const notes = (coachData.insights || []).slice(0, 4);
      if (notes.length) {
        html = `<h3>From your latest game</h3><ul class="welcome-findings">${notes.map(i =>
          `<li class="${i.kind === "bad" ? "bad" : i.kind === "good" ? "good" : ""}">${escapeHtml(i.text)}</li>`).join("")}</ul>`;
      }
    }
    $("w-findings").innerHTML = html;
  }

  return { start, refresh };
})();

// ---------- Home: the game you just played, and tonight ----------

const homeAlerts = (() => {
  let card = null;        // the post-game card, until dismissed
  let session = null;

  function newMatch(payload) { card = payload; render(); }

  async function loadSession() {
    session = state.me ? await pywebview.api.get_session(state.me) : null;
    render();
  }

  function render() {
    const parts = [];
    if (card) {
      const c = card;
      parts.push(`<section class="alert-card postgame" data-result="${escapeHtml(c.result)}">
        <div class="alert-head"><span class="alert-kicker">Just finished</span>
          <b class="pg-result">${escapeHtml(c.result.toUpperCase())} ${escapeHtml(c.scoreLine)}</b>
          <span class="sub">${escapeHtml(c.mapName)} &middot; ${escapeHtml(c.mode)}</span></div>
        <div class="pg-stats">${c.stats.map(s => `<div class="pg-stat ${s.good ? "good" : "bad"}">
          <div class="stat-label">${escapeHtml(s.label)}</div><div class="stat-value">${escapeHtml(s.value)}</div>
          <div class="stat-trend">${escapeHtml(s.note)}</div></div>`).join("")}</div>
        ${c.finding ? `<p class="pg-finding">${escapeHtml(c.finding)}</p>` : ""}
        <div class="welcome-actions"><button class="btn btn-primary" id="pg-open">Open match</button>
          <button class="btn" id="pg-dismiss">Dismiss</button></div></section>`);
    }
    if (session && session.games >= 2) {
      const dots = session.results.map(r => `<i class="dot ${r === "Win" ? "win" : r === "Loss" ? "loss" : ""}" title="${r}"></i>`).join("");
      parts.push(`<section class="alert-card session">
        <div class="alert-head"><span class="alert-kicker">Tonight</span>
          <b>${session.wins} W &middot; ${session.losses} L</b><span class="dots">${dots}</span></div>
        ${session.stats.length ? `<div class="session-stats">${session.stats.map(s =>
          `<span class="${s.good ? "good" : "bad"}">${escapeHtml(s.label)} ${escapeHtml(s.session)} <span class="sub">(usually ${escapeHtml(s.usual)})</span></span>`).join("")}</div>` : ""}
        ${session.tilt ? '<p class="pg-finding">That is a few losses in a row. A short break often helps more than another queue.</p>' : ""}
      </section>`);
    }
    $("home-alerts").innerHTML = parts.join("");
    const open = $("pg-open");
    if (open) open.onclick = () => { const p = card.path; card = null; openMatch(p); };
    const dismiss = $("pg-dismiss");
    if (dismiss) dismiss.onclick = () => { card = null; render(); };
  }

  return { newMatch, loadSession, render };
})();
