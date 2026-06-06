-- Spoily Data: Fuel Price Predictor Schema
-- Run this in Supabase SQL Editor

-- ── Fact Table ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_weekly_fuel_pricing (
    pricing_week_start   DATE PRIMARY KEY,
    pricing_week_end     DATE NOT NULL,
    ron97_price_myr      DECIMAL(6,4) NOT NULL,
    ron95_price_myr      DECIMAL(6,4) NOT NULL,       -- non-subsidized price
    avg_brent_t2_usd     DECIMAL(8,2),                 -- avg Brent 2 weeks prior
    avg_usd_myr_t2       DECIMAL(8,4),                 -- avg exchange rate 2 weeks prior
    predicted_ron97_myr  DECIMAL(6,4),                 -- predicted from T-2 Brent
    predicted_ron95_myr  DECIMAL(6,4),                 -- predicted from T-2 Brent
    prediction_delta_pct DECIMAL(5,2),                 -- (actual - predicted) / actual * 100
    last_updated         TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT chk_positive CHECK (ron97_price_myr > 0 AND ron95_price_myr > 0)
);

CREATE INDEX IF NOT EXISTS idx_week ON fact_weekly_fuel_pricing(pricing_week_start DESC);

-- ── Prediction Audit Table ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_weekly_fuel_predictions (
    pricing_week_start DATE NOT NULL,
    fuel_type          TEXT NOT NULL,   -- RON95 / RON97
    model_type         TEXT NOT NULL,   -- proportional / linear_regression
    lag_weeks          SMALLINT NOT NULL, -- 1 (T-1) / 2 (T-2)
    predicted_price_myr DECIMAL(8,4) NOT NULL,
    actual_price_myr    DECIMAL(8,4) NOT NULL,
    abs_pct_error       DECIMAL(8,4) NOT NULL,
    signed_pct_error    DECIMAL(8,4) NOT NULL,
    last_updated        TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (pricing_week_start, fuel_type, model_type, lag_weeks)
);

CREATE INDEX IF NOT EXISTS idx_predictions_week
    ON fact_weekly_fuel_predictions(pricing_week_start DESC);

-- ── Row Level Security ─────────────────────────────────────────────────────
ALTER TABLE fact_weekly_fuel_pricing ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_weekly_fuel_predictions ENABLE ROW LEVEL SECURITY;

-- Public can read
CREATE POLICY "public_read" ON fact_weekly_fuel_pricing
    FOR SELECT USING (true);

CREATE POLICY "public_read_predictions" ON fact_weekly_fuel_predictions
    FOR SELECT USING (true);

-- Only service role can write
CREATE POLICY "service_write" ON fact_weekly_fuel_pricing
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_write_predictions" ON fact_weekly_fuel_predictions
    FOR ALL USING (auth.role() = 'service_role');
