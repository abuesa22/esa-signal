"""
Claude AI analysis for market briefs — evening outlook generation.
"""

import logging
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an institutional grade crypto and market analyst. "
    "You think like a hedge fund — data first, no hype, risk aware. "
    "Your job is to score opportunities honestly and flag risks clearly. "
    "Be concise. Never oversell anything. Protect capital first."
)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=60.0,
        )
    return _client


def generate_market_outlook(market_data: dict) -> str:
    """
    Generate a 3-sentence market outlook based on the day's data.
    Returns a plain-text string.
    """
    sp500 = market_data.get("sp500", {})
    nasdaq = market_data.get("nasdaq", {})
    btc = market_data.get("btc", {})
    eth = market_data.get("eth", {})
    gold = market_data.get("gold", {})
    dxy = market_data.get("dxy", {})
    narratives = market_data.get("narratives", [])
    events = market_data.get("events", [])

    prompt = f"""Write exactly 3 sentences as a market outlook for tomorrow.
Be institutional, data-driven, and risk-aware. No fluff.

Today's market data:
S&P 500: {sp500.get('price', 'N/A')} ({sp500.get('change_pct', 'N/A')}%)
NASDAQ: {nasdaq.get('price', 'N/A')} ({nasdaq.get('change_pct', 'N/A')}%)
BTC: ${btc.get('price', 'N/A')} ({btc.get('change_pct', 'N/A')}%)
ETH: ${eth.get('price', 'N/A')} ({eth.get('change_pct', 'N/A')}%)
Gold: ${gold.get('price', 'N/A')}
DXY: {dxy.get('price', 'N/A')}
Hot crypto narratives: {', '.join(narratives) if narratives else 'None identified'}
Key events today: {', '.join(events) if events else 'None'}

Write 3 sentences covering: (1) overall market tone and direction,
(2) key risk or opportunity to watch, (3) crypto positioning advice."""

    try:
        rate_limiter.wait("anthropic")
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude API error generating market outlook: %s", exc)
        return "Market outlook unavailable — AI service error."


def summarise_crypto_narratives(trending_coins: list[dict]) -> list[str]:
    """
    Given a list of trending coin dicts from CoinGecko, identify top 3 narratives.
    Returns list of narrative strings.
    """
    if not trending_coins:
        return []

    coin_names = [c.get("name", "") for c in trending_coins[:15] if c.get("name")]
    if not coin_names:
        return []

    prompt = f"""From this list of trending crypto coins, identify the top 3 market narratives driving them.
Return only a JSON array of 3 short narrative labels (e.g. ["AI agents", "Solana memes", "RWA tokenization"]).
No explanation. Just the JSON array.

Trending coins: {', '.join(coin_names)}"""

    try:
        rate_limiter.wait("anthropic")
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as exc:
        logger.error("Claude narrative analysis error: %s", exc)
        return []
