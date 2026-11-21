#!/usr/bin/env python3
"""识别 Bitget「Stock Plus / 代币化美股（rToken）」持仓，供 build.py 计入传统股票资产。

背景：
  Bitget 的代币化美股以 r 前缀币种计价（如 rNVDA、rTSLA），走现货账户，
  报价是 USDT 交易对（rNVDAUSDT）。它们不是加密货币，应按「传统股票」类别统计。

识别规则（三重保险，避免把 RENDER 这类普通币误判成 rToken）：
  1. 币种形如 r + 股票代码（去掉前缀后命中白名单）；
  2. 白名单 = data/holdings.json 的 rtokens.tickers（可自行增补）；
  3. 且该币存在 USDT 交易对并取得到价格。

输出 data/rtoken.json：
  {"updated_at": "...", "source": "bitget_spot", "count": n,
   "items": [{"coin": "RNVDA", "ticker": "NVDA", "name": "英伟达",
              "shares": 1.0, "price_usd": 123.4, "value_usd": 123.4, "price_source": "Bitget 实时价"}]}

只读接口，不含密钥；取不到时保留旧文件不变。
"""

import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bitget_ledger as L  # 复用签名与 _get
import sources

STABLE = {"USDT", "USDC", "USD", "DAI", "FDUSD", "TUSD", "BUSD"}

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "rtoken.json"
HOLDINGS = ROOT / "data" / "holdings.json"
CST = timezone(timedelta(hours=8))
SPOT_PATH = "/api/v2/spot/account/assets"

# 常见美股代码（可在 holdings.json 的 rtokens.tickers 里增补）
DEFAULT_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "AVGO", "AMD",
    "NFLX", "SPY", "QQQ", "QQQM", "VOO", "VTI", "COIN", "MSTR", "PLTR", "TSM",
    "BABA", "JPM", "V", "MA", "KO", "PEP", "DIS", "INTC", "ORCL", "CRM",
    "UBER", "SHOP", "HOOD", "CRCL", "ARM", "MU", "SMCI", "APP", "ASML", "SONY",
]
NAME_MAP = {
    "NVDA": "英伟达", "TSLA": "特斯拉", "AAPL": "苹果", "MSFT": "微软", "AMZN": "亚马逊",
    "GOOGL": "谷歌 A", "GOOG": "谷歌 C", "META": "Meta", "AVGO": "博通", "AMD": "AMD",
    "NFLX": "奈飞", "SPY": "标普 500ETF", "QQQ": "纳指 100ETF", "VOO": "先锋标普 500",
    "COIN": "Coinbase", "MSTR": "MicroStrategy", "PLTR": "Palantir", "TSM": "台积电",
    "BABA": "阿里巴巴", "JPM": "摩根大通", "V": "Visa", "MA": "万事达", "KO": "可口可乐",
    "PEP": "百事", "DIS": "迪士尼", "INTC": "英特尔", "ORCL": "甲骨文", "CRM": "Salesforce",
    "UBER": "优步", "SHOP": "Shopify", "HOOD": "Robinhood", "ARM": "Arm", "MU": "美光",
    "SMCI": "超微电脑", "APP": "AppLovin", "ASML": "阿斯麦", "SONY": "索尼",
}


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def load_cfg():
    """读取 holdings.json 的 rtokens 配置块。"""
    try:
        h = json.loads(HOLDINGS.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return h.get("rtokens") or {}


def fetch_spot(key, secret, passphrase, log=print):
    rows = L._get(SPOT_PATH, {}, key, secret, passphrase, timeout=20)
    out = {}
    for r in rows:
        c = str(r.get("coin") or "").upper()
        if not c:
            continue
        amt = _num(r.get("available")) + _num(r.get("frozen"))
        if amt <= 0:
            continue
        out[c] = round(out.get(c, 0.0) + amt, 10)
    log("      现货持仓：%d 个币种" % len(out))
    return out


def detect(coins, tickers, extra=(), log=print):
    """从现货持仓里挑出 rToken，返回 [(coin, ticker)]。"""
    allowed = {t.upper() for t in list(tickers or []) + list(extra or [])}
    hits = []
    for coin in coins:
        if not coin.startswith("R") or len(coin) <= 1:
            continue
        ticker = coin[1:]
        if allowed and ticker not in allowed:
            continue
        # 未配置白名单时退化为「r + 1~5 位字母」，并且不能是常见普通币
        if not allowed and not (1 <= len(ticker) <= 5 and ticker.isalpha()):
            continue
        hits.append((coin, ticker))
    if hits:
        log("      rToken 命中：%s" % "、".join("%s(%s)" % (c, t) for c, t in hits))
    else:
        log("      未发现 rToken 持仓")
    return hits




def calc_cost_usdt(coins, key, secret, passphrase, since_ms, log=print):
    """按真实成交价累计每个 rToken 的净投入（USDT）。

    口径：
      · 现货成交 rXXXUSDT：买入按成交额加成本，卖出按成交额减成本；
      · 闪兑 CONVERT/SMALL_EXCHANGE：rToken 在 IN 侧 → 按 OUT 侧稳定币数量加成本；
        rToken 在 OUT 侧 → 按 IN 侧稳定币数量减成本。
    这样成本价 = 累计投入 ÷ 当前份额，完全来自实际成交价，不再借用正股成本。
    """
    cost = {c: 0.0 for c in coins}
    fills = L.fetch_fills(key, secret, passphrase, since_ms, log=lambda *a: None)
    for f in fills:
        sym = str(f.get("symbol") or "").upper()
        coin = sym[:-4] if sym.endswith("USDT") else ""
        if coin not in cost:
            continue
        try:
            size = float(f.get("size") or 0)
            amount = float(f.get("amount") or 0) or size * float(f.get("priceAvg") or 0)
        except (TypeError, ValueError):
            continue
        if str(f.get("side")).lower() in ("buy", "买入"):
            cost[coin] += amount
        else:
            cost[coin] -= amount
    pairs = L.fetch_converts(key, secret, passphrase, since_ms, log=lambda *a: None)
    for pr in pairs:
        for coin in coins:
            if any(c == coin for c, _ in pr["in"]):
                gross = sum(sz for c, sz in pr["out"] if c in STABLE)
                if gross:
                    cost[coin] += gross
                else:
                    log("      [warn] %s 闪兑的卖出侧不是稳定币，成本无法从账单还原" % coin)
            if any(c == coin for c, _ in pr["out"]):
                gross = sum(sz for c, sz in pr["in"] if c in STABLE)
                if gross:
                    cost[coin] -= gross
    return {c: round(v, 4) for c, v in cost.items()}


def main():
    key = os.environ.get("BITGET_KEY")
    secret = os.environ.get("BITGET_SECRET")
    passphrase = os.environ.get("BITGET_PASSPHRASE")
    cfg = load_cfg()
    if cfg.get("enabled", True) is False:
        print("    [skip] holdings.json 里 rtokens.enabled = false")
        return 0
    if not (key and secret and passphrase):
        print("    [warn] 未配置 Bitget 密钥，跳过 rToken 同步")
        return 1

    coins = fetch_spot(key, secret, passphrase)
    manual = cfg.get("manual") or []          # 手工兜底：[{"coin": "rNVDA", "shares": 1}]
    for m in manual:
        c = str(m.get("coin") or "").upper()
        amt = _num(m.get("shares"))
        if c and amt > 0:
            coins[c] = max(coins.get(c, 0.0), round(amt, 10))

    hits = detect(coins, cfg.get("tickers") or DEFAULT_TICKERS, cfg.get("extra_tickers"), log=print)
    since = str(cfg.get("cost_since") or "")[:10]
    since_ms = 0
    if since:
        try:
            since_ms = int(datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=CST).timestamp() * 1000)
        except ValueError:
            since_ms = 0
    if not since_ms:
        since_ms = int((datetime.now(CST) - timedelta(days=60)).timestamp() * 1000)
    costs = calc_cost_usdt([c for c, _ in hits], key, secret, passphrase, since_ms, log=print) if hits else {}
    prices = sources.bitget_prices([c for c, _ in hits], log=print) if hits else {}
    items = []
    for coin, ticker in hits:
        shares = _num(coins.get(coin))
        price = _num(prices.get(coin))
        if shares <= 0 or price <= 0:
            print("      [warn] %s 缺份额或价格（%.6g / %.6g），跳过" % (coin, shares, price))
            continue
        items.append({
            "coin": coin,
            "ticker": ticker,
            "name": NAME_MAP.get(ticker, ticker),
            "shares": round(shares, 8),
            "price_usd": round(price, 4),
            "value_usd": round(shares * price, 2),
            "price_source": "Bitget 实时价",
            "cost_usdt": costs.get(coin, 0.0),
            "cost_price": round(costs.get(coin, 0.0) / shares, 4) if shares else 0.0,
        })

    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "bitget_spot",
        "count": len(items),
        "items": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("    rToken 同步完成：%d 个标的，合计 %.2f USD" % (
        len(items), sum(i["value_usd"] for i in items)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
