/* Phone add-flow enhancer.
   Keeps the same backend form fields, but groups the normal add form into phone-first steps. */
(function () {
  const phoneMedia = window.matchMedia("(max-width: 600px) and (hover: none) and (pointer: coarse), (max-height: 520px) and (max-width: 940px) and (hover: none) and (pointer: coarse)");

  function labelText(node) {
    const label = node && node.querySelector("label");
    return String(label ? label.textContent : "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function classifyStep(field) {
    const label = labelText(field);
    if (label.includes("amount")) return ["2", "Amount"];
    if (label.includes("category") || label.includes("sub-category") || label.includes("date")) return ["1", "What"];
    if (label.includes("currency") || label.includes("account") || label.includes("payment method") || label.includes("balance account")) return ["3", "Account"];
    if (label.includes("description") || field.classList.contains("future-balance-preview")) return ["4", "Details"];
    if (field.classList.contains("normal-add-submit-row")) return ["5", "Save"];
    return ["4", "Details"];
  }

  function ensureProgress(form, stepCount) {
    if (form.querySelector(":scope > .phone-add-progress")) return;
    const progress = document.createElement("div");
    progress.className = "phone-add-progress";
    progress.innerHTML = `<strong>Phone add flow</strong><div class="phone-add-progress-dots" aria-hidden="true"></div>`;
    progress.style.setProperty("--phone-add-steps", String(stepCount));
    const dots = progress.querySelector(".phone-add-progress-dots");
    for (let i = 0; i < stepCount; i += 1) {
      const dot = document.createElement("span");
      if (i === 0) dot.className = "is-active";
      dots.appendChild(dot);
    }
    form.insertBefore(progress, form.firstElementChild);
  }

  function wrapFields(form) {
    if (!phoneMedia.matches || !form || form.dataset.phoneAddFlow === "true") return;
    form.dataset.phoneAddFlow = "true";
    const original = Array.from(form.children).filter((child) => {
      if (child.matches('input[type="hidden"], .phone-add-progress')) return false;
      return child.matches("div, section, fieldset");
    });

    const buckets = new Map();
    original.forEach((field) => {
      const [step, title] = classifyStep(field);
      const key = `${step}:${title}`;
      if (!buckets.has(key)) {
        const section = document.createElement("section");
        section.className = "phone-add-step";
        section.dataset.phoneStep = step;
        section.dataset.phoneStepTitle = `${step}. ${title}`;
        buckets.set(key, section);
      }
      const section = buckets.get(key);
      if (labelText(field).includes("amount")) section.classList.add("phone-add-primary-amount");
      section.appendChild(field);
    });

    const hiddenFields = Array.from(form.children).filter((child) => child.matches('input[type="hidden"]'));
    form.innerHTML = "";
    hiddenFields.forEach((field) => form.appendChild(field));
    const sections = Array.from(buckets.entries()).sort((a, b) => Number(a[0].split(":")[0]) - Number(b[0].split(":")[0])).map((entry) => entry[1]);
    ensureProgress(form, sections.length);
    sections.forEach((section) => form.appendChild(section));

    const dots = Array.from(form.querySelectorAll(".phone-add-progress-dots span"));
    if ("IntersectionObserver" in window && dots.length) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const step = Number(entry.target.dataset.phoneStep || 1) - 1;
          dots.forEach((dot, index) => dot.classList.toggle("is-active", index <= step));
        });
      }, { threshold: 0.42, rootMargin: "-18% 0px -52% 0px" });
      sections.forEach((section) => observer.observe(section));
    }
  }

  function enhanceAddForms() {
    if (!phoneMedia.matches) return;
    document.querySelectorAll(".normal-add-polished .transaction-form").forEach(wrapFields);
  }

  document.addEventListener("DOMContentLoaded", enhanceAddForms);
  window.addEventListener("pageshow", enhanceAddForms);
})();
