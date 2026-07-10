(() => {
  const wire = (form) => {
    if (!form || form.dataset.periodControlReady === "1") {
      return;
    }

    form.dataset.periodControlReady = "1";

    const choices = Array.from(
      form.querySelectorAll('input[name="period_mode"]')
    );
    const monthFields = form.querySelector(
      "[data-dashboard-month-fields]"
    );
    const rangeFields = form.querySelector(
      "[data-dashboard-range-fields]"
    );

    const toggleGroup = (group, visible) => {
      if (!group) {
        return;
      }

      group.hidden = !visible;
      group.setAttribute("aria-hidden", String(!visible));

      group.querySelectorAll("input, select, button").forEach((control) => {
        control.disabled = !visible;
      });
    };

    const sync = () => {
      const selectedMode =
        choices.find((input) => input.checked)?.value || "all";

      toggleGroup(monthFields, selectedMode === "month");
      toggleGroup(rangeFields, selectedMode === "range");

      choices.forEach((input) => {
        const label = input.closest(".dashboard-period-choice");
        if (label) {
          label.classList.toggle("is-selected", input.checked);
        }
        input.setAttribute("aria-checked", String(input.checked));
      });
    };

    choices.forEach((input) => {
      input.addEventListener("change", () => {
        sync();

        if (input.checked && input.value === "all") {
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
        }
      });
    });

    sync();
  };

  const wireAll = () => {
    document
      .querySelectorAll("[data-dashboard-period-form]")
      .forEach(wire);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireAll, { once: true });
  } else {
    wireAll();
  }
})();
