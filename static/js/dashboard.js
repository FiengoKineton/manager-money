(function () {
  const interactiveSelector = "a, button, input, select, textarea, label, form, summary, details, [role='button'], .mobile-row-toggle";

  function currentUrlWithParams(root, page) {
    const base = root.dataset.pageUrl || "/transactions/page";
    const url = new URL(base, window.location.origin);
    const current = new URL(window.location.href);

    current.searchParams.forEach((value, key) => {
      if (key !== "page") url.searchParams.append(key, value);
    });
    url.searchParams.set("page", String(page));
    url.searchParams.set("page_size", String(root.dataset.pageSize || "50"));
    return url;
  }

  function updateCounters(root, shown, total) {
    root.dataset.totalCount = String(total);
    document.querySelectorAll("[data-transactions-shown-count]").forEach((node) => {
      node.textContent = String(shown);
    });
    document.querySelectorAll("[data-transactions-total-count]").forEach((node) => {
      node.textContent = String(total);
    });
  }

  function wireLazyTransactionRows(root) {
    if (!root || root.dataset.lazyRowsWired === "true") return;
    root.dataset.lazyRowsWired = "true";

    root.addEventListener("click", (event) => {
      const row = event.target.closest(".clickable-row");
      if (!row || !root.contains(row)) return;
      if (event.target.closest(interactiveSelector)) return;
      const href = row.dataset.href;
      if (href) window.location.href = href;
    });
  }

  async function loadNextTransactions(root, button) {
    if (!root || !button || button.disabled) return;

    const nextPage = Number.parseInt(root.dataset.nextPage || "2", 10) || 2;
    const url = currentUrlWithParams(root, nextPage);
    const originalText = button.textContent;

    button.disabled = true;
    button.textContent = "Loading...";

    try {
      const response = await fetch(url.toString(), {
        credentials: "same-origin",
        headers: {"Accept": "application/json"},
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const payload = await response.json();
      if (!payload || payload.ok === false) throw new Error("Invalid response");

      const desktopBody = root.querySelector("[data-desktop-transactions-body]");
      const phoneList = root.querySelector("[data-phone-transactions-list]");
      if (desktopBody && payload.desktop_html) {
        desktopBody.insertAdjacentHTML("beforeend", payload.desktop_html);
      }
      if (phoneList && payload.phone_html) {
        phoneList.insertAdjacentHTML("beforeend", payload.phone_html);
      }

      root.dataset.nextPage = String(nextPage + 1);
      updateCounters(root, payload.shown_count || 0, payload.total_count || 0);

      if (!payload.has_more) {
        button.remove();
      } else {
        button.disabled = false;
        button.textContent = originalText || "Show more";
      }
    } catch (error) {
      console.error("Failed to load transactions", error);
      button.disabled = false;
      button.textContent = "Retry loading more";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-transactions-lazy-root]");
    const button = document.querySelector("[data-load-more-transactions]");
    if (!root) return;

    wireLazyTransactionRows(root);
    if (button) {
      button.addEventListener("click", () => loadNextTransactions(root, button));
    }
  });
})();
