#!/usr/bin/env python3
"""临时探针 v2：2026-10-01 起，遍历所有币种与账单类型，找 10/11 月入金。"""
import datetime as dt
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L

CST = dt.timezone(dt.timedelta(hours=8))


def ts_fmt(ms):
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, CST).strftime("%m-%d %H:%M")
    except Exception:
        return str(ms)


def show(label, rows, limit=40):
    print("[%-3s] %s -> %d 条" % ("OK" if rows is not None else "ERR", label, len(rows or [])))
    for r in (rows or [])[:limit]:
        t = ts_fmt(r.get("cTime") or r.get("ts") or r.get("uTime"))
        print("      %s %-6s %-18s %-24s %s" % (
            t, r.get("coin"), str(r.get("size") or r.get("amount") or "")[:18],
            "%s/%s" % (r.get("groupType"), r.get("businessType")) if r.get("groupType") else
            "%s->%s" % (r.get("fromType"), r.get("toType")),
            r.get("status") or ""))


def main():
    key, secret, passphrase = (os.environ.get("BITGET_KEY"), os.environ.get("BITGET_SECRET"),
                               os.environ.get("BITGET_PASSPHRASE"))
    if not (key and secret and passphrase):
        print("缺少密钥")
        return 0
    now = int(time.time() * 1000)
    start = int(dt.datetime(2026, 10, 1, tzinfo=CST).timestamp() * 1000)
    rng = {"startTime": str(start), "endTime": str(now), "limit": "20"}
    print("窗口 %s ~ %s" % (ts_fmt(start), ts_fmt(now)))

    def try_get(path, params, label):
        try:
            rows = L._get(path, params, key, secret, passphrase, timeout=20)
            show(label, rows)
            return rows
        except Exception as e:
            print("[ERR] %s -> %s" % (label, str(e)[:150]))
            return None

    try_get("/api/v2/spot/wallet/deposit-records", rng, "充值记录（全币种）")
    try_get("/api/v2/spot/wallet/withdrawal-records", rng, "提现记录（全币种）")

    bills = try_get("/api/v2/spot/account/bills", rng, "账户流水（全币种）")
    if bills:
        agg = {}
        for r in bills:
            k = "%s/%s" % (r.get("groupType"), r.get("businessType"))
            d = agg.setdefault(k, {"n": 0, "coins": set()})
            d["n"] += 1
            d["coins"].add(r.get("coin"))
        print("      流水类型汇总：")
        for k, v in sorted(agg.items(), key=lambda x: -x[1]["n"]):
            print("      %-46s %2d 笔  %s" % (k, v["n"], ",".join(sorted(v["coins"]))))

    for coin in ("USDC", "USDT", "BTC", "BGB", "SOL"):
        rows = try_get("/api/v2/spot/account/transferRecords",
                       dict(rng, coin=coin), "内部划转 %s" % coin)
        if rows:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
