"""
Transformation processor — merges Brent, fuel, and exchange rate data
into the fact table schema with T-2 lag alignment.

Malaysia fuel pricing cycle:
  - Prices announced Wednesday evening, effective Thursday
  - A "pricing week" = Thursday to Wednesday
  - The Brent price that influences week W's BBM is avg Brent from week W-2
"""
import logging
import pandas as pd
from datetime import timedelta
from src.config.settings import T2_LAG_WEEKS

logger = logging.getLogger(__name__)


def transform_weekly(
    brent_df: pd.DataFrame,
    fuel_df: pd.DataFrame,
    rates_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Transform 3 source DataFrames into the fact_weekly_fuel_pricing schema.

    Args:
        brent_df: columns [date, brent_usd] — daily Brent prices
        fuel_df:  columns [date, ron95, ron95_subsidy, ron97] — weekly fuel prices
        rates_df: columns [date, usd_myr] — daily exchange rates

    Returns:
        DataFrame matching fact_weekly_fuel_pricing columns.
    """
    if fuel_df.empty:
        logger.warning("No fuel data to transform")
        return pd.DataFrame()

    # Ensure datetime types
    brent_df = brent_df.copy()
    fuel_df = fuel_df.copy()
    rates_df = rates_df.copy()
    brent_df["date"] = pd.to_datetime(brent_df["date"])
    fuel_df["date"] = pd.to_datetime(fuel_df["date"])
    rates_df["date"] = pd.to_datetime(rates_df["date"])

    rows = []

    for _, fuel_row in fuel_df.iterrows():
        pricing_week_start = fuel_row["date"]  # Thursday (effective date from data.gov.my)
        pricing_week_end = pricing_week_start + timedelta(days=6)  # Wednesday

        # T-2 window: the week starting 2 weeks before this pricing week
        t2_start = pricing_week_start - timedelta(weeks=T2_LAG_WEEKS)
        t2_end = t2_start + timedelta(days=6)

        # Average Brent in the T-2 window
        brent_mask = (brent_df["date"] >= t2_start) & (brent_df["date"] <= t2_end)
        brent_window = brent_df.loc[brent_mask, "brent_usd"]
        avg_brent = round(brent_window.mean(), 2) if not brent_window.empty else None

        # Average USD/MYR in the T-2 window
        rate_mask = (rates_df["date"] >= t2_start) & (rates_df["date"] <= t2_end)
        rate_window = rates_df.loc[rate_mask, "usd_myr"]
        avg_rate = round(rate_window.mean(), 4) if not rate_window.empty else None

        rows.append({
            "pricing_week_start": pricing_week_start.date(),
            "pricing_week_end": pricing_week_end.date(),
            "ron97_price_myr": fuel_row["ron97"],
            "ron95_price_myr": fuel_row["ron95"],
            "ron95_subsidy_myr": fuel_row.get("ron95_subsidy"),
            "avg_brent_t2_usd": avg_brent,
            "avg_usd_myr_t2": avg_rate,
        })

    result = pd.DataFrame(rows)
    logger.info(f"Transform: produced {len(result)} weekly rows")
    return result
