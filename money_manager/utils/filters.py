# utils/filters.py
from typing import Iterable, Optional
import pandas as pd


def filter_by_date(df: pd.DataFrame,
                   start: Optional[str],
                   end: Optional[str]) -> pd.DataFrame:
    if start:
        start_dt = pd.to_datetime(start, errors="coerce")
        df = df[df["date"] >= start_dt]
    if end:
        end_dt = pd.to_datetime(end, errors="coerce")
        df = df[df["date"] <= end_dt]
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
        df["description"].fillna("").str.lower().str.contains(q)
        | df["category"].fillna("").str.lower().str.contains(q)
        | df["sub_category"].fillna("").str.lower().str.contains(q)
    )
    return df[mask]
