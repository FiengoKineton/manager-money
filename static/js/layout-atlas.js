/* --------------------------------------------------------------------------
   Atlas layout helpers
   Visual-only: keeps navigation/data logic unchanged.
-------------------------------------------------------------------------- */
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const desktop = window.matchMedia("(min-width: 1001px)");

  function setActiveNavGroups() {
    document.querySelectorAll(".app-navigation-dock .nav-group").forEach((group) => {
      const active = group.querySelector(".nav-items a.active");
      group.classList.toggle("nav-group-has-active", Boolean(active));
    });
  }

  function initAtlasLight() {
    if (reduceMotion.matches || !finePointer.matches) return;

    const surfaces = document.querySelectorAll(".app-navigation-dock.sidebar, .app-command-deck.topbar");
    surfaces.forEach((surface) => {
      surface.addEventListener("pointermove", (event) => {
        const rect = surface.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
        const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
        surface.style.setProperty("--atlas-x", `${x.toFixed(1)}%`);
        surface.style.setProperty("--atlas-y", `${y.toFixed(1)}%`);
        surface.style.setProperty("--deck-x", `${x.toFixed(1)}%`);
        surface.style.setProperty("--deck-y", `${y.toFixed(1)}%`);
      }, { passive: true });
    });
  }

  function initDesktopNavPopovers() {
    const groups = Array.from(document.querySelectorAll(".app-navigation-dock .nav-group"));
    if (!groups.length) return;

    const closeSiblings = (current) => {
      if (!desktop.matches) return;
      groups.forEach((group) => {
        if (group !== current) group.removeAttribute("open");
      });
    };

    groups.forEach((group) => {
      const summary = group.querySelector("summary");
      if (!summary) return;

      summary.addEventListener("click", () => {
        window.setTimeout(() => closeSiblings(group), 0);
      });

      group.addEventListener("mouseenter", () => closeSiblings(group), { passive: true });
    });

    document.addEventListener("click", (event) => {
      if (!desktop.matches) return;
      if (!event.target.closest(".app-navigation-dock .nav-group")) {
        groups.forEach((group) => group.removeAttribute("open"));
      }
    });
  }

  function initStaggeredCards() {
    const selectors = [
      ".summary-card",
      ".card",
      ".panel-card",
      ".chart-card",
      ".kpi-card",
      ".pending-card",
      ".payment-card",
      ".recurring-rule-card",
      ".liquid-account-card",
      ".asset-card",
      ".document-card"
    ];

    document.querySelectorAll(selectors.join(",")).forEach((card, index) => {
      card.style.setProperty("--atlas-card-index", index % 9);
    });
  }

  function initActionAutoFit() {
    const actionGrid = document.querySelector(".command-action-grid.quick-actions");
    if (!actionGrid) return;

    const update = () => {
      const width = actionGrid.getBoundingClientRect().width;
      actionGrid.classList.toggle("quick-actions-tight", width < 560);
    };

    update();
    window.addEventListener("resize", update, { passive: true });
  }

  function boot() {
    document.body.classList.add("atlas-layout-ready");
    setActiveNavGroups();
    initAtlasLight();
    initDesktopNavPopovers();
    initStaggeredCards();
    initActionAutoFit();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
