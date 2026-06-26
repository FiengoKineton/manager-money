(function () {
  function updatePill(pill, payload) {
    const valueNode = pill.querySelector("[data-topbar-net-value], [data-phone-net-value]");
    const labelNode = pill.querySelector("[data-topbar-net-label], [data-phone-net-label]");
    if (!valueNode || !payload || payload.ok === false) return;
    valueNode.textContent = payload.net_formatted || "€ 0.00";
    if (labelNode && payload.label) labelNode.textContent = payload.label;
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
      fetch(url, {
        credentials: "same-origin",
        headers: {"Accept": "application/json"},
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((payload) => {
          if (!payload || payload.ok === false) return;
          groupPills.forEach((pill) => updatePill(pill, payload));
        })
        .catch(() => {
          groupPills.forEach((pill) => {
            const valueNode = pill.querySelector("[data-topbar-net-value], [data-phone-net-value]");
            if (valueNode && valueNode.textContent === "Loading…") valueNode.textContent = "€ 0.00";
          });
        });
    });
  }

  document.addEventListener("DOMContentLoaded", loadTopbarNet);
})();
