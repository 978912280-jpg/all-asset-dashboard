#!/usr/bin/env python3
"""一次性探测 2：账户处于「统一账户模式」时，哪些只读接口可用。

背景：经典接口（/api/v2/spot/account/assets、/api/v2/mix/position/*）在统一账户模式下
返回 40085「您处于统一账户模式，暂不支持调用经典账户接口」。本脚本逐个试候选接口，
把 code/msg 打出来，用于改造每日同步脚本。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L  # noqa: E402

KEY = os.environ.get("BITGET_KEY")
SECRET = os.environ.get("BITGET_SECRET")
PASS = os.environ.get("BITGET_PASSPHRASE")

CANDIDATES = [
    ("UTA-资产", "/api/v2/uta/account/assets", {}),
    ("UTA-账户设置", "/api/v2/uta/account/settings", {}),
    ("UTA-当前持仓", "/api/v2/uta/position/current-position", {}),
    ("UTA-当前持仓(币本位)", "/api/v2/uta/position/current-position", {"productType": "COIN-FUTURES"}),
    ("UTA-历史持仓", "/api/v2/uta/position/history-position", {"productType": "COIN-FUTURES"}),
    ("UTA-账单", "/api/v2/uta/account/bill", {"limit": "20"}),
    ("统一账户-全部余额", "/api/v2/account/all-account-balance", {}),
    ("统一账户-账户列表", "/api/v2/account/accounts", {}),
    ("统一账户-单账户", "/api/v2/account/account", {}),
    ("统一账户-当前持仓", "/api/v2/position/current-position", {}),
    ("统一账户-当前持仓(币本位)", "/api/v2/position/current-position", {"productType": "COIN-FUTURES"}),
    ("统一账户-历史持仓", "/api/v2/position/history-position", {"productType": "COIN-FUTURES"}),
    ("经典-现货资产", "/api/v2/spot/account/assets", {}),
    ("经典-币本位持仓", "/api/v2/mix/position/all-position", {"productType": "COIN-FUTURES", "marginCoin": "BTC"}),
    ("理财-资产", "/api/v2/earn/account/assets", {}),
    ("统一账户-账单", "/api/v2/account/bill", {"limit": "20"}),
    ("统一账户-流水", "/api/v2/account/bills", {"limit": "20"}),
]


def main():
    for name, path, params in CANDIDATES:
        try:
            data = L._get(path, params, KEY, SECRET, PASS)
            print("\n[OK] %s %s %s" % (name, path, params))
            print(json.dumps(data, ensure_ascii=False)[:2000])
        except Exception as e:  # noqa: BLE001
            print("\n[FAIL] %s %s %s → %s" % (name, path, params, e))


if __name__ == "__main__":
    main()
