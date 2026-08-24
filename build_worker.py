#!/usr/bin/env python3
"""生成 worker.js: 内嵌 options_live.html 的 Cloudflare Worker(纯转发代理, 零解析, 免费层最稳)"""
import re

html = open("options_live.html").read()
assert "`" not in html, "HTML 包含反引号, 不能内嵌"
assert "${" not in html, "HTML 包含 ${, 不能内嵌"

WORKER = r'''// 期权链查询 - Cloudflare Worker(纯转发代理, 零解析)
// 部署后: https://<你的worker>.workers.dev/ 手机浏览器直接访问
// Worker 只做: 1) 服务 HTML 页面 2) 转发 CBOE 请求并加 CORS 头
// 所有数据解析在浏览器端完成 -> CPU 占用极小, 免费层 10 万请求/天绰绰有余
const HTML = `__HTML__`;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }
    if (url.pathname === '/api/quote') {
      const raw = url.searchParams.get('symbol') || '';
      const syms = raw.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
      if (!syms.length) {
        return Response.json({ ok: false, error: '缺少 symbol 参数, 如 /api/quote?symbol=BABA' }, { status: 400, headers: cors });
      }
      if (syms.length > 20) {
        return Response.json({ ok: false, error: '单次最多 20 个标的' }, { status: 400, headers: cors });
      }
      const symbols = {};
      const failed = [];
      for (const sym of syms) {
        try {
          const r = await fetch(`https://cdn.cboe.com/api/global/delayed_quotes/options/${sym}.json`, {
            headers: { 'User-Agent': 'Mozilla/5.0 (compatible; OptionChainViewer/1.0)' },
          });
          if (!r.ok) { failed.push(sym); continue; }
          symbols[sym] = await r.json();  // 原始 JSON 透传, 浏览器端解析
        } catch (e) {
          failed.push(sym);
        }
      }
      return Response.json({
        ok: true,
        fetched_at: new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC',
        symbols,
        failed,
      }, { headers: cors });
    }
    if (url.pathname === '/' || url.pathname === '/index.html') {
      return new Response(HTML, {
        headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store, max-age=0', ...cors },
      });
    }
    return Response.json({ ok: false, error: 'not found' }, { status: 404, headers: cors });
  },
};
'''

worker = WORKER.replace("__HTML__", html)
open("worker.js", "w").write(worker)
print(f"已生成 worker.js ({len(worker)} bytes, HTML {len(html)} bytes)")
