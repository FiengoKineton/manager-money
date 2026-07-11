# Adaptive navigation cache

The application now uses two complementary cache layers:

1. **Calculation/data cache** — encrypted-source summaries and service results persist between launches and remain valid through source fingerprints, dependency tags, application versions, and TTLs.
2. **Rendered-page cache** — safe authenticated GET pages are kept in bounded process memory after rendering. The browser prepares likely next pages in the background, so a later click can return the complete HTML document without rerunning the route or template.

## Request flow

- The requested page always has priority. On a miss, it renders normally and is stored.
- After first paint, `/api/performance/navigation-plan` returns a server-approved list of safe pages.
- Pages are warmed sequentially, in small waves, using `X-MoneyManager-Warmup: 1`.
- A real click cancels background work. If the exact page is already being prepared, it briefly joins that work instead of starting a duplicate calculation.
- Automatic recurring/debt/credit maintenance is skipped during warm-up requests, so preparation remains read-only.

## Adaptive order

The initial priority is Dashboard, Accounts, Transactions, Calendar, Pending, Analysis, and then less common pages. Every real visit updates a per-user usage profile in:

`MoneyManagerData/cache/users/<user>/navigation_usage.json`

Visit frequency, recent usage, and recency gradually reorder the warm-up plan.

## Selective invalidation

Each page declares the data tags it depends on. A write to categories, for example, invalidates Dashboard/Transactions/Analysis pages but does not discard Accounts or Calendar pages that do not depend on categories. Endpoint revision tokens tell the browser exactly which pages need warming again.

## Safety and limits

- Rendered HTML is never written to disk or browser storage.
- Entries are isolated by user, endpoint, path, and query string.
- Responses remain `Cache-Control: no-store, private`.
- Session-changing responses and transient flash-state pages are not cached.
- Default limits: 64 pages, 48 MB total, 4 MB per page, 10-minute TTL.
- The persistent calculation cache is preserved at startup by default. Set `MONEY_MANAGER_CLEAR_CACHE_ON_START=1` only for deliberate cold-start troubleshooting.

## Optional environment controls

- `MONEY_MANAGER_ADAPTIVE_PAGE_CACHE=0`
- `MONEY_MANAGER_PAGE_CACHE_ENTRIES=64`
- `MONEY_MANAGER_PAGE_CACHE_BYTES=50331648`
- `MONEY_MANAGER_PAGE_CACHE_ENTRY_BYTES=4194304`
- `MONEY_MANAGER_PAGE_CACHE_TTL_SECONDS=600`
- `MONEY_MANAGER_BACKGROUND_WARM_LIMIT=32`
