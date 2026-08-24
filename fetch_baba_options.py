#!/usr/bin/env python3
"""
BABA 期权链全量报价抓取 + 价差/价格异常检测

用法:
    .venv/bin/python fetch_baba_options.py --symbol BABA
    .venv/bin/python fetch_baba_options.py --symbol BABA --port 4002   # IB Gateway 实盘
    .venv/bin/python fetch_baba_options.py --symbol BABA --delayed      # 强制延迟行情

输出:
    options_<symbol>_<时间戳>.csv  全量合约: 到期日/方向/行权价/买卖价/价差/中间价/相对价差/异常标记
    终端打印: 标的现价、价差异常合约、价格偏离异常合约

异常检测逻辑:
    flag_spread  WIDE   = 该合约 bid-ask 价差 >= 前后各2个邻居价差中位数的 3 倍
                 NARROW = 价差 <= 邻居中位数的 34%
    flag_price   OFF    = mid 价偏离前后邻居线性插值 > 15%

依赖: ib_async (pip install ib_async)
前提: TWS 或 IB Gateway 已运行并开启 API (Global Configuration -> API -> Settings)
      实盘端口: TWS 7496 / Gateway 4002; 模拟: 7497 / 4001
"""
import argparse
import asyncio
import csv
import math
import sys
from datetime import datetime
from statistics import median

from ib_async import IB, Stock, Option

BATCH = 50   # 每批并发行情请求数 (IB 活跃 ticker 上限约 100)
WAIT = 4.0   # 每批等待数据到达的秒数


def parse_args():
    p = argparse.ArgumentParser(description="抓取 IB 期权链并检测价差异常")
    p.add_argument("--symbol", default="BABA")
    p.add_argument("--port", type=int, default=7496,
                   help="TWS 实盘 7496 / 模拟 7497; IB Gateway 实盘 4002 / 模拟 4001")
    p.add_argument("--client-id", type=int, default=17)
    p.add_argument("--delayed", action="store_true",
                   help="使用 15 分钟延迟行情(未订阅 OPRA 实时行情时)")
    p.add_argument("--min-moneyness", type=float, default=0.0,
                   help="0=全部行权价; 0.5=仅保留现价 ±50%% 范围")
    p.add_argument("--out", default=None, help="输出 CSV 路径(默认自动生成)")
    return p.parse_args()


def fmt_price(x):
    """nan / None / <=0 统一为 -1 (无有效报价)"""
    if x is None or (isinstance(x, float) and (math.isnan(x) or x <= 0)):
        return -1.0
    return float(x)


def build_contracts(symbol, chains, spot, min_moneyness):
    contracts, seen = [], set()
    for ch in chains:
        for exp in ch.expirations:
            for strike in ch.strikes:
                if min_moneyness and spot:
                    if not (spot * (1 - min_moneyness) <= strike <= spot * (1 + min_moneyness)):
                        continue
                for right in ("C", "P"):
                    key = (exp, strike, right)
                    if key in seen:
                        continue
                    seen.add(key)
                    contracts.append(Option(symbol, exp, strike, right, "SMART",
                                            tradingClass=ch.tradingClass or symbol))
    return contracts


async def fetch_quotes(ib, contracts):
    rows = []
    skipped = 0
    for i in range(0, len(contracts), BATCH):
        batch = contracts[i:i + BATCH]
        # Python 3.12+ 必须用异步版(同步版 _run 会触发 event loop already running)
        # ib_async 2.x 要求合约先 qualify 拿到 conId 才能请求行情
        await ib.qualifyContractsAsync(*batch)
        # qualify 失败的合约(深度实值/虚值, IB 返回 Error 200)conId 保持 0, 必须跳过,
        # 否则 reqTickersAsync 内 hash(contract) 会抛 ValueError
        valid = [c for c in batch if getattr(c, "conId", 0) > 0]
        skipped += len(batch) - len(valid)
        if not valid:
            done = min(i + BATCH, len(contracts))
            print(f"  行情抓取 {done}/{len(contracts)} 完成 (本批 {len(batch)} 个全部无效, 跳过)", flush=True)
            continue
        tickers = await ib.reqTickersAsync(*valid)
        await asyncio.sleep(WAIT)
        for c, t in zip(valid, tickers):
            bid, ask = fmt_price(t.bid), fmt_price(t.ask)
            spread = ask - bid if (bid > 0 and ask > 0) else -1.0
            mid = (bid + ask) / 2 if spread > 0 else -1.0
            rows.append({
                "expiration": c.lastTradeDateOrContractMonth,
                "right": c.right,
                "strike": c.strike,
                "bid": bid, "ask": ask,
                "spread": round(spread, 4), "mid": round(mid, 4),
                "rel_spread": round(spread / mid, 4) if mid > 0 else -1.0,
                "last": fmt_price(t.last),
                "flag_spread": "", "flag_price": "",
            })
        for c in valid:
            ib.cancelMktData(c)
        done = min(i + BATCH, len(contracts))
        print(f"  行情抓取 {done}/{len(contracts)} 完成 (本批有效 {len(valid)}/{len(batch)}, 累计跳过 {skipped})", flush=True)
    return rows


def flag_anomalies(rows):
    """按 (到期日, 方向) 分组、行权价升序，检测价差异常与价格偏离"""
    groups = {}
    for r in rows:
        groups.setdefault((r["expiration"], r["right"]), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["strike"])
        strikes = [r["strike"] for r in g]
        spreads = [r["spread"] for r in g]
        mids = [r["mid"] for r in g]
        n = len(g)
        for i, r in enumerate(g):
            # --- 价差异常: 与前后各 2 个邻居的中位数比较 ---
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
            # --- 价格偏离: mid 偏离前后邻居线性插值 > 15% ---
            if r["mid"] > 0 and 0 < i < n - 1:
                x0, x1 = strikes[i - 1], strikes[i + 1]
                y0, y1 = mids[i - 1], mids[i + 1]
                if y0 > 0 and y1 > 0 and x1 != x0:
                    expected = y0 + (y1 - y0) * (strikes[i] - x0) / (x1 - x0)
                    if expected > 0.05 and abs(r["mid"] - expected) / expected > 0.15:
                        r["flag_price"] = "OFF"


async def get_spot(ib, stock, delayed):
    ticker = ib.reqMktData(stock, "", False, False)
    await asyncio.sleep(2.5)
    spot = ticker.marketPrice()
    if (math.isnan(spot) or spot <= 0) and not delayed:
        print("实时行情拿不到标的价(可能未订阅)，自动切换延迟行情 ...")
        ib.cancelMktData(stock)
        ib.reqMarketDataType(3)
        ticker = ib.reqMktData(stock, "", False, False)
        await asyncio.sleep(2.5)
        spot = ticker.marketPrice()
        delayed = True
    return spot, delayed


async def main(args):
    ib = IB()
    await ib.connectAsync("127.0.0.1", args.port, clientId=args.client_id, timeout=30)
    ib.reqMarketDataType(3 if args.delayed else 1)

    stock = Stock(args.symbol, "SMART", "USD")
    await ib.qualifyContractsAsync(stock)

    spot, delayed = await get_spot(ib, stock, args.delayed)
    if math.isnan(spot) or spot <= 0:
        print("ERROR: 拿不到标的现价 (bid/ask 均为空)。")
        print("       可能原因: 模拟账户未开通行情权限 -> IB 官网 账户管理 -> 市场数据订阅，")
        print("       勾选免费的 延迟美股行情(Delayed US Equities/Options) 后重新登录 Gateway。")
        ib.disconnect()
        sys.exit(1)
    print(f"{args.symbol} 现价: {spot:.2f}  (行情类型: {'延迟15分钟' if delayed else '实时'})")

    chains = await ib.reqSecDefOptParamsAsync(stock.symbol, "", stock.secType, stock.conId)
    contracts = build_contracts(args.symbol, chains, spot, args.min_moneyness)
    exps = sorted({c.lastTradeDateOrContractMonth for c in contracts})
    print(f"期权链: {len(contracts)} 个合约, {len(exps)} 个到期日 ({exps[0]} ~ {exps[-1]})")

    rows = await fetch_quotes(ib, contracts)
    valid = sum(1 for r in rows if r["spread"] > 0)
    print(f"有效双边报价: {valid}/{len(rows)}")

    if valid == 0 and not delayed:
        print("链报价全空(疑似 354 未订阅)，自动切换延迟行情重抓 ...")
        ib.reqMarketDataType(3)
        rows = await fetch_quotes(ib, contracts)
        valid = sum(1 for r in rows if r["spread"] > 0)
        print(f"有效双边报价(延迟): {valid}/{len(rows)}")

    flag_anomalies(rows)

    out = args.out or f"options_{args.symbol}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"全量数据已写入 {out} ({len(rows)} 行)")

    anom = [r for r in rows if r["flag_spread"]]
    poff = [r for r in rows if r["flag_price"]]
    print("\n== 价差异常 (WIDE=价差远宽于前后邻居, NARROW=远窄) ==")
    if anom:
        for r in sorted(anom, key=lambda r: (r["expiration"], r["strike"])):
            print(f"  {r['expiration']} {r['right']}{r['strike']:>7}  "
                  f"bid={r['bid']:<8.2f} ask={r['ask']:<8.2f} "
                  f"价差={r['spread']:<8.2f} mid={r['mid']:<8.2f} [{r['flag_spread']}]")
    else:
        print("  (无)")
    print("\n== 价格偏离异常 (mid 偏离相邻行权价插值 >15%) ==")
    if poff:
        for r in sorted(poff, key=lambda r: (r["expiration"], r["strike"])):
            print(f"  {r['expiration']} {r['right']}{r['strike']:>7}  "
                  f"bid={r['bid']:<8.2f} ask={r['ask']:<8.2f} "
                  f"mid={r['mid']:<8.2f} [{r['flag_price']}]")
    else:
        print("  (无)")
    print(f"\n汇总: 价差异常 {len(anom)} 个, 价格偏离异常 {len(poff)} 个")
    ib.disconnect()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
