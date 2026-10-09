// Weekly goals on the Home page: the goals you're working on (with progress and how to practise),
// and suggested new ones. The maths lives in goals.py; this only draws it and sends your choices back.

const goalsUi = (() => {
  let data = null;

  async function load() {
    data = state.me ? await pywebview.api.get_goals(state.me) : null;
    render();
  }

  async function copyCode(code, btn) {
    try {
      await navigator.clipboard.writeText(code);
      btn.textContent = "Copied";
    } catch (e) {
      btn.textContent = "Select & copy it";
    }
    setTimeout(() => { btn.textContent = "Copy code"; }, 1800);
  }

  function trainingHtml(t) {
    if (!t) return "";
    const packs = (t.packs || []).map(p => `<li><b>${escapeHtml(p.name)}</b>${p.creator ? ` by ${escapeHtml(p.creator)}` : ""}
      <code>${escapeHtml(p.code)}</code> <button class="btn btn-small" data-copy="${escapeHtml(p.code)}">Copy code</button></li>`).join("");
    return `<details class="goal-train"><summary>How to practise: ${escapeHtml(t.title)}</summary>
      <ul>${t.drills.map(d => `<li>${escapeHtml(d)}</li>`).join("")}</ul>
      ${packs ? `<div class="sub">Community training packs (Play &rarr; Training &rarr; Custom &rarr; enter code). Authors sometimes remove packs; search the pack's name if a code fails.</div><ul>${packs}</ul>` : ""}
    </details>`;
  }

  function activeHtml(g) {
    const done = g.status === "met", late = g.status === "expired";
    const badge = done ? '<span class="goal-badge good">Goal met &check;</span>'
      : late ? '<span class="goal-badge bad">Time\'s up</span>'
      : `<span class="sub">${g.daysLeft} day${g.daysLeft === 1 ? "" : "s"} left</span>`;
    const now = g.current === null ? "no games yet" : `${escapeHtml(g.current)} over ${g.games} game${g.games === 1 ? "" : "s"}`;
    return `<div class="goal" data-id="${escapeHtml(g.id)}">
      <div class="goal-head"><b>${escapeHtml(g.heading)}</b>
        <span class="sub">${g.lowerBetter ? "get to" : "reach"} ${g.lowerBetter ? "&le;" : "&ge;"} ${escapeHtml(g.target)} (was ${escapeHtml(g.baseline)})</span>${badge}</div>
      <div class="rank-bar goal-bar"><i style="width:${Math.round(g.fraction * 100)}%"></i></div>
      <div class="goal-foot"><span class="sub">Now: ${now}${g.games < g.needed && !done ? ` &middot; needs ${g.needed} games to count` : ""}</span>
        <button class="btn btn-small" data-finish="${escapeHtml(g.id)}">${done || late ? "Collect" : "Drop"}</button></div>
      ${trainingHtml(g.training)}</div>`;
  }

  function ideaHtml(s) {
    return `<div class="goal idea" data-stat="${escapeHtml(s.stat)}">
      <div class="goal-head"><span class="alert-kicker">Suggested</span><b>${escapeHtml(s.heading)}</b>
        <span class="sub">${s.band ? `weak spot for ${escapeHtml(s.band)}` : "slipping lately"}</span></div>
      <div class="goal-foot"><span class="sub">${s.lowerBetter ? "Get to" : "Reach"} ${s.lowerBetter ? "&le;" : "&ge;"}
        <input type="number" step="0.1" class="goal-target" value="${s.target}" aria-label="Target for ${escapeHtml(s.heading)}">
        &nbsp;(now ${escapeHtml(String(s.baseline))}) over a week</span>
        <button class="btn btn-small primary" data-accept="${escapeHtml(s.stat)}">Set goal</button></div></div>`;
  }

  function render() {
    const box = $("home-goals");
    if (!data || (!data.active.length && !data.suggestions.length)) { box.innerHTML = ""; return; }
    box.innerHTML = `<section class="alert-card goals">
      <div class="alert-head"><span class="alert-kicker">This week's goals</span>
        ${data.streak ? `<span class="sub">${data.streak} goal${data.streak === 1 ? "" : "s"} met in a row</span>` : ""}</div>
      ${data.active.map(activeHtml).join("")}${data.suggestions.map(ideaHtml).join("")}</section>`;
    box.querySelectorAll("[data-finish]").forEach(b => b.onclick = async () => {
      data = await pywebview.api.finish_goal(state.me, b.dataset.finish);
      render();
    });
    box.querySelectorAll("[data-accept]").forEach(b => b.onclick = async () => {
      const target = parseFloat(b.closest(".idea").querySelector(".goal-target").value);
      if (Number.isNaN(target)) return;
      data = await pywebview.api.accept_goal(state.me, b.dataset.accept, target);
      render();
    });
    box.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => copyCode(b.dataset.copy, b));
  }

  return { load };
})();
