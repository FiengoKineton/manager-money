(function () {
  function loadTopbarNet() {
    const pill = document.querySelector("[data-topbar-net-pill]");
    if (!pill) return;
    if (pill.dataset.maskSensitive === "1") return;

    const valueNode = pill.querySelector("[data-topbar-net-value]");
    const labelNode = pill.querySelector("[data-topbar-net-label]");
    const url = pill.dataset.topbarSummaryUrl;
    if (!valueNode || !url) return;

    fetch(url, {
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (!payload || payload.ok === false) return;
        valueNode.textContent = payload.net_formatted || "€ 0.00";
        if (labelNode && payload.label) labelNode.textContent = payload.label;
      })
      .catch(() => {
        if (valueNode.textContent === "Loading…") valueNode.textContent = "€ 0.00";
      });
  }

  document.addEventListener("DOMContentLoaded", loadTopbarNet);
})();
