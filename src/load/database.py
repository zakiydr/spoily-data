"""
Database loader — upserts transformed data into Supabase PostgreSQL.
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import create_engine, text

from src.config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

# Columns matching fact_weekly_fuel_pricing
FACT_COLUMNS = [
    "pricing_week_start",
    "pricing_week_end",
    "ron97_price_myr",
    "ron95_price_myr",
    "avg_brent_t2_usd",
    "avg_usd_myr_t2",
    "predicted_ron97_myr",
    "predicted_ron95_myr",
    "prediction_delta_pct",
]

PREDICTION_COLUMNS = [
    "pricing_week_start",
    "fuel_type",
    "model_type",
    "lag_weeks",
    "predicted_price_myr",
    "actual_price_myr",
    "abs_pct_error",
    "signed_pct_error",
]

ENSURE_PREDICTION_TABLE_SQL = text(
    """
    CREATE TABLE IF NOT EXISTS fact_weekly_fuel_predictions (
        pricing_week_start DATE NOT NULL,
        fuel_type TEXT NOT NULL,
        model_type TEXT NOT NULL,
        lag_weeks SMALLINT NOT NULL,
        predicted_price_myr DECIMAL(8,4) NOT NULL,
        actual_price_myr DECIMAL(8,4) NOT NULL,
        abs_pct_error DECIMAL(8,4) NOT NULL,
        signed_pct_error DECIMAL(8,4) NOT NULL,
        last_updated TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (pricing_week_start, fuel_type, model_type, lag_weeks)
    );
    """
)

UPSERT_FACT_SQL = text(
    """
    INSERT INTO fact_weekly_fuel_pricing (
        pricing_week_start, pricing_week_end,
        ron97_price_myr, ron95_price_myr,
        avg_brent_t2_usd, avg_usd_myr_t2,
        predicted_ron97_myr, predicted_ron95_myr, prediction_delta_pct,
        last_updated
    ) VALUES (
        :pricing_week_start, :pricing_week_end,
        :ron97_price_myr, :ron95_price_myr,
        :avg_brent_t2_usd, :avg_usd_myr_t2,
        :predicted_ron97_myr, :predicted_ron95_myr, :prediction_delta_pct,
        NOW()
    )
    ON CONFLICT (pricing_week_start) DO UPDATE SET
        pricing_week_end     = EXCLUDED.pricing_week_end,
        ron97_price_myr      = EXCLUDED.ron97_price_myr,
        ron95_price_myr      = EXCLUDED.ron95_price_myr,
        avg_brent_t2_usd     = EXCLUDED.avg_brent_t2_usd,
        avg_usd_myr_t2       = EXCLUDED.avg_usd_myr_t2,
        predicted_ron97_myr  = EXCLUDED.predicted_ron97_myr,
        predicted_ron95_myr  = EXCLUDED.predicted_ron95_myr,
        prediction_delta_pct = EXCLUDED.prediction_delta_pct,
        last_updated         = NOW()
    """
)

UPSERT_PREDICTION_SQL = text(
    """
    INSERT INTO fact_weekly_fuel_predictions (
        pricing_week_start, fuel_type, model_type, lag_weeks,
        predicted_price_myr, actual_price_myr, abs_pct_error, signed_pct_error,
        last_updated
    ) VALUES (
        :pricing_week_start, :fuel_type, :model_type, :lag_weeks,
        :predicted_price_myr, :actual_price_myr, :abs_pct_error, :signed_pct_error,
        NOW()
    )
    ON CONFLICT (pricing_week_start, fuel_type, model_type, lag_weeks) DO UPDATE SET
        predicted_price_myr = EXCLUDED.predicted_price_myr,
        actual_price_myr    = EXCLUDED.actual_price_myr,
        abs_pct_error       = EXCLUDED.abs_pct_error,
        signed_pct_error    = EXCLUDED.signed_pct_error,
        last_updated        = NOW()
    """
)


def get_engine():
    """Create SQLAlchemy engine from DATABASE_URL."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set in environment")
    return create_engine(DATABASE_URL)


def upsert(df: pd.DataFrame, engine=None) -> int:
    """
    Upsert weekly fact rows into fact_weekly_fuel_pricing.
    """
    if df.empty:
        logger.warning("No fact data to upsert")
        return 0

    if engine is None:
        engine = get_engine()

    working_df = df.copy()
    for col in FACT_COLUMNS:
        if col not in working_df.columns:
            working_df[col] = None

    rows_upserted = 0
    with engine.begin() as conn:
        for _, row in working_df.iterrows():
            params = {col: _clean_value(row.get(col)) for col in FACT_COLUMNS}
            conn.execute(UPSERT_FACT_SQL, params)
            rows_upserted += 1

    logger.info("DB: upserted %s rows into fact_weekly_fuel_pricing", rows_upserted)
    return rows_upserted


def upsert_prediction_history(prediction_df: pd.DataFrame, engine=None) -> int:
    """
    Upsert model/lag prediction rows for dashboard and audit views.
    """
    if prediction_df.empty:
        logger.warning("No prediction history rows to upsert")
        return 0

    if engine is None:
        engine = get_engine()

    working_df = prediction_df.copy()
    for col in PREDICTION_COLUMNS:
        if col not in working_df.columns:
            working_df[col] = None

    rows_upserted = 0
    with engine.begin() as conn:
        conn.execute(ENSURE_PREDICTION_TABLE_SQL)
        for _, row in working_df.iterrows():
            params = {col: _clean_value(row.get(col)) for col in PREDICTION_COLUMNS}
            conn.execute(UPSERT_PREDICTION_SQL, params)
            rows_upserted += 1

    logger.info("DB: upserted %s rows into fact_weekly_fuel_predictions", rows_upserted)
    return rows_upserted


def _clean_value(val):
    """Convert pandas NaN/NaT to None and numpy scalars to Python native types."""
    if pd.isna(val):
        return None

    import numpy as np

    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return val
