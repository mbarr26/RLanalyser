// AI Coach tab. The findings and key moments come from rules in Python (moments.py) and are
// always shown; the written analysis and the chat need the local AI model (coach.py).
// All AI text is inserted with textContent, never as HTML.

const coachUi = (() => {
  const c = {
    path: null,
    data: null,          // get_coach result for the open match
    status: null,        // coach_status result
    download: null,      // {done, total, phase} while a model download runs
    downloadError: "",
    working: null,       // "starting" | "writing" while the AI analysis is being made
    writing: new Set(),  // paths whose analysis is being written (survives opening another match)
    autoStarted: new Set(),   // "path|player" pairs we already started automatically, so a failure never loops
    error: "",
    chats: new Map(),    // path -> [{role, text, error}]
    asking: false,
  };

  const $ = id => document.getElementById(id);

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // The orb in the panel header pulses while the model works; the text says what it is doing
  function updateStatus() {
    const busy = !!(c.working || c.asking);
    $("ai-orb").classList.toggle("working", busy);
    $("ai-status").textContent = c.working === "starting" ? "Starting the engine…"
      : c.working ? "Writing the analysis…" : c.asking ? "Thinking…" : "";
  }

  function setNote(text) {
    const note = $("coach-note");
    note.textContent = text;
    note.style.display = text ? "block" : "none";
    $("coach-body").style.display = text ? "none" : "flex";
  }

  // ---------- loading a match ----------

  async function open(path, force = false) {
    if (!path) return;
    if (!force && c.path === path && c.data) { render(); return; }
    c.path = path;
    c.data = null;
    c.error = "";
    c.working = c.writing.has(path) ? "writing" : null;
    setNote("Finding the key moments…");
    const [res, status] = await Promise.all([pywebview.api.get_coach(path), pywebview.api.coach_status()]);
    if (c.path !== path) return;   // the user moved on to another match
    c.status = status;
    if (res.error) { setNote(res.error); return; }
    c.data = res;
    if (!res.chatKept) c.chats.delete(path);
    setNote("");
    render();
    maybeAutoStart();
  }

  function invalidate() {
    c.data = null;
    if (state.view === "match" && state.currentPath) open(state.currentPath, true);
  }

  // The AI analysis starts by itself the first time a match is opened (once the model is installed)
  function maybeAutoStart() {
    if (!c.data || !c.status || !c.status.ready || c.working || c.data.report) return;
    const key = `${c.path}|${c.data.me}`;
    if (c.autoStarted.has(key)) return;
    c.autoStarted.add(key);
    generate();
  }

  // ---------- rendering ----------

  function render() {
    if (!c.data) return;
    renderInsights();
    renderSetup();
    renderReport();
    renderMoments();
    renderChat();
  }

  function renderInsights() {
    const list = $("coach-insights");
    list.innerHTML = "";
    if (!c.data.insights.length) {
      list.appendChild(el("li", "coach-item info", "Nothing stood out compared with your usual games."));
    }
    for (const i of c.data.insights) list.appendChild(el("li", `coach-item ${i.kind}`, i.text));
  }

  function renderSetup() {
    updateStatus();
    const box = $("coach-setup");
    box.innerHTML = "";
    const s = c.status;
    if (!s || !s.engine) {
      box.appendChild(el("div", "coach-muted", "The AI engine files are missing from this install, so only the findings above are available."));
      return;
    }
    if (!s.ready) {
      box.appendChild(el("div", "coach-muted",
        "The AI coach runs entirely on your PC, so it's free and private. It needs a one-off download of an AI model."));
      const tiers = el("div", "coach-tiers");
      for (const [name, t] of Object.entries(s.tiers)) {
        const label = el("label", "coach-tier");
        const radio = el("input");
        radio.type = "radio";
        radio.name = "coach-tier";
        radio.checked = name === s.tier;
        radio.disabled = !!c.download;
        radio.addEventListener("change", () => setTier(name));
        const text = el("span");
        text.appendChild(el("b", null, `${t.label} · ${t.sizeGb} GB`));
        text.appendChild(el("span", "coach-muted", ` ${t.hint}`));
        label.append(radio, text);
        tiers.appendChild(label);
      }
      box.appendChild(tiers);
      if (c.download) {
        const bar = el("div", "coach-bar");
        bar.appendChild(el("div", "coach-bar-fill"));
        bar.firstChild.id = "coach-dl-fill";
        box.appendChild(bar);
        const row = el("div", "coach-row");
        const text = el("span", "coach-muted");
        text.id = "coach-dl-text";
        const cancel = el("button", "btn", "Cancel");
        cancel.addEventListener("click", () => pywebview.api.coach_cancel_download());
        row.append(text, cancel);
        box.appendChild(row);
        updateDownload();
      } else {
        const row = el("div", "coach-row");
        const btn = el("button", "btn btn-primary", `Download AI model (${s.tiers[s.tier].sizeGb} GB)`);
        btn.addEventListener("click", startDownload);
        row.appendChild(btn);
        box.appendChild(row);
        if (c.downloadError) box.appendChild(el("div", "coach-error", c.downloadError));
      }
      return;
    }

    const row = el("div", "coach-row");
    if (c.working) {
      row.appendChild(el("span", "coach-muted", c.working === "starting"
        ? "Starting the AI engine… (the first time can take a minute)"
        : "Writing the analysis… (can take a minute or two)"));
    } else {
      const btn = el("button", "btn btn-primary", c.data.report ? "Rewrite analysis" : "Write AI analysis");
      btn.addEventListener("click", generate);
      row.appendChild(btn);
      row.appendChild(el("span", "coach-muted", `Model: ${s.tiers[s.tier].label}`));
    }
    box.appendChild(row);
    if (c.error) box.appendChild(el("div", "coach-error", c.error));
  }

  function listBlock(title, items, cls) {
    const wrap = el("div", "coach-block");
    wrap.appendChild(el("div", "coach-block-title", title));
    const ul = el("ul", "coach-list");
    for (const t of items) ul.appendChild(el("li", `coach-item ${cls}`, t));
    wrap.appendChild(ul);
    return wrap;
  }

  function renderReport() {
    const box = $("coach-report");
    box.innerHTML = "";
    const r = c.data.report;
    if (!r) return;
    box.appendChild(el("p", "coach-summary", r.summary));
    const cols = el("div", "coach-cols");
    if (r.strengths.length) cols.appendChild(listBlock("Strengths", r.strengths, "good"));
    if (r.weaknesses.length) cols.appendChild(listBlock("To improve", r.weaknesses, "bad"));
    box.appendChild(cols);
    if (r.focus_for_next_games.length) box.appendChild(listBlock("Focus for your next games", r.focus_for_next_games, "info"));
  }

  // "Was this right?" - votes go to labels.jsonl so the detection rules can be tuned on real games
  function voteButtons(m) {
    const wrap = el("span", "vote");
    wrap.title = "Was this detected correctly?";
    for (const [right, label, tip] of [[true, "👍", "Right"], [false, "👎", "Wrong"]]) {
      const b = el("button", "btn vote-btn", label);
      b.title = tip;
      b.addEventListener("click", async () => {
        await pywebview.api.label_event(c.path, m.type, m.time, right, m.title);
        wrap.querySelectorAll(".vote-btn").forEach(x => x.classList.remove("picked"));
        b.classList.add("picked");
      });
      wrap.appendChild(b);
    }
    return wrap;
  }

  function renderMoments() {
    const box = $("coach-moments");
    box.innerHTML = "";
    const explained = new Map((c.data.report ? c.data.report.key_moments : []).map(k => [k.id, k]));
    if (!c.data.moments.length) {
      box.appendChild(el("div", "coach-muted", "No key moments were detected in this match."));
    }
    for (const m of c.data.moments) {
      const card = el("div", `card coach-moment ${m.type}${m.players.includes(c.data.me) ? " mine" : ""}`);
      const head = el("div", "coach-moment-head");
      const title = el("span", "coach-moment-title");
      if (m.clock_text) title.appendChild(el("span", "coach-clock", m.clock_text));
      title.appendChild(document.createTextNode(m.title));
      const watch = el("button", "btn", "Watch");
      watch.addEventListener("click", () => watchMoment(m.time));
      const clip = el("button", "btn", "Clip");
      clip.title = "Save the 8 seconds around this as a video";
      clip.addEventListener("click", () => clipMoment(m.time, clip));
      head.append(title, watch, clip, voteButtons(m));
      card.appendChild(head);
      card.appendChild(el("div", "coach-detail", m.detail));
      const ai = explained.get(m.id);
      if (ai) {
        const box2 = el("div", "coach-ai");
        if (ai.what_happened) box2.appendChild(el("p", null, ai.what_happened));
        if (ai.advice) {
          const p = el("p");
          p.appendChild(el("b", null, "Try: "));
          p.appendChild(document.createTextNode(ai.advice));
          box2.appendChild(p);
        }
        card.appendChild(box2);
      }
      box.appendChild(card);
    }
  }

  // ---------- model download & analysis ----------

  async function setTier(tier) {
    c.status = await pywebview.api.coach_set_tier(tier);
    c.downloadError = "";
    // A report belongs to the model that wrote it, so reload to pick up the right saved one
    if (c.status.ready) open(c.path, true); else renderSetup();
  }

  async function startDownload() {
    c.downloadError = "";
    c.download = { done: 0, total: 1, phase: "download" };
    renderSetup();
    await pywebview.api.coach_download();
  }

  function updateDownload() {
    const fill = $("coach-dl-fill"), text = $("coach-dl-text");
    if (!fill || !c.download) return;
    const { done, total, phase } = c.download;
    fill.style.width = `${Math.min(100, (done / total) * 100)}%`;
    const mb = v => (v / 1e6).toFixed(0);
    text.textContent = phase === "verify"
      ? "Checking the download…"
      : `Downloading… ${mb(done)} of ${mb(total)} MB`;
  }

  async function generate() {
    c.error = "";
    c.working = "starting";
    c.writing.add(c.path);
    renderSetup();
    await pywebview.api.coach_generate(c.path);
  }

  // ---------- chat ----------

  function chatLog() {
    if (!c.chats.has(c.path)) c.chats.set(c.path, []);
    return c.chats.get(c.path);
  }

  function renderChat() {
    updateStatus();
    const box = $("chat-log");
    box.innerHTML = "";
    const log = chatLog();
    if (!log.length) {
      box.appendChild(el("div", "coach-muted chat-hint",
        c.status && c.status.ready
          ? "Ask anything about this match. Mention a game clock (like 2:30) or a goal (like \"the second goal\") and the coach will look at exactly where everyone was."
          : "Install the AI model to chat with the coach."));
    }
    for (const msg of log) {
      const node = el("div", `chat-msg ${msg.role}${msg.error ? " error" : ""}`);
      if (msg.text) {
        node.textContent = msg.text;
      } else {
        node.classList.add("typing");   // waiting for the first words: animated dots (fixed markup, no user text)
        node.innerHTML = "<i></i><i></i><i></i>";
      }
      box.appendChild(node);
    }
    box.scrollTop = box.scrollHeight;
    const ready = !!(c.status && c.status.ready) && !c.asking;
    $("chat-input").disabled = !(c.status && c.status.ready);
    $("chat-send").disabled = !ready;
  }

  function lastAssistant() {
    const nodes = $("chat-log").querySelectorAll(".chat-msg.assistant");
    return nodes[nodes.length - 1];
  }

  async function ask(event) {
    event.preventDefault();
    const input = $("chat-input");
    const text = input.value.trim();
    if (!text || c.asking || !c.data) return;
    input.value = "";
    c.asking = true;
    const log = chatLog();
    log.push({ role: "user", text });
    log.push({ role: "assistant", text: "" });
    renderChat();
    await pywebview.api.coach_ask(c.path, text);
  }

  function clearChat() {
    if (c.asking || !c.path) return;
    c.chats.delete(c.path);
    pywebview.api.coach_reset(c.path);
    renderChat();
  }

  function bind() {
    $("chat-form").addEventListener("submit", ask);
    $("chat-clear").addEventListener("click", clearChat);
  }

  // ---------- pushes from Python ----------

  Object.assign(window.app, {
    onCoachDownload(p) {
      if (p.error) { c.download = null; c.downloadError = p.error; }
      else if (p.finished) {
        c.download = null;
        pywebview.api.coach_status().then(s => { c.status = s; if (c.data) { render(); maybeAutoStart(); } });
        return;
      } else {
        c.download = p;
        if ($("coach-dl-fill")) { updateDownload(); return; }
      }
      if (c.data) renderSetup();
    },
    onCoachState(path, working) {
      if (path !== c.path) return;
      c.working = working;
      if (c.data) renderSetup();
    },
    onCoachReport(path, report) {
      c.writing.delete(path);
      if (path !== c.path || !c.data) return;
      c.working = null;
      c.data.report = report;
      render();
    },
    onCoachError(path, message) {
      c.writing.delete(path);
      if (path !== c.path) return;
      c.working = null;
      c.error = message;
      if (c.data) renderSetup();
    },
    onChatDelta(path, piece) {
      const log = c.chats.get(path);
      if (!log) return;
      log[log.length - 1].text += piece;
      if (path === c.path) {
        const node = lastAssistant();
        if (node) {
          node.classList.remove("typing");
          node.textContent = log[log.length - 1].text;
          $("chat-log").scrollTop = $("chat-log").scrollHeight;
        }
      }
    },
    onChatDone(path) {
      c.asking = false;
      if (path === c.path && c.data) renderChat();
    },
    onChatError(path, message) {
      c.asking = false;
      const log = c.chats.get(path);
      if (log) {
        const last = log[log.length - 1];
        last.text = last.text ? `${last.text}\n\n(${message})` : message;
        last.error = true;
      }
      if (path === c.path && c.data) renderChat();
    },
  });

  bind();
  return { open, invalidate };
})();
