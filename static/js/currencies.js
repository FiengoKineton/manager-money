(function () {
  "use strict";

  const settings = window.moneyManagerCurrencyHistory || {};

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function selectedCodes() {
    const checked = qsa("[data-currency-code]").filter((input) => input.checked).map((input) => input.value);
    return checked.slice(0, 8);
  }

  function syncChipStates() {
    qsa(".currency-history-chip").forEach((chip) => {
      const input = qs("[data-currency-code]", chip);
      chip.classList.toggle("is-selected", !!(input && input.checked));
    });
  }

  function setStatus(message, tone) {
    const status = qs("[data-currency-history-status]");
    if (!status) return;
    status.textContent = message;
    status.dataset.tone = tone || "neutral";
  }

  function moneyRate(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return `€ ${Number(value).toFixed(6)}`;
  }

  function percent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const sign = Number(value) > 0 ? "+" : "";
    return `${sign}${Number(value).toFixed(2)}%`;
  }

  function renderSnapshots(payload) {
    const target = qs("[data-currency-snapshots]");
    if (!target) return;
    const series = (payload.series || []).filter((item) => item.latest !== null && item.latest !== undefined);
    if (!series.length) {
      target.innerHTML = "";
      return;
    }
    target.innerHTML = series.map((item) => {
      const change = percent(item.change_pct);
      const tone = Number(item.change_pct || 0) >= 0 ? "positive" : "negative";
      return `
        <article class="currency-history-snapshot">
          <span>${item.code}</span>
          <strong>${moneyRate(item.latest)}</strong>
          <small class="${tone}">${change} in ${payload.period_label || "period"}</small>
        </article>
      `;
    }).join("");
  }

  function renderChart(payload) {
    const chart = qs("#currency-history-chart");
    if (!chart) return;
    if (!window.Plotly) {
      chart.innerHTML = '<div class="currency-history-empty">Plotly is not loaded for this page.</div>';
      return;
    }
    if (payload.error) {
      chart.innerHTML = `<div class="currency-history-empty">${payload.error}</div>`;
      renderSnapshots(payload);
      return;
    }

    const traces = (payload.series || [])
      .filter((item) => (item.values || []).some((value) => value !== null && value !== undefined))
      .map((item) => ({
        x: payload.labels || [],
        y: item.values || [],
        type: "scatter",
        mode: "lines",
        name: item.code,
        line: { width: 3, shape: "spline", smoothing: 0.45 },
        hovertemplate: `<b>${item.code}</b><br>%{x}<br>€ %{y:.6f}<extra></extra>`,
      }));

    if (!traces.length) {
      chart.innerHTML = '<div class="currency-history-empty">No historical points for the current selection.</div>';
      renderSnapshots(payload);
      return;
    }

    const layout = {
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(255,255,255,0.72)",
      margin: { l: 58, r: 22, t: 18, b: 48 },
      hovermode: "x unified",
      legend: { orientation: "h", x: 0, y: -0.18 },
      xaxis: {
        gridcolor: "rgba(16, 42, 88, 0.10)",
        zeroline: false,
        automargin: true,
      },
      yaxis: {
        title: payload.metric_label || "EUR per 1 currency unit",
        gridcolor: "rgba(16, 42, 88, 0.10)",
        zeroline: false,
        automargin: true,
      },
    };

    const config = {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
    };

    window.Plotly.react(chart, traces, layout, config);
    setStatus(`Loaded ${payload.period_label || payload.period} history from ${payload.source_name || settings.sourceName || "Frankfurter"}.`, "ok");
    renderSnapshots(payload);
  }

  let currentController = null;

  function loadHistory() {
    const chart = qs("#currency-history-chart");
    if (!chart || !settings.endpoint) return;

    syncChipStates();
    const codes = selectedCodes();
    if (!codes.length) {
      setStatus("Select at least one currency.", "warn");
      chart.innerHTML = '<div class="currency-history-empty">Select one or more currencies above.</div>';
      renderSnapshots({ series: [] });
      return;
    }

    if (currentController) currentController.abort();
    currentController = new AbortController();

    const period = qs("[data-currency-period]") ? qs("[data-currency-period]").value : (settings.defaultPeriod || "90d");
    const group = qs("[data-currency-group]") ? qs("[data-currency-group]").value : "auto";
    const params = new URLSearchParams({ codes: codes.join(","), period, group });
    setStatus(`Loading ${codes.join(", ")} from ${settings.sourceName || "Frankfurter"}…`, "loading");
    chart.classList.add("is-loading");

    fetch(`${settings.endpoint}?${params.toString()}`, { signal: currentController.signal, headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) throw new Error(`History request failed (${response.status})`);
        return response.json();
      })
      .then((payload) => renderChart(payload))
      .catch((error) => {
        if (error.name === "AbortError") return;
        setStatus(error.message || "Could not load history.", "error");
        chart.innerHTML = `<div class="currency-history-empty">${error.message || "Could not load history."}</div>`;
        renderSnapshots({ series: [] });
      })
      .finally(() => chart.classList.remove("is-loading"));
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!qs("#currency-history-chart")) return;
    qsa("[data-currency-code]").forEach((input) => input.addEventListener("change", loadHistory));
    ["[data-currency-period]", "[data-currency-group]"].forEach((selector) => {
      const input = qs(selector);
      if (input) input.addEventListener("change", loadHistory);
    });
    loadHistory();
  });
})();
