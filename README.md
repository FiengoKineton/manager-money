# Money Manager — Refactored Flask Version

This version keeps the original CSV-based app but reorganizes the code into a cleaner, more maintainable structure.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://localhost:5000
```

`run.py` and `app_complete.py` are also kept as compatible entry points.

## Main architectural idea

The project is split by responsibility:

```text
money_manager/
  app.py                  Flask application factory
  config/                 editable configuration only
  domain/                 shared schemas/constants/dataclasses
  repositories/           CSV and filesystem access
  services/               business rules and calculations
  utils/                  dataframe filters, stats, plots
  web/routes/             Flask pages/controllers
  web/templates/          Jinja templates

static/
  css/                    split CSS modules
  js/                     split JavaScript modules
  plots/                  generated charts

data/                     System files plus per-user CSV/JSON folders
documents/                local document folders
```

## Where to change things

| What you want to modify | File |
|---|---|
| Add/remove/rename categories | `money_manager/config/categories.py` |
| Default category shown for expense/income/investment | `money_manager/config/categories.py` → `DEFAULT_CATEGORY_BY_TYPE` |
| Default dashboard date range | `money_manager/config/finance.py` |
| Credit card due-day logic | `money_manager/config/finance.py` and `money_manager/services/transaction_service.py` |
| CSV file paths | `money_manager/config/paths.py` |
| Transaction saving/updating/deleting | `money_manager/repositories/transactions.py` |
| Recurring payment generation | `money_manager/services/recurring_service.py` |
| Pending payment execution | `money_manager/services/pending_service.py` |
| Dashboard calculations | `money_manager/services/analytics_service.py` |
| Charts | `money_manager/utils/interactive_plots.py` and `money_manager/utils/plots.py` |
| HTML pages | `money_manager/web/templates/` |
| CSS styling | `static/css/` |
| JavaScript behavior | `static/js/` |

## Category defaults

The old app selected the first alphabetical category because the `<select>` did not explicitly set a selected option. Now defaults are controlled here:

```python
DEFAULT_CATEGORY_BY_TYPE = {
    "expense": "Groceries",
    "income": "Salary",
    "investment": "Deposit",
}
```

Change only that dictionary if you want a different default.

## CSS organization

`static/css/app.css` imports all smaller CSS files:

```text
base.css
layout.css
components/buttons.css
components/cards.css
components/forms.css
components/tables.css
components/charts.css
pages/dashboard.css
pages/analysis.css
pages/pending.css
pages/documents.css
```

This avoids one huge `style.css`. A small `static/style.css` remains only for backward compatibility and imports the new CSS entry point.

## Notes

- The data remains stored in CSV/JSON files under `data/users/{user_id}/`.
- Generated plots are stored per-user and served through protected routes.
- Local documents go inside `documents/Cedolini/` or `documents/Tasse - Detrazioni Fiscali/`.
- The app uses an application factory (`create_app`) so it is easier to test and deploy later.


## Added modules: Sparagnat e Fottut and Debts

### Sparagnat e Fottut
Use this page for money movements that should not change the official transaction ledger:

- **saved_expense**: an expense you would have paid, but someone else paid for you;
- **cash_collected**: physical cash you received/collected over time.

Data is stored in the current user sparagnat CSV. The page compares official net balance with a hypothetical balance: `current net - saved expenses`.

Code ownership:

- `money_manager/repositories/sparagnat.py` handles CSV persistence;
- `money_manager/services/sparagnat_service.py` handles totals, filtering, and net comparison;
- `money_manager/web/routes/sparagnat.py` handles HTTP routes;
- `money_manager/web/templates/sparagnat.html` handles the page layout;
- `static/css/pages/sparagnat.css` handles the page style.

### Debts
Use this page to track active debts, register full or partial payments, and create instalment rules. Payments are saved as normal expense transactions with category `Debt`, so they affect the dashboard net balance.

Data is stored in:

- the current user debts CSV;
- the current user debt rules CSV;
- generated pending instalments continue to use the current user pending CSV with `source=debt`.

Code ownership:

- `money_manager/repositories/debts.py` handles debts and debt-rule persistence;
- `money_manager/services/debt_service.py` handles the debt lifecycle, payment registration, remaining balance, and rule generation;
- `money_manager/web/routes/debts.py` handles HTTP routes;
- `money_manager/web/templates/debts.html` handles the page layout;
- `static/css/pages/debts.css` and `static/js/debts.js` handle page-specific UI behavior.

The CSV helper now migrates headers automatically when new fields are added, so old data files are preserved.

## UI redesign and new overview layer

The home route `/` is now a high-level command dashboard. The old detailed transaction dashboard still exists at `/dashboard`.

The navigation is grouped by role instead of being one long horizontal list:

```text
Home
  Overview
  Transactions Dashboard

Planning
  Pending & Recurring
  Debts

Support
  Sparagnat e Fottut
  Parent Support

Reports
  Analysis
  Forecast
  Documents
```

## Design system folder

The visual design is now separated from page-specific CSS:

```text
static/design/
  tokens.css          colors, radius, shadows, typography variables
  shell.css           sidebar, topbar, app shell, layout foundation
  compositions.css    reusable grids, KPI cards, metric blocks
```

Page CSS remains in:

```text
static/css/pages/
```

This means global design changes should usually be made in `static/design/`, while individual page tweaks should stay in the page file.

## Parent Support page

A new page was added at `/parents`.

Use it to track money or support your parents give you without mixing it into official income:

- **Money given to me**: direct cash or transfer;
- **Expense covered for me**: fuel, rent, bills, groceries, university, phone, etc.

Data is stored in:

```text
current user parent_support.csv
```

Code ownership:

- `money_manager/repositories/parent_support.py` handles CSV persistence;
- `money_manager/services/parent_support_service.py` handles filtering and totals;
- `money_manager/web/routes/parent_support.py` handles the web page;
- `money_manager/web/templates/parent_support.html` handles the layout;
- `static/css/pages/parent_support.css` handles page-specific design.

Categories for this page are configured in:

```text
money_manager/config/categories.py
```

Look for:

```python
PARENT_SUPPORT_CATEGORIES
DEFAULT_PARENT_SUPPORT_CATEGORY
```

## Separate liquid accounts

The app still uses the three main operation files as the source of truth:

```text
current user expenses.csv
current user incomes.csv
current user investments.csv
```

The `account` column and clear category aliases route movements into separated liquid-account analysis. A movement can affect both ledgers when that is what happened in real life: for example, an expense categorized as `Pre-paid card` reduces the tracked main net and also increases the Pre-paid card balance. This prevents visible liquidity from being overstated.

Configured separated accounts:

- `Cash Flow`
- `Pre-paid card`
- `Other account` including Ticket Restaurant aliases

Only account-only cleanup rows are excluded from the main tracked net. Those rows are generated by the cleanup form to reconcile a separate liquid account to the real amount you have.

Recurring rules also have an `account` field now, so a monthly Ticket Restaurant top-up can be created as a recurring income assigned to `Ticket Restaurant`.

## Latest UI polish layer

This version keeps the same accounting logic as the previous accounts update, but improves the presentation and display helpers:

- `/` now includes a cleaner liquidity snapshot above the KPI cards.
- Separate accounts now show balance tone, last movement, income/outflow movement counts, and a small balance-share bar.
- `/pending` now has a stronger planning header with quick insight cards for expected outflow, expected income, next pending date, and auxiliary-account pending impact.
- Recurring rules are ordered by next due date and show monthly/yearly equivalent cost, account label, next payment, and auxiliary-account badges.
- Pending payments remain grouped with pending first and executed below, but now use card rows instead of a cramped table.
- Shared focus/hover states were added for better keyboard usability and clearer interaction feedback.

The data model is unchanged: `expenses.csv`, `incomes.csv`, and `investments.csv` remain the main files for ordinary movements; extra CSV files are only for modules such as recurring rules, pending payments, debts, Sparagnat e Fottut, and parent support.

## Liquid account analysis update

This version keeps the same CSV-first logic, but improves the separated account layer:

- Added `/accounts` as a dedicated page for the three separated liquid accounts.
- Added individual account paths:
  - `/accounts/cash_flow`
  - `/accounts/ticket_restaurant`
  - `/accounts/pre_paid_card`
- Each individual account page shows:
  - current balance;
  - total in;
  - total out;
  - net movement;
  - monthly in/out plot;
  - category split;
  - transaction list for that account.
- The Overview page now links directly to the account analysis pages and no longer shows the old technical CSV/source boxes.
- `sparagnat_fottut.csv` cash-collected rows are now counted as positive Cash Flow movements.
- Blank-account expenses categorized as `Pre-paid card` are treated as pre-paid card top-ups, so they increase the Pre-paid card balance instead of disappearing from the separated account view.

Important routing rule:

- Explicit `account` values still have priority.
- If `account` is empty, clear categories such as `Cash`, `Ticket Restaurant`, or `Pre-paid card` are used as account hints.
- A blank-account expense with category `Pre-paid card` is interpreted as a transfer/top-up into the pre-paid card account.

## v4 UI and liquid-account update

This version keeps the same CSV-first logic from v3, but improves the UI and the liquid-account workflow:

- The Overview page now puts the two main numbers first: **Main available** and **Visible liquidity**. Secondary values such as committed money, income, expenses, net balance and investments are shown below in smaller cards.
- Transaction forms now use a clearer account selector:
  - blank / Main bank account = main bank flow;
  - Cash Flow = separate cash balance;
  - Pre-paid card = separate pre-paid card balance;
  - Other account = generic external liquid account, including Ticket Restaurant aliases;
  - Credit card = creates a pending credit-card payment that later impacts the main account.
- Separate liquid accounts are matched either by the `account` column or, if that is blank, by clear category/sub-category aliases such as `Pre-paid card`, `Cash`, or `Ticket Restaurant`.
- Custom liquid accounts can be added from `/accounts`. They are saved in `the current user accounts.json` and immediately become available in selectors and analysis pages.
- Each liquid account detail page has a **Clean up balance** form. Example: if Cash Flow shows €1000 but you actually have €150, enter 150 and the app creates an account-only expense of €850 tagged as `Account cleanup`. It does not affect the tracked main net, dashboard totals, Sparagnat current net, or main category charts.
- `sparagnat_fottut.csv` cash-collected entries continue to increase the Cash Flow account.

## v5 net-balance consistency fix

The dashboard, Overview page, and Sparagnat e Fottut now use the same tracked-net calculation. This fixes the previous mismatch where the Overview/Dashboard net could be higher because liquid-account-routed rows were removed from the main total.

Current rule:

- ordinary transaction rows from `expenses.csv`, `incomes.csv`, and `investments.csv` affect the tracked net;
- liquid-account analysis can also read those same rows as account movements;
- `Account cleanup` rows tagged to a liquid account are account-only reconciliation rows and are excluded from the tracked net.

The Overview totals are also filtered to the configured default date range, matching the Dashboard and Sparagnat current-net calculation.

## v6 UI and Pending/Recurring polish

- The big Overview card now shows **Net balance** instead of Main available, so it matches the current net used in Sparagnat e Fottut.
- The small Tracked Net card was removed, leaving five supporting metric cards below the two large cards.
- Pending payment rows now have a compact delete icon on the right-side action rail.
- Recurring rules now use compact icon actions: green save/update at the top of the rail and red delete at the bottom.
- Delete actions ask for confirmation before removing the row from the pending or recurring CSV.

## Desktop / local launcher

### Normal Windows start (no terminal)

Double-click:

```text
MoneyManager.vbs
```

The VBScript starts the Python launcher with a hidden window style. The launcher then:

1. locates or remembers the repository path;
2. keeps launcher configuration and browser state under `%LOCALAPPDATA%\MoneyManagerLauncher`;
3. preserves the configured `MoneyManagerData` folder;
4. applies any staged update before server startup;
5. creates/updates `.venv` without opening helper consoles;
6. starts the server with `pythonw.exe` and hidden subprocess flags;
7. waits for `/system/ready`, the root route, and the favicon asset;
8. opens Microsoft Edge with `--app=<url> --start-maximized`, or Google Chrome when Edge is unavailable;
9. falls back to the system browser only when neither app-mode browser is installed;
10. finds the new browser window by its process tree, maximizes it, and brings it to the foreground.

Running the launcher again does not create another server or app window. The second launcher detects the existing Windows mutex and focuses the existing Money Manager window.

Closing the managed Edge/Chrome app window stops the local server. In system-browser fallback mode, window-close detection is not reliable, so use the diagnostic launcher and `Ctrl+C` when a manual stop is needed.

### Branded desktop shortcut

Double-click once:

```text
CreateMoneyManagerShortcut.vbs
```

It creates `Money Manager.lnk` on the Windows Desktop. The shortcut opens `MoneyManager.vbs` through `wscript.exe` and uses:

```text
static\icons\money-manager.ico
```

The ICO contains 16, 24, 32, 48, 64, 128, and 256 pixel variants. A `.vbs` file itself uses the Windows script-host icon, so the generated `.lnk` is the reliable way to display the Money Manager icon before an optional executable is built.

### Diagnostic console mode

Double-click:

```text
MoneyManagerConsole.bat
```

This keeps a visible console and supports the same portable project-path lookup. It may be renamed or copied outside the repository. Additional launcher arguments can be appended, for example:

```bat
MoneyManagerConsole.bat --port 5010
MoneyManagerConsole.bat --default-browser
```

Direct diagnostic startup is also available:

```bash
python launcher.py --console
```

Direct development server startup remains unchanged:

```bash
python run_money_manager.py
python run_money_manager.py --no-browser
python run_money_manager.py --flask-dev-server
```

### Portable repository lookup

`MoneyManager.vbs` and `MoneyManagerConsole.bat` can be renamed or moved outside the repository. They search the script/current folder and parent folders, the `MONEY_MANAGER_PROJECT_DIR` environment variable, and the remembered path. When no valid repository is found, the VBS shows a folder-selection dialog and the batch launcher asks for a path.

The selected project and data paths are stored outside the source repository:

```text
%LOCALAPPDATA%\MoneyManagerLauncher\config.json
```

Paths containing spaces are passed as quoted arguments. A valid project must contain:

```text
launcher.py
run_money_manager.py
requirements.txt
money_manager\app.py
```

### Runtime files and logs

Device-specific launcher files are kept outside the source tree:

```text
%LOCALAPPDATA%\MoneyManagerLauncher\runtime.json
%LOCALAPPDATA%\MoneyManagerLauncher\environment-<project-hash>.json
%LOCALAPPDATA%\MoneyManagerLauncher\browser-profile-<project-hash>\
%LOCALAPPDATA%\MoneyManagerLauncher\launcher_bootstrap.log
```

The virtual environment remains in `.venv/` because it belongs to the extracted code installation. Existing user data, database/configuration files, update packages, backups, and server logs remain in the configured `MoneyManagerData` folder. The launcher does not migrate or rename them.

Server output is written to:

```text
<MoneyManagerData>\logs\launcher_latest.log
```

### Coordinated restart and updates

The Updates page includes **Restart app now** when the server is managed by the desktop launcher. Restart performs the following sequence:

1. the web route sends an authenticated loopback command to the supervising launcher;
2. the current page switches to a restart/recovery screen;
3. the launcher asks Waitress/Werkzeug to close, with terminate/kill only as a fallback;
4. any staged update or rollback is applied;
5. requirements are rechecked;
6. the replacement server starts on the same host/port when possible;
7. the restart page detects the new server instance and reconnects automatically;
8. the existing app-mode window is maximized and focused again.

If the original port cannot be reused, the launcher selects the next available port, closes the old managed browser process tree, and opens one replacement app window at the new URL. Restart failures show a Windows recovery message and leave details in the launcher/server logs; user data is not moved or deleted.

### Favicon and browser-window icon

All active base, login, registration, recovery, unlock, and restart templates declare the ICO, SVG, PNG touch icon, and web manifest through absolute Flask static URLs. `/favicon.ico` is also served directly, so nested routes do not depend on relative paths.

Edge and Chrome ultimately control the taskbar icon of an app-mode window. The dedicated browser profile and page favicon provide the closest reliable site-branded result, but some browser/Windows versions may temporarily show or cache the Edge/Chrome icon. The generated Desktop shortcut and optional PyInstaller executable use the project ICO directly.

### Optional executable build

On Windows, install PyInstaller and run:

```bash
python -m pip install pyinstaller
python build_launcher_exe.py
```

The script builds two branded executables under `dist/`:

```text
MoneyManagerLauncher.exe   (windowed, no console)
MoneyManagerConsole.exe    (diagnostic console)
```

Both locate/remember the repository through the same AppData configuration and use `static\icons\money-manager.ico`.
