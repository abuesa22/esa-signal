"""
Composes the three daily Telegram briefs:
  • Morning (7am AEST)  — pre-market snapshot + day's agenda
  • Midday (12pm AEST)  — what moved since open
  • Evening (9pm AEST)  — US close recap + Claude outlook
"""

import logging
from datetime import datetime
import pytz

from markets.stock_scanner import (
    get_us_futures,
    get_us_market_close,
    get_commodities,
    get_crypto_prices,
    get_economic_calendar,
    get_earnings_calendar,
    get_market_news,
    get_top_movers,
    get_global_crypto_data,
    get_trending_coins,
    get_big_movers_crypto,
    get_recent_ipo_filings,
    get_sector_performance,
)
from ai.analyser import generate_market_outlook, summarise_crypto_narratives
from utils.helpers import format_usd

logger = logging.getLogger(__name__)

AEST = pytz.timezone("Australia/Sydney")

SEP = "━━━━━━━━━━━━━━━━━━━━━━"
BOX_TOP = "┌─────────────────────"
BOX_BOT = "└─────────────────────"


def _now_aest() -> str:
    return datetime.now(AEST).strftime("%A %d %b %Y | %I:%M %p AEST")


def _safe_pct(val) -> str:
    if val is None:
        return "N/A"
    sign = "+" if float(val) >= 0 else ""
    return f"{sign}{float(val):.2f}%"


def _safe_price(val) -> str:
    if val is None:
        return "N/A"
    v = float(val)
    if v >= 1000:
        return f"${v:,.0f}"
    if v >= 1:
        return f"${v:,.2f}"
    return f"${v:.4f}"


def _trend(val) -> str:
    if val is None:
        return ""
    return "📈" if float(val) >= 0 else "📉"


def _macro_row(label: str, price_val, pct_val) -> str:
    p = _safe_price(price_val)
    c = _safe_pct(pct_val)
    t = _trend(pct_val)
    return f"│ {label:<10} {p:<12} {c:>8} {t}"


def _crypto_row(label: str, price_val, pct_val) -> str:
    p = _safe_price(price_val)
    c = _safe_pct(pct_val)
    t = _trend(pct_val)
    return f"│ {label:<7} {p:<12} {c:>8} {t}"


def build_morning_brief() -> str:
    logger.info("Building morning brief...")
    try:
        futures = get_us_futures()
        commodities = get_commodities()
        crypto = get_crypto_prices()
        events = get_economic_calendar()
        trending = get_trending_coins()
        narratives = summarise_crypto_narratives(trending)
        global_data = get_global_crypto_data()

        sp = futures.get("sp500", {})
        nq = futures.get("nasdaq", {})
        dow = futures.get("dow", {})
        wti = commodities.get("wti_crude", {})
        gold = commodities.get("gold", {})
        dxy = commodities.get("dxy", {})
        btc = crypto.get("btc", {})
        eth = crypto.get("eth", {})

        btc_dom = global_data.get("btc_dominance", "N/A")
        total_mcap = global_data.get("total_market_cap_usd")
        mcap_str = format_usd(total_mcap) if total_mcap else "N/A"

        # Overall mood
        signals = [sp.get("change_pct") or 0, nq.get("change_pct") or 0, btc.get("change_pct") or 0]
        avg = sum(signals) / len(signals)
        mood = "🟢 RISK ON" if avg >= 0.5 else ("🔴 RISK OFF" if avg <= -0.5 else "🟡 NEUTRAL")

        # Calendar events
        event_lines = "\n".join(
            f"│ • {e.get('event', 'Event')} ({e.get('country', '?')})" for e in events[:5]
        ) or "│ • No high-impact events today"

        # Narratives
        narrative_lines = "\n".join(
            f"│ {j+1}. {n}" for j, n in enumerate(narratives[:3])
        ) or "│ • Analysing..."

        # AI outlook
        outlook_raw = generate_market_outlook({
            "sp500": sp, "nasdaq": nq, "btc": btc, "eth": eth,
            "gold": gold, "dxy": dxy,
            "narratives": narratives,
            "events": [e.get("event", "") for e in events[:3]],
        })
        outlook_lines = "\n".join(f"│ {line}" for line in (outlook_raw or "").split("\n")[:6])

        msg = f"""{SEP}
🌅 <b>ESA SIGNAL — MORNING BRIEF</b>
📅 {_now_aest()}
{SEP}

<b>MARKET MOOD: {mood}</b>

💵 <b>MACRO</b>
{BOX_TOP}
{_macro_row("S&amp;P 500", sp.get("price"), sp.get("change_pct"))}
{_macro_row("NASDAQ", nq.get("price"), nq.get("change_pct"))}
{_macro_row("DOW", dow.get("price"), dow.get("change_pct"))}
{_macro_row("DXY", dxy.get("price"), dxy.get("change_pct"))}
{_macro_row("WTI OIL", wti.get("price"), wti.get("change_pct"))}
{_macro_row("GOLD", gold.get("price"), gold.get("change_pct"))}
{BOX_BOT}

🪙 <b>CRYPTO</b>
{BOX_TOP}
{_crypto_row("BTC", btc.get("price"), btc.get("change_pct"))}
{_crypto_row("ETH", eth.get("price"), eth.get("change_pct"))}
│ TOTAL MCAP  {mcap_str}
│ BTC DOM     {btc_dom}%
{BOX_BOT}

🔥 <b>HOT NARRATIVES</b>
{narrative_lines}

📅 <b>TODAY TO WATCH</b>
{event_lines}

🤖 <b>AI OUTLOOK</b>
{BOX_TOP}
{outlook_lines}
{BOX_BOT}

{SEP}
<i>ESA Signal — Signals only. You execute.</i>
{SEP}"""
        return msg

    except Exception as exc:
        logger.error("Morning brief error: %s", exc)
        return f"⚠️ <b>ESA Signal — Morning Brief Error</b>\n\n{exc}"


def build_midday_update() -> str:
    logger.info("Building midday update...")
    try:
        crypto = get_crypto_prices()
        movers = get_top_movers()
        global_data = get_global_crypto_data()
        news = get_market_news()
        big_movers = get_big_movers_crypto(hours=4)

        btc = crypto.get("btc", {})
        eth = crypto.get("eth", {})
        btc_dom = global_data.get("btc_dominance", "N/A")

        gainers = movers.get("gainers", [])[:3]
        losers = movers.get("losers", [])[:3]

        gainer_lines = "\n".join(
            f"│ 📈 {g.get('ticker','?'):<8} {g.get('change_percentage','')}"
            for g in gainers
        ) or "│ • Data unavailable"

        loser_lines = "\n".join(
            f"│ 📉 {loser.get('ticker','?'):<8} {loser.get('change_percentage','')}"
            for loser in losers
        ) or "│ • Data unavailable"

        news_lines = "\n".join(
            f"│ • {n.get('headline', '')[:75]}..."
            for n in news[:3]
        ) or "│ • No breaking news"

        spike_lines = "\n".join(
            f"│ 🚀 {c.get('name')} (${c.get('symbol')}) "
            f"+{c.get('price_change_percentage_1h_in_currency', 0):.0f}% (1h)"
            for c in big_movers
        ) or "│ • No major spikes in last 4h"

        msg = f"""{SEP}
☀️ <b>ESA SIGNAL — MIDDAY UPDATE</b>
📅 {_now_aest()}
{SEP}

🪙 <b>CRYPTO NOW</b>
{BOX_TOP}
{_crypto_row("BTC", btc.get("price"), btc.get("change_pct"))}
{_crypto_row("ETH", eth.get("price"), eth.get("change_pct"))}
│ BTC DOM     {btc_dom}%
{BOX_BOT}

📊 <b>MARKET MOVERS</b>
{BOX_TOP}
│ 📈 TOP GAINERS
{gainer_lines}
│
│ 📉 TOP LOSERS
{loser_lines}
{BOX_BOT}

🔥 <b>CRYPTO SPIKES (+100% / 4h)</b>
{spike_lines}

📰 <b>BREAKING NEWS</b>
{news_lines}

{SEP}
<i>ESA Signal — Signals only. You execute.</i>
{SEP}"""
        return msg

    except Exception as exc:
        logger.error("Midday brief error: %s", exc)
        return f"⚠️ <b>ESA Signal — Midday Update Error</b>\n\n{exc}"


def build_evening_brief() -> str:
    logger.info("Building evening brief...")
    try:
        close = get_us_market_close()
        sectors = get_sector_performance()
        earnings = get_earnings_calendar()
        ipos = get_recent_ipo_filings()
        global_data = get_global_crypto_data()
        trending = get_trending_coins()
        narratives = summarise_crypto_narratives(trending)
        crypto = get_crypto_prices()

        sp = close.get("sp500", {})
        nq = close.get("nasdaq", {})
        dow = close.get("dow", {})
        btc = crypto.get("btc", {})
        eth = crypto.get("eth", {})

        btc_dom = global_data.get("btc_dominance", "N/A")
        total_mcap = global_data.get("total_market_cap_usd")
        mcap_str = format_usd(total_mcap) if total_mcap else "N/A"
        mcap_chg = global_data.get("market_cap_change_pct_24h", 0)

        sector_lines = "\n".join(
            f"│ {'🟢' if (s.get('change_pct') or 0) >= 0 else '🔴'} "
            f"{s.get('sector', '?'):<18} {_safe_pct(s.get('change_pct'))}"
            for s in sectors
        ) or "│ • Sector data unavailable"

        def _fmt_earning(e: dict) -> str:
            sym = e.get("symbol", "?")
            eps = e.get("eps_str", "N/A")
            rev = e.get("rev_str", "")
            timing = e.get("timing", "")
            date_s = e.get("date", "?")
            q = e.get("quarter")
            yr = e.get("year")
            reported = e.get("reported", False)
            period = f"Q{q} {yr}" if q and yr else ""
            badge = "✅" if reported else "📅"
            detail = " | ".join(
                filter(None, [f"EPS: {eps}", f"Rev: {rev}" if rev and rev != "N/A" else "", timing, period]))
            return f"│ {badge} {sym} ({date_s}) — {detail}"

        earnings_lines = "\n".join(_fmt_earning(e) for e in earnings[:5]) or "│ • No major earnings today"

        ipo_lines = "\n".join(
            f"│ • {i.get('company','?')} — {i.get('form','S-1')} filed {i.get('filed','')}"
            for i in ipos[:3]
        ) or "│ • No new S-1 filings"

        narrative_lines = "\n".join(
            f"│ {j+1}. {n}" for j, n in enumerate(narratives[:3])
        ) or "│ • None identified"

        outlook_raw = generate_market_outlook({
            "sp500": sp, "nasdaq": nq, "btc": btc, "eth": eth,
            "gold": {}, "dxy": {},
            "narratives": narratives,
            "events": [e.get("symbol", "") for e in earnings[:3]],
        })
        outlook_lines = "\n".join(f"│ {line}" for line in (outlook_raw or "").split("\n")[:6])

        msg = f"""{SEP}
🌙 <b>ESA SIGNAL — EVENING BRIEF</b>
📅 {_now_aest()}
{SEP}

📉 <b>US MARKET CLOSE</b>
{BOX_TOP}
{_macro_row("S&amp;P 500", sp.get("price"), sp.get("change_pct"))}
{_macro_row("NASDAQ", nq.get("price"), nq.get("change_pct"))}
{_macro_row("DOW", dow.get("price"), dow.get("change_pct"))}
{BOX_BOT}

📊 <b>SECTOR PERFORMANCE</b>
{BOX_TOP}
{sector_lines}
{BOX_BOT}

📋 <b>EARNINGS</b>
{earnings_lines}

🏦 <b>NEW IPO FILINGS</b>
{ipo_lines}

🪙 <b>CRYPTO 24H</b>
{BOX_TOP}
{_crypto_row("BTC", btc.get("price"), btc.get("change_pct"))}
{_crypto_row("ETH", eth.get("price"), eth.get("change_pct"))}
│ TOTAL MCAP  {mcap_str}  {_safe_pct(mcap_chg)} {_trend(mcap_chg)}
│ BTC DOM     {btc_dom}%
{BOX_BOT}

🔥 <b>HOT NARRATIVES TOMORROW</b>
{narrative_lines}

🤖 <b>AI MARKET OUTLOOK</b>
{BOX_TOP}
{outlook_lines}
{BOX_BOT}

{SEP}
<i>ESA Signal — Signals only. You execute.</i>
{SEP}"""
        return msg

    except Exception as exc:
        logger.error("Evening brief error: %s", exc)
        return f"⚠️ <b>ESA Signal — Evening Brief Error</b>\n\n{exc}"
