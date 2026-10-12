# Faz 6 — Maruziyet, erişim ve mahalle karnesi (12.10.2026)

Senaryo: drenaj devre dışı, düzgün yağış (25 / 50 / 75 / 100 mm), akış süresi ihmal. Rakamlar il içi (958 mahalle).

| Script | İş |
| --- | --- |
| `motor.py` | Kova motoru (Python referansı): yerel SCS-CN akışı → taşma zinciri → hipsometriden su kotu. Faz 5'teki tarayıcı motoru bununla aynı sonucu vermeli. |
| `01_su_derinligi.py` | Senaryo başına 10 m su derinliği rasterı, `su_seviyeleri.csv` |
| `02_maruziyet.py` | Bina (duvarına değen su), yol (≥30 cm kapalı), hastane/okul/itfaiye/metro (30 m içinde ≥10 cm) |
| `03_erisim.py` | Yol ağı (1,3 milyon düğüm, 44.800 km), su basan kenarlar çıkarılarak en yakın hastaneye mesafe |
| `04_mahalle_karnesi.py` | Nüfus dağıtımı, mahalle göstergeleri, risk indeksi, Getis-Ord Gi* |

## Sonuçlar (il içi)

| | 25 mm | 50 mm | 100 mm |
| --- | ---: | ---: | ---: |
| Su altındaki alan | 43,9 km² | 65,8 km² | 76,3 km² |
| Duvarına ≥10 cm su değen bina | 80.106 | 100.067 | 109.083 |
| ≥30 cm (bodrum/zemin riski) | 30.424 | 55.092 | 71.031 |
| Bu binalarda yaşayan nüfus | 2,19 milyon | 2,57 milyon | 2,73 milyon |
| Hastane / okul / itfaiye | 126 / 700 / 19 | 149 / 767 / 24 | 151 / 795 / 25 |
| Metro girişi | 184 | 205 | 209 |
| Kapalı yol (ağ kenarı, orta nokta ≥30 cm)* | 193 km | 383 km | 532 km |
| Hastaneye ulaşamayan yol düğümü* | %1,0 | %2,3 | %3,4 |
| Yolu 1 km'den fazla uzayan düğüm* | %2,6 | %4,8 | %6,5 |

\* Erişim satırları analiz alanının tüm yol ağı için (il dışındaki havza kısımları dahil); mahalle düzeyindeki değerler `mahalle_karnesi.csv`'de.

Kapalı yol için iki ölçü var: ağ kenarlarının orta noktası (yukarıdaki, gerçekçi) ve su değen OSM yol parçasının
tamamı (`kapali_yol_km` sütunları, 50 mm'de 6.263 km — üst sınır, uzun parçalar tümüyle sayılıyor).

**En riskli mahalleler (50 mm):** Altıntepsi (Bayrampaşa), Sanayi (Güngören), Sultançiftliği (Sultangazi), Aksaray
(Fatih), Meclis (Sancaktepe). **Gi*:** 153 mahalle %99, 51 mahalle %95 güvenle sıcak noktada; ana küme
Bağcılar–Esenler–Bayrampaşa–Güngören–Zeytinburnu–Fatih kuşağı, ikinci küme Kadıköy kıyısı, üçüncüsü Ümraniye–Sancaktepe sınırı.
Etkilenen nüfusta ilk ilçeler: Bağcılar (246 bin), Sultangazi (160 bin), Küçükçekmece (148 bin), Ümraniye (136 bin).

## Yöntem notları ve sınırlamalar

- **"Duvarına su değen bina" bir maruziyet ölçüsüdür, hasar değil.** Binanın içine su girip girmediğini bilmiyoruz
  (eşik, bodrum, zemin kotu yok). Nüfus rakamları bu binalarda yaşayanların tamamıdır; üst sınır olarak okunmalı.
- **Nüfus:** GHS-POP 2020 il içinde 14,39 milyon veriyor (TÜİK ADNKS 2020: 15.462.452); ızgara ×1,075 ölçeklendi.
  GHS-POP 2025 projeksiyonu azalma gösterdiği için kullanılmadı. Nüfusun %82,7'si mahallelerdeki OSM binalarına
  dağıtılabildi; geri kalanı binası çizilmemiş hücrelerde kaldı → etkilenen nüfus ~%17 eksik tahmin olabilir.
- **Risk indeksi** 3 bileşenin il içi yüzdelik ortalaması: tehlike (ıslak alan oranı), maruziyet (etkilenen nüfus),
  erişim kaybı. Yaş, gelir gibi kırılganlık verileri mahalle düzeyinde açık olmadığından dahil edilmedi.
- **Erişim:** yönsüz ağ (tek yönlü yollar dikkate alınmadı); köprü/tünel kenarları hiç kapanmaz kabul edildi;
  482 hastaneden 473'ü ağa bağlandı (≤500 m).
- OSM'de 1 kritik tesisin geometrisi boştu (atlandı); birkaç bina geometrisi bozuktu (zarf merkezi kullanıldı).

## Kentleşme etkisi — `05_kentlesme.py`

1990 CN'si: bugün yapılaşmış (WorldCover 50) bir pikselin CN'si, 100 m hücredeki GHSL yapı alanı oranı
r = yapı₁₉₉₀ / yapı₂₀₂₀ ile bugünkü CN ve aynı toprak grubundaki çayır CN'si arasında karıştırılır. Çukurlar ve
dolma–taşma ağacı aynı, yalnız yüzey akışı değişir. 2020 eşikleri temel tabloyla %99,45 aynı çıktı (kayan nokta farkı).

| İl içi kentsel + alt geçit çukuru (31.717) | 1990 | 2020 |
| --- | ---: | ---: |
| 10 mm'de dolan | 1.673 | 3.038 |
| 25 mm'de dolan | 9.680 | 12.162 |
| 50 mm'de dolan | 19.422 | 21.278 |
| 50 mm yağışın yüzey akışı | 86,1 milyon m³ | 95,3 milyon m³ |

16.392 çukurun eşiği düştü (ortanca 7 mm). En çok düşen mahalleler (≥10 çukur, ortanca eşik): Sancaktepe Yunus Emre
81,5 → 45 mm; Büyükçekmece Alkent 2000 74,5 → 42; Esenyurt Aşık Veysel 67 → 34,5; Kartal Uğur Mumcu 54 → 23;
Başakşehir 82 → 51. Çıktılar: `kentlesme_cukur.csv`, `kentlesme_mahalle.csv`, `kentlesme_ozet.json`, `havza_cn_hist_1990.npy`.

## Menfez tıkanması — `06_menfez.py`

1.832 menfez / kapalı dere hattının 1.294'ü tıkanınca gölet üretiyor (1,2 km pencerede tarama). İl içinde kıyısında en
çok bina pikseli olan 30'u 4 km pencereyle ayrıntılı işlendi: gölet pikselleri ve hipsometrisi (taban = menfez açıkken
doldurulmuş yüzey), memba alanı (Priority-Flood yönlendirme ağacında akışı menfezden geçen pikseller), besleyen
çukurlar (taşma noktası membada, alıcısı mansapta) ve bina / yol / tesis temas eşikleri. Toplam gölet kapasitesi
0,60 milyon m³; en büyükleri Haramidere (115 bin m³) ve adsız bir derenin 408 m'lik kapalı kesimi (215 bin m³).
Çıktılar: `menfez_tarama.csv`, `menfez_senaryo.csv`, `menfez_senaryo.npz` (simülatöre `pipeline/web/08_senaryo_paket.py` ile girer).
