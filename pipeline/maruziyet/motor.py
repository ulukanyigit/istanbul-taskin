"""Kova motoru — Python referans uygulaması.

Faz 4 çıktılarından (çukur tablosu, hipsometri, havza CN histogramı) bir yağış senaryosu için her çukurdaki su
hacmini ve su kotunu hesaplar. Faz 5'teki tarayıcı motoru (TypeScript) bununla aynı sonucu vermek zorundadır.

Varsayımlar: yağış alan üzerinde düzgün; SCS-CN (Ia = 0,2 S); drenaj kapasitesi yağış şiddetinden düşülür
(toplam yağışta: P_etkin = max(P − drenaj_mm, 0)); akış süresi ihmal; taşan su alıcı çukura anında geçer.
"""
import os

import numpy as np
from numba import njit
from osgeo import gdal

gdal.UseExceptions()
CN_MIN = 55
CN_N = 46  # 55..100


def scs_q(P_mm, cn):
    S = 25400.0 / cn - 254.0
    P_mm = np.asarray(P_mm, dtype=np.float64)
    if S <= 0:
        return P_mm.copy()
    Pe = np.maximum(P_mm - 0.2 * S, 0.0)
    return Pe ** 2 / (Pe + S)


@njit
def _basamak(alici):
    m = len(alici)
    der = np.full(m, -1, np.int32)
    der[0] = 0
    yol = np.empty(m, np.int32)
    for b in range(1, m):
        if der[b] >= 0:
            continue
        k = 0
        c = b
        while c > 0 and der[c] < 0:
            yol[k] = c
            k += 1
            c = alici[c] if alici[c] >= 0 else 0
        base = der[c] if c > 0 else 0
        for j in range(k - 1, -1, -1):
            base += 1
            der[yol[j]] = base
    return der


@njit
def _seviyeler(ofset, kot, hacim, A):
    """hacim[b] m³ su için çukur b'nin su kotu ve ıslak piksel sayısı (hipsometri: artan kotlar)."""
    m = len(hacim)
    sev = np.full(m, np.nan, np.float32)
    islak = np.zeros(m, np.int64)
    for b in range(1, m):
        o0, o1 = ofset[b - 1], ofset[b]
        n = o1 - o0
        if n == 0 or hacim[b] <= 0:
            continue
        V = hacim[b] / A
        cs = 0.0
        k = 0
        h = kot[o0]
        while k < n:
            cs += kot[o0 + k]
            k += 1
            sonraki = kot[o0 + k] if k < n else 1e30
            # k piksel ıslakken seviye h: k*h − cs = V
            h = (V + cs) / k
            if h <= sonraki:
                break
        sev[b] = h
        islak[b] = k
    return sev, islak


class Model:
    def __init__(self, kok):
        P = os.path.join(kok, "data", "processed")
        h = np.load(os.path.join(P, "hipsometri.npz"))
        self.ofset = h["ofset"]
        self.kot = h["kot"]
        self.su_kotu = h["su_kotu"]
        self.alici = h["alici"]
        import pandas as pd
        t = pd.read_csv(os.path.join(P, "cukurlar.csv"))
        self.m = int(t.cukur_id.max())
        self.kap = np.zeros(self.m + 1)
        self.kap[t.cukur_id.values] = t.hacim_m3.values
        ds = gdal.Open(os.path.join(P, "cukur_id_10m.tif"))
        gt = ds.GetGeoTransform()
        self.A = gt[1] * -gt[5]
        ds = None
        self.der = _basamak(self.alici)
        self.sira = np.argsort(-self.der[1:], kind="stable") + 1
        self.cn_hist = self._cn_hist(kok)

    def _cn_hist(self, kok):
        yol = os.path.join(kok, "data", "processed", "havza_cn_hist.npy")
        if os.path.exists(yol):
            return np.load(yol)
        hv = gdal.Open(os.path.join(kok, "data", "processed", "havza_id_10m.tif"))
        cn = gdal.Open(os.path.join(kok, "istanbul_taskin_gee", "cn_10m.tif"))
        nx, ny = hv.RasterXSize, hv.RasterYSize
        hist = np.zeros((self.m + 1) * CN_N, np.int64)
        for y in range(0, ny, 1024):
            h = min(1024, ny - y)
            a = hv.GetRasterBand(1).ReadAsArray(0, y, nx, h).astype(np.int64)
            c = cn.GetRasterBand(1).ReadAsArray(0, y, nx, h).astype(np.int64)
            s = (a > 0) & (c > 0)
            k = a[s] * CN_N + np.clip(c[s] - CN_MIN, 0, CN_N - 1)
            hist += np.bincount(k, minlength=hist.size)
        hist = hist.reshape(self.m + 1, CN_N)
        np.save(yol, hist)
        return hist

    def yerel_akis(self, P_mm, drenaj_mm=0.0):
        """Her çukurun yerel havzasından gelen akış hacmi (m³)."""
        Pe = max(float(P_mm) - float(drenaj_mm), 0.0)
        q = np.array([float(scs_q(Pe, c)) for c in range(CN_MIN, CN_MIN + CN_N)])   # mm
        return self.cn_hist @ q * (self.A / 1000.0)

    def senaryo(self, P_mm, drenaj_mm=0.0):
        """Toplam yağış P_mm için çukur hacimleri, su kotları, ıslak alan ve doluluk."""
        Vin = self.yerel_akis(P_mm, drenaj_mm)
        for b in self.sira:
            r = self.alici[b]
            fazla = Vin[b] - self.kap[b]
            if r > 0 and fazla > 0:
                Vin[r] += fazla
        depo = np.minimum(Vin, self.kap)
        sev, islak = _seviyeler(self.ofset, self.kot, depo.astype(np.float64), self.A)
        return {"hacim": depo, "giris": Vin, "seviye": sev, "islak_px": islak,
                "doluluk": np.where(self.kap > 0, depo / np.maximum(self.kap, 1e-9), 0.0)}
