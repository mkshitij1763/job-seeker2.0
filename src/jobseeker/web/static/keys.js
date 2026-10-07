(function () {
  const phoneQuery = window.matchMedia("(max-width: 640px)");
  const phone = () => phoneQuery.matches;
  let i = 0;
  const rows = () => Array.from(document.querySelectorAll("table[data-keys=rows] tbody tr[data-href]"));
  function select(n) {
    const r = rows();
    if (!r.length) return;
    i = Math.max(0, Math.min(n, r.length - 1));
    r.forEach((x, k) => x.classList.toggle("sel", k === i));
    r[i].scrollIntoView({ block: "nearest" });
  }
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey) return;
    const r = rows();
    if (!r.length) return;
    if (e.key === "j") select(i + 1);
    else if (e.key === "k") select(i - 1);
    else if (e.key === "Enter") window.location = r[i].dataset.href;
    else if (e.key === "s" || e.key === "z") {
      const b = r[i].querySelector(`button[data-key="${e.key}"]`);
      if (b) b.click();
    }
  });
  // Copy only: iOS Safari blocks opening a window after an async clipboard write, so "Open LinkedIn" is a plain link.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault();
    const src = document.querySelector(b.dataset.copy);
    const label = b.dataset.label || b.textContent;
    b.dataset.label = label;
    navigator.clipboard.writeText(src.value || src.textContent).then(() => {
      b.textContent = "Copied ✓";
      setTimeout(() => { b.textContent = label; }, 2000);
    }, () => {
      if (window.JobToast) window.JobToast("Couldn't copy. Select the text and copy it manually.");
    });
  });
  function count(t) {
    const out = document.querySelector(t.dataset.counter);
    if (!out) return;
    const n = t.dataset.unit === "words" ? t.value.trim().split(/\s+/).filter(Boolean).length : t.value.length;
    out.textContent = `${n}/${t.dataset.limit} ${t.dataset.unit}`;
    out.classList.toggle("over", n > Number(t.dataset.limit));
  }
  document.addEventListener("input", (e) => { if (e.target.dataset.limit) count(e.target); });
  // On phones the sticky action bar hides while typing, so it never covers the focused field.
  document.addEventListener("focusin", (e) => {
    if (phone() && e.target.matches("textarea, input:not([type=checkbox]):not([type=hidden])")) {
      document.body.classList.add("typing");
    }
  });
  document.addEventListener("focusout", () => document.body.classList.remove("typing"));
  function foldForPhone() {
    if (!phone()) return;
    document.querySelectorAll('details[data-phone-closed], details.col[data-count="0"]')
      .forEach((d) => d.removeAttribute("open"));
  }
  // Rotating to landscape (852px) hides the phone-only summaries, so folded sections must open again.
  phoneQuery.addEventListener("change", () => {
    if (phone()) foldForPhone();
    else document.querySelectorAll("details[data-phone-closed], details.col").forEach((d) => d.setAttribute("open", ""));
  });
  function init() {
    if (!phone()) select(0);
    foldForPhone();
    document.querySelectorAll("[data-limit]").forEach(count);
  }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
  document.addEventListener("htmx:historyRestore", init);
})();
