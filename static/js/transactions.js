(function () {
  function selectedCurrency() {
    const select = document.getElementById("currency-select");
    const fallback = { code: "EUR", rate_to_eur: 1, correction_to_eur: 0, effective_rate_to_eur: 1 };
    if (!select) return fallback;

    const selected = select.options[select.selectedIndex];
    if (!selected) return fallback;

    const rate = Number.parseFloat(selected.dataset.rate || "1");
    const correction = Number.parseFloat(selected.dataset.correction || "0");
    const effective = Number.parseFloat(selected.dataset.effective || String(rate + correction));
    return {
      code: selected.value || "EUR",
      rate_to_eur: Number.isNaN(rate) ? 1 : rate,
      correction_to_eur: Number.isNaN(correction) ? 0 : correction,
      effective_rate_to_eur: Number.isNaN(effective) ? 1 : effective,
    };
  }

  function formatMoney(value) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function parseMoney(value) {
    const parsed = Number.parseFloat(String(value || "0").replace(",", "."));
    return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
  }

  function receiptRows() {
    return Array.from(document.querySelectorAll(".add-receipt-row"));
  }

  function receiptSubtotalRaw() {
    const rows = receiptRows();
    if (!rows.length) {
      let total = 0;
      document.querySelectorAll(".amount-input").forEach((input) => {
        const value = Number.parseFloat(input.value);
        if (!Number.isNaN(value)) total += value;
      });
      return total;
    }
    let total = 0;
    rows.forEach((row) => {
      const qty = parseMoney(row.querySelector("[data-add-receipt-qty]")?.value || 1);
      const price = parseMoney(row.querySelector("[data-add-receipt-price]")?.value || 0);
      const line = qty * price;
      total += line;
      const preview = row.querySelector("[data-add-receipt-line]");
      if (preview) preview.textContent = `€ ${formatMoney(line)}`;
    });
    return total;
  }

  function receiptDiscountRaw(subtotal) {
    const type = document.getElementById("receipt-discount-type")?.value || "none";
    const value = parseMoney(document.getElementById("receipt-discount-value")?.value || 0);
    if (type === "percent") return subtotal * Math.min(value, 100) / 100;
    if (type === "voucher") return Math.min(subtotal, value);
    return 0;
  }

  function receiptTotalRaw() {
    const subtotal = receiptSubtotalRaw();
    return Math.max(0, subtotal - receiptDiscountRaw(subtotal));
  }

  function currentEurTotal() {
    return receiptTotalRaw() * selectedCurrency().effective_rate_to_eur;
  }

  function selectedAccountMeta() {
    const accountSelect = document.getElementById("account-select");
    if (!accountSelect) return { key: "main_bank", kind: "main", label: "Main bank account" };
    const selected = accountSelect.options[accountSelect.selectedIndex];
    return {
      key: (selected && selected.dataset.key) || "main_bank",
      kind: (selected && selected.dataset.kind) || "main",
      paymentMode: (selected && selected.dataset.paymentMode) || "main_net",
      label: (selected && (selected.dataset.displayLabel || selected.textContent) ? (selected.dataset.displayLabel || selected.textContent).trim() : "Main bank account"),
    };
  }


  function paymentFormState() {
    return window.moneyManagerPaymentForm || {};
  }

  function currentPaymentMethodOptions(accountId) {
    const state = paymentFormState();
    const byAccount = state.payment_methods_by_account || {};
    return byAccount[accountId] || state.payment_method_options || [];
  }

  function methodOptionLabel(method) {
    let label = method.label || method.name || method.id || "Payment method";
    if (method.disabled_reason) label += ` — ${method.disabled_reason}`;
    return label;
  }

  function updatePaymentMethodOptions() {
    const select = document.getElementById("payment-method-select");
    if (!select) return;

    const state = paymentFormState();
    const txType = state.transaction_type || (document.querySelector(".transaction-form")?.dataset.transactionType) || "expense";
    const account = selectedAccountMeta();
    const previous = select.value || state.selected_payment_method_id || "";
    const methods = currentPaymentMethodOptions(account.key);

    select.innerHTML = "";
    if (txType === "income") {
      const optional = document.createElement("option");
      optional.value = "";
      optional.textContent = "Optional for income";
      select.appendChild(optional);
    }

    methods.forEach((method) => {
      const option = document.createElement("option");
      option.value = method.id || "";
      option.textContent = methodOptionLabel(method);
      option.dataset.description = method.description || "";
      option.dataset.methodType = method.method_type || "";
      option.dataset.settlementMode = method.settlement_mode || "";
      option.dataset.linkedAccountId = method.linked_account_id || "";
      option.dataset.fundingAccountId = method.funding_account_id || "";
      option.dataset.settlementAccountId = method.settlement_account_id || "";
      option.dataset.liabilityAccountId = method.liability_account_id || "";
      if (method.disabled_reason) option.disabled = true;
      select.appendChild(option);
    });

    const hasPrevious = Array.from(select.options).some((option) => option.value === previous && !option.disabled);
    if (hasPrevious) {
      select.value = previous;
    } else {
      const firstEnabled = Array.from(select.options).find((option) => !option.disabled && option.value);
      if (firstEnabled) select.value = firstEnabled.value;
    }

    const hint = document.getElementById("payment-method-explanation");
    if (hint) {
      const selected = select.options[select.selectedIndex];
      if (!methods.length && txType !== "income") {
        hint.textContent = "No compatible card/payment method exists for this account yet. Open the Conto and add a card.";
      } else {
        hint.textContent = (selected && selected.dataset.description) || "Select a payment method to preview its route.";
      }
    }

    updateFuturePreview();
  }

  function updateTotal() {
    const currency = selectedCurrency();
    const subtotalRaw = receiptSubtotalRaw();
    const discountRaw = receiptDiscountRaw(subtotalRaw);
    const rawTotal = Math.max(0, subtotalRaw - discountRaw);
    const eurTotal = rawTotal * currency.effective_rate_to_eur;

    const totalLabel = document.getElementById("total-amount");
    const totalCurrencyCode = document.getElementById("total-currency-code");
    const eurTotalLabel = document.getElementById("eur-total-amount");
    const discountLabel = document.getElementById("receipt-discount-preview");
    const ratePreview = document.getElementById("currency-rate-preview");
    const hiddenAmount = document.getElementById("amount-hidden");

    if (totalLabel) totalLabel.innerText = formatMoney(subtotalRaw);
    if (totalCurrencyCode) totalCurrencyCode.innerText = currency.code;
    if (discountLabel) discountLabel.innerText = formatMoney(discountRaw);
    if (eurTotalLabel) eurTotalLabel.innerText = formatMoney(eurTotal);
    if (ratePreview) {
      ratePreview.innerText = `Rate: ${currency.rate_to_eur.toFixed(6)} + correction ${currency.correction_to_eur.toFixed(6)} = ${currency.effective_rate_to_eur.toFixed(6)} EUR per unit.`;
    }
    if (hiddenAmount) hiddenAmount.value = rawTotal.toFixed(2);
    updateFuturePreview();
  }

  function itemNumber(index) {
    return String(index).padStart(3, "0");
  }

  function wireReceiptRow(row) {
    row.querySelectorAll("input, select").forEach((input) => input.addEventListener("input", updateTotal));
    const remove = row.querySelector("[data-add-receipt-remove]");
    if (remove) {
      remove.addEventListener("click", () => {
        const rows = receiptRows();
        if (rows.length <= 1) {
          const name = row.querySelector("input[name='receipt_item_name']");
          const qty = row.querySelector("[data-add-receipt-qty]");
          const price = row.querySelector("[data-add-receipt-price]");
          if (name) name.value = "Item 001";
          if (qty) qty.value = "1";
          if (price) price.value = "0.00";
        } else {
          row.remove();
        }
        updateTotal();
      });
    }
  }

  function addAmountField() {
    const container = document.getElementById("amount-list");
    if (!container) return;

    if (container.classList.contains("receipt-input-list")) {
      const next = receiptRows().length + 1;
      const row = document.createElement("div");
      row.className = "add-receipt-row";
      row.innerHTML = `
        <input type="text" name="receipt_item_name" class="receipt-item-name-input" value="Item ${itemNumber(next)}" placeholder="Item ${itemNumber(next)}">
        <input type="number" min="0" step="0.01" name="receipt_item_qty" class="receipt-item-qty-input" value="1" placeholder="Qty" data-add-receipt-qty>
        <input type="number" min="0" step="0.01" name="receipt_item_unit_price" class="amount-input receipt-item-price-input" placeholder="Unit €" value="0.00" data-add-receipt-price>
        <strong class="receipt-item-line-preview" data-add-receipt-line>€ 0.00</strong>
        <button type="button" class="receipt-remove-row add-receipt-remove" data-add-receipt-remove aria-label="Remove item">×</button>
        <input type="hidden" name="receipt_item_note" value="">`;
      container.appendChild(row);
      wireReceiptRow(row);
      updateTotal();
      return;
    }

    const input = document.createElement("input");
    input.type = "number";
    input.step = "0.01";
    input.className = "amount-input";
    input.placeholder = "0.00";
    input.addEventListener("input", updateTotal);
    container.appendChild(input);
  }

  function togglePayPalPanel() {
    const panel = document.getElementById("account-payment-panel") || document.getElementById("paypal-payment-panel");
    const methodSelect = document.getElementById("account-payment-method") || document.getElementById("paypal-payment-method");
    const insufficientPanel = document.getElementById("account-insufficient-panel") || document.getElementById("paypal-insufficient-panel");
    const nameLabels = document.querySelectorAll("[data-balance-account-name]");
    const balanceLabels = document.querySelectorAll("[data-selected-account-balance]");
    const meta = selectedAccountMeta();
    const balances = window.moneyManagerAccountBalances || {};
    const isBalanceAccount = meta.paymentMode === "tracked_balance" || (meta.kind === "auxiliary" && meta.paymentMode !== "main_net" && meta.paymentMode !== "credit_statement");

    if (!panel) return;
    panel.hidden = !isBalanceAccount;

    nameLabels.forEach((node) => { node.textContent = meta.label; });
    balanceLabels.forEach((node) => { node.textContent = formatMoney(Number(balances[meta.key] || 0)); });

    if (insufficientPanel && methodSelect) {
      insufficientPanel.hidden = !isBalanceAccount || methodSelect.value !== "balance";
    }
    updateFuturePreview();
  }

  function updateFuturePreview() {
    const box = document.getElementById("future-balance-preview");
    if (!box) return;

    const form = document.querySelector(".transaction-form");
    const txType = (form && form.dataset.transactionType) || "expense";
    const amount = currentEurTotal();
    const meta = selectedAccountMeta();
    const balances = window.moneyManagerAccountBalances || {};
    const mainNet = Number(window.moneyManagerMainNet || 0);
    const methodSelect = document.getElementById("account-payment-method") || document.getElementById("paypal-payment-method");
    const insufficientSelect = document.getElementById("account-insufficient-action") || document.getElementById("paypal-insufficient-action");
    const method = methodSelect ? methodSelect.value : "balance";
    const insufficient = insufficientSelect ? insufficientSelect.value : "stop";

    if (!amount) {
      box.innerHTML = "<strong>Future preview</strong><small>Add an amount to preview the future main net or selected account balance.</small>";
      return;
    }

    const sign = txType === "income" ? 1 : -1;

    if (meta.paymentMode === "credit_statement" || meta.kind === "credit") {
      const future = txType === "expense" ? mainNet - amount : mainNet + amount;
      box.innerHTML = `<strong>Future preview</strong><small>Credit route: main net now is unchanged. Future main net after execution/payment: € ${formatMoney(future)}.</small>`;
      return;
    }

    if (meta.paymentMode === "tracked_balance" || meta.kind === "auxiliary") {
      const balance = Number(balances[meta.key] || 0);
      if (txType !== "expense") {
        box.innerHTML = `<strong>Future preview</strong><small>${meta.label} balance: € ${formatMoney(balance)} → € ${formatMoney(balance + amount)}. Main net preview is not changed by this auxiliary movement.</small>`;
        return;
      }

      if (method === "another_card") {
        box.innerHTML = `<strong>Future preview</strong><small>${meta.label} balance unchanged at € ${formatMoney(balance)}. Main net after this main/card route: € ${formatMoney(mainNet - amount)}.</small>`;
        return;
      }

      if (method === "credit") {
        box.innerHTML = `<strong>Future preview</strong><small>${meta.label} balance unchanged at € ${formatMoney(balance)}. Future main net after credit payment: € ${formatMoney(mainNet - amount)}.</small>`;
        return;
      }

      const used = Math.min(Math.max(balance, 0), amount);
      const remaining = Math.max(0, amount - used);
      const afterBalance = balance - used;
      let remainingText = "";
      if (remaining > 0) {
        if (insufficient === "use_credit_for_remaining") remainingText = ` Remaining € ${formatMoney(remaining)} will go to credit; future main net: € ${formatMoney(mainNet - remaining)}.`;
        else if (insufficient === "use_another_card_for_remaining") remainingText = ` Remaining € ${formatMoney(remaining)} will go to main/card route; main net after saving: € ${formatMoney(mainNet - remaining)}.`;
        else remainingText = ` Missing € ${formatMoney(remaining)}; saving will stop unless you choose a split option.`;
      }
      box.innerHTML = `<strong>Future preview</strong><small>${meta.label} balance: € ${formatMoney(balance)} → € ${formatMoney(afterBalance)}.${remainingText}</small>`;
      return;
    }

    const futureMain = mainNet + (sign * amount);
    box.innerHTML = `<strong>Future preview</strong><small>Main net: € ${formatMoney(mainNet)} → € ${formatMoney(futureMain)}.</small>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".amount-input, [data-add-receipt-qty], #receipt-discount-type, #receipt-discount-value").forEach((input) => {
      input.addEventListener("input", updateTotal);
      input.addEventListener("change", updateTotal);
    });
    receiptRows().forEach(wireReceiptRow);

    const addButton = document.getElementById("add-amount-btn");
    if (addButton) addButton.addEventListener("click", addAmountField);

    const currencySelect = document.getElementById("currency-select");
    if (currencySelect) currencySelect.addEventListener("change", updateTotal);

    const accountSelect = document.getElementById("account-select");
    if (accountSelect) accountSelect.addEventListener("change", () => {
      updatePaymentMethodOptions();
      togglePayPalPanel();
    });

    const mainPaymentMethodSelect = document.getElementById("payment-method-select");
    if (mainPaymentMethodSelect) mainPaymentMethodSelect.addEventListener("change", () => {
      const hint = document.getElementById("payment-method-explanation");
      const selected = mainPaymentMethodSelect.options[mainPaymentMethodSelect.selectedIndex];
      if (hint) hint.textContent = (selected && selected.dataset.description) || "Select a payment method to preview its route.";
      updateFuturePreview();
    });

    const methodSelect = document.getElementById("account-payment-method") || document.getElementById("paypal-payment-method");
    if (methodSelect) methodSelect.addEventListener("change", togglePayPalPanel);

    const insufficientSelect = document.getElementById("account-insufficient-action") || document.getElementById("paypal-insufficient-action");
    if (insufficientSelect) insufficientSelect.addEventListener("change", updateFuturePreview);

    updatePaymentMethodOptions();
    updateTotal();
    togglePayPalPanel();
  });
})();
