# Yöntem notu

**Soru:** Yağmur suyu altyapısı devre dışı kaldığında İstanbul'da hangi noktalar kaç mm yağışta ilk dolar ve kimi
etkiler? **Düzey:** il geneli ön tarama (screening); mühendislik tasarımı ya da resmi tehlike haritası değildir.

## 1. Veri ve ızgara

- **Izgara:** TUREF / TM30 (EPSG:5254), 10 m, 19.050 × 10.027 piksel; analiz alanı il sınırı ve ile akan
  HydroSHEDS seviye-12 havzaları (+500 m). Yükseklikler EGM2008 geoidine göre.
- **DEM:** FABDEM v1.2 (Copernicus GLO-30'dan bina ve ağaç etkisi çıkarılmış, 30 m) 10 m'ye çift doğrusal örneklendi.
  Amaç detay kazanmak değil, vektör yapıları (yol, dere, bina) ızgaraya yakabilmek.
- **Yüzey akışı:** ESA WorldCover 2021 × HiHydroSoil v2 hidrolojik toprak grubu → TR-55 eğri numarası (CN; il ortalaması
  80,4). SCS-CN, Ia = 0,2 S.
- **OSM (Geofabrik, 2026):** 892 bin bina, 253 bin yol parçası, 8.227 dere, 2.318 menfez, 1.374 alt geçit, 4.759 kritik
  tesis ve metro girişi, mahalle ve ilçe sınırları.
- **Nüfus:** JRC GHS-POP 2020 (100 m), il toplamı TÜİK ADNKS 2020'ye (15,46 milyon) ölçeklenip bina taban alanına göre
  binalara dağıtıldı (konut binaları öncelikli); nüfusun %82,7'si OSM binalarına atanabildi.

## 2. DEM koşullandırma

Standart hidrolojik ön işlemden farklı olarak çukurlar doldurulmaz; yalnız yapay engeller kaldırılır, kentsel akış
yolları açılır:

| Müdahale | Parametre |
| --- | --- |
| Köprü ve viyadükler | hat tamponu maskelenip altı uçlardan enterpole edilir |
| Binalar | ayak izi +5 m (akışa engel) |
| Yollar | yüzey −0,30 m, yarı genişlik sınıfa göre 3–12 m |
| Açık dereler | profil boyunca kayan medyan + kümülatif minimum, sınıfa göre 0,5–2 m oyma (en çok +3 m ek) |
| Menfez / kapalı dere | set hat boyunca yarılır; her hat "tıkanabilir" kimliğiyle ayrı tutulur |
| Alt geçitler | iki uç arasında eğimli taban, yüzeyin 5 m altı |
| Deniz | çıkış (outlet) |

Değişen topografya (maden ocakları, İGA) ayrı maskelenip "güvenilmez" işaretlendi.

## 3. Çukur ve dolma–taşma analizi

Priority-Flood (Barnes vd. 2014; numba ile yazıldı) koşullandırılmış DEM'i doldurur; doldurma − DEM > 1 cm olan
bağlantılı bölgeler çukurdur. Gürültü süzgeci: en derin noktası ≥ 10 cm, alanı ≥ 300 m², hacmi ≥ 20 m³ →
228.605 ham çukurdan **58.874**. İkinci bir Priority-Flood geçişi her pikselin suyunun ilk girdiği çukuru (yerel havza)
ve her çukurun taşma noktası ile alıcı çukurunu verir: bir dolma–taşma ağacı (Balstrøm & Crawford 2018 "bluespot"
yaklaşımı). Her çukurun piksel kotları sıralı olarak saklanır (hipsometri); bu, hacimden su seviyesine kesin dönüşümdür.

**Dolma eşiği:** 0–300 mm yağış için her çukurun yerel havzasından SCS-CN akışı hesaplanır, ağaç memba → mansap
gezilerek taşmalar alıcılara eklenir; çukurun dolduğu en küçük yağış o çukurun eşiğidir.

**Sınıflar:** kentsel (yapı oranı ≥ %25 ya da ≥ 200 m² yol), alt geçit, dere/vadi seti, kırsal; elenen: bina avlusu,
göl/baraj, değişen topografya.

## 4. Kova motoru ve senaryolar

Her 5 dakikalık adımda: (1) birikimli yağıştan her çukurun yerel havzası için SCS-CN akışı, (2) varsa boru patlaması
debisi, (3) kademe sırasıyla (memba → mansap) her çukurda drenaj kapasitesi kadar su şebekeye gider, kapasiteyi aşan su
alıcı çukura taşar, (4) hipsometriden su seviyesi. Akış süresi ihmal edilir: adım içinde taşan su aynı adımda alıcıya
ulaşır. Motorun Python (referans) ve JavaScript (tarayıcı, Web Worker) sürümleri aynı sonucu verir: 58.874 çukurda su
seviyesi farkı ≤ 0,8 cm (tarayıcıda hipsometri cm'ye yuvarlanır), zaman adımlı son durum tek adımla birebir aynı.

| Senaryo | Modeldeki karşılığı |
| --- | --- |
| Yağış | toplam, süre, üçgen hiyetograf (tepe başta / ortada / sonda) ya da düzgün; ya da IMERG'den geçmiş olay serisi |
| Drenaj kapasitesi | çukurun yerel havza alanı başına mm/sa; her adımda önce bu kadar su şebekeye gider |
| Alt geçit pompaları | alt geçit çukuru başına 0,5 m³/s ek boşaltım |
| Menfez tıkanması | menfez hattı ham DEM'e döner; set önündeki gölet ayrı bir çukur olarak açılır (bkz. 6) |
| Boru patlaması | tıklanan noktanın yerel havzasındaki çukura sabit debi |
| Arazi örtüsü 1990 | 1990 CN histogramıyla yüzey akışı (bkz. 7) |

## 5. Maruziyet ve risk

- **Bina:** bina pikselleri ve 1 piksel komşuluğundaki en büyük su derinliği. ≥ 10 cm "duvarına su değiyor",
  ≥ 30 cm "bodrum / zemin kat riski". Maruziyettir, hasar değildir.
- **Yol:** sürüşe açık OSM yolları köşe noktalarından ağ (1,3 milyon düğüm, 44.800 km); kenar orta noktasında ≥ 30 cm
  su → kapalı (köprü / tünel kapanmaz). Her düğümden en yakın hastaneye çok kaynaklı Dijkstra.
- **Tesisler:** hastane, okul, itfaiye, metro girişi çevresi 30 m'de en büyük derinlik.
- **Mahalle risk indeksi:** tehlike (su altındaki alan oranı), maruziyet (etkilenen nüfus) ve erişim kaybının il içi
  yüzdelik sıralarının ortalaması (0–100). Getis-Ord Gi* (2 km komşuluk) ile sıcak noktalar. Yaş ve gelir gibi
  kırılganlık verileri mahalle düzeyinde açık olmadığından indekse girmedi.

## 6. Menfez tıkanması

Koşullandırmada açılan 1.832 kapalı dere / menfez hattının her biri için yerel bir pencerede iki Priority-Flood
doldurması yapıldı: menfez açık (koşullandırılmış DEM) ve kapalı (hat boyunca ham FABDEM, yani yol / dolgu seti).
Doldurma farkı > 5 cm olan ve hatta bitişik bölge, tıkanınca oluşan gölettir; tabanı açık durumdaki doldurulmuş
yüzeydir (içindeki mevcut çukurlar dolu sayılır). 1.294 menfez gölet üretiyor; il içinde kıyısında en çok bina olan
30'u ayrıntılı işlendi. Gölete gelen su: Priority-Flood yönlendirme ağacında akışı menfezden geçen memba pikselleri
(hiçbir çukura girmeyenlerin akışı doğrudan) ve taşma noktası membada, alıcısı mansapta kalan çukurların taşması
(tıkanınca alıcıları gölet olur). Göletlerin toplam kapasitesi 0,60 milyon m³.

## 7. Kentleşme etkisi

Bugün yapılaşmış (WorldCover 50) her 10 m pikselin 1990 CN'si, 100 m hücredeki GHSL yapı alanı oranıyla
r = yapı₁₉₉₀ / yapı₂₀₂₀ karıştırılır: CN₁₉₉₀ = r · CN_bugün + (1 − r) · CN_çayır(toprak grubu). Topografya, çukurlar ve
ağaç aynıdır; yalnız yüzey akışı değişir. Sonuç: il içindeki 31.717 kentsel / alt geçit çukurunun 25 mm'de dolanları
9.680 → 12.162, 10 mm'de 1.673 → 3.038; 50 mm yağışın yüzey akışı 86,1 → 95,3 milyon m³. En çok etkilenen mahallelerde
ortanca dolma eşiği 30 mm'den fazla düştü (ör. Sancaktepe Yunus Emre, Başakşehir, Esenyurt Aşık Veysel).

## 8. Duyarlılık ve belirsizlik

Koşullandırma parametrelerinin her biri kendi maskesinde ölçeklenip (z = FABDEM + fark × k) çukur analizi baştan
yapıldı (`pipeline/cukur/03_duyarlilik.py`, `04_duyarlilik_mahalle.py`). Temel çözümdeki her çukur, varyantta en çok
örtüşen çukurla eşlendi (en az %30 örtüşme); il içi 31.092 kentsel çukur varyant eşiklerine göre yeniden sıralandı.
Kontrol koşusu temel sonucu birebir üretti (ilk 100'ün 100'ü, ρ = 1).

| Senaryo | Çukur sayısı | İlk 100'de kalan | Spearman ρ (eşik) | Kaybolan aday |
| --- | ---: | ---: | ---: | ---: |
| bina +3 m (temel +5) | 57.860 | 98 | 0,99 | %1,7 |
| bina +8 m | 59.214 | 100 | 1,00 | %0 |
| yol −0,15 m (temel −0,30) | 48.956 | 19 | 0,19 | %33,7 |
| yol −0,50 m | 74.408 | 36 | 0,84 | %3,2 |
| dere oyma ×0,5 / ×1,5 | 62.786 / 63.855 | 95 / 93 | 1,00 / 1,00 | %0 |
| alt geçit derinliği 3 m / 7 m | 58.818 / 58.934 | 100 / 100 | 1,00 / 1,00 | %0 |
| DEM hatası σ = 0,25 m (4 tekrar, ~30 m ilişki uzunluğu) | ~74.000 | 17–26 | 0,41 | %22 |

Aynı karşılaştırma mahalle ve ilçe düzeyinde (her mahallede 25 mm'de dolan kentsel çukur hacmi):

| Senaryo | Mahalle ρ | İlk 50 mahalleden ortak | İlçe ρ | İlk 10 ilçeden ortak |
| --- | ---: | ---: | ---: | ---: |
| yol −0,15 m | 0,94 | 40 | 0,95 | 8 |
| yol −0,50 m | 0,95 | 41 | 0,94 | 7 |
| DEM hatası σ = 0,25 m (ortalama) | 0,90 | 35 | 0,79 | 7 |

50 mm için mahalle ρ 0,96–0,98'dir.

**Yorum.** Bina yüksekliği, dere oyması ve alt geçit derinliği sonucu neredeyse hiç değiştirmiyor. Tek tek cadde
çukurlarının varlığı ve sırası ise yolun kaldırıma göre ne kadar alçak alındığına ve DEM'in cm düzeyindeki hatasına çok
duyarlı: yol 15 cm alçaltılınca kentsel çukurların üçte biri 10 cm derinlik süzgecinin altında kalıyor. Sıcak nokta
tablosu mahalle ve ilçe düzeyinde dayanıklı. Bu yüzden "ilk dolanlar" listesi bir gösterge, mahalle karnesi ve risk
indeksi daha güvenilir okumadır. Simülatörde her çukurun DEM hatasına karşı çukur olma olasılığı ve eşik aralığı
(%10–%90) çukur penceresinde gösterilir.

DEM hatası büyüklüğü: Earth Engine'de GEDI zemin atışlarıyla FABDEM karşılaştırması örnek üretmedi (dışa aktarım boş
döndü); σ bu yüzden varsayımdır. FABDEM'in kentsel alanlardaki mutlak hatası metre düzeyindedir (Hawker vd. 2022); burada
önemli olan yakın pikseller arasındaki göreli hatadır ve 30 m kaynaklı yumuşak bir yüzeyde bunun 0,25 m mertebesinde
olduğu varsayıldı. σ = 0,5 m ile yapılan tek koşuda ilk 100'ün 9'u kaldı (ρ = 0,23).

## 9. Doğrulama

Haberlerde su bastığı yazan 22 olay (2021–2026; ANKA, haberler.com, TRT Haber, sol.org.tr) konumlandırıldı:
11 cadde (OSM cadde adından, 20 m tampon) ve 11 nokta (50 / 100 / 150 m yarıçap). Karşılaştırma: il içi yapılaşmış
alandan 2.000 rastgele nokta ve 500 rastgele adlı cadde. AUC = olayın rastgele örnekten daha fazla su gösterme
olasılığı, %95 güven aralığı bootstrap ile.

| Grup | Ölçü | AUC [%95 GA] |
| --- | --- | --- |
| Cadde (n=11) | dolma eşiği | **0,83 [0,74–0,91]** |
| Cadde (n=11) | 25 mm'de derinlik | 0,73 [0,61–0,83] |
| Nokta, 100 m (n=11) | 25 mm'de derinlik | 0,66 [0,49–0,81] |
| Nokta, 50 m (n=11) | 25 mm'de derinlik | 0,50 [0,34–0,66] |

Model su basan caddeleri rastgele caddelerden açıkça ayırıyor; nokta olaylarda sinyal 11 olayla istatistiksel olarak
belirsiz. Iskalananlar kıyı ve köprü altı noktaları (Ayvansaray, Halıcıoğlu): büyük olasılıkla kanalizasyonun deniz
tarafından geri tepmesi, modelde yok.

## 10. Geçmiş yağış olayları

IMERG 30 dakikalık serisinin Earth Engine'den dışa aktarımı alınamadı. Simülatördeki geçmiş olaylar bu yüzden resmi
açıklamalarda ölçülen ya da tahmin edilen yağıştan kuruldu; toplam ve süre kaynaktan, zaman içindeki dağılım
(üçgen hiyetograf) varsayımdır. Yağış bütün ile aynı uygulanır ("fırtınanın merkezi her yerde olsaydı").

| Olay | Toplam / süre | Kaynak |
| --- | --- | --- |
| 8–9 Eylül 2009, Ayamama selinin gecesi | 150 mm / 8 sa (canlandırma; TRMM: bölgede >125, kıyıda ~200 mm, 2–9 Eylül) | NASA Earth Observatory |
| 25 Ekim 2017, Çatalca | 137 mm / 24 sa | MGM Çatalca AWOS (İPA Kent Gündemi) |
| 15 Haziran 2021, Şişli | 47 mm / 2 sa (Güngören 30 mm), 18 noktada su baskını | AKOM (ANKA) |
| 5 Eylül 2023, Arnavutköy | 128 mm / 4 sa | AKOM (İPA bilgi notu) |
| 28 Eylül 2026 | 50 mm / 12 sa (AKOM tahmininin üst sınırı) | haberler.com |

`pipeline/web/09_yagis_olaylari.py` IMERG dosyası klasöre konduğunda en büyük 15 olayı ve haber günlerini seriden
kendiliğinden ekler.

## 11. Sınırlamalar

- DEM 30 m kaynaklıdır; bordür, rögar ve küçük çukur detayı yoktur. Sonuçlar sokak ve mahalle ölçeğinde göstergedir;
  sıralama mutlak derinlikten daha güvenilirdir.
- Kanalizasyon ağı bilinmez: drenaj tek bir kapasite parametresidir. Geri tepme, deniz kabarması yoktur.
- Akış süresi ve hız yoktur: dolma sırası güvenilir, dakika düzeyindeki zamanlar yaklaşıktır.
- Bodrum ve zemin kat kotu yoktur; "duvarına su değen bina" bir maruziyet ölçüsüdür.
- OSM'de alt geçit ve menfez etiketleri eksik olabilir.
- Drenaj kapasitesi, pompa debisi ve menfez seçimleri senaryo varsayımıdır; İSKİ'nin gerçek şebeke verisi değildir.

## Kaynaklar

- Barnes, R., Lehman, C., Mulla, D. (2014). Priority-flood: An optimal depression-filling and watershed-labeling
  algorithm for digital elevation models. *Computers & Geosciences* 62.
- Balstrøm, T., Crawford, D. (2018). Arc-Malstrøm: A 1D hydrologic screening method for stormwater assessments based
  on geometric networks. *Computers & Geosciences* 116.
- Hawker, L. vd. (2022). A 30 m global map of elevation with forests and buildings removed (FABDEM). *Environ. Res. Lett.* 17.
- USDA NRCS (1986). Urban Hydrology for Small Watersheds, TR-55.
- Getis, A., Ord, J. K. (1992). The analysis of spatial association by use of distance statistics. *Geogr. Anal.* 24.
