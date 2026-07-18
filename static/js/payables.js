document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-dialog-open]').forEach((button) => button.addEventListener('click', () => document.getElementById(button.dataset.dialogOpen)?.showModal()));
  document.querySelectorAll('[data-dialog-close]').forEach((button) => button.addEventListener('click', () => button.closest('dialog')?.close()));
  document.querySelectorAll('[data-add-item]').forEach((button) => button.addEventListener('click', () => {
    const table = button.closest('form').querySelector('[data-items-table]');
    const row = document.createElement('div'); row.className='payable-item-row';
    row.innerHTML='<input name="item_name" placeholder="Item"><input type="number" step="0.01" name="item_quantity" value="1" placeholder="Qty"><input type="number" step="0.01" name="item_unit_value" placeholder="Unit value"><button type="button" data-remove-item>×</button>';
    table.appendChild(row);
  }));
  document.addEventListener('click', (event) => { if (event.target.matches('[data-remove-item]')) event.target.closest('.payable-item-row')?.remove(); });
});
