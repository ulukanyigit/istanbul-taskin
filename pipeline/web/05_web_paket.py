"""Faz 5a — Tarayıcı simülatörü için veri paketi.

Kova motorunun tarayıcıda çalışması ve su derinliğinin piksel piksel çizilmesi için gereken her şeyi küçük,
ikili (gzip) dosyalara yazar. Motorun girdileri Faz 4'ün çıktılarıyla birebir aynıdır; maruziyet çiftleri Faz 6'nın
yöntemini (bina: 1 piksel komşuluk, yol: ağ kenarı orta noktası, tesis: 7×7 piksel pencere) aynen izler, böylece
tarayıcıdaki sayılar Faz 6'daki rakamları yeniden üretir.

Çalıştırma: python 05_web_paket.py <proje_kökü> <çıktı_klasörü>

Çıktılar (<çıktı>/):
  meta.json      ızgara, projeksiyon polinomları, dosya içerik tablosu, ad sözlükleri, listeler, Faz 6 özeti
  model.bin      çukur başına diziler (alıcı, kapasite, taban kotu, sıra, kategori, CN histogramı...)
  piksel.bin     çukur pikselleri (hipsometri sırasında): sütun, satır, tabandan yükseklik (cm)
  maruz.bin      bina / yol kenarı / tesis ↔ çukur eşik çiftleri
  havza.bin      40 m yerel havza ızgarası (boru patlaması noktasından suyun gideceği çukur)
  tesisler.json  hastane, okul, itfaiye, metro girişi (ad, tür, konum)
Tüm .bin dosyaları gzip'tir; içlerindeki diziler 4 bayta hizalı art arda dizilmiştir (konumlar meta.json'da).
"""
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import pyogrio
import rasterio
from rasterio import features
from pyproj import Transformer

KOK = sys.argv[1]
CIKTI = sys.argv[2]
PR = os.path.join(KOK, "data", "processed")
INT = os.path.join(KOK, "data", "interim")
OSM = os.path.join(INT, "osm_istanbul.gpkg")
os.makedirs(CIKTI, exist_ok=True)
CN_MIN, CN_N = 55, 46
KATEGORI = ["kentsel", "dere_vadi", "alt_gecit", "kirsal", "elenen_avlu", "elenen_su", "elenen_degisen"]
TESIS_TUR = ["hospital", "school", "fire_station", "metro_girisi"]
SURUS = ("motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
         "secondary_link", "tertiary_link", "unclassified", "residential", "living_street", "service", "road")
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


class Paket:
    """Typed array'leri art arda yazan basit kap; içerik tablosu meta.json'a gider."""

    def __init__(self, ad):
        self.ad, self.parca, self.tablo, self.n = ad, [], {}, 0

    def ekle(self, isim, a):
        a = np.ascontiguousarray(a)
        assert a.dtype.byteorder in ("=", "<", "|")
        b = a.tobytes()
        self.tablo[isim] = [self.n, a.dtype.str.lstrip("<|="), int(a.size)]
        pad = (-len(b)) % 4
        self.parca.append(b + b"\0" * pad)
        self.n += len(b) + pad

    def yaz(self):
        ham = b"".join(self.parca)
        with open(os.path.join(CIKTI, self.ad + ".bin"), "wb") as f:
            f.write(gzip.compress(ham, 9, mtime=0))
        log(f"{self.ad}.bin: {len(ham) / 1e6:.1f} MB ham → {os.path.getsize(os.path.join(CIKTI, self.ad + '.bin')) / 1e6:.1f} MB gzip")
        return self.tablo


def oku(yol, dtype=None):
    with rasterio.open(yol) as ds:
        a = ds.read(1)
        gt = ds.transform.to_gdal()
    return (a.astype(dtype) if dtype else a), gt


# ---------------------------------------------------------------- 1) çukurlar ve hipsometri
h = np.load(os.path.join(PR, "hipsometri.npz"))
ofset, kot, alici = h["ofset"], h["kot"], h["alici"]
m = len(ofset) - 1                       # etiketler 1..m
n_px = int(ofset[-1])
npix = np.concatenate([[0], np.diff(ofset)]).astype(np.int64)
taban = np.zeros(m + 1, np.float64)
taban[1:] = kot[ofset[:-1]]

t = pd.read_csv(os.path.join(PR, "cukurlar_sinifli.csv")).set_index("cukur_id").reindex(np.arange(1, m + 1))
assert t.hacim_m3.notna().all()
kap = np.zeros(m + 1, np.float32); kap[1:] = t.hacim_m3.values

lab, GT = oku(os.path.join(PR, "cukur_id_10m.tif"))
NY, NX = lab.shape
A = GT[1] * -GT[5]
lab = lab.astype(np.uint16)
dem, _ = oku(os.path.join(INT, "dem_kosullu_10m.tif"), np.float32)
log(f"ızgara {NX}×{NY}, {m:,} çukur, {n_px:,} çukur pikseli")

idx = np.flatnonzero(lab.ravel())
L = lab.ravel()[idx]
Z = dem.ravel()[idx]
sira_px = np.lexsort((Z, L))
idx, L, Z = idx[sira_px], L[sira_px], Z[sira_px]
assert len(idx) == n_px and np.array_equal(np.bincount(L, minlength=m + 1)[1:], npix[1:])
assert np.allclose(Z, kot, atol=1e-4), "piksel kotları hipsometriyle uyuşmuyor"
col, row = (idx % NX).astype(np.uint16), (idx // NX).astype(np.uint16)
dz_cm = np.round((kot.astype(np.float64) - taban[L]) * 100).astype(np.uint16)
log("pikseller hipsometri sırasına dizildi, kotlar doğrulandı")

# kademe sırası (motor.py ile aynı: derinlik azalan, kararlı)
der = np.full(m + 1, -1, np.int64); der[0] = 0
for b in range(1, m + 1):
    if der[b] >= 0:
        continue
    yol, c = [], b
    while c > 0 and der[c] < 0:
        yol.append(c); c = alici[c] if alici[c] >= 0 else 0
    base = der[c] if c > 0 else 0
    for j in reversed(yol):
        base += 1; der[j] = base
sira = (np.argsort(-der[1:], kind="stable") + 1).astype(np.uint16)

# CN histogramı (seyrek)
hist = np.load(os.path.join(PR, "havza_cn_hist.npy"))
assert hist.shape == (m + 1, CN_N)
nz_b, nz_c = np.nonzero(hist)
cn_ptr = np.zeros(m + 2, np.uint32)
np.add.at(cn_ptr, nz_b + 1, 1)
cn_ptr = np.cumsum(cn_ptr).astype(np.uint32)
cn_kod = nz_c.astype(np.uint8)
cn_say = hist[nz_b, nz_c].astype(np.uint32)
yerel_px = hist.sum(1).astype(np.uint32)
log(f"CN histogramı: {len(cn_kod):,} sıfır olmayan hücre")

# kategori, bayraklar, ad sözlükleri
kat = np.zeros(m + 1, np.uint8); kat[1:] = [KATEGORI.index(k) for k in t.kategori.values]
ilce_ad = sorted(set(t.ilce.dropna()))
mah_ad = sorted(set((t.ilce.fillna("") + "|" + t.mahalle.fillna("")).loc[t.mahalle.notna()]))
ilce_i = np.zeros(m + 1, np.uint8); ilce_i[1:] = [ilce_ad.index(v) + 1 if isinstance(v, str) else 0 for v in t.ilce.values]
mah_i = np.zeros(m + 1, np.uint16)
mah_i[1:] = [mah_ad.index(f"{i}|{mm}") + 1 if isinstance(mm, str) else 0 for i, mm in zip(t.ilce.fillna(""), t.mahalle.values)]
il_ici = np.zeros(m + 1, np.uint8); il_ici[1:] = t.il_ici.fillna(0).astype(int).values
esik = np.zeros(m + 1, np.uint16); esik[1:] = t.dolma_esigi_mm.fillna(301).astype(int).values
derinlik_maks = np.zeros(m + 1, np.float32); derinlik_maks[1:] = t.maks_derinlik_m.values
yerel_havza = np.zeros(m + 1, np.float32); yerel_havza[1:] = t.yerel_havza_m2.values
toplam_havza = np.zeros(m + 1, np.float32); toplam_havza[1:] = t.toplam_havza_m2.values
# merkez (piksel ağırlıklı) ve en derin pikselin konumu
cx = np.bincount(L, weights=col.astype(np.float64) + 0.5, minlength=m + 1) / np.maximum(npix, 1)
cy = np.bincount(L, weights=row.astype(np.float64) + 0.5, minlength=m + 1) / np.maximum(npix, 1)

mp = Paket("model")
mp.ekle("ofset", ofset.astype(np.uint32))
mp.ekle("alici", np.maximum(alici, 0).astype(np.uint16))
mp.ekle("kap", kap)
mp.ekle("taban", taban.astype(np.float32))
mp.ekle("sira", sira)
mp.ekle("kat", kat)
mp.ekle("ilce", ilce_i)
mp.ekle("mah", mah_i)
mp.ekle("il_ici", il_ici)
mp.ekle("esik", esik)
mp.ekle("maks_der", derinlik_maks)
mp.ekle("yerel_havza", yerel_havza)
mp.ekle("toplam_havza", toplam_havza)
mp.ekle("yerel_px", yerel_px)
mp.ekle("cn_ptr", cn_ptr)
mp.ekle("cn_kod", cn_kod)
mp.ekle("cn_say", cn_say)
mp.ekle("cx", cx.astype(np.float32))
mp.ekle("cy", cy.astype(np.float32))
tablo = {"model": mp.yaz()}

pp = Paket("piksel")
pp.ekle("col", col)
pp.ekle("row", row)
pp.ekle("dz", dz_cm)
tablo["piksel"] = pp.yaz()

# ---------------------------------------------------------------- 2) projeksiyon: ızgara (u,v) ↔ Web Mercator
# u = sütun, v = satır (piksel kenarları tam sayı). Mercator birimi [0,1] (MapLibre dünya koordinatı).
tm2ll = Transformer.from_crs("EPSG:5254", "EPSG:4326", always_xy=True)
ll2tm = Transformer.from_crs("EPSG:4326", "EPSG:5254", always_xy=True)


def merc(lon, lat):
    x = (lon + 180.0) / 360.0
    y = (1.0 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / np.pi) / 2.0
    return x, y


def tasarim(s, q):
    return np.stack([np.ones_like(s), s, q, s * s, s * q, q * q, s ** 3, s * s * q, s * q * q, q ** 3], 1)


U0, V0, US, VS = NX / 2, NY / 2, NX / 2, NY / 2
uu, vv = np.meshgrid(np.linspace(0, NX, 120), np.linspace(0, NY, 70))
uu, vv = uu.ravel(), vv.ravel()
lon, lat = tm2ll.transform(GT[0] + uu * GT[1], GT[3] + vv * GT[5])
mx, my = merc(lon, lat)
lon0, lat0 = tm2ll.transform(GT[0] + U0 * GT[1], GT[3] + V0 * GT[5])
MX0, MY0 = merc(lon0, lat0)
s, q = (uu - U0) / US, (vv - V0) / VS
X = tasarim(s, q)
cxm = np.linalg.lstsq(X, mx - MX0, rcond=None)[0]
cym = np.linalg.lstsq(X, my - MY0, rcond=None)[0]
dunya_m = 40075016.686 * np.cos(np.radians(lat0))
hata = np.hypot(X @ cxm - (mx - MX0), X @ cym - (my - MY0)).max() * dunya_m
# ters yön: mercator ofseti → (u, v)
MS = max(np.abs(mx - MX0).max(), np.abs(my - MY0).max())
sm, qm = (mx - MX0) / MS, (my - MY0) / MS
Xi = tasarim(sm, qm)
cu = np.linalg.lstsq(Xi, uu, rcond=None)[0]
cv = np.linalg.lstsq(Xi, vv, rcond=None)[0]
hata_i = np.hypot(Xi @ cu - uu, Xi @ cv - vv).max() * GT[1]
log(f"projeksiyon polinomu: ileri en büyük hata {hata:.3f} m, ters {hata_i:.3f} m")
assert hata < 0.5 and hata_i < 0.5

# ---------------------------------------------------------------- 3) maruziyet çiftleri
mah_r, _ = oku(os.path.join(PR, "mahalle_id_10m.tif"))
kg = pyogrio.read_dataframe(os.path.join(PR, "mahalle_karnesi.gpkg"), read_geometry=False)
ist_mah = set(kg.loc[kg.istanbul.astype(int) == 1, "mahalle_fid"].astype(int))


def cift_min(sahip, cukur, z):
    """(sahip, çukur) çiftleri için en düşük kot → tabandan yükseklik (cm)."""
    s = (sahip > 0) & (cukur > 0)
    sahip, cukur, z = sahip[s].astype(np.int64), cukur[s].astype(np.int64), z[s]
    anahtar = sahip * 65536 + cukur
    o = np.lexsort((z, anahtar))
    anahtar, z = anahtar[o], z[o]
    ilk = np.concatenate([[True], anahtar[1:] != anahtar[:-1]])
    a, zz = anahtar[ilk], z[ilk]
    b = (a % 65536).astype(np.int64)
    dz = np.clip(np.round((zz.astype(np.float64) - taban[b]) * 100), 0, 65535).astype(np.uint16)
    return (a // 65536).astype(np.int64), b.astype(np.uint16), dz


# 3a) binalar: bina pikselleri (all_touched) + 1 piksel komşuluk
bdf = pyogrio.read_dataframe(OSM, layer="binalar", columns=[], fid_as_index=True, on_invalid="fix")
bdf = bdf[bdf.geometry.notna() & ~bdf.geometry.is_empty]
bid = features.rasterize(zip(bdf.geometry.values, bdf.index.values.astype(np.int32)), out_shape=(NY, NX),
                         transform=rasterio.Affine.from_gdal(*GT), all_touched=True, dtype=np.int32)
del bdf
log("bina kimlik rasterı hazır")
parcalar = []
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        ys, yd = (slice(max(0, -dy), NY - max(0, dy)), slice(max(0, dy), NY - max(0, -dy)))
        xs, xd = (slice(max(0, -dx), NX - max(0, dx)), slice(max(0, dx), NX - max(0, -dx)))
        bb = bid[ys, xs]
        ll = lab[yd, xd]
        s = (bb > 0) & (ll > 0)
        parcalar.append((bb[s], ll[s], dem[yd, xd][s]))
bsah = np.concatenate([p[0] for p in parcalar]); bcuk = np.concatenate([p[1] for p in parcalar])
bz = np.concatenate([p[2] for p in parcalar])
del parcalar
b_fid, b_cuk, b_dz = cift_min(bsah, bcuk, bz)
# bina mahallesi: Faz 6 ile aynı (bina pikselleri altındaki en büyük mahalle kimliği)
sb = bid > 0
bina_mah_tum = np.zeros(int(bid.max()) + 1, np.int32)
np.maximum.at(bina_mah_tum, bid[sb], mah_r[sb])
del bid, sb
bn = pd.read_csv(os.path.join(PR, "bina_nufus.csv")).set_index("bina_fid")
ub, b_i = np.unique(b_fid, return_inverse=True)
b_nufus = bn.nufus.reindex(ub).fillna(0).values.astype(np.float32)
b_mah = bina_mah_tum[ub]
b_ist = np.isin(b_mah, list(ist_mah)).astype(np.uint8)
log(f"bina çiftleri: {len(b_fid):,} çift, {len(ub):,} bina")

# 3b) yol ağı kenarları (03_erisim.py ile aynı kurulum), orta noktası çukur pikselinde olanlar
lyr_df = pyogrio.read_dataframe(OSM, layer="yollar", columns=["sinif", "kopru", "tunel", "name"],
                                where="sinif IN (" + ",".join(f"'{x}'" for x in SURUS) + ")")
from shapely import get_coordinates, get_num_coordinates  # noqa: E402
geoms = lyr_df.geometry.explode(index_parts=False)
kor = (lyr_df.kopru.fillna(0).astype(int) | lyr_df.tunel.fillna(0).astype(int)).reindex(geoms.index).values.astype(bool)
nk = get_num_coordinates(geoms.values)
xy = get_coordinates(geoms.values)
gecerli = np.ones(len(xy), bool)
son = np.cumsum(nk)
gecerli[son - 1] = False
i0 = np.flatnonzero(gecerli[:len(xy)])
uzun = np.hypot(xy[i0 + 1, 0] - xy[i0, 0], xy[i0 + 1, 1] - xy[i0, 1])
kenar_kor = np.repeat(kor, np.maximum(nk - 1, 0))
assert len(kenar_kor) == len(i0)
mxx, myy = (xy[i0, 0] + xy[i0 + 1, 0]) / 2, (xy[i0, 1] + xy[i0 + 1, 1]) / 2
cc = ((mxx - GT[0]) / GT[1]).astype(np.int64); rr = ((myy - GT[3]) / GT[5]).astype(np.int64)
ic = (cc >= 0) & (cc < NX) & (rr >= 0) & (rr < NY) & ~kenar_kor & (uzun > 0)
cc, rr, uzun = cc[ic], rr[ic], uzun[ic]
y_lab = lab[rr, cc]
s = y_lab > 0
y_cuk = y_lab[s]; y_uz = uzun[s].astype(np.float32)
y_dz = np.clip(np.round((dem[rr[s], cc[s]].astype(np.float64) - taban[y_cuk]) * 100), 0, 65535).astype(np.uint16)
y_ist = np.isin(mah_r[rr[s], cc[s]], list(ist_mah)).astype(np.uint8)
log(f"yol kenarları: {len(i0):,} kenar, {len(y_cuk):,} tanesi çukur pikselinde")

# 3c) tesisler: 7×7 piksel pencere (Faz 6: ±3 piksel)
tes = []
for katman in ("kritik_tesisler", "metro_girisleri"):
    df = pyogrio.read_dataframe(OSM, layer=katman)
    for _, f in df.iterrows():
        g = f.geometry
        if g is None or not hasattr(g, "is_empty") or g.is_empty:
            continue
        tes.append((katman, f.get("tur", None) if katman == "kritik_tesisler" else "metro_girisi", f.get("name"), g.x, g.y))
t_sah, t_cuk, t_z, t_bilgi = [], [], [], []
for k, (katman, tur, ad, x, y) in enumerate(tes):
    c, r_ = int((x - GT[0]) / GT[1]), int((y - GT[3]) / GT[5])
    if not (3 <= c < NX - 3 and 3 <= r_ < NY - 3):
        continue
    j = len(t_bilgi)
    lon_, lat_ = tm2ll.transform(x, y)
    t_bilgi.append({"tur": TESIS_TUR.index(tur), "ad": ad if isinstance(ad, str) else "", "lon": round(lon_, 6), "lat": round(lat_, 6),
                    "ist": int(mah_r[r_, c] in ist_mah)})
    w = lab[r_ - 3:r_ + 4, c - 3:c + 4]; zw = dem[r_ - 3:r_ + 4, c - 3:c + 4]
    s = w > 0
    t_sah.append(np.full(s.sum(), j + 1)); t_cuk.append(w[s]); t_z.append(zw[s])
t_fid, t_c, t_dz = cift_min(np.concatenate(t_sah), np.concatenate(t_cuk), np.concatenate(t_z))
log(f"tesis çiftleri: {len(t_fid):,} çift, {len(t_bilgi):,} tesis")

xp = Paket("maruz")
xp.ekle("b_i", b_i.astype(np.uint32)); xp.ekle("b_cuk", b_cuk); xp.ekle("b_dz", b_dz)
xp.ekle("b_fid", ub.astype(np.uint32)); xp.ekle("b_nufus", b_nufus); xp.ekle("b_mah", b_mah.astype(np.uint16)); xp.ekle("b_ist", b_ist)
xp.ekle("y_cuk", y_cuk.astype(np.uint16)); xp.ekle("y_dz", y_dz); xp.ekle("y_uz", y_uz); xp.ekle("y_ist", y_ist)
xp.ekle("t_i", (t_fid - 1).astype(np.uint32)); xp.ekle("t_cuk", t_c); xp.ekle("t_dz", t_dz)
tablo["maruz"] = xp.yaz()
json.dump(t_bilgi, open(os.path.join(CIKTI, "tesisler.json"), "w", encoding="utf-8"), ensure_ascii=False,
          separators=(",", ":"))

# ---------------------------------------------------------------- 4) yerel havza ızgarası (40 m, merkez örnekleme)
hv, _ = oku(os.path.join(PR, "havza_id_10m.tif"))
H = 4
hv40 = hv[H // 2::H, H // 2::H].astype(np.uint16)
hp = Paket("havza")
hp.ekle("havza", hv40)
tablo["havza"] = hp.yaz()
del hv

# ---------------------------------------------------------------- 5) Faz 6 kontrol değerleri (motor.py ile)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "maruziyet"))
try:
    from motor import Model  # noqa: E402
except ImportError:          # GDAL Python bağlantısı yoksa motor.py'nin tek kullandığı işlevi rasterio ile sağla
    import types
    _g = types.ModuleType("gdal")
    _g.UseExceptions = lambda: None
    class _DS:
        def __init__(self, p): self.p = p
        def GetGeoTransform(self):
            with rasterio.open(self.p) as d: return d.transform.to_gdal()
    _g.Open = _DS
    sys.modules["osgeo"] = types.ModuleType("osgeo"); sys.modules["osgeo"].gdal = _g; sys.modules["osgeo.gdal"] = _g
    from motor import Model  # noqa: E402

model = Model(KOK)
kontrol = {}
for P in (25, 50, 100):
    sc = model.senaryo(P)
    sev = np.nan_to_num(sc["seviye"].astype(np.float64), nan=-1e9)
    hrel = sev - taban
    bd = np.zeros(len(ub)); np.maximum.at(bd, b_i, hrel[b_cuk] - b_dz / 100.0)
    yd = hrel[y_cuk] - y_dz / 100.0
    kontrol[str(P)] = {
        "depolanan_m3": float(sc["hacim"][1:].sum()),
        "islak_km2_il_ici": float(sc["islak_px"][il_ici == 1].sum() * A / 1e6),
        "islak_km2": float(sc["islak_px"].sum() * A / 1e6),
        "bina_10cm_il_ici": int(((bd >= 0.1) & (b_ist == 1)).sum()),
        "bina_30cm_il_ici": int(((bd >= 0.3) & (b_ist == 1)).sum()),
        "nufus_10cm_il_ici": float(b_nufus[(bd >= 0.1) & (b_ist == 1)].sum()),
        "kapali_yol_km": float(y_uz[yd >= 0.3].sum() / 1000),
        "kapali_yol_km_il_ici": float(y_uz[(yd >= 0.3) & (y_ist == 1)].sum() / 1000),
        "seviye_ornek": {str(b): round(float(hrel[b]), 4) for b in (1, 2, 7, 100, 1000, 30000) if b <= m},
    }
    log(f"{P} mm kontrol: {kontrol[str(P)]}")

# ---------------------------------------------------------------- 6) listeler ve meta
liste = {}
for katman in ("ilk_100_kentsel", "ilk_50_dere_vadi"):
    df = pyogrio.read_dataframe(os.path.join(PR, "listeler.gpkg"), layer=katman, read_geometry=False)
    df = df.sort_values("sira") if "sira" in df else df
    liste[katman] = df.cukur_id.astype(int).tolist()

ozet = {k: json.load(open(os.path.join(PR, f"{k}.json"), encoding="utf-8")) for k in ("maruziyet_ozet", "erisim_ozet", "karne_ozet")}
meta = {
    "surum": time.strftime("%Y-%m-%d"),
    "izgara": {"nx": NX, "ny": NY, "x0": GT[0], "y0": GT[3], "piksel_m": GT[1], "crs": "EPSG:5254"},
    "havza_izgara": {"adim": H, "nx": int(hv40.shape[1]), "ny": int(hv40.shape[0]), "ofset": H // 2},
    "proj": {"mx0": MX0, "my0": MY0, "u0": U0, "v0": V0, "us": US, "vs": VS, "cx": cxm.tolist(), "cy": cym.tolist(),
             "ms": MS, "cu": cu.tolist(), "cv": cv.tolist(), "hata_m": round(float(hata), 3),
             "lon0": lon0, "lat0": lat0},
    "m": m, "n_px": n_px, "piksel_alan_m2": A, "cn_min": CN_MIN, "cn_n": CN_N,
    "kategori": KATEGORI, "tesis_tur": TESIS_TUR, "ilce": ilce_ad, "mahalle": mah_ad,
    "liste": liste, "kontrol_motor_py": kontrol, "ozet_faz6": ozet, "dosya": tablo,
}
json.dump(meta, open(os.path.join(CIKTI, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
log("meta.json yazıldı — bitti")
