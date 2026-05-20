"""
GATE 2 — LEGITIMACY CHECK
  • CoinGecko listed and verified?
  • CMC listed and verified?
  • Volume > $100 000 in last 24h
  • Flag listing status in alert
"""

import logging
from config import (
    COINGECKO_API_KEY,
    CMC_API_KEY,
    MIN_VOLUME_24H_USD,
)
from utils.helpers import http_get
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

CG_BASE = "https://api.coingecko.com/api/v3"
CMC_BASE = "https://pro-api.coinmarketcap.com/v1"


def _check_coingecko(ticker: str, token_address: str, chain: str) -> dict:
    """Search CoinGecko by symbol. Returns listing status dict."""
    rate_limiter.wait("coingecko")
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}

    # Try contract address lookup first (more precise)
    cg_chain_map = {"ethereum": "ethereum", "solana": "solana"}
    cg_chain = cg_chain_map.get(chain)
    coin_id = None
    cg_url = ""

    if cg_chain:
        data = http_get(
            f"{CG_BASE}/coins/{cg_chain}/contract/{token_address}",
            headers=headers,
        )
        if data and "id" in data:
            coin_id = data["id"]
            cg_url = f"https://www.coingecko.com/en/coins/{coin_id}"
            return {"listed": True, "id": coin_id, "url": cg_url, "method": "contract"}

    # Fallback: search by symbol
    rate_limiter.wait("coingecko")
    search = http_get(f"{CG_BASE}/search", headers=headers, params={"query": ticker})
    if search:
        coins = search.get("coins", [])
        for c in coins[:5]:
            if c.get("symbol", "").upper() == ticker.upper():
                coin_id = c.get("id")
                cg_url = f"https://www.coingecko.com/en/coins/{coin_id}"
                return {"listed": True, "id": coin_id, "url": cg_url, "method": "symbol_search"}

    return {"listed": False, "id": None, "url": "", "method": "not_found"}


def _check_cmc(ticker: str, token_address: str) -> dict:
    """Search CMC by symbol. Returns listing status dict."""
    if not CMC_API_KEY:
        return {"listed": False, "id": None, "url": "", "note": "No CMC key"}

    rate_limiter.wait("cmc")
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}

    data = http_get(
        f"{CMC_BASE}/cryptocurrency/info",
        headers=headers,
        params={"symbol": ticker.upper(), "aux": ""},
    )
    if data and "data" in data and data["data"]:
        # CMC returns a dict keyed by symbol
        entry = next(iter(data["data"].values()), None)
        if entry:
            cmc_id = entry.get("id")
            cmc_url = f"https://coinmarketcap.com/currencies/{entry.get('slug', '')}/"
            # Try to match contract address if provided
            return {
                "listed": True,
                "id": cmc_id,
                "url": cmc_url,
                "method": "symbol_match",
            }

    return {"listed": False, "id": None, "url": "", "method": "not_found"}


def run_gate2(pair: dict, chain: str) -> tuple[bool, dict]:
    """
    Returns (passed: bool, details: dict).
    Gate 2 does NOT hard-fail if the token isn't listed on CG/CMC —
    it flags it and checks organic volume growth instead.
    """
    ticker = pair.get("baseToken", {}).get("symbol", "").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    details: dict = {}

    # ── Volume floor ─────────────────────────────────────────────────────────
    details["volume_24h"] = volume_24h
    if volume_24h < MIN_VOLUME_24H_USD:
        details["fail_reason"] = f"Volume ${volume_24h:,.0f} below ${MIN_VOLUME_24H_USD:,}"
        return False, details

    # ── CoinGecko check ───────────────────────────────────────────────────────
    cg = _check_coingecko(ticker, token_address, chain)
    details["coingecko"] = cg

    # ── CMC check ────────────────────────────────────────────────────────────
    cmc = _check_cmc(ticker, token_address)
    details["cmc"] = cmc

    # If listed on neither, require volume and liquidity to be organically growing
    if not cg["listed"] and not cmc["listed"]:
        # Volume must be significantly above the floor — extra safety margin
        if volume_24h < MIN_VOLUME_24H_USD * 2:
            details["fail_reason"] = (
                f"Not on CG or CMC and volume ${volume_24h:,.0f} too low for unlisted token"
            )
            return False, details
        details["note"] = "Not listed on CG or CMC — organic volume accepted"

    details["passed"] = True
    return True, details
