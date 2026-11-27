#!/usr/bin/env python3
"""读取 Bitget 合约持仓（UTA v3），生成前端「合约持仓」展示块用的数据。

输出 data/bitget_position.json：
  {"updated_at": "...", "count": n,
   "items": [{"category": "COIN-FUTURES", "symbol": "BTCUSD_CM", "posSide": "long",
              "contracts": 1192, "avg_price": 59692.6, "mark_price": 59746.7,
              "margin_coin": "BTC", "margin": 0.01998127, "leverage": 1,
              "unrealized_native": 0.00001807, "liq_price": 29974.3, "margin_mode": "isolated"}]}

注意：保证金已经计入 data/bitget_account.json 的 futures 桶，这里只做展示，不重复计入总资产。
"""

import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bitget_ledger as L  # noqa: E402

CST = timezone(timedelta(hours=8))
OUT = Path(__file__).resolve().parent.parent / "data" / "bitget_position.json"
POS_PATH = "/api/v3/position/current-position"
CATEGORIES = ("COIN-FUTURES", "USDT-FUTURES", "USDC-FUTURES")


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    key, secret, phrase = (os.environ.get("BITGET_KEY"), os.environ.get("BITGET_SECRET"),
                           os.environ.get("BITGET_PASSPHRASE"))
    if not (key and secret and phrase):
        print("    [warn] 未配置 Bitget 密钥，跳过合约持仓同步")
        return 1

    items = []
    for cat in CATEGORIES:
        try:
            data = L._get(POS_PATH, {"category": cat}, key, secret, phrase, timeout=20)
            lst = (data.get("list") if isinstance(data, dict) else None) or []
        except Exception as e:  # noqa: BLE001
            print("      [warn] 读取 %s 持仓失败：%s" % (cat, str(e)[:90]))
            continue
        for p in lst:
            total = _num(p.get("total"))
            if total <= 0:
                continue
            items.append({
                "category": cat,
                "symbol": p.get("symbol"),
                "posSide": p.get("posSide"),
                "contracts": total,
                "avg_price": round(_num(p.get("avgPrice")), 4),
                "mark_price": round(_num(p.get("markPrice")), 4),
                "margin_coin": p.get("marginCoin"),
                "margin": round(_num(p.get("positionBalance")), 10),
                "leverage": _num(p.get("leverage")),
                "margin_mode": p.get("marginMode"),
                "unrealized_native": round(_num(p.get("unrealisedPnl")), 10),
                "liq_price": round(_num(p.get("liquidationPrice")), 4),
                "opened_at": int(_num(p.get("createdTime"))),
                # 本仓已实现：接口直读 curRealisedPnl + 资金费 + 开/平仓手续费（币本位计价）
                "cur_realised_native": round(_num(p.get("curRealisedPnl")), 10),
                "funding_native": round(_num(p.get("totalFunding")), 10),
                "open_fee_native": round(_num(p.get("openFeeTotal")), 10),
                "close_fee_native": round(_num(p.get("closeFeeTotal")), 10),
                "realized_native": round(_num(p.get("curRealisedPnl")) + _num(p.get("totalFunding"))
                                         + _num(p.get("openFeeTotal")) + _num(p.get("closeFeeTotal")), 10),
                "break_even_price": round(_num(p.get("breakEvenPrice")), 4),
            })

    payload = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "bitget_v3_position",
        "count": len(items),
        "items": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("    合约持仓同步完成：%d 笔" % len(items))
    for i in items:
        print("      %s %s %s 张 均价=%s 保证金=%s %s 浮盈=%s" % (
            i["symbol"], i["posSide"], i["contracts"], i["avg_price"],
            i["margin"], i["margin_coin"], i["unrealized_native"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
