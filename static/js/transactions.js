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

  function currentEurTotal() {
    const inputs = document.querySelectorAll(".amount-input");
    let total = 0;
    inputs.forEach((input) => {
      const value = Number.parseFloat(input.value);
      if (!Number.isNaN(value)) total += value;
    });
    return total * selectedCurrency().effective_rate_to_eur;
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

  function updateTotal() {
    const currency = selectedCurrency();
    const eurTotal = currentEurTotal();
    let rawTotal = 0;

    document.querySelectorAll(".amount-input").forEach((input) => {
      const value = Number.parseFloat(input.value);
      if (!Number.isNaN(value)) rawTotal += value;
    });

    const totalLabel = document.getElementById("total-amount");
    const totalCurrencyCode = document.getElementById("total-currency-code");
    const eurTotalLabel = document.getElementById("eur-total-amount");
    const ratePreview = document.getElementById("currency-rate-preview");
    const hiddenAmount = document.getElementById("amount-hidden");

    if (totalLabel) totalLabel.innerText = formatMoney(rawTotal);
    if (totalCurrencyCode) totalCurrencyCode.innerText = currency.code;
    if (eurTotalLabel) eurTotalLabel.innerText = formatMoney(eurTotal);
    if (ratePreview) {
      ratePreview.innerText = `Rate: ${currency.rate_to_eur.toFixed(6)} + correction ${currency.correction_to_eur.toFixed(6)} = ${currency.effective_rate_to_eur.toFixed(6)} EUR per unit.`;
    }
    if (hiddenAmount) hiddenAmount.value = rawTotal.toFixed(2);
    updateFuturePreview();
  }

  function addAmountField() {
    const container = document.getElementById("amount-list");
    if (!container) return;

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
    document.querySelectorAll(".amount-input").forEach((input) => input.addEventListener("input", updateTotal));

    const addButton = document.getElementById("add-amount-btn");
    if (addButton) addButton.addEventListener("click", addAmountField);

    const currencySelect = document.getElementById("currency-select");
    if (currencySelect) currencySelect.addEventListener("change", updateTotal);

    const accountSelect = document.getElementById("account-select");
    if (accountSelect) accountSelect.addEventListener("change", togglePayPalPanel);

    const methodSelect = document.getElementById("account-payment-method") || document.getElementById("paypal-payment-method");
    if (methodSelect) methodSelect.addEventListener("change", togglePayPalPanel);

    const insufficientSelect = document.getElementById("account-insufficient-action") || document.getElementById("paypal-insufficient-action");
    if (insufficientSelect) insufficientSelect.addEventListener("change", updateFuturePreview);

    updateTotal();
    togglePayPalPanel();
  });
})();
