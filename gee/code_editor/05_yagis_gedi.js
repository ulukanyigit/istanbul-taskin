// =====================================================================
// 05_yagis_gedi — Yağış olay kataloğu (IMERG) ve DEM düşey hatası (GEDI)
// code.earthengine.google.com → "tasma-511107" projesi seçiliyken yapıştır → Run →
// Tasks sekmesinde 2 görevi RUN et. Çıktılar Drive'da istanbul_taskin_gee klasörüne gelir:
//   imerg_istanbul_30dk.csv  — 2000'den bugüne il geneli 30 dakikalık yağış (ortalama ve en yüksek hücre, mm/sa)
//   gedi_fabdem_ornek.csv    — GEDI zemin atışları ile FABDEM / GLO-30 karşılaştırma örnekleri
// İlk görev 30–60 dk sürebilir (yaklaşık 450 bin görüntü); ikincisi birkaç dakika.
// =====================================================================

var PROJECT = 'tasma-511107';
var DRIVE_FOLDER = 'istanbul_taskin_gee';
var AOI = ee.FeatureCollection('projects/' + PROJECT + '/assets/istanbul_taskin_aoi').geometry();
var il = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Turkey'))
  .filter(ee.Filter.stringContains('ADM1_NAME', 'stanbul'))
  .geometry();

// ---------------------------------------------------------------- 1) IMERG V07, 30 dk
var imerg = ee.ImageCollection('NASA/GPM_L3/IMERG_V07').select('precipitation');
print('IMERG ilk / son görüntü:',
  ee.Date(imerg.aggregate_min('system:time_start')), ee.Date(imerg.aggregate_max('system:time_start')));

var reducer = ee.Reducer.mean().combine({reducer2: ee.Reducer.max(), sharedInputs: true});
var seri = imerg.map(function (img) {
  var d = img.reduceRegion({reducer: reducer, geometry: il, scale: 11132, bestEffort: true});
  return ee.Feature(null, {
    t: img.date().format('YYYY-MM-dd HH:mm'),
    ort: d.get('precipitation_mean'),
    maks: d.get('precipitation_max')
  });
}).filter(ee.Filter.gt('maks', 0.05));   // kuru zaman adımlarını atla (dosya küçük kalsın)

Export.table.toDrive({
  collection: seri, description: 'imerg_istanbul_30dk', folder: DRIVE_FOLDER,
  fileNamePrefix: 'imerg_istanbul_30dk', fileFormat: 'CSV', selectors: ['t', 'ort', 'maks']
});

// ---------------------------------------------------------------- 2) GEDI L2A zemin atışları
var gedi = ee.ImageCollection('LARSE/GEDI/GEDI02_A_002_MONTHLY')
  .filterBounds(AOI)
  .map(function (img) {
    var iyi = img.select('quality_flag').eq(1)
      .and(img.select('degrade_flag').eq(0))
      .and(img.select('sensitivity').gt(0.95));
    return img.select(['elev_lowestmode']).updateMask(iyi);
  })
  .mosaic();
var fabdem = ee.ImageCollection('projects/sat-io/open-datasets/FABDEM').filterBounds(AOI).mosaic().rename('fabdem');
var glo30 = ee.ImageCollection('COPERNICUS/DEM/GLO30').filterBounds(AOI).select('DEM').mosaic().rename('glo30');
var wc = ee.ImageCollection('ESA/WorldCover/v200').first().rename('wc');
var egim = ee.Terrain.slope(glo30).rename('egim');
var yigin = gedi.addBands([fabdem, glo30, wc, egim]);

var ornek = yigin.sample({region: AOI, scale: 25, numPixels: 60000, seed: 7, geometries: true, dropNulls: true})
  .map(function (f) {
    var c = f.geometry().coordinates();
    return f.set({lon: c.get(0), lat: c.get(1)});
  });

Export.table.toDrive({
  collection: ornek, description: 'gedi_fabdem_ornek', folder: DRIVE_FOLDER,
  fileNamePrefix: 'gedi_fabdem_ornek', fileFormat: 'CSV',
  selectors: ['lon', 'lat', 'elev_lowestmode', 'fabdem', 'glo30', 'wc', 'egim']
});
print('GEDI örnek sayısı (yaklaşık):', ornek.size());
