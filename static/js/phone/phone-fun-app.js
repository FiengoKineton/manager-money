/* --------------------------------------------------------------------------
   Phone Fun App v1
   Frontend-only phone experience layer. It reads existing DOM/data and adds a
   native-feeling mobile cockpit, feed polish, gestures and add-flow controls.
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 1120px), (hover: none) and (pointer: coarse)");
  const MONEY_RE = /[-+]?\s*(?:€\s*)?([0-9]+(?:[.,][0-9]{1,2})?)/;

  const categoryMap = [
    { test: /food|restaurant|lunch|dinner|pizza|bar|coffee|cafe|grocery|supermarket|drink/i, emoji: "🍔", a: "#ff6b6b", b: "#feca57" },
    { test: /transport|metro|train|bus|taxi|fuel|gas|parking|car|flight|travel/i, emoji: "🚆", a: "#38bdf8", b: "#2563eb" },
    { test: /salary|stipend|income|paycheck|work|bonus/i, emoji: "💼", a: "#22c55e", b: "#14b8a6" },
    { test: /invest|stock|etf|portfolio|trading|crypto|market/i, emoji: "📈", a: "#a78bfa", b: "#7c3aed" },
    { test: /home|rent|house|utility|bill|electric|water|gas/i, emoji: "🏠", a: "#fb7185", b: "#f97316" },
    { test: /health|doctor|medicine|pharmacy|gym|sport/i, emoji: "💪", a: "#2dd4bf", b: "#0f766e" },
    { test: /study|book|course|school|university|kth|exam/i, emoji: "📚", a: "#60a5fa", b: "#6366f1" },
    { test: /fun|game|cinema|movie|party|gift|shopping|clothes/i, emoji: "🎮", a: "#f472b6", b: "#c026d3" },
    { test: /debt|payable|loan|credit|paypal|card/i, emoji: "⚠️", a: "#facc15", b: "#fb7185" },
    { test: /charity|donation|zakat|sadaqah|mosque/i, emoji: "🤲", a: "#34d399", b: "#22d3ee" },
    { test: /transfer|internal|move/i, emoji: "🔁", a: "#22d3ee", b: "#818cf8" },
  ];

  function isPhone() {
    return phoneMedia.matches;
  }

  function safeText(node) {
    return String(node ? node.textContent || "" : "").replace(/\s+/g, " ").trim();
  }

  function parseMoney(text) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    const sign = /-|expense|paid|spent/i.test(clean) && !/income|salary/i.test(clean) ? -1 : 1;
    const match = clean.match(MONEY_RE);
    if (!match) return 0;
    const value = Number(match[1].replace(",", "."));
    return Number.isFinite(value) ? sign * value : 0;
  }

  function formatMoney(value) {
    const abs = Math.abs(Number(value) || 0);
    return `€ ${abs.toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function categoryFor(text) {
    const match = categoryMap.find((entry) => entry.test.test(text || ""));
    return match || { emoji: "💸", a: "#7c3aed", b: "#00d4ff" };
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
    const stack = ensureToastStack();
    const toast = document.createElement("div");
    toast.className = "phone-toast";
    toast.innerHTML = `<span aria-hidden="true">${icon}</span><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail || "")}</small></span>`;
    stack.appendChild(toast);
    window.setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translate3d(0, 0.8rem, 0)";
      window.setTimeout(() => toast.remove(), 220);
    }, 2600);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function addGlobalState() {
    document.documentElement.classList.toggle("phone-fun-active", isPhone());
    if (document.body) {
      document.body.classList.toggle("phone-fun-active", isPhone());
      document.body.dataset.phonePage = isPhone() ? getPageKind() : "";
    }
  }

  function extractNetText() {
    return safeText(document.querySelector(".topbar-net-pill strong")) || safeText(document.querySelector(".net-pill strong")) || "€ 0.00";
  }

  function extractMiniStats() {
    const cards = Array.from(document.querySelectorAll(".overview-metric-grid .summary-card, .dashboard-kpi-grid .summary-card, .summary .summary-card, .transactions-summary-grid .summary-card"));
    const preferred = ["visible", "pending", "debt", "owed", "spent", "income", "investment", "net"];
    const picked = [];

    preferred.forEach((needle) => {
      const card = cards.find((node) => safeText(node).toLowerCase().includes(needle) && !picked.includes(node));
      if (card && picked.length < 3) picked.push(card);
    });

    while (picked.length < 3 && cards[picked.length]) picked.push(cards[picked.length]);

    return picked.slice(0, 3).map((card) => {
      const label = safeText(card.querySelector("span, h3, dt")) || "Metric";
      const value = safeText(card.querySelector("strong, p, dd")) || "—";
      return { label, value };
    });
  }

  function extractRecentTransactions(limit) {
    const result = [];
    document.querySelectorAll(".recent-row, .phone-transaction-card").forEach((row) => {
      if (result.length >= limit) return;
      const title = safeText(row.querySelector("strong, b")) || safeText(row);
      const amount = safeText(row.querySelector("b:last-child, .phone-transaction-amount, .transaction-amount-cell"));
      const detail = safeText(row.querySelector("span, small"));
      result.push({ title, amount, detail, kind: amountKind(amount + " " + safeText(row)), category: categoryFor(title + " " + detail) });
    });
    return result;
  }

  function amountKind(text) {
    const lower = String(text || "").toLowerCase();
    if (/income|salary|\+/.test(lower)) return "income";
    if (/expense|paid|spent|debt|payable|-/.test(lower)) return "expense";
    if (/investment|invest/.test(lower)) return "investment";
    return "neutral";
  }

  function extractNotifications(limit) {
    const items = [];
    document.querySelectorAll(".notification-card").forEach((card) => {
      if (items.length >= limit) return;
      const title = safeText(card.querySelector("strong")) || "Reminder";
      const detail = safeText(card.querySelector("small, p"));
      const href = card.querySelector("a") ? card.querySelector("a").getAttribute("href") : "#";
      items.push({ title, detail, href, icon: card.classList.contains("notification-card-critical") ? "🔴" : card.classList.contains("notification-card-warning") ? "🟡" : "🔔" });
    });
    return items;
  }

  function buildMoneyMood(netText, alerts) {
    const net = parseMoney(netText);
    const alertCount = alerts.length;
    if (alertCount >= 2 || net < 0) {
      return { icon: "🔴", label: "Pressure", title: "Check money pressure", detail: "You have reminders that deserve attention before spending freely." };
    }
    if (alertCount === 1 || net < 350) {
      return { icon: "🟡", label: "Careful", title: "Stay sharp today", detail: "You are okay, but one thing may need a quick check." };
    }
    return { icon: "🟢", label: "Safe", title: "You look safe today", detail: "No heavy warning is visible from the current page state." };
  }

  function buildWeekBars(recent) {
    const amounts = recent.slice(0, 7).map((item) => Math.abs(parseMoney(item.amount || item.detail || item.title))).reverse();
    while (amounts.length < 7) amounts.unshift(0);
    const max = Math.max(1, ...amounts);
    const labels = ["M", "T", "W", "T", "F", "S", "S"];
    return labels.map((label, index) => {
      const value = Math.min(1, amounts[index] / max);
      return `<span class="phone-week-bar"><span style="--bar-value:${value.toFixed(3)}"></span>${label}</span>`;
    }).join("");
  }

  function createTodayCockpit() {
    if (!isPhone()) return;
    const stage = document.querySelector(".app-content-stage");
    if (!stage || stage.querySelector(":scope > .phone-today-cockpit")) return;

    const pageKind = getPageKind();
    if (!["today", "dashboard"].includes(pageKind)) return;

    const net = extractNetText();
    const miniStats = extractMiniStats();
    const recent = extractRecentTransactions(7);
    const alerts = extractNotifications(3);
    const mood = buildMoneyMood(net, alerts);
    const hour = new Date().getHours();
    const daypart = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";

    const expenseLink = document.querySelector('a[href*="add"][href*="expense"], .quick-add-expense')?.getAttribute("href") || "/add?type=expense";
    const logsLink = document.querySelector('a[href*="transactions"]')?.getAttribute("href") || "/transactions";

    const cockpit = document.createElement("section");
    cockpit.className = "phone-today-cockpit";
    cockpit.innerHTML = `
      <article class="phone-today-hero">
        <div class="phone-greeting-row">
          <span><strong>Good ${daypart} 👋</strong><small>Today money cockpit</small></span>
          <span class="phone-mood-pill">${mood.icon} ${mood.label}</span>
        </div>
        <div class="phone-net-block">
          <span class="phone-net-label">Main net</span>
          <strong>${escapeHtml(net)}</strong>
        </div>
        <div class="phone-mood-row">
          <span class="phone-mood-icon" aria-hidden="true">${mood.icon}</span>
          <span class="phone-mood-copy"><strong>${escapeHtml(mood.title)}</strong><small>${escapeHtml(mood.detail)}</small></span>
        </div>
        <div class="phone-action-row">
          <a href="${expenseLink}">＋ Add expense</a>
          <a href="${logsLink}">Open logs</a>
        </div>
      </article>
      ${miniStats.length ? `<div class="phone-mini-stats">${miniStats.map((item) => `<article class="phone-mini-stat"><small>${escapeHtml(item.label)}</small><strong>${escapeHtml(item.value)}</strong></article>`).join("")}</div>` : ""}
      <article class="phone-section-card">
        <div class="phone-section-head"><span><strong>This week pulse</strong><small>Based on the visible recent rows</small></span></div>
        <div class="phone-week-bars">${buildWeekBars(recent)}</div>
      </article>
      <article class="phone-section-card">
        <div class="phone-section-head"><span><strong>Smart checks</strong><small>Things to remember</small></span></div>
        <div class="phone-upcoming-list">
          ${(alerts.length ? alerts : [{ title: "Nothing urgent", detail: "No due payment or old debt warning is visible right now.", href: "#", icon: "✅" }]).map((item) => `
            <a class="phone-upcoming-item" href="${item.href || "#"}">
              <span class="phone-upcoming-icon" aria-hidden="true">${item.icon}</span>
              <span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.detail)}</small></span>
              <span aria-hidden="true">›</span>
            </a>`).join("")}
        </div>
      </article>
    `;
    stage.insertBefore(cockpit, stage.firstElementChild);
  }

  function addFeedHeader() {
    if (!isPhone()) return;
    const list = document.querySelector(".phone-transaction-list");
    if (!list || list.dataset.funFeedReady === "true") return;
    list.dataset.funFeedReady = "true";

    const header = document.createElement("div");
    header.className = "phone-money-feed-head";
    header.innerHTML = `<strong>Money feed</strong><small>Tap once to peek, tap again to open</small>`;

    const chips = document.createElement("div");
    chips.className = "phone-filter-chips";
    chips.innerHTML = `
      <button class="phone-filter-chip is-active" data-phone-feed-filter="all" type="button">All</button>
      <button class="phone-filter-chip" data-phone-feed-filter="expense" type="button">Expenses</button>
      <button class="phone-filter-chip" data-phone-feed-filter="income" type="button">Income</button>
      <button class="phone-filter-chip" data-phone-feed-filter="investment" type="button">Investing</button>
    `;

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
        const icon = document.createElement("span");
        icon.className = "phone-card-emoji";
        icon.textContent = category.emoji;
        card.insertBefore(icon, card.firstElementChild);
      }
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
        const now = Date.now();
        if (!card.classList.contains("is-expanded")) {
          event.preventDefault();
          document.querySelectorAll(".phone-transaction-card.is-expanded").forEach((open) => {
            if (open !== card) open.classList.remove("is-expanded");
          });
          card.classList.add("is-expanded");
          lastExpandedTap = now;
          return;
        }
        if (now - lastExpandedTap < 260) {
          event.preventDefault();
        }
      });
    });
  }

  function wireSwipeGestures() {
    if (!isPhone()) return;
    document.querySelectorAll(".phone-transaction-card, .notification-card").forEach((card) => {
      if (card.dataset.phoneSwipeReady === "true") return;
      card.dataset.phoneSwipeReady = "true";
      let startX = 0;
      let startY = 0;
      let currentX = 0;
      let tracking = false;

      card.addEventListener("touchstart", (event) => {
        const touch = event.touches[0];
        if (!touch) return;
        tracking = true;
        startX = touch.clientX;
        startY = touch.clientY;
        currentX = startX;
      }, { passive: true });

      card.addEventListener("touchmove", (event) => {
        if (!tracking) return;
        const touch = event.touches[0];
        if (!touch) return;
        currentX = touch.clientX;
        const dx = Math.max(-86, Math.min(0, currentX - startX));
        const dy = Math.abs(touch.clientY - startY);
        if (Math.abs(dx) > 12 && dy < 48) {
          card.style.setProperty("--swipe-x", `${dx}px`);
        }
      }, { passive: true });

      card.addEventListener("touchend", () => {
        if (!tracking) return;
        tracking = false;
        const dx = currentX - startX;
        const swiped = dx < -48;
        card.classList.toggle("is-swiped", swiped);
        card.style.setProperty("--swipe-x", swiped ? "-5.2rem" : "0px");
        window.setTimeout(() => {
          card.classList.remove("is-swiped");
          card.style.setProperty("--swipe-x", "0px");
        }, swiped ? 2200 : 0);
      }, { passive: true });
    });
  }

  function addModeCards(form) {
    const tabs = document.querySelector(".transaction-kind-tabs");
    if (!tabs || form.querySelector(".phone-mode-card-row")) return;
    const row = document.createElement("div");
    row.className = "phone-mode-card-row";
    row.innerHTML = Array.from(tabs.querySelectorAll("a")).map((link) => {
      const text = safeText(link);
      const icon = /income/i.test(text) ? "💰" : /invest/i.test(text) ? "📈" : "💸";
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
    Array.from(select.options).filter((option) => option.value).slice(0, 8).forEach((option) => {
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
        next.textContent = active >= steps.length - 1 ? "Review / Save" : "Next";
        const dots = form.querySelectorAll(".phone-add-progress-dots span");
        dots.forEach((dot, index) => dot.classList.toggle("is-active", index <= active));
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
    if (!isPhone()) return;
    if (!window.Plotly) return;
    window.setTimeout(() => {
      document.querySelectorAll(".js-plotly-plot, .plotly-graph-div").forEach((plot) => {
        try { window.Plotly.Plots.resize(plot); } catch (error) {}
      });
    }, 320);
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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => window.setTimeout(boot, 120));
  } else {
    window.setTimeout(boot, 120);
  }

  window.addEventListener("pageshow", () => window.setTimeout(boot, 120));
  window.addEventListener("orientationchange", () => window.setTimeout(() => { boot(); resizePlotlyCharts(); }, 360), { passive: true });
  window.addEventListener("resize", () => window.setTimeout(() => { addGlobalState(); resizePlotlyCharts(); }, 260), { passive: true });
  if (phoneMedia.addEventListener) phoneMedia.addEventListener("change", boot);
})();
