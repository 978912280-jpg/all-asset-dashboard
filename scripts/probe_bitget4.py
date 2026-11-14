#!/usr/bin/env python3
"""临时探针 v4：按 5 天窗口细扫 USDC 账单，捞出所有 STOCK_* 类记录（美股账户划转）。"""
import datetime as dt
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L

CST = dt.timezone(dt.timedelta(hours=8))


def fmt(ms):
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, CST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)


def tms(y, m, d, h=0):
    return int(dt.datetime(y, m, d, h, tzinfo=CST).timestamp() * 1000)


def scan(key, secret, passphrase, coin, start, end, keep_kw):
    hits, cursor, pages = [], None, 0
    while pages < 20:
        q = {"coin": coin, "startTime": str(start), "endTime": str(end), "limit": "20"}
        if cursor:
            q["idLessThan"] = cursor
        try:
            batch = L._get("/api/v2/spot/account/bills", q, key, secret, passphrase, timeout=20)
        except Exception as e:
            print("      [ERR] %s %s~%s 第%d页 %s" % (coin, fmt(start), fmt(end), pages + 1, str(e)[:100]))
            break
        if not batch:
            break
        for r in batch:
            txt = ("%s%s" % (r.get("groupType") or "", r.get("businessType") or "")).upper()
            if any(k in txt for k in keep_kw):
                hits.append(r)
        cursor = batch[-1].get("billId")
        pages += 1
        time.sleep(0.15)
        if len(batch) < 20:
            break
    return hits, pages


def main():
    key, secret, passphrase = (os.environ.get("BITGET_KEY"), os.environ.get("BITGET_SECRET"),
                               os.environ.get("BITGET_PASSPHRASE"))
    if not (key and secret and passphrase):
        print("缺少密钥")
        return 0

    t0 = tms(2026, 9, 20)
    now = int(time.time() * 1000)
    print("扫描窗口：%s ~ 今天，按 5 天切片，币种 USDC，关键词 STOCK/TRANSFER" % fmt(t0))

    allhits, total_pages = [], 0
    cur = t0
    while cur < now:
        nxt = min(cur + 5 * 86400 * 1000, now)
        hits, pages = scan(key, secret, passphrase, "USDC", cur, nxt, ("STOCK", "TRANSFER"))
        total_pages += pages
        allhits.extend(hits)
        print("  %s ~ %s：%d 页，命中 %d" % (fmt(cur)[5:10], fmt(nxt)[5:10], pages, len(hits)))
        cur = nxt

    print("[OK ] 共 %d 页，命中 %d 笔 STOCK/TRANSFER 类记录" % (total_pages, len(allhits)))
    for r in sorted(allhits, key=lambda x: int(x.get("cTime") or 0)):
        print("      %s  %-5s %-16s  %-34s 订单=%s" % (
            fmt(r.get("cTime")), r.get("coin"), r.get("size"),
            ("%s/%s" % (r.get("groupType"), r.get("businessType"))).strip("/"),
            r.get("bizOrderId")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
