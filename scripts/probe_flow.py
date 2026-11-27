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
    for name, path in (("充值", "/api/v3/account/deposit-records"),
                       ("提现", "/api/v3/account/withdrawal-records")):
        for days, params in ((30, {"startTime": str(NOW - 30*86400*1000), "endTime": str(NOW), "limit": "20"}),
                             (7, {"startTime": str(NOW - 7*86400*1000), "endTime": str(NOW), "limit": "20"})):
            try:
                data = L._get(path, params, KEY, SECRET, PASS, timeout=20)
                print("\n[OK] %s %s %dd\n%s" % (name, path, days, json.dumps(data, ensure_ascii=False)[:2000]))
            except Exception as e:  # noqa: BLE001
                print("\n[FAIL] %s %s %dd → %s" % (name, path, days, str(e)[:100]))


if __name__ == "__main__":
    main()
