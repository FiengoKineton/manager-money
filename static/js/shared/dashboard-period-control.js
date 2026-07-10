(() => {
  const wire = (form) => {
    if (!form || form.dataset.periodControlReady === "1") return;
    form.dataset.periodControlReady = "1";
    const choices = Array.from(form.querySelectorAll('input[name="period_mode"]'));
    const fields = form.querySelector('[data-dashboard-month-fields]');
    const selects = fields ? Array.from(fields.querySelectorAll("select")) : [];
    const sync = () => {
      const monthMode = choices.some((input) => input.checked && input.value === "month");
      if (fields) fields.classList.toggle("is-disabled", !monthMode);
      selects.forEach((select) => { select.disabled = !monthMode; });
      choices.forEach((input) => {
        const label = input.closest(".dashboard-period-choice");
        if (label) label.classList.toggle("is-selected", input.checked);
      });
    };
    choices.forEach((input) => input.addEventListener("change", sync));
    sync();
  };

  const wireAll = () => document.querySelectorAll("[data-dashboard-period-form]").forEach(wire);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireAll, {once: true});
  } else {
    wireAll();
  }
})();
