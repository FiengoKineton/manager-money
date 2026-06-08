import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from money_manager.config import PLOTS_DIR


def _empty_figure(path, message: str, figsize=(6, 3)) -> None:
    fig, ax = plt.subplots(figsize=figsize)
    ax.text(0.5, 0.5, message, ha="center", va="center")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_monthly_summary(df_monthly: pd.DataFrame, filename: str = "monthly_summary.png"):
    path = PLOTS_DIR / filename
    if df_monthly.empty:
        _empty_figure(path, "No data")
        return

    fig, ax = plt.subplots(figsize=(7, 4))
    x = range(len(df_monthly))
    months = df_monthly["month"].tolist()

    for column, label in [
        ("income", "Income"),
        ("expenses", "Expenses"),
        ("investments", "Investments"),
        ("net", "Net"),
    ]:
        ax.plot(x, df_monthly[column], marker="o", label=label)

    ax.set_xticks(list(x))
    ax.set_xticklabels(months, rotation=45, ha="right")
    ax.set_ylabel("Amount")
    ax.set_title("Monthly summary")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_expenses_by_category(df_cat: pd.DataFrame, filename: str = "expenses_by_category.png"):
    path = PLOTS_DIR / filename
    fig, ax = plt.subplots(figsize=(6, 4))

    if df_cat.empty:
        ax.text(0.5, 0.5, "No expenses", ha="center", va="center")
        ax.axis("off")
    else:
        categories = df_cat["category"].tolist()
        values = df_cat["total"].tolist()
        ax.bar(categories, values)
        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels(categories, rotation=45, ha="right")
        ax.set_ylabel("Total")
        ax.set_title("Expenses by category")
        ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_cumulative_balance(df_cum: pd.DataFrame, filename: str = "cumulative_balance.png"):
    path = PLOTS_DIR / filename
    fig, ax = plt.subplots(figsize=(7, 3))

    if df_cum.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")
    else:
        ax.plot(df_cum["date"], df_cum["balance"])
        ax.set_ylabel("Balance")
        ax.set_title("Cumulative balance")
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_weekday_spending(df_wd: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(6, 3))

    if df_wd is not None and not df_wd.empty:
        ax.bar(df_wd["weekday"], df_wd["total"])
        ax.set_ylabel("Total expenses")
        ax.set_xlabel("Weekday")
    else:
        ax.text(0.5, 0.5, "No expense data", ha="center", va="center")
        ax.axis("off")

    ax.set_title("Expenses by weekday")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "weekday_spending.png", dpi=120)
    plt.close(fig)


def plot_rolling_net_flow(df_roll: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(7, 3))

    if df_roll is not None and not df_roll.empty:
        ax.plot(df_roll["date"], df_roll["daily_net"], label="Daily net")
        ax.plot(df_roll["date"], df_roll["rolling_net"], label="Rolling 30-day net")
        ax.legend()
        ax.set_xlabel("Date")
        ax.set_ylabel("Amount")
    else:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.axis("off")

    ax.set_title("Net cash flow")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "rolling_net_flow.png", dpi=120)
    plt.close(fig)
