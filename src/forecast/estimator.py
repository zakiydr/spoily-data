"""
Forecast estimator — Step 1: Simple proportional projection.

Logic:
  If Brent moved X% from T-2(previous) to T-1(current),
  BBM likely moves by a similar proportion.

  predicted_bbm[next] ≈ last_actual_bbm * (1 + brent_change_pct)
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def predict_next_week(historical_df: pd.DataFrame) -> dict:
    """
    Predict next week's fuel prices based on Brent price changes.

    Args:
        historical_df: DataFrame with columns from fact_weekly_fuel_pricing,
                       sorted by pricing_week_start ascending.

    Returns:
        dict with keys: predicted_ron97, predicted_ron95, confidence
        Returns empty dict if not enough data.
    """
    # Need at least 2 rows to compute change
    df = historical_df.dropna(subset=["avg_brent_t2_usd"]).copy()
    if len(df) < 2:
        logger.warning("Not enough historical data for prediction (need >= 2 rows with Brent data)")
        return {}

    # Get the last two rows (most recent weeks with Brent data)
    recent = df.sort_values("pricing_week_start").tail(2)
    prev_row = recent.iloc[0]
    curr_row = recent.iloc[1]

    prev_brent = prev_row["avg_brent_t2_usd"]
    curr_brent = curr_row["avg_brent_t2_usd"]

    if prev_brent == 0 or pd.isna(prev_brent):
        logger.warning("Previous Brent price is zero or NaN, cannot predict")
        return {}

    brent_change_pct = (curr_brent - prev_brent) / prev_brent

    # Apply change to current actual BBM prices
    last_ron97 = curr_row["ron97_price_myr"]
    last_ron95 = curr_row["ron95_price_myr"]

    predicted_ron97 = round(last_ron97 * (1 + brent_change_pct), 4)
    predicted_ron95 = round(last_ron95 * (1 + brent_change_pct), 4)

    # Confidence: based on how well past predictions matched actuals
    confidence = _calculate_confidence(df)

    result = {
        "predicted_ron97": predicted_ron97,
        "predicted_ron95": predicted_ron95,
        "confidence": confidence,
    }

    logger.info(
        f"Prediction: RON97={predicted_ron97}, RON95={predicted_ron95}, "
        f"Brent Δ={brent_change_pct:+.2%}, confidence={confidence:.2f}"
    )
    return result


def enrich_with_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add prediction columns to the transformed DataFrame.
    For each row (except the first), predict based on the row before it,
    then compute delta between predicted and actual.

    Args:
        df: Transformed DataFrame sorted by pricing_week_start.

    Returns:
        Same DataFrame with predicted_ron97_myr, predicted_ron95_myr,
        and prediction_delta_pct columns filled in.
    """
    df = df.copy()
    df["predicted_ron97_myr"] = None
    df["predicted_ron95_myr"] = None
    df["prediction_delta_pct"] = None

    df = df.sort_values("pricing_week_start").reset_index(drop=True)

    for i in range(2, len(df)):
        # Use rows up to i to predict row i
        history = df.iloc[:i]
        prediction = predict_next_week(history)

        if prediction:
            df.at[i, "predicted_ron97_myr"] = prediction["predicted_ron97"]
            df.at[i, "predicted_ron95_myr"] = prediction["predicted_ron95"]

            # Delta: (actual - predicted) / actual * 100
            actual_ron97 = df.at[i, "ron97_price_myr"]
            predicted_ron97 = prediction["predicted_ron97"]
            if actual_ron97 and actual_ron97 != 0:
                delta = round((actual_ron97 - predicted_ron97) / actual_ron97 * 100, 2)
                df.at[i, "prediction_delta_pct"] = delta

    return df


def _calculate_confidence(df: pd.DataFrame) -> float:
    """
    Simple confidence score based on recent prediction accuracy.
    Returns value between 0.0 and 1.0.
    """
    deltas = df["prediction_delta_pct"].dropna() if "prediction_delta_pct" in df.columns else pd.Series(dtype="float64")

    if deltas.empty:
        return 0.5  # default confidence when no history

    # Average absolute delta — lower is better
    avg_abs_delta = deltas.abs().mean()

    # Map to confidence: 0% delta → 1.0, 10%+ delta → 0.0
    confidence = max(0.0, min(1.0, 1.0 - (avg_abs_delta / 10.0)))
    return round(confidence, 2)
