/* --------------------------------------------------------------------------
   Cockpit layout helpers
   Visual-only: active navigation indicator, command-deck light, scroll progress.
-------------------------------------------------------------------------- */
(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");

  function setScrollProgress() {
    const root = document.documentElement;
    const scrollTop = window.scrollY || document.documentElement.scrollTop || 0;
    const height = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
    const progress = Math.max(0, Math.min(100, (scrollTop / height) * 100));
    root.style.setProperty("--ui-scroll", progress.toFixed(2));
    document.body.classList.toggle("cockpit-nav-compact", scrollTop > 90);
  }

  function initNavIndicator() {
    const nav = document.querySelector(".app-navigation-dock .sidebar-nav");
    if (!nav) return;

    let indicator = nav.querySelector(".nav-orbit-indicator");
    if (!indicator) {
      indicator = document.createElement("span");
      indicator.className = "nav-orbit-indicator";
      indicator.setAttribute("aria-hidden", "true");
      nav.appendChild(indicator);
    }

    const moveTo = (item) => {
      if (!item) {
        nav.style.setProperty("--nav-indicator-opacity", "0");
        return;
      }
      const navRect = nav.getBoundingClientRect();
      const itemRect = item.getBoundingClientRect();
      nav.style.setProperty("--nav-indicator-y", `${itemRect.top - navRect.top + nav.scrollTop}px`);
      nav.style.setProperty("--nav-indicator-h", `${itemRect.height}px`);
      nav.style.setProperty("--nav-indicator-opacity", "1");
    };

    const active = nav.querySelector(".nav-items a.active");
    moveTo(active);

    nav.querySelectorAll(".nav-items a").forEach((link) => {
      link.addEventListener("mouseenter", () => moveTo(link));
      link.addEventListener("focus", () => moveTo(link));
    });

    nav.addEventListener("mouseleave", () => moveTo(active));
    nav.addEventListener("scroll", () => moveTo(nav.querySelector(".nav-items a:hover, .nav-items a:focus") || active), { passive: true });
    window.addEventListener("resize", () => moveTo(active), { passive: true });
  }

  function initCommandDeckLight() {
    const deck = document.querySelector(".app-command-deck");
    if (!deck || reduceMotion.matches || !finePointer.matches) return;

    deck.addEventListener("pointermove", (event) => {
      const rect = deck.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
      const y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
      deck.style.setProperty("--deck-x", `${x.toFixed(1)}%`);
      deck.style.setProperty("--deck-y", `${y.toFixed(1)}%`);
    }, { passive: true });
  }

  function initQuickActionDepth() {
    if (reduceMotion.matches || !finePointer.matches) return;

    document.querySelectorAll(".command-action-grid .quick-action").forEach((card) => {
      card.addEventListener("pointermove", (event) => {
        const rect = card.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(rect.width, 1) - 0.5) * 6;
        const y = ((event.clientY - rect.top) / Math.max(rect.height, 1) - 0.5) * -6;
        card.style.transform = `translateY(-4px) rotateX(${y.toFixed(2)}deg) rotateY(${x.toFixed(2)}deg)`;
      }, { passive: true });

      card.addEventListener("pointerleave", () => {
        card.style.transform = "";
      }, { passive: true });
    });
  }

  function bootCockpitLayout() {
    setScrollProgress();
    initNavIndicator();
    initCommandDeckLight();
    initQuickActionDepth();
    window.addEventListener("scroll", setScrollProgress, { passive: true });
    window.addEventListener("resize", setScrollProgress, { passive: true });
    document.body.classList.add("cockpit-layout-ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootCockpitLayout);
  } else {
    bootCockpitLayout();
  }
})();
