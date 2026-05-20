import os
from pathlib import Path
from dotenv import load_dotenv

# Search for .env or .env.txt in current and parent directories
_loaded = False
for _candidate in [".env", ".env.txt", "../.env", "../.env.txt"]:
    _p = Path(_candidate)
    if _p.exists():
        load_dotenv(_p)
        _loaded = True
        break
if not _loaded:
    load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CMC_API_KEY: str = os.getenv("CMC_API_KEY", "").strip()
ALPHA_VANTAGE_API_KEY: str = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "").strip()
FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "").strip()
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "").strip()

# Claude model — update here if you switch versions
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# ── Scanner thresholds ────────────────────────────────────────────────────────
SCAN_INTERVAL_MINUTES = 5
MIN_LIQUIDITY_USD = 5_000
MAX_MARKET_CAP_USD = 10_000_000
MIN_VOLUME_24H_USD = 20_000
MIN_AI_SCORE = 60
MIN_TOKEN_AGE_HOURS = 0.017      # ~1 minute
MAX_TOKEN_AGE_HOURS = 72
MIN_PRICE_CHANGE_1H_PCT = 0.0    # no minimum price increase required
MAX_DEV_WALLET_PCT = 5.0
MAX_TOP10_WALLET_PCT = 30.0
MAX_RUGCHECK_DANGER_RISKS = 0    # zero danger-level risks allowed

SUPPORTED_CHAINS = ["solana", "ethereum"]

# ── Scheduling ────────────────────────────────────────────────────────────────
TIMEZONE = "Australia/Sydney"
MORNING_HOUR = 7
MIDDAY_HOUR = 12
EVENING_HOUR = 21

# ── Storage ───────────────────────────────────────────────────────────────────
DB_PATH = "esa_signal.db"
LOG_FILE = "errors.log"

# ── Retry / rate limiting ─────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# calls per period (seconds)
RATE_LIMITS = {
    "coingecko": {"calls": 25, "period": 60},
    "cmc": {"calls": 25, "period": 60},
    "alphavantage": {"calls": 5, "period": 60},
    "finnhub": {"calls": 55, "period": 60},
    "dexscreener": {"calls": 295, "period": 60},
    "rugcheck": {"calls": 90, "period": 60},
    "edgar": {"calls": 10, "period": 60},
    "anthropic": {"calls": 50, "period": 60},
}
