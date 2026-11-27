#!/usr/bin/env python3
"""一次性探测：币本位永续合约（COIN-FUTURES）仓位与账户余额，以及现货 BTC 是否被划走。

目的：
  1) 确认能否通过 API 读到用户新开的 0.02 BTC 币本位多单；
  2) 确认开仓后现货账户 BTC 余额是否减少（保证金从现货划入合约账户）；
  3) 给出「仪表台要不要把合约账户里的 BTC 计入份额」的依据。
输出全部打到 stdout（GitHub Actions 日志）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L  # noqa: E402

KEY = os.environ.get("BITGET_KEY")
SECRET = os.environ.get("BITGET_SECRET")
PASS = os.environ.get("BITGET_PASSPHRASE")


def try_get(label, path, params):
    try:
        data = L._get(path, params, KEY, SECRET, PASS)
        print("\n[%s] OK  %s %s" % (label, path, params))
        print(json.dumps(data, ensure_ascii=False)[:3000])
        return data
    except Exception as e:  # noqa: BLE001
        print("\n[%s] FAIL %s %s → %s" % (label, path, params, e))
        return None


def main():
    print("=== 1) 现货账户资产（看 BTC 可用/冻结）===")
    assets = try_get("SPOT", "/api/v2/spot/account/assets", {}) or []
    for a in assets:
        coin = a.get("coin")
        if coin in ("BTC", "USDT", "USDC", "SOL"):
            print("   %-6s available=%s frozen=%s locked=%s" % (
                coin, a.get("available"), a.get("frozen"), a.get("locked")))

    print("\n=== 2) 合约账户（COIN-FUTURES / USDT-FUTURES）===")
    for ptype in ("COIN-FUTURES", "USDT-FUTURES"):
        try_get("ACCT-" + ptype, "/api/v2/mix/account/accounts", {"productType": ptype})

    print("\n=== 3) 持仓（全部 symbol）===")
    for ptype in ("COIN-FUTURES", "USDT-FUTURES"):
        pos = try_get("POS-" + ptype, "/api/v2/mix/position/all-position",
                      {"productType": ptype, "marginCoin": "BTC" if ptype == "COIN-FUTURES" else "USDT"})
        if isinstance(pos, list):
            for p in pos:
                print("   %s %s size=%s openPriceAvg=%s marginCoin=%s unrealized=%s leverage=%s" % (
                    p.get("symbol"), p.get("holdSide"), p.get("total"),
                    p.get("openPriceAvg"), p.get("marginCoin"), p.get("unrealizedPL"), p.get("leverage")))

    print("\n=== 4) 合约账单（最近 7 天，看保证金划转）===")
    import time
    end = int(time.time() * 1000)
    start = end - 7 * 86400 * 1000
    for ptype in ("COIN-FUTURES", "USDT-FUTURES"):
        rows = try_get("BILLS-" + ptype, "/api/v2/mix/account/bill",
                       {"productType": ptype, "startTime": str(start), "endTime": str(end), "limit": "50"}) or []
        for r in rows[:25]:
            print("   %s %s %s %s %s" % (r.get("bizType"), r.get("coin"), r.get("amount"),
                                         r.get("balance"), r.get("cTime")))

    print("\n=== 5) 现货账单里最近的 BTC 变动（确认是否划出）===")
    rows = try_get("SPOT-BILLS", "/api/v2/spot/account/bills",
                   {"startTime": str(start), "endTime": str(end), "limit": "100", "coin": "BTC"}) or []
    for r in rows[:25]:
        print("   %s %s %s %s %s" % (r.get("businessType"), r.get("coin"), r.get("amount"),
                                     r.get("balance"), r.get("cTime")))


if __name__ == "__main__":
    main()
