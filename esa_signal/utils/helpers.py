import time
import logging
import logging.handlers
import requests

LOG_FILE = "errors.log"


def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.WARNING)
    root.addHandler(fh)

    # Only add console handler when stdout is available (not pythonw.exe)
    import sys as _sys
    if _sys.stderr is not None:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch.setLevel(logging.INFO)
        root.addHandler(ch)


logger = logging.getLogger(__name__)


def http_get(
    url: str,
    headers: dict = None,
    params: dict = None,
    timeout: int = 15,
    max_retries: int = 3,
    retry_delay: int = 5,
) -> dict | list | None:
    """GET request with exponential-backoff retry. Returns parsed JSON or None."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(
                url,
                headers=headers or {},
                params=params or {},
                timeout=timeout,
            )
            if resp.status_code in (400, 404):
                return None
            if resp.status_code == 429:
                wait = retry_delay * attempt
                logger.warning(f"Rate limited on {url} — sleeping {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.JSONDecodeError:
            logger.warning(f"Non-JSON response from {url}")
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning(f"Request failed {url} attempt {attempt}/{max_retries}: {exc}")
            if attempt < max_retries:
                time.sleep(retry_delay)
    logger.error(f"All {max_retries} attempts failed for {url}")
    return None


def format_usd(value: float) -> str:
    if value is None:
        return "N/A"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.4f}"


def format_pct(value: float) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def format_price(value: float) -> str:
    if value is None:
        return "N/A"
    if value >= 1:
        return f"${value:,.4f}"
    if value >= 0.0001:
        return f"${value:.6f}"
    return f"${value:.10f}"
