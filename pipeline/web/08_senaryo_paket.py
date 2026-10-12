"""Faz 5e — Ek senaryoları web paketine ekler (05_web_paket.py'den hemen sonra çalıştırılır).

  * Menfez tıkanması: 06_menfez.py göletleri, çukur dizilerinin sonuna "menfez_golet" kategorisiyle eklenir
    (kimlik m0+1 … m0+K). Gölet pikselleri, maruziyet çiftleri ve besleyen çukurlar pakete girer; tarayıcı motoru
    yalnız etkin göletlere su verir ve onların besleyenlerinin taşmasını gölete yönlendirir.
  * 1990 arazi örtüsü: havza_cn_hist_1990.npy (05_kentlesme.py) seyrek CN histogramı ve 1990 dolma eşiği.
  * Belirsizlik: belirsizlik_cukur.csv (03_duyarlilik.py) → çukur olma olasılığı ve eşiğin %10–%90 aralığı.

Çalıştırma: python 08_senaryo_paket.py <proje_kökü> <veri_klasörü>
"""
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd
from pyproj import Transformer

KOK, CIKTI = sys.argv[1], sys.argv[2]
PR = os.path.join(KOK, "data", "processed")
meta = json.load(open(os.path.join(CIKTI, "meta.json"), encoding="utf-8"))
if "m0" in meta:
    sys.exit("Paket zaten genişletilmiş: önce 05_web_paket.py'yi yeniden çalıştırın.")


def oku(ad):
    ham = gzip.decompress(open(os.path.join(CIKTI, ad + ".bin"), "rb").read())
    return {k: np.frombuffer(ham, dtype=np.dtype(t), count=n, offset=o).copy() for k, (o, t, n) in meta["dosya"][ad].items()}


def yaz(ad, d):
    parca, tablo, n = [], {}, 0
    for k, a in d.items():
        a = np.ascontiguousarray(a)
        b = a.tobytes()
        tablo[k] = [n, a.dtype.str.lstrip("<|="), int(a.size)]
        pad = (-len(b)) % 4
        parca.append(b + b"\0" * pad)
        n += len(b) + pad
    open(os.path.join(CIKTI, ad + ".bin"), "wb").write(gzip.compress(b"".join(parca), 9, mtime=0))
    meta["dosya"][ad] = tablo
    print(f"{ad}.bin: {n / 1e6:.1f} MB ham")


M, Px, X = oku("model"), oku("piksel"), oku("maruz")
m0 = meta["m"]
n0 = int(M["ofset"][-1])
tesis = json.load(open(os.path.join(CIKTI, "tesisler.json"), encoding="utf-8"))
tm2ll = Transformer.from_crs("EPSG:5254", "EPSG:4326", always_xy=True)
CN_N = meta["cn_n"]

# ---------------------------------------------------------------- menfez göletleri
mz = np.load(os.path.join(PR, "menfez_senaryo.npz"))
mt = pd.read_csv(os.path.join(PR, "menfez_senaryo.csv"))
K = len(mz["kap"])
assert m0 + K < 65536
gid = np.arange(m0 + 1, m0 + K + 1)
p_ofs = mz["p_ofs"].astype(np.int64)
M["ofset"] = np.concatenate([M["ofset"], (n0 + p_ofs[1:]).astype(np.uint32)])
M["alici"] = np.concatenate([M["alici"], np.zeros(K, np.uint16)])
M["kap"] = np.concatenate([M["kap"], mz["kap"].astype(np.float32)])
M["taban"] = np.concatenate([M["taban"], mz["taban"].astype(np.float32)])
M["sira"] = np.concatenate([M["sira"], gid.astype(np.uint16)])
meta["kategori"] = meta["kategori"] + ["menfez_golet"]
M["kat"] = np.concatenate([M["kat"], np.full(K, len(meta["kategori"]) - 1, np.uint8)])
for k, v, dt in [("ilce", 0, np.uint8), ("mah", 0, np.uint16), ("il_ici", 1, np.uint8), ("esik", 301, np.uint16)]:
    M[k] = np.concatenate([M[k], np.full(K, v, dt)])
M["maks_der"] = np.concatenate([M["maks_der"], mt.maks_derinlik_m.values.astype(np.float32)])
M["yerel_havza"] = np.concatenate([M["yerel_havza"], (mt.memba_km2.values * 1e6).astype(np.float32)])
M["toplam_havza"] = np.concatenate([M["toplam_havza"], (mt.memba_km2.values * 1e6).astype(np.float32)])
cnh = mz["cn_hist"].astype(np.int64)
M["yerel_px"] = np.concatenate([M["yerel_px"], cnh.sum(1).astype(np.uint32)])
kod, say, ptr = [M["cn_kod"]], [M["cn_say"]], list(M["cn_ptr"])
son = int(M["cn_ptr"][-1])
for g in range(K):
    nz = np.flatnonzero(cnh[g])
    kod.append(nz.astype(np.uint8)); say.append(cnh[g, nz].astype(np.uint32))
    son += len(nz); ptr.append(son)
M["cn_kod"], M["cn_say"], M["cn_ptr"] = np.concatenate(kod), np.concatenate(say), np.array(ptr, np.uint32)
pr_, pc_ = mz["p_row"].astype(np.float64), mz["p_col"].astype(np.float64)
cx = [pc_[p_ofs[g]:p_ofs[g + 1]].mean() + 0.5 for g in range(K)]
cy = [pr_[p_ofs[g]:p_ofs[g + 1]].mean() + 0.5 for g in range(K)]
M["cx"] = np.concatenate([M["cx"], np.array(cx, np.float32)])
M["cy"] = np.concatenate([M["cy"], np.array(cy, np.float32)])
M["m_bes_ofs"] = mz["bes_ofs"].astype(np.uint32)
M["m_bes"] = mz["bes"].astype(np.uint16)
Px["col"] = np.concatenate([Px["col"], mz["p_col"]])
Px["row"] = np.concatenate([Px["row"], mz["p_row"]])
Px["dz"] = np.concatenate([Px["dz"], mz["p_dz"]])
# maruziyet: binalar (aynı bina hem çukura hem gölete değebilir → aynı indeks)
bn = pd.read_csv(os.path.join(PR, "bina_nufus.csv")).set_index("bina_fid")
kg = pd.read_csv(os.path.join(PR, "mahalle_karnesi.csv"))
ist = set(kg.loc[kg.istanbul == 1, "mahalle_fid"].astype(int))
fid2i = {int(f): i for i, f in enumerate(X["b_fid"])}
yeni_f, b_i_ek = [], []
for f in mz["b_fid"]:
    f = int(f)
    if f not in fid2i:
        fid2i[f] = len(X["b_fid"]) + len(yeni_f)
        yeni_f.append(f)
    b_i_ek.append(fid2i[f])
yeni_f = np.array(yeni_f, np.int64)
X["b_fid"] = np.concatenate([X["b_fid"], yeni_f.astype(np.uint32)])
X["b_nufus"] = np.concatenate([X["b_nufus"], bn.nufus.reindex(yeni_f).fillna(0).values.astype(np.float32)])
yeni_mah = bn.mahalle_fid.reindex(yeni_f).fillna(0).values.astype(np.int64)
X["b_mah"] = np.concatenate([X["b_mah"], yeni_mah.astype(np.uint16)])
X["b_ist"] = np.concatenate([X["b_ist"], np.isin(yeni_mah, list(ist)).astype(np.uint8)])
X["b_i"] = np.concatenate([X["b_i"], np.array(b_i_ek, np.uint32)])
X["b_cuk"] = np.concatenate([X["b_cuk"], (m0 + 1 + mz["b_g"]).astype(np.uint16)])
X["b_dz"] = np.concatenate([X["b_dz"], mz["b_dz"]])
X["y_cuk"] = np.concatenate([X["y_cuk"], (m0 + 1 + mz["y_g"]).astype(np.uint16)])
X["y_dz"] = np.concatenate([X["y_dz"], mz["y_dz"]])
X["y_uz"] = np.concatenate([X["y_uz"], mz["y_uz"]])
X["y_ist"] = np.concatenate([X["y_ist"], np.ones(len(mz["y_g"]), np.uint8)])
# tesisler: koordinatla eşle
tl = np.array([[t["lon"], t["lat"]] for t in tesis])
ti, tg, tdz = [], [], []
for (x, y), g, dz in zip(mz["t_xy"], mz["t_g"], mz["t_dz"]):
    lon, lat = tm2ll.transform(x, y)
    j = int(np.argmin(np.hypot(tl[:, 0] - lon, tl[:, 1] - lat)))
    if np.hypot(tl[j, 0] - lon, tl[j, 1] - lat) < 2e-5:
        ti.append(j); tg.append(m0 + 1 + g); tdz.append(dz)
X["t_i"] = np.concatenate([X["t_i"], np.array(ti, np.uint32)])
X["t_cuk"] = np.concatenate([X["t_cuk"], np.array(tg, np.uint16)])
X["t_dz"] = np.concatenate([X["t_dz"], np.array(tdz, np.uint16)])
print(f"menfez: {K} gölet, {int(p_ofs[-1])} piksel, {len(mz['b_g'])} bina çifti ({len(yeni_f)} yeni bina), "
      f"{len(mz['y_g'])} yol kenarı, {len(ti)} tesis")
menfez_bilgi = []
for _, r in mt.iterrows():
    lon, lat = tm2ll.transform(r.x, r.y)
    menfez_bilgi.append({"osm": int(r.menfez), "ad": r.ad if isinstance(r.ad, str) else "", "tur": r.tur,
                         "uzunluk_m": round(float(r.uzunluk_m)), "hacim_m3": round(float(r.hacim_m3)),
                         "maks_derinlik_m": round(float(r.maks_derinlik_m), 2), "memba_km2": round(float(r.memba_km2), 2),
                         "besleyen": int(r.besleyen), "lon": round(lon, 6), "lat": round(lat, 6)})

# ---------------------------------------------------------------- 1990 arazi örtüsü
h90 = np.load(os.path.join(PR, "havza_cn_hist_1990.npy")).astype(np.int64)
h90 = np.concatenate([h90, cnh])                    # göletlerin memba histogramı değişmeden
nz_b, nz_c = np.nonzero(h90)
p90 = np.zeros(len(h90) + 1, np.uint32)
np.add.at(p90, nz_b + 1, 1)
M["cn90_ptr"] = np.cumsum(p90).astype(np.uint32)
M["cn90_kod"] = nz_c.astype(np.uint8)
M["cn90_say"] = h90[nz_b, nz_c].astype(np.uint32)
ke = pd.read_csv(os.path.join(PR, "kentlesme_cukur.csv")).set_index("cukur_id")
e90 = np.full(m0 + K + 1, 301, np.uint16)
e90[ke.index.values] = np.clip(ke.esik_1990_mm.values, 0, 301)
M["esik90"] = e90
koz = json.load(open(os.path.join(PR, "kentlesme_ozet.json"), encoding="utf-8"))

# ---------------------------------------------------------------- belirsizlik
bel_yol = os.path.join(PR, "belirsizlik_cukur.csv")
if os.path.exists(bel_yol):
    bc = pd.read_csv(bel_yol).set_index("cukur_id")
    ol = np.full(m0 + K + 1, 255, np.uint8); p10 = np.zeros(m0 + K + 1, np.uint16); p90_ = np.zeros(m0 + K + 1, np.uint16)
    ol[bc.index.values] = np.round(bc.cukur_olasiligi.values * 100).astype(np.uint8)
    p10[bc.index.values] = bc.esik_p10_mm.values
    p90_[bc.index.values] = bc.esik_p90_mm.values
    M["bel_olas"], M["bel_p10"], M["bel_p90"] = ol, p10, p90_
    print("belirsizlik eklendi")
duy_yol = os.path.join(PR, "duyarlilik_ozet.json")
duy = json.load(open(duy_yol, encoding="utf-8")) if os.path.exists(duy_yol) else None

yaz("model", M); yaz("piksel", Px); yaz("maruz", X)
meta.update({"m0": m0, "m": m0 + K, "n_px": int(M["ofset"][-1]), "menfez": menfez_bilgi, "kentlesme": koz, "duyarlilik": duy})
json.dump(meta, open(os.path.join(CIKTI, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), default=float)
print("meta.json güncellendi")
