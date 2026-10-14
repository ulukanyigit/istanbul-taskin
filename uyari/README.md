# Taşkın ön uyarısı (deneysel)

Simülatörün statik çukur modelini günlük yağış tahminiyle çalıştıran otomatik bir ön tarama.
Sonuç sayfası: https://ulukanyigit.github.io/istanbul-taskin/uyari.html

> **Resmi uyarı değildir.** Bu bir araştırma denemesidir. Resmi meteorolojik uyarılar MGM, AKOM ve AFAD tarafından yayımlanır.

## Akış

| Adım | Dosya | Ne yapar |
|---|---|---|
| 1. Eşikleri paketle (bir kez) | `hazirla_esik.py` | Her çukur için en derin noktada suyun 10 cm ve 30 cm'ye ulaştığı yağışı (drenajsız, düzgün yağış) hesaplar → `veri/cukur.csv.gz` (32.971 il içi kentsel / alt geçit / dere vadisi çukuru), `veri/mahalle.csv.gz` (958 mahalle, 25/50/100 mm maruziyeti) |
| 2. Tahmini çek | `calistir.py` | Open-Meteo'dan 0,1° ızgarada (çukurlara 6 km'den yakın 90 nokta) saatlik yağış: ECMWF IFS 0,25°, DWD ICON, NOAA GFS, Météo-France ARPEGE; dün + 3 gün |
| 3. Etkin yağış | `calistir.py` | Her saatten drenaj kapasitesi `D` düşülür: `max(r − D, 0)`. Şimdi ve sonrasında biten 24 saatlik pencerelerin en büyüğü alınır |
| 4. Eşik karşılaştırma | `calistir.py` | Her çukur en yakın ızgara noktasının etkin yağışını kendi eşiğiyle karşılaştırır; bir eşik **en az 2 model** aşıyorsa "aşıldı" sayılır |
| 5. Seviye | `calistir.py` | Mahalle seviyesi, bina/nüfus kestirimi, ilçe özeti → `web/dist/veri/uyari/latest.json`, `arsiv/`, `arsiv.json` |
| 6. Otomasyon | `.github/workflows/uyari.yml` | Günde 4 kez (TSİ 05, 11, 17, 23) çalışır, sonucu depoya yazar ve Pages'i yeniden yayımlar; ham tahmini 90 gün saklar |

## Seviye kuralları

| Seviye | Koşul (mahalle) |
|---|---|
| Sarı | En az bir çukur 10 cm'ye ulaşıyor |
| Turuncu | ≥3 kentsel çukur 30 cm'ye ulaşıyor **veya** ≥20 binanın duvarına ≥10 cm su değiyor |
| Kırmızı | Bir alt geçit 30 cm'ye ulaşıyor **veya** ≥100 binanın duvarına ≥10 cm su değiyor |

Bina ve nüfus kestirimi: mahallede eşiği aşan çukur sayısı, düzgün 25 / 50 / 100 mm senaryolarındaki çukur sayılarıyla
eşlenir ve o senaryoların maruziyeti (mahalle karnesi) aradeğerlenir. Yaklaşık bir büyüklük göstergesidir.

## Kalibrasyon: 14 Ekim 2026

Tek bir olayla yapıldı; yeni olaylar geldikçe güncellenecek. Haberlerde su baskını yazılan 18 yerden çukurla eşleşen 9 nokta
ve bunların düştüğü 16 mahalle kullanıldı. Tahmin girdisi, 14 Ekim öğleden sonra çekilen Open-Meteo verisi (önceki gün + 3 gün);
`--simdi 2026-10-14T06:00`. Saatler model analizine yakın olduğu için bu, gerçek bir "sabah verilen tahmin" testinden iyimserdir.

| D (mm/sa) | Olay mahallesi ≥ sarı | Tüm mahalleler ≥ sarı | Olay mahallesi ≥ turuncu | Tüm mahalleler ≥ turuncu | Olay çukuru 10 cm | Alt geçit 30 cm |
|---:|---:|---:|---:|---:|---:|---:|
| 4 | 100% | 74% | 88% | 51% | 9/9 | 108 |
| 5 | 81% | 52% | 75% | 27% | 8/9 | 56 |
| **6** | **75%** | **32%** | **69%** | **18%** | **7/9** | **26** |
| 7 | 69% | 27% | 56% | 12% | 5/9 | 16 |
| 8 | 31% | 14% | 6% | 3% | 2/9 | 9 |
| 10 | 0% | 8% | 0% | 1% | 0/9 | 6 |

`D = 6 mm/sa` olayların büyük kısmını yakalarken il genelinde uyarıyı üçte bire indiren noktadır (turuncu için 3,8 kat ayırma).
Simülatördeki "kısmen tıkalı şebeke" (10 mm/sa) değerinden düşüktür; çünkü 9–28 km'lik model ızgaraları konvektif yağışın
saatlik zirvelerini yayar. Bu değer fiziksel bir drenaj kapasitesi değil, tahmin verisine göre ayarlanmış bir parametredir.

Elle deneme:

```bash
python uyari/calistir.py                                   # canlı tahmin
python uyari/calistir.py --girdi tahmin.json.gz --simdi 2026-10-14T06:00 --drenaj 6
python uyari/calistir.py --kaydet tahmin.json.gz           # ham tahmini sakla
```

## Sınırlamalar

- Yağış modellerinin konum hatası mahalle ölçeğinden büyüktür; "bu mahalle" değil "bu bölge ve bu tür yerler" okunmalı.
- Model yalnız yüzeyde, çukurlarda biriken suyu hesaplar. Dere taşkını, akan sel (ör. 14 Ekim'de Esenyurt Dereyolu), kıyı ve
  kanalizasyon geri tepmesi kapsam dışıdır.
- Kırsal alt geçitlerin bir kısmı menfez ya da yol altı geçididir; adsız olanlar kontrol edilmeden yorumlanmamalıdır.
- Kalibrasyon tek olaya dayanır. Sonraki adımlar: geçmiş olaylarla geriye dönük test (IMERG + haber arşivi), çok olaylı
  `D` ve eşik ayarı, yağış ızgarasının simülatör motoruna verilmesi.
