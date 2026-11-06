# E08 Eğitim, Yetkinlik ve Saha Gözlemi: Bağımsız Kontrol Raporu

> Tarih: 21.10.2026 · Denetlenen: `10_canli_entegrasyon/08_egitim_yetkinlik_entegrasyon.md`
> Yöntem: Canlı kod okundu (`denge-erp/backend/app`: `permissions.py`, `models/user.py`, `models/attachment.py`, `api/attachments.py`, `api/deps.py`, `api/users.py`, `services/kvkk.py`, `services/uyarilar.py`, `services/gorevler.py`, `services/statemachine.py`, `services/export.py`, `services/auth.py`, `clock.py`, `main.py`, `seeds/dev.py`, `tests/conftest.py`, `tests/unit/test_permissions.py`, `tests/unit/test_statemachine.py`). Kardeş belgeler E01, E02, E12, E13 ve eski analiz özeti (`_ozet/08_egitim_yetkinlik.json`) karşılaştırıldı. Kaynak koda dokunulmadı.

---

## 1. Genel hüküm

Tasarımın ana yönü doğru:
- Yeni alan mobilite zincirinden tamamen ayrı. `work_orders`, `work_order_items`, `settlements` ve `devices` tablolarına yazılmıyor; canlı CHECK/EXCLUDE kısıtlarına dokunulmuyor. Gözlem yalnız E01 `service_orders`'a bağlanıyor (K5).
- Kişi = `users` (K1). Ayrı personel tablosu açılmıyor; bu E01 K15 ve E13 K-01 ile tutarlı.
- Eğitim maliyeti tutulmuyor, `maliyet.gor` kümesi değişmiyor.
- Takip, geçerlilik, son yetkinlik ve uyarılar hesaplanıyor, saklanmıyor. Bu `services/uyarilar.py:9-12` ilkesine uyuyor.
- Kapsam yanıt kodları (K4: URL'deki kayıtta 404, gövdedeki katalogda 403) canlı kuralla ve `api/attachments.py:94-97` gerekçesiyle uyumlu.

"Canlıda YOK" tespitleri doğru. `backend/app` altında `training|egitim|yetkinlik|competenc|gozlem|personnel|certificate` için tek eşleşme `migration/cihaz_sim.py`'deki ilgisiz "gözlem anı" değişkeni. Eğitim izni, tablosu, uyarısı ya da sayfası yok.

21 onaylı kaynak maddenin hepsi izlenebilirlik tablosunda karşılanıyor. Reddedilen kısımlar (TrainingChangeLog, ad eşleşmeli "atama dışı" bayrağı, zorunlu sınav eşiği, overview bölme, müdür onayı + otomatik kapanış) geri sokulmamış.

**Asıl sorunlar canlı kodla değil, kardeş tasarımlarla ve birkaç teknik ayrıntıyla ilgili:**
- E13 aynı persona için ayrı bir `IK` rolü açıyor; E08 ise `EGITIM_SORUMLUSU` açıyor. Canlıda kullanıcı başına tek rol var (`users.role_id`), bu yüzden İK personeli ikisini birden taşıyamaz.
- E13, E08 K2'deki "rastgele parola" yöntemini `giris_acik` kolonuyla, "ayrıldı" bilgisini de `ayrilis_tarihi` ile değiştiriyor. E08'in "pasif personel" ve "girişsiz personel" tanımları buna göre güncellenmeli.
- E12 ortak `KpiKutusu` bileşenini, `KpiTanimi` sözlüğünü ve "her xlsx denetim izine" kuralını tanımlıyor. E08-23 ve E08-12 bunlara atıf yapmıyor.

| # | Çakışma | E08 | Kardeş belge / canlı | Karar |
|---|---|---|---|---|
| 1 | İK rolü | Yeni `EGITIM_SORUMLUSU` (TUMU) | E13 K-13: yeni `IK` (TUMU, `personel.*`, `gorev.*`). Canlıda kullanıcı başına tek rol (`models/user.py:18`) | `egitim.gor/detay/yaz` + `rapor.gor/disaaktar` E13 `IK` rolüne eklenir; `EGITIM_SORUMLUSU` açılmaz. Eğitimden ayrı bir İSG uzmanı varsa kullanıcı teyidiyle açılır ve `personel.gor` da alır. |
| 2 | Girişsiz personel | K2: `is_active=true` + rastgele parola, `users`'a kolon yok | E13 K-03: `giris_acik=false`, `POST /api/personel` | E13 yolu esas alınır. K2 "E13 öncesi geçici yol" olarak kalır. |
| 3 | "Pasif personel" | `users.is_active=false` | E13: `is_active` + `ayrilis_tarihi`; `cikis_uygula` ikisini birlikte yazar | Süzgeç `is_active AND ayrilis_tarihi IS NULL` olur (E13 yoksa yalnız `is_active`). `giris_acik` filtrelenmez. |
| 4 | Personel listesi | `GET /api/egitim/kisiler` (kendi sorgusu) | E13 `services/teknik_servis/personel.py` + `kapsam_personel` (ortak) | Liste sorgusu E13 servis fonksiyonundan çağrılır; uç izni `egitim.gor` kalır. |
| 5 | KPI kutusu | Kendi `KPI_TANIMLARI` ve kutu kodu | E12 `KpiKutusu.tsx`, `KpiTanimi` (E01-14 kalıbı) | Ön yüz `KpiKutusu`'nu kullanır; eğitim KPI'ları aynı `KpiTanimi` biçimiyle `egitim_rapor.py`'de durur. |
| 6 | Çok sayfalı xlsx | E01-15 `sayfalari_xlsx_async` | E12: `export.py` değişmez, `rapor_excel.py` tipli yazıcı + her xlsx için `audit.log(... is_personal_data)` | Kodlamadan önce TEK yardımcı seçilir. Eğitim xlsx'leri kişi adı ve not taşıdığı için denetim izine yazılır (E08-D04). |
| 7 | Gözlem–servis işi FK'si | `egitim_cekirdek` migration'ında `service_order_id → service_orders` | E01-02 migration'ı | Çekirdek E01-02'ye bağımlı kalmasın. Kolon E08-08 ile ayrı migration'da nullable eklenir. |
| 8 | Planlama takvimi | Söz yok | E02-20: "eğitim oturumları salt okunur blok olarak okunur (E08)" | Eksik madde → E08-D03 (P3). |
| 9 | İşten çıkış | Söz yok | E13 `cikis_uygula` (atama, sayaç ve görev kartı kapatır) | Açık plan ve düzeltici faaliyetler için önizleme ve "sorumlusuz faaliyet" uyarısı → E08-D02. |
| 10 | Test verisi klasörü | `backend/tests/veri/egitim.py` | Canlıda `tests/fixtures/` var (`altin/`, `anonimlestir.py`); `tests/veri` yok | `tests/fixtures/egitim.py`. |

---

## 2. Canlı koda karşı doğrulanan teknik bulgular

1. **`kapsam_personel` müşteri kapsamında "dokunmaz" diyor; bu varsayılan-açık bir kural.** `scope_filter` (`api/deps.py:108-118`) yalnız `KENDI_MUSTERILERI`'ni tanıyor. E08'in kuralına göre `KENDI_MUSTERILERI` kapsamlı bir SATIS kullanıcısına `UserPermission` istisnasıyla `egitim.gor` verilirse tüm personeli görür. Personel kapsamında müşteri kavramı yok. Doğru kural: yalnız `TUMU` hepsini görür, diğer her kapsam birim kesişimine düşer. Birimsiz bir kullanıcının kümesi boştur, sonuç `false()` olur (E13 satır 451 ile aynı).
2. **Menü eşlemesi eksik.** Kullanıcı ve rol ekranı "hangi sayfaları görür" sorusunu `api/users.py:48-71` `_SAYFA_IZINLERI` ile cevaplıyor. Şu iki satır eklenmezse rol ekranı eğitim sayfalarını göstermez: `("Eğitim ve Gelişim", "egitim.gor")`, `("Gelişim Kartım", "egitim.kendim")`.
3. **`uq_tp_kisi_kurs_yil WHERE NOT is_deleted` İPTAL'den sonra yeniden planlamayı kilitler.** İptal edilen plan silinmiyor; aynı kişi+kurs+yıl için yeni plan 409 alır, toplu planda da "atlanan" sayılır. Tekillik `WHERE NOT is_deleted AND status <> 'IPTAL'` olmalı ya da "iptal edilen yıl yeniden planlanamaz" kuralı bilinçli olarak yazılmalı. Toplu planda mükerrer atlama `ON CONFLICT ON CONSTRAINT` ile yapılamaz (kısmi indeks). Doğru biçim indeks çıkarımıdır: `ON CONFLICT (user_id, course_id, plan_yili) WHERE ... DO NOTHING RETURNING id`. Alternatif: önce varolanları okuyan tek sorgu.
4. **Pydantic sınır ihlali 400 değil 422 verir.** `main.py`'de `RequestValidationError` eşleyicisi yok (yalnız `StaleDataError`, `IntegrityError`, `DataError`: `main.py:115-161`). E08-10 kabulü "7. satırda puan 120 → 400, satır=7" diyor. Puan `Field(ge=0, le=100)` ise FastAPI 422 döner (`loc=["body","satirlar",6,"son_puan"]`). İki seçenek var: kabul 422 + `loc` olarak düzeltilir ya da puan aralığı serviste denetlenir. Öneri: şema hatası 422, servis kuralı (ileri tarih, pasif kurs, plan) 400 `{satir, mesaj}`. "301 kişi 400" doğru kalır, çünkü üst sınır ayardan okunuyor ve kontrol serviste.
5. **Durum makinesinde `ERTELENDI→ERTELENDI` yazılmamalı.** `dogrula` aynı duruma geçişi her zaman reddediyor (`statemachine.py:50-52`). Bu geçiş `gecisler`'e yazılırsa `sonraki("ERTELENDI")` arayüze imkânsız bir seçenek sunar. Tasarımdaki `*` işareti kaldırılmalı; ikinci erteleme yalnız tarih değişikliği olarak kalır. Meta-test (`tests/unit/test_statemachine.py:8-33`) iki yeni makineyi de sorunsuz sınar.
6. **`TAMAMLANDI→PLANLANDI` geri dönüşü önceki durumu kaybeder.** Plan ERTELENDI ya da BASARISIZ_TEKRAR'dan tamamlandıysa katılım düzeltmesi onu PLANLANDI'ya çeker. `hedef_tarih` korunduğu için tarih kaybı yok, ama durum etiketi değişir. Kabul edilebilir; davranış belgeye yazılmalı. Geri dönüşte `completed_on` ve `completed_session_id` NULL yapılır (`ck_tp_tamam`).
7. **Oturum tarihinin düzeltilmesi ve oturum silme tanımsız.** E08-06 P2 `PATCH /oturumlar` tarih değişikliğine izin veriyor. Bu oturumla kapanan planların `completed_on` değeri güncellenmezse "geç" hesabı ve 30/60/90 takibi yanlış kalır. Yıl değişirse plan eşleşmesi de değişebilir. Kural şöyle olmalı:
   - Tarih değişince bağlı planların `completed_on` değeri aynı transaction'da güncellenir.
   - Katılımı olan oturumda yıl değişikliği 409 alır.
   - Oturum silme ucu açılmaz. Katılımsız oturum yumuşak silinebilir; katılımlı oturum 409 alır.
8. **`sayfala` hesaplanan listelerde sıralama kırılımı eklemez.** `_kirilma_ekle` yalnız ORM varlığı seçen sorgulara PK ekliyor (`api/deps.py:160-167`). Ham kolonlu sorgularda (30/60/90 takip listesi, `DISTINCT ON` matrisi) sayfalar arasında satır kaybolabilir. Bu uçlarda açık bir tekil ORDER BY yazılmalı (ör. `plan_id, asama`; `user_id, competency_id`).
9. **`KISISEL_VARLIKLAR` canlıda hiçbir yerde okunmuyor.** Yalnız tanımlı (`services/kvkk.py:30`); `erisim_gecmisi` ve `veri_bul` bu sabite bakmıyor. Sabiti genişletmek zararsız ama tek başına işlevsel etkisi yok. Erişim logunu sağlayan şey `erisim_kaydet` çağrısı. Kişi kartında `entity="users"`, `entity_id=<kisi>` ve `amac="egitim.kart"` kullanılmalı; `training_observations` yazılmamalı, çünkü kart bir kişiye aittir. Kabul "mevcut erişim logu sorguları aynı" doğru ama gerekçesi farklı.
10. **Ek uçları K12 ile çelişiyor.** `SAHIP_IZNI` bir (gor, yaz) çifti (`api/attachments.py:41-52`). Gözlem eki için gor=`egitim.detay` olursa teknisyen kendi gözleminin fotoğrafını göremez, ama K12 kendi notunu görmesine izin veriyor. `_kapsam` dalında `entity='training_observations' AND observation.user_id == user.id AND user.has('egitim.kendim')` istisnası eklenmeli; ya da "kendi gözlem eki görülmez" kararı açıkça yazılmalı.
11. **Görev kartı bağlantısında kapsam yok.** Görev uçları kapsamı bilerek uygulamıyor (`services/gorevler.py`, `api/gorevler.py:6-9`). `KayitTipi("egitim_faaliyet", ..., alanlar=("id",))` etiketi yalnız numara gösterdiği için sızıntı yok. Etikete kişi adı ya da kurs+kişi gibi kişisel bir alan **eklenmemeli**.
12. **Kendi kendine gözlem/değerlendirme engeli canlıda doğrudan uygulanabilir.** Personel = kullanıcı olduğu için ad eşleştirme gerekmez. Eski M08-15'teki "personel–kullanıcı bağı" sorunu yapısal olarak kalkıyor; doğru tespit.
13. **`YONETIM` beklenen davranışı alır.** `_READ_ONLY_ALL` (`permissions.py:84`) `egitim.gor` ve `rapor.disaaktar` verir; `egitim.detay`, `egitim.gozlem` ve `egitim.kendim` `.gor` ile bitmediği için inmez. `test_yonetim_salt_okunur` yalnız `.yaz/.onayla/.ode/.transfer` sonekine baktığı için `egitim.gozlem` YONETIM'e verilse bile test yakalamazdı. Kural adlandırmayla korunuyor ve tasarım bunu doğru kullanıyor. Yeni test önerisi: `"egitim.detay" not in permissions_of("YONETIM")`.
14. **TRUNCATE gerekçesi doğru.** Tüm yeni tablolar `users`'a FK ile bağlı (ActorMixin `created_by` dahil), bu yüzden `users ... CASCADE` onları temizler (`tests/conftest.py:41-50`). `_TRUNCATE`'e ayrıca eklemek gereksiz ama zararsız.
15. **`ck_cas_kanit_kaynak` ve `assessed_by_user_id SET NULL` birlikte güvenli.** Canlıda kullanıcı silme ucu yok (`api/users.py` yalnız rol siliyor). SET NULL tetiklenmez, CHECK çakışması oluşmaz. Not olarak kalır.
16. **Yerel tarih (K25) gerekli ve doğru.** `Clock.now()` UTC döndürüyor (`clock.py:14-20`). 00:00–03:00 arası "ileri tarih" kontrolü yanlış güne düşerdi.

---

## 3. Madde bazında karar

| ID | Karar | Öncelik | Özet gerekçe |
|---|---|---|---|
| E08-01 | DEĞİŞTİR | P1 | Varsayılan-red personel kapsamı; `_SAYFA_IZINLERI`; `EGITIM_SORUMLUSU` yerine E13 `IK` rolü; `kapsam_personel` E13 ile ortak |
| E08-02 | DEĞİŞTİR | P1 | Kapsam daralır (gözlem → E08-05, yetkinlik → E08-03); FK E08-08'e; İPTAL sonrası yeniden planlama; ON CONFLICT biçimi; personel listesi E13'ten; göç E13 eşleme yolu ile |
| E08-03 | KABUL | P1 | Yalnız ekleme + `DISTINCT ON` doğru; sıralama kırılımı açık yazılır |
| E08-04 | DEĞİŞTİR | P1 | Makinede öz-döngü yok; geri dönüşte alanlar temizlenir; oturum tarihi/silme kuralı |
| E08-05 | KABUL | P1 | Saf fonksiyon, K7 sırası, R-84 formülü; kabul sayıları doğrulandı |
| E08-06 | DEĞİŞTİR | P1 | Oturum PATCH'inde bağlı planların güncellenmesi; oturum silme; İPTAL plan kuralı |
| E08-07 | KABUL | P2 | K10 sade ve tutarlı; uyarı izne bağlı; görev etiketi kişisel alan taşımaz |
| E08-08 | DEĞİŞTİR | P2 | `service_order_id` kolonu bu maddenin migration'ında eklenir |
| E08-09 | DEĞİŞTİR | P2 | Kendi gözlem eklerine erişim; boş kart girişsiz kişide anlamsız |
| E08-10 | DEĞİŞTİR | P2 | 422/400 ayrımı; kabul düzeltilir |
| E08-11 | DEĞİŞTİR | P2 | Tek geçerlilik fonksiyonu (plan + belge birleşimi); K14 kullanıcı teyidi |
| E08-12 | DEĞİŞTİR | P2 | Tek Excel yardımcısı; dışa aktarım denetim izine; tipli hücre |
| E08-13 | DEĞİŞTİR | P2 | Açık ORDER BY; uyarıya giren durumlar tanımlanır; pasif tanımı E13 |
| E08-14 | DEĞİŞTİR | P2 | Pasif = ayrıldı (girişsiz değil); birimsiz şefte 0 |
| E08-15 | KABUL | P2 | Bağımlılık E08-04 + E08-13 olarak düzeltilir |
| E08-16 | KABUL | P2 | P3 kısmı hesaplanır, görev kartı açılmaz |
| E08-17 | KABUL | P2 | Personel = kullanıcı sayesinde doğrudan uygulanır |
| E08-18 | DEĞİŞTİR | P3 | `egitim.yaz` yalnız TUMU rollerde; 403 yolu yalnız istisnayla oluşur, E08-19 yardımcısına birleşir |
| E08-19 | KABUL | P2 | Şef gözleminde birim kontrolü gerçekten çalışır |
| E08-20 | DEĞİŞTİR | P2 | KVKK `entity="users"`; `KISISEL_VARLIKLAR` etkisiz; xlsx denetimi |
| E08-21 | DEĞİŞTİR | P2 | `tests/fixtures/`; testler her maddeyle birlikte |
| E08-22 | KABUL | P3 | Engelleme yok, yalnız uyarı; E01-12 sonrası |
| E08-23 | DEĞİŞTİR | P1 | E12 `KpiKutusu` + `KpiTanimi`; P2 verisine dayanan kutular sonra açılır |

Ayrıntılı gerekçe ve düzeltilmiş metin StructuredOutput `verdicts` alanındadır.

---

## 4. Eklenen maddeler

| ID | Başlık | Öncelik |
|---|---|---|
| E08-D01 | Kardeş tasarımlarla rol, personel ve KPI/Excel hizalaması (§1 tablosu tek kaynak) | P1 · S |
| E08-D02 | İşten çıkışta (E13 `cikis_uygula`) eğitim kayıtları: önizleme ve sorumlusuz faaliyet | P2 · S |
| E08-D03 | Eğitim oturumlarının servis planlama kaynak görünümünde salt okunur blok olarak gösterilmesi (E02-20) | P3 · S |
| E08-D04 | Eğitim Excel dışa aktarımlarının denetim izine yazılması (KVKK) | P2 · S |

---

## 5. Kararların değerlendirmesi

| Karar | Hüküm |
|---|---|
| K1 Personel = users | Doğru; E01/E13 ile tutarlı. |
| K2 Rastgele parola | **E13 ile geçersizleşti.** `giris_acik=false` + E13 `POST /api/personel` kullanılır. "is_active=false = ayrıldı" yorumu korunur. |
| K3 Birim | Yön doğru. Ama gözlemdeki birim anlık görüntüsü "kurs birimi, yoksa gözlemcinin birincil birimi" olmamalı. TUMU kapsamlı müdürün birimi olmayabilir, gözlenenin birimiyle de ilgisi yoktur. Sıra şöyle olmalı: servis işi varsa `service_orders.birim`; yoksa kurs birimi; yoksa gözlenen personelin birincil birimi (E13 `birincil_birim`). |
| K4 404/403 | Doğru; canlı kural ve `api/attachments.py:94-97` gerekçesiyle uyumlu. |
| K5 Yalnız service_orders | Doğru; `work_orders.assigned_id` hesap FK'si. |
| K6 Gözlemci | Makul; `UserPermission` istisnası canlıda var (`models/user.py:54-65`). |
| K7 Sonuç sırası | Makul; eşik ayarlanabilir. "%85/%90 resmi eşik mi" sorusu kullanıcıya teyit için sorulmalı. |
| K8 Hesaplanır | Doğru. |
| K9 Sınav eşiği NULL | Doğru (reddedilen zorunlu eşik geri gelmiyor). |
| K10 Düzeltici faaliyet | Makul. Sorumlu=gözlemci (şef) `egitim.yaz` taşımadığı için kendi faaliyetini elle kapatamaz; yalnız yeni gözlemle otomatik kapanır. Bu bilinçli olmalı ve ekranda yazmalı. "Kritiği kim kapatır" sorusu kullanıcıya hâlâ açık. |
| K11 Atama engellenmez | Doğru (kullanıcı sorusu açık ama varsayılan güvenli). |
| K12 Teknisyen kendi notunu görür | Makul (KVKK md. 11). Ek dosya erişimi aynı kurala bağlanmalı (§2-10). Kullanıcı teyidi önerilir. |
| K13 YONETIM yalnız özet | Doğru; adlandırma hilesi canlı `_READ_ONLY_ALL` ile çalışır. |
| K14 Belge listesi boş | Doğru; veri yokken uyarı 0. |
| K15 Yalnız ekleme | Doğru. |
| K16 TrainingChangeLog yok | Doğru (denetim reddi korunuyor). |
| K17 Göç | Yön doğru. Eşleşmeyen personel için E13 `ad_esleme.py` (öneri + onaylı uygulama) kullanılmalı. `--girissiz-ac`, E13 personel servisini (`giris_acik=false`) çağırmalı; rastgele parola hilesini kendisi uygulamamalı. |
| K18 P3 hesaplanan liste | Doğru. |
| K19 Takip başlangıcı | Doğru (önceki yıl gözlemi saymaz). |
| K20 Maliyet yok | Doğru. |
| K21 xlsx | Doğru. Yardımcı seçimi E01-15/E12 ile tekleştirilmeli; dışa aktarım denetime yazılmalı (E08-D04). |
| K22 Operasyonel etki raporu kapsam dışı | Doğru. |
| K23 Yeni EGITIM_SORUMLUSU | **Değiştir:** E13 `IK` rolüne eğitim izinleri eklenir (tek rol kısıtı). |
| K24 Ayrı router `/api/egitim` | Doğru; boyut ve prefix farkı gerekçeli. |
| K25 `yerel_bugun` | Doğru ve gerekli. E01/E09/E10 da aynı yardımcıyı kullanmalı (tek yer `ortak.py`). |
| K26 M08-16 özü | Doğru. |
| K27 Kullanıcı doğrulamalı işlevler | Doğru korunmuş; PB kuralına dokunulmuyor. |

**Kullanıcıya teyit için açık kalan sorular** (tasarım "soru sorulmadı" diyerek varsayılan seçmiş):
- Kritik uygunsuzluğu kim kapatır (K10)?
- %85 eşiği resmi mi (K7)?
- Teknisyen kendi notunu görsün mü (K12)?
- Belge türleri ve yenileme periyotları (K14).
- Pilot veri taşınacak mı (K17)?

Varsayılanlar güvenli tarafta, kodlamayı bloke etmez.

---

## 6. Mobilite akışlarına etki

- `work_orders`, `work_order_items`, `settlements`, `devices`, `device_vehicle_assignments` ve `sim_device_history` tablolarına yazma ya da kısıt değişikliği yok. İş emri onayı → hak ediş zinciri, IMEI/`identity_kind` kuralı ve tarihli EXCLUDE kısıtları etkilenmez. Altın kayıt testi (932 iş / 552.825,00 TL) değişmez.
- Mevcut rollerin (`TEKNIK_SERVIS` dahil) izin listesi değişmez. `maliyet.gor` kümesi aynı kalır. `YONETIM` otomatik olarak yalnız `egitim.gor` alır.
- `uyarilar.topla()` yeni blok `if user.has("egitim.gor")` altında. Mevcut blokların sırası ve sayıları değişmez.
- `api/attachments.py:_kapsam` yalnız yeni varlık dalları alır; `accounts` dalı (`:102-114`) aynı kalır.
- Yeni `KENDI_BIRIMI`/`KENDI_ISLERI` kapsamları (E01-01) canlı `scope_filter` tarafından tanınmadığı için hesap, cihaz ve mobilite iş emri ekranlarında `TUMU` gibi davranır. E08-01 kabul (5) bunu regresyon olarak sınıyor; doğru.
- Tek dikkat noktası: §2-1'deki varsayılan-açık personel kapsamı. Düzeltilmezse mobilite rolüne istisnayla verilen `egitim.gor` tüm personeli açar.
