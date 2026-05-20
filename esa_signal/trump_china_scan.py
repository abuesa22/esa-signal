"""
One-time DexScreener scan for Trump-China narrative memecoins.
Run directly: python trump_china_scan.py
"""
import sys
import time
import requests
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

KEYWORDS = [
    "BEIJING", "XI", "XITRUMP", "TRUMPXI", "CHINADEAL",
    "SILKROAD", "GREATWALL", "DRAGONDEAL", "TRUMPCHINA",
    "CHINABULL", "REDDRAGON", "MAODEAL", "BEIJINGBULL",
    "DEALCHINA", "AIRFORCE",
]

DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{}/report/summary"

HEADERS = {"User-Agent": "Mozilla/5.0"}

seen = {}   # address -> pair dict


def age_str(created_at_ms):
    if not created_at_ms:
        return "unknown"
    now_ms = time.time() * 1000
    diff = (now_ms - created_at_ms) / 1000
    h = diff / 3600
    if h < 1:
        return f"{int(diff/60)}m"
    if h < 24:
        return f"{h:.1f}h"
    return f"{h/24:.1f}d"


def age_hours(created_at_ms):
    if not created_at_ms:
        return 9999
    return (time.time() * 1000 - created_at_ms) / 3_600_000


def rugcheck_score(address, chain):
    if chain.lower() != "solana":
        return None, None
    try:
        r = requests.get(RUGCHECK.format(address), timeout=10, headers=HEADERS)
        if r.status_code == 200:
            d = r.json()
            score = d.get("score")
            risks = [x.get("name", "") for x in d.get("risks", []) if x.get("level") in ("danger", "warn")]
            return score, risks
    except Exception:
        pass
    return None, None


def fmt_usd(v):
    if v is None:
        return "N/A"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:.0f}"


def fmt_price(v):
    if v is None:
        return "N/A"
    v = float(v)
    if v >= 1:
        return f"${v:,.4f}"
    if v >= 0.0001:
        return f"${v:.6f}"
    return f"${v:.10f}"


def fmt_pct(v):
    if v is None:
        return "N/A"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.2f}%"


print("=" * 70)
print("  TRUMP-CHINA NARRATIVE SCAN — DexScreener")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)
print(f"\nSearching {len(KEYWORDS)} keywords...\n")

for kw in KEYWORDS:
    try:
        r = requests.get(DEX_SEARCH, params={"q": kw}, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  [{kw}] HTTP {r.status_code} — skipped")
            continue
        pairs = r.json().get("pairs") or []
        matched = 0
        for p in pairs:
            addr = (p.get("baseToken") or {}).get("address", "")
            if not addr or addr in seen:
                continue
            name = (p.get("baseToken") or {}).get("name", "").upper()
            symbol = (p.get("baseToken") or {}).get("symbol", "").upper()
            if kw not in name and kw not in symbol:
                continue
            seen[addr] = p
            matched += 1
        print(f"  [{kw}] {matched} new match(es) (total unique: {len(seen)})")
    except Exception as exc:
        print(f"  [{kw}] Error: {exc}")
    time.sleep(0.3)

print(f"\nTotal unique tokens found: {len(seen)}")

if not seen:
    print("\nNo matching tokens found on DexScreener for these keywords.")
    sys.exit(0)

# ── Enrich + flag ──────────────────────────────────────────────────────────────
results = []
print("\nFetching rugcheck scores for Solana tokens...")
for addr, p in seen.items():
    base = p.get("baseToken") or {}
    chain = (p.get("chainId") or "").lower()
    liquidity = (p.get("liquidity") or {}).get("usd")
    volume24 = (p.get("volume") or {}).get("h24")
    price = p.get("priceUsd")
    mcap = p.get("marketCap") or p.get("fdv")
    txns = p.get("txns") or {}
    buys24 = (txns.get("h24") or {}).get("buys", 0)
    sells24 = (txns.get("h24") or {}).get("sells", 0)
    created = p.get("pairCreatedAt")
    ch1h = (p.get("priceChange") or {}).get("h1")
    ch24h = (p.get("priceChange") or {}).get("h24")
    url = p.get("url", "")

    # Rugcheck
    rg_score, rg_risks = None, None
    if chain == "solana":
        rg_score, rg_risks = rugcheck_score(addr, chain)
        time.sleep(0.2)

    # Flags
    flags = []
    if liquidity and liquidity < 10_000:
        flags.append("LOW_LIQ")
    holders = None  # DexScreener search doesn't return holder count directly
    if age_hours(created) > 72:
        flags.append("OLD_TOKEN")

    results.append({
        "name":     base.get("name", "?"),
        "symbol":   base.get("symbol", "?"),
        "address":  addr,
        "chain":    chain,
        "age":      age_str(created),
        "age_h":    age_hours(created),
        "liquidity": liquidity,
        "volume24":  volume24,
        "price":    price,
        "mcap":     mcap,
        "buys24":   buys24,
        "sells24":  sells24,
        "ch1h":     ch1h,
        "ch24h":    ch24h,
        "rg_score": rg_score,
        "rg_risks": rg_risks or [],
        "flags":    flags,
        "url":      url,
    })

# ── Sort: 1) liquidity desc  2) rugcheck score asc (lower = safer) ────────────
results.sort(key=lambda x: (
    -(x["liquidity"] or 0),
    x["rg_score"] if x["rg_score"] is not None else 9999,
))

# ── Print ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print(f"  RESULTS — {len(results)} token(s) ranked by liquidity")
print("=" * 70)

for i, t in enumerate(results, 1):
    flag_str = ("  ⚠️  FLAGS: " + ", ".join(t["flags"])) if t["flags"] else ""
    rg_str = f"  Rugcheck: {t['rg_score']}" if t["rg_score"] is not None else "  Rugcheck: N/A"
    if t["rg_risks"]:
        rg_str += f"  |  Risks: {', '.join(t['rg_risks'][:3])}"

    print(f"""
{'─'*70}
#{i}  {t['name']}  (${t['symbol']})
  Chain:      {t['chain'].upper()}
  Address:    {t['address']}
  Age:        {t['age']}
  Price:      {fmt_price(t['price'])}
  Mkt Cap:    {fmt_usd(t['mcap'])}
  Liquidity:  {fmt_usd(t['liquidity'])}
  Volume 24h: {fmt_usd(t['volume24'])}
  Buys/Sells: {t['buys24']} / {t['sells24']} (24h)
  1h change:  {fmt_pct(t['ch1h'])}
  24h change: {fmt_pct(t['ch24h'])}
{rg_str}{flag_str}
  URL:        {t['url']}""")

print(f"\n{'='*70}")
print(f"  Scan complete — {len(results)} token(s) found")
print(f"  Flagged: {sum(1 for r in results if r['flags'])} | "
      f"Solana: {sum(1 for r in results if r['chain']=='solana')} | "
      f"ETH/Other: {sum(1 for r in results if r['chain']!='solana')}")
print("=" * 70)
