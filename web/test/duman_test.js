// Hızlı duman testi: sayfa yükleniyor, simülasyon bitiyor, konsolda hata yok.
const http = require("http"), fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const DIST = path.join(__dirname, "..", "dist"), NM = path.join(__dirname, "..", "node_modules");
const s = http.createServer((q, r) => { const p = path.join(DIST, decodeURIComponent(q.url.split("?")[0]).replace(/\/$/, "/index.html"));
  fs.readFile(p, (e, b) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { "content-type": p.endsWith(".wasm") ? "application/wasm" : p.endsWith(".html") ? "text/html; charset=utf-8" : "application/json" }); r.end(b); }); }).listen(8766);
(async () => {
  const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell", args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const pg = await b.newPage({ viewport: { width: 900, height: 600 } });
  const h = []; pg.on("console", (m) => m.type() === "error" && h.push(m.text())); pg.on("pageerror", (e) => h.push(e.message));
  pg.on("requestfailed", (r) => h.push("istek: " + r.url().slice(-50)));
  await pg.route("https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js", (r) => r.fulfill({ path: path.join(NM, "maplibre-gl/dist/maplibre-gl.js") }));
  await pg.route("https://cdn.jsdelivr.net/npm/pmtiles@3.2.1/dist/pmtiles.js", (r) => r.fulfill({ path: path.join(NM, "pmtiles/dist/pmtiles.js") }));
  await pg.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await pg.goto("http://localhost:8766/");
  await pg.waitForFunction(() => document.getElementById("durum").hidden, null, { timeout: 90000 });
  await pg.waitForTimeout(3000);
  const o = await pg.evaluate(() => ({ alan: document.getElementById("o-alan").textContent, bina: document.getElementById("o-bina").textContent,
    liste: document.querySelectorAll("#ilk-liste li").length, su: !!window.__harita.getLayer("su") }));
  console.log(JSON.stringify(o), "\nhatalar:", h.filter((x) => !/fonts\.g/.test(x) && !/ERR_FAILED/.test(x)));
  await b.close(); s.close();
})();
