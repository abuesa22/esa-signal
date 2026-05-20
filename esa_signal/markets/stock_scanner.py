"""
Fetches market data from: yfinance, Alpha Vantage, Finnhub, CoinGecko, SEC EDGAR.
All functions return dicts; callers handle formatting.
"""

import logging
from datetime import date, timedelta

import yfinance as yf

from config import ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY, COINGECKO_API_KEY
from utils.helpers import http_get
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

AV_BASE = "https://www.alphavantage.co/query"
FH_BASE = "https://finnhub.io/api/v1"
CG_BASE = "https://api.coingecko.com/api/v3"
EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"


# ── yfinance helpers ───────────────────────────────────────────────────────────

def _yf_quote(symbol: str) -> dict:
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 1:
            return {"price": None, "change_pct": None}
        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        change_pct = ((price - prev) / prev * 100) if prev else 0
        return {"price": round(price, 4), "change_pct": round(change_pct, 2)}
    except Exception as exc:
        logger.warning("yfinance error for %s: %s", symbol, exc)
        return {"price": None, "change_pct": None}


def get_us_futures() -> dict:
    return {
        "sp500": _yf_quote("ES=F"),
        "nasdaq": _yf_quote("NQ=F"),
        "dow": _yf_quote("YM=F"),
    }


def get_us_market_close() -> dict:
    return {
        "sp500": _yf_quote("^GSPC"),
        "nasdaq": _yf_quote("^IXIC"),
        "dow": _yf_quote("^DJI"),
    }


def get_commodities() -> dict:
    return {
        "wti_crude": _yf_quote("CL=F"),
        "gold": _yf_quote("GC=F"),
        "dxy": _yf_quote("DX-Y.NYB"),
    }


def get_crypto_prices() -> dict:
    """Get BTC/ETH prices. Uses CoinGecko as primary, yfinance as fallback."""
    rate_limiter.wait("coingecko")
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
    data = http_get(
        f"{CG_BASE}/simple/price",
        headers=headers,
        params={
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        },
    )
    if data:
        btc = data.get("bitcoin", {})
        eth = data.get("ethereum", {})
        return {
            "btc": {
                "price": btc.get("usd"),
                "change_pct": round(btc.get("usd_24h_change", 0), 2),
            },
            "eth": {
                "price": eth.get("usd"),
                "change_pct": round(eth.get("usd_24h_change", 0), 2),
            },
        }
    # Fallback to yfinance
    return {
        "btc": _yf_quote("BTC-USD"),
        "eth": _yf_quote("ETH-USD"),
    }


def get_sector_performance() -> list[dict]:
    """Return sector ETF performance (top 3 gainers)."""
    sector_etfs = {
        "Technology": "XLK",
        "Energy": "XLE",
        "Financials": "XLF",
        "Healthcare": "XLV",
        "Industrials": "XLI",
        "Consumer Disc": "XLY",
        "Utilities": "XLU",
        "Materials": "XLB",
        "Real Estate": "XLRE",
        "Comm Services": "XLC",
    }
    results = []
    for sector, etf in sector_etfs.items():
        q = _yf_quote(etf)
        if q["price"]:
            results.append({"sector": sector, **q})
    results.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
    return results


# ── Alpha Vantage ──────────────────────────────────────────────────────────────

def get_top_movers() -> dict:
    """Top gainers and losers from Alpha Vantage."""
    rate_limiter.wait("alphavantage")
    data = http_get(
        AV_BASE,
        params={"function": "TOP_GAINERS_LOSERS", "apikey": ALPHA_VANTAGE_API_KEY},
    )
    if not data:
        return {"gainers": [], "losers": []}
    return {
        "gainers": data.get("top_gainers", [])[:5],
        "losers": data.get("top_losers", [])[:5],
    }


# ── Finnhub ───────────────────────────────────────────────────────────────────

def _fh_headers() -> dict:
    return {"X-Finnhub-Token": FINNHUB_API_KEY}


def get_economic_calendar() -> list[dict]:
    """Today's economic events from Finnhub."""
    rate_limiter.wait("finnhub")
    today = date.today().isoformat()
    data = http_get(
        f"{FH_BASE}/calendar/economic",
        headers=_fh_headers(),
        params={"from": today, "to": today},
    )
    if not data:
        return []
    events = data.get("economicCalendar", [])
    # Return high-impact events only
    return [e for e in events if e.get("impact") == "high"][:10]


def get_earnings_calendar() -> list[dict]:
    """Recent reported + upcoming earnings from Finnhub, most recent first."""
    rate_limiter.wait("finnhub")
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()   # catch recently reported
    end = (today + timedelta(days=3)).isoformat()
    data = http_get(
        f"{FH_BASE}/calendar/earnings",
        headers=_fh_headers(),
        params={"from": start, "to": end},
    )
    if not data:
        return []

    raw = data.get("earningsCalendar", [])

    results = []
    for e in raw:
        eps_est = e.get("epsEstimate")
        eps_act = e.get("epsActual")
        rev_est = e.get("revenueEstimate")
        rev_act = e.get("revenueActual")

        # Skip if absolutely nothing to show
        if eps_est is None and eps_act is None and rev_est is None:
            continue

        def _fmt_eps(val) -> str:
            return f"${val:+.2f}" if val is not None else "N/A"

        def _fmt_rev(val) -> str:
            if val is None:
                return "N/A"
            if val >= 1_000_000_000:
                return f"${val / 1_000_000_000:.2f}B"
            if val >= 1_000_000:
                return f"${val / 1_000_000:.1f}M"
            return f"${val:,.0f}"

        hour_map = {"bmo": "pre-mkt", "amc": "after-mkt", "dmh": "during mkt"}

        # Use actual if reported, else estimate
        eps_str = _fmt_eps(eps_act if eps_act is not None else eps_est)
        rev_str = _fmt_rev(rev_act if rev_act is not None else rev_est)
        reported = eps_act is not None

        results.append({
            "symbol": e.get("symbol", "?"),
            "date": e.get("date", "?"),
            "quarter": e.get("quarter"),
            "year": e.get("year"),
            "eps_str": eps_str,
            "rev_str": rev_str,
            "reported": reported,
            "timing": hour_map.get(e.get("hour", ""), ""),
        })

    # Most recent first
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results[:8]


def get_market_news() -> list[dict]:
    """Latest market news from Finnhub."""
    rate_limiter.wait("finnhub")
    data = http_get(
        f"{FH_BASE}/news",
        headers=_fh_headers(),
        params={"category": "general"},
    )
    if not isinstance(data, list):
        return []
    return data[:5]


def get_market_status() -> dict:
    """Is the US market open?"""
    rate_limiter.wait("finnhub")
    data = http_get(f"{FH_BASE}/stock/market-status", headers=_fh_headers(), params={"exchange": "US"})
    return data or {}


# ── CoinGecko ─────────────────────────────────────────────────────────────────

def _cg_headers() -> dict:
    return {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}


def get_global_crypto_data() -> dict:
    """Global crypto market data — BTC dominance, total market cap, etc."""
    rate_limiter.wait("coingecko")
    data = http_get(f"{CG_BASE}/global", headers=_cg_headers())
    if data and "data" in data:
        d = data["data"]
        return {
            "total_market_cap_usd": d.get("total_market_cap", {}).get("usd"),
            "total_volume_usd": d.get("total_volume", {}).get("usd"),
            "btc_dominance": round(d.get("market_cap_percentage", {}).get("btc", 0), 1),
            "eth_dominance": round(d.get("market_cap_percentage", {}).get("eth", 0), 1),
            "market_cap_change_pct_24h": round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
        }
    return {}


def get_trending_coins() -> list[dict]:
    """CoinGecko trending coins."""
    rate_limiter.wait("coingecko")
    data = http_get(f"{CG_BASE}/search/trending", headers=_cg_headers())
    if data and "coins" in data:
        return [
            {
                "name": c["item"].get("name"),
                "symbol": c["item"].get("symbol"),
                "market_cap_rank": c["item"].get("market_cap_rank"),
                "price_change_24h": c["item"].get("data", {}).get("price_change_percentage_24h", {}).get("usd"),
            }
            for c in data["coins"]
        ]
    return []


def get_big_movers_crypto(hours: int = 4) -> list[dict]:
    """Coins up 100%+ in the last N hours (from CoinGecko top-100)."""
    rate_limiter.wait("coingecko")
    data = http_get(
        f"{CG_BASE}/coins/markets",
        headers=_cg_headers(),
        params={
            "vs_currency": "usd",
            "order": "percent_change_24h_desc",
            "per_page": 100,
            "price_change_percentage": "1h",
        },
    )
    if not isinstance(data, list):
        return []
    spikes = [
        c for c in data
        if (c.get("price_change_percentage_1h_in_currency") or 0) >= 100
    ]
    return spikes[:5]


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────

_EDGAR_HEADERS = {"User-Agent": "ESA Signal Bot contact@esasignal.local"}


def _clean_edgar_display_name(raw: str) -> str:
    """'Neutron Holdings, Inc.  (CIK 0001699963)' → 'Neutron Holdings, Inc.'"""
    import re
    return re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", raw).strip()


def _parse_rss_title(title: str) -> tuple[str, str]:
    """
    'S-1 - Vaxart, Inc. (0000072444) (Filer)' → ('Vaxart, Inc.', 'S-1')
    'S-1/A - GMR Solutions Inc. (0001898718) (Filer)' → ('GMR Solutions Inc.', 'S-1/A')
    """
    import re
    m = re.match(r"^(S-1[/A]*)\s+-\s+(.+?)\s+\(\d+\)", title or "")
    if m:
        return m.group(2).strip(), m.group(1)
    return title or "Unknown", "S-1"


def get_recent_ipo_filings() -> list[dict]:
    """Recent S-1 filings from EDGAR. Primary: EFTS JSON. Fallback: RSS feed."""
    rate_limiter.wait("edgar")
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()

    # ── Primary: EFTS full-text search ───────────────────────────────────────
    data = http_get(
        "https://efts.sec.gov/LATEST/search-index",
        headers=_EDGAR_HEADERS,
        params={
            "q": "",
            "forms": "S-1",
            "dateRange": "custom",
            "startdt": week_ago,
            "enddt": today.isoformat(),
        },
    )
    if data:
        hits = data.get("hits", {}).get("hits", [])
        if hits:
            results = []
            for h in hits[:5]:
                src = h.get("_source", {})
                raw_names = src.get("display_names", [])
                company = _clean_edgar_display_name(raw_names[0]) if raw_names else "Unknown"
                ciks = src.get("ciks", [""])
                cik = ciks[0].lstrip("0") if ciks else ""
                results.append({
                    "company": company,
                    "filed": src.get("file_date", ""),
                    "form": src.get("form", "S-1"),
                    "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=S-1",
                })
            return results

    # ── Fallback: Atom/RSS feed ───────────────────────────────────────────────
    return _get_edgar_rss_filings()


def _get_edgar_rss_filings() -> list[dict]:
    """Fallback: parse EDGAR Atom RSS for recent S-1 filings."""
    try:
        import xml.etree.ElementTree as ET
        import requests as _req
        resp = _req.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            headers=_EDGAR_HEADERS,
            params={"action": "getcurrent", "type": "S-1", "owner": "include",
                    "count": "10", "output": "atom"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        results = []
        for entry in root.findall("a:entry", ns)[:5]:
            title_el = entry.find("a:title", ns)
            updated_el = entry.find("a:updated", ns)
            link_el = entry.find("a:link", ns)
            raw_title = title_el.text if title_el is not None else ""
            company, form = _parse_rss_title(raw_title)
            filed = (updated_el.text or "")[:10] if updated_el is not None else ""
            url = link_el.get("href", "") if link_el is not None else ""
            results.append({"company": company, "filed": filed, "form": form, "url": url})
        return results
    except Exception as exc:
        logger.warning("EDGAR RSS fallback failed: %s", exc)
        return []
