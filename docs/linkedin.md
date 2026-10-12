# LinkedIn yazısı (taslak)

İstanbul'da yağmur suyu şebekesi çalışmasa su önce nerede birikir?

Son haftalarda bu soruya il genelinde cevap veren bir model ve tarayıcıda çalışan bir simülatör geliştirdim.

🔹 10 m çözünürlükte 58.874 yüzey çukuru ("bluespot"): her birinin kaç mm yağışta dolduğu, taşınca suyun nereye
gittiği, duvarına su değen bina ve nüfus, kapanan yollar, hastaneye erişim.
🔹 Drenajsız 50 mm yağışta: 65,8 km² su altında, 100 bin binanın duvarına ≥10 cm su, 383 km yol araç geçemez.
🔹 Sıcak nokta kuşağı Bağcılar–Esenler–Bayrampaşa–Güngören–Zeytinburnu–Fatih.
🔹 Betonlaşmanın etkisi: aynı çukurlardan 25 mm'de dolanlar 1990'a göre %26 fazla.
🔹 Doğrulama: haberlerde su basan caddeler rastgele caddelerden ayrılıyor (AUC 0,83).

Simülatörde yağışı, drenaj kapasitesini, alt geçit pompalarını, menfez tıkanmasını ve boru patlamasını
değiştirip suyun yükselişini zaman çizelgesinde, 3B dahil izleyebiliyorsunuz.

Yöntem: Google Earth Engine (FABDEM, WorldCover, GHSL, IMERG, GEDI) · OSM · Priority-Flood ve dolma–taşma ağacı
(Python/numba) · SCS-CN · ağ analizi ve Getis-Ord Gi* · MapLibre + WebGL2.

Bu bir ön tarama; resmi taşkın haritası değil. Sınırlamalar ve kod: [repo bağlantısı]
Canlı simülatör: [bağlantı]

#CBS #GIS #Hidroloji #İstanbul #UrbanFlood #EarthEngine #RemoteSensing #HaritaMühendisliği
