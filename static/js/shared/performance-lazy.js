(function () {
  var STALE_CACHE_TTL_MS = 10 * 60 * 1000;
  var FETCH_TIMEOUT_MS = 5000;

  function now() {
    return Date.now ? Date.now() : new Date().getTime();
  }

  function cacheKey(url) {
    return "money-manager:topbar-summary:v2:" + String(url || "");
  }

  function readCached(url) {
    try {
      var raw = window.sessionStorage && window.sessionStorage.getItem(cacheKey(url));
      if (!raw) return null;
      var item = JSON.parse(raw);
      var age = now() - Number(item && item.savedAt || 0);
      if (!item || !item.payload || age > STALE_CACHE_TTL_MS) return null;
      return item.payload;
    } catch (error) {
      return null;
    }
  }

  function writeCached(url, payload) {
    try {
      if (window.sessionStorage && payload && payload.ok !== false) {
        window.sessionStorage.setItem(cacheKey(url), JSON.stringify({savedAt: now(), payload: payload}));
      }
    } catch (error) {
      // Cache storage is a performance hint only.
    }
  }

  function updatePill(pill, payload) {
    const valueNode = pill.querySelector("[data-topbar-net-value], [data-phone-net-value]");
    const labelNode = pill.querySelector("[data-topbar-net-label], [data-phone-net-label]");
    if (!valueNode || !payload || payload.ok === false) return;
    valueNode.textContent = payload.net_formatted || "€ 0.00";
    if (labelNode && payload.label) labelNode.textContent = payload.label;
  }

  function runWhenIdle(callback) {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(callback, {timeout: 800});
    } else {
      window.setTimeout(callback, 120);
    }
  }

  function fetchWithTimeout(url) {
    var controller = null;
    var timeoutId = null;
    if ("AbortController" in window) {
      controller = new AbortController();
      timeoutId = window.setTimeout(function () {
        try { controller.abort(); } catch (error) {}
      }, FETCH_TIMEOUT_MS);
    }
    return fetch(url, {
      credentials: "same-origin",
      headers: {"Accept": "application/json", "X-MoneyManager-Lazy": "topbar-summary"},
      signal: controller ? controller.signal : undefined,
    }).finally(function () {
      if (timeoutId) window.clearTimeout(timeoutId);
    });
  }

  function loadTopbarNet() {
    const pills = Array.from(document.querySelectorAll("[data-topbar-net-pill], [data-phone-net-pill]"));
    if (!pills.length) return;

    const groups = new Map();
    pills.forEach((pill) => {
      if (pill.dataset.maskSensitive === "1") return;
      const url = pill.dataset.topbarSummaryUrl;
      const valueNode = pill.querySelector("[data-topbar-net-value], [data-phone-net-value]");
      if (!url || !valueNode) return;
      if (!groups.has(url)) groups.set(url, []);
      groups.get(url).push(pill);
    });

    groups.forEach((groupPills, url) => {
      var cached = readCached(url);
      if (cached) {
        // Stale-while-revalidate: paint instantly from session cache, then
        // refresh in the idle queue so a transaction saved on the previous
        // page is reflected without making navigation wait.
        groupPills.forEach((pill) => updatePill(pill, cached));
      }

      runWhenIdle(function () {
        fetchWithTimeout(url)
          .then((response) => (response.ok ? response.json() : null))
          .then((payload) => {
            if (!payload || payload.ok === false) return;
            writeCached(url, payload);
            groupPills.forEach((pill) => updatePill(pill, payload));
          })
          .catch(() => {
            groupPills.forEach((pill) => {
              const valueNode = pill.querySelector("[data-topbar-net-value], [data-phone-net-value]");
              // A failed GET is not a zero balance. Keep any last-known value;
              // on a first-load failure show an unavailable marker instead.
              if (valueNode && valueNode.textContent === "Loading…") valueNode.textContent = "—";
            });
          });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", loadTopbarNet);
})();
