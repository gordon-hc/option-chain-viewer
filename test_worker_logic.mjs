import fs from "fs";

// 从 options_live.html 提取前端解析逻辑并测试(模拟浏览器环境)
const html = fs.readFileSync("./options_live.html", "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
if (!script) {
  console.log("FAIL: 未找到 script");
  process.exit(1);
}
// 提取 fmtRaw + parseSymbolDoc
const fmtM = script.match(/function fmtRaw[\s\S]*?\n\}/);
const parseM = script.match(/function parseSymbolDoc[\s\S]*?\n  return \{ data, meta: \{ timestamp, spot, quotes, cached: false \} \};\n\}/);
if (!fmtM || !parseM) {
  console.log("FAIL: 未找到解析函数");
  process.exit(1);
}
eval(fmtM[0] + "\n" + parseM[0] + "\nglobalThis.parseSymbolDoc = parseSymbolDoc;");

const doc = await (await fetch("https://cdn.cboe.com/api/global/delayed_quotes/options/BABA.json", {
  headers: { "User-Agent": "Mozilla/5.0" },
})).json();

const { data, meta } = parseSymbolDoc(doc);
console.log("quotes:", meta.quotes, "| strikes:", Object.keys(data).length, "| spot:", meta.spot);
const c = (data["115.0"] || []).find(q => q[0] === "2026-08-28" && q[1] === "C");
console.log("8/28 C115:", JSON.stringify(c.slice(2, 8)));
const wide = Object.values(data).flat().filter(q => q[14] === "WIDE").length;
const narrow = Object.values(data).flat().filter(q => q[14] === "NARROW").length;
console.log("异常: WIDE", wide, "NARROW", narrow);
console.log(meta.quotes > 1000 && c && c[4] > 0 ? "LOGIC_OK" : "LOGIC_FAIL");
