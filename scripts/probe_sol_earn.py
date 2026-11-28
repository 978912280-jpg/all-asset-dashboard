import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bitget_ledger as L
KEY, SECRET, PASS = os.environ["BITGET_KEY"], os.environ["BITGET_SECRET"], os.environ["BITGET_PASSPHRASE"]

cands = [
    ("/api/v3/earn/savings/assets", {}),
    ("/api/v3/earn/staking/assets", {}),
    ("/api/v3/earn/pool/assets", {}),
    ("/api/v3/earn/financial/assets", {}),
    ("/api/v3/earn/earn/assets", {}),
    ("/api/v3/earn/asset/assets", {}),
    ("/api/v3/earn/savings/accounts", {}),
    ("/api/v3/earn/account", {}),
    ("/api/v3/earn/product/list", {"category": "STAKING"}),
    ("/api/v3/earn/products", {"category": "STAKING"}),
    ("/api/v3/account/assets", {}),
    ("/api/v3/account/sub-account-assets", {}),
    ("/api/v3/account/all-account-balance", {}),
    ("/api/v3/account/balance", {}),
]
for path, params in cands:
    try:
        d = L._get(path, params, KEY, SECRET, PASS, timeout=20)
        print("\nOK", path, params, json.dumps(d, ensure_ascii=False)[:1500])
    except Exception as e:
        print("\nFAIL", path, params, str(e)[:200])
