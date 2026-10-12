"""Faz 6e — Kentleşme etkisi: 1990'daki yapılaşmayla çukurlar kaç mm'de dolardı?

1990 CN'si: bugün yapılaşmış (WorldCover 50) bir 10 m pikselin CN'si, 100 m hücredeki GHSL yapı alanı oranı
r = yapı_1990 / yapı_2020 ile bugünkü CN ve aynı toprak grubundaki çayır/mera CN'si arasında karıştırılır:
    CN_1990 = r · CN_bugün + (1 − r) · CN_çayır(HSG)
Diğer pikseller değişmez (1990'dan bu yana yapılaşmanın ortadan kalktığı alanlar yok sayılır). Çukurlar, havzalar ve
dolma–taşma ağacı aynıdır; yalnız yüzey akışı değişir. Yani sonuç "aynı topografyada, 1990'ın geçirimsizliğiyle".

Çalıştırma: python 05_kentlesme.py <proje_kökü>
Çıktılar (data/processed): havza_cn_hist_1990.npy, kentlesme_cukur.csv, kentlesme_mahalle.csv, kentlesme_ozet.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import rasterio
from numba import njit

KOK = sys.argv[1]
PR, GEE = os.path.join(KOK, "data", "processed"), os.path.join(KOK, "istanbul_taskin_gee")
CN_MERA = {1: 39, 2: 61, 3: 74, 4: 80}     # WorldCover 30 (çayır), TR-55 iyi koşul — 03_arazi_cn.js ile aynı tablo
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


def oku(ad, klasor=GEE, bant=1):
    with rasterio.open(os.path.join(klasor, ad)) as d:
        return d.read(bant), d.transform


@njit
def hist(hav, cn, m):
    h = np.zeros((m + 1, 46), np.int64)
    ny, nx = hav.shape
    for y in range(ny):
        for x in range(nx):
            b = hav[y, x]; c = cn[y, x]
            if b > 0 and c > 0:
                h[b, min(max(c - 55, 0), 45)] += 1
    return h


def scs_q(P, cn):
    S = 25400.0 / cn - 254.0
    if S <= 0:
        return P.copy()
    Pe = np.maximum(P - 0.2 * S, 0.0)
    return Pe ** 2 / (Pe + S)


def esikler(cn_hist, alici, kap, A):
    Pg = np.arange(0, 301, dtype=np.float64)
    Q = np.stack([scs_q(Pg, c) for c in np.arange(55, 101, dtype=np.float64)])
    Vin = (cn_hist.astype(np.float64) @ Q * (A / 1000.0)).astype(np.float32)
    der = np.full(len(alici), -1, np.int64); der[0] = 0
    for b in range(1, len(alici)):
        if der[b] >= 0:
            continue
        yol, c = [], b
        while c > 0 and der[c] < 0:
            yol.append(c); c = alici[c] if alici[c] >= 0 else 0
        base = der[c] if c > 0 else 0
        for j in reversed(yol):
            base += 1; der[j] = base
    for b in np.argsort(-der[1:], kind="stable") + 1:
        r = alici[b]
        if r > 0:
            Vin[r] += np.maximum(Vin[b] - kap[b], 0)
    dolu = Vin >= kap[:, None]
    e = np.where(dolu.any(axis=1), dolu.argmax(axis=1), 301).astype(np.int32)
    return e, Vin


wc, tr = oku("worldcover_10m.tif")
cn, _ = oku("cn_10m.tif")
NY, NX = wc.shape
A = tr.a * -tr.e
# 100 m GHSL ve 250 m HSG hücre indeksleri
with rasterio.open(os.path.join(GEE, "ghsl_yapi_1990_2020_100m.tif")) as d:
    g90, g20, gtr = d.read(1), d.read(2), d.transform
with rasterio.open(os.path.join(GEE, "hsg_250m.tif")) as d:
    hsg, htr = d.read(1), d.transform
xs = tr.c + (np.arange(NX) + 0.5) * tr.a
ys = tr.f + (np.arange(NY) + 0.5) * tr.e
gi = np.clip(((xs - gtr.c) / gtr.a).astype(int), 0, g90.shape[1] - 1)
gj = np.clip(((ys - gtr.f) / gtr.e).astype(int), 0, g90.shape[0] - 1)
hi = np.clip(((xs - htr.c) / htr.a).astype(int), 0, hsg.shape[1] - 1)
hj = np.clip(((ys - htr.f) / htr.e).astype(int), 0, hsg.shape[0] - 1)
oran = np.where(g20 > 0, np.clip(g90 / np.maximum(g20, 1e-6), 0, 1), 1.0).astype(np.float32)
cn90 = cn.copy()
B = 1000
for y0 in range(0, NY, B):
    sl = slice(y0, min(y0 + B, NY))
    r = oran[gj[sl]][:, gi]
    h = hsg[hj[sl]][:, hi]
    mera = np.select([h == 1, h == 2, h == 3], [CN_MERA[1], CN_MERA[2], CN_MERA[3]], CN_MERA[4])
    yap = wc[sl] == 50
    c = cn[sl].astype(np.float32)
    cn90[sl] = np.where(yap & (cn[sl] > 0), np.round(r * c + (1 - r) * mera), cn[sl]).astype(cn.dtype)
del wc
yapi = cn > 0
log(f"CN: 2020 ortalama {cn[yapi].mean():.1f} → 1990 ortalama {cn90[yapi].mean():.1f}")

hav, _ = oku("havza_id_10m.tif", PR)
h = np.load(os.path.join(PR, "hipsometri.npz"))
alici = h["alici"]
m = len(alici) - 1
hist20 = np.load(os.path.join(PR, "havza_cn_hist.npy"))
hist90 = hist(hav.astype(np.int32), cn90.astype(np.int32), m)
del hav, cn, cn90
np.save(os.path.join(PR, "havza_cn_hist_1990.npy"), hist90)
t = pd.read_csv(os.path.join(PR, "cukurlar_sinifli.csv")).set_index("cukur_id").reindex(np.arange(1, m + 1))
kap = np.zeros(m + 1, np.float32); kap[1:] = t.hacim_m3.values
e20, V20 = esikler(hist20, alici, kap, A)
e90, V90 = esikler(hist90, alici, kap, A)
temel = np.where(t.dolma_esigi_mm.values >= 0, t.dolma_esigi_mm.values, 301)
log(f"2020 eşikleri temel tabloyla aynı: {(e20[1:] == temel).mean() * 100:.2f}%")

d = t[["kategori", "ilce", "mahalle", "il_ici", "hacim_m3"]].copy()
d["esik_2020_mm"] = e20[1:]
d["esik_1990_mm"] = e90[1:]
d["fark_mm"] = d.esik_1990_mm - d.esik_2020_mm
d.reset_index().to_csv(os.path.join(PR, "kentlesme_cukur.csv"), index=False)
k = d[(d.kategori.isin(["kentsel", "alt_gecit"])) & (d.il_ici == 1)]
ozet = {
    "cn_ort_2020": round(float((hist20[1:].sum(0) @ np.arange(55, 101)) / max(hist20[1:].sum(), 1)), 2),
    "cn_ort_1990": round(float((hist90[1:].sum(0) @ np.arange(55, 101)) / max(hist90[1:].sum(), 1)), 2),
    "kentsel_aday": int(len(k)),
    **{f"kentsel_{p}mm_dolan_{y}": int((k[f"esik_{y}_mm"] <= p).sum()) for p in (10, 25, 50) for y in (1990, 2020)},
    "esigi_dusen_kentsel": int((k.fark_mm > 0).sum()),
    "esik_dusus_ortanca_mm_dusenlerde": float(k.loc[k.fark_mm > 0, "fark_mm"].median()),
}
# il geneli yerel akış (yalnız yerel havza akışı, taşma eklenmeden)
for P in (25, 50):
    q = lambda hh: float((hh.astype(np.float64) @ np.array([scs_q(np.array([float(P)]), c)[0] for c in range(55, 101)])).sum() * A / 1000 / 1e6)
    ozet[f"yuzey_akisi_{P}mm_milyon_m3_2020"] = round(q(hist20[1:]), 2)
    ozet[f"yuzey_akisi_{P}mm_milyon_m3_1990"] = round(q(hist90[1:]), 2)
# mahalle düzeyi
g = k.groupby(["ilce", "mahalle"])
mah = pd.DataFrame({
    "aday": g.size(),
    "dolan25_1990": g.apply(lambda x: int((x.esik_1990_mm <= 25).sum())),
    "dolan25_2020": g.apply(lambda x: int((x.esik_2020_mm <= 25).sum())),
    "esik_ortanca_1990": g.esik_1990_mm.median(),
    "esik_ortanca_2020": g.esik_2020_mm.median(),
}).reset_index()
mah["dusus_mm"] = mah.esik_ortanca_1990 - mah.esik_ortanca_2020
mah.to_csv(os.path.join(PR, "kentlesme_mahalle.csv"), index=False)
ozet["en_cok_dusen_mahalleler"] = mah[mah.aday >= 10].sort_values("dusus_mm", ascending=False).head(10)[
    ["ilce", "mahalle", "aday", "esik_ortanca_1990", "esik_ortanca_2020", "dusus_mm"]].to_dict("records")
json.dump(ozet, open(os.path.join(PR, "kentlesme_ozet.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
log(json.dumps(ozet, ensure_ascii=False, default=float)[:1500])
