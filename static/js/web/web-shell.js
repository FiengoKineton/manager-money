/* Single desktop/local shell. No phone/web runtime switching. */
(function () {
  function syncWebShell() {
    document.documentElement.classList.add("web-shell-active");
    if (document.body) document.body.classList.add("web-shell-active");
  }

  function setupSidebarToggle() {
    const button = document.querySelector("[data-sidebar-toggle]");
    const root = document.documentElement;
    if (!button || button.dataset.sidebarToggleReady === "true") return;
    button.dataset.sidebarToggleReady = "true";

    function isCollapsed() {
      return root.classList.contains("sidebar-collapsed");
    }

    function applyState(collapsed) {
      root.classList.toggle("sidebar-collapsed", collapsed);
      button.setAttribute("aria-expanded", collapsed ? "false" : "true");
      button.title = collapsed ? "Show left navigation" : "Hide left navigation";
      button.setAttribute("aria-label", collapsed ? "Show left navigation" : "Hide left navigation");
      try {
        window.localStorage.setItem("moneyManagerSidebarCollapsed", collapsed ? "1" : "0");
      } catch (error) {
        // Ignore persistence failures; the current click still works.
      }
      window.setTimeout(() => {
        document.querySelectorAll(".js-plotly-plot").forEach((plot) => {
          if (window.Plotly) window.Plotly.Plots.resize(plot);
        });
      }, 180);
    }

    applyState(isCollapsed());
    button.addEventListener("click", () => applyState(!isCollapsed()));
  }

  function setupScopeAccordion() {
    document.querySelectorAll("[data-scope-accordion]").forEach((nav) => {
      const groups = Array.from(nav.querySelectorAll("details[data-scope-group]"));
      groups.forEach((group) => {
        group.removeAttribute("open");
        group.addEventListener("toggle", () => {
          if (!group.open) return;
          groups.forEach((other) => {
            if (other !== group) other.removeAttribute("open");
          });
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    syncWebShell();
    setupSidebarToggle();
    setupScopeAccordion();
  });
  window.addEventListener("pageshow", () => {
    syncWebShell();
    setupSidebarToggle();
    setupScopeAccordion();
  });
  syncWebShell();
})();
