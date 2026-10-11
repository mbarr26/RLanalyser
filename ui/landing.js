// The landing page: what the app does, what Free and Pro include, and the sign in / create account forms.
// It is shown instead of the app until someone is signed in. Python (access.py + account.py) does the real work;
// the password is only ever sent to Python and never kept here. All dynamic text goes through escapeHtml.

const landingUi = (() => {
  const L = {
    st: null,          // account state (price, terms links...)
    mode: "signin",    // signin | signup | forgot | verify | sent
    email: "",         // remembered between screens so people don't retype it
    busy: false,
    agree: false,      // the terms checkbox, kept when the form is redrawn after an error
    error: "",
    notice: "",
  };

  const $ = id => document.getElementById(id);
  const esc = escapeHtml;

  const FREE = [
    "Every replay as a 2D playback",
    "Scoreboard and all stat tabs",
    "Key moments and findings",
    "Your latest 10 games of progress",
  ];
  const PRO = [
    "Everything in Free",
    "AI coach: a written analysis and chat",
    "Rank benchmarks and percentiles",
    "Weekly goals with drills",
    "Share cards and replay clips",
    "Your full history and trends",
  ];

  function show(st) {
    L.st = st || L.st;
    L.mode = "signin";
    L.error = L.notice = "";
    $("app").classList.add("landing-mode");
    showView("landing");
    render();
  }

  function hide() {
    $("app").classList.remove("landing-mode");
  }

  // ---------- rendering ----------

  function passwordHint(p) {
    const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^\w\s]/].filter(r => r.test(p)).length;
    if (p.length < 8) return ["weak", "At least 8 characters"];
    if (p.length >= 12 && kinds >= 3) return ["strong", "Strong"];
    if (kinds >= 2) return ["ok", "Good. Longer is stronger"];
    return ["weak", "Add numbers or capital letters"];
  }

  function link(url, text) {
    return url ? `<a href="#" data-link="${esc(url)}">${text}</a>` : text;
  }

  function hero() {
    const st = L.st;
    return `<section class="landing-hero">
      <div class="landing-kicker">Rocket League replay coach</div>
      <h1>Understand why you win &mdash; and why you lose.</h1>
      <p class="landing-sub">Drop in your replays. RL Analyser plays every match back in 2D, finds the moments that decided it,
        and a private AI coach on your own PC tells you what to practise next.</p>
      <div class="plans">
        <div class="plan-card">
          <div class="plan-name">Free</div><div class="plan-price">$0</div>
          <ul>${FREE.map(f => `<li>${esc(f)}</li>`).join("")}</ul>
        </div>
        <div class="plan-card pro">
          <div class="plan-name">Pro <span class="plan-flag">Most popular</span></div>
          <div class="plan-price">${esc(st.price)}</div>
          <ul>${PRO.map(f => `<li>${esc(f)}</li>`).join("")}</ul>
        </div>
      </div>
      <p class="landing-privacy">&#128274; Your replays never leave your PC. We only keep your email address and whether you're subscribed.</p>
    </section>`;
  }

  function field(id, label, type, value, extra = "") {
    return `<label class="field-row" for="${id}"><span>${label}</span>
      <input id="${id}" class="text-input" type="${type}" value="${esc(value)}" ${extra} /></label>`;
  }

  function passwordField(id, label, autocomplete) {
    return `<label class="field-row" for="${id}"><span>${label}</span>
      <span class="pw-wrap"><input id="${id}" class="text-input" type="password" autocomplete="${autocomplete}" required />
      <button type="button" class="pw-toggle" data-toggle="${id}" aria-label="Show or hide password">Show</button></span></label>`;
  }

  function authCard() {
    const err = L.error ? `<div class="auth-error" role="alert">${esc(L.error)}</div>` : "";
    const note = L.notice ? `<div class="auth-notice">${esc(L.notice)}</div>` : "";
    if (L.mode === "verify") {
      return `<div class="auth-card card"><h2>Check your email</h2>
        <p class="sub">We sent a confirmation link to <b>${esc(L.email)}</b>. Click it, then come back and sign in.
          It can take a minute, and it may land in your spam folder.</p>${note}${err}
        <div class="auth-actions"><button id="auth-signin-now" class="btn btn-primary">I've confirmed, sign in</button>
          <button id="auth-resend" class="btn">Send the email again</button></div></div>`;
    }
    if (L.mode === "sent") {
      return `<div class="auth-card card"><h2>Reset link sent</h2>
        <p class="sub">If there's an account for <b>${esc(L.email)}</b>, a link to choose a new password is on its way.</p>
        <div class="auth-actions"><button id="auth-back" class="btn btn-primary">Back to sign in</button></div></div>`;
    }
    if (L.mode === "forgot") {
      return `<div class="auth-card card"><h2>Reset your password</h2>
        <p class="sub">Enter your email and we'll send you a link to choose a new one.</p>
        <form id="auth-form" novalidate>${field("auth-email", "Email", "email", L.email, 'autocomplete="email" required')}
          ${err}<div class="auth-actions"><button class="btn btn-primary" type="submit">Send reset link</button>
          <button id="auth-back" class="btn" type="button">Back</button></div></form></div>`;
    }
    const signup = L.mode === "signup";
    return `<div class="auth-card card">
      <div class="auth-tabs" role="tablist">
        <button class="auth-tab${signup ? "" : " active"}" data-mode="signin" role="tab">Sign in</button>
        <button class="auth-tab${signup ? " active" : ""}" data-mode="signup" role="tab">Create account</button>
      </div>
      <form id="auth-form" novalidate>
        ${field("auth-email", "Email", "email", L.email, 'autocomplete="email" required')}
        ${passwordField("auth-password", "Password", signup ? "new-password" : "current-password")}
        ${signup ? `<div id="pw-hint" class="pw-hint"></div>
          <label class="agree"><input id="auth-agree" type="checkbox"${L.agree ? " checked" : ""} /> <span>I agree to the
            ${link(L.st.terms, "Terms of Service")} and ${link(L.st.privacy, "Privacy Policy")}</span></label>` : ""}
        ${note}${err}
        <div class="auth-actions"><button id="auth-submit" class="btn btn-primary btn-wide" type="submit">${signup ? "Create free account" : "Sign in"}</button></div>
        ${signup ? `<p class="sub fine">Free to start. You can upgrade to Pro ${esc(L.st.price)} whenever you like.</p>`
          : `<button id="auth-forgot" class="linklike" type="button">Forgot your password?</button>`}
      </form></div>`;
  }

  function render() {
    if (!L.st) return;
    $("landing").innerHTML = `${hero()}<section class="landing-auth">${authCard()}
      <footer class="landing-foot">${link(L.st.terms, "Terms")} &middot; ${link(L.st.privacy, "Privacy")}
        ${L.st.support ? ` &middot; <span>${esc(L.st.support)}</span>` : ""}</footer></section>`;
    bind();
    const first = $("auth-email");
    if (first && !first.value) first.focus(); else if ($("auth-password")) $("auth-password").focus();
  }

  // ---------- behaviour ----------

  function setMode(mode, keep = false) {
    const typed = $("auth-email") ? $("auth-email").value.trim() : "";
    if (typed) L.email = typed;
    L.mode = mode;
    if (!keep) L.error = L.notice = "";
    render();
  }

  function bind() {
    const root = $("landing");
    root.querySelectorAll(".auth-tab").forEach(b => b.onclick = () => setMode(b.dataset.mode));
    root.querySelectorAll("[data-link]").forEach(b => b.onclick = e => { e.preventDefault(); pywebview.api.open_link(b.dataset.link); });
    root.querySelectorAll("[data-toggle]").forEach(b => b.onclick = () => {
      const input = $(b.dataset.toggle);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      b.textContent = show ? "Hide" : "Show";
    });
    const form = $("auth-form");
    if (form) form.onsubmit = e => { e.preventDefault(); submit(); };
    if ($("auth-forgot")) $("auth-forgot").onclick = () => setMode("forgot");
    if ($("auth-back")) $("auth-back").onclick = () => setMode("signin");
    if ($("auth-signin-now")) $("auth-signin-now").onclick = () => setMode("signin");
    if ($("auth-resend")) $("auth-resend").onclick = resend;
    const pw = $("auth-password"), hint = $("pw-hint");
    if (pw && hint) pw.oninput = () => {
      const [level, text] = pw.value ? passwordHint(pw.value) : ["", ""];
      hint.className = `pw-hint ${level}`;
      hint.textContent = text;
    };
  }

  function setBusy(on) {
    L.busy = on;
    const b = $("auth-submit");
    if (b) b.disabled = on;
  }

  async function submit() {
    if (L.busy) return;
    const email = $("auth-email").value.trim();
    const password = $("auth-password") ? $("auth-password").value : "";
    L.email = email;
    L.error = "";
    if (L.mode === "signup") L.agree = $("auth-agree").checked;
    if (L.mode === "signup" && !L.agree) {
      L.error = "Please agree to the Terms and Privacy Policy to create an account.";
      return rerenderKeeping(email);
    }
    setBusy(true);
    let res;
    try {
      if (L.mode === "forgot") res = await pywebview.api.reset_password(email);
      else if (L.mode === "signup") res = await pywebview.api.sign_up(email, password);
      else res = await pywebview.api.sign_in(email, password);
    } catch (e) {
      res = { error: "Something went wrong. Please try again.", code: "error" };
    }
    setBusy(false);
    if (res.error) {
      if (res.code === "email_not_confirmed") { L.mode = "verify"; L.error = ""; return render(); }
      L.error = res.error;
      return rerenderKeeping(email);
    }
    if (L.mode === "forgot") { L.mode = "sent"; return render(); }
    if (res.needsConfirmation) { L.mode = "verify"; return render(); }
    accountUi.apply(res);        // signed in: this leaves the landing page and starts the app
  }

  // show an error without wiping what was typed (except the password)
  function rerenderKeeping(email) {
    L.email = email;
    render();
  }

  async function resend() {
    const res = await pywebview.api.resend_confirmation(L.email);
    L.error = res.error || "";
    L.notice = res.error ? "" : "Sent. Check your inbox in a minute.";
    render();
  }

  return { show, hide };
})();
