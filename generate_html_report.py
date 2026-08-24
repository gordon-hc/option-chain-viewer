#!/usr/bin/env python3
"""
生成自包含 HTML 期权链查询页面(CBOE 公开延迟报价, 免费, 支持多标的)
用法:
    .venv/bin/python generate_html_report.py                          # 默认 BABA
    .venv/bin/python generate_html_report.py --symbols BABA,AAPL,TSLA  # 多标的

页面功能:
  - 顶部"标的"下拉切换; "行权价"下拉选择
  - 表格: 各到期日 Call/Put 的 bid/ask/mid/IV/Delta/价差, 价差异常高亮
  - SVG 折线图: Call/Put mid 价格随到期日变化
"""
import argparse
import json
import re
import ssl
import time
from urllib.request import Request, urlopen

OSYM = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def parse_osymbol(code):
    m = OSYM.match(code)
    if not m:
        return None
    _, ymd, right, strike = m.groups()
    exp = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
    return exp, right, float(strike) / 1000.0


def fetch_chain(symbol):
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json",
    })
    ctx = ssl.create_default_context()
    ctx.load_verify_locations("/etc/ssl/cert.pem")
    with urlopen(req, timeout=30, context=ctx) as r:
        return json.load(r)


def fmt(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return -1.0


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
  :root { --c-call: #0a7d3c; --c-put: #b3261e; --bg: #f6f7f9; --card: #fff; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: #1c2430; padding: 16px; }
  header { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; background: var(--card); border-radius: 10px; padding: 12px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  header h1 { font-size: 18px; margin-right: 8px; }
  .chip { font-size: 12px; color: #5b6472; background: #eef0f3; border-radius: 12px; padding: 3px 10px; }
  label { font-size: 13px; color: #5b6472; }
  select { font-size: 14px; padding: 6px 10px; border: 1px solid #cfd4dc; border-radius: 8px; background: #fff; min-width: 130px; }
  .wrap { display: flex; gap: 14px; margin-top: 14px; flex-wrap: wrap; }
  .panel { background: var(--card); border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; }
  #chartPanel { flex: 1 1 480px; min-width: 320px; }
  #tablePanel { flex: 2 1 560px; min-width: 320px; max-height: 640px; overflow: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th, td { padding: 5px 7px; text-align: right; border-bottom: 1px solid #eceff3; white-space: nowrap; }
  th { position: sticky; top: 0; background: #f2f4f7; color: #46505e; font-weight: 600; z-index: 2; }
  td.exp, td.flag { text-align: left; }
  .c { color: var(--c-call); } .p { color: var(--c-put); }
  .wide td { background: #fff7d6; } .narrow td { background: #e3f0fd; }
  .legend { display: flex; gap: 14px; font-size: 12px; color: #5b6472; margin: 6px 0; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; }
  .sub { font-size: 12px; color: #8a93a1; }
  .foot { margin-top: 12px; font-size: 12px; color: #8a93a1; }
</style>
</head>
<body>
<header>
  <h1>期权链查询</h1>
  <label>标的
    <select id="symSel"></select>
  </label>
  <label>行权价
    <select id="strikeSel"></select>
  </label>
  <label>视图
    <select id="viewSel">
      <option value="both">Call + Put</option>
      <option value="c">仅 Call</option>
      <option value="p">仅 Put</option>
    </select>
  </label>
  <span class="chip" id="ts"></span>
  <span class="chip" id="spot"></span>
  <span class="chip" id="status" style="background:#e8f5e9;color:#0a7d3c">正在加载...</span>
</header>
<div class="wrap">
  <div class="panel" id="chartPanel">
    <div class="legend">
      <span><span class="dot" style="background:var(--c-call)"></span>Call mid</span>
      <span><span class="dot" style="background:var(--c-put)"></span>Put mid</span>
      <span class="sub" id="chartNote"></span>
    </div>
    <svg id="chart" width="100%" viewBox="0 0 820 300" preserveAspectRatio="xMidYMid meet"></svg>
  </div>
  <div class="panel" id="tablePanel"></div>
</div>
<p class="foot">数据源: CBOE 公开延迟报价(免费, 约15分钟延迟)。页面为离线快照, 重新抓取请运行 generate_html_report.py。</p>
<script>
window.onerror = function(msg, src, line, col) {
  var el = document.createElement('div');
  el.style.cssText = 'background:#fdecea;color:#b3261e;padding:10px 14px;margin:10px 16px;border-radius:8px;font-size:13px;font-family:monospace';
  el.textContent = 'JS 错误: ' + msg + ' (行 ' + line + ':' + col + ')';
  document.body.insertBefore(el, document.body.firstChild);
};
const ALLDATA = __DATA__;
const ALLMETA = __META__;

const symSel = document.getElementById('symSel');
const viewSel = document.getElementById('viewSel');
const strikeSel = document.getElementById('strikeSel');
const tablePanel = document.getElementById('tablePanel');
const chartEl = document.getElementById('chart');
const tsEl = document.getElementById('ts');
const spotEl = document.getElementById('spot');

let CUR = null;

Object.keys(ALLDATA).sort().forEach(s => {
  const opt = document.createElement('option');
  opt.value = s;
  opt.textContent = s;
  symSel.appendChild(opt);
});

function strikesOf() {
  // 键是字符串(如 "80.0", "115.0"), 按数值排序, 保持字符串避免整数键不匹配
  return Object.keys(ALLDATA[CUR]).sort((a,b)=>Number(a)-Number(b));
}

function quote(exp, right, strike) {
  const arr = ALLDATA[CUR][strike] || [];
  for (const q of arr) if (q[0] === exp && q[1] === right) return q;
  return null;
}

function allExpirations(strike) {
  const set = new Set();
  (ALLDATA[CUR][strike] || []).forEach(q => set.add(q[0]));
  return Array.from(set).sort();
}

function renderTable(strike, view) {
  const exps = allExpirations(strike);
  const rows = [];
  for (const exp of exps) {
    rows.push({ exp, c: quote(exp, 'C', strike), p: quote(exp, 'P', strike) });
  }
  const showC = view !== 'p', showP = view !== 'c';
  let html = '<table><thead><tr><th>到期日</th>';
  if (showC) html += '<th class="c">C bid</th><th class="c">C ask</th><th class="c">C mid</th><th>C IV</th><th>C Δ</th><th>C 价差</th>';
  if (showP) html += '<th class="p">P bid</th><th class="p">P ask</th><th class="p">P mid</th><th>P IV</th><th>P Δ</th><th>P 价差</th>';
  html += '<th>标记</th></tr></thead><tbody>';
  let hasC = false, hasP = false;
  for (const r of rows) {
    const cls = (r.c && r.c[14] === 'WIDE') || (r.p && r.p[14] === 'WIDE') ? ' class="wide"' : ((r.c && r.c[14]==='NARROW') || (r.p && r.p[14]==='NARROW') ? ' class="narrow"' : '');
    html += '<tr' + cls + '><td class="exp">' + r.exp + '</td>';
    const flag = [];
    if (r.c && r.c[14]) flag.push(r.c[14]); if (r.p && r.p[14]) flag.push(r.p[14]);
    if (showC) {
      if (r.c) { hasC = true; html += '<td>' + f(r.c[2]) + '</td><td>' + f(r.c[3]) + '</td><td class="c">' + f(r.c[4]) + '</td><td>' + f(r.c[5]) + '</td><td>' + f(r.c[6]) + '</td><td>' + f(r.c[7]) + '</td>'; }
      else html += '<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>';
    }
    if (showP) {
      if (r.p) { hasP = true; html += '<td>' + f(r.p[2]) + '</td><td>' + f(r.p[3]) + '</td><td class="p">' + f(r.p[4]) + '</td><td>' + f(r.p[5]) + '</td><td>' + f(r.p[6]) + '</td><td>' + f(r.p[7]) + '</td>'; }
      else html += '<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>';
    }
    html += '<td class="flag">' + flag.join('/') + '</td></tr>';
  }
  html += '</tbody></table>';
  tablePanel.innerHTML = html;
  drawChart(rows, strike, showC && hasC, showP && hasP);
}

function f(x) { return (x === null || x === undefined || x < 0) ? '-' : x; }

function drawChart(rows, strike, showC, showP) {
  const W = 820, H = 300, mL = 52, mR = 16, mT = 14, mB = 46;
  const vals = [];
  rows.forEach(r => { if (showC && r.c && r.c[4] > 0) vals.push(r.c[4]); if (showP && r.p && r.p[4] > 0) vals.push(r.p[4]); });
  if (!vals.length) { chartEl.innerHTML = '<text x="410" y="150" text-anchor="middle" fill="#8a93a1" font-size="13">该行权价下无有效报价</text>'; return; }
  let yMax = Math.max(...vals) * 1.12, yMin = Math.min(...vals) * 0.88;
  if (yMax - yMin < 0.02) { yMax += 0.02; yMin = Math.max(0, yMin - 0.02); }
  const y = v => mT + (H - mT - mB) * (1 - (v - yMin) / (yMax - yMin));
  const x = i => rows.length <= 1 ? W/2 : mL + (W - mL - mR) * i / (rows.length - 1);
  let svg = '';
  for (let g = 0; g <= 4; g++) {
    const v = yMin + (yMax - yMin) * g / 4, yy = y(v);
    svg += '<line x1="' + mL + '" y1="' + yy + '" x2="' + (W - mR) + '" y2="' + yy + '" stroke="#e6e9ee" stroke-width="1"/>';
    svg += '<text x="' + (mL - 6) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="10" fill="#8a93a1">' + v.toFixed(2) + '</text>';
  }
  function line(get, color) {
    const pts = [];
    rows.forEach((r, i) => { const v = get(r); if (v !== null && v > 0) pts.push([x(i), y(v)]); });
    if (pts.length < 2) return '';
    let d = '';
    pts.forEach((p, i) => d += (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1));
    let s = '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2"/>';
    pts.forEach(p => { s += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3" fill="' + color + '"/>'; });
    return s;
  }
  if (showC) svg += line(r => r.c ? r.c[4] : null, '#0a7d3c');
  if (showP) svg += line(r => r.p ? r.p[4] : null, '#b3261e');
  rows.forEach((r, i) => {
    if (rows.length > 12 && i % Math.ceil(rows.length/12) !== 0 && i !== rows.length-1) return;
    svg += '<text x="' + x(i) + '" y="' + (H - mB + 14) + '" text-anchor="middle" font-size="10" fill="#5b6472" transform="rotate(-40 ' + x(i) + ' ' + (H - mB + 14) + ')">' + r.exp.slice(5) + '</text>';
  });
  svg += '<text x="' + (W/2) + '" y="' + (H - 4) + '" text-anchor="middle" font-size="11" fill="#46505e">到期日</text>';
  chartEl.innerHTML = svg;
}

function selectSymbol(sym) {
  CUR = sym;
  const meta = ALLMETA[sym] || {};
  tsEl.textContent = '数据时间: ' + (meta.timestamp || '-');
  spotEl.textContent = '参考现价: ' + meta.spot;
  strikeSel.innerHTML = '';
  strikesOf().forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = Number(s).toFixed(2);
    strikeSel.appendChild(opt);
  });
  let best = null, bd = Infinity;
  strikesOf().forEach(s => { const d = Math.abs(Number(s) - meta.spot); if (d < bd) { bd = d; best = s; } });
  strikeSel.value = best;
  refresh();
}

function refresh() {
  if (!CUR) return;
  renderTable(strikeSel.value, viewSel.value);
}

symSel.addEventListener('change', () => selectSymbol(symSel.value));
strikeSel.addEventListener('change', refresh);
viewSel.addEventListener('change', refresh);
selectSymbol(symSel.value || Object.keys(ALLDATA)[0]);
document.getElementById('status').textContent = '已加载 ' + Object.keys(ALLDATA).length + ' 个标的';
document.getElementById('status').style.background = '#e8f5e9';
document.getElementById('status').style.color = '#0a7d3c';
</script>
</body>
</html>
"""


def process_symbol(symbol):
    """抓取+解析一个标的, 返回 (data, meta)"""
    doc = fetch_chain(symbol)
    options = doc["data"]["options"]
    timestamp = doc.get("timestamp", "")

    data = {}
    for o in options:
        parsed = parse_osymbol(o.get("option", ""))
        if not parsed:
            continue
        exp, right, strike = parsed
        bid, ask = fmt(o.get("bid")), fmt(o.get("ask"))
        if bid <= 0 or ask <= 0 or ask < bid:
            bid = ask = -1.0
        spread = round(ask - bid, 4) if bid > 0 else -1.0
        mid = round((bid + ask) / 2, 4) if spread > 0 else -1.0
        key = round(strike, 3)
        data.setdefault(key, []).append([
            exp, right, round(bid, 4), round(ask, 4), mid,
            round(fmt(o.get("iv")), 4), round(fmt(o.get("delta")), 4),
            spread, int(fmt(o.get("open_interest"))), int(fmt(o.get("volume"))),
            round(fmt(o.get("gamma")), 4), round(fmt(o.get("vega")), 4),
            round(fmt(o.get("theta")), 4), round(fmt(o.get("rho")), 4),
            "",  # 14: flag_spread
        ])

    # 价差异常检测(与 CSV 版一致): 按 (到期日, 方向) 分组
    groups = {}
    for strike, arr in data.items():
        for q in arr:
            groups.setdefault((q[0], q[1]), []).append((strike, q))
    for g in groups.values():
        g.sort(key=lambda x: x[0])
        spreads = [x[1][7] for x in g]
        n = len(g)
        for i, (strike, q) in enumerate(g):
            lo, hi = max(0, i - 2), min(n, i + 3)
            neigh = [spreads[j] for j in range(lo, hi) if j != i and spreads[j] > 0]
            if q[7] > 0.10 and neigh:
                med = sorted(neigh)[len(neigh) // 2]
                if med > 0.02:
                    ratio = q[7] / med
                    if ratio >= 3.0:
                        q[14] = "WIDE"
                    elif ratio <= 0.34:
                        q[14] = "NARROW"

    # put-call parity 粗估现价(最近到期日)
    exps_all = sorted({q[0] for arr in data.values() for q in arr})
    spot = -1.0
    if exps_all:
        nearest = exps_all[0]
        est = []
        for strike, arr in data.items():
            c = next((q for q in arr if q[0] == nearest and q[1] == "C"), None)
            p_ = next((q for q in arr if q[0] == nearest and q[1] == "P"), None)
            if c and p_ and c[4] > 0 and p_[4] > 0:
                est.append(c[4] - p_[4] + strike)
        if est:
            est.sort()
            spot = round(est[len(est) // 2], 2)

    n_quotes = sum(len(v) for v in data.values())
    return data, {"timestamp": timestamp, "spot": spot, "quotes": n_quotes}


def main():
    p = argparse.ArgumentParser(description="生成自包含 HTML 期权链查询页(多标的)")
    p.add_argument("--symbols", default="BABA", help="逗号分隔的标的列表, 如 BABA,AAPL,TSLA")
    p.add_argument("--out", default="options_query.html")
    p.add_argument("--interval", type=float, default=0.4, help="标的间抓取间隔秒数(避免被限流)")
    args = p.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    all_data, all_meta = {}, {}
    for sym in symbols:
        try:
            data, meta = process_symbol(sym)
        except Exception as e:
            print(f"[跳过] {sym}: 抓取失败 ({type(e).__name__}: {e})")
            continue
        all_data[sym] = data
        all_meta[sym] = meta
        print(f"[OK] {sym}: {meta['quotes']} 个报价, 行权价 {len(data)}, 估现价 {meta['spot']}")
        if sym != symbols[-1]:
            time.sleep(args.interval)

    if not all_data:
        print("错误: 没有成功抓取任何标的")
        raise SystemExit(1)

    html_out = (HTML_TEMPLATE
                .replace("__TITLE__", "期权链查询: " + ", ".join(all_data.keys()))
                .replace("__DATA__", json.dumps({k: {str(s): v for s, v in d.items()} for k, d in all_data.items()}))
                .replace("__META__", json.dumps(all_meta)))
    with open(args.out, "w") as f:
        f.write(html_out)
    print(f"已生成 {args.out} ({len(html_out)} bytes, {len(all_data)} 个标的)")


if __name__ == "__main__":
    main()
