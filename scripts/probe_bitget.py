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
    # 内部划转：逐页拉 USDC 全部记录（该接口必须带 coin）
    try:
        import datetime as dt
        rows, cursor, pages = [], None, 0
        while pages < 6:
            q = {"startTime": str(start), "endTime": str(now), "limit": "20", "coin": "USDC"}
            if cursor:
                q["idLessThan"] = cursor
            batch = L._get("/api/v2/spot/account/transferRecords", q, key, secret, passphrase)
            if not batch:
                break
            rows.extend(batch)
            cursor = batch[-1].get("transferId")
            pages += 1
            if len(batch) < 20:
                break
        print("[OK ] 内部划转 USDC 共 %d 条（%d 页）" % (len(rows), pages))
        types = {}
        for r in rows:
            k = "%s->%s" % (r.get("fromType"), r.get("toType"))
            types[k] = types.get(k, 0) + 1
        print("      方向分布：%s" % types)
        for r in rows:
            t = dt.datetime.fromtimestamp(int(r.get("ts") or 0) / 1000, dt.timezone(dt.timedelta(hours=8)))
            print("      %s %-5s %-16s %-10s->%-10s %s" % (t.strftime("%Y-%m-%d %H:%M"), r.get("coin"),
                  r.get("size"), r.get("fromType"), r.get("toType"), r.get("status")))
    except Exception as e:
        print("[ERR] 内部划转 USDC -> %s" % str(e)[:160])

    # 账户流水：统计业务类型分布，确认划转是否体现在流水里
    try:
        rows = L._get("/api/v2/spot/account/bills",
                      {"startTime": str(start), "endTime": str(now), "limit": "20"},
                      key, secret, passphrase)
        print("[OK ] 账户流水全量 -> %d 条" % len(rows))
        types = {}
        for r in rows:
            k = "%s/%s" % (r.get("groupType"), r.get("businessType"))
            types[k] = types.get(k, 0) + 1
        for k, v in sorted(types.items(), key=lambda x: -x[1]):
            print("      %-52s %d 笔" % (k, v))
    except Exception as e:
        print("[ERR] 账户流水全量 -> %s" % str(e)[:160])
    probe("/api/v2/spot/trade/fills", {"limit": "5"}, "成交记录（基准）", key, secret, passphrase)
    probe("/api/v2/earn/account/assets", {}, "理财持仓（基准）", key, secret, passphrase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
