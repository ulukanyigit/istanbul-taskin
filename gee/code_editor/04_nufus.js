// =====================================================================
// 04_nufus — GHS-POP nüfus ızgarası (2020 tahmini ve 2025 projeksiyonu, 100 m)
// Earth Engine Code Editor: yapıştır → Run → Tasks'ta RUN ALL.
// Izgara: TUREF / TM30 (EPSG:5254), 100 m, diğer katmanlarla aynı orijin.
// =====================================================================
var PROJECT = 'tasma-511107';
var AOI_ASSET = 'projects/' + PROJECT + '/assets/istanbul_taskin_aoi';
var DRIVE_FOLDER = 'istanbul_taskin_gee';
var bolge = ee.FeatureCollection(AOI_ASSET).geometry();
var il = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Turkey'))
  .filter(ee.Filter.stringContains('ADM1_NAME', 'stanbul')).geometry();

function nufus(yil) {
  return ee.Image('JRC/GHSL/P2023A/GHS_POP/' + yil).select('population_count').rename('nufus_' + yil);
}
var pop = nufus(2020).addBands(nufus(2025)).toFloat().clip(bolge);

// Kontrol: il sınırı içindeki toplam nüfus (TÜİK ADNKS 2020: ~15,46 milyon)
print('İl içi toplam nüfus (GHS-POP, yerel ızgara):', pop.reduceRegion({
  reducer: ee.Reducer.sum(), geometry: il, scale: 100, maxPixels: 1e10
}));

Map.centerObject(bolge, 9);
Map.addLayer(pop.select('nufus_2020').updateMask(pop.select('nufus_2020').gt(0)),
  {min: 0, max: 300, palette: ['000004', '781B6C', 'EC6824', 'FCFFA4']}, 'Nüfus 2020');

Export.image.toDrive({
  image: pop, description: 'ghs_pop_2020_2025_100m', folder: DRIVE_FOLDER,
  region: bolge.bounds(10), crs: 'EPSG:5254', crsTransform: [100, 0, 0, 0, -100, 0], maxPixels: 1e11,
  formatOptions: {cloudOptimized: true, noData: -9999}
});
