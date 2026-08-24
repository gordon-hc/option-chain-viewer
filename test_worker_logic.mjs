import fs from "fs";

// 从本地 options_live.html 提取前端解析逻辑, 用线上 API 真实返回重放
const html = fs.readFileSync("./options_live.html", "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const fmtM = script.match(/function fmtRaw[\s\S]*?\n\}/);
const parseM = script.match(/function parseSymbolDoc[\s\S]*?\n  return \{ data, meta: \{ timestamp, spot, quotes, cached: false \} \};\n\}/);
if (!fmtM || !parseM) {
  console.log("FAIL: 未找到解析函数");
  process.exit(1);
}
eval(fmtM[0] + "\n" + parseM[0] + "\nglobalThis.parseSymbolDoc = parseSymbolDoc;");

const j = await (await fetch("https://option-chain-viewer.51gaofei.workers.dev/api/quote?symbol=BABA")).json();
console.log("API ok:", j.ok, "| symbols:", Object.keys(j.symbols || {}), "| failed:", j.failed);
const doc = j.symbols && j.symbols.BABA;
console.log("doc keys:", Object.keys(doc || {}).slice(0, 4), "| options 条数:", (doc && doc.data && doc.data.options || []).length);
const parsed = parseSymbolDoc(doc);
console.log("解析后 strike 数:", Object.keys(parsed.data).length, "| quotes:", parsed.meta.quotes, "| spot:", parsed.meta.spot);
const arr = parsed.data["115.0"];
console.log("115.0 报价数:", arr ? arr.length : "未命中");
console.log(Object.keys(parsed.data).length > 50 && arr ? "REPLAY_OK" : "REPLAY_FAIL");
