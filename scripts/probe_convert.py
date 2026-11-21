#!/usr/bin/env python3
"""一次性探测脚本：确认 Bitget「闪兑 / Convert」是否会同时出现在 /fills 成交接口。

用途：判断「奖励币闪兑回 BTC/SOL」这条路，成本账本应按「0 成本增发」处理，
还是按「按市价计入成本」处理，避免两条路径重复记成本。
输出全部打到 stdout（GitHub Actions 日志）。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L  # noqa: E402

CST = timezone(timedelta(hours=8))
KEY = os.environ.get("BITGET_KEY")
SECRET = os.environ.get("BITGET_SECRET")
PASS = os.environ.get("BITGET_PASSPHRASE")


def get(path, params):
    return L._get(path, params, KEY, SECRET, PASS)


def ms(dt):
    return str(int(dt.timestamp() * 1000))


def main():
    now = datetime.now(CST)
    days = int(os.environ.get("PROBE_DAYS") or 45)
    start = now - timedelta(days=days)
    print("=== 探测窗口：%s ~ %s（%d 天）===" % (start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), days))

    # 1) 成交
    fills = L.fetch_fills(KEY, SECRET, PASS, int(start.timestamp() * 1000), log=lambda *a: None)
    print("\n[1] /fills 成交笔数：%d" % len(fills))
    syms = {}
    for f in fills:
        syms[f.get("symbol")] = syms.get(f.get("symbol"), 0) + 1
    print("    币对分布：%s" % json.dumps(syms, ensure_ascii=False))
    print("    fills 字段示例：%s" % json.dumps(fills[-1] if fills else {}, ensure_ascii=False)[:600])

    # 2) 账单（含闪兑/派息/划转），按 5 天切片翻页，字段用 businessType/groupType
    bills = []
    cur = int(start.timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    while cur < end:
        nxt = min(cur + 5 * 86400 * 1000, end)
        cursor, pages = None, 0
        while pages < 20:
            p = {"startTime": str(cur), "endTime": str(nxt), "limit": "100"}
            if cursor:
                p["idLessThan"] = cursor
            rows = get("/api/v2/spot/account/bills", p)
            if not rows:
                break
            bills.extend(rows)
            cursor = rows[-1].get("billId")
            pages += 1
            if len(rows) < 100:
                break
        cur = nxt
    seen = set()
    uniq = []
    for b in bills:
        bid = b.get("billId")
        if bid in seen:
            continue
        seen.add(bid)
        uniq.append(b)
    bills = uniq
    print("\n[2] /bills 账单条数：%d（已去重）" % len(bills))
    print("    单条原始字段：%s" % json.dumps(bills[-1] if bills else {}, ensure_ascii=False)[:600])
    biz = {}
    for b in bills:
        key = "%s/%s" % (b.get("businessType"), b.get("groupType"))
        biz[key] = biz.get(key, 0) + 1
    print("    businessType 分布：")
    for k, v in sorted(biz.items(), key=lambda x: -x[1])[:20]:
        print("      %-42s %d" % (k, v))

    # 3) 闪兑账单 vs /fills 镜像（含新版 CONVERT 通道）
    conv = [b for b in bills if str(b.get("businessType") or "").upper().startswith(("SMALL_EXCHANGE", "CONVERT"))]
    print("\n[3] 闪兑（SMALL_EXCHANGE / CONVERT）账单 %d 条，示例 12 条：" % len(conv))
    for b in sorted(conv, key=lambda x: int(x.get("cTime") or 0), reverse=True)[:12]:
        print("      " + json.dumps(b, ensure_ascii=False)[:480])

    fill_order_ids = set(str(f.get("orderId")) for f in fills)
    matched = [b for b in conv if str(b.get("orderId") or "") in fill_order_ids]
    print("    闪兑账单 orderId 命中 /fills：%d / %d" % (len(matched), len(conv)))

    print("\n[4] 每笔闪兑 120 秒内是否有同币种成交（判断是否走现货撮合）：")
    hit = 0
    for b in sorted(conv, key=lambda x: int(x.get("cTime") or 0), reverse=True)[:10]:
        ct = int(b.get("cTime") or 0)
        coin = str(b.get("coin") or "").upper()
        near = [f for f in fills if abs(int(f.get("cTime") or 0) - ct) <= 120000
                and coin and coin in str(f.get("symbol") or "")]
        if near:
            hit += 1
        print("      bill %s %s size=%s | 120s 内同币种成交 %d 笔" % (
            datetime.fromtimestamp(ct / 1000, CST).strftime("%m-%d %H:%M:%S"), coin, b.get("size"), len(near)))
        for f in near[:2]:
            print("         fill %s %s size=%s price=%s" % (f.get("symbol"), f.get("side"), f.get("size"), f.get("priceAvg")))
    print("    闪兑与现货成交重叠：%d / %d" % (hit, min(10, len(conv))))

    # 5) 派息/奖励/划转是否进入 /fills（预期恒为 0）
    earn_bills = [b for b in bills if "INTEREST" in str(b.get("businessType") or "").upper()
                  or str(b.get("businessType") or "").upper().startswith(("AIRDROP", "TRANSFER", "STOCK_"))]
    print("\n[5] 派息/奖励/划转类账单 %d 条，orderId 命中 /fills 的 %d 条" % (
        len(earn_bills), len([b for b in earn_bills if str(b.get("orderId") or "") in fill_order_ids])))

    # 6) 门类清单：fills 里出现过的币对，与账单里出现过的币，能否对应
    bill_coins = {}
    for b in bills:
        c = str(b.get("coin") or "").upper()
        bill_coins[c] = bill_coins.get(c, 0) + 1
    print("\n[6] 账单涉及币种：%s" % json.dumps(bill_coins, ensure_ascii=False)[:600])

    # 7) 美股账户入金口径对账：STOCK_* 账单 + 各币划转记录
    stock_bills = [b for b in bills if "STOCK" in str(b.get("businessType") or "").upper()]
    print("\n[7] STOCK_* 账单 %d 条：" % len(stock_bills))
    for b in sorted(stock_bills, key=lambda x: int(x.get("cTime") or 0)):
        print("      %s %s size=%s %s" % (
            datetime.fromtimestamp(int(b.get("cTime") or 0) / 1000, CST).strftime("%Y-%m-%d %H:%M"),
            b.get("businessType"), b.get("size"), b.get("coin")))
    try:
        tot = sum(abs(float(b.get("size") or 0)) for b in stock_bills
                  if "DEPOSIT_OUT" in str(b.get("businessType") or "").upper())
        print("      划出到美股合计（DEPOSIT_OUT）：%.2f" % tot)
    except (TypeError, ValueError):
        pass
    try:
        tr_all = []
        for coin in ("USDC", "USDT", "BTC", "SOL", "BGB", "ETH", "USDGO", "XAUT"):
            rows = get("/api/v2/spot/account/transferRecords",
                       {"coin": coin, "startTime": str(int(start.timestamp() * 1000)),
                        "endTime": str(int(now.timestamp() * 1000)), "limit": "100"})
            for r in rows:
                tr_all.append((coin, r))
        print("\n      划转记录（全币种，%d 条）：" % len(tr_all))
        for coin, r in tr_all[:40]:
            print("      %s %s %s size=%s %s" % (
                datetime.fromtimestamp(int(r.get("tsTime") or r.get("cTime") or 0) / 1000, CST
                                       ).strftime("%Y-%m-%d %H:%M") if (r.get("tsTime") or r.get("cTime")) else "-",
                coin, r.get("fromType"), r.get("size") or r.get("amount"), r.get("toType")))
    except Exception as e:  # noqa: BLE001
        print("      划转记录读取失败：%s" % str(e)[:80])

    print("\n=== 探测结束 ===")


if __name__ == "__main__":
    main()
