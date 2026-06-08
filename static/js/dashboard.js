(function () {
  document.addEventListener("DOMContentLoaded", () => {
    const fullTransactions = document.getElementById("full-transactions");
    const toggleButton = document.getElementById("toggle-transactions-btn");

    if (!fullTransactions || !toggleButton) return;

    let expanded = false;

    toggleButton.addEventListener("click", () => {
      expanded = !expanded;
      fullTransactions.classList.toggle("is-hidden", !expanded);
      fullTransactions.classList.toggle("is-visible-table", expanded);
      toggleButton.innerText = expanded ? "Show less" : "Show more";
    });
  });
})();
