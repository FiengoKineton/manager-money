# Performance patch notes

This patch targets the slow request paths that were making the app feel stuck or causing 504 timeouts.

## Changed

- Transactions page now renders only the first page of rows in the initial HTML.
- Added `GET /transactions/page` to fetch the next transaction slice on demand.
- Removed the old hidden full transaction table/card rendering that duplicated all remaining rows for desktop and phone.
- Account integrity checks no longer run during normal `/accounts` page rendering.
- Added `GET /accounts/integrity.json` for explicit/lazy integrity loading.
- Dashboard/account automatic maintenance now runs in a throttled per-user background thread instead of blocking GET requests.
- Topbar net is no longer calculated inside the global template context processor; it is fetched after first paint from `GET /api/topbar-summary`.
- `load_all()` now computes `signed_amount` with a vectorized Pandas operation instead of row-wise `.apply()`.

## Security model

- Disk data remains encrypted at rest through the existing secure storage layer.
- Lazy endpoints remain same-origin authenticated Flask routes.
- Topbar lazy loading does not reveal sensitive values when privacy masking is active.
- Background maintenance runs under the authenticated user context via `using_user(user_id)`.

## Files changed

- `money_manager/web/routes/core/transactions.py`
- `money_manager/web/routes/core/dashboard.py`
- `money_manager/web/routes/accounts/accounts.py`
- `money_manager/web/context.py`
- `money_manager/repositories/transactions.py`
- `money_manager/web/templates/base.html`
- `money_manager/web/templates/core/transactions.html`
- `money_manager/web/templates/transactions.html`
- `money_manager/web/templates/core/_transaction_macros.html`
- `money_manager/web/templates/core/_transaction_desktop_rows.html`
- `money_manager/web/templates/core/_transaction_phone_cards.html`
- `static/js/dashboard.js`
- `static/js/shared/performance-lazy.js`
