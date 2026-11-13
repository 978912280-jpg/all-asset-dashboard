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
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import sources  # noqa: E402

CST = timezone(timedelta(hours=8))
# 页面版本（同时作为缓存键）：与 holdings.json 的 meta.version 保持一致。
# 发布规则：每次上线改动 +0.0.1；分位到 10 进 1（1.0.9 → 1.1.0）。
PAGE_VERSION = "1.4.4"
PAGE_DATE = "2026.11.12"
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

    # 0) 美股：优先腾讯实时价（仪表台里的美股价格往往是上一交易日收盘，会滞后）
    if code.replace(".", "").replace("-", "").isalpha():
        q = sources.tencent_quote(code)
        if q and q.get("price"):
            return q, q["source"]

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


def build_traditional(holdings, fund_items, rate, prev_items=None):
    prev_items = prev_items or {}
    today = now_cst().strftime("%Y-%m-%d")
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
        # 当日浮动收益：优先用「上一份快照的份额 × 当日价差」，这样补录份额不会改写历史日期
        sid = str(it.get("id") or it.get("symbol"))
        prev = prev_items.get(sid) or {}
        prev_price = prev.get("price")
        base_shares = prev.get("shares") if prev.get("shares") else shares
        added_at = str(it.get("added_at") or "")[:10]
        if added_at and added_at >= today and price is not None:
            # 当日新买入：只算「成本价 → 现价」这段，不把买入前的日内涨跌算进来
            entry_px = cost_price if cost_price > 0 else price
            day_cny = shares * (price - entry_px) * fx
            day_basis = "new"
        elif prev_price is not None and price is not None:
            day_cny = base_shares * (price - prev_price) * fx
            day_basis = "prev_snapshot" if prev.get("shares") else "prev_price"
        else:
            day_cny = value_cny * (chg or 0) / 100.0 if value_cny is not None else None
            day_basis = "pct"
        # 持仓成本与浮动盈亏（成本价按标的币种计价，与现价同币种）
        cost_native = shares * cost_price if cost_price > 0 else None
        cost_cny = cost_native * fx if cost_native is not None else None
        pnl_cny = (value_cny - cost_cny) if (value_cny is not None and cost_cny is not None) else None
        pnl_pct = (pnl_cny / cost_cny * 100.0) if (pnl_cny is not None and cost_cny) else None
        base_name = it.get("name") or (q or {}).get("name") or str(it.get("symbol"))
        sym = str(it.get("symbol") or "").upper()
        # 中文名后统一带上代码：中文名（代码），名称里已含代码的跳过
        if sym and sym not in base_name.upper():
            base_name = "%s（%s）" % (base_name, sym)
        rows.append({
            "id": str(it.get("id") or it.get("symbol")),
            "name": base_name,
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
            "day_basis": day_basis,
            "price_source": src,
            "price_ts": (q or {}).get("ts"),
            "pending": shares <= 0,
            "note": it.get("note") or "",
        })
    return rows


# --------------------------------------------------------------------------
# 加密货币：读取加密货币资产仪表台
# --------------------------------------------------------------------------

def load_cost_total():
    """读取加密币成本总额（USDT）与成交净数量。

    返回 (cost_map, qty_net, calib_shares)。qty_net 是校准日之后 Bitget 成交累计的净数量，
    用于判断「成交已入账但加密货币快照份额尚未更新」的滞后情形。
    """
    root = Path(ROOT) / "data"
    qty_net, calib_shares = {}, {}
    calib_file = root / "crypto_cost.json"
    if calib_file.exists():
        try:
            calib_shares = (json.loads(calib_file.read_text(encoding="utf-8")).get("calibration") or {}).get("calib_shares") or {}
        except (ValueError, OSError):
            calib_shares = {}
    ledger = root / "bitget_ledger.json"
    if ledger.exists():
        try:
            p = json.loads(ledger.read_text(encoding="utf-8"))
            c = p.get("cost_total_usdt")
            if isinstance(c, dict) and c:
                print("      成本账本：%s（%s 笔成交，更新于 %s）" % (
                    "、".join("%s %.2f" % (k, v) for k, v in c.items()), p.get("fills"), p.get("updated_at")))
                # 只有明确标记为「校准后净变化」的账本才用于暂缓成本，避免旧格式（绝对持仓）误判
                if p.get("qty_mode") == "delta":
                    qty_net = {str(k).upper(): float(v) for k, v in (p.get("qty_net") or {}).items()}
                return {str(k).upper(): float(v) for k, v in c.items()}, qty_net, {str(k).upper(): float(v) for k, v in calib_shares.items()}
        except (ValueError, OSError) as e:
            print("      [warn] 成本账本读取失败：%s" % e)
    cal = root / "crypto_cost.json"
    if cal.exists():
        try:
            p = json.loads(cal.read_text(encoding="utf-8"))
            c = (p.get("calibration") or {}).get("cost_total_usdt")
            if c:
                print("      成本账本：使用 %s 校准值" % (p["calibration"].get("date"),))
                return {str(k).upper(): float(v) for k, v in c.items()}, qty_net, {str(k).upper(): float(v) for k, v in calib_shares.items()}
        except (ValueError, OSError) as e:
            print("      [warn] crypto_cost.json 读取失败：%s" % e)
    return {}, {}, {}


def load_realized_pnl():
    """已实现盈亏（USDT，按币）：来自 Bitget 卖出成交，按当时平均成本结算。"""
    f = Path(ROOT) / "data" / "bitget_ledger.json"
    if not f.exists():
        return {}
    try:
        p = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {str(k).upper(): float(v) for k, v in (p.get("realized_pnl_usdt") or {}).items()}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def load_crypto_from_account(cfg, rate, prev_items=None):
    """直接从 Bitget 私有接口读取现货+理财持仓，不依赖上游加密仪表台。

    返回 (rows, meta)；账户文件缺失或为空时返回 (None, None)，由调用方回退上游。
    """
    acct = _read_json(Path(ROOT) / "data" / "bitget_account.json")
    coins = (acct or {}).get("coins") or {}
    if not coins:
        return None, None
    include = set((cfg.get("crypto") or {}).get("include_coins") or [])
    exclude = set((cfg.get("crypto") or {}).get("exclude_coins") or [])
    coins = {c: v for c, v in coins.items()
             if (not include or c in include) and c not in exclude and float(v.get("total") or 0) > 0}
    if not coins:
        return None, None
    # 价格：稳定币按 1，其余取 Bitget 实时行情
    live = sources.bitget_prices([c for c in coins if c not in STABLE_COINS])
    rows = []
    for coin, v in sorted(coins.items(), key=lambda kv: -float(kv[1].get("total") or 0)):
        amt = float(v.get("total") or 0)
        price = 1.0 if coin in STABLE_COINS else (live.get(coin) or 0)
        if not price:
            # 无实时价时退回上游快照价（若能取到），否则跳过该币
            continue
        value_cny = amt * price * rate
        pp = (prev_items.get(coin) or {}).get("price")
        prev_amt = (prev_items.get(coin) or {}).get("shares") or amt
        day_cny = (prev_amt * (price - pp) * rate) if pp else 0.0
        chg = ((price - pp) / pp * 100) if pp else None
        is_cash = coin in STABLE_COINS
        rows.append({
            "id": coin,
            "name": coin,
            "asset_class": "现金（稳定币）" if is_cash else "加密货币",
            "group": CASH_GROUP if is_cash else CRYPTO_GROUP,
            "shares": r2(amt, 8),
            "price": r2(price, 4),
            "currency": "USDT",
            "change_pct": r2(chg, 2) if chg is not None else None,
            "value_native": r2(amt * price, 2),
            "value_cny": r2(value_cny, 2),
            "day_change_cny": r2(day_cny, 2),
            "day_basis": "prev_snapshot" if pp else "live",
            "price_source": "Bitget 实时价" if not is_cash else "面值",
            "price_ts": (acct or {}).get("updated_at"),
            "pending": False,
            "note": "Bitget 现货 %.6g + 理财 %.6g" % (
                float(v.get("spot") or 0), float(v.get("earn") or 0)) if not is_cash else "Bitget 账户",
        })
    if not rows:
        return None, None
    print("      加密货币：直接读取 Bitget 账户（%d 个币种，%s）" % (
        len(rows), (acct or {}).get("updated_at")))
    coins_total = sum(float(r.get("value_native") or 0) for r in rows)
    return rows, {
        "source": "bitget_account",
        "url": "Bitget 私有接口（现货+理财）",
        "price_mode": "live",
        "live_price_count": len([r for r in rows if r["group"] == CRYPTO_GROUP]),
        "updated_at": (acct or {}).get("updated_at"),
        "snapshot_date": now_cst().strftime("%Y-%m-%d"),
        "coin_count": len(rows),
        "total_usdt": r2(coins_total, 2),
    }


def load_crypto(cfg, rate, prev_items=None):
    prev_items = prev_items or {}
    rows, meta = load_crypto_from_account(cfg, rate, prev_items)
    if rows:
        return rows, meta
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

    # 日变动基准价：若仪表台当天已有快照（最新日期=今天），基准取前一快照；
    # 否则最新快照本身就是「上一个交易日收盘」，直接用它做基准，避免把两天涨跌算成一天。
    today_str = now_cst().strftime("%Y-%m-%d")
    base = prev if (latest.get("date") == today_str and prev) else latest
    prev_prices = {}
    for c in (base or {}).get("byCoin", []):
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
        prev_amt = (prev_items.get(coin) or {}).get("shares") or a["amount"]
        day_cny = (prev_amt * (a["price"] - pp) * rate) if (pp and a["price"]) else 0.0
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
            "day_basis": "prev_snapshot" if prev_items.get(coin) else "prev_price",
            "price_source": "加密货币资产仪表台",
            "price_ts": latest.get("date"),
            "pending": False,
            "note": "现货+理财（%s）" % "/".join(sorted(a["kinds"])) if a["kinds"] else "现货+理财",
        })
    # ---- 用 Bitget 实时价重估币类持仓（稳定币按 1:1 不动）----
    live_prices = {}
    repriced = 0
    pnl_delta_usdt = 0.0
    if os.environ.get("LIVE_CRYPTO", "1") != "0":
        coins = [r["id"] for r in rows if r["id"].upper() not in STABLE_COINS]
        print("      抓取加密货币实时价格 …")
        live_prices = sources.bitget_prices(coins)
        for row in rows:
            px = live_prices.get(row["id"])
            if not px or not row.get("shares"):
                continue
            snap_px = row.get("price") or 0
            amt = float(row["shares"])
            row["price"] = r2(px, 4)
            row["value_native"] = r2(amt * px, 2)
            row["value_cny"] = r2(amt * px * rate, 2)
            row["price_source"] = "Bitget 实时价"
            # 日变动基准：优先用昨日快照里「当时展示的价格」，保证与昨天页面上的数字连续；
            # 仅当昨日快照无该币价时才退回交易所快照价。
            pp = (prev_items.get(row["id"]) or {}).get("price") or prev_prices.get(row["id"])
            if pp:
                row["change_pct"] = r2((px - pp) / pp * 100, 2)
                prev_amt = (prev_items.get(row["id"]) or {}).get("shares") or amt
                row["day_change_cny"] = r2(prev_amt * (px - pp) * rate, 2)
            if snap_px:
                pnl_delta_usdt += amt * (px - snap_px)
            repriced += 1

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
        "price_mode": "live" if repriced else "snapshot",
        "live_price_count": repriced,
        "price_updated_at": now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "snapshot_total_usdt": r2(latest.get("totalUsdt"), 2),
    }
    # 实时价重估后：账户合计与真实盈亏跟随币价变化
    if repriced:
        meta["total_usdt"] = r2(sum(r["value_native"] or 0 for r in rows), 2)
        if meta.get("real_pnl_usdt") is not None:
            meta["real_pnl_usdt"] = r2(meta["real_pnl_usdt"] + pnl_delta_usdt, 2)
            nd = meta.get("net_deposit_usdt") or 0
            if nd:
                meta["real_pnl_pct"] = r2(meta["real_pnl_usdt"] / nd * 100, 2)
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

    snapshots = load_json(snapshots_path, [])
    if not isinstance(snapshots, list):
        snapshots = []
    today = now_cst().strftime("%Y-%m-%d")
    prev_items = {}
    prev_snapshot_date = None
    for sn in reversed(snapshots):
        if sn.get("date") and sn.get("date") < today and sn.get("items"):
            prev_items = {str(x.get("id")): x for x in sn["items"]}
            prev_snapshot_date = sn.get("date")
            break

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
    trad_rows = build_traditional(holdings, fund_items, rate, prev_items)
    for r in trad_rows:
        print("      %-8s 份额=%-10s 成本价=%-9s 现价=%-9s 市值=%s 盈亏=%s [%s]" % (
            r["id"], r["shares"], r["cost_price"], r["price"], r["value_cny"],
            r["pnl_cny"], r["price_source"]))

    print("[4/5] 抓取加密货币资产仪表台 …")
    crypto_rows, crypto_meta = load_crypto(holdings, rate, prev_items)
    # PoolX 等官方 API 不暴露的仓位：合并 data/holdings.json 手工登记的份额（零成本，摊薄成本价）
    for px in (holdings.get("poolx") or []):
        coin = str(px.get("coin") or "").upper()
        amt = float(px.get("amount") or 0)
        if not coin or amt <= 0:
            continue
        row = next((r for r in crypto_rows if str(r["id"]).upper() == coin), None)
        if row is None:
            continue
        row["shares"] = r2(float(row.get("shares") or 0) + amt, 8)
        row["value_native"] = r2(row["shares"] * float(row.get("price") or 0), 2)
        row["value_cny"] = r2(row["value_native"] * (rate if row.get("currency") in ("USD", "USDT") else 1.0), 2)
        row["note"] = (row.get("note") or "") + "；PoolX +%.6g" % amt
        print("      PoolX 合并：%s +%.6g（手工登记）" % (coin, amt))
    if crypto_meta.get("error"):
        print("      [warn] " + crypto_meta["error"])
    else:
        print("      快照 %s，共 %s 个币种，合计 %.2f USDT" % (
            crypto_meta.get("snapshot_date"), crypto_meta.get("coin_count"),
            crypto_meta.get("total_usdt") or 0))

    # 手工维护的现金账户（支付宝余额等），与稳定币一起计入「现金」组
    cash_rows = []
    for ca in (holdings.get("cash_accounts") or []):
        amt = float(ca.get("amount_cny") or 0)
        if amt <= 0:
            continue
        cash_rows.append({
            "id": str(ca.get("id") or ca.get("name")),
            "name": ca.get("name") or "支付宝现金",
            "asset_class": "现金（余额）",
            "group": CASH_GROUP,
            "shares": None,
            "price": None,
            "currency": "CNY",
            "change_pct": 0.0,
            "value_native": r2(amt, 2),
            "value_cny": r2(amt, 2),
            "day_change_cny": 0.0,
            "day_basis": "cash",
            "price_source": "手工录入",
            "pending": False,
            "note": "",
        })

    # ---- 按成本账本（净入金校准 + Bitget 成交）补齐加密币的成本与逐项盈亏 ----
    cost_map, qty_net, calib_shares = load_cost_total()
    if cost_map:
        for row in crypto_rows:
            if row["group"] != CRYPTO_GROUP:
                continue
            coin = str(row["id"]).upper()
            if coin not in cost_map:
                continue
            usdt = float(cost_map[coin] or 0)
            # 成交当晚快照份额可能还没跟上：此时成本已累加但市值未增加，会把亏损虚增。
            # 用「校准份额 + 成交净数量 − 当前快照份额」的缺口，按单位成本暂缓对应成本。
            pending_usdt = 0.0
            expected = float(calib_shares.get(coin) or 0) + float(qty_net.get(coin) or 0)
            actual = float(row.get("shares") or 0)
            if expected > 0 and actual > 0 and usdt > 0:
                gap = expected - actual
                bought = float(qty_net.get(coin) or 0)
                # 只把「本次买入尚未体现到份额」的部分暂缓；缺口若超过成交净数量，
                # 说明是质押/空投等非成交原因导致份额变动，不做成本调整。
                if gap > max(1e-9, expected * 1e-5) and gap <= bought + max(1e-9, expected * 1e-5):
                    pending_usdt = gap * (usdt / expected)
                    usdt = max(0.0, usdt - pending_usdt)
                    print("      %s 有 %.8f 尚未进入份额，暂缓 %.2f USDT 成本" % (coin, gap, pending_usdt))
                elif actual > expected + max(1e-9, expected * 1e-5):
                    print("      %s 份额比成交多 %.8f（质押/空投等 0 成本增发），成本价自动摊薄" % (
                        coin, actual - expected))
            row["cost_pending_usdt"] = r2(pending_usdt, 4) if pending_usdt else 0
            cost_cny = r2(usdt * rate, 2)
            row["cost_cny"] = cost_cny
            row["cost_price"] = r2(usdt / float(row["shares"]), 4) if row.get("shares") else None
            row["pnl_cny"] = r2((row["value_cny"] or 0) - cost_cny, 2)
            row["pnl_pct"] = r2(row["pnl_cny"] / cost_cny * 100, 2) if cost_cny else None
            row["cost_source"] = "净入金校准 + Bitget 成交" + (
                "（含 %.2f USDT 成交待份额更新）" % pending_usdt if pending_usdt else "")

    trad_cny = sum(r["value_cny"] or 0 for r in trad_rows)
    crypto_cny = sum(r["value_cny"] or 0 for r in crypto_rows if r["group"] == CRYPTO_GROUP)
    stable_cash_cny = sum(r["value_cny"] or 0 for r in crypto_rows if r["group"] == CASH_GROUP)
    fiat_cash_cny = sum(r["value_cny"] or 0 for r in cash_rows)
    cash_cny = stable_cash_cny + fiat_cash_cny
    crypto_account_cny = crypto_cny + stable_cash_cny
    total_cny = trad_cny + crypto_account_cny + fiat_cash_cny
    trad_day = sum(r["day_change_cny"] or 0 for r in trad_rows)
    crypto_day = sum(r["day_change_cny"] or 0 for r in crypto_rows if r["group"] == CRYPTO_GROUP)
    day_change = trad_day + crypto_day + \
        sum(r["day_change_cny"] or 0 for r in crypto_rows if r["group"] == CASH_GROUP) + \
        sum(r["day_change_cny"] or 0 for r in cash_rows)
    trad_cost = sum(r["cost_cny"] or 0 for r in trad_rows)
    trad_pnl = sum(r["pnl_cny"] or 0 for r in trad_rows)
    cost_pending = [r["id"] for r in trad_rows if r.get("cost_pending") and r["shares"]]
    if cost_map:
        crypto_pnl_cny = r2(sum(r["pnl_cny"] or 0 for r in crypto_rows if r["group"] == CRYPTO_GROUP), 2)
        realized_map = load_realized_pnl()
        realized_cny = r2(sum(realized_map.values()) * rate, 2)
        if realized_cny:
            crypto_pnl_cny = r2(crypto_pnl_cny + realized_cny, 2)
            print("      已实现盈亏：%.2f USDT（%.2f CNY）已计入加密总盈亏" % (
                sum(realized_map.values()), realized_cny))
        crypto_pnl_usdt = r2(crypto_pnl_cny / rate, 2)
        # 加密盈亏百分比只以「币类成本」为分母，稳定币按面值不参与涨跌
        crypto_coin_cost_cny = r2(sum(r["cost_cny"] or 0 for r in crypto_rows if r["group"] == CRYPTO_GROUP), 2)
        crypto_pnl_pct_calc = r2(crypto_pnl_cny / crypto_coin_cost_cny * 100, 2) if crypto_coin_cost_cny else None
    else:
        crypto_pnl_usdt = crypto_meta.get("real_pnl_usdt")
        crypto_pnl_cny = crypto_pnl_usdt * rate if crypto_pnl_usdt is not None else None
    total_pnl = trad_pnl + (crypto_pnl_cny or 0) if (trad_cost or crypto_pnl_cny is not None) else None
    # 总盈亏的基准成本：传统成本 + 加密账户净入金（折算人民币）
    if cost_map:
        crypto_cost_cny = sum(r.get("cost_cny") or 0 for r in crypto_rows) + stable_cash_cny
    else:
        crypto_cost_cny = (crypto_meta.get("net_deposit_usdt") or 0) * rate
    total_cost_base = trad_cost + crypto_cost_cny
    total_pnl_pct = round(total_pnl / total_cost_base * 100, 2) if (total_pnl is not None and total_cost_base) else None
    pending = [r["id"] for r in trad_rows if r["pending"]]

    def weight(v):
        return round(v / total_cny * 100, 2) if total_cny else 0.0

    for r in trad_rows + crypto_rows + cash_rows:
        r["weight"] = weight(r["value_cny"] or 0)

    # ---- 历史快照累积 ----
    build_source = (os.environ.get("BUILD_SOURCE") or "auto").lower()
    entry = {
        "date": today,
        "updated_at": now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": build_source,
        "price_mode": crypto_meta.get("price_mode"),
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
        "items": [{"id": r["id"], "shares": r.get("shares"), "price": r.get("price")}
                  for r in trad_rows + crypto_rows + cash_rows],
    }

    # 当日数据以「自动 / 手动」两次构建中较晚的一次为准
    prev_today = None
    for x in snapshots:
        if x.get("date") == today:
            prev_today = x
            break
    keep_prev = False
    if prev_today and prev_today.get("updated_at"):
        try:
            if datetime.fromisoformat(prev_today["updated_at"]) > datetime.fromisoformat(entry["updated_at"]):
                keep_prev = True
        except ValueError:
            keep_prev = False

    # 趋势/日历用的 history：必须包含「今天」这一条（快照是在 dashboard 写出之后才落库的）
    hist = [{kk: sn.get(kk) for kk in ("date", "total_cny", "traditional_cny", "crypto_cny",
                                       "cash_cny", "day_change_cny", "day_change_pct",
                                       "fx_usdcny", "crypto_usdt")}
            for sn in snapshots if sn.get("date") != today]
    hist.append({"date": today, "total_cny": entry["total_cny"],
                 "traditional_cny": entry["traditional_cny"],
                 "crypto_cny": entry["crypto_cny"], "cash_cny": entry["cash_cny"],
                 "day_change_cny": entry["day_change_cny"],
                 "day_change_pct": entry["day_change_pct"],
                 "fx_usdcny": entry["fx_usdcny"], "crypto_usdt": entry["crypto_usdt"]})
    hist.sort(key=lambda x: x.get("date") or "")

    # 盈亏分析：各板块净盈亏 + 当日浮动收益，以及计算过程用到的数据
    def pnl_rows(rows, group_key):
        out = []
        for r in rows:
            prev = prev_items.get(r["id"]) or {}
            out.append({
                "id": r["id"],
                "name": r["name"],
                "shares": r.get("shares"),
                "prev_shares": prev.get("shares"),
                "prev_price": prev.get("price"),
                "prev_date": prev_snapshot_date,
                "price": r.get("price"),
                "currency": r.get("currency"),
                "fx": r2(rate if r.get("currency") == "USD" else (rate if r.get("currency") == "USDT" else 1.0), 4),
                "cost_price": r.get("cost_price"),
                "cost_cny": r.get("cost_cny"),
                "value_cny": r.get("value_cny"),
                "day_change_cny": r.get("day_change_cny"),
                "day_basis": r.get("day_basis"),
                "pnl_cny": r.get("pnl_cny"),
                "price_source": r.get("price_source"),
            })
        return out

    cash_all = [r for r in crypto_rows if r["group"] == CASH_GROUP] + cash_rows
    pnl_breakdown = {
        "prev_date": prev_snapshot_date,
        "fx_usdcny": r2(rate, 4),
        "generated_at": now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "groups": [
            {"key": "traditional", "name": "传统股票 & 基金",
             "pnl_cny": r2(trad_pnl, 2),
             "pnl_pct": r2(trad_pnl / trad_cost * 100, 2) if trad_cost else None,
             "cost_cny": r2(trad_cost, 2),
             "day_cny": r2(trad_day, 2),
             "day_pct": round(trad_day / (trad_cny - trad_day) * 100, 2) if (trad_cny - trad_day) else 0.0,
             "items": pnl_rows(trad_rows, "traditional")},
            {"key": "crypto", "name": "加密货币",
             "pnl_cny": r2(crypto_pnl_cny, 2) if crypto_pnl_cny is not None else None,
             "pnl_pct": crypto_pnl_pct_calc,
             "cost_cny": r2(crypto_coin_cost_cny, 2),
             "realized_cny": realized_cny,
             "day_cny": r2(crypto_day, 2),
             "day_pct": round(crypto_day / (crypto_cny - crypto_day) * 100, 2) if (crypto_cny - crypto_day) else 0.0,
             "items": pnl_rows([r for r in crypto_rows if r["group"] == CRYPTO_GROUP], "crypto")},
        ],
    }

    print("[5/5] 写出 dashboard.json …")
    generated_at = now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    # 份额新鲜度：holdings.json 的 updated_at 距今多少天，用于前端提醒核对
    h_upd = (holdings.get("meta") or {}).get("updated_at")
    shares_age = None
    if h_upd:
        try:
            shares_age = (now_cst() - datetime.fromisoformat(h_upd)).days + 1
        except Exception:
            shares_age = None
    dashboard = {
        "meta": {
            "holdings_updated_at": h_upd,
            "shares_age_days": shares_age,
            "title": "全维度资产统计",
            "subtitle": "传统股票/基金 + 加密货币 合并统计 · 份额 × 价格 = 市值",
            "version": (holdings.get("meta") or {}).get("version") or "1.0.0",
            "version_date": (holdings.get("meta") or {}).get("version_date") or PAGE_DATE,
            "generated_at": generated_at,
            "build_source": build_source,
            "crypto_price_mode": crypto_meta.get("price_mode"),
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
            "stable_cash_cny": r2(stable_cash_cny, 2),
            "fiat_cash_cny": r2(fiat_cash_cny, 2),
            "crypto_account_cny": r2(crypto_account_cny, 2),
            "traditional_weight": weight(trad_cny),
            "crypto_weight": weight(crypto_cny),
            "cash_weight": weight(cash_cny),
            "day_change_cny": r2(day_change, 2),
            "day_change_pct": round(day_change / (total_cny - day_change) * 100, 2)
            if total_cny - day_change else 0.0,
            "crypto_usdt": crypto_meta.get("total_usdt"),
            "count": len(trad_rows) + len(crypto_rows) + len(cash_rows),
            "pending_count": len(pending),
            "pending_ids": pending,
            "traditional_cost_cny": r2(trad_cost, 2),
            "traditional_pnl_cny": r2(trad_pnl, 2),
            "traditional_day_change_cny": r2(trad_day, 2),
            "traditional_day_change_pct": round(trad_day / (trad_cny - trad_day) * 100, 2)
            if (trad_cny - trad_day) else 0.0,
            "traditional_pnl_pct": r2(trad_pnl / trad_cost * 100, 2) if trad_cost else None,
            "cost_pending_count": len(cost_pending),
            "cost_pending_ids": cost_pending,
            "crypto_pnl_cny": r2(crypto_pnl_cny, 2),
            "crypto_realized_cny": realized_cny,
            "crypto_day_change_cny": r2(crypto_day, 2),
            "crypto_day_change_pct": round(crypto_day / (crypto_cny - crypto_day) * 100, 2)
            if (crypto_cny - crypto_day) else 0.0,
            "crypto_pnl_usdt": crypto_pnl_usdt,
            "crypto_pnl_pct": crypto_pnl_pct_calc,
            "total_pnl_cny": r2(total_pnl, 2),
            "total_pnl_pct": total_pnl_pct,
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
                "name": "现金",
                "cny": r2(cash_cny, 2),
                "weight": weight(cash_cny),
                "count": len([r for r in crypto_rows if r["group"] == CASH_GROUP]) + len(cash_rows),
                "items": [r["id"] for r in crypto_rows if r["group"] == CASH_GROUP] +
                         [r["id"] for r in cash_rows],
            },
        ],
        "items": trad_rows + crypto_rows + cash_rows,
        "crypto_meta": crypto_meta,
        "pnl_breakdown": pnl_breakdown,
        "history": hist[-400:],
    }
    save_json(dashboard_path, dashboard)

    # 快照落库：带上当日完整明细，供首页「历史快照」整页复现
    if not keep_prev:
        entry["pnl_breakdown"] = pnl_breakdown
        entry["summary"] = dashboard["summary"]
        entry["groups"] = dashboard["groups"]
        entry["items"] = dashboard["items"]
    if keep_prev:
        print("      今日快照已由更晚的一次构建写入（%s），保留原记录" % prev_today.get("updated_at"))
        entry = prev_today
    snapshots = [x for x in snapshots if x.get("date") != today] + [entry]
    snapshots.sort(key=lambda x: x.get("date") or "")
    prev_total = None
    for sn in snapshots:
        if sn.get("day_change_cny") is None and prev_total is not None:
            d = (sn.get("total_cny") or 0) - prev_total
            sn["day_change_cny"] = r2(d, 2)
            sn["day_change_pct"] = round(d / prev_total * 100, 2) if prev_total else 0.0
        prev_total = sn.get("total_cny")
    save_json(snapshots_path, snapshots)

    print("\n合计：传统 %.2f + 加密 %.2f = %.2f CNY" % (trad_cny, crypto_cny, total_cny))
    if pending:
        print("待填写份额的标的：%s" % ", ".join(pending))
    return 0


if __name__ == "__main__":
    sys.exit(main())
