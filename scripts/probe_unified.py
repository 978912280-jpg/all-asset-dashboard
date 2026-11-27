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
    ("可划转-现货到资金", "/api/v3/account/transferable-coins", {"fromType": "SPOT", "toType": "FUNDING", "coin": "SOL"}),
    ("可划转-现货到合约", "/api/v3/account/transferable-coins", {"fromType": "SPOT", "toType": "FUTURES", "coin": "SOL"}),
    ("可划转-资金到现货", "/api/v3/account/transferable-coins", {"fromType": "FUNDING", "toType": "SPOT", "coin": "SOL"}),
    ("可划转-理财到现货", "/api/v3/account/transferable-coins", {"fromType": "EARN", "toType": "SPOT", "coin": "SOL"}),
    ("可划转-现货到理财", "/api/v3/account/transferable-coins", {"fromType": "SPOT", "toType": "EARN", "coin": "SOL"}),
    ("可划转-不带币", "/api/v3/account/transferable-coins", {"fromType": "SPOT", "toType": "FUNDING"}),
    ("可划转-小写", "/api/v3/account/transferable-coins", {"fromAccountType": "spot", "toAccountType": "funding"}),
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
