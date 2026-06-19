/* --------------------------------------------------------------------------
   Phone Fun Shell v4 - performance and reliability controller.
   Frontend-only. No backend route/data logic is touched.

   What changed from v3:
   - single click path instead of pointerup + click double handling
   - no capture-phase global toggling
   - no viewport-height recalculation on every mobile browser chrome resize
   - backdrop handles outside close, so sheets do not fight with document clicks
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 1120px), (hover: none) and (pointer: coarse)");
  const sheetSelector = ".mobile-sheet[data-mobile-sheet], .mobile-add-menu[data-mobile-sheet], .mobile-plan-menu[data-mobile-sheet], .mobile-page-menu[data-mobile-sheet]";
  const triggerSelector = "[data-mobile-open-sheet]";
  const closeSelector = "[data-mobile-close-sheets]";
  let initialViewportWidth = window.innerWidth;
  let initialViewportHeight = window.innerHeight;
  let resizeTimer = null;

  function isPhoneShell() {
    return phoneMedia.matches;
  }

  function ensurePhoneFunAppLoaded() {
    if (!isPhoneShell()) return;
    if (document.querySelector('script[data-phone-fun-app="true"]')) return;
    const script = document.createElement("script");
    script.src = "/static/js/phone/phone-fun-app.js?v=phone-fun-app-2";
    script.defer = true;
    script.dataset.phoneFunApp = "true";
    document.head.appendChild(script);
  }

  function allSheets() {
    return Array.from(document.querySelectorAll(sheetSelector));
  }

  function allTriggers() {
    return Array.from(document.querySelectorAll(triggerSelector));
  }

  function getSheetByName(name) {
    return allSheets().find((sheet) => sheet.dataset.mobileSheet === name) || null;
  }

  function isOpen(sheet) {
    return Boolean(sheet && sheet.classList.contains("is-open") && !sheet.hidden);
  }

  function setViewportHeightVariable(force) {
    const width = window.innerWidth;
    const height = window.innerHeight;

    // Mobile browsers fire resize while the URL bar hides/shows during scroll.
    // Updating --phone-vh every time causes layout jumps and stuck-feeling sheets.
    if (!force && Math.abs(width - initialViewportWidth) < 24 && Math.abs(height - initialViewportHeight) < 120) {
      return;
    }

    initialViewportWidth = width;
    initialViewportHeight = height;
    document.documentElement.style.setProperty("--phone-vh", `${height * 0.01}px`);
  }

  function syncShellClass() {
    const enabled = isPhoneShell();
    document.documentElement.classList.toggle("phone-shell-active", enabled);
    if (document.body) document.body.classList.toggle("phone-shell-active", enabled);
    if (!enabled) closeAllSheets();
  }

  function syncTriggers() {
    const anyOpen = allSheets().some(isOpen);
    document.documentElement.classList.toggle("mobile-sheet-open", anyOpen);
    if (document.body) document.body.classList.toggle("mobile-sheet-open", anyOpen);

    allTriggers().forEach((trigger) => {
      const sheet = getSheetByName(trigger.getAttribute("data-mobile-open-sheet"));
      const expanded = Boolean(sheet && isOpen(sheet) && isPhoneShell());
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
    allSheets().forEach((sheet) => {
      if (sheet !== except) closeSheet(sheet);
    });
    syncTriggers();
  }

  function openSheet(sheet) {
    if (!sheet || !isPhoneShell()) return;
    closeAllSheets(sheet);
    sheet.hidden = false;
    sheet.setAttribute("aria-hidden", "false");

    window.requestAnimationFrame(() => {
      sheet.classList.add("is-open");
      syncTriggers();
    });
  }

  function toggleSheet(name) {
    const sheet = getSheetByName(name);
    if (!sheet) return;
    if (isOpen(sheet)) {
      closeSheet(sheet);
      syncTriggers();
    } else {
      openSheet(sheet);
    }
  }

  function handleTriggerClick(event) {
    const trigger = event.target.closest(triggerSelector);
    if (!trigger || !isPhoneShell()) return;
    event.preventDefault();
    toggleSheet(trigger.getAttribute("data-mobile-open-sheet"));
  }

  function wireSheetLinksAndBackdrop() {
    allSheets().forEach((sheet) => {
      if (sheet.dataset.phoneFunSheetWired === "true") return;
      sheet.dataset.phoneFunSheetWired = "true";

      sheet.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => closeAllSheets());
      });

      sheet.querySelectorAll(closeSelector).forEach((button) => {
        button.addEventListener("click", (event) => {
          event.preventDefault();
          closeAllSheets();
        });
      });
    });
  }

  function wirePhoneShell() {
    setViewportHeightVariable(true);
    syncShellClass();
    ensurePhoneFunAppLoaded();
    wireSheetLinksAndBackdrop();
    allSheets().forEach((sheet) => {
      if (!sheet.classList.contains("is-open")) closeSheet(sheet);
    });
    syncTriggers();
  }

  document.addEventListener("click", handleTriggerClick);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllSheets();
  });

  window.addEventListener("orientationchange", () => {
    window.setTimeout(() => {
      setViewportHeightVariable(true);
      syncShellClass();
      syncTriggers();
    }, 180);
  }, { passive: true });

  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      setViewportHeightVariable(false);
      syncShellClass();
      syncTriggers();
    }, 220);
  }, { passive: true });

  document.addEventListener("DOMContentLoaded", wirePhoneShell);
  window.addEventListener("pageshow", wirePhoneShell);

  if (phoneMedia.addEventListener) {
    phoneMedia.addEventListener("change", wirePhoneShell);
  }
})();
