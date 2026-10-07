/* Swipe left = Skip, swipe right = Snooze on inbox cards (spec §4.7). The decision functions are pure for Node tests. */
(function (root) {
  const LOCK_PX = 10;         // movement before a gesture is classified
  const EDGE_PX = 24;         // iOS edge-swipe "back" zone
  const COMMIT_RATIO = 0.35;  // of card width
  const FLICK_SPEED = 0.5;    // px per ms
  const FLICK_MIN_PX = 40;

  function decide(start, current) {
    if (start.x < EDGE_PX) return { mode: "none" };
    const dx = current.x - start.x, dy = current.y - start.y;
    if (Math.abs(dx) < LOCK_PX && Math.abs(dy) < LOCK_PX) return { mode: "none" };
    return { mode: Math.abs(dx) > 1.5 * Math.abs(dy) ? "swipe" : "scroll" };
  }

  function release(start, end, cardWidth) {
    const dx = end.x - start.x, dt = Math.max(1, end.t - start.t);
    const far = Math.abs(dx) >= COMMIT_RATIO * cardWidth;
    const flick = Math.abs(dx) >= FLICK_MIN_PX && Math.abs(dx) / dt >= FLICK_SPEED;
    if (!far && !flick) return null;
    return dx < 0 ? "skip" : "snooze";
  }

  function parseOutcome(finalUrl, ok, status) {
    const params = new URL(finalUrl, "http://localhost").searchParams;
    const err = params.get("err");
    if (!ok || err) return { ok: false, message: err || `Request failed (HTTP ${status})` };
    return { ok: true, message: params.get("msg") || "Done" };
  }

  const api = { decide, release, parseOutcome };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.JobSwipe = api;

  // ---- browser wiring ----
  const reduced = () => root.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let toastTimer;

  function toast(text, undo) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.replaceChildren();
    const span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    if (undo) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "Undo";
      b.addEventListener("click", () => { el.hidden = true; undo(); });
      el.appendChild(b);
    }
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }
  root.JobToast = toast;

  async function post(url, fields) {
    let resp;
    try {
      resp = await fetch(url, { method: "POST", body: new URLSearchParams(fields), credentials: "same-origin" });
    } catch (e) {
      return { ok: false, message: "Couldn't reach the Mac" };
    }
    return parseOutcome(resp.url, resp.ok, resp.status);
  }

  const ACTIONS = {
    skip: { label: "Skipped", send: (id) => post(`/applications/${id}/status`, { status: "skipped", next: "/" }) },
    snooze: { label: "Snoozed 3 days", send: (id) => post(`/applications/${id}/snooze`, { next: "/" }) },
  };

  function move(card, x, animate) {
    const body = card.querySelector(".card-body");
    body.style.transition = animate && !reduced() ? "transform 180ms ease-out" : "none";
    body.style.transform = x ? `translateX(${x}px)` : "";
    if (x) card.dataset.dir = x < 0 ? "skip" : "snooze"; else delete card.dataset.dir;
  }

  function bind(card) {
    if (card.dataset.swipeBound) return;
    card.dataset.swipeBound = "1";
    let start = null, mode = "none";
    card.addEventListener("touchstart", (e) => {
      const t = e.touches[0];
      start = { x: t.clientX, y: t.clientY, t: e.timeStamp };
      mode = "none";
    }, { passive: true });
    card.addEventListener("touchmove", (e) => {
      if (!start || mode === "scroll") return;
      const t = e.touches[0];
      const current = { x: t.clientX, y: t.clientY, t: e.timeStamp };
      if (mode === "none") mode = decide(start, current).mode;
      if (mode === "swipe") move(card, current.x - start.x, false);
    }, { passive: true });
    card.addEventListener("touchcancel", () => { start = null; move(card, 0, true); });
    card.addEventListener("touchend", async (e) => {
      if (!start) return;
      const t = e.changedTouches[0];
      const action = mode === "swipe" ? release(start, { x: t.clientX, y: t.clientY, t: e.timeStamp }, card.offsetWidth) : null;
      start = null;
      if (!action) { move(card, 0, true); return; }
      const id = card.dataset.appId;
      move(card, action === "skip" ? -card.offsetWidth : card.offsetWidth, true);
      const outcome = await ACTIONS[action].send(id);
      if (!outcome.ok) { move(card, 0, true); toast(outcome.message); return; }
      card.remove();
      toast(ACTIONS[action].label, async () => {
        const undone = await post(`/applications/${id}/undo`, { next: "/" });
        if (undone.ok) root.location.reload(); else toast(undone.message);
      });
    });
  }

  function init() { document.querySelectorAll("[data-swipe]").forEach(bind); }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
})(typeof window !== "undefined" ? window : globalThis);
