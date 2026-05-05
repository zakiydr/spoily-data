import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from src.config.settings import DATABASE_URL

def fetch_data() -> pd.DataFrame:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT * FROM fact_weekly_fuel_pricing ORDER BY pricing_week_start"),
            conn,
        )
    return df

def run_comparison():
    df = fetch_data()
    df = df.dropna(subset=["avg_brent_t2_usd", "avg_usd_myr_t2", "ron97_price_myr", "ron95_price_myr"]).copy()
    
    # Feature for regression: Brent price in MYR (Brent USD * USD/MYR exchange rate)
    df["brent_myr"] = df["avg_brent_t2_usd"] * df["avg_usd_myr_t2"]
    
    # --- 1. Methodology: T-2 (Proportional) ---
    # This is already in the DB as predicted_ron97_myr and predicted_ron95_myr
    # But let's verify or re-calculate if needed. 
    # Actually, the DB has them from the pipeline run.
    
    # --- 2. Methodology: Regression ---
    # We use historical data to fit a model. 
    # For a fair comparison, should we use "walk-forward" validation?
    # Yes, for each week, we train on all previous weeks and predict the current one.
    
    df["regression_ron97"] = None
    df["regression_ron95"] = None
    
    # Start regression from week 5 to have some training data
    for i in range(5, len(df)):
        train = df.iloc[:i]
        
        # Fit RON97
        m97, c97 = np.polyfit(train["brent_myr"], train["ron97_price_myr"], 1)
        # Fit RON95
        m95, c95 = np.polyfit(train["brent_myr"], train["ron95_price_myr"], 1)
        
        current_brent_myr = df.iloc[i]["brent_myr"]
        df.at[df.index[i], "regression_ron97"] = round(m97 * current_brent_myr + c97, 4)
        df.at[df.index[i], "regression_ron95"] = round(m95 * current_brent_myr + c95, 4)

    df["pricing_week_start"] = pd.to_datetime(df["pricing_week_start"])
    # Filter for 2026 data
    df_2026 = df[df["pricing_week_start"] >= pd.Timestamp("2026-01-01")].copy()
    
    # Preparation for display table
    table = df_2026[[
        "pricing_week_start", 
        "ron97_price_myr", "predicted_ron97_myr", "regression_ron97",
        "ron95_price_myr", "predicted_ron95_myr", "regression_ron95"
    ]].copy()
    
    table.columns = [
        "Week", "RON97_Actual", "RON97_T2", "RON97_Regr",
        "RON95_Actual", "RON95_T2", "RON95_Regr"
    ]
    
    # Calculate Errors
    table["T2_Err97_%"] = (abs(table["RON97_T2"] - table["RON97_Actual"]) / table["RON97_Actual"] * 100).astype(float)
    table["Regr_Err97_%"] = (abs(table["RON97_Regr"] - table["RON97_Actual"]) / table["RON97_Actual"] * 100).astype(float)
    table["T2_Err95_%"] = (abs(table["RON95_T2"] - table["RON95_Actual"]) / table["RON95_Actual"] * 100).astype(float)
    table["Regr_Err95_%"] = (abs(table["RON95_Regr"] - table["RON95_Actual"]) / table["RON95_Actual"] * 100).astype(float)
    
    print("\n" + "="*120)
    print("ACCURACY COMPARISON: T-2 vs REGRESSION (2026)")
    print("="*120)
    print(table.to_string(index=False, formatters={
        "RON97_Actual": "{:.2f}".format, "RON97_T2": "{:.2f}".format, "RON97_Regr": "{:.2f}".format,
        "RON95_Actual": "{:.2f}".format, "RON95_T2": "{:.2f}".format, "RON95_Regr": "{:.2f}".format,
        "T2_Err97_%": "{:.1f}%".format, "Regr_Err97_%": "{:.1f}%".format,
        "T2_Err95_%": "{:.1f}%".format, "Regr_Err95_%": "{:.1f}%".format
    }))
    
    print("\nSummary Metrics (MAPE):")
    print(f"  RON97 T-2         : {table['T2_Err97_%'].mean():.2f}%")
    print(f"  RON97 Regression  : {table['Regr_Err97_%'].dropna().mean():.2f}%")
    print(f"  RON95 T-2         : {table['T2_Err95_%'].mean():.2f}%")
    print(f"  RON95 Regression  : {table['Regr_Err95_%'].dropna().mean():.2f}%")
    
if __name__ == "__main__":
    run_comparison()
