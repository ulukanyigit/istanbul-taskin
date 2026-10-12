// =====================================================================
// 03_arazi_cn — Arazi örtüsü, geçirimsizlik (1990/2020) ve SCS-CN rasterı
// Earth Engine Code Editor. Run → Tasks'ta RUN ALL.
// Izgara: TUREF / TM30 (EPSG:5254), 02_dem ile aynı hizada.
//
// CN = f(ESA WorldCover 2021 sınıfı, hidrolojik toprak grubu)
// Toprak grubu: HiHydroSoil v2.0 (250 m). İkili gruplar (A/D, B/D, C/D) ve
// verisi olmayan pikseller D sayılır: "drenaj çalışmıyor" senaryosu için ihtiyatlı seçim.
// CN değerleri: USDA TR-55 tabloları (iyi hidrolojik koşul).
// =====================================================================

var PROJECT = 'tasma-511107';
var AOI_ASSET = 'projects/' + PROJECT + '/assets/istanbul_taskin_aoi';
var DRIVE_FOLDER = 'istanbul_taskin_gee';
var CRS = 'EPSG:5254';
function tr(scale) { return [scale, 0, 0, 0, -scale, 0]; }

var bolge = ee.FeatureCollection(AOI_ASSET).geometry();
var pencere = bolge.bounds(10);

// 1) Arazi örtüsü (ESA WorldCover v200, 2021, 10 m)
var wc = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map').rename('landcover').clip(bolge);

// 2) Yapılaşmış yüzey oranı (GHSL P2023A, 100 m). built_surface = hücre başına m², hücre 10.000 m²
function yapiOrani(yil) {
  return ee.Image('JRC/GHSL/P2023A/GHS_BUILT_S/' + yil).select('built_surface')
    .divide(10000).rename('built_' + yil);
}
var b1990 = yapiOrani(1990);
var b2020 = yapiOrani(2020);
var yapi = b1990.addBands(b2020)
  .addBands(b2020.subtract(b1990).rename('built_change'))
  .toFloat().clip(bolge);

// 3) Hidrolojik toprak grubu (1=A, 2=B, 3=C, 4=D; 14/24/34 ikili gruplar)
var hsg = ee.Image('projects/sat-io/open-datasets/HiHydroSoilv2_0/Hydrologic_Soil_Group_250m')
  .select(0)
  .remap([1, 2, 3, 4, 14, 24, 34], [1, 2, 3, 4, 4, 4, 4])
  .unmask(4)
  .rename('hsg').toByte().clip(bolge);

// 4) CN tablosu: WorldCover sınıfı -> [A, B, C, D]
var CN = {
  10:  [30, 55, 70, 77],    // Ağaç örtüsü (orman, iyi)
  20:  [30, 48, 65, 73],    // Çalılık
  30:  [39, 61, 74, 80],    // Çayır / mera (iyi)
  40:  [67, 78, 85, 89],    // Tarım (sıralı ekim)
  50:  [89, 92, 94, 95],    // Yapılaşmış (ticari-yoğun kentsel, ~%85 geçirimsiz)
  60:  [77, 86, 91, 94],    // Çıplak / seyrek bitki
  70:  [98, 98, 98, 98],    // Kar / buz
  80:  [100, 100, 100, 100],// Kalıcı su
  90:  [98, 98, 98, 98],    // Sulak alan
  95:  [98, 98, 98, 98],    // Mangrov
  100: [77, 86, 91, 94]     // Yosun / liken
};
var anahtarlar = [], cnDegerleri = [];
Object.keys(CN).forEach(function (sinif) {
  for (var g = 1; g <= 4; g++) {
    anahtarlar.push(Number(sinif) * 10 + g);
    cnDegerleri.push(CN[sinif][g - 1]);
  }
});
// Anahtar = sınıf × 10 + toprak grubu (ör. 50 yapılaşmış + C = 503)
var cn = wc.multiply(10).add(hsg)
  .remap(anahtarlar, cnDegerleri, 0)
  .rename('cn').toByte().clip(bolge);

// 5) Özetler
print('Arazi örtüsü piksel sayıları (100 m örnekleme):', wc.reduceRegion({
  reducer: ee.Reducer.frequencyHistogram(), geometry: bolge, scale: 100, maxPixels: 1e10
}));
print('Toprak grubu dağılımı (1=A … 4=D):', hsg.reduceRegion({
  reducer: ee.Reducer.frequencyHistogram(), geometry: bolge, scale: 250, maxPixels: 1e10
}));
print('Ortalama CN:', cn.updateMask(cn.gt(0)).reduceRegion({
  reducer: ee.Reducer.mean(), geometry: bolge, scale: 100, maxPixels: 1e10
}));
print('Tabloda karşılığı olmayan piksel (0 olmalı):', cn.eq(0).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: bolge, scale: 100, maxPixels: 1e10
}));
var yapiAlani = yapi.select(['built_1990', 'built_2020'])
  .multiply(ee.Image.pixelArea()).divide(1e6)
  .reduceRegion({reducer: ee.Reducer.sum(), geometry: bolge, scale: 100, maxPixels: 1e10});
print('Yapılaşmış yüzey (km²), 1990 ve 2020:', yapiAlani);

// Haritada kontrol
Map.centerObject(bolge, 9);
Map.addLayer(wc, {}, 'WorldCover 2021', false);
Map.addLayer(cn.updateMask(cn.gt(0)), {min: 40, max: 100, palette: ['1a9850', 'd9ef8b', 'fee08b', 'f46d43', 'a50026']}, 'CN');
Map.addLayer(hsg, {min: 1, max: 4, palette: ['ffffcc', 'a1dab4', '41b6c4', '225ea8']}, 'Toprak grubu', false);
Map.addLayer(yapi.select('built_change'), {min: 0, max: 0.5, palette: ['ffffff', 'fdae61', 'd7191c']}, 'Yapılaşma artışı 1990→2020', false);

// 6) Dışa aktarma
Export.image.toDrive({
  image: wc.toByte(), description: 'worldcover_10m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(10), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: 0}
});
Export.image.toDrive({
  image: cn, description: 'cn_10m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(10), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: 0}
});
Export.image.toDrive({
  image: hsg, description: 'hsg_250m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(250), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: 0}
});
Export.image.toDrive({
  image: yapi, description: 'ghsl_yapi_1990_2020_100m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(100), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: -9999}
});
