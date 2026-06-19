/* Floating notification panel.
   - Server renders current reminders from CSV state.
   - Browser stores read IDs and a small old-notification history.
   - No backend mutation happens here. */
(function () {
  const READ_KEY = "moneyManagerReadNotificationIds:v1";
  const HISTORY_KEY = "moneyManagerNotificationHistory:v1";
  const MAX_HISTORY = 24;

  function safeParse(value, fallback) {
    try {
      return JSON.parse(value);
    } catch (error) {
      return fallback;
    }
  }

  function loadReadIds() {
    const raw = window.localStorage.getItem(READ_KEY);
    const parsed = safeParse(raw || "[]", []);
    return new Set(Array.isArray(parsed) ? parsed : []);
  }

  function saveReadIds(ids) {
    window.localStorage.setItem(READ_KEY, JSON.stringify(Array.from(ids).slice(-250)));
  }

  function loadHistory() {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    const parsed = safeParse(raw || "[]", []);
    return Array.isArray(parsed) ? parsed : [];
  }

  function saveHistory(history) {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
  }

  function currentCards(menu) {
    return Array.from(menu.querySelectorAll("[data-notification-card][data-current-notification='true']"));
  }

  function allCards(menu) {
    return Array.from(menu.querySelectorAll("[data-notification-card]"));
  }

  function payloadFromCard(card) {
    const base = safeParse(card.getAttribute("data-notification-payload") || "{}", {});
    const link = card.querySelector(".notification-card-meta a");
    return {
      id: card.getAttribute("data-notification-id") || base.id || "",
      tone: base.tone || "info",
      label: base.label || "Reminder",
      icon: base.icon || "•",
      title: base.title || "Notification",
      summary: base.summary || "",
      detail: base.detail || "",
      meta: base.meta || "",
      href: link ? link.getAttribute("href") || "" : base.href || "",
      href_label: link ? link.textContent.trim() || "Open" : base.href_label || "Open",
      sort_date: base.sort_date || "",
      last_seen_at: new Date().toISOString(),
    };
  }

  function syncHistory(menu) {
    const current = currentCards(menu).map(payloadFromCard).filter((item) => item.id);
    if (!current.length) return;

    const byId = new Map();
    current.forEach((item) => byId.set(item.id, item));
    loadHistory().forEach((item) => {
      if (item && item.id && !byId.has(item.id)) byId.set(item.id, item);
    });

    saveHistory(Array.from(byId.values()).slice(0, MAX_HISTORY));
  }

  function updateUnreadState(menu) {
    const readIds = loadReadIds();
    let unreadCount = 0;

    currentCards(menu).forEach((card) => {
      const id = card.getAttribute("data-notification-id") || "";
      const isRead = id ? readIds.has(id) : true;
      card.classList.toggle("is-read", isRead);
      card.classList.toggle("is-unread", !isRead);
      if (!isRead) unreadCount += 1;
    });

    const trigger = menu.querySelector("[data-notification-trigger]");
    const count = menu.querySelector("[data-notification-count]");
    if (trigger) {
      trigger.classList.toggle("has-unread", unreadCount > 0);
      trigger.classList.toggle("has-alerts", unreadCount > 0);
      trigger.classList.toggle("has-notifications", currentCards(menu).length > 0);
    }
    if (count) count.textContent = String(unreadCount);
  }

  function markCardRead(menu, card) {
    const payload = payloadFromCard(card);
    const id = payload.id;

    if (!id) return;

    const readIds = loadReadIds();
    readIds.add(id);
    saveReadIds(readIds);

    postReadToServer([payload]);
    updateUnreadState(menu);
  }

  function markAllRead(menu) {
    const payloads = currentCards(menu).map(payloadFromCard).filter((item) => item.id);

    const readIds = loadReadIds();
    payloads.forEach((item) => {
      readIds.add(item.id);
    });

    saveReadIds(readIds);
    postReadToServer(payloads);
    updateUnreadState(menu);
  }

  function setPanelOpen(menu, open) {
    const trigger = menu.querySelector("[data-notification-trigger]");
    const panel = menu.querySelector("[data-notification-panel]");
    if (!panel) return;

    if (open) {
      panel.hidden = false;
      panel.setAttribute("aria-hidden", "false");
      window.requestAnimationFrame(() => panel.classList.add("is-open"));
    } else {
      panel.classList.remove("is-open");
      panel.setAttribute("aria-hidden", "true");
      window.setTimeout(() => {
        if (!panel.classList.contains("is-open")) panel.hidden = true;
      }, 160);
    }

    if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function closeOtherMenus(activeMenu) {
    document.querySelectorAll("[data-notification-menu]").forEach((menu) => {
      if (menu !== activeMenu) setPanelOpen(menu, false);
    });
  }

  function cardTemplate(item) {
    const article = document.createElement("article");
    article.className = `notification-card notification-card-${item.tone || "info"} is-history is-read`;
    article.setAttribute("data-notification-card", "true");
    article.setAttribute("data-notification-id", item.id || "");

    const href = item.href || "#";
    const hrefLabel = item.href_label || "Open";
    article.innerHTML = `
      <button type="button" class="notification-card-main" data-notification-toggle aria-expanded="false">
        <span class="notification-card-icon" aria-hidden="true"></span>
        <span class="notification-card-copy">
          <span class="notification-card-label"></span>
          <strong></strong>
          <small></small>
        </span>
        <span class="notification-card-chevron" aria-hidden="true">⌄</span>
      </button>
      <div class="notification-card-detail" data-notification-detail hidden>
        <p></p>
        <div class="notification-card-meta">
          <span></span>
          <a></a>
        </div>
      </div>`;

    article.querySelector(".notification-card-icon").textContent = item.icon || "•";
    article.querySelector(".notification-card-label").textContent = item.label || "Old reminder";
    article.querySelector("strong").textContent = item.title || "Notification";
    article.querySelector("small").textContent = item.summary || "";
    article.querySelector("p").textContent = item.detail || "";
    article.querySelector(".notification-card-meta span").textContent = item.meta || "Saved notification";
    const link = article.querySelector(".notification-card-meta a");
    link.textContent = hrefLabel;
    link.setAttribute("href", href);
    return article;
  }

  function renderHistory(menu) {
    const holder = menu.querySelector("[data-notification-history]");
    const list = menu.querySelector("[data-notification-history-list]");
    if (!holder || !list) return;

    const currentIds = new Set(
      currentCards(menu).map((card) => card.getAttribute("data-notification-id"))
    );

    const serverSeed = safeParse(
      list.getAttribute("data-notification-history-seed") || "[]",
      []
    );

    const byId = new Map();

    if (Array.isArray(serverSeed)) {
      serverSeed.forEach((item) => {
        if (item && item.id && !currentIds.has(item.id)) {
          byId.set(item.id, item);
        }
      });
    }

    loadHistory().forEach((item) => {
      if (item && item.id && !currentIds.has(item.id) && !byId.has(item.id)) {
        byId.set(item.id, item);
      }
    });

    const history = Array.from(byId.values()).slice(0, 8);

    list.innerHTML = "";
    history.forEach((item) => list.appendChild(cardTemplate(item)));
    holder.hidden = history.length === 0;
  }

  function toggleCard(menu, card) {
    const isExpanded = card.classList.contains("is-expanded");
    allCards(menu).forEach((other) => {
      if (other === card) return;
      other.classList.remove("is-expanded");
      const detail = other.querySelector("[data-notification-detail]");
      const toggle = other.querySelector("[data-notification-toggle]");
      if (detail) detail.hidden = true;
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });

    card.classList.toggle("is-expanded", !isExpanded);
    const detail = card.querySelector("[data-notification-detail]");
    const toggle = card.querySelector("[data-notification-toggle]");
    if (detail) detail.hidden = isExpanded;
    if (toggle) toggle.setAttribute("aria-expanded", !isExpanded ? "true" : "false");

    if (!isExpanded && card.getAttribute("data-current-notification") === "true") {
      markCardRead(menu, card);
    }
  }

  function wireMenu(menu) {
    if (!menu || menu.dataset.notificationsWired === "true") return;
    menu.dataset.notificationsWired = "true";

    syncHistory(menu);
    renderHistory(menu);
    updateUnreadState(menu);

    const trigger = menu.querySelector("[data-notification-trigger]");
    if (trigger) {
      trigger.addEventListener("click", (event) => {
        event.preventDefault();
        const panel = menu.querySelector("[data-notification-panel]");
        const willOpen = !panel || panel.hidden || !panel.classList.contains("is-open");
        closeOtherMenus(menu);
        setPanelOpen(menu, willOpen);
        if (willOpen) renderHistory(menu);
      });
    }

    menu.addEventListener("click", (event) => {
      const closeButton = event.target.closest("[data-notification-close]");
      if (closeButton) {
        event.preventDefault();
        setPanelOpen(menu, false);
        return;
      }

      const markReadButton = event.target.closest("[data-notification-mark-read]");
      if (markReadButton) {
        event.preventDefault();
        markAllRead(menu);
        return;
      }

      const clearHistoryButton = event.target.closest("[data-notification-clear-history]");
      if (clearHistoryButton) {
        event.preventDefault();
        saveHistory(currentCards(menu).map(payloadFromCard));
        renderHistory(menu);
        return;
      }

      const toggle = event.target.closest("[data-notification-toggle]");
      if (toggle) {
        event.preventDefault();
        const card = toggle.closest("[data-notification-card]");
        if (card) toggleCard(menu, card);
      }
    });
  }

  function wireAll() {
    document.querySelectorAll("[data-notification-menu]").forEach(wireMenu);
  }

  function postReadToServer(items) {
    if (!items || !items.length) return;

    try {
      window.fetch("/notifications/read", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ items }),
        keepalive: true,
      }).catch(() => {});
    } catch (error) {
      // LocalStorage fallback still works.
    }
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-notification-menu]")) return;
    document.querySelectorAll("[data-notification-menu]").forEach((menu) => setPanelOpen(menu, false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("[data-notification-menu]").forEach((menu) => setPanelOpen(menu, false));
  });

  document.addEventListener("DOMContentLoaded", wireAll);
  window.addEventListener("pageshow", wireAll);
})();
