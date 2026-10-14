"""Uyarı hattı için model eşiklerini paketler (bir kez, veri hattı çıktılarından çalıştırılır).

Girdi : data/processed (çukur tablosu, çukur kimlik rasterı, mahalle karnesi), data/interim (koşullu DEM, OSM)
Çıktı : uyari/veri/cukur.csv.gz      her çukur: konum, ilçe, mahalle, kategori, 10 cm ve 30 cm eşiği (mm)
        uyari/veri/mahalle.csv.gz    her mahalle: konum, nüfus, 25/50/100 mm maruziyeti

Eşik: drenajsız, düzgün yağışta çukurun en derin noktasında suyun 10 / 30 cm'ye ulaştığı toplam yağış.
Kullanım: python uyari/hazirla_esik.py <proje_kökü>
"""
import os, sys, types, json
import numpy as np, pandas as pd, geopandas as gpd, pyogrio, rasterio
from pyproj import Transformer

KOK = sys.argv[1] if len(sys.argv) > 1 else "."
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(KOK, "data", "processed"); I = os.path.join(KOK, "data", "interim")
_g = types.ModuleType("gdal"); _g.UseExceptions = lambda: None
class _DS:
    def __init__(s, p): s.p = p
    def GetGeoTransform(s):
        with rasterio.open(s.p) as d: return d.transform.to_gdal()
_g.Open = _DS
try:
    import osgeo  # noqa: F401
except ImportError:
    sys.modules["osgeo"] = types.ModuleType("osgeo"); sys.modules["osgeo"].gdal = _g; sys.modules["osgeo.gdal"] = _g
sys.path.insert(0, os.path.join(REPO, "pipeline", "maruziyet"))
from motor import Model

# bellek: tam rasterlar yerine yalnız çukur pikselleri
with rasterio.open(os.path.join(P, "cukur_id_10m.tif")) as d: cid = d.read(1); T = d.transform; W = d.width
idx = np.flatnonzero(cid); lab = cid.ravel()[idx].astype(np.int64); del cid
with rasterio.open(os.path.join(I, "dem_kosullu_10m.tif")) as d: zp = d.read(1).ravel()[idx].astype(np.float64)
with rasterio.open(os.path.join(P, "mahalle_id_10m.tif")) as d: mp = d.read(1).ravel()[idx]
m = Model(KOK); ids = np.arange(1, m.m + 1)
o = np.lexsort((zp, lab)); ilk = np.r_[0, np.flatnonzero(np.diff(lab[o])) + 1]
en = o[ilk]                                   # her çukurun en derin pikseli (lab sıralı)
mn = np.full(m.m + 1, np.nan); mn[lab[en]] = zp[en]
pix = np.zeros(m.m + 1, np.int64); pix[lab[en]] = idx[en]
mahp = np.zeros(m.m + 1, np.int64); mahp[lab[en]] = mp[en]
P10 = np.full(m.m + 1, 999.0); P30 = np.full(m.m + 1, 999.0)
for Pm in np.arange(1, 201, 1.0):
    d = np.nan_to_num(m.senaryo(Pm)["seviye"].astype(float) - mn, nan=0)
    P10[(P10 > 900) & (d >= 0.10)] = Pm; P30[(P30 > 900) & (d >= 0.30)] = Pm
r = pix[1:] // W; c = pix[1:] % W
x = T.c + (c + .5) * T.a; y = T.f + (r + .5) * T.e
lon, lat = Transformer.from_crs(5254, 4326, always_xy=True).transform(x, y)
t = pd.read_csv(os.path.join(P, "cukurlar_sinifli.csv")).set_index("cukur_id").reindex(ids)
df = pd.DataFrame({"id": ids, "lon": np.round(lon, 5), "lat": np.round(lat, 5), "mah": mahp[1:], "kat": t.kategori.values,
                   "p10": P10[1:], "p30": P30[1:], "hacim": t.hacim_m3.round(0).values,
                   "ok": ((t.il_ici == 1) & (t.guvenilir == 1)).values})
df = df[df.ok & df.kat.isin(["kentsel", "alt_gecit", "dere_vadi"]) & (df.p10 < 900)].drop(columns="ok")
# alt geçit adları: en derin noktaya 40 m içindeki OSM alt geçidi
ag = pyogrio.read_dataframe(os.path.join(I, "osm_istanbul.gpkg"), layer="alt_gecitler")
ag = ag[ag["name"].notna()]
a = df[df.kat == "alt_gecit"]
pts = gpd.GeoDataFrame(a[["id"]], geometry=gpd.points_from_xy(x[a.id - 1], y[a.id - 1]), crs=5254)
j = gpd.sjoin_nearest(pts, ag[["name", "geometry"]].to_crs(5254), max_distance=40, how="left").drop_duplicates("id")
df["ad"] = df.id.map(dict(zip(j.id, j["name"]))).fillna("")
os.makedirs(os.path.join(REPO, "uyari", "veri"), exist_ok=True)
df.to_csv(os.path.join(REPO, "uyari", "veri", "cukur.csv.gz"), index=False)
# mahalleler
mk = gpd.read_file(os.path.join(P, "mahalle_karnesi.gpkg"))
mk = mk[mk.istanbul == 1].copy()
rp = mk.geometry.representative_point().to_crs(4326)
cols = ["nufus", "bina"] + [f"{k}_{p}" for p in (25, 50, 100) for k in ("bina_10cm", "nufus_10cm", "kapali_yol_km")]
md = pd.DataFrame({"mah": mk.mahalle_fid.values, "ad": mk.mahalle.values, "ilce": mk.ilce.values,
                   "lon": rp.x.round(5).values, "lat": rp.y.round(5).values, "risk": mk.risk_indeksi.round(1).values,
                   "sicak": mk.sicak_nokta.values, **{k: mk[k].values for k in cols}})
md.to_csv(os.path.join(REPO, "uyari", "veri", "mahalle.csv.gz"), index=False)
print("çukur", len(df), "alt geçit", int((df.kat == "alt_gecit").sum()), "adlı", int((df.ad != "").sum()), "mahalle", len(md))
print("eşik dağılımı p30<=25:", int((df.p30 <= 25).sum()), " p30<=50:", int((df.p30 <= 50).sum()))
