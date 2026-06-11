TRANSACTION_FIELDS = [
    "id",
    "date",
    "category",
    "sub_category",
    "amount",
    "original_amount",
    "original_currency",
    "exchange_rate_to_eur",
    "exchange_correction_to_eur",
    "exchange_effective_rate_to_eur",
    "account",
    "description",
    "created_at",
]

PENDING_FIELDS = [
    "id",
    "type",
    "date_due",
    "amount",
    "category",
    "account",
    "description",
    "status",
    "source",
    "source_id",
]

RECURRING_FIELDS = [
    "id",
    "name",
    "type",
    "amount",
    "frequency",
    "day_of_month",
    "category",
    "account",
    "start_date",
    "last_generated",
]

SPARAGNAT_FIELDS = [
    "id",
    "date",
    "kind",
    "person",
    "category",
    "amount",
    "original_amount",
    "original_currency",
    "exchange_rate_to_eur",
    "exchange_correction_to_eur",
    "exchange_effective_rate_to_eur",
    "account",
    "description",
    "created_at",
]

PARENT_SUPPORT_FIELDS = [
    "id",
    "date",
    "kind",
    "parent",
    "category",
    "amount",
    "payment_method",
    "description",
    "created_at",
]

PARENT_SUPPORT_RULE_FIELDS = [
    "id",
    "name",
    "kind",
    "parent",
    "category",
    "monthly_amount",
    "day_of_month",
    "start_date",
    "end_date",
    "payment_method",
    "description",
    "active",
    "created_at",
]

DEBT_FIELDS = [
    "id",
    "name",
    "creditor",
    "original_amount",
    "remaining_amount",
    "category",
    "account",
    "start_date",
    "due_date",
    "description",
    "status",
    "created_at",
    "closed_at",
]

DEBT_RULE_FIELDS = [
    "id",
    "debt_id",
    "name",
    "rule_type",
    "amount",
    "frequency",
    "day_of_month",
    "start_date",
    "payoff_date",
    "last_generated",
    "active",
]

RECEIVABLE_FIELDS = [
    "id",
    "name",
    "debtor",
    "original_amount",
    "remaining_amount",
    "account",
    "start_date",
    "due_date",
    "description",
    "status",
    "linked_expense_transaction_id",
    "created_at",
    "closed_at",
]

PAYABLE_FIELDS = [
    "id",
    "name",
    "payee",
    "original_amount",
    "remaining_amount",
    "category",
    "account",
    "start_date",
    "due_date",
    "description",
    "status",
    "created_at",
    "closed_at",
]

INVESTMENT_ASSET_FIELDS = [
    "id",
    "symbol",
    "label",
    "allocation_pct",
    "currency",
    "active",
    "created_at",
]

WEEKDAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
