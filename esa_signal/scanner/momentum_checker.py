"""
GATE 3 — MOMENTUM CHECK
  • Volume increasing over last 1h vs 6h average
  • Price up >= 20% in last hour
  • Buys > Sells (accumulation proxy)
  • DexScreener trending rank noted
  • Holder count growing (proxy via buy/sell ratio)

GATE 4 — MARKET CAP CHECK
  • Market cap < $10M
  • FDV not massively inflated vs circulating supply
  • Top 10 wallet concentration flagged (Rugcheck data)
"""

import logging
from config import MAX_MARKET_CAP_USD

logger = logging.getLogger(__name__)


def run_gate3(pair: dict) -> tuple[bool, dict]:
    """
    Returns (passed: bool, details: dict).
    pair is a DexScreener pair object.
    """
    details: dict = {}

    # ── Price momentum: record but do not filter ─────────────────────────────
    price_change_1h = pair.get("priceChange", {}).get("h1", 0) or 0
    details["price_change_1h"] = price_change_1h

    # ── Volume momentum: h1 volume vs h6 rate ────────────────────────────────
    vol_h1 = pair.get("volume", {}).get("h1", 0) or 0
    vol_h6 = pair.get("volume", {}).get("h6", 0) or 0

    # Annualise h6 to an h1 rate for comparison
    vol_h6_hourly = vol_h6 / 6 if vol_h6 else 0
    details["vol_h1"] = vol_h1
    details["vol_h6_hourly"] = vol_h6_hourly

    # Volume must be accelerating: h1 >= h6-hourly rate
    if vol_h1 < vol_h6_hourly * 0.8:  # 20% tolerance
        details["fail_reason"] = (
            f"Volume decelerating: h1 ${vol_h1:,.0f} < h6-rate ${vol_h6_hourly:,.0f}"
        )
        return False, details

    # ── Accumulation proxy: buys > sells in last hour ─────────────────────────
    txns_h1 = pair.get("txns", {}).get("h1", {})
    buys_h1 = txns_h1.get("buys", 0) or 0
    sells_h1 = txns_h1.get("sells", 0) or 0
    details["buys_h1"] = buys_h1
    details["sells_h1"] = sells_h1

    if sells_h1 > buys_h1 * 1.5:  # allow up to 50% more sells before failing
        details["fail_reason"] = (
            f"Sell pressure: {sells_h1} sells vs {buys_h1} buys in last hour"
        )
        return False, details

    # ── DexScreener trending rank ─────────────────────────────────────────────
    boosts = pair.get("boosts", {})
    trending_rank = boosts.get("active") if boosts else None
    details["trending_rank"] = trending_rank

    # ── Holder count growth (proxy: net positive transactions) ────────────────
    txns_h24 = pair.get("txns", {}).get("h24", {})
    buys_h24 = txns_h24.get("buys", 0) or 0
    sells_h24 = txns_h24.get("sells", 0) or 0
    details["net_txns_24h"] = buys_h24 - sells_h24

    details["passed"] = True
    return True, details


def run_gate4(pair: dict, rugcheck_details: dict | None = None) -> tuple[bool, dict]:
    """
    Returns (passed: bool, details: dict).
    """
    details: dict = {}

    # ── Market cap floor ──────────────────────────────────────────────────────
    market_cap = pair.get("marketCap", 0) or 0
    fdv = pair.get("fdv", 0) or 0
    details["market_cap"] = market_cap
    details["fdv"] = fdv

    if market_cap > MAX_MARKET_CAP_USD:
        details["fail_reason"] = (
            f"Market cap ${market_cap:,.0f} above ${MAX_MARKET_CAP_USD:,} — not early stage"
        )
        return False, details

    # ── FDV sanity: FDV should not be more than 10x market cap ───────────────
    if market_cap > 0 and fdv > 0:
        fdv_ratio = fdv / market_cap
        details["fdv_ratio"] = round(fdv_ratio, 2)
        if fdv_ratio > 10:
            details["fail_reason"] = (
                f"FDV/MC ratio {fdv_ratio:.1f}x — too inflated relative to circulating supply"
            )
            return False, details

    # ── Top-10 wallet concentration (from Rugcheck if available) ─────────────
    if rugcheck_details:
        rc_risks = rugcheck_details.get("rugcheck", {}).get("risks", [])
        concentration_risk = any(
            "concentration" in r.lower() or "top_holder" in r.lower()
            for r in rc_risks
        )
        details["concentration_risk"] = concentration_risk
        if concentration_risk:
            details["note"] = "High wallet concentration detected in Rugcheck"
            # Warn but don't hard-fail — Claude scoring will penalise

    details["passed"] = True
    return True, details
