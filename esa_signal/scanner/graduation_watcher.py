"""
Pump.fun graduation watcher.
Polls the watchlist every 2 minutes. When a token gains real DEX liquidity
(>= $5K), it has graduated from the bonding curve to Raydium.
Uses concurrent requests and a per-run cap to stay within the 60s budget.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.helpers import http_get
from database.db import get_graduation_watchlist, mark_graduated, is_already_alerted
from bot.formatters import format_graduation_alert

logger = logging.getLogger(__name__)

DEXSCREENER_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
GRADUATION_LIQUIDITY_THRESHOLD = 5_000
BATCH_SIZE = 40       # tokens per run
MAX_WORKERS = 10      # concurrent HTTP requests
REQUEST_TIMEOUT = 8   # seconds per request
STALE_HOURS = 72      # auto-prune tokens older than this


def _check_one(entry: dict) -> dict | None:
    """
    Returns a graduation dict if the token has graduated, else None.
    Runs in a thread.
    """
    addr = entry["token_address"]
    chain = entry.get("chain", "solana")
    ticker = entry.get("ticker") or "???"
    name = entry.get("name") or ticker

    data = http_get(f"{DEXSCREENER_TOKENS}/{addr}", timeout=REQUEST_TIMEOUT)
    pairs = (data or {}).get("pairs") or []

    liquid = [
        p for p in pairs
        if (p.get("liquidity") or {}).get("usd", 0) >= GRADUATION_LIQUIDITY_THRESHOLD
    ]
    if not liquid:
        return None

    pair = max(liquid, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
    return {
        "token_address": addr,
        "chain": chain,
        "ticker": pair.get("baseToken", {}).get("symbol", ticker).upper(),
        "name": pair.get("baseToken", {}).get("name", name),
        "liquidity_usd": (pair.get("liquidity") or {}).get("usd", 0),
        "market_cap": pair.get("marketCap") or 0,
        "holders": (pair.get("info") or {}).get("holders") or 0,
        "dex_url": pair.get("url") or f"https://dexscreener.com/{chain}/{addr}",
    }


def check_graduations(send_text_callback) -> int:
    watchlist = get_graduation_watchlist()
    if not watchlist:
        return 0

    # Fast-path: mark already-alerted tokens as graduated without HTTP call
    to_check = []
    for entry in watchlist:
        if is_already_alerted(entry["token_address"]):
            mark_graduated(entry["token_address"])
        else:
            to_check.append(entry)

    # Cap per run so we finish within ~40s (BATCH_SIZE / MAX_WORKERS * timeout)
    batch = to_check[:BATCH_SIZE]
    if not batch:
        return 0

    logger.debug("Checking %d/%d watchlist tokens for graduation", len(batch), len(to_check))

    graduated_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_check_one, entry): entry for entry in batch}
        for future in as_completed(futures):
            entry = futures[future]
            addr = entry["token_address"]
            try:
                result = future.result()
            except Exception as exc:
                logger.debug("Graduation check failed for %s: %s", addr, exc)
                continue

            if result is None:
                continue

            logger.info(
                "GRADUATION: %s (%s) — liquidity $%,.0f",
                result["ticker"], result["chain"], result["liquidity_usd"],
            )
            mark_graduated(addr)

            alert = format_graduation_alert(
                token_address=addr,
                chain=result["chain"],
                ticker=result["ticker"],
                name=result["name"],
                liquidity_usd=result["liquidity_usd"],
                market_cap=result["market_cap"],
                holders=result["holders"],
                dexscreener_url=result["dex_url"],
            )
            try:
                send_text_callback(alert)
                graduated_count += 1
            except Exception as exc:
                logger.error("Failed to send graduation alert for %s: %s", result["ticker"], exc)

    return graduated_count
