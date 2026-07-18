(function () {
  function text(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function cellValue(cell) {
    if (!cell) return "";
    const field = cell.querySelector("input:not([type='hidden']), select, textarea");
    if (!field) return text(cell.textContent);
    if (field.tagName === "SELECT") return text(field.selectedOptions?.[0]?.textContent || field.value);
    if (field.type === "checkbox") return field.checked ? "Active" : "Inactive";
    return text(field.value);
  }

  function findValue(headers, cells, label) {
    const wanted = text(label).toLowerCase();
    const index = headers.findIndex((header) => header === wanted || header.includes(wanted));
    return index >= 0 ? cellValue(cells[index]) : "";
  }

  function closeDialog(dialog) {
    if (dialog?.open) dialog.close();
  }

  function wireDialog(dialog, openButton) {
    openButton.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      dialog.showModal();
    });
    dialog.querySelectorAll("[data-native-dialog-close]").forEach((button) => {
      button.addEventListener("click", () => closeDialog(dialog));
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });
  }

  function transformEntityTables() {
    document.querySelectorAll("table.entity-card-grid-table").forEach((table, tableIndex) => {
      if (table.dataset.nativeDialogReady === "true") return;
      const body = table.tBodies[0];
      if (!body || !body.rows.length) return;
      table.dataset.nativeDialogReady = "true";

      const headers = Array.from(table.querySelectorAll("thead th")).map((header) => text(header.textContent).toLowerCase());
      const titleLabels = String(table.dataset.mobileTitle || "Name").split(",").map(text).filter(Boolean);
      const metaLabels = String(table.dataset.mobileMeta || "").split(",").map(text).filter(Boolean);
      const amountLabel = text(table.dataset.mobileAmount || "Amount");
      const grid = document.createElement("div");
      grid.className = "native-entity-grid recurring-compact-grid";

      Array.from(body.rows).forEach((row, rowIndex) => {
        row.querySelectorAll(":scope > .entity-card-summary, :scope > .entity-card-modal-close-cell").forEach((node) => node.remove());
        row.classList.remove("entity-card-modal-open");
        const cells = Array.from(row.cells);
        const titles = titleLabels.map((label) => findValue(headers, cells, label)).filter(Boolean);
        const meta = metaLabels.map((label) => findValue(headers, cells, label)).filter(Boolean);
        const amount = findValue(headers, cells, amountLabel);
        const status = findValue(headers, cells, "Status") || findValue(headers, cells, "Method / active");
        const dialogId = `native-entity-${tableIndex}-${rowIndex}`;

        const card = document.createElement("article");
        card.className = "recurring-compact-card native-entity-card";
        const openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "recurring-card-open native-entity-open";
        openButton.innerHTML = `
          <span class="type-badge">${status || "Details"}</span>
          <strong>${titles[0] || "Open details"}</strong>
          ${titles.slice(1).map((value) => `<span>${value}</span>`).join("")}
          ${meta.length ? `<small>${meta.join(" · ")}</small>` : ""}
          ${amount ? `<span class="native-entity-amount">€ ${amount.replace(/^€\s*/, "")}</span>` : ""}
        `;

        const dialog = document.createElement("dialog");
        dialog.id = dialogId;
        dialog.className = "entity-detail-dialog native-entity-dialog";
        const shell = document.createElement("div");
        shell.className = "native-dialog-shell";
        const header = document.createElement("div");
        header.className = "dialog-header";
        header.innerHTML = `<div><span class="eyebrow">Details and options</span><h2>${titles[0] || "Record"}</h2></div><button type="button" class="dialog-close" data-native-dialog-close aria-label="Close">×</button>`;
        const scroller = document.createElement("div");
        scroller.className = "native-dialog-content";

        const editorSection = document.createElement("section");
        editorSection.className = "native-dialog-section native-dialog-editor-section";
        editorSection.innerHTML = `<div class="native-dialog-section-heading"><span class="eyebrow">Record</span><h3>Details and editing</h3></div>`;
        const editorGrid = document.createElement("div");
        editorGrid.className = "native-dialog-field-grid";

        cells.forEach((cell, cellIndex) => {
          const label = text(table.querySelectorAll("thead th")[cellIndex]?.textContent) || `Field ${cellIndex + 1}`;
          const field = document.createElement("div");
          field.className = "native-dialog-field";
          if (/actions?/i.test(label)) field.classList.add("native-dialog-actions-field");
          const fieldLabel = document.createElement("span");
          fieldLabel.className = "native-dialog-field-label";
          fieldLabel.textContent = label;
          const fieldBody = document.createElement("div");
          fieldBody.className = "native-dialog-field-body";
          while (cell.firstChild) fieldBody.appendChild(cell.firstChild);
          field.append(fieldLabel, fieldBody);
          editorGrid.appendChild(field);
        });
        editorSection.appendChild(editorGrid);
        scroller.appendChild(editorSection);

        const historyItems = [
          ["Payment history", row.dataset.detailPaymentHistory],
          ["Linked transactions", row.dataset.detailLinkedTransactions],
          ["Timeline", row.dataset.detailTimeline],
          ["Future linked transactions", row.dataset.detailFutureLinkedTransactions],
          ["Rule history", row.dataset.detailRuleHistory]
        ].filter(([, value]) => text(value));

        if (historyItems.length) {
          const historySection = document.createElement("section");
          historySection.className = "native-dialog-section native-dialog-history-section";
          historySection.innerHTML = `<div class="native-dialog-section-heading"><span class="eyebrow">History</span><h3>Activity and linked movements</h3></div>`;
          const historyGrid = document.createElement("div");
          historyGrid.className = "native-dialog-history-grid";
          historyItems.forEach(([label, value]) => {
            const item = document.createElement("article");
            item.className = "native-dialog-history-card";
            const title = document.createElement("h4");
            title.textContent = label;
            const content = document.createElement("p");
            content.textContent = text(value);
            item.append(title, content);
            historyGrid.appendChild(item);
          });
          historySection.appendChild(historyGrid);
          scroller.appendChild(historySection);
        }

        row.remove();
        shell.append(header, scroller);
        dialog.appendChild(shell);
        card.append(openButton, dialog);
        grid.appendChild(card);
        wireDialog(dialog, openButton);
      });

      table.hidden = true;
      table.insertAdjacentElement("beforebegin", grid);
      document.body.classList.remove("entity-card-dialog-open");
      document.querySelector("[data-entity-card-backdrop]")?.remove();
    });
  }

  function transformManagedRecurringCards() {
    document.querySelectorAll(".managed-recurring-grid .special-item-card").forEach((oldCard, index) => {
      if (oldCard.dataset.nativeDialogReady === "true") return;
      const form = oldCard.querySelector(".special-item-form");
      const head = oldCard.querySelector(".special-item-head");
      if (!form || !head) return;
      oldCard.dataset.nativeDialogReady = "true";

      const title = text(head.querySelector("h3")?.textContent) || "Rule";
      const amount = text(head.querySelector("strong")?.textContent);
      const details = text(head.querySelector("p")?.textContent);
      const badges = Array.from(head.querySelectorAll(".type-badge, .soft-badge")).map((node) => node.outerHTML).join("");
      const card = document.createElement("article");
      card.className = "recurring-compact-card native-entity-card managed-native-card";
      const openButton = document.createElement("button");
      openButton.type = "button";
      openButton.className = "recurring-card-open native-entity-open";
      openButton.innerHTML = `${badges}<strong>${title}</strong><span>${amount}</span><small>${details}</small><span class="native-open-label">Open / edit</span>`;

      const dialog = document.createElement("dialog");
      dialog.className = "entity-detail-dialog native-entity-dialog";
      const shell = document.createElement("div");
      shell.className = "native-dialog-shell";
      const header = document.createElement("div");
      header.className = "dialog-header";
      header.innerHTML = `<div><span class="eyebrow">Dedicated recurring rule</span><h2>${title}</h2></div><button type="button" class="dialog-close" data-native-dialog-close aria-label="Close">×</button>`;
      form.querySelectorAll(".managed-card-close").forEach((node) => node.remove());
      form.classList.add("native-dialog-form");
      shell.append(header, form);
      dialog.appendChild(shell);
      card.append(openButton, dialog);
      oldCard.replaceWith(card);
      wireDialog(dialog, openButton);
    });
    document.body.classList.remove("managed-card-dialog-open");
  }

  document.addEventListener("DOMContentLoaded", function () {
    transformEntityTables();
    transformManagedRecurringCards();
  });
})();
