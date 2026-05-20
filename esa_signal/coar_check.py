import requests

headers = {"User-Agent": "Mozilla/5.0"}

addrs = [
    ("CoARkJh4dhZ56pBNKnxprWkrwfpQcMVKsXsxK9ZorNBX", "Solana A — 60h old, $26K liq, -66% 24h"),
    ("Hurm47RxPHZ1n2W8YYHn7WJie8PDLsD5A4n9UC1vpump", "Solana B — 53h old, $27K liq, +88% 24h"),
]

for addr, label in addrs:
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"Address: {addr}")

    # Rugcheck
    r = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{addr}/report/summary", timeout=10, headers=headers)
    if r.status_code == 200:
        d = r.json()
        score = d.get("score")
        risks = d.get("risks", [])
        print(f"\nRugcheck score: {score}  (lower = safer, <500 = good)")
        for risk in risks:
            lvl = risk.get("level", "?").upper()
            name = risk.get("name", "")
            desc = risk.get("description", "")
            print(f"  [{lvl}] {name} — {desc}")
    else:
        print(f"Rugcheck: HTTP {r.status_code}")

    # DexScreener txn detail
    r2 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}", headers=headers, timeout=15)
    data = r2.json()
    pairs = data.get("pairs") or []
    if pairs:
        p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        txns = p.get("txns", {})
        h1 = txns.get("h1") or {}
        h6 = txns.get("h6") or {}
        h24 = txns.get("h24") or {}
        vol = p.get("volume") or {}
        print("\nTransaction activity:")
        print(f"  Buys  — 1h: {h1.get('buys')}  6h: {h6.get('buys')}  24h: {h24.get('buys')}")
        print(f"  Sells — 1h: {h1.get('sells')}  6h: {h6.get('sells')}  24h: {h24.get('sells')}")
        print(
            f"Volume — 5m: ${vol.get('m5', 0):,.0f}  1h: ${vol.get('h1', 0):,.0f}"
            f"  6h: ${vol.get('h6', 0):,.0f}  24h: ${vol.get('h24', 0):,.0f}")
        pc = p.get('priceChange') or {}
        print(f"Price change — 5m: {pc.get('m5')}%  1h: {pc.get('h1')}%")
        info = p.get("info") or {}
        print(f"Holders: {info.get('holders', 'N/A')}")

print("\n" + "="*60)
print("Base chain COAR (0xd343...175d):")
print("  $444K mcap | $333K liquidity | -1.9% 24h | 52h old")
print("  No rugcheck (Base chain) — check Basescan for contract")
