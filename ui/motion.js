// Motion helper: lets menus, dialogs and banners animate out as well as in.
// Elements that start with the "hidden" class (display: none) can't transition, so show() takes "hidden" off,
// lets the browser draw the closed state once, then adds "is-open" (the CSS transition runs from there).
// hide() takes "is-open" off and only adds "hidden" back when the transition has finished, so the element can be
// shown again at any moment and simply reverses from where it is.

const motion = (() => {
  const SETTLE_MS = 600;   // longer than every transition in styles.css; the fallback if transitionend never comes

  function show(el) {
    if (!el) return;
    clearTimeout(el._hideTimer);
    if (el.classList.contains("hidden")) {
      el.classList.remove("hidden");
      void el.offsetWidth;            // draw the closed state first so the transition has somewhere to start
    }
    el.classList.add("is-open");
  }

  function hide(el) {
    if (!el || el.classList.contains("hidden")) return;
    el.classList.remove("is-open");
    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(() => { if (!el.classList.contains("is-open")) el.classList.add("hidden"); }, SETTLE_MS);
  }

  function isOpen(el) {
    return !!el && el.classList.contains("is-open");
  }

  // Scroll-edge effect: the title bar gets its divider and shadow only once a page has scrolled under it.
  function watchScroll() {
    document.addEventListener("scroll", e => {
      const t = e.target;
      if (!t || !t.classList || !(t.classList.contains("home-scroll") || t.classList.contains("progress-page"))) return;
      document.body.toggleAttribute("data-scrolled", t.scrollTop > 4);
    }, true);
  }

  function clearScrolled() {
    document.body.removeAttribute("data-scrolled");
  }

  watchScroll();
  return { show, hide, isOpen, clearScrolled };
})();
