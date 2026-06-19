/* Web shell switch. Desktop keeps the existing professional UI. */
(function () {
  const webMedia = window.matchMedia("(min-width: 1121px) and (hover: hover) and (pointer: fine)");

  function syncWebShell() {
    const enabled = webMedia.matches;
    document.documentElement.classList.toggle("web-shell-active", enabled);
    if (document.body) document.body.classList.toggle("web-shell-active", enabled);
  }

  document.addEventListener("DOMContentLoaded", syncWebShell);
  window.addEventListener("pageshow", syncWebShell);
  if (webMedia.addEventListener) webMedia.addEventListener("change", syncWebShell);
})();
