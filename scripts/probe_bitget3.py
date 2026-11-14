#!/usr/bin/env python3
"""临时探针 v3：分页拉满账单 + 试探股票账户/划转端点的其它路径。"""
import datetime as dt
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L

CST = dt.timezone(dt.timedelta(hours=8))


def fmt(ms):
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, CST).strftime("%m-%d %H:%M")
    except Exception:
        return str(ms)


def main():
    key, secret, passphrase = (os.environ.get("BITGET_KEY"), os.environ.get("BITGET_SECRET"),
                               os.environ.get("BITGET_PASSPHRASE"))
    if not (key and secret and passphrase):
        print("缺少密钥")
        return 0
    now = int(time.time() * 1000)
    start = now - 88 * 86400 * 1000
    print("账单窗口 %s ~ %s（近 88 天）" % (fmt(start), fmt(now)))

    # ---- 1. 账单分页拉满，统计全部业务类型 ----
    rows, cursor, pages = [], None, 0
    while pages < 30:
        q = {"startTime": str(start), "endTime": str(now), "limit": "20"}
        if cursor:
            q["idLessThan"] = cursor
        try:
            batch = L._get("/api/v2/spot/account/bills", q, key, secret, passphrase, timeout=20)
        except Exception as e:
            print("[ERR] bills 第 %d 页：%s" % (pages + 1, str(e)[:140]))
            break
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1].get("billId")
        pages += 1
        time.sleep(0.2)
        if len(batch) < 20:
            break
    print("[OK ] 账单共 %d 笔（%d 页）" % (len(rows), pages))
    agg = {}
    for r in rows:
        k = "%s/%s" % (r.get("groupType"), r.get("businessType"))
        d = agg.setdefault(k, {"n": 0, "coins": set(), "first": None, "last": None})
        d["n"] += 1
        d["coins"].add(r.get("coin"))
        t = int(r.get("cTime") or 0)
        d["first"] = t if not d["first"] else min(d["first"], t)
        d["last"] = t if not d["last"] else max(d["last"], t)
    for k, v in sorted(agg.items(), key=lambda x: -x[1]["n"]):
        print("      %-44s %3d 笔  %s~%s  %s" % (
            k, v["n"], fmt(v["first"]), fmt(v["last"]), ",".join(sorted(v["coins"]))))
    # 打印任何含 TRANSFER/STOCK/CONVERT/DEPOSIT 关键词的明细
    print("      含划转/股票关键词的明细：")
    hit = 0
    for r in rows:
        txt = ("%s%s%s" % (r.get("groupType"), r.get("businessType"), r.get("type"))).upper()
        if any(w in txt for w in ("TRANSFER", "STOCK", "CONVERT", "DEPOSIT", "WITHDRAW")):
            hit += 1
            if hit <= 15:
                print("      %s %-5s %-16s %s/%s %s" % (
                    fmt(r.get("cTime")), r.get("coin"), r.get("size"),
                    r.get("groupType"), r.get("businessType"), r.get("bizOrderId")))
    print("      命中 %d 笔" % hit)

    # ---- 2. 试探其它划转/股票端点 ----
    cand = [
        "/api/v2/spot/account/transferRecords",
        "/api/v2/account/transferRecords",
        "/api/v2/uta/account/transferRecords",
        "/api/v2/spot/wallet/transferRecords",
        "/api/v2/spot/wallet/transfer-records",
        "/api/v2/spot/account/transfer",
        "/api/v2/stocks/account/assets",
        "/api/v2/stock/account/assets",
        "/api/v2/spot/stock/assets",
        "/api/v2/spot/account/stocks",
    ]
    for path in cand:
        for params in ({"coin": "USDC", "startTime": str(start), "endTime": str(now), "limit": "20"},
                       {}):
            try:
                r = L._get(path, params, key, secret, passphrase, timeout=15)
                print("[OK ] %-42s 参数%-40s -> %s 条  样例=%s" % (
                    path, "有" if params else "无", len(r),
                    json.dumps(r[0], ensure_ascii=False)[:160] if r else "-"))
                break
            except Exception as e:
                msg = str(e)
                if "404" in msg:
                    print("[404] %s" % path)
                    break
                else:
                    print("[ERR] %-42s %s" % (path, msg[:110]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
