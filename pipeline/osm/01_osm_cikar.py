"""Faz 2 — OSM vektör verisi.

Girdi : data/raw/turkey-latest.osm.pbf (Geofabrik)
Çıktı : data/interim/osm_ham.gpkg       (analiz alanı kutusu, ham OSM katmanları, EPSG:5254)
        data/interim/osm_istanbul.gpkg  (tematik katmanlar, aşağıda)

QGIS Python konsolunda ya da OSGeo4W Shell'de çalışır:
    python 01_osm_cikar.py  <proje_kökü>
Proje kökü verilmezse dosyanın iki üst klasörü kullanılır.

Tematik katmanlar
- yollar            highway (yaya/bisiklet yolları hariç); kopru, tunel, katman alanlarıyla
- dereler           waterway river/stream/canal/drain/ditch; kapali = menfez veya kapalı dere
- menfezler         kapalı dere / menfez parçaları (tıkanma senaryosu adayları)
- kopruler          köprü/viyadük hatları (DEM'den çıkarılacak setler)
- alt_gecitler      ≤250 m yol tünelleri ve negatif katmanlı yollar (pompa arızası senaryosu)
- tuneller_uzun     uzun yol/ray tünelleri (yüzey çukuru değil; bilgi amaçlı)
- metro_girisleri   railway=subway_entrance
- kritik_tesisler   hastane, okul, itfaiye (nokta; poligonlar merkez noktasına çevrilir)
- binalar           building poligonları, kat sayısıyla
- ocaklar           landuse=quarry/landfill (açık ocaklar; tehlike listesinden çıkarılacak)
- havalimanlari     aeroway=aerodrome (İstanbul Havalimanı DEM'den sonra yeniden şekillendi)
- su_alanlari       natural=water, landuse=reservoir/basin
- kiyi_cizgisi      natural=coastline
"""
import os
import sys
from osgeo import gdal, ogr

gdal.UseExceptions()

KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(KOK, "data", "raw")
INT = os.path.join(KOK, "data", "interim")
GEE = os.path.join(KOK, "istanbul_taskin_gee")
PBF = os.path.join(RAW, "turkey-latest.osm.pbf")
HAM = os.path.join(INT, "osm_ham.gpkg")
CIKTI = os.path.join(INT, "osm_istanbul.gpkg")
CRS = "EPSG:5254"
os.makedirs(INT, exist_ok=True)

ALT_GECIT_MAX_M = 250  # bu uzunluğa kadar yol tünelleri "alt geçit" sayılır

# --- 1) Özel osmconf: ihtiyaç duyulan etiketleri ayrı sütun yap ---------------------------
OZNITELIK = {
    "points": "name,highway,railway,amenity,healthcare,emergency,natural,man_made",
    "lines": "name,highway,waterway,railway,natural,man_made,bridge,tunnel,layer,covered,culvert,service,embankment,cutting",
    "multipolygons": "name,type,amenity,aeroway,building,building:levels,landuse,natural,water,leisure,man_made,healthcare,emergency,layer",
}


def osmconf_yaz(yol):
    varsayilan = os.path.join(gdal.GetConfigOption("GDAL_DATA") or "", "osmconf.ini")
    if not os.path.exists(varsayilan):
        import glob
        aday = glob.glob(os.path.join(os.path.dirname(gdal.__file__), "**", "osmconf.ini"), recursive=True)
        aday += glob.glob(os.path.join(sys.prefix, "**", "osmconf.ini"), recursive=True)
        if not aday:
            raise SystemExit("osmconf.ini bulunamadı (GDAL_DATA).")
        varsayilan = aday[0]
    satirlar, bolum = [], None
    for s in open(varsayilan, encoding="utf-8"):
        t = s.strip()
        if t.startswith("[") and t.endswith("]"):
            bolum = t[1:-1]
        if bolum in OZNITELIK and t.startswith("attributes="):
            s = f"attributes={OZNITELIK[bolum]}\n"
        satirlar.append(s)
    open(yol, "w", encoding="utf-8").writelines(satirlar)


# --- 2) Analiz alanı kutusu (WGS84) -------------------------------------------------------
def aoi_kutusu():
    ds = ogr.Open(os.path.join(GEE, "aoi_havzalar.geojson"))
    xmin, xmax, ymin, ymax = ds.GetLayer().GetExtent()
    pay = 0.02  # ~2 km
    return xmin - pay, ymin - pay, xmax + pay, ymax + pay


def ham_cikar():
    conf = os.path.join(INT, "osmconf_istanbul.ini")
    osmconf_yaz(conf)
    gdal.SetConfigOption("OSM_CONFIG_FILE", conf)
    gdal.SetConfigOption("OGR_INTERLEAVED_READING", "YES")
    gdal.SetConfigOption("OSM_MAX_TMPFILE_SIZE", "4096")
    if os.path.exists(HAM):
        os.remove(HAM)
    gdal.VectorTranslate(
        HAM, PBF, format="GPKG",
        layers=["points", "lines", "multipolygons"],
        spatFilter=aoi_kutusu(), dstSRS=CRS, reproject=True,
        accessMode="overwrite",
    )


# --- 3) Tematik katmanlar -----------------------------------------------------------------
YAYA = "('footway','path','steps','cycleway','bridleway','corridor','proposed','construction','platform','raceway','elevator','via_ferrata')"
EVET = "('yes','viaduct','aqueduct','boardwalk','cantilever','covered','movable','trestle','culvert','building_passage','flooded')"

SORGULAR = {
    "yollar": f"""
        SELECT geom, osm_id, name, highway AS sinif, service,
               CASE WHEN bridge IN {EVET} THEN 1 ELSE 0 END AS kopru,
               CASE WHEN tunnel IN {EVET} THEN 1 ELSE 0 END AS tunel,
               CAST(COALESCE(layer, '0') AS INTEGER) AS katman,
               ST_Length(geom) AS uzunluk_m
        FROM lines WHERE highway IS NOT NULL AND highway NOT IN {YAYA}""",
    "dereler": f"""
        SELECT geom, osm_id, name, waterway AS tur,
               CASE WHEN tunnel IN {EVET} OR covered = 'yes' OR culvert = 'yes' THEN 1 ELSE 0 END AS kapali,
               tunnel, ST_Length(geom) AS uzunluk_m
        FROM lines WHERE waterway IN ('river','stream','canal','drain','ditch')""",
    "menfezler": f"""
        SELECT geom, osm_id, name, waterway AS tur, tunnel, covered, ST_Length(geom) AS uzunluk_m
        FROM lines WHERE waterway IN ('river','stream','canal','drain','ditch')
          AND (tunnel IN {EVET} OR covered = 'yes' OR culvert = 'yes')""",
    "kopruler": f"""
        SELECT geom, osm_id, name, COALESCE(highway, railway, waterway) AS uzerindeki, bridge,
               ST_Length(geom) AS uzunluk_m
        FROM lines WHERE bridge IN {EVET} AND (highway IS NOT NULL OR railway IS NOT NULL)""",
    "alt_gecitler": f"""
        SELECT geom, osm_id, name, highway AS sinif, tunnel, CAST(COALESCE(layer, '0') AS INTEGER) AS katman,
               ST_Length(geom) AS uzunluk_m
        FROM lines WHERE highway IS NOT NULL AND highway NOT IN {YAYA}
          AND ST_Length(geom) <= {ALT_GECIT_MAX_M}
          AND (tunnel IN {EVET}
               OR (COALESCE(tunnel, 'no') = 'no' AND CAST(COALESCE(layer, '0') AS INTEGER) < 0))""",
    "tuneller_uzun": f"""
        SELECT geom, osm_id, name, COALESCE(highway, railway) AS tur, ST_Length(geom) AS uzunluk_m
        FROM lines WHERE tunnel IN {EVET} AND (highway IS NOT NULL OR railway IS NOT NULL)
          AND ST_Length(geom) > {ALT_GECIT_MAX_M}""",
    "metro_girisleri": """
        SELECT geom, osm_id, name FROM points WHERE railway = 'subway_entrance'""",
    "kritik_tesisler": """
        SELECT geom, osm_id, name, amenity AS tur FROM points
          WHERE amenity IN ('hospital','school','fire_station')
        UNION ALL
        SELECT ST_PointOnSurface(geom) AS geom, COALESCE(osm_id, osm_way_id) AS osm_id, name, amenity AS tur
          FROM multipolygons WHERE amenity IN ('hospital','school','fire_station')""",
    "binalar": """
        SELECT geom, COALESCE(osm_id, osm_way_id) AS osm_id, building AS tur,
               CAST(NULLIF(building_levels, '') AS INTEGER) AS kat, ST_Area(geom) AS alan_m2
        FROM multipolygons WHERE building IS NOT NULL AND building <> 'no'""",
    "ocaklar": """
        SELECT geom, COALESCE(osm_id, osm_way_id) AS osm_id, name, landuse AS tur, ST_Area(geom) AS alan_m2
        FROM multipolygons WHERE landuse IN ('quarry','landfill')""",
    "havalimanlari": """
        SELECT geom, COALESCE(osm_id, osm_way_id) AS osm_id, name, ST_Area(geom) AS alan_m2
        FROM multipolygons WHERE aeroway = 'aerodrome'""",
    "su_alanlari": """
        SELECT geom, COALESCE(osm_id, osm_way_id) AS osm_id, name,
               COALESCE(water, landuse, natural) AS tur, ST_Area(geom) AS alan_m2
        FROM multipolygons WHERE natural = 'water' OR landuse IN ('reservoir','basin')""",
    "kiyi_cizgisi": """
        SELECT geom, osm_id FROM lines WHERE natural = 'coastline'""",
}


def tematik():
    if os.path.exists(CIKTI):
        os.remove(CIKTI)
    ozet = {}
    for ad, sql in SORGULAR.items():
        gdal.VectorTranslate(
            CIKTI, HAM, format="GPKG", SQLStatement=" ".join(sql.split()), SQLDialect="SQLite",
            layerName=ad, accessMode="append" if os.path.exists(CIKTI) else None,
        )
        ds = ogr.Open(CIKTI)
        ozet[ad] = ds.GetLayerByName(ad).GetFeatureCount()
        ds = None
    return ozet


if __name__ == "__main__":
    import time
    t0 = time.time()
    print("1/2 PBF'ten analiz alanı kesiliyor (birkaç dakika)...")
    ham_cikar()
    print(f"    tamam ({time.time() - t0:.0f} sn)")
    print("2/2 Tematik katmanlar yazılıyor...")
    for ad, n in tematik().items():
        print(f"    {ad:16s} {n:>9,}")
    print(f"Bitti ({time.time() - t0:.0f} sn): {CIKTI}")
