TRANSACTION_FIELDS = [
    "id",
    "date",
    "category",
    "sub_category",
    "amount",
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

WEEKDAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
