(function () {
  const backgroundUrl = document.body.dataset.backgroundUrl;
  if (backgroundUrl) {
    document.documentElement.style.setProperty("--page-bg-image", `url('${backgroundUrl}')`);
  }

  const mobileCardsMedia = window.matchMedia("(max-width: 760px)");
  const isMobileCardsViewport = () => mobileCardsMedia.matches;
  const interactiveSelector = "a, button, input, select, textarea, label, form, summary, details, [role='button'], .mobile-row-toggle";

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
      row.addEventListener("click", (event) => {
        if (event.target.closest(interactiveSelector)) return;

        if (isMobileCardsViewport() && row.classList.contains("mobile-disclosure-row")) {
          event.preventDefault();
          toggleMobileRow(row);
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
    const groups = Array.from(document.querySelectorAll(".nav-group"));
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

  function getReadableCellText(cell) {
    if (!cell) return "";

    const clone = cell.cloneNode(true);
    clone.querySelectorAll("script, style").forEach((node) => node.remove());

    clone.querySelectorAll("input, select, textarea").forEach((field) => {
      let value = "";
      if (field.tagName === "SELECT") {
        const selected = field.selectedOptions && field.selectedOptions[0];
        value = selected ? selected.textContent : field.value;
      } else if (field.type === "checkbox") {
        value = field.checked ? "Yes" : "No";
      } else {
        value = field.value || field.getAttribute("value") || field.placeholder || "";
      }
      field.replaceWith(document.createTextNode(value));
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

  function buildMobileSummary(row, headers) {
    const cells = Array.from(row.children).filter((cell) => !cell.classList.contains("mobile-row-summary"));
    const skipIndexes = new Set();

    const title =
      findCellByLabels(cells, headers, ["description", "name", "item", "category", "currency", "person", "payee", "creditor", "parent", "month", "year"]) ||
      findFirstMeaningfulCell(cells, headers, skipIndexes);
    if (title) skipIndexes.add(title.index);

    const amount =
      findCellByLabels(cells, headers, ["amount", "remaining", "total", "balance", "cash", "investment value", "estimated current value", "paid", "collected", "original", "rate", "effective rate"]);
    if (amount) skipIndexes.add(amount.index);

    const metaPieces = [];
    ["date", "type", "account", "status", "due", "source", "parent", "method"].forEach((label) => {
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
    document.querySelectorAll("table").forEach((table) => {
      if (table.dataset.noMobileCards === "true") return;

      const headers = Array.from(table.querySelectorAll("thead th")).map((header) =>
        header.textContent.trim().replace(/\s+/g, " ")
      );

      if (!headers.length) return;

      table.classList.add("mobile-card-table");
      table.querySelectorAll("tbody tr").forEach((row) => {
        const dataCells = Array.from(row.children).filter((cell) => !cell.classList.contains("mobile-row-summary"));
        dataCells.forEach((cell, index) => {
          if (cell.tagName !== "TD" || cell.hasAttribute("data-label")) return;
          cell.setAttribute("data-label", headers[index] || "");
        });
        ensureMobileSummaryRow(table, row, headers);
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

  document.addEventListener("DOMContentLoaded", () => {
    wireClickableRows();
    wireMobileNavGroups();
    enhanceResponsiveTables();
    enhanceCompactFormCards();

    document.querySelectorAll('[data-action="select-all-filters"]').forEach((button) => {
      button.addEventListener("click", selectAllFilters);
    });

    if (mobileCardsMedia.addEventListener) {
      mobileCardsMedia.addEventListener("change", collapseExpandedRowsWhenLeavingMobile);
    }
  });
})();
