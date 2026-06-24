(function () {
  const backgroundUrl = document.body.dataset.backgroundUrl;
  if (backgroundUrl) {
    document.documentElement.style.setProperty("--page-bg-image", `url('${backgroundUrl}')`);
  }

  const mobileCardsMedia = window.matchMedia("(max-width: 900px)");
  const desktopDetailMedia = window.matchMedia("(min-width: 1001px)");
  const isMobileCardsViewport = () => mobileCardsMedia.matches;
  const isDesktopDetailViewport = () => desktopDetailMedia.matches;
  const interactiveSelector = "a, button, input, select, textarea, label, form, summary, details, [role='button'], .mobile-row-toggle";
  const actionContainerSelector = ".transaction-row-actions-source, .table-action-rail, .inline-action-rail, .card-action-rail, .debt-actions, .payment-action-rail, .rule-card-actions";
  const actionElementSelector = ".row-action-form, .mini-pay-form, .project-mini-pay, .icon-action-btn, .icon-link-btn, .desktop-actions-cell, .desktop-actions-heading";

  function selectAllFilters() {
    document.querySelectorAll(".type-checkbox").forEach((box) => {
      box.checked = true;
    });

    const select = document.getElementById("category-select");
    if (!select) return;

    Array.from(select.options).forEach((option) => {
      option.selected = true;
    });
  }

  function setMobileRowExpanded(row, expanded) {
    if (!row || !row.classList.contains("mobile-disclosure-row")) return;

    if (expanded) {
      const tbody = row.closest("tbody");
      if (tbody) {
        tbody.querySelectorAll("tr.mobile-disclosure-row.is-expanded").forEach((other) => {
          if (other !== row) setMobileRowExpanded(other, false);
        });
      }
    }

    row.classList.toggle("is-expanded", expanded);
    row.setAttribute("aria-expanded", expanded ? "true" : "false");

    const toggle = row.querySelector(":scope > .mobile-row-summary .mobile-row-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    }
  }

  function toggleMobileRow(row) {
    setMobileRowExpanded(row, !row.classList.contains("is-expanded"));
  }

  function wireClickableRows() {
    document.querySelectorAll(".clickable-row").forEach((row) => {
      if (row.dataset.clickableWired === "true") return;
      row.dataset.clickableWired = "true";

      row.addEventListener("click", (event) => {
        if (event.target.closest(interactiveSelector)) return;

        if (isMobileCardsViewport() && row.classList.contains("mobile-disclosure-row")) {
          event.preventDefault();
          toggleMobileRow(row);
          return;
        }

        if (isDesktopDetailViewport() && canUseDesktopDrawer(row)) {
          event.preventDefault();
          openDesktopRowDrawer(row);
          return;
        }

        const href = row.dataset.href;
        if (href) window.location.href = href;
      });
    });
  }

  window.toggleChartSize = function toggleChartSize(button) {
    const card = button.closest(".chart-card");
    if (!card) return;

    card.classList.toggle("chart-expanded");
    button.innerText = card.classList.contains("chart-expanded") ? "Close" : "Expand";

    setTimeout(() => {
      card.querySelectorAll(".js-plotly-plot").forEach((plot) => {
        if (window.Plotly) {
          window.Plotly.Plots.resize(plot);
        }
      });
    }, 100);
  };

  function wireMobileNavGroups() {
    const groups = Array.from(document.querySelectorAll(".app-nav-group, .nav-group"));
    const media = window.matchMedia("(max-width: 1000px)");
    const isMobile = () => media.matches;

    function syncInitialStateForViewport() {
      groups.forEach((group) => {
        if (isMobile()) {
          group.removeAttribute("open");
        } else if (group.querySelector(".nav-items a.active")) {
          group.setAttribute("open", "");
        }
      });
    }

    groups.forEach((group) => {
      const summary = group.querySelector("summary");
      if (!summary) return;

      summary.addEventListener("click", () => {
        if (!isMobile()) return;

        window.setTimeout(() => {
          groups.forEach((other) => {
            if (other !== group) {
              other.removeAttribute("open");
            }
          });
        }, 0);
      });

      group.querySelectorAll(".nav-items a").forEach((link) => {
        link.addEventListener("click", () => {
          if (isMobile()) {
            group.removeAttribute("open");
          }
        });
      });
    });

    document.addEventListener("click", (event) => {
      if (!isMobile()) return;
      if (event.target.closest(".nav-group")) return;

      groups.forEach((group) => {
        group.removeAttribute("open");
      });
    });

    syncInitialStateForViewport();
    if (media.addEventListener) {
      media.addEventListener("change", syncInitialStateForViewport);
    }
  }

  function normalizeLabel(label) {
    return String(label || "")
      .toLowerCase()
      .replace(/\(.*?\)/g, "")
      .replace(/[€/$£]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function getFieldValue(field) {
    if (!field) return "";
    if (field.tagName === "SELECT") {
      const selected = field.selectedOptions && field.selectedOptions[0];
      return (selected ? selected.textContent : field.value || "").replace(/\s+/g, " ").trim();
    }
    if (field.type === "checkbox") return field.checked ? "Yes" : "No";
    return String(field.value || field.getAttribute("value") || "").replace(/\s+/g, " ").trim();
  }

  function prettifyFieldName(name) {
    return String(name || "")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (match) => match.toUpperCase())
      .trim();
  }

  function getFieldLabel(field, fallback) {
    if (!field) return fallback || "Detail";
    return (
      field.getAttribute("aria-label") ||
      field.getAttribute("data-label") ||
      prettifyFieldName(field.getAttribute("name")) ||
      fallback ||
      "Detail"
    );
  }

  function removeActionNodes(root) {
    if (!root) return;
    root.querySelectorAll(`${actionContainerSelector}, ${actionElementSelector}`).forEach((node) => node.remove());
  }

  function getReadableCellText(cell) {
    if (!cell) return "";

    const clone = cell.cloneNode(true);
    clone.querySelectorAll("script, style, input[type='hidden'], [hidden]").forEach((node) => node.remove());
    removeActionNodes(clone);

    clone.querySelectorAll("input, select, textarea").forEach((field) => {
      field.replaceWith(document.createTextNode(getFieldValue(field)));
    });

    return clone.textContent.replace(/\s+/g, " ").trim();
  }

  function findCellByLabels(cells, headers, labels) {
    const wanted = labels.map(normalizeLabel);
    for (let i = 0; i < headers.length; i += 1) {
      const header = normalizeLabel(headers[i]);
      if (!header) continue;
      if (wanted.some((label) => header === label || header.includes(label))) {
        const text = getReadableCellText(cells[i]);
        if (text) return { cell: cells[i], text, label: headers[i], index: i };
      }
    }
    return null;
  }

  function findFirstMeaningfulCell(cells, headers, skipIndexes) {
    for (let i = 0; i < cells.length; i += 1) {
      if (skipIndexes.has(i)) continue;
      const header = normalizeLabel(headers[i]);
      if (!header || header.includes("action")) continue;
      const text = getReadableCellText(cells[i]);
      if (text) return { cell: cells[i], text, label: headers[i], index: i };
    }
    return null;
  }

  function tableMobileLabels(row, datasetKey, fallbackLabels) {
    const table = row.closest("table");
    const configured = table && table.dataset ? table.dataset[datasetKey] : "";
    const labels = String(configured || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    return labels.length ? labels : fallbackLabels;
  }

  function buildMobileSummary(row, headers) {
    const cells = Array.from(row.children).filter((cell) => !cell.classList.contains("mobile-row-summary"));
    const skipIndexes = new Set();

    const title =
      findCellByLabels(cells, headers, tableMobileLabels(row, "mobileTitle", ["description", "name", "item", "category", "currency", "person", "payee", "creditor", "parent", "month", "year"])) ||
      findFirstMeaningfulCell(cells, headers, skipIndexes);
    if (title) skipIndexes.add(title.index);

    const amount =
      findCellByLabels(cells, headers, tableMobileLabels(row, "mobileAmount", ["amount", "remaining", "total", "balance", "cash", "investment value", "estimated current value", "paid", "collected", "original", "rate", "effective rate", "net"]));
    if (amount) skipIndexes.add(amount.index);

    const metaPieces = [];
    tableMobileLabels(row, "mobileMeta", ["creditor", "debtor", "person", "payee", "date", "type", "account", "status", "due", "source", "parent", "method"]).forEach((label) => {
      const piece = findCellByLabels(cells, headers, [label]);
      if (piece && piece.text && !metaPieces.some((item) => item.text === piece.text)) {
        metaPieces.push(piece);
        skipIndexes.add(piece.index);
      }
    });

    if (metaPieces.length < 2) {
      const fallback = findFirstMeaningfulCell(cells, headers, skipIndexes);
      if (fallback) metaPieces.push(fallback);
    }

    return {
      title: (title && title.text) || "Details",
      titleLabel: (title && title.label) || "Item",
      amount: (amount && amount.text) || "",
      amountLabel: (amount && amount.label) || "",
      meta: metaPieces.slice(0, 3).map((piece) => piece.text).join(" · "),
    };
  }

  function makeSpan(className, text) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    return span;
  }

  function isMoneyLikeLabel(normalizedHeader) {
    return ["amount", "remaining", "total", "balance", "cash", "value", "paid", "collected", "original", "rate", "monthly", "yearly", "debt", "net"].some((label) =>
      normalizedHeader.includes(label)
    );
  }

  function isActionLikeCell(cell, header) {
    const normalizedHeader = normalizeLabel(header);
    if (normalizedHeader.includes("action") || normalizedHeader.includes("edit") || normalizedHeader.includes("delete")) return true;
    const hasActions = Boolean(cell.querySelector(`${actionContainerSelector}, ${actionElementSelector}`));
    if (!hasActions) return false;
    // Some real data cells contain hidden drawer actions beside the actual data
    // (for example the Transactions description column). Treat the whole cell as
    // an action cell only when no readable row data remains after actions are removed.
    return !getReadableCellText(cell);
  }

  function collectActionNodes(cell, label) {
    if (!cell) return [];
    if (isActionLikeCell(cell, label)) return [cell];
    return Array.from(cell.querySelectorAll(actionContainerSelector)).filter((node) => node.querySelector("a, button, form, input, select, textarea"));
  }

  function detailLinesForDataCell(cell, label) {
    const fields = Array.from(cell.querySelectorAll("input:not([type='hidden']), select, textarea")).filter((field) => !field.closest(`${actionContainerSelector}, ${actionElementSelector}`));
    if (fields.length > 1) {
      const lines = [];
      fields.forEach((field) => {
        const value = getFieldValue(field);
        if (!value) return;
        lines.push({ label: getFieldLabel(field, label), text: value });
      });
      const staticClone = cell.cloneNode(true);
      staticClone.querySelectorAll("input, select, textarea, script, style, [hidden]").forEach((node) => node.remove());
      removeActionNodes(staticClone);
      const staticText = staticClone.textContent.replace(/\s+/g, " ").trim();
      if (staticText) lines.unshift({ label, text: staticText });
      return lines;
    }

    const text = getReadableCellText(cell);
    return text ? [{ label, text }] : [];
  }

  function getRowHeaders(row) {
    const table = row.closest("table");
    if (!table) return [];
    return Array.from(table.querySelectorAll("thead th")).map((header) => header.textContent.trim().replace(/\s+/g, " "));
  }

  function getRowDataCells(row) {
    return Array.from(row.children).filter((cell) => cell.tagName === "TD" && !cell.classList.contains("mobile-row-summary"));
  }

  function labelFromDetailDatasetKey(key) {
    return prettifyFieldName(
      String(key || "")
        .replace(/^detail/, "")
        .replace(/([A-Z])/g, " $1")
        .trim()
    );
  }

  function collectRowExtraDetails(row, existingLines) {
    const seenLabels = new Set((existingLines || []).map((line) => normalizeLabel(line.label)));
    const lines = [];

    Object.entries(row.dataset || {}).forEach(([key, rawValue]) => {
      if (!key.startsWith("detail")) return;
      const value = String(rawValue || "").replace(/\s+/g, " ").trim();
      if (!value) return;

      const label = labelFromDetailDatasetKey(key);
      const normalizedLabel = normalizeLabel(label);
      if (!normalizedLabel || seenLabels.has(normalizedLabel)) return;

      seenLabels.add(normalizedLabel);
      lines.push({ label, text: value });
    });

    return lines;
  }

  function hasMeaningfulRowDetails(row, headers) {
    const cells = getRowDataCells(row);
    if (cells.length < 2) return false;
    return cells.some((cell, index) => {
      if (isActionLikeCell(cell, headers[index] || "")) return false;
      return Boolean(getReadableCellText(cell));
    });
  }

  function canUseDesktopDrawer(row) {
    if (!row || !row.closest("table")) return false;
    return hasMeaningfulRowDetails(row, getRowHeaders(row));
  }

  let desktopDrawerElements = null;
  let desktopDrawerSourceRow = null;

  function ensureDesktopDrawer() {
    if (desktopDrawerElements) return desktopDrawerElements;

    const backdrop = document.createElement("div");
    backdrop.className = "desktop-detail-backdrop";

    const drawer = document.createElement("aside");
    drawer.className = "desktop-detail-drawer";
    drawer.setAttribute("aria-hidden", "true");
    drawer.setAttribute("aria-label", "Row details");

    drawer.innerHTML = `
      <div class="desktop-detail-shell">
        <button type="button" class="desktop-detail-close" aria-label="Close details">×</button>
        <div class="desktop-detail-head">
          <span class="desktop-detail-eyebrow">Selected row</span>
          <h2 class="desktop-detail-title">Details</h2>
          <p class="desktop-detail-subtitle"></p>
          <strong class="desktop-detail-amount"></strong>
          <div class="desktop-detail-receipt" hidden></div>
        </div>
        <div class="desktop-detail-body"></div>
        <div class="desktop-detail-actions" aria-label="Available actions"></div>
      </div>`;

    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);

    const close = () => closeDesktopRowDrawer();
    backdrop.addEventListener("click", close);
    drawer.querySelector(".desktop-detail-close").addEventListener("click", close);

    desktopDrawerElements = {
      backdrop,
      drawer,
      title: drawer.querySelector(".desktop-detail-title"),
      subtitle: drawer.querySelector(".desktop-detail-subtitle"),
      amount: drawer.querySelector(".desktop-detail-amount"),
      receipt: drawer.querySelector(".desktop-detail-receipt"),
      body: drawer.querySelector(".desktop-detail-body"),
      actions: drawer.querySelector(".desktop-detail-actions"),
    };

    return desktopDrawerElements;
  }

  function closeDesktopRowDrawer() {
    if (!desktopDrawerElements) return;
    desktopDrawerElements.backdrop.classList.remove("is-visible");
    desktopDrawerElements.drawer.classList.remove("is-visible");
    desktopDrawerElements.drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("desktop-detail-open");
    if (desktopDrawerSourceRow) desktopDrawerSourceRow.classList.remove("is-desktop-selected");
    desktopDrawerSourceRow = null;
  }

  function buildDesktopDetail(row) {
    const headers = getRowHeaders(row);
    const cells = getRowDataCells(row);
    const summary = buildMobileSummary(row, headers);
    const details = [];
    const actionCells = [];

    cells.forEach((cell, index) => {
      const label = headers[index] || cell.getAttribute("data-label") || "Detail";
      collectActionNodes(cell, label).forEach((node) => actionCells.push(node));
      if (isActionLikeCell(cell, label)) return;
      detailLinesForDataCell(cell, label).forEach((line) => details.push(line));
    });

    collectRowExtraDetails(row, details).forEach((line) => details.push(line));

    return { headers, cells, summary, details, actionCells };
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function renderReceiptBox(root, payload) {
    if (!root) return;
    const receipt = payload && payload.receipt ? payload.receipt : null;
    if (!receipt) {
      root.hidden = true;
      root.innerHTML = "";
      return;
    }

    const items = Array.isArray(receipt.items) ? receipt.items.slice(0, 8) : [];
    const itemRows = items.map((item, index) => `
      <li>
        <span>${escapeHtml(item.name || `Item ${String(index + 1).padStart(3, "0")}`)}</span>
        <small>${escapeHtml(item.qty_display || item.qty || "1")} × € ${escapeHtml(item.unit_price_display || item.unit_price || "0.00")}</small>
        <strong>€ ${escapeHtml(item.line_total_display || item.line_total || "0.00")}</strong>
      </li>`).join("");

    root.innerHTML = `
      <div class="desktop-receipt-card paper-receipt-card">
        <div class="paper-receipt-tear"></div>
        <div class="desktop-receipt-head paper-receipt-head">
          <span>Receipt</span>
          <strong>${escapeHtml(receipt.merchant || "Transaction receipt")}</strong>
          <small>${escapeHtml(receipt.purchased_at || "")}${receipt.card_label ? " · " + escapeHtml(receipt.card_label) : ""}${receipt.card_network ? " · " + escapeHtml(receipt.card_network) : ""}${receipt.card_last4 ? " · •••• " + escapeHtml(receipt.card_last4) : ""}</small>
        </div>
        <div class="paper-receipt-separator"></div>
        <ul class="desktop-receipt-items paper-receipt-items">${itemRows || "<li><span>Item 001</span><strong>€ 0.00</strong></li>"}</ul>
        <div class="paper-receipt-separator"></div>
        <div class="desktop-receipt-totals paper-receipt-totals">
          <span>Subtotal <b>€ ${escapeHtml(receipt.subtotal_display || "0.00")}</b></span>
          <span>Discount <b>${escapeHtml(receipt.discount_label || "No discount")}</b></span>
          <strong>Total € ${escapeHtml(receipt.total_display || "0.00")}</strong>
        </div>
      </div>`;
    root.hidden = false;
  }

  function loadDesktopDrawerReceipt(row, elements) {
    if (!elements || !elements.receipt) return;
    const url = row.dataset.receiptUrl || "";
    if (!url) {
      elements.receipt.hidden = true;
      elements.receipt.innerHTML = "";
      return;
    }
    elements.receipt.hidden = false;
    elements.receipt.innerHTML = '<div class="desktop-receipt-card is-loading"><span>Receipt</span><small>Loading receipt details...</small></div>';
    fetch(url, { headers: { "Accept": "application/json" } })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Receipt unavailable")))
      .then((payload) => { renderReceiptBox(elements.receipt, payload); })
      .catch(() => {
        elements.receipt.hidden = true;
        elements.receipt.innerHTML = "";
      });
  }

  function addDesktopDrawerActions(actionsRoot, row, detail) {
    actionsRoot.innerHTML = "";

    if (row.dataset.href) {
      const openLink = document.createElement("a");
      openLink.href = row.dataset.href;
      openLink.className = "desktop-drawer-primary-action";
      openLink.textContent = "Open / edit full page";
      actionsRoot.appendChild(openLink);
    }

    detail.actionCells.forEach((cell) => {
      const clone = cell.cloneNode(true);
      clone.removeAttribute("data-label");
      clone.removeAttribute("aria-hidden");
      clone.classList.remove("desktop-actions-cell", "mobile-row-summary");
      clone.querySelectorAll("[data-label]").forEach((node) => node.removeAttribute("data-label"));
      clone.querySelectorAll("[aria-hidden]").forEach((node) => node.removeAttribute("aria-hidden"));

      const group = document.createElement("div");
      group.className = "desktop-drawer-action-group";
      if (clone.matches("td, th")) {
        while (clone.firstChild) group.appendChild(clone.firstChild);
      } else {
        group.appendChild(clone);
      }
      if (group.textContent.trim() || group.querySelector("a, button, input, select, textarea, form")) {
        actionsRoot.appendChild(group);
      }
    });

    if (!actionsRoot.children.length) {
      const closeButton = document.createElement("button");
      closeButton.type = "button";
      closeButton.className = "desktop-drawer-secondary-action";
      closeButton.textContent = "Close";
      closeButton.addEventListener("click", closeDesktopRowDrawer);
      actionsRoot.appendChild(closeButton);
    }
  }

  function openDesktopRowDrawer(row) {
    if (!canUseDesktopDrawer(row)) return;

    const elements = ensureDesktopDrawer();
    const detail = buildDesktopDetail(row);

    if (desktopDrawerSourceRow && desktopDrawerSourceRow !== row) {
      desktopDrawerSourceRow.classList.remove("is-desktop-selected");
    }

    desktopDrawerSourceRow = row;
    row.classList.add("is-desktop-selected");

    elements.title.textContent = detail.summary.title || "Details";
    elements.subtitle.textContent = detail.summary.meta || "Click actions below to modify this row.";
    elements.amount.textContent = detail.summary.amount || "";
    elements.amount.style.display = detail.summary.amount ? "block" : "none";
    loadDesktopDrawerReceipt(row, elements);

    elements.body.innerHTML = "";
    detail.details.forEach((item) => {
      const line = document.createElement("div");
      line.className = "desktop-detail-line";
      line.appendChild(makeSpan("desktop-detail-line-label", item.label));
      line.appendChild(makeSpan("desktop-detail-line-value", item.text));
      elements.body.appendChild(line);
    });

    addDesktopDrawerActions(elements.actions, row, detail);

    elements.backdrop.classList.add("is-visible");
    elements.drawer.classList.add("is-visible");
    elements.drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("desktop-detail-open");
  }

  function wireDesktopDetailRows() {
    document.querySelectorAll("table.desktop-detail-table tbody tr.desktop-detail-row").forEach((row) => {
      if (row.classList.contains("clickable-row")) return;
      if (row.dataset.desktopDetailWired === "true") return;
      row.dataset.desktopDetailWired = "true";
      row.addEventListener("click", (event) => {
        if (!isDesktopDetailViewport()) return;
        if (event.target.closest(interactiveSelector)) return;
        event.preventDefault();
        openDesktopRowDrawer(row);
      });
      row.addEventListener("keydown", (event) => {
        if (!isDesktopDetailViewport()) return;
        if (event.key !== "Enter" && event.key !== " ") return;
        if (event.target.closest(interactiveSelector)) return;
        event.preventDefault();
        openDesktopRowDrawer(row);
      });
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDesktopRowDrawer();
  });

  function ensureMobileSummaryRow(table, row, headers) {
    if (row.querySelector(":scope > .mobile-row-summary")) return;

    const summary = buildMobileSummary(row, headers);
    const originalCellCount = row.children.length;
    const summaryCell = document.createElement("td");
    summaryCell.className = "mobile-row-summary";
    summaryCell.colSpan = Math.max(originalCellCount, 1);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "mobile-row-toggle";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Show row details");

    const main = document.createElement("span");
    main.className = "mobile-summary-main";
    main.appendChild(makeSpan("mobile-summary-label", summary.titleLabel));
    main.appendChild(makeSpan("mobile-summary-title", summary.title));

    const meta = makeSpan("mobile-summary-meta", summary.meta || "Tap to show details");
    const amount = makeSpan("mobile-summary-amount", summary.amount);
    const chevron = makeSpan("mobile-summary-chevron", "⌄");

    toggle.appendChild(main);
    toggle.appendChild(meta);
    toggle.appendChild(amount);
    toggle.appendChild(chevron);

    const quickActions = document.createElement("div");
    quickActions.className = "mobile-row-quick-actions";

    if (row.dataset.href) {
      const detailLink = document.createElement("a");
      detailLink.href = row.dataset.href;
      detailLink.className = "mobile-detail-action";
      detailLink.textContent = "Open / edit";
      quickActions.appendChild(detailLink);
    }

    const mobileDetail = buildDesktopDetail(row);
    mobileDetail.actionCells.forEach((cell) => {
      const clone = cell.cloneNode(true);
      clone.removeAttribute("data-label");
      clone.removeAttribute("aria-hidden");
      clone.classList.remove("desktop-actions-cell", "mobile-row-summary");
      clone.querySelectorAll("[aria-hidden]").forEach((node) => node.removeAttribute("aria-hidden"));

      const group = document.createElement("div");
      group.className = "mobile-action-group";
      if (clone.matches("td, th")) {
        while (clone.firstChild) group.appendChild(clone.firstChild);
      } else {
        group.appendChild(clone);
      }
      if (group.textContent.trim() || group.querySelector("a, button, input, select, textarea, form")) {
        quickActions.appendChild(group);
      }
    });

    const collapseButton = document.createElement("button");
    collapseButton.type = "button";
    collapseButton.className = "mobile-detail-action mobile-detail-action-secondary";
    collapseButton.textContent = "Close";
    quickActions.appendChild(collapseButton);

    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      toggleMobileRow(row);
    });

    collapseButton.addEventListener("click", (event) => {
      event.preventDefault();
      setMobileRowExpanded(row, false);
    });

    summaryCell.appendChild(toggle);
    summaryCell.appendChild(quickActions);
    row.insertBefore(summaryCell, row.firstElementChild);
    row.classList.add("mobile-disclosure-row");
    row.setAttribute("aria-expanded", "false");
    row.style.cursor = "pointer";
  }

  function enhanceResponsiveTables() {
    document.querySelectorAll("table.standard-table, table[data-mobile-cards='true'], table.transactions-table, table.inline-edit-table").forEach((table) => {
      if (table.dataset.noMobileCards === "true") return;

      const headers = Array.from(table.querySelectorAll("thead th")).map((header) =>
        header.textContent.trim().replace(/\s+/g, " ")
      );

      if (!headers.length) return;

      table.classList.add("mobile-card-table");
      table.classList.add("desktop-detail-table");

      headers.forEach((header, index) => {
        if (normalizeLabel(header).includes("action")) {
          table.classList.add("desktop-action-drawer-table");
          const headerCell = table.querySelectorAll("thead th")[index];
          if (headerCell) headerCell.classList.add("desktop-actions-heading");
        }
      });

      table.querySelectorAll("tbody tr").forEach((row) => {
        const dataCells = Array.from(row.children).filter((cell) => !cell.classList.contains("mobile-row-summary"));
        dataCells.forEach((cell, index) => {
          if (cell.tagName !== "TD") return;
          const header = headers[index] || "";
          if (!cell.hasAttribute("data-label")) cell.setAttribute("data-label", header);
          const normalizedHeader = normalizeLabel(header);
          if (isMoneyLikeLabel(normalizedHeader)) cell.classList.add("desktop-money-cell");
          if (isActionLikeCell(cell, header)) {
            cell.classList.add("desktop-actions-cell");
            table.classList.add("desktop-action-drawer-table");
            const headerCell = table.querySelectorAll("thead th")[index];
            if (headerCell) headerCell.classList.add("desktop-actions-heading");
          }
          if (normalizedHeader.includes("date") || normalizedHeader.includes("due")) cell.classList.add("desktop-date-cell");
          if (["type", "status", "category", "account"].some((label) => normalizedHeader.includes(label))) {
            cell.classList.add("desktop-pill-cell");
          }
        });
        ensureMobileSummaryRow(table, row, headers);
        if (!row.classList.contains("desktop-detail-row") && hasMeaningfulRowDetails(row, headers)) {
          row.classList.add("desktop-detail-row");
          row.setAttribute("tabindex", "0");
        }
      });
    });
  }

  function collapseExpandedRowsWhenLeavingMobile() {
    if (isMobileCardsViewport()) return;
    document.querySelectorAll("tr.mobile-disclosure-row.is-expanded").forEach((row) => {
      setMobileRowExpanded(row, false);
    });
  }



  function selectedText(select) {
    if (!select) return "";
    const selected = select.selectedOptions && select.selectedOptions[0];
    return (selected ? selected.textContent : select.value || "").replace(/\s+/g, " ").trim();
  }

  function inputValue(root, selector) {
    const field = root.querySelector(selector);
    return field ? String(field.value || field.getAttribute("value") || "").trim() : "";
  }

  function textValue(root, selector) {
    const element = root.querySelector(selector);
    return element ? element.textContent.replace(/\s+/g, " ").trim() : "";
  }

  function formatEuroAmount(raw) {
    const value = Number(String(raw || "").replace(",", "."));
    if (!Number.isFinite(value)) return raw || "";
    return `€ ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function setCompactFormExpanded(card, expanded) {
    if (!card || !card.classList.contains("mobile-compact-form-card")) return;

    if (expanded) {
      const list = card.closest(".payment-card-list, .recurring-rule-list, section, main");
      if (list) {
        list.querySelectorAll(".mobile-compact-form-card.mobile-form-expanded").forEach((other) => {
          if (other !== card) setCompactFormExpanded(other, false);
        });
      }
    }

    card.classList.toggle("mobile-form-expanded", expanded);
    card.setAttribute("aria-expanded", expanded ? "true" : "false");

    const toggle = card.querySelector(":scope > .mobile-form-summary");
    if (toggle) toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  }

  function buildPendingSummary(card) {
    const type = selectedText(card.querySelector('select[name="type"]')) || "Payment";
    const category = inputValue(card, 'input[name="category"]');
    const description = inputValue(card, 'input[name="description"]');
    const amount = formatEuroAmount(inputValue(card, 'input[name="amount"]'));
    const due = inputValue(card, 'input[name="date_due"]');
    const account = selectedText(card.querySelector('select[name="account"]'));
    const status = selectedText(card.querySelector('select[name="status"]')) || "Pending";

    const title = description || category || "Pending payment";
    const chips = [type, status, due ? `Due ${due}` : "", account].filter(Boolean);

    return {
      label: card.closest(".payment-card-list-muted") ? "Executed" : "Pending",
      title,
      amount,
      meta: category && description ? category : chips.slice(0, 3).join(" · "),
      chips: chips.slice(0, 4),
    };
  }

  function buildRecurringSummary(card) {
    const title = inputValue(card, 'input[name="name"]') || "Recurring rule";
    const amount = textValue(card, ".rule-amount-stack strong") || formatEuroAmount(inputValue(card, 'input[name="amount"]'));
    const frequency = textValue(card, ".rule-amount-stack span");
    const next = textValue(card, ".next-badge").replace(/^Next:\s*/i, "");
    const type = selectedText(card.querySelector('select[name="type"]')) || textValue(card, ".type-badge");
    const account = selectedText(card.querySelector('select[name="account"]')) || textValue(card, ".account-badge-soft");

    const chips = [type, frequency, next ? `Next ${next}` : "", account].filter(Boolean);

    return {
      label: "Recurring",
      title,
      amount,
      meta: chips.slice(0, 3).join(" · "),
      chips: chips.slice(0, 4),
    };
  }

  function renderCompactFormSummary(card, builder) {
    const summary = builder(card);
    let toggle = card.querySelector(":scope > .mobile-form-summary");
    if (!toggle) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "mobile-form-summary";
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Show details");
      card.insertBefore(toggle, card.firstElementChild);

      toggle.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setCompactFormExpanded(card, !card.classList.contains("mobile-form-expanded"));
      });
    }

    toggle.innerHTML = "";

    const main = document.createElement("span");
    main.className = "mobile-form-summary-main";
    main.appendChild(makeSpan("mobile-summary-label", summary.label));
    main.appendChild(makeSpan("mobile-summary-title", summary.title));

    const meta = makeSpan("mobile-summary-meta", summary.meta || "Tap to show details and actions");
    const amount = makeSpan("mobile-summary-amount", summary.amount || "");
    const chevron = makeSpan("mobile-summary-chevron mobile-form-chevron", "⌄");

    const chips = document.createElement("span");
    chips.className = "mobile-form-summary-chips";
    (summary.chips || []).forEach((chip) => {
      if (!chip) return;
      chips.appendChild(makeSpan("mobile-form-chip", chip));
    });

    toggle.appendChild(main);
    toggle.appendChild(meta);
    toggle.appendChild(amount);
    toggle.appendChild(chevron);
    toggle.appendChild(chips);
  }

  function enhanceCompactFormCards() {
    const compactConfigs = [
      { selector: ".payment-card", builder: buildPendingSummary },
      { selector: ".recurring-rule-card", builder: buildRecurringSummary },
    ];

    compactConfigs.forEach(({ selector, builder }) => {
      document.querySelectorAll(selector).forEach((card) => {
        if (card.dataset.mobileCompactEnhanced === "true") return;
        card.dataset.mobileCompactEnhanced = "true";
        card.classList.add("mobile-compact-form-card");
        card.setAttribute("aria-expanded", "false");

        renderCompactFormSummary(card, builder);

        card.querySelectorAll("input, select, textarea").forEach((field) => {
          field.addEventListener("input", () => renderCompactFormSummary(card, builder));
          field.addEventListener("change", () => renderCompactFormSummary(card, builder));
        });
      });
    });
  }


  function wireQuickSpecialLog() {
    document.querySelectorAll("[data-quick-special-form]").forEach((form) => {
      if (form.dataset.quickSpecialWired === "true") return;
      form.dataset.quickSpecialWired = "true";

      const panel = form.closest(".quick-special-panel");
      const radios = Array.from(form.querySelectorAll('input[name="quick_mode"]'));
      const fieldGroups = Array.from(form.querySelectorAll("[data-modes]"));
      const summary = form.querySelector("[data-quick-special-summary]");
      const modeCards = Array.from(form.querySelectorAll("[data-mode-card]"));

      function currentMode() {
        const checked = radios.find((radio) => radio.checked);
        return checked ? checked.value : "parent_support";
      }

      function toggleFields() {
        const mode = currentMode();

        fieldGroups.forEach((group) => {
          const modes = String(group.dataset.modes || "").split(/\s+/).filter(Boolean);
          const visible = modes.includes(mode);
          group.hidden = !visible;
          group.classList.toggle("is-active", visible);
          group.querySelectorAll("input, select, textarea, button").forEach((field) => {
            field.disabled = !visible;
          });
        });

        modeCards.forEach((card) => {
          card.classList.toggle("is-selected", card.dataset.modeCard === mode);
        });

        if (summary) {
          const checkedCard = modeCards.find((card) => card.dataset.modeCard === mode);
          const targetText = checkedCard ? textValue(checkedCard, "em") : "";
          const description = checkedCard ? textValue(checkedCard, "small") : "";
          const amountInput = form.querySelector('input[name="amount"]:not(:disabled)');
          const amount = Number.parseFloat(amountInput ? amountInput.value : "0") || 0;
          const accountSelect = form.querySelector('select[name="account"]:not(:disabled)');
          const selectedAccount = accountSelect ? accountSelect.options[accountSelect.selectedIndex] : null;
          const accountKind = selectedAccount ? selectedAccount.dataset.kind : "main";
          const accountKey = selectedAccount ? selectedAccount.dataset.key : "main_bank";
          const accountLabel = selectedAccount ? ((selectedAccount.dataset.displayLabel || selectedAccount.textContent || "").trim()) : "Main bank account";
          const balances = window.moneyManagerAccountBalances || {};
          const mainNet = Number(window.moneyManagerMainNet || 0);
          let preview = "";
          if (amount > 0 && ["debt_pay", "payable_pay", "project_pay", "receivable_create", "receivable_collect"].includes(mode)) {
            if (accountKind === "auxiliary") {
              const current = Number(balances[accountKey] || 0);
              const after = mode === "receivable_collect" ? current + amount : current - amount;
              preview = `Selected account preview: ${accountLabel} € ${current.toFixed(2)} → € ${after.toFixed(2)}.`;
            } else if (accountKind === "credit") {
              preview = `Credit route preview: main net now is unchanged; future main net after execution/payment ≈ € ${(mainNet - amount).toFixed(2)}.`;
            } else {
              const after = mode === "receivable_collect" ? mainNet + amount : mainNet - amount;
              preview = `Main net preview: € ${mainNet.toFixed(2)} → € ${after.toFixed(2)}.`;
            }
          }
          summary.innerHTML = `
            <strong>${escapeHtml(textValue(checkedCard, "strong") || "Special log")}</strong>
            <span>${escapeHtml(description)}</span>
            <small>${escapeHtml(targetText)}</small>
            ${preview ? `<small>${escapeHtml(preview)}</small>` : ""}
          `;
        }
      }

      radios.forEach((radio) => radio.addEventListener("change", toggleFields));
      form.querySelectorAll("input, select, textarea").forEach((field) => {
        field.addEventListener("input", toggleFields);
        field.addEventListener("change", toggleFields);
      });
      toggleFields();

      if (panel && panel.classList.contains("is-open") && window.location.hash !== "#smart-log") {
        // Do not force-scroll on initial page load; only make sure the panel is usable.
      }
    });

    document.querySelectorAll("[data-quick-special-toggle]").forEach((button) => {
      if (button.dataset.quickSpecialToggleWired === "true") return;
      button.dataset.quickSpecialToggleWired = "true";

      button.addEventListener("click", () => {
        const panel = button.closest(".quick-special-panel");
        if (!panel) return;
        const isOpen = panel.classList.toggle("is-open");
        button.textContent = isOpen ? "Hide special log" : "Debt / Parent / Payable / Project";
      });
    });
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireMobileNavGroups();
    enhanceResponsiveTables();
    wireClickableRows();
    wireDesktopDetailRows();
    enhanceCompactFormCards();
    wireQuickSpecialLog();

    document.querySelectorAll('[data-action="select-all-filters"]').forEach((button) => {
      button.addEventListener("click", selectAllFilters);
    });

    if (mobileCardsMedia.addEventListener) {
      mobileCardsMedia.addEventListener("change", collapseExpandedRowsWhenLeavingMobile);
    }

    if (desktopDetailMedia.addEventListener) {
      desktopDetailMedia.addEventListener("change", () => {
        if (!isDesktopDetailViewport()) closeDesktopRowDrawer();
      });
    }
  });
})();

/* --------------------------------------------------------------------------
   Mobile Special Log helper
-------------------------------------------------------------------------- */
(function () {
  const mobileSpecialMedia = window.matchMedia("(max-width: 760px)");

  function enhanceMobileSpecialLog() {
    document.querySelectorAll("[data-quick-special-form]").forEach((form) => {
      if (form.dataset.mobileSpecialEnhanced === "true") return;
      form.dataset.mobileSpecialEnhanced = "true";

      form.addEventListener("change", (event) => {
        if (!event.target.matches('input[name="quick_mode"]')) return;
        if (!mobileSpecialMedia.matches) return;

        const selectedCard = event.target.closest(".quick-mode-card");
        if (selectedCard) {
          selectedCard.scrollIntoView({ behavior: "auto", block: "nearest", inline: "nearest" });
        }

        window.setTimeout(() => {
          const firstActiveField = form.querySelector(
            ".quick-special-grid .form-field.is-active:not([hidden]) input:not([type='hidden']):not([disabled]), " +
            ".quick-special-grid .form-field.is-active:not([hidden]) select:not([disabled]), " +
            ".quick-special-grid .form-field.is-active:not([hidden]) textarea:not([disabled])"
          );

          if (firstActiveField) {
            firstActiveField.scrollIntoView({ behavior: "auto", block: "nearest" });
          }
        }, 180);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", enhanceMobileSpecialLog);
})();

/* --------------------------------------------------------------------------
   Glass pointer lighting
-------------------------------------------------------------------------- */
(function () {
  let ticking = false;
  let lastEvent = null;
  const coarsePointer = window.matchMedia("(hover: none), (pointer: coarse), (max-width: 1120px)");
  const glowTargetsSelector = ".page-heading, .panel-card, .card, .form-section, .transactions, .summary-card, .priority-card, .mini-priority-card, .quick-mode-card, .payment-card, .recurring-rule-card, .mobile-disclosure-row";

  function updateBodyPointer(event) {
    if (coarsePointer.matches) return;
    lastEvent = event;
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(() => {
      if (!lastEvent) return;
      const x = `${lastEvent.clientX}px`;
      const y = `${lastEvent.clientY}px`;
      document.documentElement.style.setProperty("--pointer-x", x);
      document.documentElement.style.setProperty("--pointer-y", y);
      ticking = false;
    });
  }

  function wireLocalGlow() {
    if (coarsePointer.matches) return;
    document.querySelectorAll(glowTargetsSelector).forEach((target) => {
      if (target.dataset.glowWired === "true") return;
      target.dataset.glowWired = "true";
      target.addEventListener("pointermove", (event) => {
        const rect = target.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
        const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
        target.style.setProperty("--local-x", `${x}%`);
        target.style.setProperty("--local-y", `${y}%`);
      });
    });
  }

  if (!coarsePointer.matches) {
    document.addEventListener("pointermove", updateBodyPointer, { passive: true });
  }
  document.addEventListener("DOMContentLoaded", wireLocalGlow);
})();


/* --------------------------------------------------------------------------
   Aurora UI interactions: button ripple, scroll reveal, desktop pointer glow
-------------------------------------------------------------------------- */
(function () {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const desktopPointer = window.matchMedia("(hover: hover) and (pointer: fine) and (min-width: 1001px)");
  const rippleSelector = [
    ".primary-btn",
    ".secondary-btn",
    ".compact-btn",
    ".mobile-add-menu > summary",
    ".transaction-form button",
    ".recurring-form button",
    ".debt-form button",
    ".entry-form button",
    ".form-actions button",
    ".quick-add-panel a",
    ".mobile-add-panel a",
    ".icon-action-btn",
    ".desktop-drawer-primary-action",
    ".mobile-detail-action",
    ".creditor-payoff-form button",
    ".theme-toggle-btn"
  ].join(", ");

  const revealSelector = [
    ".page-heading",
    ".panel-card",
    ".card",
    ".filters",
    ".form-section",
    ".transactions",
    ".chart-card",
    ".summary-card",
    ".priority-card",
    ".mini-priority-card",
    ".analysis-decision-card",
    ".analysis-kpi",
    ".analysis-health-card",
    ".investment-behaviour-card",
    ".payment-card",
    ".recurring-rule-card",
    ".document-card",
    ".asset-card",
    ".year-card",
    ".initial-condition-card",
    ".flow-card",
    ".top-category-card",
    ".investment-card",
    ".quick-special-panel",
    ".smart-log-studio",
    ".normal-add-polished"
  ].join(", ");

  function createRipple(event) {
    if (reducedMotion.matches || !desktopPointer.matches) return;
    const target = event.target.closest(rippleSelector);
    if (!target) return;

    const rect = target.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    const ripple = document.createElement("span");
    ripple.className = "ripple-dot";
    ripple.style.left = `${event.clientX - rect.left}px`;
    ripple.style.top = `${event.clientY - rect.top}px`;
    target.appendChild(ripple);
    ripple.addEventListener("animationend", () => ripple.remove(), { once: true });
  }

  function wireScrollReveal() {
    const nodes = Array.from(document.querySelectorAll(revealSelector));
    if (!nodes.length) return;

    if (!desktopPointer.matches || reducedMotion.matches || !("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("is-visible"));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });

    nodes.forEach((node, index) => {
      if (node.dataset.revealWired === "true") return;
      node.dataset.revealWired = "true";
      node.classList.add("reveal-on-scroll");
      node.style.setProperty("--reveal-delay", `${Math.min(index % 6, 5) * 38}ms`);
      observer.observe(node);
    });
  }

  function ensureDesktopPointerGlow() {
    if (!desktopPointer.matches || reducedMotion.matches) return null;
    let glow = document.querySelector(".desktop-pointer-glow");
    if (glow) return glow;
    glow = document.createElement("div");
    glow.className = "desktop-pointer-glow";
    glow.setAttribute("aria-hidden", "true");
    document.body.appendChild(glow);
    return glow;
  }

  let pointerTimer = null;
  function activatePointerGlow(event) {
    if (!desktopPointer.matches || reducedMotion.matches) return;
    ensureDesktopPointerGlow();
    document.body.classList.add("pointer-active");
    document.documentElement.style.setProperty("--pointer-x", `${event.clientX}px`);
    document.documentElement.style.setProperty("--pointer-y", `${event.clientY}px`);
    window.clearTimeout(pointerTimer);
    pointerTimer = window.setTimeout(() => {
      document.body.classList.remove("pointer-active");
    }, 900);
  }

  function wireAuroraInteractions() {
    if (desktopPointer.matches && !reducedMotion.matches) {
      document.addEventListener("pointerdown", createRipple, { passive: true });
      document.addEventListener("pointermove", activatePointerGlow, { passive: true });
    }
    wireScrollReveal();
  }

  document.addEventListener("DOMContentLoaded", wireAuroraInteractions);
})();

/* --------------------------------------------------------------------------
   Day / night color mode toggle
-------------------------------------------------------------------------- */
(function () {
  const storageKey = "moneyManagerColorMode";

  function getMode() {
    const mode = document.documentElement.dataset.theme || "day";
    return mode === "night" ? "night" : "day";
  }

  function setMode(mode) {
    const nextMode = mode === "night" ? "night" : "day";
    document.documentElement.dataset.theme = nextMode;
    try {
      window.localStorage.setItem(storageKey, nextMode);
    } catch (error) {
      // Local storage can fail in private windows; the visual toggle still works.
    }
    syncButtons();
  }

  function syncButtons() {
    const mode = getMode();
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const targetMode = mode === "night" ? "day" : "night";
      button.setAttribute("aria-label", `Switch to ${targetMode} mode`);
      button.setAttribute("title", `Switch to ${targetMode} mode`);
      const label = button.querySelector("[data-theme-toggle-label]");
      if (label) label.textContent = targetMode === "night" ? "Night" : "Day";
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    syncButtons();
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      if (button.dataset.themeToggleWired === "true") return;
      button.dataset.themeToggleWired = "true";
      button.addEventListener("click", () => {
        setMode(getMode() === "night" ? "day" : "night");
      });
    });
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-browser-back]").forEach((button) => {
      if (button.dataset.browserNavWired === "back") return;
      button.dataset.browserNavWired = "back";
      button.addEventListener("click", () => window.history.back());
    });
    document.querySelectorAll("[data-browser-forward]").forEach((button) => {
      if (button.dataset.browserNavWired === "forward") return;
      button.dataset.browserNavWired = "forward";
      button.addEventListener("click", () => window.history.forward());
    });
  });
})();
