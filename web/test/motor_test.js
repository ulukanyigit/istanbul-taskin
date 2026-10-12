// motor.js ↔ motor.py karşılaştırması. Çalıştırma: node web/test/motor_test.js <veri_klasörü> <su_seviyeleri.csv>
const fs = require("fs");
const { Motor } = require("../src/motor.js");
const { yukle } = require("./yukle.js");
const [dizin, csv] = process.argv.slice(2);
let t0 = Date.now();
const d = yukle(dizin);
const motor = new Motor(d);
console.log(`yüklendi ${Date.now() - t0} ms`);
const K = d.meta.kontrol_motor_py;
const satir = fs.readFileSync(csv, "utf8").trim().split("\n");
const bas = satir[0].split(",");
const tablo = satir.slice(1).map((s) => s.split(",").map(Number));
let hata = 0;
const tamam = (ad, a, b, tol) => {
  const ok = Math.abs(a - b) <= tol;
  if (!ok) hata++;
  console.log(`${ok ? "  ok " : "HATA "} ${ad}: js=${+a.toFixed(4)} py=${+b.toFixed(4)}`);
};
for (const P of [25, 50, 100]) {
  t0 = Date.now();
  const r = motor.tekAdim(P);
  console.log(`— ${P} mm (${Date.now() - t0} ms)`);
  let dep = 0; for (let b = 1; b <= motor.m; b++) dep += r.hacim[b];
  tamam("depolanan m³", dep, K[P].depolanan_m3, 1);
  for (const [b, v] of Object.entries(K[P].seviye_ornek)) tamam(`seviye #${b}`, r.seviye[b], v, 0.006);
  // tüm çukurlar: su_seviyeleri.csv'deki maks derinlik (2 ondalık) ile
  const ci = bas.indexOf(`maks_derinlik_${P}mm_m`), hi = bas.indexOf(`hacim_${P}mm_m3`);
  let maks = 0, maksV = 0, kotu = 0;
  for (const s of tablo) {
    const b = s[0], h = isNaN(r.seviye[b]) ? 0 : r.seviye[b];
    const e = Math.abs(h - s[ci]); if (e > maks) maks = e; if (e > 0.011) kotu++;
    const ev = Math.abs(r.hacim[b] - s[hi]); if (ev > maksV) maksV = ev;
  }
  tamam("tüm çukurlar en büyük derinlik farkı (m)", maks, 0, 0.011);
  tamam("tüm çukurlar en büyük hacim farkı (m³)", maksV, 0, 0.11);
  console.log(`      0,011 m'den fazla farklı çukur: ${kotu}`);
}
// zaman adımlı: drenajsız 50 mm / 60 dk → son adım tek adımla aynı olmalı
t0 = Date.now();
const S = motor.simule({ P_mm: 50, sure_dk: 60, sonra_dk: 0, dt_dk: 5, desen: "orta", drenaj_mmsa: 0 });
console.log(`— zaman adımlı 50 mm / 60 dk: ${S.N} adım, ${Date.now() - t0} ms`);
const r50 = motor.tekAdim(50);
let fark = 0;
for (let b = 1; b <= motor.m; b++) {
  const a = S.seviyeler[S.N * (motor.m + 1) + b], c = r50.seviye[b];
  if (!(isNaN(a) && isNaN(c))) fark = Math.max(fark, Math.abs(a - c));
}
tamam("zaman adımlı son adım ↔ tek adım seviye farkı", fark, 0, 1e-4);
const N = S.N;
// motor.js seviyeleri cm'ye yuvarlanmış hipsometriden gelir (≤1 cm fark) → eşiğe çok yakın birkaç bina farklı düşebilir
tamam("bina ≥10 cm (il içi)", S.st.bina10[N], K[50].bina_10cm_il_ici, K[50].bina_10cm_il_ici * 0.001);
tamam("bina ≥30 cm (il içi)", S.st.bina30[N], K[50].bina_30cm_il_ici, K[50].bina_30cm_il_ici * 0.001);
tamam("nüfus ≥10 cm (il içi)", S.st.nufus10[N], K[50].nufus_10cm_il_ici, K[50].nufus_10cm_il_ici * 0.001);
tamam("kapalı yol km (il içi)", S.st.yol_km[N], K[50].kapali_yol_km_il_ici, 0.5);
tamam("ıslak alan km² (il içi)", S.st.islak_km2[N], K[50].islak_km2_il_ici, 0.05);
console.log(`      tesis (hastane/okul/itfaiye/metro): ${S.st.tesis.map((a) => a[N]).join(" / ")}`);
// drenajlı senaryo: daha az su
const D = motor.simule({ P_mm: 50, sure_dk: 60, sonra_dk: 120, dt_dk: 5, desen: "orta", drenaj_mmsa: 20, pompa: true, pompa_m3s: 0.5 });
console.log(`— drenaj 20 mm/sa + pompa: tepe ıslak alan ${Math.max(...D.st.islak_km2).toFixed(1)} km², son ${D.st.islak_km2[D.N].toFixed(1)} km², şebekeye ${(D.st.sebeke_m3[D.N] / 1e6).toFixed(2)} milyon m³`);
// kademe sırası: JS (basamakSirasi) ↔ Python (sira)
const { basamakSirasi } = require("../src/motor.js");
const js = basamakSirasi(motor.alici.subarray(0, motor.m0 + 1));
let ayni = true; for (let i = 0; i < motor.m0; i++) if (js[i] !== motor.sira[i]) { ayni = false; break; }
tamam("kademe sırası JS = Python", ayni ? 1 : 0, 1, 0);
// 1990 arazi örtüsü: tek adım 25 mm'de dolan çukurlar = 1990 eşiği ≤ 25 mm olanlar
if (motor.cn90 && d.model.esik90) {
  const S90 = motor.simule({ P_mm: 25, sure_dk: 5, sonra_dk: 0, dt_dk: 5, desen: "duzgun", arazi: "1990" });
  const L = S90.seviyeler.subarray(S90.N * (motor.m + 1));
  let dolu = 0, bek = 0;
  for (let b = 1; b <= motor.m0; b++) { if (S90.dolmaDk[b] >= 0) dolu++; if (d.model.esik90[b] <= 25) bek++; }
  tamam("1990: 25 mm'de dolan çukur (motor ↔ eşik tablosu)", dolu, bek, bek * 0.01);
}
// menfez göletleri: kapalıyken boş, tıkalıyken dolu (yoğun yağışta)
if (motor.m > motor.m0) {
  const K = motor.m - motor.m0;
  const T = motor.simule({ P_mm: 100, sure_dk: 120, sonra_dk: 0, dt_dk: 5, desen: "orta", menfezler: Array.from({ length: K }, (_, i) => i) });
  const A0 = motor.simule({ P_mm: 100, sure_dk: 120, sonra_dk: 0, dt_dk: 5, desen: "orta" });
  let dolu = 0, bosAcik = 0;
  for (let g = 0; g < K; g++) {
    const id = motor.m0 + 1 + g;
    if (T.dolmaDk[id] >= 0) dolu++;
    if (!isNaN(A0.seviyeler[A0.N * (motor.m + 1) + id])) bosAcik++;
  }
  console.log(`      menfez: 100 mm'de ${dolu}/${K} gölet doluyor; menfezler açıkken su olan gölet: ${bosAcik}`);
  tamam("menfezler açıkken göletler boş", bosAcik, 0, 0);
  tamam("tıkalı menfezlerle bina ≥10 cm artar", T.st.bina10[T.N] >= A0.st.bina10[A0.N] ? 1 : 0, 1, 0);
}
console.log(hata ? `\n${hata} HATA` : "\nTÜM KONTROLLER GEÇTİ");
process.exit(hata ? 1 : 0);
