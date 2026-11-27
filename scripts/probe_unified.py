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
    ("V3-现金宝持仓", "/api/v3/earn/cashplus/positions", {}),
    ("V3-链上精选资产", "/api/v3/earn/elite-assets", {}),
    ("V3-理财资产A", "/api/v3/earn/assets", {}),
    ("V3-理财资产B", "/api/v3/earn/account/positions", {}),
    ("V3-理财资产C", "/api/v3/earn/savings/assets", {}),
    ("V3-账户信息", "/api/v3/account/info", {}),
    ("V3-资金账户(无参数)", "/api/v3/account/funding-assets", {}),
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
