"""
Gate diagnostics — runs a real scan cycle and tallies failures at each gate.
Does NOT send any signals or Telegram messages.
Caps at 40 tokens to keep runtime under 3 minutes.
"""
import sys
import time
import os
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.helpers import http_get  # noqa: E402
from utils.rate_limiter import rate_limiter  # noqa: E402
from database.db import is_already_alerted  # noqa: E402
from scanner.safety_checker import run_gate1  # noqa: E402
from scanner.legitimacy_checker import run_gate2  # noqa: E402
from scanner.momentum_checker import run_gate3, run_gate4  # noqa: E402
from config import SUPPORTED_CHAINS  # noqa: E402

DEXSCREENER_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DEXSCREENER_BOOSTS = "https://api.dexscreener.com/token-boosts/latest/v1"
DEXSCREENER_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
MAX_TOKENS = 40

# ── Fetch candidates ──────────────────────────────────────────────────────────
print("Fetching DexScreener profiles + boosts...")
rate_limiter.wait("dexscreener")
profiles = http_get(DEXSCREENER_PROFILES, timeout=15) or []
rate_limiter.wait("dexscreener")
boosts = http_get(DEXSCREENER_BOOSTS, timeout=15) or []

seen, candidates = set(), []
for item in (profiles if isinstance(profiles, list) else []) + \
            (boosts if isinstance(boosts, list) else []):
    addr = item.get("tokenAddress", "")
    chain = (item.get("chainId") or "").lower()
    if addr and chain and addr not in seen:
        seen.add(addr)
        candidates.append({"tokenAddress": addr, "chainId": chain})

print(f"Raw candidates: {len(candidates)}")

# ── Filter candidates ─────────────────────────────────────────────────────────
to_scan = []
skipped_chain = 0
skipped_alerted = 0
skipped_recent = 0

for c in candidates:
    chain = c["chainId"]
    addr = c["tokenAddress"]
    if chain not in SUPPORTED_CHAINS:
        skipped_chain += 1
        continue
    if is_already_alerted(addr):
        skipped_alerted += 1
        continue
    # Skip recent-scan filter in diagnostic — we want to see all failures
    # if was_scanned_recently(addr, within_minutes=30):
    #     skipped_recent += 1
    #     continue
    to_scan.append(c)
    if len(to_scan) >= MAX_TOKENS:
        break

print(
    f"Skipped — wrong chain: {skipped_chain} | already alerted: {skipped_alerted} | scanned recently: {skipped_recent}")
print(f"Tokens to diagnose: {len(to_scan)}\n")
print("=" * 65)

# ── Gate tallies ──────────────────────────────────────────────────────────────
tally = {"no_pair": 0, "g1": {}, "g2": {}, "g3": {}, "g4": {}, "ai_ready": 0}
examples = {"g1": [], "g2": [], "g3": [], "g4": []}


def _bucket(reason: str) -> str:
    r = reason.lower()
    if "age" in r:
        return "age out of range"
    if "liquidity" in r:
        return "liquidity too low"
    if "rugcheck" in r:
        return "rugcheck failed"
    if "mint" in r:
        return "mint authority"
    if "volume" in r:
        return "volume too low"
    if "decelerat" in r:
        return "volume decelerating"
    if "sell" in r:
        return "sell pressure"
    if "market cap" in r:
        return "mcap too high"
    if "fdv" in r:
        return "FDV ratio too high"
    return reason[:50]


for i, profile in enumerate(to_scan, 1):
    chain = profile["chainId"]
    addr = profile["tokenAddress"]
    short = addr[:8] + "..."

    rate_limiter.wait("dexscreener")
    data = http_get(f"{DEXSCREENER_TOKENS}/{addr}", timeout=15)
    pairs = (data or {}).get("pairs") or []

    if not pairs:
        tally["no_pair"] += 1
        print(f"  [{i:02d}] {short} ({chain}) — no pair data")
        continue

    # Best pair by liquidity
    valid = [p for p in pairs if (p.get("liquidity") or {}).get("usd", 0)]
    pair = max(valid, key=lambda p: p["liquidity"]["usd"]) if valid else pairs[0]
    ticker = pair.get("baseToken", {}).get("symbol", "???").upper()
    liq = (pair.get("liquidity") or {}).get("usd", 0) or 0
    vol24 = (pair.get("volume") or {}).get("h24", 0) or 0
    mc = pair.get("marketCap") or 0
    age_ms = pair.get("pairCreatedAt")
    age_h = ((time.time()*1000 - age_ms)/3_600_000) if age_ms else None
    age_s = f"{age_h:.1f}h" if age_h else "?"

    prefix = (
        f"  [{i:02d}] {ticker:<8} ({chain[:3]}) age={age_s:<6}"
        f" liq=${liq:>8,.0f} vol=${vol24:>8,.0f} mc=${mc:>8,.0f}"
    )

    # Gate 1
    g1_pass, g1 = run_gate1(pair, chain)
    if not g1_pass:
        reason = g1.get("fail_reason", "unknown")
        bucket = _bucket(reason)
        tally["g1"][bucket] = tally["g1"].get(bucket, 0) + 1
        if len(examples["g1"]) < 3:
            examples["g1"].append(f"{ticker}: {reason}")
        print(f"{prefix} | G1 FAIL: {bucket}")
        continue

    # Gate 2
    g2_pass, g2 = run_gate2(pair, chain)
    if not g2_pass:
        reason = g2.get("fail_reason", "unknown")
        bucket = _bucket(reason)
        tally["g2"][bucket] = tally["g2"].get(bucket, 0) + 1
        if len(examples["g2"]) < 3:
            examples["g2"].append(f"{ticker}: {reason}")
        print(f"{prefix} | G2 FAIL: {bucket}")
        continue

    # Gate 3
    g3_pass, g3 = run_gate3(pair)
    if not g3_pass:
        reason = g3.get("fail_reason", "unknown")
        bucket = _bucket(reason)
        tally["g3"][bucket] = tally["g3"].get(bucket, 0) + 1
        if len(examples["g3"]) < 3:
            examples["g3"].append(f"{ticker}: {reason}")
        print(f"{prefix} | G3 FAIL: {bucket}")
        continue

    # Gate 4
    g4_pass, g4 = run_gate4(pair, rugcheck_details=g1)
    if not g4_pass:
        reason = g4.get("fail_reason", "unknown")
        bucket = _bucket(reason)
        tally["g4"][bucket] = tally["g4"].get(bucket, 0) + 1
        if len(examples["g4"]) < 3:
            examples["g4"].append(f"{ticker}: {reason}")
        print(f"{prefix} | G4 FAIL: {bucket}")
        continue

    tally["ai_ready"] += 1
    print(f"{prefix} | ✅ ALL GATES PASSED — would hit AI scorer")

# ── Summary ───────────────────────────────────────────────────────────────────
total = len(to_scan) - tally["no_pair"]
g1_fail = sum(tally["g1"].values())
g2_fail = sum(tally["g2"].values())
g3_fail = sum(tally["g3"].values())
g4_fail = sum(tally["g4"].values())

print("\n" + "=" * 65)
print(f"GATE FAILURE SUMMARY  ({total} tokens with pair data)")
print("=" * 65)
print(f"  No pair data:       {tally['no_pair']}")
print(f"  Gate 1 (Safety):    {g1_fail}  {dict(sorted(tally['g1'].items(), key=lambda x:-x[1]))}")
print(f"  Gate 2 (Volume):    {g2_fail}  {dict(sorted(tally['g2'].items(), key=lambda x:-x[1]))}")
print(f"  Gate 3 (Momentum):  {g3_fail}  {dict(sorted(tally['g3'].items(), key=lambda x:-x[1]))}")
print(f"  Gate 4 (Mcap):      {g4_fail}  {dict(sorted(tally['g4'].items(), key=lambda x:-x[1]))}")
print(f"  Reached AI scorer:  {tally['ai_ready']}")
print()
if examples["g1"]:
    print("Gate 1 examples:", examples["g1"])
if examples["g2"]:
    print("Gate 2 examples:", examples["g2"])
if examples["g3"]:
    print("Gate 3 examples:", examples["g3"])
if examples["g4"]:
    print("Gate 4 examples:", examples["g4"])
print("=" * 65)
