"""
Brent Crude Oil price extractor — EIA API v2.
"""
import time
import logging
import requests
import pandas as pd
from src.config.settings import (
    EIA_API_KEY, EIA_BRENT_URL,
    HTTP_RETRY_COUNT, HTTP_RETRY_BACKOFF_FACTOR, HTTP_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


def fetch_brent_prices(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch daily Brent crude spot prices from EIA API v2.

    Args:
        start_date: YYYY-MM-DD
        end_date:   YYYY-MM-DD

    Returns:
        DataFrame with columns [date, brent_usd]
    """
    params = {
        "api_key": EIA_API_KEY,
        "frequency": "daily",
        "data[0]": "value",
        "facets[product][]": "EPCBRENT",
        "start": start_date,
        "end": end_date,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }

    all_rows = []
    offset = 0

    while True:
        params["offset"] = offset
        data = _request_with_retry(EIA_BRENT_URL, params)

        rows = data.get("response", {}).get("data", [])
        if not rows:
            break

        all_rows.extend(rows)
        total = int(data.get("response", {}).get("total", 0))
        offset += len(rows)

        logger.info(f"EIA: fetched {len(all_rows)}/{total} rows")

        if offset >= total:
            break

    if not all_rows:
        logger.warning("EIA: no data returned")
        return pd.DataFrame(columns=["date", "brent_usd"])

    df = pd.DataFrame(all_rows)
    df = df.rename(columns={"period": "date", "value": "brent_usd"})
    df["date"] = pd.to_datetime(df["date"])
    df["brent_usd"] = pd.to_numeric(df["brent_usd"], errors="coerce")
    df = df[["date", "brent_usd"]].dropna().sort_values("date").reset_index(drop=True)

    logger.info(f"EIA: final DataFrame has {len(df)} rows, range {df['date'].min()} to {df['date'].max()}")
    return df


def _request_with_retry(url: str, params: dict) -> dict:
    """HTTP GET with exponential backoff retry."""
    for attempt in range(1, HTTP_RETRY_COUNT + 1):
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            wait = HTTP_RETRY_BACKOFF_FACTOR ** attempt
            logger.warning(f"EIA request attempt {attempt}/{HTTP_RETRY_COUNT} failed: {exc}. Retrying in {wait}s...")
            if attempt == HTTP_RETRY_COUNT:
                raise
            time.sleep(wait)
