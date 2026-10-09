// Daily match alerts card (Settings only). cardState is pure so node tests can check it.
(function (root) {
  function cardState(s) {
    if (!s.configured) return "unconfigured";
    if (!s.hasPush || !s.standalone) return "install";
    if (s.permission === "denied") return "blocked";
    if (s.permission === "granted" && s.subscribed) return "on";
    return "ask";
  }

  function keyBytes(b64url) {
    const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
    const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  async function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  async function wire(card) {
    const key = card.dataset.vapidKey || "";
    const show = (state) => card.querySelectorAll("[data-state]").forEach((el) => {
      el.hidden = el.dataset.state !== state;
    });
    const status = card.querySelector("[data-push-status]");
    const hasPush = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
    let sub = null;
    if (hasPush && standalone) {
      const reg = await navigator.serviceWorker.getRegistration("/");
      sub = reg ? await reg.pushManager.getSubscription() : null;
    }
    const state = () => cardState({ hasPush, standalone, configured: !!key, subscribed: !!sub,
      permission: hasPush ? Notification.permission : "default" });
    show(state());

    card.querySelector("[data-push-on]")?.addEventListener("click", async () => {
      try {
        const reg = await navigator.serviceWorker.register("/sw.js");
        await navigator.serviceWorker.ready;
        if ((await Notification.requestPermission()) !== "granted") return show(state());
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
        const res = await post("/push/subscribe", sub.toJSON());
        status.textContent = res.ok ? "" : "Couldn't save this device. Try again.";
      } catch (e) {
        status.textContent = "Couldn't turn on alerts on this device.";
      }
      show(state());
    });
    card.querySelector("[data-push-off]")?.addEventListener("click", async () => {
      if (sub) {
        await post("/push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
        sub = null;
      }
      show(state());
    });
    card.querySelector("[data-push-test]")?.addEventListener("click", async () => {
      if (!sub) return;
      const res = await post("/push/test", { endpoint: sub.endpoint });
      status.textContent = await res.text();
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { cardState };
  } else {
    document.querySelectorAll("[data-push-card]").forEach((card) => { wire(card); });
  }
})(typeof window !== "undefined" ? window : globalThis);
