(function () {
  const form = document.querySelector('[data-bonifico-form]');
  if (!form) return;

  const contacts = Array.isArray(window.moneyManagerBonificoContacts) ? window.moneyManagerBonificoContacts : [];
  const byId = new Map(contacts.map((contact) => [String(contact.id || ''), contact]));
  const select = document.getElementById('bonifico-contact-select');
  const manualName = document.getElementById('bonifico-manual-name');
  const preview = document.getElementById('bonifico-contact-preview');

  function setText(selector, value) {
    const node = preview ? preview.querySelector(selector) : null;
    if (node) node.textContent = value || '—';
  }

  function setValueIfPresent(id, value, force) {
    const node = document.getElementById(id);
    if (!node) return;
    if (force || !node.value || node.dataset.bonificoAutofilled === '1') {
      node.value = value || '';
      node.dataset.bonificoAutofilled = value ? '1' : '';
      node.dispatchEvent(new Event('change', { bubbles: true }));
      node.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  function setCategory(value) {
    const category = document.getElementById('bonifico-category-select');
    if (!category || !value) return;
    const exact = Array.from(category.options).find((option) => option.value === value);
    if (exact) {
      category.value = value;
      category.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  function formatMoney(value) {
    const number = Number(value || 0);
    return number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function selectedAccountMeta() {
    const accountSelect = document.getElementById('bonifico-account-select');
    if (!accountSelect) return { key: 'main_bank', kind: 'main', paymentMode: 'main_net', label: 'Main bank account' };
    const selected = accountSelect.options[accountSelect.selectedIndex];
    return {
      key: (selected && selected.dataset.key) || 'main_bank',
      kind: (selected && selected.dataset.kind) || 'main',
      paymentMode: (selected && selected.dataset.paymentMode) || 'main_net',
      label: (selected && (selected.dataset.displayLabel || selected.textContent) ? (selected.dataset.displayLabel || selected.textContent).trim() : 'Main bank account'),
    };
  }

  function refreshPaymentPanel() {
    const panel = document.getElementById('account-payment-panel');
    const methodSelect = document.getElementById('account-payment-method');
    const insufficientPanel = document.getElementById('account-insufficient-panel');
    const balances = window.moneyManagerAccountBalances || {};
    const meta = selectedAccountMeta();
    const isBalanceAccount = meta.paymentMode === 'tracked_balance' || (meta.kind === 'auxiliary' && meta.paymentMode !== 'main_net' && meta.paymentMode !== 'credit_statement');

    if (!panel) return;
    panel.hidden = !isBalanceAccount;

    document.querySelectorAll('[data-balance-account-name]').forEach((node) => { node.textContent = meta.label; });
    document.querySelectorAll('[data-selected-account-balance]').forEach((node) => { node.textContent = formatMoney(balances[meta.key] || 0); });

    if (insufficientPanel && methodSelect) {
      insufficientPanel.hidden = !isBalanceAccount || methodSelect.value !== 'balance';
    }
  }

  function refreshPreview() {
    if (!select || !preview) return;
    const contact = byId.get(String(select.value || ''));
    if (!contact) {
      preview.hidden = true;
      return;
    }
    preview.hidden = false;
    setText('[data-contact-name]', contact.display_name || '—');
    setText('[data-contact-iban]', contact.iban_list_value || contact.iban_display || '—');
    setText('[data-contact-bic]', contact.bic_swift || '—');
    setText('[data-contact-bank]', contact.bank_name || '—');
  }

  function selectedTargetOption(type) {
    const id = type === 'debt' ? 'bonifico-debt-select' : 'bonifico-payable-select';
    const targetSelect = document.getElementById(id);
    if (!targetSelect || !targetSelect.value) return null;
    return targetSelect.options[targetSelect.selectedIndex] || null;
  }

  function applyLinkedTarget(type, force) {
    const option = selectedTargetOption(type);
    if (!option) return;

    const contactId = option.dataset.contactId || '';
    const recipient = option.dataset.recipient || '';

    setValueIfPresent('bonifico-amount-input', option.dataset.amount || '', force);
    setCategory(option.dataset.category || '');
    setValueIfPresent('bonifico-sub-category-input', option.dataset.subCategory || '', force);
    setValueIfPresent('bonifico-reference-input', option.dataset.reference || '', force);
    setValueIfPresent('bonifico-description-input', option.dataset.description || '', force);

    if (select && contactId) {
      select.value = contactId;
      if (manualName) manualName.value = '';
      refreshPreview();
    } else if (manualName && recipient && (!manualName.value || manualName.dataset.bonificoAutofilled === '1')) {
      if (select) select.value = '';
      manualName.value = recipient;
      manualName.dataset.bonificoAutofilled = '1';
      refreshPreview();
    }
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(String(value || ''));
    return String(value || '').replace(/([\"'\\])/g, '\\$1');
  }

  function checkedDebtRows() {
    return Array.from(document.querySelectorAll('[data-bonifico-debt-checkbox]:checked')).map((checkbox) => {
      const id = checkbox.dataset.debtId || checkbox.value || '';
      const amount = document.querySelector(`[data-bonifico-debt-amount][data-debt-id="${cssEscape(id)}"]`);
      return { checkbox, amount };
    });
  }

  function syncDebtAmountInputs() {
    document.querySelectorAll('[data-bonifico-debt-checkbox]').forEach((checkbox) => {
      const id = checkbox.dataset.debtId || checkbox.value || '';
      const amount = document.querySelector(`[data-bonifico-debt-amount][data-debt-id="${cssEscape(id)}"]`);
      if (amount) amount.disabled = !checkbox.checked;
    });
  }

  function applyMultipleDebts(force) {
    syncDebtAmountInputs();
    const rows = checkedDebtRows();
    if (!rows.length) return;

    let total = 0;
    const names = [];
    const recipients = new Set();
    const contactIds = new Set();

    rows.forEach(({ checkbox, amount }) => {
      const value = Number(amount && amount.value ? amount.value : checkbox.dataset.amount || 0);
      if (Number.isFinite(value) && value > 0) total += value;
      const label = checkbox.closest('.bonifico-debt-multi-row');
      const nameNode = label ? label.querySelector('strong') : null;
      if (nameNode && nameNode.textContent.trim()) names.push(nameNode.textContent.trim());
      if (checkbox.dataset.recipient) recipients.add(checkbox.dataset.recipient);
      if (checkbox.dataset.contactId) contactIds.add(checkbox.dataset.contactId);
    });

    setValueIfPresent('bonifico-amount-input', total ? total.toFixed(2) : '', true);
    setCategory('Debt');
    setValueIfPresent('bonifico-sub-category-input', 'Multiple debts', force);
    setValueIfPresent('bonifico-reference-input', 'Debt payments', force);
    setValueIfPresent('bonifico-description-input', names.length ? `Bonifico debt payments: ${names.join(', ')}` : 'Bonifico debt payments', force);

    if (contactIds.size === 1 && select) {
      select.value = Array.from(contactIds)[0];
      if (manualName) manualName.value = '';
      refreshPreview();
    } else if (recipients.size === 1 && manualName && (!manualName.value || manualName.dataset.bonificoAutofilled === '1')) {
      if (select) select.value = '';
      manualName.value = Array.from(recipients)[0];
      manualName.dataset.bonificoAutofilled = '1';
      refreshPreview();
    }
  }

  function refreshLinkedPaymentPanels(forceApply) {
    const typeSelect = document.getElementById('bonifico-target-type');
    const debtPanel = document.getElementById('bonifico-debt-panel');
    const debtsPanel = document.getElementById('bonifico-debts-panel');
    const payablePanel = document.getElementById('bonifico-payable-panel');
    const type = typeSelect ? typeSelect.value : 'expense';

    if (debtPanel) debtPanel.hidden = type !== 'debt';
    if (debtsPanel) debtsPanel.hidden = type !== 'debts';
    if (payablePanel) payablePanel.hidden = type !== 'payable';

    if (type === 'debt') applyLinkedTarget('debt', forceApply);
    if (type === 'debts') applyMultipleDebts(forceApply);
    if (type === 'payable') applyLinkedTarget('payable', forceApply);
  }

  function syncTargetFromCategory() {
    const category = document.getElementById('bonifico-category-select');
    const typeSelect = document.getElementById('bonifico-target-type');
    if (!category || !typeSelect) return;
    const value = String(category.value || '').trim().toLowerCase();
    if (value === 'debt' && typeSelect.value !== 'debt' && typeSelect.value !== 'debts') {
      typeSelect.value = 'debt';
      refreshLinkedPaymentPanels(true);
    } else if (value === 'payable' && typeSelect.value !== 'payable') {
      typeSelect.value = 'payable';
      refreshLinkedPaymentPanels(true);
    }
  }

  if (select) {
    select.addEventListener('change', function () {
      refreshPreview();
      if (manualName && select.value) {
        manualName.value = '';
        manualName.dataset.bonificoAutofilled = '';
      }
    });
    refreshPreview();
  }

  const accountSelect = document.getElementById('bonifico-account-select');
  if (accountSelect) accountSelect.addEventListener('change', refreshPaymentPanel);
  const methodSelect = document.getElementById('account-payment-method');
  if (methodSelect) methodSelect.addEventListener('change', refreshPaymentPanel);

  const targetTypeSelect = document.getElementById('bonifico-target-type');
  if (targetTypeSelect) targetTypeSelect.addEventListener('change', () => refreshLinkedPaymentPanels(true));

  const categorySelect = document.getElementById('bonifico-category-select');
  if (categorySelect) categorySelect.addEventListener('change', syncTargetFromCategory);

  const debtSelect = document.getElementById('bonifico-debt-select');
  if (debtSelect) debtSelect.addEventListener('change', () => applyLinkedTarget('debt', true));

  document.querySelectorAll('[data-bonifico-debt-checkbox]').forEach((checkbox) => {
    checkbox.addEventListener('change', () => applyMultipleDebts(true));
  });
  document.querySelectorAll('[data-bonifico-debt-amount]').forEach((amount) => {
    amount.addEventListener('input', () => applyMultipleDebts(true));
  });

  const payableSelect = document.getElementById('bonifico-payable-select');
  if (payableSelect) payableSelect.addEventListener('change', () => applyLinkedTarget('payable', true));

  if (manualName) {
    manualName.addEventListener('input', () => { manualName.dataset.bonificoAutofilled = ''; });
  }

  ['bonifico-amount-input', 'bonifico-sub-category-input', 'bonifico-reference-input', 'bonifico-description-input'].forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.addEventListener('input', () => { node.dataset.bonificoAutofilled = ''; });
  });

  refreshPaymentPanel();
  syncDebtAmountInputs();
  syncTargetFromCategory();
  refreshLinkedPaymentPanels(false);
})();
