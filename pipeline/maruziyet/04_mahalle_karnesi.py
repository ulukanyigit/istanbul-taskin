"""Faz 6d — Mahalle karnesi, risk indeksi ve sıcak noktalar.

Nüfus: GHS-POP 2020 (100 m) mekânsal dağılım olarak kullanılır, il toplamı TÜİK ADNKS 2020'ye (15.462.452)
ölçeklenir. Her 100 m hücrenin nüfusu, merkezi o hücrede olan binalara taban alanı oranında dağıtılır
(konut türü binalar varsa yalnızca onlara). Binası olmayan hücrelerin nüfusu "dağıtılamayan" olarak raporlanır.

Mahalle göstergeleri (25 / 50 / 100 mm, drenaj devre dışı):
  islak_m2, islak_oran      su altında kalan alan (derinlik > 0,5 cm)
  bina_10cm, nufus_10cm     duvarına ≥ 10 cm su değen bina ve içindeki nüfus
  bina_30cm                 ≥ 30 cm (bodrum / zemin kat riski)
  kapali_yol_km             ≥ 30 cm su olan yol parçalarının uzunluğu (parça merkezi mahallede)
  hastane, okul, itfaiye, metro   30 m içinde ≥ 10 cm su olan tesis sayısı
  ulasilamaz, uzama1km      hastaneye ulaşamayan / yolu 1 km'den fazla uzayan yol düğümü oranı (03_erisim)

Risk indeksi (50 mm): tehlike (ıslak alan oranı), maruziyet (etkilenen nüfus) ve erişim kaybı (ulaşılamaz +
uzayan düğüm oranı) bileşenlerinin il içi yüzdelik sıralarının ortalaması, 0–100. Yaş/gelir gibi kırılganlık
verileri mahalle düzeyinde açık olmadığından indekse alınmadı.
Sıcak nokta: risk indeksi üzerinde Getis-Ord Gi* (mahalle merkezleri arası ≤ 2 km, ikili ağırlık, kendisi dahil).

Çalıştırma: python 04_mahalle_karnesi.py <proje_kökü>
Çıktı (data/processed): mahalle_karnesi.gpkg, mahalle_karnesi.csv, karne_ozet.json, bina_nufus.csv
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from osgeo import gdal, ogr
from scipy.spatial import cKDTree

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PR = os.path.join(KOK, "data", "processed")
OSM = os.path.join(KOK, "data", "interim", "osm_istanbul.gpkg")
GEE = os.path.join(KOK, "istanbul_taskin_gee")
SENARYO_MM = [25, 50, 100]
TUIK_2020 = 15_462_452
KONUT = {"yes", "apartments", "house", "residential", "detached", "terrace", "semidetached_house", "dormitory", "bungalow"}
GI_BANT_M = 2000
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


# --- mahalleler ve ilçeleri
idr = ogr.Open(os.path.join(PR, "idari.gpkg"))
ilceler = [(f.GetField("ilce"), int(f.GetField("istanbul") or f.GetField("ilce") in ("Kağıthane", "Kâğıthane")),
            f.GetGeometryRef().Clone()) for f in idr.GetLayerByName("ilceler")]
mah = []
for f in idr.GetLayerByName("mahalleler"):
    g = f.GetGeometryRef()
    c = g.PointOnSurface()
    ilce, ist = None, 0
    for ad, i_, gi in ilceler:
        if gi.Contains(c):
            ilce, ist = ad, i_
            break
    mah.append({"mahalle_fid": f.GetFID(), "mahalle": f.GetField("mahalle"), "ilce": ilce, "istanbul": ist,
                "alan_m2": g.GetArea(), "cx": c.GetX(), "cy": c.GetY()})
idr = None
M = pd.DataFrame(mah).set_index("mahalle_fid")
log(f"{len(M)} mahalle, İstanbul içinde {M.istanbul.sum()}")

# --- nüfus: GHS-POP 2020 → TÜİK ölçeği → binalara
pop_ds = gdal.Open(os.path.join(GEE, "ghs_pop_2020_2025_100m.tif"))
pgt = pop_ds.GetGeoTransform()
pop = pop_ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
pop[~np.isfinite(pop) | (pop < 0)] = 0
mah_ds = gdal.Open(os.path.join(PR, "mahalle_id_10m.tif"))
gt = mah_ds.GetGeoTransform()
NX, NY = mah_ds.RasterXSize, mah_ds.RasterYSize
# 100 m hücrenin mahallesi: hücre merkezindeki 10 m piksel
ph, pw = pop.shape
yy, xx = np.mgrid[0:ph, 0:pw]
cx = pgt[0] + (xx + 0.5) * pgt[1]; cy = pgt[3] + (yy + 0.5) * pgt[5]
c10 = ((cx - gt[0]) / gt[1]).astype(np.int64); r10 = ((cy - gt[3]) / gt[5]).astype(np.int64)
ok = (c10 >= 0) & (c10 < NX) & (r10 >= 0) & (r10 < NY)
mah_r = mah_ds.GetRasterBand(1).ReadAsArray(buf_xsize=NX // 10, buf_ysize=NY // 10, resample_alg=gdal.GRIORA_NearestNeighbour)
hucre_mah = np.zeros(pop.shape, np.int32)
hucre_mah[ok] = mah_r[np.minimum(r10[ok] // 10, mah_r.shape[0] - 1), np.minimum(c10[ok] // 10, mah_r.shape[1] - 1)]
ist_fid = set(M.index[M.istanbul == 1])
ist_hucre = np.isin(hucre_mah, list(ist_fid))
ghs_il = pop[ist_hucre].sum()
olcek = TUIK_2020 / ghs_il
pop *= olcek
log(f"GHS-POP il içi {ghs_il:,.0f} → TÜİK {TUIK_2020:,} (ölçek {olcek:.3f})")

ds = ogr.Open(OSM)
b_fid, b_x, b_y, b_alan, b_konut = [], [], [], [], []
for f in ds.GetLayerByName("binalar"):
    g = f.GetGeometryRef()
    if g is None:
        continue
    try:
        c = g.Centroid()
        cx_, cy_ = c.GetX(), c.GetY()
    except RuntimeError:                      # bozuk OSM geometrisi: zarf merkezi
        e = g.GetEnvelope()
        cx_, cy_ = (e[0] + e[1]) / 2, (e[2] + e[3]) / 2
    b_fid.append(f.GetFID()); b_x.append(cx_); b_y.append(cy_)
    b_alan.append(f.GetField("alan_m2") or 0.0); b_konut.append(f.GetField("tur") in KONUT)
ds = None
B = pd.DataFrame({"bina_fid": b_fid, "x": b_x, "y": b_y, "alan": b_alan, "konut": b_konut})
B["pc"] = ((B.x - pgt[0]) / pgt[1]).astype(int); B["pr"] = ((B.y - pgt[3]) / pgt[5]).astype(int)
B = B[(B.pc >= 0) & (B.pc < pw) & (B.pr >= 0) & (B.pr < ph)]
B["hucre"] = B.pr * pw + B.pc
konut_var = B.groupby("hucre").konut.transform("any")
B["agirlik"] = np.where(~konut_var | B.konut, B.alan, 0.0)
B["agirlik_top"] = B.groupby("hucre").agirlik.transform("sum")
B["nufus"] = np.where(B.agirlik_top > 0, pop.ravel()[B.hucre.values] * B.agirlik / B.agirlik_top, 0.0)
dagitilan = B.loc[np.isin(hucre_mah.ravel()[B.hucre.values], list(ist_fid)), "nufus"].sum()
log(f"binalara dağıtılan il içi nüfus {dagitilan:,.0f} ({dagitilan / TUIK_2020:.1%})")

bm = pd.read_csv(os.path.join(PR, "bina_maruziyet.csv"))
B = B.merge(bm[["bina_fid", "mahalle_fid"] + [f"d{P}_m" for P in SENARYO_MM]], on="bina_fid", how="left")
B[["bina_fid", "mahalle_fid", "alan", "konut", "nufus"] + [f"d{P}_m" for P in SENARYO_MM]].round(2).to_csv(
    os.path.join(PR, "bina_nufus.csv"), index=False)
M["nufus"] = B.groupby("mahalle_fid").nufus.sum()
M["bina"] = B.groupby("mahalle_fid").size()

# --- ıslak alan (mahalle × senaryo)
islak = {P: np.zeros(int(M.index.max()) + 1, np.int64) for P in SENARYO_MM}
der = {P: gdal.Open(os.path.join(PR, f"derinlik_{P}mm_10m.tif")) for P in SENARYO_MM}
for y0 in range(0, NY, 1024):
    h = min(1024, NY - y0)
    mm = mah_ds.GetRasterBand(1).ReadAsArray(0, y0, NX, h)
    for P in SENARYO_MM:
        d = der[P].GetRasterBand(1).ReadAsArray(0, y0, NX, h)
        s = (d > 0.005) & (mm > 0)
        islak[P] += np.bincount(mm[s], minlength=len(islak[P]))
der = None
px = gt[1] * -gt[5]

yol = pd.read_csv(os.path.join(PR, "yol_maruziyet.csv"))
ds = ogr.Open(OSM)
ymah = {}
yl = ds.GetLayerByName("yollar")
mb = mah_ds.GetRasterBand(1)
for f in yl:
    g = f.GetGeometryRef()
    e = g.GetEnvelope() if g is not None else (0, 0, 0, 0)
    cc, rr = int(((e[0] + e[1]) / 2 - gt[0]) / gt[1]), int(((e[2] + e[3]) / 2 - gt[3]) / gt[5])
    ymah[f.GetFID()] = (cc, rr)
ds = None
yr = np.array([ymah[i][1] for i in yol.yol_fid]); yc = np.array([ymah[i][0] for i in yol.yol_fid])
ok = (yc >= 0) & (yc < NX) & (yr >= 0) & (yr < NY)
yol_mah = np.zeros(len(yol), np.int32)
srt = np.argsort(yr)
for y0 in range(0, NY, 1024):
    h = min(1024, NY - y0)
    a, b = np.searchsorted(yr[srt], [y0, y0 + h])
    idx = srt[a:b]; idx = idx[ok[idx]]
    if len(idx):
        blok = mb.ReadAsArray(0, y0, NX, h)
        yol_mah[idx] = blok[yr[idx] - y0, yc[idx]]
yol["mahalle_fid"] = yol_mah

tes = pd.read_csv(os.path.join(PR, "tesis_maruziyet.csv"))
tc = ((tes.x - gt[0]) / gt[1]).astype(int).values; tr = ((tes.y - gt[3]) / gt[5]).astype(int).values
tes["mahalle_fid"] = [int(mb.ReadAsArray(int(c), int(r), 1, 1)[0, 0]) for c, r in zip(tc, tr)]
erisim = pd.read_csv(os.path.join(PR, "mahalle_erisim.csv")).set_index("mahalle_fid")
mah_ds = None

for P in SENARYO_MM:
    d = f"d{P}_m"
    M[f"islak_m2_{P}"] = islak[P][M.index.values] * px
    M[f"islak_oran_{P}"] = (M[f"islak_m2_{P}"] / M.alan_m2).round(4)
    M[f"bina_10cm_{P}"] = B[B[d] >= 0.10].groupby("mahalle_fid").size()
    M[f"bina_30cm_{P}"] = B[B[d] >= 0.30].groupby("mahalle_fid").size()
    M[f"nufus_10cm_{P}"] = B[B[d] >= 0.10].groupby("mahalle_fid").nufus.sum()
    M[f"kapali_yol_km_{P}"] = yol[yol[d] >= 0.30].groupby("mahalle_fid").uzunluk_m.sum() / 1000
    for t, ad in [("hospital", "hastane"), ("school", "okul"), ("fire_station", "itfaiye"), ("metro_girisi", "metro")]:
        M[f"{ad}_{P}"] = tes[(tes.tur == t) & (tes[d] >= 0.10)].groupby("mahalle_fid").size()
    if P in (25, 50, 100):
        M[f"ulasilamaz_{P}"] = erisim[f"ulasilamaz_{P}"]
        M[f"uzama1km_{P}"] = erisim[f"uzama1km_{P}"]
M["hastane_ortanca_m"] = erisim.hastane_ortanca_m
M = M.fillna({c: 0 for c in M.columns if c not in ("mahalle", "ilce", "hastane_ortanca_m")})

# --- risk indeksi (50 mm) ve Gi* (yalnız İstanbul mahalleleri)
I = M[M.istanbul == 1].copy()
yuzde = lambda s: s.rank(pct=True, method="average")
I["tehlike_pct"] = yuzde(I.islak_oran_50)
I["maruziyet_pct"] = yuzde(I.nufus_10cm_50)
I["erisim_pct"] = yuzde(I.ulasilamaz_50 + I.uzama1km_50)
I["risk_indeksi"] = (100 * (I.tehlike_pct + I.maruziyet_pct + I.erisim_pct) / 3).round(1)
xy = I[["cx", "cy"]].values
agac = cKDTree(xy)
komsu = agac.query_ball_point(xy, GI_BANT_M)
x = I.risk_indeksi.values
n, xbar, s = len(x), x.mean(), x.std()
gi = np.empty(n)
for i, k in enumerate(komsu):
    w = len(k)
    pay = x[k].sum() - xbar * w
    payda = s * np.sqrt((n * w - w * w) / (n - 1))
    gi[i] = pay / payda if payda > 0 else 0
I["gi_z"] = gi.round(2)
I["sicak_nokta"] = np.select([gi >= 2.576, gi >= 1.96, gi >= 1.645, gi <= -1.96], ["%99 sıcak", "%95 sıcak", "%90 sıcak", "soğuk"], "anlamsız")
M = M.join(I[["tehlike_pct", "maruziyet_pct", "erisim_pct", "risk_indeksi", "gi_z", "sicak_nokta"]])
M.reset_index().drop(columns=["cx", "cy"]).round(4).to_csv(os.path.join(PR, "mahalle_karnesi.csv"), index=False)

# --- GPKG
src = ogr.Open(os.path.join(PR, "idari.gpkg"))
sl = src.GetLayerByName("mahalleler")
out_p = os.path.join(PR, "mahalle_karnesi.gpkg")
if os.path.exists(out_p):
    os.remove(out_p)
od = ogr.GetDriverByName("GPKG").CreateDataSource(out_p)
ol = od.CreateLayer("mahalle_karnesi", sl.GetSpatialRef(), ogr.wkbMultiPolygon)
kolonlar = [c for c in M.columns if c not in ("cx", "cy")]
for c in ["mahalle_fid"] + kolonlar:
    t = M[c].dtype if c != "mahalle_fid" else np.dtype("int64")
    ol.CreateField(ogr.FieldDefn(c, ogr.OFTString if t == object else (ogr.OFTInteger64 if t.kind in "iub" else ogr.OFTReal)))
ol.StartTransaction()
for f in sl:
    fid = f.GetFID()
    if fid not in M.index:
        continue
    nf = ogr.Feature(ol.GetLayerDefn())
    nf.SetGeometry(ogr.ForceToMultiPolygon(f.GetGeometryRef().Clone()))
    nf.SetField("mahalle_fid", int(fid))
    for c in kolonlar:
        v = M.at[fid, c]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        nf.SetField(c, v if isinstance(v, str) else (int(v) if isinstance(v, (np.integer, int, bool, np.bool_)) else float(v)))
    ol.CreateFeature(nf)
ol.CommitTransaction()
od = src = None

# --- özet
ist = M[M.istanbul == 1]
ozet = {"mahalle": int(len(ist)), "nufus_olcek": round(olcek, 4), "binalara_dagitilan_oran": round(dagitilan / TUIK_2020, 4)}
for P in SENARYO_MM:
    ozet[f"{P}mm"] = {
        "islak_km2": round(ist[f"islak_m2_{P}"].sum() / 1e6, 1),
        "bina_10cm": int(ist[f"bina_10cm_{P}"].sum()), "bina_30cm": int(ist[f"bina_30cm_{P}"].sum()),
        "nufus_10cm": int(ist[f"nufus_10cm_{P}"].sum()), "kapali_yol_km": round(ist[f"kapali_yol_km_{P}"].sum(), 1),
        "hastane": int(ist[f"hastane_{P}"].sum()), "okul": int(ist[f"okul_{P}"].sum()),
        "itfaiye": int(ist[f"itfaiye_{P}"].sum()), "metro_girisi": int(ist[f"metro_{P}"].sum()),
    }
ozet["sicak_nokta"] = ist.sicak_nokta.value_counts().to_dict()
ozet["en_riskli_10"] = ist.sort_values("risk_indeksi", ascending=False).head(10)[
    ["ilce", "mahalle", "risk_indeksi", "nufus_10cm_50", "islak_oran_50", "ulasilamaz_50"]].round(3).to_dict("records")
json.dump(ozet, open(os.path.join(PR, "karne_ozet.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
log("ÖZET\n" + json.dumps(ozet, ensure_ascii=False, indent=1, default=float))
