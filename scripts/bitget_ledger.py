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


def fetch_fills(key, secret, passphrase, start_ms, log=print):
    """翻页拉取 start_ms 之后的所有现货成交，按时间升序返回。"""
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
    return ({k: round(v, 4) for k, v in cost.items()},
            {k: round(v, 4) for k, v in realized.items()},
            {k: round(v, 8) for k, v in qty_delta.items()},
            {k: round(v, 4) for k, v in realized_pnl.items()})


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
    start_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=CST).timestamp() * 1000)
    fills = fetch_fills(key, secret, passphrase, start_ms, log=log)
    base = cal.get("cost_total_usdt") or {}
    cost, realized, qty, realized_pnl = replay(fills, base, calib_shares=cal.get("calib_shares"), log=log)
    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "since": start,
        "fills": len(fills),
        "cost_total_usdt": cost,
        "realized_usdt": realized,
        "qty_net": qty,
        "realized_pnl_usdt": realized_pnl,
        "source": "bitget_fills",
    }
    LEDGER.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("    Bitget 成本同步完成：%d 笔成交，BTC %.2f / SOL %.2f USDT" % (
        len(fills), cost.get("BTC", 0), cost.get("SOL", 0)))
    return payload


if __name__ == "__main__":
    update()
