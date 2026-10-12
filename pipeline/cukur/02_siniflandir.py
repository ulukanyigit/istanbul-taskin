"""Faz 4b — Çukur sınıflandırma, ilçe/mahalle eşleştirme ve "ilk dolacaklar" listeleri.

Kategoriler (öncelik sırasıyla):
  elenen_avlu / elenen_su / elenen_degisen  01_cukur_analizi bayrakları
  alt_gecit     OSM alt geçidi içeren çukur (pompa arızası senaryosu)
  dere_vadi     dereye/menfeze değen ya da yerel havzası > 1 km² (vadide dolgu/menfez arkası göllenme)
  kentsel       yapılaşmış alan oranı ≥ %25 ya da ≥ 200 m² yol içeren çukur (kentsel yüzey göllenmesi)
  kirsal        diğerleri

Çalıştırma: python 02_siniflandir.py <proje_kökü>
Çıktı (data/processed): idari.gpkg (ilceler, mahalleler), cukurlar.gpkg'ye yeni alanlar,
  listeler.gpkg (ilk_100_kentsel, ilk_50_dere_vadi), cukurlar_sinifli.csv
"""
import os
import sys
import time

import numpy as np
import pandas as pd
from osgeo import gdal, ogr

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INT = os.path.join(KOK, "data", "interim")
GEE = os.path.join(KOK, "istanbul_taskin_gee")
OUT = os.path.join(KOK, "data", "processed")
GPKG = os.path.join(OUT, "cukurlar.gpkg")
IDARI = os.path.join(OUT, "idari.gpkg")
P = {"dere_havza_m2": 1e6, "kentsel_yapi_orani": 0.25, "kentsel_yol_m2": 200, "liste_min_hacim_m3": 500}
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


# 1) idari sınırlar (OSM, analiz alanı kutusu)
if os.path.exists(IDARI):
    os.remove(IDARI)
ham = os.path.join(INT, "osm_ham.gpkg")
gdal.VectorTranslate(IDARI, ham, format="GPKG", layerName="ilceler", SQLDialect="SQLite", SQLStatement="""
    SELECT geom, name AS ilce, other_tags LIKE '%TR34-district%' AS istanbul
    FROM multipolygons WHERE other_tags LIKE '%"admin_level"=>"6"%'
      AND (type = 'boundary' OR other_tags LIKE '%"boundary"=>"administrative"%')""")
gdal.VectorTranslate(IDARI, ham, format="GPKG", layerName="mahalleler", accessMode="append", SQLDialect="SQLite", SQLStatement="""
    SELECT geom, name AS mahalle FROM multipolygons WHERE other_tags LIKE '%"admin_level"=>"8"%'
      AND (type = 'boundary' OR other_tags LIKE '%"boundary"=>"administrative"%')""")
ds = ogr.Open(IDARI)
ISTANBUL_ILCELERI = {
    "Adalar", "Arnavutköy", "Ataşehir", "Avcılar", "Bağcılar", "Bahçelievler", "Bakırköy", "Başakşehir", "Bayrampaşa",
    "Beşiktaş", "Beykoz", "Beylikdüzü", "Beyoğlu", "Büyükçekmece", "Çatalca", "Çekmeköy", "Esenler", "Esenyurt",
    "Eyüpsultan", "Fatih", "Gaziosmanpaşa", "Güngören", "Kadıköy", "Kağıthane", "Kâğıthane", "Kartal", "Küçükçekmece", "Maltepe",
    "Pendik", "Sancaktepe", "Sarıyer", "Silivri", "Sultanbeyli", "Sultangazi", "Şile", "Şişli", "Tuzla", "Ümraniye",
    "Üsküdar", "Zeytinburnu"}  # 39 ilçe (Kağıthane iki yazımla)
ilceler = [(f.GetFID(), f.GetField("ilce"), int(f.GetField("ilce") in ISTANBUL_ILCELERI or bool(f.GetField("istanbul"))))
           for f in ds.GetLayerByName("ilceler")]
mahalleler = [(f.GetFID(), f.GetField("mahalle")) for f in ds.GetLayerByName("mahalleler")]
ds = None
log(f"İdari sınırlar: {len(ilceler)} ilçe ({sum(i[2] for i in ilceler)} İstanbul), {len(mahalleler)} mahalle")
eksik = ISTANBUL_ILCELERI - {i[1] for i in ilceler} - {"Kağıthane", "Kâğıthane"} if ({"Kağıthane", "Kâğıthane"} & {i[1] for i in ilceler}) else ISTANBUL_ILCELERI - {i[1] for i in ilceler}
if eksik:
    log(f"UYARI: OSM'de bulunamayan İstanbul ilçeleri: {sorted(eksik)}")

# 2) çukur başına: dere pikseli, yapılaşma oranı, çoğunluk ilçe ve mahalle
ci = gdal.Open(os.path.join(OUT, "cukur_id_10m.tif"))
gt, wkt, NX, NY = ci.GetGeoTransform(), ci.GetProjection(), ci.RasterXSize, ci.RasterYSize


def id_raster(katman):
    yol = os.path.join(INT, f"_tmp_{katman}.tif")
    r = gdal.GetDriverByName("GTiff").Create(yol, NX, NY, 1, gdal.GDT_Int32, options=["COMPRESS=DEFLATE", "TILED=YES"])
    r.SetGeoTransform(gt); r.SetProjection(wkt)
    gdal.Rasterize(r, IDARI, options=gdal.RasterizeOptions(SQLStatement=f"SELECT geom, fid * 1 AS rid FROM {katman}",
                                                            SQLDialect="SQLite", attribute="rid"))
    return r


ilce_r, mah_r = id_raster("ilceler"), id_raster("mahalleler")
im = gdal.Open(os.path.join(INT, "maske_islem_10m.tif"))
wc = gdal.Open(os.path.join(GEE, "worldcover_10m.tif"))
d = pd.read_csv(os.path.join(OUT, "cukurlar.csv"))
m = int(d.cukur_id.max())
dere = np.zeros(m + 1, np.int64)
yapi = np.zeros(m + 1, np.int64)
cift_ilce, cift_mah = {}, {}
for y in range(0, NY, 1024):
    h = min(1024, NY - y)
    c = ci.GetRasterBand(1).ReadAsArray(0, y, NX, h)
    s = c > 0
    if not s.any():
        continue
    cs = c[s].astype(np.int64)
    b = im.GetRasterBand(1).ReadAsArray(0, y, NX, h)[s]
    w = wc.GetRasterBand(1).ReadAsArray(0, y, NX, h)[s]
    dere += np.bincount(cs[(b & 24) > 0], minlength=m + 1)
    yapi += np.bincount(cs[w == 50], minlength=m + 1)
    for r, hedef in ((ilce_r, cift_ilce), (mah_r, cift_mah)):
        a = r.GetRasterBand(1).ReadAsArray(0, y, NX, h)[s].astype(np.int64)
        anahtar, say = np.unique(cs * 100000 + a, return_counts=True)
        for k, n in zip(anahtar, say):
            hedef[k] = hedef.get(k, 0) + n
ci = im = wc = ilce_r = mah_r = r = None
for k in ("ilceler", "mahalleler"):
    os.remove(os.path.join(INT, f"_tmp_{k}.tif"))


def cogunluk(cift, sozluk):
    en = {}
    for k, n in cift.items():
        cid, rid = divmod(int(k), 100000)
        if rid == 0:
            continue
        if n > en.get(cid, (0, None))[0]:
            en[cid] = (n, rid)
    return {cid: sozluk.get(rid) for cid, (n, rid) in en.items()}


ilce_ad = {fid: (ad, ist) for fid, ad, ist in ilceler}
mah_ad = {fid: ad for fid, ad in mahalleler}
ci_ilce = cogunluk(cift_ilce, ilce_ad)
ci_mah = cogunluk(cift_mah, mah_ad)
d["dere_px"] = dere[d.cukur_id.values]
d["yapi_orani"] = (yapi[d.cukur_id.values] * (gt[1] * -gt[5]) / d.alan_m2).round(3)
d["ilce"] = d.cukur_id.map(lambda i: (ci_ilce.get(i) or (None, 0))[0])
d["il_ici"] = d.cukur_id.map(lambda i: int(bool((ci_ilce.get(i) or (None, 0))[1])))
d["mahalle"] = d.cukur_id.map(ci_mah.get)
log("Dere, yapılaşma ve idari eşleştirme tamam")

# 3) kategori
kat = np.full(len(d), "kirsal", dtype=object)
kat[((d.yapi_orani >= P["kentsel_yapi_orani"]) | (d.yol_m2 >= P["kentsel_yol_m2"])).values] = "kentsel"
kat[((d.dere_px > 0) | (d.yerel_havza_m2 > P["dere_havza_m2"])).values] = "dere_vadi"
kat[(d.altgecit_m2 > 0).values] = "alt_gecit"
kat[(d.degisen_topo == 1).values] = "elenen_degisen"
kat[(d.su_alani == 1).values] = "elenen_su"
kat[(d.avlu == 1).values] = "elenen_avlu"
d["kategori"] = kat
e = d.dolma_esigi_mm.where(d.dolma_esigi_mm >= 0, 9999)
d["_esik_sira"] = e

liste = d[d.kategori.isin(["kentsel", "alt_gecit"]) & (d.il_ici == 1) & (d.hacim_m3 >= P["liste_min_hacim_m3"])]
ilk100 = liste.sort_values(["_esik_sira", "hacim_m3"], ascending=[True, False]).head(100).copy()
ilk100["sira"] = np.arange(1, len(ilk100) + 1)
dv = d[(d.kategori == "dere_vadi") & (d.il_ici == 1) & (d.hacim_m3 >= P["liste_min_hacim_m3"])]
ilk50dv = dv.sort_values(["_esik_sira", "hacim_m3"], ascending=[True, False]).head(50).copy()
ilk50dv["sira"] = np.arange(1, len(ilk50dv) + 1)
d.drop(columns="_esik_sira").to_csv(os.path.join(OUT, "cukurlar_sinifli.csv"), index=False)
log("Kategoriler: " + ", ".join(f"{k} {v:,}" for k, v in d.kategori.value_counts().items()))

# 4) GPKG'ye yaz: ek tablo + SQL ile güncelle + liste katmanları
ek = d[["cukur_id", "kategori", "ilce", "mahalle", "il_ici", "dere_px", "yapi_orani"]].copy()
ek["sira_100"] = ek.cukur_id.map(dict(zip(ilk100.cukur_id, ilk100.sira))).fillna(0).astype(int)   # 0 = listede değil
ek["sira_dere"] = ek.cukur_id.map(dict(zip(ilk50dv.cukur_id, ilk50dv.sira))).fillna(0).astype(int)
ek_csv = os.path.join(OUT, "_ek.csv")
ek.to_csv(ek_csv, index=False)
gdal.VectorTranslate(GPKG, ek_csv, format="GPKG", layerName="cukur_ek", accessMode="overwrite",
                     options=["-oo", "AUTODETECT_TYPE=YES"])
ds = ogr.Open(GPKG, 1)
lyr = ds.GetLayerByName("cukurlar")
mevcut = {lyr.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(lyr.GetLayerDefn().GetFieldCount())}
for ad, tip in [("kategori", "TEXT"), ("ilce", "TEXT"), ("mahalle", "TEXT"), ("il_ici", "INTEGER"), ("dere_px", "INTEGER"),
                ("yapi_orani", "REAL"), ("sira_100", "INTEGER"), ("sira_dere", "INTEGER")]:
    if ad not in mevcut:
        ds.ExecuteSQL(f'ALTER TABLE cukurlar ADD COLUMN "{ad}" {tip}')
ds.ExecuteSQL("CREATE INDEX IF NOT EXISTS idx_ek_id ON cukur_ek(cukur_id)")
ds.ExecuteSQL("CREATE INDEX IF NOT EXISTS idx_ck_id ON cukurlar(cukur_id)")
ds.ExecuteSQL("""UPDATE cukurlar SET (kategori, ilce, mahalle, il_ici, dere_px, yapi_orani, sira_100, sira_dere) =
                 (SELECT kategori, ilce, mahalle, il_ici, dere_px, yapi_orani, sira_100, sira_dere FROM cukur_ek
                  WHERE cukur_ek.cukur_id = cukurlar.cukur_id)""")
ds = None
os.remove(ek_csv)
LISTE = os.path.join(OUT, "listeler.gpkg")
if os.path.exists(LISTE):
    os.remove(LISTE)
for ad, sql in [("ilk_100_kentsel", "SELECT * FROM cukurlar WHERE CAST(sira_100 AS INTEGER) > 0 ORDER BY CAST(sira_100 AS INTEGER)"),
                ("ilk_50_dere_vadi", "SELECT * FROM cukurlar WHERE CAST(sira_dere AS INTEGER) > 0 ORDER BY CAST(sira_dere AS INTEGER)")]:
    gdal.VectorTranslate(LISTE, GPKG, format="GPKG", layerName=ad, accessMode="append" if os.path.exists(LISTE) else None,
                         SQLStatement=sql, SQLDialect="SQLite")
log("cukurlar.gpkg güncellendi; listeler.gpkg (ilk_100_kentsel, ilk_50_dere_vadi) yazıldı")

# 5) özet
il = d[d.il_ici == 1]
print("\nİL İÇİ ÖZET")
print(il.kategori.value_counts().to_string())
for p in (10, 25, 50, 100):
    s = il[(il.dolma_esigi_mm >= 0) & (il.dolma_esigi_mm <= p)]
    print(f"≤{p:>3} mm dolan  kentsel {(s.kategori == 'kentsel').sum():>6,}  alt_gecit {(s.kategori == 'alt_gecit').sum():>4,}  "
          f"dere_vadi {(s.kategori == 'dere_vadi').sum():>5,}")
print("\nİLK 100 — ilçe dağılımı:")
print(ilk100.ilce.value_counts().head(15).to_string())
print("\nİLK 15:")
print(ilk100.head(15)[["sira", "cukur_id", "kategori", "ilce", "mahalle", "dolma_esigi_mm", "hacim_m3", "alan_m2",
                       "maks_derinlik_m", "yerel_havza_m2"]].to_string(index=False))
