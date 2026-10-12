# Faz 4 — Çukur ve dolma–taşma analizi (12.10.2026)

Senaryo: yağmur suyu drenajı tamamen devre dışı, yağış düzgün dağılımlı, akış süresi ihmal.

| Script | İş | Süre |
| --- | --- | ---: |
| `01_cukur_analizi.py` | Priority-Flood (numba) → çukurlar, havzalar, dolma–taşma ağacı, SCS-CN ile dolma eşiği | ~2 dk + poligon |
| `02_siniflandir.py` | Kategori, ilçe/mahalle (OSM), "ilk dolacaklar" listeleri | ~3 dk |

Kurulum: OSGeo4W Python'a `numba` ve `scikit-image` eklendi (`pip install ... -c numpy==1.26.4`; makinedeki
`CURL_CA_BUNDLE` geçersiz bir yolu gösterdiği için kurulum sürecinde bu değişken devre dışı bırakıldı).

## Sonuçlar

- 7.022 km² kara, 70,2 milyon piksel (10 m). Ham çukur 228.605 → süzgeç (≥10 cm derin, ≥300 m², ≥20 m³) sonrası **58.874**.
- Elenen: 5.409 bina avlusu, 303 göl/baraj, 502 "topografyası değişmiş" (maden/İGA).

İl içi kategoriler ve dolma eşikleri:

| Kategori | Çukur | ≤10 mm | ≤25 mm | ≤50 mm | ≤100 mm |
| --- | ---: | ---: | ---: | ---: | ---: |
| kentsel | 31.092 | 3.035 | 12.129 | 21.177 | 27.338 |
| alt geçit | 625 | 3 | 37 | 101 | 202 |
| dere/vadi seti | 1.256 | 335 | 846 | 1.100 | 1.182 |
| kırsal | 12.299 | | | | |

Çıktılar (`data/processed`): `cukur_id_10m.tif`, `havza_id_10m.tif`, `dolma_esigi_mm_10m.tif`, `cukurlar.gpkg`,
`cukurlar_sinifli.csv`, `hipsometri.npz`, `idari.gpkg`, `listeler.gpkg` (ilk_100_kentsel, ilk_50_dere_vadi).

## Gözle kontrol

- Sıra 1 (Pendik, Yeni Mah.): Pendik istasyonunun kuzeyinde, Marmaray demiryolu dolgusunun memba tarafında
  göllenme. Dolgu alt geçitler dışında suyu tutuyor; drenaj çalışmazsa beklenen bir davranış.
- Sıra 7 (Küçükçekmece, Atatürk Mah.): Halkalı Caddesi'nin İkitelli kavşağında Basın Ekspres altından geçtiği alt
  geçit; Ayamama Deresi'nin hemen yanında, 6.260 m³, 3 m derin, 9 mm'de doluyor. 2009 Ayamama selinin yaşandığı
  hatta denk gelmesi tutarlılık açısından olumlu.
- İlk 100 nokta yoğun kentsel çekirdekte (Bağcılar–Esenler–Bahçelievler, Kadıköy–Ataşehir, Kartal–Pendik kıyısı).

## Yorum ve sınırlamalar

- Eşiklerin düşük olması (ilk sıralar 7–9 mm) senaryodan kaynaklanıyor: drenaj sıfır, tüm akış yüzeyde.
  Gerçekte şebeke saatte onlarca mm'yi taşır; Faz 5'te drenaj kapasitesi parametresiyle bu kaydırılacak.
- Çukur içindeki alt-çukurlar ayrı izlenmiyor (bluespot basitleştirmesi); hacim–seviye eğrisi `hipsometri.npz`'de.
- Dere/vadi setlerinin bir kısmı OSM'de eksik menfezlerden kaynaklanabilir; bu liste "menfez tıkanırsa" ve
  "OSM'de menfez eksik mi?" sorularının ikisi için de aday listesi.
- 30 m kaynaklı DEM: 10 cm'lik çukur derinlikleri belirsiz; sıralama mutlak değerden daha güvenilir.

## Duyarlılık ve belirsizlik — `03_duyarlilik.py`, `04_duyarlilik_mahalle.py`

Her koşullandırma parametresi kendi maskesinde ölçeklenip (z = FABDEM + fark × k) analiz baştan yapıldı; temel çukurlar
varyanttaki en çok örtüşen çukurla eşlendi. Kontrol koşusu temeli birebir üretti.

| Senaryo | İlk 100'de kalan | ρ (tek çukur) | Mahalle ρ (25 mm) | İlk 50 mahalleden ortak |
| --- | ---: | ---: | ---: | ---: |
| bina +3 / +8 m | 98 / 100 | 0,99 / 1,00 | – | – |
| dere oyma ×0,5 / ×1,5 | 95 / 93 | 1,00 | – | – |
| alt geçit 3 / 7 m | 100 / 100 | 1,00 | – | – |
| yol −0,15 m | 19 | 0,19 | 0,94 | 40 |
| yol −0,50 m | 36 | 0,84 | 0,95 | 41 |
| DEM hatası σ 0,25 m (4 tekrar) | 17–26 | 0,41 | 0,90 | 35 |

Tek tek cadde çukurları yol alçaltma varsayımına ve DEM hatasına duyarlı; mahalle ve ilçe düzeyi dayanıklı.
Çıktılar: `duyarlilik.csv`, `duyarlilik_mahalle.json`, `duyarlilik_ozet.json`, `belirsizlik_cukur.csv` (her çukur için
çukur olma olasılığı ve eşiğin %10/%50/%90 değerleri). GEDI ile DEM hatası ölçülemedi (Earth Engine dışa aktarımı boş).
