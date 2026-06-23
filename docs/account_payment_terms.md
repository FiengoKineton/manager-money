# Account/payment terminology

This document fixes the vocabulary for the account/payment refactor. The important rule is simple: **an account is where money or liability lives; a payment method is how a transaction is paid.** The current v10 code still mixes those two ideas in several fields, so later prompts should use these terms consistently before changing balance logic.

## A. Account / Conto

An **Account / Conto** is a real balance container. It answers: **where does the money, asset cash, voucher balance, or liability balance live?**

Examples:

- Conto Corrente Intesa
- Conto Corrente Revolut
- Cash
- PayPal Balance
- Prepaid Card Balance
- EdenRed / meal voucher balance
- Investment cash account
- Credit card liability account

Implementation target:

- A future account should have a stable `account_id`.
- It should be stored in `accounts.json` schema_version 3.
- It should be balance-affecting only through ledger movements, not through category-name guessing.
- It may have bank details such as institution, IBAN, BIC/SWIFT, currency, opening balance, closing status, and parent/dependency metadata.

Do **not** use "account" to mean a card, a checkout route, or a vague text note like `cash / card / bank`.

## B. Payment Method / Metodo di pagamento

A **Payment Method / Metodo di pagamento** is a way to pay. It answers: **which instrument or channel did the user use at checkout or transfer time?**

Examples:

- Debit card linked to Conto Intesa
- Credit card linked to Conto Intesa
- Bonifico from Conto Intesa
- PayPal balance
- PayPal via debit card
- PayPal via credit card
- Cash
- EdenRed

Implementation target:

- A future payment method should have a stable `payment_method_id`.
- It should be stored in a new per-user `payment_methods.json`.
- It should resolve to one or more ledger movements through a payment-resolution layer.
- It may reference a linked account, funding account, settlement account, card metadata, channel metadata, and settlement rules.

Do **not** store a payment method as the transaction's real account. A transaction paid with "PayPal via credit card" is not the same thing as a transaction paid from "PayPal Balance".

## C. Funding account

The **funding account** is the account that ultimately funds a payment.

Examples:

- A debit card payment may have `payment_method_id=debit_card_intesa` and `funding_account_id=conto_intesa`.
- A PayPal checkout funded by a debit card may have `payment_method_id=paypal_via_debit_card` and `funding_account_id=conto_intesa`.
- A cash expense may have `payment_method_id=cash` and `funding_account_id=cash`.

The funding account is not always visible to the merchant. It is the app's accounting source of money.

## D. Settlement account

The **settlement account** is the account used to settle delayed payments, especially credit cards.

Examples:

- A credit card purchase creates a liability in a credit liability account.
- The monthly card statement is later paid from `conto_intesa`.
- In that case, the credit card liability account tracks the debt, while `conto_intesa` is the settlement account.

The settlement account should be locked into the future credit settlement/event record when the settlement is created, so changing a card's default settlement account later does not rewrite old history by accident.

## E. Linked account

A **linked account** is the account directly represented by a method.

Examples:

- A "PayPal balance" method is linked directly to the PayPal Balance account.
- A "Prepaid Card Balance" method is linked directly to the Prepaid Card Balance account.
- A "Cash" method is linked directly to the Cash account.

A method can have a linked account and still be funded elsewhere under special rules. For example, topping up a prepaid card from a current account creates movements in both accounts.

## F. Dependent account

A **dependent account** is a wallet/account that depends on or is linked to another current account.

Examples:

- A prepaid card balance funded from a current account.
- A meal voucher balance funded through employer income rules.
- A PayPal balance that may be topped up or used as a payment channel.

Dependent accounts need explicit funding rules. They should not rely on category aliases such as `Pre-paid card` or `PayPal` to guess whether a row is a top-up, a purchase, or a channel-only wrapper.

## G. Current account / Conto Corrente

A **Current account / Conto Corrente** is a main bank account that can fund cards, transfers, bills, mortgages, and settlements.

Examples:

- Conto Corrente Intesa
- Conto Corrente Revolut
- Conto Corrente UniCredit

Implementation target:

- The old single `main_bank` route should become one or more real current accounts.
- The user's profile-level `bank_name`, `iban`, `bic_swift`, and `default_main_account` should migrate into account records.
- A user can have multiple current accounts, and one of them may be the default funding/settlement account.

## H. Credit liability account

A **credit liability account** is a liability bucket used to track credit card purchases before settlement.

Examples:

- Credit Card liability account
- Visa Intesa monthly statement bucket
- PayPal via credit-card liability route, if PayPal is only the checkout wrapper and the card creates the debt

Implementation target:

- Purchases increase the liability on charge date.
- Statement settlement decreases the liability and reduces the settlement/funding account.
- The app should keep statement month, due date, settlement account, and source charge IDs stable.

## I. Ledger movement

A **ledger movement** is a row that explains how a transaction affects balances.

Examples:

- Expense paid from Cash: one ledger movement, Cash decreases.
- Transfer from Conto Intesa to Prepaid: two ledger movements, Intesa decreases and Prepaid increases.
- Credit card purchase: one liability movement on purchase date, then a settlement group later.
- PayPal via credit card: possible channel event plus credit liability movement, but no PayPal Balance decrease.

Implementation target:

- Add `account_ledger.csv` later.
- Each movement should include `ledger_group_id`, `transaction_uid`, `account_id`, signed amount, movement type, date, source module, and reversal/reference fields.
- Balances and analysis should eventually read from the ledger, not infer account effects from mixed text fields.

## J. Payment resolution

**Payment resolution** is the result of applying a payment-method rule to a transaction.

It answers:

- Which account is funded immediately?
- Is there a linked account?
- Is there a settlement account?
- Does this create a pending row?
- Does this create a liability movement?
- Does the transaction affect main net now, later, or never?
- Which ledger movements should be created?

Implementation target:

- The resolver should take `transaction_type`, `amount`, `date`, `payment_method_id`, optional `account_id`, optional settlement details, and module context.
- The resolver should return a deterministic object that can be saved, tested, reversed, and explained.

## Legacy v10 mapping guidance

| v10 item | Current meaning | Future target |
|---|---|---|
| `account` transaction CSV column | Mixed: real account, payment method, legacy alias, empty means main route | Keep temporarily as legacy text, add `account_id` and `payment_method_id` |
| `account_key_snapshot` | Credit-account routing snapshot for due-day stability | Replace/augment with stable `account_id` and settlement event metadata |
| `account_name_snapshot` | Label snapshot for credit rows | Account snapshot metadata only, not primary identity |
| `account_due_day_snapshot` | Due-day snapshot for credit statement grouping | Credit settlement schedule/event metadata |
| `payment_method` | Mixed free text: bonifico marker, parent-support note, account-payment selection | Stable `payment_method_id` plus optional display snapshot |
| `account_payment_method` | Form-only route choice: balance/credit/another_card | Payment resolver input, then explicit method ID or route option |
| `paypal_payment_method` | Backward-compatible alias of `account_payment_method` | Remove after migration; map to PayPal-specific payment methods |
| `from_account` / `to_account` | Internal transfer text labels/blank-main alias | Stable `from_account_id` / `to_account_id` and ledger group |
| `main_bank` | Singleton main-route account key | One current-account record or a default current-account pointer |
| `credit_card` | Default credit liability account key and category alias | Real credit liability account plus payment methods/cards linked to it |
| `cash_flow`, `pre_paid_card`, `edenred`, `paypal` | Mostly real accounts, sometimes category aliases/payment methods | Real accounts with separate payment methods and explicit funding rules |
