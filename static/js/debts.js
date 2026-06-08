document.addEventListener("DOMContentLoaded", () => {
  const ruleTypeSelect = document.getElementById("debt-rule-type");
  const monthlyFields = document.querySelectorAll(".monthly-rule-field");
  const payoffFields = document.querySelectorAll(".payoff-rule-field");

  if (!ruleTypeSelect) return;

  function syncRuleFields() {
    const isPayoff = ruleTypeSelect.value === "payoff_date";

    monthlyFields.forEach((field) => {
      field.classList.toggle("hidden-debt-rule-field", isPayoff);
    });

    payoffFields.forEach((field) => {
      field.classList.toggle("hidden-debt-rule-field", !isPayoff);
    });
  }

  ruleTypeSelect.addEventListener("change", syncRuleFields);
  syncRuleFields();
});
