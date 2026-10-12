"""Ortak ayarlar: tüm Earth Engine scriptleri bu dosyayı kullanır."""
import ee

PROJECT = "tasma-511107"
ASSET_ROOT = f"projects/{PROJECT}/assets"
AOI_ASSET = f"{ASSET_ROOT}/istanbul_taskin_aoi"
DRIVE_FOLDER = "istanbul_taskin_gee"

# Analiz ızgarası: TUREF / TM30 (EPSG:5254), 10 m.
# crsTransform sabit tutulur -> tüm rasterler piksel piksel aynı hizada çıkar.
CRS = "EPSG:5254"
SCALE = 10
NODATA = -9999


def transform(scale=SCALE):
    """Orijini (0, 0) olan, verilen çözünürlükte hizalı ızgara."""
    return [scale, 0, 0, 0, -scale, 0]


def init():
    try:
        ee.Initialize(project=PROJECT)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=PROJECT)


def asset_exists(path):
    try:
        ee.data.getAsset(path)
        return True
    except ee.EEException:
        return False


def ensure_folder(path=ASSET_ROOT):
    if not asset_exists(path):
        ee.data.createAsset({"type": "FOLDER"}, path)
        print(f"Asset klasörü oluşturuldu: {path}")


def replace_asset(path):
    """Scriptin kendi ürettiği asset'i yeniden çalıştırmadan önce siler."""
    if asset_exists(path):
        ee.data.deleteAsset(path)
        print(f"Eski asset silindi (yeniden üretilecek): {path}")


def aoi():
    """01_aoi.py tamamlandıktan sonra analiz alanını döndürür."""
    path = AOI_ASSET
    if not asset_exists(path):
        raise SystemExit(
            "AOI asset'i yok. Önce 01_aoi.py'yi çalıştırın ve görev bitene kadar bekleyin "
            "(Cloud Console > Earth Engine > Tasks)."
        )
    return ee.FeatureCollection(path)


def export_image(image, name, region, scale=SCALE, nodata=NODATA):
    """GeoTIFF (COG) olarak Drive'a, sabit TM30 ızgarasında dışa aktarır.
    Büyük alanlarda Drive'a birden fazla parça (tile) halinde iner; QGIS'te
    sanal raster (VRT) ile birleştirilir."""
    task = ee.batch.Export.image.toDrive(
        image=image,
        description=name,
        folder=DRIVE_FOLDER,
        fileNamePrefix=name,
        region=region,
        crs=CRS,
        crsTransform=transform(scale),
        maxPixels=1e11,
        fileFormat="GeoTIFF",
        formatOptions={"cloudOptimized": True, "noData": nodata},
    )
    task.start()
    print(f"Başlatıldı: {name}  ({scale} m, task id: {task.id})")
    return task


def export_table(fc, name, to_asset=False):
    if to_asset:
        path = f"{ASSET_ROOT}/{name}"
        replace_asset(path)
        task = ee.batch.Export.table.toAsset(collection=fc, description=f"{name}_asset", assetId=path)
    else:
        task = ee.batch.Export.table.toDrive(
            collection=fc, description=f"{name}_drive", folder=DRIVE_FOLDER,
            fileNamePrefix=name, fileFormat="GeoJSON",
        )
    task.start()
    print(f"Başlatıldı: {name} -> {'asset' if to_asset else 'Drive (GeoJSON)'}  (task id: {task.id})")
    return task
