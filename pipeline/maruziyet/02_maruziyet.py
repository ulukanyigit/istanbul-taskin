"""Faz 6b — Maruziyet: binalar, yollar, kritik tesisler, metro girişleri.

Kurallar (her senaryo için):
  bina      çevresindeki (1 piksel komşuluk) en büyük su derinliği; ≥ 0,10 m "su değiyor", ≥ 0,30 m "bodrum/zemin riski"
  yol       hat üzerindeki en büyük derinlik; ≥ 0,30 m araç geçemez → kapalı
  tesis     30 m yarıçapta en büyük derinlik (hastane, okul, itfaiye, metro girişi)

Çalıştırma: python 02_maruziyet.py <proje_kökü>
Çıktı (data/processed): bina_maruziyet.csv, yol_maruziyet.csv, tesis_maruziyet.csv, maruziyet_ozet.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from osgeo import gdal, ogr
from scipy import ndimage

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(KOK, "data", "processed")
INT = os.path.join(KOK, "data", "interim")
OSM = os.path.join(INT, "osm_istanbul.gpkg")
IDARI = os.path.join(OUT, "idari.gpkg")
SENARYO_MM = [25, 50, 75, 100]
ESIK = {"bina_temas_m": 0.10, "bina_risk_m": 0.30, "yol_kapali_m": 0.30, "tesis_m": 0.10, "tesis_yaricap_px": 3}
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


ref = gdal.Open(os.path.join(OUT, "cukur_id_10m.tif"))
GT, WKT, NX, NY = ref.GetGeoTransform(), ref.GetProjection(), ref.RasterXSize, ref.RasterYSize
ref = None


def id_raster(ad, kaynak, sql, all_touched):
    yol = os.path.join(INT, f"_tmp_{ad}.tif")
    r = gdal.GetDriverByName("GTiff").Create(yol, NX, NY, 1, gdal.GDT_Int32, options=["COMPRESS=DEFLATE", "TILED=YES"])
    r.SetGeoTransform(GT); r.SetProjection(WKT)
    gdal.Rasterize(r, kaynak, options=gdal.RasterizeOptions(SQLStatement=sql, SQLDialect="SQLite", attribute="rid",
                                                            allTouched=all_touched))
    r = None
    return yol


BINA_CSV, YOL_CSV, PX_JSON = (os.path.join(OUT, n) for n in ("bina_maruziyet.csv", "yol_maruziyet.csv", "_yol_px.json"))
dinc = all(os.path.exists(p) for p in (BINA_CSV, YOL_CSV)) and min(
    os.path.getmtime(p) for p in (BINA_CSV, YOL_CSV)) > max(
    os.path.getmtime(os.path.join(OUT, f"derinlik_{P}mm_10m.tif")) for P in SENARYO_MM)
if dinc:
    bt, yt = pd.read_csv(BINA_CSV), pd.read_csv(YOL_CSV)
    yol_px = {int(k): v for k, v in json.load(open(PX_JSON)).items()} if os.path.exists(PX_JSON) else None
    derin = {P: gdal.Open(os.path.join(OUT, f"derinlik_{P}mm_10m.tif")) for P in SENARYO_MM}
    log("bina ve yol maruziyeti güncel, yeniden hesaplanmadı")
else:
    bina_r = id_raster("bina", OSM, "SELECT geom, fid * 1 AS rid FROM binalar", True)
    yol_r = id_raster("yol", OSM, "SELECT geom, fid * 1 AS rid FROM yollar WHERE kopru = 0 AND tunel = 0", True)
    mah_r = id_raster("mah", IDARI, "SELECT geom, fid * 1 AS rid FROM mahalleler", False)
    log("bina, yol ve mahalle kimlik rasterları hazır")


    def fid_max(katman):
        ds = ogr.Open(OSM)
        l = ds.GetLayerByName(katman)
        mx = max(f.GetFID() for f in l)
        return mx


    nb, ny_ = fid_max("binalar"), fid_max("yollar")
    bina_d = {P: np.zeros(nb + 1, np.float32) for P in SENARYO_MM}
    yol_d = {P: np.zeros(ny_ + 1, np.float32) for P in SENARYO_MM}
    yol_px = {P: 0 for P in SENARYO_MM}
    bina_mah = np.zeros(nb + 1, np.int32)
    derin = {P: gdal.Open(os.path.join(OUT, f"derinlik_{P}mm_10m.tif")) for P in SENARYO_MM}
    br, yr, mr = gdal.Open(bina_r), gdal.Open(yol_r), gdal.Open(mah_r)
    B = 1024
    for y0 in range(0, NY, B):
        ya, yb = max(0, y0 - 1), min(NY, y0 + B + 1)
        h = yb - ya
        iy0, iy1 = y0 - ya, min(y0 + B, NY) - ya
        bid = br.GetRasterBand(1).ReadAsArray(0, ya, NX, h)[iy0:iy1]
        yid = yr.GetRasterBand(1).ReadAsArray(0, ya, NX, h)[iy0:iy1]
        mid = mr.GetRasterBand(1).ReadAsArray(0, ya, NX, h)[iy0:iy1]
        sb, sy = bid > 0, yid > 0
        np.maximum.at(bina_mah, bid[sb], mid[sb])
        for P in SENARYO_MM:
            d = derin[P].GetRasterBand(1).ReadAsArray(0, ya, NX, h)
            if not d.any():
                continue
            dm = ndimage.maximum_filter(d, size=3)[iy0:iy1]   # binanın duvarına değen su
            np.maximum.at(bina_d[P], bid[sb], dm[sb])
            dd = d[iy0:iy1]
            np.maximum.at(yol_d[P], yid[sy], dd[sy])
            yol_px[P] += int(((dd >= ESIK["yol_kapali_m"]) & sy).sum())
    br = yr = mr = None
    for p in (bina_r, yol_r, mah_r):
        os.remove(p)
    log("bina ve yol derinlikleri tamam")

    # öznitelikler
    ds = ogr.Open(OSM)
    bl = ds.GetLayerByName("binalar")
    b_fid, b_alan, b_kat, b_tur = [], [], [], []
    for f in bl:
        b_fid.append(f.GetFID()); b_alan.append(f.GetField("alan_m2")); b_kat.append(f.GetField("kat")); b_tur.append(f.GetField("tur"))
    yl = ds.GetLayerByName("yollar")
    y_fid, y_sinif, y_uz, y_ad = [], [], [], []
    for f in yl:
        y_fid.append(f.GetFID()); y_sinif.append(f.GetField("sinif")); y_uz.append(f.GetField("uzunluk_m")); y_ad.append(f.GetField("name"))
    ds = None
    idr = ogr.Open(IDARI)
    mah_ad = {f.GetFID(): f.GetField("mahalle") for f in idr.GetLayerByName("mahalleler")}
    idr = None

    bt = pd.DataFrame({"bina_fid": b_fid, "tur": b_tur, "alan_m2": np.round(b_alan, 1), "kat": b_kat})
    bt["mahalle_fid"] = bina_mah[bt.bina_fid.values]
    for P in SENARYO_MM:
        bt[f"d{P}_m"] = bina_d[P][bt.bina_fid.values].round(2)
    bt.to_csv(os.path.join(OUT, "bina_maruziyet.csv"), index=False)
    yt = pd.DataFrame({"yol_fid": y_fid, "ad": y_ad, "sinif": y_sinif, "uzunluk_m": np.round(y_uz, 1)})
    for P in SENARYO_MM:
        yt[f"d{P}_m"] = yol_d[P][yt.yol_fid.values].round(2)
    yt.to_csv(os.path.join(OUT, "yol_maruziyet.csv"), index=False)
    log("bina_maruziyet.csv ve yol_maruziyet.csv yazıldı")
    json.dump({str(k): v for k, v in yol_px.items()}, open(PX_JSON, "w"))
    derin = {P: gdal.Open(os.path.join(OUT, f"derinlik_{P}mm_10m.tif")) for P in SENARYO_MM}

# kritik tesisler + metro girişleri: 30 m yarıçapta en büyük derinlik
r = ESIK["tesis_yaricap_px"]
ds = ogr.Open(OSM)
kayit = []
for katman in ("kritik_tesisler", "metro_girisleri"):
    for f in ds.GetLayerByName(katman):
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        x, y = g.GetX(), g.GetY()
        c, rr = int((x - GT[0]) / GT[1]), int((y - GT[3]) / GT[5])
        if not (r <= c < NX - r and r <= rr < NY - r):
            continue
        satir = {"katman": katman, "tur": f.GetField("tur") if katman == "kritik_tesisler" else "metro_girisi",
                 "ad": f.GetField("name"), "x": round(x, 1), "y": round(y, 1)}
        for P in SENARYO_MM:
            w = derin[P].GetRasterBand(1).ReadAsArray(c - r, rr - r, 2 * r + 1, 2 * r + 1)
            satir[f"d{P}_m"] = round(float(w.max()), 2)
        kayit.append(satir)
ds = None
derin = None
tt = pd.DataFrame(kayit)
tt.to_csv(os.path.join(OUT, "tesis_maruziyet.csv"), index=False)
log("tesis_maruziyet.csv yazıldı")

ozet = {}
for P in SENARYO_MM:
    c = f"d{P}_m"
    ozet[f"{P}mm"] = {
        "bina_su_degiyor": int((bt[c] >= ESIK["bina_temas_m"]).sum()),
        "bina_riskli_30cm": int((bt[c] >= ESIK["bina_risk_m"]).sum()),
        "kapali_yol_km_piksel": round(yol_px[P] * GT[1] / 1000, 1) if yol_px else None,
        "kapali_yol_km_parca": round(float(yt.loc[yt[c] >= ESIK["yol_kapali_m"], "uzunluk_m"].sum() / 1000), 1),
        "kapali_yol_segment": int((yt[c] >= ESIK["yol_kapali_m"]).sum()),
        "tesis": {t: int(((tt.tur == t) & (tt[c] >= ESIK["tesis_m"])).sum()) for t in ["hospital", "school", "fire_station", "metro_girisi"]},
    }
json.dump({"esikler": ESIK, "ozet": ozet}, open(os.path.join(OUT, "maruziyet_ozet.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
log("ÖZET\n" + json.dumps(ozet, ensure_ascii=False, indent=1))
