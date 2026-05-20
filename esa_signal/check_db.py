import sqlite3
conn = sqlite3.connect("esa_signal.db")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
sigs = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
scans = conn.execute("SELECT COUNT(*) FROM scanned_tokens").fetchone()[0]
print(f"Signals sent: {sigs} | Tokens scanned so far: {scans}")
conn.close()
print("Database OK")
