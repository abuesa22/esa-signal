"""Quick sanity test — fetches real data from each source."""
import sys
sys.path.insert(0, ".")

print("Testing yfinance (BTC, ETH, SP500 futures)...")
from markets.stock_scanner import get_crypto_prices, get_us_futures, get_commodities  # noqa: E402
crypto = get_crypto_prices()
futures = get_us_futures()
commodities = get_commodities()
print(f"  BTC: {crypto.get('btc')}")
print(f"  ETH: {crypto.get('eth')}")
print(f"  SP500 futures: {futures.get('sp500')}")
print(f"  Gold: {commodities.get('gold')}")
print(f"  DXY: {commodities.get('dxy')}")

print("\nTesting CoinGecko (global + trending)...")
from markets.stock_scanner import get_global_crypto_data, get_trending_coins  # noqa: E402
gcrypto = get_global_crypto_data()
trending = get_trending_coins()
print(f"  BTC dominance: {gcrypto.get('btc_dominance')}%")
print(f"  Total market cap: ${gcrypto.get('total_market_cap_usd', 0)/1e9:.1f}B")
print(f"  Trending coins: {[c['name'] for c in trending[:3]]}")

print("\nTesting Finnhub (news)...")
from markets.stock_scanner import get_market_news  # noqa: E402
news = get_market_news()
print(f"  News items: {len(news)}")
if news:
    print(f"  Latest: {news[0].get('headline', '')[:60]}...")

print("\nTesting DexScreener (new token profiles)...")
from utils.helpers import http_get  # noqa: E402
data = http_get("https://api.dexscreener.com/token-profiles/latest/v1")
if isinstance(data, list):
    print(f"  Token profiles returned: {len(data)}")
    sol_tokens = [p for p in data if p.get('chainId') == 'solana']
    eth_tokens = [p for p in data if p.get('chainId') == 'ethereum']
    print(f"  Solana: {len(sol_tokens)} | Ethereum: {len(eth_tokens)}")
else:
    print(f"  Unexpected response: {type(data)}")

print("\nTesting Anthropic (quick test)...")
import os  # noqa: E402
import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
load_dotenv("../.env.txt")
key = os.getenv("ANTHROPIC_API_KEY", "").strip()
if key:
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=30,
        messages=[{"role": "user", "content": "Say OK"}]
    )
    print(f"  Claude response: {resp.content[0].text.strip()}")
else:
    print("  No API key")

print("\nAll tests complete.")
