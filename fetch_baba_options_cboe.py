#!/usr/bin/env python3
"""
BABA 期权链全量抓取(CBOE 公开延迟报价, 免费, 无需 IB 权限/订阅)
数据源: https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json

输出: options_<symbol>_<时间戳>.csv
  expiration/right/strike/bid/ask/spread/mid/rel_spread/last/iv/open_interest/
  volume/delta/gamma/vega/theta/rho/flag_spread/flag_price

异常检测(与 IB 版一致):
  flag_spread  WIDE   = 该合约 bid-ask 价差 >= 前后各2个邻居价差中位数的 3 倍
               NARROW = 价差 <= 邻居中位数的 34%
  flag_price   OFF    = mid 价偏离前后邻居线性插值 > 15%
"""
import argparse
import csv
import json
import math
import re
import ssl
import sys
from datetime import datetime
from statistics import median
from urllib.request import Request, urlopen

OSYM = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def parse_osymbol(code):
    """BABA260828C00080000 -> (expiration, right, strike)"""
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
    ctx.load_verify_locations("/etc/ssl/cert.pem")  # macOS 系统 CA(macOS 版 Python 3.14 找不到默认 CA)
    with urlopen(req, timeout=30, context=ctx) as r:
        return json.load(r)


def fmt(x):
    return float(x) if x is not None else -1.0


def flag_anomalies(rows):
    """按 (到期日, 方向) 分组、行权价升序, 检测价差异常与价格偏离"""
    groups = {}
    for r in rows:
        groups.setdefault((r["expiration"], r["right"]), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["strike"])
        spreads = [r["spread"] for r in g]
        mids = [r["mid"] for r in g]
        strikes = [r["strike"] for r in g]
        n = len(g)
        for i, r in enumerate(g):
            lo, hi = max(0, i - 2), min(n, i + 3)
            neigh_s = [spreads[j] for j in range(lo, hi) if j != i and spreads[j] > 0]
            if r["spread"] > 0.10 and neigh_s:
                med = median(neigh_s)
                if med > 0.02:
                    ratio = r["spread"] / med
                    if ratio >= 3.0:
                        r["flag_spread"] = "WIDE"
                    elif ratio <= 0.34:
                        r["flag_spread"] = "NARROW"
            if r["mid"] > 0 and 0 < i < n - 1:
                x0, x1 = strikes[i - 1], strikes[i + 1]
                y0, y1 = mids[i - 1], mids[i + 1]
                if y0 > 0 and y1 > 0 and x1 != x0:
                    expected = y0 + (y1 - y0) * (strikes[i] - x0) / (x1 - x0)
                    if expected > 0.05 and abs(r["mid"] - expected) / expected > 0.15:
                        r["flag_price"] = "OFF"


def main():
    p = argparse.ArgumentParser(description="CBOE 免费期权链抓取 + 价差/价格异常检测")
    p.add_argument("--symbol", default="BABA")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    print(f"下载 {args.symbol} 期权链(CBOE 公开延迟报价)...")
    doc = fetch_chain(args.symbol)
    options = doc["data"]["options"]
    ts = doc.get("timestamp", "")
    print(f"数据时间戳: {ts}, 合约数: {len(options)}")

    rows = []
    for o in options:
        parsed = parse_osymbol(o.get("option", ""))
        if not parsed:
            continue
        exp, right, strike = parsed
        bid, ask = fmt(o.get("bid")), fmt(o.get("ask"))
        if bid <= 0 or ask <= 0 or ask < bid:
            bid = ask = -1.0
        spread = ask - bid if (bid > 0 and ask > 0) else -1.0
        mid = (bid + ask) / 2 if spread > 0 else -1.0
        rows.append({
            "expiration": exp,
            "right": right,
            "strike": strike,
            "bid": round(bid, 4),
            "ask": round(ask, 4),
            "spread": round(spread, 4),
            "mid": round(mid, 4),
            "rel_spread": round(spread / mid, 4) if mid > 0 else -1.0,
            "last": round(fmt(o.get("last_trade_price")), 4),
            "iv": round(fmt(o.get("iv")), 4),
            "open_interest": int(fmt(o.get("open_interest"))),
            "volume": int(fmt(o.get("volume"))),
            "delta": round(fmt(o.get("delta")), 4),
            "gamma": round(fmt(o.get("gamma")), 4),
            "vega": round(fmt(o.get("vega")), 4),
            "theta": round(fmt(o.get("theta")), 4),
            "rho": round(fmt(o.get("rho")), 4),
            "flag_spread": "",
            "flag_price": "",
        })

    flag_anomalies(rows)
    valid = sum(1 for r in rows if r["spread"] > 0)
    exps = sorted({r["expiration"] for r in rows})
    print(f"解析合约: {len(rows)} 个, 有效双边报价: {valid}, 到期日: {len(exps)} 个")

    out = args.out or f"options_{args.symbol}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fields = ["expiration", "right", "strike", "bid", "ask", "spread", "mid",
              "rel_spread", "last", "iv", "open_interest", "volume",
              "delta", "gamma", "vega", "theta", "rho",
              "flag_spread", "flag_price"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"全量数据已写入 {out} ({len(rows)} 行)")

    anom = [r for r in rows if r["flag_spread"]]
    poff = [r for r in rows if r["flag_price"]]
    print("\n== 价差异常 (WIDE=价差远宽于前后邻居, NARROW=远窄) ==")
    if anom:
        for r in sorted(anom, key=lambda r: (r["expiration"], r["strike"])):
            print(f"  {r['expiration']} {r['right']}{r['strike']:>8}  "
                  f"bid={r['bid']:<8.2f} ask={r['ask']:<8.2f} "
                  f"价差={r['spread']:<8.2f} mid={r['mid']:<8.2f} [{r['flag_spread']}]")
    else:
        print("  (无)")
    print("\n== 价格偏离异常 (mid 偏离相邻行权价插值 >15%) ==")
    if poff:
        for r in sorted(poff, key=lambda r: (r["expiration"], r["strike"])):
            print(f"  {r['expiration']} {r['right']}{r['strike']:>8}  "
                  f"bid={r['bid']:<8.2f} ask={r['ask']:<8.2f} "
                  f"mid={r['mid']:<8.2f} [{r['flag_price']}]")
    else:
        print("  (无)")
    print(f"\n汇总: 价差异常 {len(anom)} 个, 价格偏离异常 {len(poff)} 个")


if __name__ == "__main__":
    main()
