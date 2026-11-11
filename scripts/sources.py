"""
全维度资产统计 —— 数据取数层（仅 Python 标准库，无需第三方依赖）。

行情优先级：
  1) 全球资产仪表台（index-fund-dashboard）已抓好的 data/dashboard.json —— 标的在其中时直接用它的价格
  2) 腾讯实时行情 qt.gtimg.cn（A股/ETF/美股）
  3) 天天基金净值 fundgz.1234567.com.cn（场外基金）
  4) Yahoo chart（海外兜底）

加密货币：直接读取『加密货币资产仪表台』bitget-pnl-dashboard 的 data/history.json。
汇率：open.er-api.com 免费接口，失败回退 holdings.json 中的兜底值。

以上免费源仅供个人研究，不得商用或再分发。
"""

import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
TIMEOUT = 15


def _fetch(url, params=None, headers=None, retries=2, decode="utf-8"):
    """GET 请求，返回文本；失败返回 None。"""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
            try:
                return raw.decode(decode)
            except UnicodeDecodeError:
                return raw.decode("latin-1")
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout,
                ssl.SSLError, ConnectionError, OSError) as e:
            last = str(e)
            if attempt < retries:
                time.sleep(1.2)
    print("  [warn] fetch failed:", url.split("?")[0], last)
    return None


def _f(x):
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:
            return None
        return v
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 1) 全球资产仪表台
# --------------------------------------------------------------------------

FUND_DASHBOARD_URL = "https://978912280-jpg.github.io/index-fund-dashboard/data/dashboard.json"


def fund_dashboard_items(url=FUND_DASHBOARD_URL):
    """读取全球资产仪表台全部标的，返回 {code: item}。"""
    raw = _fetch(url, retries=2)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    out = {}
    for it in data.get("items", []):
        code = str(it.get("code") or "").upper()
        if code:
            out[code] = it
    return out


# --------------------------------------------------------------------------
# 2) 腾讯实时行情
# --------------------------------------------------------------------------

def tencent_code(symbol):
    """把标的代码规范成腾讯行情代码。"""
    s = str(symbol or "").strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith(("sh", "sz", "us", "hk", "bj")):
        return low
    if re.fullmatch(r"\d{6}", s):
        return ("sh" if s[0] in "569" else "sz") + s
    if re.fullmatch(r"[A-Za-z.\-]+", s):
        return "us" + s.upper().replace(".", "")
    return None


def tencent_quote(symbol):
    """腾讯实时行情，返回 {price, prev_close, change_pct, ts, name, source} 或 None。"""
    code = tencent_code(symbol)
    if not code:
        return None
    raw = _fetch("https://qt.gtimg.cn/q=" + code, decode="gbk")
    if not raw:
        return None
    m = re.search(r'="([^"]*)"', raw)
    if not m:
        return None
    p = m.group(1).split("~")
    if len(p) < 6 or not p[3]:
        return None

    def g(i):
        return _f(p[i]) if i < len(p) else None

    price, prev = g(3), g(4)
    chg = g(32)
    if chg is None and price is not None and prev:
        chg = (price - prev) / prev * 100
    return {
        "price": price,
        "prev_close": prev,
        "change_pct": chg,
        "ts": (p[30] if len(p) > 30 else None),
        "name": p[1] if len(p) > 1 else None,
        "source": "腾讯实时",
        "kind": "quote",
    }


# --------------------------------------------------------------------------
# 3) 场外基金净值（天天基金）
# --------------------------------------------------------------------------

def fundgz_nav(code):
    """场外基金最新净值，返回 {price, change_pct, ts, name, source} 或 None。"""
    raw = _fetch("http://fundgz.1234567.com.cn/js/%s.js" % code, retries=1)
    if not raw:
        return None
    m = re.search(r"jsonpgz\((\{.*\})\)", raw)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return None
    price = _f(d.get("gsz")) or _f(d.get("dwjz"))
    if price is None:
        return None
    chg = _f(d.get("gszzl"))
    return {
        "price": price,
        "prev_close": _f(d.get("dwjz")),
        "change_pct": chg,
        "ts": d.get("gztime") or d.get("jzrq"),
        "name": d.get("name"),
        "source": "天天基金",
        "kind": "nav",
    }


# --------------------------------------------------------------------------
# 4) Yahoo 兜底
# --------------------------------------------------------------------------

def yahoo_quote(symbol):
    raw = _fetch("https://query1.finance.yahoo.com/v8/finance/chart/%s" % urllib.parse.quote(symbol),
                 params={"range": "5d", "interval": "1d"}, retries=1)
    if not raw:
        return None
    try:
        res = json.loads(raw)["chart"]["result"][0]
        meta = res["meta"]
        price = _f(meta.get("regularMarketPrice"))
        prev = _f(meta.get("chartPreviousClose")) or _f(meta.get("previousClose"))
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    if price is None:
        return None
    chg = (price - prev) / prev * 100 if prev else None
    return {
        "price": price,
        "prev_close": prev,
        "change_pct": chg,
        "ts": time.strftime("%Y-%m-%d %H:%M", time.localtime(meta.get("regularMarketTime") or time.time())),
        "name": meta.get("shortName"),
        "source": "Yahoo",
        "kind": "quote",
    }


# --------------------------------------------------------------------------
# 汇率
# --------------------------------------------------------------------------

def usdcny():
    raw = _fetch("https://open.er-api.com/v6/latest/USD", retries=1)
    if raw:
        try:
            rate = json.loads(raw)["rates"]["CNY"]
            return float(rate), "open.er-api.com"
        except (ValueError, KeyError, TypeError):
            pass
    return None, None
