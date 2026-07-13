(function () {
  "use strict";

  /*
   * Navigation acceleration has two jobs:
   *
   * 1. Ask the server which authenticated GET pages are safe to prepare.
   * 2. Warm at most one likely page after the app is idle, and optionally warm
   *    a link only after deliberate hover/focus intent. A real click is never
   *    delayed by a speculative request; it navigates immediately and can still
   *    consume an already-hot server-side page-cache entry.
   *
   * This avoids duplicate click requests without introducing a risky
   * client-side DOM router. Every destination is still loaded as a normal Flask
   * document, so page-specific scripts, forms and browser history keep their
   * existing behaviour.
   */

  var ENABLED = window.MONEY_MANAGER_DISABLE_ADAPTIVE_NAV !== true;
  var body = document.body;
  var PLAN_URL = (body && body.dataset.navigationPlanUrl) || "/api/performance/navigation-plan";
  var CURRENT_ENDPOINT = (body && body.dataset.pageEndpoint) || "";

  var MARKER_KEY = "money-manager:adaptive-warm-pages:v3";
  var MARKER_MAX_AGE_MS = 5 * 60 * 1000;
  var PLAN_DISCOVERY_DELAY_MS = 240;
  var BACKGROUND_WARM_DELAY_MS = 2600;
  var INTENT_DELAY_MS = 220;
  var BACKGROUND_WARM_LIMIT = 1;
  var MAX_RETRIES = 1;

  var navigationCommitted = false;
  var navigationPreparing = false;
  var preparingTargetKey = "";
  var planPromise = null;
  var planReady = false;
  var planItems = [];
  var planByUrl = new Map();
  var activeWarmPromises = new Map();
  var controllerByUrl = new Map();
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

  function ensureNavigationUi() {
    if (!document.querySelector(".nav-transition-bar")) {
      var bar = document.createElement("div");
      bar.className = "nav-transition-bar";
      bar.setAttribute("aria-hidden", "true");
      document.body.appendChild(bar);
    }

    if (!document.querySelector(".nav-transition-status")) {
      var status = document.createElement("div");
      status.className = "nav-transition-status";
      status.setAttribute("aria-live", "polite");
      status.setAttribute("aria-atomic", "true");
      status.textContent = "Preparing page…";
      document.body.appendChild(status);
    }
  }

  function beginVisualTransition(preparing) {
    ensureNavigationUi();
    navigationPreparing = Boolean(preparing);
    if (!navigationPreparing) preparingTargetKey = "";
    document.body.classList.remove("pointer-active");
    document.body.classList.add("is-navigating");
    document.body.classList.toggle("is-navigation-preparing", Boolean(preparing));
    document.documentElement.setAttribute("aria-busy", "true");
  }

  function clearVisualTransition() {
    navigationPreparing = false;
    preparingTargetKey = "";
    document.body.classList.remove("is-navigating", "is-navigation-preparing");
    document.documentElement.removeAttribute("aria-busy");
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

  function plainPrimaryClick(event) {
    return !event.defaultPrevented && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0;
  }

  function waitForIdle(timeout) {
    return new Promise(function (resolve) {
      if (navigationCommitted || navigationPreparing) {
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

  function cancelBackgroundWarmups(exceptUrl) {
    var exceptKey = canonicalUrl(exceptUrl || "");
    controllerByUrl.forEach(function (controller, key) {
      if (exceptKey && key === exceptKey) return;
      try { controller.abort(); } catch (error) {}
    });
  }

  async function performWarm(key, url, token, reason, retryCount, options) {
    options = options || {};
    var urgent = Boolean(options.urgent);

    if (!urgent) {
      await waitUntilVisible();
      await waitForIdle(reason === "intent" ? 180 : 1100);
      if (navigationCommitted || (navigationPreparing && key !== preparingTargetKey)) return false;
    }

    var attempts = Number(retryCount || 0);
    var inProgressPolls = 0;
    while (!navigationCommitted) {
      var controller = "AbortController" in window ? new AbortController() : null;
      if (controller) controllerByUrl.set(key, controller);

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
          priority: urgent || reason === "intent" ? "high" : "low"
        });

        if (response.status === 202) {
          // Another request is already preparing this exact page. During an
          // actual click, keep the current page visible and poll until the
          // server reports that the rendered-page cache entry is ready.
          if (urgent && inProgressPolls < 14) {
            inProgressPolls += 1;
            await new Promise(function (resolve) { window.setTimeout(resolve, 120); });
            continue;
          }
          return false;
        }

        if (response.ok || response.status === 204) {
          markWarmed(url, token);
          return true;
        }

        if (attempts >= MAX_RETRIES || response.status < 500) return false;
        attempts += 1;
        await new Promise(function (resolve) { window.setTimeout(resolve, 250); });
      } catch (error) {
        if (error && error.name === "AbortError") return false;
        if (attempts >= MAX_RETRIES) return false;
        attempts += 1;
        await new Promise(function (resolve) { window.setTimeout(resolve, 250); });
      } finally {
        if (controllerByUrl.get(key) === controller) controllerByUrl.delete(key);
      }
    }
    return false;
  }

  function warmUrl(url, token, reason, retryCount, options) {
    if (!ENABLED || navigationCommitted || !url) return Promise.resolve(false);

    var key = canonicalUrl(url);
    if (!key || key === canonicalUrl(window.location.href)) return Promise.resolve(false);
    if (wasWarmedRecently(url, token)) return Promise.resolve(true);

    var existing = activeWarmPromises.get(key);
    if (existing) return existing;

    var operation = performWarm(key, url, token, reason, retryCount, options)
      .finally(function () {
        if (activeWarmPromises.get(key) === operation) activeWarmPromises.delete(key);
      });
    activeWarmPromises.set(key, operation);
    return operation;
  }

  function planParams() {
    var params = new URLSearchParams();
    params.set("current", CURRENT_ENDPOINT);
    try {
      var currentUrl = new URL(window.location.href);
      var accountId = currentUrl.searchParams.get("account_id") || "";
      if (accountId) params.set("account_id", accountId);
    } catch (error) {}
    return params;
  }

  function discoverPlan() {
    if (!ENABLED || !CURRENT_ENDPOINT) return Promise.resolve([]);
    if (planPromise) return planPromise;

    planPromise = window.fetch(PLAN_URL + "?" + planParams().toString(), {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Accept": "application/json" }
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (payload) {
      planItems = payload && Array.isArray(payload.items) ? payload.items : [];
      planReady = true;
      planByUrl.clear();
      planItems.forEach(function (item) {
        var key = canonicalUrl(item && item.url);
        if (key) planByUrl.set(key, item);
      });
      return planItems;
    }).catch(function () {
      planPromise = null;
      planReady = false;
      planItems = [];
      return [];
    });

    return planPromise;
  }

  async function runBackgroundPlan() {
    var connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection && connection.saveData) return;

    var items = await discoverPlan();
    var pendingItems = items.filter(function (item) {
      return item && item.url && !wasWarmedRecently(item.url, item.token);
    }).slice(0, BACKGROUND_WARM_LIMIT);

    for (var i = 0; i < pendingItems.length; i += 1) {
      if (navigationCommitted || navigationPreparing) return;
      await warmUrl(pendingItems[i].url, pendingItems[i].token, "adaptive", 0, { urgent: false });
      if (i < pendingItems.length - 1) {
        await new Promise(function (resolve) { window.setTimeout(resolve, 180); });
      }
    }
  }

  function schedulePlan() {
    window.setTimeout(function () {
      discoverPlan();
    }, PLAN_DISCOVERY_DELAY_MS);

    window.setTimeout(function () {
      waitForIdle(1400).then(runBackgroundPlan);
    }, BACKGROUND_WARM_DELAY_MS);
  }

  function scheduleIntentWarm(link) {
    if (!isSafeNavigationLink(link) || navigationCommitted || navigationPreparing) return;
    var key = canonicalUrl(link.href);
    var item = planByUrl.get(key);
    if (!item) {
      if (planReady) return;
      discoverPlan().then(function () {
        var discovered = planByUrl.get(key);
        if (discovered) scheduleIntentWarm(link);
      });
      return;
    }
    if (intentTimer) window.clearTimeout(intentTimer);
    intentTimer = window.setTimeout(function () {
      warmUrl(item.url, item.token, "intent", 0, { urgent: false });
    }, INTENT_DELAY_MS);
  }

  function allowImmediateNavigation() {
    // A real click must never wait for a second speculative render.  The normal
    // document request can consume an existing hot page-cache entry, or build
    // the page once and store it for the next visit.
    navigationCommitted = true;
    navigationPreparing = false;
    preparingTargetKey = "";
    cancelBackgroundWarmups();
    beginVisualTransition(false);
  }


  document.addEventListener("mouseover", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    scheduleIntentWarm(link);
  }, { passive: true });

  document.addEventListener("focusin", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    scheduleIntentWarm(link);
  });

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    if (!isSafeNavigationLink(link) || !plainPrimaryClick(event)) return;

    // Do not preventDefault and do not perform a warm-up fetch here.  The old
    // flow waited as long as 2.6 seconds before starting the actual navigation,
    // producing two GETs for one click and competing for encrypted-file IO.
    allowImmediateNavigation();
  }, true);

  window.addEventListener("pageshow", function () {
    navigationCommitted = false;
    navigationPreparing = false;
    preparingTargetKey = "";
    clearVisualTransition();
    schedulePlan();
  });

  window.addEventListener("pagehide", function () {
    navigationCommitted = true;
    cancelBackgroundWarmups();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedulePlan, { once: true });
  } else {
    schedulePlan();
  }
})();
