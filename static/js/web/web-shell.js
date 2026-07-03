/* Single desktop/local shell. No phone/web runtime switching. */
(function () {
  function syncWebShell() {
    document.documentElement.classList.add("web-shell-active");
    if (document.body) document.body.classList.add("web-shell-active");
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
    setupScopeAccordion();
  });
  window.addEventListener("pageshow", () => {
    syncWebShell();
    setupScopeAccordion();
  });
  syncWebShell();
})();
