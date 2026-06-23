(function () {
  function openDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "open");
    document.body.classList.add("mm-modal-open");
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
    if (!document.querySelector("dialog.mm-modal[open]")) {
      document.body.classList.remove("mm-modal-open");
    }
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function getCards(deck) {
    return Array.from(deck.querySelectorAll(".wallet-card-vivid"));
  }

  function activeIndex(deck) {
    const cards = getCards(deck);
    if (!cards.length) return 0;
    const raw = Number.parseInt(deck.dataset.activeIndex || "", 10);
    if (Number.isFinite(raw)) return clamp(raw, 0, cards.length - 1);
    const selected = cards.findIndex((card) => card.classList.contains("is-selected"));
    return selected >= 0 ? selected : 0;
  }

  function layoutStack(deck, index) {
    const cards = getCards(deck);
    if (!cards.length) return;

    const nextIndex = clamp(index, 0, cards.length - 1);
    deck.dataset.activeIndex = String(nextIndex);

    cards.forEach((card, cardIndex) => {
      const rel = cardIndex - nextIndex;
      const abs = Math.abs(rel);
      const direction = rel === 0 ? 0 : rel > 0 ? 1 : -1;

      let x = 0;
      let y = 0;
      let scale = 1;
      let rotate = 0;
      let opacity = 1;
      let blur = 0;
      let saturate = 1;
      let z = 100;

      if (rel === 0) {
        /* Focused card */
        x = 0;
        y = 0;
        scale = 1;
        rotate = 0;
        opacity = 1;
        blur = 0;
        saturate = 1.08;
        z = 100;
      } else if (abs === 1) {
        /*
          First peeking card.
          It is moved DOWN and SIDEWAYS so it peeks around the active card,
          not through the active card center.
        */
        x = direction * 112;
        y = 108;
        scale = 0.91;
        rotate = direction * 2.8;
        opacity = 0.86;
        blur = 0.4;
        saturate = 0.86;
        z = 30;
      } else if (abs === 2) {
        /* Second peeking card, barely visible */
        x = direction * 154;
        y = 146;
        scale = 0.84;
        rotate = direction * 4.5;
        opacity = 0.38;
        blur = 1.2;
        saturate = 0.72;
        z = 12;
      } else {
        /* Hide the rest */
        x = direction * 190;
        y = 176;
        scale = 0.78;
        rotate = direction * 6;
        opacity = 0;
        blur = 2;
        saturate = 0.65;
        z = 1;
      }

      card.style.setProperty("--stack-x", `${x}px`);
      card.style.setProperty("--stack-y", `${y}px`);
      card.style.setProperty("--stack-scale", String(scale));
      card.style.setProperty("--stack-rotate", `${rotate}deg`);
      card.style.setProperty("--stack-opacity", String(opacity));
      card.style.setProperty("--stack-blur", `${blur}px`);
      card.style.setProperty("--stack-saturate", String(saturate));
      card.style.setProperty("--stack-z", String(z));

      card.classList.toggle("is-stack-active", rel === 0);
      card.classList.toggle("is-stack-prev", rel === -1);
      card.classList.toggle("is-stack-next", rel === 1);
      card.classList.toggle("is-stack-far", abs > 2);

      card.setAttribute("aria-current", rel === 0 ? "true" : "false");
      card.tabIndex = abs <= 1 ? 0 : -1;
    });
  }

  function focusWalletCard(card) {
    if (!card) return;
    const deck = card.closest(".wallet-carousel-vertical");
    if (!deck) return;
    const cards = getCards(deck);
    const index = cards.indexOf(card);
    if (index >= 0) layoutStack(deck, index);
  }

  function wireWalletDecks() {
    document.querySelectorAll(".wallet-carousel-vertical").forEach((deck) => {
      if (deck.dataset.walletDeckWired === "true") return;
      deck.dataset.walletDeckWired = "true";

      const cards = getCards(deck);
      layoutStack(deck, activeIndex(deck));

      let wheelLocked = false;
      deck.addEventListener("wheel", (event) => {
        if (!cards.length) return;
        event.preventDefault();
        if (wheelLocked) return;
        wheelLocked = true;
        const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
        const next = activeIndex(deck) + (delta > 0 ? 1 : -1);
        layoutStack(deck, next);
        window.setTimeout(() => { wheelLocked = false; }, 230);
      }, { passive: false });

      deck.addEventListener("keydown", (event) => {
        if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(event.key)) return;
        event.preventDefault();
        const step = ["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1;
        layoutStack(deck, activeIndex(deck) + step);
      });

      cards.forEach((card, index) => {
        card.addEventListener("focus", () => layoutStack(deck, index));
        card.addEventListener("click", (event) => {
          if (!card.classList.contains("is-stack-active")) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            layoutStack(deck, index);
          }
        }, true);
      });
    });
  }

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-mm-dialog-open]");
    if (opener) {
      event.preventDefault();
      const id = opener.getAttribute("data-mm-dialog-open");
      openDialog(document.getElementById(id));
      return;
    }

    const dialog = event.target.closest("dialog.mm-modal");
    if (dialog && event.target === dialog) {
      closeDialog(dialog);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("dialog.mm-modal[open]").forEach(closeDialog);
  });

  document.addEventListener("DOMContentLoaded", () => {
    wireWalletDecks();
    document.querySelectorAll("dialog.mm-modal[data-mm-open-on-load='1']").forEach(openDialog);
  });
})();
