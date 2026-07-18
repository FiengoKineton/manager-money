(function () {
  const TITLE_RE = /^(add|create|new)\b/i;

  function directHeading(panel) {
    return panel.querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > .panel-header h1, :scope > .panel-header h2, :scope > .panel-header h3, :scope > header h1, :scope > header h2, :scope > header h3');
  }

  function eligible(panel) {
    if (!panel || panel.closest('dialog') || panel.matches('[data-create-panel-ignore]')) return false;
    if (!panel.querySelector('form')) return false;
    const heading = directHeading(panel);
    if (!heading || !TITLE_RE.test((heading.textContent || '').trim())) return false;
    if (panel.closest('.entity-detail-dialog, .transaction-detail-page, .auth-shell, .onboarding-shell')) return false;
    return true;
  }

  function transform(panel, index) {
    const heading = directHeading(panel);
    const label = (heading.textContent || 'Create item').trim();
    const id = `auto-create-dialog-${index}`;
    const launcher = document.createElement('button');
    launcher.type = 'button';
    launcher.className = 'primary-btn auto-create-launcher';
    launcher.textContent = `+ ${label}`;
    launcher.setAttribute('aria-haspopup', 'dialog');
    launcher.setAttribute('aria-controls', id);

    const dialog = document.createElement('dialog');
    dialog.id = id;
    dialog.className = 'create-entity-dialog';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'dialog-close create-dialog-close';
    close.setAttribute('aria-label', 'Close');
    close.textContent = '×';

    panel.parentNode.insertBefore(launcher, panel);
    panel.parentNode.insertBefore(dialog, panel);
    dialog.appendChild(close);
    dialog.appendChild(panel);

    launcher.addEventListener('click', () => dialog.showModal());
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    const endpoint = document.body?.dataset?.pageEndpoint || '';
    if (/^(transactions\.add_transaction|auth\.|onboarding)/.test(endpoint)) return;

    const candidates = Array.from(document.querySelectorAll('main .form-section, main .panel-card'));
    candidates.filter(eligible).forEach(transform);
  });
})();
