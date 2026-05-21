# app.py
import os, pandas as pd
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, send_from_directory
from config import DOCUMENTS_DIR 

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
    next_credit_due,
)
from utils.filters import (
    filter_by_date, 
    filter_by_types, 
    filter_by_categories, 
    filter_by_query,
)
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
from utils.pending_utils import (
    append_pending, 
    load_pending, 
    mark_executed,
)
from utils.recurring_utils import (
    load_recurring,
    append_recurring,
    update_recurring,
    delete_recurring,
    generate_recurring,
    next_due_date_for_rule,
)
from utils.interactive_plots import (
    chart_monthly_summary,
    chart_expenses_by_category,
    chart_cumulative_balance,
    chart_rolling_net_flow,
    chart_weekday_spending,
)


app = Flask(__name__)

@app.context_processor
def inject_endpoint_checker():
    def endpoint_exists(endpoint):
        return endpoint in app.view_functions
    return dict(endpoint_exists=endpoint_exists)

@app.route("/documents-background/<path:filename>")
def documents_background(filename):
    return send_from_directory("Documents", filename)

@app.route("/")
def index():
    generate_recurring()
    process_pending()
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
    charts = {
        "monthly_summary": chart_monthly_summary(df_month),
        "expenses_by_category": chart_expenses_by_category(df_cat),
        "cumulative_balance": chart_cumulative_balance(df_cum),
    }

    plot_monthly_summary(df_month)
    plot_expenses_by_category(df_cat)
    plot_cumulative_balance(df_cum)

    # All unique categories in filtered data (for dropdown)
    all_categories = sorted(df["category"].dropna().unique().tolist()) if not df.empty else []

    pending = load_pending()

    today = date.today()
    pending_total = 0.0

    for tx in pending:
        if tx["status"] == "pending":
            pending_total += float(tx["amount"])

    net_after_pending = totals["net"] - pending_total

    return render_template(
        "index.html",
        transactions=df_filtered.to_dict(orient="records"),
        transactions_initial=df_filtered.head(50).to_dict(orient="records"),
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
        net_after_pending=net_after_pending,
        pending_this_month=pending_total,
        charts=charts,
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

        account = tx.get("account", "").strip().lower()

        credit_keywords = {
            "credit",
            "credit card",
            "card credit",
            "carta credito",
            "carta di credito",
            "visa",
            "mastercard",
        }
        
        if account in credit_keywords:
            tx["account"] = "credit"

            try:
                payment_date = date.fromisoformat(date_str)
            except (TypeError, ValueError):
                payment_date = date.today()

            due_date = next_credit_due(payment_date)
            append_pending(tx, due_date)
        else:
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

    charts = {
        "monthly_summary": chart_monthly_summary(df_month),
        "rolling_net_flow": chart_rolling_net_flow(df_roll),
        "expenses_by_category": chart_expenses_by_category(df_cat),
        "weekday_spending": chart_weekday_spending(df_wd),
        "cumulative_balance": chart_cumulative_balance(df_cum),
    }

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
        charts=charts,
    )


def process_pending():
    pending = load_pending()
    today = date.today()

    credit_group = {}   # group by due_date
    other_to_execute = []

    # --- split pending ---
    for tx in pending:
        if tx["status"] != "pending":
            continue

        due = date.fromisoformat(tx["date_due"])

        if due > today:
            continue

        amount = float(tx["amount"])

        # CREDIT → group
        if tx["account"].lower() == "credit":
            key = tx["date_due"]

            if key not in credit_group:
                credit_group[key] = 0.0

            credit_group[key] += amount

        else:
            other_to_execute.append(tx)

    # --- execute normal pending ---
    for tx in other_to_execute:
        append_transaction({
            "type": tx["type"],
            "date": tx["date_due"],
            "category": tx["category"],
            "sub_category": "",
            "amount": float(tx["amount"]),
            "account": tx["account"],
            "description": tx["description"],
        })

        mark_executed(int(tx["id"]))

    # --- execute CREDIT grouped ---
    for due_date, total in credit_group.items():

        append_transaction({
            "type": "expense",
            "date": due_date,
            "category": "Credit Card",
            "sub_category": "",
            "amount": total,
            "account": "credit",
            "description": f"Credit card payment ({due_date})",
        })

        # mark ALL credit rows with that due_date as executed
        for tx in pending:
            if (
                tx["status"] == "pending"
                and tx["account"].lower() == "credit"
                and tx["date_due"] == due_date
            ):
                mark_executed(int(tx["id"]))



@app.route("/documents")
def documents():
    return render_template("documents.html")

@app.route("/api/files/<folder>")
def get_files(folder):
    """Returns a JSON list of files in the requested folder."""
    if folder not in ["Cedolini", "Tasse - Detrazioni Fiscali"]:
        return jsonify({"error": "Invalid folder"}), 400
        
    folder_path = DOCUMENTS_DIR / folder
    if not folder_path.exists():
        return jsonify({"files": []})
        
    # Get all files (ignore subdirectories)
    files = [f for f in os.listdir(folder_path) if os.path.isfile(folder_path / f)]
    return jsonify({"files": sorted(files)})

@app.route("/document/<folder>/<filename>")
def serve_document(folder, filename):
    """Serves the actual file to the iframe."""
    if folder not in ["Cedolini", "Tasse - Detrazioni Fiscali"]:
        return "Invalid folder", 400
    return send_from_directory(DOCUMENTS_DIR / folder, filename)

@app.route("/pending", methods=["GET", "POST"])
def pending_page():
    from utils.recurring_utils import (
        load_recurring,
        append_recurring,
        delete_recurring,
        generate_recurring,
        next_due_date_for_rule,
    )

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            append_recurring({
                "name": request.form.get("name"),
                "type": request.form.get("type"),
                "amount": float(request.form.get("amount")),
                "frequency": int(request.form.get("frequency", 1)),
                "day_of_month": int(request.form.get("day_of_month")),
                "category": request.form.get("category"),
                "start_date": request.form.get("start_date"),
            })

        elif action == "update":
            update_recurring(
                request.form.get("id"),
                {
                    "name": request.form.get("name"),
                    "type": request.form.get("type"),
                    "amount": float(request.form.get("amount")),
                    "frequency": int(request.form.get("frequency", 1)),
                    "day_of_month": int(request.form.get("day_of_month")),
                    "category": request.form.get("category"),
                }
            )

        elif action == "delete":
            delete_recurring(int(request.form.get("id")))

        return redirect(url_for("pending_page"))

    generate_recurring()
    process_pending()

    pending = load_pending()
    recurring = load_recurring()

    for r in recurring:
        r["next_payment"] = next_due_date_for_rule(r).isoformat()

    return render_template(
        "pending.html",
        pending=pending,
        recurring=recurring,
        EXPENSE_CATEGORIES=EXPENSE_CATEGORIES,
        INCOME_CATEGORIES=INCOME_CATEGORIES,
        INVESTMENT_CATEGORIES=INVESTMENT_CATEGORIES
    )


@app.route("/forecast", methods=["GET", "POST"])
def forecast():
    import numpy as np

    # default values
    result = None

    if request.method == "POST":
        monthly_income = float(request.form.get("income", 0))
        monthly_expenses = float(request.form.get("expenses", 0))
        monthly_invest = float(request.form.get("investment", 0))
        years = int(request.form.get("years", 5))
        rate = float(request.form.get("rate", 5)) / 100.0

        # starting point (from your real data)
        df = load_all()
        totals = summary_totals(df)

        net = totals["net"]
        invested = totals["investments"]

        months = years * 12

        values = []
        total = net + invested

        for m in range(months):
            # monthly savings
            savings = monthly_income - monthly_expenses - monthly_invest

            # grow investments
            total = total * (1 + rate / 12)

            # add flows
            total += savings + monthly_invest

            values.append(total)

        # save plot
        import matplotlib.pyplot as plt

        plt.figure()
        plt.plot(values)
        plt.title("Wealth Projection")
        plt.xlabel("Months")
        plt.ylabel("€")
        plt.grid()

        plot_path = os.path.join("static", "plots", "forecast.png")
        plt.savefig(plot_path)
        plt.close()

        result = {
            "final_value": values[-1],
            "years": years
        }

    return render_template("forecast.html", result=result)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )