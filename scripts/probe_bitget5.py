#!/usr/bin/env python3
"""临时探针 v5：回溯全部历史链上充提（90 天窗口切片），核对 net_deposit=15065。"""
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


def tms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=CST).timestamp() * 1000)


def pull(path, start, end, key, secret, passphrase):
    out, cursor, pages = [], None, 0
    while pages < 12:
        q = {"startTime": str(start), "endTime": str(end), "limit": "20"}
        if cursor:
            q["idLessThan"] = cursor
        try:
            batch = L._get(path, q, key, secret, passphrase, timeout=20)
        except Exception as e:
            print("      [ERR] %s %s~%s %s" % (path.split("/")[-1], fmt(start), fmt(end), str(e)[:90]))
            break
        if not batch:
            break
        out.extend(batch)
        cursor = batch[-1].get("orderId") or batch[-1].get("id")
        pages += 1
        time.sleep(0.15)
        if len(batch) < 20:
            break
    return out


def main():
    key, secret, passphrase = (os.environ.get("BITGET_KEY"), os.environ.get("BITGET_SECRET"),
                               os.environ.get("BITGET_PASSPHRASE"))
    if not (key and secret and passphrase):
        print("缺少密钥")
        return 0

    now = int(time.time() * 1000)
    dep, wd = [], []
    cur = now
    floor = tms(2023, 1, 1)
    windows = 0
    while cur > floor:
        start = max(cur - 88 * 86400 * 1000, floor)
        d = pull("/api/v2/spot/wallet/deposit-records", start, cur, key, secret, passphrase)
        w = pull("/api/v2/spot/wallet/withdrawal-records", start, cur, key, secret, passphrase)
        dep.extend(d)
        wd.extend(w)
        windows += 1
        print("  窗口 %s ~ %s：充值 %d，提现 %d" % (fmt(start)[:10], fmt(cur)[:10], len(d), len(w)))
        cur = start

    dep = {r.get("orderId") or r.get("tradeId"): r for r in dep}.values()
    wd = {r.get("orderId") or r.get("tradeId"): r for r in wd}.values()
    print("[OK ] 去重后 充值 %d 笔 / 提现 %d 笔（%d 个窗口）" % (len(dep), len(wd), windows))

    def agg(rows, label, sign):
        per = {}
        print("  %s 明细：" % label)
        for r in sorted(rows, key=lambda x: int(x.get("cTime") or 0)):
            coin = r.get("coin")
            size = float(r.get("size") or 0)
            per[coin] = per.get(coin, 0) + size
            print("    %s %-5s %+16.6f  %-10s %s" % (
                fmt(r.get("cTime")), coin, sign * size,
                r.get("status"), (r.get("chain") or r.get("dest") or "")))
        for c, v in sorted(per.items()):
            print("  %s 合计 %-5s %+.6f" % (label, c, sign * v))
        return per

    dep_per = agg(dep, "充值", 1)
    wd_per = agg(wd, "提现", -1)

    print("  ── 净流入（按币种） ──")
    coins = set(dep_per) | set(wd_per)
    total = 0.0
    for c in sorted(coins):
        v = dep_per.get(c, 0) - wd_per.get(c, 0)
        print("    %-5s %+14.6f" % (c, v))
        if c in ("USDT", "USDC", "DAI"):
            total += v
    print("  ── 稳定币净流入合计 ≈ %.2f USDT ──" % total)
    print("  校准口径 net_deposit_usdt = 15065.00 → 差异 %.2f" % (total - 15065.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
