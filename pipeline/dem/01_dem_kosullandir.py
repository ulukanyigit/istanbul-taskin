"""Faz 3 — DEM koşullandırma.

Açık 30 m DEM'in (FABDEM, 10 m'ye örneklenmiş) göremediği kentsel yapıları OSM vektörlerinden DEM'e işler.
Çukurlar toptan doldurulmaz: bu projede çukurlar sonucun kendisidir. Yalnızca yapay setler (köprüler)
kaldırılır, akış yolları (dereler, menfezler, yollar) açılır, alt geçitler çukur olarak eklenir.

Çalıştırma (OSGeo4W Python, numpy + scipy + GDAL):
    python 01_dem_kosullandir.py <proje_kökü>

Girdi
  istanbul_taskin_gee/fabdem_10m.tif, cn_10m.tif (AOI maskesi: cn > 0), glo30_su_maskesi_30m.tif
  data/interim/osm_istanbul.gpkg
Çıktı (data/interim)
  dem_kosullu_10m.tif     koşullandırılmış DEM (Float32, nodata −9999; deniz ve AOI dışı = nodata → çıkış)
  dem_fark_10m.tif        koşullu − FABDEM (m), kalite kontrol
  maske_islem_10m.tif     işlem kodu (bit alanı, aşağıda)
  menfez_id_10m.tif       menfez pikselleri → menfez sıra no (tıkanma senaryosu)
  altgecit_id_10m.tif     alt geçit pikselleri → alt geçit sıra no (pompa arızası senaryosu)
  degisen_topo_10m.tif    1 = topografyası DEM'den sonra değişmiş olabilir (ocak, döküm, İGA, karada DEM < −2 m)
  dem_kosullandirma_parametreler.json
İşlem bitleri: 1 köprü kaldırıldı · 2 bina yükseltildi · 4 yol alçaltıldı · 8 açık dere oyuldu
               16 menfez açıldı · 32 alt geçit eklendi · 64 deniz (çıkış)
"""
import json
import os
import sys
import time

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()

KOK = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GEE = os.path.join(KOK, "istanbul_taskin_gee")
INT = os.path.join(KOK, "data", "interim")
OSM = os.path.join(INT, "osm_istanbul.gpkg")
DEM_IN = os.path.join(GEE, "fabdem_10m.tif")
NODATA = -9999.0

# ------------------------------------------------------------------ parametreler
P = {
    "bina_yukseklik_m": 5.0,          # binalar akışa engel: tabana eklenen yükseklik
    "yol_alcaltma_m": 0.30,           # kentte su caddeden akar: kaldırım/bordür farkı
    "yol_yari_genislik_m": {          # yol sınıfına göre yarım genişlik (tampon)
        "motorway": 12, "trunk": 10, "primary": 8, "secondary": 7, "tertiary": 6,
        "motorway_link": 5, "trunk_link": 5, "primary_link": 5, "secondary_link": 5, "tertiary_link": 5,
        "residential": 4, "unclassified": 4, "living_street": 4, "pedestrian": 4, "_diger": 3,
    },
    "kopru_ek_tampon_m": 5,           # köprü tamponu = yol yarı genişliği + bu değer
    "kopru_doldurma_maks_px": 40,     # köprü altı enterpolasyonunda arama mesafesi (10 m px)
    "dere": {                         # tür: [oyma derinliği m, yarım genişlik m]
        "river": [2.0, 10], "canal": [1.5, 6], "stream": [1.0, 0], "drain": [0.5, 0], "ditch": [0.5, 0],
    },
    "hat_ornekleme_m": 5,
    "dere_medyan_pencere": 7,        # örnek (5 m aralıkla ~35 m)
    "dere_maks_ek_oyma_m": 3.0,      # yerel zeminin en fazla derinlik + bu kadar altına inilir
    "altgecit_derinlik_m": 5.0,       # alt geçit tabanı = iki uç arasında doğrusal zemin − bu değer
    "altgecit_yari_genislik_m": 6,
    "degisen_esik_m": -2.0,         # karada bu kotun altı: maden çukuru / güncel olmayan DEM şüphesi
    "karo_px": 2048,
    "karo_pay_px": 64,
}

# ------------------------------------------------------------------ ızgara
ref = gdal.Open(os.path.join(GEE, "cn_10m.tif"))
GT = ref.GetGeoTransform()
NX, NY = ref.RasterXSize, ref.RasterYSize
WKT = ref.GetProjection()
ref = None
PX = GT[1]


def yeni_raster(yol, dtype, nodata=None):
    ds = gdal.GetDriverByName("GTiff").Create(
        yol, NX, NY, 1, dtype,
        options=["COMPRESS=DEFLATE", "PREDICTOR=" + ("3" if dtype == gdal.GDT_Float32 else "2"),
                 "TILED=YES", "BIGTIFF=IF_SAFER", "NUM_THREADS=ALL_CPUS"])
    ds.SetGeoTransform(GT)
    ds.SetProjection(WKT)
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    return ds


def rasterize(yol, sql, deger=1, attribute=None, dtype=gdal.GDT_Byte, all_touched=False):
    ds = yeni_raster(yol, dtype, 0)
    opts = dict(SQLStatement=" ".join(sql.split()), SQLDialect="SQLite", allTouched=all_touched)
    if attribute:
        opts["attribute"] = attribute
    else:
        opts["burnValues"] = [deger]
    gdal.Rasterize(ds, OSM, options=gdal.RasterizeOptions(**opts))
    ds = None


def tmp(ad):
    return os.path.join(INT, f"_tmp_{ad}.tif")


# ------------------------------------------------------------------ 1) vektörlerden maskeler
def genislik_case(alan="sinif", ek=0):
    yg = P["yol_yari_genislik_m"]
    parca = " ".join(f"WHEN '{k}' THEN {v + ek}" for k, v in yg.items() if not k.startswith("_"))
    return f"CASE {alan} {parca} ELSE {yg['_diger'] + ek} END"


def maskeler():
    t = time.time()
    rasterize(tmp("bina"), "SELECT geom FROM binalar")
    rasterize(tmp("yol"), f"SELECT ST_Buffer(geom, {genislik_case()}) AS geom FROM yollar WHERE kopru = 0 AND tunel = 0")
    rasterize(tmp("kopru"), f"""SELECT ST_Buffer(k.geom, {genislik_case('k.uzerindeki', P['kopru_ek_tampon_m'])}) AS geom
                                FROM kopruler k""", all_touched=True)
    rasterize(tmp("ocak"), "SELECT geom FROM ocaklar", all_touched=True)
    rasterize(tmp("iga"), "SELECT geom FROM havalimanlari WHERE name = 'İstanbul Havalimanı'", all_touched=True)
    # deniz: GLO30 su maskesi (1 = deniz), 30 m → 10 m en yakın komşu
    gdal.Warp(tmp("deniz"), os.path.join(GEE, "glo30_su_maskesi_30m.tif"), format="GTiff",
              outputBounds=(GT[0], GT[3] + NY * GT[5], GT[0] + NX * GT[1], GT[3]), width=NX, height=NY,
              resampleAlg="near", dstSRS=WKT, creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
    print(f"  maskeler hazır ({time.time() - t:.0f} sn)")


# ------------------------------------------------------------------ 2) hat profilleri (dere, menfez, alt geçit)
def satir_sutun(x, y):
    return ((GT[3] - y) / PX).astype(np.int64), ((x - GT[0]) / PX).astype(np.int64)


def hat_noktalari(geom, adim):
    g = geom.Clone()
    g.Segmentize(adim)
    if g.GetGeometryType() in (ogr.wkbMultiLineString, ogr.wkbMultiLineString25D):
        parcalar = [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
    else:
        parcalar = [g]
    out = []
    for p in parcalar:
        pts = np.array(p.GetPoints())[:, :2] if p.GetPointCount() else np.empty((0, 2))
        if len(pts):
            out.append(pts)
    return out


def komsuluk(yari_m):
    r = int(round(yari_m / PX))
    if r <= 0:
        return np.array([[0, 0]])
    d = np.arange(-r, r + 1)
    yy, xx = np.meshgrid(d, d, indexing="ij")
    m = yy ** 2 + xx ** 2 <= r * r + r
    return np.stack([yy[m], xx[m]], axis=1)


def profiller(dem):
    ds = ogr.Open(OSM)
    adim = P["hat_ornekleme_m"]
    sonuc = {"dere": [], "menfez": [], "altgecit": []}   # (satır, sütun, hedef kot, id)
    ters = 0

    lyr = ds.GetLayerByName("dereler")
    for f in lyr:
        tur = f.GetField("tur")
        derinlik, yari = P["dere"].get(tur, [0.5, 0])
        kom = komsuluk(yari)
        kapali = f.GetField("kapali") == 1
        for pts in hat_noktalari(f.GetGeometryRef(), adim):
            r, c = satir_sutun(pts[:, 0], pts[:, 1])
            ok = (r >= 0) & (r < NY) & (c >= 0) & (c < NX)
            r, c = r[ok], c[ok]
            if len(r) < 2:
                continue
            z = dem[r, c].astype(np.float64)
            gecerli = np.isfinite(z) & (z != NODATA)
            if gecerli.sum() < 2:
                continue
            zi = np.interp(np.arange(len(z)), np.flatnonzero(gecerli), z[gecerli])
            # OSM akış yönü mansaba doğrudur; uçlar yokuş yukarı gösteriyorsa ters çiz
            n = max(1, len(zi) // 10)
            if zi[:n].mean() < zi[-n:].mean() - 0.5:
                zi, r, c = zi[::-1], r[::-1], c[::-1]
                ters += 1
            # tek piksellik DEM gürültüsü tüm kola yayılmasın: önce kayan medyan, sonra kümülatif minimum
            k = P["dere_medyan_pencere"]
            if len(zi) >= k:
                pad = np.pad(zi, k // 2, mode="edge")
                zs = np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1)
            else:
                zs = zi
            hedef = np.minimum.accumulate(zs) - derinlik    # mansaba doğru hiç yükselmeyen profil
            hedef = np.maximum(hedef, zi - derinlik - P["dere_maks_ek_oyma_m"])   # aşırı oymayı sınırla
            rr = (r[:, None] + kom[:, 0]).ravel()
            cc = (c[:, None] + kom[:, 1]).ravel()
            hh = np.repeat(hedef, len(kom))
            kim = "menfez" if kapali else "dere"
            sonuc[kim].append(np.stack([rr, cc, hh, np.full(len(rr), f.GetFID())], axis=1))

    lyr = ds.GetLayerByName("alt_gecitler")
    kom = komsuluk(P["altgecit_yari_genislik_m"])
    for f in lyr:
        for pts in hat_noktalari(f.GetGeometryRef(), adim):
            r, c = satir_sutun(pts[:, 0], pts[:, 1])
            ok = (r >= 0) & (r < NY) & (c >= 0) & (c < NX)
            r, c = r[ok], c[ok]
            if len(r) < 2:
                continue
            uc = dem[[r[0], r[-1]], [c[0], c[-1]]].astype(np.float64)
            if not np.isfinite(uc).all() or (uc == NODATA).any():
                continue
            # taban, iki uç arasındaki eğimi izler ve yüzeyin D metre altındadır
            s_ = np.linspace(0.0, 1.0, len(r))
            taban = uc[0] + (uc[1] - uc[0]) * s_ - P["altgecit_derinlik_m"]
            rr = (r[:, None] + kom[:, 0]).ravel()
            cc = (c[:, None] + kom[:, 1]).ravel()
            sonuc["altgecit"].append(np.stack([rr, cc, np.repeat(taban, len(kom)), np.full(len(rr), f.GetFID())], axis=1))

    for k in sonuc:
        a = np.concatenate(sonuc[k]) if sonuc[k] else np.empty((0, 4))
        ok = (a[:, 0] >= 0) & (a[:, 0] < NY) & (a[:, 1] >= 0) & (a[:, 1] < NX)
        sonuc[k] = a[ok]
    print(f"  profiller: dere {len(sonuc['dere']):,} px, menfez {len(sonuc['menfez']):,} px, "
          f"alt geçit {len(sonuc['altgecit']):,} px; yönü ters çevrilen dere parçası {ters}")
    return sonuc


def piksel_min(a):
    """Aynı piksele düşen kayıtlardan en düşük hedefi tut."""
    if not len(a):
        return a
    a = a[np.lexsort((a[:, 2], a[:, 1], a[:, 0]))]
    ilk = np.ones(len(a), bool)
    ilk[1:] = (a[1:, 0] != a[:-1, 0]) | (a[1:, 1] != a[:-1, 1])
    return a[ilk]


# ------------------------------------------------------------------ 3) karo döngüsü
def karo_dongusu(hatlar):
    t = time.time()
    src = {k: gdal.Open(v) for k, v in {
        "dem": DEM_IN, "cn": os.path.join(GEE, "cn_10m.tif"), "bina": tmp("bina"), "yol": tmp("yol"),
        "kopru": tmp("kopru"), "ocak": tmp("ocak"), "iga": tmp("iga"), "deniz": tmp("deniz")}.items()}
    out = {
        "dem": yeni_raster(os.path.join(INT, "dem_kosullu_10m.tif"), gdal.GDT_Float32, NODATA),
        "fark": yeni_raster(os.path.join(INT, "dem_fark_10m.tif"), gdal.GDT_Float32, NODATA),
        "islem": yeni_raster(os.path.join(INT, "maske_islem_10m.tif"), gdal.GDT_Byte, 0),
        "menfez": yeni_raster(os.path.join(INT, "menfez_id_10m.tif"), gdal.GDT_Int32, 0),
        "altgecit": yeni_raster(os.path.join(INT, "altgecit_id_10m.tif"), gdal.GDT_Int32, 0),
        "degisen": yeni_raster(os.path.join(INT, "degisen_topo_10m.tif"), gdal.GDT_Byte, 0),
    }
    K, M = P["karo_px"], P["karo_pay_px"]
    sayac = {k: 0 for k in ["kopru", "bina", "yol", "dere", "menfez", "altgecit", "deniz", "degisen"]}
    # hat kayıtlarını karolara hızlı dağıtmak için satıra göre sırala
    for k in hatlar:
        hatlar[k] = hatlar[k][np.argsort(hatlar[k][:, 0], kind="stable")]

    for y0 in range(0, NY, K):
        for x0 in range(0, NX, K):
            # pay ile okuma penceresi
            ya, xa = max(0, y0 - M), max(0, x0 - M)
            yb, xb = min(NY, y0 + K + M), min(NX, x0 + K + M)
            h, w = yb - ya, xb - xa
            oku = lambda k: src[k].GetRasterBand(1).ReadAsArray(xa, ya, w, h)
            dem0 = oku("dem").astype(np.float32)
            aoi = oku("cn") > 0
            gecerli = aoi & np.isfinite(dem0)
            dem0 = np.where(gecerli, dem0, NODATA).astype(np.float32)
            if not gecerli.any():
                continue
            z = dem0.copy()
            islem = np.zeros((h, w), np.uint8)

            # (a) köprüler: tabliyeyi kaldır, altını çevreden enterpole et, asla yükseltme
            kopru = (oku("kopru") == 1) & gecerli
            if kopru.any():
                mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Float32)
                b = mem.GetRasterBand(1)
                b.SetNoDataValue(NODATA)
                b.WriteArray(np.where(kopru, NODATA, z))
                gdal.FillNodata(b, None, P["kopru_doldurma_maks_px"], 0)
                dolu = b.ReadAsArray()
                yeni = np.where(kopru & (dolu != NODATA), np.minimum(z, dolu), z)
                islem[kopru & (yeni < z)] |= 1
                z = yeni.astype(np.float32)

            # (b) binalar engel, (c) yollar binaları ezer ve alçaltılır
            bina = (oku("bina") == 1) & gecerli
            yol = (oku("yol") == 1) & gecerli
            z = np.where(bina & ~yol, z + P["bina_yukseklik_m"], z)
            islem[bina & ~yol] |= 2
            z = np.where(yol, z - P["yol_alcaltma_m"], z)
            islem[yol] |= 4

            # (d) hatlar: dere, menfez, alt geçit → hedef kotun altına indir
            idler = {"menfez": np.zeros((h, w), np.int32), "altgecit": np.zeros((h, w), np.int32)}
            for k, bit in [("dere", 8), ("menfez", 16), ("altgecit", 32)]:
                a = hatlar[k]
                i0, i1 = np.searchsorted(a[:, 0], [ya, yb])
                a = a[i0:i1]
                a = a[(a[:, 1] >= xa) & (a[:, 1] < xb)]
                if not len(a):
                    continue
                r = (a[:, 0] - ya).astype(np.int64)
                c = (a[:, 1] - xa).astype(np.int64)
                ok = gecerli[r, c]
                r, c, hedef = r[ok], c[ok], a[ok, 2].astype(np.float32)
                once = z[r, c]
                np.minimum.at(z, (r, c), hedef)
                degisti = z[r, c] < once
                islem[r[degisti], c[degisti]] |= bit
                if k in idler:
                    idler[k][r, c] = (a[ok, 3] + 1).astype(np.int32)

            # (e) deniz → nodata (çıkış)
            deniz = (oku("deniz") == 1) & gecerli
            islem[deniz] |= 64
            z[deniz] = NODATA
            z[~gecerli] = NODATA

            # (f) topografyası değişmiş olabilecek alanlar
            degisen = ((oku("ocak") == 1) | (oku("iga") == 1) | ((dem0 < P["degisen_esik_m"]) & ~deniz)) & gecerli

            # yalnızca karo içini yaz
            iy, ix = y0 - ya, x0 - xa
            hh, ww = min(K, NY - y0), min(K, NX - x0)
            s = (slice(iy, iy + hh), slice(ix, ix + ww))
            fark = np.where((z != NODATA) & (dem0 != NODATA), z - dem0, NODATA).astype(np.float32)
            out["dem"].GetRasterBand(1).WriteArray(z[s], x0, y0)
            out["fark"].GetRasterBand(1).WriteArray(fark[s], x0, y0)
            out["islem"].GetRasterBand(1).WriteArray(islem[s], x0, y0)
            out["menfez"].GetRasterBand(1).WriteArray(idler["menfez"][s], x0, y0)
            out["altgecit"].GetRasterBand(1).WriteArray(idler["altgecit"][s], x0, y0)
            out["degisen"].GetRasterBand(1).WriteArray(degisen[s].astype(np.uint8), x0, y0)
            ic = islem[s]
            for k, bit in [("kopru", 1), ("bina", 2), ("yol", 4), ("dere", 8), ("menfez", 16), ("altgecit", 32), ("deniz", 64)]:
                sayac[k] += int(((ic & bit) > 0).sum())
            sayac["degisen"] += int(degisen[s].sum())
        print(f"  satır {min(y0 + K, NY):>6}/{NY}  ({time.time() - t:.0f} sn)")

    for d in out.values():
        d.FlushCache()
    out = None
    src = None
    return sayac


if __name__ == "__main__":
    t0 = time.time()
    print("1/3 vektörler rasterleştiriliyor...")
    maskeler()
    print("2/3 dere, menfez ve alt geçit profilleri...")
    dem_ds = gdal.Open(DEM_IN)
    dem_full = dem_ds.GetRasterBand(1).ReadAsArray()
    dem_ds = None
    hatlar = {k: piksel_min(v) for k, v in profiller(dem_full).items()}
    del dem_full
    print("3/3 karolar işleniyor...")
    sayac = karo_dongusu(hatlar)
    km2 = {k: round(v * PX * PX / 1e6, 2) for k, v in sayac.items()}
    print("Değişen alan (km²):", km2)
    for k in ["bina", "yol", "kopru", "ocak", "iga", "deniz"]:
        try:
            os.remove(tmp(k))
        except OSError:
            pass
    json.dump({"parametreler": P, "degisen_alan_km2": km2, "sure_sn": round(time.time() - t0)},
              open(os.path.join(INT, "dem_kosullandirma_parametreler.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Bitti ({time.time() - t0:.0f} sn)")
