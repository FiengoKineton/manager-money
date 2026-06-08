document.addEventListener("submit", (event) => {
  const form = event.target;
  const action = form.querySelector('input[name="action"]')?.value;

  if (action === "delete_debt" || action === "delete_rule") {
    const ok = window.confirm("Delete this item? This does not remove transactions already created.");
    if (!ok) event.preventDefault();
  }

  if (action === "pay_debt") {
    const ok = window.confirm("Register this payment as an expense transaction with category Debt?");
    if (!ok) event.preventDefault();
  }
});
