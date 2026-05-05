"""
Settings module — loads all env vars and defines constants.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── API Keys ────────────────────────────────────────────────────────────────
EIA_API_KEY = os.getenv("EIA_API_KEY", "")

# ── Supabase / Database ─────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── API Endpoints ───────────────────────────────────────────────────────────
EIA_BRENT_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
FUEL_PRICE_URL = "https://api.data.gov.my/data-catalogue"
EXCHANGE_RATE_URL = "https://api.frankfurter.dev/v2/rates"

# ── Pipeline Constants ──────────────────────────────────────────────────────
DATE_FORMAT = "%Y-%m-%d"
T2_LAG_WEEKS = 2  # BBM price is influenced by Brent price ~2 weeks prior

# Malaysia fuel pricing cycle: announced on Wednesday, effective Thursday
# So a "pricing week" runs Thursday to Wednesday
PRICING_WEEK_START_DAY = 3  # Thursday (0=Monday in Python weekday())

# ── Data Quality Thresholds ─────────────────────────────────────────────────
RON_PRICE_MIN = 1.00   # MYR
RON_PRICE_MAX = 10.00  # MYR — raised to accommodate non-subsidized prices
BRENT_PRICE_MIN = 20.0  # USD
BRENT_PRICE_MAX = 200.0  # USD
WEEK_OVER_WEEK_MAX_CHANGE_PCT = 30.0  # anomaly flag threshold

# ── Retry / HTTP ────────────────────────────────────────────────────────────
HTTP_RETRY_COUNT = 3
HTTP_RETRY_BACKOFF_FACTOR = 2  # exponential: 2s, 4s, 8s
HTTP_TIMEOUT_SECONDS = 30

# ── Alerting ────────────────────────────────────────────────────────────────
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
