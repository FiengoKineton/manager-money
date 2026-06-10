# utils/filters.py
from typing import Iterable, Optional
import pandas as pd


def filter_by_date(df: pd.DataFrame,
                   start: Optional[str],
                   end: Optional[str]) -> pd.DataFrame:
    if start:
        start_dt = pd.to_datetime(start, errors="coerce")
        if not pd.isna(start_dt):
            df = df[df["date"] >= start_dt]
    if end:
        end_dt = pd.to_datetime(end, errors="coerce")
        if not pd.isna(end_dt):
            df = df[df["date"] <= end_dt]
    return df


def filter_by_amount_range(df: pd.DataFrame,
                           amount_min: Optional[str | float],
                           amount_max: Optional[str | float],
                           *,
                           absolute: bool = True) -> pd.DataFrame:
    """Filter transactions by amount range.

    By default this uses the absolute displayed amount so a search for 20..50
    finds both a €20 income and a €20 expense.  The stored CSV amount is always
    positive, so this also works for the current transaction model.
    """
    if df.empty or "amount" not in df.columns:
        return df

    values = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    if absolute:
        values = values.abs()

    min_value = _parse_amount_bound(amount_min)
    max_value = _parse_amount_bound(amount_max)

    if min_value is not None:
        df = df[values >= min_value]
        values = values.loc[df.index]
    if max_value is not None:
        df = df[values <= max_value]
    return df


def filter_by_types(df: pd.DataFrame,
                    types: Optional[Iterable[str]]) -> pd.DataFrame:
    if not types:
        return df
    types = list(types)
    return df[df["type"].isin(types)]


def filter_by_categories(df: pd.DataFrame,
                         categories: Optional[Iterable[str]]) -> pd.DataFrame:
    if not categories:
        return df
    categories = [c.strip() for c in categories if c.strip()]
    if not categories:
        return df
    return df[df["category"].isin(categories)]


def filter_by_query(df: pd.DataFrame, q: Optional[str]) -> pd.DataFrame:
    if not q:
        return df
    q = q.strip().lower()
    if not q:
        return df
    mask = (
        df["description"].fillna("").str.lower().str.contains(q, regex=False)
        | df["category"].fillna("").str.lower().str.contains(q, regex=False)
        | df["sub_category"].fillna("").str.lower().str.contains(q, regex=False)
        | df.get("account", pd.Series("", index=df.index)).fillna("").str.lower().str.contains(q, regex=False)
    )
    return df[mask]


def _parse_amount_bound(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        return None
