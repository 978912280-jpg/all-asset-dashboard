#!/usr/bin/env python3
"""临时探针：验证 Bitget 钱包（充提/内部划转）记录接口是否在当前 Key 权限内。

只读，不修改任何数据文件。输出每个端点的 HTTP 状态、业务返回码与样例条数。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L


def probe(path, params, label, key, secret, passphrase):
    try:
        rows = L._get(path, params, key, secret, passphrase, timeout=20)
        print("[OK ] %-46s %s -> %d 条" % (label, path, len(rows)))
        if isinstance(rows, dict):
            keys = list(rows.keys())[:6]
            print("      字段：%s" % ", ".join(keys))
            rows = rows.get("rows") or rows.get("data") or []
        for r in (rows or [])[:2]:
            keep = {}
            for k in ("coin", "type", "amount", "status", "cTime", "uTime",
                      "fromType", "toType", "transferType", "depositType",
                      "chain", "txId", "clientOid", "bizType"):
                if k in r:
                    keep[k] = r[k]
            print("      样例：%s" % json.dumps(keep, ensure_ascii=False)[:220])
        return True
    except Exception as e:
        msg = str(e)
        print("[ERR] %-46s %s -> %s" % (label, path, msg[:160]))
        return False


def main():
    key = os.environ.get("BITGET_KEY")
    secret = os.environ.get("BITGET_SECRET")
    passphrase = os.environ.get("BITGET_PASSPHRASE")
    if not (key and secret and passphrase):
        print("缺少密钥环境变量，跳过")
        return 0
    print("Bitget 钱包接口探针  key 尾号：%s" % key[-4:])

    probe("/api/v2/spot/account/assets", {}, "现货账户（基准）", key, secret, passphrase)
    probe("/api/v2/spot/wallet/deposit-records",
          {"startTime": "1700000000000", "endTime": "1800000000000", "limit": "20"},
          "充值记录", key, secret, passphrase)
    probe("/api/v2/spot/wallet/withdrawal-records",
          {"startTime": "1700000000000", "endTime": "1800000000000", "limit": "20"},
          "提现记录", key, secret, passphrase)
    probe("/api/v2/spot/wallet/transfer-records",
          {"startTime": "1700000000000", "endTime": "1800000000000", "limit": "20"},
          "内部划转记录", key, secret, passphrase)
    probe("/api/v2/spot/account/bills",
          {"startTime": "1700000000000", "endTime": "1800000000000", "limit": "20"},
          "账户流水 bills", key, secret, passphrase)
    probe("/api/v2/spot/trade/fills", {"limit": "5"}, "成交记录（基准）", key, secret, passphrase)
    probe("/api/v2/earn/account/assets", {}, "理财持仓（基准）", key, secret, passphrase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
