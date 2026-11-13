"""构建完成后把当日资产摘要推送到 Bark。

环境变量：
  BARK_KEY     必填，Bark App 里的 key（也接受完整 https://api.day.app/xxx 形式）
  BARK_SERVER  可选，自建服务地址，默认 https://api.day.app
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fmt_cny(v, signed=False):
    v = float(v or 0)
    sign = ""
    if signed:
        sign = "+" if v > 0 else ("−" if v < 0 else "")
    return "%s¥%s" % (sign, "{:,.2f}".format(abs(v)))


def fmt_pct(v):
    v = float(v or 0)
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return "%s%.2f%%" % (sign, abs(v))


def build_message(d):
    s = d.get("summary") or {}
    meta = d.get("meta") or {}

    def block(label, value_key, pnl_key, pnl_pct_key, day_key, day_pct_key):
        out = [label,
               "市值：%s" % fmt_cny(s.get(value_key)),
               "总盈亏：%s（%s）" % (fmt_cny(s.get(pnl_key), True), fmt_pct(s.get(pnl_pct_key))),
               "今日浮动：%s（%s）" % (fmt_cny(s.get(day_key), True), fmt_pct(s.get(day_pct_key)))]
        return out

    lines = [
        "总资产：%s" % fmt_cny(s.get("total_cny")),
        "总盈亏：%s（%s）" % (fmt_cny(s.get("total_pnl_cny"), True), fmt_pct(s.get("total_pnl_pct"))),
        "今日浮动：%s（%s）" % (fmt_cny(s.get("day_change_cny"), True), fmt_pct(s.get("day_change_pct"))),
        "",
    ]
    lines += block("传统", "traditional_cny", "traditional_pnl_cny",
                   "traditional_pnl_pct", "traditional_day_change_cny", "traditional_day_change_pct")
    lines.append("")
    crypto = block("加密", "crypto_cny", "crypto_pnl_cny",
                   "crypto_pnl_pct", "crypto_day_change_cny", "crypto_day_change_pct")
    if s.get("crypto_pnl_usdt") is not None:
        crypto[2] += "｜%s USDT" % fmt_cny(s.get("crypto_pnl_usdt"), True).replace("¥", "")
    lines += crypto
    lines += [
        "",
        "现金：%s（含稳定币 %s）" % (fmt_cny(s.get("cash_cny")), fmt_cny(s.get("stable_cash_cny"))),
        "",
        "v%s · %s" % (meta.get("version") or "—", str(meta.get("generated_at") or "")[:16].replace("T", " ")),
    ]
    return "资产日报", "\n".join(lines)


def send(key, server, title, body):
    url = (server or "https://api.day.app").rstrip("/") + "/" + key
    payload = json.dumps({
        "title": title,
        "body": body,
        "group": "资产统计",
        "icon": "https://978912280-jpg.github.io/all-asset-dashboard/favicon.ico",
        "level": "active",
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    key = (os.environ.get("BARK_KEY") or "").strip()
    if not key:
        print("    [warn] 未配置 BARK_KEY，跳过推送")
        return 0
    if key.startswith("http"):
        parts = key.split("/")
        key, server = parts[-1], "/".join(parts[:-1])
    else:
        server = (os.environ.get("BARK_SERVER") or "https://api.day.app").strip()
    data = json.loads((ROOT / "data" / "dashboard.json").read_text(encoding="utf-8"))
    title, body = build_message(data)
    try:
        status, text = send(key, server, title, body)
        print("    Bark 推送：HTTP %s %s" % (status, text[:160]))
    except urllib.error.URLError as e:
        print("    [warn] Bark 推送失败：%s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
