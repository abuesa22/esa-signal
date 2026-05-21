"""
Crypto Scanner — runs every 5 minutes.
Sources: DexScreener profiles, boosts, and trending search.
Batch-fetches pair data concurrently, runs 4 gates, then AI scores survivors.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SUPPORTED_CHAINS, MIN_AI_SCORE, RESCAN_INTERVAL_MINUTES, MAX_TOKENS_PER_SCAN
from database.db import is_already_alerted, mark_scanned, was_scanned_recently, add_to_graduation_watchlist
from database.models import TokenSignal
from scanner.safety_checker import run_gate1
from scanner.legitimacy_checker import run_gate2
from scanner.momentum_checker import run_gate3, run_gate4
from ai.scorer import score_token
from utils.helpers import http_get
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

DEXSCREENER_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_BOOSTS = "https://api.dexscreener.com/token-boosts/latest/v1"
DEXSCREENER_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search"

# Trending search terms — catches narrative-driven tokens the profile feed misses
_TREND_QUERIES = ["solana new", "trending", "pump"]


def _fetch_latest_profiles() -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(DEXSCREENER_PROFILES, timeout=15)
    return data if isinstance(data, list) else []


def _fetch_boosted_tokens() -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(DEXSCREENER_BOOSTS, timeout=15)
    return data if isinstance(data, list) else []


def _fetch_trending_tokens() -> list[dict]:
    """Pull top results from a few trending DexScreener searches."""
    results = []
    for q in _TREND_QUERIES:
        try:
            rate_limiter.wait("dexscreener")
            data = http_get(DEXSCREENER_SEARCH, params={"q": q}, timeout=10)
            for p in (data or {}).get("pairs") or []:
                addr = (p.get("baseToken") or {}).get("address", "")
                chain = (p.get("chainId") or "").lower()
                if addr and chain:
                    results.append({"tokenAddress": addr, "chainId": chain})
        except Exception as exc:
            logger.debug("Trending search '%s' failed: %s", q, exc)
    return results


def _fetch_token_pairs(token_address: str) -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEXSCREENER_TOKENS}/{token_address}", timeout=8)
    if data and isinstance(data.get("pairs"), list):
        return data["pairs"]
    return []


def _fetch_pairs_batch(addresses: list[str]) -> dict[str, list[dict]]:
    """Fetch pair data for multiple addresses concurrently."""
    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_token_pairs, addr): addr for addr in addresses}
        for fut in as_completed(futures, timeout=45):
            addr = futures[fut]
            try:
                results[addr] = fut.result()
            except Exception as exc:
                logger.debug("Pair fetch failed for %s: %s", addr, exc)
                results[addr] = []
    return results


def _best_pair(pairs: list[dict]) -> dict | None:
    valid = [p for p in pairs if (p.get("liquidity") or {}).get("usd", 0)]
    if not valid:
        return None
    return max(valid, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))


def _launch_tag(age_hours: float) -> str:
    if age_hours < 1:
        return "JUST LAUNCHED"
    if age_hours < 6:
        return "NEW TODAY"
    return ""


def _mcap_tier(market_cap: float) -> str:
    if market_cap < 1_000_000:
        return "NANO"
    if market_cap < 5_000_000:
        return "MICRO"
    return "SMALL"


def scan_new_tokens(send_signal_callback) -> tuple[int, int]:
    """
    Main scan loop. Calls send_signal_callback(sig) for each qualifying token.
    Returns (tokens_checked, signals_passed).
    """
    logger.info("Starting crypto scan cycle...")

    profiles = _fetch_latest_profiles()
    boosts = _fetch_boosted_tokens()
    trending = _fetch_trending_tokens()

    seen: set[str] = set()
    candidates: list[dict] = []
    for item in profiles + boosts + trending:
        addr = item.get("tokenAddress", "")
        chain = (item.get("chainId") or "").lower()
        if addr and chain and addr not in seen:
            seen.add(addr)
            candidates.append({"tokenAddress": addr, "chainId": chain})

    if not candidates:
        logger.warning("No token candidates from DexScreener")
        return 0, 0

    # Pre-filter: supported chain, not already alerted, not scanned recently
    to_fetch = []
    for profile in candidates:
        chain = (profile.get("chainId") or "").lower()
        addr = profile.get("tokenAddress", "")
        if not addr or chain not in SUPPORTED_CHAINS:
            continue
        if is_already_alerted(addr):
            continue
        if was_scanned_recently(addr, within_minutes=RESCAN_INTERVAL_MINUTES):
            continue
        to_fetch.append(profile)
        if len(to_fetch) >= MAX_TOKENS_PER_SCAN:
            break

    if not to_fetch:
        logger.info("All candidates already scanned — nothing new this cycle")
        return 0, 0

    # Batch-fetch pair data concurrently
    addresses = [p["tokenAddress"] for p in to_fetch]
    chain_map = {p["tokenAddress"]: p["chainId"] for p in to_fetch}
    pair_data = _fetch_pairs_batch(addresses)

    tokens_checked = 0
    signals_passed = 0

    for token_address, pairs in pair_data.items():
        chain = chain_map.get(token_address, "").lower()
        mark_scanned(token_address, chain)
        tokens_checked += 1

        # Pump.fun graduation watchlist check
        if chain == "solana" and pairs:
            all_liq = sum((p.get("liquidity") or {}).get("usd", 0) for p in pairs)
            total_vol = sum((p.get("volume") or {}).get("h24", 0) for p in pairs)
            age_ms = pairs[0].get("pairCreatedAt")
            age_h = ((time.time() * 1000 - age_ms) / 3_600_000) if age_ms else 999
            if all_liq < 5_000 and total_vol >= 50_000 and age_h < 6 and token_address.endswith("pump"):
                sym = pairs[0].get("baseToken", {}).get("symbol", "???").upper()
                nam = pairs[0].get("baseToken", {}).get("name", sym)
                add_to_graduation_watchlist(token_address, chain, sym, nam, total_vol)
                logger.info("Graduation watchlist: %s (vol=$%,.0f)", sym, total_vol)

        pair = _best_pair(pairs)
        if not pair:
            continue

        ticker = pair.get("baseToken", {}).get("symbol", "???").upper()
        name = pair.get("baseToken", {}).get("name", ticker)

        # ── GATE 1: Safety (age, liquidity, rugcheck) ─────────────────────────
        g1_pass, g1 = run_gate1(pair, chain)
        if not g1_pass:
            logger.debug("[%s/%s] G1 FAIL: %s", chain, ticker, g1.get("fail_reason"))
            continue

        # ── GATE 2: Legitimacy (volume, CG/CMC — runs concurrently) ──────────
        g2_pass, g2 = run_gate2(pair, chain)
        if not g2_pass:
            logger.debug("[%s/%s] G2 FAIL: %s", chain, ticker, g2.get("fail_reason"))
            continue

        # ── GATE 3: Momentum (volume trend, buy/sell ratio) ───────────────────
        g3_pass, g3 = run_gate3(pair)
        if not g3_pass:
            logger.debug("[%s/%s] G3 FAIL: %s", chain, ticker, g3.get("fail_reason"))
            continue

        # ── GATE 4: Market Cap ────────────────────────────────────────────────
        g4_pass, g4 = run_gate4(pair, rugcheck_details=g1)
        if not g4_pass:
            logger.debug("[%s/%s] G4 FAIL: %s", chain, ticker, g4.get("fail_reason"))
            continue

        logger.info("[%s/%s] All gates passed — AI scoring", chain, ticker)

        cg = g2.get("coingecko", {})
        cmc_data = g2.get("cmc", {})
        rc = g1.get("rugcheck", {})
        market_cap = g4.get("market_cap", 0)

        ai_result = score_token(
            name=name,
            ticker=ticker,
            chain=chain,
            price_usd=float(pair.get("priceUsd") or 0),
            market_cap=market_cap,
            volume_24h=g2.get("volume_24h", 0),
            liquidity_usd=g1.get("liquidity_usd", 0),
            age_hours=g1.get("age_hours", 0),
            price_change_1h=g3.get("price_change_1h", 0),
            price_change_24h=(pair.get("priceChange") or {}).get("h24", 0) or 0,
            holder_count=(pair.get("info") or {}).get("holders") or 0,
            coingecko_listed=cg.get("listed", False),
            cmc_listed=cmc_data.get("listed", False),
            rugcheck_score=rc.get("score", 0),
            rugcheck_risks=rc.get("risks", []),
            buys_h1=g3.get("buys_h1", 0),
            sells_h1=g3.get("sells_h1", 0),
            mcap_tier=_mcap_tier(market_cap),
            vol_h1=g3.get("vol_h1", 0),
            vol_h6_hourly=g3.get("vol_h6_hourly", 0),
        )

        ai_score = ai_result.get("score", 0)
        if ai_score < MIN_AI_SCORE:
            logger.info("[%s/%s] AI score %d below threshold %d", chain, ticker, ai_score, MIN_AI_SCORE)
            continue

        price_usd = float(pair.get("priceUsd") or 0)
        age_hours = g1.get("age_hours", 0)

        sig = TokenSignal(
            token_address=token_address,
            chain=chain,
            ticker=ticker,
            name=name,
            price_usd=price_usd,
            market_cap=market_cap,
            volume_24h=g2.get("volume_24h", 0),
            liquidity_usd=g1.get("liquidity_usd", 0),
            holder_count=(pair.get("info") or {}).get("holders") or 0,
            price_change_1h=g3.get("price_change_1h", 0),
            price_change_24h=(pair.get("priceChange") or {}).get("h24", 0) or 0,
            age_hours=age_hours,
            gate1_passed=g1_pass,
            gate2_passed=g2_pass,
            gate3_passed=g3_pass,
            gate4_passed=g4_pass,
            rugcheck_score=rc.get("score", 0),
            rugcheck_risks=rc.get("risks", []),
            has_mint_authority=rc.get("has_mint", False),
            has_freeze_authority=rc.get("has_freeze", False),
            lp_locked=g1.get("lp_locked") is True,
            launch_tag=_launch_tag(age_hours),
            coingecko_listed=cg.get("listed", False),
            cmc_listed=cmc_data.get("listed", False),
            ai_score=ai_score,
            narrative=ai_result.get("narrative", ""),
            conviction=ai_result.get("conviction", "LOW"),
            risks=ai_result.get("risks", []),
            entry_zone_low=price_usd * 0.95,
            entry_zone_high=price_usd * 1.05,
            position_size=ai_result.get("position_size", "SMALL"),
            urgency=ai_result.get("urgency", "LOW"),
            trending_rank=g3.get("trending_rank"),
            dexscreener_url=pair.get("url") or f"https://dexscreener.com/{chain}/{token_address}",
            coingecko_url=cg.get("url", ""),
            cmc_url=cmc_data.get("url", ""),
        )

        try:
            send_signal_callback(sig)
            signals_passed += 1
        except Exception as exc:
            logger.error("Failed to queue signal for %s: %s", ticker, exc)

        time.sleep(1)

    logger.info(
        "Scan complete — checked %d tokens, %d passed all filters",
        tokens_checked, signals_passed,
    )
    return tokens_checked, signals_passed
