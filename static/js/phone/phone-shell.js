/* --------------------------------------------------------------------------
   Money Manager phone shell
   Desktop is untouched. On real phone screens this script builds a separate
   top header, bottom dock and bottom sheets from the existing desktop DOM.
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 760px) and (hover: none) and (pointer: coarse), (max-height: 560px) and (max-width: 980px) and (hover: none) and (pointer: coarse)");
  const SHELL_ID = "phone-native-shell";
  const SHEET_SELECTOR = ".phone-native-sheet[data-phone-sheet]";
  let observer = null;

  function isPhone() {
    return phoneMedia.matches;
  }

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $all(selector, root) {
    return Array.from((root || document).querySelectorAll(selector));
  }

  function text(node, fallback) {
    const value = String(node ? node.textContent || "" : "").replace(/\s+/g, " ").trim();
    return value || fallback || "";
  }

  function attr(node, name, fallback) {
    return node && node.getAttribute(name) ? node.getAttribute(name) : fallback;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function currentTitle() {
    return text($(".app-topbar-title h1"), document.title || "Money Manager");
  }

  function personalFinanceLabel() {
    return text($(".app-topbar-title .eyebrow"), "Personal finance");
  }

  function homeHref() {
    return attr($(".topbar-nav-btn[title='Home'], .topbar-nav-btn[aria-label='Home']"), "href", "/");
  }

  function profileHref() {
    return attr($(".app-brand, .profile-footer-card"), "href", homeHref());
  }

  function profileInitials() {
    return text($(".brand-mark, .brand-mark-fallback"), "👤");
  }

  function netLabel() {
    return text($(".topbar-net-pill span[data-topbar-net-label], .topbar-net-pill span"), "Net");
  }

  function netValue() {
    return text($(".topbar-net-pill strong[data-topbar-net-value], .topbar-net-pill strong"), "€ 0.00");
  }

  function netHref() {
    return attr($(".topbar-net-pill"), "href", "/accounts");
  }

  function unreadCount() {
    const value = text($(".notification-count"), "");
    return value && value !== "0" ? value : "";
  }

  function isActiveHref(href) {
    if (!href || href === "#") return false;
    try {
      const url = new URL(href, window.location.origin);
      const here = window.location.pathname.replace(/\/$/, "") || "/";
      const there = url.pathname.replace(/\/$/, "") || "/";
      return here === there;
    } catch (error) {
      return false;
    }
  }

  function button(label, icon, sheet) {
    return `<button type="button" class="phone-native-icon" data-phone-open="${escapeHtml(sheet)}" aria-label="${escapeHtml(label)}">${icon}</button>`;
  }

  function sheet(name, title, subtitle, bodyClass, bodyHtml) {
    return `<section class="phone-native-sheet" data-phone-sheet="${escapeHtml(name)}" hidden aria-hidden="true">
      <button type="button" class="phone-native-backdrop" data-phone-close aria-label="Close"></button>
      <div class="phone-native-panel" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
        <header class="phone-native-sheet-head">
          <span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(subtitle || "")}</small></span>
          <button type="button" data-phone-close aria-label="Close">×</button>
        </header>
        <div class="phone-native-sheet-body ${escapeHtml(bodyClass || "")}">${bodyHtml || ""}</div>
      </div>
    </section>`;
  }

  function cloneNavHtml() {
    const wrap = document.createElement("div");
    const nav = $(".app-sidebar-nav");
    const footer = $(".app-sidebar-footer");

    if (nav) {
      const copy = nav.cloneNode(true);
      copy.querySelectorAll("script").forEach((node) => node.remove());
      wrap.appendChild(copy);
    }

    if (footer) {
      const copy = footer.cloneNode(true);
      copy.querySelectorAll("script").forEach((node) => node.remove());
      wrap.appendChild(copy);
    }

    if (!wrap.children.length) {
      wrap.innerHTML = `<div class="phone-native-add-grid">
        <a class="phone-native-add-card" href="${escapeHtml(homeHref())}"><span>⌂</span><b>Home</b><small>Open dashboard</small></a>
        <a class="phone-native-add-card" href="/accounts"><span>🏦</span><b>Accounts</b><small>Open accounts</small></a>
        <a class="phone-native-add-card" href="/transactions"><span>⇄</span><b>Transactions</b><small>Open transaction log</small></a>
      </div>`;
    }

    return wrap.innerHTML;
  }

  function addHtml() {
    const links = $all(".quick-add-panel a");
    if (links.length) {
      return `<div class="phone-native-add-grid">${links.map((link) => {
        const icon = text($("span", link), "＋");
        const label = text($("b", link), text(link, "Add"));
        const hint = text($("small", link), "Create movement");
        return `<a class="phone-native-add-card" href="${escapeHtml(attr(link, "href", "#"))}"><span>${escapeHtml(icon)}</span><b>${escapeHtml(label)}</b><small>${escapeHtml(hint)}</small></a>`;
      }).join("")}</div>`;
    }
    return `<div class="phone-native-add-grid">
      <a class="phone-native-add-card" href="/transactions/add?type=expense"><span>−</span><b>Expense</b><small>Money going out</small></a>
      <a class="phone-native-add-card" href="/transactions/add?type=income"><span>＋</span><b>Income</b><small>Money coming in</small></a>
      <a class="phone-native-add-card" href="/transactions/add?type=investment"><span>↗</span><b>Investment</b><small>Asset movement</small></a>
    </div>`;
  }

  function searchHtml() {
    const form = $(".topbar-global-search");
    const action = attr(form, "action", "/search");
    const value = attr($("input[name='q']", form), "value", "");
    return `<form class="phone-native-search-form" method="get" action="${escapeHtml(action)}">
      <input type="search" name="q" value="${escapeHtml(value)}" placeholder="Search..." aria-label="Search Money Manager">
      <button type="submit">Search</button>
    </form>`;
  }

  function alertsHtml() {
    const panel = $(".notification-panel");
    if (!panel) return `<div class="notification-empty"><span aria-hidden="true">✓</span><strong>No alerts</strong><small>Nothing urgent right now.</small></div>`;
    const copy = panel.cloneNode(true);
    copy.removeAttribute("hidden");
    copy.setAttribute("aria-hidden", "false");
    copy.querySelectorAll("script").forEach((node) => node.remove());
    copy.querySelectorAll("[data-notification-close]").forEach((node) => node.remove());
    return copy.outerHTML;
  }

  function buildShell() {
    const unread = unreadCount();
    const shell = document.createElement("div");
    shell.id = SHELL_ID;
    shell.className = "phone-native-shell";
    shell.setAttribute("aria-label", "Phone app navigation");
    shell.innerHTML = `
      <header class="phone-native-topbar">
        ${button("Open menu", "☰", "menu")}
        <a class="phone-native-title" href="${escapeHtml(homeHref())}">
          <span>${escapeHtml(personalFinanceLabel())}</span>
          <strong>${escapeHtml(currentTitle())}</strong>
        </a>
        ${button("Search", "⌕", "search")}
        <button type="button" class="phone-native-icon phone-native-alert ${unread ? "has-alerts" : ""}" data-phone-open="alerts" aria-label="Open alerts">🔔${unread ? `<small>${escapeHtml(unread)}</small>` : ""}</button>
      </header>
      <nav class="phone-native-dock" aria-label="Phone bottom navigation">
        <a href="${escapeHtml(homeHref())}" class="${isActiveHref(homeHref()) ? "is-active" : ""}"><span aria-hidden="true">⌂</span><b>Home</b></a>
        <button type="button" data-phone-open="menu"><span aria-hidden="true">☰</span><b>Menu</b></button>
        <button type="button" class="phone-native-add" data-phone-open="add"><span aria-hidden="true">＋</span><b>Add</b></button>
        <a href="${escapeHtml(netHref())}" class="phone-native-net"><small data-phone-net-label>${escapeHtml(netLabel())}</small><strong data-phone-net-value>${escapeHtml(netValue())}</strong></a>
        <a href="${escapeHtml(profileHref())}" class="${isActiveHref(profileHref()) ? "is-active" : ""}"><span aria-hidden="true">${escapeHtml(profileInitials())}</span><b>Profile</b></a>
      </nav>
      ${sheet("menu", "Menu", "Navigate the app", "phone-native-menu", cloneNavHtml())}
      ${sheet("add", "Add", "Create a new movement", "", addHtml())}
      ${sheet("search", "Search", "Find transactions and records", "", searchHtml())}
      ${sheet("alerts", "Alerts", unread ? `${unread} unread` : "No urgent alerts", "phone-native-alerts", alertsHtml())}`;
    return shell;
  }

  function closeAllSheets() {
    $all(SHEET_SELECTOR).forEach((sheet) => {
      sheet.classList.remove("is-open");
      sheet.hidden = true;
      sheet.setAttribute("aria-hidden", "true");
    });
    document.documentElement.classList.remove("phone-sheet-open");
  }

  function openSheet(name) {
    if (!isPhone()) return;
    const target = $(`.phone-native-sheet[data-phone-sheet="${CSS.escape(name)}"]`);
    if (!target) return;
    closeAllSheets();
    target.hidden = false;
    target.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      target.classList.add("is-open");
      document.documentElement.classList.add("phone-sheet-open");
    });
  }

  function wireShell(shell) {
    if (shell.dataset.wired === "true") return;
    shell.dataset.wired = "true";

    shell.addEventListener("click", (event) => {
      const close = event.target.closest("[data-phone-close]");
      if (close) {
        event.preventDefault();
        closeAllSheets();
        return;
      }

      const opener = event.target.closest("[data-phone-open]");
      if (opener) {
        event.preventDefault();
        openSheet(opener.getAttribute("data-phone-open"));
        return;
      }

      const link = event.target.closest("a[href]");
      if (link) closeAllSheets();
    });
  }

  function syncTitleAndNet() {
    const shell = document.getElementById(SHELL_ID);
    if (!shell) return;
    const title = $(".phone-native-title strong", shell);
    if (title) title.textContent = currentTitle();
    const netLabelNode = $("[data-phone-net-label]", shell);
    const netValueNode = $("[data-phone-net-value]", shell);
    if (netLabelNode) netLabelNode.textContent = netLabel();
    if (netValueNode) netValueNode.textContent = netValue();
  }



  function normalized(value) {
    return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function cellText(node) {
    return String(node ? node.textContent || "" : "").replace(/\s+/g, " ").trim();
  }

  function cloneInteractive(cell) {
    const wrap = document.createElement("div");
    const interactive = Array.from(cell.querySelectorAll("a[href], button, form"));
    const used = new Set();
    interactive.forEach((node) => {
      const top = node.closest("form") || node;
      if (used.has(top)) return;
      used.add(top);
      const copy = top.cloneNode(true);
      copy.querySelectorAll("script").forEach((script) => script.remove());
      wrap.appendChild(copy);
    });
    return wrap.innerHTML;
  }

  function headerIndex(headers, preferred, fallback) {
    const wanted = normalized(preferred);
    if (wanted) {
      const exact = headers.findIndex((header) => normalized(header) === wanted);
      if (exact >= 0) return exact;
      const partial = headers.findIndex((header) => normalized(header).includes(wanted) || wanted.includes(normalized(header)));
      if (partial >= 0) return partial;
    }
    return fallback;
  }

  function inferAmountIndex(headers, row) {
    const explicit = headerIndex(headers, row.closest("table")?.dataset.mobileAmount || "", -1);
    if (explicit >= 0) return explicit;
    const amountByHeader = headers.findIndex((header) => /amount|total|saldo|closing|spent|remaining|monthly|€|eur|value|paid|requested/i.test(header));
    if (amountByHeader >= 0) return amountByHeader;
    const cells = Array.from(row.children);
    for (let index = cells.length - 1; index >= 0; index -= 1) {
      if (/[-+]?\s*€?\s*\d+[\d.,]*/.test(cellText(cells[index]))) return index;
    }
    return Math.max(0, cells.length - 1);
  }

  function splitMetaPreference(table) {
    return String(table.dataset.mobileMeta || "")
      .split(",")
      .map((item) => normalized(item))
      .filter(Boolean);
  }

  function buildMobileTableCards(table) {
    if (!isPhone()) return;
    if (!table || table.dataset.noMobileCards === "true") return;
    if (table.classList.contains("phone-cardified-source")) return;
    if (!table.matches("table.standard-table, table.inline-edit-table, table.mobile-card-table")) return;
    const body = table.tBodies && table.tBodies[0];
    if (!body) return;
    const rows = Array.from(body.rows).filter((row) => row.cells && row.cells.length);
    if (!rows.length) return;

    const headers = Array.from(table.querySelectorAll("thead th")).map(cellText);
    const maxCards = 80;
    const titleIndex = headerIndex(headers, table.dataset.mobileTitle || "", 0);
    const list = document.createElement("div");
    list.className = "phone-table-card-list";
    list.dataset.phoneTableCards = "true";

    rows.slice(0, maxCards).forEach((row) => {
      const cells = Array.from(row.cells);
      const amountIndex = inferAmountIndex(headers, row);
      const metaPrefs = splitMetaPreference(table);
      const card = document.createElement(row.dataset.href ? "a" : "article");
      card.className = "phone-table-card";
      if (row.dataset.href) {
        card.href = row.dataset.href;
        card.setAttribute("aria-label", `Open ${cellText(cells[titleIndex]) || "row"}`);
      }

      const title = cellText(cells[titleIndex]) || "Item";
      const amount = amountIndex >= 0 ? cellText(cells[amountIndex]) : "";
      const metaItems = [];
      const actions = [];

      cells.forEach((cell, index) => {
        if (index === titleIndex || index === amountIndex) return;
        const label = headers[index] || cell.dataset.label || "Info";
        const value = cellText(cell);
        const hasInteractive = cell.querySelector("a[href], button, form");
        if (hasInteractive) {
          actions.push(cloneInteractive(cell));
          if (!value || value.length < 2) return;
        }
        const wanted = !metaPrefs.length || metaPrefs.some((pref) => normalized(label).includes(pref) || pref.includes(normalized(label)));
        if (wanted && value) {
          metaItems.push(`<span class="phone-table-meta-item"><b>${escapeHtml(label)}</b><span>${escapeHtml(value)}</span></span>`);
        }
      });

      if (!metaItems.length) {
        cells.forEach((cell, index) => {
          if (index === titleIndex || index === amountIndex) return;
          const value = cellText(cell);
          if (value) metaItems.push(`<span class="phone-table-meta-item"><span>${escapeHtml(value)}</span></span>`);
        });
      }

      card.innerHTML = `<div class="phone-table-card-top"><div class="phone-table-card-title">${escapeHtml(title)}</div>${amount ? `<div class="phone-table-card-amount">${escapeHtml(amount)}</div>` : ""}</div><div class="phone-table-card-meta">${metaItems.slice(0, 6).join("")}</div>${actions.length ? `<div class="phone-table-card-actions">${actions.join("")}</div>` : ""}`;
      list.appendChild(card);
    });

    if (rows.length > maxCards) {
      const note = document.createElement("div");
      note.className = "phone-table-meta-item";
      note.textContent = `${maxCards} of ${rows.length} rows shown on phone. Use filters to narrow this table.`;
      list.appendChild(note);
    }

    table.classList.add("phone-cardified-source");
    table.after(list);
  }

  function enhancePhoneContent() {
    if (!isPhone()) return;
    document.querySelectorAll("table.standard-table, table.inline-edit-table, table.mobile-card-table").forEach(buildMobileTableCards);
  }

  function clearPhoneEnhancements() {
    document.querySelectorAll(".phone-table-card-list[data-phone-table-cards]").forEach((node) => node.remove());
    document.querySelectorAll("table.phone-cardified-source").forEach((table) => table.classList.remove("phone-cardified-source"));
  }


  function setupNetObserver() {
    if (observer) observer.disconnect();
    const target = $(".topbar-net-pill");
    if (!target || !window.MutationObserver) return;
    observer = new MutationObserver(syncTitleAndNet);
    observer.observe(target, { childList: true, subtree: true, characterData: true, attributes: true });
  }

  function enablePhone() {
    document.documentElement.classList.add("phone-shell-active");
    if (document.body) document.body.classList.add("phone-shell-active");
    let shell = document.getElementById(SHELL_ID);
    if (!shell) {
      shell = buildShell();
      document.body.appendChild(shell);
      wireShell(shell);
    }
    syncTitleAndNet();
    setupNetObserver();
    enhancePhoneContent();
  }

  function disablePhone() {
    clearPhoneEnhancements();
    closeAllSheets();
    document.documentElement.classList.remove("phone-shell-active", "phone-sheet-open");
    if (document.body) document.body.classList.remove("phone-shell-active");
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    const shell = document.getElementById(SHELL_ID);
    if (shell) shell.remove();
  }

  function boot() {
    if (isPhone()) enablePhone();
    else disablePhone();
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllSheets();
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.addEventListener("pageshow", boot);
  window.addEventListener("orientationchange", () => window.setTimeout(boot, 180), { passive: true });
  window.addEventListener("resize", () => window.setTimeout(boot, 180), { passive: true });
  if (phoneMedia.addEventListener) phoneMedia.addEventListener("change", boot);
})();
