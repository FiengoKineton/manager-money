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
    return value.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function updateTotal() {
    const inputs = document.querySelectorAll(".amount-input");
    let total = 0;

    inputs.forEach((input) => {
      const value = Number.parseFloat(input.value);
      if (!Number.isNaN(value)) total += value;
    });

    const currency = selectedCurrency();
    const eurTotal = total * currency.effective_rate_to_eur;

    const totalLabel = document.getElementById("total-amount");
    const totalCurrencyCode = document.getElementById("total-currency-code");
    const eurTotalLabel = document.getElementById("eur-total-amount");
    const ratePreview = document.getElementById("currency-rate-preview");
    const hiddenAmount = document.getElementById("amount-hidden");

    if (totalLabel) totalLabel.innerText = formatMoney(total);
    if (totalCurrencyCode) totalCurrencyCode.innerText = currency.code;
    if (eurTotalLabel) eurTotalLabel.innerText = formatMoney(eurTotal);
    if (ratePreview) {
      ratePreview.innerText = `Rate: ${currency.rate_to_eur.toFixed(6)} + correction ${currency.correction_to_eur.toFixed(6)} = ${currency.effective_rate_to_eur.toFixed(6)} EUR per unit.`;
    }
    if (hiddenAmount) hiddenAmount.value = total.toFixed(2);
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
    const accountSelect = document.getElementById("account-select");
    const panel = document.getElementById("paypal-payment-panel");
    const methodSelect = document.getElementById("paypal-payment-method");
    const insufficientPanel = document.getElementById("paypal-insufficient-panel");

    if (!accountSelect || !panel) return;

    const selected = accountSelect.options[accountSelect.selectedIndex];
    const isPayPal = selected && selected.dataset.key === "paypal";

    panel.hidden = !isPayPal;

    if (insufficientPanel && methodSelect) {
      insufficientPanel.hidden = !isPayPal || methodSelect.value !== "balance";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".amount-input").forEach((input) => {
      input.addEventListener("input", updateTotal);
    });

    const addButton = document.getElementById("add-amount-btn");
    if (addButton) addButton.addEventListener("click", addAmountField);

    const currencySelect = document.getElementById("currency-select");
    if (currencySelect) currencySelect.addEventListener("change", updateTotal);

    const accountSelect = document.getElementById("account-select");
    if (accountSelect) accountSelect.addEventListener("change", togglePayPalPanel);

    const methodSelect = document.getElementById("paypal-payment-method");
    if (methodSelect) methodSelect.addEventListener("change", togglePayPalPanel);

    updateTotal();
    togglePayPalPanel();
  });
})();
