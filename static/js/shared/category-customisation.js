(function () {
  const NEW_VALUE = "__new_category__";

  function syncInlineCategoryCreate() {
    const select = document.getElementById("category-select");
    const panel = document.querySelector("[data-inline-category-fields]");
    const nameInput = document.getElementById("custom-category-name");
    const iconInput = document.getElementById("custom-category-icon");
    if (!select || !panel) return;

    const isCreating = select.value === NEW_VALUE;
    panel.hidden = !isCreating;
    panel.classList.toggle("is-visible", isCreating);
    if (nameInput) nameInput.required = isCreating;

    if (isCreating && iconInput && !iconInput.value.trim()) {
      iconInput.value = "✎";
    }
  }

  function wireInlineCategoryCreate() {
    const select = document.getElementById("category-select");
    if (!select || select.dataset.inlineCategoryWired === "true") return;
    select.dataset.inlineCategoryWired = "true";
    select.addEventListener("change", syncInlineCategoryCreate);
    syncInlineCategoryCreate();
  }

  document.addEventListener("DOMContentLoaded", wireInlineCategoryCreate);
  window.addEventListener("pageshow", wireInlineCategoryCreate);
})();
