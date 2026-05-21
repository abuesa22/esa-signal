"""
GATE 2 — LEGITIMACY CHECK
  • Volume > MIN_VOLUME_24H_USD
  • CoinGecko / CMC listing checked concurrently (halves gate-2 latency)
  • Unlisted tokens require 2x volume floor
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from config import COINGECKO_API_KEY, CMC_API_KEY, MIN_VOLUME_24H_USD
from utils.helpers import http_get
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

CG_BASE = "https://api.coingecko.com/api/v3"
CMC_BASE = "https://pro-api.coinmarketcap.com/v1"

# CoinGecko chain IDs for contract-address lookups
_CG_CHAIN = {"ethereum": "ethereum", "solana": "solana", "base": "base"}


def _check_coingecko(ticker: str, token_address: str, chain: str) -> dict:
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
    cg_chain = _CG_CHAIN.get(chain)

    if cg_chain:
        rate_limiter.wait("coingecko")
        data = http_get(
            f"{CG_BASE}/coins/{cg_chain}/contract/{token_address}",
            headers=headers,
            timeout=8,
        )
        if data and "id" in data:
            coin_id = data["id"]
            return {
                "listed": True,
                "id": coin_id,
                "url": f"https://www.coingecko.com/en/coins/{coin_id}",
                "method": "contract",
            }

    rate_limiter.wait("coingecko")
    search = http_get(
        f"{CG_BASE}/search", headers=headers, params={"query": ticker}, timeout=8
    )
    if search:
        for c in search.get("coins", [])[:5]:
            if c.get("symbol", "").upper() == ticker.upper():
                coin_id = c.get("id")
                return {
                    "listed": True,
                    "id": coin_id,
                    "url": f"https://www.coingecko.com/en/coins/{coin_id}",
                    "method": "symbol_search",
                }

    return {"listed": False, "id": None, "url": "", "method": "not_found"}


def _check_cmc(ticker: str, token_address: str) -> dict:
    if not CMC_API_KEY:
        return {"listed": False, "id": None, "url": "", "note": "No CMC key"}

    rate_limiter.wait("cmc")
    data = http_get(
        f"{CMC_BASE}/cryptocurrency/info",
        headers={"X-CMC_PRO_API_KEY": CMC_API_KEY},
        params={"symbol": ticker.upper(), "aux": ""},
        timeout=8,
    )
    if data and "data" in data and data["data"]:
        entry = next(iter(data["data"].values()), None)
        if entry:
            return {
                "listed": True,
                "id": entry.get("id"),
                "url": f"https://coinmarketcap.com/currencies/{entry.get('slug', '')}/",
                "method": "symbol_match",
            }

    return {"listed": False, "id": None, "url": "", "method": "not_found"}


def run_gate2(pair: dict, chain: str) -> tuple[bool, dict]:
    ticker = pair.get("baseToken", {}).get("symbol", "").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    details: dict = {"volume_24h": volume_24h}

    if volume_24h < MIN_VOLUME_24H_USD:
        details["fail_reason"] = f"Volume ${volume_24h:,.0f} below ${MIN_VOLUME_24H_USD:,}"
        return False, details

    # Fire CoinGecko and CMC lookups in parallel — saves ~2-4s per token
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_cg = pool.submit(_check_coingecko, ticker, token_address, chain)
        fut_cmc = pool.submit(_check_cmc, ticker, token_address)
        try:
            cg = fut_cg.result(timeout=25)
        except Exception as exc:
            logger.warning("CoinGecko lookup failed for %s: %s", ticker, exc)
            cg = {"listed": False, "id": None, "url": "", "method": "error"}
        try:
            cmc = fut_cmc.result(timeout=25)
        except Exception as exc:
            logger.warning("CMC lookup failed for %s: %s", ticker, exc)
            cmc = {"listed": False, "id": None, "url": "", "method": "error"}

    details["coingecko"] = cg
    details["cmc"] = cmc

    if not cg["listed"] and not cmc["listed"]:
        if volume_24h < MIN_VOLUME_24H_USD * 2:
            details["fail_reason"] = (
                f"Not on CG or CMC and volume ${volume_24h:,.0f} too low for unlisted token"
            )
            return False, details
        details["note"] = "Unlisted — organic volume accepted"

    details["passed"] = True
    return True, details
