"""
Malaysian retail fuel price extractor — data.gov.my API.

Key schema notes (from live API testing):
  - Fields: date, ron95, ron97, diesel, ron95_skps, ron95_budi95, diesel_eastmsia, series_type
  - series_type = "level" → actual price; "change_weekly" → weekly delta (skip this)
  - ron95      → regular/non-subsidized retail price (target for this project)
  - Date = effective date (Thursday of pricing week)
"""

import logging
import time

import pandas as pd
import requests

from src.config.settings import (
    FUEL_PRICE_URL,
    HTTP_RETRY_BACKOFF_FACTOR,
    HTTP_RETRY_COUNT,
    HTTP_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


def fetch_fuel_prices(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch Malaysian weekly fuel prices from data.gov.my.

    Args:
        start_date: YYYY-MM-DD
        end_date:   YYYY-MM-DD

    Returns:
        DataFrame with columns [date, ron95, ron97]
        Only "level" rows (actual prices), not "change_weekly".
    """
    params = {
        "id": "fuelprice",
        "date_start": f"{start_date}@date",
        "date_end": f"{end_date}@date",
        "limit": 1000,
    }

    data = _request_with_retry(FUEL_PRICE_URL, params)

    if not data:
        logger.warning("data.gov.my: no data returned")
        return pd.DataFrame(columns=["date", "ron95", "ron97"])

    df = pd.DataFrame(data)

    # Filter only actual price levels, not weekly deltas
    df = df[df["series_type"] == "level"].copy()

    df["date"] = pd.to_datetime(df["date"])

    # Map fields to our schema
    result = pd.DataFrame(
        {
            "date": df["date"],
            "ron95": pd.to_numeric(df["ron95"], errors="coerce"),
            "ron97": pd.to_numeric(df["ron97"], errors="coerce"),
        }
    )

    result = (
        result.dropna(subset=["ron95", "ron97"])
        .sort_values("date")
        .reset_index(drop=True)
    )

    logger.info(
        f"data.gov.my: final DataFrame has {len(result)} rows, range {result['date'].min()} to {result['date'].max()}"
    )
    return result


def _request_with_retry(url: str, params: dict) -> list:
    """HTTP GET with exponential backoff retry. Returns parsed JSON list."""
    for attempt in range(1, HTTP_RETRY_COUNT + 1):
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            wait = HTTP_RETRY_BACKOFF_FACTOR**attempt
            logger.warning(
                f"data.gov.my request attempt {attempt}/{HTTP_RETRY_COUNT} failed: {exc}. Retrying in {wait}s..."
            )
            if attempt == HTTP_RETRY_COUNT:
                raise
            time.sleep(wait)

    raise RuntimeError("Unreachable: retry loop exited unexpectedly")
