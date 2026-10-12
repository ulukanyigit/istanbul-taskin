# Faz 3 — DEM koşullandırma (12.10.2026)

Script: `01_dem_kosullandir.py` (OSGeo4W Python, ~75 sn, 2048 px karolar). Parametreler script başında ve
`data/interim/dem_kosullandirma_parametreler.json` içinde.

Kural: çukurlar toptan doldurulmaz (sonucun kendisi onlar). Yalnızca yapay setler kaldırılır, akış yolları
açılır, alt geçitler çukur olarak eklenir. Arazi hiçbir yerde yükseltilmez; tek istisna engel olarak binalar.

| İşlem | Kural | Etkilenen alan |
| --- | --- | ---: |
| Köprüler | Tampon içi nodata → çevreden enterpolasyon (≤400 m), yalnızca alçaltma | 6,4 km² |
| Binalar | +5 m (yol pikselleri hariç) | 187 km² |
| Yollar | −0,30 m, sınıfa göre 3–12 m yarım genişlik; köprü/tünel hariç | 383 km² |
| Açık dereler | OSM akış yönünde kayan medyan (7 örnek) + kümülatif minimum − derinlik (nehir 2 m, kanal 1,5 m, dere 1 m, drenaj 0,5 m); en fazla derinlik + 3 m | 43 km² |
| Menfez / kapalı dere | Aynı profil; `menfez_id_10m.tif` ile ayrıca kodlandı (tıkanma senaryosu) | 2,4 km² |
| Alt geçitler | Taban = iki uç arasında doğrusal zemin − 5 m, ~30 m genişlik; `altgecit_id_10m.tif` | 3,0 km² |
| Deniz | GLO30 su maskesi = 1 → nodata (çıkış) | 474 km² |
| Topografyası değişmiş olabilir | Ocak/döküm sahası, İstanbul Havalimanı, karada DEM < −2 m | 60,9 km² |

## Kalite kontrol (koşullu − FABDEM, m)

| İşlem | %1 | %10 | ortanca | %90 | %99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Köprü kaldırma | −5,75 | −1,98 | −0,48 | −0,05 | 0,00 |
| Açık dere | −5,28 | −2,75 | −1,02 | −0,95 | −0,48 |
| Menfez | −5,53 | −3,08 | −1,50 | −0,52 | −0,45 |
| Alt geçit | −12,1 | −7,0 | −5,26 | −4,31 | −2,29 |

İlk sürümde derelerin %1'i 11 m'den derin oyuluyordu (tek alçak DEM pikseli tüm kola yayılıyordu) ve eğimli
arazideki alt geçitler 20 m'ye kadar derin çıkıyordu; kayan medyan, oyma sınırı ve eğimli taban ile düzeltildi.

## Bilinen sınırlamalar

- 519 dere parçasında uçlar yokuş yukarı göründüğü için yön ters çevrildi. Düz arazide DEM gürültüsü yanlış
  çevirmeye yol açabilir; etkisi profili hafifçe düzleştirmekle sınırlı.
- Alt geçit rampaları ayrı modellenmedi (OSM tünel parçası genelde yalnızca kapalı kısım); hacim alttan tahmin.
- 10 m ızgarada dar sokaklar bina pikselleriyle kapanabilir; yollar binaları ezdiği için OSM'de çizili sokaklar açık.
- Bina avlularında sahte çukurlar oluşur → Faz 4'te tamamen bina pikselleriyle çevrili çukurlar elenecek.
- 30 m → 10 m bilineer örneklemenin ızgara izi hillshade'de görülebilir; analiz sonucuna etkisi küçük.
