(function () {
  let currentFiles = [];
  let currentIndex = 0;
  let currentFolder = "";
  let loadSequence = 0;
  let messageTimer = null;

  function previewUrl(folder, file) {
    return `/document-preview/${encodeURIComponent(folder)}/${encodeURIComponent(file)}`;
  }

  function setActiveFolder(folder) {
    document.querySelectorAll(".folder-btn[data-folder]").forEach((button) => {
      button.classList.toggle("active", button.dataset.folder === folder);
    });
  }

  function setNavigationState() {
    const disabled = currentFiles.length === 0;
    document.querySelectorAll("[data-doc-action]").forEach((button) => {
      button.disabled = disabled;
    });
  }

  function renderFileList() {
    const list = document.getElementById("document-file-list");
    if (!list) return;

    list.replaceChildren();

    if (currentFiles.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No files found in this folder.";
      list.appendChild(empty);
      return;
    }

    currentFiles.forEach((file, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `document-file-item${index === currentIndex ? " active" : ""}`;
      button.dataset.docIndex = String(index);
      button.title = file;

      const name = document.createElement("span");
      name.textContent = file;
      button.appendChild(name);

      button.addEventListener("click", () => {
        currentIndex = index;
        updateViewer();
      });

      list.appendChild(button);
    });
  }

  function updateViewer() {
    const viewer = document.getElementById("file-viewer");
    const indicator = document.getElementById("file-indicator");

    if (!viewer || !indicator) return;

    setNavigationState();

    if (currentFiles.length === 0) {
      viewer.src = "about:blank";
      indicator.textContent = "No files found in this folder.";
      renderFileList();
      return;
    }

    if (currentIndex < 0 || currentIndex >= currentFiles.length) currentIndex = 0;

    const file = currentFiles[currentIndex];
    viewer.src = previewUrl(currentFolder, file);
    indicator.textContent = `File ${currentIndex + 1} of ${currentFiles.length}: ${file}`;
    renderFileList();
  }

  async function loadFolder(folder, preferredFile) {
    if (!folder) return;

    const requestSequence = ++loadSequence;
    currentFolder = folder;
    setActiveFolder(folder);

    const label = document.getElementById("current-folder-label");
    if (label) label.textContent = folder;

    const indicator = document.getElementById("file-indicator");
    if (indicator) indicator.textContent = "Loading files...";

    try {
      const response = await fetch(`/api/files/${encodeURIComponent(folder)}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Could not load this folder.");

      const data = await response.json();
      if (requestSequence !== loadSequence) return;

      currentFiles = Array.isArray(data.files) ? data.files : [];
      const preferredIndex = preferredFile ? currentFiles.indexOf(preferredFile) : -1;
      currentIndex = preferredIndex >= 0 ? preferredIndex : 0;
      updateViewer();
    } catch (error) {
      if (requestSequence !== loadSequence) return;
      currentFiles = [];
      currentIndex = 0;
      updateViewer();
      showPageMessage(error.message || "Could not load the documents.", "error");
    }
  }

  function previousFile() {
    if (currentFiles.length === 0) return;
    currentIndex = (currentIndex - 1 + currentFiles.length) % currentFiles.length;
    updateViewer();
  }

  function nextFile() {
    if (currentFiles.length === 0) return;
    currentIndex = (currentIndex + 1) % currentFiles.length;
    updateViewer();
  }

  function showPageMessage(message, tone) {
    const element = document.getElementById("document-page-message");
    if (!element) return;

    window.clearTimeout(messageTimer);
    element.textContent = message;
    element.dataset.tone = tone || "success";
    element.hidden = false;

    messageTimer = window.setTimeout(() => {
      element.hidden = true;
      element.textContent = "";
    }, 5500);
  }

  function setUploadStatus(message, tone) {
    const status = document.getElementById("document-upload-status");
    if (!status) return;

    status.textContent = message || "";
    status.dataset.tone = tone || "error";
    status.hidden = !message;
  }

  function openUploadDialog() {
    const dialog = document.getElementById("document-upload-dialog");
    const folderSelect = document.getElementById("document-upload-folder");
    const fileInput = document.getElementById("document-upload-file");

    if (!dialog) return;
    if (folderSelect && currentFolder) folderSelect.value = currentFolder;
    setUploadStatus("");

    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }

    window.setTimeout(() => fileInput && fileInput.focus(), 0);
  }

  function closeUploadDialog() {
    const dialog = document.getElementById("document-upload-dialog");
    if (!dialog) return;

    if (typeof dialog.close === "function" && dialog.open) {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  function setUploadBusy(isBusy) {
    const submit = document.getElementById("document-upload-submit");
    const form = document.getElementById("document-upload-form");
    if (submit) {
      submit.disabled = isBusy;
      submit.textContent = isBusy ? "Saving..." : "Add document";
    }
    if (form) {
      form.querySelectorAll("input, select, [data-close-document-upload]").forEach((control) => {
        control.disabled = isBusy;
      });
    }
  }

  async function submitDocument(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const uploadUrl = form.dataset.uploadUrl;
    const fileInput = document.getElementById("document-upload-file");
    const folderSelect = document.getElementById("document-upload-folder");

    if (!uploadUrl || !fileInput || !fileInput.files || fileInput.files.length === 0) {
      setUploadStatus("Choose a document to upload.", "error");
      return;
    }

    // Capture the form payload before disabling its controls. Disabled inputs are
    // omitted from FormData, which previously removed both the folder and file.
    const formData = new FormData(form);

    setUploadStatus("");
    setUploadBusy(true);

    try {
      const response = await fetch(uploadUrl, {
        method: "POST",
        body: formData,
        headers: { Accept: "application/json" },
      });

      let data = {};
      try {
        data = await response.json();
      } catch (error) {
        data = {};
      }

      if (!response.ok || !data.ok) {
        throw new Error(data.error || "The document could not be saved.");
      }

      const savedDocument = data.document || {};
      const destinationFolder = savedDocument.folder || folderSelect.value;
      const savedFilename = savedDocument.filename || "";

      form.reset();
      updateSelectedFileName();
      closeUploadDialog();
      showPageMessage(data.message || "Document added successfully.", "success");
      await loadFolder(destinationFolder, savedFilename);
    } catch (error) {
      setUploadStatus(error.message || "The document could not be saved.", "error");
    } finally {
      setUploadBusy(false);
    }
  }

  function updateSelectedFileName() {
    const input = document.getElementById("document-upload-file");
    const label = document.getElementById("document-upload-file-name");
    if (!input || !label) return;

    const file = input.files && input.files[0];
    label.textContent = file
      ? `${file.name} · ${formatFileSize(file.size)}`
      : `Choose one of the supported files · maximum ${input.dataset.maxUploadMb || "50"} MB`;
  }

  function formatFileSize(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const layout = document.querySelector(".documents-layout[data-default-folder]");
    currentFolder = (layout && layout.dataset.defaultFolder) || "";

    document.querySelectorAll(".folder-btn[data-folder]").forEach((button) => {
      button.addEventListener("click", () => loadFolder(button.dataset.folder));
    });

    document.querySelectorAll('[data-doc-action="previous"]').forEach((button) => {
      button.addEventListener("click", previousFile);
    });

    document.querySelectorAll('[data-doc-action="next"]').forEach((button) => {
      button.addEventListener("click", nextFile);
    });

    document.querySelectorAll("[data-open-document-upload]").forEach((button) => {
      button.addEventListener("click", openUploadDialog);
    });

    document.querySelectorAll("[data-close-document-upload]").forEach((button) => {
      button.addEventListener("click", closeUploadDialog);
    });

    const form = document.getElementById("document-upload-form");
    if (form) form.addEventListener("submit", submitDocument);

    const fileInput = document.getElementById("document-upload-file");
    if (fileInput) fileInput.addEventListener("change", updateSelectedFileName);

    const dialog = document.getElementById("document-upload-dialog");
    if (dialog) {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeUploadDialog();
      });
    }

    loadFolder(currentFolder);
  });
})();
