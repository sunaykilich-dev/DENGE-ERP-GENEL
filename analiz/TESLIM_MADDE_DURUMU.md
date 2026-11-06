# Teslim — TS Madde Durumu (Dalga 0–4, son bütünleştirme)

Tarih: 23.10.2026 · Çalışma kopyası: `denge-erp/` (son commit 41fec5a + Dalga 4
commit edilmemiş değişiklikleri) · Alembic head: `d4a000000002` (tek head;
`d3a000000003` bilerek yok).
Kaynak liste: `10_canli_entegrasyon/01_ENTEGRASYON_VE_KODLAMA_PLANI.md` §2
(181 TS maddesi; Ek A'daki her kaynak madde bu TS maddelerinden birine bağlı).

## Özet

| | TAMAM | KISMEN | EKSİK | Toplam |
|---|---|---|---|---|
| Dalga 0 (TS-001…018) | 18 | 0 | 0 | 18 |
| Dalga 1 (TS-020…078) | 55 | 0 | 0 | 55 |
| Dalga 2 (TS-080…177) | 69 | 2 | 0 | 71 |
| Dalga 3 (TS-180…208) | 23 | 3 | 0 | 26 |
| Dalga 4 (TS-210…220) | 10 | 1 | 0 | 11 |
| **Toplam** | **175** | **6** | **0** | **181** |

KISMEN maddelerin hiçbiri kod eksiği değil; ortam (WeasyPrint, prova
sunucusu, canlı kopya) ya da kullanıcı kararı (MESAI, pivot şablonu) bekliyor.
Hepsi `CANLIYA_GECIS_KONTROL_LISTESI.md`'de iş adımı olarak yer alıyor.

## Doğrulama (son bütünleştirme)

- `alembic upgrade head`: `dengeerp_test_v` ve `dengeerp_test_v2`'de
  d3a000000004 → d4a000000001 → d4a000000002 hatasız.
- **Tam suite iki DB'ye bölünerek:** grup A (`tests/unit`, `tests/migration`,
  integration'ın ilk yarısı; `dengeerp_test_v`) **1528 geçti, 12 atlandı**;
  grup B (integration'ın ikinci yarısı; `dengeerp_test_v2`) **764 geçti,
  2 atlandı**. Toplam **2292 geçti, 14 atlandı, 0 kırmızı**.
  Atlananlar: 11 altın kayıt (`tests/fixtures/altin/hakedis-anonim.db` bu
  makinede yok), 2 WeasyPrint PDF (Windows), 1 zamanlama ölçümü
  (`ZAMANLAMA_TESTI=1`).
- Son bütünleştirme düzeltmelerinden sonra etkilenen dosyalar yeniden koşuldu
  (`dengeerp_test_c`): 67 + 211 geçti, 1 atlandı (yeni
  `tests/unit/test_dalga4_butunlestirme.py` 6 test dahil).
- `ruff check` temiz, `ruff format --check` 451 dosya temiz; `npm run build`
  temiz, `oxlint` 0 uyarı 0 hata; `/api/health` → 200 (`{"status":"ok"}`,
  test DB'sine bağlı yerel uvicorn).

## Son bütünleştirmede kapatılan devreden açıklar

| Açık | Durum | Dosya |
|---|---|---|
| Zorunlu parola ekranı uygulama kapısına bağlı değildi (parola_degismeli kullanıcı her ekranda 403) | KAPANDI | `frontend/src/main.tsx` |
| Giriş ekranında "kilitlendiyse yöneticinize başvurun" | KAPANDI | `frontend/src/pages/LoginPage.tsx` |
| `canliya-hazirla` yönetici parolasını geçici saymıyordu | KAPANDI | `backend/app/yonetim.py` |
| `kancalar.atama_uyarilari` imzasında clock yok | KAPANDI (geri uyumlu `clock=None`) | `s/kancalar.py`, `s/atama.py`, `s/egitim_yetkinlik.py` |
| `erisim_girissiz_gun` ayarı DEFAULTS'ta yoktu | KAPANDI (60, sınır 7–365) | `sv/settings.py`, `a/erisim_gozden.py` |
| `servis_rapor_excel_azami_satir` ayara taşınması | KAPANDI (50 000, sınır 1 000–100 000; servis kitabı + bakım Excel'i) | `sv/settings.py`, `s/rapor_tanimlari.py`, `s/rapor_excel.py`, `s/bakim_raporlari.py` |
| `servis_rapor_azami_ay` ayara taşınması | BİLİNÇLİ KOD SABİTİ | 24 ay sınırı eşzamanlı süzgeç doğrulamasında (`panel.aralik_gunleri`, `bakim_raporlari.filtre_dogrula`); ayar okunamaz ve gevşetilmesi sorgu maliyetini büyütür (E12-08). Not `settings.py`'de. |
| `.env.example` `FORWARDED_ALLOW_IPS` | KAPANDI | `.env.example`, `deploy/KURULUM.md` G.0.1 |
| KURULUM: IP doğrulama, `db-least-privilege.sql` Dalga 4 bloğu, ek içerik denetimi açma adımı, sürüm notu | KAPANDI | `deploy/KURULUM.md` G.0.1 |
| RMA ön yüzü: sunucu sayfalaması ve ek yükleyici (TS-217) | KAPANDI | `frontend/src/pages/RmaPage.tsx` |
| Kullanım kılavuzu §13.2 vekâlet (D4-A teslimine göre), yeni §13.3 parola ve giriş | KAPANDI | `docs/KULLANIM-KILAVUZU.md` |

## Kalan açıklar (kod dışı / karar)

1. Commit edilmedi (kural gereği); `paket-uret.sh` yalnız commit'li dosyaları paketler.
2. Çıkış provası (TS-220) ve birim bazlı göç provası (TS-177) canlı döküm kopyasında koşulmadı.
3. Altın kayıt (932 iş / 552.825,00 TL) fixture olmadığı için bu makinede koşulmadı.
4. PDF testleri (TS-036 onay/servis formu, TS-143 teklif) Docker'da koşulmalı.
5. Kullanıcı kararları: ATOLYE `hesap.gor`, MUHASEBE_DESTEK `servis_rapor.disaaktar`, `RmaOut.cost` görünürlüğü, MESAI takvimi (TS-200), pivot şablonu (TS-201).
6. Bilinen sınır: Dalga 4 öncesi `users` güncelleme denetim satırları `is_personal_data=false` yazıldığı için KVKK maskesi onlara uygulanmaz.

## Madde tablosu

Kanıt sütunu: önce kod dosyası, sonra test dosyası (plan §2'deki dosyalar ya da
TS id'sini anan testler). Kısaltma: `services/teknik_servis/` = servis
katmanı, `fe/` = `frontend/src/`, `tests/` = `backend/tests/`.

| TS id | Başlık | Paket | Durum | Kanıt (dosya / test) | Not |
|---|---|---|---|---|---|
| TS-001 | İzin kataloğu, kapsam sabitleri, servis rolleri | D0-A | **TAMAM** | `permissions.py`, `seeds/dev.py`, `tests/unit/test_permissions.py` |  |
| TS-002 | Birim üyeliği yönetimi (`user_units`) | D0-D | **TAMAM** | `services/teknik_servis/personel.py`, `api/personel.py`, `tests/integration/test_personel.py` |  |
| TS-003 | Kapsam yardımcıları (birim, personel, katalog) | D0-A | **TAMAM** | `services/teknik_servis/kapsam.py`, `tests/integration/test_birim_kapsami.py` |  |
| TS-004 | Kullanıcı/rol ekranları yeni kapsamları ve sayfaları tanır | D0-A | **TAMAM** | `api/users.py`, `fe/components/RolDuzenle.tsx`, `tests/integration/test_rol_ve_izin_duzenleme.py` |  |
| TS-005 | Menü grubu, açılış sayfası, rota iskeleti | D0-B | **TAMAM** | `fe/components/AppLayout.tsx` | TS id koda yazılmamış; kanıt `main.tsx` `Acilis`/`acilisYolu`, `AppLayout.tsx` menü grupları. |
| TS-006 | Yetki yükseltme önlemi | D0-A | **TAMAM** | `services/yetki.py`, `api/users.py`, `tests/integration/test_yetki_yukseltme.py` |  |
| TS-007 | Oturum: 12 saat mutlak süre ve `giris_acik` | D0-A | **TAMAM** | `services/auth.py`, `api/auth.py`, `tests/integration/test_oturum_suresi.py` |  |
| TS-008 | Personel kartı = kullanıcı; aktifleştirme girişi açmaz | D0-D | **TAMAM** | `services/teknik_servis/personel.py`, `api/personel.py`, `tests/integration/test_personel.py` |  |
| TS-009 | Atanabilir personel servisi (planlama kaynak listesi) | D0-D | **TAMAM** | `services/teknik_servis/personel.py`, `api/personel.py`, `tests/integration/test_atanabilir_personel.py` |  |
| TS-010 | Personel toplu yükleme profili | D0-D | **TAMAM** | `services/imports/personel.py`, `tests/fixtures/personel_ornek.xlsx`, `tests/integration/test_personel_yukle.py` |  |
| TS-011 | Ortak yardımcılar: yerel zaman, numara, normalizasyonlar | D0-B | **TAMAM** | `services/teknik_servis/yerel_zaman.py`, `services/teknik_servis/numara.py`, `tests/unit/test_normalize_seri.py`, `tests/unit/test_teknik_servis_saat.py` |  |
| TS-012 | Paylaşılan kayıt noktaları + DEFAULTS + KpiKutusu | D0-B | **TAMAM** | `api/attachments.py`, `models/attachment.py`, `tests/integration/test_ortak_kayit_noktalari.py` |  |
| TS-013 | Test altyapısı ve otomatik yetki matrisi | D0-B | **TAMAM** | `api/deps.py`, `backend/pyproject.toml`, `tests/conftest.py`, `tests/integration/test_yetki_matrisi.py` |  |
| TS-014 | Müşteri genişletmesi: doğrulama, hızlı ekleme, VKN, cari kodu, hafif arama | D0-C | **TAMAM** | `services/teknik_servis/ana_veri.py`, `api/teknik_servis_ana_veri.py`, `tests/integration/test_ana_veri_musteri.py` |  |
| TS-015 | Lokasyon (tesis), lokasyon irtibatı, takma ad, ortak doğrulayıcı ve lokasyon anahtarı | D0-C | **TAMAM** | `services/teknik_servis/ana_veri.py`, `api/lokasyonlar.py`, `tests/integration/test_ana_veri_lokasyon.py`, `tests/unit/test_servis_lokasyon_anahtari.py` |  |
| TS-016 | Ana veri KVKK ve denetim | D0-C | **TAMAM** | `services/kvkk.py`, `tests/integration/test_ana_veri_kvkk.py` |  |
| TS-017 | Veri kalitesi ölçümü (kaynak + canlı) ve kütük profili | D0-E | **TAMAM** | `migration/teknik_servis/sql/m14_olcum.sql`, `migration/ana_veri_olcum.py`, `tests/integration/test_ana_veri_olcum.py` | Ölçüm betikleri hazır ve testli; canlı döküm KOPYASINDA koşulması kontrol listesinde (madde 3). |
| TS-018 | Şema iskeleti: Dalga 0 + Dalga 1 tüm tablolar, sequence'ler, tetikleyici, makineler, kanca ve dosya iskeletleri | D0-S | **TAMAM** | `tests/migration/test_ts_sema.py`, `tests/unit/test_ts_sema_iskeleti.py` |  |
| TS-020 | Servis işi açılış, detay, TUR_KURALLARI, kategori, numara, PB değişmezleri | D1-B | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `api/teknik_servis.py`, `tests/integration/test_servis_is_emri.py` |  |
| TS-021 | Tek `durum_degistir`, makine, kancalar, `first_completed_at`, durum grupları | D1-B | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `services/teknik_servis/kancalar.py`, `tests/integration/test_servis_durum.py`, `tests/unit/test_servis_durum_gruplari.py` |  |
| TS-022 | Silinemez olay geçmişi ve iş notu | D1-B | **TAMAM** | `services/teknik_servis/gecmis.py`, `api/teknik_servis.py`, `tests/integration/test_servis_is_emri.py`, `tests/unit/test_servis_olay_gecmisi.py` |  |
| TS-023 | Bekleme akışı ve bekleme nedeni kataloğu | D1-B | **TAMAM** | `services/teknik_servis/bekletme.py`, `api/teknik_servis.py`, `tests/integration/test_servis_bekleme.py` |  |
| TS-024 | Kapanış sonucu, çözüm kanalı, arıza nedeni kataloğu, açılışta çözüldü | D1-B | **TAMAM** | `services/teknik_servis/sonuc.py`, `api/teknik_servis.py`, `tests/integration/test_servis_sonuc.py` |  |
| TS-025 | Kimlik bazlı çoklu atama, tek sorumlu, toplu atama, ekip senkronu | D1-B | **TAMAM** | `services/teknik_servis/atama.py`, `api/teknik_servis.py`, `tests/integration/test_servis_atama.py`, `tests/integration/test_servis_ekip_senkron.py` |  |
| TS-026 | Liste: sunucu filtresi, SQL kapsamı, sayfalama, tipli Excel | D1-B | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `services/export.py`, `tests/integration/test_servis_excel.py` |  |
| TS-027 | Tek kayıt kapsamı, KENDI_ISLERI, telefon maskeleme, uç taraması | D1-B | **TAMAM** | `services/teknik_servis/kapsam.py`, `api/teknik_servis.py`, `tests/integration/test_servis_kapsam.py` |  |
| TS-028 | Mobilite etkisizlik regresyonu | D1-B | **TAMAM** | `tests/integration/test_servis_mobilite_etkisizlik.py`, `tests/unit/test_servis_bagimsizlik.py` |  |
| TS-029 | Talep alma bilgileri ve mükerrer kontrolü | D1-B | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `api/teknik_servis.py`, `tests/integration/test_servis_is_emri.py` |  |
| TS-030 | Bağlı iş ilişkisi | D1-B | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `tests/integration/test_servis_is_emri.py` |  |
| TS-031 | Temel bilgi, seri, müşteri/lokasyon gerekçeli düzeltme | D1-B | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `api/teknik_servis.py`, `tests/integration/test_servis_musteri_duzeltme.py` |  |
| TS-032 | Servis işi ekleri: fotoğraf/form/imza, magic-byte, 24 saat silme | D1-C | **TAMAM** | `services/teknik_servis/ek_kapsam.py`, `tests/integration/test_servis_ekler.py` |  |
| TS-033 | Servis İşleri ön yüzü (liste, Drawer, form, durum/bekleme/sonuç/atama pencereleri) | D1-C | **TAMAM** | `fe/pages/ServisIsleriPage.tsx`, `fe/pages/ServisIsFormu.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-034 | Formda müşteri-lokasyon-irtibat seçici, hızlı ekleme, plan ön dolumu | D1-C | **TAMAM** | `fe/components/MusteriLokasyonSecici.tsx`, `fe/pages/ServisIsFormu.tsx`, `tests/integration/test_servis_butunlestirme.py` |  |
| TS-035 | Servis Paneli ve tek KPI tanım kaydı | D1-C | **TAMAM** | `services/teknik_servis/panel.py`, `api/teknik_servis.py`, `tests/integration/test_servis_panel.py` |  |
| TS-036 | Müşteri onayı (tekil + ziyaret grubu) ve Türkçe servis formu PDF'i (tekil + ziyaret toplu) | D1-C | **TAMAM** | `services/teknik_servis/onay.py`, `templates/servis_formu.html`, `tests/integration/test_servis_onay.py` |  |
| TS-037 | Servis uyarıları, görev bağlantısı, genel arama, KVKK | D1-C | **TAMAM** | `services/teknik_servis/uyarilar.py`, `services/teknik_servis/is_emirleri.py`, `tests/integration/test_servis_butunlestirme.py`, `tests/integration/test_servis_onay.py` |  |
| TS-040 | Plan yazımı: tek aktif plan, kilit, kapalı işi geri çekmeme | D1-D | **TAMAM** | `services/teknik_servis/planlama.py`, `tests/integration/test_servis_planlama_eszamanli.py`, `tests/integration/test_servis_planlama_durum.py` |  |
| TS-041 | Tekli plan ve ekip ataması (tek uç, tek transaction) | D1-D | **TAMAM** | `api/teknik_servis_planlama.py`, `fe/components/PlanPenceresi.tsx`, `tests/integration/test_servis_planlama_tekli.py` |  |
| TS-042 | Takvim (Gün/Hafta/Ay), plansız havuz, şehir/ilçe gruplama, planlama KPI'ları, KENDI_ISLERI | D1-D | **TAMAM** | `services/teknik_servis/takvim.py`, `api/teknik_servis_planlama.py`, `tests/integration/test_servis_performans.py`, `tests/integration/test_servis_takvim.py` |  |
| TS-043 | Toplu planlama ve PB toplu planlama | D1-D | **TAMAM** | `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `tests/integration/test_servis_toplu_plan.py` |  |
| TS-044 | Erteleme nedeni, plan geri alma, plan geçmişi | D1-D | **TAMAM** | `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `tests/integration/test_servis_plan_gecmisi.py` |  |
| TS-045 | Çakışma kontrolü ve şefin "sahaya gidiyor" bayrağı | D1-D | **TAMAM** | `services/teknik_servis/cakisma.py`, `fe/api/client.ts`, `tests/unit/test_servis_cakisma.py`, `tests/integration/test_servis_cakisma_eszamanli.py` |  |
| TS-046 | Ziyaret kartındaki seçili işleri tek işlemde yeniden planlama | D1-D | **TAMAM** | `services/teknik_servis/planlama.py`, `fe/pages/ServisPlanlamaPage.tsx`, `tests/integration/test_servis_yeniden_plan.py` |  |
| TS-047 | Saha önerisi (aynı lokasyonun son planı) | D1-D | **TAMAM** | `services/teknik_servis/planlama.py`, `api/teknik_servis_planlama.py`, `tests/integration/test_servis_saha_onerisi.py` |  |
| TS-048 | Servis araç havuzu | D1-D | **TAMAM** | `api/teknik_servis_planlama.py`, `fe/pages/ServisPlanlamaPage.tsx`, `tests/integration/test_servis_araclar.py` |  |
| TS-049 | Planlama uyarıları, Excel, irtibat gizliliği, planlama KVKK | D1-D | **TAMAM** | `services/teknik_servis/uyarilar.py`, `services/teknik_servis/takvim.py`, `tests/integration/test_servis_takvim.py` |  |
| TS-050 | Ekipman ekle/düzenle/pasif; kapsam; tek yazma kapısı; hesap-adres-irtibat tutarlılığı | D1-E | **TAMAM** | `services/teknik_servis/ekipman.py`, `api/servis_ekipman.py`, `tests/integration/test_servis_ekipman.py`, `tests/integration/test_servis_ekipman_kapsam.py` |  |
| TS-051 | Kütük değişiklik geçmişi (audit_logs) | D1-E | **TAMAM** | `services/teknik_servis/ekipman.py`, `fe/components/EkipmanKarti.tsx`, `tests/integration/test_servis_ekipman_gecmis.py` |  |
| TS-052 | Ekipman kartı ve birleşik geçmiş (servis işi, bakım, atölye, parça) | D1-E | **TAMAM** | `services/teknik_servis/ekipman.py`, `fe/components/EkipmanKarti.tsx`, `tests/integration/test_servis_ekipman_gecmis.py` |  |
| TS-053 | Kütük ekranı: liste, filtre, sayfalama, Excel (T1) + tıklanabilir KPI ve toplu işlem (T2) | D1-E | **TAMAM** | `fe/pages/ServisEkipmanPage.tsx`, `api/servis_ekipman.py`, `tests/integration/test_servis_butunlestirme.py`, `tests/integration/test_servis_ekipman.py` |  |
| TS-054 | Tek normalize seri ile eşleşme ve lokasyon önerisi | D1-E | **TAMAM** | `services/teknik_servis/ekipman.py`, `tests/integration/test_servis_ekipman.py` |  |
| TS-055 | Yaşam döngüsü durumu ve hesaplanan "Serviste" rozeti | D1-E | **TAMAM** | `services/teknik_servis/ekipman.py`, `fe/pages/ServisEkipmanPage.tsx`, `tests/integration/test_servis_ekipman.py` |  |
| TS-056 | Garanti tarihleri/kaynağı ve sözleşme bağı sayısı | D1-E | **TAMAM** | `services/teknik_servis/ekipman.py`, `fe/pages/ServisEkipmanPage.tsx`, `tests/integration/test_servis_ekipman.py` |  |
| TS-057 | Ekipman ekleri, görev, arama, KVKK | D1-E | **TAMAM** | `services/teknik_servis/ek_kapsam.py`, `services/teknik_servis/ekipman.py`, `tests/integration/test_servis_butunlestirme.py`, `tests/integration/test_servis_ekipman_gecmis.py` |  |
| TS-060 | Bakım sözleşmesi yönetimi, tür+adet kapsamı, ücret giriş yolu, tesis/cari ve dönem çakışması uyarısı | D1-F | **TAMAM** | `services/teknik_servis/bakim.py`, `api/bakim.py`, `tests/integration/test_bakim_sozlesme.py` |  |
| TS-061 | Dönem modeli (sayaç saklanmaz, döngüden hesaplanır) | D1-F | **TAMAM** | `services/teknik_servis/bakim.py`, `tests/unit/test_bakim_takvim.py` |  |
| TS-062 | PB üretim motoru, worker, hedef tarih, önizleme, ekipman kimliğiyle eşleşme | D1-F | **TAMAM** | `services/teknik_servis/bakim_uretim.py`, `services/teknik_servis/bakim_sablonlari.py`, `tests/integration/test_bakim_uretim.py` |  |
| TS-063 | Sözleşme–ekipman ilk eşleştirmesi (sistem önerir, şef onaylar) | D1-F | **TAMAM** | `services/teknik_servis/bakim.py`, `fe/pages/BakimPage.tsx`, `tests/integration/test_servis_bakim_eslestirme.py` |  |
| TS-064 | Dijital bakım formu, ziyaret kaydı, tamamlamada ekipman bağlama | D1-F | **TAMAM** | `services/teknik_servis/bakim_formu.py`, `api/bakim.py`, `tests/integration/test_bakim_formu.py` |  |
| TS-065 | PB koruma kancası ve dönem kapanışı gece uzlaştırması | D1-F | **TAMAM** | `services/teknik_servis/bakim_formu.py`, `worker.py` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-066 | Cihazın dönem dışı bırakılması (kapsam dışı talebi, şef onayı) | D1-F | **TAMAM** | `services/teknik_servis/bakim_formu.py`, `api/bakim.py` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-067 | Uygunsuzluk aksiyonları ve bağlı arıza işi | D1-F | **TAMAM** | `services/teknik_servis/bakim_formu.py`, `api/bakim.py` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-068 | PB yeniden açma ve form/kontrol kayıtlarında kullanıcı kimliği | D1-F | **TAMAM** | `services/teknik_servis/bakim_formu.py`, `tests/integration/test_bakim_formu.py` | TS id koda yazılmamış; kanıt `yeniden-ac` ucu ve `YENIDEN_ACMA` ziyaret satırı (`bakim_formu.py`, `test_bakim_formu.py`). |
| TS-069 | Bakım uyarıları, görev kartı, KVKK | D1-F | **TAMAM** | `services/teknik_servis/bakim.py`, `tests/integration/test_bakim_sozlesme.py`, `tests/integration/test_servis_butunlestirme.py` |  |
| TS-070 | Zaman kaydı servisi ve manuel kayıt | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `api/servis_zaman.py`, `tests/integration/test_servis_zaman_kayit.py` |  |
| TS-071 | Tek dokunuş saha akışı ve sunucu zamanı | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `fe/components/SayacDugmeleri.tsx`, `tests/integration/test_servis_zaman_akis.py` |  |
| TS-072 | Sayaç düzeltmeleri: unuttum, 5 dk geri alma, uzun sayaç yönetici düzeltmesi | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `fe/components/AktifSayacBandi.tsx`, `tests/integration/test_servis_zaman_kayit.py` |  |
| TS-073 | Sayaç–durum ve sayaç–atama kancaları | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `tests/integration/test_servis_zaman_akis.py` |  |
| TS-074 | Sayacı sonraki işe taşıma | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `tests/integration/test_servis_zaman_akis.py` |  |
| TS-075 | İş zaman çizelgesi, `sure_ozeti` tek kaynak, null anlamı | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `tests/unit/test_zaman_hesap.py` |  |
| TS-076 | Kapanışta "süre kaydı eksik" onayı | D1-G | **TAMAM** | `services/teknik_servis/zaman.py`, `fe/pages/ServisIsleriPage.tsx`, `tests/integration/test_atolye_durum.py`, `tests/integration/test_servis_butunlestirme.py` |  |
| TS-077 | Benim İşlerim: tek mobil ekran (Bugün/Yarın, plan, kart, sayaç bandı) + kamera eki | D1-G | **TAMAM** | `services/teknik_servis/mobil.py`, `api/servis_zaman.py`, `tests/integration/test_benim_islerim.py` |  |
| TS-078 | "Bugünüm" özeti ve gün sonu eksik listesi | D1-G | **TAMAM** | `services/teknik_servis/mobil.py`, `fe/pages/BenimIslerimPage.tsx`, `tests/integration/test_benim_islerim.py` |  |
| TS-080 | Şema iskeleti Dalga 2 (SLA, atölye, kiralama, parça, teklif/maliyet, eğitim, bağlar) | D2-S | **TAMAM** | `tests/migration/test_ts_sema_d2.py`, `tests/unit/test_ts_sema_d2.py` |  |
| TS-081 | SLA politikası, işe damgalanan hedef, ilk müdahale, öncelik doğrulama, tek SLA modülü, PB dışı, yürürlük anı | D2-G | **TAMAM** | `services/teknik_servis/sla.py`, `services/teknik_servis/sla_takvim.py`, `tests/integration/test_servis_sla*.py`, `tests/unit/test_on_yuz_sla_hesabi_yok.py` |  |
| TS-082 | Operasyon Merkezi ve personel iş yükü | D2-G | **TAMAM** | `services/teknik_servis/operasyon.py`, `api/servis_operasyon.py`, `tests/integration/test_operasyon_merkezi.py` |  |
| TS-083 | Kalıcı SLA bildirimi ve rozet | D2-G | **TAMAM** | `services/teknik_servis/uyari_uretimi.py`, `worker.py`, `tests/integration/test_servis_bildirim.py` |  |
| TS-084 | Tekrar arıza işareti ve kök neden teyidi (KAPATILDI'da) | D2-G | **TAMAM** | `services/teknik_servis/tekrar_ariza.py`, `tests/integration/test_servis_tekrar_ariza.py` |  |
| TS-085 | İş beklemesi / personel bekleme ayrımı; Benim İşlerim SLA bloğu | D2-G | **TAMAM** | `services/teknik_servis/sla.py`, `services/teknik_servis/mobil.py`, `tests/integration/test_servis_sla.py` |  |
| TS-090 | Atölye çekirdeği: kabul (iş + kayıt tek transaction), ATOLYE makinesi, eşleme, olay, iptal yansıması, seri tek kaynak, yetim iş yok | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `api/atolye.py`, `tests/integration/test_atolye_durum.py`, `tests/unit/test_atolye_esleme.py` |  |
| TS-091 | Atölye atama, kapsam, yetki, kapanış kontrolleri | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `api/atolye.py`, `tests/integration/test_atolye_kapsam.py` |  |
| TS-092 | Tamir bedeli gizliliği | D2-B | **TAMAM** | `api/atolye.py`, `services/teknik_servis/atolye_rapor.py`, `tests/integration/test_atolye_maliyet.py` |  |
| TS-093 | Yapılandırılmış teşhis, onarım, test | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `fe/pages/AtolyePage.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-094 | Ücretli onarımda müşteri onayı ve teklif bağı | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `fe/components/AtolyeDurumPenceresi.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-095 | Kabul fişi ve teslim tutanağı PDF | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `templates/atolye_kabul_fisi.html` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-096 | Satır bazlı aksesuar ve teslimde karşılaştırma | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `fe/components/AtolyeKabulPenceresi.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-097 | Seri geçmişi, açık kayıt engeli, tekrar geliş, garanti durumu | D2-B | **TAMAM** | `services/teknik_servis/atolye.py` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-098 | Atölye listesi, yaşlandırma, KPI kutuları, teslim/kargo kuralları, sunucu doğrulaması | D2-B | **TAMAM** | `services/teknik_servis/atolye_rapor.py`, `api/atolye.py`, `tests/integration/test_atolye_rapor.py` |  |
| TS-099 | Atölye detayında parça ve süre görünümü | D2-B | **TAMAM** | `api/atolye.py`, `fe/pages/AtolyePage.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-100 | Toplu kabul (kabul grubu) ve toplu atama | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `fe/components/AtolyeKabulPenceresi.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-101 | Atölye kişisel verilerinin KVKK kapsamı | D2-B | **TAMAM** | `services/teknik_servis/atolye.py`, `tests/integration/test_atolye_kvkk.py` |  |
| TS-102 | Kiralık cihaz → atölye köprüsü ve envanterden çıkış (HURDA) | D2-C (kiralama tarafı), D2-B (atölye kancası) | **TAMAM** | `services/teknik_servis/kiralik_envanter.py`, `services/teknik_servis/atolye.py`, `tests/integration/test_kiralik_envanter.py`, `tests/integration/test_servis_uctan_uca_d2.py` |  |
| TS-110 | Kiralama çekirdeği: başlık, kalem, irtibat, müşteri = hesap, kiralama depoları, birim tutarlılığı | D2-C | **TAMAM** | `services/teknik_servis/kiralama.py`, `api/kiralamalar.py`, `tests/integration/test_kiralama_akis.py` |  |
| TS-111 | Kiralık envanter, ekleme-yalnız hareket defteri, depo ayrımı, IMEI ürün dışlama | D2-C | **TAMAM** | `services/teknik_servis/kiralik_envanter.py`, `api/kiralamalar.py`, `tests/integration/test_kiralik_envanter.py`, `tests/integration/test_kiralama_depo_ayrimi.py` |  |
| TS-112 | Adet bazlı kısmi tahsis, sevk sonrası ek tahsis | D2-C | **TAMAM** | `services/teknik_servis/kiralama_tahsis.py`, `tests/integration/test_kiralama_tahsis.py` |  |
| TS-113 | KIRALAMA makinesi, sevk şartı, cihaz bazlı kısmi sevk ve iade | D2-C | **TAMAM** | `services/teknik_servis/kiralama.py`, `services/teknik_servis/kiralama_tahsis.py`, `tests/integration/test_kiralama_akis.py`, `tests/integration/test_servis_uctan_uca_d2.py` |  |
| TS-114 | Son aşamayı gerekçeyle geri alma; iptalde tahsis çözme | D2-C | **TAMAM** | `services/teknik_servis/kiralama.py`, `tests/integration/test_kiralama_akis.py` |  |
| TS-115 | Dönüş kontrol kaydı | D2-C | **TAMAM** | `services/teknik_servis/kiralik_envanter.py`, `fe/pages/KiralikEnvanterPage.tsx`, `tests/integration/test_kiralik_envanter.py` |  |
| TS-116 | Tarih bazlı müsaitlik ve rezervasyon, bitiş uzatma | D2-C | **TAMAM** | `services/teknik_servis/kiralama_tahsis.py`, `tests/integration/test_kiralama_musaitlik.py` |  |
| TS-117 | Teslim/iade tutanağı (fiyatsız PDF, TASLAK filigranı) | D2-C | **TAMAM** | `services/teknik_servis/kiralama.py`, `templates/kiralama_tutanak.html`, `tests/integration/test_kiralama_akis.py` |  |
| TS-118 | Kiralama kataloğu ve seri takibi koruması | D2-C (+ D2-D `a/catalog.py` satırı) | **TAMAM** | `api/kiralamalar.py`, `api/catalog.py`, `tests/integration/test_kiralik_envanter.py` |  |
| TS-119 | Kiralama uyarıları | D2-C | **TAMAM** | `services/teknik_servis/kiralama_raporlar.py` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-120 | Kurulum/toplama işlerinin servis işine bağlanması | D2-C | **TAMAM** | `services/teknik_servis/kiralama.py`, `api/kiralamalar.py`, `tests/integration/test_kiralama_servis_isi.py` |  |
| TS-121 | Toplu kiralık envanter girişi (önizlemeli) | D2-C | **TAMAM** | `services/teknik_servis/kiralik_envanter.py`, `api/kiralamalar.py`, `tests/integration/test_kiralik_envanter.py` |  |
| TS-122 | Kiralamalar ve Kiralık Envanter sayfaları | D2-C | **TAMAM** | `fe/pages/KiralamalarPage.tsx`, `fe/pages/KiralikEnvanterPage.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-130 | Tek stok yazıcısı, hareket türü, defter değişmezliği, maliyet kolonu | D2-D | **TAMAM** | `services/teknik_servis/parca.py`, `tests/unit/test_parca_tur_kurali.py` |  |
| TS-131 | Servis depoları, birim kapsamı, teknisyen araç deposu, mobilite uçlarına sızma önlemi | D2-D | **TAMAM** | `api/stock.py`, `services/stock.py`, `tests/integration/test_yedek_parca_kapsam.py` |  |
| TS-132 | Kapalı işe çıkış engeli; iade ve ters kayıt | D2-D | **TAMAM** | `services/teknik_servis/parca.py`, `api/yedek_parca.py`, `tests/integration/test_yedek_parca.py` |  |
| TS-133 | Servis işinde Kullanılan Parçalar; teknisyen çıkışı; PB formu ve atölyeye gömülü bileşen | D2-D | **TAMAM** | `api/yedek_parca.py`, `fe/components/ServisParcalari.tsx`, `tests/integration/test_servis_uctan_uca_d2.py`, `tests/integration/test_yedek_parca_kapsam.py` |  |
| TS-134 | Açılış stoğu yükleme | D2-D | **TAMAM** | `services/imports/parca_acilis.py`, `api/yedek_parca.py`, `tests/integration/test_yedek_parca.py` |  |
| TS-135 | Parça kartı stok alanları, az stok tek fonksiyon, ondalık reddi, düşük stok uyarısı | D2-D | **TAMAM** | `api/yedek_parca.py`, `services/teknik_servis/parca.py`, `tests/integration/test_yedek_parca.py`, `tests/unit/test_parca_tur_kurali.py` |  |
| TS-136 | Yedek Parça ekranı, giriş belge no, hareket geçmişi (filtre, sayfa, Excel) | D2-D | **TAMAM** | `fe/pages/YedekParcaPage.tsx`, `fe/components/ParcaHareketPenceresi.tsx`, `tests/integration/test_yedek_parca.py` |  |
| TS-137 | Depolar arası transfer ve onaylı stok sayımı | D2-D | **TAMAM** | `services/teknik_servis/parca.py`, `api/yedek_parca.py`, `tests/integration/test_yedek_parca.py` |  |
| TS-138 | Parça talebi ve MALZEME beklemesi | D2-D | **TAMAM** | `services/teknik_servis/parca.py`, `api/yedek_parca.py`, `tests/integration/test_yedek_parca.py` |  |
| TS-140 | Teklif kapsamı ve birimi, sayfalama, indeks; sunucu doğrulaması ve yuvarlama | D2-E | **TAMAM** | `services/quotes.py`, `api/quotes.py`, `tests/integration/test_servis_teklif_kapsam.py` |  |
| TS-141 | İç onay, TEKLIF makinesi, durum geçmişi, yalnız güncel sürüme karar | D2-E | **TAMAM** | `services/quotes.py`, `api/quotes.py`, `tests/integration/test_servis_teklif_akisi.py` |  |
| TS-142 | Elle gönderildi, yeniden gönderim, ≤3 alıcı, gönderene CC, genel hata mesajı | D2-E | **TAMAM** | `api/quotes.py`, `services/mail.py`, `tests/integration/test_servis_teklif_gonderim.py` |  |
| TS-143 | Teklif PDF: tüm kalemler, çok sayfa, Türkçe, satır sarma, Sayfa x/y; kurumsal alanlar | D2-E | **KISMEN** | `templates/teklif.html`, `api/quotes.py`, `tests/integration/test_servis_teklif_gonderim.py` | PDF üretimi kodda; Türkçe/çok sayfa PDF testi WeasyPrint gerektirir, Windows'ta atlanıyor → Docker'da koşulmalı (kontrol listesi). |
| TS-144 | Satış panel/rapor/listesinin birimli tekliflerden ayrılması; servis teklifi siparişe dönüşmez | D2-E | **TAMAM** | `services/reports.py`, `api/reports.py`, `tests/integration/test_raporlar.py` |  |
| TS-145 | İş geliri ve diğer maliyet kaydı, gelir yok/ücretsiz ayrımı, geçmiş, fatura sonrası kilit | D2-E | **TAMAM** | `services/teknik_servis/maliyet.py`, `api/servis_maliyet.py`, `tests/integration/test_servis_maliyet.py` |  |
| TS-146 | Maliyet hesabı: eksik veri ayrımı, işçilik tarifesi | D2-E | **TAMAM** | `services/teknik_servis/maliyet.py`, `api/servis_maliyet.py`, `tests/integration/test_servis_maliyet.py` |  |
| TS-147 | Teklif–servis işi bağı, TEKLIF beklemesi, "teklif sunulacak" uyarısı, kabul gelirinin aktarımı, PB bulgu teklifi, Faz B adres bağları | D2-E | **TAMAM** | `services/quotes.py`, `services/teknik_servis/maliyet.py`, `tests/integration/test_servis_teklif_akisi.py`, `tests/integration/test_servis_uctan_uca_d2.py` |  |
| TS-148 | Taslak teklif düzenleme (PUT) ve teklif listesi filtre/KPI/Excel | D2-E | **TAMAM** | `api/quotes.py`, `fe/pages/TeklifFormu.tsx`, `tests/integration/test_servis_teklif_akisi.py` |  |
| TS-149 | Servis maliyet analizi ekranı | D2-E | **TAMAM** | `services/teknik_servis/maliyet.py`, `api/servis_maliyet.py`, `tests/integration/test_servis_maliyet.py` |  |
| TS-150 | Eğitim çekirdeği: katalog, toplu yıllık plan, oturum/katılım, kişi kartı, plan.xlsx; yetkinlik değerlendirme geçmişi | D2-F | **TAMAM** | `services/teknik_servis/egitim.py`, `services/teknik_servis/egitim_yetkinlik.py`, `tests/integration/test_egitim_cekirdek.py` |  |
| TS-151 | Plan tamamlama kuralları ve gözlem sonucunun sunucuda hesaplanması | D2-F | **TAMAM** | `services/teknik_servis/egitim.py`, `services/teknik_servis/egitim_gozlem.py`, `tests/unit/test_egitim_sonuc.py` |  |
| TS-152 | Düzeltme/iptal (gözlem, plan, kurs, kriter, oturum) | D2-F | **TAMAM** | `services/teknik_servis/egitim.py`, `services/teknik_servis/egitim_gozlem.py` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-153 | Eğitim Yönetim Özeti (tıklanabilir KPI) | D2-F | **TAMAM** | `services/teknik_servis/egitim_rapor.py`, `fe/pages/EgitimPage.tsx`, `tests/integration/test_egitim_ozet_takip.py` |  |
| TS-154 | Kişisel performans detayının `egitim.detay`'a bağlanması ve Excel denetimi | D2-F | **TAMAM** | `api/egitim.py`, `services/teknik_servis/ek_kapsam.py`, `tests/integration/test_egitim_kendim_katilim.py` |  |
| TS-155 | Kritik İSG uygunsuzluğu için düzeltici faaliyet | D2-F | **TAMAM** | `services/teknik_servis/egitim_gozlem.py`, `api/egitim.py`, `tests/integration/test_servis_uctan_uca_d2.py` |  |
| TS-156 | Gözlemi servis işinden başlatma; kapsam/aktiflik; gözlemci kimliği; tarih/aşama doğrulaması | D2-F | **TAMAM** | `services/teknik_servis/egitim_gozlem.py`, `fe/components/GozlemFormu.tsx` | Kod var; doğrudan TS atıflı test dosyası yok, davranış ilgili modül testlerinde. |
| TS-157 | Gelişim Kartım ve "Gördüm" onayı | D2-F | **TAMAM** | `fe/pages/GelisimKartimPage.tsx`, `api/egitim.py`, `tests/integration/test_egitim_kendim_katilim.py` |  |
| TS-158 | Toplu katılım girişi | D2-F | **TAMAM** | `fe/components/KatilimTablosu.tsx`, `api/egitim.py`, `tests/integration/test_egitim_kendim_katilim.py` |  |
| TS-159 | Belge geçerlilik, 30/60/90 takibi, uyarı birim süzmesi | D2-F | **TAMAM** | `services/teknik_servis/egitim_rapor.py`, `tests/integration/test_egitim_ozet_takip.py` |  |
| TS-160 | Yetkinlik kataloğu yönetimi | D2-F | **TAMAM** | `services/teknik_servis/egitim_yetkinlik.py`, `api/egitim.py`, `tests/integration/test_egitim_kendim_katilim.py` |  |
| TS-165 | İşten çıkış akışı, eğitim kayıtlarına etkisi, personel KVKK | D2-H | **TAMAM** | `services/teknik_servis/personel.py`, `api/personel.py`, `tests/integration/test_personel_cikis.py`, `tests/integration/test_personel_kvkk.py` |  |
| TS-170 | Eski ad bazlı kayıtların onaylı personel eşlemesi | D2-I | **TAMAM** | `services/teknik_servis/ad_esleme.py`, `services/imports/ad_esleme.py`, `tests/integration/test_ad_esleme.py`, `tests/unit/test_servis_goc_kurallari.py` |  |
| TS-171 | Serbest metinden müşteri/lokasyon eşleştirmesi Faz 1 (sözleşme + Güvenlik ekipmanı) | D2-I | **TAMAM** | `services/imports/musteri_eslestirme.py`, `services/teknik_servis/veri_kalitesi.py`, `tests/integration/test_ana_veri_eslestirme.py` |  |
| TS-172 | Ekipman kütüğü göçü (idempotent) | D2-I | **TAMAM** | `migration/kaynak_kutuk.py`, `migration/hazirla_kutuk.py`, `tests/migration/test_kutuk_gocu.py` |  |
| TS-173 | Bakım sözleşmesi göçü, teyit listesi, ekrandan düzenleneni ezmeme, içe/dışa aktarma güvenliği | D2-I | **TAMAM** | `migration/bakim_sozlesme.py`, `services/imports/bakim_sozlesme.py`, `tests/integration/test_bakim_goc.py` |  |
| TS-174 | Servis işi göçü (POC durum → çözüm kanalı eşlemesi, olay, sonuç, seri, eski numara) | D2-I | **TAMAM** | `migration/servis_goc.py`, `services/imports/servis_isleri.py`, `tests/migration/test_servis_gocu.py` |  |
| TS-175 | Plan göçü (WorkOrderPlans/TPL → visits/plans/members) | D2-I | **TAMAM** | `migration/servis_plan.py`, `tests/integration/test_goc_servis_plan.py` |  |
| TS-176 | Zaman kaydı göçü | D2-I | **TAMAM** | `migration/servis_zaman.py`, `tests/migration/test_servis_gocu.py` |  |
| TS-177 | Göç uzlaşma raporu ve birim bazlı geçiş provası | D2-I | **KISMEN** | `migration/servis_uzlasma.py`, `tests/migration/test_servis_gocu.py` | Uzlaşma raporu ve Makefile hedefleri hazır; canlı kopyada birim bazlı geçiş provası yapılmadı (kontrol listesi Göç provaları). |
| TS-180 | Şema Dalga 3 (kiralama sayımı, bildirim/e-posta tabloları, koşullu mesai takvimi, eğitim yetkinlik eşlemesi) | D3-S | **TAMAM** | `tests/integration/test_dalga3_butunlestirme.py`, `tests/migration/test_ts_sema_d3.py` |  |
| TS-181 | Sunucu tarafı tek rapor/KPI motoru, `/ozet`, parametre doğrulama, SQL'de toplama | D3-A | **TAMAM** | `services/teknik_servis/rapor_tanimlari.py`, `services/teknik_servis/rapor_motoru.py`, `tests/integration/servis_rapor_ortam.py`, `tests/integration/test_servis_rapor_altin.py` |  |
| TS-182 | `servis_rapor.personel` uygulaması ve dışa aktarım denetim kaydı | D3-A | **TAMAM** | `api/servis_raporlari.py`, `services/teknik_servis/rapor_excel.py`, `tests/integration/test_servis_rapor_rbac.py` |  |
| TS-183 | Hesap doğruluğu, altın KPI veri seti, çapraz testler | D3-A | **TAMAM** | `tests/fixtures/servis_rapor_seed.py`, `tests/fixtures/servis_rapor_beklenen.json` |  |
| TS-184 | Eksik kırılımlar ve rapor boyutu (şef, müşteri, tesis, şehir, öncelik, çözüm kanalı) | D3-A | **TAMAM** | `services/teknik_servis/rapor_motoru.py`, `tests/integration/test_servis_rapor_hesap.py` |  |
| TS-185 | Planlı bakım tamamlama raporu ve bakım KPI adım 1–2 | D3-E | **TAMAM** | `services/teknik_servis/bakim_raporlari.py`, `api/bakim.py`, `tests/integration/test_bakim_rapor.py` |  |
| TS-186 | SLA ve bekleme raporu | D3-A | **TAMAM** | `services/teknik_servis/rapor_hesap.py`, `api/servis_raporlari.py`, `tests/integration/test_servis_rapor_hesap.py` |  |
| TS-187 | Tekrar arıza/ziyaret ve yeniden açılan iş göstergesi | D3-A | **TAMAM** | `services/teknik_servis/rapor_hesap.py`, `tests/integration/test_servis_rapor_hesap.py` |  |
| TS-188 | Veri Kalitesi sayfası (servis + ana veri KPI + ekipman listeleri) | D3-C | **TAMAM** | `services/teknik_servis/rapor_kalite.py`, `services/teknik_servis/veri_kalitesi.py`, `tests/integration/test_ekipman_kalite_birlestirme.py`, `tests/integration/test_veri_kalitesi_sayfasi.py` |  |
| TS-189 | Saha / Zaman Takibi yönetim ekranı ve veri disiplini sütunları | D3-B | **TAMAM** | `services/teknik_servis/rapor_hesap.py`, `fe/pages/ZamanTakibiPage.tsx`, `tests/integration/test_servis_zaman_takibi.py`, `tests/unit/test_planlama_p3_hesap.py` |  |
| TS-190 | Planlama P3: müsaitlik blokları, kaynak görünümü, plan uyumu, kapanmış iş soluk, bölge önerisi, eğitim oturumu blokları | D3-B | **TAMAM** | `services/teknik_servis/planlama.py`, `services/teknik_servis/takvim.py`, `tests/integration/test_servis_planlama_p3.py`, `tests/unit/test_planlama_p3_hesap.py` |  |
| TS-191 | Ekipman birleştirme, saha farkının kütüğe dönüşü, analitik KPI | D3-C | **TAMAM** | `services/teknik_servis/ekipman.py`, `api/servis_ekipman.py`, `tests/integration/test_ekipman_kalite_birlestirme.py` |  |
| TS-192 | Müşteri kartında Lokasyonlar/Servis sekmeleri, hesap/lokasyon birleştirme, kapsam bilgisi, sözleşme mükerrer listesi | D3-C | **TAMAM** | `services/hesap_birlestir.py`, `services/teknik_servis/ana_veri.py`, `tests/integration/test_ana_veri_birlestirme.py` |  |
| TS-193 | Seri → mobilite cihaz kütüğü bağı ve cihaz kartında servis sekmesi | D3-C | **TAMAM** | `services/teknik_servis/is_emirleri.py`, `fe/pages/CihazlarPage.tsx`, `tests/integration/test_veri_kalitesi_sayfasi.py`, `tests/unit/test_servis_bagimsizlik.py` |  |
| TS-194 | Atölye KPI raporları, dış servis takibi, atölye uyarıları | D3-D | **TAMAM** | `services/teknik_servis/atolye_rapor.py`, `services/teknik_servis/atolye.py`, `tests/integration/test_atolye_kpi_raporu.py` |  |
| TS-195 | Kiralama raporları, saha cihaz değişimi, depo sayımı | D3-D | **TAMAM** | `services/teknik_servis/kiralama_raporlar.py`, `api/kiralamalar.py`, `tests/integration/test_kiralama_raporlar.py`, `tests/integration/test_kiralama_sayim.py` |  |
| TS-196 | Parça tüketim raporu ve satın alma mal kabulünden serisiz parça girişi | D3-D | **TAMAM** | `services/teknik_servis/parca.py`, `services/purchasing.py`, `tests/integration/test_satinalma*.py` |  |
| TS-197 | Maliyet Excel, fatura devri işareti, teklif dönüşüm raporu | D3-E | **TAMAM** | `api/servis_maliyet.py`, `fe/pages/FaturaDevriPage.tsx`, `tests/integration/test_servis_fatura_devri.py` |  |
| TS-198 | Eğitim etkinlik raporu, kurs↔yetkinlik bağı, atamada yetkinlik uyarısı | D3-E | **TAMAM** | `services/teknik_servis/egitim_rapor.py`, `services/teknik_servis/egitim_yetkinlik.py`, `tests/integration/test_dalga3_butunlestirme.py`, `tests/integration/test_egitim_rapor_yetkinlik.py` |  |
| TS-199 | "Ekibim" süzgeci ve mobilite BAKIM ad ayrımı | D3-F | **TAMAM** | `services/teknik_servis/personel.py`, `fe/pages/PersonelPage.tsx`, `tests/integration/test_personel_ekibim.py`, `tests/unit/test_servis_eposta_birim.py` |  |
| TS-200 | Mesai takvimi (koşullu) ve e-posta bildirimi | D3-F | **KISMEN** | `services/teknik_servis/sla_takvim.py`, `services/teknik_servis/eposta.py`, `tests/integration/test_servis_eposta.py`, `tests/migration/test_ts_sema_d3.py` | E-posta bildirimi (outbox + `servis-eposta` görevi) tamam; MESAI takvimi KD-23 kararı bekliyor, `d3a000000003` bilerek atlandı. |
| TS-201 | Önceki dönem karşılaştırması, 12 aylık trend, native pivot şablonu | D3-A | **KISMEN** | `services/teknik_servis/rapor_motoru.py`, `tests/integration/servis_rapor_ortam.py`, `tests/integration/test_servis_rapor_hesap.py` | Önceki dönem ve 12 ay trend tamam; native pivot şablonu (`templates/excel/servis_pivot_sablonu.xlsx`) yok → `PIVOT_SABLONU_ETKIN=False`, tipli tablo yedeği. |
| TS-205 | Atölye pilot verisi sağlık raporu ve kiralama pilot uzlaştırması | D3-G | **KISMEN** | `migration/atolye_saglik.py`, `services/imports/kiralama_goc.py`, `tests/migration/test_goc2.py`, `tests/unit/test_goc2_kurallari.py` | Atölye sağlık raporu tamam; kiralama pilot uzlaştırma profilleri gerçek pilot verisiyle denenmedi. |
| TS-206 | Eğitim göçü | D3-G | **TAMAM** | `migration/egitim.py`, `tests/migration/test_goc2.py` |  |
| TS-207 | SLA alanlarının geri doldurulması (rapor modu, idempotent) | D3-G | **TAMAM** | `migration/servis_sla_geri_doldur.py`, `tests/migration/test_goc2.py` |  |
| TS-208 | Eski serbest metin parça kayıtları ve ana veri eşleştirmesi Faz 2 | D3-G | **TAMAM** | `migration/servis_goc.py`, `services/imports/musteri_eslestirme.py`, `tests/integration/test_dalga3_butunlestirme.py`, `tests/migration/test_goc2.py` |  |
| TS-210 | Şema Dalga 4 (denetim tetikleyicisi, süreli vekâlet kolonu) | D4-S | **TAMAM** | `models/rbac.py`, `tests/migration/test_ts_sema_d4.py`, `tests/unit/test_ts_sema_d4.py` | d4a000000001 (trg_audit_degistirilemez) + d4a000000002 (süreli vekâlet); head→d3a000000004→head yeşil, tek head. |
| TS-211 | Denetim kaydının DB seviyesinde değişmezliği ve gerçek IP | D4-A | **TAMAM** | `services/kvkk.py`, `deploy/db-least-privilege.sql`, `tests/integration/test_denetim_degismezlik.py` | DELETE/UPDATE reddi, KVKK maskesi, `--forwarded-allow-ips`; `.env.example` `FORWARDED_ALLOW_IPS` son bütünleştirmede eklendi. |
| TS-212 | Parola ve giriş yaşam döngüsü | D4-A | **TAMAM** | `services/auth.py`, `api/auth.py`, `tests/integration/test_auth_rbac.py`, `tests/integration/test_parola_yasam_dongusu.py` | Son bütünleştirmede `ParolaDegistirPage` `main.tsx` kapısına bağlandı, giriş ekranına kilit yönlendirmesi, `canliya-hazirla` yönetici parolası geçici. |
| TS-213 | Süreli vekâlet ve vekâlete kapalı izinler | D4-A | **TAMAM** | `permissions.py`, `api/vekalet.py`, `tests/integration/test_vekalet.py`, `tests/unit/test_permissions.py` | `vekalet.ver`, VEKALETE_KAPALI, ≤30 gün CHECK, alıcı oturumu düşer, `vekalet-sona-erme` worker görevi. |
| TS-214 | Erişim gözden geçirme listesi | D4-A | **TAMAM** | `api/erisim_gozden.py`, `fe/pages/UsersPage.tsx`, `tests/integration/test_erisim_gozden.py`, `tests/unit/test_servis_sozluk_tutarliligi.py` | KPI = liste sayısı testli; eşik `erisim_girissiz_gun` ayarına alındı (son bütünleştirme). |
| TS-215 | Teklif gönderim sıkılaştırması: SMTP hız sınırı, gönderilen PDF sha256 | D4-B | **TAMAM** | `api/quotes.py`, `tests/integration/test_teklif_gonderim_hizi.py`, `tests/unit/test_servis_sozluk_tutarliligi.py` | Dakikada 10 (ayar `teklif_gonderim_dakika_limiti`), 429'da SMTP/kayıt yok; `pdf_sha256`. |
| TS-216 | Fiyat/maliyet ve kişisel veri sızıntısı test seti | D4-B | **TAMAM** | `tests/integration/test_servis_fiyat_sizintisi.py`, `tests/unit/test_on_yuz_kisisel_veri.py` | 195 GET ucu × servis rolleri taranıyor; 8 uç gerekçeli beyaz listede. |
| TS-217 | Canlı modüllerdeki kapsam açıkları (RMA eki, RMA liste kapsam/sayfalama, cihaz kartı kapsamı) | D4-B | **TAMAM** | `api/attachments.py`, `api/rma.py`, `tests/integration/test_kapsam_guvenligi.py` | Arka uç: RMA liste kapsam+sayfa, tek kayıt 404, RMA eki, cihaz kapsamı, arama sızıntısı. Ön yüz: son bütünleştirmede RmaPage sunucu sayfalaması + `EkYukleyici` eklendi. Açık karar: `RmaOut.cost` `maliyet.gor` ile korunmuyor. |
| TS-218 | Magic-byte denetiminin diğer ek sahiplerine yayılması ve mobilite Excel'lerinin denetim kaydı | D4-B | **TAMAM** | `services/teknik_servis/ek_kapsam.py`, `api/reports.py`, `tests/integration/test_kapsam_guvenligi.py`, `tests/unit/test_servis_sozluk_tutarliligi.py` | Canlı türlerde kuru koşu (`ek_icerik_denetimi_canli_turler=False`), rapor ucu `/api/ekler/icerik-denetimi`; 3 mobilite Excel'i denetime yazıyor. |
| TS-219 | Yedek dizini tutarlılığı ve doğrulama/ön kontrol genişletmesi | D4-C | **TAMAM** | `deploy/yedekle.sh`, `deploy/dogrula.sh`, `tests/unit/test_deploy_betikleri.py` | Tek `YEDEK_DIZIN=/var/backups/denge-erp`; dogrula head/rol/26 tablo/worker görevleri; on-kontrol ≥39 migration + tek head. |
| TS-220 | Canlıya çıkış paketi ve prova | D4-C | **KISMEN** | `deploy/KURULUM.md`, `deploy/paket-uret.sh`, `tests/integration/test_cikis_provasi_duman.py`, `tests/unit/test_deploy_betikleri.py` | Paket, KURULUM.md EK G, `cikis-provasi.sh`, `servis_duman.py`, tutanak şablonu hazır; canlı döküm kopyasında prova KOŞULMADI (sunucu yok) → kontrol listesi. |
