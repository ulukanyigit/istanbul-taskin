"""Faz 6a — Senaryo su derinliği rasterları.

Drenaj devre dışı senaryosunda 25, 50, 75, 100 mm toplam yağış için her çukurun su kotu (kova motoru) ve
10 m su derinliği rasterı.

Çalıştırma: python 01_su_derinligi.py <proje_kökü>
Çıktı (data/processed): derinlik_{P}mm_10m.tif (Float32, m; kuru = 0), su_seviyeleri.csv
"""
import os
import sys
import time

import numpy as np
import pandas as pd
from osgeo import gdal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motor import Model  # noqa: E402

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(KOK, "data", "processed")
SENARYO_MM = [25, 50, 75, 100]
t0 = time.time()

model = Model(KOK)
print(f"[{time.time() - t0:4.0f} sn] model yüklendi: {model.m:,} çukur", flush=True)

tablo = pd.DataFrame({"cukur_id": np.arange(1, model.m + 1)})
seviyeler = {}
taban = np.full(model.m + 1, np.nan, np.float32)
taban[1:] = model.kot[model.ofset[:-1]]
for P in SENARYO_MM:
    s = model.senaryo(P)
    seviyeler[P] = s["seviye"]
    tablo[f"hacim_{P}mm_m3"] = s["hacim"][1:].round(1)
    tablo[f"doluluk_{P}mm"] = s["doluluk"][1:].round(3)
    tablo[f"islak_{P}mm_m2"] = s["islak_px"][1:] * model.A
    tablo[f"maks_derinlik_{P}mm_m"] = np.nan_to_num(s["seviye"][1:] - taban[1:]).round(2)
    print(f"[{time.time() - t0:4.0f} sn] {P} mm: dolu çukur {(s['doluluk'][1:] >= 0.999).sum():,}, "
          f"ıslak alan {s['islak_px'][1:].sum() * model.A / 1e6:.1f} km², depolanan {s['hacim'][1:].sum() / 1e6:.2f} milyon m³", flush=True)
tablo.to_csv(os.path.join(OUT, "su_seviyeleri.csv"), index=False)

ci = gdal.Open(os.path.join(OUT, "cukur_id_10m.tif"))
dm = gdal.Open(os.path.join(KOK, "data", "interim", "dem_kosullu_10m.tif"))
nx, ny = ci.RasterXSize, ci.RasterYSize
cikti = {}
for P in SENARYO_MM:
    d = gdal.GetDriverByName("GTiff").Create(os.path.join(OUT, f"derinlik_{P}mm_10m.tif"), nx, ny, 1, gdal.GDT_Float32,
                                             options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES", "BIGTIFF=IF_SAFER"])
    d.SetGeoTransform(ci.GetGeoTransform()); d.SetProjection(ci.GetProjection()); d.GetRasterBand(1).SetNoDataValue(0)
    cikti[P] = d
for y in range(0, ny, 1024):
    h = min(1024, ny - y)
    lab = ci.GetRasterBand(1).ReadAsArray(0, y, nx, h)
    z = dm.GetRasterBand(1).ReadAsArray(0, y, nx, h)
    s = lab > 0
    for P in SENARYO_MM:
        out = np.zeros((h, nx), np.float32)
        sev = seviyeler[P][lab[s]]
        dd = np.where(np.isfinite(sev), sev - z[s], 0)
        out[s] = np.where(dd > 0.005, dd, 0)
        cikti[P].GetRasterBand(1).WriteArray(out, 0, y)
for d in cikti.values():
    d.FlushCache()
cikti = ci = dm = None
print(f"[{time.time() - t0:4.0f} sn] derinlik rasterları yazıldı", flush=True)
