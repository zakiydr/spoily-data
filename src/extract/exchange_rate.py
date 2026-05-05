"""
USD/MYR exchange rate extractor — Frankfurter API v2.

Endpoint: https://api.frankfurter.dev/v2/rates?from=YYYY-MM-DD&to=YYYY-MM-DD&base=USD&quotes=MYR
No API key required. Returns daily rates.
"""
import time
import logging
import requests
import pandas as pd
from src.config.settings import (
    EXCHANGE_RATE_URL,
    HTTP_RETRY_COUNT, HTTP_RETRY_BACKOFF_FACTOR, HTTP_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


def fetch_usd_myr_rates(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch daily USD/MYR exchange rates from Frankfurter API v2.

    Args:
        start_date: YYYY-MM-DD
        end_date:   YYYY-MM-DD

    Returns:
        DataFrame with columns [date, usd_myr]
    """
    params = {
        "from": start_date,
        "to": end_date,
        "base": "USD",
        "quotes": "MYR",
    }

    data = _request_with_retry(EXCHANGE_RATE_URL, params)

    if not data:
        logger.warning("Frankfurter: no data returned")
        return pd.DataFrame(columns=["date", "usd_myr"])

    df = pd.DataFrame(data)
    df = df.rename(columns={"rate": "usd_myr"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "usd_myr"]].sort_values("date").reset_index(drop=True)

    logger.info(f"Frankfurter: final DataFrame has {len(df)} rows, range {df['date'].min()} to {df['date'].max()}")
    return df


def _request_with_retry(url: str, params: dict) -> list:
    """HTTP GET with exponential backoff retry. Returns parsed JSON list."""
    for attempt in range(1, HTTP_RETRY_COUNT + 1):
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            wait = HTTP_RETRY_BACKOFF_FACTOR ** attempt
            logger.warning(f"Frankfurter request attempt {attempt}/{HTTP_RETRY_COUNT} failed: {exc}. Retrying in {wait}s...")
            if attempt == HTTP_RETRY_COUNT:
                raise
            time.sleep(wait)
