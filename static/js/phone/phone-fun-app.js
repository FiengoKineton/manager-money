/* --------------------------------------------------------------------------
   Phone Fun App v2
   Phone-only experience layer with read-only backend summary data, smoother
   gestures, richer colors/animations, and stronger overflow guards.
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 600px) and (hover: none) and (pointer: coarse), (max-height: 520px) and (max-width: 940px) and (hover: none) and (pointer: coarse)");
  const SUMMARY_URL = "/phone/api/summary";
  const MONEY_RE = /[-+]?\s*(?:€\s*)?([0-9]+(?:[.,][0-9]{1,2})?)/;
  const state = { summary: null, summaryStarted: false, summaryFailed: false };

  const categoryMap = [
    { test: /food|restaurant|lunch|dinner|pizza|bar|coffee|cafe|grocery|supermarket|drink/i, emoji: "🍔", a: "#ff2e93", b: "#ffb703" },
    { test: /transport|metro|train|bus|taxi|fuel|gas|parking|car|flight|travel/i, emoji: "🚆", a: "#00d4ff", b: "#4361ee" },
    { test: /salary|stipend|income|paycheck|work|bonus|polimi|kineton/i, emoji: "💼", a: "#00f5a0", b: "#00d9f5" },
    { test: /invest|stock|etf|portfolio|trading|crypto|market|deposit/i, emoji: "📈", a: "#c77dff", b: "#7209b7" },
    { test: /home|rent|house|utility|bill|electric|water|gas|onedrive|subscription/i, emoji: "🏠", a: "#ff6b6b", b: "#f97316" },
    { test: /health|doctor|medicine|pharmacy|gym|sport/i, emoji: "💪", a: "#2dd4bf", b: "#0f766e" },
    { test: /study|book|course|school|university|kth|exam/i, emoji: "📚", a: "#60a5fa", b: "#7c3aed" },
    { test: /fun|game|cinema|movie|party|gift|shopping|clothes|vinted/i, emoji: "🎮", a: "#f72585", b: "#b5179e" },
    { test: /debt|payable|loan|credit|paypal|card|cila|infissi/i, emoji: "⚠️", a: "#ffd166", b: "#ef476f" },
    { test: /charity|donation|zakat|sadaqah|mosque/i, emoji: "🤲", a: "#34d399", b: "#22d3ee" },
    { test: /transfer|internal|move|pre-paid|prepaid/i, emoji: "🔁", a: "#22d3ee", b: "#818cf8" },
  ];

  function isPhone() {
    return phoneMedia.matches;
  }

  function safeText(node) {
    return String(node ? node.textContent || "" : "").replace(/\s+/g, " ").trim();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function parseMoney(text) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    const sign = /-|expense|paid|spent/i.test(clean) && !/income|salary/i.test(clean) ? -1 : 1;
    const match = clean.match(MONEY_RE);
    if (!match) return 0;
    const value = Number(match[1].replace(",", "."));
    return Number.isFinite(value) ? sign * value : 0;
  }

  function formatMoney(value, signed) {
    const num = Number(value) || 0;
    const abs = Math.abs(num);
    const prefix = signed ? (num < 0 ? "−" : "+") : "";
    return `${prefix}€ ${abs.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function categoryFor(text) {
    return categoryMap.find((entry) => entry.test.test(text || "")) || { emoji: "💸", a: "#7c3aed", b: "#00d4ff" };
  }

  function getPageKind() {
    const title = safeText(document.querySelector(".app-topbar-title h1")).toLowerCase();
    const path = window.location.pathname.toLowerCase();
    if (path.includes("transaction") || title.includes("transaction")) return "transactions";
    if (path.includes("add") || title.includes("add")) return "add";
    if (title.includes("dashboard")) return "dashboard";
    if (title.includes("overview") || path === "/" || path.endsWith("/overview")) return "today";
    if (/pending|recurring|payable|debt|owed|project/.test(title + path)) return "plan";
    if (/analysis|investment|forecast|yearly/.test(title + path)) return "analysis";
    return "other";
  }

  function addGlobalState() {
    const enabled = isPhone();
    document.documentElement.classList.toggle("phone-fun-active", enabled);
    if (document.body) {
      document.body.classList.toggle("phone-fun-active", enabled);
      document.body.dataset.phonePage = enabled ? getPageKind() : "";
    }
  }

  function ensureToastStack() {
    let stack = document.querySelector(".phone-toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "phone-toast-stack";
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    return stack;
  }

  function showToast(icon, title, detail) {
    if (!isPhone()) return;
    const toast = document.createElement("div");
    toast.className = "phone-toast";
    toast.innerHTML = `<span aria-hidden="true">${icon}</span><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail || "")}</small></span>`;
    ensureToastStack().appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add("is-leaving");
      window.setTimeout(() => toast.remove(), 240);
    }, 2500);
  }

  function cachedSummaryFromSession() {
    try {
      const raw = window.sessionStorage.getItem("phoneExperienceSummary.v1");
      if (!raw) return null;
      const record = JSON.parse(raw);
      if (!record || !record.savedAt || !record.value) return null;
      if (Date.now() - Number(record.savedAt) > 90 * 1000) return null;
      return record.value;
    } catch (error) {
      return null;
    }
  }

  function saveSummaryToSession(value) {
    try {
      window.sessionStorage.setItem("phoneExperienceSummary.v1", JSON.stringify({ savedAt: Date.now(), value }));
    } catch (error) {}
  }

  function loadSummary() {
    if (!isPhone() || state.summaryStarted) return;
    const cached = cachedSummaryFromSession();
    if (cached) {
      state.summaryStarted = true;
      state.summary = cached;
      updateTodayCockpit();
      decorateCards();
      return;
    }

    state.summaryStarted = true;
    const runFetch = () => {
      window.fetch(SUMMARY_URL, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("summary failed")))
        .then((data) => {
          state.summary = data || null;
          saveSummaryToSession(state.summary);
          updateTodayCockpit();
          decorateCards();
        })
        .catch(() => {
          state.summaryFailed = true;
        });
    };

    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(runFetch, { timeout: 900 });
    } else {
      window.setTimeout(runFetch, 180);
    }
  }

  function extractNetText() {
    return safeText(document.querySelector(".topbar-net-pill strong")) || safeText(document.querySelector(".net-pill strong")) || "€ 0.00";
  }

  function extractMiniStatsFallback() {
    const cards = Array.from(document.querySelectorAll(".overview-metric-grid .summary-card, .dashboard-kpi-grid .summary-card, .summary .summary-card, .transactions-summary-grid .summary-card"));
    const picked = [];
    ["visible", "pending", "debt", "owed", "spent", "income", "investment", "net"].forEach((needle) => {
      const card = cards.find((node) => safeText(node).toLowerCase().includes(needle) && !picked.includes(node));
      if (card && picked.length < 3) picked.push(card);
    });
    while (picked.length < 3 && cards[picked.length]) picked.push(cards[picked.length]);
    return picked.slice(0, 3).map((card) => ({
      label: safeText(card.querySelector("span, h3, dt")) || "Metric",
      value: safeText(card.querySelector("strong, p, dd")) || "—",
    }));
  }

  function extractNotificationsFallback(limit) {
    const items = [];
    document.querySelectorAll(".notification-card").forEach((card) => {
      if (items.length >= limit) return;
      const title = safeText(card.querySelector("strong")) || "Reminder";
      const detail = safeText(card.querySelector("small, p"));
      const href = card.querySelector("a") ? card.querySelector("a").getAttribute("href") : "#";
      const icon = card.classList.contains("notification-card-critical") ? "🔴" : card.classList.contains("notification-card-warning") ? "🟡" : "🔔";
      items.push({ title, detail, href, icon });
    });
    return items;
  }

  function buildMoneyMoodFallback(netText, alerts) {
    const net = parseMoney(netText);
    if (alerts.length >= 2 || net < 0) return { icon: "🔴", label: "Pressure", title: "Check money pressure", detail: "You have reminders that deserve attention before spending freely." };
    if (alerts.length === 1 || net < 350) return { icon: "🟡", label: "Careful", title: "Stay sharp today", detail: "You are okay, but one thing may need a quick check." };
    return { icon: "🟢", label: "Safe", title: "You look safe today", detail: "No heavy warning is visible from the current page state." };
  }

  function extractRecentTransactionsFallback(limit) {
    const result = [];
    document.querySelectorAll(".recent-row, .phone-transaction-card").forEach((row) => {
      if (result.length >= limit) return;
      const title = safeText(row.querySelector("strong, b")) || safeText(row);
      const amount = safeText(row.querySelector("b:last-child, .phone-transaction-amount, .transaction-amount-cell"));
      const detail = safeText(row.querySelector("span, small"));
      result.push({ title, amount, detail, category: categoryFor(title + " " + detail) });
    });
    return result;
  }

  function cockpitData() {
    const net = extractNetText();
    if (state.summary) {
      const metrics = state.summary.metrics || {};
      return {
        net,
        mood: state.summary.mood || buildMoneyMoodFallback(net, []),
        stats: [
          { label: "Today spent", value: formatMoney(metrics.today_spent || 0) },
          { label: "This week", value: formatMoney(metrics.week_spent || 0) },
          { label: "This month", value: formatMoney(metrics.month_spent || 0) },
        ],
        daily: Array.isArray(state.summary.daily_spending) ? state.summary.daily_spending : [],
        checks: Array.isArray(state.summary.smart_checks) ? state.summary.smart_checks : [],
        categories: Array.isArray(state.summary.category_spending) ? state.summary.category_spending : [],
        recent: Array.isArray(state.summary.recent) ? state.summary.recent : [],
        quickActions: Array.isArray(state.summary.quick_actions) ? state.summary.quick_actions : [],
        source: "api",
      };
    }
    const alerts = extractNotificationsFallback(4);
    return {
      net,
      mood: buildMoneyMoodFallback(net, alerts),
      stats: extractMiniStatsFallback(),
      daily: [],
      checks: alerts,
      categories: [],
      recent: extractRecentTransactionsFallback(6),
      quickActions: [
        { label: "Add expense", href: document.querySelector(".quick-add-expense")?.getAttribute("href") || "/add?type=expense", icon: "💸" },
        { label: "Open logs", href: document.querySelector('a[href*="transactions"]')?.getAttribute("href") || "/transactions", icon: "≡" },
      ],
      source: "dom",
    };
  }

  function weekBars(daily, recent) {
    let rows = Array.isArray(daily) && daily.length ? daily : [];
    if (!rows.length) {
      const amounts = recent.slice(0, 7).map((item) => Math.abs(parseMoney(item.amount || item.detail || item.title))).reverse();
      while (amounts.length < 7) amounts.unshift(0);
      rows = ["M", "T", "W", "T", "F", "S", "S"].map((label, index) => ({ label, amount: amounts[index] }));
    }
    const max = Math.max(1, ...rows.map((item) => Number(item.amount) || 0));
    return rows.slice(-7).map((item, index) => {
      const value = Math.min(1, (Number(item.amount) || 0) / max);
      const label = item.label || ["M", "T", "W", "T", "F", "S", "S"][index] || "•";
      return `<span class="phone-week-bar" style="--bar-value:${value.toFixed(3)}"><span></span>${escapeHtml(label)}</span>`;
    }).join("");
  }

  function categoriesHtml(categories) {
    if (!categories || !categories.length) return "";
    return `<article class="phone-section-card phone-category-pulse-card">
      <div class="phone-section-head"><span><strong>Color map</strong><small>Top spending this month</small></span></div>
      <div class="phone-category-pulse-row">
        ${categories.slice(0, 6).map((item) => {
          const cat = categoryFor(item.category);
          return `<span class="phone-category-pulse" style="--chip-a:${cat.a};--chip-b:${cat.b}"><b>${cat.emoji} ${escapeHtml(item.category)}</b><small>${formatMoney(item.amount || 0)}</small></span>`;
        }).join("")}
      </div>
    </article>`;
  }

  function recentHtml(recent) {
    if (!recent || !recent.length) return "";
    return `<article class="phone-section-card phone-mini-feed-card">
      <div class="phone-section-head"><span><strong>Latest moves</strong><small>Recent money activity</small></span><a href="/transactions">View all</a></div>
      <div class="phone-mini-feed">
        ${recent.slice(0, 5).map((item) => {
          const cat = categoryFor(`${item.category || ""} ${item.title || ""}`);
          const amount = item.signed_amount !== undefined ? formatMoney(item.signed_amount, true) : escapeHtml(item.amount || "");
          return `<a class="phone-mini-feed-item" href="${item.href || "/transactions"}" style="--chip-a:${cat.a};--chip-b:${cat.b}"><span>${cat.emoji}</span><b>${escapeHtml(item.title || item.category || "Money log")}</b><small>${escapeHtml(item.subtitle || item.detail || "")}</small><em>${amount}</em></a>`;
        }).join("")}
      </div>
    </article>`;
  }

  function checksHtml(checks) {
    const rows = checks && checks.length ? checks : [{ title: "Nothing urgent", detail: "No due payment or old debt warning is visible right now.", href: "#", icon: "✅" }];
    return rows.slice(0, 4).map((item) => `
      <a class="phone-upcoming-item phone-tone-${item.tone || "info"}" href="${item.href || "#"}">
        <span class="phone-upcoming-icon" aria-hidden="true">${item.icon || "🔔"}</span>
        <span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.detail || item.summary || "")}</small></span>
        <span aria-hidden="true">›</span>
      </a>`).join("");
  }

  function quickActionsHtml(actions) {
    const rows = actions && actions.length ? actions : [];
    return rows.slice(0, 4).map((action, index) => `<a class="phone-quick-pill phone-quick-${index}" href="${action.href || "#"}"><span>${action.icon || "＋"}</span>${escapeHtml(action.label || "Open")}</a>`).join("");
  }

  function renderCockpit(cockpit) {
    const data = cockpitData();
    const hour = new Date().getHours();
    const daypart = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
    cockpit.dataset.phoneSummarySource = data.source;
    cockpit.innerHTML = `
      <article class="phone-today-hero">
        <span class="phone-hero-orb phone-hero-orb-a" aria-hidden="true"></span>
        <span class="phone-hero-orb phone-hero-orb-b" aria-hidden="true"></span>
        <div class="phone-greeting-row">
          <span><strong>Good ${daypart} 👋</strong><small>Today money cockpit</small></span>
          <span class="phone-mood-pill">${data.mood.icon} ${escapeHtml(data.mood.label)}</span>
        </div>
        <div class="phone-net-block">
          <span class="phone-net-label">Main net</span>
          <strong>${escapeHtml(data.net)}</strong>
        </div>
        <div class="phone-mood-row">
          <span class="phone-mood-icon" aria-hidden="true">${data.mood.icon}</span>
          <span class="phone-mood-copy"><strong>${escapeHtml(data.mood.title)}</strong><small>${escapeHtml(data.mood.detail)}</small></span>
        </div>
        <div class="phone-action-row">${quickActionsHtml(data.quickActions)}</div>
      </article>
      ${data.stats.length ? `<div class="phone-mini-stats">${data.stats.map((item) => `<article class="phone-mini-stat"><small>${escapeHtml(item.label)}</small><strong>${escapeHtml(item.value)}</strong></article>`).join("")}</div>` : ""}
      <article class="phone-section-card phone-week-card">
        <div class="phone-section-head"><span><strong>This week pulse</strong><small>${data.source === "api" ? "Live from your data" : "Based on visible rows"}</small></span></div>
        <div class="phone-week-bars">${weekBars(data.daily, data.recent)}</div>
      </article>
      ${categoriesHtml(data.categories)}
      <article class="phone-section-card">
        <div class="phone-section-head"><span><strong>Smart checks</strong><small>Things to remember</small></span></div>
        <div class="phone-upcoming-list">${checksHtml(data.checks)}</div>
      </article>
      ${recentHtml(data.recent)}
    `;
  }

  function createTodayCockpit() {
    if (!isPhone()) return;
    const stage = document.querySelector(".app-content-stage");
    if (!stage) return;
    const pageKind = getPageKind();
    if (!["today", "dashboard"].includes(pageKind)) return;
    let cockpit = stage.querySelector(":scope > .phone-today-cockpit");
    if (!cockpit) {
      cockpit = document.createElement("section");
      cockpit.className = "phone-today-cockpit";
      stage.insertBefore(cockpit, stage.firstElementChild);
    }
    renderCockpit(cockpit);
    loadSummary();
  }

  function updateTodayCockpit() {
    const cockpit = document.querySelector(".phone-today-cockpit");
    if (cockpit && isPhone()) renderCockpit(cockpit);
  }

  function addFeedHeader() {
    if (!isPhone()) return;
    const list = document.querySelector(".phone-transaction-list");
    if (!list || list.dataset.funFeedReady === "true") return;
    list.dataset.funFeedReady = "true";
    const header = document.createElement("div");
    header.className = "phone-money-feed-head";
    header.innerHTML = `<strong>Money feed</strong><small>Tap to peek. Swipe left for quick action.</small>`;
    const chips = document.createElement("div");
    chips.className = "phone-filter-chips";
    chips.innerHTML = `
      <button class="phone-filter-chip is-active" data-phone-feed-filter="all" type="button">✨ All</button>
      <button class="phone-filter-chip" data-phone-feed-filter="expense" type="button">💸 Expenses</button>
      <button class="phone-filter-chip" data-phone-feed-filter="income" type="button">💰 Income</button>
      <button class="phone-filter-chip" data-phone-feed-filter="investment" type="button">📈 Investing</button>`;
    list.parentNode.insertBefore(header, list);
    list.parentNode.insertBefore(chips, list);
    chips.addEventListener("click", (event) => {
      const button = event.target.closest("[data-phone-feed-filter]");
      if (!button) return;
      const filter = button.dataset.phoneFeedFilter;
      chips.querySelectorAll(".phone-filter-chip").forEach((chip) => chip.classList.toggle("is-active", chip === button));
      document.querySelectorAll(".phone-transaction-card").forEach((card) => {
        const text = safeText(card).toLowerCase();
        const kind = card.classList.contains("row-expense") || text.includes("expense") ? "expense" : card.classList.contains("row-income") || text.includes("income") ? "income" : card.classList.contains("row-investment") || text.includes("investment") ? "investment" : "other";
        card.hidden = filter !== "all" && kind !== filter;
      });
    });
  }

  function ensureSwipeAction(card) {
    let action = card.querySelector(":scope > .phone-swipe-action");
    if (!action) {
      action = document.createElement("span");
      action.className = "phone-swipe-action";
      action.textContent = "Open";
      card.appendChild(action);
    }
    return action;
  }

  function ensureSwipeFront(card) {
    let front = card.querySelector(":scope > .phone-swipe-front");
    const action = ensureSwipeAction(card);
    if (front) return front;

    front = document.createElement("span");
    front.className = "phone-swipe-front";

    Array.from(card.childNodes).forEach((node) => {
      if (node === action) return;
      front.appendChild(node);
    });

    card.insertBefore(front, action);
    return front;
  }

  function decorateCards() {
    if (!isPhone()) return;
    const cards = Array.from(document.querySelectorAll(".phone-transaction-card, .recent-row, tr.mobile-disclosure-row"));
    cards.forEach((card, index) => {
      if (card.dataset.phoneDecorated === "true") return;
      card.dataset.phoneDecorated = "true";
      card.style.setProperty("--phone-card-index", String(index));
      const label = safeText(card.querySelector("b, strong, .mobile-row-title, td:nth-child(3)")) || safeText(card);
      const category = categoryFor(label + " " + safeText(card));
      card.style.setProperty("--chip-a", category.a);
      card.style.setProperty("--chip-b", category.b);

      if (card.matches(".phone-transaction-card")) {
        if (!card.querySelector(".phone-card-emoji")) {
          const icon = document.createElement("span");
          icon.className = "phone-card-emoji";
          icon.textContent = category.emoji;
          card.insertBefore(icon, card.firstElementChild);
        }
        const front = ensureSwipeFront(card);
        front.style.transform = card.classList.contains("is-swiped") ? "translate3d(-76px,0,0)" : "translate3d(0,0,0)";
      }
    });
  }

  function closeOpenSwipes(except) {
    document.querySelectorAll(".phone-transaction-card.is-swiped").forEach((card) => {
      if (card === except) return;
      const front = card.querySelector(":scope > .phone-swipe-front");
      card.classList.remove("is-swiped", "is-swiping");
      card.style.removeProperty("--swipe-x");
      if (front) front.style.transform = "translate3d(0,0,0)";
    });
  }

  function wireExpandableTransactionCards() {
    if (!isPhone()) return;
    document.querySelectorAll(".phone-transaction-card").forEach((card) => {
      if (card.dataset.phoneExpandable === "true") return;
      card.dataset.phoneExpandable = "true";
      let lastExpandedTap = 0;
      card.addEventListener("click", (event) => {
        if (!isPhone()) return;
        if (card.dataset.justSwiped === "true") {
          event.preventDefault();
          event.stopPropagation();
          card.dataset.justSwiped = "false";
          return;
        }
        if (card.classList.contains("is-swiped")) {
          event.preventDefault();
          const front = card.querySelector(":scope > .phone-swipe-front");
          card.classList.remove("is-swiped", "is-swiping");
          if (front) front.style.transform = "translate3d(0,0,0)";
          return;
        }
        const now = Date.now();
        if (!card.classList.contains("is-expanded")) {
          event.preventDefault();
          closeOpenSwipes(card);
          document.querySelectorAll(".phone-transaction-card.is-expanded").forEach((open) => {
            if (open !== card) open.classList.remove("is-expanded");
          });
          card.classList.add("is-expanded");
          lastExpandedTap = now;
          return;
        }
        if (now - lastExpandedTap < 260) event.preventDefault();
      });
    });
  }

  function wireSwipeGestures() {
    if (!isPhone()) return;
    document.querySelectorAll(".phone-transaction-card").forEach((card) => {
      if (card.dataset.phoneSwipeReady === "true") return;
      card.dataset.phoneSwipeReady = "true";
      let startX = 0;
      let startY = 0;
      let lastX = 0;
      let pointerId = null;
      let locked = false;
      let dragging = false;
      let raf = 0;
      let pendingX = 0;
      let front = null;

      function setFrontX(x) {
        pendingX = x;
        if (raf) return;
        raf = window.requestAnimationFrame(() => {
          if (front) front.style.transform = `translate3d(${pendingX}px,0,0)`;
          raf = 0;
        });
      }

      function releasePointer() {
        try {
          if (pointerId !== null && card.hasPointerCapture && card.hasPointerCapture(pointerId)) {
            card.releasePointerCapture(pointerId);
          }
        } catch (error) {}
      }

      function finish(open) {
        if (raf) {
          window.cancelAnimationFrame(raf);
          raf = 0;
        }
        releasePointer();
        dragging = false;
        locked = false;
        pointerId = null;
        card.classList.remove("is-swiping", "is-swipe-ready");
        card.classList.toggle("is-swiped", open);
        if (front) front.style.transform = open ? "translate3d(-76px,0,0)" : "translate3d(0,0,0)";
        if (open) {
          card.dataset.justSwiped = "true";
          window.setTimeout(() => { card.dataset.justSwiped = "false"; }, 140);
        }
      }

      card.addEventListener("pointerdown", (event) => {
        if (!isPhone() || event.pointerType === "mouse") return;
        if (event.target.closest("button, input, select, textarea")) return;
        front = ensureSwipeFront(card);
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        lastX = startX;
        locked = false;
        dragging = true;
        card.classList.add("is-swipe-ready");
        try { card.setPointerCapture(pointerId); } catch (error) {}
      }, { passive: true });

      card.addEventListener("pointermove", (event) => {
        if (!dragging || event.pointerId !== pointerId) return;
        const dxRaw = event.clientX - startX;
        const dy = Math.abs(event.clientY - startY);
        lastX = event.clientX;
        if (!locked) {
          if (dy > 16 && Math.abs(dxRaw) < 18) {
            finish(card.classList.contains("is-swiped"));
            return;
          }
          if (Math.abs(dxRaw) > 9 && dy < 26) {
            locked = true;
            closeOpenSwipes(card);
          }
        }
        if (!locked) return;
        event.preventDefault();
        const base = card.classList.contains("is-swiped") ? -76 : 0;
        const dx = Math.max(-86, Math.min(0, base + dxRaw));
        card.classList.add("is-swiping");
        setFrontX(dx);
      }, { passive: false });

      function end(event) {
        if (!dragging || (event && event.pointerId !== pointerId)) return;
        const dx = lastX - startX;
        const wasOpen = card.classList.contains("is-swiped");
        const open = wasOpen ? !(dx > 30) : dx < -38;
        finish(open);
      }

      card.addEventListener("pointerup", end, { passive: true });
      card.addEventListener("pointercancel", () => finish(card.classList.contains("is-swiped")), { passive: true });
    });
  }

  function addModeCards(form) {
    const tabs = document.querySelector(".transaction-kind-tabs");
    if (!tabs || form.querySelector(".phone-mode-card-row")) return;
    const row = document.createElement("div");
    row.className = "phone-mode-card-row";
    row.innerHTML = Array.from(tabs.querySelectorAll("a")).map((link) => {
      const text = safeText(link);
      const icon = /income/i.test(text) ? "💰" : /invest/i.test(text) ? "📈" : /special/i.test(text) ? "⭐" : "💸";
      return `<a href="${link.getAttribute("href") || "#"}" class="${link.classList.contains("active") ? "active" : ""}"><b>${icon} ${escapeHtml(text)}</b><small>Choose type</small></a>`;
    }).join("");
    form.insertBefore(row, form.firstElementChild?.nextSibling || form.firstElementChild);
  }

  function addCalculatorPad(form) {
    const amount = form.querySelector('input[name="amount"]');
    if (!amount || form.querySelector(".phone-calculator-pad")) return;
    const pad = document.createElement("div");
    pad.className = "phone-calculator-pad";
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].forEach((key) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = key;
      btn.addEventListener("click", () => {
        if (key === "⌫") amount.value = amount.value.slice(0, -1);
        else if (key === "." && amount.value.includes(".")) return;
        else amount.value += key;
        amount.dispatchEvent(new Event("input", { bubbles: true }));
      });
      pad.appendChild(btn);
    });
    const field = amount.closest(".form-field, .phone-add-step") || amount.parentNode;
    field.appendChild(pad);
  }

  function addCategoryCards(form) {
    const select = form.querySelector('select[name="category"]');
    if (!select || form.querySelector(".phone-category-card-row")) return;
    const row = document.createElement("div");
    row.className = "phone-category-card-row";
    Array.from(select.options).filter((option) => option.value).slice(0, 10).forEach((option) => {
      const cat = categoryFor(option.textContent || option.value);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "phone-category-card";
      btn.innerHTML = `<b>${cat.emoji} ${escapeHtml(option.textContent || option.value)}</b><small>Category</small>`;
      btn.style.setProperty("--chip-a", cat.a);
      btn.style.setProperty("--chip-b", cat.b);
      btn.addEventListener("click", () => {
        select.value = option.value;
        row.querySelectorAll(".phone-category-card").forEach((item) => item.classList.toggle("is-selected", item === btn));
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      if (option.selected) btn.classList.add("is-selected");
      row.appendChild(btn);
    });
    select.closest(".form-field, .phone-add-step")?.appendChild(row);
  }

  function setupPagedAddFlow() {
    if (!isPhone()) return;
    document.querySelectorAll(".normal-add-polished .transaction-form").forEach((form) => {
      if (form.dataset.phoneFunPaged === "true") return;
      const steps = Array.from(form.querySelectorAll(".phone-add-step"));
      if (!steps.length) return;
      form.dataset.phoneFunPaged = "true";
      form.classList.add("phone-flow-paged");
      let active = 0;
      const nav = document.createElement("div");
      nav.className = "phone-flow-nav";
      nav.innerHTML = `<button type="button" data-phone-flow-prev>Back</button><button type="button" data-phone-flow-next>Next</button>`;
      form.appendChild(nav);
      const prev = nav.querySelector("[data-phone-flow-prev]");
      const next = nav.querySelector("[data-phone-flow-next]");
      function sync() {
        steps.forEach((step, index) => step.classList.toggle("is-active", index === active));
        prev.disabled = active === 0;
        next.textContent = active >= steps.length - 1 ? "Review" : "Next";
        form.querySelectorAll(".phone-add-progress-dots span").forEach((dot, index) => dot.classList.toggle("is-active", index <= active));
      }
      prev.addEventListener("click", () => {
        active = Math.max(0, active - 1);
        sync();
        steps[active].scrollIntoView({ block: "center", behavior: "smooth" });
      });
      next.addEventListener("click", () => {
        if (active >= steps.length - 1) {
          const submit = form.querySelector('button[type="submit"], input[type="submit"]');
          if (submit) submit.scrollIntoView({ block: "center", behavior: "smooth" });
          showToast("✅", "Ready to save", "Check the final card and press Save.");
          return;
        }
        active = Math.min(steps.length - 1, active + 1);
        sync();
        steps[active].scrollIntoView({ block: "center", behavior: "smooth" });
      });
      addModeCards(form);
      addCalculatorPad(form);
      addCategoryCards(form);
      sync();
    });
  }

  function wireFormFeedback() {
    if (!isPhone()) return;
    document.querySelectorAll("form").forEach((form) => {
      if (form.dataset.phoneToastSubmit === "true") return;
      form.dataset.phoneToastSubmit = "true";
      form.addEventListener("submit", () => {
        if (!isPhone()) return;
        const amount = form.querySelector('input[name="amount"]')?.value;
        const category = form.querySelector('select[name="category"] option:checked')?.textContent || form.querySelector('input[name="category"]')?.value || "Money log";
        if (amount) showToast("🎉", "Saving transaction", `${category} · € ${amount}`);
      });
    });
  }

  function resizePlotlyCharts() {
    if (!isPhone() || !window.Plotly) return;
    window.setTimeout(() => {
      document.querySelectorAll(".js-plotly-plot, .plotly-graph-div").forEach((plot) => {
        try { window.Plotly.Plots.resize(plot); } catch (error) {}
      });
    }, 260);
  }

  function boot() {
    addGlobalState();
    if (!isPhone()) return;
    createTodayCockpit();
    addFeedHeader();
    decorateCards();
    wireExpandableTransactionCards();
    wireSwipeGestures();
    setupPagedAddFlow();
    wireFormFeedback();
    resizePlotlyCharts();
    loadSummary();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => window.setTimeout(boot, 80));
  } else {
    window.setTimeout(boot, 80);
  }
  window.addEventListener("pageshow", () => window.setTimeout(boot, 80));
  window.addEventListener("orientationchange", () => window.setTimeout(() => { boot(); resizePlotlyCharts(); }, 260), { passive: true });
  window.addEventListener("resize", () => window.setTimeout(() => { addGlobalState(); resizePlotlyCharts(); }, 220), { passive: true });
  if (phoneMedia.addEventListener) phoneMedia.addEventListener("change", boot);
})();
