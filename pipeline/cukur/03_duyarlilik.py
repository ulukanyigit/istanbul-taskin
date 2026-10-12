"""Faz 4b — Duyarlılık ve belirsizlik: "ilk 100" listesi koşullandırma parametrelerine ve DEM hatasına ne kadar dayanıklı?

1) Duyarlılık: koşullandırılmış DEM'deki her müdahale (bina yükseltme, yol alçaltma, dere oyma, alt geçit) kendi
   maskesinde ölçeklenir (z = FABDEM + fark × k) ve çukur analizi yeniden yapılır. Varyant başına 2 senaryo.
2) Belirsizlik (Monte Carlo): DEM'e uzamsal ilişkili hata eklenir (σ ve ilişki uzunluğu parametre), N tekrar.

Her koşuda: Priority-Flood → çukurlar (aynı filtreler) → dolma–taşma ağacı → yerel havza CN histogramı → dolma
eşiği (0–300 mm). Temel çözümdeki her çukur, varyanttaki en çok örtüşen çukurla eşlenir; temel "kentsel, il içi"
adayları varyant eşiklerine göre yeniden sıralanır. Ölçüler: ilk 100'ün korunma oranı, Spearman ρ, kaybolan çukur.

Çalıştırma: python 03_duyarlilik.py <proje_kökü> [duyarlilik|belirsizlik|hepsi] [N_mc]
Çıktılar (data/processed): duyarlilik.csv, belirsizlik_cukur.csv, duyarlilik_ozet.json
"""
import importlib.util
import json
import os
import sys
import time
import types

import numpy as np
import pandas as pd
import rasterio
from numba import njit
from scipy import ndimage
from scipy.stats import spearmanr

KOK = sys.argv[1]
MOD = sys.argv[2] if len(sys.argv) > 2 else "hepsi"
N_MC = int(sys.argv[3]) if len(sys.argv) > 3 else 8
INT, PR, GEE = (os.path.join(KOK, *p) for p in (("data", "interim"), ("data", "processed"), ("istanbul_taskin_gee",)))
MC_SIGMA_M, MC_KORELASYON_PX = 0.5, 3.0          # DEM hatası: σ 0,5 m, ~30 m ilişki uzunluğu (Gauss süzgeci)
ESLESME_MIN = 0.3                                  # temel çukurun en az %30'u varyant çukurunda ise "korunmuş"
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:6.0f} sn] {m}", flush=True)


# 01_cukur_analizi.py'nin numba işlevlerini kullan (GDAL bağlantısı yoksa boş modülle yükle)
for ad in ("osgeo", "osgeo.gdal", "osgeo.ogr", "osgeo.osr"):
    if ad not in sys.modules:
        try:
            __import__(ad)
        except ImportError:
            m = types.ModuleType(ad)
            m.UseExceptions = lambda: None
            sys.modules[ad] = m
            if ad != "osgeo":
                setattr(sys.modules["osgeo"], ad.split(".")[1], m)
sp = importlib.util.spec_from_file_location("ca", os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_cukur_analizi.py"))
sys.argv, _argv = [sys.argv[0], KOK], sys.argv
ca = importlib.util.module_from_spec(sp)
sp.loader.exec_module(ca)
sys.argv = _argv
P = ca.P


def oku(yol, dtype=None):
    with rasterio.open(yol) as d:
        a = d.read(1)
        return (a.astype(dtype) if dtype is not None else a), d.transform


@njit
def cn_hist_say(hav, cn, m):
    h = np.zeros((m + 1, 46), np.int64)
    ny, nx = hav.shape
    for y in range(ny):
        for x in range(nx):
            b = hav[y, x]
            c = cn[y, x]
            if b > 0 and c > 0:
                k = min(max(c - 55, 0), 45)
                h[b, k] += 1
    return h


def analiz(dem, valid, cn, piksel_m2):
    """Bir DEM için çukur etiketleri ve dolma eşikleri (01_cukur_analizi.py ile aynı adımlar, dosya yazmadan)."""
    ny, nx = dem.shape
    filled, _, _, _ = ca.priority_flood(dem, valid, np.zeros((1, 1), np.int32), False, 0)
    filled = filled.reshape(ny, nx)
    maske = ((filled - dem) > P["derinlik_esik_m"]) & valid
    labels = np.empty((ny, nx), np.int32)
    nlab = ndimage.label(maske, structure=np.ones((3, 3), bool), output=labels)
    del maske
    alan, hacim, maksd, _ = ca.cukur_istatistik(dem, filled, labels, nlab)
    del filled
    alan_m2, hacim_m3 = alan * piksel_m2, hacim * piksel_m2
    tut = (maksd >= P["min_maks_derinlik_m"]) & (alan_m2 >= P["min_alan_m2"]) & (hacim_m3 >= P["min_hacim_m3"])
    tut[0] = False
    harita = np.zeros(nlab + 1, np.int32)
    harita[tut] = np.arange(1, tut.sum() + 1, dtype=np.int32)
    ca.etiket_esle(labels, harita)
    m = int(tut.sum())
    hacim_m3 = np.concatenate([[0], hacim_m3[tut]])
    _, havza, alici, _ = ca.priority_flood(dem, valid, labels, True, m)
    havza = havza.reshape(ny, nx)
    cn_hist = cn_hist_say(havza, cn, m)
    del havza
    Pg = np.arange(0, P["yagis_mm_maks"] + 1, dtype=np.float64)
    Qtab = np.stack([ca.scs_q(Pg, c) for c in np.arange(55, 101, dtype=np.float64)])
    Vin = (cn_hist.astype(np.float64) @ Qtab * (piksel_m2 / 1000.0)).astype(np.float32)
    der = ca.basamak_derinligi(alici)
    cap = hacim_m3.astype(np.float32)
    for b in np.argsort(-der[1:], kind="stable") + 1:
        r = alici[b]
        if r > 0:
            Vin[r] += np.maximum(Vin[b] - cap[b], 0)
    dolu = Vin >= cap[:, None]
    esik = np.where(dolu.any(axis=1), dolu.argmax(axis=1), P["yagis_mm_maks"] + 1).astype(np.int32)
    esik[0] = P["yagis_mm_maks"] + 1
    return labels, m, esik


def esle(labels, temel_idx, temel_id, m_temel):
    """Temel çukur pikselleri → varyant etiketi; her temel çukur için en çok örtüşen varyant çukuru ve örtüşme oranı."""
    v = labels.ravel()[temel_idx].astype(np.int64)
    s = v > 0
    anahtar = temel_id[s].astype(np.int64) * (1 << 32) + v[s]
    u, say = np.unique(anahtar, return_counts=True)
    tb, vb = (u >> 32).astype(np.int64), (u & 0xFFFFFFFF).astype(np.int64)
    o = np.lexsort((-say, tb))
    tb, vb, say = tb[o], vb[o], say[o]
    ilk = np.concatenate([[True], tb[1:] != tb[:-1]])
    es = np.zeros(m_temel + 1, np.int64)
    oran = np.zeros(m_temel + 1)
    npx = np.bincount(temel_id, minlength=m_temel + 1)
    es[tb[ilk]] = vb[ilk]
    oran[tb[ilk]] = say[ilk] / np.maximum(npx[tb[ilk]], 1)
    return es, oran


def main():
    # bellek: temel DEM tutulmaz, her koşuda diskten yeniden okunur
    DEM_YOL = os.path.join(INT, "dem_kosullu_10m.tif")
    dem0, tr = oku(DEM_YOL, np.float32)
    piksel_m2 = tr.a * -tr.e
    valid = np.isfinite(dem0) & (dem0 != ca.NODATA)
    del dem0
    cn, _ = oku(os.path.join(GEE, "cn_10m.tif"), np.int16)
    lab0, _ = oku(os.path.join(PR, "cukur_id_10m.tif"))
    temel_idx = np.flatnonzero(lab0.ravel() > 0)
    temel_id = lab0.ravel()[temel_idx].astype(np.int64)
    del lab0
    t = pd.read_csv(os.path.join(PR, "cukurlar_sinifli.csv")).set_index("cukur_id")
    m0 = int(t.index.max())
    esik0 = np.full(m0 + 1, 301, np.int64)
    esik0[t.index.values] = np.where(t.dolma_esigi_mm.values >= 0, t.dolma_esigi_mm.values, 301)
    hacim0 = np.zeros(m0 + 1); hacim0[t.index.values] = t.hacim_m3.values
    aday = t.index[(t.kategori == "kentsel") & (t.il_ici.fillna(0) == 1)].values

    def ilk100(e):
        o = np.lexsort((-hacim0[aday], e[aday]))
        return set(aday[o[:100]].tolist())

    temel100 = ilk100(esik0)
    log(f"temel: {m0:,} çukur, {len(aday):,} kentsel aday")

    sonuc = []

    def degerlendir(ad, dem):
        labels, m, esik = analiz(dem, valid, cn, piksel_m2)
        es, oran = esle(labels, temel_idx, temel_id, m0)
        del labels
        korunan = oran >= ESLESME_MIN
        e_v = np.where(korunan, esik[es], 301)
        v100 = ilk100(e_v)
        a = aday
        rho = spearmanr(esik0[a], e_v[a]).correlation
        fark = np.abs(e_v[a] - esik0[a])[korunan[a]]
        r = {"senaryo": ad, "cukur_sayisi": m, "ilk100_korunan_%": len(temel100 & v100),
             "spearman_rho": round(float(rho), 3), "kaybolan_aday_%": round(100 * (1 - korunan[a].mean()), 1),
             "esik_fark_ortanca_mm": float(np.median(fark)) if len(fark) else None,
             "esik_fark_p90_mm": float(np.percentile(fark, 90)) if len(fark) else None,
             "25mm_dolan_aday": int((e_v[a] <= 25).sum()), "25mm_dolan_aday_temel": int((esik0[a] <= 25).sum())}
        log(f"{ad}: {r}")
        sonuc.append(r)
        return korunan, e_v

    if MOD in ("duyarlilik", "hepsi"):
        degerlendir("temel (kontrol)", oku(DEM_YOL, np.float32)[0])
        fark, _ = oku(os.path.join(INT, "dem_fark_10m.tif"), np.float32)
        fark = np.nan_to_num(fark).astype(np.float16)
        islem, _ = oku(os.path.join(INT, "maske_islem_10m.tif"), np.uint8)
        for ad, bit, k in [("bina +3 m (temel +5)", 2, 0.6), ("bina +8 m", 2, 1.6),
                           ("yol −0,15 m (temel −0,30)", 4, 0.5), ("yol −0,50 m", 4, 5 / 3),
                           ("dere oyma ×0,5", 8, 0.5), ("dere oyma ×1,5", 8, 1.5),
                           ("alt geçit ×0,6 (3 m)", 32, 0.6), ("alt geçit ×1,4 (7 m)", 32, 1.4)]:
            s = (islem & bit) > 0
            dem = oku(DEM_YOL, np.float32)[0]
            dem[s] += fark[s].astype(np.float32) * (k - 1)     # z = FABDEM + fark·k
            del s
            degerlendir(ad, dem)
            del dem
        del fark, islem
        pd.DataFrame(sonuc).to_csv(os.path.join(PR, "duyarlilik.csv"), index=False)

    if MOD in ("belirsizlik", "hepsi"):
        rng = np.random.default_rng(42)
        kor = np.zeros(m0 + 1)
        esikler = []
        ilk100_say = {}
        for i in range(N_MC):
            g = rng.standard_normal(valid.shape, dtype=np.float32)
            ndimage.gaussian_filter(g, MC_KORELASYON_PX, output=g)
            g *= MC_SIGMA_M / g.std()
            g[~valid] = 0
            dem = oku(DEM_YOL, np.float32)[0]
            dem += g
            del g
            k, e_v = degerlendir(f"DEM hatası #{i + 1}", dem)
            del dem
            kor += k
            esikler.append(e_v.astype(np.int16))
            for b in ilk100(e_v):
                ilk100_say[b] = ilk100_say.get(b, 0) + 1
        E = np.stack(esikler)
        bc = pd.DataFrame({"cukur_id": np.arange(1, m0 + 1), "cukur_olasiligi": (kor / N_MC)[1:].round(2),
                           "esik_p10_mm": np.percentile(E, 10, axis=0)[1:].astype(int),
                           "esik_p50_mm": np.percentile(E, 50, axis=0)[1:].astype(int),
                           "esik_p90_mm": np.percentile(E, 90, axis=0)[1:].astype(int)})
        bc["ilk100_olasiligi"] = bc.cukur_id.map(lambda b: ilk100_say.get(b, 0) / N_MC).round(2)
        bc.to_csv(os.path.join(PR, "belirsizlik_cukur.csv"), index=False)
        pd.DataFrame(sonuc).to_csv(os.path.join(PR, "duyarlilik.csv"), index=False)
        t100 = sorted(temel100)
        ozet_mc = {"N": N_MC, "sigma_m": MC_SIGMA_M, "iliski_px": MC_KORELASYON_PX,
                   "ilk100_ortalama_olasilik": float(bc.set_index("cukur_id").loc[t100, "ilk100_olasiligi"].mean()),
                   "ilk100_cukur_olasiligi_ortanca": float(bc.set_index("cukur_id").loc[t100, "cukur_olasiligi"].median()),
                   "aday_cukur_olasiligi_ortanca": float(bc.set_index("cukur_id").loc[aday, "cukur_olasiligi"].median())}
        json.dump({"senaryolar": sonuc, "monte_carlo": ozet_mc}, open(os.path.join(PR, "duyarlilik_ozet.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    log("bitti")


if __name__ == "__main__":
    main()
