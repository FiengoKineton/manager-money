(function () {
  let currentFiles = [];
  let currentIndex = 0;
  let currentFolder = "Cedolini";

  function previewUrl(folder, file) {
    return `/document-preview/${encodeURIComponent(folder)}/${encodeURIComponent(file)}`;
  }

  function setActiveFolder(folder) {
    document.querySelectorAll(".folder-btn[data-folder]").forEach((button) => {
      button.classList.toggle("active", button.dataset.folder === folder);
    });
  }

  function renderFileList() {
    const list = document.getElementById("document-file-list");
    if (!list) return;

    if (currentFiles.length === 0) {
      list.innerHTML = '<p class="empty">No files found in this folder.</p>';
      return;
    }

    list.innerHTML = currentFiles
      .map((file, index) => {
        const active = index === currentIndex ? " active" : "";
        return `<button type="button" class="document-file-item${active}" data-doc-index="${index}"><span>${file}</span></button>`;
      })
      .join("");

    list.querySelectorAll("[data-doc-index]").forEach((button) => {
      button.addEventListener("click", () => {
        currentIndex = Number(button.dataset.docIndex || 0);
        updateViewer();
      });
    });
  }

  function updateViewer() {
    const viewer = document.getElementById("file-viewer");
    const indicator = document.getElementById("file-indicator");

    if (!viewer || !indicator) return;

    if (currentFiles.length === 0) {
      viewer.src = "about:blank";
      indicator.innerText = "No files found in this folder.";
      renderFileList();
      return;
    }

    const file = currentFiles[currentIndex];
    viewer.src = previewUrl(currentFolder, file);
    indicator.innerText = `File ${currentIndex + 1} of ${currentFiles.length}: ${file}`;
    renderFileList();
  }

  function loadFolder(folder) {
    currentFolder = folder;
    setActiveFolder(folder);

    const label = document.getElementById("current-folder-label");
    if (label) label.innerText = folder;

    const indicator = document.getElementById("file-indicator");
    if (indicator) indicator.innerText = "Loading files...";

    fetch(`/api/files/${encodeURIComponent(folder)}`)
      .then((response) => response.json())
      .then((data) => {
        currentFiles = data.files || [];
        currentIndex = 0;
        updateViewer();
      })
      .catch(() => {
        currentFiles = [];
        currentIndex = 0;
        updateViewer();
      });
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

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".folder-btn[data-folder]").forEach((button) => {
      button.addEventListener("click", () => loadFolder(button.dataset.folder));
    });

    document.querySelectorAll('[data-doc-action="previous"]').forEach((button) => {
      button.addEventListener("click", previousFile);
    });

    document.querySelectorAll('[data-doc-action="next"]').forEach((button) => {
      button.addEventListener("click", nextFile);
    });

    loadFolder(currentFolder);
  });
})();
