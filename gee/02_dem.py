"""02_dem — Analiz DEM'i ve tanı katmanları.

Ana DEM FABDEM'dir (Copernicus GLO-30'dan bina ve ağaç etkisi çıkarılmış hali).
30 m veri 10 m TM30 ızgarasına bilineer örneklenir. Amaç detay kazanmak değil;
Faz 3'te yol, dere, alt geçit gibi vektör yapıları ızgaraya yakabilmek.
Yükseklikler EGM2008 geoidine göredir.

Çıktılar (Drive / istanbul_taskin_gee)
- fabdem_10m.tif           Float32, 10 m   -> Faz 3 koşullandırmanın tabanı
- glo30_eksi_fabdem_30m.tif Float32, 30 m   -> bina/ağaç düzeltmesinin büyüklüğü (QC)
- glo30_su_maskesi_30m.tif  Byte, 30 m      -> 0 kara, 1 deniz, 2 göl, 3 nehir (deniz = çıkış)
"""
import ee
from config import init, aoi, export_image

init()
bolge_fc = aoi()
bolge = bolge_fc.geometry()
pencere = bolge.bounds(maxError=10)

# FABDEM (awesome-gee-community-catalog). Kimlik değişirse burada güncelleyin.
FABDEM_ID = "projects/sat-io/open-datasets/FABDEM"
fab_col = ee.ImageCollection(FABDEM_ID).filterBounds(bolge)
n_fab = fab_col.size().getInfo()
if n_fab == 0:
    raise SystemExit(f"{FABDEM_ID} analiz alanında karo döndürmedi; topluluk kataloğundaki güncel kimliği kontrol edin.")
print(f"FABDEM karo sayısı: {n_fab}")

fab_proj = fab_col.first().projection()
fabdem = (
    fab_col.mosaic().select(0).rename("elev")
    .setDefaultProjection(fab_proj)
    .resample("bilinear")
    .toFloat()
    .clip(bolge)
)

glo_col = ee.ImageCollection("COPERNICUS/DEM/GLO30").filterBounds(bolge)
glo_proj = glo_col.first().select("DEM").projection()
glo = glo_col.mosaic().setDefaultProjection(glo_proj)

fark = glo.select("DEM").subtract(fabdem).rename("glo30_minus_fabdem").toFloat().clip(bolge)
su = glo.select("WBM").rename("water_mask").toByte().clip(bolge)

# Kısa özet: DEM aralığı ve düzeltmenin büyüklüğü (30 m'de, hızlı).
ozet = fabdem.addBands(fark).reduceRegion(
    reducer=ee.Reducer.minMax().combine(ee.Reducer.mean(), sharedInputs=True),
    geometry=bolge, scale=90, maxPixels=1e10, bestEffort=True,
).getInfo()
print("Özet (90 m örnekleme):")
for k in sorted(ozet):
    v = ozet[k]
    print(f"  {k}: {v:.2f}" if isinstance(v, (int, float)) else f"  {k}: {v}")

export_image(fabdem, "fabdem_10m", pencere, scale=10)
export_image(fark, "glo30_eksi_fabdem_30m", pencere, scale=30)
export_image(su, "glo30_su_maskesi_30m", pencere, scale=30, nodata=255)

print("\nfabdem_10m büyük bir dosya; Drive'a birkaç parça halinde inebilir. QGIS'te 'Sanal Raster Oluştur' ile birleştirin.")
