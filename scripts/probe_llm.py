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

for t in (0.3, 0.9):
    print(f"\n########## SAMPLE temp={t} ##########")
    try:
        print(call(t))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e)[:200])
