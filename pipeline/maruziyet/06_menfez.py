"""Faz 5d — Menfez tıkanması senaryosu.

Koşullandırmada açılan her kapalı dere / menfez hattı (menfez_id_10m) tıkanınca, hat boyunca DEM ham haline (FABDEM
seti) döner; setin membaında yeni bir gölet oluşur. Her aday menfez için yerel bir pencerede:

  1) Gölet: Priority-Flood doldurma, menfez açık (koşullandırılmış DEM) ve kapalı (hat ham) iki kez yapılır;
     doldurma farkı > 5 cm olan ve menfeze bitişik bölge gölettir. Gölet tabanı "açık durumdaki doldurulmuş yüzey"dir
     (içindeki mevcut çukurların dolu olduğu varsayılır), kapasite = Σ fark × piksel alanı.
  2) Gölete gelen su: menfez açıkken akışı menfezden geçen pikseller (Priority-Flood yönlendirme ağacında menfezin
     membası). Bunlardan hiçbir çukura girmeyenlerin akışı doğrudan gölete gelir; taşma noktası menfezin membasında
     olup alıcısı mansapta kalan çukurlar (besleyenler) tıkanınca taşmalarını gölete verir.
  3) Gölet pikselleri için bina / yol kenarı / tesis temas eşikleri (05_web_paket.py ile aynı yöntem).

Önce il içindeki tüm menfezler kısa pencereyle taranır (gölet hacmi ve bitişik bina pikseli); bitişik binası en çok
olan KAÇ menfez geniş pencereyle (memba alanı için) ayrıntılı işlenir.

Çalıştırma: python 06_menfez.py <proje_kökü> [kac=30]
Çıktılar (data/processed): menfez_tarama.csv, menfez_senaryo.npz, menfez_senaryo.csv
"""
import importlib.util
import os
import sys
import time
import types

import numpy as np
import pandas as pd
import pyogrio
import rasterio
from numba import njit
from rasterio import features
from rasterio.windows import Window
from scipy import ndimage

KOK = sys.argv[1]
KAC = int(sys.argv[2]) if len(sys.argv) > 2 else 30
INT, PR, GEE = (os.path.join(KOK, *p) for p in (("data", "interim"), ("data", "processed"), ("istanbul_taskin_gee",)))
OSM = os.path.join(INT, "osm_istanbul.gpkg")
TARAMA_PAY, DETAY_PAY = 120, 400        # piksel (1,2 km ve 4 km)
MIN_FARK = 0.05
SURUS = ("motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
         "secondary_link", "tertiary_link", "unclassified", "residential", "living_street", "service", "road")
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


for ad in ("osgeo", "osgeo.gdal", "osgeo.ogr", "osgeo.osr"):
    if ad not in sys.modules:
        try:
            __import__(ad)
        except ImportError:
            mm = types.ModuleType(ad); mm.UseExceptions = lambda: None; sys.modules[ad] = mm
            if ad != "osgeo":
                setattr(sys.modules["osgeo"], ad.split(".")[1], mm)
sp = importlib.util.spec_from_file_location("ca", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cukur", "01_cukur_analizi.py"))
_a = sys.argv; sys.argv = [_a[0], KOK]
ca = importlib.util.module_from_spec(sp); sp.loader.exec_module(ca)
sys.argv = _a


@njit
def yonlendir(dem, valid):
    """Priority-Flood ile her pikselin akış yönü (keşfedildiği komşu = mansap) ve ziyaret sırası."""
    ny, nx = dem.shape
    N = ny * nx
    d = dem.ravel(); v = valid.ravel()
    closed = np.zeros(N, np.bool_)
    ebeveyn = np.full(N, -1, np.int64)
    sira = np.empty(N, np.int64); ns = 0
    cap = 1 << 16
    hk = np.empty(cap, np.float32); hs = np.empty(cap, np.int64); hi = np.empty(cap, np.int64)
    n, seq = 0, 0
    dy = np.array([-1, -1, -1, 0, 0, 1, 1, 1]); dx = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    for y in range(ny):
        for x in range(nx):
            c = y * nx + x
            if not v[c]:
                continue
            kenar = y == 0 or x == 0 or y == ny - 1 or x == nx - 1
            if not kenar:
                for k in range(8):
                    if not v[(y + dy[k]) * nx + x + dx[k]]:
                        kenar = True; break
            if kenar:
                closed[c] = True
                if n == cap:
                    cap *= 2
                    hk2 = np.empty(cap, np.float32); hs2 = np.empty(cap, np.int64); hi2 = np.empty(cap, np.int64)
                    hk2[:n] = hk[:n]; hs2[:n] = hs[:n]; hi2[:n] = hi[:n]; hk, hs, hi = hk2, hs2, hi2
                n = ca._heap_push(hk, hs, hi, n, d[c], seq, c); seq += 1
    while n > 0:
        lev, c, n = ca._heap_pop(hk, hs, hi, n)
        sira[ns] = c; ns += 1
        y = c // nx; x = c - y * nx
        for k in range(8):
            yy = y + dy[k]; xx = x + dx[k]
            if yy < 0 or xx < 0 or yy >= ny or xx >= nx:
                continue
            m = yy * nx + xx
            if closed[m] or not v[m]:
                continue
            closed[m] = True
            ebeveyn[m] = c
            if n == cap:
                cap *= 2
                hk2 = np.empty(cap, np.float32); hs2 = np.empty(cap, np.int64); hi2 = np.empty(cap, np.int64)
                hk2[:n] = hk[:n]; hs2[:n] = hs[:n]; hi2[:n] = hi[:n]; hk, hs, hi = hk2, hs2, hi2
            n = ca._heap_push(hk, hs, hi, n, max(d[m], lev), seq, m); seq += 1
    return ebeveyn, sira[:ns]


@njit
def memba(ebeveyn, sira, menfez):
    f = menfez.copy()
    for i in range(len(sira)):
        c = sira[i]
        p = ebeveyn[c]
        if p >= 0 and f[p]:
            f[c] = True
    return f


src = {k: rasterio.open(os.path.join(d, f)) for k, (d, f) in {
    "dem": (INT, "dem_kosullu_10m.tif"), "fark": (INT, "dem_fark_10m.tif"), "menfez": (INT, "menfez_id_10m.tif"),
    "islem": (INT, "maske_islem_10m.tif"), "hav": (PR, "havza_id_10m.tif"), "lab": (PR, "cukur_id_10m.tif"),
    "cn": (GEE, "cn_10m.tif"), "mah": (PR, "mahalle_id_10m.tif")}.items()}
TR = src["dem"].transform
NY, NX = src["dem"].height, src["dem"].width
A = TR.a * -TR.e


def pencere(r0, r1, c0, c1, pay):
    r0, c0 = max(0, r0 - pay), max(0, c0 - pay)
    r1, c1 = min(NY, r1 + pay + 1), min(NX, c1 + pay + 1)
    return Window(c0, r0, c1 - c0, r1 - r0), r0, c0


def oku(k, w, dtype=None):
    a = src[k].read(1, window=w)
    return a.astype(dtype) if dtype is not None else a


# ---------------------------------------------------------------- menfez pikselleri
idler, rr, cc = [], [], []
for y0 in range(0, NY, 1024):
    a = src["menfez"].read(1, window=Window(0, y0, NX, min(1024, NY - y0)))
    r, c = np.nonzero(a)
    idler.append(a[r, c]); rr.append(r + y0); cc.append(c)
idler, rr, cc = np.concatenate(idler), np.concatenate(rr), np.concatenate(cc)
o = np.argsort(idler, kind="stable")
idler, rr, cc = idler[o], rr[o], cc[o]
u, bas = np.unique(idler, return_index=True)
son = np.append(bas[1:], len(idler))
kg = pyogrio.read_dataframe(os.path.join(PR, "mahalle_karnesi.gpkg"), read_geometry=False)
ist = set(kg.loc[kg.istanbul.astype(int) == 1, "mahalle_fid"].astype(int))
dere = pyogrio.read_dataframe(OSM, layer="dereler", columns=["name", "tur", "uzunluk_m"], fid_as_index=True)
log(f"{len(u):,} menfez hattı")


def gol_hesapla(k, i, pay, ayrinti):
    r, c = rr[bas[i]:son[i]], cc[bas[i]:son[i]]
    w, wr0, wc0 = pencere(r.min(), r.max(), c.min(), c.max(), pay)
    z = oku("dem", w, np.float32)
    valid = np.isfinite(z) & (z > -9000)
    fark = np.nan_to_num(oku("fark", w, np.float32))
    mf = oku("menfez", w) == k
    zr = z.copy()
    zr[mf] = z[mf] - fark[mf]
    bos = np.zeros((1, 1), np.int32)
    fc = ca.priority_flood(z, valid, bos, False, 0)[0].reshape(z.shape)
    fr = ca.priority_flood(zr, valid, bos, False, 0)[0].reshape(z.shape)
    df = np.where(valid, fr - fc, 0)
    lab, n = ndimage.label((df > MIN_FARK) & ~mf, structure=np.ones((3, 3), bool))
    temas = np.unique(lab[ndimage.binary_dilation(mf, iterations=2)])
    temas = temas[temas > 0]
    gol = np.isin(lab, temas)
    if not gol.any():
        return None
    islem = oku("islem", w)
    bina_bitisik = int(((islem & 2) > 0)[ndimage.binary_dilation(gol) & ~gol].sum())
    mah = oku("mah", w)
    rc, ccc = int(np.median(r)) - wr0, int(np.median(c)) - wc0
    s = {"menfez": int(k), "ad": dere.name.get(k), "tur": dere.tur.get(k), "uzunluk_m": float(dere.uzunluk_m.get(k, 0)),
         "gol_px": int(gol.sum()), "hacim_m3": float(df[gol].sum() * A), "maks_derinlik_m": float(df[gol].max()),
         "bina_bitisik_px": bina_bitisik, "il_ici": int(mah[rc, ccc] in ist),
         "x": float(TR.c + (np.median(c) + 0.5) * TR.a), "y": float(TR.f + (np.median(r) + 0.5) * TR.e)}
    if not ayrinti:
        return s
    # gölet hipsometrisi: taban = açık durumda doldurulmuş yüzey
    gy, gx = np.nonzero(gol)
    taban = fc[gy, gx]
    o = np.argsort(taban, kind="stable")
    gy, gx, taban = gy[o], gx[o], taban[o]
    tmin = float(taban[0])
    s.update({"taban_kot": tmin, "su_kotu": float(fr[gol].max())})
    piks = {"row": (gy + wr0).astype(np.uint16), "col": (gx + wc0).astype(np.uint16),
            "dz": np.clip(np.round((taban - tmin) * 100), 0, 65535).astype(np.uint16)}
    # memba ve gelen su
    eb, sira = yonlendir(z, valid)
    up = memba(eb, sira, mf.ravel()).reshape(z.shape)
    hav = oku("hav", w); cn = oku("cn", w, np.int32)
    yerel = up & (hav == 0) & (cn > 0)
    cn_hist = np.bincount(np.clip(cn[yerel] - 55, 0, 45), minlength=46).astype(np.int64)
    s["memba_km2"] = float(up.sum() * A / 1e6)
    s["memba_kenar_kesik"] = bool(up[0].any() or up[-1].any() or up[:, 0].any() or up[:, -1].any())
    # besleyen çukurlar: taşma noktası membada, alıcısı membada olmayan
    besleyen = []
    lab0 = oku("lab", w)
    t = CUK
    pen = (t.ty >= wr0) & (t.ty < wr0 + z.shape[0]) & (t.tx >= wc0) & (t.tx < wc0 + z.shape[1])
    for b, ty, tx, al in zip(t.index[pen], t.ty[pen], t.tx[pen], t.alici_id[pen]):
        if not up[ty - wr0, tx - wc0]:
            continue
        if al > 0:
            d = DERIN.get(int(al))
            if d is not None and wr0 <= d[0] < wr0 + z.shape[0] and wc0 <= d[1] < wc0 + z.shape[1] and up[d[0] - wr0, d[1] - wc0]:
                continue        # alıcı da membada: su zaten membada kalıyor
        besleyen.append(int(b))
    s["besleyen"] = len(besleyen)
    s["besleyen_toplam_havza_km2"] = float(t.loc[besleyen, "toplam_havza_m2"].sum() / 1e6) if besleyen else 0.0
    del lab0
    return s, piks, cn_hist, np.array(besleyen, np.int32), (w, wr0, wc0, gol, taban, gy, gx)


# temel çukur tablosu: taşma pikseli ve en derin piksel
CUK = pd.read_csv(os.path.join(PR, "cukurlar_sinifli.csv")).set_index("cukur_id")
CUK["tx"] = ((CUK.tasma_x - TR.c) / TR.a).astype(int)
CUK["ty"] = ((CUK.tasma_y - TR.f) / TR.e).astype(int)
DERIN = {}
with rasterio.open(os.path.join(PR, "cukur_id_10m.tif")) as d:
    for y0 in range(0, NY, 1024):
        a = d.read(1, window=Window(0, y0, NX, min(1024, NY - y0)))
        dm = src["dem"].read(1, window=Window(0, y0, NX, min(1024, NY - y0)))
        r, c = np.nonzero(a)
        if not len(r):
            continue
        b = a[r, c]; zz = dm[r, c]
        o = np.lexsort((zz, b))
        b, r, c = b[o], r[o], c[o]
        ilk = np.concatenate([[True], b[1:] != b[:-1]])
        for bb, r_, c_, z_ in zip(b[ilk], r[ilk], c[ilk], zz[o][ilk]):
            if bb not in DERIN or z_ < DERIN[bb][2]:
                DERIN[int(bb)] = (int(r_ + y0), int(c_), float(z_))
log("çukur taşma ve en derin pikselleri hazır")

# ---------------------------------------------------------------- 1) tarama
TARAMA = os.path.join(PR, "menfez_tarama.csv")
if os.path.exists(TARAMA):
    tarama = pd.read_csv(TARAMA)
    log("tarama önceden yapılmış, okundu")
else:
    kayit = []
    for i, k in enumerate(u):
        if dere.uzunluk_m.get(k, 0) < 10:
            continue
        s = gol_hesapla(int(k), i, TARAMA_PAY, False)
        if s:
            kayit.append(s)
        if i % 200 == 0:
            log(f"tarama {i}/{len(u)}")
    tarama = pd.DataFrame(kayit)
    tarama.to_csv(TARAMA, index=False)
secim = tarama[(tarama.il_ici == 1) & (tarama.hacim_m3 >= 500)].sort_values("bina_bitisik_px", ascending=False).head(KAC)
log(f"tarama: {len(tarama)} gölet oluşturan menfez, il içi seçilen {len(secim)}")

# ---------------------------------------------------------------- 2) ayrıntı
indeks = {int(k): i for i, k in enumerate(u)}
cikti, P_row, P_col, P_dz, P_ofs, CN, BES, BES_ofs = [], [], [], [], [0], [], [], [0]
# maruziyet çiftleri için binalar ve yollar
YOL_SQL = "sinif IN (" + ",".join(f"'{x}'" for x in SURUS) + ")"
tes = pd.concat([pyogrio.read_dataframe(OSM, layer="kritik_tesisler").assign(katman="kritik_tesisler"),
                 pyogrio.read_dataframe(OSM, layer="metro_girisleri").assign(katman="metro_girisleri")], ignore_index=True)
from shapely import get_coordinates, get_num_coordinates  # noqa: E402
B_f, B_g, B_dz, Y_uz, Y_g, Y_dz, T_xy, T_g, T_dz = [], [], [], [], [], [], [], [], []
for j, (_, row) in enumerate(secim.iterrows()):
    k = int(row.menfez)
    sonuc = gol_hesapla(k, indeks[k], DETAY_PAY, True)
    if sonuc is None:
        continue
    s, piks, cn_hist, bes, (w, wr0, wc0, gol, taban, gy, gx) = sonuc
    g = len(cikti)              # gölet sıra no (0 tabanlı)
    s["golet"] = g
    cikti.append(s)
    P_row.append(piks["row"]); P_col.append(piks["col"]); P_dz.append(piks["dz"]); P_ofs.append(P_ofs[-1] + len(piks["row"]))
    CN.append(cn_hist); BES.append(bes); BES_ofs.append(BES_ofs[-1] + len(bes))
    tmin = s["taban_kot"]
    tab = np.full(gol.shape, np.nan, np.float32); tab[gy, gx] = taban
    # binalar (pencere içinde, all_touched) + 1 piksel komşuluk
    wb = rasterio.windows.bounds(w, TR)
    alt = pyogrio.read_dataframe(OSM, layer="binalar", columns=[], fid_as_index=True, on_invalid="fix", bbox=wb)
    alt = alt[alt.geometry.notna() & ~alt.geometry.is_empty]
    if len(alt):
        bid = features.rasterize(zip(alt.geometry.values, alt.index.values.astype(np.int32)), out_shape=gol.shape,
                                 transform=rasterio.windows.transform(w, TR), all_touched=True, dtype=np.int32)
        en = {}
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sb = np.roll(np.roll(bid, dy, 0), dx, 1)
                ss = (sb > 0) & gol
                for f_, t_ in zip(sb[ss], tab[ss]):
                    if f_ not in en or t_ < en[f_]:
                        en[f_] = t_
        for f_, t_ in en.items():
            B_f.append(int(f_)); B_g.append(g); B_dz.append(int(round((t_ - tmin) * 100)))
    # yol kenarları (orta nokta gölette)
    ya = pyogrio.read_dataframe(OSM, layer="yollar", columns=["sinif", "kopru", "tunel"], where=YOL_SQL, bbox=wb)
    if len(ya):
        gg = ya.geometry.explode(index_parts=False)
        kor = (ya.kopru.fillna(0).astype(int) | ya.tunel.fillna(0).astype(int)).reindex(gg.index).values.astype(bool)
        nk = get_num_coordinates(gg.values); xy = get_coordinates(gg.values)
        gec = np.ones(len(xy), bool); gec[np.cumsum(nk) - 1] = False
        i0 = np.flatnonzero(gec)
        kk = np.repeat(kor, np.maximum(nk - 1, 0))
        mx, my = (xy[i0, 0] + xy[i0 + 1, 0]) / 2, (xy[i0, 1] + xy[i0 + 1, 1]) / 2
        uz = np.hypot(xy[i0 + 1, 0] - xy[i0, 0], xy[i0 + 1, 1] - xy[i0, 1])
        r_ = ((my - TR.f) / TR.e).astype(int) - wr0; c_ = ((mx - TR.c) / TR.a).astype(int) - wc0
        ok = (r_ >= 0) & (r_ < gol.shape[0]) & (c_ >= 0) & (c_ < gol.shape[1]) & ~kk
        ok[ok] = gol[r_[ok], c_[ok]]
        for uu, t_ in zip(uz[ok], tab[r_[ok], c_[ok]]):
            Y_uz.append(float(uu)); Y_g.append(g); Y_dz.append(int(round((t_ - tmin) * 100)))
    # tesisler (7×7 pencere)
    for ti, tr_ in tes.iterrows():
        gm = tr_.geometry
        if gm is None or not hasattr(gm, "x") or not (wb[0] <= gm.x <= wb[2] and wb[1] <= gm.y <= wb[3]):
            continue
        r_ = int((gm.y - TR.f) / TR.e) - wr0; c_ = int((gm.x - TR.c) / TR.a) - wc0
        pw = gol[max(0, r_ - 3):r_ + 4, max(0, c_ - 3):c_ + 4]
        if pw.any():
            tw = tab[max(0, r_ - 3):r_ + 4, max(0, c_ - 3):c_ + 4]
            T_xy.append((round(gm.x, 1), round(gm.y, 1))); T_g.append(g); T_dz.append(int(round((np.nanmin(tw[pw]) - tmin) * 100)))
    log(f"#{g} menfez {k} ({s['ad'] or s['tur']}): gölet {s['hacim_m3']:,.0f} m³, {s['gol_px']} px, maks {s['maks_derinlik_m']:.1f} m, "
        f"memba {s['memba_km2']:.1f} km², besleyen {s['besleyen']}, bina {sum(1 for x in B_g if x == g)}")

out = pd.DataFrame(cikti)
out.to_csv(os.path.join(PR, "menfez_senaryo.csv"), index=False)
kap = out.hacim_m3.values.astype(np.float32)
np.savez_compressed(os.path.join(PR, "menfez_senaryo.npz"),
                    menfez=out.menfez.values.astype(np.int32), kap=kap,
                    taban=out.taban_kot.values.astype(np.float32),
                    p_ofs=np.array(P_ofs, np.uint32), p_row=np.concatenate(P_row), p_col=np.concatenate(P_col),
                    p_dz=np.concatenate(P_dz), cn_hist=np.stack(CN), bes_ofs=np.array(BES_ofs, np.uint32),
                    bes=np.concatenate(BES) if BES else np.zeros(0, np.int32),
                    b_fid=np.array(B_f, np.int64), b_g=np.array(B_g, np.int32), b_dz=np.clip(B_dz, 0, 65535).astype(np.uint16),
                    y_uz=np.array(Y_uz, np.float32), y_g=np.array(Y_g, np.int32), y_dz=np.clip(Y_dz, 0, 65535).astype(np.uint16),
                    t_xy=np.array(T_xy, np.float64).reshape(-1, 2), t_g=np.array(T_g, np.int32), t_dz=np.clip(T_dz, 0, 65535).astype(np.uint16))
log(f"bitti: {len(out)} menfez senaryosu, toplam gölet hacmi {kap.sum() / 1e6:.2f} milyon m³")
