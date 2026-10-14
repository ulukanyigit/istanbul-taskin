"""Simülatörü derler: src/index.html + motor.js + MapLibre CSS → dist/index.html, src/uyari.html → dist/uyari.html, veri → dist/veri.

dist/veri/uyari (günlük uyarı çıktısı, GitHub Actions yazar) derleme sırasında korunur.

Çalıştırma: python web/build.py   (önce: cd web && npm install)
"""
import os
import shutil

KOK = os.path.dirname(os.path.abspath(__file__))
SRC, DIST, VERI = (os.path.join(KOK, p) for p in ("src", "dist", os.path.join("public", "veri")))
html = open(os.path.join(SRC, "index.html"), encoding="utf-8").read()
motor = open(os.path.join(SRC, "motor.js"), encoding="utf-8").read()
css = open(os.path.join(KOK, "node_modules", "maplibre-gl", "dist", "maplibre-gl.css"), encoding="utf-8").read()
assert "</script" not in motor
# İkili dosyalar (.bin, .pbf, PMTiles parçaları) ".wasm" ekiyle yayımlanır: artifact barındırıcısı yalnız bilinen
# web türlerini sunuyor ve application/wasm baytları olduğu gibi iletiyor. Sayfa aynı eki URL'lere ekler.
EK = ".wasm"
html = html.replace("/*MOTOR_JS*/", motor).replace("/*MAPLIBRE_CSS*/", css).replace("/*IKILI_EK*/", EK)
UYARI = os.path.join(DIST, "veri", "uyari")
yedek = os.path.join(KOK, "_uyari_yedek")
if os.path.exists(UYARI):
    shutil.rmtree(yedek, ignore_errors=True); shutil.copytree(UYARI, yedek)
if os.path.exists(DIST):
    shutil.rmtree(DIST)
os.makedirs(os.path.join(DIST, "veri"))
if os.path.exists(yedek):
    shutil.copytree(yedek, UYARI); shutil.rmtree(yedek)
open(os.path.join(DIST, "index.html"), "w", encoding="utf-8").write(html)
uyari = open(os.path.join(SRC, "uyari.html"), encoding="utf-8").read()
uyari = uyari.replace("/*MAPLIBRE_CSS*/", css).replace("/*IKILI_EK*/", EK)
open(os.path.join(DIST, "uyari.html"), "w", encoding="utf-8").write(uyari)
n = 0
for kok, _, dosyalar in os.walk(VERI):
    if "_tmp" in kok:
        continue
    for f in dosyalar:
        if f.endswith(".pmtiles"):
            continue
        hedef = os.path.join(DIST, "veri", os.path.relpath(os.path.join(kok, f), VERI))
        if not f.endswith((".json", ".geojson")):
            hedef += EK
        os.makedirs(os.path.dirname(hedef), exist_ok=True)
        shutil.copy(os.path.join(kok, f), hedef)
        n += 1
boyut = sum(os.path.getsize(os.path.join(k, f)) for k, _, fs in os.walk(DIST) for f in fs)
print(f"dist/index.html {len(html.encode()) / 1e3:.0f} KB, {n} veri dosyası, toplam {boyut / 1e6:.1f} MB")
