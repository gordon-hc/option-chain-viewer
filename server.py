#!/usr/bin/env python3
"""
本地期权查询服务(按需抓取, 不落盘)
  - GET /                -> 查询页面(options_live.html)
  - GET /api/quote?symbol=BABA[,AAPL] -> 实时转抓 CBOE 延迟报价, 返回 JSON
  - 内存缓存 5 分钟, 同一标的重复查询不重复请求 CBOE

启动: .venv/bin/python server.py
手机访问: 与电脑同一 WiFi, 浏览器打开 http://<电脑局域网IP>:8788/
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from generate_html_report import fetch_chain

CACHE_TTL = 300  # 缓存秒数
_cache = {}
_lock = threading.Lock()


def fetch_symbols(symbols):
    """按需抓取, 透传 CBOE 原始 JSON(解析在浏览器端), 返回 {symbol: raw_doc}"""
    out = {}
    for sym in symbols:
        with _lock:
            hit = _cache.get(sym)
            if hit and time.time() - hit[0] < CACHE_TTL:
                out[sym] = hit[1]
                continue
        try:
            doc = fetch_chain(sym)
            with _lock:
                _cache[sym] = (time.time(), doc)
            out[sym] = doc
        except Exception:
            pass  # 失败的不放入结果, 由 failed 列表体现
    return out


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/quote":
            q = parse_qs(url.query)
            raw = q.get("symbol", [""])[0]
            syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
            if not syms:
                return self._json({"ok": False, "error": "缺少 symbol 参数, 如 /api/quote?symbol=BABA"}, 400)
            if len(syms) > 20:
                return self._json({"ok": False, "error": "单次最多 20 个标的"}, 400)
            try:
                result = fetch_symbols(syms)
                failed = [s for s in syms if s not in result]
                return self._json({
                    "ok": True,
                    "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "symbols": result,
                    "failed": failed,
                })
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        elif url.path in ("/", "/index.html"):
            try:
                with open("options_live.html", "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                return self._json({"ok": False, "error": "options_live.html 不存在"}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 静默


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    PORT = 8788
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    ip = lan_ip()
    print("=" * 56)
    print("期权查询服务已启动")
    print(f"  电脑访问: http://127.0.0.1:{PORT}/")
    print(f"  手机访问: http://{ip}:{PORT}/  (需与电脑同一 WiFi)")
    print("  按 Ctrl+C 停止")
    print("=" * 56)
    srv.serve_forever()
