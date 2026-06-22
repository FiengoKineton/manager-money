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

This repo can now be started in two ways: directly from a terminal or through the Windows launcher.

### Run from terminal

From the repo root:

```bash
python -m pip install -r requirements.txt
python run_money_manager.py
```

The app starts on:

```text
http://127.0.0.1:5000
```

`run_money_manager.py` resolves the repo path from its own file location, so it can also be called from another directory:

```bash
python C:\path\to\manager-money\run_money_manager.py
```

By default it opens the browser automatically. To start the server without opening the browser:

```bash
python run_money_manager.py --no-browser
```

When using this direct terminal mode, stop the app with `Ctrl+C` in the terminal.

### Run with the Windows launcher

Double-click:

```text
launcher.bat
```

The launcher will:

- find the project folder;
- check that Python is available;
- create `.venv` inside the repo if it is missing;
- install `requirements.txt` inside `.venv` only when needed;
- store install status in `.launcher_state.json`;
- start the app with the `.venv` Python;
- open Money Manager at `http://127.0.0.1:5000`;
- open the terminal minimized so it does not cover the desktop.

The launcher opens Money Manager in a dedicated Edge/Chrome app-style window when Edge or Chrome is available. Closing that browser app window stops the local server automatically, so it does not remain open in the terminal.

No global Python packages are installed.

### Moving or renaming `launcher.bat`

You may rename `launcher.bat`, copy it to the Desktop, or move it to another folder. The batch file is only a portable bootstrap: it searches for the real Money Manager project folder and then runs `launcher.py` from that folder.

Search order:

1. the `MONEY_MANAGER_PROJECT_DIR` environment variable, if set;
2. the user-level launcher config in AppData;
3. an old `.money_manager_project_path.txt` next to the batch file, only for automatic migration;
4. the batch file folder;
5. the current terminal folder;
6. parent folders.

If the project folder is still not found, the batch file asks for the folder path once and stores it in:

```text
%LOCALAPPDATA%\MoneyManagerLauncher\config.json
```

That means copying `launcher.bat` to the Desktop no longer creates a visible `.txt` helper file on the Desktop. If an older launcher already created `.money_manager_project_path.txt`, the new launcher will migrate it into AppData and remove the old text file when the cached path is valid.

Do not rename or remove `launcher.py` inside the repo; copied `.bat` files still use that file to start the real launcher.

### Foreground/debug launcher mode

If you want to see the launcher logs in the current terminal instead of opening a minimized window, run:

```bat
launcher.bat --foreground
```

You can also run the launcher directly:

```bash
python launcher.py
```

To force the normal default browser instead of the dedicated app window:

```bash
python launcher.py --default-browser
```

In default-browser mode the server cannot reliably detect when only the browser tab/window is closed, so stop it with `Ctrl+C`.

### Where the virtual environment is created

The virtual environment is created here:

```text
.venv/
```

The browser app profile used by the launcher is created here:

```text
.launcher_browser_profile/
```

Both folders are local to the repo and ignored by git/ZIP packaging.

### Reset the local environment

Close the launcher/server window, then delete:

```text
.venv/
.launcher_state.json
.launcher_browser_profile/
```

To reset the remembered project path for a copied or moved `launcher.bat`, delete:

```text
%LOCALAPPDATA%\MoneyManagerLauncher\config.json
```

After that, run `launcher.bat` again. It will recreate the environment, reinstall the requirements if needed, and ask for the project folder again only if it cannot find it automatically.

### Build a launcher executable later

The repo includes `build_launcher_exe.py` as optional PyInstaller support. It does not include a generated `.exe`.

To build it later from the repo root:

```bash
python -m pip install pyinstaller
python build_launcher_exe.py
```

The executable will be generated under `dist/`. If the executable is moved outside the project folder, `launcher.py` is designed to ask once for the Money Manager project folder and store that path in the same AppData config used by the batch launcher:

```text
%LOCALAPPDATA%\MoneyManagerLauncher\config.json
```
