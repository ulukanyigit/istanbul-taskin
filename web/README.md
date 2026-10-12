# Faz 5 — Tarayıcı simülatörü

Tek sayfalık, sunucusuz bir uygulama. Kova motoru (`src/motor.js`) tarayıcıda bir Web Worker'da çalışır. Su, ayrı bir
WebGL2 bağlamında iki geçişte çizilir: (1) görünen bölgedeki çukur pikselleri bir derinlik dokusuna yazılır, (2) her
ekran pikseli bu dokudan çift doğrusal (çadır süzgeçli) okunur; kıyı çizgisi derinliğin sıfır eş-eğrisi olarak yumuşak
çıkar. Sonuç `su://z/x/y` iç protokolüyle raster karo olarak haritaya verilir, böylece 3B görünümde araziye serilir.
3B görünüm: arazi `arazi.pmtiles` (Terrarium, z8–12, 1,6× abartı), binalar OSM kat sayısından (yoksa 2 kat × 3,2 m). Altlık harita da projenin kendi OSM verisinden üretilir,
dış karo sunucusu gerekmez.

## Klasörler

| Yol | İçerik |
| --- | --- |
| `src/index.html` | Arayüz (HTML + CSS + uygulama kodu) |
| `src/motor.js` | Zaman adımlı kova motoru (`pipeline/maruziyet/motor.py`'nin karşılığı) |
| `public/veri/` | Veri paketi (`pipeline/web/05–07` üretir) |
| `test/motor_test.js` | motor.js ↔ motor.py karşılaştırması |
| `test/ekran_test.js` | Playwright ile ekran görüntüleri ve hata kontrolü |
| `build.py` | `dist/` klasörünü üretir (motor ve MapLibre CSS'i sayfaya gömer) |

## Veri paketini üretme

```bash
python pipeline/web/05_web_paket.py <proje_kökü> web/public/veri            # çukur modeli, pikseller, maruziyet çiftleri
python pipeline/web/06_altlik.py   <proje_kökü> web/public/veri <tippecanoe> # vektör altlık + arazi yükseklikleri (PMTiles, 2 MB parçalar)
python pipeline/web/07_web_ek.py   <proje_kökü> web/public/veri <fonts>      # mahalle karnesi, olaylar, yazı tipleri
python pipeline/web/08_senaryo_paket.py <proje_kökü> web/public/veri          # menfez göletleri, 1990 CN, belirsizlik
python pipeline/web/09_yagis_olaylari.py <proje_kökü> web/public/veri         # geçmiş yağış olayları
```

`08` öncesinde `pipeline/maruziyet/05_kentlesme.py`, `06_menfez.py` ve `pipeline/cukur/04_duyarlilik_mahalle.py`
çalışmış olmalı; `08` paketi yerinde genişlettiği için yeniden çalıştırmadan önce `05_web_paket.py` tekrar koşulur.

`06` için [tippecanoe](https://github.com/felt/tippecanoe) (derlenmiş klasörü) ve `pmtiles` Python paketi gerekir;
yazı tipleri [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets) deposundaki `fonts/`
klasöründen alınır (Noto Sans, OFL lisansı).

## Derleme, test, yayın

```bash
cd web && npm install            # maplibre-gl 4.7.1, pmtiles 3.2.1 (yalnız CSS ve yerel test için), playwright
python build.py                  # → dist/
node test/motor_test.js public/veri <su_seviyeleri.csv>
node test/duman_test.js           # hızlı: yükleniyor mu, hata var mı
node test/ekran_test.js /tmp/ekran # ekran görüntüleri (yazılım GPU'suyla yavaş)
node test/uc_test.js /tmp/uc [koyu] # yakın 2B ve 3B görünüm
```

`dist/` klasörü herhangi bir statik sunucuda (GitHub Pages dahil) olduğu gibi çalışır. İkili dosyalar (`.bin`, yazı tipleri, PMTiles parçaları) `dist/` içinde `.wasm` ekiyle yazılır: Claude artifact barındırıcısı yalnız bilinen web türlerini sunduğu için; sayfa aynı eki URL'lere ekler. GitHub Pages için `dist/`
içeriğini `gh-pages` dalına ya da `docs/` klasörüne koymak yeterli. Toplam ~50 MB; haritanın yalnız görülen
bölgesinin karo parçaları indirilir.

## Motor doğrulaması (12.10.2026)

| Kontrol | Sonuç |
| --- | --- |
| 58.874 çukurun su seviyesi, 25 / 50 / 100 mm (motor.py ile) | en büyük fark 0,8 cm (hipsometri cm'ye yuvarlandı) |
| Depolanan hacim | fark < 1 m³ (34,26 milyon m³, 50 mm) |
| Zaman adımlı (12 × 5 dk) son durum ↔ tek adım | birebir aynı |
| Bina ≥10 cm, 50 mm, il içi | 99.222 (motor.py ile aynı çiftlerden 99.215) |
| Kapalı yol, 50 mm | 383,1 km tüm alan (Faz 6: 383 km) |
| Kademe sırası JS ↔ Python | aynı |
| 1990: 25 mm'de dolan çukur (motor ↔ eşik tablosu) | 16.842 / 16.832 |
| Menfezler açıkken gölette su | yok; 100 mm'de 30 göletin 29'u doluyor |

Faz 6'daki bina sayısı (100.067) ile %0,85 fark var: bina rasterizasyonu burada rasterio ile yapıldı ve
bozuk geometriler düzeltildi.

## Senaryo varsayımları

- Yağış: toplam miktar, süre ve üçgen hiyetograf (tepe başta / ortada / sonda) ya da düzgün yağış; 5 dk adım.
- Drenaj kapasitesi: çukurun yerel havza alanı başına mm/sa; her adımda önce bu kadar su şebekeye gider.
- Alt geçit pompaları: alt geçit çukuru başına 0,5 m³/s ek boşaltım (varsayım).
- Boru patlaması: tıklanan noktanın 40 m havza ızgarasından bulunan çukura sabit debi.
- Menfez tıkanması: seçilen göletler (çukur kimliği m0+1…) su almaya başlar, besleyen çukurların alıcısı gölet olur;
  kademe sırası tarayıcıda yeniden hesaplanır.
- Arazi örtüsü 1990: yerel akış 1990 CN histogramıyla hesaplanır.
- Geçmiş olay: 5 dakikalık yağış serisi doğrudan motora verilir.
- Akış süresi ihmal edilir (taşan su aynı adımda alıcıya geçer); kanalizasyon geri tepmesi yok.
