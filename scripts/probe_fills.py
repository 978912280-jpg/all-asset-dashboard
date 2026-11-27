import json, os, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L
CST = timezone(timedelta(hours=8))
KEY, SECRET, PASS = os.environ["BITGET_KEY"], os.environ["BITGET_SECRET"], os.environ["BITGET_PASSPHRASE"]
start = datetime(2026, 11, 13, 12, 0, tzinfo=CST)
start_ms = int(start.timestamp() * 1000)
now = int(time.time() * 1000)
print("start", start_ms, "now", now, "span_days", (now - start_ms) / 86400000)
for win in (7, 3, 1):
    print("\n=== window %d days ===" % win)
    cur = start_ms
    while cur < now:
        nxt = min(cur + win * 86400000, now)
        for lim in ("50", "100"):
            try:
                rows = L._get("/api/v3/trade/fills", {"category": "SPOT", "startTime": str(cur), "endTime": str(nxt), "limit": lim}, KEY, SECRET, PASS, timeout=20)
                data = rows if isinstance(rows, list) else (rows.get("list") if isinstance(rows, dict) else []) or []
                print("  %s~%s lim=%s → %d 条" % (
                    datetime.fromtimestamp(cur / 1000, CST).strftime("%m-%d %H:%M"),
                    datetime.fromtimestamp(nxt / 1000, CST).strftime("%m-%d %H:%M"), lim, len(data)))
                break
            except Exception as e:
                print("  %s lim=%s → FAIL %s" % (datetime.fromtimestamp(cur / 1000, CST).strftime("%m-%d"), lim, str(e)[:120]))
        cur = nxt
        break
print("\n=== single call last 30 days limit 100 ===")
try:
    rows = L._get("/api/v3/trade/fills", {"category": "SPOT", "startTime": str(now - 30 * 86400000), "endTime": str(now), "limit": "100"}, KEY, SECRET, PASS, timeout=20)
    print(json.dumps(rows, ensure_ascii=False)[:600])
except Exception as e:
    print("FAIL", str(e)[:200])
