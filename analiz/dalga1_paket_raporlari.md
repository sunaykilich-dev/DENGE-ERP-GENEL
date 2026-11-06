

# Paket sonucu 1

**D1-E Ekipman kütüğü: TS-050…057 raporu**

TS-050, 051, 052, 054, 055 ve 056 tamam. TS-053 ile TS-057 kısmen yapıldı: TS-053'te iki toplu işlem diğer paketlerin uçlarını bekliyor, TS-057'de hesabı olmayan ekipmanın irtibat adını silmenin yolu yok. Hedefli testlerin hepsi geçti. Ön yüz hatasız derleniyor ama tarayıcıda açıp bakmadım; 375 px görünüm kontrol edilmedi.

**Madde durumu**

| Madde | Ö | Durum | Not |
|---|---|---|---|
| TS-050 | P1 | TAMAM | Ekle, düzenle, pasife al, aktifleştir tek kapıdan geçiyor. Aynı tip+marka+seri ile ikinci kayıt 409 veriyor, gerekçeyle açılıyor; başka birimdeki eşleşmenin kimliği gösterilmiyor. Eski sürümle düzenleme 409. Başka hesabın adresi/irtibatı 400; hesap değişince adres ve irtibat boşalıyor. Kapsam: birim + müşteri, kapsam dışı birime kayıt açma ya da taşıma 404. |
| TS-051 | P1 | TAMAM | Geçmiş `audit_logs`'tan geliyor. İrtibat değişikliği ayrı satıra kişisel veri olarak yazılıyor. Hesap anonimleştirilince seri değişikliği görünmeye devam ediyor (testli). Uç yalnız okuma. |
| TS-052 | P1 | TAMAM | Kart ve tek `gecmis()` fonksiyonu: servis işleri (bağlı olanlar + seri metniyle eşleşen eski işler "METIN" etiketli), bakım ziyaretleri, kütük olayları. Süre kaydı yoksa "eksik" gösteriliyor, 0 değil. Maliyet alanı `maliyet.gor` olmayana hiç gönderilmiyor. Dalga 2 kaynakları için `gecmis_kaynagi_kaydet` kayıt noktası var. |
| TS-053 | P1/P2 | KISMEN | Yapılan: liste, süzgeç, sayfalama, Excel (≤20.000 satır, seri metin hücre, denetime yazılıyor), 7 KPI kutusu (kutu sayısı = açılan listenin toplamı), toplu durum (ya hepsi ya hiçbiri, en çok 200), toplu garanti. EKSİK: toplu "Sözleşmeye bağla" (D1-F ucu gerekiyor) ve toplu "Servis işi aç" (D1-B ucu gerekiyor). |
| TS-054 | P2 | TAMAM | `seri_ile_bul` + `GET /oneri`: öneri yalnız kapsam içinde tek eşleşme varsa; başka birimin kaydı öneri vermiyor ve varlığını da sızdırmıyor. `00123≠123`, `AB-1≠AB1`. |
| TS-055 | P2 | TAMAM | Durum makineyle değişiyor; gerekçe zorunlu (400), kural dışı geçiş 409. KURULU'ya geçişte kurulum tarihi doluyor. "Serviste" rozeti açık ARIZA işinden hesaplanıyor, saklanmıyor. DEVRE_DISI/HURDA'da açık işler silinmiyor, yanıtta uyarı dönüyor. |
| TS-056 | P2 | TAMAM | Garanti rozeti hesaplanıyor; bitiş < başlangıç 400. Toplu garanti önce önizleme, sonra uygulama; ikisi aynı satır sayısını veriyor, kaynak HESAPLANDI, BELGE kaynaklı kayda dokunulmuyor. Sözleşme bağı kartta ve listede ayrı sayılıyor; D1-F için `bagli_ekipman_sayilari()` hazır. |
| TS-057 | P2 | KISMEN | Yapılan: ek kapsamı (başka birim 404), genel arama (seri ile, kapsamlı), görev etiketi `#id` ve rota, KVKK (anonimleştirmede irtibat adı temizleniyor, kişisel denetim satırları maskeleniyor, veri bulmada `servis_ekipmanlari`). EKSİK: hesabı olmayan ekipmanın irtibat adını temizleyen ayrı bir yol yok (veri bulma bu kaydı buluyor ama silemiyor). |

**Değişen dosyalar**
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\app\services\teknik_servis\ekipman.py`
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\app\api\servis_ekipman.py`
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\tests\integration\test_servis_ekipman.py` (yeni)
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\tests\integration\test_servis_ekipman_kapsam.py` (yeni)
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\tests\integration\test_servis_ekipman_gecmis.py` (yeni)
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\api\servisEkipman.ts`
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\components\EkipmanFormu.tsx`
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\components\EkipmanKarti.tsx`
- `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\pages\ServisEkipmanPage.tsx`

**Testler (dengeerp_test_e)**
- `alembic upgrade head`: hatasız.
- Benim üç test dosyam: 37 geçti, 0 kaldı.
- `tests/unit` + `test_router_kapsam_taramasi` + `test_yetki_matrisi` + `test_kapsam_guvenligi`: 314 geçti, 0 kaldı (sayı ilerleme çıktısındaki noktalardan sayıldı, pytest özet satırı yoktu).
- Ruff format ve check temiz. `npm run build` (tsc + vite) temiz; oxlint benim 4 dosyamda 0 uyarı.

**Plana göre verdiğim kararlar**
- Excel izni `ekipman.gor` + `servis_rapor.disaaktar` (plan §6.2; E03'teki `rapor.disaaktar` geçersiz).
- Kapsam dışı birime taşıma 404 (plan §1.2), E03'teki 403 değil.
- İrtibat adı kartta yalnız `servis.irtibat_gor` ya da `ekipman.yaz` olana gösteriliyor (KVKK en az erişim). Gösterildiğinde erişim KVKK loguna yazılıyor.
- API'den açılan kayıtta müşteri zorunlu (plan §1.5).
- `seri_ile_bul`'a isteğe bağlı `user=` parametresi ekledim; eski imzayla çağrılar bozulmaz.

**Şema talepleri:** yok.

**Diğer paketlere talepler**
- **D1-C:** `service_equipment` ek kapsamını `ekipman.py` kendi içinde kaydediyor (`ek_kapsam.kaydet`). D1-C aynı tür için ikinci bir fonksiyon kaydederse açılışta ValueError olur, kaydetmemeli. İsteğe bağlı: `EK_TURLERI`'ne `CIHAZ_ETIKETI`, `KURULUM_TUTANAGI`, `GARANTI_BELGESI` eklenebilir; şimdilik ön yüz `DIGER` türünü kullanıyor.
- **D1-F:** sözleşme listesindeki "Bağlı ekipman" sütunu için `ekipman.bagli_ekipman_sayilari(db, idler, an)`, TS-063 eşleştirmesi için `ekipman.seri_ile_bul(..., user=)` kullanılabilir. Bakım ziyaretleri geçmişe zaten giriyor, ikinci bir kaynak kaydetmeyin. Toplu "Sözleşmeye bağla" için bir uç gerekiyor.
- **D1-B:** kütükten toplu "Servis işi aç" için bir uç gerekiyor. Saha farkında otomatik bağlama `seri_ile_bul(account_id=...)` ile yapılabilir.
- **Dalga 2 (atölye, parça):** geçmişe olay eklemek için `ekipman.gecmis_kaynagi_kaydet(fn)`; maliyet anahtarları kullanıcıya göre otomatik çıkarılıyor.
- **Bilgi:** çalışma sırasında D1-G'nin `zaman.py` dosyası bir süre `import app.main`'i bozdu (`DURUM_GRUPLARI` `app.models`'ten import edilemiyordu). Sonraki denemede düzelmişti; ben dokunmadım.



# Paket sonucu 2

TS-070…078 paketinin tamamı yazıldı; tek eksik nokta ortak sayaç bandının her sayfada görünmemesi (TS-077). TS-076 ve TS-077 kısmen bitti: TS-076 için kapanış uçlarının yeni fonksiyonu çağırması, TS-077 için bandın donmuş `AppLayout.tsx`'e eklenmesi gerekiyor. Sahibi olduğum testler ve kapsam taraması/yetki matrisi yeşil. `npm run build` ve kendi dosyalarımda `ruff`/`oxlint` temiz.

## Madde durumu

| Madde | Durum | Not |
|---|---|---|
| TS-070 Manuel kayıt | TAMAM | Çakışma yazmadan önce sorgulanıyor; mesaj örneği: "10.03.2026 09:00-09:30 MOLA (SRV-…) ile çakışıyor". Kısıt yalnız yarışta devreye giriyor. 2 günden eski kayıt ve başkası adına kayıt `servis.planla` istiyor. Yalnız `sistem.kullanici` olan hesap 403 alıyor. Gerekçeli iptalde satır silinmiyor, iş geçmişine DUZELTME olayı ve denetim kaydı yazılıyor. |
| TS-071 Tek dokunuş akış | TAMAM | Yola Çıktım işi YOLA_CIKILDI, Sahaya Vardım SAHADA yapıyor (`kaynak='sayac'`). Açık sayaç varken başlatma 409 ("Önce açık sayacı bitirin: SRV-…"). Geçişte sıra kapat → flush → ekle. Çift basışta ikinci istek sürüm uyuşmazlığıyla 409. Her yanıtta `sunucu_zamani` var; ön yüz saat farkını buna göre düzeltiyor. |
| TS-072 Düzeltmeler | TAMAM | Unuttum her açık sayaçta kullanılabiliyor (kontrol belgesi B18 kararı). İlk 5 dakikada geri alma iz bırakıyor. Yönetici gerçek bitişle kapatabiliyor ya da iptal edebiliyor. 10 saati aşan veya dünden kalan sayaç için şefe birim kapsamlı, sahibine kendi uyarısı gidiyor. Sayaç kendiliğinden kapanmıyor. |
| TS-073 Kancalar | TAMAM | `acik_sayac_dogrula`: açık sayaçlı işte TAMAMLANDI/IPTAL 409. `acik_sayac_cikarma_dogrula`: açık sayaçlı kişiyi ekipten çıkarma 409 ("Önce Ali Veli'nin SRV-… işindeki sayacını bitirin…"). Kapalı ya da beklemedeki işte sayaç başlatılamıyor (409). |
| TS-074 Sonraki işe taşıma | TAMAM | Hedef iş açık değilse veya kişiye atanmamışsa 409 ve ilk işteki sayaç açık kalıyor. Bitiş ile yeni başlangıç mikrosaniyesine kadar aynı. |
| TS-075 Süre özeti | TAMAM | `sure_ozeti_toplu` ve `sure_eksik_ifadesi`: SQL ve Python tanımlarının aynı işleri seçtiği 9 senaryoluk testle kilitli. Kayıt yoksa süre `None` ve durum EKSIK. `or 0` / `coalesce` yasağı testle denetleniyor. Mola kişi-saate girmiyor. |
| TS-076 Kapanışta "süre eksik" onayı | KISMEN | `zaman.sure_eksik_kapanis_dogrula` yazıldı ve test edildi: onay yoksa 409 ("Süre kaydı eksik: Ali Veli. Onaylayarak kapatın."), onaylı kapanışta NOT olayı. **Eksik:** sonuç ucu, bakım formu tamamlama ve iş ekranındaki onay penceresi bu fonksiyonu henüz çağırmıyor (talepler aşağıda). |
| TS-077 Benim İşlerim | KISMEN | Tek uç (liste + kart), gruplar Geciken/Bugün/Yarın/Sonra/Plansız ve yerel gün sınırı testli. Aynı gün aynı tesis tek ziyaret kartı. Kartta fiyat/maliyet anahtarı yok. Kapsam dışı kart 404. Kameradan ek (`capture`) ve kılavuz bölümü 10.1 eklendi. **Eksik:** sayaç bandı yalnız Benim İşlerim ve iş kartı sayfalarında görünüyor, çünkü `AppLayout.tsx` donmuş. 375 px'te elle doğrulama yapmadım; yalnız build geçti. |
| TS-078 Bugünüm | TAMAM | Gün yerel. Yalnız kişinin kendi kayıtları; `user_id` parametresi verilirse 422. Eksik listesi süre eksik ifadesiyle aynı tanımı kullanıyor. Telefonla çözülen iş listeye girmiyor. |

## Plana göre verdiğim kararlar
- **Bölüm uçlarının yolu:** `/isler/{is_id}/zaman/bolumler/{bolum_id}/<eylem>` oldu. Kapsam taraması yalnız sözleşmedeki parametre adlarını tanıyor; `{bid}` kullansaydım test kırmızı olurdu.
- **Sahibi istisnası:** kişi kendi sayacına her zaman erişiyor. Başkasının sayacında iş kapsam dışıysa 404, kapsam içindeyse 403.
- **Durum kuralları:** kapalı ya da beklemedeki işte sayaç başlatma ve kişiye atanmamış hedef 409; kendine atanmamış işte başlatma 400.
- **"Süre beklenmiyor" durumları:** MUSTERI_TALEBI, PLANLAMADA, PLANLANDI, BEKLEMEDE, TEKRAR_ACILDI ve IPTAL ile telefon/uzaktan çözülen işler. "Süre eksik" = EKSIK ya da KISMI.

## Değişen dosyalar
- Arka uç: `backend\app\services\teknik_servis\zaman.py`, `backend\app\services\teknik_servis\mobil.py`, `backend\app\api\servis_zaman.py`
- Testler: `backend\tests\unit\test_zaman_hesap.py`, `backend\tests\integration\zaman_ortam.py`, `backend\tests\integration\test_servis_zaman_kayit.py`, `backend\tests\integration\test_servis_zaman_akis.py`, `backend\tests\integration\test_benim_islerim.py`
- Ön yüz: `frontend\src\api\servisZaman.ts`, `frontend\src\components\SayacDugmeleri.tsx`, `frontend\src\components\AktifSayacBandi.tsx`, `frontend\src\components\EkYukleyici.tsx` (yalnız `capture` prop'u eklendi), `frontend\src\pages\BenimIslerimPage.tsx`, `frontend\src\pages\ServisIsKartiMobil.tsx`
- Belge: `docs\KULLANIM-KILAVUZU.md` (bölüm 10 güncellendi, 10.1 eklendi)

Tüm yollar `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\` altında.

## Hedefli test sonuçları (`dengeerp_test_g`)
- `tests/unit` + kendi entegrasyon dosyalarım: 373 geçti, 0 başarısız (73'ü bu paketin testi).
- `test_router_kapsam_taramasi`, `test_yetki_matrisi`, `test_teknik_servis_saat`: 15 geçti, 0 başarısız.

## Şema talepleri
Yok; mevcut şema yetti.

## Diğer paketlere talepler
- **D1-B:** Sonuç ucu (TAMAMLANDI'ya giden yol) gövdesine `sure_eksik_onay: bool = False` eklenmeli ve TAMAMLANDI'dan önce `zaman.sure_eksik_kapanis_dogrula(db, so, onay=..., user=..., clock=...)` çağrılmalı. İş detayı, liste ve Excel süre için `zaman.sure_ozeti_toplu` kullanmalı.
- **D1-C:** İş ekranında, detaydaki `sure_durumu` EKSIK ya da KISMI ise kaydetmeden önce onay penceresi gösterilmeli ve `sure_eksik_onay=true` gönderilmeli. İş detayına "Zaman" kartı eklenmeli: `GET /isler/{id}/zaman` ve hazır `ManuelKayitPenceresi` bileşeni kullanılabilir. Panel "süre eksik" KPI'sı `zaman.sure_eksik_ifadesi()` ile hesaplanmalı.
- **D1-F:** Bakım formu tamamlamada aynı `sure_eksik_kapanis_dogrula` çağrısı.
- **D1-D:** Plan üyesi çıkarılan her yolda `kancalar.ekip_degisiyor` çağrılmalı; yoksa açık sayaç kontrolü atlanır.
- **D2-S (AppLayout'un sonraki sahibi):** `<AktifSayacBandi/>` `<Outlet/>`'in üstüne eklenmeli; bileşen `zaman.yaz` yoksa ne çizer ne istek atar.
- **D3-B:** Kişi-saat hesabı `zaman.sure_ozeti_toplu` üzerinden yapılmalı.



# Paket sonucu 3

**D1-D (Planlama) raporu: TS-040…049**

P1 ve P2 maddelerinin arka uç kodu yazıldı ve hedefli testlerden geçti. Ön yüz derlendi ama tarayıcıda denenmedi. Eksik kalan iki şey var: bakım ekranından PB toplu planlama bağlantısı (dosya D1-F'nin) ve takvim performans testi.

**Hedefli test sonucu:** `tests/unit` + 10 yeni entegrasyon dosyası + `test_router_kapsam_taramasi` + `test_yetki_matrisi` birlikte koşuldu: **386 geçti, 0 hata**. Ruff (format + check) kendi dosyalarımda temiz. `npm run build` ve oxlint temiz; tsc projede hata vermedi.

**Madde durumu**

| Madde | Durum | Not |
|---|---|---|
| TS-040 Tek aktif plan, kapalı işi geri çekmeme | TAMAM | Eşzamanlı iki istekte tek aktif satır kalıyor. MUSTERI_TALEBI/PLANLAMADA/TEKRAR_ACILDI → PLANLANDI. Sahada, atölyede ya da beklemedeki işte durum korunuyor. Kapalı işte dört uç da 409 veriyor ve hiçbir şey değişmiyor. |
| TS-041 Tekli plan + ekip | TAMAM | `PUT /isler/{is_id}/plan` + `beklenen_aktif_plan_id`; uyuşmazlık 409, şema ihlali 422. Ekip `atama.ata` ile yazılıyor. Araç pasif ya da başka birimin ise 409. Hata enjekte edildiğinde ne plan ne üye ne atama yazılıyor. |
| TS-042 Takvim, havuz, KPI, KENDI_ISLERI | KISMEN | Takvim en çok 62 gün, havuz lokasyon ve şehir/ilçe gruplamalı, 6 KPI'da sayı = liste testli, teknisyen yalnız kendi işini görüyor. Eksik: `slow` işaretli performans testi yazılmadı, çünkü işaret `pyproject.toml`'da kayıtlı değil. |
| TS-043 Toplu plan, PB toplu plan | KISMEN | `POST /toplu-plan`: 17 iş tek ziyarette ayrı planlara dönüşüyor. Karışık birim/müşteri/lokasyon ya da kapalı/planlı iş 409 + iş no listesi veriyor, 151 iş 422. Eksik: bakım dönem ekranından aynı pencereyle açılış. `PlanPenceresi` "toplu" modunda hazır; bağlamayı D1-F yapmalı. |
| TS-044 Erteleme nedeni, geri alma, geçmiş | TAMAM | Nedensiz erteleme ve nedensiz geri alma 409. PLANLANDI → PLANLAMADA; diğer durumlar korunuyor. `/plan-gecmisi` planlayan ve nedenle bütün satırları veriyor. |
| TS-045 Çakışma, "şef sahaya gidiyor" | TAMAM | 409 gövdesi `{detail, kod:'PLAN_CAKISMA', cakismalar}`. En az 10 karakterlik gerekçeyle geçilebiliyor. Kapsam dışı iş maskeli dönüyor. Kilit gün sırasıyla alınıyor (gece yarısını aşan plan iki günü kilitliyor). Ön izleme ucu `POST /kontrol`. |
| TS-046 Ziyaretten seçilenleri taşıma | TAMAM | Tarih değişirse YENIDEN_PLAN ve neden zorunlu; yalnız ekip/araç değişirse EKIP_DEGISIMI. Seçilmeyen iş eski planında kalıyor. |
| TS-047 Saha önerisi | TAMAM | Adres ve irtibat yalnız aynı müşterinin tesisinden geliyor. Telefon yalnız `servis.irtibat_gor` iznine ya da işin ekibine gösteriliyor. |
| TS-048 Servis araç havuzu | TAMAM | `servis.arac_yaz` izni; plaka anahtarı tekil (409); birim NULL = ortak havuz; birim kapsamı 404 + veri değişmedi testli; `vehicles` yalnız okunuyor. Güncelleme `PATCH /araclar` ile ve kimlik gövdede (gerekçe aşağıda). |
| TS-049 Uyarılar, Excel, irtibat gizliliği, KVKK | TAMAM | Excel `?baslangic=` boşken 200 ve satır sayısı takvimle aynı; izin `servis.gor` + `servis_rapor.disaaktar`. İrtibat alanları izinsizde null. Planlama uyarıları birim ve KENDI_ISLERI kapsamlı. Hesap anonimleştirmesi plan ve ziyaret notlarını temizliyor. |

**Planla bilinçli farklar**
- Başka birimin kişisi ekipte olunca 409 dönüyor (E02-03 400 diyordu). Kuralı tek yerde tutmak için `atama` modülünün doğrulayıcısını kullandım; D1-B 409 seçmiş.
- `api.delete` gövde de alabilecek şekilde genişletildi; plan geri alma bu yolla neden ve not gönderiyor. Plan yalnız `ApiError.govde` eklemesine izin veriyordu; bu değişikliğin onayı gerekiyor.

**Değişen dosyalar**
- Arka uç:
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\app\services\teknik_servis\planlama.py`
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\app\services\teknik_servis\takvim.py`
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\app\services\teknik_servis\cakisma.py`
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\app\api\teknik_servis_planlama.py`
- Ön yüz:
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\api\servisPlanlama.ts`
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\api\client.ts`
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\components\PlanPenceresi.tsx`
  - `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\frontend\src\pages\ServisPlanlamaPage.tsx`
- Testler, `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\backend\tests\` altında:
  - `integration\planlama_yardim.py` (ortak kurulum)
  - `integration\test_servis_planlama_tekli.py`, `_durum.py`, `_eszamanli.py`
  - `integration\test_servis_toplu_plan.py`, `test_servis_plan_gecmisi.py`, `test_servis_yeniden_plan.py`
  - `integration\test_servis_cakisma_eszamanli.py`, `test_servis_saha_onerisi.py`, `test_servis_araclar.py`, `test_servis_takvim.py`
  - `unit\test_servis_cakisma.py`

**Şema talepleri:** Model/migration değişikliği gerekmedi; mevcut şemayla çalışıldı. Donmuş dosyalar için iki talep:
1. `kancalar.ekip_degisti` imzası saat (Clock) taşımıyor. Şimdilik zaman, atama satırlarının Clock ile yazılmış en son damgasından alınıyor; imzaya `clock` eklenmeli (D2-S).
2. `pyproject.toml` işaret listesine `slow` eklenmeli; takvim performans testi bunu bekliyor.

**Diğer paketlere talepler**
- **Kapsam taraması:** `test_router_kapsam_taramasi.py` tanıdığı parametre adlarına `arac_id` (hedef: servis aracı, başka birim) eklenmeli. Eklenince araç güncellemesi `PATCH /araclar/{arac_id}` yoluna taşınabilir; şimdilik kimlik gövdede, kapsam kontrolü yine yazmadan önce yapılıyor.
- **D1-F:** PB dönem ekranında `PlanPenceresi` "toplu" modunda açılsın (TS-043, E04-12). Sunucu ucu hazır.
- **D1-C:** İş detayında "Plan Geçmişi" sekmesi `GET /planlama/isler/{id}/plan-gecmisi` ucunu kullanabilir.
- **D1-B:** `atama._satirlari_dogrula` ve `atama._atanabilirlik_dogrula` planlamadan çağrılıyor; adları değişirse planlama bozulur.



# Paket sonucu 4

# D1-C raporu (TS-032…TS-037)

TS-032, TS-033, TS-035 ve TS-036 tamam. TS-034 ile TS-037 kısmen tamam. Eksik kalan parçaların hepsi başka paketlerin dosyalarına bağlı; onlar için talep yazdım.

Hedefli testler `dengeerp_test_c` üzerinde koştu: **430 geçti, 1 atlandı, 0 hata**. Kapsam: `tests/unit` ile `test_servis_ekler`, `test_servis_panel`, `test_servis_onay`, `test_ortak_kayit_noktalari`, `test_ekler`, `test_router_kapsam_taramasi`, `test_yetki_matrisi`, `test_ana_veri_kvkk`. Atlanan tek test PDF ucu: bu makinede WeasyPrint kitaplıkları yok. Kendi dosyalarımda ruff format/check temiz, `npm run build` başarılı.

**Önemli bulgu:** Panel, onay ve PDF uçlarını D1-B `a/teknik_servis.py` içine zaten yazmış ve benim servis fonksiyonlarımı çağırıyor. Bu yüzden ayrı API dosyası açmadım, D1-B'nin dosyasına da dokunmadım.

## Madde durumu

| Madde | Durum | Açıklama |
|---|---|---|
| TS-032 (P1) Ekler | TAMAM | Okuma birim veya kendi işi; yazma için aktif atama şart (plan üyeliği yetmez). Magic-byte uyuşmazlığı servis işinde 400, diğer teknik servis türlerinde Dalga 0'daki 422 korundu. Kapalı işe ek ekleme/silme yalnız `servis.kapat` ile. Yükleyen kişi 24 saat içinde siler; süre EK olayının Clock zamanından sayılır. Onaya bağlı ek silinirse 409. EK_SIL olayı dosya adı ve sha256 tutar. Canlı ek türlerinin davranışı değişmedi. |
| TS-033 (P1) Servis İşleri ön yüzü | TAMAM | Liste sunucuda süzülüp sayfalanıyor; süzgeç URL'de, `?kpi=&donem=` ile panelden açılıyor. Excel, toplu atama ve ziyaret onayı/formu var. Drawer'da düğmeler sunucunun `gecisler` listesinden ve `yetkili()` ile çiziliyor. Durum, bekleme, sonuç, kapat, iptal, yeniden aç, ekip ve onay pencereleri var. 409'da kayıt yenileniyor ve kullanıcıya söyleniyor. TS-076'nın "süre kaydı eksik" onayı sonuç penceresinde. 375 px için duyarlı düzen yazdım ama tarayıcıda gözle doğrulamadım. |
| TS-034 (P1) Müşteri-lokasyon-irtibat seçici | KISMEN | 300 ms gecikmeli sunucu araması, hızlı ekleme (`servis.yaz` + `lokasyon.yaz`) ve IBAN/VKN göstermeyen tesis kartı var. Seçilen lokasyonun birincil irtibatı forma öneriliyor; eşleşirse `contact_id` gönderiliyor. Eksik: öneri yalnız `hesap.gor` ya da `lokasyon.yaz` olana çalışıyor (sunucu kuralı), bu izni olmayan teknisyende öneri yok. Lokasyondaki tüm irtibatların listesinden seçim de yapılmadı. Planlamadan ön dolum D1-D'nin işi. |
| TS-035 (P1) Panel ve KPI kaydı | TAMAM | 22 KPI tek kayıtta; her kutu sayısı = `/isler?kpi=` X-Toplam-Kayit (test edildi). Dönem seçimi tarayıcıda hatırlanıyor, birim kapsamı uygulanıyor. "Atölyede" = kategori ATOLYE ve açık; "bugün planlı" var; PB servis kutularında sayılmıyor. Süre kaydı yoksa "0" değil "eksik" gösteriliyor. |
| TS-036 (P2) Onay ve servis formu PDF | TAMAM | Dört onay biçimi (imza canvas'ı IMZA eki olarak yükleniyor). Onay değişmez; yenisi eskisini `gecersiz_kilan_id` ile geçersiz kılıyor. `servis_onay_zorunlu_turler` tamamlamada kanca ile kontrol ediliyor (409). Ziyaret onayı tek `onay_grubu`, aynı müşteri/lokasyon/gün dışı 409, kapsam dışı 404. Şablon fiyatsız; süre yoksa "Süre kaydı eksik"; PB'de kontrol listesi bloğu var. Anonimleştirmeden sonra imza eki 404 dönüyor. |
| TS-037 (P2) Uyarılar, görev, arama, KVKK | KISMEN | Yapılanlar: üç servis uyarısı (kapsamlı, izinli, sayı = liste); detaya "Görevler" sekmesi; anonimleştirme, veri bulma ve denetim satırı maskeleme kancaları. Arama fonksiyonu `panel.servis_ara` kapsamlı çalışıyor ama `/api/arama`'ya bağlı değil — kayıt D1-B'nin API dosyasında yapılmalı. Eksik: saklama listesinin servis işi olan müşteriyi dışarıda tutması (`sv/kvkk.py` donmuş, kanca yok). |

## Değişen dosyalar

Kök: `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp\`

- **Arka uç:**
  - `backend\app\services\teknik_servis\ek_kapsam.py` — servis işi dalı ve sahip türüne göre ek kuralı kayıt defteri.
  - `backend\app\api\attachments.py` — kural kancaları, Clock, 400/409 kodları.
  - `backend\app\services\teknik_servis\panel.py`
  - `backend\app\services\teknik_servis\onay.py`
  - `backend\app\templates\servis_formu.html`
- **Testler (yeni):**
  - `backend\tests\integration\test_servis_ekler.py` — 14 test
  - `backend\tests\integration\test_servis_panel.py` — 9 test
  - `backend\tests\integration\test_servis_onay.py` — 21 test (1 atlandı)
- **Ön yüz:**
  - `frontend\src\api\teknikServis.ts`
  - `frontend\src\pages\ServisIsleriPage.tsx`
  - `frontend\src\pages\ServisIsFormu.tsx`
  - `frontend\src\pages\ServisPaneli.tsx`
  - `frontend\src\components\MusteriLokasyonSecici.tsx` — yalnız isteğe bağlı `onSahaOnerisi` eklendi, mevcut kullanımı bozmaz.

## Şema talebi
- Yok. Uyarı eşikleri (kapanış bekleyen 3 gün, uzun bekleme 7 gün) plan §1.9 ayar listesinde olmadığı için `panel.py` içinde kod sabiti. Ayar olması isteniyorsa `servis_kapanis_bekleme_uyari_gun` ve `servis_bekleme_uyari_gun` anahtarları için **ayar talebi**.

## Diğer paketlere talepler
1. **D1-B, `is_emirleri.liste_sorgusu`:** `tanim.suzgec(stmt, user, clock)` çağrısına `donem=f.donem` geçirilmeli. Şu an dönemsel kutularda varsayılan dışı dönem seçilirse panel sayısı ile liste toplamı ayrışır; varsayılan dönemde eşit.
2. **D1-B, `a/teknik_servis.py`:** Servis formu ve ziyaret formu PDF uçları `PdfUretilemedi`'yi yakalayıp 503 dönmeli (teklif ucundaki gibi); şu an 500 düşüyor.
3. **D1-B, `a/teknik_servis.py`:** `/panel` ucuna `birim` parametresi eklenmesi isteğe bağlı; `panel_ozeti(birim=)` hazır.
4. **D1-B, `a/teknik_servis.py`:** Genel aramaya bağlamak için şu kayıt eklenmeli: `@arayici_kaydet("servis.gor") async def _servis_ara(db, user, terim, limit): return [AramaSonucu(**s) for s in await panel.servis_ara(db, user, terim, limit)]`.
5. **D0-C / D2-H (`sv/kvkk.py`):** `saklama_suresi_dolanlar` için bir hariç tutma kanca kayıt defteri gerekiyor; son N yılda servis işi olan müşteri listeden çıkmalı.
6. **D1-F:** `frontend\src\pages\BakimPage.tsx(554)` satırında tsc hatası var: `KayitGorevleri`'ne `tip/kayitId` veriliyor, doğrusu `entity/entityId`. Bu hata derlemeyi kırıyor, benim dosyalarımda değil.



# Paket sonucu 5

**D1-F Planlı bakım (TS-060…069): rapor**

TS-060…068 bitti. TS-069'da KVKK tarafı sınırlı kaldı. Paketin hedefli testleri ve yetki matrisi, kapsam taraması, ortak kayıt noktaları testleri birlikte koşuldu: **395 geçti, 0 kaldı**. Bunların 42'si bu paketin yeni testi. Ön yüz `npm run build` temiz (tsc + vite), oxlint 0 hata. Kendi dosyalarımda ruff check ve format temiz.

**Madde durumu**

| Madde | Durum | Not |
|---|---|---|
| TS-060 | TAMAM | Sözleşme ekleme, düzenleme, durum (makine), tür+adet kapsam ve ayrı ücret ucu (`bakim.yaz` + `maliyet.gor`) yazıldı. Ücreti görmeyen kullanıcının yanıtında ücret alanı hiç yok; ücret gönderirse 403 ve hiçbir şey yazılmaz. Aynı tesiste dönemi çakışan sözleşme 409 alır; onay + gerekçe ile geçilir ve denetime yazılır. **Karar:** çakışma aktifleştirmede ve aktif sözleşmenin düzenlenmesinde aranır, TASLAK açılışta aranmaz. |
| TS-061 | TAMAM | Dönemler sözleşme yılına göre hesaplanır, sayaç saklanmaz. Elle değiştirilen hedef tarih korunur. Dönem kapanışı tekrar çalıştırılabilir ve geri açılabilir. |
| TS-062 | TAMAM | Kalem başına tek PB, `ON CONFLICT … WHERE tur='PB'` ile; ikinci tur 0 PB üretir. Atlananlar gerekçesiyle yazılır (EKIPMAN_YOK, SURESI_DOLMUS, SABLON_YOK, TEYIT_BEKLIYOR, HATA). Önizleme aynı motoru SAVEPOINT içinde koşar, hiçbir şey yazmaz. Worker görevi `pb-uretimi` ayar kapalıyken üretmez. Eksik PB ucu var. Elle üretim kullanıcının kapsamıyla sınırlı. Kontrol maddeleri eski koddan aynen taşındı (X-Ray 11, kapı dedektörü 10). |
| TS-063 | TAMAM | Tek aday varsa öneri gelir, birden çok aday listede kalır, şef onaylar; oran ekranda. Otomatik üretim %100 olmadan açılamaz (409). **Karar:** bu bayrağı yalnız tüm birimleri gören (TUMU kapsamlı) kullanıcı değiştirir; birim şefi 403 alır. |
| TS-064 | TAMAM | Taslak kaydı, tamamlama ve değişmez ziyaret kaydı çalışıyor. Bekleyen madde varken tamamlama 409; uygunsuz madde notsuzsa 400; müşteri onayı zorunlu. Sahadaki seri kütükten farklıysa kütük farkı açılır. Ekipman başka sözleşmenin kapsamındaysa (EXCLUDE) bağ kurulmaz ama tamamlama bloke olmaz, uyarı döner. **Karar:** "Tekrar Gidilecek" sonucunda ziyaret yazılır, form ve iş açık kalır. |
| TS-065 | TAMAM | PB koruma kancası kayıtlı: genel uçtan TAMAMLANDI ya da İPTAL, `/sonuc` ve `/iptal` 409 alır. Dönem kapanışı durum kancasında güncellenir. Gece görevi `bakim-donem-uzlastirma` farkı düzeltir ve log'a yazar. |
| TS-066 | TAMAM | Kapsam dışı talebi açılır; kişi kendi talebini onaylarsa 409. Onayda PB İPTAL olur ve aynı cihaz-dönem yeniden üretilmez. Bir cihaz tamamlanıp diğeri kapsam dışı onaylanınca dönem KISMI kapanır. |
| TS-067 | TAMAM | Uygunsuz madde aksiyon açar ve PB'yi BAKIM_UYGUNSUZLUK beklemesine alır. Son aksiyon kapanınca PB kendiliğinden TAMAMLANDI olur. Bağlı arıza işi `BAKIM_BULGUSU` ilişkisiyle açılır. TEKLIF aksiyonu Dalga 1'de pasif (409). |
| TS-068 | TAMAM | Yeniden açma D1-B'nin `/isler/{id}/yeniden-ac` ucuyla yapılır. Kanca formu TASLAK'a döndürür, gerekçeli YENIDEN_ACMA ziyaret satırı yazar ve dönemi açar; yeniden tamamlanınca dönem tekrar kapanır. |
| TS-069 | KISMEN | Uyarılar kayıtlı ve birim kapsamlı: geciken dönem, teyit bekleyen, bitişi yaklaşan, kişinin kendi talebi hariç kapsam dışı talepleri. KPI kutusundaki sayı açtığı listenin sayısıyla aynı (testli). Sözleşme ekleri için kapsam kontrolü kayıtlı. **Eksik:** KVKK tarafında yalnız denetim kaydı maskeleme kancası var; sözleşme/form serbest metinleri (not, teknisyen notu) anonimleştirilmiyor. |

**Değişen dosyalar**
- Arka uç: `backend/app/api/bakim.py` (32 uç), `backend/app/services/teknik_servis/bakim.py`, `bakim_uretim.py`, `bakim_formu.py`, `bakim_sablonlari.py`, `backend/app/worker.py` (`pb-uretimi` ve `bakim-donem-uzlastirma` görevleri)
- Ön yüz: `frontend/src/api/bakim.ts`, `frontend/src/pages/BakimPage.tsx`, `frontend/src/pages/BakimFormu.tsx`
- Testler: `backend/tests/unit/test_bakim_takvim.py` (10), `backend/tests/integration/test_bakim_sozlesme.py` (10), `test_servis_bakim_eslestirme.py` (4), `test_bakim_uretim.py` (8), `test_bakim_formu.py` (10), yardımcı `bakim_yardimci.py`

**Şema talepleri:** yok. Mevcut şemayla çalışıldı.

**Diğer paketlere talepler**
1. **Ayarlar (`api/settings_api.py` / `sv/settings.py`, donmuş):** genel `PATCH /api/ayarlar` ucu `bakim_otomatik_uretim`'i eşleştirme oranına bakmadan açabiliyor. Bu anahtar genel uçta reddedilmeli ya da `bakim.otomatik_uretim_ayarla` üzerinden geçmeli; şu an %100 kuralı bu yoldan delinebiliyor.
2. **Ayar anahtarı:** bitişi yaklaşan sözleşme uyarısı için `bakim_sozlesme_bitis_uyari_gun` (60) DEFAULTS'ta yok; şimdilik kod sabiti.
3. **D1-C:** servis formu PDF'inde PB kontrol listesi bloğu `maintenance_form_checks`'ten okunmalı (TS-036). Servis İşleri ekranına `BakimFormu` bileşeniyle bir "Bakım Formunu Aç" düğmesi eklenebilir.
4. **D1-B:** yeniden açma kancası gerekçeyi DURUM olayının özetindeki "— gerekçe:" metninden okuyor. Biçim değişecekse gerekçe `veri["gerekce"]` anahtarına da yazılmalı.
5. **D1-E:** ekipman kartı bakım geçmişi için `GET /api/teknik-servis/bakim/ekipman/{ekipman_id}/bakim-gecmisi` ucunu kullanabilir.



# Paket sonucu 6

**D1-B raporu: Servis iş emri arka ucu (TS-020…TS-031)**

TS-020…TS-031 maddelerinin hepsi yazıldı, hiçbir madde EKSİK değil. Hedefli koşuda 388 test geçti, 0 hata (kendi testlerim + `tests/unit` + yetki matrisi + kapsam taraması). Ön yüz derlemesi (`npm run build`) ve `oxlint` temiz. Ruff kendi dosyalarımda temiz.

**Madde durumu**
| Madde | Durum | Not |
|---|---|---|
| TS-020 Açılış, detay, numara, PB değişmezleri | TAMAM | |
| TS-021 Tek `durum_degistir` | TAMAM | |
| TS-022 Olay geçmişi ve iş notu | TAMAM | |
| TS-023 Bekleme ve neden kataloğu | TAMAM | |
| TS-024 Sonuç, çözüm kanalı, arıza nedeni | TAMAM | |
| TS-025 Atama, toplu atama, ekip senkronu | TAMAM | "Aktif planda plan üyeleri = atamalar" kuralı D1-D'nin `ekip_degisti` kancasıyla sağlanıyor; ben yalnız kancanın doğru çağrıldığını sınadım. |
| TS-026 Liste ve Excel | KISMEN | İşlev tam; "10.000 işte liste < 1 sn" ölçümü yapılmadı. |
| TS-027 Kapsam ve telefon maskeleme | TAMAM | |
| TS-028 Mobilite etkisizlik | TAMAM | |
| TS-029 Talep bilgisi, mükerrer kontrolü (P2) | TAMAM | Kanal ve irtibat zorunluluğu yalnız ekrandan açılışta (API) uygulanıyor; sistem açılışları muaf. |
| TS-030 Bağlı iş (P2) | TAMAM | |
| TS-031 Gerekçeli düzeltme (P2) | KISMEN | Kategori yalnız türden türetiliyor; E01-16'daki "kategoriyi `servis.kapat` ile gerekçeli düzeltme" yazılmadı. |

**Değişen dosyalar**
- Arka uç:
  - `backend/app/services/teknik_servis/is_emirleri.py`, `gecmis.py`, `bekletme.py`, `sonuc.py`, `atama.py`
  - `backend/app/api/teknik_servis.py`
  - `backend/app/services/export.py`: yalnız yeni çok sayfalı, tipli Excel fonksiyonu eklendi; `satirlari_xlsx` değişmedi.
- Ön yüz: `frontend/src/pages/ServisTanimlarPage.tsx` (arıza nedeni ve bekleme nedeni sekmeleri).
- Yeni testler:
  - `backend/tests/integration/`: `servis_yardimci.py`, `test_servis_is_emri.py`, `test_servis_durum.py`, `test_servis_bekleme.py`, `test_servis_sonuc.py`, `test_servis_atama.py`, `test_servis_ekip_senkron.py`, `test_servis_kapsam.py`, `test_servis_excel.py`, `test_servis_musteri_duzeltme.py`, `test_servis_mobilite_etkisizlik.py`
  - `backend/tests/unit/`: `test_servis_durum_gruplari.py`, `test_servis_olay_gecmisi.py`, `test_servis_bagimsizlik.py`
- `s/kapsam.py`'de değişiklik gerekmedi; D0-A'nın hâli yeterliydi.

**Test sayıları**
- Bu paketin testleri: 75 (58 entegrasyon + 17 unit).
- Hedefli koşu: 388 geçti, 0 hata. Son değişiklikten sonra tekrarlandı.
- Tüm servis ve bakım entegrasyon dosyaları (diğer paketlerinkiler dahil) süre kontrolü eklenmeden önce yeşildi. Bu değişiklikten sonra `/sonuc` ucunu kullanan dosyalar (`test_bakim_formu`, `test_servis_onay`, `test_servis_zaman_akis`) yeniden koşuldu ve yeşil.

**Şema talepleri:** Yok.

**Diğer paketlere talepler**
- **D1-F, D2 atölye, D2 kiralama:** Sonuçsuz TAMAMLANDI artık her yoldan 409. Durumu TAMAMLANDI yapmadan önce `sonuc.sonuc_kaydet` ile COZULDU ya da COZULEMEDI sonucu yazılmalı. `bakim_formu.py` bunu zaten yapıyor.
- **PB/kiralama üretimi yapanlar:** `ServisIsiGirdisi`'ne sona eklenen alanlar var: `contract_item_id`, `maintenance_period_id`, `coverage_status`, `coverage_snapshot`, `numara_tarihi`. PB işi açılırken `contract_item_id` ve `maintenance_period_id` dolu olmalı, yoksa şemadaki PB kısıtı açılışı reddeder.
- **D1-G:** Sonuç ucu TAMAMLANDI yolunda D1-G'nin "süre kaydı eksik" kontrolünü (`zaman.sure_eksik_kapanis_dogrula`) çağırıyor. Süre kaydı yoksa istemci `sure_eksik_onay: true` göndermeli, aksi hâlde 409 döner.
- **D1-D:** `planlama.py`, `atama._satirlari_dogrula` ve `_atanabilirlik_dogrula` fonksiyonlarını doğrudan kullanıyor. Adları sabit tuttum; dalga sonunda bunları açık (alt çizgisiz) adlara çevirmeyi öneririm.
- **D1-C:** Panel ucu sözlük döndürüyor ve `birim` parametresi alıyor. Liste ucunda `kpi` süzgeci D1-C'nin `panel.kpi_uygula` fonksiyonunu kullanıyor. PDF uçları `onay.servis_formu_pdf` ve `onay.ziyaret_formu_pdf`'i çağırıyor. Yanıt şekilleri `fa/teknikServis.ts` ile uyumlu.
- **D0-B / D2-S:**
  - Kapsam taraması yalnız bilinen yol parametrelerini tanıdığı için katalog düzenleme uçlarını yol parametresiz yazdım: `PUT /tanimlar/ariza-nedenleri` ve `PUT /tanimlar/bekleme-nedenleri`, kimlik gövdede. İleride tarama sözlüğüne katalog kimliği eklenmesi önerilir.
  - Arıza ve bekleme nedeni tabloları test temizliğinde boşaltılmıyor (tohum veri korunsun diye). Bu yüzden testlerim eklediği satırları kendisi siliyor.

