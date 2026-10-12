// Tarayıcı testi: dist/ klasörünü yerel sunucuda açar, CDN betiklerini node_modules'tan verir, ekran görüntüsü alır.
// Çalıştırma: node web/test/ekran_test.js <çıktı_klasörü> [koyu]
const http = require("http"), fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const KOK = path.join(__dirname, "..");
const DIST = path.join(KOK, "dist"), NM = path.join(KOK, "node_modules");
const CIKTI = process.argv[2] || "/tmp/ekran";
const KOYU = process.argv.includes("koyu");
fs.mkdirSync(CIKTI, { recursive: true });
const TUR = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".geojson": "application/json", ".js": "text/javascript" };
const sunucu = http.createServer((q, r) => {
  const p = path.join(DIST, decodeURIComponent(q.url.split("?")[0]).replace(/\/$/, "/index.html"));
  fs.readFile(p, (e, b) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { "content-type": TUR[path.extname(p)] || "application/octet-stream" }); r.end(b); });
}).listen(8765);

(async () => {
  const tarayici = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell", args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const sonuc = {};
  for (const [ad, vp] of [["masaustu", { width: 1440, height: 900 }], ["telefon", { width: 400, height: 860 }]]) {
    const ctx = await tarayici.newContext({ viewport: vp, colorScheme: KOYU ? "dark" : "light", deviceScaleFactor: 1 });
    const sayfa = await ctx.newPage();
    const hatalar = [];
    sayfa.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") hatalar.push(m.type() + ": " + m.text()); });
    sayfa.on("pageerror", (e) => hatalar.push("pageerror: " + e.message));
    await sayfa.route("https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js", (r) => r.fulfill({ path: path.join(NM, "maplibre-gl/dist/maplibre-gl.js"), contentType: "text/javascript" }));
    await sayfa.route("https://cdn.jsdelivr.net/npm/pmtiles@3.2.1/dist/pmtiles.js", (r) => r.fulfill({ path: path.join(NM, "pmtiles/dist/pmtiles.js"), contentType: "text/javascript" }));
    await sayfa.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    const t0 = Date.now();
    await sayfa.goto("http://localhost:8765/");
    await sayfa.waitForFunction(() => document.getElementById("durum").hidden, null, { timeout: 120000 });
    const yuk = Date.now() - t0;
    await sayfa.waitForTimeout(4000);
    await sayfa.screenshot({ timeout: 180000,  path: path.join(CIKTI, `${ad}${KOYU ? "_koyu" : ""}_1.png`), fullPage: ad === "telefon" });
    sonuc[ad] = { yukleme_ms: yuk };
    if (ad === "masaustu") {
      // yakınlaş: Bayrampaşa–Güngören kuşağı
      await sayfa.evaluate(() => window.__harita && window.__harita.jumpTo({ center: [28.89, 41.045], zoom: 12.2 }));
      await sayfa.waitForTimeout(5000);
      await sayfa.screenshot({ timeout: 180000,  path: path.join(CIKTI, `${ad}${KOYU ? "_koyu" : ""}_2_yakın.png`) });
      // haritada su pikseline tıkla (merkez civarında)
      const t1 = Date.now();
      await sayfa.click("#t-ilk");
      await sayfa.waitForTimeout(500);
      await sayfa.click("#ilk-liste li:first-child button");
      await sayfa.waitForTimeout(4000);
      await sayfa.screenshot({ timeout: 180000,  path: path.join(CIKTI, `${ad}${KOYU ? "_koyu" : ""}_3_ilk.png`) });
      // senaryo değiştir: altyapı çalışıyor
      await sayfa.click("#t-senaryo");
      const t2 = Date.now();
      await sayfa.click("#altyapi-hazir .cip:nth-child(3)");
      await sayfa.waitForFunction(() => document.querySelector("#altyapi-hazir .cip:nth-child(3)").getAttribute("aria-pressed") === "true");
      await sayfa.waitForTimeout(3000);
      sonuc[ad].simule_ms = Date.now() - t2;
      await sayfa.screenshot({ timeout: 180000,  path: path.join(CIKTI, `${ad}${KOYU ? "_koyu" : ""}_4_drenaj.png`) });
      await sayfa.click("#t-karne");
      await sayfa.evaluate(() => window.__harita && window.__harita.jumpTo({ center: [28.95, 41.03], zoom: 11 }));
      await sayfa.waitForTimeout(4000);
      await sayfa.screenshot({ timeout: 180000,  path: path.join(CIKTI, `${ad}${KOYU ? "_koyu" : ""}_5_karne.png`) });
      sonuc[ad].fps = await sayfa.evaluate(() => new Promise((coz) => {
        const h = window.__harita; let n = 0; const t0 = performance.now();
        const f = () => { h.triggerRepaint(); n++; if (performance.now() - t0 < 2000) requestAnimationFrame(f); else coz(n / 2); }; f(); }));
    }
    sonuc[ad].hatalar = hatalar.slice(0, 20);
    await ctx.close();
  }
  console.log(JSON.stringify(sonuc, null, 1));
  await tarayici.close();
  sunucu.close();
})().catch((e) => { console.error(e); process.exit(1); });
