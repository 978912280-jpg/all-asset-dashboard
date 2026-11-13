"""读取 Bitget 账户持仓：现货 + 理财/质押（用于摆脱上游加密仪表台依赖）。

输出 data/bitget_account.json：
  {"updated_at": "...", "source": "bitget_account",
   "coins": {"BTC": {"spot": 0.00014, "earn": 0.083062, "total": 0.083202}}}

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

SPOT_PATH = "/api/v2/spot/account/assets"
EARN_PATH = "/api/v2/earn/account/assets"


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch(key, secret, passphrase, log=print):
    coins = {}
    raw = {}

    try:
        rows = L._get(SPOT_PATH, {}, key, secret, passphrase, timeout=20)
        raw["spot"] = rows[:4]
        for r in rows:
            c = str(r.get("coin") or "").upper()
            if not c:
                continue
            amt = _num(r.get("available")) + _num(r.get("frozen"))
            if amt <= 0:
                continue
            d = coins.setdefault(c, {"spot": 0.0, "earn": 0.0})
            d["spot"] += amt
        log("      现货持仓：%d 个币种" % len(coins))
    except Exception as e:
        log("      [warn] 现货接口失败：%s" % e)

    try:
        rows = L._get(EARN_PATH, {}, key, secret, passphrase, timeout=20)
        raw["earn"] = rows[:4]
        for r in rows:
            c = str(r.get("coin") or r.get("productCoin") or "").upper()
            if not c:
                continue
            amt = _num(r.get("amount")) + _num(r.get("available")) + _num(r.get("balance"))
            if amt <= 0:
                continue
            d = coins.setdefault(c, {"spot": 0.0, "earn": 0.0})
            d["earn"] += amt
        log("      理财/质押命中 %d 个币种" % len(
            [1 for v in coins.values() if v["earn"] > 0]))
    except Exception as e:
        log("      [warn] 理财接口失败：%s" % e)

    for c, v in coins.items():
        v["total"] = round(v["spot"] + v["earn"], 10)
    return coins, raw


def main():
    key = os.environ.get("BITGET_KEY")
    secret = os.environ.get("BITGET_SECRET")
    passphrase = os.environ.get("BITGET_PASSPHRASE")
    if not (key and secret and passphrase):
        print("    [warn] 未配置 Bitget 密钥，跳过账户持仓同步")
        return 1
    coins, raw = fetch(key, secret, passphrase)
    print("      账户原始字段：%s" % json.dumps(raw, ensure_ascii=False)[:600])
    if not coins:
        print("    [warn] 未取到任何持仓")
        return 1
    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "bitget_account",
        "coins": {c: {k: round(v, 10) for k, v in d.items()} for c, d in sorted(coins.items())},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("    Bitget 账户同步完成：%s" % " / ".join(
        "%s %.8f" % (c, d["total"]) for c, d in sorted(coins.items()) if d["total"] > 0))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
