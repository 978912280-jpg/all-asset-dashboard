"""一次性实验：让模型基于原始数据自由撰写当日资产观察，输出到日志供人工评估。"""
import json, os, urllib.request, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, "data/dashboard.json"), encoding="utf-8"))
try:
    h = json.load(open(os.path.join(ROOT, "data/holdings.json"), encoding="utf-8"))
except Exception:
    h = {}
try:
    c = json.load(open(os.path.join(ROOT, "data/crypto_events.json"), encoding="utf-8"))
except Exception:
    c = {}

s = d.get("summary", {})
groups = d.get("groups", [])
items = [{k: v for k, v in r.items() if k in ("id", "name", "group", "shares", "price", "currency",
         "value_cny", "day_change_cny", "cost_price", "cost_cny", "change_pct")} for r in d.get("items", [])]
hist = [{k: x.get(k) for k in ("date", "total_cny", "traditional_cny", "crypto_cny", "cash_cny",
        "day_change_cny", "day_change_pct", "total_pnl_cny")} for x in (d.get("history") or [])][-15:]
net = (c.get("net_deposit") or {})
earn = (c.get("earn_daily") or [])[:60]
digest = {
    "today": d.get("analysis", {}).get("date"),
    "summary": s,
    "weights": [{"name": g.get("name"), "cny": g.get("cny"), "weight": g.get("weight")} for g in groups],
    "items": items,
    "history_recent": hist,
    "net_deposit": net,
    "earn_daily_recent": earn,
    "counts": c.get("counts"),
    "realized": d.get("realized_detail"),
    "cash_accounts": h.get("cash_accounts"),
    "trade_ledger": h.get("trade_ledger"),
}
data_txt = json.dumps(digest, ensure_ascii=False)

prompt = f"""下面是我个人资产仪表台的当日原始数据（JSON）。请你以「资产观察」的方式自由撰写一份当日解读，要求：
1. 中文，350~500 字，2~4 个自然段，可以用一句加粗式小标题开头。
2. 必须基于给定数据，可以解释、归因、对比、点出值得留意的地方；但不得编造数据中没有的数字或事实。
3. 所有金额写人民币（元），不要自己换算美元；保留两位有效数字的近似表达即可（如 12.8 万）。
4. 不做买卖建议、不预测价格。
5. 直接输出正文，不要 JSON、不要代码块。

数据：
{data_txt}
"""

def call(temp):
    key = os.environ.get("LLM_API_KEY")
    base = (os.environ.get("LLM_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL") or "doubao-seed-1-6-250615"
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temp}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read().decode())
    return out["choices"][0]["message"]["content"].strip()

FACTS = """【可引用事实，数字只能照抄，不得自行计算或换算】
总资产 {total} 元；今日变动 {day} 元（{pct}）。
传统股票与基金 {trad} 元，占 {wt}%；加密货币 {crypto} 元，占 {wc}%；现金 {cash} 元，占 {wcs}%。
加密账户口径（含稳定币）{acc} 元，其中稳定币 {stb} 元；支付宝现金 {ali} 元。
BTC {btc} 元，占加密币值 {wbtc}%；SOL {sol} 元，占 {wsol}%；BGB {bgb} 元。
累计总盈亏 {pnl} 元（{pnlp}）；其中加密 {pnlc} 元（收益率 {pnlcp}）、传统 {pnlt} 元（收益率 {pnltp}）。
近 5 个交易日累计 {r5} 元（{r5p}），最高点 {hi} 元、最低点 {lo} 元。
净入金总额 {net} 元；加密账户口径净入金 {netc} 元；划入美股账户 {stock} 元（内部划转）。
最近一次链上出金：11-06，1,000.04 USDT，约 {dout} 元。
近 30 日理财派息 64.76 USDT，约 {earn} 元，折年化约 {apr}%。
已实现盈亏 0 元，卖出 0 笔。
持仓份额已 {age} 天未更新。
"""
FACTS_TXT = FACTS.format(total="128,291", day="+68", pct="+0.05%", trad="29,083", wt="22.7",
    crypto="58,174", wc="45.5", cash="40,825", wcs="31.8", acc="94,330", stb="36,156", ali="4,669",
    btc="37,166", wbtc="63.7", sol="21,032", wsol="36.0", bgb="185",
    pnl="−6,306", pnlp="−4.85%", pnlc="−6,276", pnlcp="−10.03%", pnlt="−30", pnltp="−0.10%",
    r5="−6,696", r5p="−5.20%", hi="13.0 万", lo="12.6 万",
    net="115,705", netc="100,780", stock="14,940", dout="6,690", earn="433", apr="5.6", age="5")

FREE_PROMPT = f"""这是我自己维护的个人资产仪表台，下面是当日事实清单。请像自己复盘一样，写一段当日资产观察，具体要求：
1. 中文，250~400 字，3 段左右；第一段给一句总判断，第二段讲变化和原因，第三段点出一两个值得注意的结构事实。
2. 只能引用事实清单里出现过的数字，不得自行计算比例、不得互相推导新数字；没有的数字就说"未单独统计"或直接不提。
3. 金额单位用元，可写"约 12.8 万"这类近似，但近似必须对应清单里的原值。
4. 不做买卖建议，不预测价格，不评价好坏对错，只做中性陈述。
5. 直接输出正文，不要 JSON、不要标题层级。

{FACTS_TXT}
"""


def call2(temp, prompt_text):
    key = os.environ.get("LLM_API_KEY")
    base = (os.environ.get("LLM_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
    model = os.environ.get("LLM_MODEL") or "doubao-seed-1-6-250615"
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    payload = {"model": model, "messages": [{"role": "user", "content": prompt_text}], "temperature": temp}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read().decode())
    return out["choices"][0]["message"]["content"].strip()

for t in (0.3, 0.6):
    print(f"\n########## FACTS temp={t} ##########")
    try:
        print(call2(t, FREE_PROMPT))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e)[:200])
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e)[:200])
