"""
Accuracy analysis: Brent T-2 -> Malaysia fuel price predictions.
Pulls data from Supabase, computes correlation and prediction error metrics.

Run:  python -m scripts.analyze_accuracy
"""
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from src.config.settings import DATABASE_URL

pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", "{:.4f}".format)


def fetch_data() -> pd.DataFrame:
    """Pull all rows from fact_weekly_fuel_pricing."""
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT * FROM fact_weekly_fuel_pricing ORDER BY pricing_week_start"),
            conn,
        )
    print(f"Fetched {len(df)} rows from Supabase\n")
    return df


def analyze(df: pd.DataFrame):
    # -- 1. Data overview -------------------------------------------------
    print("=" * 80)
    print("1. DATA OVERVIEW")
    print("=" * 80)
    print(f"  Period         : {df['pricing_week_start'].min()} -> {df['pricing_week_start'].max()}")
    print(f"  Total weeks    : {len(df)}")
    print(f"  Weeks w/ Brent : {df['avg_brent_t2_usd'].notna().sum()}")
    print(f"  Weeks w/ preds : {df['predicted_ron97_myr'].notna().sum()}")
    print()

    # -- 2. Actual price ranges -------------------------------------------
    print("=" * 80)
    print("2. ACTUAL PRICE RANGES")
    print("=" * 80)
    for col, label in [
        ("ron97_price_myr", "RON97 (MYR)"),
        ("ron95_price_myr", "RON95 (MYR)"),
        ("avg_brent_t2_usd", "Brent T-2 (USD)"),
        ("avg_usd_myr_t2", "USD/MYR T-2"),
    ]:
        vals = df[col].dropna()
        if vals.empty:
            print(f"  {label:20s} : no data")
        else:
            print(f"  {label:20s} : {vals.min():.4f} - {vals.max():.4f}  (mean {vals.mean():.4f}, std {vals.std():.4f})")
    print()

    # -- 3. Brent <-> Fuel correlation ------------------------------------
    print("=" * 80)
    print("3. BRENT <-> FUEL PRICE CORRELATION (T-2 lag)")
    print("=" * 80)
    corr_df = df.dropna(subset=["avg_brent_t2_usd", "ron97_price_myr", "ron95_price_myr"])
    if len(corr_df) >= 3:
        r97 = corr_df["avg_brent_t2_usd"].corr(corr_df["ron97_price_myr"])
        r95 = corr_df["avg_brent_t2_usd"].corr(corr_df["ron95_price_myr"])
        print(f"  Brent T-2 vs RON97 : r = {r97:+.4f}  (R2 = {r97**2:.4f})")
        print(f"  Brent T-2 vs RON95 : r = {r95:+.4f}  (R2 = {r95**2:.4f})")

        # Also check Brent*USD/MYR vs fuel (since fuel is in MYR)
        corr_df2 = corr_df.dropna(subset=["avg_usd_myr_t2"])
        if len(corr_df2) >= 3:
            corr_df2 = corr_df2.copy()
            corr_df2["brent_myr"] = corr_df2["avg_brent_t2_usd"] * corr_df2["avg_usd_myr_t2"]
            r97m = corr_df2["brent_myr"].corr(corr_df2["ron97_price_myr"])
            r95m = corr_df2["brent_myr"].corr(corr_df2["ron95_price_myr"])
            print(f"  Brent*FX vs RON97  : r = {r97m:+.4f}  (R2 = {r97m**2:.4f})  <- MYR-adjusted")
            print(f"  Brent*FX vs RON95  : r = {r95m:+.4f}  (R2 = {r95m**2:.4f})  <- MYR-adjusted")
    else:
        print("  Not enough data for correlation (need >= 3 rows with Brent)")
    print()

    # -- 4. Prediction accuracy -------------------------------------------
    print("=" * 80)
    print("4. PREDICTION ACCURACY (proportional model)")
    print("=" * 80)
    pred_df = df.dropna(subset=["predicted_ron97_myr", "ron97_price_myr"]).copy()
    if pred_df.empty:
        print("  No prediction data available")
        return

    pred_df["error_ron97"] = pred_df["predicted_ron97_myr"] - pred_df["ron97_price_myr"]
    pred_df["error_ron95"] = pred_df["predicted_ron95_myr"] - pred_df["ron95_price_myr"]
    pred_df["abs_pct_error_ron97"] = (pred_df["error_ron97"].abs() / pred_df["ron97_price_myr"]) * 100
    pred_df["abs_pct_error_ron95"] = (pred_df["error_ron95"].abs() / pred_df["ron95_price_myr"]) * 100

    for fuel, col_err, col_pct in [
        ("RON97", "error_ron97", "abs_pct_error_ron97"),
        ("RON95", "error_ron95", "abs_pct_error_ron95"),
    ]:
        err = pred_df[col_err]
        pct = pred_df[col_pct]
        print(f"\n  {fuel}:")
        print(f"    Mean Absolute Error (MAE) : RM {err.abs().mean():.4f}")
        print(f"    Mean Abs % Error (MAPE)   : {pct.mean():.2f}%")
        print(f"    Median Abs % Error        : {pct.median():.2f}%")
        print(f"    Max Abs % Error           : {pct.max():.2f}%")
        print(f"    Mean Bias (signed)        : RM {err.mean():+.4f}  ({'over-predicts' if err.mean() > 0 else 'under-predicts'})")
        within_5 = (pct <= 5.0).sum()
        print(f"    Within +/-5% accuracy     : {within_5}/{len(pct)} ({within_5/len(pct)*100:.0f}%)")
        within_10 = (pct <= 10.0).sum()
        print(f"    Within +/-10% accuracy    : {within_10}/{len(pct)} ({within_10/len(pct)*100:.0f}%)")
    print()

    # -- 5. Week-by-week detail table -------------------------------------
    print("=" * 80)
    print("5. WEEK-BY-WEEK DETAIL")
    print("=" * 80)
    detail = pred_df[[
        "pricing_week_start",
        "avg_brent_t2_usd",
        "ron97_price_myr", "predicted_ron97_myr", "abs_pct_error_ron97",
        "ron95_price_myr", "predicted_ron95_myr", "abs_pct_error_ron95",
    ]].copy()
    detail.columns = [
        "Week", "Brent_T2",
        "RON97_Act", "RON97_Pred", "RON97_Err%",
        "RON95_Act", "RON95_Pred", "RON95_Err%",
    ]
    print(detail.to_string(index=False))
    print()

    # -- 6. Direction accuracy --------------------------------------------
    print("=" * 80)
    print("6. DIRECTION ACCURACY (did we predict the right up/down?)")
    print("=" * 80)
    pred_sorted = pred_df.sort_values("pricing_week_start").reset_index(drop=True)
    if len(pred_sorted) >= 2:
        actual_change = pred_sorted["ron97_price_myr"].diff()
        pred_change = pred_sorted["predicted_ron97_myr"] - pred_sorted["ron97_price_myr"].shift(1)
        valid = actual_change.notna() & pred_change.notna()
        if valid.sum() > 0:
            correct = ((actual_change[valid] > 0) == (pred_change[valid] > 0)).sum()
            total = valid.sum()
            print(f"  RON97 direction correct : {correct}/{total} ({correct/total*100:.0f}%)")
    print()

    # -- 7. Summary verdict -----------------------------------------------
    print("=" * 80)
    print("7. VERDICT")
    print("=" * 80)
    mape97 = pred_df["abs_pct_error_ron97"].mean()
    if mape97 <= 5:
        verdict = "[GOOD] Step 1 proportional model is adequate (MAPE <= 5%)"
    elif mape97 <= 10:
        verdict = "[FAIR] Consider upgrading to linear regression (Step 2)"
    else:
        verdict = "[POOR] Model needs Step 2 upgrade (linear regression / sklearn)"
    print(f"  RON97 MAPE = {mape97:.2f}%  ->  {verdict}")
    print()


if __name__ == "__main__":
    df = fetch_data()
    analyze(df)
