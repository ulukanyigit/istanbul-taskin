# Faz 7 — Doğrulama (12.10.2026)

Soru: haberlerde su bastığı yazan yerlerde model, rastgele yerlere göre daha fazla su gösteriyor mu?

**Olaylar** (`olaylar.csv`, 22 olay, hepsi kaynaklı): AKOM'un 15.06.2021'de açıkladığı 18 noktadan 12'si, 28.09.2026
sağanağı (Zincirlikuyu, Kanarya, Terazidere, İslambey, Lütfi Aykaç Bulvarı, Güzeldere), 07.12.2025 (Hasdal) ve
04.07.2026 (Mecidiyeköy, Harem Sahil Yolu, Üsküdar Sahaflar Çarşısı). Konumlar OSM cadde adlarından (11 cadde)
ya da haberdeki yer adından elle (11 nokta) üretildi. Nokta konumlarının bir kısmı "orta" güvende (±100–200 m).

**Karşılaştırma:** noktalar için il içi yapılaşmış alandan 2.000 rastgele nokta, caddeler için il içinden rastgele
500 adlı cadde (aynı 20 m tampon). AUC = olayın, rastgele örnekten daha fazla su gösterme olasılığı; %95 güven
aralığı bootstrap ile.

| Grup | Ölçü | Olay | Karşılaştırma | AUC [%95 GA] |
| --- | --- | ---: | ---: | --- |
| Cadde (n=11) | 25 mm'de ≥10 cm su | %91 | %50 | derinlik 0,73 [0,61–0,83] |
| Cadde (n=11) | dolma eşiği | ortanca 10 mm | | eşik **0,83 [0,74–0,91]** |
| Nokta, 100 m (n=11) | 25 mm'de ≥30 cm su | %45 | %28 | derinlik 0,66 [0,49–0,81] |
| Nokta, 150 m (n=11) | 25 mm'de ≥30 cm su | %73 | %44 | derinlik 0,66 [0,49–0,82] |
| Nokta, 50 m (n=11) | | | | derinlik 0,50 [0,34–0,66] |

**Yorum**
- Model su basan **caddeleri** rastgele caddelerden açıkça ayırıyor (AUC 0,83, güven aralığı 0,5'in çok üstünde).
- **Nokta olaylarda** sinyal var ama 11 olayla istatistiksel olarak belirsiz; 50 m ölçeğinde sinyal kayboluyor,
  bu da 30 m kaynaklı DEM'in ve elle verilen konumların hassasiyet sınırına işaret ediyor.
- **Iskalananlar:** Ayvansaray Haliç Köprüsü altı ve D100 Halıcıoğlu (kıyı/köprü altı). Model kıyıdaki suyu denize
  akıtıyor; bu noktalardaki baskınlar büyük olasılıkla kanalizasyonun deniz tarafından geri tepmesi. Zincirlikuyu ve
  Mecidiyeköy'de model yalnızca ~10 cm su veriyor; Zincirlikuyu alt geçidi OSM'de alt geçit olarak işaretli olmayabilir.

**Sınırlamalar:** az sayıda olay; haberler merkezi ilçelere ve trafiği etkileyen noktalara eğilimli; olay
tarihlerindeki gerçek yağış ve drenaj durumu modele girilmedi (model "drenaj devre dışı" senaryosu).
Kurum verisi (AKOM/İSKİ konumlu ihbarlar) alınabilirse aynı script ile çok daha güçlü bir test yapılabilir.

Kaynaklar: [ANKA 15.06.2021](https://ankahaber.net/haber/detay/istanbulda_en_cok_yagis_sisli_ve_gungoren_ilcelerinde_oldu_18_noktada_su_baskini_yasandi_43288) ·
[haberler.com 28.09.2026](https://www.haberler.com/haberler/istanbulu-saganak-vurdu-yol-coktu-alt-gecidi-su-20277507-haberi/) ·
[TRT Haber 07.12.2025](https://www.trthaber.com/haber/turkiye/istanbulu-saganak-vurdu-rogarlar-tasti-araclar-mahsur-kaldi-928012.html) ·
[sol.org.tr 04.07.2026](https://haber.sol.org.tr/haber/istanbulda-kuvvetli-saganak-ev-ve-isyerlerini-caddeleri-su-basti-411379)
