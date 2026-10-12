# İstanbul Taşkın Simülatörü — proje özeti

**Hamza Yiğit Ulukan** · Harita Mühendisi · İstanbul · hamzayigitulukan@gmail.com · linkedin.com/in/yulukan

**Soru:** Yağmur suyu şebekesi çalışmazsa İstanbul'da su önce nerede birikir, kaç mm yağışta ve kimi etkiler?

**Ne yaptım:** İl genelinde 10 m çözünürlükte 58.874 yüzey çukurunu (bluespot) çıkarıp her birinin "kaç mm'de dolar"
eşiğini, taşınca suyun nereye gittiğini ve kimi etkilediğini hesapladım; sonucu yağış, drenaj, pompa, menfez tıkanması,
boru patlaması ve 1990 / bugün arazi örtüsü senaryolarıyla tarayıcıda çalışan bir simülatöre dönüştürdüm.

**Sonuçlar (drenaj devre dışı, 50 mm):** 65,8 km² su altında · 100 bin binanın duvarına ≥10 cm su (2,6 milyon kişi) ·
149 hastane, 767 okul, 205 metro girişi · 383 km yol araç geçemez · sıcak nokta kuşağı Bağcılar–Esenler–Bayrampaşa–
Güngören–Zeytinburnu–Fatih · betonlaşma 25 mm'de dolan kentsel çukur sayısını 1990'a göre %26 artırdı.

**Doğrulama:** haberlerde su basan caddeler rastgele caddelerden ayrılıyor (AUC 0,83 [0,74–0,91]).

| Aşama | Yöntem / araç |
| --- | --- |
| Girdi üretimi | Google Earth Engine: FABDEM, WorldCover, HiHydroSoil → SCS-CN; GHSL, GHS-POP, IMERG, GEDI |
| Vektör ve DEM | OSM (GDAL), DEM koşullandırma: köprü, bina, yol, dere, menfez, alt geçit |
| Hidroloji | Priority-Flood (numba), dolma–taşma ağacı, hipsometri, SCS-CN eşikleri |
| Maruziyet | dasimetrik nüfus, ağ analizi (Dijkstra), risk indeksi, Getis-Ord Gi* |
| Belirsizlik | parametre duyarlılığı, DEM hatası Monte Carlo |
| Web | MapLibre GL, WebGL2 su çizimi, Web Worker motoru, PMTiles, 3B arazi |

**Becerilerim için gösterdikleri:** büyük raster işleme (191 milyon piksel), hidrolojik modelleme, koordinat sistemleri
ve düşey datum, mekânsal istatistik, test edilmiş iki dilli model (Python ↔ JavaScript), sunucusuz web haritacılığı.

Kod ve yöntem: github.com/… (README) · Canlı simülatör: …
