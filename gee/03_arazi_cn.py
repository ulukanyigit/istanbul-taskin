"""03_arazi_cn — Arazi örtüsü, geçirimsizlik (1990/2020) ve SCS-CN rasterı.

code_editor/03_arazi_cn.js ile aynı çıktıları üretir.
CN = f(ESA WorldCover 2021 sınıfı, hidrolojik toprak grubu). Toprak grubu HiHydroSoil v2.0;
ikili gruplar ve verisi olmayan pikseller D sayılır (drenaj çalışmıyor senaryosu, ihtiyatlı).
CN değerleri USDA TR-55 tablolarından (iyi hidrolojik koşul).
"""
import ee
from config import init, aoi, export_image

init()
bolge = aoi().geometry()
pencere = bolge.bounds(maxError=10)

wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").rename("landcover").clip(bolge)


def yapi_orani(yil):
    return (ee.Image(f"JRC/GHSL/P2023A/GHS_BUILT_S/{yil}").select("built_surface")
            .divide(10000).rename(f"built_{yil}"))


b1990, b2020 = yapi_orani(1990), yapi_orani(2020)
yapi = (b1990.addBands(b2020)
        .addBands(b2020.subtract(b1990).rename("built_change"))
        .toFloat().clip(bolge))

hsg = (ee.Image("projects/sat-io/open-datasets/HiHydroSoilv2_0/Hydrologic_Soil_Group_250m")
       .select(0)
       .remap([1, 2, 3, 4, 14, 24, 34], [1, 2, 3, 4, 4, 4, 4])
       .unmask(4).rename("hsg").toByte().clip(bolge))

CN = {  # WorldCover sınıfı: [A, B, C, D]
    10: [30, 55, 70, 77],      # Ağaç örtüsü
    20: [30, 48, 65, 73],      # Çalılık
    30: [39, 61, 74, 80],      # Çayır / mera
    40: [67, 78, 85, 89],      # Tarım
    50: [89, 92, 94, 95],      # Yapılaşmış (~%85 geçirimsiz)
    60: [77, 86, 91, 94],      # Çıplak / seyrek bitki
    70: [98, 98, 98, 98],      # Kar / buz
    80: [100, 100, 100, 100],  # Kalıcı su
    90: [98, 98, 98, 98],      # Sulak alan
    95: [98, 98, 98, 98],      # Mangrov
    100: [77, 86, 91, 94],     # Yosun / liken
}
anahtarlar = [s * 10 + g for s in CN for g in range(1, 5)]
degerler = [CN[s][g - 1] for s in CN for g in range(1, 5)]
cn = wc.multiply(10).add(hsg).remap(anahtarlar, degerler, 0).rename("cn").toByte().clip(bolge)

ozet = {
    "arazi_ortusu": wc.reduceRegion(ee.Reducer.frequencyHistogram(), bolge, 100, maxPixels=1e10),
    "toprak_grubu": hsg.reduceRegion(ee.Reducer.frequencyHistogram(), bolge, 250, maxPixels=1e10),
    "ortalama_cn": cn.updateMask(cn.gt(0)).reduceRegion(ee.Reducer.mean(), bolge, 100, maxPixels=1e10),
    "tablo_disi_piksel": cn.eq(0).reduceRegion(ee.Reducer.sum(), bolge, 100, maxPixels=1e10),
    "yapi_km2": yapi.select(["built_1990", "built_2020"]).multiply(ee.Image.pixelArea()).divide(1e6)
                    .reduceRegion(ee.Reducer.sum(), bolge, 100, maxPixels=1e10),
}
for k, v in ee.Dictionary(ozet).getInfo().items():
    print(f"{k}: {v}")

export_image(wc.toByte(), "worldcover_10m", pencere, scale=10, nodata=0)
export_image(cn, "cn_10m", pencere, scale=10, nodata=0)
export_image(hsg, "hsg_250m", pencere, scale=250, nodata=0)
export_image(yapi, "ghsl_yapi_1990_2020_100m", pencere, scale=100)
