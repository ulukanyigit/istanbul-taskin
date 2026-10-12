"""Faz 5c — Arayüzün küçük ek dosyaları: mahalle karnesi, doğrulama olayları, harita yazı tipleri.

Çalıştırma: python 07_web_ek.py <proje_kökü> <çıktı_klasörü> <fonts_klasörü>
Çıktılar: karne.json, olaylar.geojson, dogrulama.json, font/{nsr,nsm}/{aralık}.pbf
"""
import json
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pyogrio

KOK, CIKTI, FONT = sys.argv[1:4]
PR = os.path.join(KOK, "data", "processed")
V = os.path.join(KOK, "validation")

# mahalle karnesi (yalnız il içi): fid → kısa alan adları
k = pd.read_csv(os.path.join(PR, "mahalle_karnesi.csv"))
k = k[k.istanbul == 1]
alan = {"nufus": 0, "bina": 0, "hastane_ortanca_m": 0, "risk_indeksi": 3, "gi_z": 2, "sicak_nokta": None,
        "tehlike_pct": 1, "maruziyet_pct": 1, "erisim_pct": 1}
for P in (25, 50, 100):
    for a, r in (("islak_oran", 4), ("bina_10cm", 0), ("bina_30cm", 0), ("nufus_10cm", 0), ("kapali_yol_km", 2),
                 ("hastane", 0), ("okul", 0), ("itfaiye", 0), ("metro", 0), ("ulasilamaz", 4), ("uzama1km", 4)):
        alan[f"{a}_{P}"] = r
karne = {}
for _, s in k.iterrows():
    d = {"ad": s.mahalle, "ilce": s.ilce}
    for a, r in alan.items():
        v = s[a]
        if isinstance(v, (float, np.floating)) and np.isnan(v):
            v = None
        elif r is not None:
            v = round(float(v), r) if r else int(round(float(v)))
        d[a] = v
    karne[int(s.mahalle_fid)] = d
# kentleşme etkisi (05_kentlesme.py): mahalle adı + ilçe ile eşle
ky = os.path.join(PR, "kentlesme_mahalle.csv")
if os.path.exists(ky):
    km = pd.read_csv(ky)
    km = km[km.aday >= 5].set_index(["ilce", "mahalle"])
    for d in karne.values():
        key = (d["ilce"], d["ad"])
        if key in km.index:
            r = km.loc[key]
            d["esik90"], d["esik20"], d["dusus_mm"] = float(r.esik_ortanca_1990), float(r.esik_ortanca_2020), float(r.dusus_mm)
json.dump(karne, open(os.path.join(CIKTI, "karne.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("karne.json", len(karne), "mahalle")

# doğrulama olayları
ol = pd.read_csv(os.path.join(V, "olaylar.csv"))
ds = pd.read_csv(os.path.join(V, "dogrulama_sonuc.csv"))
ol = ol.merge(ds[["olay_id", "min_esik_mm_hat", "maks_derinlik_25mm_hat", "min_esik_mm_r100", "maks_derinlik_25mm_r100",
                  "yuzdelik_derinlik25"]], on="olay_id", how="left")
oz = []
for katman in ("olaylar_nokta", "olaylar_hat"):
    g = pyogrio.read_dataframe(os.path.join(V, "olaylar.gpkg"), layer=katman).to_crs(4326)
    oz.append(g[["olay_id", "geometry"]])
g = pd.concat(oz).merge(ol, on="olay_id")
g["esik_mm"] = g.min_esik_mm_hat.fillna(g.min_esik_mm_r100)
g["derinlik25"] = g.maks_derinlik_25mm_hat.fillna(g.maks_derinlik_25mm_r100).round(2)
g = g[["olay_id", "tarih", "ilce", "tanim", "tip", "guven", "kaynak", "esik_mm", "derinlik25", "yuzdelik_derinlik25", "geometry"]]
yol = os.path.join(CIKTI, "olaylar.geojson")
if os.path.exists(yol):
    os.remove(yol)
pyogrio.write_dataframe(g, yol, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": 6})
print("olaylar.geojson", len(g))
shutil.copy(os.path.join(V, "dogrulama_ozet.json"), os.path.join(CIKTI, "dogrulama.json"))

# yazı tipleri: Türkçe için 0-255 ve 256-511, tipografik işaretler için 8192-8447
for kisa, ad in (("nsr", "Noto Sans Regular"), ("nsm", "Noto Sans Medium")):
    hedef = os.path.join(CIKTI, "font", kisa)
    os.makedirs(hedef, exist_ok=True)
    for ar in ("0-255", "256-511", "8192-8447"):
        shutil.copy(os.path.join(FONT, ad, ar + ".pbf"), hedef)
print("yazı tipleri kopyalandı")
