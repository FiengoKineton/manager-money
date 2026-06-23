# Ledger layer and payment routing notes

Prompt 11C adds an accounting foundation without replacing the current v10 dashboard/account calculations yet.

## Concept split

- Transaction: what happened.
- Payment method: how it was paid.
- Account: where balance lives.
- Ledger movement: how balances are affected.

## Sign convention

The new ledger uses one consistent convention:

- Asset accounts use positive balances.
- Income/cash-in movements increase assets with positive `signed_amount`.
- Expenses/cash-out movements reduce assets with negative `signed_amount`.
- Liability accounts use negative balances for amounts owed.
- A credit-card purchase posts `credit_liability_increase` with a negative `signed_amount` on the credit liability account.
- Later settlement will use two movements: `credit_settlement_cash_out` on the current account and `credit_liability_decrease` on the credit liability account.

## Prompt 11C integration boundary

The ledger services are side-effect safe unless their append/write helpers are called explicitly. Existing pages still use the v10 calculations:

- dashboard/overview
- account detail calculations
- Pending page credit statement behavior
- add-transaction form behavior

Full form migration is intentionally left for Prompts 11D-11F.
