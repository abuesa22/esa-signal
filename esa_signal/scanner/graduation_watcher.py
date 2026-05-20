"""
Pump.fun graduation watcher.
Polls the watchlist every 2 minutes. When a token that had $0 DEX liquidity
gains real liquidity (>= $5K), it has graduated from the bonding curve to
Raydium — send an immediate Telegram alert.
"""

import logging
from utils.helpers import http_get
from utils.rate_limiter import rate_limiter
from database.db import get_graduation_watchlist, mark_graduated, is_already_alerted
from bot.formatters import format_graduation_alert

logger = logging.getLogger(__name__)

DEXSCREENER_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
GRADUATION_LIQUIDITY_THRESHOLD = 5_000  # $5K signals real DEX liquidity


def check_graduations(send_text_callback) -> int:
    """
    Checks all watchlist tokens for graduation.
    Calls send_text_callback(text: str) for each newly graduated token.
    Returns number of graduations detected.
    """
    watchlist = get_graduation_watchlist()
    if not watchlist:
        return 0

    graduated_count = 0

    for entry in watchlist:
        addr = entry["token_address"]
        chain = entry["chain"]
        ticker = entry.get("ticker") or "???"
        name = entry.get("name") or ticker

        if is_already_alerted(addr):
            mark_graduated(addr)
            continue

        rate_limiter.wait("dexscreener")
        data = http_get(f"{DEXSCREENER_TOKENS}/{addr}", timeout=15)
        pairs = (data or {}).get("pairs") or []

        if not pairs:
            continue

        # Find best pair with real liquidity
        liquid_pairs = [
            p for p in pairs
            if (p.get("liquidity") or {}).get("usd", 0) >= GRADUATION_LIQUIDITY_THRESHOLD
        ]

        if not liquid_pairs:
            continue

        pair = max(liquid_pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
        liquidity_usd = (pair.get("liquidity") or {}).get("usd", 0)
        market_cap = pair.get("marketCap") or 0
        holders = (pair.get("info") or {}).get("holders") or 0
        ticker = pair.get("baseToken", {}).get("symbol", ticker).upper()
        name = pair.get("baseToken", {}).get("name", name)
        dex_url = pair.get("url") or f"https://dexscreener.com/{chain}/{addr}"

        logger.info("GRADUATION DETECTED: %s (%s) — liquidity $%,.0f", ticker, chain, liquidity_usd)

        mark_graduated(addr)

        alert = format_graduation_alert(
            token_address=addr,
            chain=chain,
            ticker=ticker,
            name=name,
            liquidity_usd=liquidity_usd,
            market_cap=market_cap,
            holders=holders,
            dexscreener_url=dex_url,
        )

        try:
            send_text_callback(alert)
            graduated_count += 1
        except Exception as exc:
            logger.error("Failed to send graduation alert for %s: %s", ticker, exc)

    return graduated_count
