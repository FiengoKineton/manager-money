# Account/payment migration checklist

This checklist is for later prompts. It should be executed only after the audit terms and target architecture are accepted. Do not complete these items in the audit-only patch.

## 1. Data model foundations

- [ ] Create per-user `payment_methods.json`.
- [ ] Define payment-method schema with stable `payment_method_id`, label, type/channel, linked account, funding account, settlement account, active/archive flags, display order, and metadata.
- [ ] Upgrade `accounts.json` to `schema_version: 3` while preserving legacy fields.
- [ ] Add stable `account_id` if different from the old `key`; keep `key` as compatibility alias.
- [ ] Preserve `main_net_policy`, `payment_logic`, `aliases`, and `category_aliases` during the compatibility period.
- [ ] Add account lifecycle fields: `opened_at`, `closed_at`, `closure_status`, `closed_balance_transfer_group_id`, and `allow_new_transactions`.
- [ ] Add explicit account dependency fields for wallets/cards funded by a current account.
- [ ] Add default/current account settings without assuming only one `main_bank` account.

## 2. Ledger/event files

- [ ] Add `account_ledger.csv`.
- [ ] Add `account_events.json`.
- [ ] Add `credit_settlements.csv` or equivalent settlement-event storage.
- [ ] Add `ledger_group_id` and `transaction_uid` to transaction-like rows.
- [ ] Add fields for ledger movement source: `source_module`, `source_file`, `source_id`, `movement_type`, `created_at`, `reversed_at`, `reversal_of`, and `notes`.
- [ ] Decide whether ledger rows are append-only or can be rebuilt from canonical event files.
- [ ] Add integrity rules that prevent orphan ledger rows, duplicate settlement rows, and unbalanced internal transfers.

## 3. Transaction field migration

- [ ] Add `payment_method_id` and `account_id` transaction fields.
- [ ] Add optional `funding_account_id`, `linked_account_id`, and `settlement_account_id` where useful.
- [ ] Keep legacy `account` and `payment_method` columns during migration.
- [ ] Migrate legacy account values row by row.
- [ ] Migrate `account_key_snapshot`, `account_name_snapshot`, and `account_due_day_snapshot` into new settlement/account snapshot metadata.
- [ ] Migrate PayPal legacy values into PayPal Balance vs PayPal channel methods.
- [ ] Migrate credit-card category-alias rows into explicit credit liability account charges.
- [ ] Migrate blank-main rows to the selected/default current account policy without changing historical net totals.
- [ ] Migrate legacy category aliases (`cash`, `pre-paid`, `edenred`, `paypal`, etc.) into compatibility mapping records.

## 4. Profile bank migration

- [ ] Migrate profile `bank_name`, `iban`, and `bic_swift` into a real current account record.
- [ ] Update `default_main_account` to point to an account ID, not a free text value.
- [ ] Keep profile-level fields as compatibility/read-only fallback until old backups are migrated.
- [ ] Update onboarding so `main_bank_name` creates/updates the default current account.
- [ ] Update profile UI to show source bank details through current accounts.
- [ ] Preserve privacy masking for IBAN/BIC/account identifiers.

## 5. Payment resolver

- [ ] Implement one central payment-resolution service.
- [ ] Input should include transaction type, amount, date, payment method ID, optional account ID, optional linked module/source, and insufficient-balance preference.
- [ ] Output should include ledger movements, pending/settlement events, display explanation, and validation errors.
- [ ] Replace form-only route names `balance`, `credit`, and `another_card` with proper method/rule outputs.
- [ ] Keep adapter support for `account_payment_method` and `paypal_payment_method` until templates and old forms are migrated.
- [ ] Add resolver tests for main current account, cash, prepaid, EdenRed, PayPal balance, PayPal via card, credit card, Bonifico, and internal transfer.

## 6. Internal transfers and account closure

- [ ] Update internal transfers to use stable `from_account_id` and `to_account_id`.
- [ ] Write transfer ledger groups instead of only synthetic runtime movements.
- [ ] Preserve legacy `from_account` / `to_account` text for old CSV import/export.
- [ ] Update the move-all behavior to read from ledger/account balances.
- [ ] Define close-account flow: block new transactions, settle/execute pending items, move remaining balance, then mark closed.
- [ ] Decide how to handle pending payments tied to a closing account.
- [ ] Support transferring pending/dependent method references to the receiver account when appropriate.
- [ ] Add validation so closing a credit liability account requires zero outstanding liability or explicit settlement.

## 7. Credit settlements and pending logic

- [ ] Update credit settlements to use explicit charge IDs and settlement events.
- [ ] Preserve historical due-day snapshots so old charges do not move when future due days change.
- [ ] Add settlement account selection for each credit liability account or credit method.
- [ ] Replace description-based settlement detection with explicit movement/event types.
- [ ] Update Pending page to display settlement events and their underlying charges.
- [ ] Update pending execution to write ledger movements and mark events executed atomically.
- [ ] Prevent duplicate statement rows after migration.
- [ ] Add tests for due-day changes, statement month grouping, executed rows, and PayPal via credit card.

## 8. Module updates

- [ ] Update transaction add form.
- [ ] Update transaction edit/delete logic.
- [ ] Update Bonifico.
- [ ] Update Payables.
- [ ] Update Recurring.
- [ ] Update Pending.
- [ ] Update Debts.
- [ ] Update Receivables.
- [ ] Update Parent Support.
- [ ] Update Expense Projects.
- [ ] Update Investments funding logic.
- [ ] Update Quick Log.
- [ ] Update account detail/account list pages.
- [ ] Update yearly summary, analysis, dashboard, topbar balances, and net explanation.

## 9. Backup, import, privacy, navigation, and i18n

- [ ] Update Backup export/import to include `payment_methods.json`, `account_ledger.csv`, `account_events.json`, and credit settlement files.
- [ ] Update backup validation for new files.
- [ ] Update schema/migration helpers to create and repair new files.
- [ ] Update Privacy masking for account identifiers, IBAN/BIC, card labels/last4, and payment-method labels when sensitive.
- [ ] Update Navigation/i18n labels for Accounts, Current Accounts, Payment Methods, Ledger, Settlements, and Funding rules.
- [ ] Do not modify phone-specific UI unless a later prompt explicitly asks for it.

## 10. Data integrity tools

- [ ] Add migration dry-run report.
- [ ] Add ledger rebuild/check command.
- [ ] Add account balance reconciliation command.
- [ ] Add orphan payment-method/account detector.
- [ ] Add duplicate settlement detector.
- [ ] Add legacy alias usage report.
- [ ] Add backup round-trip test.
- [ ] Add smoke tests for all pages that display account/payment data.
- [ ] Add regression fixtures for current v10 data values.

## 11. Compatibility and cleanup

- [ ] Keep old fields readable for at least one migration cycle.
- [ ] Mark old fields as legacy in code comments and docs.
- [ ] Avoid deleting old columns until export/import and migration tests pass.
- [ ] After migration, stop creating new data that relies on category aliases for account balance effects.
- [ ] After migration, stop creating new data that uses `paypal_payment_method`.
- [ ] After migration, stop using `account` to mean payment method.
