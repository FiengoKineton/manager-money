/* Phone transaction feed enhancer.
   It only adds presentation classes and animation indexes; it does not change data or forms. */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 1120px), (hover: none) and (pointer: coarse)");

  function textFrom(node) {
    return String(node ? node.textContent || "" : "").replace(/\s+/g, " ").trim();
  }

  function amountKind(amountText, rowText) {
    const text = `${amountText} ${rowText}`.toLowerCase();
    if (/\bincome\b|salary|collected|repaid|\+\s*€|€\s*\+/.test(text)) return "income";
    if (/\bexpense\b|paid|debt|payable|spent|-\s*€|€\s*-/.test(text)) return "expense";
    return "neutral";
  }

  function enhanceCards() {
    if (!phoneMedia.matches) return;
    const rows = Array.from(document.querySelectorAll("tr.mobile-disclosure-row"));
    rows.forEach((row, index) => {
      row.style.setProperty("--phone-card-index", String(index));
      const amountNode = row.querySelector(".mobile-row-amount");
      const amount = textFrom(amountNode);
      const kind = amountKind(amount, textFrom(row));
      row.classList.toggle("phone-row-income", kind === "income");
      row.classList.toggle("phone-row-expense", kind === "expense");
      if (amountNode) {
        amountNode.classList.toggle("phone-amount-income", kind === "income");
        amountNode.classList.toggle("phone-amount-expense", kind === "expense");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => window.setTimeout(enhanceCards, 80));
  window.addEventListener("pageshow", () => window.setTimeout(enhanceCards, 80));
  if (phoneMedia.addEventListener) phoneMedia.addEventListener("change", enhanceCards);
})();
