"""
Telegram message formatters — professional layout.
"""

from database.models import TokenSignal
from utils.helpers import format_usd, format_price, format_pct

SEP = "━━━━━━━━━━━━━━━━━━━━━━"
BOX_TOP = "┌─────────────────────"
BOX_MID = "├─────────────────────"
BOX_BOT = "└─────────────────────"


def _chk(val: bool) -> str:
    return "✅" if val else "❌"


def _trend(val) -> str:
    if val is None:
        return ""
    return "📈" if float(val) >= 0 else "📉"


def _conviction_label(c: str) -> str:
    return {"LOW": "🟡 LOW", "MEDIUM": "🟠 MEDIUM", "HIGH": "🔴 HIGH"}.get(c.upper(), c)


def _urgency_label(u: str) -> str:
    return {
        "LOW": "🟢 LOW",
        "MEDIUM": "🟡 MEDIUM",
        "HIGH": "🟠 HIGH",
        "APE NOW": "🚨 APE NOW",
    }.get(u.upper(), u)


def _age_str(age_hours: float) -> str:
    if age_hours < 1:
        return f"{max(1, int(age_hours * 60))}min"
    if age_hours < 24:
        return f"{age_hours:.1f}h"
    return f"{age_hours / 24:.1f}d"


def _mcap_tier(mc: float) -> str:
    if mc < 1_000_000:
        return "NANO"
    if mc < 5_000_000:
        return "MICRO"
    return "SMALL"


def _vol_liq_ratio(vol: float, liq: float) -> str:
    if not liq:
        return "N/A"
    ratio = vol / liq
    bar = "🟢" if ratio >= 3 else ("🟡" if ratio >= 1 else "🔴")
    return f"{bar} {ratio:.1f}x"


def _explorer_links(chain: str, address: str) -> list[str]:
    links = []
    if chain == "solana":
        links.append(f'<a href="https://solscan.io/token/{address}">Solscan</a>')
        if address.endswith("pump"):
            links.append(f'<a href="https://pump.fun/{address}">Pump.fun</a>')
    elif chain == "ethereum":
        links.append(f'<a href="https://etherscan.io/token/{address}">Etherscan</a>')
    elif chain == "base":
        links.append(f'<a href="https://basescan.org/token/{address}">Basescan</a>')
    return links


def format_signal(sig: TokenSignal) -> str:
    age_display = _age_str(sig.age_hours)
    if sig.launch_tag == "JUST LAUNCHED":
        age_line = f"⏰ {age_display} — ⚡ JUST LAUNCHED"
    elif sig.launch_tag == "NEW TODAY":
        age_line = f"⏰ {age_display} — 🆕 NEW TODAY"
    else:
        age_line = f"⏰ {age_display} old"

    tier = _mcap_tier(sig.market_cap)
    contract_safe = sig.gate1_passed and not sig.has_mint_authority
    mint_str = "❌ Present" if sig.has_mint_authority else "✅ None"
    freeze_str = "❌ Present" if sig.has_freeze_authority else "✅ None"
    lp_str = "✅ Locked" if sig.lp_locked else "⚠️ Unlocked"

    cg_str = "✅ YES" if sig.coingecko_listed else "❌ NO"
    cmc_str = "✅ YES" if sig.cmc_listed else "❌ NO"
    p1h_str = f"{format_pct(sig.price_change_1h)} {_trend(sig.price_change_1h)}"
    p24h_str = f"{format_pct(sig.price_change_24h)} {_trend(sig.price_change_24h)}"
    vol_liq = _vol_liq_ratio(sig.volume_24h, sig.liquidity_usd)

    entry = sig.entry_zone_low or sig.price_usd
    tp1 = format_price(entry * 2)
    tp2 = format_price(entry * 5)
    tp3 = format_price(entry * 10)
    sl_price = format_price(entry * 0.65)

    risks_lines = "\n".join(f"│ • {r}" for r in sig.risks[:3]) or "│ • None identified"

    # Build links
    links = []
    if sig.dexscreener_url:
        links.append(f'<a href="{sig.dexscreener_url}">DexScreener</a>')
    links.extend(_explorer_links(sig.chain, sig.token_address))
    if sig.coingecko_listed and sig.coingecko_url:
        links.append(f'<a href="{sig.coingecko_url}">CoinGecko</a>')
    if sig.cmc_listed and sig.cmc_url:
        links.append(f'<a href="{sig.cmc_url}">CMC</a>')
    links_text = " | ".join(links) if links else "—"

    # Catalyst line (new field from AI v2)
    catalyst = getattr(sig, "catalyst", "") or ""
    catalyst_line = f"│ 💡 {catalyst}\n" if catalyst else ""

    msg = f"""{SEP}
🚨 <b>ESA SIGNAL — {tier} CAP ALERT</b>
{SEP}

🪙 <b>${sig.ticker}</b> — {sig.name}
⛓ <b>{sig.chain.upper()}</b>  {age_line}
📊 Score: <b>{sig.ai_score}/100</b>  {_conviction_label(sig.conviction)}

{SEP}
🔐 <b>SAFETY</b>
{BOX_TOP}
│ Safe Contract:    {_chk(contract_safe)}
│ LP:               {lp_str}
│ Mint Authority:   {mint_str}
│ Freeze Authority: {freeze_str}
│ Rugcheck:         {sig.rugcheck_score:.0f}/100
{BOX_BOT}

📈 <b>MARKET DATA</b>
{BOX_TOP}
│ Price:       {format_price(sig.price_usd)}
│ Market Cap:  {format_usd(sig.market_cap)}  [{tier}]
│ Liquidity:   {format_usd(sig.liquidity_usd)}
│ Vol 24h:     {format_usd(sig.volume_24h)}
│ Vol/Liq:     {vol_liq}
│ Holders:     {sig.holder_count:,}
│ 1h Change:   {p1h_str}
│ 24h Change:  {p24h_str}
│ CoinGecko:   {cg_str}  CMC: {cmc_str}
{BOX_BOT}

🧠 <b>AI ANALYSIS</b>
{BOX_TOP}
│ {sig.narrative}
{catalyst_line}│ Conviction:  {_conviction_label(sig.conviction)}
{BOX_MID}
│ ⚠️ KEY RISKS
{risks_lines}
{BOX_BOT}

💰 <b>TRADE SETUP</b>
{BOX_TOP}
│ Entry:     {format_price(sig.entry_zone_low)} – {format_price(sig.entry_zone_high)}
│ Size:      {sig.position_size}
│ TP1 (2x):  {tp1}
│ TP2 (5x):  {tp2}
│ TP3 (10x): {tp3}
│ Stop:      -35% → {sl_price}
│ Urgency:   {_urgency_label(sig.urgency)}
{BOX_BOT}

🔗 {links_text}
{SEP}
<i>ESA Signal — Signals only. You execute.</i>"""

    if len(msg) > 4090:
        msg = msg[:4087] + "..."
    return msg


def format_stats(stats: dict) -> str:
    total = stats.get("total_signals", 0)
    evaluated = stats.get("evaluated", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    win_rate = stats.get("win_rate", 0.0)
    avg_score = stats.get("avg_ai_score", 0.0)
    outcomes = stats.get("outcomes", {})

    outcome_lines = "\n".join(
        f"│ {k}: {v}" for k, v in outcomes.items()
    ) or "│ No outcomes yet"

    return f"""{SEP}
📊 <b>ESA SIGNAL — STATS</b>
{SEP}
{BOX_TOP}
│ Total Signals:  {total}
│ Evaluated:      {evaluated}
│ Wins (≥2x):     {wins}
│ Losses:         {losses}
│ Win Rate:       {win_rate:.1f}%
│ Avg AI Score:   {avg_score:.1f}/100
{BOX_BOT}

<b>Outcome Breakdown:</b>
{outcome_lines}

<i>/outcome [id] [2x|5x|10x|LOSS|HOLD]</i>"""


def format_history(signals: list[dict]) -> str:
    if not signals:
        return f"{SEP}\n📋 <b>No signals sent yet.</b>\n{SEP}"

    lines = []
    for s in signals:
        outcome = s.get("outcome") or "PENDING"
        icon = {"2x": "✅", "5x": "💰", "10x": "🚀", "LOSS": "❌", "HOLD": "⏳"}.get(outcome, "⏳")
        lines.append(
            f"{icon} <b>#{s['id']}</b> ${s.get('ticker','?')} "
            f"[{s.get('chain','?').upper()}] score:{s.get('ai_score','?')} — {outcome}"
        )

    return f"{SEP}\n📋 <b>LAST 10 SIGNALS</b>\n{SEP}\n\n" + "\n".join(lines)


def format_top_signals(signals: list[dict]) -> str:
    if not signals:
        return f"{SEP}\n🏆 <b>No winning signals yet.</b>\n{SEP}"

    lines = []
    for s in signals:
        outcome = s.get("outcome", "?")
        icon = {"2x": "✅", "5x": "💰", "10x": "🚀"}.get(outcome, "📈")
        lines.append(
            f"{icon} <b>#{s['id']}</b> ${s.get('ticker','?')} "
            f"({s.get('chain','?').upper()}) — {outcome} — {s.get('ai_score','?')}/100"
        )

    return f"{SEP}\n🏆 <b>TOP PERFORMERS</b>\n{SEP}\n\n" + "\n".join(lines)


def format_graduation_alert(
    token_address: str,
    chain: str,
    ticker: str,
    name: str,
    liquidity_usd: float,
    market_cap: float,
    holders: int,
    dexscreener_url: str,
) -> str:
    return f"""{SEP}
🎓 <b>PUMP.FUN GRADUATION</b>
{SEP}

🪙 <b>${ticker}</b> — {name}
⛓ SOLANA — Just graduated from bonding curve

{BOX_TOP}
│ Liquidity:  {format_usd(liquidity_usd)}
│ Market Cap: {format_usd(market_cap)}
│ Holders:    {holders:,}
│ BC:         100% ✅
{BOX_BOT}

🔗 <a href="{dexscreener_url}">DexScreener</a> | <a href="https://solscan.io/token/{token_address}">Solscan</a>
{SEP}
<i>ESA Signal — Signals only. You execute.</i>"""


def format_watchlist(items: list[dict]) -> str:
    if not items:
        return f"{SEP}\n👀 <b>Graduation watchlist is empty.</b>\n{SEP}"

    lines = []
    for it in items[:15]:
        vol = it.get("volume_peak", 0)
        lines.append(
            f"• <b>${it.get('ticker','?')}</b> "
            f"vol=${vol:,.0f} "
            f"<a href=\"https://dexscreener.com/solana/{it['token_address']}\">chart</a>"
        )

    return (
        f"{SEP}\n👀 <b>PUMP.FUN WATCHLIST</b> ({len(items)} tokens)\n{SEP}\n\n"
        + "\n".join(lines)
    )
