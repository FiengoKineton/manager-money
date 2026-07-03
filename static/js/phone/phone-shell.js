/* --------------------------------------------------------------------------
   Phone shell - native mobile navigation for Money Manager.
   It keeps the desktop DOM untouched and adds a separate phone-only shell:
   top bar, bottom dock, and bottom sheets for menu/add/search/alerts/net.
-------------------------------------------------------------------------- */
(function () {
  const SHELL_ID = "phone-native-shell";
  const TOPBAR_ID = "phone-native-topbar";
  const DOCK_ID = "phone-native-dock";
  const SHEET_ROOT_ID = "phone-native-sheets";
  let resizeTimer = null;

  function isForcedPhone() {
    try {
      const params = new URLSearchParams(window.location.search || "");
      if (params.get("ui") === "phone" || params.get("phone") === "1" || params.get("mobile") === "1") {
        window.localStorage.setItem("moneyManagerPhoneMode", "1");
        return true;
      }
      if (params.get("ui") === "desktop" || params.get("phone") === "0" || params.get("mobile") === "0") {
        window.localStorage.setItem("moneyManagerPhoneMode", "0");
        return false;
      }
      return window.localStorage.getItem("moneyManagerPhoneMode") === "1";
    } catch (error) {
      return false;
    }
  }

  function isPhone() {
    try {
      const ua = String(navigator.userAgent || "");
      const isPhoneUA = /iPhone|iPod|Android.*Mobile|Windows Phone|Mobile Safari/i.test(ua);
      const isAndroidPhone = /Android/i.test(ua) && /Mobile/i.test(ua);
      const hasTouch = (navigator.maxTouchPoints || 0) > 0 || "ontouchstart" in window;
      const root = document.documentElement;
      const vw = Math.min(
        window.innerWidth || 9999,
        root ? root.clientWidth || 9999 : 9999,
        screen && screen.width ? screen.width : 9999
      );
      const vh = Math.min(
        window.innerHeight || 9999,
        root ? root.clientHeight || 9999 : 9999,
        screen && screen.height ? screen.height : 9999
      );

      if (isForcedPhone()) return true;
      if (!hasTouch && !isPhoneUA && !isAndroidPhone) return false;
      if (vw <= 720 && (isPhoneUA || isAndroidPhone || hasTouch)) return true;
      if (vw <= 940 && vh <= 560 && (isPhoneUA || isAndroidPhone || hasTouch)) return true;
      return false;
    } catch (error) {
      return false;
    }
  }

  function text(node, fallback) {
    const value = String(node ? node.textContent || "" : "").replace(/\s+/g, " ").trim();
    return value || fallback || "";
  }

  function htmlEscape(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function syncClass() {
    const enabled = isPhone();
    document.documentElement.classList.toggle("phone-shell-active", enabled);
    document.documentElement.classList.toggle("phone-native-active", enabled);
    if (document.body) {
      document.body.classList.toggle("phone-shell-active", enabled);
      document.body.classList.toggle("phone-native-active", enabled);
    }
    if (!enabled) closeSheets();
  }

  function currentTitle() {
    return text(document.querySelector(".app-topbar-title h1"), "Money Manager");
  }

  function homeHref() {
    const candidates = [
      '.topbar-nav-btn[aria-label="Home"]',
      '.app-sidebar a[href*="overview"]',
      '.app-sidebar a[href="/"]',
      'a[href*="accounts"]'
    ];
    for (const selector of candidates) {
      const href = document.querySelector(selector)?.getAttribute("href");
      if (href) return href;
    }
    return "/";
  }

  function profileHref() {
    return document.querySelector('.app-brand')?.getAttribute('href') || "/profile";
  }

  function footerActionLinksHtml() {
    const parts = [];
    const profileUrl = profileHref();
    if (profileUrl) {
      parts.push(`<a class="phone-utility-link" href="${htmlEscape(profileUrl)}"><span>⚙</span><b>Profile</b><small>Photo, name, language and theme</small></a>`);
    }

    const billScanner = Array.from(document.querySelectorAll('.profile-footer-card')).find((link) => /bill|scanner|receipt|scontr/i.test(text(link)));
    const billUrl = billScanner?.getAttribute('href');
    if (billUrl) {
      parts.push(`<a class="phone-utility-link" href="${htmlEscape(billUrl)}"><span>▤</span><b>Bill scanner</b><small>Import PDF receipts as expenses</small></a>`);
    }

    const settingsLinks = Array.from(document.querySelectorAll('.settings-drawer-links a'))
      .filter((link) => link.getAttribute('href'))
      .map((link) => `<a class="phone-settings-link ${link.classList.contains('active') ? 'active' : ''}" href="${htmlEscape(link.getAttribute('href'))}">${htmlEscape(text(link, 'Settings'))}</a>`)
      .join('');
    if (settingsLinks) {
      parts.push(`<details class="phone-settings-group"><summary><span>⋯</span><b>Settings</b></summary><div>${settingsLinks}</div></details>`);
    }

    return parts.length ? `<section class="phone-utility-actions"><h4>Profile & settings</h4>${parts.join('')}</section>` : '';
  }

  function addHref(type) {
    const selector = type ? `.quick-add-${type}` : '.quick-add-expense';
    return document.querySelector(selector)?.getAttribute('href') || `/transactions/add?type=${type || 'expense'}`;
  }

  function netText() {
    const pill = document.querySelector(".topbar-net-pill, .net-pill");
    const value = text(pill?.querySelector("strong"), "€ 0.00");
    const label = text(pill?.querySelector("span"), "Net");
    return { value, label, href: pill?.getAttribute("href") || "/accounts" };
  }

  function unreadCount() {
    return text(document.querySelector("[data-notification-count]"), "0");
  }

  function openSheet(name) {
    if (!isPhone()) return;
    ensureShell();
    closeSheets(name);
    const sheet = document.querySelector(`[data-phone-sheet="${name}"]`);
    if (!sheet) return;
    sheet.hidden = false;
    requestAnimationFrame(() => {
      sheet.classList.add("is-open");
      document.documentElement.classList.add("phone-sheet-open");
      if (document.body) document.body.classList.add("phone-sheet-open");
      document.querySelectorAll("[data-phone-open]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.getAttribute("data-phone-open") === name);
        btn.setAttribute("aria-expanded", btn.getAttribute("data-phone-open") === name ? "true" : "false");
      });
    });
  }

  function closeSheets(exceptName) {
    document.querySelectorAll("[data-phone-sheet]").forEach((sheet) => {
      if (exceptName && sheet.getAttribute("data-phone-sheet") === exceptName) return;
      sheet.classList.remove("is-open");
      sheet.hidden = true;
    });
    if (!exceptName) {
      document.documentElement.classList.remove("phone-sheet-open");
      if (document.body) document.body.classList.remove("phone-sheet-open");
      document.querySelectorAll("[data-phone-open]").forEach((btn) => {
        btn.classList.remove("is-active");
        btn.setAttribute("aria-expanded", "false");
      });
    }
  }

  function navCloneHtml() {
    const nav = document.querySelector(".app-sidebar-nav");
    let html = `<a href="${htmlEscape(homeHref())}">Home</a>`;
    if (nav) {
      const clone = nav.cloneNode(true);
      clone.querySelectorAll("details").forEach((details) => {
        if (details.classList.contains("is-active")) details.setAttribute("open", "");
        else details.removeAttribute("open");
      });
      clone.querySelectorAll("script, style").forEach((node) => node.remove());
      html = clone.innerHTML;
    }
    return html + footerActionLinksHtml();
  }

  function addPanelHtml() {
    const quick = document.querySelector(".quick-add-panel");
    if (quick) return quick.innerHTML;
    return `
      <a class="quick-add-expense" href="${htmlEscape(addHref('expense'))}"><span>−</span><b>Expense</b><small>Add money out</small></a>
      <a class="quick-add-income" href="${htmlEscape(addHref('income'))}"><span>＋</span><b>Income</b><small>Add money in</small></a>
      <a class="quick-add-investment" href="${htmlEscape(addHref('investment'))}"><span>↗</span><b>Investment</b><small>Add investment move</small></a>
      <a class="quick-add-special" href="${htmlEscape(addHref('special'))}"><span>◆</span><b>Special</b><small>Special expense</small></a>`;
  }

  function searchPanelHtml() {
    const form = document.querySelector(".topbar-global-search");
    if (form) {
      const clone = form.cloneNode(true);
      clone.classList.add("phone-search-form");
      return clone.outerHTML;
    }
    return `<form class="phone-search-form" method="get" action="/search"><input type="search" name="q" placeholder="Search transactions, categories, accounts"><button type="submit">Search</button></form>`;
  }

  function alertsPanelHtml() {
    const panel = document.querySelector(".notification-panel");
    if (!panel) return `<p class="phone-sheet-empty">No alert panel is available on this page.</p>`;
    const clone = panel.cloneNode(true);
    clone.removeAttribute("id");
    clone.hidden = false;
    clone.removeAttribute("hidden");
    clone.setAttribute("aria-hidden", "false");
    clone.querySelectorAll("[data-notification-toggle]").forEach((button) => {
      button.removeAttribute("data-notification-toggle");
      button.setAttribute("aria-expanded", "true");
    });
    clone.querySelectorAll("[data-notification-detail]").forEach((detail) => {
      detail.hidden = false;
      detail.removeAttribute("hidden");
    });
    return clone.innerHTML;
  }

  function buildSheets() {
    const net = netText();
    return `
      <section class="phone-sheet" data-phone-sheet="menu" hidden aria-label="Navigation menu">
        <button class="phone-sheet-backdrop" type="button" data-phone-close aria-label="Close menu"></button>
        <div class="phone-sheet-panel phone-menu-panel">
          <header><strong>Menu</strong><button type="button" data-phone-close aria-label="Close">×</button></header>
          <nav class="phone-menu-list">${navCloneHtml()}</nav>
        </div>
      </section>
      <section class="phone-sheet" data-phone-sheet="add" hidden aria-label="Add transaction">
        <button class="phone-sheet-backdrop" type="button" data-phone-close aria-label="Close add menu"></button>
        <div class="phone-sheet-panel phone-add-panel">
          <header><strong>Add</strong><button type="button" data-phone-close aria-label="Close">×</button></header>
          <div class="phone-add-grid">${addPanelHtml()}</div>
        </div>
      </section>
      <section class="phone-sheet" data-phone-sheet="search" hidden aria-label="Search">
        <button class="phone-sheet-backdrop" type="button" data-phone-close aria-label="Close search"></button>
        <div class="phone-sheet-panel phone-search-panel">
          <header><strong>Search</strong><button type="button" data-phone-close aria-label="Close">×</button></header>
          ${searchPanelHtml()}
        </div>
      </section>
      <section class="phone-sheet" data-phone-sheet="alerts" hidden aria-label="Alerts">
        <button class="phone-sheet-backdrop" type="button" data-phone-close aria-label="Close alerts"></button>
        <div class="phone-sheet-panel phone-alerts-panel">
          <header><strong>Alerts</strong><button type="button" data-phone-close aria-label="Close">×</button></header>
          <div class="phone-alerts-list">${alertsPanelHtml()}</div>
        </div>
      </section>
      <section class="phone-sheet" data-phone-sheet="net" hidden aria-label="Net summary">
        <button class="phone-sheet-backdrop" type="button" data-phone-close aria-label="Close net panel"></button>
        <div class="phone-sheet-panel phone-net-panel">
          <header><strong>${htmlEscape(net.label)}</strong><button type="button" data-phone-close aria-label="Close">×</button></header>
          <div class="phone-net-big"><span>Current net</span><strong>${htmlEscape(net.value)}</strong><a href="${htmlEscape(net.href)}">Open accounts</a></div>
        </div>
      </section>`;
  }

  function ensureShell() {
    syncClass();
    if (!isPhone()) return;

    const net = netText();
    let topbar = document.getElementById(TOPBAR_ID);
    if (!topbar) {
      topbar = document.createElement("header");
      topbar.id = TOPBAR_ID;
      topbar.className = "phone-native-topbar";
      document.body.appendChild(topbar);
    }
    topbar.innerHTML = `
      <button type="button" class="phone-icon-btn" data-phone-open="menu" aria-expanded="false" aria-label="Open menu">☰</button>
      <div class="phone-title-block"><small>Personal finance</small><strong>${htmlEscape(currentTitle())}</strong></div>
      <button type="button" class="phone-icon-btn" data-phone-open="search" aria-expanded="false" aria-label="Search">⌕</button>
      <button type="button" class="phone-icon-btn phone-alert-btn" data-phone-open="alerts" aria-expanded="false" aria-label="Alerts">🔔${unreadCount() !== "0" ? `<em>${htmlEscape(unreadCount())}</em>` : ""}</button>`;

    let dock = document.getElementById(DOCK_ID);
    if (!dock) {
      dock = document.createElement("nav");
      dock.id = DOCK_ID;
      dock.className = "phone-bottom-dock";
      dock.setAttribute("aria-label", "Phone navigation");
      document.body.appendChild(dock);
    }
    dock.innerHTML = `
      <a class="phone-dock-item" href="${htmlEscape(homeHref())}"><span>⌂</span><b>Home</b></a>
      <button type="button" class="phone-dock-item" data-phone-open="menu" aria-expanded="false"><span>☰</span><b>Menu</b></button>
      <button type="button" class="phone-dock-item phone-dock-add" data-phone-open="add" aria-expanded="false"><span>＋</span><b>Add</b></button>
      <button type="button" class="phone-dock-item" data-phone-open="net" aria-expanded="false"><span>${htmlEscape(net.value)}</span><b>Net</b></button>
      <a class="phone-dock-item" href="${htmlEscape(profileHref())}"><span>●</span><b>Profile</b></a>`;

    let sheets = document.getElementById(SHEET_ROOT_ID);
    if (!sheets) {
      sheets = document.createElement("div");
      sheets.id = SHEET_ROOT_ID;
      sheets.className = "phone-sheet-root";
      document.body.appendChild(sheets);
    }
    sheets.innerHTML = buildSheets();
  }

  function handleClick(event) {
    const close = event.target.closest("[data-phone-close]");
    if (close) {
      event.preventDefault();
      closeSheets();
      return;
    }

    const trigger = event.target.closest("[data-phone-open]");
    if (!trigger || !isPhone()) return;
    event.preventDefault();
    const name = trigger.getAttribute("data-phone-open");
    const sheet = document.querySelector(`[data-phone-sheet="${name}"]`);
    if (sheet && sheet.classList.contains("is-open")) closeSheets();
    else openSheet(name);
  }

  function wireSheetLinks() {
    document.querySelectorAll("[data-phone-sheet] a").forEach((link) => {
      if (link.dataset.phoneLinkWired === "true") return;
      link.dataset.phoneLinkWired = "true";
      link.addEventListener("click", closeSheets);
    });
  }

  function convertGenericTables() {
    if (!isPhone()) return;
    document.querySelectorAll("table:not([data-no-mobile-cards])").forEach((table) => {
      if (table.dataset.phoneCardsReady === "true") return;
      const headers = Array.from(table.querySelectorAll("thead th")).map((th) => text(th));
      if (!headers.length) return;
      const rows = Array.from(table.querySelectorAll("tbody tr")).filter((tr) => tr.children.length);
      if (!rows.length) return;
      table.dataset.phoneCardsReady = "true";
      table.classList.add("phone-hidden-table");
      const list = document.createElement("div");
      list.className = "phone-table-card-list";
      rows.slice(0, 120).forEach((row) => {
        const cells = Array.from(row.children);
        const amountIndex = headers.findIndex((h) => /amount|totale|saldo|value|€|price|payment/i.test(h));
        const titleIndex = headers.findIndex((h) => /description|category|name|title|account|conto/i.test(h));
        const card = document.createElement(row.dataset.href ? "a" : "article");
        card.className = "phone-table-card";
        if (row.dataset.href) card.setAttribute("href", row.dataset.href);
        const title = text(cells[titleIndex >= 0 ? titleIndex : 0], "Item");
        const amount = amountIndex >= 0 ? text(cells[amountIndex], "") : "";
        const detail = cells.map((cell, index) => ({ label: headers[index] || "Info", value: text(cell) }))
          .filter((item) => item.value && item.value !== title && item.value !== amount)
          .slice(0, 4)
          .map((item) => `<span><small>${htmlEscape(item.label)}</small><b>${htmlEscape(item.value)}</b></span>`)
          .join("");
        card.innerHTML = `<div class="phone-table-card-head"><strong>${htmlEscape(title)}</strong>${amount ? `<em>${htmlEscape(amount)}</em>` : ""}</div><div class="phone-table-card-detail">${detail}</div>`;
        list.appendChild(card);
      });
      table.insertAdjacentElement("afterend", list);
    });
  }

  function boot() {
    ensureShell();
    wireSheetLinks();
    convertGenericTables();
  }

  document.addEventListener("click", handleClick);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSheets();
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(boot, 180);
  }, { passive: true });

  window.addEventListener("orientationchange", () => window.setTimeout(boot, 220), { passive: true });
  document.addEventListener("DOMContentLoaded", boot);
  window.addEventListener("pageshow", boot);
  // Do not rely on matchMedia(pointer/hover). Several Android browsers report those
  // inconsistently, which made the real phone keep the desktop sidebar.
})();
