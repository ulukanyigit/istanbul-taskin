"""Faz 7 — Doğrulama: haberlerdeki su baskını noktaları modelle örtüşüyor mu?

Olaylar `validation/olaylar.csv`'de (tarih, kaynak, konum kuralı). Konum kuralları:
  nokta    enlem/boylam (haberden elle; güven = iyi/orta)
  kesisim  iki cadde adının OSM'deki kesişimi (ilçe içinde)
  yol      cadde adının ilçe içindeki OSM parçaları (hat olay)
Ölçütler (ayak izi içinde): en düşük dolma eşiği (mm), 25/50 mm senaryosunda en büyük su derinliği (m).
Nokta olaylar 50/100/150 m yarıçapla, il içi yapılaşmış alandan 2.000 rastgele noktayla karşılaştırılır.
Hat (cadde) olaylar 20 m tamponla, il içinden rastgele seçilen 500 adlı caddeyle (aynı tampon) karşılaştırılır.
AUC = rastgele seçilmiş bir olayın, rastgele seçilmiş bir karşılaştırma örneğinden daha derin su (ya da daha
düşük eşik) gösterme olasılığı (0,5 = ayırt edemiyor, 1 = kusursuz). Az sayıda olay olduğu için güven aralığı
bootstrap ile (2.000 tekrar) verilir.

Çalıştırma: python 01_dogrulama.py <proje_kökü>
Çıktı (validation/): dogrulama_sonuc.csv, dogrulama_ozet.json, olaylar.gpkg
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
V = os.path.join(KOK, "validation")
PR = os.path.join(KOK, "data", "processed")
OSM = os.path.join(KOK, "data", "interim", "osm_istanbul.gpkg")
YARICAPLAR = (50.0, 100.0, 150.0)
YARICAP = 150.0
N_CADDE = 500
YOL_TAMPON = 20.0
N_RASTGELE = 2000
ESIKLER = (25, 50)
rng = np.random.default_rng(42)

wgs = osr.SpatialReference(); wgs.ImportFromEPSG(4326); wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
tm = osr.SpatialReference(); tm.ImportFromEPSG(5254); tm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
ct = osr.CoordinateTransformation(wgs, tm)

idr = ogr.Open(os.path.join(PR, "idari.gpkg"))
ilce_geom = {}
for f in idr.GetLayerByName("ilceler"):
    ilce_geom[f.GetField("ilce")] = f.GetGeometryRef().Clone()
ilce_geom["Kağıthane"] = ilce_geom.get("Kağıthane") or ilce_geom.get("Kâğıthane")
idr = None
osm = ogr.Open(OSM)
yollar = osm.GetLayerByName("yollar")


def ilce_birlesik(ilceler):
    g = None
    for ad in ilceler.split("|"):
        gi = ilce_geom.get(ad)
        if gi is None:
            continue
        g = gi.Clone() if g is None else g.Union(gi)
    return g


def yol_bul(ad, alan):
    yollar.SetAttributeFilter(f"name LIKE '%{ad}%'")
    yollar.SetSpatialFilter(alan)
    g = ogr.Geometry(ogr.wkbMultiLineString)
    for f in yollar:
        gg = f.GetGeometryRef()
        if not gg.Intersects(alan):
            continue
        if gg.GetGeometryType() == ogr.wkbLineString:
            g.AddGeometry(gg.Clone())
        else:
            for i in range(gg.GetGeometryCount()):
                g.AddGeometry(gg.GetGeometryRef(i).Clone())
    yollar.SetAttributeFilter(None); yollar.SetSpatialFilter(None)
    return g if g.GetGeometryCount() else None


def konumla(r):
    if r.tip == "nokta":
        x, y, _ = ct.TransformPoint(float(r.lon), float(r.lat))
        p = ogr.Geometry(ogr.wkbPoint); p.AddPoint_2D(x, y)
        return p, p.Buffer(YARICAP), "nokta"
    alan = ilce_birlesik(r.ilce)
    if r.tip == "yol":
        g = yol_bul(r.yol1, alan)
        return (g, g.Buffer(YOL_TAMPON), "hat") if g else (None, None, "bulunamadı")
    a, b = yol_bul(r.yol1, alan), yol_bul(r.yol2, alan)
    if not a or not b:
        return None, None, "bulunamadı"
    k = a.Intersection(b)
    if k.IsEmpty():
        if a.Distance(b) > 50:
            return None, None, "kesişim yok"
        k = a.Buffer(50).Intersection(b)
    p = k.Centroid()
    return p, p.Buffer(YARICAP), "nokta"


# rasterlar
esik_ds = gdal.Open(os.path.join(PR, "dolma_esigi_mm_10m.tif"))
cid_ds = gdal.Open(os.path.join(PR, "cukur_id_10m.tif"))
der_ds = {P: gdal.Open(os.path.join(PR, f"derinlik_{P}mm_10m.tif")) for P in ESIKLER}
GT, NX, NY = esik_ds.GetGeoTransform(), esik_ds.RasterXSize, esik_ds.RasterYSize
cuk = pd.read_csv(os.path.join(PR, "cukurlar_sinifli.csv")).set_index("cukur_id")


def ayak_izi_olc(poly):
    xmin, xmax, ymin, ymax = poly.GetEnvelope()
    c0, c1 = max(0, int((xmin - GT[0]) / GT[1])), min(NX, int((xmax - GT[0]) / GT[1]) + 1)
    r0, r1 = max(0, int((ymax - GT[3]) / GT[5])), min(NY, int((ymin - GT[3]) / GT[5]) + 1)
    w, h = c1 - c0, r1 - r0
    if w <= 0 or h <= 0:
        return None
    mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Byte)
    mem.SetGeoTransform((GT[0] + c0 * GT[1], GT[1], 0, GT[3] + r0 * GT[5], 0, GT[5]))
    vd = (ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")).CreateDataSource("")
    lyr = vd.CreateLayer("a", tm, ogr.wkbPolygon)
    f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(poly); lyr.CreateFeature(f)
    gdal.RasterizeLayer(mem, [1], lyr, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    m = mem.GetRasterBand(1).ReadAsArray() == 1
    e = esik_ds.GetRasterBand(1).ReadAsArray(c0, r0, w, h)
    c = cid_ds.GetRasterBand(1).ReadAsArray(c0, r0, w, h)
    sec = m & (c > 0)
    sonuc = {"min_esik_mm": np.nan, "cukur_id": 0, "kategori": None}
    if sec.any():
        ids = np.unique(c[sec])
        ids = [i for i in ids if not str(cuk.at[i, "kategori"]).startswith("elenen")]
        if ids:
            es = cuk.loc[ids, "dolma_esigi_mm"].replace(-1, 999)
            i = int(es.idxmin())
            sonuc.update(min_esik_mm=float(es.min()), cukur_id=i, kategori=cuk.at[i, "kategori"])
    for P in ESIKLER:
        d = der_ds[P].GetRasterBand(1).ReadAsArray(c0, r0, w, h)
        sonuc[f"maks_derinlik_{P}mm"] = float(d[m].max()) if m.any() else 0.0
    return sonuc


olaylar = pd.read_csv(os.path.join(V, "olaylar.csv"))
satirlar, geom_kayit = [], []
for _, r in olaylar.iterrows():
    g, iz, tur = konumla(r)
    s_ = {"olay_id": r.olay_id, "tarih": r.tarih, "ilce": r.ilce, "tanim": r.tanim, "tip": r.tip, "guven": r.guven, "konum": tur}
    if g is not None:
        if tur == "nokta":
            for R in YARICAPLAR:
                o = ayak_izi_olc(g.Buffer(R)) or {}
                s_.update({f"{k}_r{int(R)}": v for k, v in o.items()})
        else:
            s_.update({f"{k}_hat": v for k, v in (ayak_izi_olc(g.Buffer(YOL_TAMPON)) or {}).items()})
        geom_kayit.append((r.olay_id, r.tanim, g if tur == "nokta" else g))
    satirlar.append(s_)
sonuc = pd.DataFrame(satirlar)

# karşılaştırma 1: il içi yapılaşmış alandan rastgele noktalar
wc = gdal.Open(os.path.join(KOK, "istanbul_taskin_gee", "worldcover_10m.tif"))
k = 5
W, H = NX // k, NY // k
wcl = wc.GetRasterBand(1).ReadAsArray(buf_xsize=W, buf_ysize=H, resample_alg=gdal.GRIORA_NearestNeighbour)
mem = gdal.GetDriverByName("MEM").Create("", W, H, 1, gdal.GDT_Byte)
mem.SetGeoTransform((GT[0], GT[1] * k, 0, GT[3], 0, GT[5] * k)); mem.SetProjection(esik_ds.GetProjection())
vd = ogr.GetDriverByName("MEM").CreateDataSource("") if ogr.GetDriverByName("MEM") else ogr.GetDriverByName("Memory").CreateDataSource("")
il_lyr = vd.CreateLayer("il", tm, ogr.wkbMultiPolygon)
il_geom = None
idr = ogr.Open(os.path.join(PR, "idari.gpkg"))
for f in idr.GetLayerByName("ilceler"):
    if f.GetField("istanbul") or f.GetField("ilce") in ("Kağıthane", "Kâğıthane"):
        gg = f.GetGeometryRef().Clone()
        ff = ogr.Feature(il_lyr.GetLayerDefn()); ff.SetGeometry(gg); il_lyr.CreateFeature(ff)
        il_geom = gg if il_geom is None else il_geom.Union(gg)
gdal.RasterizeLayer(mem, [1], il_lyr, burn_values=[1])
ilm = mem.GetRasterBand(1).ReadAsArray() == 1
yy, xx = np.nonzero(ilm & (wcl == 50))
rast = []
for i in rng.choice(len(yy), N_RASTGELE, replace=False):
    p_ = ogr.Geometry(ogr.wkbPoint)
    p_.AddPoint_2D(GT[0] + (xx[i] + rng.random()) * GT[1] * k, GT[3] + (yy[i] + rng.random()) * GT[5] * k)
    s_ = {}
    for R in YARICAPLAR:
        s_.update({f"{kk}_r{int(R)}": v for kk, v in (ayak_izi_olc(p_.Buffer(R)) or {}).items()})
    rast.append(s_)
rast = pd.DataFrame(rast)

# karşılaştırma 2: il içinden rastgele adlı caddeler (tüm parçalarıyla, ilçe içinde)
yollar.SetAttributeFilter("name IS NOT NULL AND sinif IN ('primary','secondary','tertiary','residential','unclassified','living_street')")
adaylar = [(f.GetField("name"), f.GetGeometryRef().Centroid().Clone()) for f in yollar]
yollar.SetAttributeFilter(None)
ilce_listesi = [(a, g) for a, g in ilce_geom.items() if a]
cadde, gorulen = [], set()
for i in rng.permutation(len(adaylar)):
    if len(cadde) >= N_CADDE:
        break
    ad, c = adaylar[i]
    if "'" in ad or not il_geom.Contains(c):
        continue
    ilce = next((a for a, g in ilce_listesi if g.Contains(c)), None)
    if ilce is None or (ad, ilce) in gorulen:
        continue
    gorulen.add((ad, ilce))
    g = yol_bul(ad, ilce_geom[ilce])
    if g is None:
        continue
    o = ayak_izi_olc(g.Buffer(YOL_TAMPON))
    if o:
        cadde.append({f"{kk}_hat": v for kk, v in o.items()})
cadde = pd.DataFrame(cadde)


def auc(olay, ref, buyuk_iyi=True):
    a, b = np.asarray(olay, float), np.asarray(ref, float)
    if not buyuk_iyi:
        a, b = -a, -b
    if len(a) == 0 or len(b) == 0:
        return None
    gt_ = (a[:, None] > b[None, :]).mean()
    eq = (a[:, None] == b[None, :]).mean()
    return float(gt_ + 0.5 * eq)


def auc_ci(olay, ref, buyuk_iyi=True, n=2000):
    olay = np.asarray(olay, float)
    if len(olay) < 3:
        return None
    vals = [auc(rng.choice(olay, len(olay)), ref, buyuk_iyi) for _ in range(n)]
    return [round(float(np.percentile(vals, 2.5)), 2), round(float(np.percentile(vals, 97.5)), 2)]


def olc(df_o, df_r, ek):
    out = {}
    der25 = f"maks_derinlik_25mm_{ek}"
    esik = f"min_esik_mm_{ek}"
    o_d, r_d = df_o[der25].fillna(0), df_r[der25].fillna(0)
    o_e, r_e = df_o[esik].fillna(999), df_r[esik].fillna(999)
    out["n_olay"], out["n_karsilastirma"] = int(len(df_o)), int(len(df_r))
    out["auc_derinlik_25mm"] = round(auc(o_d, r_d), 3)
    out["auc_derinlik_25mm_ci95"] = auc_ci(o_d, r_d)
    out["auc_esik"] = round(auc(o_e, r_e, buyuk_iyi=False), 3)
    out["auc_esik_ci95"] = auc_ci(o_e, r_e, buyuk_iyi=False)
    for t in (0.10, 0.30):
        out[f"derinlik25_ge_{t}m"] = {"olay": round(float((o_d >= t).mean()), 3), "karsilastirma": round(float((r_d >= t).mean()), 3)}
    out["medyan_derinlik_25mm"] = {"olay": round(float(o_d.median()), 2), "karsilastirma": round(float(r_d.median()), 2)}
    return out


nokta = sonuc[sonuc.konum == "nokta"]
hat = sonuc[sonuc.konum == "hat"]
ozet = {"olay_sayisi": int(len(sonuc)), "konumlanan_nokta": int(len(nokta)), "konumlanan_hat": int(len(hat)),
        "konumlanamayan": sonuc.loc[~sonuc.konum.isin(["nokta", "hat"]), "olay_id"].tolist()}
for R in YARICAPLAR:
    ozet[f"nokta_r{int(R)}m"] = olc(nokta, rast, f"r{int(R)}")
if len(hat) and len(cadde):
    ozet["hat_20m"] = olc(hat, cadde, "hat")
# her olayın karşılaştırma dağılımındaki yeri (25 mm derinlik; 1 = karşılaştırmaların hepsinden derin)
def yer(v, ref):
    return round(float((ref.fillna(0) < (0 if v != v else v)).mean()), 3)
sonuc["yuzdelik_derinlik25"] = [
    yer(r_["maks_derinlik_25mm_r100"], rast["maks_derinlik_25mm_r100"]) if r_.konum == "nokta"
    else (yer(r_["maks_derinlik_25mm_hat"], cadde["maks_derinlik_25mm_hat"]) if r_.konum == "hat" else np.nan)
    for _, r_ in sonuc.iterrows()]
sonuc.to_csv(os.path.join(V, "dogrulama_sonuc.csv"), index=False)
json.dump(ozet, open(os.path.join(V, "dogrulama_ozet.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

gp = os.path.join(V, "olaylar.gpkg")
if os.path.exists(gp):
    os.remove(gp)
vd = ogr.GetDriverByName("GPKG").CreateDataSource(gp)
for tip, gtype in (("nokta", ogr.wkbPoint), ("hat", ogr.wkbMultiLineString)):
    lyr = vd.CreateLayer(f"olaylar_{tip}", tm, gtype)
    for ad in ("olay_id", "tanim"):
        lyr.CreateField(ogr.FieldDefn(ad, ogr.OFTString))
    lyr.CreateField(ogr.FieldDefn("yuzdelik_derinlik25", ogr.OFTReal))
    for oid, tanim, g in geom_kayit:
        if (g.GetGeometryType() == ogr.wkbPoint) != (tip == "nokta"):
            continue
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetField("olay_id", oid); f.SetField("tanim", tanim)
        v = sonuc.loc[sonuc.olay_id == oid, "yuzdelik_derinlik25"].iloc[0]
        if v == v:
            f.SetField("yuzdelik_derinlik25", float(v))
        f.SetGeometry(g if tip == "nokta" else ogr.ForceToMultiLineString(g)); lyr.CreateFeature(f)
vd = None

pd.set_option("display.width", 250)
kol = ["olay_id", "ilce", "tanim", "konum", "min_esik_mm_r100", "maks_derinlik_25mm_r100", "min_esik_mm_hat",
       "maks_derinlik_25mm_hat", "yuzdelik_derinlik25"]
print(sonuc[[c for c in kol if c in sonuc.columns]].to_string(index=False))
print(json.dumps(ozet, ensure_ascii=False, indent=1))
