// =====================================================================
// 02_dem — FABDEM 10 m + kalite kontrol katmanları (Earth Engine Code Editor)
// ÖNCE 01_aoi'nin "istanbul_taskin_aoi_asset" görevi Completed olmalı.
// Run → Tasks sekmesinde 3 görevi tek tek RUN et.
// Izgara: TUREF / TM30 (EPSG:5254), sabit hizalı crsTransform; yükseklik EGM2008.
// =====================================================================

var PROJECT = 'tasma-511107';
var AOI_ASSET = 'projects/' + PROJECT + '/assets/istanbul_taskin_aoi';
var DRIVE_FOLDER = 'istanbul_taskin_gee';
var CRS = 'EPSG:5254';
function tr(scale) { return [scale, 0, 0, 0, -scale, 0]; }

var bolge = ee.FeatureCollection(AOI_ASSET).geometry();
var pencere = bolge.bounds(10);

// FABDEM (awesome-gee-community-catalog)
var fabCol = ee.ImageCollection('projects/sat-io/open-datasets/FABDEM').filterBounds(bolge);
print('FABDEM karo sayısı (0 olmamalı):', fabCol.size());

var fabdem = fabCol.mosaic().select(0).rename('elev')
  .setDefaultProjection(fabCol.first().projection())
  .resample('bilinear')
  .toFloat()
  .clip(bolge);

var gloCol = ee.ImageCollection('COPERNICUS/DEM/GLO30').filterBounds(bolge);
var glo = gloCol.mosaic().setDefaultProjection(gloCol.first().select('DEM').projection());

var fark = glo.select('DEM').subtract(fabdem).rename('glo30_minus_fabdem').toFloat().clip(bolge);
var su = glo.select('WBM').rename('water_mask').toByte().clip(bolge); // 0 kara, 1 deniz, 2 göl, 3 nehir

// Özet istatistik (90 m örnekleme, hızlı)
print('Özet:', fabdem.addBands(fark).reduceRegion({
  reducer: ee.Reducer.minMax().combine(ee.Reducer.mean(), '', true),
  geometry: bolge, scale: 90, maxPixels: 1e10, bestEffort: true
}));

// Haritada kontrol
Map.centerObject(bolge, 9);
Map.addLayer(fabdem, {min: 0, max: 400, palette: ['1a9850', 'fee08b', 'd73027', 'ffffff']}, 'FABDEM');
Map.addLayer(fark, {min: -5, max: 15, palette: ['2166ac', 'f7f7f7', 'b2182b']}, 'GLO30 − FABDEM', false);
Map.addLayer(su.selfMask(), {min: 1, max: 3, palette: ['08306b', '4292c6', '9ecae1']}, 'Su maskesi', false);

// Dışa aktarma
Export.image.toDrive({
  image: fabdem, description: 'fabdem_10m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(10), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: -9999}
});
Export.image.toDrive({
  image: fark, description: 'glo30_eksi_fabdem_30m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(30), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: -9999}
});
Export.image.toDrive({
  image: su, description: 'glo30_su_maskesi_30m', folder: DRIVE_FOLDER,
  region: pencere, crs: CRS, crsTransform: tr(30), maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: 255}
});
