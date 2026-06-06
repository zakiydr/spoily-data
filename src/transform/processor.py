"""
Transformation processor — merges Brent, fuel, and exchange rate data
into the fact table schema with lag alignment.

Malaysia fuel pricing cycle:
  - Prices announced Wednesday evening, effective Thursday
  - A "pricing week" = Thursday to Wednesday
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def transform_weekly(
    brent_df: pd.DataFrame,
    fuel_df: pd.DataFrame,
    rates_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Transform 3 source DataFrames into weekly fact rows.

    Args:
        brent_df: columns [date, brent_usd] — daily Brent prices
        fuel_df: columns [date, ron95, ron97] — weekly fuel prices
        rates_df: columns [date, usd_myr] — daily exchange rates

    Returns:
        DataFrame matching fact_weekly_fuel_pricing columns (+ T-1 helper columns).
    """
    if fuel_df.empty:
        logger.warning("No fuel data to transform")
        return pd.DataFrame()

    brent_df = brent_df.copy()
    fuel_df = fuel_df.copy()
    rates_df = rates_df.copy()

    brent_df["date"] = pd.to_datetime(brent_df["date"])
    fuel_df["date"] = pd.to_datetime(fuel_df["date"])
    rates_df["date"] = pd.to_datetime(rates_df["date"])

    rows: list[dict] = []

    for _, fuel_row in fuel_df.iterrows():
        pricing_week_start = pd.Timestamp(str(fuel_row["date"]))
        pricing_week_end = pricing_week_start + timedelta(days=6)

        t1_start = pricing_week_start - timedelta(weeks=1)
        t1_end = t1_start + timedelta(days=6)

        t2_start = pricing_week_start - timedelta(weeks=2)
        t2_end = t2_start + timedelta(days=6)

        avg_brent_t1 = _window_average(brent_df, "brent_usd", t1_start, t1_end, 2)
        avg_rate_t1 = _window_average(rates_df, "usd_myr", t1_start, t1_end, 4)

        avg_brent_t2 = _window_average(brent_df, "brent_usd", t2_start, t2_end, 2)
        avg_rate_t2 = _window_average(rates_df, "usd_myr", t2_start, t2_end, 4)

        rows.append(
            {
                "pricing_week_start": pricing_week_start.date(),
                "pricing_week_end": pricing_week_end.date(),
                "ron97_price_myr": fuel_row["ron97"],
                "ron95_price_myr": fuel_row["ron95"],
                "avg_brent_t1_usd": avg_brent_t1,
                "avg_usd_myr_t1": avg_rate_t1,
                "avg_brent_t2_usd": avg_brent_t2,
                "avg_usd_myr_t2": avg_rate_t2,
            }
        )

    result = pd.DataFrame(rows)
    logger.info("Transform: produced %s weekly rows", len(result))
    return result


def _window_average(
    df: pd.DataFrame,
    value_col: str,
    start_date: Any,
    end_date: Any,
    rounding: int,
) -> float | None:
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    values = df.loc[mask, value_col]
    if values.empty:
        return None
    return round(float(values.mean()), rounding)
