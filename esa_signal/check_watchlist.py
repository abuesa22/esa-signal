import sqlite3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect("esa_signal.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM graduation_watchlist ORDER BY volume_peak DESC")
rows = c.fetchall()
print(f"Graduation watchlist: {len(rows)} tokens")
for r in rows:
    d = dict(r)
    print(f"  {d['ticker']} | vol=${d['volume_peak']:,.0f} | graduated={d['graduated']} | {d['token_address'][:20]}...")
conn.close()
