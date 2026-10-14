// RL Analyser website behaviour: the shared header and footer, download details, and the effects.
// Plain JavaScript, no libraries. Everything animated respects prefers-reduced-motion.

(() => {
  "use strict";
  const S = window.SITE || {};
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const home = document.body.dataset.page === "home";
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  document.documentElement.classList.remove("no-js");

  // ---------- icons (inline so there are no extra requests) ----------
  const ICON = {
    windows: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3 5.5l7.5-1v7H3zM11.5 4.4L21 3v8.5h-9.5zM3 12.5h7.5v7L3 18.5zM11.5 12.5H21V21l-9.5-1.4z"/></svg>',
    download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M4 20h16"/></svg>',
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  };
  const LOGO = '<svg viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#6d28d9"/></linearGradient></defs>' +
    '<rect width="32" height="32" rx="9" fill="url(#lg)"/><circle cx="16" cy="16" r="8.2" fill="none" stroke="#fff" stroke-opacity=".85" stroke-width="1.8"/>' +
    '<path d="M16 7.8v16.4M7.8 16h16.4" stroke="#fff" stroke-opacity=".4" stroke-width="1.2"/><circle cx="21.4" cy="11.2" r="2.6" fill="#fff"/></svg>';

  // ---------- the shared header and footer (one copy, here, for every page) ----------
  const link = hash => (home ? hash : "index.html" + hash);
  function buildChrome() {
    const header = $("#site-header");
    if (header) {
      header.innerHTML = `<nav class="nav" aria-label="Main">
        <div class="wrap">
          <a class="brand" href="${home ? "#top" : "index.html"}" aria-label="${esc(S.name)} home">${LOGO}<span><span class="rl">RL</span> Analyser</span></a>
          <div class="nav-links" id="nav-links">
            <a href="${link("#features")}">Features</a><a href="${link("#how")}">How it works</a>
            <a href="${link("#pricing")}">Pricing</a><a href="${link("#faq")}">FAQ</a>
          </div>
          <div class="nav-cta"><a class="btn btn-primary btn-small" href="download.html" data-nav-download>${ICON.download} Download</a></div>
          <button class="menu-btn" id="menu-btn" aria-label="Menu" aria-expanded="false" aria-controls="nav-links">${ICON.menu}</button>
        </div></nav>`;
    }
    const footer = $("#site-footer");
    if (footer) {
      const social = S.social || {};
      const socials = [["discord", "Discord"], ["youtube", "YouTube"], ["x", "X"], ["github", "GitHub"]]
        .filter(([k]) => social[k]).map(([k, label]) => `<li><a href="${esc(social[k])}" rel="noopener">${label}</a></li>`).join("");
      footer.innerHTML = `<footer class="site"><div class="wrap">
        <div class="foot">
          <div><a class="brand" href="${home ? "#top" : "index.html"}">${LOGO}<span><span class="rl">RL</span> Analyser</span></a>
            <p class="about">${esc(S.tagline)} Replay analysis and a private AI coach for Rocket League, running on your own PC.</p></div>
          <div><h2 class="foot-h">Product</h2><ul><li><a href="${link("#features")}">Features</a></li><li><a href="${link("#pricing")}">Pricing</a></li><li><a href="download.html">Download</a></li><li><a href="${link("#faq")}">FAQ</a></li></ul></div>
          <div><h2 class="foot-h">Legal</h2><ul><li><a href="terms.html">Terms of Service</a></li><li><a href="privacy.html">Privacy Policy</a></li><li><a href="refunds.html">Cancellation &amp; refunds</a></li></ul></div>
          <div><h2 class="foot-h">Contact</h2><ul><li><a href="mailto:${esc(S.supportEmail)}">${esc(S.supportEmail)}</a></li>${socials}</ul></div>
        </div>
        <p class="legal-line">&copy; <span id="year"></span> ${esc(S.name)}. ${esc(S.name)} is an independent tool and is not affiliated with, endorsed by, or sponsored by Psyonix or Epic Games.
          Rocket League is a trademark of Psyonix LLC. Rank names and the game's name are used only to describe what the tool works with.</p>
      </div></footer>`;
      $("#year").textContent = new Date().getFullYear();
    }
    const menu = $("#menu-btn"), nav = $(".nav");
    if (menu && nav) {
      menu.addEventListener("click", () => { const open = nav.classList.toggle("open"); menu.setAttribute("aria-expanded", String(open)); });
      $$("#nav-links a").forEach(a => a.addEventListener("click", () => { nav.classList.remove("open"); menu.setAttribute("aria-expanded", "false"); }));
    }
    const onScroll = () => nav && nav.classList.toggle("scrolled", window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // ---------- text from the config ----------
  function fillConfig() {
    $$("[data-site]").forEach(el => { const v = S[el.dataset.site]; if (v) el.textContent = v; });
    $$("[data-site-email]").forEach(el => { el.href = "mailto:" + S.supportEmail; el.textContent = S.supportEmail; });
    $$("[data-section]").forEach(el => { if (S.sections && S.sections[el.dataset.section] === false) el.classList.add("hidden"); });
  }

  // ---------- the download button and details (assets/release.json) ----------
  async function loadRelease() {
    let rel = {};
    try { rel = await (await fetch("assets/release.json", { cache: "no-cache" })).json(); } catch (e) { /* offline or not served: treat as no release */ }
    const ready = !!(rel.url && rel.version);
    $$("[data-download]").forEach(a => {
      a.innerHTML = `${ICON.windows} ${ready ? "Download for Windows" : "Coming soon"}`;
      if (ready) { a.href = rel.url; a.removeAttribute("aria-disabled"); a.setAttribute("download", ""); }
      else { a.href = "download.html"; a.setAttribute("aria-disabled", "true"); }
    });
    $$("[data-nav-download]").forEach(a => { if (!ready) a.innerHTML = `${ICON.download} Download`; });
    const mb = rel.size ? (rel.size / 1048576).toFixed(0) + " MB" : "";
    const set = (id, v, fallback) => { const el = document.getElementById(id); if (el) el.textContent = v || fallback; };
    set("dl-version", rel.version && "Version " + rel.version, "Not released yet");
    set("dl-size", mb, "");
    set("dl-date", rel.released && "Released " + rel.released, "");
    const hash = document.getElementById("dl-hash");
    if (hash) { hash.textContent = rel.sha256 || "Published with the first release"; const b = document.getElementById("dl-copy"); if (b && !rel.sha256) b.classList.add("hidden"); }
    const notes = document.getElementById("dl-notes");
    if (notes) { const box = notes.closest("[data-notes-box]"); if (rel.notes) notes.textContent = rel.notes; else if (box) box.classList.add("hidden"); }
    const lead = document.getElementById("dl-lead");
    if (lead && !ready) lead.textContent = "The first public release is on its way. The download button will appear here the moment it's ready.";
  }

  // ---------- effects ----------
  function reveals() {
    const items = $$(".reveal");
    if (reduced || !("IntersectionObserver" in window)) { items.forEach(el => el.classList.add("in")); return; }
    items.forEach((el, i) => { const sib = el.parentElement ? [...el.parentElement.children].filter(c => c.classList.contains("reveal")).indexOf(el) : 0; el.style.setProperty("--d", Math.max(0, sib) * 0.08 + "s"); });
    const io = new IntersectionObserver(entries => entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    items.forEach(el => io.observe(el));
  }

  function spotlight() {
    if (reduced) return;
    document.addEventListener("pointermove", e => {
      const card = e.target.closest && e.target.closest(".card");
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", e.clientX - r.left + "px");
      card.style.setProperty("--my", e.clientY - r.top + "px");
    }, { passive: true });
  }

  // The hero replay leans a little toward the pointer (and the floating chips a little further, for depth).
  // Only two CSS variables change, on pointer-move and through requestAnimationFrame; the CSS spring in
  // .replay / .float does the smoothing and carries it back to rest when the pointer leaves. Mouse and pen only.
  function tilt() {
    const stage = $(".stage");
    if (!stage || reduced || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    let raf = 0, x = 0, y = 0;
    const apply = () => { raf = 0; stage.style.setProperty("--tx", x.toFixed(3)); stage.style.setProperty("--ty", y.toFixed(3)); };
    stage.addEventListener("pointermove", e => {
      const r = stage.getBoundingClientRect();
      x = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width - 0.5) * 2));
      y = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height - 0.5) * 2));
      if (!raf) raf = requestAnimationFrame(apply);
    }, { passive: true });
    stage.addEventListener("pointerleave", () => { x = 0; y = 0; if (!raf) raf = requestAnimationFrame(apply); });
  }

  function onVisible(el, fn, once = true) {
    if (!("IntersectionObserver" in window)) { fn(); return; }
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { fn(); if (once) io.disconnect(); } }), { threshold: 0.35 });
    io.observe(el);
  }

  function counters() {
    $$("[data-count]").forEach(el => {
      const target = parseFloat(el.dataset.count), suffix = el.dataset.suffix || "";
      const draw = v => { el.textContent = Math.round(v) + suffix; };
      if (reduced) { draw(target); return; }
      draw(0);
      onVisible(el, () => {
        const t0 = performance.now(), dur = 1300;
        const tick = now => { const p = Math.min(1, (now - t0) / dur); draw(target * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); };
        requestAnimationFrame(tick);
      });
    });
  }

  function bars() {
    $$(".bar i[data-w]").forEach(i => {
      i.style.setProperty("--w", i.dataset.w + "%");
      if (reduced) { i.classList.add("on"); return; }
      onVisible(i.parentElement, () => requestAnimationFrame(() => i.classList.add("on")));
    });
  }

  function typing() {
    $$("[data-typing]").forEach(box => {
      const text = box.dataset.typing, target = $(".typed", box);
      if (!target) return;
      target.textContent = text;                          // reserve the finished height so the page doesn't jump while typing
      box.style.minHeight = box.getBoundingClientRect().height + "px";
      target.textContent = "";
      if (reduced) { target.textContent = text; return; }
      let timer;
      const run = () => {
        let i = 0; target.textContent = "";
        clearInterval(timer);
        timer = setInterval(() => {
          i += 2; target.textContent = text.slice(0, i);
          if (i >= text.length) { clearInterval(timer); setTimeout(run, 7000); }
        }, 24);
      };
      onVisible(box, run);
    });
  }

  // ---------- the animated 2D replay in the hero (drawn from scratch, no real match data) ----------
  function replay(canvas) {
    const ctx = canvas.getContext("2d");
    const hud = { b: $("#hud-b"), o: $("#hud-o"), clock: $("#hud-clock"), track: $("#hud-track"), state: $("#hud-state") };
    let w = 0, h = 0, running = false, raf = 0, last = 0, t = 0;
    const LOOP = 14, GOAL_AT = 10.2;
    const ease = x => x * x * (3 - 2 * x);
    const WAY = [[0, .5, .5], [2.6, .36, .4], [4.4, .3, .62], [6.6, .56, .55], [8.4, .74, .38], [GOAL_AT, .99, .5]];

    function ballAt(time) {
      if (time >= GOAL_AT && time < 12.2) return [.99, .5];
      if (time >= 12.2) return [.5, .5];
      for (let i = 0; i < WAY.length - 1; i++) {
        const [t0, u0, v0] = WAY[i], [t1, u1, v1] = WAY[i + 1];
        if (time >= t0 && time <= t1) { const k = ease((time - t0) / (t1 - t0)); return [u0 + (u1 - u0) * k, v0 + (v1 - v0) * k]; }
      }
      return [.5, .5];
    }
    const cars = [
      { team: 0, u: .3, v: .5, role: "chase" }, { team: 0, u: .18, v: .3, role: "support" },
      { team: 1, u: .7, v: .5, role: "press" }, { team: 1, u: .86, v: .65, role: "guard" },
    ].map(c => ({ ...c, a: 0, speed: 0, trail: [] }));
    const trail = [];

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2), r = canvas.getBoundingClientRect();
      w = r.width; h = r.height;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    const PAD = 0.045;
    const px = (u, v) => [w * (PAD + u * (1 - 2 * PAD)), h * (PAD + v * (1 - 2 * PAD))];

    function drawField(time) {
      const g = ctx.createLinearGradient(0, 0, w, 0);
      g.addColorStop(0, "#0b1322"); g.addColorStop(.5, "#0a0b13"); g.addColorStop(1, "#1a1010");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      const [x0, y0] = px(0, 0), [x1, y1] = px(1, 1);
      ctx.strokeStyle = "rgba(255,255,255,.14)"; ctx.lineWidth = 1.5; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.beginPath(); ctx.moveTo((x0 + x1) / 2, y0); ctx.lineTo((x0 + x1) / 2, y1); ctx.stroke();
      ctx.beginPath(); ctx.arc((x0 + x1) / 2, (y0 + y1) / 2, h * 0.13, 0, 7); ctx.stroke();
      // goals, glowing in the team colours
      const gh = (y1 - y0) * 0.26;
      for (const [x, col, dir] of [[x0, "57,135,229", -1], [x1, "217,89,38", 1]]) {
        const gg = ctx.createLinearGradient(x, 0, x + dir * 60, 0);
        gg.addColorStop(0, `rgba(${col},.55)`); gg.addColorStop(1, `rgba(${col},0)`);
        ctx.fillStyle = gg; ctx.fillRect(dir > 0 ? x - 60 : x, (y0 + y1) / 2 - gh / 2, 60, gh);
        ctx.strokeStyle = `rgba(${col},.9)`; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x, (y0 + y1) / 2 - gh / 2); ctx.lineTo(x, (y0 + y1) / 2 + gh / 2); ctx.stroke();
      }
      // boost pads
      for (const [u, v, big] of [[.12, .12, 1], [.12, .88, 1], [.88, .12, 1], [.88, .88, 1], [.5, .06, 0], [.5, .94, 0], [.3, .5, 0], [.7, .5, 0], [.22, .3, 0], [.22, .7, 0], [.78, .3, 0], [.78, .7, 0]]) {
        const [x, y] = px(u, v);
        ctx.beginPath(); ctx.arc(x, y, big ? 5.5 : 2.4, 0, 7);
        ctx.fillStyle = big ? "rgba(250,178,25,.85)" : "rgba(250,178,25,.35)";
        if (big) { ctx.shadowColor = "rgba(250,178,25,.8)"; ctx.shadowBlur = 12; }
        ctx.fill(); ctx.shadowBlur = 0;
      }
    }

    function step(dt, time) {
      const [bu, bv] = ballAt(time);
      const targets = [
        [bu - .05, bv + .02], [Math.max(.1, bu - .22), .5 + .22 * Math.sin(time * .6)],
        [Math.min(.95, bu + .07), bv - .03], [.88, .5 + .18 * Math.sin(time * .5 + 1)],
      ];
      cars.forEach((c, i) => {
        const k = 1 - Math.exp(-dt * (i === 0 || i === 2 ? 2.6 : 1.5));
        const pu = c.u, pv = c.v;
        c.u += (targets[i][0] - c.u) * k; c.v += (targets[i][1] - c.v) * k;
        const du = (c.u - pu) * w, dv = (c.v - pv) * h;
        c.speed = Math.hypot(du, dv) / Math.max(dt, 1e-3);
        if (c.speed > 8) c.a = Math.atan2(dv, du);
        c.trail.push([c.u, c.v]); if (c.trail.length > 14) c.trail.shift();
      });
      trail.push([bu, bv]); if (trail.length > 26) trail.shift();
    }

    function drawCars() {
      for (const c of cars) {
        const col = c.team === 0 ? "57,135,229" : "217,89,38";
        ctx.lineCap = "round";
        c.trail.forEach(([u, v], i) => { // boost trail
          const [x, y] = px(u, v); ctx.beginPath(); ctx.arc(x, y, 2 + i * 0.12, 0, 7); ctx.fillStyle = `rgba(${col},${i / c.trail.length * 0.22})`; ctx.fill();
        });
        const [x, y] = px(c.u, c.v), L = Math.max(18, w * 0.034), Wd = L * 0.52;
        ctx.save(); ctx.translate(x, y); ctx.rotate(c.a);
        if (c.speed > 120) { const fl = ctx.createLinearGradient(-L * 1.5, 0, -L * 0.5, 0); fl.addColorStop(0, "rgba(255,170,60,0)"); fl.addColorStop(1, "rgba(255,200,90,.9)"); ctx.fillStyle = fl; ctx.beginPath(); ctx.moveTo(-L * .5, -Wd * .25); ctx.lineTo(-L * 1.5, 0); ctx.lineTo(-L * .5, Wd * .25); ctx.fill(); }
        ctx.shadowColor = `rgba(${col},.9)`; ctx.shadowBlur = 16; ctx.fillStyle = `rgb(${col})`;
        ctx.beginPath(); ctx.roundRect(-L / 2, -Wd / 2, L, Wd, 4); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.fillRect(L * .1, -Wd * .3, L * .22, Wd * .6); // windscreen
        ctx.restore();
      }
    }

    function drawBall(time) {
      const [bu, bv] = ballAt(time);
      trail.forEach(([u, v], i) => { const [x, y] = px(u, v); ctx.beginPath(); ctx.arc(x, y, 2 + i * 0.16, 0, 7); ctx.fillStyle = `rgba(190,170,255,${i / trail.length * 0.5})`; ctx.fill(); });
      const [x, y] = px(bu, bv), r = Math.max(7, w * 0.017);
      const g = ctx.createRadialGradient(x - r * .3, y - r * .3, 1, x, y, r);
      g.addColorStop(0, "#fff"); g.addColorStop(1, "#c4b5fd");
      ctx.shadowColor = "rgba(167,139,250,.95)"; ctx.shadowBlur = 22; ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    }

    function drawGoal(time) {
      if (time < GOAL_AT || time > GOAL_AT + 1.8) return;
      const k = (time - GOAL_AT) / 1.8, a = Math.sin(Math.PI * Math.min(1, k * 1.15));
      const [gx, gy] = px(1, .5);
      const g = ctx.createRadialGradient(gx, gy, 0, gx, gy, w * 0.5);
      g.addColorStop(0, `rgba(96,165,250,${0.5 * a})`); g.addColorStop(1, "rgba(96,165,250,0)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      ctx.font = `800 ${Math.round(h * 0.13)}px "Segoe UI", system-ui, sans-serif`; ctx.textAlign = "center";
      ctx.fillStyle = `rgba(255,255,255,${a})`; ctx.shadowColor = "rgba(96,165,250,.9)"; ctx.shadowBlur = 24;
      ctx.fillText("GOAL!", w / 2, h * 0.5 + h * 0.04 - k * 10); ctx.shadowBlur = 0;
    }

    function hudUpdate(time) {
      if (!hud.clock) return;
      const scored = time >= GOAL_AT + 0.25;
      const clockS = Math.max(0, 298 - Math.floor(time * 3));
      hud.clock.textContent = `${Math.floor(clockS / 60)}:${String(clockS % 60).padStart(2, "0")}`;
      hud.b.textContent = scored ? "1" : "0"; hud.o.textContent = "0";
      hud.track.style.width = (time / LOOP * 100).toFixed(1) + "%";
      if (hud.state) hud.state.textContent = time >= GOAL_AT && time < GOAL_AT + 1.8 ? "GOAL REPLAY" : "";
    }

    function frame(time) {
      drawField(time); drawCars(); drawBall(time); drawGoal(time); hudUpdate(time);
    }

    function loop(now) {
      if (!running) return;
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      t += dt; if (t >= LOOP) { t = 0; cars.forEach(c => { c.trail.length = 0; }); trail.length = 0; }
      step(dt, t); frame(t);
      raf = requestAnimationFrame(loop);
    }
    function start() { if (running || reduced || document.hidden) return; running = true; last = performance.now(); raf = requestAnimationFrame(loop); }
    function stop() { running = false; cancelAnimationFrame(raf); }

    resize();
    new ResizeObserver(() => { resize(); if (!running) frame(t); }).observe(canvas);
    if (reduced) { for (let i = 0; i < 60; i++) step(0.05, 6.4 + i * 0.002); t = 6.4; frame(t); return; }
    // let the cars settle into position before the first frame is seen
    for (let i = 0; i < 40; i++) step(0.05, 0.4);
    frame(0);
    if ("IntersectionObserver" in window) new IntersectionObserver(es => es.forEach(e => (e.isIntersecting ? start() : stop())), { threshold: 0.05 }).observe(canvas);
    else start();
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
  }

  // ---------- small helpers ----------
  function copyButtons() {
    $$("[data-copy]").forEach(btn => btn.addEventListener("click", async () => {
      const text = (document.getElementById(btn.dataset.copy) || {}).textContent || "";
      try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch (e) { btn.textContent = "Select and copy"; }
      setTimeout(() => { btn.textContent = "Copy"; }, 1800);
    }));
  }

  // the one page every return link lands on (?status=paid|cancelled|confirmed)
  function thanksPage() {
    const box = $("[data-thanks]");
    if (!box) return;
    const status = new URLSearchParams(location.search).get("status") || "paid";
    const msg = {
      paid: ["You're Pro", "Thanks for subscribing. Switch back to RL Analyser: it unlocks by itself within a few seconds, with no restart needed."],
      cancelled: ["No payment was taken", "You haven't been charged. You can upgrade any time from the account menu in the app."],
      confirmed: ["Email confirmed", "Your account is ready. Open RL Analyser and sign in with your email and password."],
      portal: ["All done", "Your billing changes are saved. You can close this tab and go back to RL Analyser."],
    }[status] || ["All done", "You can close this tab and go back to RL Analyser."];
    $("#thanks-title").textContent = msg[0];
    $("#thanks-text").textContent = msg[1];
    box.dataset.status = status;
  }

  function init() {
    buildChrome(); fillConfig(); loadRelease(); reveals(); spotlight(); tilt(); counters(); bars(); typing(); copyButtons(); thanksPage();
    const canvas = $("#replay-canvas");
    if (canvas && canvas.getContext) replay(canvas);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
