(function () {
  "use strict";

  var FLOATING_SELECTOR = [
    "[data-smart-floating-submit]",
    ".add-mode-stack.is-normal-mode .normal-add-submit-row"
  ].join(",");

  var rows = [];
  var rafId = 0;

  function viewportHeight() {
    return window.innerHeight || document.documentElement.clientHeight || 0;
  }

  function isElementUsable(element) {
    if (!element || !element.isConnected) return false;
    var style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  }

  function makeSentinel(row) {
    var sentinel = document.createElement("span");
    sentinel.className = "smart-floating-submit-sentinel";
    sentinel.setAttribute("aria-hidden", "true");
    row.parentNode.insertBefore(sentinel, row);
    return sentinel;
  }

  function getContext(row) {
    return row.closest("form, .form-section, .card, section, main") || document.body;
  }

  function shouldFloat(row, sentinel) {
    if (!isElementUsable(row)) return false;

    var context = getContext(row);
    var contextRect = context.getBoundingClientRect();
    var vh = viewportHeight();

    // Do not show a floating save button when the user is completely outside the form/card.
    if (contextRect.bottom < 0 || contextRect.top > vh) return false;

    var sentinelRect = sentinel.getBoundingClientRect();
    var visibleTop = Math.max(0, sentinelRect.top);
    var visibleBottom = Math.min(vh, sentinelRect.bottom || sentinelRect.top + 1);
    var sentinelVisible = visibleBottom > visibleTop;

    if (sentinelVisible) return false;

    // If the original row is already visible, keep it normal.
    var wasFloating = row.classList.contains("is-smart-floating");
    if (!wasFloating) {
      var rowRect = row.getBoundingClientRect();
      var rowVisibleTop = Math.max(0, rowRect.top);
      var rowVisibleBottom = Math.min(vh, rowRect.bottom);
      if (rowVisibleBottom - rowVisibleTop > Math.min(48, Math.max(1, rowRect.height * 0.35))) {
        return false;
      }
    }

    return true;
  }

  function updateRow(item) {
    var row = item.row;
    var sentinel = item.sentinel;
    var nextFloating = shouldFloat(row, sentinel);

    row.classList.toggle("is-smart-floating", nextFloating);
    sentinel.style.height = nextFloating ? Math.ceil(row.offsetHeight || 64) + "px" : "0px";

    return nextFloating;
  }

  function updateAll() {
    rafId = 0;
    var anyFloating = false;
    rows = rows.filter(function (item) {
      if (!item.row.isConnected || !item.sentinel.isConnected) return false;
      anyFloating = updateRow(item) || anyFloating;
      return true;
    });
    document.body.classList.toggle("has-smart-floating-submit", anyFloating);
  }

  function scheduleUpdate() {
    if (rafId) return;
    rafId = window.requestAnimationFrame(updateAll);
  }

  function register(row) {
    if (!row || row.dataset.smartFloatingReady === "1" || !row.parentNode) return;
    row.dataset.smartFloatingReady = "1";
    rows.push({ row: row, sentinel: makeSentinel(row) });
  }

  function init() {
    document.querySelectorAll(FLOATING_SELECTOR).forEach(register);
    scheduleUpdate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.addEventListener("scroll", scheduleUpdate, { passive: true });
  window.addEventListener("resize", scheduleUpdate);
  window.addEventListener("orientationchange", scheduleUpdate);
  window.addEventListener("pageshow", scheduleUpdate);

  if ("MutationObserver" in window) {
    var observer = new MutationObserver(function () {
      init();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
