(function () {
  document.addEventListener("DOMContentLoaded", () => {
    const fullTransactions = document.getElementById("full-transactions");
    const phoneFullTransactions = document.getElementById("phone-full-transactions");
    const toggleButton = document.getElementById("toggle-transactions-btn");

    if ((!fullTransactions && !phoneFullTransactions) || !toggleButton) return;

    let expanded = false;

    toggleButton.addEventListener("click", () => {
      expanded = !expanded;

      if (fullTransactions) {
        fullTransactions.classList.toggle("is-hidden", !expanded);
        fullTransactions.classList.toggle("is-visible-table", expanded);
      }

      if (phoneFullTransactions) {
        phoneFullTransactions.classList.toggle("is-hidden", !expanded);
        phoneFullTransactions.classList.toggle("is-visible-phone", expanded);
      }

      toggleButton.innerText = expanded ? "Show less" : "Show more";
    });
  });
})();
