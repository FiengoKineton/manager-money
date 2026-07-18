(function () {
  function readConfig() {
    const script = document.getElementById("category-config");
    if (!script) {
      return { categoriesByType: {}, defaultCategoryByType: {} };
    }

    try {
      return JSON.parse(script.textContent);
    } catch (error) {
      console.error("Invalid category config", error);
      return { categoriesByType: {}, defaultCategoryByType: {} };
    }
  }

  function updateCategories(config) {
    const typeSelect = document.getElementById("type-select");
    const categorySelect = document.getElementById("category-select");

    if (!typeSelect || !categorySelect) return;

    const type = typeSelect.value;
    const categories = config.categoriesByType[type] || [];
    const defaultCategory = config.defaultCategoryByType[type];

    categorySelect.innerHTML = "";

    let foundDefault = false;

    categories.forEach((category) => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category;

      if (category === defaultCategory) {
        option.selected = true;
        foundDefault = true;
      }

      categorySelect.appendChild(option);
    });

    if (!foundDefault && categorySelect.options.length > 0) {
      categorySelect.selectedIndex = 0;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const config = readConfig();
    const typeSelect = document.getElementById("type-select");

    if (typeSelect) {
      typeSelect.addEventListener("change", () => updateCategories(config));
    }

    updateCategories(config);
  });
})();

(function () {
  function refreshConnectionPanels(root) {
    const selected = root.querySelector('input[name="connection_type"]:checked');
    const value = selected ? selected.value : '';
    root.querySelectorAll('[data-connection-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.connectionPanel !== value;
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-dialog-open]').forEach((button) => {
      button.addEventListener('click', () => {
        const dialog = document.getElementById(button.dataset.dialogOpen);
        if (dialog) {
          refreshConnectionPanels(dialog);
          dialog.showModal();
        }
      });
    });
    document.querySelectorAll('[data-dialog-close]').forEach((button) => {
      button.addEventListener('click', () => button.closest('dialog')?.close());
    });
    document.querySelectorAll('.recurring-form, .entity-detail-dialog').forEach((root) => {
      root.querySelectorAll('input[name="connection_type"]').forEach((radio) => {
        radio.addEventListener('change', () => refreshConnectionPanels(root));
      });
      refreshConnectionPanels(root);
    });
  });
})();
