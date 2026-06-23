# Scoped account model

This app now treats `main_bank` as one normal current account, not as the only real money center.

## Financial center

A financial center is an account scope that can have its own balance and planning totals. Normal current accounts use:

```json
{
  "account_kind": "current_account",
  "is_current_account": true,
  "is_financial_center": true,
  "liquidity_rollup_policy": "own_only"
}
```

`main_bank` is kept for compatibility, but it is only the default current account. Other current accounts can be created and opened with the same account-detail logic.

Independent liquid accounts, such as physical cash or CashFlow, are only global financial centers when explicitly configured as standalone:

```json
{
  "is_financial_center": true,
  "liquidity_rollup_policy": "standalone"
}
```

## Dependent account

A dependent account is a wallet or balance that belongs under another account, for example PayPal, Glovo, EasyPark, a prepaid balance, or a meal voucher wallet.

Dependent accounts should use:

```json
{
  "is_dependent_account": true,
  "parent_account_id": "main_bank",
  "liquidity_rollup_policy": "roll_up_to_parent"
}
```

`roll_up_to_parent` means the dependent balance is included when viewing the parent account scope. `own_only` means it stays local and is not added to the parent total. `standalone` makes an account act as its own financial center.

## Payment methods and cards

Cards are payment methods, not independent financial centers. A payment method can point to accounts through:

- `linked_account_id`
- `funding_account_id`
- `settlement_account_id`
- `liability_account_id`
- `delegates_to_payment_method_id`

The app prefers `payment_methods.json` for payment routing. Legacy `account.cards` is retained only for display and backward compatibility.

## Global scope

`global` means all financial centers once. It must not double-count dependent accounts that already roll up to a parent.

Use it in URLs as:

```text
/dashboard?scope=global
/analysis?scope=global
/pending?scope=global
```

## Account scope

`account:<account_id>` means one account context.

Examples:

```text
/dashboard?scope=account:main_bank
/accounts/main_bank
/pending?scope=account:main_bank
/payables?scope=account:paypal_wallet
```

For a current account, the scope includes that account plus dependent accounts only when their rollup policy allows it. For a dependent account, the scope shows the dependent account’s local view.

## Credit card settlement

Credit cards have two account concepts:

- a liability account, where the card obligation exists;
- a settlement account, usually a current account, where the real cash payment will leave.

Delayed credit-card purchases should not immediately reduce liquid current-account net unless settlement has happened. Their settlement obligation should be visible through pending/credit settlement logic under the proper settlement account.

## Compatibility

Old names still exist while templates and legacy imports are migrated:

- `main_bank`
- `main_account_transactions(df)`
- `auxiliary_total(df)`
- `main_net`
- `main_pending_total`

New code should prefer `money_manager.services.account_scope_service` and pass either `global` or `account:<id>`.

## Regression tools

Run:

```bash
python -m compileall money_manager
python tools/audit_account_payment_usage.py
python tools/check_scoped_account_model.py
```

The audit is read-only. It separates allowed compatibility/default usage from unsafe service logic and unsafe template naming.
