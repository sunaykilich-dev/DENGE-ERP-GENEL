# E09 Saha / Zaman Takibi ve Mobil Teknisyen Görünümü: Bağımsız Kontrol Raporu

> Tarih: 21.10.2026 · Denetlenen: `10_canli_entegrasyon/09_saha_zaman_entegrasyon.md`
> Yöntem: Canlı kod okundu: `backend/app/{main.py, clock.py, worker.py, permissions.py, models/{workorder,sim,stock,user,mixins}.py, services/{uyarilar,export,normalize}.py, api/{sims,workorders,settings_api}.py}`, `backend/{Dockerfile, pyproject.toml, uv.lock}`, `tests/conftest.py`, `frontend/src/{api/client.ts, components/AppLayout.tsx, components/UyariZili.tsx}`, `docker-compose.yml`, `docs/KULLANIM-KILAVUZU.md`. Kardeş belgeler de okundu: E01, E02 ve kontrolleri, E04 kontrolü, E05, E07, E10, E12, E13. Kaynak koda dokunulmadı.

---

## 1. Genel hüküm

Tasarımın ana yönü doğru:
- Tek yeni tablo var (`service_time_entries`) ve yalnız `service_orders`'a bağlanıyor. `work_orders.started_at`, hak ediş ve mevcut uyarı bloklarına dokunulmuyor.
- EXCLUDE ve kısmi tekil indeks kalıbı canlıdaki emsallere birebir uyuyor (`models/sim.py:162-176` `where=`, `models/stock.py:88-97` `uq_custody_acik`).
- Yumuşak silme iptal olarak kullanılıyor. `Clock` kullanılıyor. Kayıt yoksa sonuç `None`, 0 yazılmıyor.
- Tek yeni izin açılıyor (`zaman.yaz`). Mobilite `TEKNIK_SERVIS` rolüne dokunulmuyor ve `maliyet.gor` kümesi değişmiyor.

"Canlıda YOK" tespitleri **doğru**:
- Canlıda zaman kaydı ya da sayaç tablosu yok.
- `/api/health` yalnız `status/env` döndürüyor (`main.py:211-213`).
- "Bugün" UTC'den alınıyor (`api/sims.py:138` `clock.now().date()`, `api/workorders.py:210`).
- `tzdata` `uv.lock`'ta yalnız `sys_platform == 'win32'` koşuluyla var (`uv.lock:1225`). Yani Linux imajında Python paketi olarak gelmiyor ve `ZoneInfo` için eklenmesi gerekli.
- Uyarı merkezi saklamıyor, hesaplıyor (`services/uyarilar.py:9-12`). `UyariZili` 60 sn'de bir yoklama yapıyor (`UyariZili.tsx:45`).

Mobilite akışlarını (iş emri onayı → hak ediş, IMEI/`identity_kind`, mevcut EXCLUDE kısıtları) bozan bir öğe bulunmadı. Canlı tablolara kolon, CHECK ya da EXCLUDE eklenmiyor.

**Asıl sorunlar ikiye ayrılıyor:**
- (a) Kardeş tasarımlarla mükerrerlik ve tanım çatışması: mobil ekran üç belgede, işçilik maliyeti iki belgede, "süre eksik" tanımı iki belgede ve faaliyet sözlüğü dört belgede ayrı tanımlı.
- (b) Canlı altyapının gerçekte verdiği davranışla tasarımın vaat ettiği davranış arasında birkaç uyumsuzluk var: 409 mesajları, `ApiError` gövdesi, saat farkı görevi, ayar gizliliği.

---

## 2. Bulgular

| # | Bulgu | Kanıt | Etki | Karar |
|---|---|---|---|---|
| B1 | **Mobil teknisyen ekranı üç kez tasarlanmış.** E02-14 `ZiyaretlerimPage` (`/ziyaretlerim`, `servis.gor`, `service_plan_members`), E09-04 `BenimIslerimPage` (`/benim-islerim`, menü `zaman.yaz`) ve E10-16 `BenimIslerimPage` (`/benim-islerim`, menü `servis.gor`) aynı işi yapıyor. Ziyaret anahtarı ve gruplama E02 ile E09'da ayrı ayrı yazılmış. | `02_planlama...md:73, 222, 519-533`; `10_operasyon_sla...md:534-538, 593`; E09 §E09-04 | Teknisyene iki menü kalemi, iki uç ve iki gruplama kuralı çıkar. E09 ile E10 aynı dosya adını farklı izinle tanımlıyor. | **Tek sayfa** `/benim-islerim` (E09-04 sahip). E02-14 bu sayfanın "Bugün/Yarın" görünümüne, E10-16 ise SLA rozetine indirgenir. Uç tek: `GET /benim-islerim`. (E09-D01) |
| B2 | **İşçilik maliyeti iki kez tanımlanmış.** E09-13 tek bir ayar (`servis_iscilik_saat_maliyeti_tl`) ve kendi `servis_maliyet_ozeti` + `GET /raporlar/maliyet` ucunu öneriyor. E07 ise birim bazlı, tarihli `iscilik_tarife` tablosu (EXCLUDE, `hourly_cost > 0`), `maliyet.py:iscilik_hesapla` ve `/maliyet/analiz` tanımlıyor. | `07_teklif_maliyet...md:73-80, 187, 402-428, 595-615` | İki farklı sonuç çıkar: biri sabit ₺/sa, diğeri birim + tarih tarifesi. | E09-13'ün maliyet hesabı ve ayarı kaldırılır; E07 kullanılır. E09 yalnız "kayıt yoksa null" sözleşmesini ve `sure_ozeti`'ni sağlar. |
| B3 | **Maliyet ayarı maliyet gizliliğini deliyor.** `DEFAULTS` anahtarları `sistem.ayar` iznine açık (`api/settings_api.py:19`). `sistem.ayar` sahibi `maliyet.gor`'a sahip olmayabilir; saat maliyeti ayarlar ekranında görünür. | `api/settings_api.py:19`, `api/deps.py:103-105` | Kural 9 ("maliyet varsayılan gizli") ihlal edilir. | B2 ile birlikte çözülür: ayar eklenmez. |
| B4 | **"Süre kaydı eksik" iki ayrı tanıma sahip.** E09 §2.4: çalışılmış durumda hiç bölüm yok, TELEFON/UZAKTAN çözüm ise BEKLENMIYOR. E12 `sure_eksik_mi`: grup = COZULDU **ve** hiç kayıt yok, tarih filtresinden bağımsız. E07 `SURE_EKSIK`, E05 `sure_durumu`, E04 de ayrı çağırıyor. | `12_raporlama...md:252`; E09 §2.4; `07_...md:403`; `05_...md:404` | E09'un kendi kabulü "ekran = liste = Excel = KPI" modüller arasında bozulur. Eski H-02 hatası (sayı ile liste farklı koşul) geri gelir. | Tanımın sahibi E09 `sure_ozeti_toplu`. E04/E05/E07/E12 bunu çağırır, kendi sorgusunu yazmaz. E12 toplu SQL için aynı modülden `sure_eksik_ifadesi()` alır. (E09-D02) |
| B5 | **Faaliyet sözlüğü dört belgede farklı.** E09: YOL/SAHA/BEKLEME/MOLA/UZAKTAN/ATOLYE/TEST/DIGER. 00 §6.2 ile E07 K22 ve E10 §1: YOL/ISCILIK/MOLA/BEKLEME. E05: "E09 eklemezse ISCILIK". E10 ilk müdahaleyi "faaliyet ∉ {YOL, MOLA, BEKLEME}" ile tanımlıyor. | `00_MIMARI...md:284`; `07_...md:724`; `10_...md:54, 226`; `05_...md:146` | `ck_ste_faaliyet` kodlandıktan sonra diğer modüller `ISCILIK` yazarsa 409 alır. CHECK değişikliğini autogenerate yakalamaz (00 §2). | Tek kaynak E09 `ZAMAN_FAALIYETLERI`. Diğer belgelerdeki `ISCILIK` → `SAHA` (+ `ATOLYE`/`TEST`/`UZAKTAN`) olarak düzeltilir. (E09-D02) |
| B6 | **Kişi bazlı süre verisinin izni çatışıyor.** E09-14/15 personel dağılımını ve disiplin sütunlarını `servis.gor + rapor.gor` ile açıyor. `YONETIM` tüm `.gor` izinlerini otomatik aldığı için (`permissions.py:84, 247`) kişi bazlı süreleri görür. E12 ise KVKK gerekçesiyle `rapor.personel` açıyor ve kişi bazlı süreyi YONETIM'den saklıyor. | `12_raporlama...md:130-137, 384`; `permissions.py:84` | Çalışan verisi (kim, ne zaman, nerede) iki modülde farklı korunur. Daha gevşek olan E09 sızıntı yolu olur. | Kişi bazlı ekip görünümü (personel dağılımı, disiplin sütunları, ayrıntı listesi kişi filtresi, Excel "Personel" sayfası) **`rapor.personel`** ister. Kişisiz toplamlar `rapor.gor` ile kalır. (E09-D03) |
| B7 | **409 mesajları vaat edildiği gibi gelmez.** Global eşleyici mesajı kısıt adının ilk 3 harfinden seçiyor. `uq_` → "Bu kayıt zaten var…", `ex_` → "Bu tarih aralığı mevcut bir dönemle çakışıyor." (`main.py:69-75, 131-148`). E09-02'deki "Önce açık sayacı bitirin: SRV-…" ve E09-09'daki "Ali Veli'nin SRV-… sayacını bitirin" bu yoldan **üretilemez**. | `main.py:69-75, 146-148` | Teknisyen hangi sayacın çakıştığını göremez. | Servis yazmadan önce açık bölümü ve çakışan aralığı sorgular, `ZamanHatasi`'nı açık mesajla yükseltir. DB kısıtları yarış durumu için arka kapı olarak kalır; o yolda genel mesaj kabul edilir. |
| B8 | **`ApiError` nesne gövdesini taşımaz.** `client.ts:39-45` yalnız string `detail`'i mesaja çeviriyor; gövdedeki `{kod, eksik_kisiler}` istemciye ulaşmaz. `ApiError.cakisma` ise her 409'u "başka biri değiştirdi" anlamında kullanıyor (`client.ts:21-23`, `HesaplarPage.tsx:176`). | `frontend/src/api/client.ts:12-49` | E09-12'deki `kod==="SURE_EKSIK"` kontrolü çalışmaz. Onay penceresi açılmaz, kullanıcı "Beklenmeyen hata (409)" görür. | Ön yüz onayı, detayda zaten dönen `sure_durumu` ile POST'tan **önce** sorar. Sunucu `sure_eksik_onay` yoksa string `detail` ile 409 döner (arka kapı). Ortak `client.ts` değişmez. |
| B9 | **Saat farkı görevi yapısal olarak boş.** `db`, `api` ve `worker` tek sunucuda, aynı `docker-compose.yml` içinde koşuyor. Konteynerler çekirdek saatini paylaşır, yani DB `now()` ile `RealClock` (`datetime.now(UTC)`) arasındaki fark ölçülebilir değildir. | `docker-compose.yml` (db: `postgres:17-alpine`, api, worker); `clock.py:18-20`; `README.md:53` "tek sunucu" | Hiçbir şey ölçmeyen ve hep "0 sn" yazan bir worker görevi eklenir. | `saat-farki` görevi çıkarılır. Saat kayması riski NTP'nindir (A4-06). `sunucu_zamani` ile istemci ofseti ve `yerel_gun` kalır. |
| B10 | **Yerel gün yardımcısı tek modülde kalırsa kopyalanır.** E07 (`iscilik_hesapla` yerel tarih), E02 (gün grupları), E10 (SLA takvimi) ve E12 (gün kırılımı) de Europe/Istanbul günü istiyor. | `07_...md:423`; E09 §2.4 | Her modül kendi `ZoneInfo` sarmalayıcısını yazar. | `yerel_gun()` ve `yerel_gun_araligi()` tek bir paylaşılan teknik servis yardımcısına konur (ör. `services/teknik_servis/yerel_zaman.py`); E09 sahibi olur. Canlı `clock.py`'ye dokunulmaz (K18 korunur). |
| B11 | **"Mobil saha yok" yazılı bir ürün kararı.** `docs/KULLANIM-KILAVUZU.md:415-420` bunu "eksiklik değil, **karar**" diye listeliyor; `permissions.py:87-88` de aynı. | `KULLANIM-KILAVUZU.md:415-420` | Kılavuz güncellenmezse belge ile ürün çelişir. | K23 (ayrı uygulama değil, aynı SPA'da duyarlı rota) karara uygun bir revizyon. Kılavuz §10 ve `permissions.py` yorumu güncellenir. (E09-D05) |
| B12 | **Dar ekranda içerik genişliği 279 px.** `Sider collapsedWidth={56}` her zaman görünüyor ve `Content padding: 20` (`AppLayout.tsx:203-212`). 375 − 56 − 40 = 279 px. | `components/AppLayout.tsx:203-212` | E09-04 kabul (5) "375 px'te yatay kaydırma yok" sağlanabilir, ama düğmeler ve kart buna göre tasarlanmalı. | Kabul ölçütü "279 px içerik genişliğinde" diye netleştirilir. AppLayout'ta ortak dolgu değişmez. |
| B13 | **E01 kontrolü durum adlarını değiştiriyor.** `KARGODA/TEST_KONTROL` servis işinden çıkarılıyor; `YOLA_CIKILDI` ile E02'deki `YOLDA` arasında birinin seçilmesi isteniyor. E01-03 DEĞİŞTİR kararıyla `PLANLAMADA→YOLA_CIKILDI` geçişi de belirsiz. | `01_is_emirleri_kontrol.md:15-16, 39` | E09-10'daki `SAYAC_ACILABILIR_DURUMLAR`, §2.4 `sure_durumu` tablosu ve K4 eski adlarla yazılmış. | Listeler elle yazılmaz, E01 `DURUM_GRUPLARI`'ndan türetilir (tasarım zaten bunu söylüyor). Belgedeki sabit listeler E01 kesinleşince güncellenir. |
| B14 | **Ekip iki tabloda.** E02 kontrolü `service_order_assignments` (E01) ile `service_plan_members` (E02) arasında senkron kuralı istiyor (E02-D01). E09 "aktif atama" kontrolünü yalnız E01 atamasına bağlıyor. | `02_planlama_kontrol.md:14, 99` | Plan ekibinden çıkarılan kişinin sayacı E09-09 kontrolünü atlayabilir. | E09-09'un "açık sayaç → 409" kontrolü ekip değiştiren **her** yolda (E01 ata/toplu_ata ve E02 plan üyesi) çağrılır. |
| B15 | **K2 "pasif kullanıcı" şemada açılamaz.** `users.password_hash` NOT NULL (`models/user.py:17`). | E02 kontrol K-01 | Şefin "başkası adına" girdiği hesapsız personel için kullanıcı açma yolu tanımsız. | E02 kontrolündeki çözüm uygulanır: kullanılamaz hash (`"!"`), `is_active=false`, ekranda "girişsiz personel" işareti. E09 bunu yalnız referans alır. |
| B16 | **`duzelten_id` mevcut aktörün kopyası.** `ActorMixin.updated_by` (`mixins.py:37-49`) kaydı son değiştiren kişiyi zaten tutuyor. Bölüm kapandıktan sonra satır değişmediği için `updated_by` = kapatan/düzelten kişidir. "Kim düzeltti" bilgisi `kaynak` + `updated_by` + denetim iziyle tam. | `models/mixins.py:37-49` | Gereksiz kolon ve iki kaynaklı "kim" bilgisi. | `duzelten_id` kaldırılır, `updated_by` kullanılır. (`girildi_at` ise gerekçeli: `created_at` DB saatidir, FakeClock ile sınanamaz. Kalır.) |
| B17 | **E10 kancası eksik.** E10 `ilk_mudahale_isle()`'nin "E09 zaman kaydı başlatma ucundan" çağrılacağını söylüyor, ama E09'da bu çağrı yok. E10 ayrıca `bitis IS NULL` gibi Türkçe kolon adı kullanıyor. | `10_...md:226, 275, 431` | SLA ilk müdahale kaçar ya da E10 kendi sorgusunu yazar. | E09-02 `baslat/gecis` aynı transaction'da `sla.ilk_mudahale_isle(...)` çağırır (E10 kurulu değilse çağrı yok). Kolon adları `ended_at/started_at`. |
| B18 | **"Unuttum" pencere koşulu yanlış veriye iter.** E09-07, unuttum akışını yalnız bölüm >10 sa ya da gün değişmişse açıyor. 15:00'te işi bırakıp 19:00'da sayacı fark eden teknisyenin önünde tek yol `bitir` kalıyor ve 4 saatlik sahte süre yazılıyor. | E09 §E09-07 | Kişi-saat şişer; düzeltme yalnız şefe kalır. | Unuttum her açık bölümde kullanılabilir (asgari süre dolduktan sonra). Gerekçe zorunlu kalır; kayıt `KULLANICI_DUZELTMESI` olarak disiplin sütununda sayılır. |

Ek gözlemler (bulgu değil):
- GECIS'te önce A'nın kapatılması, sonra B'nin eklenmesi gerekir. Yoksa `uq_ste_acik_kisi` ve EXCLUDE, aynı flush içinde "iki açık bölüm" görür. SQLAlchemy aynı tabloda UPDATE'i INSERT'ten önce yazıyor, ama bu dolaylı bir garantidir. Kapatmadan sonra açık bir `await db.flush()` yazılması (kod notu) sırayı kesinleştirir.
- `EkYukleyici` bileşeninde `capture` özelliği yok. E09-04 bunu kullanacaksa bileşene yalnız ekleme yapılır (isteğe bağlı prop; mevcut çağıranlar etkilenmez).
- E12'de ortak `KpiKutusu.tsx` var. E09-14 kendi `Card hoverable` kodunu yazmamalı (E04 kontrolündeki 13. çakışmanın aynısı).
- `@pytest.mark.performans` için `pyproject.toml` `markers` listesine kayıt gerekir; bugün yalnız `integration` var (`pyproject.toml:37-39`).

---

## 3. Madde hükümleri

| Madde | Hüküm | Öncelik | Gerekçe ve revizyon |
|---|---|---|---|
| E09-01 | DEĞİŞTİR | P1 | Model doğru. Değişiklikler: B16 (`duzelten_id` yerine `updated_by`); B7 (manuel kayıtta servis önce çakışan bölümü sorgular ve "10:00-10:30 MOLA (SRV-…) ile çakışıyor" mesajını verir, EXCLUDE arka kapı kalır); B5 (faaliyet sözlüğünün tek sahibi). `servis.planla` canlıda yok, E01'de açılıyor ("mevcut" ifadesi düzeltilir). `kaynak_personel_adi` ve `konum_notu` içeren denetim satırları `is_personal_data=True` ile yazılır. |
| E09-02 | DEĞİŞTİR | P1 | B7: `baslat` önce açık bölümü okur ve "Önce açık sayacı bitirin: SRV-…" mesajıyla 409 verir; `uq_ste_acik_kisi` yalnız eşzamanlı yarışı yakalar (genel mesaj kabul). GECIS'te kapat → `flush` → aç sırası açık yazılır. B17: `baslat/gecis` E10 `ilk_mudahale_isle` kancasını çağırır. Faaliyet adları B5'e göre. |
| E09-03 | KABUL | P2 | Ayrı `move` ucu açılmaması doğru. Tek transaction, rollback ve 17 PB kabulü yeterli. B13 durum adları E01'den türetilir. |
| E09-04 | DEĞİŞTİR | P1 | B1: E02-14 ve E10-16 ile tek sayfa ve tek uç olur; sahibi E09-04. Menü izni `zaman.yaz`. Ziyaret anahtarı E02 takvim kodundan çağrılır, yeniden yazılmaz. B12: kabul "279 px içerik genişliği" olarak yazılır. `EkYukleyici`'ye `capture` yalnız ekleme olarak eklenir. B11: kılavuz güncellenir. |
| E09-05 | KABUL | P2 | Yalnız kişinin kendi verisi, `user_id` parametresi yok. Eksik listesi B4 tanımını çağırır. |
| E09-06 | KABUL | P2 | Uyarı bloğu yalnız sona ekleniyor; ack açılmaması canlı tasarım ilkesine (`uyarilar.py:9-12`) uygun. Sayım `kapsam_birim` + `kapsam_musteri` ile yapılır. Uyarı 60 sn'de bir koşar; sorgu `uq_ste_acik_kisi` kısmi indeksini kullanır, maliyet düşük. |
| E09-07 | DEĞİŞTİR | P1 | B18: ">10 sa veya gün değişmiş" ön koşulu kaldırılır. Sahibi, asgari süre dolmuş her açık bölümü gerçek bitiş + gerekçeyle kapatabilir. 18 sa ve `<= clock.now()` sınırları kalır. |
| E09-08 | KABUL | P2 | Önceki bölümün yeniden açılmaması basit ve öngörülebilir. Boşluk en fazla 5 dk. |
| E09-09 | DEĞİŞTİR | P1 | B14: açık sayaç kontrolü E02 plan üyesi çıkarma yolunda da (E02-D01 senkronu) çağrılır. B7: 409 mesajı servis tarafında kişi adı ve iş no ile string `detail` olarak üretilir. |
| E09-10 | DEĞİŞTİR | P2 | B13: `SAYAC_ACILABILIR_DURUMLAR` ve K4 hedefleri E01 kontrol kararları sonrası katalogdan türetilir (`KARGODA/TEST_KONTROL` çıkar; `YOLA_CIKILDI`/`YOLDA` tek ad). Ön yüzde "Sonuç Gir" açık sayaçta önce "Sayacı bitir" önerir; sunucu kuralı aynen kalır. |
| E09-11 | DEĞİŞTİR | P2 | B4: `sure_ozeti_toplu` ve SQL karşılığı `sure_eksik_ifadesi()` E04/E05/E07/E12'nin tek kaynağıdır. E12 `sure_eksik_mi` kendi tanımını bırakır. Python ile SQL çıktısının eşitliği parametrik testle kilitlenir (E10 SLA emsali). |
| E09-12 | DEĞİŞTİR | P2 | B8: onay penceresi detaydaki `sure_durumu` ile POST'tan önce açılır. Sunucu onaysız istekte string `detail` ile 409 döner ("Süre kaydı eksik: Ali Veli. Onaylayarak kapatın."). Ortak `client.ts`'e dokunulmaz. NOT olayı aynen yazılır. |
| E09-13 | DEĞİŞTİR | P1 | B2/B3: `servis_iscilik_saat_maliyeti_tl` ayarı, `raporlar.servis_maliyet_ozeti` ve `GET /raporlar/maliyet` kaldırılır; işçilik maliyeti E07 `iscilik_hesapla` + `iscilik_tarife` ile hesaplanır. E09'da kalan: kayıt yoksa `kisi_saat_dk=None` (`coalesce(...,0)` yasağı + test), "Kayıt eksik" gösterimi, Excel'de boş hücre. Efor S'ye düşer. |
| E09-14 | DEĞİŞTİR | P2 | B6: kişi bazlı bölümler (personel dağılımı, kişi filtresi, Excel "Personel" sayfası) `rapor.personel` ister; toplamlar `rapor.gor`. Menü izni `rapor.gor` (teknisyene görünmeyen kalem, yönlendirme gerekmez). KPI kutusu E12 `KpiKutusu`'dur. Kişi-saat sorgu fonksiyonu E12 `GET /kisi-saat` ile paylaşılır; E12 ikinci sorgu yazmaz. |
| E09-15 | DEĞİŞTİR | P3 | İçerik doğru. Kişi bazlı disiplin verisi olduğu için `rapor.personel` ister (B6). |
| E09-16 | DEĞİŞTİR | P1 | B9: worker `saat-farki` görevi çıkarılır; tek sunucu ve tek çekirdek saati var, ölçecek fark yok. B10: `yerel_gun`/`yerel_gun_araligi` paylaşılan teknik servis yardımcısına konur ve E02/E07/E10/E12 bunu kullanır. `tzdata` eklenmesi doğru (`uv.lock:1225` yalnız win32). `sunucu_zamani` ve istemci ofseti kalır. |
| E09-17 | DEĞİŞTİR | P1 | Ayrı P3 madde olmaz; E01 kontrolü B10'daki ilkeyle (yeni ucun izin ve kapsam testi doğruluktur, sıkılaştırma değildir) uç taraması testi E09-18'e, rol kabulleri E09-01'e taşınır. Kabul maddeleri aynen korunur. |
| E09-18 | KABUL | P1 | `_TRUNCATE` içindeki `users` CASCADE yeni tabloyu da temizler. `performans` işareti `pyproject.toml` `markers`'a kaydedilir. E09-17 uç taraması buraya eklenir. B4 Python/SQL eşitlik testi ve B5 sözlük eşitliği unit testleri eklenir. |

### Kararların değerlendirmesi

| Karar | Hüküm | Not |
|---|---|---|
| K1 tek tablo + tek EXCLUDE | Makul | Mola/manuel/canlı çakışmasını şemada kapatıyor; emsale uygun. |
| K2 pasif kullanıcı | Değiştir | B15: `password_hash` NOT NULL; kullanılamaz hash + `is_active=false` (E02 kontrol K-01). |
| K3 GPS yok | Makul | KVKK açısından doğru. `konum_notu` kişisel veri sayılır (B6, E09-D03). |
| K4 sınırlı otomatik durum | Makul | Durum adları E01 kesinleşince güncellenir (B13). |
| K5, K6, K7, K8, K9 | Makul | K7 canlı uyarı ilkesine birebir uygun. |
| K10 olay geçmişi | Makul | `ck_soe_tur`'da DUZELTME ve NOT var (`01_...md:116`). |
| K11 ekip arkadaşının süresi iş detayında | Makul | Aynı işe erişimi olanla sınırlı. Ekip raporu `rapor.personel` ister. |
| K12, K13, K14, K15, K16 | Makul | K16 "uydurma tarih yasağı" ile tutarlı. |
| K17 saat kaynağı | Değiştir | Worker görevi gereksiz (B9). |
| K18 UTC gün gözlemi | Makul | Canlı koda dokunulmaz, gözlem olarak kalır. |
| K19 çevrimdışı yok | Makul | |
| K20 tek yeni izin | Makul, eksik | E12'nin `rapor.personel` izni E09 ekip görünümüne de uygulanır (B6). |
| K21 göç | Makul | `tr_normkey` canlıda var (`services/normalize.py:119`); `app/migration/` paketi var. Tekrar koşuda UPSERT `uq_ste_kaynak` ile. |
| K22 işçilik maliyeti ayarı | **Ret** | B2/B3: E07 tarifesi kullanılır. |
| K23 aynı SPA'da rota | Makul | Kılavuz kararı güncellenir (B11); tek sayfa (B1). |
| K24 saha beklemesi ≠ iş beklemesi | Makul | |

---

## 4. Eklenen maddeler

- **E09-D01 (P1, S):** Tek teknisyen mobil ekranı (E02-14 + E09-04 + E10-16 birleşimi).
- **E09-D02 (P1, S):** Faaliyet sözlüğü ve "süre eksik" tanımı için modüller arası tek kaynak.
- **E09-D03 (P2, S):** Kişi bazlı zaman verisinin gizliliği: `rapor.personel` hizalaması, KVKK işaretleme ve saklama notu.
- **E09-D04 (P2, S):** E10 SLA ilk müdahale kancası ve kolon adı hizalaması.
- **E09-D05 (P3, S):** Kullanım kılavuzu ve `permissions.py` yorumunun "mobil saha yok" kararına göre güncellenmesi; `EkYukleyici` `capture` ekleme.

Ayrıntılar yapılandırılmış çıktıdadır.

---

## 5. Dokunulmazlık teyidi

- `work_orders`, `work_order_items`, `settlements`, `services/settlements.py`, `services/reports.py` ve `uyarilar.py`'deki mevcut bloklar değişmiyor. Altın kayıt riski yok.
- `devices`, `device_vehicle_assignments`, `sim_device_history` ve stok EXCLUDE'ları değişmiyor. IMEI/`identity_kind` kuralları etkilenmiyor.
- Ortak dosyalarda yalnız ekleme var: `AppLayout.tsx` (koşullu bant + menü), `EkYukleyici.tsx` (isteğe bağlı prop), `pyproject.toml` (`tzdata`, işaret), `conftest.py`. `client.ts`, `main.py` hata eşleyicileri ve `clock.py` değişmiyor (B7, B8 ve B10 kararlarının sonucu).
