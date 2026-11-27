#!/usr/bin/env python3
"""Bitget 流水归档：交易 / 理财生息 / 出入金 / 内部划转。

统一账户（UTA）下经典 v2 接口返回 40085，本脚本优先走 v3：
  - /api/v3/trade/fills                     成交
  - /api/v3/account/financial-records       账户流水（SPOT / OTHER 两类）
  - /api/v3/account/deposit-records         链上充值（30 天窗口）
  - /api/v3/account/withdrawal-records      链上提现（30 天窗口）
  - /api/v3/earn/savings/assets             理财累计收益（用于推算每日生息）
历史数据：每次只按窗口抓增量，与 crypto_events.json 已有记录按 ref 合并，旧记录永不丢弃。

v2 接口（仅在未升级统一账户时使用）：
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


V3_OTHER_TYPES = {
    "TRANSFER_IN": ("transfer", "账户间划转"),
    "TRANSFER_OUT": ("transfer", "账户间划转"),
    "FINANCIAL_TRANSFER_IN": ("transfer", "理财账户划入"),
    "FINANCIAL_TRANSFER_OUT": ("transfer", "理财账户划出"),
    "SMALL_ASSET_SOURCE_TOKEN_USER_OUT": ("trade_bill", "闪兑"),
    "SMALL_ASSET_TARGET_TOKEN_USER_IN": ("trade_bill", "闪兑"),
}
V3_SPOT_TYPES = {
    "ORDER_DEALT_IN": ("trade_bill", "买入"),
    "ORDER_DEALT_OUT": ("trade_bill", "卖出"),
    "ORDER_PLF_FEE_OUT": ("trade_bill", "手续费"),
}


def pull_financial_records(category, key, secret, passphrase, start_ms, end_ms, log=print):
    """v3 账户流水：7 天切片 + cursor 翻页。"""
    out, cur = [], start_ms
    while cur < end_ms:
        nxt = min(cur + 7 * 86400 * 1000, end_ms)
        cursor, pages = None, 0
        while pages < 20:
            params = {"category": category, "startTime": str(cur), "endTime": str(nxt), "limit": "100"}
            if cursor:
                params["cursor"] = cursor
            try:
                data = L._get("/api/v3/account/financial-records", params, key, secret, passphrase, timeout=20)
            except Exception as e:  # noqa: BLE001
                log("      [warn] v3 流水(%s) %s~%s：%s" % (category, dstr(cur, "%m-%d"), dstr(nxt, "%m-%d"), str(e)[:80]))
                break
            rows = (data.get("list") if isinstance(data, dict) else None) or []
            if not rows:
                break
            out.extend(rows)
            cursor = (data.get("cursor") if isinstance(data, dict) else None) or rows[-1].get("id")
            pages += 1
            if len(rows) < 100 or not cursor:
                break
            time.sleep(0.08)
        cur = nxt
    return out


def bill_from_v3(r, category):
    """把 v3 流水记录规范成旧账单形状，交给 classify_bill 之后的分支复用。"""
    t = str(r.get("type") or "").upper()
    mapping = V3_SPOT_TYPES if category == "SPOT" else V3_OTHER_TYPES
    kind = mapping.get(t)
    if not kind:
        return None
    return {
        "billId": r.get("id"),
        "bizOrderId": r.get("id"),
        "coin": str(r.get("coin") or "").upper(),
        "size": r.get("amount"),
        "cTime": r.get("ts"),
        "_board": kind[0],
        "_sub": kind[1],
        "_type": t,
    }


def pull_v3_wallet(path, key, secret, passphrase, start_ms, end_ms, log=print):
    """v3 充提记录：接口限制时间区间，按 10 天切片。"""
    out, cur = [], start_ms
    while cur < end_ms:
        nxt = min(cur + 10 * 86400 * 1000, end_ms)
        try:
            rows = L._get(path, {"startTime": str(cur), "endTime": str(nxt), "limit": "20"},
                          key, secret, passphrase, timeout=20)
        except Exception as e:  # noqa: BLE001
            log("      [warn] v3 %s %s~%s：%s" % (path.split("/")[-1], dstr(cur, "%m-%d"), dstr(nxt, "%m-%d"), str(e)[:80]))
            cur = nxt
            continue
        for r in rows or []:
            if str(r.get("status") or "success").lower() != "success":
                continue
            out.append(r)
        cur = nxt
        time.sleep(0.08)
    return out


def pull_bills(key, secret, passphrase, start_ms, end_ms, log=print):
    """账单按 5 天切片，每片翻页直到取尽。"""
    out, cur = [], start_ms
    while cur < end_ms:
        nxt = min(cur + SLICE_DAYS * 86400 * 1000, end_ms)
        cursor, pages = None, 0
        while pages < 30:
            params = {"startTime": str(cur), "endTime": str(nxt), "limit": "100"}
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
            if len(rows) < 100:
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
        coin = sym
        for _q in ("USDT", "USDC", "USDGO", "USDG", "DAI"):
            if sym.endswith(_q):
                coin = sym[:-len(_q)]
                break
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

    # ---- 账单（生息 / 划转 / 闪兑 / 空投）：UTA 下走 v3 流水，经典账户回退 v2 ----
    earn, transfers, misc_trades = [], [], []
    stock_total_v3 = 0.0
    bills = []
    v3_ok = False
    try:
        rows_v3 = []
        for cat in ("SPOT", "OTHER"):
            rows_v3 += pull_financial_records(cat, key, secret, passphrase, start, now)
        keep = 0
        for r in rows_v3:
            cat = str(r.get("category") or "OTHER").upper()
            b = bill_from_v3(r, "SPOT" if cat == "SPOT" else "OTHER")
            if b:
                bills.append(b)
                keep += 1
            t = str(r.get("type") or "").upper()
            if t in ("STOCK_USER_DEPOSIT_OUT", "STOCK_USER_DEPOSIT_IN"):
                stock_total_v3 += abs(num(r.get("amount")))
        v3_ok = True
        print("      v3 流水：%d 条（可用业务 %d 条）" % (len(rows_v3), keep))
    except Exception as e:  # noqa: BLE001
        print("      [warn] v3 流水失败，回退 v2 账单：%s" % str(e)[:90])

    if not v3_ok:
        bills = [r for r in pull_bills(key, secret, passphrase, start, now)
                 if str(r.get("businessType") or "").upper() != "DEDUCTION_HANDLING_FEE"]

    for r in bills:
        if v3_ok:
            board, sub = r["_board"], r["_sub"]
        else:
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
        elif board == "trade_bill" and sub in ("闪兑", "手续费"):
            misc_trades.append({
                "date": dstr(r.get("cTime")), "coin": coin, "qty": qty,
                "value_usdt": value_usdt(coin, qty, prices),
                "kind": sub, "ref": r.get("bizOrderId") or r.get("billId"),
            })

    EARN_BASE_NEW = None
    # 统一账户不提供派息流水，用 savings 的累计 totalProfit 差值推算当日生息
    if v3_ok:
        try:
            acct = json.loads((DATA / "bitget_account.json").read_text(encoding="utf-8"))
            profits = {str(k).upper(): float(v or 0) for k, v in (acct.get("earn_profit") or {}).items()}
            prev_cost = {}
            try:
                prev_cost = json.loads(COST.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                prev_cost = {}
            base_p = (prev_cost.get("earn_profit_baseline") or {}).get("profits") or {}
            today = datetime.now(CST).strftime("%Y-%m-%d")
            for coin, tot in profits.items():
                delta = round(tot - float(base_p.get(coin) or 0), 10)
                if delta > 0:
                    v = value_usdt(coin, delta, prices)
                    earn.append({"day": today, "coin": coin, "qty": delta, "value_usdt": v})
            if profits:
                EARN_BASE_NEW = {"date": today, "profits": profits}
                print("      理财累计收益推算当日生息：%s" % "、".join(
                    "%s %.8f" % (c, p) for c, p in profits.items()))
        except (ValueError, OSError) as e:
            print("      [warn] 生息推算跳过：%s" % str(e)[:80])

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
    deps, wds = [], []
    if v3_ok:
        deps = pull_v3_wallet("/api/v3/account/deposit-records", key, secret, passphrase, start, now)
        wds = pull_v3_wallet("/api/v3/account/withdrawal-records", key, secret, passphrase, start, now)
    else:
        deps = pull_records("/api/v2/spot/wallet/deposit-records", key, secret, passphrase, start, now)
        wds = pull_records("/api/v2/spot/wallet/withdrawal-records", key, secret, passphrase, start, now)
    flows = []
    for r in deps:
        coin = str(r.get("coin") or "").upper()
        _t = r.get("createdTime") or r.get("cTime")
        flows.append({"date": dstr(_t), "day": day(_t), "coin": coin,
                      "qty": num(r.get("size")), "value_usdt": value_usdt(coin, num(r.get("size")), prices),
                      "direction": "入金", "channel": r.get("chain") or r.get("dest") or "",
                      "ref": r.get("orderId") or r.get("recordId") or r.get("tradeId")})
    for r in wds:
        coin = str(r.get("coin") or "").upper()
        _t = r.get("createdTime") or r.get("cTime")
        flows.append({"date": dstr(_t), "day": day(_t), "coin": coin,
                      "qty": num(r.get("size")), "value_usdt": value_usdt(coin, num(r.get("size")), prices),
                      "direction": "出金", "channel": r.get("chain") or "",
                      "ref": r.get("orderId") or r.get("recordId") or r.get("tradeId")})
    flows.sort(key=lambda x: x["date"], reverse=True)
    print("      出入金：%d 笔（入 %d / 出 %d）" % (
        len(flows), len(deps), len(wds)))

    # ---- 内部划转：v3 下已由流水 TRANSFER_*/FINANCIAL_TRANSFER_* 覆盖，只有经典账户才额外查 ----
    raw_tr = [] if v3_ok else pull_transfers(key, secret, passphrase, start, now, ["USDC", "USDT", "BTC", "SOL", "BGB"])
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
    if EARN_BASE_NEW:
        cost["earn_profit_baseline"] = EARN_BASE_NEW

    # 划入美股账户金额：以账单 STOCK_USER_DEPOSIT_OUT 为准（transferRecords 只覆盖 uta/spot 互转，
    # 会漏掉部分划出记录，导致口径偏小）。这是唯一权威来源。
    stock_total = 0.0
    if v3_ok:
        stock_total = stock_total_v3
        if stock_total <= 0:
            stock_total = float((cost.get("net_deposit") or {}).get("stock_part_usdt") or 0)
            print("      [warn] v3 流水未返回划入美股记录，沿用上次口径：%.2f USDT" % stock_total)
    else:
        for b in bills:
            if str(b.get("businessType") or "").upper() == "STOCK_USER_DEPOSIT_OUT":
                try:
                    stock_total += abs(float(b.get("size") or 0))
                except (TypeError, ValueError):
                    continue
    print("      划入美股账户（账单口径）：%.2f USDT" % stock_total)

    dep_after = sum((f["value_usdt"] or 0) for f in flows
                    if f["direction"] == "入金" and f["day"] > base_date)
    wd_after = sum((f["value_usdt"] or 0) for f in flows
                   if f["direction"] == "出金" and f["day"] > base_date)
    net_total = round(baseline_total + dep_after - wd_after, 2)
    stock_part = round(stock_total, 2)
    # 加密账户口径 = 总净入金 − 全部划入美股（不再用基准日那一个静态值，避免漏算基准日后的划出）
    net = round(net_total - stock_part, 2) if stock_part else round(baseline + dep_after - wd_after, 2)

    # ---- 与历史归档合并：窗口外/接口读不到旧记录一律保留 ----
    def _merge(new_items, old_items, key_fn):
        have = {key_fn(x) for x in new_items}
        kept = [x for x in old_items if key_fn(x) not in have]
        if kept:
            print("      保留历史记录：%d 条" % len(kept))
        return new_items + kept

    prev = {}
    try:
        prev = json.loads(EVENTS.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        prev = {}

    def k_trade(x):
        return x.get("ref") or "|".join(str(x.get(k)) for k in ("date", "symbol", "side", "qty"))

    def k_flow(x):
        return x.get("ref") or "|".join(str(x.get(k)) for k in ("date", "coin", "direction", "qty"))

    def k_tr(x):
        return x.get("ref") or "|".join(str(x.get(k)) for k in ("date", "coin", "kind", "qty"))

    def k_misc(x):
        return x.get("ref") or "|".join(str(x.get(k)) for k in ("date", "coin", "kind", "qty"))

    trades = _merge(trades, prev.get("trades") or [], k_trade)
    flows = _merge(flows, prev.get("flows") or [], k_flow)
    transfers = _merge(transfers, prev.get("transfers") or [], k_tr)
    misc_trades = _merge(misc_trades, prev.get("misc") or [], k_misc)
    earn_daily = _merge(earn_daily, prev.get("earn_daily") or [],
                        lambda x: "%s|%s" % (x.get("day"), x.get("coin")))

    # 合并后再算一次净入金，确保窗口外的历史充提也算进净入金
    dep_after = sum((f["value_usdt"] or 0) for f in flows
                    if f["direction"] == "入金" and f["day"] > base_date)
    wd_after = sum((f["value_usdt"] or 0) for f in flows
                   if f["direction"] == "出金" and f["day"] > base_date)
    net_total = round(baseline_total + dep_after - wd_after, 2)
    stock_part = round(stock_total, 2)
    net = round(net_total - stock_part, 2) if stock_part else round(baseline + dep_after - wd_after, 2)


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
