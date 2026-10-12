"""Faz 5b — Simülatörün altlık haritası (kendi sunduğumuz vektör karolar + gölgeli rölyef).

Yayımlanan sayfa dış karo sunucularına erişemediği için altlık OSM verisinden üretilir:
  altlik.pmtiles   vektör karolar (z6–14): deniz, su alanları, dereler, yollar (adlarıyla), binalar,
                   mahalle ve ilçe sınırları, etiket noktaları
  rolyef.pmtiles   gölgeli rölyef (z8–12, WebP), koşullandırılmış DEM'den (binalar 3×3 blok minimumu ile bastırılır)
Karolar tarayıcıda 2 MB'lık parçalar halinde (altlik.pmtiles.000, .001 …) okunur; böylece sunucunun Range
isteği desteklemesi gerekmez.

Çalıştırma: python 06_altlik.py <proje_kökü> <çıktı_klasörü> <tippecanoe_klasörü> [vektor,arazi,rolyef]
"""
import io
import math
import os
import subprocess
import sys
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from rasterio.warp import Resampling, reproject
from shapely import STRtree, box, polygonize, unary_union
from shapely.geometry import Point

KOK, CIKTI, TC = sys.argv[1], sys.argv[2], sys.argv[3]
ADIMLAR = sys.argv[4] if len(sys.argv) > 4 else "vektor,arazi"
OSM = os.path.join(KOK, "data", "interim", "osm_istanbul.gpkg")
IDARI = os.path.join(KOK, "data", "processed", "idari.gpkg")
TMP = os.path.join(CIKTI, "_tmp")
os.makedirs(TMP, exist_ok=True)
PARCA = 2 * 1024 * 1024
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:5.0f} sn] {m}", flush=True)


def yaz(gdf, ad):
    yol = os.path.join(TMP, ad + ".geojsonl")
    if os.path.exists(yol):
        os.remove(yol)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].to_crs(4326)
    pyogrio.write_dataframe(gdf, yol, driver="GeoJSONSeq", layer_options={"COORDINATE_PRECISION": 6})
    log(f"{ad}: {len(gdf):,} nesne")
    return yol


with rasterio.open(os.path.join(KOK, "data", "processed", "cukur_id_10m.tif")) as d:
    TR, CRS, NX, NY = d.transform, d.crs, d.width, d.height
BBOX = box(TR.c, TR.f + TR.e * NY, TR.c + TR.a * NX, TR.f)

if "vektor" in ADIMLAR:
    # ---------------------------------------------------------------- 1) deniz: OSM kıyı çizgisinden yüzeyler
    kiyi = pyogrio.read_dataframe(OSM, layer="kiyi_cizgisi")
    hatlar = [g for g in kiyi.geometry.explode(index_parts=False) if g is not None and not g.is_empty]
    yuz = list(polygonize([unary_union(hatlar + [BBOX.boundary])]).geoms)
    agac = STRtree(yuz)
    oy = np.zeros(len(yuz))
    for h in hatlar:
        c = np.asarray(h.coords)
        for a, b in zip(c[:-1], c[1:]):
            d = b - a
            L = math.hypot(*d)
            if L < 2:
                continue
            mid = (a + b) / 2
            sag = mid + np.array([d[1], -d[0]]) / L * 1.0     # OSM: kara solda, deniz sağda
            sol = mid - np.array([d[1], -d[0]]) / L * 1.0
            for p, w in ((sag, 1), (sol, -1)):
                for i in agac.query(Point(p), predicate="within"):
                    oy[i] += w
    deniz = gpd.GeoDataFrame(geometry=[y for y, o in zip(yuz, oy) if o > 0], crs=CRS)
    log(f"deniz: {len(yuz)} yüzeyden {len(deniz)} tanesi deniz")

    # ---------------------------------------------------------------- 2) vektör katmanlar
    YOL_Z = {"motorway": 6, "trunk": 7, "primary": 9, "secondary": 10, "motorway_link": 11, "trunk_link": 11,
             "primary_link": 12, "secondary_link": 12, "tertiary": 11, "tertiary_link": 12, "busway": 12,
             "residential": 13, "unclassified": 12, "living_street": 13, "pedestrian": 13, "road": 13,
             "service": 14, "track": 13}
    yol = pyogrio.read_dataframe(OSM, layer="yollar", columns=["name", "sinif", "kopru", "tunel"])
    yol = yol[yol.sinif.isin(YOL_Z)].copy()
    yol["kopru"] = yol.kopru.fillna(0).astype(int)
    yol["tunel"] = yol.tunel.fillna(0).astype(int)
    yol = yol.rename(columns={"sinif": "s", "name": "ad"})
    dosyalar = {}
    for z in sorted(set(YOL_Z.values())):
        alt = yol[yol.s.map(YOL_Z) == z]
        dosyalar[f"yol_z{z}"] = (yaz(alt, f"yol_z{z}"), "yol", z)

    dere = pyogrio.read_dataframe(OSM, layer="dereler", columns=["name", "tur", "kapali"])
    dere = dere[dere.kapali.fillna(0).astype(int) == 0].rename(columns={"name": "ad"})[["ad", "tur", "geometry"]]
    dosyalar["dere"] = (yaz(dere, "dere"), "dere", 10)
    su = pyogrio.read_dataframe(OSM, layer="su_alanlari", columns=["name", "tur"]).rename(columns={"name": "ad"})
    dosyalar["su"] = (yaz(pd.concat([su[["ad", "geometry"]], deniz.assign(ad="")], ignore_index=True), "su"), "su", 6)
    bina = pyogrio.read_dataframe(OSM, layer="binalar", columns=["kat"], on_invalid="ignore")
    bina["k"] = pd.to_numeric(bina.kat, errors="coerce").clip(1, 60)   # kat sayısı (3B yükseklik); yoksa boş
    bina = bina[["k", "geometry"]]
    dosyalar["bina"] = (yaz(bina, "bina"), "bina", 14)

    mah = pyogrio.read_dataframe(IDARI, layer="mahalleler", fid_as_index=True)
    mah["fid"] = mah.index.astype(int)
    mah = mah.reset_index(drop=True)
    kg = pyogrio.read_dataframe(os.path.join(KOK, "data", "processed", "mahalle_karnesi.gpkg"), read_geometry=False)
    mah = mah.merge(kg[["mahalle_fid", "ilce", "istanbul"]], left_on="fid", right_on="mahalle_fid", how="left")
    mah["ist"] = mah.istanbul.fillna(0).astype(int)
    mah = mah.rename(columns={"mahalle": "ad"})[["fid", "ad", "ilce", "ist", "geometry"]]
    mah["geometry"] = mah.geometry.simplify(5)
    dosyalar["mahalle"] = (yaz(mah, "mahalle"), "mahalle", 8)
    ilce = pyogrio.read_dataframe(IDARI, layer="ilceler")
    ilce = ilce.rename(columns={"ilce": "ad"})
    ilce["ist"] = ilce.istanbul.fillna(0).astype(int)
    ilce = ilce[["ad", "ist", "geometry"]]
    ilce["geometry"] = ilce.geometry.simplify(10)
    dosyalar["ilce"] = (yaz(ilce, "ilce"), "ilce", 6)
    etiket = pd.concat([
        gpd.GeoDataFrame({"ad": ilce.ad, "t": "ilce", "ist": ilce.ist}, geometry=ilce.geometry.representative_point(), crs=CRS),
        gpd.GeoDataFrame({"ad": mah.ad, "t": "mahalle", "ist": mah.ist}, geometry=mah.geometry.representative_point(), crs=CRS),
    ], ignore_index=True)
    dosyalar["etiket"] = (yaz(etiket, "etiket"), "etiket", 8)

    # ---------------------------------------------------------------- 3) tippecanoe
    tpc = os.path.join(TC, "tippecanoe")
    parcalar = []
    for ad, (yol_, katman, zmin) in dosyalar.items():
        out = os.path.join(TMP, ad + ".pmtiles")
        arg = [tpc, "-q", "-f", "-o", out, "-l", katman, "-Z", str(zmin), "-z", "14", "--no-tile-stats",
               "--simplification=4"]
        if katman in ("mahalle", "ilce"):
            arg += ["--detect-shared-borders"]
        if katman == "bina":
            arg += ["--drop-densest-as-needed", "--extend-zooms-if-still-dropping"]
        elif katman in ("yol", "dere"):
            arg += ["--drop-densest-as-needed", "--coalesce-smallest-as-needed"]
        elif katman == "etiket":
            arg += ["-r1", "--no-feature-limit", "--no-tile-size-limit"]
        else:
            arg += ["--no-tile-size-limit", "--coalesce-densest-as-needed"]
        subprocess.run(arg + [yol_], check=True)
        parcalar.append(out)
        log(f"tippecanoe {ad} → {os.path.getsize(out) / 1e6:.1f} MB")
    hedef = os.path.join(CIKTI, "altlik.pmtiles")
    subprocess.run([os.path.join(TC, "tile-join"), "-q", "-f", "--no-tile-size-limit", "--no-tile-stats", "-o", hedef] + parcalar,
                   check=True)
    log(f"altlik.pmtiles: {os.path.getsize(hedef) / 1e6:.1f} MB")

# ---------------------------------------------------------------- 4) gölgeli rölyef karoları
# Rölyef bir kez z12 karo ızgarasına (Web Mercator, ~38 m) yeniden örneklenir; alt düzeyler 2×2 ortalamayla.
if "rolyef" in ADIMLAR:
    with rasterio.open(os.path.join(KOK, "data", "interim", "dem_kosullu_10m.tif")) as d:
        z = d.read(1)
    B = 3
    ny3, nx3 = NY // B, NX // B
    z = z[:ny3 * B, :nx3 * B].reshape(ny3, B, nx3, B)
    zg = (z > -9000).any(axis=(1, 3))
    z = np.where(z > -9000, z, np.inf).min(axis=(1, 3))
    z[~zg] = np.nan
    s = 10.0 * B
    zf = np.where(np.isnan(z), np.nanmean(z), z)
    gy, gx = np.gradient(zf, s)
    az, alt = math.radians(315), math.radians(45)
    egim = np.arctan(np.hypot(gx, gy) * 1.6)
    baki = np.arctan2(-gx, gy)
    hs = np.sin(alt) * np.cos(egim) + np.cos(alt) * np.sin(egim) * np.cos(az - baki)
    duz = np.sin(alt)
    golge = np.clip((duz - hs) / duz, 0, 1).astype(np.float32)
    isik = np.clip((hs - duz) / (1 - duz), 0, 1).astype(np.float32)
    golge[~zg] = np.nan
    isik[~zg] = np.nan
    TR3 = rasterio.Affine(TR.a * B, 0, TR.c, 0, TR.e * B, TR.f)
    del z, zf, gx, gy, egim, baki, hs

    from pyproj import Transformer  # noqa: E402
    tr = Transformer.from_crs(CRS, 4326, always_xy=True)
    lons, lats = tr.transform([BBOX.bounds[0], BBOX.bounds[2], BBOX.bounds[0], BBOX.bounds[2]],
                              [BBOX.bounds[1], BBOX.bounds[1], BBOX.bounds[3], BBOX.bounds[3]])
    ZM = 12
    n = 2 ** ZM
    tx0, ty0 = int((min(lons) + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(max(lats)))) / math.pi) / 2 * n)
    tx1, ty1 = int((max(lons) + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(min(lats)))) / math.pi) / 2 * n)
    # z8 sınırına hizala ki alt düzeyler tam karo olsun
    k = 2 ** (ZM - 8)
    tx0, ty0 = tx0 // k * k, ty0 // k * k
    tx1, ty1 = (tx1 // k + 1) * k - 1, (ty1 // k + 1) * k - 1
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    R = 6378137.0 * math.pi
    res = 2 * R / (n * 256)
    dst_tr = rasterio.Affine(res, 0, tx0 * 256 * res - R, 0, -res, R - ty0 * 256 * res)
    kat = []
    for src in (golge, isik):
        out = np.full((H, W), np.nan, np.float32)
        reproject(src, out, src_transform=TR3, src_crs=CRS, dst_transform=dst_tr, dst_crs="EPSG:3857",
                  resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan, num_threads=2)
        kat.append(out)
    del golge, isik
    log(f"rölyef z{ZM} ızgarasına örneklendi ({W}×{H})")
    kayit = []
    g, l = kat
    for zz in range(ZM, 7, -1):
        f = 2 ** (ZM - zz)
        nxt, nyt = (tx1 - tx0 + 1) // f, (ty1 - ty0 + 1) // f
        for j in range(nyt):
            for i in range(nxt):
                gg = g[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
                if np.isnan(gg).all():
                    continue
                ll_ = np.nan_to_num(l[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256])
                gg = np.nan_to_num(gg)
                a = np.clip(gg * 200 + ll_ * 120, 0, 255).astype(np.uint8)
                renk = np.where(gg >= ll_, 0, 255).astype(np.uint8)
                buf = io.BytesIO()
                Image.fromarray(np.dstack([renk, renk, renk, a]), "RGBA").save(buf, "WEBP", quality=50, method=4)
                kayit.append((zxy_to_tileid(zz, tx0 // f + i, ty0 // f + j), buf.getvalue()))
        if zz > 8:   # bir üst düzey için 2×2 ortalama (NaN'ları yok sayarak)
            def kucult(a):
                h2, w2 = a.shape[0] // 2, a.shape[1] // 2
                b = a[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2)
                with np.errstate(invalid="ignore"):
                    return np.nanmean(b, axis=(1, 3)).astype(np.float32)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                g, l = kucult(g), kucult(l)
    kayit.sort()
    hedef = os.path.join(CIKTI, "rolyef.pmtiles")
    with open(hedef, "wb") as fh:
        w = Writer(fh)
        for tid, veri in kayit:
            w.write_tile(tid, veri)
        E7 = lambda v: int(v * 1e7)  # noqa: E731
        w.finalize({"tile_type": TileType.WEBP, "tile_compression": Compression.NONE, "min_zoom": 8, "max_zoom": ZM,
                    "min_lon_e7": E7(min(lons)), "min_lat_e7": E7(min(lats)), "max_lon_e7": E7(max(lons)),
                    "max_lat_e7": E7(max(lats)), "center_zoom": 10, "center_lon_e7": E7(29.0), "center_lat_e7": E7(41.03)},
                   {"attribution": "FABDEM / Copernicus DEM"})
    log(f"rolyef.pmtiles: {len(kayit)} karo, {os.path.getsize(hedef) / 1e6:.1f} MB")

# ---------------------------------------------------------------- 4b) arazi yükseklik karoları (Terrarium, 3B görünüm + gölgeleme)
# Zemin = koşullandırılmış DEM − bina yükseltmesi (+5 m); 3×3 blok ortalaması (30 m), z12 ızgarasına örneklenir.
# Kodlama (Terrarium): yükseklik = R·256 + G + B/256 − 32768. Analiz alanı dışı 0 m.
if "arazi" in ADIMLAR:
    with rasterio.open(os.path.join(KOK, "data", "interim", "dem_kosullu_10m.tif")) as d:
        z = d.read(1)
    with rasterio.open(os.path.join(KOK, "data", "interim", "maske_islem_10m.tif")) as d:
        mk = d.read(1)
    gecerli = z > -9000
    z = np.where((mk & 2) > 0, z - 5.0, z)
    z = np.where((mk & 64) > 0, 0.0, z)     # deniz
    del mk
    B = 3
    ny3, nx3 = NY // B, NX // B
    zz_ = np.where(gecerli, z, 0.0)[:ny3 * B, :nx3 * B].reshape(ny3, B, nx3, B).mean(axis=(1, 3)).astype(np.float32)
    del z, gecerli
    TR3 = rasterio.Affine(TR.a * B, 0, TR.c, 0, TR.e * B, TR.f)
    from pyproj import Transformer  # noqa: E402
    tr = Transformer.from_crs(CRS, 4326, always_xy=True)
    lons, lats = tr.transform([BBOX.bounds[0], BBOX.bounds[2], BBOX.bounds[0], BBOX.bounds[2]],
                              [BBOX.bounds[1], BBOX.bounds[1], BBOX.bounds[3], BBOX.bounds[3]])
    ZM = 12
    n = 2 ** ZM
    tx0, ty0 = int((min(lons) + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(max(lats)))) / math.pi) / 2 * n)
    tx1, ty1 = int((max(lons) + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(min(lats)))) / math.pi) / 2 * n)
    k = 2 ** (ZM - 8)
    tx0, ty0 = tx0 // k * k, ty0 // k * k
    tx1, ty1 = (tx1 // k + 1) * k - 1, (ty1 // k + 1) * k - 1
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    R = 6378137.0 * math.pi
    res = 2 * R / (n * 256)
    dst_tr = rasterio.Affine(res, 0, tx0 * 256 * res - R, 0, -res, R - ty0 * 256 * res)
    g = np.zeros((H, W), np.float32)
    reproject(zz_, g, src_transform=TR3, src_crs=CRS, dst_transform=dst_tr, dst_crs="EPSG:3857",
              resampling=Resampling.bilinear, src_nodata=None, dst_nodata=0, num_threads=2)
    del zz_
    log(f"arazi z{ZM} ızgarasına örneklendi ({W}×{H})")
    kayit = []
    for zz in range(ZM, 7, -1):
        f = 2 ** (ZM - zz)
        nxt, nyt = (tx1 - tx0 + 1) // f, (ty1 - ty0 + 1) // f
        for j in range(nyt):
            for i in range(nxt):
                t = g[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256]
                if not np.any(np.abs(t) > 0.5):
                    continue
                v = np.clip(np.round((t.astype(np.float64) + 32768) * 256), 0, 2 ** 24 - 1).astype(np.uint32)
                rgb = np.dstack([(v >> 16) & 255, (v >> 8) & 255, v & 255]).astype(np.uint8)
                buf = io.BytesIO()
                Image.fromarray(rgb, "RGB").save(buf, "WEBP", lossless=True, quality=60, method=4)
                kayit.append((zxy_to_tileid(zz, tx0 // f + i, ty0 // f + j), buf.getvalue()))
        if zz > 8:
            h2, w2 = g.shape[0] // 2, g.shape[1] // 2
            g = g[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).mean(axis=(1, 3)).astype(np.float32)
    kayit.sort()
    hedef = os.path.join(CIKTI, "arazi.pmtiles")
    with open(hedef, "wb") as fh:
        w = Writer(fh)
        for tid, veri in kayit:
            w.write_tile(tid, veri)
        E7 = lambda v: int(v * 1e7)  # noqa: E731
        w.finalize({"tile_type": TileType.WEBP, "tile_compression": Compression.NONE, "min_zoom": 8, "max_zoom": ZM,
                    "min_lon_e7": E7(min(lons)), "min_lat_e7": E7(min(lats)), "max_lon_e7": E7(max(lons)),
                    "max_lat_e7": E7(max(lats)), "center_zoom": 10, "center_lon_e7": E7(29.0), "center_lat_e7": E7(41.03)},
                   {"attribution": "FABDEM / Copernicus DEM", "encoding": "terrarium"})
    log(f"arazi.pmtiles: {len(kayit)} karo, {os.path.getsize(hedef) / 1e6:.1f} MB")

# ---------------------------------------------------------------- 5) 4 MB parçalara böl
import json  # noqa: E402
KJ = os.path.join(CIKTI, "karolar.json")
boyut = json.load(open(KJ)) if os.path.exists(KJ) else {}
for ad in ("altlik.pmtiles", "rolyef.pmtiles", "arazi.pmtiles"):
    yol_ = os.path.join(CIKTI, ad)
    if not os.path.exists(yol_):
        continue
    veri = open(yol_, "rb").read()
    for eski in os.listdir(CIKTI):          # önceki çalıştırmadan kalan parçalar
        if eski.startswith(ad + "."):
            os.remove(os.path.join(CIKTI, eski))
    for i in range(0, len(veri), PARCA):
        open(f"{yol_}.{i // PARCA:03d}", "wb").write(veri[i:i + PARCA])
    log(f"{ad}: {math.ceil(len(veri) / PARCA)} parça ({len(veri):,} bayt)")
    boyut[ad] = {"bayt": len(veri), "parca": PARCA, "n": math.ceil(len(veri) / PARCA)}
    os.remove(yol_)
json.dump(boyut, open(KJ, "w"))
log("bitti")
