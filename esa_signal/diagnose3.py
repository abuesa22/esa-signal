"""Verify fixed EDGAR company names and Finnhub earnings."""
import sys
sys.path.insert(0, ".")

print("=== EDGAR IPO filings ===")
from markets.stock_scanner import get_recent_ipo_filings  # noqa: E402
ipos = get_recent_ipo_filings()
if ipos:
    for i in ipos:
        print(f"  {i['form']:6s} | {i['filed']} | {i['company']}")
else:
    print("  No results")

print("\n=== Finnhub earnings (with estimates only) ===")
from markets.stock_scanner import get_earnings_calendar  # noqa: E402
earnings = get_earnings_calendar()
if earnings:
    for e in earnings:
        print(f"  {e['symbol']:8s} {e['date']} | EPS: {e['eps_est']:>8s} | Rev: {e['rev_est']:>10s} | {e['timing']}")
else:
    print("  No results with estimates")
