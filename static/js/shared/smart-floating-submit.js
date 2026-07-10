(function () {
  "use strict";

  var TARGET_SELECTOR = [
    "[data-smart-floating-submit]",
    ".add-mode-stack.is-normal-mode .normal-add-submit-row button[type='submit']",
    ".add-mode-stack.is-normal-mode .normal-add-submit-row input[type='submit']"
  ].join(",");

  var targets = [];
  var rafId = 0;
  var activeItem = null;

  function viewportHeight() {
    return window.innerHeight || document.documentElement.clientHeight || 0;
  }

  function viewportWidth() {
    return window.innerWidth || document.documentElement.clientWidth || 0;
  }

  function isUsable(element) {
    if (!element || !element.isConnected) return false;
    if (element.disabled) return false;
    var style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    return true;
  }

  function visibleAreaRatio(element) {
    var rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return 0;
    var left = Math.max(0, rect.left);
    var right = Math.min(viewportWidth(), rect.right);
    var top = Math.max(0, rect.top);
    var bottom = Math.min(viewportHeight(), rect.bottom);
    var visibleWidth = Math.max(0, right - left);
    var visibleHeight = Math.max(0, bottom - top);
    return (visibleWidth * visibleHeight) / (rect.width * rect.height);
  }

  function getContext(button) {
    return button.closest("form") || button.closest(".add-mode-stack") || button.closest("main") || document.body;
  }

  function contextIntersectsViewport(button) {
    var context = getContext(button);
    var rect = context.getBoundingClientRect();
    var vh = viewportHeight();
    return rect.bottom > 0 && rect.top < vh;
  }

  function labelFor(button) {
    var explicit = button.getAttribute("data-smart-floating-label");
    if (explicit) return String(explicit).replace(/\s+/g, " ").trim();
    var value = button.tagName === "INPUT" ? button.value : button.textContent;
    return String(value || "Save").replace(/\s+/g, " ").trim() || "Save";
  }

  function createProxy(button) {
    var proxy = document.createElement("button");
    proxy.type = "button";
    proxy.className = "smart-floating-submit-proxy";
    proxy.hidden = true;
    proxy.setAttribute("aria-hidden", "true");
    proxy.addEventListener("click", function () {
      if (!isUsable(button)) return;
      button.click();
    });
    document.body.appendChild(proxy);
    return proxy;
  }

  function register(button) {
    if (!button || button.dataset.smartFloatingSubmitReady === "1") return;
    if (!isUsable(button)) return;
    button.dataset.smartFloatingSubmitReady = "1";
    targets.push({ button: button, proxy: createProxy(button) });
  }

  function hide(item) {
    if (!item || !item.proxy) return;
    item.proxy.hidden = true;
    item.proxy.setAttribute("aria-hidden", "true");
    if (activeItem === item) activeItem = null;
  }

  function show(item) {
    var button = item.button;
    var proxy = item.proxy;
    proxy.textContent = labelFor(button);
    proxy.disabled = !!button.disabled;
    proxy.hidden = false;
    proxy.setAttribute("aria-hidden", "false");
    activeItem = item;
  }

  function shouldShow(item) {
    var button = item.button;
    if (!isUsable(button)) return false;
    if (!contextIntersectsViewport(button)) return false;

    // Keep the normal button when it is actually reachable on screen.
    if (visibleAreaRatio(button) >= 0.55) return false;

    var rect = button.getBoundingClientRect();
    var vh = viewportHeight();
    return rect.bottom < 0 || rect.top > vh || visibleAreaRatio(button) < 0.20;
  }

  function updateAll() {
    rafId = 0;
    var nextActive = null;

    targets = targets.filter(function (item) {
      if (!item.button.isConnected) {
        if (item.proxy && item.proxy.parentNode) item.proxy.parentNode.removeChild(item.proxy);
        return false;
      }
      if (!nextActive && shouldShow(item)) nextActive = item;
      return true;
    });

    targets.forEach(function (item) {
      if (item === nextActive) {
        show(item);
      } else {
        hide(item);
      }
    });

    document.body.classList.toggle("has-smart-floating-submit", !!nextActive);
  }

  function scheduleUpdate() {
    if (rafId) return;
    rafId = window.requestAnimationFrame(updateAll);
  }

  function scan() {
    document.querySelectorAll(TARGET_SELECTOR).forEach(register);
    scheduleUpdate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scan, { once: true });
  } else {
    scan();
  }

  window.addEventListener("scroll", scheduleUpdate, { passive: true });
  window.addEventListener("resize", scheduleUpdate);
  window.addEventListener("orientationchange", scheduleUpdate);
  window.addEventListener("pageshow", scheduleUpdate);
  window.addEventListener("load", scheduleUpdate);
  document.addEventListener("input", scheduleUpdate, true);
  document.addEventListener("change", scheduleUpdate, true);

  if ("MutationObserver" in window) {
    var observer = new MutationObserver(function () {
      scan();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden", "disabled"] });
  }
})();
