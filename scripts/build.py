"""
全维度资产统计 —— 后台计算脚本。

输入：
  data/holdings.json      你维护的份额（唯一人工输入）
  data/snapshots.json     历史每日总资产快照（脚本自动累积）

抓取：
  传统标的  ← 全球资产仪表台(index-fund-dashboard) 已抓取的价格 / 腾讯实时 / 天天基金 / Yahoo
  加密货币  ← 加密货币资产仪表台(bitget-pnl-dashboard) 最新快照（现货+理财合并）
  汇率      ← open.er-api.com（USD→CNY），失败用 holdings.json 兜底

输出：
  data/dashboard.json     前端页面直接渲染的数据（份额 × 价格 = 市值、占比、日变动、趋势）

用法：
  python3 scripts/build.py
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import sources  # noqa: E402

CST = timezone(timedelta(hours=8))
PAGE_VERSION = "20261112t"  # 页面逻辑版本：改动 index.html / admin.html / js / css 时同步 +1
TRADITIONAL_GROUP = "traditional"
CRYPTO_GROUP = "crypto"
CASH_GROUP = "cash"
# 稳定币按 1:1 计价、不参与币价波动，单列为「现金」
STABLE_COINS = {"USDT", "USDC", "USDG", "USDGO", "DAI", "FDUSD", "TUSD", "USDP", "PYUSD"}


def now_cst():
    return datetime.now(CST)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def r2(x, n=2):
    return None if x is None else round(float(x), n)


# --------------------------------------------------------------------------
# 传统标的：抓价格
# --------------------------------------------------------------------------

def resolve_price(item, fund_items):
    """按优先级返回 (quote, source_desc)。quote 结构见 sources.py。"""
    code = str(item.get("symbol") or item.get("id") or "").strip()
    upper = code.upper()

    # 1) 全球资产仪表台
    hit = fund_items.get(upper)
    if hit and hit.get("price"):
        return {
            "price": hit.get("price"),
            "prev_close": None,
            "change_pct": hit.get("change_pct"),
            "ts": hit.get("ts"),
            "name": hit.get("name"),
            "source": "全球资产仪表台",
            "kind": "quote",
        }, "全球资产仪表台"

    # 2) 腾讯实时
    q = sources.tencent_quote(code)
    if q and q.get("price"):
        return q, q["source"]

    # 3) 场外基金净值（东方财富 → 天天基金）
    if code.isdigit() and len(code) == 6:
        q = sources.eastmoney_nav(code)
        if q and q.get("price"):
            return q, q["source"]
        q = sources.fundgz_nav(code)
        if q and q.get("price"):
            return q, q["source"]

    # 4) Yahoo
    ysym = upper if not code.isdigit() else code
    q = sources.yahoo_quote(ysym)
    if q and q.get("price"):
        return q, q["source"]

    return None, "未取到"


def build_traditional(holdings, fund_items, rate):
    rows = []
    for it in holdings.get("traditional", []):
        shares = float(it.get("shares") or 0)
        cost_price = float(it.get("cost_price") or 0)
        cur = (it.get("currency") or ("USD" if str(it.get("symbol", "")).upper() in
                                      ("QQQM", "VOO", "QQQI") else "CNY")).upper()
        q, src = resolve_price(it, fund_items)
        price = (q or {}).get("price")
        chg = (q or {}).get("change_pct")
        value_native = shares * price if price is not None else None
        fx = rate if cur == "USD" else 1.0
        value_cny = value_native * fx if value_native is not None else None
        day_cny = value_cny * (chg or 0) / 100.0 if value_cny is not None else None
        # 持仓成本与浮动盈亏（成本价按标的币种计价，与现价同币种）
        cost_native = shares * cost_price if cost_price > 0 else None
        cost_cny = cost_native * fx if cost_native is not None else None
        pnl_cny = (value_cny - cost_cny) if (value_cny is not None and cost_cny is not None) else None
        pnl_pct = (pnl_cny / cost_cny * 100.0) if (pnl_cny is not None and cost_cny) else None
        rows.append({
            "id": str(it.get("id") or it.get("symbol")),
            "name": it.get("name") or (q or {}).get("name") or str(it.get("symbol")),
            "asset_class": it.get("asset_class") or "其他",
            "group": TRADITIONAL_GROUP,
            "shares": r2(shares, 6),
            "cost_price": r2(cost_price, 4),
            "price": r2(price, 4),
            "currency": cur,
            "change_pct": r2(chg, 2),
            "value_native": r2(value_native, 2),
            "value_cny": r2(value_cny, 2),
            "cost_native": r2(cost_native, 2),
            "cost_cny": r2(cost_cny, 2),
            "pnl_cny": r2(pnl_cny, 2),
            "pnl_pct": r2(pnl_pct, 2),
            "cost_pending": cost_price <= 0,
            "day_change_cny": r2(day_cny, 2),
            "price_source": src,
            "price_ts": (q or {}).get("ts"),
            "pending": shares <= 0,
            "note": it.get("note") or "",
        })
    return rows


# --------------------------------------------------------------------------
# 加密货币：读取加密货币资产仪表台
# --------------------------------------------------------------------------

def load_crypto(cfg, rate):
    url = (cfg.get("crypto") or {}).get("source_url")
    raw = sources._fetch(url, retries=2)
    if not raw:
        return [], {"error": "加密货币仪表台数据读取失败", "source": url}
    try:
        history = json.loads(raw)
    except ValueError:
        return [], {"error": "加密货币仪表台数据解析失败", "source": url}
    if not isinstance(history, list) or not history:
        return [], {"error": "加密货币仪表台无快照数据", "source": url}

    latest = history[-1]
    prev = history[-2] if len(history) > 1 else None

    # 上一快照各币价格，用于算币价日变动
    prev_prices = {}
    if prev:
        for c in prev.get("byCoin", []):
            prev_prices.setdefault(c.get("coin"), c.get("price"))

    include = set((cfg.get("crypto") or {}).get("include_coins") or [])
    exclude = set((cfg.get("crypto") or {}).get("exclude_coins") or [])

    agg = {}
    for c in latest.get("byCoin", []):
        coin = c.get("coin")
        if not coin:
            continue
        if include and coin not in include:
            continue
        if coin in exclude:
            continue
        a = agg.setdefault(coin, {"coin": coin, "amount": 0.0, "usdt": 0.0,
                                  "price": c.get("price"), "kinds": set()})
        a["amount"] += float(c.get("amount") or 0)
        a["usdt"] += float(c.get("usdt") or 0)
        if c.get("price"):
            a["price"] = c.get("price")
        if c.get("kind"):
            a["kinds"].add(c["kind"])

    rows = []
    for coin, a in agg.items():
        pp = prev_prices.get(coin)
        chg = ((a["price"] - pp) / pp * 100) if (pp and a["price"]) else None
        value_cny = a["usdt"] * rate
        day_cny = (a["amount"] * (a["price"] - pp) * rate) if (pp and a["price"]) else 0.0
        is_cash = coin.upper() in STABLE_COINS
        rows.append({
            "id": coin,
            "name": coin,
            "asset_class": "现金（稳定币）" if is_cash else "加密货币",
            "group": CASH_GROUP if is_cash else CRYPTO_GROUP,
            "shares": r2(a["amount"], 8),
            "price": r2(a["price"], 4),
            "currency": "USDT",
            "change_pct": r2(chg, 2),
            "value_native": r2(a["usdt"], 2),
            "value_cny": r2(value_cny, 2),
            "day_change_cny": r2(day_cny, 2),
            "price_source": "加密货币资产仪表台",
            "price_ts": latest.get("date"),
            "pending": False,
            "note": "现货+理财（%s）" % "/".join(sorted(a["kinds"])) if a["kinds"] else "现货+理财",
        })
    rows.sort(key=lambda x: x["value_cny"] or 0, reverse=True)

    meta = {
        "source": "bitget-pnl-dashboard / data/history.json",
        "url": url,
        "snapshot_date": latest.get("date"),
        "total_usdt": r2(latest.get("totalUsdt"), 2),
        "spot_usdt": r2(latest.get("spotUsdt"), 2),
        "earn_usdt": r2(latest.get("earnUsdt"), 2),
        "coin_count": len(rows),
        "daily_change_usdt": r2(latest.get("dailyChangeUsdt"), 2),
        "real_pnl_usdt": r2(latest.get("realPnlUsdt"), 2),
        "real_pnl_pct": r2(latest.get("realPnlPct"), 2),
        "net_deposit_usdt": r2(latest.get("netDepositUsdt"), 2),
    }
    return rows, meta


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main():
    holdings_path = os.path.join(ROOT, "data", "holdings.json")
    dashboard_path = os.path.join(ROOT, "data", "dashboard.json")
    snapshots_path = os.path.join(ROOT, "data", "snapshots.json")

    holdings = load_json(holdings_path, {})
    if not holdings.get("traditional"):
        print("[error] holdings.json 缺少 traditional 列表")
        return 1

    print("[1/5] 抓取全球资产仪表台价格 …")
    fund_items = sources.fund_dashboard_items()
    print("      命中的标的：%s" % (", ".join(sorted(fund_items.keys())) or "无"))

    print("[2/5] 抓取汇率 …")
    rate, fx_src = sources.usdcny()
    if not rate:
        rate = float((holdings.get("fx") or {}).get("usdcny_fallback") or 7.12)
        fx_src = "holdings.json 兜底值"
    print("      USD→CNY = %.4f（%s）" % (rate, fx_src))

    print("[3/5] 计算传统标的市值 …")
    trad_rows = build_traditional(holdings, fund_items, rate)
    for r in trad_rows:
        print("      %-8s 份额=%-10s 成本价=%-9s 现价=%-9s 市值=%s 盈亏=%s [%s]" % (
            r["id"], r["shares"], r["cost_price"], r["price"], r["value_cny"],
            r["pnl_cny"], r["price_source"]))

    print("[4/5] 抓取加密货币资产仪表台 …")
    crypto_rows, crypto_meta = load_crypto(holdings, rate)
    if crypto_meta.get("error"):
        print("      [warn] " + crypto_meta["error"])
    else:
        print("      快照 %s，共 %s 个币种，合计 %.2f USDT" % (
            crypto_meta.get("snapshot_date"), crypto_meta.get("coin_count"),
            crypto_meta.get("total_usdt") or 0))

    trad_cny = sum(r["value_cny"] or 0 for r in trad_rows)
    crypto_cny = sum(r["value_cny"] or 0 for r in crypto_rows if r["group"] == CRYPTO_GROUP)
    cash_cny = sum(r["value_cny"] or 0 for r in crypto_rows if r["group"] == CASH_GROUP)
    crypto_account_cny = crypto_cny + cash_cny
    total_cny = trad_cny + crypto_account_cny
    day_change = sum(r["day_change_cny"] or 0 for r in trad_rows) + \
                 sum(r["day_change_cny"] or 0 for r in crypto_rows)
    trad_cost = sum(r["cost_cny"] or 0 for r in trad_rows)
    trad_pnl = sum(r["pnl_cny"] or 0 for r in trad_rows)
    cost_pending = [r["id"] for r in trad_rows if r.get("cost_pending") and r["shares"]]
    crypto_pnl_usdt = crypto_meta.get("real_pnl_usdt")
    crypto_pnl_cny = crypto_pnl_usdt * rate if crypto_pnl_usdt is not None else None
    total_pnl = trad_pnl + (crypto_pnl_cny or 0) if (trad_cost or crypto_pnl_cny is not None) else None
    pending = [r["id"] for r in trad_rows if r["pending"]]

    def weight(v):
        return round(v / total_cny * 100, 2) if total_cny else 0.0

    for r in trad_rows + crypto_rows:
        r["weight"] = weight(r["value_cny"] or 0)

    # ---- 历史快照累积 ----
    today = now_cst().strftime("%Y-%m-%d")
    snapshots = load_json(snapshots_path, [])
    if not isinstance(snapshots, list):
        snapshots = []
    entry = {
        "date": today,
        "total_cny": r2(total_cny, 2),
        "traditional_cny": r2(trad_cny, 2),
        "crypto_cny": r2(crypto_account_cny, 2),
        "crypto_account_cny": r2(crypto_account_cny, 2),
        "cash_cny": r2(cash_cny, 2),
        "day_change_cny": r2(day_change, 2),
        "day_change_pct": round(day_change / (total_cny - day_change) * 100, 2)
        if total_cny - day_change else 0.0,
        "fx_usdcny": r2(rate, 4),
        "crypto_usdt": crypto_meta.get("total_usdt"),
    }
    snapshots = [s for s in snapshots if s.get("date") != today] + [entry]
    snapshots.sort(key=lambda s: s.get("date") or "")
    prev_total = None
    for sn in snapshots:
        if sn.get("day_change_cny") is None and prev_total is not None:
            d = (sn.get("total_cny") or 0) - prev_total
            sn["day_change_cny"] = r2(d, 2)
            base = prev_total
            sn["day_change_pct"] = round(d / base * 100, 2) if base else 0.0
        prev_total = sn.get("total_cny")
    save_json(snapshots_path, snapshots)

    print("[5/5] 写出 dashboard.json …")
    generated_at = now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    dashboard = {
        "meta": {
            "title": "全维度资产统计",
            "subtitle": "传统股票/基金 + 加密货币 合并统计 · 份额 × 价格 = 市值",
            "version": (holdings.get("meta") or {}).get("version") or "1.0.0",
            "generated_at": generated_at,
            "page_version": PAGE_VERSION,
            "base_currency": "CNY",
            "fx": {"usdcny": r2(rate, 4), "source": fx_src},
            "sources": {
                "traditional_price": "全球资产仪表台 → 腾讯实时 → 东方财富基金 → Yahoo",
                "traditional_price_url": sources.FUND_DASHBOARD_URL,
                "crypto": crypto_meta.get("url"),
                "crypto_dashboard": "https://978912280-jpg.github.io/bitget-pnl-dashboard/",
            },
        },
        "summary": {
            "total_cny": r2(total_cny, 2),
            "traditional_cny": r2(trad_cny, 2),
            "crypto_cny": r2(crypto_cny, 2),
            "cash_cny": r2(cash_cny, 2),
            "crypto_account_cny": r2(crypto_account_cny, 2),
            "traditional_weight": weight(trad_cny),
            "crypto_weight": weight(crypto_cny),
            "cash_weight": weight(cash_cny),
            "day_change_cny": r2(day_change, 2),
            "day_change_pct": round(day_change / (total_cny - day_change) * 100, 2)
            if total_cny - day_change else 0.0,
            "crypto_usdt": crypto_meta.get("total_usdt"),
            "count": len(trad_rows) + len(crypto_rows),
            "pending_count": len(pending),
            "pending_ids": pending,
            "traditional_cost_cny": r2(trad_cost, 2),
            "traditional_pnl_cny": r2(trad_pnl, 2),
            "traditional_pnl_pct": r2(trad_pnl / trad_cost * 100, 2) if trad_cost else None,
            "cost_pending_count": len(cost_pending),
            "cost_pending_ids": cost_pending,
            "crypto_pnl_cny": r2(crypto_pnl_cny, 2),
            "crypto_pnl_usdt": crypto_pnl_usdt,
            "crypto_pnl_pct": crypto_meta.get("real_pnl_pct"),
            "total_pnl_cny": r2(total_pnl, 2),
        },
        "groups": [
            {
                "key": TRADITIONAL_GROUP,
                "name": "传统股票 & 基金",
                "cny": r2(trad_cny, 2),
                "weight": weight(trad_cny),
                "count": len(trad_rows),
                "items": [r["id"] for r in trad_rows],
            },
            {
                "key": CRYPTO_GROUP,
                "name": "加密货币",
                "cny": r2(crypto_cny, 2),
                "weight": weight(crypto_cny),
                "count": len([r for r in crypto_rows if r["group"] == CRYPTO_GROUP]),
                "items": [r["id"] for r in crypto_rows if r["group"] == CRYPTO_GROUP],
            },
            {
                "key": CASH_GROUP,
                "name": "现金（稳定币）",
                "cny": r2(cash_cny, 2),
                "weight": weight(cash_cny),
                "count": len([r for r in crypto_rows if r["group"] == CASH_GROUP]),
                "items": [r["id"] for r in crypto_rows if r["group"] == CASH_GROUP],
            },
        ],
        "items": trad_rows + crypto_rows,
        "crypto_meta": crypto_meta,
        "history": [{"date": s.get("date"),
                     "total_cny": s.get("total_cny"),
                     "traditional_cny": s.get("traditional_cny"),
                     "crypto_cny": s.get("crypto_cny"),
                     "cash_cny": s.get("cash_cny"),
                     "day_change_cny": s.get("day_change_cny"),
                     "day_change_pct": s.get("day_change_pct"),
                     "fx_usdcny": s.get("fx_usdcny"),
                     "crypto_usdt": s.get("crypto_usdt")} for s in snapshots][-400:],
    }
    save_json(dashboard_path, dashboard)

    print("\n合计：传统 %.2f + 加密 %.2f = %.2f CNY" % (trad_cny, crypto_cny, total_cny))
    if pending:
        print("待填写份额的标的：%s" % ", ".join(pending))
    return 0


if __name__ == "__main__":
    sys.exit(main())
