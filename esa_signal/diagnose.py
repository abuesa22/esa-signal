"""Diagnose API key loading and live connections."""
import sys
sys.path.insert(0, ".")

print("=== 1. ENV FILE LOADING ===")
from pathlib import Path  # noqa: E402
for candidate in [".env", ".env.txt", "../.env", "../.env.txt"]:
    p = Path(candidate)
    if p.exists():
        print(f"Found env file: {p.resolve()}")
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key = line.split("=")[0].strip()
                    val = "=".join(line.split("=")[1:]).strip()
                    print(f"  {key} = '{val[:6]}...{val[-4:]}' (len={len(val)})")
        break

print("\n=== 2. CONFIG VALUES ===")
import config  # noqa: E402
print(f"  ANTHROPIC_API_KEY: '{config.ANTHROPIC_API_KEY[:10]}...' (len={len(config.ANTHROPIC_API_KEY)})")
print(f"  COINGECKO_API_KEY: '{config.COINGECKO_API_KEY[:10]}...' (len={len(config.COINGECKO_API_KEY)})")
print(f"  CMC_API_KEY:       '{config.CMC_API_KEY[:10]}...' (len={len(config.CMC_API_KEY)})")
print(f"  TELEGRAM_BOT_TOKEN set: {bool(config.TELEGRAM_BOT_TOKEN)}")

print("\n=== 3. ANTHROPIC CONNECTION ===")
try:
    import anthropic  # noqa: E402
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{"role": "user", "content": "Reply: OK"}]
    )
    print(f"  Anthropic: OK — '{resp.content[0].text.strip()}'")
except Exception as e:
    print(f"  Anthropic ERROR: {e}")

print("\n=== 4. COINGECKO — BTC/ETH PRICES ===")
import requests  # noqa: E402
headers = {"x-cg-demo-api-key": config.COINGECKO_API_KEY}
try:
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        headers=headers,
        params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=15
    )
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"  BTC: ${d['bitcoin']['usd']:,} ({d['bitcoin']['usd_24h_change']:+.2f}%)")
        print(f"  ETH: ${d['ethereum']['usd']:,} ({d['ethereum']['usd_24h_change']:+.2f}%)")
    else:
        print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  CoinGecko ERROR: {e}")

print("\n=== 5. CMC — BTC QUOTE ===")
try:
    r = requests.get(
        "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
        headers={"X-CMC_PRO_API_KEY": config.CMC_API_KEY},
        params={"symbol": "BTC", "convert": "USD"},
        timeout=15
    )
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        btc = d["data"]["BTC"]["quote"]["USD"]
        print(f"  BTC: ${btc['price']:,.2f} ({btc['percent_change_24h']:+.2f}%)")
    else:
        print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  CMC ERROR: {e}")

print("\n=== 6. YFINANCE BTC-USD ===")
try:
    import yfinance as yf  # noqa: E402
    t = yf.Ticker("BTC-USD")
    hist = t.history(period="5d", interval="1d")
    if not hist.empty:
        price = float(hist["Close"].iloc[-1])
        print(f"  yfinance BTC: ${price:,.2f}")
    else:
        print("  yfinance returned empty dataframe")
except Exception as e:
    print(f"  yfinance ERROR: {e}")
