# app_backup.py
from __future__ import annotations

import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from config import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    INVESTMENT_CATEGORIES,
)

# ---------------------------------------------------------------------
# Paths (adjust if your layout is different)
# ---------------------------------------------------------------------
DATA_DIR = Path("data")
EXPENSES_CSV = DATA_DIR / "expenses.csv"
INCOMES_CSV = DATA_DIR / "incomes.csv"
INVESTMENTS_CSV = DATA_DIR / "investments.csv"

url_for('documents_background', filename='background.jpg')

app = Flask(__name__)

@app.route("/documents-background/<path:filename>")
def documents_background(filename):
    return send_from_directory("Documents", filename)

# ---------------------------------------------------------------------
# CSV helpers (no pandas, no numpy)
# ---------------------------------------------------------------------
def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_csv(path: Path, ttype: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = dict(raw)
            row["type"] = ttype

            # id
            try:
                row["id"] = int(row.get("id", "") or 0)
            except Exception:
                row["id"] = 0

            # date
            ds = row.get("date", "") or ""
            try:
                dt = datetime.fromisoformat(ds)
            except Exception:
                dt = None
            row["_date_obj"] = dt
            row["date_str"] = ds

            # amount
            amt_raw = row.get("amount", "0") or "0"
            try:
                amt = float(amt_raw.replace(",", "."))
            except Exception:
                amt = 0.0
            row["amount_float"] = amt
            row["amount_str"] = f"{amt:.2f}"

            rows.append(row)
    return rows


def load_all_simple() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rows.extend(_load_csv(EXPENSES_CSV, "expense"))
    rows.extend(_load_csv(INCOMES_CSV, "income"))
    rows.extend(_load_csv(INVESTMENTS_CSV, "investment"))

    # newest first
    rows.sort(
        key=lambda r: (r["_date_obj"] or datetime.min, r["id"]),
        reverse=True,
    )
    return rows


# -------- NEW: totals computation for simple app ---------------------
def compute_totals_simple(transactions: List[Dict[str, Any]]) -> Dict[str, float]:
    income = sum(tx["amount_float"] for tx in transactions if tx["type"] == "income")
    expenses = sum(tx["amount_float"] for tx in transactions if tx["type"] == "expense")
    investments = sum(
        tx["amount_float"] for tx in transactions if tx["type"] == "investment"
    )

    net = income - expenses - investments
    savings_rate = net / income if income > 0 else 0.0

    return {
        "income": income,
        "expenses": expenses,
        "investments": investments,
        "net": net,
        "savings_rate": savings_rate,
    }
# ---------------------------------------------------------------------


def _next_id_for(path: Path) -> int:
    if not path.exists():
        return 1
    max_id = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            try:
                rid = int(raw.get("id", "") or 0)
            except Exception:
                continue
            if rid > max_id:
                max_id = rid
    return max_id + 1


def append_transaction_simple(tx: Dict[str, Any]) -> None:
    _ensure_data_dir()
    mapping = {
        "expense": EXPENSES_CSV,
        "income": INCOMES_CSV,
        "investment": INVESTMENTS_CSV,
    }
    path = mapping[tx["type"]]

    fieldnames = [
        "id",
        "date",
        "category",
        "sub_category",
        "amount",
        "account",
        "description",
        "created_at",
    ]

    is_new = not path.exists() or path.stat().st_size == 0
    new_id = _next_id_for(path)

    row = {
        "id": new_id,
        "date": tx.get("date", ""),
        "category": tx.get("category", ""),
        "sub_category": tx.get("sub_category", ""),
        "amount": str(tx.get("amount", "0")),
        "account": tx.get("account", ""),
        "description": tx.get("description", ""),
        "created_at": "",
    }

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def get_transaction(ttype: str, tx_id: int) -> Dict[str, Any] | None:
    mapping = {
        "expense": EXPENSES_CSV,
        "income": INCOMES_CSV,
        "investment": INVESTMENTS_CSV,
    }
    path = mapping.get(ttype)
    if path is None or not path.exists():
        return None

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            try:
                rid = int(raw.get("id", "") or 0)
            except Exception:
                continue
            if rid == tx_id:
                row = dict(raw)
                row["type"] = ttype
                amt_raw = row.get("amount", "0") or "0"
                try:
                    amt = float(amt_raw.replace(",", "."))
                except Exception:
                    amt = 0.0
                row["amount_str"] = f"{amt:.2f}"
                return row
    return None


def update_transaction_simple(ttype: str, tx_id: int, data: Dict[str, Any]) -> None:
    mapping = {
        "expense": EXPENSES_CSV,
        "income": INCOMES_CSV,
        "investment": INVESTMENTS_CSV,
    }
    path = mapping[ttype]
    if not path.exists():
        return

    fieldnames = [
        "id",
        "date",
        "category",
        "sub_category",
        "amount",
        "account",
        "description",
        "created_at",
    ]

    rows: List[Dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = dict(raw)
            try:
                rid = int(row.get("id", "") or 0)
            except Exception:
                rid = 0

            if rid == tx_id:
                # overwrite this row with new data
                row["date"] = data.get("date", row.get("date", ""))
                row["category"] = data.get("category", row.get("category", ""))
                row["sub_category"] = data.get("sub_category", row.get("sub_category", ""))
                row["amount"] = str(data.get("amount", row.get("amount", "0")))
                row["account"] = data.get("account", row.get("account", ""))
                row["description"] = data.get("description", row.get("description", ""))
                # keep created_at as is
            rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def delete_transaction_simple(ttype: str, tx_id: int) -> None:
    mapping = {
        "expense": EXPENSES_CSV,
        "income": INCOMES_CSV,
        "investment": INVESTMENTS_CSV,
    }
    path = mapping[ttype]
    if not path.exists():
        return

    fieldnames = [
        "id",
        "date",
        "category",
        "sub_category",
        "amount",
        "account",
        "description",
        "created_at",
    ]

    rows: List[Dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = dict(raw)
            try:
                rid = int(row.get("id", "") or 0)
            except Exception:
                rid = 0

            if rid == tx_id:
                # skip: this deletes it
                continue
            rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------
# Routes: simple dashboard, add, detail
# ---------------------------------------------------------------------
@app.route("/", endpoint="index")
@app.route("/simple", endpoint="simple_index")
def simple_index():
    transactions = load_all_simple()
    totals = compute_totals_simple(transactions)   # <-- NEW
    return render_template(
        "simple_index.html",
        transactions=transactions,
        totals=totals,
    )


@app.route("/add", methods=["GET", "POST"], endpoint="add_transaction")
@app.route("/simple/add", methods=["GET", "POST"], endpoint="simple_add_transaction")
def simple_add_transaction():
    if request.method == "POST":
        ttype = request.form.get("type", "expense")
        if ttype not in ("expense", "income", "investment"):
            ttype = "expense"

        date_str = request.form.get("date") or datetime.today().date().isoformat()
        category = request.form.get("category", "")
        sub_category = request.form.get("sub_category", "")
        amount_str = request.form.get("amount", "0").replace(",", ".")
        account = request.form.get("account", "")
        description = request.form.get("description", "")

        try:
            amount = float(amount_str)
        except Exception:
            amount = 0.0

        tx = {
            "type": ttype,
            "date": date_str,
            "category": category,
            "sub_category": sub_category,
            "amount": amount,
            "account": account,
            "description": description,
        }
        append_transaction_simple(tx)
        return redirect(url_for("index"))  # back to simple_index/index

    # GET
    ttype = request.args.get("type", "expense")
    if ttype not in ("expense", "income", "investment"):
        ttype = "expense"

    # pick category list like in the full app
    if ttype == "expense":
        categories = EXPENSE_CATEGORIES
    elif ttype == "income":
        categories = INCOME_CATEGORIES
    else:
        categories = INVESTMENT_CATEGORIES

    today = datetime.today().date().isoformat()
    return render_template(
        "simple_add_transaction.html",
        ttype=ttype,
        today=today,
        categories=categories,
    )



@app.route("/tx/<string:ttype>/<int:tx_id>", methods=["GET", "POST"])
def simple_transaction_detail(ttype: str, tx_id: int):
    if ttype not in ("expense", "income", "investment"):
        return "Invalid type", 400

    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            delete_transaction_simple(ttype, tx_id)
            return redirect(url_for("index"))

        if action == "update":
            date_str = request.form.get("date") or ""
            category = request.form.get("category", "")
            sub_category = request.form.get("sub_category", "")
            amount_str = request.form.get("amount", "0").replace(",", ".")
            account = request.form.get("account", "")
            description = request.form.get("description", "")

            try:
                amount = float(amount_str)
            except Exception:
                amount = 0.0

            data = {
                "date": date_str,
                "category": category,
                "sub_category": sub_category,
                "amount": amount,
                "account": account,
                "description": description,
            }
            update_transaction_simple(ttype, tx_id, data)
            return redirect(url_for("simple_transaction_detail", ttype=ttype, tx_id=tx_id))

    # GET or after redirect
    tx = get_transaction(ttype, tx_id)
    if tx is None:
        return f"Transaction {tx_id} not found", 404

    # normalize for template
    tx_date = tx.get("date", "")
    tx_amount = tx.get("amount_str", "0.00")
    tx_category = tx.get("category", "")
    tx_subcat = tx.get("sub_category", "")
    tx_account = tx.get("account", "")
    tx_desc = tx.get("description", "")

    tx_view = {
        "id": int(tx.get("id", 0) or 0),
        "type": ttype,
        "date": tx_date,
        "category": tx_category,
        "sub_category": tx_subcat,
        "amount": tx_amount,
        "account": tx_account,
        "description": tx_desc,
    }

    return render_template("simple_detail.html", tx=tx_view)


@app.route("/analysis")
def analysis():
    """
    Placeholder for the simple app (no pandas, no heavy stats).
    Just send the user back to the simple dashboard.
    """
    return redirect(url_for("index"))



if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )