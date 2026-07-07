(function () {
  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    var shell = document.querySelector('[data-command-palette]');
    if (!shell) return;
    var input = shell.querySelector('[data-command-palette-input]');
    var items = Array.prototype.slice.call(shell.querySelectorAll('[data-command-item]'));
    var searchValue = shell.querySelector('[data-command-palette-search-value]');

    function visibleItems() {
      return items.filter(function (item) { return item.style.display !== 'none'; });
    }

    function openPalette() {
      shell.hidden = false;
      shell.setAttribute('aria-hidden', 'false');
      document.documentElement.classList.add('command-palette-open');
      if (input) {
        input.value = '';
        filter('');
        setTimeout(function () { input.focus(); }, 25);
      }
    }

    function closePalette() {
      shell.hidden = true;
      shell.setAttribute('aria-hidden', 'true');
      document.documentElement.classList.remove('command-palette-open');
    }

    function filter(query) {
      var q = String(query || '').trim().toLowerCase();
      items.forEach(function (item) {
        var text = (item.textContent || '') + ' ' + (item.getAttribute('data-keywords') || '');
        var match = !q || text.toLowerCase().indexOf(q) !== -1;
        item.style.display = match ? '' : 'none';
      });
      if (searchValue) searchValue.value = String(query || '').trim();
    }

    document.addEventListener('keydown', function (event) {
      var key = String(event.key || '').toLowerCase();
      if ((event.ctrlKey || event.metaKey) && key === 'k') {
        event.preventDefault();
        openPalette();
        return;
      }
      if (event.key === 'Escape' && !shell.hidden) {
        event.preventDefault();
        closePalette();
        return;
      }
      if (event.key === 'Enter' && !shell.hidden && document.activeElement === input) {
        var first = visibleItems()[0];
        if (first) {
          event.preventDefault();
          window.location.href = first.href;
        }
      }
    });

    document.querySelectorAll('[data-command-palette-open]').forEach(function (button) {
      button.addEventListener('click', openPalette);
    });
    shell.querySelectorAll('[data-command-palette-close]').forEach(function (button) {
      button.addEventListener('click', closePalette);
    });
    shell.addEventListener('click', function (event) {
      if (event.target === shell) closePalette();
    });
    if (input) {
      input.addEventListener('input', function () { filter(input.value); });
    }
  });
})();
