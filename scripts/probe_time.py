import json, os, time, urllib.request
d = json.load(open("data/dashboard.json", encoding="utf-8"))
a = d["analysis"]
facts = a.get("facts") or []
key = os.environ["LLM_API_KEY"]
base = (os.environ.get("LLM_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
model = os.environ.get("LLM_MODEL")
url = base if base.endswith("/chat/completions") else base + "/chat/completions"
prompt = ("写 4 段当日资产观察，550~750 字，所有数字用给定占位符。\n" + "\n".join("- " + f for f in facts))
for mt in (500, 900):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.6, "max_tokens": mt}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read()
        dt = time.time() - t0
        out = json.loads(raw)
        content = out["choices"][0]["message"]["content"]
        print(f"\n#### max_tokens={mt} elapsed={dt:.1f}s chars={len(content)} ####")
        print(content)
    except Exception as e:
        print(f"\n#### max_tokens={mt} FAILED after {time.time()-t0:.1f}s: {type(e).__name__} {str(e)[:120]}")
