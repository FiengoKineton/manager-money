/* --------------------------------------------------------------------------
   Prism visual helpers
   UI-only: nav dropdown behavior, pointer lighting, reveal animations.
-------------------------------------------------------------------------- */
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const desktop = window.matchMedia("(min-width: 1001px)");

  function allGroups() {
    return Array.from(document.querySelectorAll("[data-prism-group]"));
  }

  function closeOtherGroups(current) {
    allGroups().forEach((group) => {
      if (group !== current) group.removeAttribute("open");
    });
  }

  function closeAllGroups() {
    allGroups().forEach((group) => group.removeAttribute("open"));
  }

  function initNav() {
    const groups = allGroups();
    if (!groups.length) return;

    groups.forEach((group) => {
      group.removeAttribute("open");

      group.addEventListener("toggle", () => {
        if (group.open) closeOtherGroups(group);
      });

      if (finePointer.matches) {
        group.addEventListener("mouseenter", () => {
          if (!desktop.matches) return;
          group.setAttribute("open", "");
          closeOtherGroups(group);
        });
      }
    });

    const bar = document.querySelector(".prism-shellbar");
    if (bar && finePointer.matches) {
      bar.addEventListener("mouseleave", () => {
        if (desktop.matches) closeAllGroups();
      }, { passive: true });
    }

    document.addEventListener("click", (event) => {
      if (!event.target.closest("[data-prism-group]")) closeAllGroups();
    });

    window.addEventListener("resize", closeAllGroups, { passive: true });
  }

  function initPointerLight() {
    if (reduceMotion.matches || !finePointer.matches) return;

    document.querySelectorAll(".prism-shellbar, .prism-action-dock").forEach((surface) => {
      surface.addEventListener("pointermove", (event) => {
        const rect = surface.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
        const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
        surface.style.setProperty("--prism-x", `${x.toFixed(1)}%`);
        surface.style.setProperty("--prism-y", `${y.toFixed(1)}%`);
        surface.style.setProperty("--dock-x", `${x.toFixed(1)}%`);
        surface.style.setProperty("--dock-y", `${y.toFixed(1)}%`);
      }, { passive: true });
    });
  }

  function initScrollState() {
    const update = () => {
      const scrolled = window.scrollY > 36;
      document.body.classList.toggle("prism-scrolled", scrolled);
      document.documentElement.style.setProperty("--dock-rise", scrolled ? "-4px" : "0px");
    };

    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
  }

  function initReveal() {
    const selector = [
      ".prism-hero-ticket",
      ".prism-money-orbit",
      ".prism-position-card",
      ".prism-pathway",
      ".panel-card",
      ".summary-card",
      ".mini-priority-card",
      ".quick-link-card",
      ".chart-card"
    ].join(",");

    const targets = Array.from(document.querySelectorAll(selector));
    if (!targets.length) return;

    if (reduceMotion.matches || !("IntersectionObserver" in window)) {
      targets.forEach((target) => target.classList.add("prism-in-view"));
      return;
    }

    targets.forEach((target) => target.classList.add("prism-reveal"));

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("prism-in-view");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });

    targets.forEach((target) => observer.observe(target));
  }

  function keepActionDockVisible() {
    const dock = document.querySelector(".prism-action-dock");
    if (!dock) return;
    dock.hidden = false;
    dock.removeAttribute("aria-hidden");
  }

  function boot() {
    document.body.classList.add("prism-layout-ready");
    initNav();
    initPointerLight();
    initScrollState();
    initReveal();
    keepActionDockVisible();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
