"""
Research chat mode — answers free-text Telegram messages intelligently.
Classifies the question, fetches relevant live data, then asks Claude to answer.

Returns a ResearchResult dict:
  text       — formatted Telegram HTML message
  image_url  — coin logo URL to send_photo before text (or None)
  caption    — caption for the photo (coin name/symbol)
"""

import logging
import re
import time
import requests
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, COINGECKO_API_KEY
from utils.rate_limiter import rate_limiter
from utils.helpers import http_get

logger = logging.getLogger(__name__)

SEP = "━━━━━━━━━━━━━━━━━━━━━━"
BOX_TOP = "┌─────────────────────"
BOX_BOT = "└─────────────────────"

RESEARCH_SYSTEM = (
    "You are ESA Signal — a personal hedge fund grade research analyst. "
    "The user has asked you a question. You have been given real live market data to work with. "
    "Answer concisely and intelligently like an institutional analyst would. "
    "Give real data, real insights, flag risks clearly. "
    "Format your answer cleanly for Telegram — use emojis, short paragraphs, bullet points. "
    "Never make up data — only use what you have been given. "
    "If you don't have enough data say so and explain what you do know. "
    "Keep the answer scannable in under 60 seconds."
)

_client: Anthropic | None = None

CG_BASE = "https://api.coingecko.com/api/v3"
DEX_BASE = "https://api.dexscreener.com"

_SOLANA_ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_ETH_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ── AI helper ─────────────────────────────────────────────────────────────────

def _ai(prompt: str, max_tokens: int = 600) -> str:
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60.0)
    rate_limiter.wait("anthropic")
    try:
        resp = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=RESEARCH_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        logger.error("Research AI error: %s", exc)
        return "AI analysis unavailable right now."


def _cg_headers() -> dict:
    return {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}


# ── Image + social extractors ─────────────────────────────────────────────────

def _extract_dex_media(pairs: list[dict]) -> tuple[str | None, dict]:
    """Pull image URL and socials from DexScreener pair info."""
    image_url = None
    socials = {}
    for p in pairs:
        info = p.get("info") or {}
        if not image_url:
            image_url = info.get("imageUrl")
        if not socials.get("website"):
            websites = info.get("websites") or []
            if websites:
                socials["website"] = websites[0].get("url", "")
        for s in (info.get("socials") or []):
            stype = (s.get("type") or "").lower()
            surl = s.get("url", "")
            if stype == "twitter" and not socials.get("twitter"):
                socials["twitter"] = surl
            elif stype == "telegram" and not socials.get("telegram"):
                socials["telegram"] = surl
        if image_url and len(socials) >= 2:
            break
    return image_url, socials


def _extract_cg_media(cg_data: dict) -> tuple[str | None, dict]:
    """Pull image URL and socials from CoinGecko coin detail."""
    image_url = (cg_data.get("image") or {}).get("large")
    links = cg_data.get("links") or {}
    homepage = (links.get("homepage") or [""])[0]
    twitter_handle = links.get("twitter_screen_name", "")
    tg_channel = links.get("telegram_channel_identifier", "")
    subreddit = links.get("subreddit_url", "")
    socials = {
        "website":  homepage or "",
        "twitter":  f"https://x.com/{twitter_handle}" if twitter_handle else "",
        "telegram": f"https://t.me/{tg_channel}" if tg_channel else "",
        "reddit":   subreddit or "",
    }
    return image_url, socials


def _build_socials_block(socials: dict, dex_url: str = "", cg_id: str = "") -> str:
    """Format the social links section for Telegram HTML."""
    def _link(label: str, url: str) -> str:
        if url and url.startswith("http"):
            return f"│ {label} <a href=\"{url}\">{url.split('//')[-1][:40]}</a>"
        return f"│ {label} N/A"

    cg_url = f"https://www.coingecko.com/en/coins/{cg_id}" if cg_id else ""
    lines = [
        "🌐 <b>SOCIALS</b>",
        BOX_TOP,
        _link("🌍 Website: ", socials.get("website", "")),
        _link("🐦 Twitter: ", socials.get("twitter", "")),
        _link("💬 Telegram:", socials.get("telegram", "")),
        _link("📱 Reddit:  ", socials.get("reddit", "")),
        _link("🔍 DEX:     ", dex_url),
        _link("🦎 CoinGecko:", cg_url),
        BOX_BOT,
    ]
    return "\n".join(lines)


# ── Data fetchers ──────────────────────────────────────────────────────────────

def _fetch_cg_coin(query: str) -> dict:
    rate_limiter.wait("coingecko")
    search = http_get(f"{CG_BASE}/search", headers=_cg_headers(), params={"query": query})
    if not search:
        return {}
    coins = search.get("coins", [])
    if not coins:
        return {}
    coin_id = coins[0]["id"]
    rate_limiter.wait("coingecko")
    data = http_get(
        f"{CG_BASE}/coins/{coin_id}",
        headers=_cg_headers(),
        params={"localization": "false", "tickers": "false",
                "community_data": "false", "developer_data": "false"},
    )
    return data or {}


def _fetch_cg_trending() -> list[dict]:
    rate_limiter.wait("coingecko")
    data = http_get(f"{CG_BASE}/search/trending", headers=_cg_headers())
    if data and "coins" in data:
        return [
            {
                "name":      c["item"].get("name"),
                "symbol":    c["item"].get("symbol"),
                "rank":      c["item"].get("market_cap_rank"),
                "change_24h": c["item"].get("data", {}).get("price_change_percentage_24h", {}).get("usd"),
                "image":     c["item"].get("small"),
            }
            for c in data["coins"][:10]
        ]
    return []


def _fetch_cg_global() -> dict:
    rate_limiter.wait("coingecko")
    data = http_get(f"{CG_BASE}/global", headers=_cg_headers())
    if data and "data" in data:
        d = data["data"]
        return {
            "total_mcap_usd":  d.get("total_market_cap", {}).get("usd"),
            "total_volume_usd": d.get("total_volume", {}).get("usd"),
            "btc_dominance":   round(d.get("market_cap_percentage", {}).get("btc", 0), 1),
            "eth_dominance":   round(d.get("market_cap_percentage", {}).get("eth", 0), 1),
            "mcap_change_24h": round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
            "active_coins":    d.get("active_cryptocurrencies"),
        }
    return {}


def _fetch_btc_eth() -> dict:
    rate_limiter.wait("coingecko")
    data = http_get(
        f"{CG_BASE}/simple/price",
        headers=_cg_headers(),
        params={
            "ids": "bitcoin,ethereum,solana",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
        },
    )
    return data or {}


def _fetch_dex_search(keyword: str) -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEX_BASE}/latest/dex/search", params={"q": keyword})
    pairs = (data or {}).get("pairs") or []
    valid = [p for p in pairs if p.get("pairCreatedAt")]
    valid.sort(key=lambda p: p.get("pairCreatedAt", 0), reverse=True)
    return valid[:8]


def _fetch_dex_token(address: str) -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEX_BASE}/latest/dex/tokens/{address}")
    return (data or {}).get("pairs") or []


def _fetch_dex_trending() -> list[dict]:
    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEX_BASE}/token-profiles/latest/v1")
    return data[:15] if isinstance(data, list) else []


def _fetch_rugcheck(address: str) -> dict:
    try:
        r = requests.get(
            f"https://api.rugcheck.xyz/v1/tokens/{address}/report/summary",
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _fetch_finnhub_news() -> list[dict]:
    from markets.stock_scanner import get_market_news
    return get_market_news()


def _fetch_macro() -> dict:
    from markets.stock_scanner import get_us_market_close, get_commodities
    return {"equities": get_us_market_close(), "commodities": get_commodities()}


# ── Question classifier ────────────────────────────────────────────────────────

def _classify(text: str) -> str:
    t = text.lower().strip()
    for tok in text.split():
        if _ETH_ADDR.match(tok) or _SOLANA_ADDR.match(tok):
            return "contract"
    if any(w in t for w in ["rugcheck", "contract", "address", "safe?", "rug?"]):
        return "contract"
    if any(w in t for w in ["find", "search", "look for", "coins about", "tokens about", "related to", "launched"]):
        return "coin_search"
    if any(w in t for w in ["trending", "hot", "what's pumping", "what is pumping", "top gainers", "movers"]):
        return "trending"
    if any(w in t for w in ["news", "happening", "latest", "what's going on"]):
        return "news"
    if any(w in t for w in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "price", "up or down", "going"]):
        return "crypto_price"
    if any(w in t for w in ["market", "s&p", "nasdaq", "dow", "oil", "gold", "stocks", "macro", "dxy", "fed"]):
        return "macro"
    if any(w in t for w in ["sector", "defi", "nft", "layer", "ai", "rwa", "meme", "narrative"]):
        return "narrative"
    return "general"


def _extract_address(text: str) -> str | None:
    for tok in text.split():
        if _ETH_ADDR.match(tok) or _SOLANA_ADDR.match(tok):
            return tok
    return None


def _extract_search_term(text: str) -> str:
    for prefix in ["find coins about", "find tokens about", "search for", "look for coins about",
                   "find me", "search", "coins related to", "tokens related to", "find"]:
        if text.lower().startswith(prefix):
            return text[len(prefix):].strip()
    return text.strip()


# ── Research handlers — all return (answer_text, image_url, caption, socials_block) ──

def _handle_contract(text: str):
    address = _extract_address(text) or text.strip()
    chain_hint = "solana" if _SOLANA_ADDR.match(address) else "ethereum/base"

    # DexScreener
    pairs = _fetch_dex_token(address)
    dex_image, dex_socials = _extract_dex_media(pairs)
    dex_url = ""
    market_lines = [f"Address: <code>{address}</code>", f"Chain: {chain_hint}"]

    name_str = address[:8] + "..."
    if pairs:
        best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
        b = best.get("baseToken", {})
        liq = (best.get("liquidity") or {}).get("usd", 0)
        vol = (best.get("volume") or {}).get("h24", 0)
        mc = best.get("marketCap") or best.get("fdv") or 0
        pc = best.get("priceChange") or {}
        created = best.get("pairCreatedAt")
        age_h = ((time.time() * 1000 - created) / 3_600_000) if created else None
        age_str = f"{age_h:.1f}h old" if age_h else "unknown age"
        dex_url = best.get("url", "")
        name_str = f"{b.get('name', '?')} (${b.get('symbol', '?')})"
        market_lines += [
            f"Name: {name_str}",
            f"Price: ${best.get('priceUsd', 'N/A')}",
            f"Market Cap: ${mc:,.0f}",
            f"Liquidity: ${liq:,.0f}",
            f"Volume 24h: ${vol:,.0f}",
            f"1h / 24h: {pc.get('h1', 'N/A')}% / {pc.get('h24', 'N/A')}%",
            f"Age: {age_str}",
        ]
    else:
        market_lines.append("DexScreener: no pairs found")

    # Try CoinGecko if it's a named token
    cg_data, cg_image, cg_socials, cg_id = {}, None, {}, ""
    if pairs:
        sym = (pairs[0].get("baseToken") or {}).get("symbol", "")
        if sym:
            cg_data = _fetch_cg_coin(sym)
            if cg_data:
                cg_id = cg_data.get("id", "")
                cg_image, cg_socials = _extract_cg_media(cg_data)

    # Rugcheck
    rg_lines = []
    if _SOLANA_ADDR.match(address):
        rg = _fetch_rugcheck(address)
        if rg:
            score = rg.get("score", "N/A")
            risks = rg.get("risks", [])
            rg_lines.append(f"Rugcheck score: {score}")
            for risk in risks:
                lvl = risk.get("level", "?").upper()
                rg_lines.append(f"  [{lvl}] {risk.get('name')} — {risk.get('description', '')}")
        else:
            rg_lines.append("Rugcheck: unavailable")

    # Merge socials (CoinGecko wins over DexScreener for quality)
    socials = {**dex_socials, **{k: v for k, v in cg_socials.items() if v}}
    socials_block = _build_socials_block(socials, dex_url=dex_url, cg_id=cg_id)

    data_summary = "\n".join(market_lines + rg_lines)
    answer = _ai(
        f"The user wants a safety and market analysis for this crypto contract.\n\n"
        f"Raw data:\n{data_summary}\n\n"
        f"Give a clear verdict: Is this safe to trade? What are the risks? "
        f"What does the market data suggest about momentum and opportunity?",
        max_tokens=500,
    )
    image_url = cg_image or dex_image
    return answer, image_url, name_str, socials_block


def _handle_coin_search(text: str):
    keyword = _extract_search_term(text).upper()
    pairs = _fetch_dex_search(keyword)

    if not pairs:
        return f"No tokens found on DexScreener matching '{keyword}'.", None, None, ""

    lines = [f"DexScreener search: '{keyword}' — {len(pairs)} results\n"]
    top_image, top_caption = None, None

    for i, p in enumerate(pairs[:5]):
        b = p.get("baseToken", {})
        liq = (p.get("liquidity") or {}).get("usd", 0)
        vol = (p.get("volume") or {}).get("h24", 0)
        mc = p.get("marketCap") or p.get("fdv") or 0
        ch24 = (p.get("priceChange") or {}).get("h24", "N/A")
        created = p.get("pairCreatedAt")
        age_h = ((time.time() * 1000 - created) / 3_600_000) if created else None
        age_str = f"{age_h:.1f}h" if age_h else "?"

        if i == 0:
            # Image for top result only
            top_caption = f"{b.get('name', '?')} (${b.get('symbol', '?')})"
            img, _ = _extract_dex_media([p])
            if not img:
                cg = _fetch_cg_coin(b.get("symbol", ""))
                if cg:
                    img, _ = _extract_cg_media(cg)
            top_image = img

        lines.append(
            f"{'🥇' if i==0 else f'{i+1}.'} {b.get('name')} (${b.get('symbol')}) | "
            f"{p.get('chainId','?').upper()} | age={age_str} | "
            f"liq=${liq:,.0f} | vol24h=${vol:,.0f} | mcap=${mc:,.0f} | 24h={ch24}%\n"
            f"   🔗 {p.get('url','')}"
        )

    data_summary = "\n".join(lines)
    answer = _ai(
        f"The user searched for crypto tokens matching '{keyword}'.\n\n"
        f"Results:\n{data_summary}\n\n"
        f"Summarise the best options, flag any risks (very low liquidity, suspicious names), "
        f"and give narrative context for why these tokens exist right now.",
        max_tokens=600,
    )
    return answer, top_image, top_caption, ""


def _handle_trending(_text: str):
    cg_trending = _fetch_cg_trending()
    global_data = _fetch_cg_global()
    dex_trending = _fetch_dex_trending()

    cg_lines = "\n".join(
        f"  {c['name']} (${c['symbol']}) rank={c['rank']} change={c.get('change_24h','N/A')}%"
        for c in cg_trending
    )
    data_summary = (
        f"CoinGecko global: mcap={global_data.get('total_mcap_usd','N/A')} "
        f"btc_dom={global_data.get('btc_dominance')}% mcap_chg24h={global_data.get('mcap_change_24h')}%\n\n"
        f"CoinGecko trending:\n{cg_lines}\n\n"
        f"DexScreener recent profiles: {len(dex_trending)} tokens being promoted"
    )
    answer = _ai(
        f"The user wants to know what is trending in crypto right now.\n\n"
        f"Live data:\n{data_summary}\n\n"
        f"Identify the top narratives, which coins have the most momentum, "
        f"and what sectors or themes are driving attention today.",
        max_tokens=600,
    )
    return answer, None, None, ""


def _handle_crypto_price(text: str):
    prices = _fetch_btc_eth()
    global_data = _fetch_cg_global()

    common = {"bitcoin": "bitcoin", "btc": "bitcoin", "ethereum": "ethereum",
              "eth": "ethereum", "solana": "solana", "sol": "solana"}
    specific = next((common[w] for w in text.lower().split() if w in common), None)

    # For a named major coin, fetch logo
    image_url, caption = None, None
    cg_data = {}
    if specific:
        cg_data = _fetch_cg_coin(specific)
        if cg_data:
            image_url, _ = _extract_cg_media(cg_data)
            sym = cg_data.get("symbol", "").upper()
            name = cg_data.get("name", specific.title())
            caption = f"{name} (${sym})"

    # If it's not a major, try searching CoinGecko for whatever they asked about
    if not specific and not cg_data:
        words = [w for w in text.split() if len(w) > 2 and w.lower() not in
                 {"is", "the", "for", "what", "how", "price", "going", "today", "now", "doing"}]
        if words:
            cg_data = _fetch_cg_coin(words[0])
            if cg_data:
                image_url, _ = _extract_cg_media(cg_data)
                sym = cg_data.get("symbol", "").upper()
                name = cg_data.get("name", words[0].title())
                caption = f"{name} (${sym})"

    btc = prices.get("bitcoin", {})
    eth = prices.get("ethereum", {})
    sol = prices.get("solana", {})

    # Specific coin detail lines
    coin_detail_lines = ""
    if cg_data:
        md = cg_data.get("market_data", {})
        coin_detail_lines = (
            f"\n{cg_data.get('name')} detail:\n"
            f"  Price: ${(md.get('current_price') or {}).get('usd', 'N/A')}\n"
            f"  24h change: {(md.get('price_change_percentage_24h') or 0):.2f}%\n"
            f"  7d change: {(md.get('price_change_percentage_7d') or 0):.2f}%\n"
            f"  Market cap: ${(md.get('market_cap') or {}).get('usd', 0):,.0f}\n"
            f"  ATH: ${(md.get('ath') or {}).get('usd', 'N/A')}\n"
            f"  ATH change: {(md.get('ath_change_percentage') or {}).get('usd', 'N/A')}%"
        )

    data_summary = (
        f"BTC: ${btc.get('usd','N/A'):,} | 24h: {btc.get('usd_24h_change',0):.2f}%\n"
        f"ETH: ${eth.get('usd','N/A'):,} | 24h: {eth.get('usd_24h_change',0):.2f}%\n"
        f"SOL: ${sol.get('usd','N/A'):,} | 24h: {sol.get('usd_24h_change',0):.2f}%\n"
        f"Global mcap: ${global_data.get('total_mcap_usd','N/A'):,} | "
        f"BTC dom: {global_data.get('btc_dominance')}% | "
        f"24h change: {global_data.get('mcap_change_24h')}%"
        f"{coin_detail_lines}"
    )
    answer = _ai(
        f"User question: {text}\n\nLive market data:\n{data_summary}\n\n"
        f"Answer the question directly. Give context on direction, momentum, and what to watch.",
        max_tokens=500,
    )

    # Build socials block for specific coin
    socials_block = ""
    if cg_data:
        _, cg_socials = _extract_cg_media(cg_data)
        cg_id = cg_data.get("id", "")
        socials_block = _build_socials_block(cg_socials, cg_id=cg_id)

    return answer, image_url, caption, socials_block


def _handle_macro(text: str):
    macro = _fetch_macro()
    eq = macro.get("equities", {})
    cm = macro.get("commodities", {})

    def row(label, d):
        return f"{label}: ${d.get('price','N/A')} ({d.get('change_pct','N/A')}%)"

    data_summary = (
        f"{row('S&P 500', eq.get('sp500', {}))}\n"
        f"{row('NASDAQ',  eq.get('nasdaq', {}))}\n"
        f"{row('DOW',     eq.get('dow', {}))}\n"
        f"{row('WTI Oil', cm.get('wti_crude', {}))}\n"
        f"{row('Gold',    cm.get('gold', {}))}\n"
        f"{row('DXY',     cm.get('dxy', {}))}"
    )
    answer = _ai(
        f"User question: {text}\n\nLive macro data:\n{data_summary}\n\n"
        f"Answer the question directly. Give context on what the moves mean.",
        max_tokens=500,
    )
    return answer, None, None, ""


def _handle_news(text: str):
    news = _fetch_finnhub_news()
    if news:
        lines = [f"{i+1}. {n.get('headline','')} — {n.get('source','')}"
                 for i, n in enumerate(news[:7])]
        data_summary = "Latest market news:\n" + "\n".join(lines)
    else:
        data_summary = "News feed unavailable right now."
    answer = _ai(
        f"User question: {text}\n\n{data_summary}\n\n"
        f"Summarise the most important stories and explain what they mean for markets and crypto.",
        max_tokens=600,
    )
    return answer, None, None, ""


def _handle_general(text: str):
    prices = _fetch_btc_eth()
    global_data = _fetch_cg_global()
    btc = prices.get("bitcoin", {})
    data_summary = (
        f"BTC: ${btc.get('usd','N/A')} | 24h: {btc.get('usd_24h_change',0):.2f}%\n"
        f"Global mcap: ${global_data.get('total_mcap_usd','N/A')} | "
        f"BTC dom: {global_data.get('btc_dominance')}%"
    )
    answer = _ai(
        f"User question: {text}\n\nContext data:\n{data_summary}\n\n"
        f"Answer the question as best you can using your knowledge and the data provided.",
        max_tokens=600,
    )
    return answer, None, None, ""


# ── Main entry point ───────────────────────────────────────────────────────────

def research(question: str) -> dict:
    """
    Main research handler.
    Returns dict:
      text       — formatted Telegram HTML message
      image_url  — logo URL to send_photo before text (or None)
      caption    — photo caption string (or None)
    """
    q = question.strip()
    q_type = _classify(q)
    logger.info("Research query [%s]: %s", q_type, q[:80])

    socials_block = ""
    image_url = None
    caption = None

    try:
        if q_type == "contract":
            answer, image_url, caption, socials_block = _handle_contract(q)
        elif q_type == "coin_search":
            answer, image_url, caption, socials_block = _handle_coin_search(q)
        elif q_type == "trending":
            answer, image_url, caption, socials_block = _handle_trending(q)
        elif q_type == "crypto_price":
            answer, image_url, caption, socials_block = _handle_crypto_price(q)
        elif q_type == "macro":
            answer, image_url, caption, socials_block = _handle_macro(q)
        elif q_type == "news":
            answer, image_url, caption, socials_block = _handle_news(q)
        else:
            answer, image_url, caption, socials_block = _handle_general(q)
    except Exception as exc:
        logger.error("Research handler error [%s]: %s", q_type, exc, exc_info=True)
        answer = f"Research failed: {exc}"

    # Escape the user question for HTML
    q_escaped = q.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    socials_section = f"\n\n{socials_block}" if socials_block else ""

    text = (
        f"{SEP}\n"
        f"🔍 <b>ESA RESEARCH</b>\n"
        f"{SEP}\n\n"
        f"<i>{q_escaped}</i>\n\n"
        f"{answer}"
        f"{socials_section}\n\n"
        f"{SEP}\n"
        f"<i>ESA Signal — Signals only. You execute.</i>\n"
        f"{SEP}"
    )

    return {"text": text, "image_url": image_url, "caption": caption}
