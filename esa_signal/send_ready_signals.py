"""
One-shot script — immediately runs AI scoring on the 5 ready tokens
(PURPLECUP, OPOSSUM, APPLE, 1BILLION, SPCX) and sends signals to Telegram.
Run once then discard.
"""
import sys
import os
import asyncio
import time
import logging
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from utils.helpers import http_get  # noqa: E402
from utils.rate_limiter import rate_limiter  # noqa: E402
from scanner.safety_checker import run_gate1  # noqa: E402
from scanner.legitimacy_checker import run_gate2  # noqa: E402
from scanner.momentum_checker import run_gate3, run_gate4  # noqa: E402
from ai.scorer import score_token  # noqa: E402
from database.db import init_db, is_already_alerted, save_signal  # noqa: E402
from database.models import TokenSignal  # noqa: E402
from bot.formatters import format_signal  # noqa: E402
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MIN_AI_SCORE  # noqa: E402

init_db()

# Tokens confirmed passing all gates in last diagnostic run
# These are Solana tokens — look them up live to get fresh data
READY_TICKERS = ["PURPLECUP", "OPOSSUM", "APPLE", "1BILLION", "SPCX"]

DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search"
DEXSCREENER_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"


def _fetch_by_ticker(ticker: str) -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEXSCREENER_SEARCH}?q={ticker}", timeout=15)
    pairs = (data or {}).get("pairs") or []
    return [p for p in pairs if p.get("baseToken", {}).get("symbol", "").upper() == ticker.upper()
            and (p.get("chainId") or "").lower() == "solana"]


def _best_pair(pairs: list[dict]) -> dict | None:
    valid = [p for p in pairs if (p.get("liquidity") or {}).get("usd", 0) >= 5_000]
    if not valid:
        return None
    return max(valid, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))


def _launch_tag(age_hours: float) -> str:
    if age_hours < 1:
        return "JUST LAUNCHED"
    if age_hours < 6:
        return "NEW TODAY"
    return ""


async def main():
    from telegram import Bot
    from telegram.constants import ParseMode

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    for ticker in READY_TICKERS:
        print(f"\n{'='*60}")
        print(f"Processing {ticker}...")

        pairs = _fetch_by_ticker(ticker)
        pair = _best_pair(pairs)

        if not pair:
            print(f"  {ticker} — no pair found with sufficient liquidity, skipping")
            continue

        token_address = pair.get("baseToken", {}).get("address", "")
        chain = (pair.get("chainId") or "solana").lower()
        name = pair.get("baseToken", {}).get("name", ticker)

        if is_already_alerted(token_address):
            print(f"  {ticker} — already alerted, skipping")
            continue

        liq = (pair.get("liquidity") or {}).get("usd", 0)
        vol24 = (pair.get("volume") or {}).get("h24", 0) or 0
        mc = pair.get("marketCap") or 0
        print(f"  Found: {ticker} | liq=${liq:,.0f} | vol24=${vol24:,.0f} | mc=${mc:,.0f}")

        # Gate 1
        g1_pass, g1 = run_gate1(pair, chain)
        if not g1_pass:
            print(f"  Gate 1 FAIL: {g1.get('fail_reason')}")
            # Still attempt scoring with relaxed check — token passed diag earlier
            # Override with current data instead
        print(f"  Gate 1: {'PASS' if g1_pass else 'FAIL'}")

        # Gate 2
        g2_pass, g2 = run_gate2(pair, chain)
        print(f"  Gate 2: {'PASS' if g2_pass else 'FAIL — ' + g2.get('fail_reason','?')}")

        # Gate 3
        g3_pass, g3 = run_gate3(pair)
        print(f"  Gate 3: {'PASS' if g3_pass else 'FAIL — ' + g3.get('fail_reason','?')}")

        # Gate 4
        g4_pass, g4 = run_gate4(pair, rugcheck_details=g1)
        print(f"  Gate 4: {'PASS' if g4_pass else 'FAIL — ' + g4.get('fail_reason','?')}")

        # AI score regardless of gate failures (user confirmed these are ready)
        cg = g2.get("coingecko", {})
        cmc_data = g2.get("cmc", {})
        rc = g1.get("rugcheck", {})

        print("  Running AI scorer...")
        ai_result = score_token(
            name=name,
            ticker=ticker,
            chain=chain,
            price_usd=float(pair.get("priceUsd") or 0),
            market_cap=g4.get("market_cap", 0) or mc,
            volume_24h=g2.get("volume_24h", 0) or vol24,
            liquidity_usd=g1.get("liquidity_usd", 0) or liq,
            age_hours=g1.get("age_hours", 0) or 1,
            price_change_1h=g3.get("price_change_1h", 0),
            price_change_24h=(pair.get("priceChange") or {}).get("h24", 0) or 0,
            holder_count=(pair.get("info") or {}).get("holders") or 0,
            coingecko_listed=cg.get("listed", False),
            cmc_listed=cmc_data.get("listed", False),
            rugcheck_score=rc.get("score", 50),
            rugcheck_risks=rc.get("risks", []),
            buys_h1=g3.get("buys_h1", 0),
            sells_h1=g3.get("sells_h1", 0),
        )

        ai_score = ai_result.get("score", 0)
        print(f"  AI Score: {ai_score}/100 — {ai_result.get('conviction','?')} conviction")

        if ai_score < MIN_AI_SCORE:
            print(f"  Score {ai_score} below threshold {MIN_AI_SCORE} — skipping signal")
            continue

        price_usd = float(pair.get("priceUsd") or 0)
        age_hours = g1.get("age_hours") or 1

        sig = TokenSignal(
            token_address=token_address,
            chain=chain,
            ticker=ticker,
            name=name,
            price_usd=price_usd,
            market_cap=g4.get("market_cap", 0) or mc,
            volume_24h=g2.get("volume_24h", 0) or vol24,
            liquidity_usd=g1.get("liquidity_usd", 0) or liq,
            holder_count=(pair.get("info") or {}).get("holders") or 0,
            price_change_1h=g3.get("price_change_1h", 0),
            price_change_24h=(pair.get("priceChange") or {}).get("h24", 0) or 0,
            age_hours=age_hours,
            gate1_passed=g1_pass,
            gate2_passed=g2_pass,
            gate3_passed=g3_pass,
            gate4_passed=g4_pass,
            rugcheck_score=rc.get("score", 50),
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

        signal_id = save_signal(sig)
        sig.id = signal_id
        text = format_signal(sig)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        print(f"  ✅ Signal sent for {ticker} (id={signal_id}, score={ai_score})")
        time.sleep(2)

    print("\n" + "="*60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
