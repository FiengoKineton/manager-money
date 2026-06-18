/* --------------------------------------------------------------------------
   Nebula layout helpers
   Visual-only: nav hover behavior, dock light, active state hints.
-------------------------------------------------------------------------- */
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const desktop = window.matchMedia("(min-width: 1001px)");

  function closeSiblingGroups(current) {
    document.querySelectorAll(".nebula-nav-lane .nav-group").forEach((group) => {
      if (group !== current) group.removeAttribute("open");
    });
  }

  function initNav() {
    const groups = Array.from(document.querySelectorAll(".nebula-nav-lane .nav-group"));
    if (!groups.length) return;

    groups.forEach((group) => {
      const hasActive = Boolean(group.querySelector(".nav-items a.active"));
      group.classList.toggle("nav-group-has-active", hasActive);
      group.removeAttribute("open");

      group.addEventListener("toggle", () => {
        if (group.open && desktop.matches) closeSiblingGroups(group);
      });

      if (finePointer.matches) {
        group.addEventListener("mouseenter", () => {
          if (!desktop.matches) return;
          group.setAttribute("open", "");
          closeSiblingGroups(group);
        });
      }
    });

    const nav = document.querySelector(".nebula-topnav");
    if (nav && finePointer.matches) {
      nav.addEventListener("mouseleave", () => {
        if (!desktop.matches) return;
        groups.forEach((group) => group.removeAttribute("open"));
      }, { passive: true });
    }

    document.addEventListener("click", (event) => {
      if (!event.target.closest(".nebula-nav-lane .nav-group")) {
        groups.forEach((group) => group.removeAttribute("open"));
      }
    });

    const closeAll = () => groups.forEach((group) => group.removeAttribute("open"));
    if (desktop.addEventListener) {
      desktop.addEventListener("change", closeAll);
    }
    window.addEventListener("resize", closeAll, { passive: true });
  }

  function initPointerLight() {
    if (reduceMotion.matches || !finePointer.matches) return;

    document.querySelectorAll(".nebula-topnav, .nebula-action-dock").forEach((surface) => {
      surface.addEventListener("pointermove", (event) => {
        const rect = surface.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
        const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
        surface.style.setProperty("--nebula-x", `${x.toFixed(1)}%`);
        surface.style.setProperty("--nebula-y", `${y.toFixed(1)}%`);
        surface.style.setProperty("--dock-x", `${x.toFixed(1)}%`);
        surface.style.setProperty("--dock-y", `${y.toFixed(1)}%`);
      }, { passive: true });
    });
  }

  function initScrollState() {
    const update = () => {
      const scrolled = window.scrollY > 48;
      document.body.classList.toggle("nebula-scrolled", scrolled);
      document.documentElement.style.setProperty("--nebula-scroll", String(Math.min(window.scrollY, 220)));
      document.documentElement.style.setProperty("--dock-lift", scrolled ? "4" : "0");
    };

    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
  }

  function initCardDepth() {
    if (reduceMotion.matches || !finePointer.matches) return;

    const selector = [
      ".mini-priority-card",
      ".summary-card",
      ".priority-card",
      ".quick-link-card",
      ".panel-card",
      ".chart-card"
    ].join(",");

    document.querySelectorAll(selector).forEach((card) => {
      card.addEventListener("pointermove", (event) => {
        const rect = card.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(rect.width, 1) - 0.5) * 4;
        const y = ((event.clientY - rect.top) / Math.max(rect.height, 1) - 0.5) * -4;
        card.style.transform = `translateY(-4px) rotateX(${y.toFixed(2)}deg) rotateY(${x.toFixed(2)}deg)`;
      }, { passive: true });

      card.addEventListener("pointerleave", () => {
        card.style.transform = "";
      }, { passive: true });
    });
  }

  function boot() {
    document.body.classList.add("nebula-layout-ready");
    initNav();
    initPointerLight();
    initScrollState();
    initCardDepth();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
