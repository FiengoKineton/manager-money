(function () {
  "use strict";

  // Document prefetch is intentionally opt-in.
  // In this local Flask app every prefetched document executes the full backend
  // route, which can decrypt CSV/JSON data, build dashboards, run maintenance,
  // and compete with the real click.  Keep instant-nav as a visual transition,
  // but do not silently prepare the whole workflow just because a link was
  // hovered/focused.
  var ENABLE_DOCUMENT_PREFETCH = window.MONEY_MANAGER_ENABLE_DOCUMENT_PREFETCH === true;
  var prefetched = new Set();
  var PREFETCH_LIMIT = 3;
  var SKIP_PATH_PARTS = ["/logout", "/delete", "/archive", "/restore", "/export", "/api/", "/integrity"];

  function ensureBar() {
    if (document.querySelector(".nav-transition-bar")) {
      return;
    }
    var bar = document.createElement("div");
    bar.className = "nav-transition-bar";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
  }

  function samePage(url) {
    return url.pathname === window.location.pathname && url.search === window.location.search;
  }

  function isSafeNavigationLink(link) {
    if (!link || link.dataset.noInstantNav === "true" || link.dataset.noPrefetch === "true") {
      return false;
    }
    var href = link.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0 || href.indexOf("mailto:") === 0 || href.indexOf("tel:") === 0) {
      return false;
    }
    if (link.target && link.target !== "_self") {
      return false;
    }
    if (link.hasAttribute("download")) {
      return false;
    }
    var url;
    try {
      url = new URL(href, window.location.href);
    } catch (error) {
      return false;
    }
    if (url.origin !== window.location.origin || samePage(url)) {
      return false;
    }
    return !SKIP_PATH_PARTS.some(function (part) { return url.pathname.indexOf(part) !== -1; });
  }

  function prefetch(link) {
    if (!ENABLE_DOCUMENT_PREFETCH || !isSafeNavigationLink(link) || prefetched.size >= PREFETCH_LIMIT) {
      return;
    }
    var url = new URL(link.getAttribute("href"), window.location.href);
    var key = url.pathname + url.search;
    if (prefetched.has(key)) {
      return;
    }
    prefetched.add(key);

    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(function () { addPrefetch(url.href); }, { timeout: 900 });
    } else {
      window.setTimeout(function () { addPrefetch(url.href); }, 120);
    }
  }

  function addPrefetch(href) {
    var hint = document.createElement("link");
    hint.rel = "prefetch";
    hint.href = href;
    hint.as = "document";
    document.head.appendChild(hint);
  }

  function startNavigation(link, event) {
    if (!isSafeNavigationLink(link)) {
      return;
    }
    if (event && (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)) {
      return;
    }
    ensureBar();
    document.body.classList.add("is-navigating");
    document.documentElement.setAttribute("aria-busy", "true");
  }

  document.addEventListener("mouseover", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    prefetch(link);
  }, { passive: true });

  document.addEventListener("focusin", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    prefetch(link);
  });

  document.addEventListener("touchstart", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    prefetch(link);
  }, { passive: true });

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    startNavigation(link, event);
  }, true);

  window.addEventListener("pageshow", function () {
    document.body.classList.remove("is-navigating");
    document.documentElement.removeAttribute("aria-busy");
  });
})();
