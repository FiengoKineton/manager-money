(function () {
  const HIDDEN_KEY = "moneyManagerNotificationCenterHidden:v1";

  function safeParse(raw, fallback) {
    try {
      return JSON.parse(raw || "");
    } catch (error) {
      return fallback;
    }
  }

  function loadHidden() {
    const parsed = safeParse(window.localStorage.getItem(HIDDEN_KEY), {});
    return parsed && typeof parsed === "object" ? parsed : {};
  }

  function saveHidden(hidden) {
    window.localStorage.setItem(HIDDEN_KEY, JSON.stringify(hidden));
  }

  function todayIso() {
    return new Date().toISOString().slice(0, 10);
  }

  function plusDays(days) {
    const date = new Date();
    date.setDate(date.getDate() + Number(days || 0));
    return date.toISOString().slice(0, 10);
  }

  function isHiddenUntil(value) {
    if (!value) return false;
    if (value === "ignored") return true;
    return String(value) >= todayIso();
  }

  function cardPayload(card) {
    return {
      id: card.getAttribute("data-center-notification-id") || "",
      title: (card.querySelector("h4") || {}).textContent || "Notification",
      summary: (card.querySelector(".notification-center-meta") || {}).textContent || "",
      detail: (card.querySelector("p") || {}).textContent || "",
      href_label: "Open",
    };
  }

  function postRead(card) {
    const payload = cardPayload(card);
    if (!payload.id) return;
    try {
      window.fetch("/notifications/read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: [payload] }),
        keepalive: true,
      }).catch(() => {});
    } catch (error) {}
  }

  function refreshEmptyStates() {
    document.querySelectorAll("[data-notification-section]").forEach((section) => {
      const visible = Array.from(section.querySelectorAll("[data-center-notification-card]")).filter((card) => !card.hidden);
      section.classList.toggle("is-empty-after-client-filter", visible.length === 0);
      const count = section.querySelector(".notification-section-count");
      if (count) count.textContent = String(visible.length);
    });
  }

  function applyHiddenState() {
    const hidden = loadHidden();
    document.querySelectorAll("[data-center-notification-card]").forEach((card) => {
      const id = card.getAttribute("data-center-notification-id") || "";
      const until = hidden[id];
      card.hidden = isHiddenUntil(until);
    });
    refreshEmptyStates();
  }

  function hideCard(card, until) {
    const id = card.getAttribute("data-center-notification-id") || "";
    if (!id) return;
    const hidden = loadHidden();
    hidden[id] = until || "ignored";
    saveHidden(hidden);
    postRead(card);
    card.hidden = true;
    refreshEmptyStates();
  }

  function wire() {
    const root = document.querySelector("[data-notification-center]");
    if (!root || root.dataset.wired === "true") return;
    root.dataset.wired = "true";
    applyHiddenState();

    root.addEventListener("click", (event) => {
      const card = event.target.closest("[data-center-notification-card]");
      if (!card) return;

      const ignore = event.target.closest("[data-center-ignore]");
      if (ignore) {
        event.preventDefault();
        hideCard(card, "ignored");
        return;
      }

      const snooze = event.target.closest("[data-center-snooze-days]");
      if (snooze) {
        event.preventDefault();
        hideCard(card, plusDays(snooze.getAttribute("data-center-snooze-days") || 3));
        return;
      }

      const setReminder = event.target.closest("[data-center-set-reminder]");
      if (setReminder) {
        event.preventDefault();
        const input = card.querySelector("[data-center-reminder-date]");
        const value = input && input.value ? input.value : plusDays(1);
        hideCard(card, value);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", wire);
  window.addEventListener("pageshow", wire);
})();
