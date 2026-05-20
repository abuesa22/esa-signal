"""
Telegram message formatters — premium style.
All messages use ━ dividers and ┌│└ box sections.
"""

from database.models import TokenSignal
from utils.helpers import format_usd, format_price, format_pct

SEP = "━━━━━━━━━━━━━━━━━━━━━━"
BOX_TOP = "┌─────────────────────"
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
        return f"{max(1, int(age_hours * 60))} min old"
    return f"{age_hours:.1f}h old"


def format_signal(sig: TokenSignal) -> str:
    # Age + launch badge
    age_display = _age_str(sig.age_hours)
    if sig.launch_tag == "JUST LAUNCHED":
        age_line = f"⏰ Age: {age_display} — ⚡ JUST LAUNCHED"
    elif sig.launch_tag == "NEW TODAY":
        age_line = f"⏰ Age: {age_display} — 🆕 NEW TODAY"
    else:
        age_line = f"⏰ Age: {age_display}"

    # Safety
    contract_safe = sig.gate1_passed and not sig.has_mint_authority
    mint_str = "❌ Present" if sig.has_mint_authority else "✅ None"
    freeze_str = "❌ Present" if sig.has_freeze_authority else "✅ None"
    lp_str = "✅ Locked" if sig.lp_locked else "⚠️ Unknown"

    # Market
    cg_str = "✅ YES" if sig.coingecko_listed else "❌ NO"
    cmc_str = "✅ YES" if sig.cmc_listed else "❌ NO"
    p1h_str = f"{format_pct(sig.price_change_1h)} {_trend(sig.price_change_1h)}"
    p24h_str = f"{format_pct(sig.price_change_24h)} {_trend(sig.price_change_24h)}"

    # Trade levels
    entry = sig.entry_zone_low or sig.price_usd
    tp1 = format_price(entry * 2)
    tp2 = format_price(entry * 5)
    tp3 = format_price(entry * 10)
    sl_price = format_price(entry * 0.65)

    # AI risks
    risks_lines = "\n".join(f"│ • {r}" for r in sig.risks[:3]) or "│ • None identified"

    # Links
    links = []
    if sig.dexscreener_url:
        links.append(f'<a href="{sig.dexscreener_url}">DexScreener</a>')
    if sig.coingecko_listed and sig.coingecko_url:
        links.append(f'<a href="{sig.coingecko_url}">CoinGecko</a>')
    if sig.cmc_listed and sig.cmc_url:
        links.append(f'<a href="{sig.cmc_url}">CMC</a>')
    if sig.chain == "solana":
        links.append(f'<a href="https://birdeye.so/token/{sig.token_address}">Birdeye</a>')
    links_text = " | ".join(links) if links else "—"

    msg = f"""{SEP}
🚨 <b>ESA SIGNAL — NEW COIN ALERT</b>
{SEP}

🪙 <b>${sig.ticker}</b> — {sig.name}
⛓ Chain: <b>{sig.chain.upper()}</b>
{age_line}
📊 Score: <b>{sig.ai_score}/100</b> — {_conviction_label(sig.conviction)} CONVICTION

{SEP}
🔐 <b>SAFETY</b>
{BOX_TOP}
│ Contract Safe:    {_chk(contract_safe)}
│ Liquidity Locked: {lp_str}
│ Mint Authority:   {mint_str}
│ Freeze Authority: {freeze_str}
│ Rugcheck Score:   {sig.rugcheck_score:.0f}/100
{BOX_BOT}

📈 <b>MARKET DATA</b>
{BOX_TOP}
│ Price:       {format_price(sig.price_usd)}
│ Market Cap:  {format_usd(sig.market_cap)}
│ Liquidity:   {format_usd(sig.liquidity_usd)}
│ Volume 24h:  {format_usd(sig.volume_24h)}
│ Holders:     {sig.holder_count:,}
│ 1h Change:   {p1h_str}
│ 24h Change:  {p24h_str}
│ CG Listed:   {cg_str}
│ CMC Listed:  {cmc_str}
{BOX_BOT}

🧠 <b>AI ANALYSIS</b>
{BOX_TOP}
│ {sig.narrative}
│
│ Conviction: {_conviction_label(sig.conviction)}
│
│ ⚠️ RISKS
{risks_lines}
{BOX_BOT}

💰 <b>TRADE SETUP</b>
{BOX_TOP}
│ Entry Zone:    {format_price(sig.entry_zone_low)} – {format_price(sig.entry_zone_high)}
│ Position Size: {sig.position_size}
│ Take Profit 1: 2x  — {tp1}
│ Take Profit 2: 5x  — {tp2}
│ Take Profit 3: 10x — {tp3}
│ Stop Loss:     -35% — {sl_price}
│ Urgency:       {_urgency_label(sig.urgency)}
{BOX_BOT}

🔗 <b>LINKS</b>
{links_text}

{SEP}
<i>ESA Signal — Signals only. You execute.</i>
{SEP}"""

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
        f"│ {k}: {v} signals" for k, v in outcomes.items()
    ) or "│ No outcomes recorded yet"

    return f"""{SEP}
📊 <b>ESA SIGNAL — STATS</b>
{SEP}
{BOX_TOP}
│ Total Signals:  {total}
│ Evaluated:      {evaluated}
│ Wins (2x+):     {wins}
│ Losses:         {losses}
│ Win Rate:       {win_rate:.1f}%
│ Avg AI Score:   {avg_score:.1f}/100
{BOX_BOT}

<b>Outcome Breakdown:</b>
{outcome_lines}

<i>Update outcomes with /outcome [signal_id] [2x|5x|10x|LOSS|HOLD]</i>"""


def format_history(signals: list[dict]) -> str:
    if not signals:
        return f"{SEP}\n📋 <b>No signals sent yet.</b>\n{SEP}"

    lines = []
    for s in signals:
        outcome = s.get("outcome") or "PENDING"
        icon = {"2x": "✅", "5x": "💰", "10x": "🚀", "LOSS": "❌", "HOLD": "⏳"}.get(outcome, "⏳")
        lines.append(
            f"{icon} <b>#{s['id']}</b> ${s.get('ticker','?')} "
            f"[{s.get('chain','?').upper()}] — Score: {s.get('ai_score','?')}/100 — {outcome}"
        )

    return f"{SEP}\n📋 <b>ESA SIGNAL — LAST 10 SIGNALS</b>\n{SEP}\n\n" + "\n".join(lines)


def format_graduation_alert(token_address: str, chain: str, ticker: str, name: str,
                            liquidity_usd: float, market_cap: float, holders: int,
                            dexscreener_url: str) -> str:
    from utils.helpers import format_usd
    return f"""{SEP}
🎓 <b>PUMP.FUN GRADUATION ALERT</b>
{SEP}

🪙 <b>${ticker}</b> — {name}
⛓ Chain: <b>SOLANA</b>
📊 Just graduated from pump.fun bonding curve

📈 <b>MARKET DATA</b>
{BOX_TOP}
│ Liquidity:      {format_usd(liquidity_usd)}
│ Market Cap:     {format_usd(market_cap)}
│ Holders:        {holders:,}
│ Bonding Curve:  100% ✅
{BOX_BOT}

🔗 <a href="{dexscreener_url}">DexScreener</a>

{SEP}
<i>ESA Signal — Signals only. You execute.</i>
{SEP}"""


def format_top_signals(signals: list[dict]) -> str:
    if not signals:
        return f"{SEP}\n🏆 <b>No winning signals recorded yet.</b>\n{SEP}"

    lines = []
    for s in signals:
        outcome = s.get("outcome", "?")
        icon = {"2x": "✅", "5x": "💰", "10x": "🚀"}.get(outcome, "📈")
        lines.append(
            f"{icon} <b>#{s['id']}</b> ${s.get('ticker','?')} "
            f"({s.get('chain','?').upper()}) — {outcome} — Score: {s.get('ai_score','?')}/100"
        )

    return f"{SEP}\n🏆 <b>ESA SIGNAL — TOP PERFORMERS</b>\n{SEP}\n\n" + "\n".join(lines)
