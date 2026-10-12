"""01_aoi — Havza tabanlı analiz alanı.

İl sınırı tek başına yetmez: İstanbul'a dışarıdan akan su da çukurları doldurur.
Bu yüzden analiz alanı = il sınırına değen HydroBASINS (seviye 12) havzaları
+ bunlara memba yönünden akan tüm havzalar.

Çıktılar
- Asset:  istanbul_taskin_aoi               (çözülmüş analiz alanı, sonraki scriptler kullanır)
- Drive:  istanbul_il_siniri.geojson        (raporlama/kırpma için il sınırı)
          aoi_havzalar.geojson              (havzalar tek tek, QGIS kontrolü için)
"""
import ee
from config import init, export_table

init()

# 1) İl sınırı (FAO GAUL 2015, seviye 1). "İstanbul"/"Istanbul" yazımına karşı esnek filtre.
il = (
    ee.FeatureCollection("FAO/GAUL/2015/level1")
    .filter(ee.Filter.eq("ADM0_NAME", "Turkey"))
    .filter(ee.Filter.stringContains("ADM1_NAME", "stanbul"))
)
n_il = il.size().getInfo()
if n_il != 1:
    raise SystemExit(f"İl sınırı filtresi {n_il} kayıt döndürdü (1 bekleniyordu). ADM1_NAME değerlerini kontrol edin.")
il_geom = il.geometry()

# 2) İl sınırına değen seviye-12 havzalar.
havzalar = ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_12")
yakin = havzalar.filterBounds(il_geom.buffer(60000).bounds())  # memba araması için çalışma penceresi
secili = set(havzalar.filterBounds(il_geom).aggregate_array("HYBAS_ID").getInfo())
print(f"İl sınırına değen havza: {len(secili)}")

# 3) Memba havzalarını ekle: NEXT_DOWN değeri seçili kümede olan havzalar, yeni havza kalmayana kadar.
for tur in range(1, 21):
    yeni = set(
        yakin.filter(ee.Filter.inList("NEXT_DOWN", list(secili)))
        .filter(ee.Filter.inList("HYBAS_ID", list(secili)).Not())
        .aggregate_array("HYBAS_ID")
        .getInfo()
    )
    if not yeni:
        break
    secili |= yeni
    print(f"  tur {tur}: +{len(yeni)} memba havzası")
else:
    print("UYARI: 20 turda memba araması bitmedi; 60 km pencere dar kalmış olabilir.")

aoi_havzalar = havzalar.filter(ee.Filter.inList("HYBAS_ID", list(secili)))
# HydroBASINS ve GAUL kıyı çizgileri kaba (15") olduğundan dar kıyı şeritleri dışarıda kalabilir.
# Havzalar + il sınırı birleştirilip 500 m tamponlanır; deniz pikselleri 02_dem'deki
# su maskesiyle zaten ayrılır.
aoi_geom = (
    aoi_havzalar.union(maxError=10).geometry()
    .union(il_geom, maxError=10)
    .buffer(500, maxError=10)
)

alan_il = il_geom.area(maxError=100).divide(1e6).getInfo()
alan_aoi = aoi_geom.area(maxError=100).divide(1e6).getInfo()
print(f"Toplam havza: {len(secili)}")
print(f"İl alanı (GAUL): {alan_il:,.0f} km²  |  Analiz alanı: {alan_aoi:,.0f} km²")

# 4) Dışa aktar.
export_table(ee.FeatureCollection([ee.Feature(aoi_geom, {"ad": "istanbul_taskin_aoi", "havza_sayisi": len(secili)})]), "istanbul_taskin_aoi", to_asset=True)
export_table(il.select(["ADM1_NAME"]), "istanbul_il_siniri")
export_table(aoi_havzalar.select(["HYBAS_ID", "NEXT_DOWN", "SUB_AREA", "UP_AREA"]), "aoi_havzalar")

print("\nGörevler Cloud Console > Earth Engine > Tasks altında. 'istanbul_taskin_aoi' asset'i bitmeden 02_dem.py'yi çalıştırmayın.")
