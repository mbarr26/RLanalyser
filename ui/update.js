// Updates: a title-bar button and a banner. Python (updater.py) finds, downloads and checks the
// new version; this only shows it. Nothing is installed without the user clicking Install.
// Release notes are plain text from a file, so they are inserted with textContent, never as HTML.

const updateUi = (() => {
  const u = {
    info: null,          // the newer release, once found
    manual: false,       // the current check was started by a click (so errors are shown)
    installing: false,
    dismissed: null,     // the version whose banner the user closed with "Later"
    configured: false,
  };

  const $ = id => document.getElementById(id);

  // ---------- title-bar button ----------

  function setButton(text, { disabled = false, title = "", primary = false } = {}) {
    const b = $("update-btn");
    b.textContent = text;
    b.disabled = disabled;
    b.title = title;
    b.classList.toggle("primary", primary);
  }

  function resetButton() {
    if (!u.configured) {
      setButton("Updates not set up", {
        disabled: true,
        title: "No update address is set. Add \"update_url\" to config.json (see the README), or set UPDATE_URL in version.py.",
      });
    } else if (u.info) {
      setButton(`Update ${u.info.version} available`, { primary: true, title: "Click to see what's new" });
    } else {
      setButton("Check for updates");
    }
  }

  // ---------- banner ----------

  function showBanner({ title, notes = "", error = false, install = false, later = true, cancel = false, progress = false }) {
    const banner = $("update-banner");
    banner.classList.remove("hidden");
    banner.classList.toggle("error", error);
    $("update-title").textContent = title;
    $("update-notes").textContent = notes;
    $("update-install").classList.toggle("hidden", !install);
    $("update-later").classList.toggle("hidden", !later);
    $("update-cancel").classList.toggle("hidden", !cancel);
    $("update-progress").classList.toggle("hidden", !progress);
  }

  function hideBanner() {
    $("update-banner").classList.add("hidden");
  }

  function showAvailable() {
    const i = u.info;
    const when = i.released ? ` (${i.released})` : "";
    showBanner({ title: `RL Analyser ${i.version} is available${when}`, notes: i.notes, install: true });
    $("update-install").textContent = "Install & restart";
  }

  // ---------- actions ----------

  function check(manual) {
    if (u.installing) return;
    u.manual = manual;
    if (manual) setButton("Checking…", { disabled: true });
    pywebview.api.check_for_update();   // the answer arrives as onUpdate
  }

  async function install(force = false) {
    if (!u.info || u.installing) return;
    const res = await pywebview.api.update_install(force);
    if (res && res.busy) {
      if (confirm("The AI coach is still working on something. Installing the update now will stop it.\n\nInstall anyway?")) {
        install(true);
      }
      return;
    }
    if (!res || res.started === false) return;
    u.installing = true;
    setButton("Updating…", { disabled: true });
    showBanner({ title: "Downloading the update…", later: false, cancel: true, progress: true });
    $("update-bar-fill").style.width = "0%";
  }

  function bind() {
    $("update-btn").addEventListener("click", () => {
      if (u.info) { u.dismissed = null; showAvailable(); } else check(true);
    });
    $("update-install").addEventListener("click", () => install(false));
    $("update-later").addEventListener("click", () => {
      u.dismissed = u.info ? u.info.version : null;
      hideBanner();
    });
    $("update-cancel").addEventListener("click", () => pywebview.api.update_cancel());
  }

  // ---------- pushes from Python ----------

  Object.assign(window.app, {
    onUpdate(res) {
      const manual = u.manual;
      u.manual = false;
      if (res.state === "unconfigured") {
        u.configured = false;
        resetButton();
      } else if (res.state === "available") {
        u.configured = true;
        u.info = res.info;
        resetButton();
        if (manual || u.dismissed !== res.info.version) showAvailable();
      } else if (res.state === "none") {
        u.configured = true;
        u.info = null;
        setButton("Up to date ✓", { title: `You have the latest version (v${res.version}). Click to check again.` });
        if (manual) hideBanner();
      } else {   // error: only worth interrupting the user for if they asked
        u.configured = true;
        resetButton();
        if (manual) showBanner({ title: "Couldn't check for updates", notes: res.error, error: true });
      }
    },

    onUpdateProgress(p) {
      if (p.phase === "installing") {
        showBanner({ title: "Installing the update… RL Analyser will restart by itself.", later: false, progress: true });
        $("update-bar-fill").style.width = "100%";
        return;
      }
      const pct = p.total ? Math.min(100, (p.done / p.total) * 100) : 0;
      $("update-bar-fill").style.width = `${pct}%`;
      const mb = v => (v / 1e6).toFixed(1);
      $("update-title").textContent = `Downloading the update… ${mb(p.done)} of ${mb(p.total)} MB`;
    },

    onUpdateFailed(p) {
      u.installing = false;
      resetButton();
      if (p.cancelled) {
        showAvailable();
      } else {
        showBanner({ title: "The update didn't install", notes: p.error, error: true, install: true });
        $("update-install").textContent = "Try again";
      }
    },
  });

  function start() {
    bind();
    pywebview.api.get_meta().then(meta => {
      u.configured = !!meta.updatesConfigured;
      resetButton();
      if (u.configured) setTimeout(() => check(false), 3000);   // a quiet check shortly after start-up
    });
  }

  if (window.pywebview) start(); else window.addEventListener("pywebviewready", start);
  return { check };
})();
