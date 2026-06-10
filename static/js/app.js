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

  function wireMobileNavGroups() {
    const groups = Array.from(document.querySelectorAll(".nav-group"));
    const isMobile = () => window.matchMedia("(max-width: 1000px)").matches;

    groups.forEach((group) => {
      const summary = group.querySelector("summary");
      if (!summary) return;

      summary.addEventListener("click", () => {
        if (!isMobile()) return;

        window.setTimeout(() => {
          groups.forEach((other) => {
            if (other !== group) {
              other.removeAttribute("open");
            }
          });
        }, 0);
      });

      group.querySelectorAll(".nav-items a").forEach((link) => {
        link.addEventListener("click", () => {
          if (isMobile()) {
            group.removeAttribute("open");
          }
        });
      });
    });

    document.addEventListener("click", (event) => {
      if (!isMobile()) return;
      if (event.target.closest(".nav-group")) return;

      groups.forEach((group) => {
        group.removeAttribute("open");
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireClickableRows();
    wireMobileNavGroups();
    });
})();
