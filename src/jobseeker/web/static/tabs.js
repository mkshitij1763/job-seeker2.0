/* Phone tabs and stage chips: [data-tabs] > [data-tab=x] buttons + [data-panel=x] panels. CSS hides .is-hidden only on
   phones, so the Mac layout and no-JS readers always see every panel. */
(function (root) {
  function resolveTab(available, requested, fallback) {
    if (!available.length) return "";
    if (requested && available.includes(requested)) return requested;
    return available.includes(fallback) ? fallback : available[0];
  }
  const api = { resolveTab };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  function show(box, name) {
    box.querySelectorAll("[data-tab]").forEach((b) => {
      const on = b.dataset.tab === name;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    box.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("is-hidden", p.dataset.panel !== name));
    box.dataset.current = name;
  }
  const bound = new WeakSet();
  function init() {
    document.querySelectorAll("[data-tabs]").forEach((box) => {
      const names = [...box.querySelectorAll("[data-tab]")].map((b) => b.dataset.tab);
      show(box, resolveTab(names, box.dataset.current || null, box.dataset.default || ""));
      // A WeakSet, not a DOM marker: htmx history snapshots copy attributes but not listeners.
      if (bound.has(box)) return;
      bound.add(box);
      box.addEventListener("click", (e) => {
        const b = e.target.closest("[data-tab]");
        if (b && box.contains(b)) { e.preventDefault(); show(box, b.dataset.tab); }
      });
    });
  }
  // An in-page link ("Review and approve ↓") whose target sits in a hidden tab opens that tab first.
  document.addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="#"]');
    const id = a && a.getAttribute("href").slice(1);
    const target = id && document.getElementById(id);
    const panel = target && target.closest("[data-panel]");
    const box = panel && panel.closest("[data-tabs]");
    if (!box || !panel.classList.contains("is-hidden")) return;
    e.preventDefault();
    show(box, panel.dataset.panel);
    target.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  root.JobTabs = { init };
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
  document.addEventListener("htmx:historyRestore", init);
})(typeof window !== "undefined" ? window : globalThis);
