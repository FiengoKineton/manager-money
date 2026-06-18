/* --------------------------------------------------------------------------
   Phone Fun Shell v3
   Reliable frontend-only mobile shell controller.
   - Uses plain hidden panels instead of native <details> for mobile sheets.
   - Handles click + pointerup so phone taps are dependable.
   - Keeps Add/Plan/More panels inside the viewport and closes them cleanly.
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 1120px), (hover: none) and (pointer: coarse)");
  const sheetSelector = ".mobile-sheet[data-mobile-sheet], .mobile-add-menu[data-mobile-sheet], .mobile-plan-menu[data-mobile-sheet], .mobile-page-menu[data-mobile-sheet]";
  const triggerSelector = "[data-mobile-open-sheet]";
  const closeSelector = "[data-mobile-close-sheets]";
  let lastPointerToggleAt = 0;

  function isPhoneShell() {
    return phoneMedia.matches;
  }

  function sheets() {
    return Array.from(document.querySelectorAll(sheetSelector));
  }

  function triggers() {
    return Array.from(document.querySelectorAll(triggerSelector));
  }

  function getSheetByName(name) {
    return sheets().find((sheet) => sheet.dataset.mobileSheet === name) || null;
  }

  function isSheetOpen(sheet) {
    return Boolean(sheet && sheet.classList.contains("is-open") && !sheet.hidden);
  }

  function setViewportHeightVariable() {
    document.documentElement.style.setProperty("--phone-vh", `${window.innerHeight * 0.01}px`);
  }

  function syncShellClass() {
    const active = isPhoneShell();
    document.documentElement.classList.toggle("phone-shell-active", active);
    if (document.body) document.body.classList.toggle("phone-shell-active", active);
    if (!active) closeAllSheets();
  }

  function syncTriggers() {
    const anyOpen = sheets().some(isSheetOpen);
    document.documentElement.classList.toggle("mobile-sheet-open", anyOpen);
    if (document.body) document.body.classList.toggle("mobile-sheet-open", anyOpen);

    triggers().forEach((trigger) => {
      const name = trigger.getAttribute("data-mobile-open-sheet");
      const sheet = name ? getSheetByName(name) : null;
      const expanded = Boolean(sheet && isSheetOpen(sheet) && isPhoneShell());
      trigger.setAttribute("aria-expanded", expanded ? "true" : "false");
      trigger.classList.toggle("sheet-open", expanded);
    });
  }

  function closeSheet(sheet) {
    if (!sheet) return;
    sheet.classList.remove("is-open");
    sheet.setAttribute("aria-hidden", "true");
    sheet.hidden = true;
  }

  function closeAllSheets(except) {
    sheets().forEach((sheet) => {
      if (sheet !== except) closeSheet(sheet);
    });
    syncTriggers();
  }

  function openSheet(sheet) {
    if (!sheet || !isPhoneShell()) return;
    closeAllSheets(sheet);
    sheet.hidden = false;
    sheet.setAttribute("aria-hidden", "false");

    // Let the browser apply the non-open styles first, then transition in.
    window.requestAnimationFrame(() => {
      sheet.classList.add("is-open");
      syncTriggers();
    });
  }

  function toggleSheetByName(name) {
    const sheet = getSheetByName(name);
    if (!sheet) return;
    if (isSheetOpen(sheet)) {
      closeSheet(sheet);
      syncTriggers();
    } else {
      openSheet(sheet);
    }
  }

  function handleTriggerActivation(event) {
    const trigger = event.target.closest(triggerSelector);
    if (!trigger || !isPhoneShell()) return;

    event.preventDefault();
    event.stopPropagation();

    if (event.type === "pointerup") {
      lastPointerToggleAt = Date.now();
    } else if (event.type === "click" && Date.now() - lastPointerToggleAt < 450) {
      return;
    }

    toggleSheetByName(trigger.getAttribute("data-mobile-open-sheet"));
  }

  function handleCloseActivation(event) {
    if (!isPhoneShell()) return;
    if (!event.target.closest(closeSelector)) return;
    event.preventDefault();
    closeAllSheets();
  }

  function wireSheetLinks() {
    sheets().forEach((sheet) => {
      if (sheet.dataset.phoneFunSheetWired === "true") return;
      sheet.dataset.phoneFunSheetWired = "true";
      sheet.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => closeAllSheets());
      });
    });
  }

  function wirePhoneShell() {
    setViewportHeightVariable();
    syncShellClass();
    wireSheetLinks();
    sheets().forEach((sheet) => {
      if (!sheet.classList.contains("is-open")) closeSheet(sheet);
    });
    syncTriggers();
  }

  document.addEventListener("pointerup", handleTriggerActivation, true);
  document.addEventListener("click", handleTriggerActivation, true);
  document.addEventListener("click", handleCloseActivation, true);

  document.addEventListener("click", (event) => {
    if (!isPhoneShell()) return;
    const insideSheetPanel = event.target.closest(".mobile-sheet-panel, .mobile-page-panel, .mobile-add-panel");
    const insideTrigger = event.target.closest(triggerSelector);
    const insideTabbarLink = event.target.closest(".mobile-tabbar a");

    if (insideTabbarLink) {
      closeAllSheets();
      return;
    }

    if (!insideSheetPanel && !insideTrigger && !event.target.closest(closeSelector)) {
      closeAllSheets();
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllSheets();
  });

  window.addEventListener("resize", () => {
    setViewportHeightVariable();
    syncShellClass();
    syncTriggers();
  }, { passive: true });

  window.addEventListener("orientationchange", () => {
    window.setTimeout(() => {
      setViewportHeightVariable();
      syncShellClass();
      syncTriggers();
    }, 140);
  }, { passive: true });

  document.addEventListener("DOMContentLoaded", wirePhoneShell);
  window.addEventListener("pageshow", wirePhoneShell);

  if (phoneMedia.addEventListener) {
    phoneMedia.addEventListener("change", wirePhoneShell);
  }
})();
