"""
Data quality checks — soft validation before loading.
All checks produce warnings, not hard failures.
"""
import logging
import pandas as pd
from dataclasses import dataclass, field
from src.config.settings import (
    RON_PRICE_MIN, RON_PRICE_MAX,
    BRENT_PRICE_MIN, BRENT_PRICE_MAX,
    WEEK_OVER_WEEK_MAX_CHANGE_PCT,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Container for validation output."""
    is_valid: bool = True
    warnings: list = field(default_factory=list)
    row_count: int = 0

    def add_warning(self, msg: str):
        self.warnings.append(msg)
        logger.warning(f"DQ: {msg}")

    def summary(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "warning_count": len(self.warnings),
            "warnings": self.warnings,
            "row_count": self.row_count,
        }


def validate(df: pd.DataFrame) -> ValidationResult:
    """
    Run data quality checks on transformed DataFrame.

    Checks:
      1. No nulls in required columns
      2. RON prices within RM 1.00 - RM 10.00
      3. Brent prices within $20 - $200
      4. Week-over-week change < 30%
      5. No duplicate pricing_week_start

    Args:
        df: Transformed DataFrame with fact_weekly_fuel_pricing columns.

    Returns:
        ValidationResult with warnings (soft fail, never blocks pipeline).
    """
    result = ValidationResult(row_count=len(df))

    if df.empty:
        result.add_warning("DataFrame is empty — nothing to validate")
        return result

    # 1. Check nulls in required columns
    required_cols = ["pricing_week_start", "pricing_week_end", "ron97_price_myr", "ron95_price_myr"]
    for col in required_cols:
        if col in df.columns:
            null_count = df[col].isna().sum()
            if null_count > 0:
                result.add_warning(f"Column '{col}' has {null_count} null values")

    # 2. RON price range
    for col in ["ron97_price_myr", "ron95_price_myr"]:
        if col in df.columns:
            out_of_range = df[
                (df[col] < RON_PRICE_MIN) | (df[col] > RON_PRICE_MAX)
            ]
            if not out_of_range.empty:
                result.add_warning(
                    f"{len(out_of_range)} rows have {col} outside "
                    f"RM {RON_PRICE_MIN}-{RON_PRICE_MAX} range"
                )

    # 3. Brent price range
    if "avg_brent_t2_usd" in df.columns:
        brent_valid = df["avg_brent_t2_usd"].dropna()
        out_of_range = brent_valid[
            (brent_valid < BRENT_PRICE_MIN) | (brent_valid > BRENT_PRICE_MAX)
        ]
        if not out_of_range.empty:
            result.add_warning(
                f"{len(out_of_range)} rows have avg_brent_t2_usd outside "
                f"${BRENT_PRICE_MIN}-${BRENT_PRICE_MAX} range"
            )

    # 4. Week-over-week change
    if "ron97_price_myr" in df.columns and len(df) >= 2:
        sorted_df = df.sort_values("pricing_week_start")
        pct_change = sorted_df["ron97_price_myr"].pct_change().abs() * 100
        anomalies = pct_change[pct_change > WEEK_OVER_WEEK_MAX_CHANGE_PCT]
        if not anomalies.empty:
            result.add_warning(
                f"{len(anomalies)} rows have RON97 week-over-week change "
                f"> {WEEK_OVER_WEEK_MAX_CHANGE_PCT}%"
            )

    # 5. Duplicate check
    if "pricing_week_start" in df.columns:
        dupes = df["pricing_week_start"].duplicated().sum()
        if dupes > 0:
            result.add_warning(f"{dupes} duplicate pricing_week_start values found")

    logger.info(f"DQ: validation complete — {len(result.warnings)} warnings, {result.row_count} rows")
    return result
