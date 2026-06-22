# QUEUEING



#### Prompt 11B — Accounts + Payment Methods data model migration

You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 and Prompt 11A are already completed:
- Multi-user app exists.
- account/payment audit docs exist.
- v10 account logic still works.
- No new payment architecture has been applied yet.

Current repo context:
- data/users/{user_id}/accounts.json exists and is schema_version 2.
- money_manager/services/account_config_service.py owns current account config.
- money_manager/services/account_payment_policy_service.py owns current account payment policy.
- money_manager/config/user_defaults.py defines DEFAULT_ACCOUNTS.
- money_manager/services/schema_service.py repairs user schemas.
- Profile still stores one bank_name/iban/bic_swift.
- No payment_methods.json exists yet.

Goal of this patch:
Add the professional data model for Accounts and Payment Methods, without yet changing all transaction forms or dashboards.

This patch is a data-model migration and service foundation patch.

Do not redesign the UI.
Do not yet add the ledger layer.
Do not yet change transaction save/edit logic broadly.
Do not modify phone-specific UI.

Implement the following:

1. Upgrade Accounts model

Upgrade per-user:

data/users/{user_id}/accounts.json

from schema_version 2 to schema_version 3.

The new accounts.json should represent real balance containers only.

Each account should support these fields:

{
  "id": "conto_intesa",
  "key": "conto_intesa",
  "name": "Conto Intesa",
  "label": "Conto Intesa",

  "account_kind": "current_account",
  "type": "current_account",

  "currency": "EUR",
  "institution": "",
  "iban": "",
  "bic_swift": "",

  "initial_balance": 0.0,

  "is_current_account": true,
  "is_dependent_account": false,
  "parent_account_id": "",
  "parent_key": "",

  "is_liability": false,
  "is_container": false,

  "is_default": false,
  "is_custom": true,
  "is_active": true,
  "is_closed": false,
  "closed_at": "",
  "replacement_account_id": "",

  "display_order": 10,

  "aliases": [],
  "category_aliases": [],
  "category_match_enabled": false,
  "category_match_mode": "",

  "main_net_policy": "affects_main_net",

  "metadata": {},
  "legacy": {},

  "created_at": "",
  "updated_at": "",
  "archived_at": ""
}

Keep legacy fields:
- key
- type
- main_net_policy
- category_aliases
- payment_logic
- due_day
- statement_day
- cards

but mark them as compatibility/legacy. Do not delete them yet.

2. Account kinds

Support these account_kind values:

- current_account
- cash
- prepaid_balance
- wallet_balance
- meal_voucher
- investment_cash
- credit_card_liability
- dependent_wallet
- external_account
- container
- other

Validation rules:
- current_account can have IBAN/BIC/bank/institution.
- dependent accounts may have parent_account_id.
- credit_card_liability is a liability bucket, not a payment method.
- container accounts cannot be used directly as payment accounts unless explicitly allowed.
- archived/closed accounts remain visible for old transactions but hidden from new forms by default.

3. Add Payment Methods model

Create per-user:

data/users/{user_id}/payment_methods.json

Structure:

{
  "schema_version": 1,
  "payment_methods": [
    {
      "id": "intesa_debit_card",
      "name": "Intesa Debit Card",
      "method_type": "debit_card",

      "linked_account_id": "conto_intesa",
      "funding_account_id": "conto_intesa",
      "settlement_account_id": "conto_intesa",
      "liability_account_id": "",

      "settlement_mode": "immediate",

      "delegates_to_payment_method_id": "",

      "is_default": false,
      "is_active": true,
      "is_archived": false,
      "display_order": 10,

      "rules": {
        "due_day": null,
        "statement_day": null,
        "settlement_day_policy": "next_month",
        "allow_manual_due_date": true
      },

      "aliases": [],
      "legacy": {},
      "metadata": {},

      "created_at": "",
      "updated_at": "",
      "archived_at": ""
    }
  ]
}

4. Payment method types

Support:

- debit_card
- credit_card
- prepaid_card
- wallet_balance
- wallet_linked_card
- bank_transfer
- cash
- meal_voucher
- investment_cash_transfer
- other

5. Settlement modes

Support:

- immediate
- delayed
- stored_balance
- delegated
- external_record_only

Meanings:
- immediate: affects funding_account_id immediately.
- delayed: creates/uses liability_account_id now and settles from settlement_account_id later.
- stored_balance: affects linked_account_id immediately.
- delegated: forwards logic to delegates_to_payment_method_id while keeping wrapper metadata.
- external_record_only: records a transaction without affecting tracked balances unless explicitly configured.

6. Create payment method service

Create:

- money_manager/services/payment_method_service.py

Responsibilities:
- load_payment_methods(user_id=None)
- save_payment_methods(payload, user_id=None)
- ensure_payment_methods_file(user_id=None)
- all_payment_methods(include_archived=True, user_id=None)
- active_payment_methods(user_id=None)
- payment_method_by_id(method_id, include_archived=True, user_id=None)
- normalize_payment_method_id(value, user_id=None)
- payment_method_options_for_forms(user_id=None)
- create_payment_method_from_form(form, user_id=None)
- update_payment_method_from_form(method_id, form, user_id=None)
- archive_payment_method(method_id, user_id=None)
- restore_payment_method(method_id, user_id=None)
- validate_payment_method(method, accounts, methods)
- infer_default_payment_methods_from_accounts(accounts_payload)

Validation:
- Prevent duplicate active method IDs.
- Prevent duplicate active names case-insensitively.
- Validate linked_account_id/funding_account_id/settlement_account_id/liability_account_id exist when required.
- Validate delegated methods do not create cycles.
- Archived methods are hidden from new forms but usable for old transactions.

7. Default migration from existing v10 accounts

When payment_methods.json is missing, generate it from existing accounts.json.

Rules:

A. main_bank
- Create/keep an account:
  - account_kind = current_account
  - is_current_account = true
- Create payment method:
  - id: main_bank_transfer
  - name: Main bank account
  - method_type: bank_transfer
  - settlement_mode: immediate
  - funding_account_id: main_bank

B. cash_flow
- Account:
  - account_kind = cash
- Payment method:
  - id: cash
  - method_type: cash
  - settlement_mode: stored_balance
  - linked_account_id: cash_flow
  - funding_account_id: cash_flow

C. pre_paid_card
- Account:
  - account_kind = prepaid_balance
- Payment method:
  - id: pre_paid_card
  - method_type: prepaid_card
  - settlement_mode: stored_balance
  - linked_account_id: pre_paid_card
  - funding_account_id: pre_paid_card

D. edenred
- Account:
  - account_kind = meal_voucher
- Payment method:
  - id: edenred
  - method_type: meal_voucher
  - settlement_mode: stored_balance
  - linked_account_id: edenred
  - funding_account_id: edenred

E. paypal
- Account:
  - account_kind = dependent_wallet or wallet_balance
  - is_dependent_account = true if parent account is known
- Payment method:
  - id: paypal_balance
  - method_type: wallet_balance
  - settlement_mode: stored_balance
  - linked_account_id: paypal
  - funding_account_id: paypal

F. credit_card
- Convert to:
  - account_kind = credit_card_liability
  - is_liability = true
  - main_net_policy = credit_pending for legacy compatibility
- Create payment method:
  - id: credit_card
  - method_type: credit_card
  - settlement_mode: delayed
  - funding_account_id: main_bank
  - settlement_account_id: main_bank
  - liability_account_id: credit_card
  - rules.due_day = old due_day or 15
  - aliases include credit, credit card, carta credito, carta di credito

G. PayPal via credit card
- If paypal and credit_card exist, create:
  - id: paypal_via_credit_card
  - method_type: wallet_linked_card
  - settlement_mode: delegated
  - linked_account_id: paypal
  - delegates_to_payment_method_id: credit_card
  - aliases include paypal_credit and old PayPal credit aliases

H. PayPal via main/debit
- If paypal and main_bank exist, create:
  - id: paypal_via_main_bank
  - method_type: wallet_linked_card
  - settlement_mode: delegated or immediate
  - linked_account_id: paypal
  - delegates_to_payment_method_id: main_bank_transfer

8. Preserve backward compatibility

Update:
- money_manager/config/user_defaults.py
- money_manager/services/schema_service.py
- money_manager/services/account_config_service.py
- money_manager/config/accounts.py

Requirements:
- Existing account_options_for_forms() must still return something compatible.
- Existing templates must not crash.
- Existing services importing account_config_service must not break.
- Existing account names/keys must still normalize.
- Existing account_policy_for_key() still works.
- Existing account_due_day_for_key() still works.
- Do not remove old payment_logic yet.
- Do not remove account_payment_policy_service.py yet.

9. Add defaults

Update user defaults:
- Add DEFAULT_PAYMENT_METHODS.
- Add "payment_methods.json" to USER_CONFIG_DEFAULTS.
- New users should get default payment_methods.json.
- Existing users should get it on schema repair.

10. Add migration report

When migration runs, write/update:

data/users/{user_id}/migration_info.json

with a section:

"account_payment_model_migration": {
  "from_accounts_schema": 2,
  "to_accounts_schema": 3,
  "payment_methods_created": true,
  "created_at": "",
  "notes": []
}

11. No UI-heavy work

Do not yet:
- Redesign accounts page.
- Change all transaction forms.
- Add ledger.
- Rewrite dashboard.
- Move profile IBAN yet.
- Change internal transfers yet.

Minimal account settings UI can show payment methods only if easy, but backend correctness is more important.

12. i18n

Add basic keys to en.json and it.json:
- accounts.current_account
- accounts.dependent_account
- accounts.payment_methods
- accounts.payment_method
- accounts.funding_account
- accounts.settlement_account
- accounts.liability_account
- accounts.credit_card_liability
- accounts.archived_method
- accounts.delayed_settlement
- accounts.stored_balance
- accounts.delegated_method

13. Validation

Run:

python -m compileall money_manager

Then verify:
- Existing app starts.
- Existing user accounts.json is upgraded to schema_version 3.
- payment_methods.json is created.
- Existing account page still loads.
- Existing add transaction page still loads.
- Existing transactions still display.
- Existing credit-card delayed pending logic is not broken.
- New users get accounts.json and payment_methods.json.
- User A payment methods are not visible to user B.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Files modified
- accounts.json schema_version 3 structure
- payment_methods.json structure
- Migration behavior from v10 accounts.json
- Backward compatibility choices
- Known limitations remaining for prompts 11C-11G

/--------------------------------------------------------------------------------------



#### Prompt 11C — Ledger layer and centralized payment routing engine


You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 and Prompts 11A-11B are already completed:
- Audit docs exist.
- accounts.json is schema_version 3.
- payment_methods.json exists per user.
- payment_method_service.py exists.
- Existing transaction/account behavior still works.
- No ledger layer has been fully integrated yet.

Goal of this patch:
Add the professional ledger layer and centralized payment routing engine.

This patch should introduce the correct accounting foundation, but should not yet force every page/form to use it. Full form migration comes later in Prompt 11F.

Do not redesign the UI.
Do not modify phone-specific UI.

Core idea:
Transaction = what happened.
Payment method = how it was paid.
Account = where balance lives.
Ledger movement = how balances are affected.

Implement the following:

1. Add account ledger CSV

Create per user:

data/users/{user_id}/account_ledger.csv

Add fields to money_manager/domain/constants.py:

ACCOUNT_LEDGER_FIELDS = [
  "id",
  "ledger_group_id",
  "transaction_uid",
  "transaction_type",
  "transaction_id",
  "source_kind",
  "source_id",
  "date",
  "effective_date",
  "account_id",
  "account_name_snapshot",
  "counterparty_account_id",
  "counterparty_account_name_snapshot",
  "payment_method_id",
  "payment_method_name_snapshot",
  "movement_kind",
  "direction",
  "amount",
  "currency",
  "signed_amount",
  "status",
  "is_void",
  "voided_by_ledger_group_id",
  "created_from_resolution_json",
  "notes",
  "created_at"
]

Meanings:
- ledger_group_id groups all movements created by the same transaction/payment resolution.
- transaction_uid should be stable, for example "expense:123".
- movement_kind examples:
  - expense_cash_out
  - income_cash_in
  - investment_cash_out
  - transfer_out
  - transfer_in
  - credit_liability_increase
  - credit_liability_decrease
  - credit_settlement_cash_out
  - adjustment
  - opening_balance
- status examples:
  - posted
  - scheduled
  - voided
  - simulated
- is_void marks reversal rows.
- scheduled rows are future movements, for example credit card settlement.

2. Add account ledger service

Create:

- money_manager/services/account_ledger_service.py
- money_manager/repositories/account_ledger.py if needed

Responsibilities:
- ensure_account_ledger()
- load_ledger(include_void=False, user_id=None)
- append_ledger_movements(movements, user_id=None)
- ledger_rows_for_transaction(transaction_uid, include_void=True)
- void_ledger_group(ledger_group_id, reason="", user_id=None)
- void_ledger_for_transaction(transaction_uid, reason="", user_id=None)
- account_balance_from_ledger(account_id, as_of=None, include_scheduled=False)
- account_balances_from_ledger(as_of=None, include_scheduled=False)
- scheduled_movements(as_of=None)
- validate_ledger_rows()
- rebuild_ledger_from_transactions(dry_run=True)

Important:
- Voiding must not delete rows. It should create reversal/void rows or mark existing rows as voided, preserving auditability.
- Existing old transactions may not have ledger rows. The service must tolerate this.
- All writes must be user-specific.
- Do not access another user's ledger.

3. Add payment resolution domain object

Create:

- money_manager/domain/payment.py

Define dataclasses or typed dictionaries:

PaymentResolution:
- ok
- warnings
- errors
- transaction_type
- amount
- currency
- transaction_date
- account_id
- account_name_snapshot
- payment_method_id
- payment_method_name_snapshot
- linked_account_id
- funding_account_id
- settlement_account_id
- liability_account_id
- settlement_mode
- due_date
- due_day_snapshot
- statement_period
- ledger_group_id
- display_explanation
- movements

LedgerMovementDraft:
- account_id
- account_name_snapshot
- movement_kind
- direction
- amount
- signed_amount
- effective_date
- status
- notes

4. Add payment routing service

Create:

- money_manager/services/payment_routing_service.py

Core function:

resolve_payment(
    transaction_type,
    amount,
    date,
    account_id=None,
    payment_method_id=None,
    category=None,
    sub_category=None,
    description="",
    existing_row=None,
    user_id=None,
) -> PaymentResolution

Responsibilities:
- Load accounts from account_config_service.py.
- Load payment methods from payment_method_service.py.
- Validate selected account/payment method.
- Resolve legacy account values where needed.
- Return deterministic ledger movement drafts.
- Never write CSVs directly. It only resolves.
- The caller decides whether to persist movements.

5. Routing rules

Implement these rules:

A. Income
- If account_id is a current/cash/wallet/prepaid account:
  - create one posted ledger movement:
    account +amount
- If no account_id:
  - default to user default current account or main_bank.

B. Expense with debit_card / bank_transfer immediate
- Deduct from funding_account_id immediately:
  - funding account -amount posted.

C. Expense with cash
- Deduct from cash account immediately.

D. Expense with prepaid_card
- Deduct from prepaid balance immediately.

E. Expense with meal_voucher
- Deduct from meal voucher account immediately.

F. Expense with wallet_balance
- Deduct from wallet linked account immediately.

G. Expense with credit_card delayed
- Increase liability now:
  - liability account -amount or +amount consistently according to selected sign convention.
- Do not deduct from settlement/current account now.
- Add scheduled settlement metadata:
  - due_date
  - due_day_snapshot
  - statement_period
- The actual cash settlement will be handled by credit settlement service later.

Be explicit in docs and code comments about sign convention:
- Assets use positive balance.
- Expenses reduce asset accounts with negative signed_amount.
- Liabilities should either be negative balance or separate liability positive owed amount.
Choose one convention and document it clearly.

H. wallet_linked_card delegated
- Keep wrapper info:
  - payment_method_id = PayPal via Credit Card
- Delegate actual settlement to delegates_to_payment_method_id.
- Store both wrapper and delegated method in resolution JSON.
- For PayPal via credit card:
  - PayPal balance should not change.
  - Credit card liability changes.
  - Transaction display can still show PayPal as channel.
- For PayPal via debit/main bank:
  - PayPal balance should not change unless method is PayPal balance.
  - Main/current account is affected.

I. external_record_only
- No ledger movement unless method rules explicitly configure one.
- Return warning explaining no tracked balance was affected.

6. Due date and statement period

Implement helper functions:
- compute_statement_period(transaction_date, statement_day=None)
- compute_due_date(transaction_date, due_day, statement_day=None, policy="next_month")

Rules:
- Preserve snapshots.
- If payment method due_day changes later, old resolutions remain unchanged.
- Statement day can be null for calendar-month statement.
- Default due_day = 15 for legacy credit card.

7. Add credit settlement service skeleton

Create:

- money_manager/services/credit_settlement_service.py

Do not fully replace Pending page yet.

Responsibilities for now:
- group_unsettled_credit_movements()
- preview_credit_settlements()
- settlement_due_dates()
- explain_credit_settlement_group()

It may read ledger and payment resolutions, but should not yet rewrite all existing pending behavior.

8. Add schema repair

Update:
- money_manager/domain/constants.py
- money_manager/services/schema_service.py

Ensure:
- account_ledger.csv is created for every user.
- Missing columns are added safely.
- No destructive migration.

9. Add diagnostics route or CLI helper

Optional but useful:

- tools/rebuild_ledger_preview.py

It should:
- Load current user or a specified user.
- Run rebuild_ledger_from_transactions(dry_run=True).
- Print number of inferred movements.
- Not write unless called with explicit flag.

Do not make launcher depend on it.

10. Do not yet replace all calculations

Important:
Existing dashboards/account calculations should continue using current v10 behavior for now unless safely opt-in.

You may add ledger-based preview helpers, but do not break:
- main_account_transactions()
- account_balance_rows()
- pending_service credit statements
- overview/dashboard

11. Validation

Run:

python -m compileall money_manager

Then verify:
- account_ledger.csv is created for users.
- payment_routing_service.resolve_payment() works for:
  - debit/bank transfer immediate
  - credit card delayed
  - PayPal via credit card delegated
  - PayPal balance stored_balance
  - cash
  - prepaid
- credit settlement preview groups delayed credit movements.
- Existing app starts.
- Existing add transaction page still works.
- Existing pending page still works.
- Existing credit card behavior is not broken.
- User A ledger is separate from user B ledger.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Files modified
- account_ledger.csv schema
- PaymentResolution structure
- Sign convention chosen
- Routing behavior for each payment method type
- What still remains legacy until prompts 11D-11F


/--------------------------------------------------------------------------------------




#### Prompt 11D — Transaction schema, ledger persistence, and safe payment-method editing


You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 and Prompts 11A-11C are already completed:
- accounts.json schema_version 3 exists.
- payment_methods.json exists.
- payment_method_service.py exists.
- account_ledger.csv exists.
- payment_routing_service.py exists.
- account_ledger_service.py exists.
- Existing app still works.

Goal of this patch:
Update transaction storage and transaction editing so new/edited transactions can safely use account_id + payment_method_id and write ledger movements.

This is a backend correctness patch. Do not redesign the dashboard yet. Do not update every external module/form yet; that comes in Prompt 11F.

Do not modify phone-specific UI.

1. Extend transaction fields

Update money_manager/domain/constants.py.

Extend TRANSACTION_FIELDS and SPARAGNAT_FIELDS safely by adding:

- transaction_uid
- account_id
- account_name_snapshot
- payment_method_id
- payment_method_name_snapshot
- payment_channel_method_id_snapshot
- payment_channel_name_snapshot
- funding_account_id_snapshot
- funding_account_name_snapshot
- settlement_account_id_snapshot
- settlement_account_name_snapshot
- liability_account_id_snapshot
- liability_account_name_snapshot
- settlement_mode_snapshot
- payment_due_date_snapshot
- payment_due_day_snapshot
- payment_statement_period_snapshot
- payment_resolution_json
- ledger_group_id
- ledger_status

Keep all old columns:
- account
- account_key_snapshot
- account_name_snapshot
- account_due_day_snapshot
- payment_method

Do not delete or rename old fields yet.

2. Schema migration

Update schema_service.py and repositories/csv_files behavior if needed so:
- Existing CSVs get new columns.
- Existing row values are preserved.
- Unknown extra columns are preserved.
- Empty files are created with the new schema.
- No destructive migration.

3. Update TransactionInput

Update:

- money_manager/domain/transaction.py

Add fields:
- account_id
- payment_method_id
- payment_channel_method_id optional
- force_payment_rebuild optional
- confirm_settled_edit optional

Backwards-compatible mapping:
- If form has payment_method_id, use it.
- Else if form has account_payment_method/paypal_payment_method, preserve legacy behavior.
- Else if form has account, infer as before.

Do not break old forms.

4. Create transaction UID helpers

Add helpers:
- make_transaction_uid(transaction_type, tx_id)
- parse_transaction_uid(uid)

Use transaction_uid like:
- expense:123
- income:15
- investment:8
- sparagnat:3 if applicable

5. Update append_transaction

Update money_manager/repositories/transactions.py and/or transaction_service.py carefully.

Requirements:
- append_transaction should be able to store all new metadata fields.
- When creating a transaction through the new service path:
  - call payment_routing_service.resolve_payment()
  - write transaction row with snapshots
  - write account_ledger.csv rows through account_ledger_service
  - store ledger_group_id in transaction row
- When append_transaction is called by legacy services without payment_method_id:
  - keep old behavior
  - infer account/payment as best effort only if safe
  - do not crash

Important:
Avoid circular imports. If repository-level append_transaction cannot safely call services, keep repository simple and put resolution in transaction_service.py.

6. New transaction save path

Update transaction_service.save_new_transaction() and save_transaction_payload().

Behavior:
- If tx_input.payment_method_id exists:
  - use new payment routing path.
- Else:
  - keep legacy v10 path.
- If tx_input.account_id exists but payment_method_id does not:
  - use account_id as target account for income/investment if applicable.
  - for expenses, either infer default payment method or fallback to legacy account field.
- Store both new and legacy fields where useful for compatibility:
  - account = old display/legacy value
  - account_id = stable account id
  - payment_method = old display/legacy value
  - payment_method_id = stable method id

7. Safe transaction editing

Current v10 update_existing_transaction() edits CSV data only. This is not enough.

Update transaction editing so:

When a transaction is edited:
1. Load original row.
2. Detect if date, amount, type, account_id, payment_method_id, account, or payment_method changed.
3. If no payment-affecting field changed, update metadata normally.
4. If payment-affecting field changed:
   - Find existing ledger rows by transaction_uid or ledger_group_id.
   - Void/reverse old ledger group through account_ledger_service.
   - Re-run payment_routing_service.resolve_payment().
   - Write new ledger rows.
   - Update transaction row snapshots.
   - Preserve old transaction ID.
   - Add a note/audit metadata that payment route was rebuilt.

8. Editing settled credit transactions

If transaction has delayed credit settlement and is already settled/executed:
- Do not silently rewrite history.
- Detect this using:
  - ledger rows status
  - pending/credit settlement references
  - payment_due_date_snapshot
  - settlement rows if present
- Safe first implementation:
  - Block payment-method/account changes unless form includes confirm_settled_edit=1.
  - If confirmed, create adjustment ledger rows instead of deleting old history.
  - Add warning message for the UI.

If exact settlement detection is uncertain, be conservative and warn/block.

9. Safe transaction delete

Update delete_existing_transaction():
- Delete or mark transaction as deleted according to current repo behavior.
- Void/reverse ledger rows for that transaction.
- Do not delete old ledger history.
- If transaction already settled, warn or create adjustment rows according to the same rule as editing.

If UI cannot show confirmation yet, keep current delete behavior for legacy rows but implement backend function ready for confirmation.

10. Transaction detail UI minimal update

Update transaction detail template enough to show:
- Account / Conto
- Payment Method / Metodo di pagamento
- Funding account
- Settlement account
- Due date if delayed
- Ledger status
- Payment routing explanation

Do not redesign heavily.

Add hidden/optional fields if necessary:
- account_id
- payment_method_id
- confirm_settled_edit

Full form migration comes in Prompt 11F.

11. Add transaction repository helpers

Add helpers:
- get_transaction_by_uid()
- update_transaction_by_uid()
- transaction_row_to_payment_context()
- transaction_has_payment_snapshots()
- transaction_is_legacy_payment()

12. Backward compatibility

Existing old rows without payment_method_id must:
- Still display.
- Still calculate balances with old account_service enrichment.
- Not require ledger rows.
- Not crash transaction detail page.
- Not be forcibly migrated unless safe.

13. Validation

Run:

python -m compileall money_manager

Then verify:
- Existing transactions still display.
- Existing transaction detail page loads.
- New CSV columns are added.
- New transaction with payment_method_id creates transaction + ledger rows.
- Legacy transaction without payment_method_id still saves.
- Editing non-payment fields does not rebuild ledger.
- Editing payment method voids old ledger and creates new ledger.
- Deleting a transaction voids ledger rows.
- Settled credit-card edits are blocked or require explicit confirmation.
- User A cannot affect user B ledger.
- Existing Pending page still works.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Files modified
- New transaction fields
- How new transaction saving works
- How old rows remain compatible
- How payment-method edits are handled
- Known limitations for Prompt 11F



/--------------------------------------------------------------------------------------




#### Prompt 11E — Internal transfers, credit settlements, and account closure


You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 and Prompts 11A-11D are already completed:
- Professional accounts model exists.
- payment_methods.json exists.
- Ledger and payment routing exist.
- Transaction schema has account_id/payment_method_id and ledger metadata.
- Transaction edit/delete can void/rebuild ledger rows.

Goal of this patch:
Handle the big account lifecycle cases:
1. Internal transfers between real accounts.
2. Credit card settlements.
3. Closing/archiving a Conto Corrente safely.

Do not redesign the whole dashboard.
Do not add Bollette/Mutui yet.
Do not modify phone-specific UI.

PART A — Internal transfers

1. Upgrade internal transfer schema

Update INTERNAL_TRANSFER_FIELDS in money_manager/domain/constants.py.

Keep old fields:
- from_account
- to_account

Add new fields:
- transfer_uid
- from_account_id
- from_account_name_snapshot
- to_account_id
- to_account_name_snapshot
- fee_amount
- fee_payment_method_id
- fee_payment_method_name_snapshot
- ledger_group_id
- status
- transfer_kind
- metadata_json

Possible transfer_kind:
- normal_transfer
- prepaid_topup
- wallet_topup
- cash_deposit
- cash_withdrawal
- account_closure_balance_move
- credit_settlement
- adjustment

2. Update internal transfer service

Update:

- money_manager/services/internal_transfer_service.py
- money_manager/repositories/internal_transfers.py
- money_manager/web/routes/accounts/internal_transfers.py
- money_manager/web/templates/accounts/internal_transfers.html

Behavior:
- Internal transfer must mean movement from one real account to another.
- It should not mean payment method.
- It should not use category logic.
- It should not be saved as normal income/expense unless fee requires a separate expense.
- It should write ledger rows:
  - from_account_id: -amount
  - to_account_id: +amount
- It should store snapshots.
- It should preserve old from_account/to_account text for compatibility.

Validation:
- from_account_id and to_account_id must be different.
- Both accounts must exist.
- Archived/closed accounts cannot be used for new transfers unless explicitly allowed for closure migration.
- Containers cannot be used directly unless allowed.
- Check balance if current behavior checks balance.

3. Fees

If a transfer has a fee:
- fee_amount > 0 creates a separate ledger movement or transaction according to existing architecture.
- fee_payment_method_id is optional.
- Use payment_routing_service for fee payment when possible.
- Do not hard-code Pre-paid card fee. Use account/payment metadata.

PART B — Credit card settlements

4. Add credit settlement storage

Create per user:

data/users/{user_id}/credit_settlements.csv

Add fields:

CREDIT_SETTLEMENT_FIELDS = [
  "id",
  "settlement_uid",
  "payment_method_id",
  "payment_method_name_snapshot",
  "liability_account_id",
  "liability_account_name_snapshot",
  "settlement_account_id",
  "settlement_account_name_snapshot",
  "statement_period",
  "due_date",
  "amount",
  "currency",
  "status",
  "ledger_group_id",
  "pending_id",
  "executed_transaction_uid",
  "created_from_ledger_group_ids_json",
  "created_at",
  "updated_at",
  "executed_at",
  "notes"
]

status:
- open
- scheduled
- executed
- cancelled
- adjusted

5. Implement credit settlement service

Update/create:

- money_manager/services/credit_settlement_service.py
- money_manager/repositories/credit_settlements.py

Responsibilities:
- group_unsettled_credit_movements()
- sync_credit_settlements()
- preview_credit_settlements()
- execute_credit_settlement(settlement_id, execution_date=None)
- settle_all_due(today=None)
- settle_now_for_payment_method(payment_method_id)
- cancel_or_adjust_settlement()
- settlement_rows_for_payment_method()
- settlement_rows_for_account()

Rules:
- Credit card purchases create liability ledger movements.
- Settlement pays the liability from settlement_account_id.
- Execution creates ledger movements:
  - settlement/current account: -amount
  - credit liability account: +amount or liability decrease according to sign convention chosen in 11C.
- Do not double-settle.
- Preserve statement period and due day snapshots.
- Changing due day affects future statements only.
- Old pending-service credit statements must remain compatible during transition.

6. Pending integration

The repo currently has pending_service.py that aggregates credit account statements.

Do not break it.

Migration approach:
- Either keep pending_service as UI queue and make it call credit_settlement_service for credit settlements,
  OR let credit_settlement_service create/update pending rows for backward UI compatibility.
- Do not have two different systems execute the same credit settlement twice.
- Store cross references:
  - pending_id in credit_settlements.csv
  - source/source_id in pending.csv
- Existing executed pending rows must remain visible.

7. Credit settlement UI minimal update

Update Pending page or add a small Credit Settlements section:

Show:
- Payment method
- Statement period
- Amount
- Due date
- Settlement account
- Status
- Execute now button
- Details of included transactions if easy

Do not make a full dashboard redesign.

PART C — Account closure

8. Add account events storage

Create per user:

data/users/{user_id}/account_events.json

Structure:

{
  "schema_version": 1,
  "events": [
    {
      "id": "uuid",
      "event_type": "account_closure",
      "account_id": "",
      "replacement_account_id": "",
      "status": "completed",
      "created_at": "",
      "completed_at": "",
      "details": {},
      "warnings": []
    }
  ]
}

9. Add account closure service

Create:

- money_manager/services/account_closure_service.py

Responsibilities:
- account_closure_precheck(account_id)
- close_account(account_id, options)
- archive_account_only(account_id)
- move_balance_to_replacement(account_id, replacement_account_id, date)
- reassign_payment_methods(account_id, replacement_account_id)
- settle_pending_credit_now(account_id)
- move_future_credit_settlements(account_id, replacement_account_id)
- block_closure_if_unsafe(account_id)
- create closure event

Precheck must inspect:
- Current balance from ledger and legacy fallback.
- Active payment methods where linked/funding/settlement/liability account is account_id.
- Dependent accounts with parent_account_id = account_id.
- Open credit settlements.
- Pending rows.
- Recurring rules.
- Payables.
- Debts.
- Receivables.
- Parent support rules.
- Expense project planned items.
- Internal transfer templates if any.
- Future Bills/Mutui should be noted as future checks but not required yet.

10. Closure options

Support these closure modes:

A. Archive only
Allowed only when:
- balance is zero or user confirms adjustment
- no active methods depend on it
- no open settlements
- no active recurring/future rules use it

B. Move balance then archive
- Create internal transfer:
  old account -> replacement account
- transfer_kind = account_closure_balance_move
- Then archive account.

C. Reassign active payment methods
- Payment methods linked to old account can be reassigned to replacement account.
- Credit card settlement account can be changed to replacement.
- Due day/rules stay the same unless user changes them.

D. Settle credit now then close
- Execute open credit settlements immediately.
- Then proceed with closure.

E. Move future settlements to replacement account
- Only for open/not-yet-executed settlements.
- Preserve existing settled history.

Do not destructively delete the account.

Set:
- is_active = false
- is_closed = true
- closed_at = date
- replacement_account_id = selected account
- archived_at = date if appropriate

11. Closure UI minimal update

Add to account detail/settings page:
- Close/archive account button.
- Precheck page/modal.
- Show blockers and warnings.
- Show available closure options.
- Confirmation required.

Do not allow closing the last active current_account unless user explicitly confirms and understands the app will need another default account.

12. Profile/default account update

If closed account is the profile default account:
- Ask/select replacement.
- Update profile.default_current_account_id or legacy default_main_account safely.
- If no replacement, clear default and warn.

13. Backup/schema

Update:
- schema_service.py to create credit_settlements.csv and account_events.json.
- backup_service.py automatically includes them because user folder export should include all non-excluded files. Verify this.

14. i18n

Add English/Italian keys for:
- Internal transfer
- From account
- To account
- Credit settlement
- Statement period
- Settle now
- Close account
- Closure precheck
- Move balance
- Reassign payment methods
- Replacement account
- Pending settlement
- Account cannot be closed
- Account closed

15. Validation

Run:

python -m compileall money_manager

Then verify:
- Existing internal transfers still display.
- New internal transfer uses from_account_id/to_account_id and writes ledger.
- Transfer fee works or is safely ignored with message if not configured.
- Credit settlements can be previewed.
- Credit settlement can be executed once only.
- Existing Pending page does not double-settle credit card rows.
- Account closure precheck finds active payment methods.
- Account closure precheck finds open settlements.
- Closing account does not delete old transactions.
- Moving balance creates internal transfer and ledger movements.
- Reassigning payment methods updates payment_methods.json safely.
- Closing profile default account updates/requires replacement.
- User A cannot close or transfer user B accounts.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Files modified
- Internal transfer schema changes
- Credit settlement behavior
- Account closure workflow
- Pending page compatibility
- Remaining work for Prompt 11F



/--------------------------------------------------------------------------------------




#### Prompt 11F — Update all forms/services to use Account + Payment Method


You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 and Prompts 11A-11E are already completed:
- Accounts schema_version 3 exists.
- payment_methods.json exists.
- Ledger and payment routing exist.
- Transaction schema supports account_id/payment_method_id.
- Internal transfers use real account IDs.
- Credit settlements exist.
- Account closure workflow exists.

Goal of this patch:
Update the rest of the app so forms/services consistently use:

1. Account / Conto
   The real balance container.

2. Payment Method / Metodo di pagamento
   The way the transaction is paid.

Every feature that records money movement should call payment_routing_service.py instead of guessing payment behavior from account/category names.

Do not redesign the entire dashboard yet.
Do not modify phone-specific UI.

1. Add shared form context helpers

Create or update:

- money_manager/services/payment_form_service.py

Responsibilities:
- account_options_for_payment_forms()
- current_account_options()
- dependent_account_options()
- payment_method_options_for_forms()
- compatible_payment_methods_for_account(account_id)
- default_payment_method_for_account(account_id)
- explain_payment_method(method_id)
- payment_form_context(transaction_type=None, selected_account_id=None)

Returned option dictionaries should include:
- id
- value
- label
- description
- method_type
- settlement_mode
- linked_account_id
- funding_account_id
- settlement_account_id
- liability_account_id
- is_archived
- disabled_reason if incompatible

2. Update Add Transaction

Update:
- money_manager/web/routes/core/transactions.py
- money_manager/web/templates/core/add_transaction.html
- money_manager/domain/transaction.py
- money_manager/services/transaction_service.py

Form should clearly show:
- Account / Conto
- Payment Method / Metodo di pagamento

Behavior:
- For income:
  - Account selector is required or defaults to default current account.
  - Payment method can be hidden or optional.
- For expense:
  - Payment method is required.
  - Account can be automatically resolved from payment method, but if shown, it must validate compatibility.
- For investment:
  - Account/funding source should be selectable.
  - Payment method/source should route cash movement if applicable.

Do not remove legacy fields yet.
Include hidden legacy account field only if needed for old functions.

Show a small explanation:
- “This payment method deducts immediately from Conto Intesa.”
- “This credit card will be settled on day 15 from Conto Intesa.”
- “This PayPal method delegates to Intesa Credit Card.”

3. Update Transaction Detail/Edit

Update:
- money_manager/web/templates/core/transaction_detail.html
- transaction_detail route/service

Allow changing:
- Account / Conto
- Payment Method

When changed:
- Use safe edit logic from Prompt 11D.
- Show confirmation if settled/delayed transaction is risky.
- Show routing explanation and ledger status.

4. Update Bonifico

Update:
- money_manager/services/bonifico_service.py
- money_manager/web/routes/bonifico.py
- money_manager/web/templates/bonifico/bonifico.html

Bonifico should become:
- payment method type = bank_transfer
- selected source account = current account / conto corrente
- selected payment_method_id should be a bank_transfer method linked to that account

Behavior:
- Existing Bonifico contact logic remains.
- It still records a Money Manager transaction only; it does not execute a real bank transfer.
- It uses payment_routing_service.py.
- It stores contact snapshots as before.

5. Update Payables

Update:
- money_manager/services/payable_service.py
- money_manager/web/routes/planning/payables.py
- templates for payables

Payables can have partial payments.

Rules:
- The payable itself may store preferred account_id/payment_method_id.
- Each actual payment event must store its own payment_method_id.
- Partial payments call payment_routing_service.py.
- Do not assume account field means payment method.
- Existing payables.csv remains compatible.

If needed, add fields to PAYABLE_FIELDS:
- account_id
- account_name_snapshot
- preferred_payment_method_id
- preferred_payment_method_name_snapshot

If partial payment records exist elsewhere, update them similarly.

6. Update Debts and Receivables

Update:
- debt_service.py
- receivable_service.py
- related routes/templates

Rules:
- Debt payoff payment uses payment_method_id.
- Receivable collection uses receiving account_id.
- If debt/receivable was created from a transaction, keep link.
- Do not break existing debt pending rules.

7. Update Recurring Rules

Update:
- recurring service/repository/templates
- pending recurring page if recurring lives in pending.py

Add fields to RECURRING_FIELDS safely:
- account_id
- account_name_snapshot
- payment_method_id
- payment_method_name_snapshot
- payment_resolution_template_json

Rules:
- Recurring expense requires payment_method_id.
- Recurring income requires account_id.
- If a recurring rule uses an archived payment method/account, show warning and require replacement before generating future transactions.
- When recurring transaction is generated, call payment_routing_service.py.

8. Update Pending

Update:
- pending_service.py
- pending templates/routes

Rules:
- Manual pending payment should store account_id/payment_method_id where appropriate.
- Credit settlements should be handled by credit_settlement_service.py.
- Pending execution should call payment_routing_service.py or credit_settlement_service.py.
- Do not double-execute credit card settlements.
- Existing pending rows remain compatible.

9. Update Expense Projects

Update:
- expense_project_service.py
- templates/routes

Rules:
- Planned item preferred payment method can be stored.
- When creating actual transaction/payable from project item, use payment_method_id.
- Existing project rows remain compatible.

10. Update Parent Support

Update:
- parent_support_service.py
- templates/routes

Rules:
- Replace ambiguous payment_method free text with payment_method_id where money movement is recorded.
- Keep old payment_method text for display/backward compatibility.
- Use payment routing for actual payments.

11. Update Investments

Update:
- investment_service.py
- routes/templates

Rules:
- Investment buy/sell/dividend must distinguish:
  - investment asset/security
  - funding/receiving account
  - payment/transfer method
- Buy:
  - cash leaves selected funding account/payment method.
- Sell/dividend:
  - cash enters selected account.
- Do not assume investments always use main account.
- Keep current investment analytics working.

12. Update Quick Log / Special Log

Update:
- quick_log_service.py
- quick log template sections

Rules:
- Transfer quick log uses from_account_id/to_account_id.
- Expense quick log uses payment_method_id.
- Income quick log uses account_id.
- Existing quick modes remain compatible.

13. Update Sparagnat if applicable

Update:
- sparagnat_service.py
- routes/templates

Rules:
- If it records money movement, use account_id/payment_method_id.
- Preserve current behavior and legacy columns.

14. Update category/account services

Update:
- category_service.py
- account_service.py
- account_config_service.py

Rules:
- Existing account_options_for_forms() can remain as compatibility.
- New templates should prefer payment_form_service.py.
- Do not duplicate payment routing logic in these services.

15. UI labels

Replace misleading labels:
- Old “Account” where it means payment method -> “Payment Method”
- New “Account / Conto” where it means real account

Keep translations:
- English and Italian keys.

16. Validation search

Search the repo after changes.

Any remaining use of:
- name="account"
- account_options_for_forms
- account_payment_method
- paypal_payment_method
- payment_method free text

must be classified as:
- intentionally legacy compatibility
- old CSV display
- still to fix

Add findings to:

docs/account_payment_refactor_plan.md

17. Validation

Run:

python -m compileall money_manager

Then verify:
- Add transaction expense works with payment_method_id.
- Add transaction income works with account_id.
- Transaction detail can change payment method safely.
- Bonifico uses bank_transfer payment method.
- Payable partial payment uses payment_method_id.
- Recurring generated expense uses payment_method_id.
- Pending execution does not double-settle credit cards.
- Internal transfer still uses from/to accounts, not payment methods.
- Investment buy can specify funding account/payment method.
- Existing legacy rows still display.
- Existing analytics still load.
- User A options are separate from user B.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Files modified
- Which forms now use account_id/payment_method_id
- Which legacy account/payment fields remain and why
- Any known remaining ambiguous “account” usages


/--------------------------------------------------------------------------------------




#### Prompt 11G — Profile cleanup, account settings, backup/schema, and integrity tools


You are given the latest ZIP of my Flask Money Manager repo.

Assume Steps 1-10 and Prompts 11A-11F are already completed:
- Accounts/payment model exists.
- payment_methods.json exists.
- Ledger exists.
- Transaction schema supports account_id/payment_method_id.
- Internal transfers and credit settlements are updated.
- Forms/services mostly use Account + Payment Method.

Goal of this patch:
Clean up the remaining professional structure:
1. Move bank/IBAN ownership from Profile to Accounts.
2. Improve account/payment settings UI enough to manage the model.
3. Add integrity validation tools.
4. Update backup/schema/privacy/i18n for the new architecture.

Do not redesign the full dashboard yet. That comes after this architecture is stable.
Do not modify phone-specific UI.

PART A — Profile cleanup

1. Update profile model

Profile should represent the user, not one bank account.

Update profile.json defaults and profile_service.py.

Keep personal fields:
- first_name
- last_name
- display_name
- birth_year
- profile_image

Keep preferences elsewhere:
- theme
- language
- currency
- privacy_mode

Replace/migrate old fields:
- bank_name
- iban
- bic_swift
- default_main_account

New profile fields:
- default_current_account_id
- default_payment_method_id optional
- onboarding_completed
- profile_notes optional

Legacy fields can remain temporarily but should be marked deprecated:
- bank_name
- iban
- bic_swift
- default_main_account

2. Migrate profile bank info

If profile.json has bank_name/iban/bic_swift and the default/current account lacks those values:
- Copy them into the default current account in accounts.json.
- Do not delete profile fields immediately.
- Add migration note to migration_info.json.

If multiple current accounts exist:
- Do not guess.
- Only migrate to default_current_account_id or main_bank.
- If ambiguous, leave profile fields and add warning in integrity report.

3. Update Profile page

Update:
- money_manager/web/routes/profile.py
- money_manager/web/templates/profile/profile.html

Profile page should:
- Show personal info.
- Show preferences.
- Show default current account selector.
- Show default payment method selector.
- Remove or de-emphasize direct IBAN input.
- Add link/card:
  - “Manage bank accounts”
  - “Manage payment methods”

Profile may show a read-only summary of accounts:
- Conto name
- Bank
- masked IBAN
- payment methods count

But editing IBAN should happen in account settings, not profile.

PART B — Account/payment settings UI

4. Improve account settings page

Update:
- money_manager/web/routes/accounts/accounts.py
- money_manager/web/templates/accounts/accounts.html
- money_manager/web/templates/accounts/account_detail.html
- CSS if needed

UI should support:

Accounts:
- Add current account / Conto Corrente
- Add dependent account/wallet
- Add cash/prepaid/meal voucher account
- Edit account
- Archive account
- Close account through closure workflow
- Restore archived account
- Set as default current account
- Edit bank name/institution
- Edit IBAN
- Edit BIC/SWIFT
- Link dependent account to parent current account

Payment methods:
- Add payment method
- Edit payment method
- Archive/restore payment method
- Select method type
- Select linked account
- Select funding account
- Select settlement account
- Select liability account for credit cards
- Configure due day and statement day
- Configure delegated method for PayPal-like methods
- Show routing explanation

Keep UI practical. Do not over-design.

5. Add compatibility warnings

On account/payment settings page, show warnings if:
- Account is archived but used by active payment method.
- Payment method points to missing account.
- Payment method delegates to missing method.
- Credit card has no liability account.
- Credit card has no settlement account.
- Profile default account is archived/missing.
- Recurring rule uses archived payment method.
- Pending/credit settlement uses missing account/method.

PART C — Integrity tools

6. Add integrity service

Create:

- money_manager/services/account_integrity_service.py

Responsibilities:
- validate_accounts()
- validate_payment_methods()
- validate_transaction_snapshots()
- validate_ledger_consistency()
- validate_credit_settlements()
- validate_internal_transfers()
- validate_profile_defaults()
- validate_recurring_and_pending_references()
- validate_backup_schema_files()
- full_integrity_report(user_id=None)

Report structure:

{
  "ok": true,
  "errors": [],
  "warnings": [],
  "info": [],
  "counts": {
    "accounts": 0,
    "payment_methods": 0,
    "ledger_rows": 0,
    "transactions_without_payment_method_id": 0
  }
}

7. Add integrity page

Create route/template:

- GET /settings/integrity
- POST /settings/integrity/rebuild-ledger-preview
- POST /settings/integrity/repair-safe

or place under Profile/Settings.

Template:
- money_manager/web/templates/profile/integrity.html

Features:
- Run integrity check.
- Show errors/warnings.
- Show safe repair options.
- Preview ledger rebuild.
- Do not run destructive repair automatically.
- Require confirmation for any write.

Safe repairs may include:
- Create missing JSON/CSV files.
- Add missing CSV columns.
- Create missing payment_methods.json.
- Fill missing transaction_uid.
- Fill missing account/payment snapshots where unambiguous.
- Do not rewrite historical balances silently.

PART D — Backup/schema/privacy

8. Schema service

Update schema_service.py:
- Include payment_methods.json.
- Include account_events.json.
- Include account_ledger.csv.
- Include credit_settlements.csv.
- Include new transaction/internal transfer fields.
- Include any new profile fields.

9. Backup service

Verify backup exports/imports:
- accounts.json
- payment_methods.json
- account_ledger.csv
- credit_settlements.csv
- account_events.json
- updated profile.json
- updated transactions/internal_transfers

Add validation:
- Imported payment methods cannot reference paths outside user folder.
- Imported files cannot path-traverse.
- Imported account/payment refs are checked by integrity service after import.

10. Privacy mode

Update privacy helpers and UI display:
- Mask account IBANs.
- Mask account balances.
- Mask payment method names optionally if privacy_mode is strict.
- Mask credit liabilities.
- Mask settlement amounts.
- Keep calculations unchanged.
- Do not mask backup files.

11. i18n

Add/update English and Italian keys:
- Default current account
- Default payment method
- Manage bank accounts
- Manage payment methods
- Integrity check
- Ledger consistency
- Missing account
- Missing payment method
- Archived account still in use
- Credit card liability account
- Statement day
- Due day
- Rebuild ledger preview
- Safe repair
- Profile bank fields migrated

PART E — Final compatibility pass

12. Search and document remaining legacy fields

Search repo for:
- default_main_account
- bank_name
- iban
- bic_swift
- account_payment_method
- paypal_payment_method
- main_net_policy
- payment_logic
- account_options_for_forms
- name="account"

For each remaining usage:
- If still needed, comment/document why.
- If obsolete, replace.
- Update docs/account_payment_refactor_plan.md.

13. Validation

Run:

python -m compileall money_manager

Then verify:
- Profile page no longer treats one IBAN as the whole app bank source.
- Existing profile bank fields migrate to default current account if safe.
- Account settings can manage multiple current accounts.
- Payment methods can be managed.
- Integrity page loads.
- Integrity report detects broken references.
- Safe repair does not destroy data.
- Backup includes new files.
- Import runs integrity check after restore.
- Privacy masks account/payment sensitive data.
- Existing transactions still display.
- Existing dashboards still load.
- User A data remains separate from user B.
- No phone-specific UI was modified.
- __pycache__, .venv, cache files, and generated artifacts are not included in final ZIP.

Output:
Return the FULL updated repo as a downloadable .zip.

Also summarize:
- Files added
- Files modified
- How profile bank fields were migrated
- Account/payment settings changes
- Integrity checks implemented
- Backup/schema/privacy updates
- Remaining legacy compatibility fields and why they remain



/--------------------------------------------------------------------------------------



