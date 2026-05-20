"""
Crypto Scanner — runs every 5 minutes.
Fetches new tokens from DexScreener (profiles + boosts), runs them through
all 4 gates, then sends qualifying tokens to the AI scorer.
"""

import logging
import time
from config import SUPPORTED_CHAINS, MIN_AI_SCORE
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
DEXSCREENER_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
DEXSCREENER_BOOSTS = "https://api.dexscreener.com/token-boosts/latest/v1"


def _fetch_latest_profiles() -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(DEXSCREENER_PROFILES, timeout=15)
    return data if isinstance(data, list) else []


def _fetch_boosted_tokens() -> list[dict]:
    """Boosted tokens are actively promoted — often newly launched."""
    rate_limiter.wait("dexscreener")
    data = http_get(DEXSCREENER_BOOSTS, timeout=15)
    return data if isinstance(data, list) else []


def _fetch_token_pairs(token_address: str) -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEXSCREENER_TOKENS}/{token_address}", timeout=15)
    if data and isinstance(data.get("pairs"), list):
        return data["pairs"]
    return []


def _best_pair(pairs: list[dict]) -> dict | None:
    valid = [p for p in pairs if p.get("liquidity", {}).get("usd", 0)]
    if not valid:
        return None
    return max(valid, key=lambda p: p.get("liquidity", {}).get("usd", 0))


def _launch_tag(age_hours: float) -> str:
    if age_hours < 1:
        return "JUST LAUNCHED"
    if age_hours < 6:
        return "NEW TODAY"
    return ""


def scan_new_tokens(send_signal_callback) -> tuple[int, int]:
    """
    Main scan loop. Calls send_signal_callback(sig) for each qualifying token.
    Returns (tokens_checked, signals_passed).
    """
    logger.info("Starting crypto scan cycle...")

    # Merge profiles + boosts for broader token coverage
    profiles = _fetch_latest_profiles()
    boosts = _fetch_boosted_tokens()

    seen: set[str] = set()
    candidates: list[dict] = []
    for item in profiles + boosts:
        addr = item.get("tokenAddress", "")
        chain = (item.get("chainId") or "").lower()
        if addr and chain and addr not in seen:
            seen.add(addr)
            candidates.append({"tokenAddress": addr, "chainId": chain})

    if not candidates:
        logger.warning("No token candidates from DexScreener")
        return 0, 0

    tokens_checked = 0
    signals_passed = 0

    for profile in candidates:
        chain = (profile.get("chainId") or "").lower()
        if chain not in SUPPORTED_CHAINS:
            continue

        token_address = profile.get("tokenAddress", "")
        if not token_address:
            continue

        if is_already_alerted(token_address):
            continue

        # Re-check every 30 min — reduces API load per cycle without missing launches
        if was_scanned_recently(token_address, within_minutes=30):
            continue

        tokens_checked += 1
        mark_scanned(token_address, chain)

        pairs = _fetch_token_pairs(token_address)

        # pump.fun graduation watchlist: high bonding-curve volume but no DEX liquidity yet
        if chain == "solana" and pairs:
            all_liq = sum((p.get("liquidity") or {}).get("usd", 0) for p in pairs)
            total_vol = sum((p.get("volume") or {}).get("h24", 0) for p in pairs)
            age_ms = pairs[0].get("pairCreatedAt")
            age_h = ((time.time() * 1000 - age_ms) / 3_600_000) if age_ms else 999
            if all_liq < 5_000 and total_vol >= 50_000 and age_h < 6 and token_address.endswith("pump"):
                sym = pairs[0].get("baseToken", {}).get("symbol", "???").upper()
                nam = pairs[0].get("baseToken", {}).get("name", sym)
                add_to_graduation_watchlist(token_address, chain, sym, nam, total_vol)
                logger.info("Added to graduation watchlist: %s (vol=$%,.0f)", sym, total_vol)

        pair = _best_pair(pairs)
        if not pair:
            logger.debug("No valid pair for %s on %s", token_address, chain)
            continue

        ticker = pair.get("baseToken", {}).get("symbol", "???").upper()
        name = pair.get("baseToken", {}).get("name", ticker)

        # ── GATE 1: Safety ────────────────────────────────────────────────────
        g1_pass, g1 = run_gate1(pair, chain)
        if not g1_pass:
            logger.debug("[%s/%s] Gate1 FAIL: %s", chain, ticker, g1.get("fail_reason"))
            continue

        # ── GATE 2: Legitimacy ────────────────────────────────────────────────
        g2_pass, g2 = run_gate2(pair, chain)
        if not g2_pass:
            logger.debug("[%s/%s] Gate2 FAIL: %s", chain, ticker, g2.get("fail_reason"))
            continue

        # ── GATE 3: Momentum ──────────────────────────────────────────────────
        g3_pass, g3 = run_gate3(pair)
        if not g3_pass:
            logger.debug("[%s/%s] Gate3 FAIL: %s", chain, ticker, g3.get("fail_reason"))
            continue

        # ── GATE 4: Market Cap ────────────────────────────────────────────────
        g4_pass, g4 = run_gate4(pair, rugcheck_details=g1)
        if not g4_pass:
            logger.debug("[%s/%s] Gate4 FAIL: %s", chain, ticker, g4.get("fail_reason"))
            continue

        logger.info("[%s/%s] All 4 gates passed — running AI score", chain, ticker)

        cg = g2.get("coingecko", {})
        cmc_data = g2.get("cmc", {})
        rc = g1.get("rugcheck", {})

        ai_result = score_token(
            name=name,
            ticker=ticker,
            chain=chain,
            price_usd=float(pair.get("priceUsd") or 0),
            market_cap=g4.get("market_cap", 0),
            volume_24h=g2.get("volume_24h", 0),
            liquidity_usd=g1.get("liquidity_usd", 0),
            age_hours=g1.get("age_hours", 0),
            price_change_1h=g3.get("price_change_1h", 0),
            price_change_24h=pair.get("priceChange", {}).get("h24", 0) or 0,
            holder_count=pair.get("info", {}).get("holders") or 0,
            coingecko_listed=cg.get("listed", False),
            cmc_listed=cmc_data.get("listed", False),
            rugcheck_score=rc.get("score", 0),
            rugcheck_risks=rc.get("risks", []),
            buys_h1=g3.get("buys_h1", 0),
            sells_h1=g3.get("sells_h1", 0),
        )

        if ai_result.get("score", 0) < MIN_AI_SCORE:
            logger.info(
                "[%s/%s] AI score %d below threshold %d — skipped",
                chain, ticker, ai_result.get("score", 0), MIN_AI_SCORE,
            )
            continue

        price_usd = float(pair.get("priceUsd") or 0)
        age_hours = g1.get("age_hours", 0)

        sig = TokenSignal(
            token_address=token_address,
            chain=chain,
            ticker=ticker,
            name=name,
            price_usd=price_usd,
            market_cap=g4.get("market_cap", 0),
            volume_24h=g2.get("volume_24h", 0),
            liquidity_usd=g1.get("liquidity_usd", 0),
            holder_count=pair.get("info", {}).get("holders") or 0,
            price_change_1h=g3.get("price_change_1h", 0),
            price_change_24h=pair.get("priceChange", {}).get("h24", 0) or 0,
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
            ai_score=ai_result.get("score", 0),
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
        "Scan cycle complete — checked %d tokens, %d passed all filters",
        tokens_checked, signals_passed,
    )
    return tokens_checked, signals_passed
