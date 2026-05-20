"""Check raw EDGAR and Finnhub responses."""
import sys
import requests
import json
from datetime import date, timedelta
sys.path.insert(0, ".")
import config  # noqa: E402

# ── 1. EDGAR RSS raw titles ───────────────────────────────────────────────────
print("=== EDGAR RSS feed (raw entry titles) ===")
import xml.etree.ElementTree as ET  # noqa: E402
headers = {"User-Agent": "ESA Signal Bot contact@esasignal.local"}
r = requests.get(
    "https://www.sec.gov/cgi-bin/browse-edgar",
    headers=headers,
    params={"action": "getcurrent", "type": "S-1", "owner": "include", "count": "5", "output": "atom"},
    timeout=15,
)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.text)
    for i, entry in enumerate(root.findall("a:entry", ns)[:5]):
        title_el = entry.find("a:title", ns)
        updated_el = entry.find("a:updated", ns)
        link_el = entry.find("a:link", ns)
        company_el = entry.find("a:company-name", ns)   # may not exist
        print(f"\n  Entry {i+1}:")
        print(f"    title:   {repr(title_el.text)}")
        updated_txt = updated_el.text if updated_el is not None else None
        print(f"    updated: {repr(updated_txt)}")
        link_href = link_el.get('href', '') if link_el is not None else None
        print(f"    link:    {link_href}")
        # Show all child tags
        for child in entry:
            tag = child.tag.split("}")[-1]
            if tag not in ("title", "updated", "link", "id", "content", "summary"):
                print(f"    {tag}: {child.text!r}")

# ── 2. EDGAR EFTS with correct User-Agent ─────────────────────────────────────
print("\n\n=== EDGAR EFTS search (JSON) ===")
today = date.today()
week_ago = (today - timedelta(days=7)).isoformat()
r2 = requests.get(
    "https://efts.sec.gov/LATEST/search-index",
    headers=headers,
    params={"q": "", "forms": "S-1", "dateRange": "custom",
            "startdt": week_ago, "enddt": today.isoformat()},
    timeout=15,
)
print(f"Status: {r2.status_code}")
if r2.status_code == 200:
    d = r2.json()
    hits = d.get("hits", {}).get("hits", [])
    print(f"Hits: {len(hits)}")
    if hits:
        print(f"  First hit _source keys: {list(hits[0].get('_source', {}).keys())}")
        print(f"  First hit: {json.dumps(hits[0].get('_source', {}), indent=4)[:500]}")
else:
    print(f"Body: {r2.text[:300]}")

# ── 3. Finnhub earnings raw ───────────────────────────────────────────────────
print("\n\n=== Finnhub earnings calendar (raw) ===")
fh_headers = {"X-Finnhub-Token": config.FINNHUB_API_KEY}
today_s = date.today().isoformat()
end_s = (date.today() + timedelta(days=7)).isoformat()
r3 = requests.get(
    "https://finnhub.io/api/v1/calendar/earnings",
    headers=fh_headers,
    params={"from": today_s, "to": end_s},
    timeout=15,
)
print(f"Status: {r3.status_code}")
if r3.status_code == 200:
    d3 = r3.json()
    entries = d3.get("earningsCalendar", [])[:5]
    print(f"Entries: {len(entries)}")
    for e in entries:
        print(f"  {json.dumps(e)}")
else:
    print(f"Body: {r3.text[:300]}")
