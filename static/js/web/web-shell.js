/* Single desktop/local shell. No phone/web runtime switching. */
(function () {
  function syncWebShell() {
    document.documentElement.classList.add("web-shell-active");
    if (document.body) document.body.classList.add("web-shell-active");
  }

  document.addEventListener("DOMContentLoaded", syncWebShell);
  window.addEventListener("pageshow", syncWebShell);
  syncWebShell();
})();
