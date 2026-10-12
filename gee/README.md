# Faz 1 — Earth Engine girdileri

Proje: `tasma-511107` (noncommercial, Community Tier)
Izgara: TUREF / TM30 (EPSG:5254), sabit hizalı `crsTransform`; yükseklikler EGM2008.

Her script iki sürümde var; ikisi aynı çıktıyı üretir:

- `code_editor/*.js` → tarayıcıda, kurulum yok (önerilen başlangıç)
- `*.py` → bilgisayarında Python ile (ileride pipeline'a bağlamak için)

## A) Code Editor ile (tarayıcı)

1. code.earthengine.google.com adresini aç.
2. Sağ üstteki profil simgesinden projeyi **tasma-511107** seç.
3. Ortadaki kod alanına `01_aoi.js` içeriğini yapıştır → **Run**.
4. Konsolda (sağda) "İl kaydı sayısı: 1" ve alan değerlerini, haritada analiz alanını kontrol et.
5. Sağdaki **Tasks** sekmesinde üç görev turuncu görünür. Her birinde **RUN** → açılan pencerede **Run**.
6. `istanbul_taskin_aoi_asset` görevi mavi tik (Completed) olunca `02_dem.js` ve `03_arazi_cn.js` için 3–5. adımları tekrarla (her biri ayrı script olarak kaydedilir).

İpucu: Scripts sekmesinde **NEW → File** ile `01_aoi` ve `02_dem` adlarıyla kaydedersen kod kaybolmaz.

## B) Python ile

```bash
conda create -n taskin python=3.11 -y
conda activate taskin
pip install earthengine-api
earthengine authenticate
cd gee
python 01_aoi.py
# Tasks'ta 'istanbul_taskin_aoi_asset' Completed olunca:
python 02_dem.py
```

Python sürümünde görevler kendiliğinden başlar, RUN'a basmak gerekmez.

## Çıktılar

Google Drive → `istanbul_taskin_gee/`

| Dosya | İçerik |
| --- | --- |
| istanbul_il_siniri.geojson | İl sınırı |
| aoi_havzalar.geojson | Analiz alanındaki havzalar |
| fabdem_10m*.tif | Ana DEM, 10 m (birkaç parça olabilir → QGIS'te Sanal Raster) |
| glo30_eksi_fabdem_30m.tif | Bina/ağaç düzeltmesinin büyüklüğü |
| glo30_su_maskesi_30m.tif | 0 kara, 1 deniz, 2 göl, 3 nehir |
| worldcover_10m.tif | ESA WorldCover 2021 arazi örtüsü sınıfları |
| cn_10m.tif | SCS eğri numarası (30–100) |
| hsg_250m.tif | Hidrolojik toprak grubu (1=A … 4=D) |
| ghsl_yapi_1990_2020_100m.tif | Yapılaşmış yüzey oranı: 1990, 2020, fark |

## Kontrol listesi (QGIS) — 12.10.2026 tamamlandı

- [x] Tüm rasterler EPSG:5254; 10 m katmanlar aynı ızgara (19050 × 10027), 30/100/250 m katmanlar aynı orijinde iç içe
- [x] Analiz alanı il sınırını ve sınırı kesen havzaları kapsıyor (il içi ~5.226 km²)
- [x] `fabdem_10m` tek parça indi; il sınırı içinde DEM boşluğu yok
- [x] GLO30 − FABDEM sınıfa göre mantıklı: ağaç ortanca 5,2 m, yapılaşmış 2,7 m, tarım ~0, su 0
- [x] Su maskesi: AOI içinde deniz ~461 km², göl ~110 km²; WorldCover suyu ile uyumlu
- [x] CN 55–100, ortalama 80,4; tabloda karşılığı olmayan piksel 0

### Sonraki adımlara taşınan bulgular

1. **AOI maskesi olarak `cn_10m > 0` kullan.** GEE maskeli pikselleri beklenen nodata ile yazmadı:
   DEM'de AOI dışı `NaN` (−9999 değil), su maskesinde AOI dışı `0` (255 değil, yani "kara" gibi görünüyor).
2. **DEM boşluğu ~31 km²:** tamamı il sınırı dışında, AOI kenarının 370 m yakınında (tampon şeridi). Havza
   sırtlarında olduğu için akışı etkilemez; gerekirse GLO30 ile doldurulur.
3. **Negatif kotlar = açık ocaklar.** Kemerburgaz–Ağaçlı (41,31K 28,77D, −25 m), 41,27K 28,92D (−26 m),
   41,13K 29,29D (−34 m). Bunlar çukur analizinde en büyük "çukurlar" olarak çıkacak; OSM `landuse=quarry`
   ile maskelenip tehlike listesinden çıkarılmalı (Faz 2–3).
4. **GHSL'de çok küçük negatif değerler (≥ −0,02):** kullanırken 0'a kırp.

QGIS projesi: `tasma_calisma\istanbul_taskin.qgz` · kontrol görüntüleri: `tasma_calisma\qc\`

Not: Plandaki 03_landcover, 04_impervious ve 05_soil_cn tek scriptte (`03_arazi_cn`) birleştirildi.

Sıradaki: 06_rain_events · 07_validation
