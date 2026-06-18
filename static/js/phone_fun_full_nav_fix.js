/* --------------------------------------------------------------------------
   Phone Fun Shell v2
   Frontend-only mobile shell controller. Keeps sheets reliable on phone/PWA,
   makes Add/Plan/More reachable from the bottom tabbar, and avoids desktop
   dropdown positioning bugs.
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 1120px), (hover: none) and (pointer: coarse)");
  const sheetSelector = ".mobile-sheet[data-mobile-sheet], .mobile-add-menu[data-mobile-sheet], .mobile-plan-menu[data-mobile-sheet], .mobile-page-menu[data-mobile-sheet]";
  const triggerSelector = "[data-mobile-open-sheet]";

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
    triggers().forEach((trigger) => {
      const name = trigger.getAttribute("data-mobile-open-sheet");
      const sheet = name ? getSheetByName(name) : null;
      const expanded = Boolean(sheet && sheet.open && isPhoneShell());
      trigger.setAttribute("aria-expanded", expanded ? "true" : "false");
      trigger.classList.toggle("sheet-open", expanded);
    });
  }

  function closeSheet(sheet) {
    if (sheet && sheet.open) sheet.removeAttribute("open");
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
    sheet.setAttribute("open", "");
    syncTriggers();
  }

  function toggleSheetByName(name) {
    const sheet = getSheetByName(name);
    if (!sheet) return;
    if (sheet.open) {
      closeSheet(sheet);
      syncTriggers();
    } else {
      openSheet(sheet);
    }
  }

  function wireTrigger(trigger) {
    if (!trigger || trigger.dataset.phoneFunTriggerWired === "true") return;
    trigger.dataset.phoneFunTriggerWired = "true";

    trigger.addEventListener("click", (event) => {
      if (!isPhoneShell()) return;
      event.preventDefault();
      event.stopPropagation();
      toggleSheetByName(trigger.getAttribute("data-mobile-open-sheet"));
    });
  }

  function wireSheet(sheet) {
    if (!sheet || sheet.dataset.phoneFunSheetWired === "true") return;
    sheet.dataset.phoneFunSheetWired = "true";

    sheet.addEventListener("toggle", syncTriggers);

    sheet.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => closeAllSheets());
    });
  }

  function wirePhoneShell() {
    syncShellClass();
    setViewportHeightVariable();
    sheets().forEach(wireSheet);
    triggers().forEach(wireTrigger);
    syncTriggers();
  }

  document.addEventListener("click", (event) => {
    if (!isPhoneShell()) return;

    const insideSheetPanel = event.target.closest(".mobile-sheet-panel, .mobile-page-panel, .mobile-add-panel");
    const insideTrigger = event.target.closest(triggerSelector);
    const insideTabbarLink = event.target.closest(".mobile-tabbar a");

    if (insideTabbarLink) {
      closeAllSheets();
      return;
    }

    if (!insideSheetPanel && !insideTrigger) {
      closeAllSheets();
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllSheets();
  });

  window.addEventListener("resize", () => {
    syncShellClass();
    setViewportHeightVariable();
    syncTriggers();
  }, { passive: true });

  window.addEventListener("orientationchange", () => {
    window.setTimeout(() => {
      syncShellClass();
      setViewportHeightVariable();
      syncTriggers();
    }, 120);
  }, { passive: true });

  document.addEventListener("DOMContentLoaded", wirePhoneShell);
  window.addEventListener("pageshow", wirePhoneShell);

  if (phoneMedia.addEventListener) {
    phoneMedia.addEventListener("change", wirePhoneShell);
  }
})();
