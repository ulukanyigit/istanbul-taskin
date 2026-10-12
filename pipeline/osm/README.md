# Faz 2 — OSM vektör verisi (12.10.2026)

Kaynak: Geofabrik `turkey-latest.osm.pbf` (OSM verisi 8 Ekim 2026'ya kadar), analiz alanı kutusu.
Çıktı: `data/interim/osm_istanbul.gpkg` (EPSG:5254). Script: `01_osm_cikar.py` (~1 dakika).

| Katman | Kayıt | Not |
| --- | ---: | --- |
| yollar | 253.129 | ~55.700 km; köprü 378 km, tünel 182 km |
| dereler | 8.227 | açık 4.210 km, kapalı/menfez 177 km |
| menfezler | 2.318 | ortalama 76 m, en uzun 2,7 km (kapalı dere) |
| kopruler | 6.027 | DEM'den çıkarılacak setler |
| alt_gecitler | 1.374 | ≤250 m yol tünelleri + negatif katmanlı yollar |
| tuneller_uzun | 611 | yüzey çukuru değil, bilgi amaçlı |
| metro_girisleri | 573 | |
| kritik_tesisler | 4.217 | 482 hastane, 3.593 okul, 142 itfaiye |
| binalar | 892.299 | 231 km² taban alanı; kat bilgisi yalnızca %8,8'inde |
| ocaklar | 214 | 175 ocak (38,6 km²), 39 döküm sahası (7,6 km²) |
| havalimanlari | 8 | İstanbul Havalimanı OSM poligonu 19,9 km² |
| su_alanlari | 2.240 | |
| kiyi_cizgisi | 359 | deniz çıkışını tanımlamak için |

## Bulgular

1. **DEM'deki derin çukurlar OSM ocaklarıyla örtüşmüyor.** Karada −3 m'nin altındaki DEM piksellerinin
   yalnızca %4'ü bugünkü bir ocak poligonunun içinde; havalimanı poligonlarında hiç yok. WorldCover bu
   noktaları bugün çoğunlukla çayır/çıplak arazi gösteriyor. Yorum: DEM (TanDEM-X, ~2011–2015) maden
   çukurlarını, bu çukurlar sonradan doldurulmadan/rehabilite edilmeden önceki haliyle kaydetmiş.
   → Faz 3/4'te "topografyası değişmiş olabilir" maskesi: karada DEM < 0 m **veya** ocak/döküm sahası **veya**
   havalimanı. Bu maskeye değen çukurlar ilk 100 listesinden çıkarılır, haritada ayrı işaretlenir.
2. **Bina kat bilgisi seyrek (%8,8).** Dasimetrik nüfus dağıtımında kat sayısı yerine GHSL bina hacmi ya da
   taban alanı kullanılmalı.
3. Görsel kontrol (`qc/05_osm_ayamama.png`): Ayamama Deresi ve kollarındaki kapalı kesimler, D100 çevresindeki
   alt geçitler, köprüler ve metro girişleri doğru konumda.

İndirme notu: QGIS konsolundan arka planda indirildi (~20 dk). Ham GPKG `data/interim/osm_ham.gpkg` yeniden
çalıştırma için saklandı.
