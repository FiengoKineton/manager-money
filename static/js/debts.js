document.addEventListener("DOMContentLoaded", () => {
  const ruleTypeSelect = document.getElementById("debt-rule-type");
  if (!ruleTypeSelect) return;

  const periodicFields = document.querySelectorAll(".periodic-rule-field");
  const monthlyOnlyFields = document.querySelectorAll(".monthly-only-rule-field");
  const payoffDateFields = document.querySelectorAll(".payoff-rule-field");
  const amortizedFields = document.querySelectorAll(".amortized-rule-field");
  const payoffLabel = document.getElementById("debt-rule-payoff-label");

  function toggle(fields, hidden) {
    fields.forEach((field) => field.classList.toggle("hidden-debt-rule-field", hidden));
  }

  function syncRuleFields() {
    const type = ruleTypeSelect.value;
    const isPayoffDate = type === "payoff_date";
    const isAmortized = type === "amortized";

    toggle(monthlyOnlyFields, type !== "monthly_instalment");
    toggle(periodicFields, isPayoffDate);
    toggle(amortizedFields, !isAmortized);
    toggle(payoffDateFields, !(isPayoffDate || isAmortized));

    if (payoffLabel) {
      payoffLabel.textContent = isAmortized ? "Payoff date (leave blank if using “Payoff in”)" : "Extinguish date";
    }

    estimateAmortizedInstalment();
  }

  const debtSelect = document.getElementById("debt-rule-debt-select");
  const frequencyInput = document.getElementById("debt-rule-frequency");
  const dayInput = document.getElementById("debt-rule-day");
  const startInput = document.getElementById("debt-rule-start");
  const durationInput = document.getElementById("debt-rule-duration");
  const payoffInput = document.getElementById("debt-rule-payoff");
  const estimateOutput = document.getElementById("debt-rule-estimate");

  function parseDateInput(value) {
    if (!value) return null;
    const parsed = new Date(`${value}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function addMonthsApprox(date, months) {
    const result = new Date(date.getTime());
    result.setMonth(result.getMonth() + months);
    return result;
  }

  // Approximates the server's calendar-accurate amortization math for
  // instant feedback. The stored figure is always recomputed server-side
  // from the exact remaining balance and month-stepping schedule, so this
  // is intentionally labelled as an estimate rather than presented as final.
  function estimateAmortizedInstalment() {
    if (!estimateOutput || ruleTypeSelect.value !== "amortized") return;

    const remaining = parseFloat(debtSelect?.selectedOptions?.[0]?.dataset.remaining || "0") || 0;
    const frequency = Math.max(1, parseInt(frequencyInput?.value || "1", 10) || 1);
    const start = parseDateInput(startInput?.value) || new Date();
    const duration = parseInt(durationInput?.value || "0", 10);
    const explicitPayoff = parseDateInput(payoffInput?.value);
    const payoff = explicitPayoff || (duration > 0 ? addMonthsApprox(start, duration) : null);

    if (!payoff || remaining <= 0 || payoff <= start) {
      estimateOutput.textContent = "Fill in the fields below";
      return;
    }

    const totalMonths = Math.max(1, Math.round((payoff - start) / (30.44 * 24 * 3600 * 1000)));
    const periods = Math.max(1, Math.round(totalMonths / frequency));
    const amount = Math.ceil((remaining * 100) / periods) / 100;
    const unit = frequency === 1 ? "month" : `${frequency} months`;

    estimateOutput.textContent = `≈ €${amount.toFixed(2)} every ${unit} (${periods} payment${periods === 1 ? "" : "s"})`;
  }

  [debtSelect, frequencyInput, dayInput, startInput, durationInput, payoffInput].forEach((field) => {
    if (!field) return;
    field.addEventListener("input", estimateAmortizedInstalment);
    field.addEventListener("change", estimateAmortizedInstalment);
  });

  ruleTypeSelect.addEventListener("change", syncRuleFields);
  syncRuleFields();
});