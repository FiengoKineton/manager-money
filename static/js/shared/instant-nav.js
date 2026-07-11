(function () {
  "use strict";

  var ENABLED = window.MONEY_MANAGER_DISABLE_ADAPTIVE_NAV !== true;
  var body = document.body;
  var PLAN_URL = (body && body.dataset.navigationPlanUrl) || "/api/performance/navigation-plan";
  var CURRENT_ENDPOINT = (body && body.dataset.pageEndpoint) || "";
  var MARKER_KEY = "money-manager:adaptive-warm-pages:v1";
  var MARKER_MAX_AGE_MS = 5 * 60 * 1000;
  var INTENT_DELAY_MS = 70;
  var PLAN_START_DELAY_MS = 320;
  var MAX_RETRIES = 1;
  var MAX_RECONCILIATION_PASSES = 2;

  var navigationStarted = false;
  var planLoaded = false;
  var planByUrl = new Map();
  var activeWarmUrls = new Set();
  var activeControllers = new Set();
  var intentTimer = null;
  var markers = readMarkers();

  function now() {
    return Date.now ? Date.now() : new Date().getTime();
  }

  function canonicalUrl(rawUrl) {
    try {
      var url = new URL(rawUrl, window.location.href);
      url.hash = "";
      return url.pathname + url.search;
    } catch (error) {
      return "";
    }
  }

  function readMarkers() {
    try {
      var raw = window.sessionStorage && window.sessionStorage.getItem(MARKER_KEY);
      var payload = raw ? JSON.parse(raw) : {};
      return payload && typeof payload === "object" ? payload : {};
    } catch (error) {
      return {};
    }
  }

  function saveMarkers() {
    try {
      if (!window.sessionStorage) return;
      var cutoff = now() - MARKER_MAX_AGE_MS;
      Object.keys(markers).forEach(function (key) {
        if (!markers[key] || Number(markers[key].savedAt || 0) < cutoff) {
          delete markers[key];
        }
      });
      window.sessionStorage.setItem(MARKER_KEY, JSON.stringify(markers));
    } catch (error) {
      // Warm markers are only a scheduling hint.
    }
  }

  function wasWarmedRecently(url, token) {
    var key = canonicalUrl(url);
    var marker = key && markers[key];
    if (!marker) return false;
    if (token && String(marker.token || "") !== String(token)) return false;
    return now() - Number(marker.savedAt || 0) <= MARKER_MAX_AGE_MS;
  }

  function markWarmed(url, token) {
    var key = canonicalUrl(url);
    if (!key) return;
    markers[key] = { token: String(token || "intent"), savedAt: now() };
    saveMarkers();
  }

  function ensureBar() {
    if (document.querySelector(".nav-transition-bar")) return;
    var bar = document.createElement("div");
    bar.className = "nav-transition-bar";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
  }

  function samePage(url) {
    return url.pathname === window.location.pathname && url.search === window.location.search;
  }

  function isSafeNavigationLink(link) {
    if (!link || link.dataset.noInstantNav === "true" || link.dataset.noPrefetch === "true") return false;
    var href = link.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0 || href.indexOf("mailto:") === 0 || href.indexOf("tel:") === 0) return false;
    if (link.target && link.target !== "_self") return false;
    if (link.hasAttribute("download")) return false;
    try {
      var url = new URL(href, window.location.href);
      return url.origin === window.location.origin && !samePage(url);
    } catch (error) {
      return false;
    }
  }

  function startNavigation(link, event) {
    if (!isSafeNavigationLink(link)) return;
    if (event && (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)) return;
    navigationStarted = true;
    activeControllers.forEach(function (controller) {
      try { controller.abort(); } catch (error) {}
    });
    activeControllers.clear();
    ensureBar();
    document.body.classList.add("is-navigating");
    document.documentElement.setAttribute("aria-busy", "true");
  }

  function waitForIdle(timeout) {
    return new Promise(function (resolve) {
      if (navigationStarted) {
        resolve();
        return;
      }
      if ("requestIdleCallback" in window) {
        window.requestIdleCallback(function () { resolve(); }, { timeout: timeout || 900 });
      } else {
        window.setTimeout(resolve, 100);
      }
    });
  }

  function waitUntilVisible() {
    if (document.visibilityState === "visible") return Promise.resolve();
    return new Promise(function (resolve) {
      function onVisible() {
        if (document.visibilityState !== "visible") return;
        document.removeEventListener("visibilitychange", onVisible);
        resolve();
      }
      document.addEventListener("visibilitychange", onVisible);
    });
  }

  async function warmUrl(url, token, reason, retryCount) {
    if (!ENABLED || navigationStarted || !url) return false;
    var key = canonicalUrl(url);
    if (!key || key === canonicalUrl(window.location.href)) return false;
    if (wasWarmedRecently(url, token) || activeWarmUrls.has(key)) return true;

    await waitUntilVisible();
    await waitForIdle(reason === "intent" ? 220 : 1100);
    if (navigationStarted) return false;

    var controller = "AbortController" in window ? new AbortController() : null;
    if (controller) activeControllers.add(controller);
    activeWarmUrls.add(key);
    try {
      var response = await window.fetch(url, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Accept": "text/html",
          "X-MoneyManager-Warmup": "1",
          "X-MoneyManager-Warm-Reason": reason || "adaptive"
        },
        signal: controller ? controller.signal : undefined,
        priority: reason === "intent" ? "high" : "low"
      });
      if (response.ok || response.status === 202 || response.status === 204) {
        markWarmed(url, token);
        return true;
      }
      if ((retryCount || 0) < MAX_RETRIES && response.status >= 500) {
        await new Promise(function (resolve) { window.setTimeout(resolve, 350); });
        return warmUrl(url, token, reason, (retryCount || 0) + 1);
      }
    } catch (error) {
      if (error && error.name === "AbortError") return false;
    } finally {
      activeWarmUrls.delete(key);
      if (controller) activeControllers.delete(controller);
    }
    return false;
  }

  async function runPlan(items) {
    var connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection && connection.saveData) return;
    for (var i = 0; i < items.length; i += 1) {
      if (navigationStarted) return;
      // Warm the most likely pages first, then yield between waves so the
      // background queue never monopolises CPU or encrypted-file IO.
      if (i > 0 && i % 6 === 0) {
        await new Promise(function (resolve) { window.setTimeout(resolve, 850); });
        await waitForIdle(1500);
      }
      var item = items[i] || {};
      await warmUrl(item.url, item.token, "adaptive", 0);
    }
  }

  async function loadPlan(reconciliationPass) {
    var passNumber = Number(reconciliationPass || 0);
    if (!ENABLED || navigationStarted || !CURRENT_ENDPOINT) return;
    if (planLoaded && passNumber === 0) return;
    if (passNumber === 0) planLoaded = true;
    var params = new URLSearchParams();
    params.set("current", CURRENT_ENDPOINT);
    try {
      var currentUrl = new URL(window.location.href);
      var accountId = currentUrl.searchParams.get("account_id") || "";
      if (accountId) params.set("account_id", accountId);
    } catch (error) {}

    try {
      var response = await window.fetch(PLAN_URL + "?" + params.toString(), {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) return;
      var payload = await response.json();
      var items = payload && Array.isArray(payload.items) ? payload.items : [];
      items.forEach(function (item) {
        var key = canonicalUrl(item && item.url);
        if (key) planByUrl.set(key, item);
      });
      var pendingItems = items.filter(function (item) {
        return item && item.url && !wasWarmedRecently(item.url, item.token);
      });
      if (!pendingItems.length) return;
      await runPlan(pendingItems);

      // Background maintenance or first-use file creation can invalidate pages
      // prepared earlier in the same cycle. Re-read dependency revision tokens
      // up to two times. Stable pages are skipped by their marker; only changed
      // endpoints are requested again.
      if (passNumber < MAX_RECONCILIATION_PASSES && !navigationStarted) {
        await waitForIdle(1600);
        await loadPlan(passNumber + 1);
      }
    } catch (error) {
      if (passNumber === 0) planLoaded = false;
    }
  }

  function schedulePlan() {
    window.setTimeout(function () {
      waitForIdle(1200).then(loadPlan);
    }, PLAN_START_DELAY_MS);
  }

  function scheduleIntentWarm(link) {
    if (!isSafeNavigationLink(link) || navigationStarted) return;
    var key = canonicalUrl(link.href);
    var item = planByUrl.get(key);
    // Only routes declared by the server's safe page registry are prepared.
    if (!item) return;
    if (intentTimer) window.clearTimeout(intentTimer);
    intentTimer = window.setTimeout(function () {
      warmUrl(item.url, item.token, "intent", 0);
    }, INTENT_DELAY_MS);
  }

  document.addEventListener("mouseover", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    scheduleIntentWarm(link);
  }, { passive: true });

  document.addEventListener("focusin", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    scheduleIntentWarm(link);
  });

  document.addEventListener("touchstart", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    scheduleIntentWarm(link);
  }, { passive: true });

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    startNavigation(link, event);
  }, true);

  window.addEventListener("pageshow", function () {
    navigationStarted = false;
    document.body.classList.remove("is-navigating");
    document.documentElement.removeAttribute("aria-busy");
    schedulePlan();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedulePlan, { once: true });
  } else {
    schedulePlan();
  }
})();
