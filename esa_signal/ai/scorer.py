"""
Claude AI scoring for tokens that pass all 4 gates.
Uses prompt caching on the system prompt to reduce latency and cost.
Returns a structured dict: score, narrative, conviction, risks, position_size, urgency, catalyst.
"""

import json
import logging
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

_client: Anthropic | None = None

SYSTEM_PROMPT = """\
You are an institutional-grade crypto analyst at a quantitative hedge fund.
Your mandate: identify early-stage token opportunities with asymmetric upside.
You think in risk/reward ratios, not hype. Capital preservation is priority one.
Be direct and data-driven. No filler. No speculation without data support.
When scoring, be calibrated — a 90+ score should be genuinely exceptional.
Most tokens should score 40-65. Only send HIGH conviction on clear setups."""


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60.0)
    return _client


def score_token(
    name: str,
    ticker: str,
    chain: str,
    price_usd: float,
    market_cap: float,
    volume_24h: float,
    liquidity_usd: float,
    age_hours: float,
    price_change_1h: float,
    price_change_24h: float,
    holder_count: int,
    coingecko_listed: bool,
    cmc_listed: bool,
    rugcheck_score: float,
    rugcheck_risks: list,
    buys_h1: int,
    sells_h1: int,
    mcap_tier: str = "NANO",
    vol_h1: float = 0,
    vol_h6_hourly: float = 0,
) -> dict:
    vol_liq_ratio = round(volume_24h / liquidity_usd, 1) if liquidity_usd > 0 else 0
    buy_sell_ratio = round(buys_h1 / sells_h1, 2) if sells_h1 > 0 else buys_h1
    vol_acceleration = round(vol_h1 / vol_h6_hourly, 2) if vol_h6_hourly > 0 else 0

    prompt = f"""Score this {mcap_tier}-cap token. Return ONLY valid JSON — no markdown, no text outside the JSON.

TOKEN: {name} (${ticker}) on {chain.upper()}
━━━ FUNDAMENTALS ━━━
Age:          {age_hours:.1f}h
Price:        ${price_usd:.8f}
Market Cap:   ${market_cap:,.0f}  [{mcap_tier} CAP]
Liquidity:    ${liquidity_usd:,.0f}
Vol/Liq:      {vol_liq_ratio}x  (>3x = strong organic activity)
24h Volume:   ${volume_24h:,.0f}
1h Volume:    ${vol_h1:,.0f}
Vol Accel:    {vol_acceleration}x h1 vs h6-avg  (>1.5x = accelerating)
1h Change:    {price_change_1h:+.2f}%
24h Change:   {price_change_24h:+.2f}%
Holders:      {holder_count:,}
Buys/Sells:   {buys_h1}/{sells_h1} last hour  (ratio: {buy_sell_ratio})
━━━ SAFETY ━━━
Rugcheck:     {rugcheck_score:.0f}/100  (higher = safer)
Risks:        {", ".join(rugcheck_risks) if rugcheck_risks else "None"}
CoinGecko:    {"LISTED" if coingecko_listed else "NOT LISTED"}
CMC:          {"LISTED" if cmc_listed else "NOT LISTED"}

Scoring criteria (weight accordingly):
1. MOMENTUM (35%): vol acceleration, buy pressure, price trend, 1h vs 24h comparison
2. RISK/SAFETY (25%): rugcheck score, liquidity depth, age vs volume, lp status
3. NARRATIVE (25%): hot category (AI, meme, RWA, DePIN, political, etc.), timing
4. LIQUIDITY HEALTH (15%): vol/liq ratio, liq depth vs mcap, sustainable or wash traded

Return exactly this JSON structure:
{{
  "score": <integer 0-100>,
  "narrative": "<2 sentences: what this token is + why it has momentum now>",
  "catalyst": "<1 sentence: the specific trigger driving this move>",
  "conviction": "<LOW|MEDIUM|HIGH>",
  "risks": ["<top risk>", "<second risk>", "<third risk>"],
  "position_size": "<SMALL|MEDIUM|LARGE>",
  "urgency": "<LOW|MEDIUM|HIGH|APE NOW>"
}}

Score guide:
90-100  Exceptional — strong narrative, clean safety, accelerating momentum, act now
75-89   Strong setup — worth alerting, good risk/reward, HIGH or MEDIUM conviction
60-74   Acceptable — alert with LOW conviction, size small
55-59   Borderline — only alert if narrative is very strong
0-54    Reject

Position sizing:
SMALL  (1-2% portfolio): Score 55-74
MEDIUM (3-5% portfolio): Score 75-89
LARGE  (5-10% portfolio): Score 90+, HIGH conviction only

Urgency:
APE NOW   Price action extremely hot, window <30 min
HIGH      Act within 2-3 hours
MEDIUM    Good setup, 12-24h window
LOW       Early entry, patient"""

    try:
        rate_limiter.wait("anthropic")
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        result["score"] = max(0, min(100, int(result.get("score", 0))))
        result["conviction"] = result.get("conviction", "LOW").upper()
        result["position_size"] = result.get("position_size", "SMALL").upper()
        result["urgency"] = result.get("urgency", "LOW").upper()
        result.setdefault("catalyst", "")
        if not isinstance(result.get("risks"), list):
            result["risks"] = ["Unknown risk"]
        return result

    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON for %s: %s", ticker, exc)
    except Exception as exc:
        logger.error("Claude API error scoring %s: %s", ticker, exc)

    return {
        "score": 0,
        "narrative": "AI scoring unavailable.",
        "catalyst": "",
        "conviction": "LOW",
        "risks": ["AI scoring failed — manual review required"],
        "position_size": "SMALL",
        "urgency": "LOW",
    }
