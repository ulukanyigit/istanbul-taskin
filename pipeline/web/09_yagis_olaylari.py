"""Faz 1b/5f — IMERG 30 dakikalık seriden geçmiş yağış olayları kataloğu ve simülatör senaryoları.

Girdi: istanbul_taskin_gee/imerg_istanbul_30dk.csv (05_yagis_gedi.js): t (UTC), ort (il ortalaması, mm/sa),
       maks (il içindeki en yağışlı ~10 km hücre, mm/sa). Kuru adımlar dosyada yoktur.
Olay: en yağışlı hücre serisinde en az 6 saat kuru (< 0,5 mm/sa) aralıkla ayrılmış yağış dönemleri. En büyük toplam
yağışlı 15 olay ile haberlerde su baskını görülen günler (validation/olaylar.csv) kataloğa girer.
Simülatöre giden seri: en yağışlı hücrenin 30 dk yoğunlukları 5 dakikalık adımlara bölünür (adım başına mm).
Bu bilinçli bir seçim: kentsel baskınlar yerel sağanaklarla olur, il ortalaması onları siler. Model bu seriyi tüm
ile düzgün uygular; sonuç "fırtınanın merkezi her yerde olsaydı" diye okunmalıdır.

Ayrıca resmi açıklamalarda ölçülen ya da tahmin edilen yağışı belgelenmiş olaylar (AKOM, MGM, NASA) her durumda
kataloğa girer: toplam ve süre kaynaktan, zaman içindeki dağılım (üçgen hiyetograf) varsayımdır. IMERG serisi yoksa
(Earth Engine dışa aktarımı alınamadıysa) katalog yalnız bunlardan oluşur.

Çalıştırma: python 09_yagis_olaylari.py <proje_kökü> <veri_klasörü>
Çıktılar: <veri>/olaylar_yagis.json, <kök>/data/processed/yagis_olay_katalogu.csv
"""
import json
import os
import sys

import numpy as np
import pandas as pd

KOK, CIKTI = sys.argv[1], sys.argv[2]
BELGELI = [
    # ad, başlangıç, toplam mm, süre dk, desen, açıklama, kaynak
    ("8–9 Eylül 2009 · Ayamama selinin gecesi", "2009-09-08 22:00", 150, 480, "orta",
     "NASA TRMM: bölgede 125 mm'nin üstü, kıyıda 200 mm'ye yakın (2–9 Eylül); en yoğun yağış 8–9 Eylül gecesi. 150 mm / 8 saat canlandırmadır.",
     "https://earthobservatory.nasa.gov/images/40152/heavy-rain-in-istanbul"),
    ("25 Ekim 2017 · Çatalca", "2017-10-25 00:00", 137, 1440, "orta",
     "MGM Çatalca AWOS: günlük 137 kg/m². Gün içindeki dağılım varsayımdır.",
     "https://ipa.istanbul/wp-content/uploads/2024/03/KENT-GUNDEMI-ASIRI-YAGIS-VE-TASKIN-OLAYLARI.pdf"),
    ("15 Haziran 2021 · Şişli istasyonu", "2021-06-15 10:00", 47, 120, "basta",
     "AKOM: Şişli 47, Güngören 30 kg/m²; yağış 10:00 civarı başladı, öğlen saatlerinde etkili oldu. 18 noktada su baskını.",
     "https://ankahaber.net/haber/detay/istanbulda_en_cok_yagis_sisli_ve_gungoren_ilcelerinde_oldu_18_noktada_su_baskini_yasandi_43288"),
    ("5 Eylül 2023 · Arnavutköy", "2023-09-05 17:00", 128, 240, "orta",
     "AKOM: Arnavutköy 128, Çatalca 40, Beykoz 37 kg/m²; yağış 17:30'da şiddetlendi, 20:30'da su baskınları başladı.",
     "https://ipa.istanbul/wp-content/uploads/2023/09/05-06-Eylul-Taskin_IPA-Bilgi-Notu.pdf"),
    ("28 Eylül 2026 · AKOM tahmini üst sınır", "2026-09-28 00:00", 50, 720, "duzgun",
     "AKOM tahmini: günlük 20–50 kg/m², zaman zaman kuvvetli. Ölçüm değil, tahminin üst sınırı.",
     "https://www.haberler.com/haberler/istanbulu-saganak-vurdu-yol-coktu-alt-gecidi-su-20277507-haberi/"),
]


def ucgen(desen, x):
    """motor.js::birikimli ile aynı."""
    x = np.clip(x, 0, 1)
    if desen == "duzgun":
        return x
    r = {"basta": 0.25, "sonda": 0.75}.get(desen, 0.5)
    return np.where(x <= r, x * x / r, 1 - (1 - x) ** 2 / (1 - r))


cikti = []
for ad, bas_, P, sure, desen, aciklama, kaynak in BELGELI:
    n = sure // 5
    F = P * ucgen(desen, np.arange(n + 1) / n)
    seri = np.diff(F)
    cikti.append({"id": bas_[:10].replace("-", ""), "ad": ad, "baslangic": bas_, "sure_dk": int(sure), "toplam_mm": float(P),
                  "il_ortalama_mm": None, "tepe_1sa_mm": round(float(np.convolve(seri, np.ones(12), "valid").max() if n >= 12 else seri.sum()), 1),
                  "haber": True, "tur": "belgeli", "aciklama": aciklama, "kaynak": kaynak,
                  "seri": [round(float(x), 3) for x in seri]})

IMERG = os.path.join(KOK, "istanbul_taskin_gee", "imerg_istanbul_30dk.csv")
if not os.path.exists(IMERG):
    json.dump({"kaynak": "AKOM, MGM ve NASA açıklamaları (IMERG serisi alınamadı)", "olaylar": cikti},
              open(os.path.join(CIKTI, "olaylar_yagis.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for o in cikti:
        print(f"{o['ad']:>45}  {o['toplam_mm']:6.1f} mm  {o['sure_dk'] / 60:5.1f} sa  tepe 1 sa {o['tepe_1sa_mm']:5.1f} mm")
    sys.exit(0)

d = pd.read_csv(os.path.join(KOK, "istanbul_taskin_gee", "imerg_istanbul_30dk.csv"))
d["t"] = pd.to_datetime(d.t) + pd.Timedelta(hours=3)          # UTC → İstanbul (UTC+3)
d = d.sort_values("t").set_index("t")
tam = pd.date_range(d.index.min(), d.index.max(), freq="30min")
d = d.reindex(tam).fillna(0.0)
print(f"IMERG: {d.index.min()} – {d.index.max()}, {len(d):,} adım")

ISLAK, ARA = 0.5, 12                                          # mm/sa, 12 × 30 dk = 6 sa
islak = d.maks.values >= ISLAK
olay, bas, son_islak = [], None, None
for i, w in enumerate(islak):
    if w:
        if bas is None:
            bas = i
        son_islak = i
    elif bas is not None and i - son_islak >= ARA:
        olay.append((bas, son_islak)); bas = None
if bas is not None:
    olay.append((bas, son_islak))
kayit = []
for a, b in olay:
    s = d.iloc[a:b + 1]
    kayit.append({"bas": s.index[0], "son": s.index[-1] + pd.Timedelta(minutes=30), "sure_sa": len(s) / 2,
                  "toplam_maks_mm": s.maks.sum() / 2, "toplam_ort_mm": s.ort.sum() / 2,
                  "tepe_1sa_mm": float(s.maks.rolling(2, min_periods=1).mean().max()), "a": a, "b": b})
k = pd.DataFrame(kayit)
k.drop(columns=["a", "b"]).to_csv(os.path.join(KOK, "data", "processed", "yagis_olay_katalogu.csv"), index=False)
print(f"{len(k):,} yağış olayı")

haber = pd.read_csv(os.path.join(KOK, "validation", "olaylar.csv"))
haber_gun = sorted(set(pd.to_datetime(haber.tarih).dt.date))
sec = k.sort_values("toplam_maks_mm", ascending=False).head(15).copy()
sec["haber"] = False
for g in haber_gun:
    gun = k[(k.bas.dt.date <= g) & (k.son.dt.date >= g)]
    if len(gun):
        r = gun.sort_values("toplam_maks_mm", ascending=False).iloc[[0]].copy()
        r["haber"] = True
        sec = pd.concat([sec[~sec.bas.isin(r.bas)], r])
    else:
        print(f"uyarı: {g} haber olayı IMERG serisinde yok (veri aralığı dışında olabilir)")
sec = sec.sort_values("bas")
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
for _, r in sec.iterrows():
    s = d.iloc[int(r.a):int(r.b) + 1].maks.values
    s = s[: 48]                                               # en çok 24 saat
    seri5 = np.repeat(s / 12.0, 6)                            # mm/sa → 5 dk'lık mm
    cikti.append({"id": r.bas.strftime("%Y%m%d%H"), "ad": f"{r.bas.day} {AY[r.bas.month - 1]} {r.bas.year}",
                  "baslangic": r.bas.strftime("%Y-%m-%d %H:%M"), "sure_dk": int(len(seri5) * 5),
                  "toplam_mm": round(float(seri5.sum()), 1), "il_ortalama_mm": round(float(r.toplam_ort_mm), 1),
                  "tepe_1sa_mm": round(float(r.tepe_1sa_mm), 1), "haber": bool(r.haber), "tur": "imerg",
                  "aciklama": "IMERG, en yağışlı ~10 km hücre", "kaynak": "https://gpm.nasa.gov/data/imerg",
                  "seri": [round(float(x), 3) for x in seri5]})
json.dump({"kaynak": "NASA GPM IMERG V07 (30 dk, ~10 km)", "aralik": [str(d.index.min().date()), str(d.index.max().date())],
           "olaylar": cikti}, open(os.path.join(CIKTI, "olaylar_yagis.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
for o in cikti:
    print(f"{o['ad']:>20}  {o['toplam_mm']:6.1f} mm (il ort. {o['il_ortalama_mm']:5.1f})  tepe {o['tepe_1sa_mm']:5.1f} mm/sa  {o['sure_dk'] / 60:4.1f} sa  {'haber' if o['haber'] else ''}")
