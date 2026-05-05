"""
Pipeline orchestrator — runs the full ETL cycle:
  Extract → Transform → Forecast → Validate → Load → Status Report

Can be run as:  python -m src.pipeline
"""
import json
import time
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

from src.config.settings import (
    DATE_FORMAT, PROJECT_ROOT,
    ALERT_EMAIL_TO, ALERT_EMAIL_FROM,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
)
from src.extract.brent_crude import fetch_brent_prices
from src.extract.malaysia_fuel import fetch_fuel_prices
from src.extract.exchange_rate import fetch_usd_myr_rates
from src.transform.processor import transform_weekly
from src.forecast.estimator import enrich_with_predictions
from src.quality.checks import validate
from src.load.database import upsert


def setup_logging():
    """Configure structured JSON-ish logging to console + file."""
    log_format = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    log_file = PROJECT_ROOT / "logs" / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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
    Extracts 2026 data, transforms, predicts, validates, and loads to DB.
    """
    setup_logging()
    logger = logging.getLogger("pipeline")

    pipeline_start = time.time()
    status = {
        "last_run": datetime.now().isoformat(),
        "status": "running",
        "stages": {},
        "rows_loaded": 0,
        "dq_warnings": [],
        "duration_seconds": 0,
        "error": None,
    }

    try:
        # ── Date range: 2026 YTD ────────────────────────────────────────
        # Pull extra weeks before Jan 1 for T-2 lag alignment
        start_date = "2025-12-01"
        end_date = datetime.now().strftime(DATE_FORMAT)

        # ── STAGE 1: Extract ────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("STAGE 1: EXTRACT")
        logger.info("=" * 60)

        t0 = time.time()
        logger.info(f"Extracting Brent prices: {start_date} to {end_date}")
        brent_df = fetch_brent_prices(start_date, end_date)
        status["stages"]["extract_brent"] = {
            "rows": len(brent_df), "duration_ms": int((time.time() - t0) * 1000)
        }

        t0 = time.time()
        logger.info(f"Extracting fuel prices: {start_date} to {end_date}")
        fuel_df = fetch_fuel_prices(start_date, end_date)
        status["stages"]["extract_fuel"] = {
            "rows": len(fuel_df), "duration_ms": int((time.time() - t0) * 1000)
        }

        t0 = time.time()
        logger.info(f"Extracting exchange rates: {start_date} to {end_date}")
        rates_df = fetch_usd_myr_rates(start_date, end_date)
        status["stages"]["extract_rates"] = {
            "rows": len(rates_df), "duration_ms": int((time.time() - t0) * 1000)
        }

        logger.info(f"Extract complete: Brent={len(brent_df)}, Fuel={len(fuel_df)}, Rates={len(rates_df)}")

        # ── STAGE 2: Transform + Forecast ───────────────────────────────
        logger.info("=" * 60)
        logger.info("STAGE 2: TRANSFORM + FORECAST")
        logger.info("=" * 60)

        t0 = time.time()
        transformed_df = transform_weekly(brent_df, fuel_df, rates_df)
        enriched_df = enrich_with_predictions(transformed_df)
        status["stages"]["transform"] = {
            "rows": len(enriched_df), "duration_ms": int((time.time() - t0) * 1000)
        }

        logger.info(f"Transform complete: {len(enriched_df)} weekly rows")

        # ── STAGE 3: Data Quality ───────────────────────────────────────
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

        logger.info(f"DQ complete: {len(dq_result.warnings)} warnings")

        # ── STAGE 4: Load ───────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("STAGE 4: LOAD")
        logger.info("=" * 60)

        t0 = time.time()
        rows_loaded = upsert(enriched_df)
        status["stages"]["load"] = {
            "rows": rows_loaded, "duration_ms": int((time.time() - t0) * 1000)
        }
        status["rows_loaded"] = rows_loaded

        logger.info(f"Load complete: {rows_loaded} rows upserted")

        # ── Done ────────────────────────────────────────────────────────
        status["status"] = "success"
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE — SUCCESS")
        logger.info("=" * 60)

    except Exception as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        logger.exception(f"Pipeline failed: {exc}")
        _send_alert(f"Pipeline FAILED: {exc}")

    finally:
        status["duration_seconds"] = round(time.time() - pipeline_start, 2)
        _write_status(status)

    return status


def _write_status(status: dict):
    """Write pipeline run status to JSON file."""
    status_path = PROJECT_ROOT / "pipeline_status.json"
    with open(status_path, "w") as f:
        json.dump(status, f, indent=2, default=str)
    logging.getLogger("pipeline").info(f"Status written to {status_path}")


def _send_alert(message: str):
    """Send failure alert via email (if configured)."""
    logger = logging.getLogger("pipeline.alert")

    if not all([ALERT_EMAIL_TO, SMTP_USER, SMTP_PASSWORD]):
        logger.info("Email alerting not configured, skipping alert")
        return

    try:
        msg = MIMEText(f"Spoily Data Pipeline Alert\n\n{message}\n\nTimestamp: {datetime.now().isoformat()}")
        msg["Subject"] = "🚨 Spoily Data Pipeline Alert"
        msg["From"] = ALERT_EMAIL_FROM or SMTP_USER
        msg["To"] = ALERT_EMAIL_TO

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Alert email sent to {ALERT_EMAIL_TO}")
    except Exception as exc:
        logger.error(f"Failed to send alert email: {exc}")


if __name__ == "__main__":
    run_pipeline()
