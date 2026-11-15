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
PAGE_VERSION = "1.10.14"
PAGE_DATE = "2026.11.15"
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


def load_crypto_sell_entries():
    """加密逐笔卖出明细（累积，不限 90 天）：来自成交回放。"""
    f = Path(ROOT) / "data" / "bitget_ledger.json"
    if not f.exists():
        return []
    try:
        p = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return list(p.get("sell_entries") or [])


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


ANA_KINDS = {"money", "signed", "pct", "int"}


def build_daily_analysis(*, today, total_cny, day_change, summary, groups, items,
                         events, rate, realized_entries, price_mode, shares_age,
                         pending, cost_pending, generated_at, history=None):
    """按当日数据生成摘要模板：数字用 {token} 占位，前端按当前币种填充后再展示。"""
    values = {}

    def tok(key, v, kind="money"):
        values[key] = {"v": r2(v or 0, 2), "kind": kind}
        return "{" + key + "}"

    def signed(key, v):
        return tok(key, v, "signed")

    def ratio(key, v):
        return tok(key, v, "ratio")

    day_pct = summary.get("day_change_pct") or 0
    bullets = []

    # 1. 当日盈亏 + 累计 + 区间
    movers = [r for r in items if isinstance(r.get("day_change_cny"), (int, float))]
    movers.sort(key=lambda r: r["day_change_cny"] or 0, reverse=True)
    up = [r for r in movers if (r.get("day_change_cny") or 0) > 30][:2]
    down = [r for r in movers if (r.get("day_change_cny") or 0) < -30][-2:][::-1]
    t1 = "总资产 %s，今日 %s（%s）；传统 %s，加密货币 %s。" % (
        tok("total", total_cny), signed("day", day_change), tok("pct", day_pct, "pct"),
        signed("trad_day", summary.get("traditional_day_change_cny") or 0),
        signed("crypto_day", summary.get("crypto_day_change_cny") or 0),
    )
    detail = []
    if up:
        detail.append("贡献 " + "、".join(
            "%s %s" % (r["id"], signed("up%d" % (i + 1), r["day_change_cny"])) for i, r in enumerate(up)))
    if down:
        detail.append("拖累 " + "、".join(
            "%s %s" % (r["id"], signed("down%d" % (i + 1), r["day_change_cny"])) for i, r in enumerate(down)))
    if detail:
        t1 += " ".join(detail) + "。"
    t1 += "累计总盈亏 %s（%s），其中加密 %s、传统 %s。" % (
        signed("pnl_total", summary.get("total_pnl_cny") or 0),
        tok("pnl_pct", summary.get("total_pnl_pct") or 0, "pct"),
        signed("pnl_crypto", summary.get("crypto_pnl_cny") or 0),
        signed("pnl_trad", summary.get("traditional_pnl_cny") or 0),
    )
    hist = [h for h in (history or []) if isinstance(h.get("day_change_cny"), (int, float))]
    if len(hist) >= 3:
        win = hist[-30:]
        first_total = win[0].get("total_cny") or 0
        chg = sum(h.get("day_change_cny") or 0 for h in win[1:]) if len(win) > 1 else 0
        best = max(win, key=lambda h: h.get("day_change_cny") or 0)
        worst = min(win, key=lambda h: h.get("day_change_cny") or 0)
        rng_pct = (chg / first_total * 100) if first_total else 0
        if abs(best.get("day_change_cny") or 0) >= 30 or abs(worst.get("day_change_cny") or 0) >= 30:
            t1 += "近 %d 日累计 %s（%s），最佳 %s（%s）、最差 %s（%s）。" % (
                len(win), signed("range_chg", chg), tok("range_pct", rng_pct, "pct"),
                (best.get("date") or "")[5:], signed("best_day", best.get("day_change_cny") or 0),
                (worst.get("date") or "")[5:], signed("worst_day", worst.get("day_change_cny") or 0),
            )
        else:
            t1 += "近 %d 日累计 %s（%s）。" % (len(win), signed("range_chg", chg), tok("range_pct", rng_pct, "pct"))
    bullets.append({"label": "盈亏", "text": t1, "tone": "pos" if day_change >= 0 else "neg"})

    # 2. 结构（含加密集中度）
    w_trad = summary.get("traditional_weight") or 0
    w_crypto = summary.get("crypto_weight") or 0
    w_cash = summary.get("cash_weight") or 0
    crypto_rows = [r for r in items if r.get("group") == "crypto"]
    crypto_val = sum(float(r.get("value_cny") or 0) for r in crypto_rows) or 0
    t2 = "结构：加密 %s、传统 %s、现金 %s。" % (
        ratio("w_crypto", w_crypto), ratio("w_trad", w_trad), ratio("w_cash", w_cash))
    top = sorted(crypto_rows, key=lambda r: float(r.get("value_cny") or 0), reverse=True)[:2]
    if crypto_val and len(top) >= 2:
        parts = ["%s %s（%s）" % (
            r["id"], tok("val_%s" % r["id"].lower(), float(r.get("value_cny") or 0)),
            ratio("share_%s" % r["id"].lower(), float(r.get("value_cny") or 0) / crypto_val * 100))
            for r in top]
        t2 += "币值集中在 " + "与".join(parts) + "，合计 %s。" % ratio(
            "share_top2", sum(float(r.get("value_cny") or 0) for r in top) / crypto_val * 100)
    else:
        t2 += "加密账户合计 %s。" % tok("crypto_val", crypto_val)
    bullets.append({"label": "结构", "text": t2, "tone": "muted"})

    # 3. 出入金（取最近一个有记录的日子，避免当日无流水时误报为 0）
    flows = events.get("flows") or []
    transfer_rows = events.get("transfers") or []
    flow_days = sorted({x.get("day") for x in flows if x.get("day")})
    last_flow_day = flow_days[-1] if flow_days else None
    net = events.get("net_deposit") or {}
    net_total = tok("net_total", (net.get("computed_total_usdt") or net.get("baseline_total_usdt") or 0) * rate)
    net_crypto = tok("net_crypto", (net.get("computed_usdt") or net.get("baseline_usdt") or 0) * rate)
    if last_flow_day:
        din = sum(float(x.get("value_usdt") or 0) for x in flows
                  if x.get("day") == last_flow_day and x.get("direction") == "入金")
        dout = sum(float(x.get("value_usdt") or 0) for x in flows
                   if x.get("day") == last_flow_day and x.get("direction") == "出金")
        when = "今日" if last_flow_day == today else "最近一笔（" + last_flow_day[5:] + "）"
        parts = []
        if din:
            parts.append("入金 %s USDT（约 %s）" % (format(din, ",.2f"), tok("din", din * rate)))
        if dout:
            parts.append("出金 %s USDT（约 %s）" % (format(dout, ",.2f"), tok("dout", dout * rate)))
        body = "，".join(parts) if parts else "无链上出入金"
        t3 = "%s链上%s；净入金总额 %s，加密账户口径 %s。" % (when, body, net_total, net_crypto)
    else:
        t3 = "窗口内暂无链上出入金记录；净入金总额 %s。" % net_total
    stock_in = sum(float(x.get("value_usdt") or 0) for x in transfer_rows
                   if "美股" in str(x.get("kind") or "") and str(x.get("kind") or "").startswith("划入"))
    if stock_in:
        t3 += "划入美股账户 %s，属内部划转。" % tok("stock_in", stock_in * rate)
    after = float(net.get("deposit_after") or 0) + float(net.get("withdraw_after") or 0)
    if not after:
        t3 += "本期无新增链上充值或提现，变动来自价格。"
    bullets.append({"label": "出入金", "text": t3, "tone": "muted"})

    # 4. 理财生息（含折年化）
    earn = events.get("earn_daily") or []
    earn_days = sorted({x.get("day") for x in earn if x.get("day")})
    if earn_days:
        last_earn_day = earn_days[-1]
        rows = [x for x in earn if x.get("day") == last_earn_day]
        val = sum(float(x.get("value_usdt") or 0) for x in rows)
        cnt = sum(int(x.get("count") or 0) for x in rows)
        coins = sorted({x.get("coin") for x in rows})
        win_start = datetime.fromisoformat(today).date() - timedelta(days=29)
        val30 = sum(float(x.get("value_usdt") or 0) for x in earn
                    if x.get("day") and datetime.fromisoformat(x["day"]).date() >= win_start)
        base_usdt = summary.get("crypto_usdt") or 0
        t4 = "%s派息 %s USDT（%s，%d 笔）；近 30 日 %s，约 %s" % (
            "今日" if last_earn_day == today else last_earn_day[5:],
            format(val, ",.2f"), "、".join(coins) or "—", cnt,
            format(val30, ",.2f"), tok("earn30", val30 * rate),
        )
        if base_usdt and val30:
            t4 += "，折年化约 %s。" % ratio("earn_apr", val30 * 365 / 30 / base_usdt * 100)
        else:
            t4 += "。"
    else:
        t4 = "窗口内暂无理财派息记录。"
    bullets.append({"label": "理财生息", "text": t4, "tone": "muted"})

    # 5. 已实现
    if realized_entries:
        today_n = sum(1 for x in realized_entries if str(x.get("date") or "")[:10] == today)
        t5 = "已实现累计：加密 %s、传统 %s，共 %d 笔%s；其余为未实现。" % (
            signed("real_crypto", summary.get("crypto_realized_cny") or 0),
            signed("real_trad", summary.get("traditional_realized_cny") or 0),
            len(realized_entries),
            "，其中今日 %d 笔" % today_n if today_n else "",
        )
    else:
        t5 = "暂无卖出记录，已实现 %s；账面盈亏均为未实现。" % signed("real_total", 0)
    bullets.append({"label": "已实现", "text": t5, "tone": "muted"})

    # 6. 待办
    notes = []
    if shares_age and shares_age >= 3:
        notes.append("份额已 %d 天未更新，建议核对持仓。" % shares_age)
    if price_mode and price_mode != "live":
        notes.append("本次币价使用快照回退，涨跌仅供参考。")
    if pending:
        notes.append("%d 个标的待填份额：%s。" % (len(pending), "、".join(pending[:3])))
    if cost_pending:
        notes.append("%d 个标的待填成本价：%s。" % (len(cost_pending), "、".join(cost_pending[:3])))
    if notes:
        bullets.append({"label": "待办", "text": " ".join(notes), "tone": "warn"})
    else:
        bullets.append({"label": "待办", "text": "份额、成本价、币价均为最新，无需处理。", "tone": "muted"})

    # ---- 供「自由叙述」使用的额外占位符与事实清单（前端同日按币种渲染） ----
    def raw(key, v, kind="usdt", text=None):
        values[key] = {"v": v, "kind": kind}
        if text is not None:
            values[key]["text"] = text
        return "{" + key + "}"

    flow_date_tok = raw("flow_date", 0, "date", last_flow_day[5:] if last_flow_day else "—")
    dout_usdt = 0
    if last_flow_day:
        dout_usdt = sum(float(x.get("value_usdt") or 0) for x in flows
                        if x.get("day") == last_flow_day and x.get("direction") == "出金")
    dout_usdt_tok = raw("dout_usdt", dout_usdt, "usdt")
    earn_today_tok = "{earn_today}"
    earn30_usdt_tok = "{earn30_usdt}"
    earn_cnt_tok = "{earn_cnt}"
    coins_txt = "—"
    val_today = 0.0
    cnt_today = 0
    val30 = 0.0
    if earn_days:
        le = earn_days[-1]
        rows = [x for x in earn if x.get("day") == le]
        val_today = sum(float(x.get("value_usdt") or 0) for x in rows)
        cnt_today = sum(int(x.get("count") or 0) for x in rows)
        coins_txt = "、".join(sorted({x.get("coin") for x in rows})) or "—"
        val30 = sum(float(x.get("value_usdt") or 0) for x in earn
                    if x.get("day") and datetime.fromisoformat(x["day"]).date() >= win_start)
    raw("earn_today", val_today, "usdt")
    raw("earn30_usdt", val30, "usdt")
    raw("earn_cnt", cnt_today, "int")
    raw("crypto_day_pct", summary.get("crypto_day_change_pct") or 0, "pct")
    raw("pnl_crypto_pct", summary.get("crypto_pnl_pct") or 0, "pct")
    raw("pnl_trad_pct", summary.get("traditional_pnl_pct") or 0, "pct")
    raw("crypto_account", summary.get("crypto_account_cny") or 0, "money")
    raw("stable_cash", summary.get("stable_cash_cny") or 0, "money")
    raw("alipay", summary.get("fiat_cash_cny") or 0, "money")
    raw("range_days", len(hist[-30:]) if hist else 1, "int")
    raw("sold_cnt", len(realized_entries or []), "int")
    raw("shares_age", shares_age or 0, "int")
    for r in crypto_rows:
        tok("val_%s" % r["id"].lower(), float(r.get("value_cny") or 0))

    facts = [
        "总资产 %s，今日 %s（%s）" % ("{total}", "{day}", "{pct}"),
        "传统日变动 %s，加密日变动 %s，加密日涨幅 %s" % ("{trad_day}", "{crypto_day}", "{crypto_day_pct}"),
        "累计总盈亏 %s（%s），其中加密 %s（%s）、传统 %s（%s）" % (
            "{pnl_total}", "{pnl_pct}", "{pnl_crypto}", "{pnl_crypto_pct}", "{pnl_trad}", "{pnl_trad_pct}"),
        "近 {range_days} 日累计 {range_chg}（{range_pct}）" + (
            "，最佳 %s（{best_day}）、最差 %s（{worst_day}）" % (
                (best.get("date") or "")[5:], (worst.get("date") or "")[5:]) if len(hist) >= 3 else ""),
        "结构：加密 {w_crypto}、传统 {w_trad}、现金 {w_cash}；加密账户口径 {crypto_account}，其中稳定币 {stable_cash}",
        "加密内部：BTC {val_btc}（{share_btc}）、SOL {val_sol}（{share_sol}）、BGB {val_bgb}",
        "净入金总额 {net_total}，加密账户口径 {net_crypto}，划入美股 {stock_in}（内部划转）",
        "最近一次链上出金 %s，%s USDT（约 %s）；本期新增链上充值/提现为 0" % (
            flow_date_tok, dout_usdt_tok, "{dout}" if dout_usdt else "{dout}"),
        "理财：今日派息 %s USDT（%s，%s 笔），近 30 日 %s USDT（约 %s），折年化 %s" % (
            earn_today_tok, coins_txt or "—", earn_cnt_tok, earn30_usdt_tok, "{earn30}", "{earn_apr}"),
        "已实现盈亏 %s，卖出 %s 笔" % ("{real_total}", "{sold_cnt}"),
        "支付宝现金 {alipay}；持仓份额已 {shares_age} 天未更新",
    ]

    if abs(day_change) < 0.5 or abs(day_pct) < 0.01:
        headline = "今日资产 {total}，与上一交易日基本持平"
    elif day_change > 0:
        headline = "今日资产 {total}，上涨 {day}（{pct}）"
    else:
        headline = "今日资产 {total}，下跌 {day_abs}（{pct}）"
        values["day_abs"] = {"v": r2(abs(day_change), 2), "kind": "abs"}
    if movers:
        lead = max(movers, key=lambda r: abs(r.get("day_change_cny") or 0))
        if abs(lead.get("day_change_cny") or 0) > 0.5:
            headline += "；波动主要来自 %s" % lead["id"]
    headline += "。"

    return {
        "date": today,
        "generated_at": generated_at,
        "price_mode": price_mode,
        "headline": headline,
        "tone": "pos" if day_change >= 0 else "neg",
        "bullets": bullets,
        "values": values,
        "day_change_cny": r2(day_change, 2),
        "day_change_pct": summary.get("day_change_pct"),
        "source": "rules",
        "facts": facts,
    }


def decl(v, key, values, kind="money"):
    values[key] = {"v": r2(v or 0, 2), "kind": kind}


def llm_polish(analysis):
    """让模型基于事实清单自由叙述当日观察：
    - 内容/顺序/取舍自由，可归因、可对比、可点评中性事实；
    - 但所有数字必须写成 {占位符}，不得出现裸数字，不得新增占位符，不得自行推算；
    - 任何违规都整段弃用，退回规则文案。
    """
    import json as _json
    import os
    import re as _re
    import socket
    import urllib.request

    key = os.environ.get("LLM_API_KEY") or os.environ.get("ARK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        analysis["ai"] = {"used": False, "reason": "no_key"}
        return analysis
    base = (os.environ.get("LLM_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").strip()
    if base.rstrip("/").endswith("/chat/completions"):
        url = base.rstrip("/")
    else:
        url = base.rstrip("/") + "/chat/completions"
    model = os.environ.get("LLM_MODEL") or "doubao-seed-1-6-250615"

    facts = analysis.get("facts") or []
    allowed = set((analysis.get("values") or {}).keys())
    prompt = (
        "你是个人资产仪表台的撰写者。下面是今天的真实数据，每一项都带有占位符。\n"
        "请写一份「当日资产观察」：2~3 段自然叙述，全文 300~420 字，第一段给总判断，第二段讲今天的变化与原因，"
        "第三段点出一两个值得留意的结构事实。语言自然、克制，像人复盘，不要小标题、不要列表、不要客套。\n\n"
        "硬规则：\n"
        "1. 所有数字（金额、比例、笔数、日期、天数）必须原样写成给定的 {占位符}，禁止出现任何裸数字或中文数字金额（如「三成」「两笔」）。\n"
        "2. 只能使用下面出现过的占位符，不得新增、不得改写占位符名字。\n"
        "3. 不得自行加减乘除推算新数字，不得加入数据里没有的事实。\n"
        "4. 不做买卖建议、不预测价格、不做好坏评价。\n"
        "5. 只输出 JSON：{\"paragraphs\": [\"第一段\", \"第二段\", \"第三段\"]}，不要解释。\n\n"
        "数据：\n" + "\n".join("- " + f for f in facts)
    )
    payload = {"model": model,
               "messages": [{"role": "system", "content": "你只做中文资产观察写作，严格遵守占位符规则，输出 JSON。"},
                            {"role": "user", "content": prompt}],
               "temperature": 0.6}
    req = urllib.request.Request(url, data=_json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        data = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                break
            except (TimeoutError, socket.timeout):
                if attempt == 1:
                    raise
        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        out = _json.loads(text)
        paras = [str(x).strip() for x in (out.get("paragraphs") or []) if str(x).strip()]
        if not (1 <= len(paras) <= 5):
            analysis["ai"] = {"used": False, "reason": "bad_shape"}
            return analysis
        used, bad, naked = [], [], []
        for para in paras:
            used += _re.findall(r"\{([a-z0-9_]+)\}", para)
            naked += _re.findall(r"[0-9]", _re.sub(r"\{[a-z0-9_]+\}", "", para))
        for name in used:
            if name not in allowed:
                bad.append(name)
        if bad:
            analysis["ai"] = {"used": False, "reason": "invalid_tokens:" + ",".join(sorted(set(bad))[:5])}
            return analysis
        if naked:
            analysis["ai"] = {"used": False, "reason": "naked_digits:%d" % len(naked)}
            return analysis
        if len(set(used)) < 3:
            analysis["ai"] = {"used": False, "reason": "too_few_facts"}
            return analysis
        total = sum(len(x) for x in paras)
        if total > 620:
            analysis["ai"] = {"used": False, "reason": "too_long:%d" % total}
            return analysis
        analysis["freeform"] = paras
        analysis["ai"] = {"used": True, "model": model, "mode": "freeform", "chars": total,
                          "facts_used": len(set(used))}
    except Exception as exc:
        detail = ""
        body = getattr(exc, "read", None)
        if body:
            try:
                detail = " | body=" + body().decode("utf-8", "ignore")[:200]
            except Exception:
                detail = ""
        analysis["ai"] = {"used": False,
                          "reason": type(exc).__name__ + ": " + str(exc)[:100] + detail,
                          "url": url, "model": model}
    return analysis


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
    # 净入金：以加密流水归档的「基准 + 基准日之后链上充提」为准，不再依赖上游仪表台
    events = _read_json(os.path.join(ROOT, "data", "crypto_events.json"))
    if events and (events.get("net_deposit") or {}).get("computed_usdt") is not None:
        crypto_meta["net_deposit_usdt"] = r2(events["net_deposit"]["computed_usdt"], 2)
        print("      净入金（充值口径）：%.2f USDT（基准 %.0f @ %s，之后入 %.2f / 出 %.2f）" % (
            crypto_meta["net_deposit_usdt"], events["net_deposit"]["baseline_usdt"],
            events["net_deposit"]["baseline_date"], events["net_deposit"]["deposit_after"],
            events["net_deposit"]["withdraw_after"]))
    if crypto_meta.get("error"):
        print("      [warn] " + crypto_meta["error"])
    else:
        print("      快照 %s，共 %s 个币种，合计 %.2f USDT" % (
            crypto_meta.get("snapshot_date"), crypto_meta.get("coin_count"),
            crypto_meta.get("total_usdt") or 0))

    # ---- 传统已实现：来自后台手工录入的卖出记录 ----
    def load_trade_ledger(holdings, rate):
        """手工卖出记录 → 传统已实现盈亏（CNY）。成本价取该标的当前成本价（平均成本法，卖出后不变）。"""
        cmap = {}
        for h in (holdings.get("traditional") or []):
            cmap[str(h.get("id") or "").upper()] = h
        rows = []
        for e in (holdings.get("trade_ledger") or []):
            hid = str(e.get("id") or e.get("symbol") or "").strip().upper()
            if not hid:
                continue
            h = cmap.get(hid) or {}
            cur = str(h.get("currency") or e.get("currency") or "USD").upper()
            try:
                shares = float(e.get("shares") or 0)
                price = float(e.get("price") or 0)
                amount = float(e.get("amount") or 0) or shares * price
                cp = float(h.get("cost_price") or e.get("cost_price") or 0)
            except (TypeError, ValueError):
                continue
            if shares <= 0 or cp <= 0:
                continue
            pnl_native = amount - shares * cp
            fx = rate if cur == "USD" else 1.0
            rows.append({
                "date": str(e.get("date") or ""), "id": hid, "currency": cur,
                "shares": round(shares, 8), "price": round(price, 4),
                "cost_price": round(cp, 4),
                "pnl_native": round(pnl_native, 2),
                "pnl_cny": r2(pnl_native * fx, 2),
                "price_cny": r2(price * fx, 4),
                "cost_price_cny": r2(cp * fx, 4),
                "note": str(e.get("note") or ""),
            })
        rows.sort(key=lambda x: x["date"], reverse=True)
        return rows

    # 手工维护的现金账户（支付宝余额等），与稳定币一起计入「现金」组
    cash_rows = []
    for ca in (holdings.get("cash_accounts") or []):
        cur = str(ca.get("currency") or "CNY").upper()
        if cur == "USD":
            amt = float(ca.get("amount_usd") or 0) * rate
        else:
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
            "updated_at": ca.get("updated_at") or "",
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
    trad_realized_entries = load_trade_ledger(holdings, rate)
    trad_realized_cny = r2(sum(x["pnl_cny"] for x in trad_realized_entries), 2)
    if trad_realized_entries:
        print("      传统已实现：%d 笔卖出记录，合计 %.2f CNY" % (
            len(trad_realized_entries), trad_realized_cny))

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
    trad_unrealized = sum(r["pnl_cny"] or 0 for r in trad_rows)
    trad_pnl = r2(trad_unrealized + trad_realized_cny, 2)
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
    # 加密账户口径成本（收益率分母，剔除划往美股账户的部分）
    if cost_map:
        crypto_cost_cny = sum(r.get("cost_cny") or 0 for r in crypto_rows) + stable_cash_cny
    else:
        crypto_cost_cny = (crypto_meta.get("net_deposit_usdt") or 0) * rate

    # 总盈亏 = 传统净盈亏 + 加密净盈亏（现金按面值不产生盈亏）
    total_pnl = r2(trad_pnl + (crypto_pnl_cny or 0), 2)
    # 收益率分母：传统成本 + 加密账户净入金（不含闲置现金，避免被现金稀释）
    total_cost_base = r2(trad_cost + crypto_cost_cny, 2)
    total_pnl_pct = round(total_pnl / total_cost_base * 100, 2) if total_cost_base else None
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
        "crypto_coin_cny": r2(crypto_cny, 2),
        "stable_cash_cny": r2(stable_cash_cny, 2),
        "total_pnl_cny": r2(total_pnl, 2) if total_pnl is not None else None,
        "traditional_pnl_cny": r2(trad_pnl, 2),
        "crypto_pnl_cny": r2(crypto_pnl_cny, 2) if crypto_pnl_cny is not None else None,
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
    def snap_field(sn, key):
        v = sn.get(key)
        if v is None:
            v = (sn.get("summary") or {}).get(key)
        if v is None and key.endswith("_pnl_cny"):
            # 老快照兜底：按当日明细逐项求和（现金项盈亏恒为 0）
            want = {"total_pnl_cny": None, "traditional_pnl_cny": "traditional",
                    "crypto_pnl_cny": "crypto"}[key]
            items = sn.get("items") or []
            v = round(sum((i.get("pnl_cny") or 0) for i in items
                          if (want is None or i.get("group") == want)), 2)
        if v is None and key in ("crypto_coin_cny", "stable_cash_cny"):
            # 老快照兜底：按当日分组（crypto = 币类，cash = 稳定币+法币余额）取值
            for g in (sn.get("groups") or []):
                if (key == "crypto_coin_cny" and g.get("key") == "crypto") or \
                   (key == "stable_cash_cny" and g.get("key") == "cash"):
                    v = g.get("cny")
                    break
        return v

    hist = [{kk: snap_field(sn, kk) for kk in ("date", "total_cny", "traditional_cny", "crypto_cny",
                                               "cash_cny", "day_change_cny", "day_change_pct",
                                               "fx_usdcny", "crypto_usdt", "crypto_coin_cny",
                                               "stable_cash_cny", "total_pnl_cny",
                                               "traditional_pnl_cny", "crypto_pnl_cny")}
            for sn in snapshots if sn.get("date") != today]
    hist.append({"date": today, "total_cny": entry["total_cny"],
                 "traditional_cny": entry["traditional_cny"],
                 "crypto_cny": entry["crypto_cny"], "cash_cny": entry["cash_cny"],
                 "day_change_cny": entry["day_change_cny"],
                 "day_change_pct": entry["day_change_pct"],
                 "fx_usdcny": entry["fx_usdcny"], "crypto_usdt": entry["crypto_usdt"],
                 "crypto_coin_cny": entry["crypto_coin_cny"],
                 "stable_cash_cny": entry["stable_cash_cny"],
                 "total_pnl_cny": entry["total_pnl_cny"],
                 "traditional_pnl_cny": entry["traditional_pnl_cny"],
                 "crypto_pnl_cny": entry["crypto_pnl_cny"]})
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

    # 逐笔已实现明细（累积，供「盈亏分析」里的两个模块展示）
    crypto_detail = []
    for e in load_crypto_sell_entries():
        try:
            pnl_cny = r2(float(e.get("pnl_usdt") or 0) * rate, 2)
        except (TypeError, ValueError):
            pnl_cny = 0.0
        crypto_detail.append({
            "date": e.get("date") or "", "coin": e.get("coin") or "",
            "shares": e.get("shares"), "price": e.get("price"),
            "cost_price": e.get("cost_price"),
            "pnl_usdt": e.get("pnl_usdt"), "pnl_cny": pnl_cny,
            "proceeds_usdt": e.get("proceeds"),
        })
    trad_detail = [{"date": x.get("date") or "", "id": x.get("id") or "",
                    "currency": x.get("currency"), "shares": x.get("shares"),
                    "price": x.get("price"), "cost_price": x.get("cost_price"),
                    "price_cny": x.get("price_cny"), "cost_price_cny": x.get("cost_price_cny"),
                    "pnl_cny": x.get("pnl_cny"), "note": x.get("note")}
                   for x in trad_realized_entries]

    cash_all = [r for r in crypto_rows if r["group"] == CASH_GROUP] + cash_rows
    pnl_breakdown = {
        "prev_date": prev_snapshot_date,
        "fx_usdcny": r2(rate, 4),
        "generated_at": now_cst().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "groups": [
            {"key": "traditional", "name": "传统股票 & 基金",
             "pnl_cny": r2(trad_pnl, 2),
             "unrealized_cny": r2(trad_unrealized, 2),
             "realized_cny": r2(trad_realized_cny, 2),
             "realized_entries": trad_realized_entries,
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
            "traditional_unrealized_cny": r2(trad_unrealized, 2),
            "traditional_realized_cny": r2(trad_realized_cny, 2),
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
        "events": events,
        "pnl_breakdown": pnl_breakdown,
        "realized_detail": {"crypto": crypto_detail, "traditional": trad_detail},
        "history": hist[-400:],
    }
    # ---------- 当日资产分析（自动摘要） ----------
    dashboard["analysis"] = build_daily_analysis(
        today=today,
        total_cny=total_cny,
        day_change=day_change,
        summary=dashboard["summary"],
        groups=dashboard["groups"],
        items=dashboard["items"],
        events=events or {},
        rate=rate,
        realized_entries=(crypto_detail or []) + (trad_detail or []),
        price_mode=crypto_meta.get("price_mode"),
        shares_age=dashboard["meta"].get("shares_age_days"),
        pending=pending,
        cost_pending=cost_pending,
        generated_at=dashboard["meta"].get("generated_at"),
        history=hist,
    )
    dashboard["analysis"] = llm_polish(dashboard["analysis"])
    ai = dashboard["analysis"].get("ai") or {}
    print("      当日分析：%s" % ("AI 润色成功（%s）" % ai.get("model") if ai.get("used")
                                 else "规则文案（未润色：%s）" % ai.get("reason")))

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
