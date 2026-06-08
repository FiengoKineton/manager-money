(function () {
  let currentFiles = [];
  let currentIndex = 0;
  let currentFolder = "Cedolini";

  function updateViewer() {
    const viewer = document.getElementById("file-viewer");
    const indicator = document.getElementById("file-indicator");

    if (!viewer || !indicator) return;

    if (currentFiles.length === 0) {
      viewer.src = "";
      indicator.innerText = "No files found in this folder.";
      return;
    }

    const file = currentFiles[currentIndex];
    viewer.src = `/document/${encodeURIComponent(currentFolder)}/${encodeURIComponent(file)}`;
    indicator.innerText = `File ${currentIndex + 1} of ${currentFiles.length}: ${file}`;
  }

  function loadFolder(folder) {
    currentFolder = folder;

    const label = document.getElementById("current-folder-label");
    if (label) label.innerText = folder;

    fetch(`/api/files/${encodeURIComponent(folder)}`)
      .then((response) => response.json())
      .then((data) => {
        currentFiles = data.files || [];
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
