"""
Pipeline orchestrator — runs the full ETL cycle:
  Extract → Transform → Forecast → Validate → Load → Status Report

Run with: python -m src.pipeline
"""

from __future__ import annotations

import json
import logging
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from src.config.settings import (
    ALERT_EMAIL_FROM,
    ALERT_EMAIL_TO,
    DATE_FORMAT,
    PROJECT_ROOT,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)
from src.extract.brent_crude import fetch_brent_prices
from src.extract.exchange_rate import fetch_usd_myr_rates
from src.extract.malaysia_fuel import fetch_fuel_prices
from src.forecast.estimator import build_prediction_outputs
from src.load.database import upsert, upsert_prediction_history
from src.quality.checks import validate
from src.transform.processor import transform_weekly


def setup_logging():
    """Configure structured logging to console + file."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    log_file = (
        PROJECT_ROOT
        / "logs"
        / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def run_pipeline():
    """
    Main pipeline entry point.

    Scope:
    - Backfills approximately 3 years of weekly history.
    - Benchmarks proportional vs linear regression using T-1 and T-2 lag windows.
    - Persists both fact rows and model prediction history tables.
    """
    setup_logging()
    logger = logging.getLogger("pipeline")

    pipeline_start = time.time()
    status = {
        "last_run": datetime.now().isoformat(),
        "status": "running",
        "stages": {},
        "rows_loaded": 0,
        "prediction_rows_loaded": 0,
        "dq_warnings": [],
        "model_selection": {},
        "duration_seconds": 0,
        "error": None,
    }

    try:
        end_date = datetime.now().strftime(DATE_FORMAT)
        # +30 days to preserve lag windows for earliest target week
        start_date = (datetime.now() - timedelta(days=(3 * 365) + 30)).strftime(
            DATE_FORMAT
        )

        logger.info("=" * 60)
        logger.info("STAGE 1: EXTRACT")
        logger.info("=" * 60)

        t0 = time.time()
        logger.info("Extracting Brent prices: %s to %s", start_date, end_date)
        brent_df = fetch_brent_prices(start_date, end_date)
        status["stages"]["extract_brent"] = {
            "rows": len(brent_df),
            "duration_ms": int((time.time() - t0) * 1000),
        }

        t0 = time.time()
        logger.info("Extracting fuel prices: %s to %s", start_date, end_date)
        fuel_df = fetch_fuel_prices(start_date, end_date)
        status["stages"]["extract_fuel"] = {
            "rows": len(fuel_df),
            "duration_ms": int((time.time() - t0) * 1000),
        }

        t0 = time.time()
        logger.info("Extracting exchange rates: %s to %s", start_date, end_date)
        rates_df = fetch_usd_myr_rates(start_date, end_date)
        status["stages"]["extract_rates"] = {
            "rows": len(rates_df),
            "duration_ms": int((time.time() - t0) * 1000),
        }

        logger.info(
            "Extract complete: Brent=%s, Fuel=%s, Rates=%s",
            len(brent_df),
            len(fuel_df),
            len(rates_df),
        )

        logger.info("=" * 60)
        logger.info("STAGE 2: TRANSFORM + FORECAST")
        logger.info("=" * 60)

        t0 = time.time()
        transformed_df = transform_weekly(brent_df, fuel_df, rates_df)
        enriched_df, prediction_history_df, model_summary = build_prediction_outputs(
            transformed_df
        )
        status["stages"]["transform"] = {
            "rows": len(enriched_df),
            "prediction_rows": len(prediction_history_df),
            "duration_ms": int((time.time() - t0) * 1000),
        }
        status["model_selection"] = model_summary.get("selected_models", {})

        logger.info("Transform complete: %s weekly rows", len(enriched_df))
        logger.info("Prediction history generated: %s rows", len(prediction_history_df))
        logger.info("Model selection: %s", status["model_selection"])

        logger.info("=" * 60)
        logger.info("STAGE 3: DATA QUALITY")
        logger.info("=" * 60)

        t0 = time.time()
        dq_result = validate(enriched_df)
        status["stages"]["quality"] = {
            "warnings": len(dq_result.warnings),
            "duration_ms": int((time.time() - t0) * 1000),
        }
        status["dq_warnings"] = dq_result.warnings

        logger.info("DQ complete: %s warnings", len(dq_result.warnings))

        logger.info("=" * 60)
        logger.info("STAGE 4: LOAD")
        logger.info("=" * 60)

        t0 = time.time()
        rows_loaded = upsert(enriched_df)
        prediction_rows_loaded = upsert_prediction_history(prediction_history_df)
        status["stages"]["load"] = {
            "rows": rows_loaded,
            "prediction_rows": prediction_rows_loaded,
            "duration_ms": int((time.time() - t0) * 1000),
        }
        status["rows_loaded"] = rows_loaded
        status["prediction_rows_loaded"] = prediction_rows_loaded

        logger.info(
            "Load complete: fact=%s rows, predictions=%s rows",
            rows_loaded,
            prediction_rows_loaded,
        )

        status["status"] = "success"
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE — SUCCESS")
        logger.info("=" * 60)

    except Exception as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        logger.exception("Pipeline failed: %s", exc)
        _send_alert(f"Pipeline FAILED: {exc}")

    finally:
        status["duration_seconds"] = round(time.time() - pipeline_start, 2)
        _write_status(status)

    return status


def _write_status(status: dict):
    """Write pipeline run status to JSON file."""
    status_path = PROJECT_ROOT / "pipeline_status.json"
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2, default=str)
    logging.getLogger("pipeline").info("Status written to %s", status_path)


def _send_alert(message: str):
    """Send failure alert via email (if configured)."""
    logger = logging.getLogger("pipeline.alert")

    if not all([ALERT_EMAIL_TO, SMTP_USER, SMTP_PASSWORD]):
        logger.info("Email alerting not configured, skipping alert")
        return

    try:
        msg = MIMEText(
            f"Spoily Data Pipeline Alert\n\n{message}\n\nTimestamp: {datetime.now().isoformat()}"
        )
        msg["Subject"] = "🚨 Spoily Data Pipeline Alert"
        msg["From"] = ALERT_EMAIL_FROM or SMTP_USER
        msg["To"] = ALERT_EMAIL_TO

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Alert email sent to %s", ALERT_EMAIL_TO)
    except Exception as exc:
        logger.error("Failed to send alert email: %s", exc)


if __name__ == "__main__":
    run_pipeline()
