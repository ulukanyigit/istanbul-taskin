"""Faz 4c — Yol alçaltma ve DEM hatasına duyarlılık; tek tek çukurlar ile mahalle ve ilçe düzeyi.

03_duyarlilik.py tek tek çukurların sırasının yol alçaltmaya (−0,15 / −0,50 m; temel −0,30 m) çok duyarlı olduğunu
gösterdi. Bu betik aynı varyantları yeniden koşar ve sonucu mahalle / ilçe düzeyine toplar: her mahallede il içi
kentsel çukurlardan 25 ve 50 mm'de dolanların toplam hacmi. Sıcak nokta mahalleleri parametreye dayanıklı mı?

Çalıştırma: python 04_duyarlilik_mahalle.py <proje_kökü>
Çıktılar (data/processed): duyarlilik_mahalle.json, belirsizlik_cukur.csv, duyarlilik_ozet.json
"""
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage
from scipy.stats import spearmanr

KOK = sys.argv[1]
INT, PR = os.path.join(KOK, "data", "interim"), os.path.join(KOK, "data", "processed")
sp = importlib.util.spec_from_file_location("dy", os.path.join(os.path.dirname(os.path.abspath(__file__)), "03_duyarlilik.py"))
_a = sys.argv; sys.argv = [_a[0], KOK, "yok"]
dy = importlib.util.module_from_spec(sp); sp.loader.exec_module(dy)
sys.argv = _a


def oku(ad, d=INT, dt=None):
    with rasterio.open(os.path.join(d, ad)) as r:
        a = r.read(1)
        return (a.astype(dt) if dt is not None else a), r.transform


DEM = "dem_kosullu_10m.tif"
dem, tr = oku(DEM, dt=np.float32)
A = tr.a * -tr.e
valid = np.isfinite(dem) & (dem != -9999.0)
del dem
cn, _ = oku("cn_10m.tif", os.path.join(KOK, "istanbul_taskin_gee"), np.int16)
mah, _ = oku("mahalle_id_10m.tif", PR)
lab0, _ = oku("cukur_id_10m.tif", PR)
idx = np.flatnonzero(lab0.ravel() > 0)
tid = lab0.ravel()[idx].astype(np.int64)
del lab0
t = pd.read_csv(os.path.join(PR, "cukurlar_sinifli.csv")).set_index("cukur_id")
m0 = int(t.index.max())
aday = t.index[(t.kategori == "kentsel") & (t.il_ici.fillna(0) == 1)].values
# çukurun mahallesi: en derin pikselindeki mahalle kimliği yerine çoğunluk
mah_b = np.zeros(m0 + 1, np.int64)
mv = mah.ravel()[idx]
u, say = np.unique(tid * 100000 + mv, return_counts=True)
bb, mm = u // 100000, u % 100000
o = np.lexsort((-say, bb))
ilk = np.concatenate([[True], bb[o][1:] != bb[o][:-1]])
mah_b[bb[o][ilk]] = mm[o][ilk]
del mah, mv
kg = pd.read_csv(os.path.join(PR, "mahalle_karnesi.csv")).set_index("mahalle_fid")
hacim = np.zeros(m0 + 1); hacim[t.index.values] = t.hacim_m3.values
e0 = np.full(m0 + 1, 301); e0[t.index.values] = np.where(t.dolma_esigi_mm >= 0, t.dolma_esigi_mm, 301)


def topla(e):
    d = pd.DataFrame({"mah": mah_b[aday], "e": e[aday], "v": hacim[aday]})
    d = d[d.mah.isin(kg.index[kg.istanbul == 1])]
    g = d.groupby("mah")
    return pd.DataFrame({"v25": g.apply(lambda x: x.v[x.e <= 25].sum()), "v50": g.apply(lambda x: x.v[x.e <= 50].sum())})


temel = topla(e0)
ilce = kg.ilce
sonuc = []
fark, _ = oku("dem_fark_10m.tif", dt=np.float32)
fark = np.nan_to_num(fark).astype(np.float16)
islem, _ = oku("maske_islem_10m.tif", dt=np.uint8)
SIGMA, N_MC = 0.25, 4
rng = np.random.default_rng(7)
kor_say = np.zeros(m0 + 1); E = []; ilk100_say = {}


def ilk100(e):
    o = np.lexsort((-hacim[aday], e[aday]))
    return set(aday[o[:100]].tolist())


temel100 = ilk100(e0)
senaryolar = [("yol −0,15 m", "yol", 0.5), ("yol −0,50 m", "yol", 5 / 3)] + [(f"DEM hatası σ={SIGMA} m #{i + 1}", "mc", i) for i in range(N_MC)]
for ad, tur, k in senaryolar:
    dem, _ = oku(DEM, dt=np.float32)
    if tur == "yol":
        s = (islem & 4) > 0
        dem[s] += fark[s].astype(np.float32) * (k - 1)
        del s
    else:
        g = rng.standard_normal(valid.shape, dtype=np.float32)
        ndimage.gaussian_filter(g, dy.MC_KORELASYON_PX, output=g)
        g *= SIGMA / g.std()
        g[~valid] = 0
        dem += g
        del g
    labels, m, esik = dy.analiz(dem, valid, cn, A)
    del dem
    es, oran = dy.esle(labels, idx, tid, m0)
    del labels
    korunan = oran >= dy.ESLESME_MIN
    ev = np.where(korunan, esik[es], 301)
    v100 = ilk100(ev)
    r = {"senaryo": ad, "cukur_sayisi": m, "ilk100_korunan_%": len(temel100 & v100),
         "spearman_rho": round(float(spearmanr(e0[aday], ev[aday]).correlation), 3),
         "kaybolan_aday_%": round(100 * (1 - korunan[aday].mean()), 1)}
    v = topla(ev).reindex(temel.index).fillna(0)
    for c in ("v25", "v50"):
        r[f"mahalle_{c}_spearman"] = round(float(spearmanr(temel[c], v[c]).correlation), 3)
        t50 = set(temel[c].nlargest(50).index); v50 = set(v[c].nlargest(50).index)
        r[f"mahalle_{c}_ilk50_ortak"] = len(t50 & v50)
        ti = temel[c].groupby(ilce.reindex(temel.index)).sum(); vi = v[c].groupby(ilce.reindex(v.index)).sum()
        r[f"ilce_{c}_spearman"] = round(float(spearmanr(ti, vi.reindex(ti.index).fillna(0)).correlation), 3)
        r[f"ilce_{c}_ilk10_ortak"] = len(set(ti.nlargest(10).index) & set(vi.nlargest(10).index))
    print(r, flush=True)
    sonuc.append(r)
    if tur == "mc":
        kor_say += korunan; E.append(ev.astype(np.int16))
        for b in v100:
            ilk100_say[b] = ilk100_say.get(b, 0) + 1
json.dump(sonuc, open(os.path.join(PR, "duyarlilik_mahalle.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
E = np.stack(E)
bc = pd.DataFrame({"cukur_id": np.arange(1, m0 + 1), "cukur_olasiligi": (kor_say / N_MC)[1:].round(2),
                   "esik_p10_mm": np.percentile(E, 10, axis=0)[1:].astype(int),
                   "esik_p50_mm": np.percentile(E, 50, axis=0)[1:].astype(int),
                   "esik_p90_mm": np.percentile(E, 90, axis=0)[1:].astype(int)})
bc["ilk100_olasiligi"] = bc.cukur_id.map(lambda b: ilk100_say.get(b, 0) / N_MC).round(2)
bc.to_csv(os.path.join(PR, "belirsizlik_cukur.csv"), index=False)
t100 = sorted(temel100)
b2 = bc.set_index("cukur_id")
var = pd.read_csv(os.path.join(PR, "duyarlilik.csv")).to_dict("records")
ozet = {"senaryolar": var, "mahalle_duzeyi": sonuc,
        "monte_carlo": {"N": N_MC, "sigma_m": SIGMA, "iliski_px": dy.MC_KORELASYON_PX,
                        "ilk100_ortalama_olasilik": float(b2.loc[t100, "ilk100_olasiligi"].mean()),
                        "ilk100_cukur_olasiligi_ortanca": float(b2.loc[t100, "cukur_olasiligi"].median()),
                        "aday_cukur_olasiligi_ortanca": float(b2.loc[aday, "cukur_olasiligi"].median()),
                        "not": "σ=0,5 m ile tek koşu: ilk 100'ün 9'u kaldı, ρ=0,23"}}
json.dump(ozet, open(os.path.join(PR, "duyarlilik_ozet.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
print("bitti", ozet["monte_carlo"], flush=True)
