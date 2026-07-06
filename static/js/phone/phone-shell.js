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
  let phoneCreateFormId = 0;

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
      <nav class="phone-history-nav" aria-label="Page navigation">
        <a class="phone-mini-nav-btn" href="${htmlEscape(homeHref())}" title="Home" aria-label="Home">⌂</a>
        <button type="button" class="phone-mini-nav-btn" data-browser-back title="Back" aria-label="Back">‹</button>
        <button type="button" class="phone-mini-nav-btn" data-browser-forward title="Forward" aria-label="Forward">›</button>
      </nav>
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

  const compactInteractiveSelector = "a, button, input, select, textarea, label, summary, [role='button'], .icon-action-btn, .desktop-drawer-primary-action, .phone-form-open-card";

  function wirePhoneCompactCards() {
    if (!isPhone()) return;
    const selectors = [
      ".recurring-rule-card",
      ".finished-rule-card",
      ".payment-card",
      ".special-item-card",
      ".account-card",
      ".account-directory-card",
      ".professional-table-card",
      ".phone-table-card",
      ".summary-card",
      ".analysis-card",
      ".mortgage-card",
      ".managed-recurring-card",
      ".bill-card",
      ".work-income-card",
      ".debt-card",
      ".payable-card",
      ".receivable-card",
      ".project-card"
    ];
    document.querySelectorAll(selectors.join(",")).forEach((card) => {
      if (card.dataset.phoneCompactCardWired === "true") return;
      card.dataset.phoneCompactCardWired = "true";
      card.classList.add("phone-card-collapsible");
      const compactByDefault = card.matches(".recurring-rule-card, .finished-rule-card, .payment-card, .special-item-card, .professional-table-card, .phone-table-card, .analysis-card, .mortgage-card, .managed-recurring-card, .bill-card, .work-income-card, .debt-card, .payable-card, .receivable-card, .project-card");
      if (!compactByDefault) {
        card.classList.add("phone-card-expanded");
      }
      card.addEventListener("click", (event) => {
        if (!isPhone()) return;
        if (event.target.closest(compactInteractiveSelector)) return;
        event.preventDefault();
        card.classList.toggle("phone-card-expanded");
      });
    });
  }



  function labelForCreatePanel(panel, form) {
    const heading = panel.querySelector(".panel-header h2, .panel-header h3, h2, h3") || form.querySelector("legend");
    const raw = text(heading, "Add item");
    if (/^new\b/i.test(raw)) return raw;
    if (/^add\b/i.test(raw)) return raw;
    return `Open ${raw}`;
  }

  function createPanelHint(form) {
    if (form.matches(".debt-form")) return "Tap to fill the compact mobile form.";
    if (form.matches(".special-form-grid")) return "Tap to create or update the rule details.";
    if (form.matches(".entry-form")) return "Tap to fill the full entry details.";
    if (form.matches(".expense-project-form")) return "Tap to add the project details.";
    if (form.matches(".forecast-form-grid")) return "Tap to edit the forecast inputs.";
    return "Tap to open the full form.";
  }

  function shouldModalizeCreateForm(form) {
    if (!form || form.dataset.phoneModalReady === "true") return false;
    if (form.closest(".phone-sheet, .phone-native-topbar, .phone-bottom-dock")) return false;
    if (form.closest(".add-mode-stack, .receipt-entry-page, .transaction-detail-page")) return false;
    if (form.matches(".logout-form, .filters-form, .filter-form, .row-action-form, .mini-pay-form, .inline-form, .special-item-form, .archived-special-row, .creditor-payoff-form, .expense-project-inline-actions, .hidden-support-form")) return false;
    if (form.id && /update-/i.test(form.id)) return false;
    const panel = form.closest("section");
    if (!panel) return false;
    if (panel.closest(".transactions, .phone-sheet")) return false;
    if (panel.querySelector("table")) return false;
    return form.matches(
      ".debt-form, .special-form-grid:not(.compact-special-form), .expense-project-form, .forecast-form-grid, .entry-form.designer-form.support-form, .entry-form:not(.filters-form)"
    );
  }

  let activePhoneCreateModal = null;

  function ensurePhoneFormPortal() {
    let portal = document.getElementById("phone-form-modal-portal");
    if (portal) return portal;
    portal = document.createElement("section");
    portal.id = "phone-form-modal-portal";
    portal.className = "phone-form-portal";
    portal.hidden = true;
    portal.innerHTML = `
      <button type="button" class="phone-form-portal-backdrop" data-phone-form-portal-close aria-label="Close form"></button>
      <div class="phone-form-portal-panel" role="dialog" aria-modal="true">
        <header class="phone-form-portal-header">
          <strong data-phone-form-portal-title>Add item</strong>
          <button type="button" data-phone-form-portal-close aria-label="Close form">×</button>
        </header>
        <div class="phone-form-portal-body"></div>
      </div>`;
    document.body.appendChild(portal);
    return portal;
  }

  function closePhoneCreateModal(panel) {
    const active = activePhoneCreateModal;
    if (active && (!panel || panel === active.panel)) {
      active.panel.classList.remove("phone-form-modal-open");
      if (active.opener) active.opener.setAttribute("aria-expanded", "false");
      if (active.placeholder && active.placeholder.parentNode) {
        active.placeholder.parentNode.insertBefore(active.form, active.placeholder);
        active.placeholder.remove();
      }
      const portal = document.getElementById("phone-form-modal-portal");
      if (portal) {
        portal.classList.remove("is-open");
        portal.hidden = true;
        const body = portal.querySelector(".phone-form-portal-body");
        if (body) body.innerHTML = "";
      }
      activePhoneCreateModal = null;
    } else if (panel) {
      panel.classList.remove("phone-form-modal-open");
      const opener = panel.querySelector(".phone-form-open-card");
      if (opener) opener.setAttribute("aria-expanded", "false");
    }

    if (!activePhoneCreateModal) {
      document.documentElement.classList.remove("phone-form-modal-active");
      if (document.body) document.body.classList.remove("phone-form-modal-active");
    }
  }

  function openPhoneCreateModal(panel) {
    if (!isPhone() || !panel) return;
    const form = panel.querySelector("form.phone-form-modal-form");
    if (!form) return;
    if (activePhoneCreateModal) closePhoneCreateModal(activePhoneCreateModal.panel);
    document.querySelectorAll(".phone-form-modal-open").forEach((other) => {
      if (other !== panel) closePhoneCreateModal(other);
    });

    const portal = ensurePhoneFormPortal();
    const body = portal.querySelector(".phone-form-portal-body");
    const title = portal.querySelector("[data-phone-form-portal-title]");
    const opener = panel.querySelector(".phone-form-open-card");
    const placeholder = document.createElement("span");
    placeholder.hidden = true;
    placeholder.dataset.phoneFormPlaceholder = "true";

    form.parentNode.insertBefore(placeholder, form);
    body.appendChild(form);
    panel.classList.add("phone-form-modal-open");
    if (title) title.textContent = labelForCreatePanel(panel, form);
    if (opener) opener.setAttribute("aria-expanded", "true");

    activePhoneCreateModal = { panel, form, placeholder, opener };
    portal.hidden = false;
    requestAnimationFrame(() => portal.classList.add("is-open"));
    document.documentElement.classList.add("phone-form-modal-active");
    if (document.body) document.body.classList.add("phone-form-modal-active");

    const first = form.querySelector("input:not([type='hidden']), select, textarea");
    window.setTimeout(() => {
      try { first?.focus({ preventScroll: true }); } catch (error) { /* ignored */ }
    }, 180);
  }

  function wirePhoneFormModals() {
    if (!isPhone()) return;
    document.querySelectorAll("form").forEach((form) => {
      if (!shouldModalizeCreateForm(form)) return;
      const panel = form.closest("section");
      if (!panel) return;
      phoneCreateFormId += 1;
      const modalId = `phone-create-form-${phoneCreateFormId}`;
      form.dataset.phoneModalReady = "true";
      form.id = form.id || modalId;
      form.classList.add("phone-form-modal-form");
      panel.classList.add("phone-form-modal-card");
      if (!panel.querySelector(".phone-form-close")) {
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "phone-form-close";
        closeButton.setAttribute("aria-label", "Close form");
        closeButton.textContent = "×";
        form.insertAdjacentElement("afterbegin", closeButton);
      }
      if (!panel.querySelector(".phone-form-open-card")) {
        const opener = document.createElement("button");
        opener.type = "button";
        opener.className = "phone-form-open-card";
        opener.setAttribute("aria-controls", form.id);
        opener.setAttribute("aria-expanded", "false");
        opener.innerHTML = `<span>＋</span><strong>${htmlEscape(labelForCreatePanel(panel, form))}</strong><small>${htmlEscape(createPanelHint(form))}</small>`;
        const header = panel.querySelector(".panel-header") || panel.querySelector("h2, h3")?.parentElement;
        if (header) header.insertAdjacentElement("afterend", opener);
        else panel.insertAdjacentElement("afterbegin", opener);
      }
    });
  }

  function handlePhoneFormModalClick(event) {
    if (!isPhone()) return;
    const opener = event.target.closest(".phone-form-open-card");
    if (opener) {
      const panel = opener.closest(".phone-form-modal-card");
      if (!panel) return;
      event.preventDefault();
      openPhoneCreateModal(panel);
      return;
    }
    const close = event.target.closest(".phone-form-close, [data-phone-form-portal-close]");
    if (close) {
      event.preventDefault();
      closePhoneCreateModal(activePhoneCreateModal ? activePhoneCreateModal.panel : close.closest(".phone-form-modal-card"));
    }
  }

  function controlText(control) {
    if (!control || control.disabled) return "";
    const tag = String(control.tagName || "").toLowerCase();
    const type = String(control.getAttribute("type") || "").toLowerCase();
    if (type === "hidden" || type === "password" || type === "submit" || type === "button") return "";
    if ((type === "checkbox" || type === "radio") && !control.checked) return "";
    if (tag === "select") {
      return Array.from(control.selectedOptions || [])
        .map((option) => text(option))
        .filter(Boolean)
        .join(", ");
    }
    if (tag === "textarea" || tag === "input") return String(control.value || "").trim();
    return text(control);
  }

  function cellText(cell, fallback) {
    if (!cell) return fallback || "";
    const controls = Array.from(cell.querySelectorAll("input, select, textarea"))
      .map(controlText)
      .filter(Boolean);
    if (controls.length) {
      return Array.from(new Set(controls)).slice(0, 4).join(" · ");
    }
    const clone = cell.cloneNode(true);
    clone.querySelectorAll("script, style, form, button, .table-action-rail, .row-action-form, .mini-pay-form").forEach((node) => node.remove());
    return text(clone, fallback);
  }

  function preferredHeaderIndex(headers, preferred, fallbackRegex) {
    const tokens = String(preferred || "")
      .split(",")
      .map((token) => token.trim().toLowerCase())
      .filter(Boolean);
    for (const token of tokens) {
      const exact = headers.findIndex((header) => header.toLowerCase() === token);
      if (exact >= 0) return exact;
      const partial = headers.findIndex((header) => header.toLowerCase().includes(token));
      if (partial >= 0) return partial;
    }
    return headers.findIndex((header) => fallbackRegex.test(header));
  }

  function bestTitleFromCells(table, headers, cells) {
    const preferredTitle = table.dataset.mobileTitle || "Payee,Person,Debtor,Creditor,Name,Description,Title,Account,Conto";
    const titleIndexes = String(preferredTitle)
      .split(",")
      .map((token) => token.trim())
      .filter(Boolean)
      .map((token) => preferredHeaderIndex(headers, token, /$a/))
      .filter((index) => index >= 0);
    const fallbackIndexes = [headers.findIndex((h) => /name|title|description|payee|person|debtor|creditor|account|conto/i.test(h)), 0].filter((index) => index >= 0);
    const candidates = [...titleIndexes, ...fallbackIndexes];
    for (const index of candidates) {
      const value = cellText(cells[index], "");
      if (value && !/^item(?:\s*\d+)?$/i.test(value)) return value;
    }
    return cellText(cells[candidates[0] || 0], "Item");
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
        const amountIndex = preferredHeaderIndex(headers, table.dataset.mobileAmount || "Remaining,Amount,Total,Saldo,Value,Price,Payment,Paid,Collected", /remaining|amount|total|totale|saldo|value|€|price|payment|paid|collected/i);
        const card = document.createElement("article");
        card.className = "phone-table-card";
        const title = bestTitleFromCells(table, headers, cells);
        const amount = amountIndex >= 0 ? cellText(cells[amountIndex], "") : "";
        const preferredMeta = String(table.dataset.mobileMeta || "")
          .split(",")
          .map((token) => token.trim())
          .filter(Boolean)
          .map((token) => preferredHeaderIndex(headers, token, /$a/))
          .filter((index) => index >= 0);
        const fallbackMeta = cells.map((_, index) => index);
        const detailIndexes = Array.from(new Set([...preferredMeta, ...fallbackMeta]));
        const detail = detailIndexes.map((index) => ({ label: headers[index] || "Info", value: cellText(cells[index], "") }))
          .filter((item) => item.value && item.value !== title && item.value !== amount)
          .slice(0, 6)
          .map((item) => `<span><small>${htmlEscape(item.label)}</small><b>${htmlEscape(item.value)}</b></span>`)
          .join("");
        const openLink = row.dataset.href ? `<a class="phone-table-card-open" href="${htmlEscape(row.dataset.href)}">Open</a>` : "";
        card.innerHTML = `<div class="phone-table-card-head"><strong>${htmlEscape(title)}</strong>${amount ? `<em>${htmlEscape(amount)}</em>` : ""}</div><div class="phone-table-card-detail">${detail}${openLink}</div>`;
        list.appendChild(card);
      });
      table.insertAdjacentElement("afterend", list);
    });
  }


  function setupPhoneScopeSwitcher() {
    if (!isPhone()) return;
    document.querySelectorAll("[data-scope-accordion]").forEach((nav) => {
      const groups = Array.from(nav.querySelectorAll("details[data-scope-group]"));
      if (!groups.length || nav.dataset.phoneScopeReady === "true") return;
      nav.dataset.phoneScopeReady = "true";
      groups.forEach((group) => {
        group.addEventListener("toggle", () => {
          if (!isPhone()) return;
          if (group.open) {
            groups.forEach((other) => {
              if (other !== group) other.removeAttribute("open");
            });
            document.documentElement.classList.add("phone-scope-menu-open");
          } else if (!groups.some((item) => item.open)) {
            document.documentElement.classList.remove("phone-scope-menu-open");
          }
        });
      });
    });
  }

  function closePhoneScopeSwitcher(event) {
    if (!isPhone()) return;
    if (event && event.target && event.target.closest && event.target.closest(".grouped-scope-switcher")) return;
    document.querySelectorAll("details[data-scope-group][open]").forEach((group) => group.removeAttribute("open"));
    document.documentElement.classList.remove("phone-scope-menu-open");
  }

  function boot() {
    ensureShell();
    setupPhoneScopeSwitcher();
    wireSheetLinks();
    convertGenericTables();
    wirePhoneCompactCards();
    wirePhoneFormModals();
  }

  document.addEventListener("click", closePhoneScopeSwitcher);
  document.addEventListener("click", handleClick);
  document.addEventListener("click", handlePhoneFormModalClick);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSheets();
      closePhoneScopeSwitcher();
      document.querySelectorAll(".phone-form-modal-open").forEach(closePhoneCreateModal);
    }
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
