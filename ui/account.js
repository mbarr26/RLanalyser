// Accounts in the page: the title-bar account menu and plan badge, the offline / payment banners, and
// the upgrade dialog (shown when a Pro feature is used, and while waiting for a payment).
// Python (access.py) decides what a user may do; this only shows it and routes "locked" answers to the dialog.
// Nothing here ever sees a password after it is sent, a token, or card details: payment is on Stripe's page.

const accountUi = (() => {
  const a = {
    st: null,             // the latest account state from Python
    modal: null,          // {mode: "offer" | "waiting" | "done" | "error", feature, name, error}
    poll: null,           // interval while waiting for a payment
    pollUntil: 0,
    bannerDismissed: null,
  };

  const $ = id => document.getElementById(id);
  const esc = escapeHtml;
  const POLL_MS = 3000, POLL_MAX_MS = 5 * 60 * 1000;

  const PRO_FEATURES = [
    "The AI coach: a written analysis of every match, and a chat about it",
    "Rank benchmarks: how your stats compare with players at your rank",
    "Weekly goals with drills and training packs",
    "Share cards and replay clips",
    "Your full history and trends (Free keeps your latest 10 games)",
  ];

  function can(feature) {
    return a.st ? a.st.features[feature] !== false : true;
  }

  // Python answers {locked: "coach", name: "The AI coach"} instead of data when a feature needs Pro.
  // Returns true when it was such an answer (and the upgrade dialog has been opened).
  function guard(result) {
    if (result && result.locked) { paywall(result.locked, result.name); return true; }
    return false;
  }

  // ---------- applying a new account state ----------

  function apply(st) {
    if (!st || st.plan === undefined) return;
    const prev = a.st;
    a.st = st;
    renderButton();
    renderBanner();
    $("demo-chip").classList.toggle("hidden", !st.demo);
    if (!$("account-menu").classList.contains("hidden")) renderMenu();
    if (a.modal) renderModal();
    if (st.needsSignIn && state.view !== "landing" && state.meta) landingUi.show(st);
    else if (!st.needsSignIn && state.view === "landing") enterApp();
    if (prev && (prev.plan !== st.plan || prev.signedIn !== st.signedIn)) planChanged(prev, st);
  }

  async function planChanged(prev, st) {
    if (a.modal && st.plan === "pro" && prev.plan !== "pro") {
      a.modal = { ...a.modal, mode: "done" };
      stopPolling();
      renderModal();
    }
    if (!state.meta) return;
    const meta = await pywebview.api.get_meta();
    state.rankModes = meta.rankModes || [];
    homeDirty = progressDirty = true;
    goalsUi.load();
    coachUi.invalidate();
  }

  function renderButton() {
    const b = $("account-btn"), st = a.st;
    b.classList.toggle("hidden", !(st && st.configured && st.signedIn));
    if (b.classList.contains("hidden")) return;
    const name = (st.email || "").split("@")[0];
    b.innerHTML = `<span class="plan-badge ${st.plan}">${st.plan === "pro" ? "Pro" : "Free"}</span> ${esc(name)}`;
    b.title = st.email || "Your account";
  }

  // ---------- banner: offline, payment failed, subscription ended ----------

  function bannerFor(st) {
    if (!st || !st.configured || !st.signedIn || st.reason === "forced") return null;
    if (st.reason === "offline") {
      const days = Math.max(1, Math.ceil(st.daysLeft || 0));
      return { key: "offline", title: "You're offline",
        notes: `Pro keeps working for ${days} more day${days === 1 ? "" : "s"} without a connection. Reconnect to stay up to date.` };
    }
    if (st.reason === "past_due") {
      return { key: "past_due", title: "Your last payment didn't go through",
        notes: "Update your card to keep Pro. Your replays and stats are safe either way.", action: "Update card", run: manage };
    }
    if (st.reason === "lapsed") {
      return { key: "lapsed", title: "Your Pro subscription has ended",
        notes: "You're on the Free plan. Everything you saved is still here. Renew any time to get Pro back.",
        action: "Renew Pro", run: () => paywall(null) };
    }
    return null;
  }

  function renderBanner() {
    const banner = $("account-banner"), info = bannerFor(a.st);
    if (!info || a.bannerDismissed === info.key) { banner.classList.add("hidden"); return; }
    banner.classList.remove("hidden");
    banner.classList.toggle("error", info.key !== "offline");
    $("account-banner-title").textContent = info.title;
    $("account-banner-notes").textContent = info.notes;
    const action = $("account-banner-action");
    action.classList.toggle("hidden", !info.action);
    action.textContent = info.action || "";
    action.onclick = info.run || null;
    $("account-banner-close").onclick = () => { a.bannerDismissed = info.key; banner.classList.add("hidden"); };
  }

  // ---------- the account menu ----------

  function renderMenu() {
    const st = a.st, menu = $("account-menu");
    if (!st) return;
    const pro = st.plan === "pro" && st.reason !== "forced";
    const until = st.periodEnd ? new Date(st.periodEnd).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
    const planLine = st.reason === "forced" ? "Testing plan: " + st.plan
      : pro ? `Pro${until ? ` · paid until ${esc(until)}` : ""}` : "Free plan";
    menu.innerHTML = `
      <div class="account-head"><div class="account-email">${esc(st.email)}</div><div class="sub">${planLine}</div>
        ${st.demo ? '<div class="sub demo-line">Demo mode: pretend account, pretend payments</div>' : ""}</div>
      ${pro || st.status === "past_due" || st.status === "canceled"
        ? `<button class="menu-item" data-act="manage">Manage subscription</button>`
        : `<button class="menu-item accent" data-act="upgrade">Upgrade to Pro · ${esc(st.price)}</button>`}
      <button class="menu-item" data-act="refresh">Refresh my plan</button>
      <div class="menu-sep"></div>
      <button class="menu-item" data-act="signout">Sign out</button>
      <button class="menu-item danger" data-act="delete">Delete my account…</button>`;
    menu.querySelectorAll("[data-act]").forEach(b => b.onclick = () => menuAction(b.dataset.act, b));
  }

  async function menuAction(act, button) {
    closeMenu();
    if (act === "upgrade") paywall(null);
    else if (act === "manage") manage();
    else if (act === "refresh") {
      $("status").textContent = "Checking your plan…";
      const st = await pywebview.api.refresh_entitlement();
      apply(st);
      $("status").textContent = st.error ? st.error : `You're on the ${st.plan === "pro" ? "Pro" : "Free"} plan`;
    } else if (act === "signout") {
      apply(await pywebview.api.sign_out());
    } else if (act === "delete") {
      const ok = confirm("Delete your account?\n\nThis cancels your subscription and permanently deletes your account. " +
        "Your replays and stats on this PC are not touched.");
      if (!ok) return;
      const st = await pywebview.api.delete_account();
      if (st.error) $("status").textContent = st.error; else apply(st);
    }
  }

  function toggleMenu() {
    const menu = $("account-menu");
    if (menu.classList.contains("hidden")) { renderMenu(); menu.classList.remove("hidden"); }
    else closeMenu();
  }

  function closeMenu() {
    $("account-menu").classList.add("hidden");
  }

  async function manage() {
    const res = await pywebview.api.open_portal();
    $("status").textContent = res.error ? res.error : "Opened your billing page in the browser";
  }

  // ---------- the upgrade dialog ----------

  function paywall(feature, name) {
    if (a.st && a.st.plan === "pro" && a.st.reason !== "forced") return;
    a.modal = { mode: "offer", feature, name: name || (feature && a.st && a.st.featureNames[feature]) || null, error: "" };
    renderModal();
  }

  function renderModal() {
    const m = a.modal, box = $("upgrade-modal"), body = $("upgrade-body"), st = a.st;
    if (!m || !st) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const close = '<button class="btn" data-act="close">Not now</button>';
    if (m.mode === "done") {
      body.innerHTML = `<h2 id="upgrade-title">You're Pro</h2>
        <p class="sub">Thanks for subscribing! Everything is unlocked: the AI coach, rank benchmarks, goals, sharing and your full history.</p>
        <div class="modal-actions"><button class="btn btn-primary" data-act="close">Let's go</button></div>`;
    } else if (m.mode === "waiting") {
      body.innerHTML = `<h2 id="upgrade-title">Finish paying in your browser</h2>
        <p class="sub">We opened the secure payment page. When you've paid, this window unlocks by itself, so there's no need to restart.</p>
        <div class="waiting"><span class="spinner"></span> Waiting for your payment…</div>
        <div class="modal-actions"><button class="btn" data-act="reopen">Open the payment page again</button>
          <button class="btn" data-act="cancel">Cancel</button></div>`;
    } else {
      const lead = m.name ? `${esc(m.name)} needs ${esc(st.planName)}.` : `Get more out of every match with ${esc(st.planName)}.`;
      body.innerHTML = `<h2 id="upgrade-title">${m.name ? "Unlock " + esc(m.name) : "Upgrade to Pro"}</h2>
        <p class="sub">${lead}</p>
        <ul class="pro-list">${PRO_FEATURES.map(f => `<li>${esc(f)}</li>`).join("")}</ul>
        <div class="price-line"><b>${esc(st.price)}</b><span class="sub"> · ${st.demo ? "pretend: nobody is charged in demo mode" : "cancel any time"}</span></div>
        ${m.error ? `<div class="auth-error">${esc(m.error)}</div>` : ""}
        <div class="modal-actions"><button class="btn btn-primary" data-act="upgrade">Upgrade</button>${close}</div>`;
    }
    body.querySelectorAll("[data-act]").forEach(b => b.onclick = () => modalAction(b.dataset.act));
  }

  async function modalAction(act) {
    if (act === "close" || act === "cancel") { stopPolling(); a.modal = null; renderModal(); return; }
    if (act === "upgrade" || act === "reopen") await startCheckout();
  }

  async function startCheckout() {
    const res = await pywebview.api.open_checkout();
    if (res.error) { a.modal = { ...a.modal, mode: "offer", error: res.error }; renderModal(); return; }
    a.modal = { ...a.modal, mode: "waiting", error: "" };
    renderModal();
    startPolling();
  }

  // After the browser opens, ask the server every few seconds whether the payment went through.
  function startPolling() {
    stopPolling();
    a.pollUntil = Date.now() + POLL_MAX_MS;
    a.poll = setInterval(refreshNow, POLL_MS);
  }

  function stopPolling() {
    if (a.poll) clearInterval(a.poll);
    a.poll = null;
  }

  async function refreshNow() {
    if (Date.now() > a.pollUntil) {
      stopPolling();
      if (a.modal && a.modal.mode === "waiting") {
        a.modal = { ...a.modal, mode: "offer", error: "We haven't seen a payment yet. If you paid, press Upgrade and then Refresh my plan in your account menu." };
        renderModal();
      }
      return;
    }
    const st = await pywebview.api.refresh_entitlement();
    if (st && st.plan !== undefined) apply(st);
  }

  // ---------- wiring ----------

  function init() {
    $("account-btn").addEventListener("click", e => { e.stopPropagation(); toggleMenu(); });
    document.addEventListener("click", e => {
      if (!e.target.closest(".account-wrap")) closeMenu();
      const lock = e.target.closest("[data-upgrade]");
      if (lock) paywall(lock.dataset.upgrade);
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape") { closeMenu(); if (a.modal && a.modal.mode !== "waiting") modalAction("close"); }
    });
    $("upgrade-modal").addEventListener("click", e => {
      if (e.target === $("upgrade-modal") && a.modal && a.modal.mode !== "waiting") modalAction("close");
    });
    window.addEventListener("focus", () => { if (a.modal && a.modal.mode === "waiting") refreshNow(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();

  // Python tells the page whenever the plan may have changed (a re-check, signing in or out...)
  Object.assign(window.app, { onAccount: apply });

  return { apply, can, guard, paywall, manage, get state() { return a.st; } };
})();
