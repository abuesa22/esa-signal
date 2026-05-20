"""
Claude AI scoring for tokens that pass all 4 gates.
Returns a structured dict with score, narrative, conviction, risks, etc.
"""

import json
import logging
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# Always create fresh client — avoids stale httpx/proxies state from old versions
_client: Anthropic | None = None

SYSTEM_PROMPT = (
    "You are an institutional grade crypto and market analyst. "
    "You think like a hedge fund — data first, no hype, risk aware. "
    "Your job is to score opportunities honestly and flag risks clearly. "
    "Be concise. Never oversell anything. Protect capital first."
)


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=60.0,
        )
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
) -> dict:
    """
    Ask Claude to score this token 0-100 and provide analysis.
    Returns dict with keys: score, narrative, conviction, risks, position_size, urgency.
    Falls back to safe defaults on any error.
    """
    prompt = f"""Score this crypto token opportunity.
Return ONLY valid JSON, no markdown, no explanation outside the JSON.

Token: {name} (${ticker})
Chain: {chain.upper()}
Age: {age_hours:.1f} hours old
Price: ${price_usd:.8f}
Market Cap: ${market_cap:,.0f}
24h Volume: ${volume_24h:,.0f}
Liquidity: ${liquidity_usd:,.0f}
1h Price Change: {price_change_1h:+.2f}%
24h Price Change: {price_change_24h:+.2f}%
Holder Count: {holder_count}
1h Buys: {buys_h1} | 1h Sells: {sells_h1}
CoinGecko Listed: {"YES" if coingecko_listed else "NO"}
CMC Listed: {"YES" if cmc_listed else "NO"}
Rugcheck Safety Score: {rugcheck_score:.0f}/100
Rugcheck Risks Detected: {", ".join(rugcheck_risks) if rugcheck_risks else "None"}

Scoring criteria:
- Narrative strength (is this a hot category: AI, RWA, meme, DePIN, etc.)
- Community momentum (buy pressure, holder growth proxy)
- On-chain health (liquidity depth, age, no red flags)
- Risk factors (rugcheck issues, low liquidity, high concentration)
- Comparable setups — what have similar early-stage tokens returned

Return this exact JSON structure:
{{
  "score": <integer 0-100>,
  "narrative": "<2 sentences max — what this token is and why it has momentum>",
  "conviction": "<LOW|MEDIUM|HIGH>",
  "risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "position_size": "<SMALL|MEDIUM|LARGE>",
  "urgency": "<LOW|MEDIUM|HIGH|APE NOW>"
}}

Scoring guide:
- 90-100: Exceptional setup, strong fundamentals, clear narrative, high urgency
- 70-89: Good setup, passes all checks, worth monitoring
- 60-69: Acceptable setup — alert with LOW conviction
- Below 60: Reject

Position size guide:
- SMALL (1-2%): Score 60-74, lower conviction
- MEDIUM (3-5%): Score 75-89, medium conviction
- LARGE (5-10%): Score 90+, high conviction only

Urgency guide:
- APE NOW: Price action extremely hot, window closing fast
- HIGH: Strong momentum, act within hours
- MEDIUM: Good setup, act within 24h
- LOW: Early, patient entry"""

    try:
        rate_limiter.wait("anthropic")
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if Claude adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        # Validate and clamp score
        result["score"] = max(0, min(100, int(result.get("score", 0))))
        result["conviction"] = result.get("conviction", "LOW").upper()
        result["position_size"] = result.get("position_size", "SMALL").upper()
        result["urgency"] = result.get("urgency", "LOW").upper()
        if not isinstance(result.get("risks"), list):
            result["risks"] = ["Unknown risk"]
        return result

    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON for %s: %s", ticker, exc)
    except Exception as exc:
        logger.error("Claude API error scoring %s: %s", ticker, exc)

    # Safe fallback
    return {
        "score": 0,
        "narrative": "AI scoring unavailable.",
        "conviction": "LOW",
        "risks": ["AI scoring failed — manual review required"],
        "position_size": "SMALL",
        "urgency": "LOW",
    }
