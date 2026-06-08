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

data/                     CSV database files
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

- The data remains stored in CSV files under `data/`.
- Generated plots are stored in `static/plots/`.
- Local documents go inside `documents/Cedolini/` or `documents/Tasse - Detrazioni Fiscali/`.
- The app uses an application factory (`create_app`) so it is easier to test and deploy later.


## Added modules: Sparagnat e Fottut and Debts

### Sparagnat e Fottut
Use this page for money movements that should not change the official transaction ledger:

- **saved_expense**: an expense you would have paid, but someone else paid for you;
- **cash_collected**: physical cash you received/collected over time.

Data is stored in `data/sparagnat_fottut.csv`. The page compares official net balance with a hypothetical balance: `current net - saved expenses`.

Code ownership:

- `money_manager/repositories/sparagnat.py` handles CSV persistence;
- `money_manager/services/sparagnat_service.py` handles totals, filtering, and net comparison;
- `money_manager/web/routes/sparagnat.py` handles HTTP routes;
- `money_manager/web/templates/sparagnat.html` handles the page layout;
- `static/css/pages/sparagnat.css` handles the page style.

### Debts
Use this page to track active debts, register full or partial payments, and create instalment rules. Payments are saved as normal expense transactions with category `Debt`, so they affect the dashboard net balance.

Data is stored in:

- `data/debts.csv`;
- `data/debt_rules.csv`;
- generated pending instalments continue to use `data/pending.csv` with `source=debt`.

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
data/parent_support.csv
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
