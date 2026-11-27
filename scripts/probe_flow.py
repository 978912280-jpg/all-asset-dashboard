#!/usr/bin/env python3
"""一次性探测：统一账户下流水（账单）与充提记录的可用接口。

目标：确认 v3 financial-records 各 category 能覆盖哪些业务类型（生息/划转/划入美股/闪兑），
以及链上充提在 v3 下走哪个路径。
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L  # noqa: E402

KEY = os.environ.get("BITGET_KEY")
SECRET = os.environ.get("BITGET_SECRET")
PASS = os.environ.get("BITGET_PASSPHRASE")
NOW = int(time.time() * 1000)
START = NOW - 88 * 86400 * 1000


def pull(path, params):
    """翻页取尽（cursor 分页）。"""
    out, cursor, pages = [], None, 0
    while pages < 30:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        data = L._get(path, p, KEY, SECRET, PASS, timeout=20)
        lst = (data.get("list") if isinstance(data, dict) else data) or []
        out.extend(lst)
        cursor = (data.get("cursor") if isinstance(data, dict) else None)
        pages += 1
        if not lst or not cursor:
            break
        time.sleep(0.08)
    return out


def main():
    for cat in ("SPOT", "OTHER", "COIN-FUTURES", "USDT-FUTURES", "MARGIN"):
        try:
            rows = pull("/api/v3/account/financial-records",
                        {"category": cat, "startTime": str(START), "endTime": str(NOW), "limit": "100"})
        except Exception as e:  # noqa: BLE001
            print("\n[FAIL] 流水 %s → %s" % (cat, str(e)[:120]))
            continue
        types = Counter(str(r.get("type")) for r in rows)
        print("\n[OK] 流水 %s：%d 条" % (cat, len(rows)))
        print("  类型分布：%s" % dict(types))
        samples = {}
        for r in rows:
            samples.setdefault(str(r.get("type")), r)
        for t, r in list(samples.items())[:12]:
            print("  样例 %-38s %s" % (t, json.dumps(r, ensure_ascii=False)[:260]))

    for name, path in (("充值", "/api/v3/account/deposit-records"),
                       ("提现", "/api/v3/account/withdrawal-records"),
                       ("划转", "/api/v3/account/transfer-records"),
                       ("充提2", "/api/v3/account/deposit-withdraw-records")):
        for params in ({"startTime": str(START), "endTime": str(NOW), "limit": "20"}, {}):
            try:
                data = L._get(path, params, KEY, SECRET, PASS, timeout=20)
                print("\n[OK] %s %s %s\n%s" % (name, path, params, json.dumps(data, ensure_ascii=False)[:1500]))
                break
            except Exception as e:  # noqa: BLE001
                print("\n[FAIL] %s %s %s → %s" % (name, path, params, str(e)[:100]))


if __name__ == "__main__":
    main()
