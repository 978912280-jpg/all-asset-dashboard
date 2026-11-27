import json, os, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L
CST = timezone(timedelta(hours=8))
KEY, SECRET, PASS = os.environ["BITGET_KEY"], os.environ["BITGET_SECRET"], os.environ["BITGET_PASSPHRASE"]
now = int(time.time() * 1000)

print("=== current-position raw ===")
for cat in ("COIN-FUTURES", "USDT-FUTURES"):
    try:
        d = L._get("/api/v3/position/current-position", {"category": cat}, KEY, SECRET, PASS, timeout=20)
        print(cat, json.dumps(d.get("list") if isinstance(d, dict) else d, ensure_ascii=False)[:3000])
    except Exception as e:
        print(cat, "FAIL", str(e)[:150])

print("\n=== financial-records COIN-FUTURES last 3 days ===")
cur = now - 3 * 86400000
while cur < now:
    nxt = min(cur + 86400000, now)
    try:
        d = L._get("/api/v3/account/financial-records",
                   {"category": "COIN-FUTURES", "startTime": str(cur), "endTime": str(nxt), "limit": "100"},
                   KEY, SECRET, PASS, timeout=25)
        rows = (d.get("list") if isinstance(d, dict) else None) or []
        print(datetime.fromtimestamp(cur / 1000, CST).strftime("%m-%d"), len(rows))
        for r in rows:
            print("   ", json.dumps(r, ensure_ascii=False))
    except Exception as e:
        print(datetime.fromtimestamp(cur / 1000, CST).strftime("%m-%d"), "FAIL", str(e)[:150])
    cur = nxt

print("\n=== position history endpoints ===")
for path, params in (
    ("/api/v3/position/history-position", {"category": "COIN-FUTURES", "startTime": str(now - 3 * 86400000), "endTime": str(now)}),
    ("/api/v3/position/position-history", {"category": "COIN-FUTURES"}),
):
    try:
        d = L._get(path, params, KEY, SECRET, PASS, timeout=20)
        print(path, json.dumps(d, ensure_ascii=False)[:2000])
    except Exception as e:
        print(path, "FAIL", str(e)[:150])
