"""Faz 6c — Hastaneye yol erişimi: kuru durum ile su basmış durum karşılaştırması.

Yol ağı: OSM yolları (araç trafiğine açık sınıflar), köşe noktaları düğüm, ardışık köşeler kenar.
Kenar orta noktasındaki su derinliği ≥ 0,30 m ise kenar kapalı (köprü/tünel kenarları hiç kapanmaz).
Her düğümden en yakın hastaneye en kısa yol (çok kaynaklı Dijkstra, yönsüz). Mahalle düzeyinde: düğümlerin
ortanca mesafesi, hastaneye hiç ulaşamayan düğüm oranı ve mesafesi 1 km'den fazla uzayan düğüm oranı.

Çalıştırma: python 03_erisim.py <proje_kökü>
Çıktı (data/processed): mahalle_id_10m.tif (yoksa), mahalle_erisim.csv, erisim_ozet.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from osgeo import gdal, ogr
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PR = os.path.join(KOK, "data", "processed")
OSM = os.path.join(KOK, "data", "interim", "osm_istanbul.gpkg")
SENARYO_MM = [25, 50, 100]
KAPALI_M = 0.30
SURUS = ("motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
         "secondary_link", "tertiary_link", "unclassified", "residential", "living_street", "service", "road")
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


ref = gdal.Open(os.path.join(PR, "cukur_id_10m.tif"))
GT, WKT, NX, NY = ref.GetGeoTransform(), ref.GetProjection(), ref.RasterXSize, ref.RasterYSize
ref = None

# mahalle kimlik rasterı (kalıcı; 04 ve web de kullanır)
MAH_R = os.path.join(PR, "mahalle_id_10m.tif")
if not os.path.exists(MAH_R):
    r = gdal.GetDriverByName("GTiff").Create(MAH_R, NX, NY, 1, gdal.GDT_Int32, options=["COMPRESS=DEFLATE", "TILED=YES"])
    r.SetGeoTransform(GT); r.SetProjection(WKT); r.GetRasterBand(1).SetNoDataValue(0)
    gdal.Rasterize(r, os.path.join(PR, "idari.gpkg"), options=gdal.RasterizeOptions(
        SQLStatement="SELECT geom, fid * 1 AS rid FROM mahalleler", SQLDialect="SQLite", attribute="rid"))
    r = None
    log("mahalle_id_10m.tif yazıldı")

# 1) kenarlar
ds = ogr.Open(OSM)
lyr = ds.GetLayerByName("yollar")
lyr.SetAttributeFilter("sinif IN (" + ",".join(f"'{s}'" for s in SURUS) + ")")
X, Y, U_off, korunan = [], [], [], []
for f in lyr:
    g = f.GetGeometryRef()
    parcalar = [g] if g.GetGeometryType() == ogr.wkbLineString else [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
    kopru_tunel = (f.GetField("kopru") or 0) or (f.GetField("tunel") or 0)
    for p in parcalar:
        pts = p.GetPoints()
        if len(pts) < 2:
            continue
        a = np.asarray(pts)[:, :2]
        X.append(a[:, 0]); Y.append(a[:, 1]); U_off.append(len(a)); korunan.append(bool(kopru_tunel))
ds = None
x = np.concatenate(X); y = np.concatenate(Y)
uz = np.array(U_off)
anahtar = np.round(x * 10).astype(np.int64) * 100000000 + np.round(y * 10).astype(np.int64)
_, dugum = np.unique(anahtar, return_inverse=True)
n_dugum = int(dugum.max()) + 1
son = np.cumsum(uz)
bas = son - uz
gecerli = np.ones(len(x), bool); gecerli[son - 1] = False           # her hattın son köşesi kenar başlatmaz
i0 = np.flatnonzero(gecerli)
u, v = dugum[i0], dugum[i0 + 1]
L = np.hypot(x[i0 + 1] - x[i0], y[i0 + 1] - y[i0])
mx, my = (x[i0] + x[i0 + 1]) / 2, (y[i0] + y[i0 + 1]) / 2
kenar_korunan = np.repeat(np.array(korunan), uz - 1)
dx = np.zeros(n_dugum); dy = np.zeros(n_dugum)
dx[dugum] = x; dy[dugum] = y
log(f"ağ: {n_dugum:,} düğüm, {len(u):,} kenar, {L.sum() / 1000:,.0f} km")

# 2) kenar orta noktalarında su derinliği (satır bloklarıyla)
col = ((mx - GT[0]) / GT[1]).astype(np.int64)
row = ((my - GT[3]) / GT[5]).astype(np.int64)
icerde = (col >= 0) & (col < NX) & (row >= 0) & (row < NY)
derinlik = {P: np.zeros(len(u), np.float32) for P in SENARYO_MM}
sira = np.argsort(row)
for P in SENARYO_MM:
    rds = gdal.Open(os.path.join(PR, f"derinlik_{P}mm_10m.tif"))
    rd = rds.GetRasterBand(1)
    for y0 in range(0, NY, 1024):
        h = min(1024, NY - y0)
        a, b = np.searchsorted(row[sira], [y0, y0 + h])
        idx = sira[a:b]
        idx = idx[icerde[idx]]
        if not len(idx):
            continue
        blok = rd.ReadAsArray(0, y0, NX, h)
        derinlik[P][idx] = blok[row[idx] - y0, col[idx]]
log("kenar derinlikleri okundu")

# 3) düğüm → mahalle
mahalle = np.zeros(n_dugum, np.int32)
dc = ((dx - GT[0]) / GT[1]).astype(np.int64); dr = ((dy - GT[3]) / GT[5]).astype(np.int64)
ok = (dc >= 0) & (dc < NX) & (dr >= 0) & (dr < NY)
mds = gdal.Open(MAH_R)
mb = mds.GetRasterBand(1)
srt = np.argsort(dr)
for y0 in range(0, NY, 1024):
    h = min(1024, NY - y0)
    a, b = np.searchsorted(dr[srt], [y0, y0 + h])
    idx = srt[a:b]; idx = idx[ok[idx]]
    if len(idx):
        blok = mb.ReadAsArray(0, y0, NX, h)
        mahalle[idx] = blok[dr[idx] - y0, dc[idx]]

# 4) hastaneler → en yakın düğüm
ds = ogr.Open(OSM)
hx, hy = [], []
for f in ds.GetLayerByName("kritik_tesisler"):
    if f.GetField("tur") == "hospital":
        g = f.GetGeometryRef(); hx.append(g.GetX()); hy.append(g.GetY())
ds = None
agac = cKDTree(np.column_stack([dx, dy]))
mesafe, hd = agac.query(np.column_stack([hx, hy]))
hastane_dugum = np.unique(hd[mesafe < 500])
log(f"{len(hx)} hastane, {len(hastane_dugum)} tanesi ağa bağlandı (≤500 m)")


def en_kisa(acik):
    a, b, w = u[acik], v[acik], L[acik]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    df = pd.DataFrame({"a": lo, "b": hi, "w": w}).groupby(["a", "b"], sort=False).w.min().reset_index()
    G = sparse.csr_matrix((df.w.values, (df.a.values, df.b.values)), shape=(n_dugum, n_dugum))
    return dijkstra(G, directed=False, indices=hastane_dugum, min_only=True)


kuru = en_kisa(np.ones(len(u), bool))
log("kuru durum mesafeleri")
sonuclar = {}
for P in SENARYO_MM:
    kapali = (derinlik[P] >= KAPALI_M) & ~kenar_korunan
    sonuclar[P] = (en_kisa(~kapali), int(kapali.sum()), float(L[kapali].sum() / 1000))
    log(f"{P} mm: kapalı kenar {kapali.sum():,} ({L[kapali].sum() / 1000:,.1f} km)")

# 5) mahalle özeti
erisilen = np.isfinite(kuru)
df = pd.DataFrame({"mahalle_fid": mahalle, "kuru": kuru})
for P in SENARYO_MM:
    d = sonuclar[P][0]
    df[f"ulasilamaz_{P}"] = erisilen & ~np.isfinite(d)
    df[f"uzama1km_{P}"] = erisilen & np.isfinite(d) & ((d - kuru) > 1000)
    df[f"ek_m_{P}"] = np.where(erisilen & np.isfinite(d), d - kuru, np.nan)
df = df[(df.mahalle_fid > 0) & erisilen]
agg = {"kuru": "median"}
for P in SENARYO_MM:
    agg.update({f"ulasilamaz_{P}": "mean", f"uzama1km_{P}": "mean", f"ek_m_{P}": "median"})
m = df.groupby("mahalle_fid").agg(agg)
m.insert(0, "dugum", df.groupby("mahalle_fid").size())
m = m.rename(columns={"kuru": "hastane_ortanca_m"}).round(3).reset_index()
m.to_csv(os.path.join(PR, "mahalle_erisim.csv"), index=False)
ozet = {"dugum": n_dugum, "kenar": int(len(u)), "ag_km": round(float(L.sum() / 1000)), "hastane_bagli": int(len(hastane_dugum))}
for P in SENARYO_MM:
    d = sonuclar[P][0]
    ozet[f"{P}mm"] = {"kapali_kenar": sonuclar[P][1], "kapali_km": round(sonuclar[P][2], 1),
                      "ulasilamaz_dugum_orani": round(float((erisilen & ~np.isfinite(d)).sum() / erisilen.sum()), 4),
                      "uzayan_1km_dugum_orani": round(float((erisilen & np.isfinite(d) & ((d - kuru) > 1000)).sum() / erisilen.sum()), 4),
                      "mahalle_10pct_ulasilamaz": int((m[f"ulasilamaz_{P}"] >= 0.10).sum())}
json.dump(ozet, open(os.path.join(PR, "erisim_ozet.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
log("ÖZET " + json.dumps(ozet, ensure_ascii=False))
