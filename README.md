# Option Chain Viewer(期权链查询工具)

美股期权链查询工具:BABA / AAPL / TSLA 等任意标的,选一个行权价,横向对比所有到期日的 Call/Put 报价。

- **数据源**:CBOE 公开延迟报价(免费,无需任何券商账号;收盘后即收盘价)
- **零依赖**:单文件部署,不下载、不留存数据,输入代码即时抓取
- **手机可用**:部署后手机浏览器直接访问

## 网页版部署(推荐,手机随时可用)

单文件 `worker.js` 部署到 Cloudflare Workers(免费层 10 万请求/天,长期免费):

1. 注册 https://dash.cloudflare.com
2. Workers & Pages → Create Worker → 任意命名 → Deploy
3. Edit code → 粘贴 `worker.js` 全部内容 → Deploy
4. 手机浏览器打开 `https://<你的worker>.workers.dev/` → 输入代码 → 查询

## 本地版(电脑上跑)

```bash
.venv/bin/python server.py        # 启动本地服务, 端口 8788
# 电脑: http://127.0.0.1:8788/   手机(同一WiFi): http://<电脑IP>:8788/
```

## 生成静态 HTML 快照(离线版)

```bash
.venv/bin/python generate_html_report.py --symbols BABA,AAPL,TSLA
# 生成 options_query.html, 双击即可打开(数据内嵌)
```

## 命令行抓 CSV

```bash
.venv/bin/python fetch_baba_options_cboe.py --symbol BABA
# 生成 options_BABA_<时间戳>.csv, 并打印价差/价格异常
```

## 异常检测规则

| 标记 | 含义 |
|---|---|
| `WIDE` | 该合约 bid-ask 价差 ≥ 前后各 2 个邻居价差中位数的 3 倍 |
| `NARROW` | 价差 ≤ 邻居中位数的 34% |
| `OFF` | mid 价偏离相邻行权价线性插值 > 15% |

## 文件说明

| 文件 | 作用 |
|---|---|
| `worker.js` | Cloudflare Workers 部署文件(内嵌页面 + CBOE 转发代理) |
| `options_live.html` | 查询页面(输入代码→即时抓取→表格+图表+异常高亮) |
| `build_worker.py` | 把 options_live.html 打包进 worker.js |
| `server.py` | 本地按需查询服务(与 worker 同接口) |
| `generate_html_report.py` | 生成内嵌数据的静态 HTML 快照 |
| `fetch_baba_options_cboe.py` | 命令行抓取 CSV + 异常检测 |
| `fetch_baba_options.py` | IB 版抓取脚本(需 IB Gateway + OPRA 订阅,备用) |

## 数据说明

- CBOE 延迟约 15 分钟,盘前/收盘后显示前日收盘数据
- 现价由最近到期日的 put-call parity 中位数估算,仅供参考
- 价差异常标记基于同一到期日/方向相邻行权价的统计比较,冷门合约(深度虚值)可能出现误报,交易前请复核
