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

## 2026-07-03 hotfix: navigation and config hot paths

This hotfix keeps the app logic and route structure unchanged, but removes extra work that happened during normal navigation.

- Disabled full-document hover/focus/touch prefetch by default in `static/js/shared/instant-nav.js`. The transition animation remains, but the browser no longer starts expensive Flask page requests before the user clicks.
- Added a server-side 204 guard for browser `prefetch`/`prerender` document requests in `money_manager/app.py`, registered before blueprints so auth/onboarding guards do not repair or decrypt data for speculative requests.
- Added short sessionStorage caching, idle scheduling, and a timeout for the topbar summary fetch in `static/js/shared/performance-lazy.js`.
- Added a stat-keyed in-process cache around `load_user_config()` so repeated encrypted JSON config loads avoid repeated decrypt/parse/deep-merge work until the file changes.
- Added request-local account/payment-method lookup snapshots so forms, sidebars, and transaction rows do not rebuild alias/id maps repeatedly in the same request.
- Bumped the script query strings in `base.html` so browsers use the updated JavaScript immediately.

These changes target overfetching/over-eager preparation and repeated config lookup work; they do not change transaction calculations, schemas, routes, or page-level business behavior.
