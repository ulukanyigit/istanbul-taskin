// =====================================================================
// 01_aoi — Havza tabanlı analiz alanı (Earth Engine Code Editor)
// code.earthengine.google.com → sağ üstten "tasma-511107" projesini seç,
// bu kodu yapıştır → Run → sağdaki Tasks sekmesinde 3 görevi tek tek RUN et.
// =====================================================================

var PROJECT = 'tasma-511107';
var AOI_ASSET = 'projects/' + PROJECT + '/assets/istanbul_taskin_aoi';
var DRIVE_FOLDER = 'istanbul_taskin_gee';

// 1) İl sınırı (FAO GAUL 2015, seviye 1)
var il = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Turkey'))
  .filter(ee.Filter.stringContains('ADM1_NAME', 'stanbul'));
print('İl kaydı sayısı (1 olmalı):', il.size());
var ilGeom = il.geometry();

// 2) İl sınırına değen seviye-12 havzalar
var havzalar = ee.FeatureCollection('WWF/HydroSHEDS/v1/Basins/hybas_12');
var yakin = havzalar.filterBounds(ilGeom.buffer(60000).bounds());
var baslangic = havzalar.filterBounds(ilGeom).aggregate_array('HYBAS_ID');

// 3) Memba havzaları: NEXT_DOWN değeri seçili kümede olanları 20 tur boyunca ekle
var secili = ee.List(ee.List.sequence(1, 20).iterate(function (tur, acc) {
  acc = ee.List(acc);
  var yeni = yakin.filter(ee.Filter.inList('NEXT_DOWN', acc)).aggregate_array('HYBAS_ID');
  return acc.cat(yeni).distinct();
}, baslangic));

var aoiHavzalar = havzalar.filter(ee.Filter.inList('HYBAS_ID', secili));

// Kıyı şeritleri dışarıda kalmasın: havzalar + il sınırı, 500 m tampon
var aoiGeom = aoiHavzalar.union(10).geometry()
  .union(ilGeom, 10)
  .buffer(500, 10);

print('İl sınırına değen havza:', baslangic.size());
print('Toplam havza (memba dahil):', secili.size());
print('İl alanı (km²):', ilGeom.area(100).divide(1e6));
print('Analiz alanı (km²):', aoiGeom.area(100).divide(1e6));

// Haritada kontrol
Map.centerObject(ilGeom, 8);
Map.addLayer(aoiHavzalar.style({color: '4a90d9', fillColor: '4a90d920', width: 1}), {}, 'Havzalar');
Map.addLayer(ee.FeatureCollection([ee.Feature(aoiGeom)]).style({color: 'e8590c', fillColor: '00000000', width: 2}), {}, 'Analiz alanı');
Map.addLayer(il.style({color: '000000', fillColor: '00000000', width: 2}), {}, 'İl sınırı');

// 4) Dışa aktarma (Tasks sekmesinde RUN gerekir)
Export.table.toAsset({
  collection: ee.FeatureCollection([ee.Feature(aoiGeom, {ad: 'istanbul_taskin_aoi'})]),
  description: 'istanbul_taskin_aoi_asset',
  assetId: AOI_ASSET
});
Export.table.toDrive({
  collection: il.select(['ADM1_NAME']),
  description: 'istanbul_il_siniri',
  folder: DRIVE_FOLDER,
  fileFormat: 'GeoJSON'
});
Export.table.toDrive({
  collection: aoiHavzalar.select(['HYBAS_ID', 'NEXT_DOWN', 'SUB_AREA', 'UP_AREA']),
  description: 'aoi_havzalar',
  folder: DRIVE_FOLDER,
  fileFormat: 'GeoJSON'
});
