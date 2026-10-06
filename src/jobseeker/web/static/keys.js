(function () {
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
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault();
    const src = document.querySelector(b.dataset.copy);
    navigator.clipboard.writeText(src.value || src.textContent).then(() => {
      b.textContent = "Copied ✓";
      if (b.dataset.open) window.open(b.dataset.open, "_blank", "noopener");
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
  function init() { select(0); document.querySelectorAll("[data-limit]").forEach(count); }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
})();
