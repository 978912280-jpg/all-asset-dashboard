"""
全维度资产统计 —— 本地后台服务（仅 Python 标准库）。

作用：
  1) 静态托管本项目（index.html / admin.html / data …）
  2) 提供份额读写接口，让 admin.html 可以直接保存并触发重建
       GET  /api/holdings   读取份额配置
       POST /api/holdings   保存份额配置（自动备份旧文件 + 重建 data/dashboard.json）
       POST /api/rebuild    重新抓取价格并重建

用法：
  python3 scripts/server.py            # 默认 http://127.0.0.1:8787
  python3 scripts/server.py 8787 0.0.0.0   # 指定端口并允许局域网访问（注意无鉴权）

注意：接口无鉴权，默认只监听本机回环地址；不要把 0.0.0.0 暴露到公网。
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
CST = timezone(timedelta(hours=8))
BUILD = os.path.join(HERE, "build.py")

# 重建是串行的，避免并发写坏数据文件
BUILD_LOCK = threading.Lock()


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def run_build():
    with BUILD_LOCK:
        proc = subprocess.run([sys.executable, BUILD], cwd=ROOT,
                              capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "构建失败").strip()[-800:]
    dashboard = read_json(os.path.join(DATA, "dashboard.json"))
    s = dashboard.get("summary", {})
    return True, "总资产 %.2f CNY（传统 %.2f + 加密 %.2f）" % (
        s.get("total_cny") or 0, s.get("traditional_cny") or 0, s.get("crypto_cny") or 0)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (datetime.now(CST).strftime("%H:%M:%S"), fmt % args))

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return raw.decode("utf-8") if raw else ""

    def do_GET(self):
        if self.path.split("?")[0] == "/api/holdings":
            try:
                return self._json(200, read_json(os.path.join(DATA, "holdings.json")))
            except (OSError, ValueError) as e:
                return self._json(500, {"ok": False, "error": str(e)})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/holdings":
            return self._save_holdings()
        if path == "/api/rebuild":
            ok, msg = run_build()
            return self._json(200 if ok else 500, {"ok": ok, "message" if ok else "error": msg})
        return self._json(404, {"ok": False, "error": "not found"})

    def _save_holdings(self):
        try:
            data = json.loads(self._read_body())
        except ValueError:
            return self._json(400, {"ok": False, "error": "请求体不是合法 JSON"})

        if not isinstance(data, dict) or not isinstance(data.get("traditional"), list):
            return self._json(400, {"ok": False, "error": "缺少 traditional 列表"})

        for i, it in enumerate(data["traditional"]):
            if not isinstance(it, dict):
                return self._json(400, {"ok": False, "error": "traditional[%d] 不是对象" % i})
            shares = it.get("shares")
            try:
                v = float(shares if shares is not None else 0)
            except (TypeError, ValueError):
                return self._json(400, {"ok": False, "error": "traditional[%d] 的 shares 非法" % i})
            if v < 0:
                return self._json(400, {"ok": False, "error": "traditional[%d] 的 shares 不能为负" % i})
            it["shares"] = v
            cost = it.get("cost_price")
            try:
                cv = float(cost if cost is not None else 0)
            except (TypeError, ValueError):
                return self._json(400, {"ok": False, "error": "traditional[%d] 的 cost_price 非法" % i})
            if cv < 0:
                return self._json(400, {"ok": False, "error": "traditional[%d] 的 cost_price 不能为负" % i})
            it["cost_price"] = cv

        # 保留可能被前端丢弃的固定段落
        old = read_json(os.path.join(DATA, "holdings.json"))
        for key in ("meta", "fx", "crypto"):
            if key not in data and key in old:
                data[key] = old[key]
        data.setdefault("meta", {}).setdefault("version", "1.0.0")
        data["meta"]["updated_at"] = datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")

        # 备份旧配置
        backup_dir = os.path.join(DATA, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now(CST).strftime("%Y%m%d-%H%M%S")
        write_json(os.path.join(backup_dir, "holdings-%s.json" % stamp), old)

        write_json(os.path.join(DATA, "holdings.json"), data)

        ok, msg = run_build()
        if not ok:
            return self._json(500, {"ok": False, "error": "份额已保存，但重建失败：" + msg})
        return self._json(200, {"ok": True, "message": msg})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    server = ThreadingHTTPServer((host, port), Handler)
    base = os.path.relpath(ROOT, os.getcwd())
    print("全维度资产统计后台已启动： http://%s:%d/" % ("127.0.0.1" if host == "127.0.0.1" else host, port))
    print("  仪表台： /index.html")
    print("  份额后台： /admin.html")
    print("  静态根目录： %s" % base)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
