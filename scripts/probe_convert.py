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

    # 2) 账单（含闪兑/派息/划转）
    bills = []
    cursor = None
    pages = 0
    while pages < 20:
        p = {"limit": "100", "startTime": ms(start), "endTime": ms(now)}
        if cursor:
            p["idLessThan"] = cursor
        rows = get("/api/v2/spot/account/bills", p)
        if not rows:
            break
        bills.extend(rows)
        cursor = rows[-1].get("billId") or rows[-1].get("id")
        pages += 1
        if len(rows) < 100:
            break
    print("\n[2] /bills 账单条数：%d" % len(bills))
    biz = {}
    for b in bills:
        key = "%s/%s" % (b.get("bizType"), b.get("bizTypeDesc") or "")
        biz[key] = biz.get(key, 0) + 1
    print("    bizType 分布：")
    for k, v in sorted(biz.items(), key=lambda x: -x[1])[:20]:
        print("      %-40s %d" % (k, v))

    # 3) 闪兑 / convert 类账单，逐条看是否在 fills 里有镜像
    conv = [b for b in bills if "convert" in str(b.get("bizType")).lower()
            or "闪兑" in str(b.get("bizTypeDesc") or "")]
    print("\n[3] 闪兑类账单 %d 条（示例 6 条原始字段）：" % len(conv))
    for b in conv[:6]:
        print("      " + json.dumps(b, ensure_ascii=False)[:520])

    fill_order_ids = set(str(f.get("orderId")) for f in fills)
    fill_trade_ids = set(str(f.get("tradeId")) for f in fills)
    matched = 0
    for b in conv:
        oid = str(b.get("orderId") or b.get("relatedOrderId") or "")
        if oid and (oid in fill_order_ids or oid in fill_trade_ids):
            matched += 1
    print("    闪兑账单 orderId 命中 /fills 的条数：%d / %d" % (matched, len(conv)))

    # 4) 抽样：同一天的成交与账单时间对照，看看闪兑时刻有没有对应成交
    print("\n[4] 最近 3 笔闪兑时间点附近的成交（同币种）：")
    conv_recent = sorted(conv, key=lambda x: int(x.get("cTime") or 0), reverse=True)[:3]
    for b in conv_recent:
        ct = int(b.get("cTime") or 0)
        coin = str(b.get("coin") or "").upper()
        near = [f for f in fills if abs(int(f.get("cTime") or 0) - ct) <= 120000
                and coin and coin in str(f.get("symbol") or "")]
        print("      bill %s %s size=%s cTime=%s | 120s 内同币种成交 %d 笔" % (
            datetime.fromtimestamp(ct / 1000, CST).strftime("%Y-%m-%d %H:%M:%S"),
            coin, b.get("size"), ct, len(near)))
        for f in near[:3]:
            print("         fill %s %s size=%s price=%s orderId=%s" % (
                f.get("symbol"), f.get("side"), f.get("size"), f.get("priceAvg"), f.get("orderId")))

    # 5) 派息/划转是否出现在 fills（应恒为 0）
    print("\n[5] 派息/划转在 /fills 中的镜像：")
    print("    BATCH_INTEREST 类账单：%d 条；其中 orderId 命中 fills：%d" % (
        len([b for b in bills if "INTEREST" in str(b.get("bizType")).upper()]),
        len([b for b in bills if "INTEREST" in str(b.get("bizType")).upper()
             and str(b.get("orderId") or "") in fill_order_ids])))
    print("\n=== 探测结束 ===")


if __name__ == "__main__":
    main()
