import sqlite3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

conn = sqlite3.connect("esa_signal.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Schema discovery
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

for tbl in tables:
    c.execute(f"PRAGMA table_info({tbl})")
    cols = [r[1] for r in c.fetchall()]
    print(f"  {tbl}: {cols}")

print()

# Signals
c.execute("SELECT * FROM signals ORDER BY rowid DESC LIMIT 10")
rows = c.fetchall()
print(f"=== SIGNALS (last 10) — {len(rows)} found ===")
for r in rows:
    d = dict(r)
    print(f"  #{d.get('id','?')} {d.get('ticker','?')} ({d.get('chain','?')}) | "
          f"score={d.get('ai_score','?')} {d.get('conviction','?')} | "
          f"mcap=${float(d.get('market_cap') or 0):,.0f} | "
          f"liq=${float(d.get('liquidity_usd') or 0):,.0f} | "
          f"{d.get('timestamp') or d.get('sent_at') or d.get('created_at','?')}")

# Scan activity
c.execute("SELECT COUNT(*) FROM scanned_tokens")
total = c.fetchone()[0]

c.execute("SELECT * FROM scanned_tokens ORDER BY rowid DESC LIMIT 1")
latest = c.fetchone()

print("\n=== SCAN ACTIVITY ===")
print(f"  Total tokens ever scanned: {total}")
if latest:
    d = dict(latest)
    print(f"  Most recent entry: {d}")

conn.close()
