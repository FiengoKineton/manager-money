from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd
import plotly.graph_objects as go

from money_manager.config import INVESTMENT_MARKET_CACHE_JSON
from money_manager.repositories.investments import (
    append_investment_asset,
    delete_investment_asset,
    load_investment_assets,
    update_investment_asset,
)
from money_manager.repositories.transactions import load_by_type

PLOT_CONFIG = {"displaylogo": False, "responsive": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
MARKET_LOOKBACK = "2y"

POSITIVE_COLOR = "#18794e"
NEGATIVE_COLOR = "#c2410c"
NEUTRAL_COLOR = "#1f2937"
BLUE_COLOR = "#2454d6"

FLOW_IN_CATEGORIES = {"deposit", "buy"}
FLOW_OUT_CATEGORIES = {"withdrawal", "withdraw", "sell"}
DIVIDEND_CATEGORIES = {"dividend", "dividends"}


def add_asset_from_form(form) -> None:
    append_investment_asset({
        "symbol": form.get("symbol", ""),
        "label": form.get("label", ""),
        "allocation_pct": form.get("allocation_pct", 100),
        "currency": form.get("currency", "EUR"),
        "active": "1" if form.get("active", "1") else "0",
    })
    refresh_market_data(force=True)


def delete_asset_from_form(form) -> None:
    try:
        delete_investment_asset(int(form.get("id")))
    except (TypeError, ValueError):
        return


def update_asset_from_form(form) -> None:
    try:
        asset_id = int(form.get("id"))
    except (TypeError, ValueError):
        return
    update_investment_asset(asset_id, {
        "symbol": form.get("symbol", ""),
        "label": form.get("label", ""),
        "allocation_pct": form.get("allocation_pct", 0),
        "currency": form.get("currency", "EUR"),
        "active": "1" if form.get("active") else "0",
    })
    refresh_market_data(force=True)


def refresh_market_data(force: bool = True) -> dict:
    """Fetch configured market symbols from Yahoo Finance chart JSON.

    The app never crashes if the network is unavailable. It keeps the last good
    response in data/investment_market_cache.json and falls back to that cache.
    """
    assets = [a for a in load_investment_assets() if _is_active(a)]
    cache = _read_cache()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for asset in assets:
        symbol = asset["symbol"]
        if not force and symbol in cache.get("symbols", {}):
            continue
        fetched = _fetch_yahoo_chart(symbol)
        if fetched:
            cache.setdefault("symbols", {})[symbol] = {
                "symbol": symbol,
                "label": asset.get("label", symbol),
                "currency": asset.get("currency", "EUR"),
                "fetched_at": now,
                "prices": fetched,
                "error": "",
            }
        else:
            cache.setdefault("symbols", {}).setdefault(symbol, {
                "symbol": symbol,
                "label": asset.get("label", symbol),
                "currency": asset.get("currency", "EUR"),
                "fetched_at": "",
                "prices": [],
                "error": "No market data available yet.",
            })
            if not cache["symbols"][symbol].get("prices"):
                cache["symbols"][symbol]["error"] = "Fetch failed and no cache exists."

    cache["last_refresh_attempt"] = now
    _write_cache(cache)
    return cache


def page_context() -> dict:
    cache = refresh_market_data(force=True)
    assets = load_investment_assets()
    tx = _load_investment_transactions()
    market = _weighted_market_index(assets, cache)
    daily = _estimate_daily_portfolio(tx, market)
    flow_rows = _flow_rows_for_display(tx, market)

    totals = _investment_totals(tx, daily)
    charts = {
        "profit_loss": _chart_profit_loss(daily),
        "cashflows": _chart_cashflows(tx),
        "market": _chart_market_index(market),
    }

    active_symbols = [a for a in assets if _is_active(a)]
    market_status = _market_status(active_symbols, cache)

    return {
        "today": date.today().isoformat(),
        "assets": assets,
        "active_assets": active_symbols,
        "market_status": market_status,
        "totals": totals,
        "charts": charts,
        "flow_rows": flow_rows,
        "transactions": _transactions_for_display(tx),
    }



def overview_snapshot(refresh: bool = False) -> dict:
    """Small, safe investment snapshot for the overview pages.

    It does not crash without internet.  By default it reuses the local market
    cache so opening the overview stays fast; the Investments page still forces
    a refresh.
    """
    cache = refresh_market_data(force=True) if refresh else _read_cache()
    assets = load_investment_assets()
    tx = _load_investment_transactions()
    market = _weighted_market_index(assets, cache)
    daily = _estimate_daily_portfolio(tx, market)
    totals = _investment_totals(tx, daily)
    return {
        "net_invested": float(totals.get("net_invested", 0.0) or 0.0),
        "estimated_value": float(totals.get("estimated_value", 0.0) or 0.0),
        "profit_loss": float(totals.get("profit_loss", 0.0) or 0.0),
        "profit_loss_pct": float(totals.get("profit_loss_pct", 0.0) or 0.0),
        "profit_loss_tone": totals.get("profit_loss_tone", "positive"),
    }


def investment_habit_snapshot(refresh: bool = False) -> dict:
    """Return compact investment behaviour metrics for Analysis and Forecast.

    Deposits and buys are treated as invested cash. Withdrawals and sells are
    treated as cash coming back out. Dividends are tracked separately because
    they are income from the portfolio, not market profit/loss.
    """
    cache = refresh_market_data(force=True) if refresh else _read_cache()
    assets = load_investment_assets()
    tx = _load_investment_transactions()
    market = _weighted_market_index(assets, cache)
    daily = _estimate_daily_portfolio(tx, market)
    totals = _investment_totals(tx, daily)

    months = _observed_month_count(tx)
    if tx.empty:
        deposits_buys = withdrawals_sells = dividends = 0.0
        transaction_count = 0
        last_activity = ""
    else:
        deposits_buys = float(tx.loc[tx["flow_signed"] > 0, "flow_signed"].sum())
        withdrawals_sells = float(-tx.loc[tx["flow_signed"] < 0, "flow_signed"].sum())
        dividends = float(tx.loc[tx["is_dividend"], "amount"].sum())
        transaction_count = int(len(tx))
        last_activity = tx["date"].max().strftime("%Y-%m-%d")

    annual_return_pct = _annualized_return_pct(daily, totals)
    monthly_deposit_buy = deposits_buys / months
    monthly_withdraw_sell = withdrawals_sells / months
    monthly_net_investment = (deposits_buys - withdrawals_sells) / months
    monthly_dividends = dividends / months

    return {
        "months_observed": months,
        "transaction_count": transaction_count,
        "last_activity": last_activity,
        "deposits_buys": deposits_buys,
        "withdrawals_sells": withdrawals_sells,
        "dividends": dividends,
        "monthly_deposit_buy": monthly_deposit_buy,
        "monthly_withdraw_sell": monthly_withdraw_sell,
        "monthly_net_investment": monthly_net_investment,
        "monthly_dividends": monthly_dividends,
        "annual_return_pct": annual_return_pct,
        "net_invested": totals.get("net_invested", 0.0),
        "estimated_value": totals.get("estimated_value", 0.0),
        "profit_loss": totals.get("profit_loss", 0.0),
        "profit_loss_pct": totals.get("profit_loss_pct", 0.0),
        "profit_loss_tone": totals.get("profit_loss_tone", "positive"),
        "cashflows_chart": _chart_cashflows(tx),
        "flow_rows": _flow_rows_for_display(tx, market)[:8],
    }


def _observed_month_count(tx: pd.DataFrame) -> int:
    if tx.empty or "date" not in tx:
        return 1
    dates = tx["date"].dropna()
    if dates.empty:
        return 1
    start = dates.min().to_period("M")
    end = max(pd.Timestamp.today(), dates.max()).to_period("M")
    return max(1, (end.year - start.year) * 12 + (end.month - start.month) + 1)


def _annualized_return_pct(daily: pd.DataFrame, totals: dict) -> float:
    fallback = float(totals.get("profit_loss_pct", 0.0) or 0.0)
    if daily.empty or len(daily) < 2:
        return fallback

    first = daily[daily["net_invested"].abs() > 0.01].head(1)
    latest = daily.tail(1)
    if first.empty or latest.empty:
        return fallback

    start_date = pd.to_datetime(first.iloc[0]["date"], errors="coerce")
    end_date = pd.to_datetime(latest.iloc[0]["date"], errors="coerce")
    if pd.isna(start_date) or pd.isna(end_date):
        return fallback

    years = max((end_date - start_date).days / 365.25, 1 / 12)
    principal = abs(float(latest.iloc[0].get("net_invested", 0.0) or 0.0))
    value = float(latest.iloc[0].get("estimated_value", principal) or principal)
    if principal <= 0 or value <= 0:
        return fallback

    try:
        return ((value / principal) ** (1 / years) - 1.0) * 100.0
    except Exception:
        return fallback

def _load_investment_transactions() -> pd.DataFrame:
    df = load_by_type("investment")
    if df.empty:
        return pd.DataFrame(columns=["date", "category", "sub_category", "amount", "account", "description"])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["category_clean"] = df["category"].fillna("").astype(str).str.strip().str.casefold()
    df["flow_signed"] = df.apply(_signed_investment_flow, axis=1)
    df["is_dividend"] = df["category_clean"].isin(DIVIDEND_CATEGORIES)
    df = df.dropna(subset=["date"]).sort_values("date")
    return df


def _signed_investment_flow(row) -> float:
    category = str(row.get("category_clean", "")).strip().casefold()
    amount = float(row.get("amount", 0.0) or 0.0)
    if category in FLOW_IN_CATEGORIES:
        return amount
    if category in FLOW_OUT_CATEGORIES:
        return -amount
    # Dividends are deliberately excluded from profit/loss margin. They are
    # shown as cash return, not as market performance.
    return 0.0


def _fetch_yahoo_chart(symbol: str) -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range={MARKET_LOOKBACK}&interval=1d"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 MoneyManager/1.0"})
    try:
        with urlopen(req, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    try:
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception:
        return []

    rows = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
        try:
            price = float(close)
        except (TypeError, ValueError):
            continue
        rows.append({"date": day, "close": price})
    return rows


def _weighted_market_index(assets: list[dict], cache: dict) -> pd.DataFrame:
    active = [a for a in assets if _is_active(a)]
    frames = []
    weights = []

    for asset in active:
        symbol = asset["symbol"]
        price_rows = cache.get("symbols", {}).get(symbol, {}).get("prices", [])
        if not price_rows:
            continue
        frame = pd.DataFrame(price_rows)
        if frame.empty or "date" not in frame or "close" not in frame:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).drop_duplicates("date").sort_values("date")
        if frame.empty:
            continue
        first = float(frame["close"].iloc[0])
        if first <= 0:
            continue
        frame = frame[["date", "close"]].copy()
        frame[symbol] = frame["close"] / first
        frames.append(frame[["date", symbol]])
        weights.append((symbol, float(asset.get("allocation_pct", 0.0) or 0.0)))

    if not frames:
        return pd.DataFrame(columns=["date", "market_index"])

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="date", how="outer")
    merged = merged.sort_values("date").ffill().dropna(how="all")

    total_weight = sum(weight for _, weight in weights) or 1.0
    merged["market_index"] = 0.0
    for symbol, weight in weights:
        if symbol in merged:
            merged["market_index"] += merged[symbol].ffill().fillna(1.0) * (weight / total_weight)
    return merged[["date", "market_index"]].dropna()


def _estimate_daily_portfolio(tx: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    if market.empty:
        return pd.DataFrame(columns=["date", "net_invested", "estimated_value", "profit_loss", "profit_loss_pct"])

    timeline = market[["date", "market_index"]].copy().sort_values("date")
    flows = tx[tx["flow_signed"].abs() > 0].copy() if not tx.empty else tx
    if flows.empty:
        timeline["net_invested"] = 0.0
        timeline["estimated_value"] = 0.0
        timeline["profit_loss"] = 0.0
        timeline["profit_loss_pct"] = 0.0
        return timeline

    start = pd.to_datetime(flows["date"].min()).normalize()
    timeline = timeline[timeline["date"] >= start].copy()
    if timeline.empty:
        return pd.DataFrame(columns=["date", "net_invested", "estimated_value", "profit_loss", "profit_loss_pct"])

    flow_records = []
    for _, row in flows.iterrows():
        entry_index = _index_on_or_before(market, row["date"])
        if entry_index <= 0:
            entry_index = 1.0
        flow_records.append({
            "date": row["date"],
            "amount": float(row["flow_signed"]),
            "entry_index": entry_index,
        })

    net_invested = []
    estimated_value = []
    for _, day in timeline.iterrows():
        current_index = float(day["market_index"] or 1.0)
        current_date = day["date"]
        principal = 0.0
        value = 0.0
        for flow in flow_records:
            if flow["date"] <= current_date:
                principal += flow["amount"]
                value += flow["amount"] * current_index / flow["entry_index"]
        net_invested.append(principal)
        estimated_value.append(value)

    timeline["net_invested"] = net_invested
    timeline["estimated_value"] = estimated_value
    timeline["profit_loss"] = timeline["estimated_value"] - timeline["net_invested"]
    timeline["profit_loss_pct"] = timeline.apply(
        lambda row: 0.0 if abs(row["net_invested"]) < 0.01 else row["profit_loss"] / abs(row["net_invested"]) * 100.0,
        axis=1,
    )
    return timeline


def _flow_rows_for_display(tx: pd.DataFrame, market: pd.DataFrame) -> list[dict]:
    if tx.empty:
        return []
    latest_index = _latest_index(market)
    rows = []
    for _, row in tx.sort_values("date", ascending=False).iterrows():
        amount = float(row.get("amount", 0.0) or 0.0)
        signed = float(row.get("flow_signed", 0.0) or 0.0)
        entry_index = _index_on_or_before(market, row["date"])
        estimated_value = 0.0
        profit_loss = 0.0
        if abs(signed) > 0 and entry_index > 0 and latest_index > 0:
            estimated_value = signed * latest_index / entry_index
            profit_loss = estimated_value - signed
        rows.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "category": row.get("category", ""),
            "amount": amount,
            "signed_flow": signed,
            "is_dividend": bool(row.get("is_dividend", False)),
            "estimated_value": estimated_value,
            "profit_loss": profit_loss,
            "tone": "positive" if profit_loss >= 0 else "negative",
            "account": row.get("account", ""),
            "description": row.get("description", ""),
        })
    return rows


def _transactions_for_display(tx: pd.DataFrame) -> list[dict]:
    if tx.empty:
        return []
    rows = []
    for _, row in tx.sort_values("date", ascending=False).iterrows():
        rows.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "category": row.get("category", ""),
            "sub_category": row.get("sub_category", ""),
            "amount": float(row.get("amount", 0.0) or 0.0),
            "account": row.get("account", ""),
            "description": row.get("description", ""),
        })
    return rows


def _investment_totals(tx: pd.DataFrame, daily: pd.DataFrame) -> dict:
    flow_df = tx if not tx.empty else pd.DataFrame(columns=["flow_signed", "is_dividend", "amount", "category_clean"])
    deposits = float(flow_df.loc[flow_df["category_clean"].eq("deposit"), "amount"].sum()) if not flow_df.empty else 0.0
    buys = float(flow_df.loc[flow_df["category_clean"].eq("buy"), "amount"].sum()) if not flow_df.empty else 0.0
    withdrawals = float(flow_df.loc[flow_df["category_clean"].isin({"withdrawal", "withdraw"}), "amount"].sum()) if not flow_df.empty else 0.0
    sells = float(flow_df.loc[flow_df["category_clean"].eq("sell"), "amount"].sum()) if not flow_df.empty else 0.0
    dividends = float(flow_df.loc[flow_df["category_clean"].isin(DIVIDEND_CATEGORIES), "amount"].sum()) if not flow_df.empty else 0.0
    net_invested = deposits + buys - withdrawals - sells

    latest = daily.iloc[-1].to_dict() if not daily.empty else {}
    estimated_value = float(latest.get("estimated_value", net_invested) or 0.0)
    profit_loss = float(latest.get("profit_loss", 0.0) or 0.0)
    profit_loss_pct = 0.0 if abs(net_invested) < 0.01 else profit_loss / abs(net_invested) * 100.0

    return {
        "deposits": deposits,
        "buys": buys,
        "withdrawals": withdrawals,
        "sells": sells,
        "dividends": dividends,
        "net_invested": float(net_invested),
        "estimated_value": estimated_value,
        "profit_loss": profit_loss,
        "profit_loss_pct": profit_loss_pct,
        "profit_loss_tone": "positive" if profit_loss >= 0 else "negative",
    }


def _chart_profit_loss(daily: pd.DataFrame) -> str:
    if daily.empty:
        return _empty_chart("Investment profit/loss estimate")
    fig = go.Figure()
    colors = [POSITIVE_COLOR if value >= 0 else NEGATIVE_COLOR for value in daily["profit_loss"]]
    fig.add_trace(go.Bar(
        x=daily["date"],
        y=daily["profit_loss"],
        name="Profit/Loss margin",
        marker_color=colors,
        opacity=0.42,
        hovertemplate="%{x|%Y-%m-%d}<br>P/L: €%{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=daily["date"],
        y=daily["estimated_value"],
        mode="lines",
        name="Estimated market value",
        line=dict(color=BLUE_COLOR, width=3),
        hovertemplate="%{x|%Y-%m-%d}<br>Value: €%{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=daily["date"],
        y=daily["net_invested"],
        mode="lines",
        name="Net invested capital",
        line=dict(color=NEUTRAL_COLOR, width=2, dash="dash"),
        hovertemplate="%{x|%Y-%m-%d}<br>Net invested: €%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title="Estimated profit/loss vs deposits, buys, withdrawals and sells",
        height=460,
        barmode="relative",
        yaxis_title="Euro",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return _to_html(fig)


def _chart_cashflows(tx: pd.DataFrame) -> str:
    if tx.empty:
        return _empty_chart("Investment cash flows")
    tmp = tx.copy()
    tmp["month"] = tmp["date"].dt.to_period("M").dt.to_timestamp()
    tmp["deposit_buy"] = tmp["flow_signed"].clip(lower=0)
    tmp["withdraw_sell"] = (-tmp["flow_signed"].clip(upper=0))
    tmp["dividend_amount"] = tmp.apply(lambda row: row["amount"] if row.get("is_dividend") else 0.0, axis=1)
    grouped = tmp.groupby("month", as_index=False)[["deposit_buy", "withdraw_sell", "dividend_amount"]].sum()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=grouped["month"], y=grouped["deposit_buy"], name="Deposits + buys", marker_color=BLUE_COLOR))
    fig.add_trace(go.Bar(x=grouped["month"], y=-grouped["withdraw_sell"], name="Withdrawals + sells", marker_color=NEGATIVE_COLOR))
    fig.add_trace(go.Bar(x=grouped["month"], y=grouped["dividend_amount"], name="Dividends", marker_color=POSITIVE_COLOR))
    fig.update_layout(title="Investment cash flows by month", height=360, yaxis_title="Euro", barmode="relative")
    return _to_html(fig)


def _chart_market_index(market: pd.DataFrame) -> str:
    if market.empty:
        return _empty_chart("Market index")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=market["date"],
        y=(market["market_index"] - 1.0) * 100.0,
        mode="lines",
        name="Weighted market move",
        line=dict(color=BLUE_COLOR, width=3),
        hovertemplate="%{x|%Y-%m-%d}<br>Move: %{y:.2f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line_width=1, line_dash="dash", line_color="#6b7280")
    fig.update_layout(title="Configured market proxy movement", height=340, yaxis_title="Move from first cached day (%)")
    return _to_html(fig)


def _market_status(active_assets: list[dict], cache: dict) -> list[dict]:
    rows = []
    for asset in active_assets:
        symbol = asset["symbol"]
        item = cache.get("symbols", {}).get(symbol, {})
        prices = item.get("prices", [])
        last_price = prices[-1]["close"] if prices else None
        last_date = prices[-1]["date"] if prices else ""
        rows.append({
            "symbol": symbol,
            "label": asset.get("label", symbol),
            "allocation_pct": float(asset.get("allocation_pct", 0.0) or 0.0),
            "last_price": last_price,
            "last_date": last_date,
            "fetched_at": item.get("fetched_at", ""),
            "status": "ok" if prices else "missing",
            "error": item.get("error", ""),
        })
    return rows


def _index_on_or_before(market: pd.DataFrame, target_date) -> float:
    if market.empty:
        return 1.0
    target = pd.to_datetime(target_date)
    sub = market[market["date"] <= target]
    if sub.empty:
        return float(market["market_index"].iloc[0] or 1.0)
    return float(sub["market_index"].iloc[-1] or 1.0)


def _latest_index(market: pd.DataFrame) -> float:
    if market.empty:
        return 1.0
    return float(market["market_index"].iloc[-1] or 1.0)


def _is_active(asset: dict) -> bool:
    return str(asset.get("active", "1")).strip().lower() in {"1", "true", "yes", "on"}


def _read_cache() -> dict:
    path = Path(INVESTMENT_MARKET_CACHE_JSON)
    if not path.exists():
        return {"symbols": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("symbols", {})
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {"symbols": {}}


def _write_cache(cache: dict) -> None:
    path = Path(INVESTMENT_MARKET_CACHE_JSON)
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _empty_chart(title: str) -> str:
    fig = go.Figure()
    fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False, font={"size": 16})
    fig.update_layout(title=title, height=320, template="plotly_white", margin=dict(l=40, r=20, t=50, b=40))
    return _to_html(fig)


def _to_html(fig: go.Figure) -> str:
    fig.update_layout(template="plotly_white", autosize=True, margin=dict(l=45, r=25, t=70, b=45), hovermode="x unified")
    return fig.to_html(full_html=False, include_plotlyjs=False, config=PLOT_CONFIG)
