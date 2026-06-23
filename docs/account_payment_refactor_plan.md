# Account/payment refactor plan and audit

## Scope of this patch

This patch is intentionally non-invasive. It adds documentation and one optional audit script only. It does **not** change transaction saving, balance calculations, credit-card pending behavior, internal transfers, profile forms, account-management UI, dashboard calculations, or phone-specific UI.

## Future prompt map

| Prompt | Responsibility |
|---|---|
| 11B | Data model foundations: `payment_methods.json`, `accounts.json` schema_version 3, account IDs, method IDs, profile-bank migration plan, compatibility fields. |
| 11C | Transaction and ledger architecture: `account_ledger.csv`, `transaction_uid`, `ledger_group_id`, payment-resolution output, transaction add/edit/delete/reversal behavior. |
| 11D | Internal transfers and account lifecycle: stable `from_account_id` / `to_account_id`, dependent-account funding, close-account flow, move remaining balance, pending-transfer handling. |
| 11E | Delayed/linked payment flows: credit settlements, Pending, Recurring, Payables, Debts, Receivables, Parent Support, Expense Projects, Bonifico payment interactions. |
| 11F | UI/profile/i18n/privacy/navigation: account/payment forms, profile IBAN migration UI, labels, privacy masking, no phone-specific redesign. |
| 11G | Migration, backup/import, integrity checks, reporting/analysis verification, test fixtures, repair tools, and cleanup of legacy aliases after compatibility period. |

## Audit method

Searched these repo areas:

- `money_manager/config/`
- `money_manager/domain/`
- `money_manager/repositories/`
- `money_manager/services/`
- `money_manager/web/routes/`
- `money_manager/web/templates/`
- `money_manager/i18n/`
- `data/users/*/*.json`
- `data/users/*/*.csv` headers and representative values

Searched for these terms and aliases:

`account`, `account_key`, `account_name_snapshot`, `account_due_day_snapshot`, `account_payment_method`, `paypal_payment_method`, `payment_method`, `from_account`, `to_account`, `main_bank`, `credit_card`, `cash_flow`, `paypal`, `pre_paid_card`, `edenred`, `main_net_policy`, `payment_logic`, pending credit/card logic, internal transfers, and profile IBAN/bank fields.

## Main findings

1. The v10 code has a strong transitional layer, but the transaction CSV `account` field is still doing too much: it can mean a real account, a legacy payment alias, a category-derived account, an empty main-bank route, a PayPal credit wrapper, or a credit-settlement marker.
2. `accounts.json` already contains many future-account concepts (`type`, `iban`, `parent_account_id`, `main_net_policy`, `payment_logic`, `cards`), but `payment_logic` still lives inside accounts instead of separate payment methods.
3. Credit-card behavior is the highest-risk area. It depends on category aliases, `main_net_policy=credit_pending`, runtime account enrichment, `account_*_snapshot` fields, Pending statement aggregation, and settlement detection from descriptions.
4. Internal transfers are already modeled separately, but still save `from_account` and `to_account` as text/blank-main aliases. They create synthetic movements at runtime instead of ledger rows.
5. Profile still has one bank name/IBAN/BIC and `default_main_account`, while accounts also have `institution` and `iban`. This creates duplicate bank-info ownership.
6. Several planning/support modules call the shared transaction router, but each stores its own `account` or `payment_method` fields differently. They must migrate together to avoid hidden inconsistencies.
7. There are active templates under subfolders such as `core/`, `accounts/`, `planning/`, and `support/`, plus older root-level template duplicates. Future UI changes should edit the routed templates, not the stale duplicates.
8. Backup currently exports user data but excludes runtime folders. New account/payment/ledger files must be added to schema validation and backup/import validation.

## Audit table

| File | Function/template/section | Current field/name | Classification | Current meaning | Future meaning | Risk level | Future prompt | Notes |
|---|---|---|---|---|---|---|---|---|
| `money_manager/config/accounts.py` | constants and aliases | `MAIN_ACCOUNT_KEY`, `main_bank` | legacy_alias | Blank/main/bank values normalize to one singleton main route. | Default current-account pointer or migrated account ID. | high | 11B | Do not remove until old CSV rows and forms are migrated. |
| `money_manager/config/accounts.py` | constants and aliases | `CREDIT_OPTION_KEY`, `credit_card`, `CREDIT_ACCOUNT_ALIASES` | credit_settlement | Credit-card category/method aliases all normalize to the default credit account. | Real credit liability account plus separate card payment methods. | high | 11B/11E | Category alias and payment-method alias are currently blended. |
| `money_manager/config/accounts.py` | constants and aliases | `PAYPAL_ACCOUNT_KEY`, `PAYPAL_CREDIT_ACCOUNT_VALUE`, `PAYPAL_CREDIT_ALIASES` | payment_channel_wrapper | PayPal can mean PayPal Balance or PayPal via credit route. | Separate PayPal Balance account and PayPal channel methods. | high | 11B/11E | The alias `paypal_credit` is not a real PayPal balance movement. |
| `money_manager/config/accounts.py` | `account_options_for_forms` | `account.value`, `kind`, `payment_mode`, embedded `payment_logic` | payment_method | Account dropdown doubles as payment-routing selector. | Form should choose account where needed and payment method separately. | high | 11F | UI must stop presenting payment methods as accounts. |
| `money_manager/config/accounts.py` | `save_custom_account` | `aliases`, `category_aliases` | category_alias | Account creation can map category names to account movements. | Explicit migration rules only; no new balance logic from categories. | medium | 11B/11G | Keep for backward compatibility until ledger migration. |
| `money_manager/config/finance.py` | constants | `CREDIT_CARD_DUE_DAY`, `CREDIT_CARD_PAYMENT_CATEGORY`, `CREDIT_ACCOUNT_KEYWORDS` | credit_settlement | Global credit due day/category and aliases. | Per credit liability/payment method schedule. | high | 11E | Global constants should become defaults only. |
| `money_manager/config/user_defaults.py` | `DEFAULT_PROFILE` | `bank_name`, `iban`, `bic_swift`, `default_main_account` | profile_bank_info | One profile-level bank identity. | Bank data belongs to one or more current accounts. | high | 11B/11F | Needs one-time migration into `accounts.json`. |
| `money_manager/config/user_defaults.py` | `DEFAULT_ACCOUNTS` | `main_bank`, `cash_flow`, `credit_card`, `other_account` | real_account | Default real/virtual accounts in schema v2. | Account records in schema v3 with stable IDs. | high | 11B | Already close to target, but still missing ledger references. |
| `money_manager/config/user_defaults.py` | `DEFAULT_ACCOUNTS` | `main_net_policy`, `payment_logic` | payment_method | Stores payment behavior inside account records. | Move reusable methods/rules to `payment_methods.json`. | high | 11B | Preserve fields temporarily for compatibility. |
| `money_manager/domain/constants.py` | `TRANSACTION_FIELDS` | `account` | legacy_alias | Primary transaction route text, mixed semantics. | Legacy display field; add `account_id`/`payment_method_id`. | high | 11B/11C | The most important migration point. |
| `money_manager/domain/constants.py` | `TRANSACTION_FIELDS` | `account_key_snapshot`, `account_name_snapshot`, `account_due_day_snapshot` | credit_settlement | Credit statement stability snapshots. | Settlement/account snapshot metadata tied to ledger/event rows. | high | 11C/11E | Must preserve due dates for already-created charges. |
| `money_manager/domain/constants.py` | `TRANSACTION_FIELDS` | `payment_method` | payment_method | Bonifico marker or free-text payment note. | Stable `payment_method_id` plus label snapshot. | high | 11B/11C | Current values are inconsistent across modules. |
| `money_manager/domain/constants.py` | `TRANSACTION_FIELDS` | `iban_snapshot`, `bic_swift_snapshot`, `bank_name_snapshot` | profile_bank_info | Recipient/contact bank snapshot for transfers. | Keep as immutable recipient snapshot; add source account snapshot if needed. | medium | 11C/11E | These are not source-bank profile fields. |
| `money_manager/domain/constants.py` | `INTERNAL_TRANSFER_FIELDS` | `from_account`, `to_account` | internal_transfer | Text labels; blank means main bank. | `from_account_id`, `to_account_id` plus ledger group. | high | 11D | Must support account closure and transfer reversal. |
| `money_manager/domain/constants.py` | `PENDING_FIELDS` | `account`, `account_key`, `account_label`, `pending_kind` | credit_settlement | Pending row can be ordinary pending, credit statement, or legacy credit route. | Pending event linked to ledger/settlement record. | high | 11E | Needs careful executed-history preservation. |
| `money_manager/domain/constants.py` | `RECURRING_FIELDS` | `account` | payment_method | Recurring account can be main, aux, credit alias, PayPal alias. | Store method/account IDs at recurrence definition time. | high | 11E | Existing future generated rows must not double count. |
| `money_manager/domain/constants.py` | `SPARAGNAT_FIELDS` | `account`, account snapshots, `payment_method` | legacy_alias | Cash/help log has transaction-like fields. | Migrate like transactions or isolate from core ledger. | medium | 11E/11G | Also injects cash movements into Cash Flow account. |
| `money_manager/domain/constants.py` | `PARENT_SUPPORT_FIELDS` | `payment_method` | payment_method | Free-text/support-specific payment note. | Stable payment method or explicit note field. | medium | 11E | Currently no account ID. |
| `money_manager/domain/constants.py` | `DEBT_FIELDS`, `PAYABLE_FIELDS`, `RECEIVABLE_FIELDS` | `account` | payment_method | Chosen account/payment source for debt/payable/receivable flows. | Store selected funding account and payment method separately. | high | 11E | These modules call the shared router when paid. |
| `money_manager/domain/transaction.py` | `TransactionInput` | `account`, `account_payment_method`, `paypal_payment_method` | payment_method | Form input splits account dropdown from route choice but keeps PayPal aliases. | Payment method ID + optional account ID resolver input. | high | 11C | Good place to introduce compatibility parser. |
| `money_manager/repositories/transactions.py` | `append_transaction` | `account` and snapshots | backup/schema | Persists legacy account text plus optional credit snapshots. | Persist v2 legacy fields and new v3 fields during migration. | high | 11C | Must not break old CSV loading. |
| `money_manager/repositories/transactions.py` | `_credit_account_snapshot_for_row` | `account_key_snapshot`, due-day snapshot | credit_settlement | Captures credit due day for saved rows. | Move into settlement event/ledger metadata. | high | 11C/11E | Preserve old snapshot semantics exactly. |
| `money_manager/repositories/transactions.py` | `update_transaction` | `payment_method`, bank snapshots | backup/schema | Editable columns include account/payment/contact fields. | Edit must reverse/rebuild ledger group safely. | high | 11C | Current edit does not regenerate payment side effects. |
| `money_manager/repositories/internal_transfers.py` | CSV repository | `from_account`, `to_account` | internal_transfer | Stores text source/destination. | Store account IDs and ledger group IDs. | high | 11D | Existing CSV must migrate label/blank-main values. |
| `money_manager/repositories/parent_support.py` | CSV repository | `payment_method` | payment_method | Free text. | Stable method ID or non-ledger note. | medium | 11E | Decide whether parent support affects ledger. |
| `money_manager/services/account_config_service.py` | `normalize_accounts_config` | schema_version 2 accounts | real_account | Repairs v1/list/old account records to v2. | Upgrade to schema v3, preserving v2 compatibility fields. | high | 11B | Keep unknown fields during normalization. |
| `money_manager/services/account_config_service.py` | `normalize_account_record` | `id`, `key`, `label`, `type`, `parent_account_id` | real_account | Canonicalizes account record and aliases. | Stable account ID model. | high | 11B | Current `key` can be enough short-term but distinguish ID/key. |
| `money_manager/services/account_config_service.py` | `normalize_account_record` | `aliases`, `category_aliases` | category_alias | Old text/category values resolve to account keys. | Migration lookup only, not new logic. | medium | 11B/11G | This is needed for old data but risky for new data. |
| `money_manager/services/account_config_service.py` | `_default_payment_logic_for_normalized_account` | `payment_logic` | payment_method | Account-bound payment behavior. | Generate default methods in `payment_methods.json`. | high | 11B | Same logic duplicated in policy service. |
| `money_manager/services/account_payment_policy_service.py` | constants | `balance`, `credit`, `another_card`, insufficiency actions | payment_method | Route options for tracked-balance accounts. | Method/action rules in payment-method resolver. | high | 11B/11C | Names are route options, not real payment methods. |
| `money_manager/services/account_payment_policy_service.py` | `payment_selection_from_form` | `account_payment_method`, `paypal_payment_method` | legacy_alias | Reads new field with PayPal fallback. | Compatibility adapter mapping old forms to method IDs. | high | 11C | Good migration seam. |
| `money_manager/services/account_service.py` | `enrich_transactions_with_accounts` | runtime `account_key`, `account_label`, `account_route_source` | dashboard_aggregation | Infers account effects at read time. | Ledger reader should replace inference for new rows. | high | 11C/11G | Keep for old rows after migration. |
| `money_manager/services/account_service.py` | `_infer_account_from_row` | `account`, category aliases, PayPal credit aliases | legacy_alias | Chooses account from explicit text, cleanup hints, or category. | Legacy migration resolver only. | high | 11C/11G | High risk of wrong account/payment meaning. |
| `money_manager/services/account_service.py` | `_affects_main_net_mask` | `main_net_policy`, credit settlement masks | dashboard_aggregation | Determines which rows count in main net. | Main net should be ledger sum over selected current accounts. | high | 11C | Current logic is correct for v10 but fragile. |
| `money_manager/services/account_service.py` | `_account_signed_amount` | account balance direction inference | dashboard_aggregation | Converts tx rows into account balance impacts. | Ledger movement signs should be stored explicitly. | high | 11C | Sign logic is central to every balance. |
| `money_manager/services/account_service.py` | `_credit_settlement_like_mask`, `_is_credit_settlement_row` | description/subcategory heuristics | credit_settlement | Detects statement payment by text. | Explicit settlement event/type. | high | 11E | Description parsing must be eliminated for new rows. |
| `money_manager/services/account_service.py` | `_paypal_credit_linked_paypal_movements` | PayPal credit linked view | payment_channel_wrapper | Shows PayPal channel trace without PayPal balance effect. | Payment-channel event or method snapshot. | medium | 11C/11E | Useful UX concept; should not be balance logic. |
| `money_manager/services/account_service.py` | `_sparagnat_cash_movements` | `cash_flow` synthetic movements | category_alias | Injects Sparagnat cash into Cash Flow. | Either ledger integration or separate support feature. | medium | 11E/11G | Needs explicit decision. |
| `money_manager/services/transaction_service.py` | `save_transaction_payload` | `account`, `payment_method`, `insufficient_action` | payment_method | Main router for expenses through aux/credit/main. | Payment resolver and ledger writer. | high | 11C | Core money logic; change only after tests. |
| `money_manager/services/transaction_service.py` | `_save_balance_account_expense` | route methods `balance`, `credit`, `another_card` | payment_method | Splits tracked-balance checkout based on route. | Explicit method rules and split ledger movements. | high | 11C | Handles insufficient balance behavior. |
| `money_manager/services/transaction_service.py` | `_save_credit_account_charge` | `credit_card` pending grouping | credit_settlement | Saves purchase now; Pending later groups statement. | Liability ledger movement + settlement event. | high | 11C/11E | Must preserve no-main-net-on-purchase behavior. |
| `money_manager/services/transaction_service.py` | `_append_balance_credit_pending` | `paypal_credit` / `credit` | payment_channel_wrapper | Creates old pending credit route for balance account checkout. | Payment method with funding/settlement account. | high | 11E | PayPal-specific branch should become generic. |
| `money_manager/services/transaction_service.py` | `update_existing_transaction`, `delete_existing_transaction` | transaction edit/delete | backup/schema | Edits/deletes CSV row only. | Reverse/rebuild ledger and related pending/settlement rows. | high | 11C | One of the highest-risk future changes. |
| `money_manager/services/pending_service.py` | `pending_total` | `account`, aux skip, credit statement include | credit_settlement | Calculates expected main-account outflow. | Pending impact should come from settlement events. | high | 11E | Must handle pending paid from non-main current accounts. |
| `money_manager/services/pending_service.py` | `process_pending` | credit grouping and execution | credit_settlement | Executes due credit rows and ordinary pending rows. | Settlement processor creates ledger movements. | high | 11E | Executed pending history must be stable. |
| `money_manager/services/pending_service.py` | `sync_credit_account_statements` | statement aggregation by `account_key`, month, due day | credit_settlement | Creates one pending statement row per closed month/account. | Credit settlement table/event. | high | 11E | Should migrate to `credit_settlements.csv` or equivalent. |
| `money_manager/services/pending_service.py` | `_execute_pending_row` | pending row becomes transaction | credit_settlement | Writes settlement/payment transaction when executed. | Execute event writes ledger and marks event executed. | high | 11E | Must avoid duplicate transaction creation. |
| `money_manager/services/pending_service.py` | `_credit_pending_key` | PayPal/credit aliases | legacy_alias | Normalizes legacy credit pending values. | Compatibility mapper only. | medium | 11E/11G | Keep until old pending rows are migrated. |
| `money_manager/services/recurring_service.py` | `_credit_style_key`, `_pending_account_for_rule` | `account` as credit/main/aux route | credit_settlement | Recurring rules generate pending rows with old account values. | Store payment method/account IDs in recurring rules. | high | 11E | Future charges must preserve due-day behavior. |
| `money_manager/services/internal_transfer_service.py` | `validate_transfer` | `from_account`, `to_account`, `move_all` | internal_transfer | Checks balances and normalizes labels. | Account-ID transfer command. | high | 11D | Good base for close-account/move-all flow. |
| `money_manager/services/internal_transfer_service.py` | `_append_configured_topup_fee` | metadata `topup_fee_amount` | internal_transfer | Optional fee for top-up from main to target. | Transfer policy/event with ledger rows. | medium | 11D | Fee should be a separate transaction/ledger group. |
| `money_manager/services/internal_transfer_service.py` | `main_account_transfer_movements`, `auxiliary_transfer_movements` | synthetic transfer movements | dashboard_aggregation | Runtime movements used in balances. | Real ledger movements. | high | 11D/11C | Avoid double-counting when ledger is introduced. |
| `money_manager/services/bonifico_service.py` | `create_bonifico_from_form` | `account`, `payment_method=bonifico`, recipient snapshots | payment_method | Bank transfer uses account router plus contact snapshot. | Bonifico payment method with source account and recipient bank snapshot. | high | 11E/11F | Must work with debts/payables/contact autofill. |
| `money_manager/services/bonifico_service.py` | linked debt/payable/receivable handling | `source_account`, `payment_selection` | payment_method | Uses Bonifico to pay/collect linked items. | Method-specific flow writing ledger/event links. | high | 11E | Must not bypass payable/debt balance updates. |
| `money_manager/services/contact_service.py` | contact bank fields | `iban`, `bic_swift`, `bank_name` | profile_bank_info | Recipient bank data. | Keep as contact payment destination metadata. | medium | 11E/11F | Different from user's source bank accounts. |
| `money_manager/services/debt_service.py` | payment helpers | `account`, `account_payment_method`, pending debt source | payment_method | Debt payoff creates transactions/pending through shared router. | Debt payment event references method/account IDs. | high | 11E | Must update pending debt registration too. |
| `money_manager/services/payable_service.py` | `pay_item` | `account`, `account_payment_method` | payment_method | Payable payment uses shared router. | Payable event references payment method and ledger group. | high | 11E | Payable remaining updates must be atomic with ledger. |
| `money_manager/services/receivable_service.py` | `create_receivable_from_form`, collection | `account` | payment_method | Loan/collection account is chosen as source/destination. | Funding/collection account ID plus payment method. | high | 11E | Receivable creation can create an expense immediately. |
| `money_manager/services/expense_project_service.py` | planned item payment | `account`, `account_payment_method` | payment_method | Project/payable planned items route payments. | Project movement references ledger group. | high | 11E | Needs consistency with Payables. |
| `money_manager/services/parent_support_service.py` | entries/rules | `payment_method` | payment_method | Free-text method note. | Stable payment method or explicit non-ledger note. | medium | 11E | Decide whether to convert to ledger-affecting flows. |
| `money_manager/services/quick_log_service.py` | quick cards/forms | `from_account`, `to_account`, `account`, `payment_method`, `account_payment_method` | payment_method | Fast entry passes through different module-specific fields. | Quick entry should call same resolver as full forms. | high | 11E/11F | Easy place to miss during UI refactor. |
| `money_manager/services/profile_service.py` | profile normalization/display | `bank_name`, `iban`, `bic_swift`, `default_main_account` | profile_bank_info | Profile-owned single bank fields. | Current-account records and defaults. | high | 11B/11F | Keep display fallback after migration. |
| `money_manager/services/backup_service.py` | export/import | user data files, schema validation | backup/schema | Exports user folder excluding `cache`, `plots`, `backups`. | Include new account/payment/ledger files and validate them. | medium | 11G | No direct keyword hit for account, but backup must be updated. |
| `money_manager/services/yearly_summary_service.py` | transfer summaries | `from_account`, `to_account` | analysis_filter | Displays transfer route labels. | Read ledger transfer groups. | medium | 11G | Analysis should not parse text transfer fields later. |
| `money_manager/web/routes/accounts/accounts.py` | account CRUD routes | account form fields | real_account | Creates/updates/archive account records. | Schema v3 account UI/handler. | medium | 11F | Active routed template is `accounts/accounts.html`. |
| `money_manager/web/routes/accounts/internal_transfers.py` | transfer page route | internal transfer forms | internal_transfer | Saves transfer text rows. | Transfer command with stable account IDs. | high | 11D/11F | Keep credit accounts excluded unless design changes. |
| `money_manager/web/routes/core/transactions.py` | add/detail/update/delete routes | account/payment form submission | payment_method | Receives form values and calls transaction service. | Must pass method/account IDs and handle resolver failures. | high | 11C/11F | Active template is `core/add_transaction.html`. |
| `money_manager/web/routes/bonifico.py` | Bonifico routes/API | account, contact bank fields | payment_method | Renders transfer form and contact JSON. | Method-specific source/destination flow. | high | 11E/11F | Requires account options without credit containers. |
| `money_manager/web/routes/onboarding.py` | first-login setup | `main_bank_name`, profile/default account | profile_bank_info | Stores bank name in profile and updates main account institution. | Create/update default current account record. | high | 11B/11F | Onboarding should not create duplicate bank sources. |
| `money_manager/web/routes/profile.py` | profile form | profile bank fields and default account | profile_bank_info | Edits one profile IBAN/bank plus default main account. | Select/manage current accounts instead. | high | 11F | Privacy masking must continue. |
| `money_manager/web/templates/core/add_transaction.html` | add transaction forms | account dropdown, `account_payment_method` | payment_method | Account dropdown controls both account and payment mode UI. | Separate payment-method selector with resolver preview. | high | 11F | Do not edit old root duplicate by mistake. |
| `money_manager/web/templates/core/transaction_detail.html` | edit form/details | account selector, `payment_method`, bank snapshots | payment_method | Edits account text only; shows transfer snapshots. | Ledger-aware edit/delete with immutable transfer snapshots. | high | 11C/11F | Existing edit cannot update pending side effects. |
| `money_manager/web/templates/accounts/accounts.html` | account management UI | account type, `main_net_policy`, IBAN, cards | real_account | User edits account config and embedded card list. | Account UI plus separate payment-method/card UI. | high | 11F | Cards should likely become payment methods. |
| `money_manager/web/templates/accounts/internal_transfers.html` | transfer UI | `from_account`, `to_account`, `move_all` | internal_transfer | Transfer between account options. | Stable ID transfer and close-account support. | high | 11D/11F | Preserve current move-all UX. |
| `money_manager/web/templates/planning/pending.html` | pending UI | `account`, credit statement details | credit_settlement | Pending table handles credit statement rows. | Settlement event table/view. | high | 11E/11F | Needs explicit settlement-account display. |
| `money_manager/web/templates/planning/recurring.html` | recurring UI | `account` selector | payment_method | Rule stores account text/alias. | Rule stores payment method/account IDs. | high | 11E/11F | Active routed template. |
| `money_manager/web/templates/planning/payables.html` | payables UI | `account`, `account_payment_method` | payment_method | Payable payment uses account dropdown and route choice. | Payable payment resolver preview. | high | 11E/11F | Also check planning/project templates. |
| `money_manager/web/templates/support/debts.html` | debts UI | `account`, account payment fields | payment_method | Debt payoff selected route. | Debt payment resolver. | high | 11E/11F | May also generate pending debt rows. |
| `money_manager/web/templates/support/receivables.html` | receivables UI | `account` | payment_method | Loan/collection route. | Funding/collection account IDs. | high | 11E/11F | Creation and collection have different money direction. |
| `money_manager/web/templates/support/parent_support.html` | parent support UI | `payment_method` text | payment_method | Free text. | Stable method or note-only field. | medium | 11E/11F | Decide whether ledger-affecting. |
| `money_manager/web/templates/support/sparagnat.html` | sparagnat UI | `account` text | legacy_alias | Free text cash/card/none. | Explicit account/method or non-ledger support log. | medium | 11E/11F | Current cash injection is implicit. |
| `money_manager/i18n/en.json`, `money_manager/i18n/it.json` | translation labels | account/payment/profile/IBAN labels | i18n/UI label | Existing labels describe v10 concepts. | Add labels for current accounts, payment methods, ledgers, settlements. | low | 11F | Do after model names are settled. |
| `data/users/fiengokineton/accounts.json` | user config | schema_version 2, account records | real_account | User-specific accounts include main, cash, prepaid, EdenRed, PayPal, children, credit card. | Migrate to schema v3 and generate payment methods. | high | 11B/11G | Preserve account keys as legacy aliases. |
| `data/users/fiengokineton/profile.json` | user profile | `bank_name`, `iban`, `bic_swift`, `default_main_account` | profile_bank_info | Single profile bank fields. | Move to default current account; retain compatibility. | high | 11B/11G | Existing IBAN value is sample-like but still sensitive. |
| `data/users/fiengokineton/expenses.csv`, `incomes.csv`, `investments.csv`, `sparagnat_fottut.csv` | CSV headers | `account`, snapshots, `payment_method`, bank snapshots | backup/schema | Transaction records with mixed account/payment meanings. | Add new IDs and ledger group fields; keep old columns. | high | 11C/11G | Migration must be row-by-row. |
| `data/users/fiengokineton/pending.csv` | CSV headers/data | `account`, `account_key`, `account_label`, `pending_kind`, `statement_month` | credit_settlement | Pending and credit statement rows. | `credit_settlements.csv` or equivalent event records. | high | 11E/11G | Preserve executed pending rows. |
| `data/users/fiengokineton/internal_transfers.csv` | CSV headers | `from_account`, `to_account` | internal_transfer | Text transfer endpoints. | Account IDs and ledger group. | high | 11D/11G | Needs migration before account close. |
| `data/users/fiengokineton/debts.csv`, `payables.csv`, `receivables.csv`, `recurring.csv`, `parent_support*.csv` | CSV headers | `account`, `payment_method` | payment_method | Module-specific payment/account columns. | Module rows should reference method/account IDs. | high | 11E/11G | Must be migrated with services. |
| root-level duplicate templates such as `money_manager/web/templates/add_transaction.html`, `accounts.html`, `pending.html` | stale/legacy templates | account/payment form fields | i18n/UI label | Older duplicates still contain account/payment fields but are not routed by current blueprints. | Remove or keep only after confirming not used. | medium | 11F/11G | Avoid editing these instead of active subfolder templates. |

## Highest-risk areas for later implementation

1. **Credit settlement**: currently depends on snapshots, pending rows, aliases, statement-month grouping, and description heuristics.
2. **Transaction edit/delete**: currently updates/deletes CSV rows without reversing related pending or future ledger side effects.
3. **Main net vs account balance**: currently inferred at read time from mixed fields, category aliases, and synthetic transfer rows.
4. **PayPal / PayPal credit**: PayPal Balance and PayPal as payment-channel wrapper are intentionally separated only by compatibility heuristics.
5. **Internal transfers and close-account flow**: transfer rows are text-based and do not yet create durable ledger rows.
6. **Profile bank info**: source-bank data exists both in profile and account records.
7. **Cross-module flows**: Bonifico, Payables, Debts, Receivables, Recurring, Pending, Parent Support, Expense Projects, Investments, and Quick Log all touch account/payment fields differently.

## Prompt 11F implementation notes

### Shared form context

Added `money_manager/services/payment_form_service.py` as the shared source for account/payment-method options. New templates should use it instead of the legacy `account_options_for_forms()` dropdown when the field means a real balance container. The helper returns account options, payment method options, compatibility reasons, default methods, and user-facing routing explanations.

### Forms and services moved to stable IDs

The following money-moving paths now accept and persist stable `account_id` and/or `payment_method_id` while keeping old CSV text fields for backward compatibility:

- Add Transaction: expense/investment forms show Account / Conto and Payment Method / Metodo di pagamento; income uses Account / Conto.
- Transaction Detail/Edit: account/payment method selectors are present and edits flow through the Prompt 11D safe edit path.
- Bonifico: source account is `account_id`; payment method is a bank-transfer `payment_method_id`; contact snapshots remain unchanged. It only records a Money Manager transaction and never executes a real bank transfer.
- Payables: preferred account/payment method are stored on the payable; every partial payment can submit its own `payment_method_id` and calls `save_transaction_payload()`.
- Debts: debt payoff uses `payment_method_id`; pending debt payments carry `account_id`/`payment_method_id` into execution.
- Receivables: receivable creation uses payment method for money leaving; collection uses receiving `account_id` and routes through `save_transaction_payload()` instead of direct append.
- Recurring rules: stored rules and generated pending rows carry `account_id`, `payment_method_id`, and a future `payment_resolution_template_json` field.
- Pending: manual execution of non-credit pending rows now routes through `save_transaction_payload()` with stable IDs when present; credit settlements remain delegated to `credit_settlement_service.py`.
- Expense Projects: planned items store preferred account/payment method; actual project payments pass `payment_method_id` to the transaction service.
- Parent Support and Sparagnat: new account/payment-method ID fields are persisted where the trackers record payment context; legacy display text remains.
- Investments: market assets can store a default funding account/payment method, while actual buy/sell/dividend cash movement should be logged as investment transactions with Account / Payment Method.
- Quick Log: special logging now carries `account_id` and `payment_method_id`; transfers use `from_account_id`/`to_account_id` while keeping legacy aliases.

### Legacy fields intentionally kept

These remain on purpose:

- `account` in transaction-like CSVs: old rows and old analytics still display it; it also acts as a legacy fallback when stable IDs are missing.
- `account_payment_method` and `paypal_payment_method`: compatibility aliases still parsed by `TransactionInput` and `account_payment_policy_service.py` so old forms, old rows, and old PayPal routes do not crash.
- `payment_method` free text in Parent Support: kept as display/backward-compatibility text; new `payment_method_id` is now stored alongside it.
- Root duplicate templates such as `money_manager/web/templates/add_transaction.html`, `transaction_detail.html`, and some root planning/support copies: classified as legacy duplicate template copies. The registered blueprints use the grouped `core/`, `planning/`, `support/`, `assets/`, and `bonifico/` templates.
- `account_options_for_forms()` in `money_manager/config/accounts.py`, `money_manager/config/__init__.py`, `category_service.py`, and `profile.py`: compatibility for profile/account-management UI and older category helpers. New money-movement forms should prefer `payment_form_service.py`.

### Remaining ambiguous account usages found by validation search

- Hidden `name="account"` fields in the new forms are intentional compatibility shims so old CSV display and fallback services still receive a legacy account value.
- `name="account"` in root duplicate templates is legacy/dead-copy risk, not the primary registered route path.
- `account_payment_method` occurrences in services are legacy fallback adapters only; new forms should submit `payment_method_id`.
- Parent Support templates still show the old `payment_method` text input for display/backward compatibility; stored ID fields now exist, but the UI can be polished further in a later visual pass.
- Sparagnat templates still expose a simple legacy account text field. The service now accepts stable IDs, but this tracker was intentionally left visually simple because it is not a core ledger screen.

### Validation performed

- `python -m compileall money_manager` completed successfully.
- Jinja templates under `money_manager/web/templates` parsed successfully with no syntax errors.
- Validation search results were reviewed and classified above.

## Prompt 11G implementation notes

### Profile cleanup and bank-field migration

`profile.json` now represents the person using the app, not a single bank account. The active profile model keeps identity fields, default account/payment-method pointers, onboarding state, notes, and deprecated compatibility fields. Preferences remain in `preferences.json`.

Legacy `bank_name`, `iban`, and `bic_swift` are copied into the default current account only when this is safe. The migration targets `default_current_account_id` first, then the legacy `default_main_account`, then `main_bank`. Existing account bank data is never overwritten. The deprecated profile fields are kept so older imports/pages remain safe. Each migration attempt writes a `profile_bank_fields_migration` entry in `migration_info.json`.

If no safe current-account target exists, or the chosen target is not a current account, the profile bank fields stay in place and the integrity report raises a warning instead of guessing.

### Account and payment settings

The account settings page now manages both sides of the model:

- accounts can be added, edited, archived/restored, closed through the existing closure workflow, and marked as the default current account;
- account records expose institution/bank name, IBAN, BIC/SWIFT, initial balance, aliases, category aliases, due/statement day, and parent-account linking;
- dependent/wallet accounts can link to a parent current account or legacy container bucket;
- payment methods can be added, edited, archived/restored, marked as default, linked to accounts, configured with funding/settlement/liability accounts, due/statement days, aliases, settlement mode, and delegated PayPal-like routing;
- payment-method rows show a human-readable routing explanation.

### Integrity tools

Added `money_manager/services/account_integrity_service.py` and `/settings/integrity`.

The full report validates accounts, payment methods, transaction snapshots, ledger rows, credit settlements, internal transfers, profile defaults, recurring/pending references, and backup/schema files. It reports `ok`, `errors`, `warnings`, `info`, and counts for accounts, payment methods, ledger rows, and transaction rows without payment-method IDs.

The integrity page can show the report, preview ledger rebuild coverage, and run conservative safe repairs only after confirmation. Safe repair creates missing files, adds missing CSV columns, creates/repairs `payment_methods.json`, fills missing `transaction_uid`, and fills account/payment snapshots only when the IDs are unambiguous. It does not silently rewrite historical balances or destructive ledger history.

### Backup, schema, privacy, and i18n

`schema_service.py` already covers the architecture files and now remains the repair entry point for `payment_methods.json`, `account_events.json`, `account_ledger.csv`, `credit_settlements.csv`, updated transaction/internal-transfer CSV fields, and profile defaults.

Backup export runs schema repair first and therefore includes the new account/payment/ledger/settlement/event files. Import validates ZIP paths, blocks traversal, rejects excluded runtime folders, validates `payment_methods.json` for unsafe path-like values, restores into the current user's folder only, runs schema repair, then runs the integrity report after restore.

Privacy masking is applied to profile/account summaries, account balances, IBAN displays, payment-method display names, credit liabilities, and settlement/balance amounts through the existing privacy filters. Backup files are not masked because backup/export must preserve raw data.

English and Italian i18n keys were added for default current account, default payment method, management links, integrity checks, ledger consistency, missing account/method warnings, archived references, credit-card liability/settlement fields, statement/due day, rebuild preview, safe repair, and profile bank-field migration.

### Remaining legacy compatibility fields after 11G

These fields remain intentionally:

- `default_main_account`: deprecated profile fallback used by older profile files and account-closure cleanup. New UI writes `default_current_account_id`.
- `bank_name`, `iban`, `bic_swift`: deprecated in profile, authoritative on current accounts. They stay in profile only for migration compatibility and import safety.
- `account_payment_method` and `paypal_payment_method`: legacy form aliases still parsed by compatibility adapters so older routes/rows do not crash. New forms should submit `payment_method_id`.
- `main_net_policy` and `payment_logic`: account-side compatibility fields still required by dashboards, legacy account inference, and older credit-pending behavior until the dashboard becomes fully ledger-derived.
- `account_options_for_forms()`: legacy dropdown helper retained for old category/account displays. New money-movement forms should use `payment_form_service.py` helpers.
- `name="account"`: still present in old/root duplicate templates and some compatibility hidden fields so legacy CSV display/fallback code can continue reading old rows.
