#!/usr/bin/env python3
"""Bitget 流水归档：交易 / 理财生息 / 出入金 / 内部划转。

数据来源全部是 Bitget 只读接口：
  - /api/v2/spot/trade/fills              成交（交易记录）
  - /api/v2/spot/account/bills            账户账单（生息、划转、闪兑、空投）
  - /api/v2/spot/wallet/deposit-records    链上充值（外部入金）
  - /api/v2/spot/wallet/withdrawal-records 链上提现（外部出金）
  - /api/v2/spot/account/transferRecords   内部划转（须带 coin）

输出 data/crypto_events.json，同时刷新 data/crypto_cost.json 里的净入金基准块。
需要环境变量 BITGET_KEY / BITGET_SECRET / BITGET_PASSPHRASE。
"""

import json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bitget_ledger as L

CST = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EVENTS = DATA / "crypto_events.json"
COST = DATA / "crypto_cost.json"
DASH = DATA / "dashboard.json"

WINDOW_DAYS = 88          # 与 Bitget 90 天查询上限保持余量
SLICE_DAYS = 5            # 账单切片，避开「每页 20 条 + 翻页上限」
BASELINE_USDT = 15065.0        # 加密账户口径（已扣除划往美股账户的部分，用于收益率分母）
BASELINE_TOTAL_USDT = 17296.0  # 转入 Bitget 总额口径（含已划入美股账户）
BASELINE_DATE = "2026-11-13"

STABLE = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDG", "USDGO", "USDP", "PYUSD"}


def ts(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n > 1e14:      # 微秒
        n /= 1000
    if n > 1e11:      # 毫秒
        n /= 1000
    return datetime.fromtimestamp(n, CST)


def dstr(v, fmt="%Y-%m-%d %H:%M"):
    t = ts(v)
    return t.strftime(fmt) if t else ""


def day(v):
    t = ts(v)
    return t.strftime("%Y-%m-%d") if t else ""


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def load_prices():
    """用仪表台当前价格给流水里的非稳定币估值（USDT 计价）。"""
    prices = {}
    try:
        items = json.loads(DASH.read_text(encoding="utf-8")).get("items") or []
        for it in items:
            sym = str(it.get("symbol") or it.get("id") or "").upper()
            p = it.get("price")
            if sym and p:
                prices[sym] = float(p)
    except (ValueError, OSError):
        pass
    for s in STABLE:
        prices.setdefault(s, 1.0)
    return prices


def value_usdt(coin, qty, prices):
    """按 USDT 估值；稳定币/美元锚定奖励币按 1:1，其他无行情币返回 None（页面显示「—」）。"""
    c = str(coin or "").upper()
    if c in STABLE:
        return round(qty, 6)
    p = prices.get(c)
    if not p:
        return None
    return round(qty * p, 6)


def pull_bills(key, secret, passphrase, start_ms, end_ms, log=print):
    """账单按 5 天切片，每片翻页直到取尽。"""
    out, cur = [], start_ms
    while cur < end_ms:
        nxt = min(cur + SLICE_DAYS * 86400 * 1000, end_ms)
        cursor, pages = None, 0
        while pages < 20:
            params = {"startTime": str(cur), "endTime": str(nxt), "limit": "20"}
            if cursor:
                params["idLessThan"] = cursor
            try:
                rows = L._get("/api/v2/spot/account/bills", params, key, secret, passphrase, timeout=20)
            except Exception as e:
                log("      [warn] bills %s~%s：%s" % (dstr(cur, "%m-%d"), dstr(nxt, "%m-%d"), str(e)[:90]))
                break
            if not rows:
                break
            out.extend(rows)
            cursor = rows[-1].get("billId")
            pages += 1
            time.sleep(0.12)
            if len(rows) < 20:
                break
        cur = nxt
    seen, uniq = set(), []
    for r in out:
        bid = r.get("billId")
        if bid in seen:
            continue
        seen.add(bid)
        uniq.append(r)
    log("      账单：%d 笔（已去重）" % len(uniq))
    return uniq


def pull_records(path, key, secret, passphrase, start_ms, end_ms, log=print):
    """充提记录：按 88 天窗口翻页。"""
    out, cursor, pages = [], None, 0
    while pages < 20:
        params = {"startTime": str(start_ms), "endTime": str(end_ms), "limit": "20"}
        if cursor:
            params["idLessThan"] = cursor
        try:
            rows = L._get(path, params, key, secret, passphrase, timeout=20)
        except Exception as e:
            log("      [warn] %s：%s" % (path.split("/")[-1], str(e)[:90]))
            break
        if not rows:
            break
        out.extend(rows)
        cursor = rows[-1].get("orderId") or rows[-1].get("id")
        pages += 1
        time.sleep(0.12)
        if len(rows) < 20:
            break
    return out


def pull_transfers(key, secret, passphrase, start_ms, end_ms, coins, log=print):
    out = []
    for coin in coins:
        cursor, pages = None, 0
        while pages < 6:
            params = {"coin": coin, "startTime": str(start_ms), "endTime": str(end_ms), "limit": "20"}
            if cursor:
                params["idLessThan"] = cursor
            try:
                rows = L._get("/api/v2/spot/account/transferRecords", params,
                              key, secret, passphrase, timeout=20)
            except Exception as e:
                log("      [warn] 划转 %s：%s" % (coin, str(e)[:80]))
                break
            if not rows:
                break
            out.extend(rows)
            cursor = rows[-1].get("transferId")
            pages += 1
            if len(rows) < 20:
                break
            time.sleep(0.12)
    log("      内部划转：%d 笔" % len(out))
    return out


def classify_bill(r):
    """账单业务类型 → (板块, 子类型)。返回 None 表示忽略。"""
    bt = str(r.get("businessType") or "").upper()
    gt = str(r.get("groupType") or "").upper()
    if bt in ("BUY", "SELL"):
        return ("trade_bill", bt)
    if bt == "DEDUCTION_HANDLING_FEE":
        return None
    if bt in ("BATCH_INTEREST_USER_IN", "LOCK_INTEREST_USER_IN", "SINGLE_USER_OUT_LOOP"):
        return ("earn", "理财派息" if bt == "BATCH_INTEREST_USER_IN" else "锁仓收益")
    if bt.startswith("AIRDROP"):
        return ("earn", "活动奖励")
    if bt == "STOCK_USER_DEPOSIT_OUT":
        return ("transfer", "划入美股账户")
    if bt.startswith("STOCK_"):
        return ("transfer", "美股账户划出")
    if gt == "TRANSFER" or bt.startswith("TRANSFER_"):
        return ("transfer", "账户间划转")
    if bt.startswith("SMALL_EXCHANGE"):
        return ("trade_bill", "闪兑")
    if gt == "TRANSACTION" and bt in ("SINGLE_RELEASE_USER_IN", "SINGLE_USER_OUT"):
        return None
    return None


def main():
    key = os.environ.get("BITGET_KEY")
    secret = os.environ.get("BITGET_SECRET")
    passphrase = os.environ.get("BITGET_PASSPHRASE")
    if not (key and secret and passphrase):
        print("缺少 Bitget 密钥环境变量，跳过流水归档")
        return 0

    now = int(time.time() * 1000)
    start = now - WINDOW_DAYS * 86400 * 1000
    prices = load_prices()

    print("Bitget 流水归档：%s ~ %s" % (dstr(start, "%Y-%m-%d"), dstr(now, "%Y-%m-%d")))

    # ---- 成交（交易记录） ----
    try:
        fills = L.fetch_fills(key, secret, passphrase, start, log=lambda *a: None)
    except Exception as e:
        print("      [warn] 成交接口失败：%s" % str(e)[:90])
        fills = []
    trades = []
    for f in fills:
        sym = str(f.get("symbol") or "")
        coin = sym.replace("USDT", "").replace("USDC", "")
        side = "买入" if str(f.get("side")).lower() == "buy" else "卖出"
        fd = f.get("feeDetail") or {}
        trades.append({
            "date": dstr(f.get("cTime")),
            "date_day": day(f.get("cTime")),
            "coin": coin,
            "side": side,
            "qty": num(f.get("size")),
            "price": num(f.get("priceAvg")),
            "quote_usdt": round(num(f.get("amount")), 4),
            "fee": ("%s %s" % (fd.get("feeCoin") or "", num(f.get("totalFee") or fd.get("totalFee")))),
            "symbol": sym,
            "ref": f.get("tradeId") or f.get("orderId"),
        })
    print("      成交：%d 笔" % len(trades))

    # ---- 账单（生息 / 划转 / 闪兑 / 空投） ----
    bills = pull_bills(key, secret, passphrase, start, now)
    earn, transfers, misc_trades = [], [], []
    for r in bills:
        kind = classify_bill(r)
        if not kind:
            continue
        board, sub = kind
        coin = str(r.get("coin") or "").upper()
        qty = num(r.get("size"))
        if board == "earn":
            earn.append({"day": day(r.get("cTime")), "coin": coin,
                         "qty": qty, "value_usdt": value_usdt(coin, qty, prices)})
        elif board == "transfer":
            _v = value_usdt(coin, qty, prices)
            transfers.append({
                "date": dstr(r.get("cTime")), "day": day(r.get("cTime")),
                "coin": coin, "qty": abs(qty), "value_usdt": None if _v is None else abs(_v),
                "kind": sub, "ref": r.get("bizOrderId") or r.get("billId"),
            })
        elif board == "trade_bill" and sub == "闪兑":
            misc_trades.append({
                "date": dstr(r.get("cTime")), "coin": coin, "qty": qty,
                "value_usdt": value_usdt(coin, qty, prices),
                "kind": "闪兑", "ref": r.get("bizOrderId") or r.get("billId"),
            })

    # 生息按「日 + 币 + 类型」聚合，页面只吃日汇总
    agg = {}
    for e in earn:
        k = (e["day"], e["coin"])
        a = agg.setdefault(k, {"day": e["day"], "coin": e["coin"], "qty": 0.0,
                               "value_usdt": None, "count": 0})
        a["qty"] += e["qty"]
        if e["value_usdt"] is not None:
            a["value_usdt"] = (a["value_usdt"] or 0.0) + e["value_usdt"]
        a["count"] += 1
    earn_daily = sorted(agg.values(), key=lambda x: (x["day"], x["coin"]), reverse=True)

    # ---- 出入金（链上充提） ----
    deps = pull_records("/api/v2/spot/wallet/deposit-records", key, secret, passphrase, start, now)
    wds = pull_records("/api/v2/spot/wallet/withdrawal-records", key, secret, passphrase, start, now)
    flows = []
    for r in deps:
        coin = str(r.get("coin") or "").upper()
        flows.append({"date": dstr(r.get("cTime")), "day": day(r.get("cTime")), "coin": coin,
                      "qty": num(r.get("size")), "value_usdt": value_usdt(coin, num(r.get("size")), prices),
                      "direction": "入金", "channel": r.get("chain") or r.get("dest") or "",
                      "ref": r.get("orderId") or r.get("tradeId")})
    for r in wds:
        coin = str(r.get("coin") or "").upper()
        flows.append({"date": dstr(r.get("cTime")), "day": day(r.get("cTime")), "coin": coin,
                      "qty": num(r.get("size")), "value_usdt": value_usdt(coin, num(r.get("size")), prices),
                      "direction": "出金", "channel": r.get("chain") or "",
                      "ref": r.get("orderId") or r.get("tradeId")})
    flows.sort(key=lambda x: x["date"], reverse=True)
    print("      出入金：%d 笔（入 %d / 出 %d）" % (
        len(flows), len(deps), len(wds)))

    # ---- 内部划转（账户间，按币种查） ----
    coins = ["USDC", "USDT", "BTC", "SOL", "BGB"]
    raw_tr = pull_transfers(key, secret, passphrase, start, now, coins)
    for r in raw_tr:
        ft, tt = str(r.get("fromType")), str(r.get("toType"))
        coin = str(r.get("coin") or "").upper()
        qty = num(r.get("size"))
        _v = value_usdt(coin, qty, prices)
        transfers.append({"date": dstr(r.get("ts")), "day": day(r.get("ts")), "coin": coin,
                          "qty": abs(qty), "value_usdt": None if _v is None else abs(_v),
                          "kind": "%s → %s" % (ft, tt), "ref": r.get("transferId")})

    # 去重：同一 ref 只留一条
    seen, uniq_tr = set(), []
    for t in sorted(transfers, key=lambda x: x["date"], reverse=True):
        if t["ref"] in seen:
            continue
        seen.add(t["ref"])
        uniq_tr.append(t)
    transfers = uniq_tr

    # ---- 净入金：基准 + 基准日之后的链上充提 ----
    base_date = BASELINE_DATE
    baseline = BASELINE_USDT
    baseline_total = BASELINE_TOTAL_USDT
    cost = {}
    try:
        cost = json.loads(COST.read_text(encoding="utf-8"))
        nd = cost.get("net_deposit") or {}
        baseline = float(nd.get("baseline_usdt") or BASELINE_USDT)
        baseline_total = float(nd.get("baseline_total_usdt") or BASELINE_TOTAL_USDT)
        base_date = nd.get("baseline_date") or BASELINE_DATE
    except (ValueError, OSError):
        pass

    dep_after = sum((f["value_usdt"] or 0) for f in flows
                    if f["direction"] == "入金" and f["day"] > base_date)
    wd_after = sum((f["value_usdt"] or 0) for f in flows
                   if f["direction"] == "出金" and f["day"] > base_date)
    net = round(baseline + dep_after - wd_after, 2)
    net_total = round(baseline_total + dep_after - wd_after, 2)
    stock_part = round(baseline_total - baseline, 2)

    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "window": {"start": dstr(start, "%Y-%m-%d"), "end": dstr(now, "%Y-%m-%d")},
        "trades": sorted(trades, key=lambda x: x["date"], reverse=True),
        "earn_daily": earn_daily,
        "flows": flows,
        "transfers": transfers,
        "misc": misc_trades,
        "net_deposit": {
            "baseline_usdt": baseline,              # 加密账户口径（收益率分母）
            "baseline_total_usdt": baseline_total,  # 转入 Bitget 总额（含划去美股的部分）
            "stock_part_usdt": stock_part,          # 已划入美股账户的金额
            "baseline_date": base_date,
            "deposit_after": round(dep_after, 2),
            "withdraw_after": round(wd_after, 2),
            "computed_usdt": net,
            "computed_total_usdt": net_total,
        },
        "counts": {"trades": len(trades), "earn_daily": len(earn_daily),
                   "earn_raw": len(earn), "flows": len(flows), "transfers": len(transfers)},
    }
    EVENTS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("      已写入 %s（交易 %d / 生息日汇总 %d / 出入金 %d / 划转 %d），净入金 %.2f USDT" % (
        EVENTS.relative_to(ROOT), len(trades), len(earn_daily), len(flows),
        len(transfers), net))

    cost["net_deposit"] = payload["net_deposit"]
    COST.write_text(json.dumps(cost, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("      已刷新 crypto_cost.json 的 net_deposit 基准块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
