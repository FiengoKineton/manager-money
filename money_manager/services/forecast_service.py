import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from money_manager.config import PLOTS_DIR
from money_manager.repositories.transactions import load_all
from money_manager.services.account_service import main_account_transactions
from money_manager.utils.stats import summary_totals


def project_wealth(monthly_income: float, monthly_expenses: float, monthly_investment: float, years: int, annual_rate: float) -> dict:
    df = main_account_transactions(load_all())
    totals = summary_totals(df)

    current_cash = totals["net"]
    current_invested = totals["investments"]
    total = current_cash + current_invested

    months = years * 12
    values = []

    for _ in range(months):
        savings = monthly_income - monthly_expenses - monthly_investment
        total = total * (1 + annual_rate / 12)
        total += savings + monthly_investment
        values.append(total)

    _save_forecast_plot(values)

    return {
        "final_value": values[-1] if values else total,
        "years": years,
    }


def _save_forecast_plot(values: list[float]) -> None:
    plot_path = PLOTS_DIR / "forecast.png"

    fig, ax = plt.subplots()
    ax.plot(values)
    ax.set_title("Wealth Projection")
    ax.set_xlabel("Months")
    ax.set_ylabel("€")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(plot_path)
    plt.close(fig)
