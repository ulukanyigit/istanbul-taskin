"""Faz 4 — Çukur (bluespot) ve dolma–taşma analizi.

Yöntem (Balstrøm & Crawford 2018 "bluespot" yaklaşımı, Barnes 2014 Priority-Flood):
 1. Priority-Flood ile koşullu DEM doldurulur; doldurulan her bağlantılı bölge bir çukurdur.
 2. Küçük/sığ çukurlar elenir (gürültü); süzülen çukurların suyu mansaba geçer.
 3. Aynı Priority-Flood sırası ikinci kez yürütülür: her pikselin suyunun ilk girdiği çukur (yerel havza) ve
    her çukurun taşma noktası ile taştığında suyu alan çukur (alıcı) bulunur → dolma–taşma ağacı.
 4. SCS-CN ile yerel havzanın akış hacmi Q(P) hesaplanır; memba çukurlarından taşan su eklenerek her çukurun
    dolduğu yağış (dolma eşiği, mm) bulunur. Senaryo: drenaj tamamen devre dışı, yağış düzgün dağılımlı,
    akış süresi ihmal (anlık yönlendirme).

Çalıştırma (OSGeo4W Python; numpy, scipy, numba, GDAL):
    python 01_cukur_analizi.py <proje_kökü>
Girdi : data/interim/dem_kosullu_10m.tif, maske_islem_10m.tif, altgecit_id_10m.tif, degisen_topo_10m.tif
        istanbul_taskin_gee/cn_10m.tif, worldcover_10m.tif
Çıktı : data/processed/cukur_id_10m.tif, havza_id_10m.tif, dolma_esigi_mm_10m.tif
        data/processed/cukurlar.gpkg (katman: cukurlar), cukurlar.csv, hipsometri.npz, cukur_parametreler.json
"""
import json
import os
import sys
import time

import numpy as np
from numba import njit
from osgeo import gdal, ogr, osr
from scipy import ndimage

gdal.UseExceptions()
KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INT = os.path.join(KOK, "data", "interim")
GEE = os.path.join(KOK, "istanbul_taskin_gee")
OUT = os.path.join(KOK, "data", "processed")
os.makedirs(OUT, exist_ok=True)
NODATA = -9999.0

P = {
    "derinlik_esik_m": 0.01,      # doldurma − DEM bundan büyükse çukur pikseli
    "min_maks_derinlik_m": 0.10,  # daha sığ çukurlar gürültü sayılır
    "min_alan_m2": 300,           # 3 pikselden küçük çukurlar elenir
    "min_hacim_m3": 20,
    "yagis_mm_maks": 300,         # dolma eşiği bu değere kadar 1 mm adımla aranır
    "avlu_bina_orani": 0.8,       # çevresinin bu kadarı bina olan küçük çukur = bina avlusu
    "avlu_maks_alan_m2": 3000,
    "su_orani": 0.5,              # alanının yarısı WorldCover suyu olan çukur = göl/baraj
    "degisen_orani": 0.2,         # alanının %20'si "topografyası değişmiş olabilir" = güvenilmez
}
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:6.0f} sn] {m}", flush=True)


# ------------------------------------------------------------------ Priority-Flood (numba)
@njit
def _heap_push(hk, hs, hi, n, key, seq, idx):
    i = n
    hk[i], hs[i], hi[i] = key, seq, idx
    while i > 0:
        p = (i - 1) >> 1
        if hk[p] < hk[i] or (hk[p] == hk[i] and hs[p] < hs[i]):
            break
        hk[p], hk[i] = hk[i], hk[p]
        hs[p], hs[i] = hs[i], hs[p]
        hi[p], hi[i] = hi[i], hi[p]
        i = p
    return n + 1


@njit
def _heap_pop(hk, hs, hi, n):
    key, idx = hk[0], hi[0]
    n -= 1
    hk[0], hs[0], hi[0] = hk[n], hs[n], hi[n]
    i = 0
    while True:
        l, r, m = 2 * i + 1, 2 * i + 2, i
        if l < n and (hk[l] < hk[m] or (hk[l] == hk[m] and hs[l] < hs[m])):
            m = l
        if r < n and (hk[r] < hk[m] or (hk[r] == hk[m] and hs[r] < hs[m])):
            m = r
        if m == i:
            break
        hk[m], hk[i] = hk[i], hk[m]
        hs[m], hs[i] = hs[i], hs[m]
        hi[m], hi[i] = hi[i], hi[m]
        i = m
    return key, idx, n


@njit
def priority_flood(dem, valid, labels, rota, nlab):
    """rota=False: doldurulmuş yüzeyi döndürür.
    rota=True : labels ile (çukur no) ilk girilen çukuru (havza), çukurların alıcısını ve taşma pikselini döndürür."""
    ny, nx = dem.shape
    N = ny * nx
    d = dem.ravel()
    v = valid.ravel()
    lab = labels.ravel()
    closed = np.zeros(N, np.bool_)
    filled = np.empty(N if not rota else 1, np.float32)
    havza = np.zeros(N if rota else 1, np.int32)
    alici = np.full(nlab + 1, -1, np.int32)
    tasma = np.full(nlab + 1, -1, np.int64)
    cap = 1 << 22
    hk = np.empty(cap, np.float32); hs = np.empty(cap, np.int64); hi = np.empty(cap, np.int64)
    qcap = 1 << 22
    qi = np.empty(qcap, np.int64); ql = np.empty(qcap, np.float32)
    qh, qt = 0, 0
    n, seq = 0, 0
    dy = np.array([-1, -1, -1, 0, 0, 1, 1, 1]); dx = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    # başlangıç: kenardaki ya da nodata komşusu olan geçerli pikseller (çıkış)
    for y in range(ny):
        for x in range(nx):
            c = y * nx + x
            if not v[c]:
                continue
            kenar = y == 0 or x == 0 or y == ny - 1 or x == nx - 1
            if not kenar:
                for k in range(8):
                    if not v[(y + dy[k]) * nx + x + dx[k]]:
                        kenar = True
                        break
            if kenar:
                closed[c] = True
                if not rota:
                    filled[c] = d[c]
                else:
                    if lab[c] > 0:
                        havza[c] = lab[c]
                        if tasma[lab[c]] < 0:
                            tasma[lab[c]] = c
                            alici[lab[c]] = 0
                if n == cap:
                    cap *= 2
                    hk2 = np.empty(cap, np.float32); hs2 = np.empty(cap, np.int64); hi2 = np.empty(cap, np.int64)
                    hk2[:n] = hk[:n]; hs2[:n] = hs[:n]; hi2[:n] = hi[:n]
                    hk, hs, hi = hk2, hs2, hi2
                n = _heap_push(hk, hs, hi, n, d[c], seq, c)
                seq += 1
    while n > 0 or qh != qt:
        if qh != qt:
            c = qi[qh]; lev = ql[qh]
            qh = (qh + 1) % qcap
        else:
            lev, c, n = _heap_pop(hk, hs, hi, n)
        y = c // nx; x = c - y * nx
        for k in range(8):
            yy = y + dy[k]; xx = x + dx[k]
            if yy < 0 or xx < 0 or yy >= ny or xx >= nx:
                continue
            m = yy * nx + xx
            if closed[m] or not v[m]:
                continue
            closed[m] = True
            if rota:
                if lab[m] > 0:
                    havza[m] = lab[m]
                    if tasma[lab[m]] < 0:          # çukura ilk girilen piksel = taşma noktası
                        tasma[lab[m]] = m
                        alici[lab[m]] = havza[c]
                else:
                    havza[m] = havza[c]
            if d[m] <= lev:
                if not rota:
                    filled[m] = lev
                if (qt + 1) % qcap == qh:          # kuyruğu büyüt
                    sz = (qt - qh) % qcap
                    qi2 = np.empty(qcap * 2, np.int64); ql2 = np.empty(qcap * 2, np.float32)
                    for j in range(sz):
                        qi2[j] = qi[(qh + j) % qcap]; ql2[j] = ql[(qh + j) % qcap]
                    qi, ql, qcap, qh, qt = qi2, ql2, qcap * 2, 0, sz
                qi[qt] = m; ql[qt] = lev
                qt = (qt + 1) % qcap
            else:
                if not rota:
                    filled[m] = d[m]
                if n == cap:
                    cap *= 2
                    hk2 = np.empty(cap, np.float32); hs2 = np.empty(cap, np.int64); hi2 = np.empty(cap, np.int64)
                    hk2[:n] = hk[:n]; hs2[:n] = hs[:n]; hi2[:n] = hi[:n]
                    hk, hs, hi = hk2, hs2, hi2
                n = _heap_push(hk, hs, hi, n, d[m], seq, m)
                seq += 1
    return filled, havza, alici, tasma


@njit
def cukur_istatistik(dem, filled, labels, nlab):
    ny, nx = dem.shape
    alan = np.zeros(nlab + 1, np.int64)
    hacim = np.zeros(nlab + 1, np.float64)
    maksd = np.zeros(nlab + 1, np.float32)
    seviye = np.zeros(nlab + 1, np.float32)
    for y in range(ny):
        for x in range(nx):
            b = labels[y, x]
            if b > 0:
                dd = filled[y, x] - dem[y, x]
                alan[b] += 1
                hacim[b] += dd
                if dd > maksd[b]:
                    maksd[b] = dd
                seviye[b] = filled[y, x]
    return alan, hacim, maksd, seviye


@njit
def etiket_esle(labels, harita):
    ny, nx = labels.shape
    for y in range(ny):
        for x in range(nx):
            if labels[y, x] > 0:
                labels[y, x] = harita[labels[y, x]]


@njit
def blok_say(lab, hav, cn, islem, ag, deg, wc, y_ic0, y_ic1, nlab, cn_hist, n_yol, n_ag, ag_id, n_deg, n_su, kenar_top, kenar_bina):
    """lab/hav/... blok dizileri (üst-alt 1 satır pay ile). y_ic0..y_ic1 blok içi sayılacak satırlar."""
    ny, nx = lab.shape
    for y in range(y_ic0, y_ic1):
        for x in range(nx):
            h = hav[y, x]
            c = cn[y, x]
            if h > 0 and c > 0:
                k = min(max(c - 55, 0), 45)
                cn_hist[h, k] += 1
            b = lab[y, x]
            if b <= 0:
                continue
            if (islem[y, x] & 4) > 0:
                n_yol[b] += 1
            if ag[y, x] > 0:
                n_ag[b] += 1
                ag_id[b] = ag[y, x]
            if deg[y, x] > 0:
                n_deg[b] += 1
            if wc[y, x] == 80:
                n_su[b] += 1
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dy == 0 and dx == 0:
                        continue
                    yy, xx = y + dy, x + dx
                    if yy < 0 or xx < 0 or yy >= ny or xx >= nx:
                        continue
                    if lab[yy, xx] != b:
                        kenar_top[b] += 1
                        if (islem[yy, xx] & 2) > 0:
                            kenar_bina[b] += 1


@njit
def basamak_derinligi(alici):
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
            yol[k] = c; k += 1
            c = alici[c] if alici[c] >= 0 else 0
        base = der[c] if c > 0 else 0
        for j in range(k - 1, -1, -1):
            base += 1
            der[yol[j]] = base
    return der


def scs_q(P_mm, cn):
    """SCS-CN yüzey akışı (mm). CN 100 → Q = P."""
    S = 25400.0 / cn - 254.0
    if S <= 0:
        return np.asarray(P_mm, dtype=np.float64).copy()
    Ia = 0.2 * S
    Pe = np.maximum(P_mm - Ia, 0.0)
    return Pe ** 2 / (Pe + S)


def raster_yaz(yol, dizi, dtype, nodata, gt, wkt):
    ds = gdal.GetDriverByName("GTiff").Create(yol, dizi.shape[1], dizi.shape[0], 1, dtype,
                                              options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER", "NUM_THREADS=ALL_CPUS"])
    ds.SetGeoTransform(gt); ds.SetProjection(wkt)
    b = ds.GetRasterBand(1); b.SetNoDataValue(nodata)
    for y in range(0, dizi.shape[0], 1024):
        b.WriteArray(dizi[y:y + 1024], 0, y)
    ds = None


def main():
    src = gdal.Open(os.path.join(INT, "dem_kosullu_10m.tif"))
    gt, wkt = src.GetGeoTransform(), src.GetProjection()
    ny, nx = src.RasterYSize, src.RasterXSize
    piksel_m2 = gt[1] * -gt[5]
    dem = src.GetRasterBand(1).ReadAsArray().astype(np.float32)
    src = None
    valid = np.isfinite(dem) & (dem != NODATA)
    log(f"DEM okundu: {nx}×{ny}, geçerli piksel {valid.sum():,}")

    # 1) doldurma
    filled, _, _, _ = priority_flood(dem, valid, np.zeros((1, 1), np.int32), False, 0)
    filled = filled.reshape(ny, nx)
    filled[~valid] = NODATA
    log("Priority-Flood doldurma tamam")

    maske = (filled - dem) > P["derinlik_esik_m"]
    maske &= valid
    labels = np.empty((ny, nx), np.int32)
    nlab = ndimage.label(maske, structure=np.ones((3, 3), bool), output=labels)
    del maske
    alan, hacim, maksd, seviye = cukur_istatistik(dem, filled, labels, nlab)
    del filled
    alan_m2 = alan * piksel_m2
    hacim_m3 = hacim * piksel_m2
    tut = (maksd >= P["min_maks_derinlik_m"]) & (alan_m2 >= P["min_alan_m2"]) & (hacim_m3 >= P["min_hacim_m3"])
    tut[0] = False
    harita = np.zeros(nlab + 1, np.int32)
    harita[tut] = np.arange(1, tut.sum() + 1, dtype=np.int32)
    etiket_esle(labels, harita)
    m = int(tut.sum())
    alan_m2, hacim_m3, maksd, seviye = (np.concatenate([[0], a[tut]]) for a in (alan_m2, hacim_m3, maksd, seviye))
    log(f"Çukur: ham {nlab:,} → süzülmüş {m:,}")

    # 2) yönlendirme: havza, alıcı, taşma noktası
    _, havza, alici, tasma = priority_flood(dem, valid, labels, True, m)
    havza = havza.reshape(ny, nx)
    log("Dolma–taşma ağacı tamam")

    # hipsometri: her çukurun piksel kotları (artan) → hacim-seviye eğrisi
    idx = np.flatnonzero(labels.ravel() > 0)
    lb = labels.ravel()[idx]
    sira = np.lexsort((dem.ravel()[idx], lb))
    hip_kot = dem.ravel()[idx][sira].astype(np.float32)
    hip_ofset = np.concatenate([[0], np.cumsum(np.bincount(lb, minlength=m + 1)[1:])]).astype(np.int64)
    del idx, lb, sira
    del dem, valid

    raster_yaz(os.path.join(OUT, "cukur_id_10m.tif"), labels, gdal.GDT_Int32, 0, gt, wkt)
    raster_yaz(os.path.join(OUT, "havza_id_10m.tif"), havza, gdal.GDT_Int32, 0, gt, wkt)
    log("cukur_id ve havza_id yazıldı")

    # 3) havza CN histogramı ve çukur içerik bayrakları (satır blokları)
    cn_hist = np.zeros((m + 1, 46), np.int64)
    n_yol = np.zeros(m + 1, np.int64); n_ag = np.zeros(m + 1, np.int64); ag_id = np.zeros(m + 1, np.int32)
    n_deg = np.zeros(m + 1, np.int64); n_su = np.zeros(m + 1, np.int64)
    kenar_top = np.zeros(m + 1, np.int64); kenar_bina = np.zeros(m + 1, np.int64)
    ds = {k: gdal.Open(p) for k, p in {
        "cn": os.path.join(GEE, "cn_10m.tif"), "islem": os.path.join(INT, "maske_islem_10m.tif"),
        "ag": os.path.join(INT, "altgecit_id_10m.tif"), "deg": os.path.join(INT, "degisen_topo_10m.tif"),
        "wc": os.path.join(GEE, "worldcover_10m.tif")}.items()}
    B = 1024
    for y0 in range(0, ny, B):
        ya, yb = max(0, y0 - 1), min(ny, y0 + B + 1)
        oku = lambda k: ds[k].GetRasterBand(1).ReadAsArray(0, ya, nx, yb - ya)
        blok_say(labels[ya:yb], havza[ya:yb], oku("cn").astype(np.int32), oku("islem").astype(np.uint8),
                 oku("ag").astype(np.int32), oku("deg").astype(np.uint8), oku("wc").astype(np.uint8),
                 y0 - ya, min(y0 + B, ny) - ya, m, cn_hist, n_yol, n_ag, ag_id, n_deg, n_su, kenar_top, kenar_bina)
    ds = None
    log("CN histogramı ve içerik bayrakları tamam")

    # 4) dolma eşiği: yerel akış + memba taşması, yağış 0..Pmax mm
    Pg = np.arange(0, P["yagis_mm_maks"] + 1, dtype=np.float64)
    cn_deger = np.arange(55, 101, dtype=np.float64)
    Qtab = np.stack([scs_q(Pg, c) for c in cn_deger])                       # 46 × nP, mm
    Vin = np.empty((m + 1, len(Pg)), np.float32)                             # m³
    for i in range(0, m + 1, 50000):
        Vin[i:i + 50000] = cn_hist[i:i + 50000].astype(np.float64) @ Qtab * (piksel_m2 / 1000.0)
    hav_alan = cn_hist.sum(axis=1) * piksel_m2
    der = basamak_derinligi(alici)
    sira = np.argsort(-der[1:], kind="stable") + 1                           # en uzak memba önce
    toplam_hav = hav_alan.astype(np.float64).copy()
    cap = hacim_m3.astype(np.float32)
    for b in sira:
        r = alici[b]
        if r > 0:
            Vin[r] += np.maximum(Vin[b] - cap[b], 0)
            toplam_hav[r] += toplam_hav[b]
    dolu = Vin >= cap[:, None]
    esik = np.where(dolu.any(axis=1), dolu.argmax(axis=1), -1).astype(np.int32)
    esik[0] = -1
    def doluluk(p):
        return np.minimum(Vin[:, p] / np.maximum(cap, 1e-6), 1.0)
    log(f"Dolma eşikleri: {((esik >= 0) & (esik <= 50)).sum():,} çukur 50 mm'de doluyor")

    # bayraklar
    alan_px = np.maximum(alan_m2 / piksel_m2, 1)
    bina_oran = kenar_bina / np.maximum(kenar_top, 1)
    avlu = (bina_oran >= P["avlu_bina_orani"]) & (alan_m2 <= P["avlu_maks_alan_m2"])
    su = n_su / alan_px >= P["su_orani"]
    degisen = n_deg / alan_px >= P["degisen_orani"]
    guvenilir = ~(avlu | su | degisen)

    # 5) tablo + poligonlar
    ty, tx = np.divmod(np.maximum(tasma, 0), nx)
    tasma_x = gt[0] + (tx + 0.5) * gt[1]; tasma_y = gt[3] + (ty + 0.5) * gt[5]
    cn_ort = (cn_hist * np.arange(55, 101)).sum(axis=1) / np.maximum(cn_hist.sum(axis=1), 1)
    sut = {
        "cukur_id": np.arange(m + 1), "alan_m2": alan_m2.round(0), "hacim_m3": hacim_m3.round(1),
        "maks_derinlik_m": maksd.round(2), "su_kotu_m": seviye.round(2),
        "yerel_havza_m2": hav_alan, "toplam_havza_m2": toplam_hav.round(0), "havza_cn_ort": cn_ort.round(1),
        "alici_id": alici, "dolma_esigi_mm": esik,
        "doluluk_25mm": doluluk(25).round(3), "doluluk_50mm": doluluk(50).round(3), "doluluk_100mm": doluluk(100).round(3),
        "yol_m2": n_yol * piksel_m2, "altgecit_m2": n_ag * piksel_m2, "altgecit_osm_fid": ag_id,
        "bina_kenar_orani": bina_oran.round(2), "avlu": avlu.astype(int), "su_alani": su.astype(int),
        "degisen_topo": degisen.astype(int), "guvenilir": guvenilir.astype(int),
        "tasma_x": tasma_x.round(1), "tasma_y": tasma_y.round(1), "basamak": der,
    }
    import csv
    with open(os.path.join(OUT, "cukurlar.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(sut.keys())
        for i in range(1, m + 1):
            w.writerow([sut[k][i] for k in sut])
    np.savez_compressed(os.path.join(OUT, "hipsometri.npz"), ofset=hip_ofset, kot=hip_kot, su_kotu=seviye,
                        alici=alici, yerel_vin_tablosu_mm=Pg)
    # dolma eşiği rasterı
    esik_f = np.where(esik >= 0, esik, P["yagis_mm_maks"] + 1).astype(np.float32)
    esik_f[0] = -1
    ds = gdal.GetDriverByName("GTiff").Create(os.path.join(OUT, "dolma_esigi_mm_10m.tif"), nx, ny, 1, gdal.GDT_Float32,
                                              options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
    ds.SetGeoTransform(gt); ds.SetProjection(wkt); ds.GetRasterBand(1).SetNoDataValue(-1)
    for y in range(0, ny, 1024):
        ds.GetRasterBand(1).WriteArray(esik_f[labels[y:y + 1024]], 0, y)
    ds = None
    log("Tablo, hipsometri ve eşik rasterı yazıldı")

    gpkg = os.path.join(OUT, "cukurlar.gpkg")
    if os.path.exists(gpkg):
        os.remove(gpkg)
    rs = gdal.Open(os.path.join(OUT, "cukur_id_10m.tif"))
    srs = osr.SpatialReference(wkt=wkt)
    vd = ogr.GetDriverByName("GPKG").CreateDataSource(gpkg)
    lyr = vd.CreateLayer("cukurlar", srs, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("cukur_id", ogr.OFTInteger))
    gdal.Polygonize(rs.GetRasterBand(1), rs.GetRasterBand(1), lyr, 0, ["8CONNECTED=8"])
    rs = None
    tipler = {k: (ogr.OFTReal if np.asarray(v).dtype.kind == "f" else ogr.OFTInteger64) for k, v in sut.items() if k != "cukur_id"}
    for k, t in tipler.items():
        lyr.CreateField(ogr.FieldDefn(k, t))
    lyr.StartTransaction()
    for f in lyr:
        i = f.GetField("cukur_id")
        for k in tipler:
            val = sut[k][i]
            f.SetField(k, float(val) if tipler[k] == ogr.OFTReal else int(val))
        lyr.SetFeature(f)
    lyr.CommitTransaction()
    vd = None
    log(f"cukurlar.gpkg yazıldı")

    ozet = {
        "cukur_sayisi": m, "ham_cukur": int(nlab),
        "guvenilir": int(guvenilir[1:].sum()), "avlu": int(avlu[1:].sum()), "su_alani": int(su[1:].sum()),
        "degisen_topo": int(degisen[1:].sum()),
        "dolan_guvenilir": {f"{p}mm": int(((esik[1:] >= 0) & (esik[1:] <= p) & guvenilir[1:]).sum()) for p in (10, 25, 50, 75, 100)},
        "toplam_hacim_m3": float(hacim_m3[1:].sum()),
    }
    json.dump({"parametreler": P, "ozet": ozet, "sure_sn": round(time.time() - t0)},
              open(os.path.join(OUT, "cukur_parametreler.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"Bitti: {json.dumps(ozet, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
