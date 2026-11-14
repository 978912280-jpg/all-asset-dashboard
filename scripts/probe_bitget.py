#!/usr/bin/env python3
"""临时探针：验证 Bitget 钱包（充提/内部划转）记录接口是否在当前 Key 权限内。

只读，不修改任何数据文件。输出每个端点的 HTTP 状态、业务返回码与样例条数。
"""
import json, os, sys, time

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
        for r in (rows or [])[:3]:
            print("      样例：%s" % json.dumps(r, ensure_ascii=False)[:300])
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

    now = int(time.time() * 1000)
    start = now - 85 * 86400 * 1000
    rng = {"startTime": str(start), "endTime": str(now), "limit": "20"}
    probe("/api/v2/spot/account/assets", {}, "现货账户（基准）", key, secret, passphrase)
    probe("/api/v2/spot/wallet/deposit-records", dict(rng, coin="USDC"), "充值记录 USDC", key, secret, passphrase)
    probe("/api/v2/spot/wallet/withdrawal-records", dict(rng, coin="USDC"), "提现记录 USDC", key, secret, passphrase)
    probe("/api/v2/spot/account/bills", dict(rng, coin="USDC"), "账户流水 bills USDC", key, secret, passphrase)
    for path, label in [
        ("/api/v2/spot/wallet/transfer-records", "内部划转 A"),
        ("/api/v2/spot/account/transfer-records", "内部划转 B"),
        ("/api/v2/spot/account/transferRecords", "内部划转 C"),
        ("/api/v2/spot/wallet/transfer-record", "内部划转 D"),
    ]:
        probe(path, dict(rng, coin="USDC"), label, key, secret, passphrase)
    probe("/api/v2/spot/trade/fills", {"limit": "5"}, "成交记录（基准）", key, secret, passphrase)
    probe("/api/v2/earn/account/assets", {}, "理财持仓（基准）", key, secret, passphrase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
