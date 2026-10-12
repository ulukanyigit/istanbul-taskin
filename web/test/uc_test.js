// 2B yumuşak su ve 3B görünüm ekran görüntüleri. Çalıştırma: node web/test/uc_test.js <çıktı> [koyu]
const http = require("http"), fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const DIST = path.join(__dirname, "..", "dist"), NM = path.join(__dirname, "..", "node_modules");
const OUT = process.argv[2] || "/tmp/uc"; const KOYU = process.argv.includes("koyu");
fs.mkdirSync(OUT, { recursive: true });
const s = http.createServer((q, r) => { const p = path.join(DIST, decodeURIComponent(q.url.split("?")[0]).replace(/\/$/, "/index.html"));
  fs.readFile(p, (e, b) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { "content-type": p.endsWith(".wasm") ? "application/wasm" : p.endsWith(".html") ? "text/html; charset=utf-8" : "application/json" }); r.end(b); }); }).listen(8767);
(async () => {
  const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell", args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const pg = await b.newPage({ viewport: { width: 1280, height: 800 }, colorScheme: KOYU ? "dark" : "light" });
  const h = []; pg.on("console", (m) => (m.type() === "error" || m.type() === "warning") && h.push(m.text())); pg.on("pageerror", (e) => h.push("pageerror " + e.message));
  await pg.route("https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js", (r) => r.fulfill({ path: path.join(NM, "maplibre-gl/dist/maplibre-gl.js") }));
  await pg.route("https://cdn.jsdelivr.net/npm/pmtiles@3.2.1/dist/pmtiles.js", (r) => r.fulfill({ path: path.join(NM, "pmtiles/dist/pmtiles.js") }));
  await pg.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await pg.goto("http://localhost:8767/");
  await pg.waitForFunction(() => document.getElementById("durum").hidden, null, { timeout: 120000 });
  await pg.waitForTimeout(3000);
  await pg.screenshot({ path: path.join(OUT, "1_genel.png"), timeout: 300000 });
  const bekle = () => pg.evaluate(() => new Promise((r) => { const m = window.__harita; if (!m.isMoving()) r(); else m.once("moveend", r); }));
  await pg.evaluate(() => window.__harita.jumpTo({ center: [28.896, 41.0425], zoom: 15.3 }));
  await bekle(); await pg.waitForTimeout(6000);
  await pg.screenshot({ path: path.join(OUT, "2_yakın_2b.png"), timeout: 300000 });
  await pg.click(".uc-dugme");
  await pg.waitForTimeout(2500); await bekle(); await pg.waitForTimeout(9000);
  await pg.screenshot({ path: path.join(OUT, "3_3b.png"), timeout: 300000 });
  console.log(JSON.stringify(h.filter((x) => !/fonts\.g|ERR_FAILED/.test(x)).slice(0, 15), null, 1));
  await b.close(); s.close();
})().catch((e) => { console.error(e); process.exit(1); });
