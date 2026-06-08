(function () {
  function updateTotal() {
    const inputs = document.querySelectorAll(".amount-input");
    let total = 0;

    inputs.forEach((input) => {
      const value = Number.parseFloat(input.value);
      if (!Number.isNaN(value)) total += value;
    });

    const totalLabel = document.getElementById("total-amount");
    const hiddenAmount = document.getElementById("amount-hidden");

    if (totalLabel) totalLabel.innerText = total.toFixed(2);
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

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".amount-input").forEach((input) => {
      input.addEventListener("input", updateTotal);
    });

    const addButton = document.getElementById("add-amount-btn");
    if (addButton) addButton.addEventListener("click", addAmountField);

    updateTotal();
  });
})();
