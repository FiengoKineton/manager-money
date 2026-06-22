# ONGOING



#### Prompt 11A — Audit account/payment usage and write the refactor map


You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 are already completed:
- Launcher exists.
- Multi-user auth/user paths exist.
- Profile/preferences exist.
- Custom categories/accounts/document types exist.
- i18n exists.
- Contacts exist.
- Bonifico exists.
- Customizable sidebar exists.
- Backup/export/import, privacy mode, and onboarding exist.

Current v10 repo context:
- account_config_service.py exists.
- account_payment_policy_service.py exists.
- account_service.py exists.
- accounts.json exists per user and is currently schema_version 2.
- There is no payment_methods.json yet.
- There is no account ledger yet.
- Transactions still use account/payment_method fields in a mixed way.
- Internal transfers still use from_account/to_account text fields.
- Profile currently stores one bank_name, iban, bic_swift, and default_main_account.
- Do not modify phone-specific UI.

Goal of this patch:
Do a safe audit and prepare the account/payment refactor plan before changing money logic.

This patch should be mostly non-invasive. Do not implement the new payment architecture yet. Do not redesign the UI yet.

Implement the following:

1. Create documentation folder/files

Create:

- docs/account_payment_terms.md
- docs/account_payment_refactor_plan.md
- docs/account_payment_migration_checklist.md

2. Define professional terminology

In docs/account_payment_terms.md, clearly define:

A. Account / Conto
A real balance container.

Examples:
- Conto Corrente Intesa
- Conto Corrente Revolut
- Cash
- PayPal Balance
- Prepaid Card Balance
- EdenRed / meal voucher balance
- Investment cash account
- Credit card liability account

B. Payment Method / Metodo di pagamento
A way to pay.

Examples:
- Debit card linked to Conto Intesa
- Credit card linked to Conto Intesa
- Bonifico from Conto Intesa
- PayPal balance
- PayPal via debit card
- PayPal via credit card
- Cash
- EdenRed

C. Funding account
The account that ultimately funds a payment.

D. Settlement account
The account used to settle delayed payments, especially credit cards.

E. Linked account
The account directly represented by a method, for example PayPal Balance or Prepaid Card Balance.

F. Dependent account
A wallet/account that depends on or is linked to another current account.

G. Current account / Conto Corrente
A main bank account that can fund cards, transfers, bills, mortgages, etc.

H. Credit liability account
A liability bucket used to track credit card purchases before settlement.

I. Ledger movement
A row that explains how a transaction affects balances.

J. Payment resolution
The result of applying a payment method rule to a transaction.

3. Audit current repo usage

Inspect the entire repo and document every meaningful use of:

- account
- account_key
- account_name_snapshot
- account_due_day_snapshot
- account_payment_method
- paypal_payment_method
- payment_method
- from_account
- to_account
- main_bank
- credit_card
- cash_flow
- paypal
- pre_paid_card
- edenred
- main_net_policy
- payment_logic
- pending credit/card logic
- internal transfers
- profile IBAN/bank fields

Search at least:

- money_manager/config/
- money_manager/domain/
- money_manager/repositories/
- money_manager/services/
- money_manager/web/routes/
- money_manager/web/templates/
- money_manager/i18n/
- data/users/*/*.json
- data/users/*/*.csv headers

4. Create an audit table

In docs/account_payment_refactor_plan.md, add a table with columns:

- File
- Function/template/section
- Current field/name
- Current meaning
- Future meaning
- Risk level: low/medium/high
- Which future prompt should handle it: 11B/11C/11D/11E/11F/11G
- Notes

Classify each usage as one of:

- real_account
- payment_method
- payment_channel_wrapper
- legacy_alias
- category_alias
- internal_transfer
- credit_settlement
- profile_bank_info
- dashboard_aggregation
- analysis_filter
- backup/schema
- i18n/UI label

5. Create migration checklist

In docs/account_payment_migration_checklist.md, list all concrete migration tasks needed later.

Include at least:

- Create payment_methods.json.
- Upgrade accounts.json to schema_version 3 while preserving legacy fields.
- Add account_ledger.csv.
- Add account_events.json.
- Add credit_settlements.csv or equivalent.
- Add payment_method_id and account_id transaction fields.
- Add ledger_group_id / transaction_uid.
- Migrate legacy account values.
- Migrate profile IBAN/bank data into accounts.
- Update internal transfers.
- Update credit settlements.
- Update transaction edit/delete logic.
- Update add transaction form.
- Update Bonifico.
- Update Payables.
- Update Recurring.
- Update Pending.
- Update Debts/Receivables/Parent Support/Expense Projects.
- Update Investments funding logic.
- Update Backup export/import.
- Update Privacy masking.
- Update Navigation/i18n labels.
- Add data integrity tools.

6. Add an optional audit script

Create:

- tools/audit_account_payment_usage.py

The script should:
- Scan .py, .html, .json files.
- Look for the keywords listed above.
- Print a grouped report.
- Not modify files.
- Be safe to run from repo root.

Do not make the app depend on this script.

7. Do not change business logic

This prompt must not change:
- transaction saving behavior
- balance calculations
- credit card pending behavior
- internal transfer behavior
- profile forms
- account management UI
- dashboard calculations

Only add documentation and optional audit tooling.

8. Validation

Run:

python -m compileall money_manager

Also verify:
- App still starts.
- Existing pages still load.
- No account/payment behavior changed.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Main findings from the audit
- Highest-risk areas for the next prompts
- Any assumptions you made


/--------------------------------------------------------------------------------------

