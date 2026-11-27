#!/usr/bin/env python3
"""一次性探测 2：账户处于「统一账户模式」时，哪些只读接口可用。

背景：经典接口（/api/v2/spot/account/assets、/api/v2/mix/position/*）在统一账户模式下
返回 40085「您处于统一账户模式，暂不支持调用经典账户接口」。本脚本逐个试候选接口，
把 code/msg 打出来，用于改造每日同步脚本。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L  # noqa: E402

NOW = int(time.time() * 1000)

KEY = os.environ.get("BITGET_KEY")
SECRET = os.environ.get("BITGET_SECRET")
PASS = os.environ.get("BITGET_PASSPHRASE")

CANDIDATES = [
    ("流水EARN", "/api/v3/account/financial-records", {"category": "EARN", "startTime": "%d" % (NOW - 30*86400*1000), "endTime": "%d" % NOW, "limit": "100"}),
    ("流水MARGIN", "/api/v3/account/financial-records", {"category": "MARGIN", "startTime": "%d" % (NOW - 7*86400*1000), "endTime": "%d" % NOW, "limit": "50"}),
    ("理财assets", "/api/v3/earn/assets", {}),
    ("理财positions", "/api/v3/earn/positions", {}),
    ("理财order", "/api/v3/earn/order-list", {"limit": "100"}),
    ("理财hodl", "/api/v3/earn/hodl/positions", {}),
    ("理财poolx", "/api/v3/earn/poolx/positions", {}),
    ("理财launchpool", "/api/v3/earn/launchpool/positions", {}),
    ("理财staking-pos", "/api/v3/earn/staking/positions", {}),
    ("理财onchain-pos", "/api/v3/earn/onchain/positions", {}),
    ("账户all-assets", "/api/v3/account/all-assets", {}),
    ("账户balance", "/api/v3/account/balance", {}),
    ("账户asset-detail", "/api/v3/account/asset-detail", {}),
]


def main():
    for name, path, params in CANDIDATES:
        try:
            data = L._get(path, params, KEY, SECRET, PASS)
            print("\n[OK] %s %s %s" % (name, path, params))
            print("LEN=%d" % len(json.dumps(data, ensure_ascii=False)))
            print(json.dumps(data, ensure_ascii=False)[:5000])
        except Exception as e:  # noqa: BLE001
            print("\n[FAIL] %s %s %s → %s" % (name, path, params, e))


if __name__ == "__main__":
    main()
