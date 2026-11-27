#!/usr/bin/env python3
"""读取 Bitget 持仓（UTA 统一账户 v3 优先，经典 v2 兜底）。

统一账户下「资产」拆分在三处，必须合并才能得到真实总持仓：
  1. /api/v3/account/assets            —— 交易账户可用余额（spot）
  2. /api/v3/earn/savings/assets       —— 理财/生息持仓（earn）
  3. /api/v3/position/current-position —— 合约保证金（futures，按 marginCoin 计）

输出 data/bitget_account.json：
  {"updated_at": "...", "source": "bitget_account", "mode": "uta",
   "coins": {"BTC": {"spot": ..., "earn": ..., "futures": ..., "total": ...}}}

PoolX 等营销产品官方 API 不暴露，由 data/holdings.json 的 poolx 清单手工登记，在 build.py 合并。
"""

import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bitget_ledger as L  # 复用签名与 _get

CST = timezone(timedelta(hours=8))
OUT = Path(__file__).resolve().parent.parent / "data" / "bitget_account.json"

V3_ASSETS = "/api/v3/account/assets"
V3_SAVINGS = "/api/v3/earn/savings/assets"
V3_POSITIONS = "/api/v3/position/current-position"
V2_SPOT = "/api/v2/spot/account/assets"
V2_EARN = "/api/v2/earn/account/assets"


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _bump(coins, coin, bucket, amt):
    c = str(coin or "").upper()
    if not c or amt <= 0:
        return
    d = coins.setdefault(c, {"spot": 0.0, "earn": 0.0, "futures": 0.0})
    d[bucket] += amt


def fetch_v3(key, secret, passphrase, log=print):
    """统一账户：交易账户 + 理财 + 合约保证金三路合并。"""
    coins, raw, ok = {}, {}, 0

    try:
        data = L._get(V3_ASSETS, {}, key, secret, passphrase, timeout=20)
        assets = (data.get("assets") if isinstance(data, dict) else None) or []
        raw["assets"] = {"accountEquity": data.get("accountEquity"),
                         "btcEquity": data.get("btcEquity"), "count": len(assets)}
        for a in assets:
            # equity = 该币在交易账户里的总权益（含锁仓），比 balance 更完整
            _bump(coins, a.get("coin"), "spot", _num(a.get("equity")) or _num(a.get("balance")))
        ok += 1
        log("      [v3] 交易账户资产：%d 个币种" % len(assets))
    except Exception as e:  # noqa: BLE001
        log("      [warn] v3 资产接口失败：%s" % str(e)[:90])

    try:
        data = L._get(V3_SAVINGS, {}, key, secret, passphrase, timeout=20)
        rs = (data.get("resultList") if isinstance(data, dict) else None) or []
        raw["savings"] = {"count": len(rs)}
        for r in rs:
            if str(r.get("status") or "") not in ("in_holding", ""):
                continue
            _bump(coins, r.get("productCoin") or r.get("coin"), "earn", _num(r.get("holdAmount")))
        ok += 1
        log("      [v3] 理财/生息持仓：%d 条" % len(rs))
    except Exception as e:  # noqa: BLE001
        log("      [warn] v3 理财接口失败：%s" % str(e)[:90])

    for ptype in ("COIN-FUTURES", "USDT-FUTURES", "USDC-FUTURES"):
        try:
            data = L._get(V3_POSITIONS, {"category": ptype}, key, secret, passphrase, timeout=20)
            lst = (data.get("list") if isinstance(data, dict) else None) or []
            raw.setdefault("positions", {})[ptype] = len(lst)
            for p in lst:
                _bump(coins, p.get("marginCoin"), "futures", _num(p.get("positionBalance")))
            ok += 1
        except Exception as e:  # noqa: BLE001
            log("      [warn] v3 持仓接口(%s)失败：%s" % (ptype, str(e)[:80]))

    return (coins, raw, "uta") if ok else (None, raw, None)


def fetch_v2(key, secret, passphrase, log=print):
    """经典账户兜底（未升级 UTA 时用）。"""
    coins, raw = {}, {}
    try:
        rows = L._get(V2_SPOT, {}, key, secret, passphrase, timeout=20)
        raw["spot"] = len(rows)
        for r in rows:
            _bump(coins, r.get("coin"), "spot", _num(r.get("available")) + _num(r.get("frozen")))
        log("      现货持仓：%d 个币种" % len(coins))
    except Exception as e:  # noqa: BLE001
        log("      [warn] 现货接口失败：%s" % str(e)[:90])

    try:
        rows = L._get(V2_EARN, {}, key, secret, passphrase, timeout=20)
        raw["earn"] = len(rows)
        for r in rows:
            _bump(coins, r.get("coin") or r.get("productCoin"), "earn",
                  _num(r.get("amount")) + _num(r.get("available")) + _num(r.get("balance")))
        log("      理财/质押命中 %d 个币种" % len([1 for v in coins.values() if v["earn"] > 0]))
    except Exception as e:  # noqa: BLE001
        log("      [warn] 理财接口失败：%s" % str(e)[:90])

    return (coins if coins else None), raw, "classic"


def main():
    key = os.environ.get("BITGET_KEY")
    secret = os.environ.get("BITGET_SECRET")
    passphrase = os.environ.get("BITGET_PASSPHRASE")
    if not (key and secret and passphrase):
        print("    [warn] 未配置 Bitget 密钥，跳过账户持仓同步")
        return 1

    coins, raw, mode = fetch_v3(key, secret, passphrase)
    if not coins:
        print("    [warn] v3 接口没有结果，回退经典账户接口")
        coins, raw, mode = fetch_v2(key, secret, passphrase)
    print("      账户原始字段：%s" % json.dumps(raw, ensure_ascii=False)[:600])
    if not coins:
        print("    [warn] 未取到任何持仓")
        return 1

    for v in coins.values():
        v["total"] = round(v["spot"] + v["earn"] + v["futures"], 10)

    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "bitget_account",
        "mode": mode,
        "coins": {c: {k: round(vv, 10) for k, vv in d.items()} for c, d in sorted(coins.items())},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("    Bitget 账户同步完成（%s）：%s" % (mode, " / ".join(
        "%s %.8f" % (c, d["total"]) for c, d in sorted(coins.items()) if d["total"] > 0)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
