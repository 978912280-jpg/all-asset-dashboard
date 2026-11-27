#!/usr/bin/env python3
"""从 Bitget 现货成交记录累计每个币的净投入（成本总额 USDT）。

只使用只读接口 /api/v2/spot/trade/fills，需要环境变量：
  BITGET_KEY / BITGET_SECRET / BITGET_PASSPHRASE
累计结果写到 data/bitget_ledger.json（只含聚合金额与笔数，不含任何密钥）。
"""
import base64, hashlib, hmac, json, os, time
import urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://api.bitget.com"
LEDGER = Path(__file__).resolve().parent.parent / "data" / "bitget_ledger.json"
CST = timezone(timedelta(hours=8))


def _sign(secret, ts, method, path, query=""):
    pre = ts + method.upper() + path + query
    mac = hmac.new(secret.encode(), pre.encode(), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()


def _get(path, params, key, secret, passphrase, timeout=20):
    ts = str(int(time.time() * 1000))
    query = "&".join("%s=%s" % (k, params[k]) for k in sorted(params))
    headers = {
        "ACCESS-KEY": key,
        "ACCESS-SIGN": _sign(secret, ts, "GET", path, ("?" + query) if query else ""),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": passphrase,
        "locale": "zh-CN",
        "Content-Type": "application/json",
    }
    url = BASE + path + (("?" + query) if query else "")
    req = urllib.request.Request(url, headers=headers)
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s %s" % (e.code, e.read()[:160]))
    body = json.loads(raw)
    if str(body.get("code")) != "00000":
        raise RuntimeError("API %s %s" % (body.get("code"), body.get("msg")))
    return body.get("data") or []


def _fetch_fills_v3(key, secret, passphrase, start_ms, log=print):
    """UTA 统一账户（v3）现货成交，规范成与 v2 相同的字段，供 replay 复用。

    只取 category=SPOT：币本位合约的成交单位是「张/美元」，混进来会污染币的份额。
    """
    out, now_ms = [], int(datetime.now(CST).timestamp() * 1000)
    win = 7 * 86400 * 1000
    cur = int(start_ms)
    while cur < now_ms:
        nxt = min(cur + win, now_ms)
        rows = _get("/api/v3/trade/fills",
                    {"category": "SPOT", "startTime": str(cur), "endTime": str(nxt), "limit": "100"},
                    key, secret, passphrase)
        data = rows if isinstance(rows, list) else (rows.get("list") if isinstance(rows, dict) else []) or []
        for r in data:
            sym = str(r.get("symbol") or "").upper()
            coin = sym[:-4] if sym.endswith("USDT") else ""
            if not coin:
                continue
            fee_total, fee_coin = 0.0, ""
            for fd in (r.get("feeDetail") or []):
                try:
                    fee_total += float(fd.get("fee") or 0)
                except (TypeError, ValueError):
                    pass
                fee_coin = fee_coin or str(fd.get("feeCoin") or "")
            out.append({
                "coin": coin, "symbol": sym, "side": r.get("side"),
                "size": r.get("execQty"), "priceAvg": r.get("execPrice"),
                "amount": r.get("execValue"),
                "feeDetail": {"totalFee": fee_total, "feeCoin": fee_coin},
                "cTime": r.get("createdTime"),
                "tradeId": r.get("execId"),
            })
        cur = nxt
        time.sleep(0.25)
    out.sort(key=lambda x: int(x.get("cTime") or 0))
    log("    Bitget 成交记录（v3）：%d 笔" % len(out))
    return out


def fetch_fills(key, secret, passphrase, start_ms, log=print):
    """翻页拉取 start_ms 之后的所有现货成交，按时间升序返回。"""
    try:
        return _fetch_fills_v2(key, secret, passphrase, start_ms, log=log)
    except Exception as e:  # noqa: BLE001
        if "40085" not in str(e):
            raise
        log("    [warn] 账户已升级统一账户（40085），改用 v3 成交接口")
        return _fetch_fills_v3(key, secret, passphrase, start_ms, log=log)


def _fetch_fills_v2(key, secret, passphrase, start_ms, log=print):
    out, cursor, pages = [], None, 0
    while pages < 30:
        params = {"limit": "100", "startTime": str(start_ms)}
        if cursor:
            params["idLessThan"] = cursor
        rows = _get("/api/v2/spot/trade/fills", params, key, secret, passphrase)
        if not rows:
            break
        out.extend(rows)
        cursor = rows[-1].get("tradeId") or rows[-1].get("orderId")
        pages += 1
        if len(rows) < 100:
            break
        time.sleep(0.25)
    out.sort(key=lambda x: int(x.get("cTime") or 0))
    log("    Bitget 成交记录：%d 笔（%d 页）" % (len(out), pages))
    for f in out[:20]:
        fd = (f.get("feeDetail") or {})
        log("      fill %s %s 金额=%s 均价=%s 手续费=%s %s" % (
            f.get("symbol"), f.get("side"), f.get("amount"), f.get("priceAvg"),
            fd.get("totalFee"), fd.get("feeCoin")))
    return out


STABLE = {"USDT", "USDC", "USD", "DAI", "FDUSD", "TUSD", "BUSD"}


def replay(fills, base_cost, calib_shares=None, fx_price=None, log=print):
    """把成交重放成每个币的成本总额（USDT）。买入增加成本，卖出减少成本。"""
    cost = dict(base_cost or {})
    realized = {}
    qty = {str(k).upper(): float(v) for k, v in (calib_shares or {}).items()}
    qty_delta = {}
    realized_pnl = {}
    sell_entries = []
    for f in fills:
        coin = (f.get("coin") or "").upper() or (f.get("symbol") or "").split("USDT")[0]
        if not coin:
            continue
        fd = f.get("feeDetail") or {}
        try:
            size = float(f.get("size") or 0)
            price = float(f.get("priceAvg") or f.get("price") or 0)
            amount = float(f.get("amount") or 0) or size * price
        except (TypeError, ValueError):
            continue
        if size <= 0 or amount <= 0:
            continue
        side = (f.get("side") or "").lower()
        fee = abs(float(fd.get("totalFee") or f.get("fee") or 0))
        fee_coin = (fd.get("feeCoin") or f.get("feeCoin") or "").upper()
        fee_usdt = 0.0
        if fee_coin in STABLE:
            fee_usdt = fee
        elif fee_coin == coin:
            fee_usdt = fee * price
        elif fx_price and fee_coin in fx_price:
            fee_usdt = fee * fx_price[fee_coin]
        if side == "buy":
            cost[coin] = cost.get(coin, 0.0) + amount + fee_usdt
            qty[coin] = qty.get(coin, 0.0) + size
            qty_delta[coin] = qty_delta.get(coin, 0.0) + size
        elif side == "sell":
            # 稳定币之间的兑换（如 USDC→USDT）属于内部划转，不产生盈亏，
            # 也不计入卖出笔数与已实现盈亏，只调整份额。
            if coin in STABLE:
                held0 = qty.get(coin, 0.0)
                qty[coin] = max(0.0, held0 - size)
                qty_delta[coin] = qty_delta.get(coin, 0.0) - size
                cost[coin] = max(0.0, cost.get(coin, 0.0) - size)
                continue
            held = qty.get(coin, 0.0)
            avg_cost = (cost.get(coin, 0.0) / held) if held > 0 else 0.0
            basis = min(cost.get(coin, 0.0), avg_cost * size)
            proceeds = amount - fee_usdt
            # 卖出：只把对应成本基数移出，差额记已实现盈亏（不按卖出额直接减成本）
            cost[coin] = max(0.0, cost.get(coin, 0.0) - basis)
            qty[coin] = max(0.0, held - size)
            qty_delta[coin] = qty_delta.get(coin, 0.0) - size
            realized[coin] = realized.get(coin, 0.0) + proceeds
            realized_pnl[coin] = realized_pnl.get(coin, 0.0) + (proceeds - basis)
            try:
                ts = int(f.get("cTime") or 0)
                when = datetime.fromtimestamp(ts / 1000, CST).strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError, OSError):
                when = ""
            sell_entries.append({
                "date": when, "coin": coin, "shares": round(size, 8),
                "price": round(price, 4),
                "cost_price": round(avg_cost, 4),
                "proceeds": round(proceeds, 2), "fee": round(fee_usdt, 4),
                "pnl_usdt": round(proceeds - basis, 4),
            })
    return ({k: round(v, 4) for k, v in cost.items()},
            {k: round(v, 4) for k, v in realized.items()},
            {k: round(v, 8) for k, v in qty_delta.items()},
            {k: round(v, 4) for k, v in realized_pnl.items()},
            sorted(sell_entries, key=lambda x: x["date"], reverse=True))


RECENT_DAYS = 3


def parse_start(text):
    """校准起点支持「日期」与「日期 时:分」两种写法。

    校准份额取自当日快照，快照已包含当日 06:00 的成交；因此起点必须能精确到时刻，
    否则会把已计入校准份额的成交再算一次，产生永久性「缺口」。
    """
    text = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    raise ValueError("无法解析校准起点：%s" % text)


def recent_qty(fills, days=RECENT_DAYS, now=None):
    """统计最近 days 天内的成交净数量（用于判定「成交已入账但快照份额未跟上」的临时缺口）。"""
    now = now or datetime.now(CST)
    since_ms = int((now - timedelta(days=days)).timestamp() * 1000)
    out = {}
    for f in fills:
        try:
            ts = int(f.get("cTime") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts and ts < since_ms:
            continue
        coin = (f.get("coin") or "").upper() or (f.get("symbol") or "").split("USDT")[0].upper()
        if not coin:
            continue
        try:
            size = float(f.get("size") or f.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        sign = -1 if str(f.get("side")).lower() in ("sell", "卖出") else 1
        out[coin] = out.get(coin, 0.0) + sign * size
    return {k: round(v, 8) for k, v in out.items()}


CONVERT_BIZ = ("CONVERT_USER_IN", "CONVERT_USER_OUT", "SMALL_EXCHANGE_USER_IN", "SMALL_EXCHANGE_USER_OUT")


def fetch_converts(key, secret, passphrase, start_ms, log=print):
    """拉取「闪兑 / 兑换」账单，按 bizOrderId 配成一笔进出。

    闪兑不走现货撮合，/fills 里查不到，只能靠账单还原：卖出币数量、买入币数量。
    返回 [{ts, id, out:[(coin,size)], in:[(coin,size)]}]，size 均为正数。
    """
    rows, cur, now_ms = [], int(start_ms), int(datetime.now(CST).timestamp() * 1000)
    use_v3 = False
    while cur < now_ms:
        nxt = min(cur + 5 * 86400 * 1000, now_ms)
        cursor, pages = None, 0
        while pages < 20:
            params = {"startTime": str(cur), "endTime": str(nxt), "limit": "100"}
            if cursor:
                params["idLessThan"] = cursor
            try:
                if use_v3:
                    chunk = _get("/api/v3/account/financial-records",
                                 {"category": "OTHER", "startTime": str(cur), "endTime": str(nxt), "limit": "500"},
                                 key, secret, passphrase)
                    chunk = chunk.get("list") if isinstance(chunk, dict) else chunk
                    chunk = chunk or []
                else:
                    chunk = _get("/api/v2/spot/account/bills", params, key, secret, passphrase)
            except Exception as e:  # noqa: BLE001
                if "40085" in str(e) and not use_v3:
                    log("      [warn] 账户为统一账户，闪兑账单改用 v3 流水")
                    use_v3 = True
                    continue
                log("      [warn] 闪兑账单 %s 段读取失败：%s" % (cur, str(e)[:80]))
                break
            if not chunk:
                break
            rows.extend(chunk)
            cursor = chunk[-1].get("billId")
            pages += 1
            if len(chunk) < 100:
                break
        cur = nxt

    groups = {}
    for b in rows:
        bt = str(b.get("businessType") or "").upper()
        if not bt and use_v3:
            bt = str(b.get("type") or "").upper()
        if "CONVERT" not in bt and "SMALL_EXCHANGE" not in bt and "SWITCH" not in bt:
            continue
        if not bt.startswith(("CONVERT_USER", "SMALL_EXCHANGE")):
            continue
        try:
            size = abs(float(b.get("size") or b.get("amount") or 0))
        except (TypeError, ValueError):
            continue
        if size <= 0:
            continue
        coin = str(b.get("coin") or "").upper()
        oid = str(b.get("bizOrderId") or b.get("billId") or b.get("id"))
        g = groups.setdefault(oid, {"ts": int(b.get("cTime") or b.get("ts") or 0), "out": [], "in": []})
        g["out" if bt.endswith("_OUT") else "in"].append((coin, size))
    pairs = [dict(v, id=k) for k, v in groups.items() if v["out"] and v["in"]]
    log("    Bitget 闪兑账单：%d 条明细，%d 组可配对" % (len(rows), len(pairs)))
    return pairs


def apply_converts(pairs, cost, holdings, qty_delta, log=print):
    """把闪兑的「卖出币账面成本」按数量比例转移到「买入币」，不产生已实现盈亏。

    奖励币（派息/空投）成本本就为 0，换回 BTC/SOL 时转移 0，仍然是 0 成本增发（摊薄）；
    用真金换来的币，则把成本如实带过去，避免「闪兑买入按 0 成本」的假盈利。
    """
    transferred = 0.0
    for pr in sorted(pairs, key=lambda x: x["ts"]):
        out_cost = 0.0
        for coin, size in pr["out"]:
            held = holdings.get(coin, 0.0)
            unit = (cost.get(coin, 0.0) / held) if held > 0 else 0.0
            take = min(cost.get(coin, 0.0), unit * size)
            cost[coin] = max(0.0, cost.get(coin, 0.0) - take)
            holdings[coin] = max(0.0, held - size)
            qty_delta[coin] = qty_delta.get(coin, 0.0) - size
            out_cost += take
        total = sum(s for _, s in pr["in"]) or 1.0
        for coin, size in pr["in"]:
            cost[coin] = cost.get(coin, 0.0) + out_cost * size / total
            holdings[coin] = holdings.get(coin, 0.0) + size
            qty_delta[coin] = qty_delta.get(coin, 0.0) + size
        transferred += out_cost
    if pairs:
        log("    闪兑成本转移完成：%d 组，转移成本 %.2f USDT" % (len(pairs), transferred))
    return transferred


def update(data_path=None, log=print):
    cfg = json.loads(Path(data_path or (Path(__file__).resolve().parent.parent / "data" / "crypto_cost.json")).read_text(encoding="utf-8"))
    key, secret, passphrase = os.environ.get("BITGET_KEY"), os.environ.get("BITGET_SECRET"), os.environ.get("BITGET_PASSPHRASE")
    if not (key and secret and passphrase):
        log("    [warn] 未配置 Bitget 密钥，跳过成交同步")
        return None
    cal = cfg.get("calibration") or {}
    start = cal.get("fills_since") or cal.get("date")
    if not start:
        log("    [warn] crypto_cost.json 缺少校准日期")
        return None
    start_dt = parse_start(start)
    start_ms = int(start_dt.timestamp() * 1000)
    fills = fetch_fills(key, secret, passphrase, start_ms, log=log)
    base = cal.get("cost_total_usdt") or {}
    cost, realized, qty, realized_pnl, sell_entries = replay(fills, base, calib_shares=cal.get("calib_shares"), log=log)
    # 闪兑：/fills 看不到，用账单把「卖出币成本」转移给「买入币」（奖励币成本 0 → 仍为 0 成本摊薄）
    converts = []
    try:
        converts = fetch_converts(key, secret, passphrase, start_ms, log=log)
    except Exception as e:  # noqa: BLE001
        log("    [warn] 闪兑账单读取失败，按无闪兑处理：%s" % str(e)[:90])
    holdings = {k: float(v) for k, v in (cal.get("calib_shares") or {}).items()}
    for coin, delta in qty.items():
        holdings[coin] = holdings.get(coin, 0.0) + float(delta)
    transferred = apply_converts(converts, cost, holdings, qty, log=log)
    recent = recent_qty(fills)
    rec_ms = int((datetime.now(CST) - timedelta(days=RECENT_DAYS)).timestamp() * 1000)
    for pr in converts:
        if pr["ts"] < rec_ms:
            continue
        for coin, size in pr["out"]:
            recent[coin] = recent.get(coin, 0.0) - size
        for coin, size in pr["in"]:
            recent[coin] = recent.get(coin, 0.0) + size
    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "since": start,
        "fills": len(fills),
        "cost_total_usdt": cost,
        "realized_usdt": realized,
        "qty_net": qty,
        "qty_net_recent": {k: round(v, 8) for k, v in recent.items()},
        "converts": len(converts),
        "convert_cost_usdt": round(transferred, 4),
        "recent_days": RECENT_DAYS,
        "qty_mode": "delta",
        "realized_pnl_usdt": realized_pnl,
        "sell_entries": sell_entries,
        "source": "bitget_fills",
    }
    LEDGER.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("    Bitget 成本同步完成：%d 笔成交，BTC %.2f / SOL %.2f USDT" % (
        len(fills), cost.get("BTC", 0), cost.get("SOL", 0)))
    return payload


if __name__ == "__main__":
    update()
