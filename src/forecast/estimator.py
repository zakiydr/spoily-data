"""
Forecast estimator supporting methodology audit and production predictions.

Implements walk-forward backtesting for:
- Proportional model
- Linear regression model
Across lag windows T-1 and T-2.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


FUEL_TARGETS = {
    "RON97": "ron97_price_myr",
    "RON95": "ron95_price_myr",
}

MODEL_TYPES = ("proportional", "linear_regression")
LAGS = (1, 2)


def enrich_with_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible wrapper: returns only enriched fact rows."""
    enriched_df, _, _ = build_prediction_outputs(df)
    return enriched_df


def build_prediction_outputs(
    df: pd.DataFrame,
    min_regression_train_rows: int = 12,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """
    Build prediction history and select best methodology per fuel type.

    Returns:
        tuple:
          1) enriched weekly fact DataFrame (for `fact_weekly_fuel_pricing`)
          2) prediction history DataFrame (for dashboard/audit table)
          3) summary dict with selected model per fuel and MAPE stats
    """
    base_df = df.copy().sort_values("pricing_week_start").reset_index(drop=True)

    prediction_history_rows: list[dict[str, Any]] = []

    for fuel_type, actual_col in FUEL_TARGETS.items():
        for lag_weeks in LAGS:
            for model_type in MODEL_TYPES:
                model_rows = _walk_forward_predictions(
                    df=base_df,
                    fuel_type=fuel_type,
                    actual_col=actual_col,
                    lag_weeks=lag_weeks,
                    model_type=model_type,
                    min_regression_train_rows=min_regression_train_rows,
                )
                prediction_history_rows.extend(model_rows)

    prediction_history_df = pd.DataFrame(prediction_history_rows)

    if prediction_history_df.empty:
        logger.warning("Prediction history is empty; returning unchanged frame")
        base_df["predicted_ron97_myr"] = None
        base_df["predicted_ron95_myr"] = None
        base_df["prediction_delta_pct"] = None
        return base_df, prediction_history_df, {"selected_models": {}, "mape": {}}

    summary_df = prediction_history_df.groupby(
        ["fuel_type", "model_type", "lag_weeks"], as_index=False
    ).agg(mape=("abs_pct_error", "mean"), rows=("abs_pct_error", "count"))
    summary_df = pd.DataFrame(summary_df)
    summary_df["rows_rank"] = -summary_df["rows"]
    summary_df = summary_df.sort_values(["fuel_type", "mape", "rows_rank"]).drop(
        columns=["rows_rank"]
    )

    selected_models: dict[str, dict[str, Any]] = {}
    for fuel_type in FUEL_TARGETS:
        fuel_summary = summary_df[summary_df["fuel_type"] == fuel_type]
        if fuel_summary.empty:
            continue
        best = fuel_summary.iloc[0]
        selected_models[fuel_type] = {
            "model_type": str(best["model_type"]),
            "lag_weeks": int(best["lag_weeks"]),
            "mape": round(float(best["mape"]), 4),
            "rows": int(best["rows"]),
        }

    enriched_df = base_df.copy()
    enriched_df["predicted_ron97_myr"] = None
    enriched_df["predicted_ron95_myr"] = None
    enriched_df["prediction_delta_pct"] = None

    enriched_df = _merge_selected_predictions(
        enriched_df=enriched_df,
        prediction_history_df=prediction_history_df,
        fuel_type="RON97",
        output_col="predicted_ron97_myr",
        selection=selected_models.get("RON97"),
    )
    enriched_df = _merge_selected_predictions(
        enriched_df=enriched_df,
        prediction_history_df=prediction_history_df,
        fuel_type="RON95",
        output_col="predicted_ron95_myr",
        selection=selected_models.get("RON95"),
    )

    # Keep compatibility with existing schema: single delta column based on RON97.
    valid = (
        enriched_df["predicted_ron97_myr"].notna()
        & enriched_df["ron97_price_myr"].notna()
    )
    enriched_df.loc[valid, "prediction_delta_pct"] = (
        (
            enriched_df.loc[valid, "ron97_price_myr"]
            - enriched_df.loc[valid, "predicted_ron97_myr"]
        )
        / enriched_df.loc[valid, "ron97_price_myr"]
        * 100
    ).round(2)

    summary = {
        "selected_models": selected_models,
        "mape": summary_df.to_dict(orient="records"),
    }

    logger.info("Selected models: %s", selected_models)
    return enriched_df, prediction_history_df, summary


def _walk_forward_predictions(
    df: pd.DataFrame,
    fuel_type: str,
    actual_col: str,
    lag_weeks: int,
    model_type: str,
    min_regression_train_rows: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    brent_col = f"avg_brent_t{lag_weeks}_usd"
    fx_col = f"avg_usd_myr_t{lag_weeks}"

    if brent_col not in df.columns:
        logger.warning("Missing required column for lag %s: %s", lag_weeks, brent_col)
        return rows

    work = df[
        ["pricing_week_start", actual_col, brent_col]
        + ([fx_col] if fx_col in df.columns else [])
    ].copy()
    if fx_col not in work.columns:
        work[fx_col] = np.nan

    work["feature_brent_myr"] = work[brent_col] * work[fx_col]

    for i in range(1, len(work)):
        current = work.iloc[i]
        current_week = current["pricing_week_start"]
        actual_price = current[actual_col]
        predicted_price: float | None = None

        if pd.isna(actual_price) or pd.isna(current[brent_col]):
            continue

        if model_type == "proportional":
            prev = work.iloc[i - 1]
            prev_brent = prev[brent_col]
            prev_actual = prev[actual_col]
            curr_brent = current[brent_col]

            if pd.notna(prev_brent) and prev_brent != 0 and pd.notna(prev_actual):
                change_pct = (curr_brent - prev_brent) / prev_brent
                predicted_price = float(round(prev_actual * (1 + change_pct), 4))

        elif model_type == "linear_regression":
            train = work.iloc[:i].dropna(subset=["feature_brent_myr", actual_col])
            if len(train) >= min_regression_train_rows and pd.notna(
                current["feature_brent_myr"]
            ):
                x = train["feature_brent_myr"].to_numpy(dtype=float)
                y = train[actual_col].to_numpy(dtype=float)
                if np.unique(x).size >= 2:
                    slope, intercept = np.polyfit(x, y, 1)
                    predicted_price = float(
                        round(
                            (slope * float(current["feature_brent_myr"])) + intercept, 4
                        )
                    )
        else:
            raise ValueError(f"Unsupported model type: {model_type}")

        if predicted_price is None:
            continue

        abs_pct_error = (
            abs((predicted_price - float(actual_price)) / float(actual_price)) * 100
        )
        signed_pct_error = (
            (float(actual_price) - predicted_price) / float(actual_price)
        ) * 100

        rows.append(
            {
                "pricing_week_start": current_week,
                "fuel_type": fuel_type,
                "model_type": model_type,
                "lag_weeks": lag_weeks,
                "predicted_price_myr": predicted_price,
                "actual_price_myr": float(actual_price),
                "abs_pct_error": round(float(abs_pct_error), 4),
                "signed_pct_error": round(float(signed_pct_error), 4),
            }
        )

    return rows


def _merge_selected_predictions(
    enriched_df: pd.DataFrame,
    prediction_history_df: pd.DataFrame,
    fuel_type: str,
    output_col: str,
    selection: dict[str, Any] | None,
) -> pd.DataFrame:
    if selection is None:
        return enriched_df

    selected_rows = prediction_history_df.loc[
        (prediction_history_df["fuel_type"] == fuel_type)
        & (prediction_history_df["model_type"] == selection["model_type"])
        & (prediction_history_df["lag_weeks"] == selection["lag_weeks"]),
        ["pricing_week_start", "predicted_price_myr"],
    ].copy()
    selected_rows = selected_rows.rename(columns={"predicted_price_myr": output_col})

    merged = enriched_df.merge(
        selected_rows, on="pricing_week_start", how="left", suffixes=("", "__selected")
    )
    merged[output_col] = merged[f"{output_col}__selected"]
    return merged.drop(columns=[f"{output_col}__selected"])
