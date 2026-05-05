"""
Database loader — upserts transformed data into Supabase PostgreSQL.
Uses SQLAlchemy + raw SQL for ON CONFLICT upsert.
"""
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from src.config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

# Column list matching the fact table
COLUMNS = [
    "pricing_week_start", "pricing_week_end",
    "ron97_price_myr", "ron95_price_myr", "ron95_subsidy_myr",
    "avg_brent_t2_usd", "avg_usd_myr_t2",
    "predicted_ron97_myr", "predicted_ron95_myr", "prediction_delta_pct",
]

UPSERT_SQL = text("""
    INSERT INTO fact_weekly_fuel_pricing (
        pricing_week_start, pricing_week_end,
        ron97_price_myr, ron95_price_myr, ron95_subsidy_myr,
        avg_brent_t2_usd, avg_usd_myr_t2,
        predicted_ron97_myr, predicted_ron95_myr, prediction_delta_pct,
        last_updated
    ) VALUES (
        :pricing_week_start, :pricing_week_end,
        :ron97_price_myr, :ron95_price_myr, :ron95_subsidy_myr,
        :avg_brent_t2_usd, :avg_usd_myr_t2,
        :predicted_ron97_myr, :predicted_ron95_myr, :prediction_delta_pct,
        NOW()
    )
    ON CONFLICT (pricing_week_start) DO UPDATE SET
        pricing_week_end     = EXCLUDED.pricing_week_end,
        ron97_price_myr      = EXCLUDED.ron97_price_myr,
        ron95_price_myr      = EXCLUDED.ron95_price_myr,
        ron95_subsidy_myr    = EXCLUDED.ron95_subsidy_myr,
        avg_brent_t2_usd    = EXCLUDED.avg_brent_t2_usd,
        avg_usd_myr_t2       = EXCLUDED.avg_usd_myr_t2,
        predicted_ron97_myr  = EXCLUDED.predicted_ron97_myr,
        predicted_ron95_myr  = EXCLUDED.predicted_ron95_myr,
        prediction_delta_pct = EXCLUDED.prediction_delta_pct,
        last_updated         = NOW()
""")


def get_engine():
    """Create SQLAlchemy engine from DATABASE_URL."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set in environment")
    return create_engine(DATABASE_URL)


def upsert(df: pd.DataFrame, engine=None) -> int:
    """
    Upsert DataFrame rows into fact_weekly_fuel_pricing.
    Idempotent: running multiple times with same data produces same result.

    Args:
        df: DataFrame with fact table columns.
        engine: SQLAlchemy engine (created from DATABASE_URL if not provided).

    Returns:
        Number of rows upserted.
    """
    if df.empty:
        logger.warning("No data to upsert")
        return 0

    if engine is None:
        engine = get_engine()

    # Ensure all columns exist, fill missing with None
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None

    rows_upserted = 0

    with engine.begin() as conn:
        for _, row in df.iterrows():
            params = {col: _clean_value(row.get(col)) for col in COLUMNS}
            conn.execute(UPSERT_SQL, params)
            rows_upserted += 1

    logger.info(f"DB: upserted {rows_upserted} rows into fact_weekly_fuel_pricing")
    return rows_upserted


def _clean_value(val):
    """Convert pandas NaN/NaT to None and numpy scalars to Python types for SQL params."""
    if pd.isna(val):
        return None
    # Convert numpy scalars to native Python types
    import numpy as np
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return val
