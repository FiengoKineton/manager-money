(function () {
  const backgroundUrl = document.body.dataset.backgroundUrl;
  if (backgroundUrl) {
    document.documentElement.style.setProperty("--page-bg-image", `url('${backgroundUrl}')`);
  }

  function selectAllFilters() {
    document.querySelectorAll(".type-checkbox").forEach((box) => {
      box.checked = true;
    });

    const select = document.getElementById("category-select");
    if (!select) return;

    Array.from(select.options).forEach((option) => {
      option.selected = true;
    });
  }

  function wireClickableRows() {
    document.querySelectorAll(".clickable-row").forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.target.closest("a, button, input, select, textarea, label, form")) return;
        const href = row.dataset.href;
        if (href) window.location.href = href;
      });
    });
  }

  window.toggleChartSize = function toggleChartSize(button) {
    const card = button.closest(".chart-card");
    if (!card) return;

    card.classList.toggle("chart-expanded");
    button.innerText = card.classList.contains("chart-expanded") ? "Close" : "Expand";

    setTimeout(() => {
      card.querySelectorAll(".js-plotly-plot").forEach((plot) => {
        if (window.Plotly) {
          window.Plotly.Plots.resize(plot);
        }
      });
    }, 100);
  };

  document.addEventListener("DOMContentLoaded", () => {
    wireClickableRows();

    document.querySelectorAll('[data-action="select-all-filters"]').forEach((button) => {
      button.addEventListener("click", selectAllFilters);
    });
  });
})();
