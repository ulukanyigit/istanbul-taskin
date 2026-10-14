"""İstanbul taşkın erken uyarı — günlük çalıştırma.

1. Open-Meteo'dan İstanbul üzerindeki 0,1° ızgara için saatlik yağış tahmini (dört model) çekilir.
2. Her ızgara noktasında, drenaj kapasitesini aşan yağış (mm/sa) kayan 24 saatlik pencerede toplanır.
3. Her çukur en yakın ızgara noktasının yağışıyla kendi 10 cm / 30 cm eşiğiyle karşılaştırılır.
4. Mahalle, ilçe ve il özetleri, alt geçit listesi ve uyarı seviyeleri JSON'a yazılır.

Kullanım:
  python uyari/calistir.py                      # canlı: Open-Meteo'dan çeker
  python uyari/calistir.py --girdi tahmin.json  # kayıtlı tahminle (test / geçmiş olay)
  python uyari/calistir.py --simdi 2026-10-14T06:00 --drenaj 10

Bu bir ön tarama göstergesidir; resmi uyarı AKOM ve AFAD tarafından verilir.
"""
import argparse, datetime as dt, gzip, json, os, sys, time, urllib.request, urllib.parse
import numpy as np, pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERI = os.path.join(KOK, "uyari", "veri")
CIKTI = os.path.join(KOK, "web", "dist", "veri", "uyari")
MODELLER = ["ecmwf_ifs025", "icon_seamless", "gfs_seamless", "meteofrance_seamless"]
MODEL_AD = {"ecmwf_ifs025": "ECMWF", "icon_seamless": "ICON", "gfs_seamless": "GFS", "meteofrance_seamless": "ARPEGE"}
API = "https://api.open-meteo.com/v1/forecast"
TZ = dt.timezone(dt.timedelta(hours=3))

# uyarı kuralları (kalibrasyon: uyari/README.md)
SEVIYE_AD = ["yok", "sarı", "turuncu", "kırmızı"]
MIN_MODEL = 2            # bir eşiğin "aşıldı" sayılması için en az kaç modelin aşması gerekir
TURUNCU_CUKUR = 3        # mahallede 30 cm'ye ulaşan kentsel çukur sayısı
TURUNCU_BINA, KIRMIZI_BINA = 20, 100


def izgara(c):
    """Çukurların 6 km yakınındaki 0,1° ızgara noktaları."""
    la = np.round(np.arange(40.80, 41.61, 0.1), 2); lo = np.round(np.arange(27.95, 29.96, 0.1), 2)
    LA, LO = np.meshgrid(la, lo, indexing="ij"); LA, LO = LA.ravel(), LO.ravel()
    d = np.min(np.hypot((c.lat.values[None, :] - LA[:, None]) * 111, (c.lon.values[None, :] - LO[:, None]) * 84), axis=1)
    k = d < 6
    return LA[k], LO[k]


def cek(lat, lon, past_days=1, forecast_days=3):
    """Open-Meteo'dan toplu çekim; dönen: {model: dizi[nokta, saat]}, saatler."""
    out = {m: [] for m in MODELLER}; saat = None
    for i in range(0, len(lat), 50):
        q = {"latitude": ",".join(f"{v:.2f}" for v in lat[i:i + 50]), "longitude": ",".join(f"{v:.2f}" for v in lon[i:i + 50]),
             "hourly": "precipitation", "models": ",".join(MODELLER), "past_days": past_days, "forecast_days": forecast_days,
             "timezone": "Europe/Istanbul"}
        url = API + "?" + urllib.parse.urlencode(q)
        for deneme in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    js = json.loads(r.read()); break
            except Exception as e:  # noqa: BLE001
                if deneme == 3: raise
                time.sleep(5 * (deneme + 1))
        js = js if isinstance(js, list) else [js]
        for o in js:
            saat = o["hourly"]["time"]
            for m in MODELLER:
                v = o["hourly"].get(f"precipitation_{m}")
                out[m].append([np.nan if x is None else x for x in v] if v else [np.nan] * len(saat))
    return {m: np.array(v, float) for m, v in out.items()}, saat


def hesapla(R, saat, simdi, drenaj):
    """R: {model: [nokta, saat]} → nokta×model etkin yağış (en yüksek 24 sa, şimdi ve sonrası biten), zirve saati."""
    t = pd.to_datetime(saat)
    ileri = np.asarray(t >= pd.Timestamp(simdi.replace(tzinfo=None)).floor("h"))
    sonuc, toplam, zirve = {}, {}, {}
    for m, A in R.items():
        if np.all(np.isnan(A)): continue
        e = np.maximum(np.nan_to_num(A) - drenaj, 0)
        cs = np.cumsum(e, axis=1); cs = np.concatenate([np.zeros((len(e), 1)), cs], axis=1)
        k = 24; s24 = cs[:, k:] - cs[:, :-k]                    # pencere [j, j+24) → bitiş j+23
        bitis_ileri = ileri[k - 1:]
        s24 = np.where(bitis_ileri[None, :], s24, 0)
        sonuc[m] = s24.max(axis=1)
        toplam[m] = np.nan_to_num(A)[:, ileri][:, :48].sum(axis=1)
        zirve[m] = np.array(t)[ileri][np.argmax(np.nan_to_num(A)[:, ileri][:, :48], axis=1)]
    return sonuc, toplam, zirve


def yakin(lat, lon, glat, glon):
    d = (lat[:, None] - glat[None, :]) ** 2 + ((lon[:, None] - glon[None, :]) * 0.75) ** 2
    return np.argmin(d, axis=1)


def etki(k, K, B):
    """k: mahallede şu an 10 cm'ye ulaşan çukur sayısı; K: 25/50/100 mm'deki sayılar; B: o senaryolardaki bina/nüfus.
    Sayı ekseninde parçalı doğrusal (0→0), 100 mm üstü sabit."""
    k = np.asarray(k, float); K = [np.asarray(v, float) for v in K]; B = [np.asarray(v, float) for v in B]
    out = np.zeros(len(k)); x0 = np.zeros(len(k)); y0 = np.zeros(len(k)); bitti = np.zeros(len(k), bool)
    for x1, y1 in zip(K, B):
        on = ~bitti & (k <= x1)
        w = np.where(x1 > x0, (k - x0) / np.maximum(x1 - x0, 1e-9), 1.0)
        out[on] = (y0 + (y1 - y0) * w)[on]; bitti |= on; x0, y0 = x1, y1
    out[~bitti] = y0[~bitti]
    return np.maximum(out, 0)


def calistir(R, saat, glat, glon, simdi, drenaj, c, mh):
    modeller = [m for m in MODELLER if m in R and not np.all(np.isnan(R[m]))]
    S, TOP, Z = hesapla({m: R[m] for m in modeller}, saat, simdi, drenaj)
    gc = yakin(c.lat.values, c.lon.values, glat, glon); gm = yakin(mh.lat.values, mh.lon.values, glat, glon)
    Pc = np.stack([S[m][gc] for m in modeller], 1)              # çukur × model
    n30 = (Pc >= c.p30.values[:, None]).sum(1); n10 = (Pc >= c.p10.values[:, None]).sum(1)
    Pm = np.stack([S[m][gm] for m in modeller], 1); Pmed = np.median(Pm, 1)
    mh = mh.copy(); mh["P"] = Pmed
    c = c.copy(); c["n30"] = n30; c["n10"] = n10; c["P"] = np.median(Pc, 1)
    asan30 = c[c.n30 >= MIN_MODEL]; asan10 = c[c.n10 >= MIN_MODEL]
    # etki: mahallede 10 cm'ye ulaşan çukur sayısı, düzgün 25/50/100 mm senaryolarındaki sayılarla eşlenir
    # (eşik altında doğrusal-sıfırdan değil, çukur sayısı oranıyla ölçeklenir)
    k = mh.mah.map(asan10.groupby("mah").size()).fillna(0).values
    K = [mh.mah.map(c[c.p10 <= p].groupby("mah").size()).fillna(0).values for p in (25, 50, 100)]
    mh["b10"] = etki(k, K, [mh.bina_10cm_25, mh.bina_10cm_50, mh.bina_10cm_100])
    mh["n10"] = etki(k, K, [mh.nufus_10cm_25, mh.nufus_10cm_50, mh.nufus_10cm_100])
    ag = asan30[asan30.kat == "alt_gecit"].groupby("mah").size()
    kc = asan30[asan30.kat == "kentsel"].groupby("mah").size()
    s10 = asan10.groupby("mah").size()
    sev = np.zeros(len(mh), int)
    sev[mh.mah.map(s10).fillna(0).values > 0] = 1
    sev[(mh.mah.map(kc).fillna(0).values >= TURUNCU_CUKUR) | (mh.b10.values >= TURUNCU_BINA)] = 2
    sev[(mh.mah.map(ag).fillna(0).values > 0) | (mh.b10.values >= KIRMIZI_BINA)] = 3
    mh["sev"] = sev
    mah_ad = mh.set_index("mah")
    def nokta_kaydi(r):
        ma = mah_ad.loc[r.mah] if r.mah in mah_ad.index else None
        return {"id": int(r.id), "lon": r.lon, "lat": r.lat, "ad": r.ad if isinstance(r.ad, str) and r.ad else None,
                "mahalle": ma.ad if ma is not None else None, "ilce": ma.ilce if ma is not None else None,
                "kat": r.kat, "p10": r.p10, "p30": r.p30, "yagis": round(float(r.P), 1), "n30": int(r.n30), "n10": int(r.n10)}
    altg = [nokta_kaydi(r) for r in asan30[asan30.kat == "alt_gecit"].sort_values(["n30", "p30"], ascending=[False, True]).itertuples()]
    kent = [nokta_kaydi(r) for r in asan30[asan30.kat != "alt_gecit"].sort_values(["n30", "p30"], ascending=[False, True]).head(400).itertuples()]
    il = mh.groupby("ilce").agg(yagis=("P", "max"), seviye=("sev", "max"), bina=("b10", "sum"), nufus=("n10", "sum")).reset_index()
    il = il.sort_values(["seviye", "bina"], ascending=False)
    # şehir geneli saatlik seri (ızgara ortalaması, model başına)
    t = pd.to_datetime(saat); ileri = np.asarray(t >= pd.Timestamp(simdi.replace(tzinfo=None)).floor("h"))
    i0 = max(int(np.argmax(ileri)) - 24, 0)
    seri = {"saat": [s for s in saat[i0:i0 + 72]], **{MODEL_AD[m]: np.round(np.nanmean(R[m][:, i0:i0 + 72], 0), 2).tolist() for m in modeller}}
    zirve_m = {MODEL_AD[m]: round(float(np.nanmax(TOP[m])), 1) for m in modeller}
    sonuc = {
        "uretim": dt.datetime.now(TZ).isoformat(timespec="minutes"), "simdi": simdi.isoformat(timespec="minutes"),
        "kaynak": "Open-Meteo (" + ", ".join(MODEL_AD[m] for m in modeller) + ")", "modeller": [MODEL_AD[m] for m in modeller],
        "drenaj_mmsa": drenaj, "min_model": MIN_MODEL,
        "not": "Ön tarama göstergesidir, resmi uyarı değildir. Model yüzeyde biriken suyu hesaplar; akan sel ve kanalizasyon geri tepmesi yoktur.",
        "il": {"seviye": int(sev.max()), "kirmizi": int((sev == 3).sum()), "turuncu": int((sev == 2).sum()), "sari": int((sev == 1).sum()),
               "bina_10cm": int(mh.b10.sum()), "nufus_10cm": int(mh.n10.sum()),
               "alt_gecit_30cm": len(altg), "cukur_30cm": int(len(asan30)),
               "yagis_48sa_en_cok": zirve_m, "etkin_24sa_medyan_en_cok": round(float(Pmed.max()), 1)},
        "ilceler": [{"ilce": r.ilce, "seviye": int(r.seviye), "yagis": round(float(r.yagis), 1), "bina": int(r.bina), "nufus": int(r.nufus)} for r in il.itertuples()],
        "mahalle": {str(int(r.mah)): [int(r.sev), round(float(r.P), 1), int(r.b10), int(r.n10), r.ad, r.ilce] for r in mh.itertuples() if r.sev > 0 or r.P > 0.5},
        "alt_gecitler": altg, "noktalar": kent, "seri": seri,
        "izgara": [{"lat": float(a), "lon": float(b), **{MODEL_AD[m]: round(float(TOP[m][i]), 1) for m in modeller}} for i, (a, b) in enumerate(zip(glat, glon))],
    }
    return sonuc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--girdi"); ap.add_argument("--kaydet"); ap.add_argument("--simdi"); ap.add_argument("--drenaj", type=float, default=6.0)
    ap.add_argument("--cikti", default=CIKTI); ap.add_argument("--etiket", help="ör. geriye dönük test")
    a = ap.parse_args()
    c = pd.read_csv(os.path.join(VERI, "cukur.csv.gz")); mh = pd.read_csv(os.path.join(VERI, "mahalle.csv.gz"))
    simdi = dt.datetime.fromisoformat(a.simdi).replace(tzinfo=TZ) if a.simdi else dt.datetime.now(TZ)
    if a.girdi:
        js = json.load(gzip.open(a.girdi) if a.girdi.endswith(".gz") else open(a.girdi))
        glat, glon, saat = np.array(js["lat"]), np.array(js["lon"]), js["saat"]
        R = {m: np.array(js["R"][m], float) for m in js["R"]}
    else:
        glat, glon = izgara(c)
        R, saat = cek(glat, glon)
    if a.kaydet:
        json.dump({"lat": glat.tolist(), "lon": glon.tolist(), "saat": saat, "R": {m: np.round(np.nan_to_num(v, nan=-1), 2).tolist() for m, v in R.items()}},
                  gzip.open(a.kaydet, "wt"))
    for m in list(R): R[m] = np.where(R[m] < 0, np.nan, R[m])
    s = calistir(R, saat, glat, glon, simdi, a.drenaj, c, mh)
    if a.etiket: s["etiket"] = a.etiket
    os.makedirs(os.path.join(a.cikti, "arsiv"), exist_ok=True)
    json.dump(s, open(os.path.join(a.cikti, "latest.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    ad = simdi.strftime("%Y-%m-%dT%H")
    json.dump({k: s[k] for k in ("uretim", "simdi", "kaynak", "drenaj_mmsa", "il", "ilceler")}, open(os.path.join(a.cikti, "arsiv", ad + ".json"), "w"), ensure_ascii=False)
    idx_yol = os.path.join(a.cikti, "arsiv.json")
    idx = json.load(open(idx_yol)) if os.path.exists(idx_yol) else []
    idx = [x for x in idx if x["ad"] != ad] + [{"ad": ad, "seviye": s["il"]["seviye"], "alt_gecit": s["il"]["alt_gecit_30cm"], "bina": s["il"]["bina_10cm"]}]
    json.dump(sorted(idx, key=lambda x: x["ad"])[-120:], open(idx_yol, "w"), ensure_ascii=False)
    il = s["il"]
    ozet = (f"## İstanbul taşkın ön uyarısı — {s['simdi']}\n\n"
            f"Seviye: **{SEVIYE_AD[il['seviye']]}** · kırmızı {il['kirmizi']}, turuncu {il['turuncu']}, sarı {il['sari']} mahalle\n\n"
            f"48 saatlik en yüksek yağış (ızgara, model): " + ", ".join(f"{k} {v} mm" for k, v in il["yagis_48sa_en_cok"].items()) + "\n\n"
            f"30 cm'ye ulaşan alt geçit: {il['alt_gecit_30cm']} · duvarına ≥10 cm su değen bina: {il['bina_10cm']:,}\n".replace(",", "."))
    print(ozet)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(ozet)


if __name__ == "__main__":
    main()
