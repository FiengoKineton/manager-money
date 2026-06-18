/* --------------------------------------------------------------------------
   Phone shell reliability layer
   Frontend-only: closes mobile sheets safely, keeps add/page menus from
   fighting each other, and marks touch/phone layouts for CSS.
-------------------------------------------------------------------------- */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 1120px), (hover: none) and (pointer: coarse)");
  const sheetSelector = ".mobile-add-menu, .mobile-page-menu";

  function isPhoneShell() {
    return phoneMedia.matches;
  }

  function closeSheet(sheet) {
    if (sheet && sheet.open) sheet.removeAttribute("open");
  }

  function closeAllSheets(except) {
    document.querySelectorAll(sheetSelector).forEach((sheet) => {
      if (sheet !== except) closeSheet(sheet);
    });
  }

  function syncShellClass() {
    const active = isPhoneShell();
    document.documentElement.classList.toggle("phone-shell-active", active);
    if (document.body) document.body.classList.toggle("phone-shell-active", active);
    if (!active) closeAllSheets();
  }

  function setViewportHeightVariable() {
    document.documentElement.style.setProperty("--phone-vh", `${window.innerHeight * 0.01}px`);
  }

  function wireSheet(sheet) {
    if (!sheet || sheet.dataset.phoneFunWired === "true") return;
    sheet.dataset.phoneFunWired = "true";

    const summary = sheet.querySelector(":scope > summary");
    if (summary) {
      summary.addEventListener("click", () => {
        if (!isPhoneShell()) return;
        window.setTimeout(() => {
          if (sheet.open) closeAllSheets(sheet);
        }, 0);
      });
    }

    sheet.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => closeAllSheets());
    });
  }

  function wirePhoneShell() {
    syncShellClass();
    setViewportHeightVariable();
    document.querySelectorAll(sheetSelector).forEach(wireSheet);
  }

  document.addEventListener("click", (event) => {
    if (!isPhoneShell()) return;

    const activeSheet = event.target.closest(sheetSelector);
    const bottomNavLink = event.target.closest(".mobile-bottom-nav a");
    const sheetLink = event.target.closest(".mobile-add-panel a, .mobile-page-panel a");

    if (bottomNavLink || sheetLink || !activeSheet) {
      closeAllSheets(activeSheet || null);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllSheets();
  });

  window.addEventListener("resize", () => {
    syncShellClass();
    setViewportHeightVariable();
  }, { passive: true });

  window.addEventListener("orientationchange", () => {
    window.setTimeout(() => {
      syncShellClass();
      setViewportHeightVariable();
    }, 120);
  }, { passive: true });

  window.addEventListener("pageshow", wirePhoneShell);
  document.addEventListener("DOMContentLoaded", wirePhoneShell);

  if (phoneMedia.addEventListener) {
    phoneMedia.addEventListener("change", wirePhoneShell);
  }
})();
