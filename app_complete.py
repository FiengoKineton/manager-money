# app.py
import pandas as pd
from datetime import date
from flask import Flask, render_template, request, redirect, url_for

from config import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    INVESTMENT_CATEGORIES,
    DEFAULT_TYPES,
    default_date_range,
)
from utils.io_utils import (
    load_all,
    append_transaction,
    update_transaction_record,
    delete_transaction_record,
)
from utils.filters import filter_by_date, filter_by_types, filter_by_categories, filter_by_query
from utils.stats import (
    summary_totals,
    monthly_summary,
    expenses_by_category,
    cumulative_balance,
    weekday_spending,
    rolling_net_flow,
    largest_expenses,
    expenses_by_weekday,
    period_income_expense,
)
from utils.plots import (
    plot_monthly_summary,
    plot_expenses_by_category,
    plot_cumulative_balance,
    plot_weekday_spending,
    plot_rolling_net_flow,
    plot_expenses_by_weekday,
)


app = Flask(__name__)


@app.route("/")
def index():
    df = load_all()

    today = pd.Timestamp.today()
    start_this_month = today.replace(day=1)
    start_3_months = today - pd.DateOffset(months=3)

    df_this_month = df[(df['date'] >= start_this_month) & (df['date'] <= today)]
    df_3_months = df[(df['date'] >= start_3_months) & (df['date'] <= today)]

    stats_this_month = period_income_expense(df_this_month)
    stats_3_months = period_income_expense(df_3_months)

    # Filters from query params
    start_default, end_default = default_date_range()
    start = request.args.get("from", start_default)
    end = request.args.get("to", end_default)

    # Types: getlist() because multiple checkboxes
    types = request.args.getlist("types")
    if not types:
        types = DEFAULT_TYPES[:]  # default: all three

    # Categories: getlist() because <select multiple>
    categories = request.args.getlist("category")

    q = request.args.get("q", "").strip()

    # Apply filters
    df_filtered = df.copy()
    df_filtered = filter_by_date(df_filtered, start, end)
    df_filtered = filter_by_types(df_filtered, types)
    df_filtered = filter_by_categories(df_filtered, categories)
    df_filtered = filter_by_query(df_filtered, q)

    # Prepare display-friendly columns
    if not df_filtered.empty:
        df_filtered = df_filtered.copy()
        df_filtered["date_str"] = df_filtered["date"].dt.strftime("%Y-%m-%d")
        df_filtered["amount_str"] = df_filtered["amount"].map(lambda x: f"{x:.2f}")
        df_filtered["row_index"] = df_filtered.index
    else:
        df_filtered["date_str"] = []
        df_filtered["amount_str"] = []

    # Stats
    totals = summary_totals(df_filtered)
    df_month = monthly_summary(df_filtered, start=start, end=end)
    df_cat = expenses_by_category(df_filtered)
    df_cum = cumulative_balance(df_filtered)

    # Plots
    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)

    # All unique categories in filtered data (for dropdown)
    all_categories = sorted(df["category"].dropna().unique().tolist()) if not df.empty else []

    return render_template(
        "index.html",
        transactions=df_filtered.to_dict(orient="records"),
        totals=totals,
        start=start,
        end=end,
        active_types=types,
        all_types=DEFAULT_TYPES,
        categories_selected=categories,
        categories_all=all_categories,
        q=q,
        stats_this_month=stats_this_month,
        stats_3_months=stats_3_months,
    )


@app.route("/add", methods=["GET", "POST"])
def add_transaction():
    if request.method == "POST":
        ttype = request.form.get("type")
        date_str = request.form.get("date")
        category = request.form.get("category")
        sub_category = request.form.get("sub_category", "")
        amount_str = request.form.get("amount", "0").replace(",", ".")
        account = request.form.get("account", "")
        description = request.form.get("description", "")

        try:
            amount = float(amount_str)
        except ValueError:
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

        append_transaction(tx)

        return redirect(url_for("index"))

    # GET
    ttype = request.args.get("type", "expense")
    if ttype not in DEFAULT_TYPES:
        ttype = "expense"

    if ttype == "expense":
        categories = EXPENSE_CATEGORIES
    elif ttype == "income":
        categories = INCOME_CATEGORIES
    else:
        categories = INVESTMENT_CATEGORIES

    today = date.today().isoformat()

    return render_template(
        "add_transaction.html",
        ttype=ttype,
        categories=categories,
        today=today,
    )

@app.route("/transaction/<int:row_index>", methods=["GET", "POST"])
def transaction_detail(row_index):
    df = load_all()

    # locate row by DataFrame index (what you passed from the table)
    try:
        row = df.loc[row_index]
    except KeyError:
        return f"Transaction {row_index} not found", 404

    if request.method == "POST":
        action = request.form.get("action")

        if action == "delete":
            # use CSV id + type to delete from correct file
            delete_transaction_record(int(row["id"]), row["type"])
            return redirect(url_for("index"))

        if action == "update":
            date_str = request.form.get("date")
            category = request.form.get("category")
            sub_category = request.form.get("sub_category", "")
            amount_str = request.form.get("amount", "0").replace(",", ".")
            account = request.form.get("account", "")
            description = request.form.get("description", "")

            try:
                amount = float(amount_str)
            except ValueError:
                amount = 0.0

            data = {
                "date": date_str,
                "category": category,
                "sub_category": sub_category,
                "amount": amount,
                "account": account,
                "description": description,
            }

            update_transaction_record(int(row["id"]), row["type"], data)
            # stay on the same row_index
            return redirect(url_for("transaction_detail", row_index=row_index))

    # -------- prepare values for template (GET / after redirect) --------
    if hasattr(row["date"], "strftime"):
        date_str = row["date"].strftime("%Y-%m-%d")
    else:
        date_str = str(row["date"]) if row["date"] else ""

    amount_str = f"{row['amount']:.2f}"

    desc = row.get("description", "")
    desc = "" if str(desc) == "nan" else desc

    subcat = row.get("sub_category", "")
    subcat = "" if str(subcat) == "nan" else subcat

    account = row.get("account", "")
    account = "" if str(account) == "nan" else account

    tx = {
        "id": int(row_index),          # this is the DataFrame index
        "type": row["type"],
        "date": date_str,
        "category": row["category"],
        "sub_category": subcat,
        "amount": amount_str,
        "account": account,
        "description": desc,
    }

    if tx["type"] == "expense":
        categories = EXPENSE_CATEGORIES
    elif tx["type"] == "income":
        categories = INCOME_CATEGORIES
    else:
        categories = INVESTMENT_CATEGORIES

    return render_template("transaction_detail.html", tx=tx, categories=categories)


@app.route("/analysis")
def analysis():
    df = load_all()

    # Empty dataset → show empty analysis nicely
    if df.empty:
        totals = {
            "income": 0.0,
            "expenses": 0.0,
            "investments": 0.0,
            "net": 0.0,
            "savings_rate": 0.0,
        }
        return render_template(
            "analysis.html",
            totals=totals,
            weekday_data=[],
            top_expenses=[],
        )

    # High-level totals
    totals = summary_totals(df)

    # Analysis data
    df_wd = weekday_spending(df)          # weekday totals
    df_roll = rolling_net_flow(df)        # daily + rolling net
    top_exp = largest_expenses(df, n=10).copy()

    # Clean up top expenses for template
    if not top_exp.empty:
        if pd.api.types.is_datetime64_any_dtype(top_exp["date"]):
            top_exp["date_str"] = top_exp["date"].dt.strftime("%Y-%m-%d")
        else:
            top_exp["date_str"] = top_exp["date"].astype(str)

        for col in ["description", "category"]:
            if col in top_exp.columns:
                top_exp[col] = top_exp[col].fillna("")

    # Monthly / category / cumulative
    df_month = monthly_summary(df)
    df_cat = expenses_by_category(df)
    df_cum = cumulative_balance(df)

    # Plots
    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)
    plot_weekday_spending(df_wd)
    plot_rolling_net_flow(df_roll)

    return render_template(
        "analysis.html",
        totals=totals,
        weekday_data=df_wd.to_dict(orient="records"),
        top_expenses=top_exp.to_dict(orient="records"),
    )




if __name__ == "__main__":
    app.run(debug=True)
