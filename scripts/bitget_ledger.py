#!/usr/bin/env python3
"""从 Bitget 现货成交记录累计每个币的净投入（成本总额 USDT）。

只使用只读接口 /api/v2/spot/trade/fills，需要环境变量：
  BITGET_KEY / BITGET_SECRET / BITGET_PASSPHRASE
累计结果写到 data/bitget_ledger.json（只含聚合金额与笔数，不含任何密钥）。
"""
import base64, hashlib, hmac, json, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

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
    r = requests.get(BASE + path, params=params, headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s %s" % (r.status_code, r.text[:160]))
    body = r.json()
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
    return out


STABLE = {"USDT", "USDC", "USD", "DAI", "FDUSD", "TUSD", "BUSD"}


def replay(fills, base_cost, fx_price=None, log=print):
    """把成交重放成每个币的成本总额（USDT）。买入增加成本，卖出减少成本。"""
    cost = dict(base_cost or {})
    realized = {}
    for f in fills:
        coin = (f.get("coin") or "").upper() or (f.get("symbol") or "").split("USDT")[0]
        if not coin:
            continue
        try:
            size = float(f.get("size") or 0)
            price = float(f.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if size <= 0 or price <= 0:
            continue
        side = (f.get("side") or "").lower()
        amount = size * price
        fee = abs(float(f.get("fee") or 0))
        fee_coin = (f.get("feeCoin") or "").upper()
        fee_usdt = 0.0
        if fee_coin in STABLE:
            fee_usdt = fee
        elif fee_coin == coin:
            fee_usdt = fee * price
        elif fx_price and fee_coin in fx_price:
            fee_usdt = fee * fx_price[fee_coin]
        if side == "buy":
            cost[coin] = cost.get(coin, 0.0) + amount + fee_usdt
        elif side == "sell":
            # 卖出：收回的资金从投入里扣回（成本基数下降，已实现收益单独记录）
            cost[coin] = max(0.0, cost.get(coin, 0.0) - (amount - fee_usdt))
            realized[coin] = realized.get(coin, 0.0) + (amount - fee_usdt)
    return {k: round(v, 4) for k, v in cost.items()}, {k: round(v, 4) for k, v in realized.items()}


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
    cost, realized = replay(fills, base, log=log)
    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "since": start,
        "fills": len(fills),
        "cost_total_usdt": cost,
        "realized_usdt": realized,
        "source": "bitget_fills",
    }
    LEDGER.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("    Bitget 成本同步完成：%d 笔成交，BTC %.2f / SOL %.2f USDT" % (
        len(fills), cost.get("BTC", 0), cost.get("SOL", 0)))
    return payload


if __name__ == "__main__":
    update()
