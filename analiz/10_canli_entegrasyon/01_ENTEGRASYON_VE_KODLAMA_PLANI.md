# Teknik Servis → Denge Mobilite ERP: Birleşik Entegrasyon ve Kodlama Planı

> Tarih: 2026-10-21 · Durum: **KESİN — kodlamaya doğrudan girdi** (kullanıcı tüm maddeleri onayladı, ayrıca soru sorulmayacak).
> Kaynaklar: `00_MIMARI_KURALLAR.md` (bağlayıcı mimari), `01..14_*_entegrasyon.md` ve `*_kontrol.md` (denetçi onaylı modül maddeleri), canlı kod `denge-erp` (yalnız OKUNDU; bu aşamada kaynak koda dokunulmadı).
> Canlı Alembic head (2026-10-21 doğrulandı): `b30e012dd879` (gorev_karti_coklu_ilgili_kisi_ve_etiket).

## 0. Bu belge nasıl okunur

1. **Öncelik sırası:** Bu plan > `00_MIMARI_KURALLAR.md` > modül entegrasyon belgeleri (`01..14`). Modül belgesindeki bir ad, izin, dosya yolu veya numara biçimi bu planla çelişiyorsa **bu plan geçerlidir**; çelişmeyen ayrıntı (kolon listesi, kabul ölçütü, karar gerekçesi) modül belgesinden aynen alınır. Bu planın değiştirdiği her şey §6.2 "Modül belgelerini geçersiz kılan kararlar" tablosunda tek tek yazılıdır.
2. **Madde kimliği:** Her iş maddesi `TS-NNN`. Kaynak modül maddeleri (`E01-02` vb.) "Kaynak" sütununda; Ek A'da her kaynak maddenin hangi `TS` maddesine gittiği tersten listelenir (hiçbir madde kaybolmadı).
3. **Kısaltmalar (dosya yolları):** `m/` = `backend/app/models/`, `s/` = `backend/app/services/teknik_servis/`, `sv/` = `backend/app/services/`, `a/` = `backend/app/api/`, `mg/` = `backend/app/migration/`, `t/` = `backend/tests/`, `p/` = `frontend/src/pages/`, `c/` = `frontend/src/components/`, `fa/` = `frontend/src/api/`.
4. **Canlı durum:** `YOK` (sıfırdan), `KISMEN` (altyapı var, iş kuralı yok), `VAR` (yalnız test/kanıt gerekir).

---

## 1. Ortak altyapı kararları (tek ve kesin)

### 1.1 Mimari yerleşim

Teknik servis, canlının **katman bazlı** yapısına gömülür (00 §6.2 seçenek B). Django tarzı uygulama paketi açılmaz; `work_orders`/`work_order_items`/`settlements` tablolarına hiçbir servis kodu yazmaz.

**Model dosyaları** (her biri `models/__init__.py`'ye import + `__all__`):

| Dosya | Tablolar | Dalga |
|---|---|---|
| `m/rbac.py` (genişletme) | `user_units` (`UserUnit`) | 0 |
| `m/user.py` (genişletme) | `users` personel kolonları, `User.birimler` ilişkisi, `User.giris_yapabilir_mi()` | 0 |
| `m/personel.py` (yeni) | `personnel_name_maps` | 0 |
| `m/account.py` (genişletme) | `accounts`/`addresses`/`contacts` yeni kolonları, `account_aliases`, `account_merges` | 0 |
| `m/teknik_servis.py` (yeni) | `service_orders`, `service_order_serials`, `service_order_events`, `service_hold_reasons`, `service_holds`, `service_fault_reasons`, `service_results`, `service_order_assignments`, `service_approvals`, `service_time_entries`; Dalga 2'de `service_sla_policies`, `service_alerts`, `service_alert_reads`; Dalga 3'te `service_notification_prefs`, `service_mail_outbox`, (koşullu) `service_work_calendar`, `service_holidays` | 0 / 2 / 3 |
| `m/servis_planlama.py` (yeni) | `service_visits`, `service_plans`, `service_plan_members`, `service_vehicles`, `service_unavailability` | 0 |
| `m/servis_ekipman.py` (yeni) | `service_equipment` | 0 |
| `m/servis_bakim.py` (yeni) | `maintenance_contracts`, `maintenance_contract_items`, `maintenance_periods`, `maintenance_generation_runs`, `maintenance_forms`, `maintenance_form_checks`, `maintenance_visits`, `maintenance_nonconformities`, `maintenance_exclusion_requests` | 0 |
| `m/servis_atolye.py` (yeni) | `workshop_records`, `workshop_accessories` | 2 |
| `m/servis_kiralama.py` (yeni) | `rental_catalog_items`, `rental_assets`, `rental_inventory_movements`, `rentals`, `rental_items`, `rental_contacts`, `rental_allocations`, `rental_events`, `rental_checks`; Dalga 3'te `rental_counts`, `rental_count_lines` | 2 / 3 |
| `m/servis_parca.py` (yeni) | `stock_counts`, `stock_count_lines`, `service_part_requests` | 2 |
| `m/servis_maliyet.py` (yeni) | `service_labor_rates`, `service_order_financials` | 2 |
| `m/quote.py` (genişletme) | `quotes`/`quote_versions`/`quote_lines` kolonları, `quote_sends` | 2 |
| `m/stock.py`, `m/catalog.py` (genişletme) | `stock_movements`, `warehouses`, `products` kolonları | 2 |
| `m/egitim.py` (yeni) | `training_*`, `competencies`, `competency_assessments`, `personnel_certificates`; Dalga 3'te `course_competencies`, `service_competency_requirements` | 2 / 3 |

**Servis katmanı:** `sv/teknik_servis/` alt paketi (emsal `sv/imports/`). Ortak dosyalar: `__init__.py` (tüm alt modülleri import eder ki kancalar kaydolsun), `kapsam.py`, `kancalar.py`, `yerel_zaman.py`, `numara.py`, `ana_veri.py`, `personel.py`, `uyarilar.py` (modül uyarı fonksiyonlarını toplar). Modül dosyaları: `is_emirleri.py, gecmis.py, bekletme.py, sonuc.py, atama.py, onay.py, panel.py, planlama.py, takvim.py, cakisma.py, ekipman.py, bakim.py, bakim_uretim.py, bakim_formu.py, bakim_sablonlari.py, bakim_raporlari.py, zaman.py, mobil.py, atolye.py, atolye_rapor.py, kiralama.py, kiralama_tahsis.py, kiralik_envanter.py, kiralama_raporlar.py, parca.py, maliyet.py, egitim.py, egitim_gozlem.py, egitim_yetkinlik.py, egitim_rapor.py, sla.py, sla_takvim.py, operasyon.py, tekrar_ariza.py, uyari_uretimi.py, eposta.py, rapor_tanimlari.py, rapor_motoru.py, rapor_hesap.py, rapor_excel.py, rapor_kalite.py, veri_kalitesi.py`.

**API dosyaları** (her biri `main.py`'de `include_router`; büyük modül ayrı dosya — dosya sahipliği çakışmasın diye bölündü):

| Dosya | Prefix | Dalga |
|---|---|---|
| `a/personel.py` | `/api/personel` | 0 |
| `a/lokasyonlar.py` | `/api/hesaplar/{hesap_id}/lokasyonlar` ve `/api/lokasyonlar` | 0 |
| `a/teknik_servis_ana_veri.py` | `/api/teknik-servis/ana-veri` (musteri-ara, lokasyon-ara, hızlı ekleme, eşleştirme, birleştirme) | 0 |
| `a/teknik_servis.py` | `/api/teknik-servis` (işler, panel, tanımlar/arıza nedenleri) | 1 |
| `a/teknik_servis_planlama.py` | `/api/teknik-servis/planlama` | 1 |
| `a/servis_ekipman.py` | `/api/teknik-servis/ekipman` | 1 |
| `a/bakim.py` | `/api/teknik-servis/bakim` | 1 |
| `a/servis_zaman.py` | `/api/teknik-servis/zaman` ve `/api/teknik-servis/benim-islerim` | 1 |
| `a/servis_operasyon.py` | `/api/teknik-servis/operasyon` ve `/api/teknik-servis/sla-tanimlari` | 2 |
| `a/atolye.py` | `/api/teknik-servis/atolye` | 2 |
| `a/kiralamalar.py` | `/api/kiralama` | 2 |
| `a/yedek_parca.py` | `/api/teknik-servis/parca` | 2 |
| `a/servis_maliyet.py` | `/api/teknik-servis/maliyet` | 2 |
| `a/egitim.py` | `/api/egitim` | 2 |
| `a/servis_raporlari.py` | `/api/teknik-servis/raporlar` | 3 |
| `a/vekalet.py`, `a/erisim_gozden.py` | `/api/vekalet`, `/api/erisim-gozden` | 4 |

**Ön yüz:** her modül kendi `fa/<modul>.ts` dosyasını alır (`teknikServis.ts` yalnız servis işleri; `servisPlanlama.ts`, `servisEkipman.ts`, `bakim.ts`, `servisZaman.ts`, `atolye.ts`, `kiralama.ts`, `yedekParca.ts`, `servisMaliyet.ts`, `egitim.ts`, `servisOperasyon.ts`, `servisRaporlari.ts`, `personel.ts`, `anaVeri.ts`). Ortak bileşenler: `c/KpiKutusu.tsx`, `c/MusteriLokasyonSecici.tsx`, `c/ServisParcalari.tsx`, `c/SlaEtiketi.tsx`.

**PDF:** her modül kendi bağlam fonksiyonunu kendi servis dosyasında yazar (`onay.servis_formu_baglami`, `atolye.kabul_fisi_baglami`, `kiralama.tutanak_baglami`); `sv/belgeler.py` yalnız `firma_bilgisi()` için çağrılır ve tek değişikliği K24 (teklif adresi TESIS'i atlar, Dalga 0). Şablonlar `backend/app/templates/`.

### 1.2 Birim kavramı ve kapsam güvenliği

```python
# permissions.py (Dalga 0)
BIRIMLER: dict[str, str] = {
    "GUVENLIK": "Güvenlik Sistemleri",
    "HABERLESME": "Haberleşme",
    "POC": "POC",
    "MOBILITE": "Mobilite",
    "ARAC_TAKIP": "Araç Takip",
}
SCOPE_ALL = "TUMU"
SCOPE_OWN_CUSTOMERS = "KENDI_MUSTERILERI"
SCOPE_OWN_UNITS = "KENDI_BIRIMI"
SCOPE_OWN_JOBS = "KENDI_ISLERI"
SCOPES = (SCOPE_ALL, SCOPE_OWN_CUSTOMERS, SCOPE_OWN_UNITS, SCOPE_OWN_JOBS)
BIRIM_KAPSAMLARI = (SCOPE_OWN_UNITS, SCOPE_OWN_JOBS)
```

- **Üyelik:** `user_units(user_id FK users CASCADE, birim CHECK→BIRIMLER, is_primary)`; PK (`user_id`,`birim`); `uq_user_units_birincil` kısmi tekil (`user_id`) `WHERE is_primary`. Çoklu birim serbest. `User.birimler` (`lazy="selectin"`), `/api/auth/me` çıktısına `birimler`, `birincil_birim` eklenir.
- **Kapsam semantiği (tek tablo — bütün modüller buna uyar):**

| Rol kapsamı | Servis işleri ve bağlıları (plan, zaman, onay, ek, atölye kaydı, PB, teklif köprüsü) | Diğer teknik servis varlıkları (ekipman, sözleşme, kiralama, depo/parça, birimli teklif, eğitim kişi kaydı, personel) | Canlı modüller (hesap, cihaz, hat, mobilite iş emri, satış teklifi) |
|---|---|---|---|
| `TUMU` | hepsi | hepsi | hepsi (değişmez) |
| `KENDI_BIRIMI` | `birim ∈ user_units` | `birim ∈ user_units`; birimsiz kayıt (ör. `birim NULL` ortak depo) görünür, birimsiz **personel** görünmez | mevcut davranış (filtre yok) |
| `KENDI_ISLERI` | aktif ataması (`service_order_assignments.removed_at IS NULL`) **veya** aktif plan üyeliği olan işler | `birim ∈ user_units` | mevcut davranış |
| `KENDI_MUSTERILERI` | `kapsam_musteri(customer_id)` | `user_units` kesişimi (genelde boş → hiçbiri) | mevcut davranış |

- **Fail-closed:** birim kapsamlı rolde `user_units` satırı yoksa liste boş, tek kayıt 404. Bilinmeyen kapsam dizesi → boş (varsayılan red).
- **Uygulayıcılar** (`s/kapsam.py`, `kapsam_musteri` kalıbının karşılığı): `kapsam_birim(stmt, user, sutun)`, `birim_disinda_mi(user, birim)`, `birim_degisimi_yasak_mi(user, eski, yeni)`, `kapsam_isler(stmt, user, so_id_sutunu)`, `is_erisimi_yok_mu(db, user, so)`, `kapsam_personel(stmt, user, user_id_sutunu)`, `personel_disinda_mi(db, user, user_id)`, `katalog_birim_yasak_mi(user, birim)`. Liste uçları `kapsam_musteri` + `kapsam_birim` (+ `kapsam_isler`) uygular; KPI sayıları, uyarı sayıları, Excel ve arama aynı fonksiyonları kullanır (**sayı = sızıntı**).
- **Yanıt kodları:** URL'deki kayıt kapsam dışı → **404** ve hiçbir yazma yapılmaz (`db.refresh` ile test edilir). Gövdedeki referans kayıt (servis işi, kişi) kapsam dışı → **404**. Gövdedeki katalog öğesi başka birimin (kurs, yetkinlik) → **403**. İzin yok → **403**. Kural ihlali → **409**, girdi hatası → **400**, şema dışı → **422**.
- **Birim değiştirme:** yazmada hedef birim de kullanıcının birimlerinde olmalı (`api/accounts.py:441-447` emsali) — aksi 404.
- **Mevcut yardımcılar** (`sv/accounts.py: kapsam_musteri/kapsam_disinda_mi`) DEĞİŞMEZ; `KENDI_BIRIMI`/`KENDI_ISLERI` rolleri canlı ekranlarda `TUMU` gibi davranır (bilinçli; E01-01 açıklaması `_KAPSAM_ACIKLAMA`'ya yazılır: "servis işlerinde kısıtlı, diğer modüllerde tüm kayıtlar").
- `a/users.py:181,225` sabit iki değer kontrolü `SCOPES` üyeliğine çevrilir (TS-004).

### 1.3 İzin kataloğu — `permissions.py`'ye girecek hâl

`PERMISSIONS` sözlüğüne (mevcut kodların SONUNA, `sistem.goc`'tan önce bir blok olarak) eklenecek kodlar. Mevcut kodlar değişmez.

```python
    # --- Teknik Servis: servis işleri -----------------------------------------
    "servis.gor": ("Teknik Servis", "Servis işlerini, planı ve servis panelini görür (kapsamı kadar)"),
    "servis.yaz": ("Teknik Servis", "Servis işi açar; not, ek, seri, irtibat girer; müşteri/lokasyon seçer"),
    "servis.planla": ("Teknik Servis", "Plan ve ekip atar, toplu plan/atama, erteleme, müsaitlik; çakışmayı gerekçeyle geçer"),
    "servis.tamamla": ("Teknik Servis", "Sonuç girer ve işi TAMAMLANDI yapar"),
    "servis.kapat": ("Teknik Servis", "Kapatır, iptal eder, yeniden açar; kapalı işte gerekçeli düzeltme yapar"),
    "servis.uzaktan_coz": ("Teknik Servis", "Açılışta telefonla/uzaktan çözüldü kaydı açar"),
    "servis.tanim": ("Teknik Servis", "Arıza nedeni kataloğunu düzenler"),
    "servis.arac_yaz": ("Teknik Servis", "Servis araç havuzunu yönetir"),
    "servis.irtibat_gor": ("Teknik Servis", "Saha yetkilisi, telefon ve açık adresi görür (atandığı işte izinsiz de görür)"),
    # --- Ana veri (hesap genişletmesi) ------------------------------------------
    "lokasyon.yaz": ("Hesaplar", "Tesis/lokasyon ve lokasyon irtibatı açar, düzenler; hızlı müşteri ekler"),
    "hesap.birlestir": ("Hesaplar", "Hesap/lokasyon birleştirir, takma ad ve eşleştirme dosyası uygular, hızlı açılanı doğrular"),
    # --- Servis ekipmanı -------------------------------------------------------
    "ekipman.gor": ("Servis Ekipmanı", "Kurulu ekipman kütüğünü, kartı ve geçmişi görür"),
    "ekipman.yaz": ("Servis Ekipmanı", "Ekipman ekler, düzenler, durumunu değiştirir, birleştirir, saha farkını uygular"),
    # --- Planlı bakım ----------------------------------------------------------
    "bakim.gor": ("Planlı Bakım", "Bakım sözleşmesi, dönem, uygunsuzluk ve bakım KPI'larını görür"),
    "bakim.yaz": ("Planlı Bakım", "Sözleşme ve kapsamı yönetir, PB üretir, hedef tarihi gerekçeyle değiştirir"),
    "bakim.onayla": ("Planlı Bakım", "Kapsam dışı talebine karar verir, uygunsuzluk aksiyonu atar ve kapatır"),
    # --- Atölye -----------------------------------------------------------------
    "atolye.gor": ("Atölye", "Atölye kayıtlarını, seri geçmişini ve fişleri görür"),
    "atolye.yaz": ("Atölye", "Kabul, teşhis, onarım, test, onay, aksesuar, teslim ve kargo girer"),
    # --- Kiralama ----------------------------------------------------------------
    "kiralama.gor": ("Kiralama", "Kiralamaları ve kiralık envanteri görür"),
    "kiralama.yaz": ("Kiralama", "Kiralama talebi, kalem, irtibat, tarih girer; planlar, iptal eder, kapatır"),
    "kiralama.envanter": ("Kiralama", "Kiralık envanter girişi, transfer, tahsis, dönüş kontrolü, sayım ve katalog"),
    "kiralama.asama": ("Kiralama", "Sevk, iade, kurulum/toplama aşamaları, saha değişimi ve geri alma"),
    # --- Teklif / maliyet -------------------------------------------------------
    "teklif.onayla": ("Teklif", "Birimli servis teklifini iç onaydan geçirir/geri çevirir; kabul edileni iptal eder"),
    "maliyet.yaz": ("Özel", "Birim işçilik tarifesi, iş geliri ve diğer maliyet girer"),
    # --- Saha / zaman ---------------------------------------------------------------
    "zaman.yaz": ("Saha / Zaman", "Kendi sayacını yönetir, sınırlı geriye manuel kayıt, unuttum ve geri alma"),
    # --- Operasyon / SLA -----------------------------------------------------------
    "operasyon.gor": ("Operasyon", "Operasyon Merkezi sayaçlarını, SLA listesini ve iş yükünü görür"),
    "operasyon.yonet": ("Operasyon", "SLA politikası, mesai takvimi, tatil ve bekleme nedeni kataloğunu yönetir"),
    # --- Yedek parça ------------------------------------------------------------
    "parca.gor": ("Yedek Parça", "Servis depolarındaki parça stoğunu ve hareketleri görür"),
    "parca.kullan": ("Yedek Parça", "Açık servis işine parça çıkışı/iadesi ve parça talebi yapar"),
    "parca.yonet": ("Yedek Parça", "Giriş, transfer, zayi, ters kayıt, sayım ve onayı, açılış stoğu, parça kartı stok alanları"),
    # --- Eğitim ---------------------------------------------------------------------
    "egitim.gor": ("Eğitim", "Eğitim özeti, plan, katalog ve skorları görür"),
    "egitim.detay": ("Eğitim", "Gözlem notu, madde puanı, aksiyon planı, yetkinlik kanıtı ve belge no görür"),
    "egitim.yaz": ("Eğitim", "Katalog, toplu plan, erteleme/iptal, oturum, katılım, belge ve yetkinlik kataloğu"),
    "egitim.gozlem": ("Eğitim", "Saha gözlemi ve yetkinlik değerlendirmesi girer"),
    "egitim.kendim": ("Eğitim", "Kendi gelişim kartını görür ve gözleme 'Gördüm' onayı verir"),
    # --- Servis raporları ---------------------------------------------------------
    "servis_rapor.gor": ("Servis Raporları", "Teknik servis raporları, KPI ve zaman takibi ekranını görür"),
    "servis_rapor.disaaktar": ("Servis Raporları", "Teknik servis Excel dışa aktarımlarını alır"),
    "servis_rapor.personel": ("Servis Raporları", "Kişi bazlı süre, teknisyen notu, konum notu ve saha irtibatı kırılımlarını görür"),
    # --- Personel ---------------------------------------------------------------------
    "personel.gor": ("Personel", "Personel kartlarını ve birim üyeliğini görür (kapsamı kadar)"),
    "personel.yaz": ("Personel", "Personel kartı, birim üyeliği, saha rolü, girişsiz personel açar/düzenler"),
    "personel.cikis": ("Personel", "İşten çıkış akışını çalıştırır"),
```

Dalga 4'te (TS-213 ile birlikte, öncesinde değil — "her izin en az bir rolde" testi): `"vekalet.ver": ("Personel", "Süreli vekâlet verir ve iptal eder")`.

Ek sabitler (Dalga 0):

```python
SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER", "OFIS", "YOK")
ATANABILIR_SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER")
AYRILIS_NEDENLERI = ("ISTIFA", "FESIH", "EMEKLILIK", "SOZLESME_BITIMI", "DIGER")
YUKSEK_YETKILI_IZINLER = frozenset({"sistem.kullanici", "sistem.denetim", "sistem.ayar", "sistem.goc", "kvkk.yonet"})
VEKALETE_KAPALI = YUKSEK_YETKILI_IZINLER | {
    "maliyet.gor", "maliyet.yaz", "teklif.onayla", "hakedis.onayla", "hakedis.ode", "tahsilat.yaz", "vekalet.ver",
}
```

**Otomatik etkiler:** `_READ_ONLY_ALL` `.gor` ile biten kodları topladığı için `YONETIM` şunları kendiliğinden alır: `servis.gor, ekipman.gor, bakim.gor, atolye.gor, kiralama.gor, operasyon.gor, parca.gor, egitim.gor, servis_rapor.gor, personel.gor`. **Bilinçli olarak almaz:** `servis.irtibat_gor`, `egitim.detay`, `servis_rapor.personel` (KVKK en az erişim; adları `.gor` ile bitmez). `ADMIN` hepsini alır. `maliyet.gor` rol kümesi DEĞİŞMEZ (`ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK, YONETIM`); `maliyet.yaz` yalnız `ADMIN`'de, ihtiyaç sahibine kişi bazlı `UserPermission(allow, gerekce)`.

**Neden `rapor.gor`/`rapor.disaaktar` servis rollerine verilmez:** canlı `a/reports.py:29-30` `Aktarici = rapor.disaaktar` tek başına mobilite hak ediş/finans Excel'lerini kapsamsız açar (E12-D01). Servis raporları kendi `servis_rapor.*` izinlerini kullanır; tüm teknik servis Excel uçları `<modül>.gor` + `servis_rapor.disaaktar` ister.

### 1.4 Roller — `ROLES`'a girecek hâl

Mevcut 9 rol (`ADMIN, SATIS, SATIS_MUDURU, DEPO, TEKNIK_SERVIS, MONTAJ_KOORD, HAT_SORUMLUSU, MUHASEBE_DESTEK, YONETIM`) **aynen kalır**; `TEKNIK_SERVIS` mobilite montaj/onay rolüdür, yeniden anlamlandırılmaz.

```python
    "SERVIS_YONETICI": ("Teknik Servis Müdürü", (
        "servis.gor", "servis.yaz", "servis.planla", "servis.tamamla", "servis.kapat", "servis.uzaktan_coz",
        "servis.tanim", "servis.arac_yaz", "servis.irtibat_gor",
        "hesap.gor", "lokasyon.yaz", "hesap.birlestir", "urun.gor", "cihaz.gor", "rma.gor",
        "teklif.gor", "teklif.yaz", "teklif.onayla", "teklif.iskonto_onayla",
        "ekipman.gor", "ekipman.yaz", "bakim.gor", "bakim.yaz", "bakim.onayla", "atolye.gor", "atolye.yaz",
        "kiralama.gor", "kiralama.yaz", "kiralama.envanter", "kiralama.asama", "zaman.yaz",
        "operasyon.gor", "operasyon.yonet", "parca.gor", "parca.kullan", "parca.yonet",
        "egitim.gor", "egitim.detay", "egitim.yaz", "egitim.gozlem", "egitim.kendim",
        "personel.gor", "personel.yaz", "personel.cikis",
        "servis_rapor.gor", "servis_rapor.disaaktar", "servis_rapor.personel", "gorev.gor", "gorev.yaz",
    ), SCOPE_ALL),
    "SERVIS_SEF": ("Teknik Servis Şefi", (
        "servis.gor", "servis.yaz", "servis.planla", "servis.tamamla", "servis.kapat", "servis.uzaktan_coz",
        "servis.irtibat_gor", "hesap.gor", "lokasyon.yaz", "urun.gor", "cihaz.gor", "rma.gor",
        "teklif.gor", "teklif.yaz", "ekipman.gor", "ekipman.yaz", "bakim.gor", "bakim.yaz", "bakim.onayla",
        "atolye.gor", "atolye.yaz", "kiralama.gor", "kiralama.asama", "zaman.yaz", "operasyon.gor",
        "parca.gor", "parca.kullan", "egitim.gor", "egitim.detay", "egitim.gozlem", "egitim.kendim",
        "personel.gor", "servis_rapor.gor", "servis_rapor.disaaktar", "servis_rapor.personel",
        "gorev.gor", "gorev.yaz",
    ), SCOPE_OWN_UNITS),
    "SERVIS_OPERASYON": ("Teknik Servis Operasyon Uzmanı", (
        "servis.gor", "servis.yaz", "servis.uzaktan_coz", "hesap.gor", "lokasyon.yaz", "urun.gor", "cihaz.gor",
        "kiralama.gor", "kiralama.yaz", "operasyon.gor", "egitim.kendim", "personel.gor", "gorev.gor", "gorev.yaz",
    ), SCOPE_OWN_UNITS),
    "SERVIS_TEKNISYEN": ("Servis Teknisyeni", (
        "servis.gor", "servis.yaz", "servis.tamamla", "servis.irtibat_gor", "urun.gor", "cihaz.gor",
        "ekipman.gor", "zaman.yaz", "parca.gor", "parca.kullan", "egitim.kendim", "gorev.gor",
    ), SCOPE_OWN_JOBS),
    "ATOLYE": ("Atölye Kabul / Usta", (
        "servis.gor", "servis.yaz", "servis.planla", "servis.tamamla", "lokasyon.yaz", "urun.gor", "cihaz.gor",
        "rma.gor", "ekipman.gor", "atolye.gor", "atolye.yaz", "kiralama.gor", "zaman.yaz",
        "parca.gor", "parca.kullan", "egitim.kendim", "gorev.gor",
    ), SCOPE_OWN_UNITS),
    "SERVIS_DEPO": ("Servis Deposu / Yedek Parça", (
        "parca.gor", "parca.kullan", "parca.yonet", "servis.gor", "urun.gor", "hesap.gor",
        "servis_rapor.gor", "servis_rapor.disaaktar", "gorev.gor", "gorev.yaz",
    ), SCOPE_OWN_UNITS),
    "KIRALAMA_DEPO": ("Kiralama Deposu", (
        "kiralama.gor", "kiralama.envanter", "kiralama.asama", "hesap.gor", "urun.gor",
        "servis_rapor.gor", "gorev.gor", "gorev.yaz",
    ), SCOPE_OWN_UNITS),
    "IK": ("İnsan Kaynakları / Eğitim", (
        "personel.gor", "personel.yaz", "personel.cikis", "egitim.gor", "egitim.detay", "egitim.yaz",
        "servis_rapor.gor", "servis_rapor.disaaktar", "gorev.gor", "gorev.yaz",
    ), SCOPE_ALL),
```

Notlar: Servis rollerinde `hesap.yaz`, `isemri.*`, `hakedis.*`, `tahsilat.*`, `rapor.gor`, `rapor.disaaktar`, `maliyet.*` YOK (unit testle kilitlenir). `SERVIS_TEKNISYEN`'de `hesap.gor` yok: müşteri/irtibat bilgisi servis işi detayında gömülü döner; `/api/hesaplar` → 403. Özelleştirilmiş (`ozellestirildi=True`) DB rollerine seed yeni izin indirmez; `seeds/dev.py` eksikleri log'a "elle eklenecek" listesi olarak yazar.

### 1.5 Müşteri / lokasyon / saha ana verisinin hesaplarla ilişkisi

- **Müşteri = `accounts(is_musteri=True)`** (fatura/sözleşme tarafı cari). Ayrı `customers`/`sites`/servis irtibatı tablosu AÇILMAZ.
- **Gidilen yer = tesis = `addresses(kind='TESIS')`** (carinin altında). `addresses` genişler: `kind` (MERKEZ/FATURA/SEVK/TESIS, varsayılan MERKEZ), `site_name`, `site_key` (`unvan_anahtari`, trgm GIN), `line` NULL olabilir (yalnız TESIS'te; `ck_addresses_satir`), `access_note`, `primary_contact_id`, `is_active`, `is_verified`, Actor/Versioned/Source mixin, `uq_addresses_tesis_aktif` (`account_id`,`site_key`) `WHERE kind='TESIS' AND is_active`. Silme ucu yok, pasifleme var.
- **İrtibat = `contacts`** (+ `address_id` ile lokasyon irtibatı). Kişisel veri: denetimde `is_personal_data=True`.
- **Takma ad / birleştirme:** `account_aliases` (`alias_key` global tekil), `account_merges` (değişmez kayıt). Birleştirme servisi `sv/hesap_birlestir.py`'ye taşınır (`mg/hesap_birlestir.py` onu çağırır); ekrandan birleştirme hak ediş zincirine referansı olan hesapta 409.
- **Doğrulama:** `accounts.is_verified` (varsayılan true; hızlı eklenen false), `verified_at/by` yalnız `/dogrula` (`hesap.birlestir`) ile yazılır; 7 günden eski doğrulanmamış kayıt uyarısı.
- **Tüm servis kayıtları** (`service_orders`, `service_equipment`, `maintenance_contracts`, `rentals`, `workshop_records` üzerinden servis işi, `quotes.address_id`) müşteri/lokasyon/irtibatı **FK** ile tutar; tek doğrulayıcı `ana_veri.lokasyon_dogrula(db, account_id, address_id, contact_id)` (adres ve irtibat aynı hesaba ait, hesap `is_musteri` ve silinmemiş). Göç kayıtlarında eşleşmeyen ham metin `customer_name_raw`/`location_raw` kolonlarında kalır; API ile açılan kayıtta FK zorunlu (`ck_so_musteri`: `customer_id IS NOT NULL OR source_system IS NOT NULL`).
- **Hafif arama:** `GET /api/teknik-servis/ana-veri/musteri-ara` ve `/lokasyon-ara` (`servis.gor`): yalnız ad + il + doğrulama rozeti; VKN/IBAN/irtibat döndürmez.
- **Hızlı ekleme:** `servis.yaz + lokasyon.yaz` (Operasyon, Şef, Yönetici, Atölye); benzerlik taraması takma adları da kapsar; VKN çakışması 409 + onay/gerekçe.
- **Lokasyon anahtarı (tek fonksiyon):** `ana_veri.lokasyon_anahtari(kayit)` → `("L", address_id)` | `("M", customer_id, unvan_anahtari(location_raw))` | `("E", unvan_anahtari(ham))`, birim ön ekiyle. Havuz, toplu plan, ziyaret, rapor boyutu ve veri kalitesi yalnız bunu çağırır.
- **Bayi/entegratör:** iş son kullanıcı tesisinin carisine açılır; aracı bayi canlı `accounts.parent_dealer_id` ile gösterilir.

### 1.6 Numara serileri

Tek yardımcı: `s/numara.py: belge_no(db, sekans, onek, tarih) -> str` → `f"{onek}-{tarih:%Y%m}-{nextval:06d}"`. Ay, `yerel_zaman` (Europe/Istanbul) ile Clock'tan alınır; **sequence yıl/ay başında sıfırlanmaz** (eşzamanlılık ve göç çakışması yok; tekillik `uq_` ile ayrıca korunur). Canlıdaki `count()+1`/`max(id)+1` üreticilerine dokunulmaz.

| Belge | Biçim | Sequence | Tarih kaynağı | Not |
|---|---|---|---|---|
| Servis işi | `SRV-YYYYAA-NNNNNN` | `service_order_no_seq` | açılış anı | göç kayıtları eski numarayı korur |
| Planlı bakım işi | `PB-YYYYAA-NNNNNN` | `service_order_no_seq` (ortak) | dönemin hedef ayı | |
| Ziyaret | `ZYR-YYYYAA-NNNNNN` | `service_visit_no_seq` | plan tarihi | |
| Bakım sözleşmesi | `BAKIM-NNNN` | `seq_bakim_sozlesme_no` (`OWNED BY`, göçten sonra `setval(max)`) | — | göç `BAKIM-00NN` korunur |
| Atölye kaydı | `AT-YYYYAA-NNNNNN` | `atolye_no_seq` | kabul anı | kabul grubu: `atolye_kabul_grubu_seq` (salt sayı) |
| Kiralama | `KIR-YYYYAA-NNNNNN` | `rental_no_seq` (`OWNED BY rentals.id`) | talep anı | |
| Stok sayımı | `SAY-YYYYAA-NNNNNN` | `stock_count_no_seq` | açılış | |
| Teklif | canlı `TKF{yıl}-{sıra}` | canlı | — | revizyon `-R{n}` yalnız gösterim |

Testler numara değerine bağlanmaz (biçim regex'i test edilir); sequence'ler `OWNED BY` ile bağlanır ki `TRUNCATE ... RESTART IDENTITY` sıfırlasın.

### 1.7 Tek kaynak sözlükler (kod sabiti + adlı CHECK + gerekirse StateMachine)

**SERVIS_IS_EMRI durumları** (`m/teknik_servis.py: SERVIS_DURUMLARI`; KARGODA ve TEST_KONTROL YOK — ayrıntılı atölye durumu `workshop_records`'tadır):
`MUSTERI_TALEBI, PLANLAMADA, PLANLANDI, YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, KAPATILDI, TEKRAR_ACILDI, IPTAL`

| Kaynak → hedefler | |
|---|---|
| (başlangıç) | `MUSTERI_TALEBI`, `PLANLAMADA` (PB ve kiralama kurulum/toplama işleri `PLANLAMADA` doğar) |
| `MUSTERI_TALEBI` | PLANLAMADA, PLANLANDI, ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL |
| `PLANLAMADA` | PLANLANDI, ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL |
| `PLANLANDI` | PLANLAMADA (plan geri alma), YOLA_CIKILDI, SAHADA, ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL |
| `YOLA_CIKILDI` | PLANLANDI (yanlış başlatma geri alma), SAHADA, BEKLEMEDE, TAMAMLANDI |
| `SAHADA` | ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI |
| `ISLEMDE` | SAHADA, ATOLYEDE, BEKLEMEDE, TAMAMLANDI |
| `ATOLYEDE` | BEKLEMEDE, TAMAMLANDI, IPTAL |
| `BEKLEMEDE` | MUSTERI_TALEBI, PLANLAMADA, PLANLANDI, SAHADA, ISLEMDE, ATOLYEDE, TEKRAR_ACILDI (yalnız `beklemeyi_bitir` → `onceki_durum`), IPTAL |
| `TAMAMLANDI` | KAPATILDI, TEKRAR_ACILDI |
| `KAPATILDI` | TEKRAR_ACILDI |
| `TEKRAR_ACILDI` | PLANLAMADA, PLANLANDI, SAHADA, ISLEMDE, ATOLYEDE, BEKLEMEDE, TAMAMLANDI, IPTAL |
| `IPTAL` | — (terminal) |

`DURUM_GRUPLARI`: `KAPALI = {TAMAMLANDI, KAPATILDI, IPTAL}`, `ACIK = diğerleri`, rapor grubu `COZULDU = {TAMAMLANDI, KAPATILDI}`, `SAHA = {YOLA_CIKILDI, SAHADA, ISLEMDE}`, `SAYAC_ACILABILIR = ACIK − {BEKLEMEDE}`. Aynı duruma geçiş 409. Geçiş **yalnız** `is_emirleri.durum_degistir(db, so, hedef, *, kaynak, user, clock, gerekce=None)` ile; `kaynak ∈ UC_HEDEFLERI` (`genel, planla, plan_geri_al, sayac, bekleme, sonuc, uzaktan, atolye, bakim_formu, kapsam_disi, kapat, yeniden_ac, iptal, kiralama`) ve her kaynak yalnız kendi hedef kümesini sürer (ör. `TAMAMLANDI` yalnız `sonuc|uzaktan|atolye|bakim_formu`; `KAPATILDI` yalnız `kapat`). `SERVIS_IS_EMRI.dogrula` servis içinde çağrılır.

**Tür → kategori** (`TUR_KURALLARI`, `is_emirleri.py`): `ARIZA→GUNLUK_SERVIS`, `PLANSIZ_BAKIM→GUNLUK_SERVIS`, `DESTEK→GUNLUK_SERVIS`, `PB→PLANLI_BAKIM` (yalnız worker/bakım üretir; tek seri; tür ve seri değişmez), `ATOLYE→ATOLYE` (yalnız atölye kabul ucu açar), `KURULUM→PROJE`, `TOPLAMA→PROJE`, `KESIF→PROJE`, `DEMONTAJ→PROJE`. Her kuralda `seri_zorunlu`, `birim_kisiti`, `sla_olculur` (yalnız GUNLUK_SERVIS) alanları.

**Diğer sözlükler:**

| Sözlük | Değerler | Yer |
|---|---|---|
| Öncelik | KRITIK, YUKSEK, NORMAL | `ck_so_oncelik` |
| Talep kanalı | TELEFON, WHATSAPP, EPOSTA, SAHADA_BILDIRILDI, BAKIM_OTOMATIK, DIGER | `ck_so_kanal` |
| İlişki türü | MUKERRER, TEKRAR_ARIZA, DEVAM, BAKIM_BULGUSU | `ck_so_iliski` |
| Sonuç | COZULDU, COZULEMEDI, TEKRAR_GIDILECEK, TEKLIF_SUNULACAK | `service_results` |
| Çözüm kanalı | YERINDE, UZAKTAN, TELEFON, ATOLYE | NOT NULL |
| Onay türü | IMZA, SOZLU, BASILI_FORM, ALINAMADI (+ `onay_grubu uuid`) | `service_approvals` |
| Atama rolü | SEF, TEKNISYEN | `uq_soa_tek_sorumlu` |
| Bekleme nedeni | **tablo** `service_hold_reasons` (FK, CHECK değil): MALZEME, MUSTERI_ONAYI★, TEKLIF★, MUSTERI_ERISIMI★, PERSONEL, BAKIM_UYGUNSUZLUK (sadece_sistem), DIS_SERVIS, DIGER (açıklama zorunlu) — ★ `sla_durdurur=true` | tohumlu, `operasyon.yonet` düzenler |
| Zaman faaliyeti | YOL, SAHA, UZAKTAN, ATOLYE, TEST, BEKLEME, MOLA, DIGER; `KISI_SAATE_DAHIL` = MOLA hariç hepsi | `ZAMAN_FAALIYETLERI` |
| Olay türü | OLUSTUR, DURUM, ATAMA, PLAN, BEKLEME, BEKLEME_BITTI, SONUC, NOT, EK, EK_SIL, ONAY, DUZELTME, SERI, ILISKI, PARCA, ATOLYE (`veri.alt_tur`), TEKLIF, SLA | `ck_soe_tur` (Dalga 0'da hepsi; sonra ALTER gerekmez) |
| Arıza nedeni | tablo `service_fault_reasons` (birim bazlı tohum: Güç/Besleme, Kablo/Bağlantı, Donanım Arızası, Yazılım/Yapılandırma, Kullanıcı Hatası, Çevresel/Fiziksel Hasar, Arıza Bulunamadı, Diğer) | `servis.tanim` |

Bu sözlüklerin E01/E02/E04/E05/E09/E10/E12 arasında aynı olduğu `t/unit/test_servis_sozluk_tutarliligi.py` ile kilitlenir.

**Durum makineleri** (`sv/statemachine.py`, `MAKINELER`'e eklenir → meta-test otomatik sınar): Dalga 0: `SERVIS_IS_EMRI`, `SERVIS_EKIPMANI`, `BAKIM_SOZLESMESI`. Dalga 2: `ATOLYE`, `KIRALAMA`, `TEKLIF` (yalnız birimli teklifte zorlanır), `EGITIM_PLANI`, `DUZELTICI_FAALIYET`, `STOK_SAYIM`, `PARCA_TALEBI`.

### 1.8 Kanca sözleşmesi (modüller arası tek bağlantı noktası)

`s/kancalar.py` — süreç içi kayıt defteri; modüller dosyalarının en altında kaydolur, `s/__init__.py` tüm modülleri **sabit sırayla** import eder. Böylece Dalga 1 dosyaları sonraki dalgalarda düzenlenmeden yeni davranış eklenir.

| Kanca | Çağıran (tek yer) | Kaydolanlar | Hata davranışı |
|---|---|---|---|
| `durum_dogrula(db, so, hedef, kaynak)` | `is_emirleri.durum_degistir` (yazmadan önce) | `bakim_formu.pb_gecis_dogrula` (PB), `atolye.atolye_gecis_dogrula` (kategori ATOLYE), `zaman.acik_sayac_dogrula` (TAMAMLANDI/IPTAL'de açık sayaç → 409) | `ServisHatasi` → 409 |
| `durum_degisti(db, so, onceki, hedef, kaynak, clock)` | aynı fonksiyon (yazdıktan sonra) | `bekletme` (aktif beklemeyi kapat), `bakim_formu.donem_kapanisini_guncelle`, `sla.durum_isle`, `parca.talepleri_kapat`, `kiralama.asama_oner` | aynı transaction |
| `is_olusturuldu(db, so, clock)` | `is_emirleri.olustur` | `sla.damgala`, `tekrar_ariza.isaretle` | |
| `ekip_degisiyor(db, so, cikan_user_ids)` | `atama.ata/toplu_ata`, `planlama.ekip_degisti` | `zaman.acik_sayac_cikarma_dogrula` | 409, hiçbir iş değişmez |
| `ekip_degisti(db, so, yeni_ekip)` | `atama.ata/toplu_ata` | `planlama.ekip_degisti` (aktif planda EKIP_DEGISIMI satırı) | |
| `oncelik_birim_degisti(db, so)` | `is_emirleri.guncelle` | `sla.yeniden_damgala` | |
| `zaman_bolumu_acildi(db, bolum)` | `zaman.baslat/gecis` | `sla.ilk_mudahale_isle` | |

Kanca kaydı olmayan ortamda (ör. Dalga 1 yayınında SLA yok) çağrı no-op'tur.

### 1.9 Ayar anahtarları (`sv/settings.py DEFAULTS` — tümü Dalga 0'da TEK seferde eklenir)

```python
    # --- Teknik servis --------------------------------------------------------
    "servis_onay_zorunlu_turler": ["PB"],        # ALINAMADI+neden de onay kaydı sayılır; saha bloke olmaz
    "servis_toplu_atama_ust_sinir": 150,          # toplu atama/plan; 151 → 422
    "servis_ek_silme_saat": 24,
    "servis_kapsam_son_is_gun": 30,
    "servis_plan_varsayilan_sure_dk": 60,
    "servis_bolge_oneri_gun": 3,
    "servis_plan_bekleyen_uyari_gun": 3,
    "hesap_dogrulanmamis_uyari_gun": 7,
    # --- Ekipman / bakım ----------------------------------------------------------
    "servis_varsayilan_garanti_ay": 24,
    "servis_garanti_uyari_gun": 30,
    "servis_kpi_bakim_gecikme_ay": 12,
    "ekipman_tekrar_ariza_gun": 90,
    "ekipman_tekrar_ariza_esik": 2,
    "bakim_on_acilis_gun": 30,
    "bakim_tolerans_gun": 30,
    "bakim_otomatik_uretim": False,               # sözleşme–ekipman eşleştirmesi bitince açılır (TS-063)
    # --- Saha / zaman ---------------------------------------------------------------
    "zaman_manuel_geri_gun": 2,
    "zaman_manuel_gerekce_esik_dk": 30,
    "zaman_geri_alma_dk": 5,
    "zaman_asgari_bolum_dk": 1,
    "zaman_uzun_sayac_uyari_saat": 10,
    "zaman_gecikmeli_manuel_saat": 24,
    "zaman_rapor_varsayilan_gun": 31,
    # --- SLA / operasyon ------------------------------------------------------------
    "servis_sla_yururluk_at": None,               # ISO zaman; boşken SLA damgalanmaz (göç fırtınası önlemi)
    "servis_sla_risk_yuzde": 80,
    "servis_tekrar_ariza_gun": 30,
    "servis_uyari_uretimi_acik": True,
    "servis_uyari_saklama_gun": 90,
    "servis_eposta_acik": False,
    "servis_eposta_deneme": 3,
    "servis_gunluk_ozet_saati": "07:30",
    # --- Atölye / kiralama ----------------------------------------------------------
    "atolye_tekrar_gelis_gun": 90,
    "atolye_teslim_alinmayan_uyari_gun": 30,
    "kiralama_kontrol_uyari_gun": 7,
    # --- Teklif ------------------------------------------------------------------------
    "teklif_oz_onay_yasak": True,
    "teklif_takip_uyari_gun": 3,
    "teklif_sunulacak_uyari_is_gunu": 2,
    # --- Eğitim ------------------------------------------------------------------------
    "egitim_gozlem_basari_esigi_yuzde": 85,
    "egitim_rozet_sari_esigi_yuzde": 65,
    "egitim_duzeltici_termin_gun": 14,
    "egitim_belge_uyari_gun": 30,
    "egitim_plan_uyari_gun": 7,
    "egitim_toplu_plan_ust_sinir": 300,
    "egitim_takip_pencere_gun": 7,
```

`set_many` canlıda doğrulama yapmadığı için yeni anahtarlara `AYAR_SINIRLARI = {anahtar: (tip, alt, ust)}` eklenir ve yalnız bu anahtarlarda uygulanır (mevcut anahtarların davranışı değişmez). Süre sınırları (15–1440 dk plan, 18 saat zaman bölümü, 62 gün takvim) kod sabitidir, ayar değildir.

### 1.10 Menü yapısı ve açılış sayfası

`c/AppLayout.tsx` `MENU` öğesine isteğe bağlı `grup?: string` alanı eklenir; aynı gruptaki öğeler AntD alt menüsü olarak çizilir (grup başlığı, içinde en az bir yetkili öğe varsa görünür). Mevcut öğeler grupsuz ve aynı sırada kalır ("İş Emirleri" = mobilite, "RMA / Servis" adları değişmez).

| Grup | Yol | Etiket | İzin | Dalga |
|---|---|---|---|---|
| Teknik Servis | `/servis-paneli` | Servis Paneli | servis.gor | 1 |
| Teknik Servis | `/operasyon` | Operasyon Merkezi | operasyon.gor | 2 |
| Teknik Servis | `/servis-isleri` | Servis İşleri | servis.gor | 1 |
| Teknik Servis | `/servis-planlama` | Planlama | servis.gor | 1 |
| Teknik Servis | `/benim-islerim` | Benim İşlerim | zaman.yaz | 1 |
| Teknik Servis | `/servis-ekipman` | Ekipman Kütüğü | ekipman.gor | 1 |
| Teknik Servis | `/bakim` | Planlı Bakım | bakim.gor | 1 |
| Teknik Servis | `/atolye` | Atölye | atolye.gor | 2 |
| Teknik Servis | `/kiralamalar` | Kiralamalar | kiralama.gor | 2 |
| Teknik Servis | `/kiralik-envanter` | Kiralık Envanter | kiralama.gor | 2 |
| Teknik Servis | `/yedek-parca` | Yedek Parça | parca.gor | 2 |
| Teknik Servis | `/zaman-takibi` | Saha / Zaman Takibi | servis_rapor.gor | 3 |
| Teknik Servis | `/servis-raporlari` | Servis Raporları | servis_rapor.gor | 3 |
| Teknik Servis | `/servis-maliyet` | Servis Maliyet | maliyet.gor | 2 |
| Teknik Servis | `/fatura-devri` | Fatura Devri | tahsilat.gor | 3 |
| Teknik Servis | `/servis-ana-veri` | Ana Veri Kalitesi | hesap.birlestir | 2 |
| Teknik Servis | `/servis-tanimlar` | Servis Tanımları | [servis.tanim, operasyon.yonet] | 1 |
| İnsan Kaynakları | `/personel` | Personel | personel.gor | 0 |
| İnsan Kaynakları | `/egitim` | Eğitim ve Gelişim | egitim.gor | 2 |
| İnsan Kaynakları | `/gelisim-kartim` | Gelişim Kartım | egitim.kendim | 2 |

**Varsayılan açılış (`main.tsx` index rotası):** `rapor.gor` → `/` (canlı panel, değişmez); değilse `zaman.yaz` ∧ ¬`servis.planla` → `/benim-islerim`; değilse `servis.gor` → `/servis-paneli`; değilse `egitim.kendim` → `/gelisim-kartim`; değilse ilk yetkili menü öğesi. (Servis kullanıcısının `/` PanelPage'de 403 yağmuru görmesi engellenir.)

`a/users.py _SAYFA_IZINLERI` aynı listeyle güncellenir (rol önizlemesi yeni sayfaları tanır).

### 1.11 Paylaşılan kayıt noktaları (her modül buraya **kendi dosyasından** kaydolur)

| Nokta | Dosya | Yapılan (Dalga 0'da altyapı) | Eklenen değerler |
|---|---|---|---|
| Ek sahipleri | `m/attachment.py` `EK_SAHIPLERI`, `EK_TURLERI`; `a/attachments.py` `SAHIP_IZNI`, `_SAHIP_TABLOSU`, `_kapsam` | `_kapsam` bir kayıt defterine (`sv/teknik_servis/ek_kapsam.py: SAHIP_KAPSAMLARI[entity] = async fn(db, user, entity_id, yazma)`) dönüştürülür; `accounts` dalı birebir korunur; dört yapının anahtar eşitliği unit testle kilitlenir; magic-byte yardımcısı `ek_kapsam.icerik_dogrula` (yalnız kayıtlı varlıklar için açılır) | Sahipler: `service_orders, service_equipment, maintenance_contracts, rentals, rental_assets, addresses, training_observations, training_corrective_actions, personnel_certificates`. Türler: `SERVIS_ONCESI, SERVIS_SONRASI, SERVIS_FORMU, BAKIM_FORMU, GOZLEM_FOTOGRAFI, DUZELTICI_KANIT, SERTIFIKA` (+ mevcut `IMZA`; `MUSTERI_IMZASI` açılmaz) |
| Görev panosu | `sv/gorevler.py KAYIT_TIPLERI` | — | `servis_isi`, `ekipman` (etiket `Ekipman #id`), `bakim_sozlesme`, `atolye`, `kiralama`, `egitim_faaliyet`; alanlarda kişisel veri yok |
| Uyarılar | `sv/uyarilar.py topla()` | tek blok: `uyarilar += await ts_uyarilar.topla(db, user, clock)`; `s/uyarilar.py` modül fonksiyonlarını sabit sırayla çağırır, her biri izin + birim kapsamlı | servis, planlama, bakım, zaman, atölye, kiralama, parça, teklif, eğitim, SLA, ana veri |
| KVKK | `sv/kvkk.py` | `ANONIMLESTIRME_KANCALARI`, `VERI_BUL_KANCALARI`, `DENETIM_MASKE_VARLIKLARI` kayıt defterleri | her modül kendi temizleyicisini kaydeder |
| Genel arama | `a/search.py` | `ARAYICILAR` kayıt defteri | `_servis_ara` (so_no, seri_norm), `_ekipman_ara` |
| İçe aktarma | `sv/imports/__init__.py PROFILLER, PROFIL_IZINLERI` | profiller listenin SONUNA eklenir | `personel`, `ad_esleme`, `musteri_eslestirme`, `kutuk`, `bakim_sozlesme`, `servis_isleri`, `servis_plan`, `servis_zaman`, `parca_acilis`, `kiralama_*` |
| Worker | `worker.py GOREVLER` | — | `pb-uretimi` (gece), `bakim-donem-uzlastirma` (gece), `servis-sla-uyarilari` (5 dk), `servis-uyari-temizligi` (24 sa), `kiralama-uzlastirma` (gece, yalnız rapor), `servis-eposta` (Dalga 3) |

### 1.12 Canlı tablolara/uçlara dokunan değişiklikler (tam liste)

Kural: canlı tabloya yalnız `nullable` veya `server_default`'lu kolon; mevcut CHECK/EXCLUDE'a dokunmak YASAK — **onaylı istisnalar** satırda "İSTİSNA" diye işaretli.

| Canlı nesne | Değişiklik | Dalga | Regresyon güvencesi |
|---|---|---|---|
| `users` | `giris_acik` (NOT NULL default true), `sicil_no`+`uq_users_sicil_no` (kısmi), `unvan`, `saha_rolu`+CHECK, `ise_giris_tarihi`, `ayrilis_tarihi`, `ayrilis_nedeni`+CHECK, `ayrilisi_yapan_id`, `yonetici_id`+CHECK, `personel_notu`, `parola_degismeli`, `gecici_parola_bitis`, `parola_degisti_at`, `son_giris_at` | 0 | `test_auth_rbac` yeşil |
| `accounts` | `is_verified` (default true), `verified_at/by`, `dis_referans`, `merged_into_id` + CHECK'ler | 0 | `test_kapsam_guvenligi`, altın kayıt |
| `addresses` | yeni kolonlar + **İSTİSNA: `line DROP NOT NULL`** (yalnız `kind='TESIS'` boş olabilir, `ck_addresses_satir`); downgrade TESIS+line NULL satır varsa durur | 0 | teklif PDF testi |
| `contacts` | `address_id` | 0 | |
| `quotes` | `birim`, `service_order_id`, `contact_id`, `address_id`, gönderim/iptal alanları, indeks; **İSTİSNA: `ck_quote_durum`'a ONAYLANDI, IPTAL eklenir** (drop+create; downgrade ONAYLANDI→TASLAK, IPTAL→RED) | 0 (`address_id`) / 2 | `test_teklif*`, sipariş testleri |
| `quote_versions`, `quote_lines` | onay/gönderim alanları; `quote_lines.service_order_id`; **İSTİSNA: `description` 300→500 genişletme** (yalnız birimli teklif servis katmanında 500) | 2 | |
| `stock_movements` | `hareket_turu`, `service_order_id`, `reversal_of_id`, `transfer_grup`, `stock_count_id`, `part_request_id`, `unit_cost Numeric(14,4)`; yeni CHECK'ler yalnız yeni kolonlara; `trg_stok_hareket_degismez` yalnız `hareket_turu IS NOT NULL` satırlarda | 2 | mobilite stok testleri, `/api/stok/hareketler` servis satırı döndürmez |
| `products` | `yedek_parca`, `birim`, `min_stok` + CHECK'ler | 2 | katalog testleri |
| `warehouses` | `birim`, `kiralama_deposu`, `servis_deposu`, `ck_warehouse_tur_tekil` | 2 | `/api/stok/depolar` yalnız `servis_deposu=false AND kiralama_deposu=false` |
| `audit_logs` | `trg_audit_degistirilemez` | 4 | KVKK anonimleştirme testi |
| `user_permissions` | `bitis_at` + CHECK | 4 | |
| Uçlar | `a/users.py` (kapsam, yetki yükseltme), `a/auth.py`+`sv/auth.py` (oturum, `giris_acik`, parola), `a/attachments.py` (kayıt defteri), `a/stock.py`+`sv/stock.py` (servis/kiralama depolarına 409), `a/catalog.py` (identity_kind koruması), `a/quotes.py`/`a/public_quotes.py`/`a/orders.py` (birimli teklif kuralları; servis teklifi siparişe 409), `sv/reports.py`+`a/reports.py` (satış panel/raporu yalnız `birim IS NULL` teklif), `sv/mail.py` (`_smtp_gonder`, genel hata mesajı), `sv/belgeler.py` (teklif adresi TESIS atlar), `sv/settings.py`, `sv/uyarilar.py`, `sv/kvkk.py`, `a/search.py`, `sv/gorevler.py`, `worker.py`, `sv/imports/hesap.py` (Cari Kodu sütunu) | 0–4 | her değişiklik için mevcut test + yeni regresyon testi |

**Hiç dokunulmayanlar:** `work_orders`, `work_order_items`, `settlement*`, `installation_partners`, `devices` (yazma yok; yalnız okunur), `vehicles`, cihaz/hat/araç durum makineleri, `PanelPage`, `RaporlarPage`'in mobilite sekmeleri, `sv/reports.dashboard` (yalnız teklif süzgeci eklenir), `export.satirlari_xlsx`, `clock.py`.

---

## 2. Birleştirilmiş madde listesi

Toplam **181 madde** (Dalga 0: 18 · Dalga 1: 55 · Dalga 2: 71 · Dalga 3: 26 · Dalga 4: 11) + 1 ertelenen. Öncelik dağılımı: P1 88 · P2 79 · P3 14. Her maddenin "bitti" tanımı §4.5'teki ortak DoD + satırdaki kabul ölçütüdür. Kaynak modül maddesinin `revised` metni ve kabul ölçütleri, bu satırla çelişmedikçe aynen geçerlidir.

### 2.1 Dalga 0 — Ortak altyapı

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-001 | İzin kataloğu, kapsam sabitleri, servis rolleri | E01-01, E03-01, E04-01, E05-26, E06-01, E07 izin, E08-01, E09-17, E10-14, E11-05, E12-09, E12-D01, E13-10, E13-D01, E14-D01 | KISMEN | P1 | M | – | D0-A | `permissions.py`, `seeds/dev.py`, `t/unit/test_permissions.py` | §1.3–1.4 birebir; her izin ≥1 rolde; `maliyet.gor` kümesi sabit; YONETIM'de yazma izni ve `egitim.detay`/`servis.irtibat_gor`/`servis_rapor.personel` yok; `TEKNIK_SERVIS` izin listesi anlık görüntüyle aynı; servis rollerinde `isemri.*, hakedis.*, tahsilat.*, rapor.gor, rapor.disaaktar, hesap.yaz, maliyet.*` yok; `SERVIS_TEKNISYEN`'de `hesap.gor` yok; seed özelleştirilmiş rol eksiklerini log'a yazar |
| TS-002 | Birim üyeliği yönetimi (`user_units`) | E01-01, E13-06, K21 | YOK | P1 | S | TS-001, TS-018 | D0-D | `s/personel.py`, `a/personel.py`, `p/PersonelPage.tsx` | `PUT /api/personel/{id}/birimler` (`personel.yaz`); BIRIMLER dışı 400; iki birincil 409; kişi kendi birimini değiştiremez 403; `log_change`; `/api/auth/me` `birimler`, `birincil_birim` döner |
| TS-003 | Kapsam yardımcıları (birim, personel, katalog) | E01-01(5), E08-01, E13-11, 00 §6.3 | YOK | P1 | S | TS-001 | D0-A | `s/kapsam.py`, `t/integration/test_birim_kapsami.py` | §1.2 tablosu; birimsiz KENDI_BIRIMI → liste boş/tek kayıt 404; KENDI_MUSTERILERI + servis izni istisnası → boş; TUMU hepsi; unit testler her kapsam × varlık türü |
| TS-004 | Kullanıcı/rol ekranları yeni kapsamları ve sayfaları tanır | E01-01(K29, 2–4), E01-D02, E13-D02 | KISMEN | P1 | S | TS-001 | D0-A | `a/users.py`, `c/RolDuzenle.tsx`, `p/UsersPage.tsx`, `auth/AuthContext.tsx`, `t/integration/test_rol_ve_izin_duzenleme.py` | `users.py:181,225` `SCOPES` üyeliğine çevrilir; rol ekranında 4 kapsam seçilir; `_KAPSAM_ACIKLAMA` ve `_SAYFA_IZINLERI` §1.10 ile güncel; kapsam etiketleri genelleşir; mevcut rol testleri yeşil |
| TS-005 | Menü grubu, açılış sayfası, rota iskeleti | E01-02 (menü), E13-D02 | YOK | P1 | S | TS-001 | D0-B | `c/AppLayout.tsx`, `main.tsx` | `grup` desteği; §1.10 açılış kuralı; servis rolü girişte `/servis-paneli`, teknisyen `/benim-islerim`; `/` 403 hatası görülmez; 375 px'te yatay kaydırma yok |
| TS-006 | Yetki yükseltme önlemi | E13-01 | KISMEN | P1 | M | TS-001 | D0-A | `sv/yetki.py` (yeni), `a/users.py`, `t/integration/test_yetki_yukseltme.py` | E13-01 revised (1)–(8): YUKSEK_YETKILI_IZINLER yalnız ADMIN; ADMIN'i yalnız ADMIN atar; `rol_guncelle('ADMIN')` 409; son aktif ADMIN korunur 409; üst yetkili hedefte `personel.*` 403; retler denetime yazılır |
| TS-007 | Oturum: 12 saat mutlak süre ve `giris_acik` | E13-02 | KISMEN | P1 | S | TS-018 | D0-A | `sv/auth.py`, `a/auth.py`, `t/integration/test_oturum_suresi.py` | `SESSION_MAX=12h` kod sabiti; `User.giris_yapabilir_mi()` authenticate/login_mfa/resolve_session'da; `giris_acik=false` yapan her yol `revoke_all_sessions`; MFA'lı girişsiz hesap pending_token ile 401 |
| TS-008 | Personel kartı = kullanıcı; aktifleştirme girişi açmaz | E13-05, E13-03 | KISMEN | P1 | M | TS-002, TS-006 | D0-D | `s/personel.py`, `a/personel.py`, `p/PersonelPage.tsx`, `fa/personel.ts`, `p/UsersPage.tsx` (bağlantı), `t/integration/test_personel.py` | E13-05/03 revised; `PersonelOut` ayrı, e-posta/kullanıcı adı/not yalnız `personel.yaz`; `log_change(is_personal_data=True)`; üst yetkili hedefte `full_name` 403; yeniden aktifleştirme `giris_acik`'ı açmaz |
| TS-009 | Atanabilir personel servisi (planlama kaynak listesi) | E13-07, E02-04 | YOK | P1 | M | TS-002, TS-008 | D0-D | `s/personel.py`, `a/personel.py`, `t/integration/test_atanabilir_personel.py` | `GET /api/personel/atanabilir?birim=` (`servis.gor`); ölçüt: aktif, ayrılmamış, `saha_rolu ∈ ATANABILIR`, birim üyesi; `giris_acik` süzülmez ("giriş yok" bayrağı); KENDI_ISLERI yalnız kendisi; birim doğrulanır 400, kapsam dışı 404; alanlar `{id, ad, saha_rolu, birimler, birincil_birim, giris_acik}` |
| TS-010 | Personel toplu yükleme profili | E13-04 | KISMEN | P1 | S | TS-008 | D0-D | `sv/imports/personel.py`, `t/fixtures/personel_ornek.xlsx`, `t/integration/test_personel_yukle.py` | `PROFIL_IZINLERI['personel']='personel.yaz'`; eşleşme sicil → username; yeni kayıt `giris_acik=false`, rol SERVIS_TEKNISYEN, parola rastgele sırrın argon2 özeti; ikinci uygulama 0 yeni satır; depoda gerçek ad yok |
| TS-011 | Ortak yardımcılar: yerel zaman, numara, normalizasyonlar | E01-02, E03-10/12/D01, E05-D01, E09-16, E10-12, E14-01, E14-D02 | YOK | P1 | S | – | D0-B | `s/yerel_zaman.py`, `s/numara.py`, `sv/normalize.py` (yalnız ekleme), `pyproject.toml` (tzdata), `t/unit/test_normalize_seri.py`, `t/unit/test_teknik_servis_saat.py` | `yerel_bugun/yerel_gun/yerel_gun_araligi(clock)` Europe/Istanbul; `belge_no()`; `normalize_seri`: strip, iç boşluk teke, ASCII büyük harf (i/ı/İ→I), sıfır ve `/-.` korunur (`' abc-i01 '→'ABC-I01'`, `00123≠123`, `AB-1≠AB1`); `unvan_anahtari`; `il_normalize` (81 il listesi); `s/` altında `datetime.now`/`date.today` arayan grep testi |
| TS-012 | Paylaşılan kayıt noktaları + DEFAULTS + KpiKutusu | E01-07(_kapsam yapısı), E01-18, E03-16, E06-02, E12-08, E01-14 | KISMEN | P1 | M | TS-018 | D0-B | `a/attachments.py`, `m/attachment.py` (sabitler), `s/ek_kapsam.py`, `sv/gorevler.py`, `sv/uyarilar.py`, `s/uyarilar.py`, `a/search.py`, `sv/imports/__init__.py`, `sv/settings.py`, `c/KpiKutusu.tsx` | §1.9 ve §1.11 tam; `test_kapsam_guvenligi` (accounts) yeşil; ek sözlük eşitliği unit testi; `AYAR_SINIRLARI` doğrulaması; KpiKutusu `{kod, baslik, tanim, deger, yol}` alır, tıklama `navigate(yol)` |
| TS-013 | Test altyapısı ve otomatik yetki matrisi | E13-14, E01-19, E09-18, E10-19, E07-D05 | KISMEN | P1 | M | TS-001, TS-018 | D0-B | `t/conftest.py`, `a/deps.py` (`_guard.izinler`), `t/integration/test_yetki_matrisi.py`, `t/integration/test_router_kapsam_taramasi.py`, `t/unit/test_servis_sozluk_tutarliligi.py`, `pyproject.toml` (markers) | fixture'lar: `birimli_kullanici_ac(rol, birimler)`, `servis_isi_ac`, `ekipman_ac`, `sozlesme_ac`, `lokasyon_ac`; matris `app.routes`'tan rol × uç 200/403 üretir ve yeni uçları otomatik kapsar; uç taraması `{id}` yollu tüm teknik servis uçlarında kapsam dışı 404 + veri değişmedi |
| TS-014 | Müşteri genişletmesi: doğrulama, hızlı ekleme, VKN, cari kodu, hafif arama | E14-01, E14-D01 | KISMEN | P1 | M | TS-018, TS-011 | D0-C | `s/ana_veri.py`, `a/teknik_servis_ana_veri.py`, `a/accounts.py` (yalnız `/dogrula`), `sv/imports/hesap.py`, `p/HesaplarPage.tsx`, `t/integration/test_ana_veri_musteri.py` | E14-01 revised; VKN çakışması yalnız değişince 409+onay; `is_verified/verified_*/merged_into_id` HesapIn/Patch'te yok; musteri-ara ad+il döner, VKN/IBAN yok; doğrulama `hesap.birlestir` |
| TS-015 | Lokasyon (tesis), lokasyon irtibatı, takma ad, ortak doğrulayıcı ve lokasyon anahtarı | E14-02, E14-04 (fonksiyon), E14-06, E02-09, E14-16 (kaynak) | KISMEN | P1 | M | TS-014 | D0-C | `s/ana_veri.py`, `a/lokasyonlar.py`, `sv/belgeler.py` (K24), `c/LokasyonPenceresi.tsx`, `c/MusteriLokasyonSecici.tsx`, `fa/anaVeri.ts`, `t/integration/test_ana_veri_lokasyon.py`, `t/unit/test_servis_lokasyon_anahtari.py` | E14-02 revised; `lokasyon_dogrula`, `lokasyon_anahtari`, `saha_onerisi_kaynak` tek yerde; 'Akyaka  AVM' ve 'AKYAKA AVM' aynı anahtar; adressiz kayıt gruplanmaz; teklif PDF'i TESIS satırını atlar ve bugünkü çıktı değişmez |
| TS-016 | Ana veri KVKK ve denetim | E14-03 | KISMEN | P1 | S | TS-014, TS-015 | D0-C | `sv/kvkk.py` (kayıt defterleri dahil), `t/integration/test_ana_veri_kvkk.py` | E14-03 revised; anonimleştirmede `alias_key/site_key` maskeli metinden yeniden üretilir; `addresses`, `account_aliases` denetim satırları maskelenir; `veri_bul` yeni alanları arar |
| TS-017 | Veri kalitesi ölçümü (kaynak + canlı) ve kütük profili | E14-08, E03-05 | YOK | P1 | S | – | D0-E | `mg/teknik_servis/sql/m14_olcum.sql`, `mg/ana_veri_olcum.py`, `mg/kutuk_profil.py`, `t/integration/test_ana_veri_olcum.py` | salt okunur (`SET TRANSACTION READ ONLY`); aynı VKN'li aktif hesap grupları, çok adresli hesap sayısı, il yazım çeşitleri, kütük mükerrer seri / serisiz satır sayıları raporlanır; sayı uydurulmaz |
| TS-018 | Şema iskeleti: Dalga 0 + Dalga 1 tüm tablolar, sequence'ler, tetikleyici, makineler, kanca ve dosya iskeletleri | E01-02/04 (model), E02-01, E03-02, E04-02/05/09/13/14/15, E09-01, E10-03 (katalog), E12-02 (kolon), E01-D01, E04-D01, E05-D02 | YOK | P1 | L | – | D0-S | §4.2 "D0-S" satırı | 7 migration (§4.3) head→base→head yeşil, tek head; `uq_so_pb_cihaz_donem`, `uq_svcplan_aktif`, `ex_mci_ekipman_cakisma`, `ex_svcmusait_cakisma`, `ex_ste_kisi_cakisma`, `trg_soe_salt_ekleme` mevcut; `SERVIS_IS_EMRI/SERVIS_EKIPMANI/BAKIM_SOZLESMESI` meta-testte; tüm Dalga 1 servis/API/sayfa dosyaları imzalı iskelet olarak var (uçlar 501 değil, router kayıtlı ama boş); altın kayıt yeşil |

### 2.2 Dalga 1 — Çekirdek teknik servis akışı

**Servis iş emri (E01)**

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-020 | Servis işi açılış, detay, TUR_KURALLARI, kategori, numara, PB değişmezleri | E01-02, E01-16, E01-17, E14-04 | YOK | P1 | L | TS-018, TS-003, TS-015 | D1-B | `s/is_emirleri.py`, `a/teknik_servis.py`, `t/integration/test_servis_is_emri.py` | E01-02 revised; müşteri `is_musteri ∧ ¬is_deleted`; `lokasyon_dogrula`; TUMU her birime, birim kapsamlı yalnız kendi birimine açar (aksi 404); `SRV-`/`PB-` biçimi; PB'de tür/seri değişikliği ve PB'ye tür geçişi 409; tek kayıt kapsam dışı 404 + veri değişmedi |
| TS-021 | Tek `durum_degistir`, makine, kancalar, `first_completed_at`, durum grupları | E01-03, E01-D01, E05-D02, E10-11, E12-01, E12-02 | KISMEN | P1 | L | TS-020, TS-022 | D1-B | `s/is_emirleri.py`, `s/kancalar.py` (uygulama), `t/integration/test_servis_durum.py`, `t/unit/test_servis_durum_gruplari.py` | §1.7 tablosu; `UC_HEDEFLERI` dışı geçiş 409; aynı durum 409; BEKLEMEDE dışına her geçişte aktif bekleme aynı transaction'da kapanır; `first_completed_at` ilk TAMAMLANDI'da yazılır, TEKRAR_ACILDI'da silinmez; KAPATILDI yalnız `servis.kapat` |
| TS-022 | Silinemez olay geçmişi ve iş notu | E01-04 | KISMEN | P1 | S | TS-018 | D1-B | `s/gecmis.py`, `a/teknik_servis.py` | E01-04 revised; UPDATE/DELETE tetikleyici reddeder (test); `olay_yaz` irtibat adı/telefon/imzalayan adını reddeder (unit); kritik işlemler ayrıca `audit.log` |
| TS-023 | Bekleme akışı ve bekleme nedeni kataloğu | E01-05, E10-03 | YOK | P1 | M | TS-021 | D1-B | `s/bekletme.py`, `a/teknik_servis.py`, `t/integration/test_servis_bekleme.py` | tek aktif bekleme (`uq_hold_aktif`); katalog dışı neden 400; DIGER açıklama zorunlu; `sadece_sistem` neden kullanıcıdan 400; `beklemeyi_bitir` önceki duruma döner; süre ve geçmiş listelenir; katalog düzenleme `operasyon.yonet` |
| TS-024 | Kapanış sonucu, çözüm kanalı, arıza nedeni kataloğu, açılışta çözüldü | E01-06 | YOK | P1 | M | TS-021 | D1-B | `s/sonuc.py`, `a/teknik_servis.py` | sonuçsuz TAMAMLANDI 409; `cozum_kanali` NOT NULL; teknisyen yalnız TAMAMLANDI (KAPATILDI 403); `servis.uzaktan_coz` tek istekte açılış+TAMAMLANDI, iki olay; arıza nedeni birim bazlı, `servis.tanim` |
| TS-025 | Kimlik bazlı çoklu atama, tek sorumlu, toplu atama, ekip senkronu | E01-12, E02-08, E02-D01, E09-09 | YOK | P1 | M | TS-021, TS-009 | D1-B | `s/atama.py`, `a/teknik_servis.py`, `t/integration/test_servis_atama.py`, `t/integration/test_servis_ekip_senkron.py` | atanabilir = TS-009 ölçütü; ayrılmış kullanıcı 400; girişsiz saha personeli 200; tek sorumlu `uq_soa_tek_sorumlu`; toplu atama ≤150, 151 → 422, kural ihlalinde hiçbir iş değişmez; `ekip_degisiyor` 409'u (açık sayaç) tüm isteği geri alır; aktif planlı işte plan üyeleri = atamalar |
| TS-026 | Liste: sunucu filtresi, SQL kapsamı, sayfalama, tipli Excel | E01-15, E12-06 | KISMEN | P1 | M | TS-020 | D1-B | `s/is_emirleri.py`, `sv/export.py` (`sayfalari_xlsx_async` + isteğe bağlı sütun şeması), `a/teknik_servis.py`, `t/integration/test_servis_excel.py` | `sayfala()`; `X-Toplam-Kayit` = Excel satır sayısı; Excel `servis.gor + servis_rapor.disaaktar`; seri METIN, tarih yerel; maskeli telefon Excel'de de maskeli; `satirlari_xlsx` değişmez |
| TS-027 | Tek kayıt kapsamı, KENDI_ISLERI, telefon maskeleme, uç taraması | E01-20, E01-01 kabul, E02-D02 (fonksiyon) | KISMEN | P1 | M | TS-025 | D1-B | `s/kapsam.py` (`kapsam_isler`, `is_erisimi_yok_mu`), `a/teknik_servis.py`, `t/integration/test_servis_kapsam.py` | atanmamış teknisyen her uçta 404 + veri değişmedi; `servis.tamamla` olmayan 403, `servis.kapat` olmayan 403; `servis.yaz` olmayana telefon `kvkk.maskele` ile (liste+Excel); KENDI_ISLERI teknisyeni `/api/hesaplar` 403 |
| TS-028 | Mobilite etkisizlik regresyonu | E01-D04, E02-D03 | YOK | P1 | S | TS-020 | D1-B | `t/integration/test_servis_mobilite_etkisizlik.py`, `t/unit/test_servis_bagimsizlik.py` | servis akışının tamamı koşulduktan sonra `work_orders`, `work_order_items`, `settlements*`, `devices`, `vehicles` satır sayısı ve özeti aynı; uyarı sayıları ve `reports.dashboard` aynı; `s/` altında bu tablolara yazan import yok (unit) |
| TS-029 | Talep alma bilgileri ve mükerrer kontrolü | E01-09 | YOK | P2 | S | TS-020 | D1-B | `s/is_emirleri.py`, `a/teknik_servis.py` | açık işte aynı `seri_norm` 409 (kapsam dışı mükerrerde iş no verilmez); müşteri+lokasyon eşleşmesi yalnız uyarı; `reported_at` en çok 7 gün geri |
| TS-030 | Bağlı iş ilişkisi | E01-11 | YOK | P2 | S | TS-029 | D1-B | `s/is_emirleri.py` | tek üst bağ; kendine bağ CHECK; kapsam dışı bağda iş no maskeli |
| TS-031 | Temel bilgi, seri, müşteri/lokasyon gerekçeli düzeltme | E01-13, E14-13 | YOK | P2 | S | TS-021 | D1-B | `s/is_emirleri.py`, `a/teknik_servis.py`, `t/integration/test_servis_musteri_duzeltme.py` | iyimser kilit 409; kapalı işte yalnız `servis.kapat` + gerekçe; açık işte müşteri düzeltme `servis.planla`; PB'de müşteri/seri düzeltme 409; teknisyen 403; DUZELTME olayı |
| TS-032 | Servis işi ekleri: fotoğraf/form/imza, magic-byte, 24 saat silme | E01-07 | KISMEN | P1 | M | TS-012, TS-027 | D1-C | `s/ek_kapsam.py` (service_orders dalı), `t/integration/test_servis_ekler.py` | E01-07 revised; okuma birim+kendi işi, yazma aktif atama; magic-byte uyuşmazlığı 400 (yalnız service_orders); 24 saat EK olayının zamanından; onaya bağlı ek silme 409; EK_SIL olayı ad+sha256 tutar |
| TS-033 | Servis İşleri ön yüzü (liste, Drawer, form, durum/bekleme/sonuç/atama pencereleri) | E01-02…E01-13 (UI) | YOK | P1 | L | TS-020…TS-027 | D1-C | `p/ServisIsleriPage.tsx`, `p/ServisIsFormu.tsx`, `fa/teknikServis.ts` | butonlar `sonraki_durumlar` ve `yetkili()` ile; sunucu sayfalaması; 409'da yenileme mesajı; `npm run build` temiz; 375 px'te kullanılabilir |
| TS-034 | Formda müşteri-lokasyon-irtibat seçici, hızlı ekleme, plan ön dolumu | E14-05 | YOK | P1 | M | TS-015, TS-033 | D1-C | `c/MusteriLokasyonSecici.tsx`, `p/ServisIsFormu.tsx` | arama 300 ms debounce, sunucuda; hızlı ekleme `servis.yaz+lokasyon.yaz`; seçilen lokasyonun birincil irtibatı önerilir; kart IBAN/VKN göstermez |
| TS-035 | Servis Paneli ve tek KPI tanım kaydı | E01-14, E05-21 | KISMEN | P1 | M | TS-021, TS-023, TS-024, TS-025 | D1-C | `s/panel.py` (`KPI_TANIMLARI`), `a/teknik_servis.py` (`/panel`, `/isler?kpi=`), `p/ServisPaneli.tsx`, `t/integration/test_servis_panel.py` | her kutu sayısı = `/isler?kpi=<kod>` `X-Toplam-Kayit`; dönem seçimi; birim kapsamı; "Atölyede" = kategori ATOLYE ∧ açık; "bugün planlı" kutusu Dalga 1'de var (planlama aynı dalgada); mobilite `PanelPage` değişmez |
| TS-036 | Müşteri onayı (tekil + ziyaret grubu) ve Türkçe servis formu PDF'i (tekil + ziyaret toplu) | E01-08, E04-15, E04-16 | KISMEN | P2 | L | TS-024, TS-032 | D1-C | `s/onay.py`, `templates/servis_formu.html`, `a/teknik_servis.py`, `t/integration/test_servis_onay.py` | IMZA (canvas PNG ek), SOZLU, BASILI_FORM, ALINAMADI+neden; `servis_onay_zorunlu_turler` (varsayılan PB) kapanışta kontrol; ziyaret onayı: aynı müşteri+adres+gün (409), erişim (404), tek transaction'da `onay_grubu`; PDF fiyatsız, Türkçe karakter, PB'de kontrol listesi bloğu, süre yoksa "Süre kaydı eksik"; anonimleştirme sonrası imza eki indirilemez |
| TS-037 | Servis uyarıları, görev bağlantısı, genel arama, KVKK | E01-18 | KISMEN | P2 | S | TS-012, TS-035 | D1-C | `s/uyarilar.py` (servis bloğu), `s/is_emirleri.py` (KVKK kancası) | E01-18 revised (1)–(5); arama so_no/seri_norm kapsamlı; saklama listesi son N yılda servis işi olan müşteriyi hariç tutar; anonimleştirme sonrası servis denetim satırlarında telefon yok |

**Planlama ve toplu atama (E02)**

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-040 | Plan yazımı: tek aktif plan, kilit, kapalı işi geri çekmeme | E02-01, E02-02 | YOK | P1 | M | TS-021 | D1-D | `s/planlama.py`, `t/integration/test_servis_planlama_eszamanli.py`, `t/integration/test_servis_planlama_durum.py` | E02-01/02 revised; eşzamanlı iki istekten sonra tek aktif satır; MUSTERI_TALEBI/PLANLAMADA/TEKRAR_ACILDI → PLANLANDI; saha/atölye/bekleme durumunda yalnız plan güncellenir; kapalı işte 409 ve db.refresh sonrası değişiklik yok |
| TS-041 | Tekli plan ve ekip ataması (tek uç, tek transaction) | E02-03 | YOK | P1 | S | TS-040, TS-025 | D1-D | `a/teknik_servis_planlama.py`, `c/PlanPenceresi.tsx`, `fa/servisPlanlama.ts`, `t/integration/test_servis_planlama_tekli.py` | `PUT /isler/{id}/plan` + `beklenen_aktif_plan_id`; uyuşmazlık 409; şema ihlali 422; ekip `atama.ata` ile; araç aktif ve birimi uygun, aksi 409; hata enjeksiyonunda ne plan ne üye yazılır |
| TS-042 | Takvim (Gün/Hafta/Ay), plansız havuz, şehir/ilçe gruplama, planlama KPI'ları, KENDI_ISLERI | E02-05, E02-06, E02-16 (havuz), E02-D02, E14-06 | YOK | P1 | M | TS-040 | D1-D | `s/takvim.py`, `a/teknik_servis_planlama.py`, `p/ServisPlanlamaPage.tsx` | tarih aralıklı yükleme (≤62 gün); havuz `lokasyon_anahtari` + `addresses.city/district`; KPI sayı = liste; teknisyen yalnız kendi işlerini görür; `slow` işareti kayıtlı |
| TS-043 | Toplu planlama ve PB toplu planlama | E02-07, E04-12 | YOK | P1 | M | TS-041, TS-042 | D1-D | `s/planlama.py`, `a/teknik_servis_planlama.py`, `c/PlanPenceresi.tsx` (toplu mod), `t/integration/test_servis_toplu_plan.py` | `POST /toplu-plan`; karışık birim/müşteri/lokasyon/kapalı/planlı iş 409 + iş no listesi; 151 iş 422; bir `service_visits`, iş başına plan + üye; PB seçimi bakım dönem ekranından aynı pencereyle; kapalı ve IPTAL satır seçilemez |
| TS-044 | Erteleme nedeni, plan geri alma, plan geçmişi | E02-12 | YOK | P2 | M | TS-040 | D1-D | `s/planlama.py`, `a/teknik_servis_planlama.py`, `t/integration/test_servis_plan_gecmisi.py` | `DELETE /isler/{id}/plan {neden, not}`; PLANLANDI → PLANLAMADA; nedensiz erteleme 409; `/plan-gecmisi` tüm satırlar |
| TS-045 | Çakışma kontrolü ve şefin "sahaya gidiyor" bayrağı | E02-15, E02-10 | YOK | P2 | M | TS-041 | D1-D | `s/cakisma.py`, `fa/client.ts` (yalnız `govde` alanı ekleme), `c/PlanPenceresi.tsx`, `t/unit/test_servis_cakisma.py`, `t/integration/test_servis_cakisma_eszamanli.py` | 409 `{detail, kod:'PLAN_CAKISMA', cakismalar}`; gerekçeyle geçme `servis.planla`; kapsam dışı çakışan iş maskeli; advisory lock gün sıralı; şef yalnız `sahaya_gidiyor` ise çakışmaya girer |
| TS-046 | Ziyaret kartındaki seçili işleri tek işlemde yeniden planlama | E02-13 | YOK | P2 | M | TS-044, TS-045 | D1-D | `s/planlama.py`, `p/ServisPlanlamaPage.tsx`, `t/integration/test_servis_yeniden_plan.py` | tarih/saat değişirse YENIDEN_PLAN + neden zorunlu; yalnız ekip/araç → EKIP_DEGISIMI; kural ihlalinde 409 + iş no listesi |
| TS-047 | Saha önerisi (aynı lokasyonun son planı) | E02-11, E14-16 | YOK | P2 | S | TS-042 | D1-D | `s/planlama.py`, `a/teknik_servis_planlama.py`, `t/integration/test_servis_saha_onerisi.py` | adres/irtibat yalnız aynı müşteriye aitse; kütük `contact_name_raw` öneri olmaz; telefon yalnız `servis.irtibat_gor` |
| TS-048 | Servis araç havuzu | E02-17 | KISMEN | P2 | M | TS-041 | D1-D | `a/teknik_servis_planlama.py`, `p/ServisPlanlamaPage.tsx`, `t/integration/test_servis_araclar.py` | `servis.arac_yaz`; plaka anahtarı tekil; birim NULL = ortak havuz; `vehicles` yalnız okunur |
| TS-049 | Planlama uyarıları, Excel, irtibat gizliliği, planlama KVKK | E02-25, E02-19, E02-24, E02-D05 | YOK | P2 | S | TS-042 | D1-D | `s/uyarilar.py` (planlama fonksiyonu kendi dosyasında `s/takvim.py`), `a/teknik_servis_planlama.py`, `sv/kvkk.py` kaydı (kendi dosyasından) | Excel `?baslangic=` boşta 200; irtibat alanları izinsizde null; hesap anonimleştirmesi plan serbest metinlerini temizler; uyarı birim + KENDI_ISLERI kapsamlı |

**Güvenlik cihaz kütüğü (E03)**

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-050 | Ekipman ekle/düzenle/pasif; kapsam; tek yazma kapısı; hesap-adres-irtibat tutarlılığı | E03-01, E03-02, E03-D02, E03-D04 | YOK | P1 | M | TS-018, TS-015 | D1-E | `s/ekipman.py`, `a/servis_ekipman.py`, `c/EkipmanFormu.tsx`, `fa/servisEkipman.ts`, `t/integration/test_servis_ekipman.py`, `t/integration/test_servis_ekipman_kapsam.py` | E03-02 revised; mükerrer anahtarı (tip, tr_normkey(marka), serial_key) + advisory lock → 409 + `duplicate_ack_reason` ile geçilir; hesap değişince adres/irtibat sıfırlanır; `uq_svceq_cihaz`; tüm `/ekipman*` uçlarında müşteri+birim kapsamı; statik yollar `/{id}`'den önce |
| TS-051 | Kütük değişiklik geçmişi (audit_logs) | E03-03 | KISMEN | P1 | S | TS-050 | D1-E | `s/ekipman.py`, `c/EkipmanKarti.tsx`, `t/integration/test_servis_ekipman_gecmis.py` | irtibat alanları ayrı `is_personal_data=True` satırı; anonimleştirme sonrası seri değişikliği görünmeye devam eder |
| TS-052 | Ekipman kartı ve birleşik geçmiş (servis işi, bakım, atölye, parça) | E03-06, E04-17 (geçmiş) | YOK | P1 | M | TS-051 | D1-E | `s/ekipman.py` (`gecmis()` tek fonksiyon), `c/EkipmanKarti.tsx` | olay kaynakları modül kancasıyla eklenir (bakım Dalga 1, atölye/parça Dalga 2); maliyet anahtarı yalnız `sees_cost` |
| TS-053 | Kütük ekranı: liste, filtre, sayfalama, Excel (T1) + tıklanabilir KPI ve toplu işlem (T2) | E03-11 | KISMEN | P1 | M | TS-050 | D1-E | `p/ServisEkipmanPage.tsx`, `a/servis_ekipman.py` | T1 P1, T2 P2; Excel ≤20.000 satır, seri metin; özet sayıları kapsamlı |
| TS-054 | Tek normalize seri ile eşleşme ve lokasyon önerisi | E03-12 | YOK | P2 | S | TS-050, TS-011 | D1-E | `s/ekipman.py` (`seri_ile_bul`) | öneri yalnız kapsam içi TEK eşleşmede; başka birimin kaydı öneri vermez |
| TS-055 | Yaşam döngüsü durumu ve hesaplanan "Serviste" rozeti | E03-09 | YOK | P2 | M | TS-051 | D1-E | `s/ekipman.py`, `p/ServisEkipmanPage.tsx` | `SERVIS_EKIPMANI` makinesi; HURDA gerekçe zorunlu; rozet açık ARIZA işinden hesaplanır, saklanmaz |
| TS-056 | Garanti tarihleri/kaynağı ve sözleşme bağı sayısı | E03-08 | KISMEN | P2 | M | TS-050, TS-060 | D1-E | `s/ekipman.py`, `p/ServisEkipmanPage.tsx` | toplu garanti önizlemeli, HESAPLANDI kaynaklı, BELGE kayda dokunmaz; "bağlı ekipman" ile sözleşme adedi ayrı gösterilir |
| TS-057 | Ekipman ekleri, görev, arama, KVKK | E03-16 | KISMEN | P2 | S | TS-012, TS-050 | D1-E | `s/ek_kapsam.py` (service_equipment dalı — D1-C ile koordineli, bkz. §4.2), `s/ekipman.py` | başka birim/müşteri eki 404; KayitTipi etiketi `Ekipman #id`; anonimleştirme `contact_name_raw`'ı temizler |

**Planlı bakım ve dijital form (E04)**

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-060 | Bakım sözleşmesi yönetimi, tür+adet kapsamı, ücret giriş yolu, tesis/cari ve dönem çakışması uyarısı | E04-02, E04-D04, E14-11 (uyarı) | YOK | P1 | L | TS-018, TS-015 | D1-F | `s/bakim.py`, `a/bakim.py`, `p/BakimPage.tsx`, `fa/bakim.ts`, `t/integration/test_bakim_sozlesme.py` | E04-02 revised; ilk dönem penceresindeyken üretim N PB açar; ücret ayrı uç (`maliyet.gor ∧ bakim.yaz`, pratikte ADMIN); ücret görmeyene alan yok, gönderirse 403; aynı tesiste çakışan dönem 409 + onay |
| TS-061 | Dönem modeli (sayaç saklanmaz, döngüden hesaplanır) | E04-05 | YOK | P1 | M | TS-060 | D1-F | `s/bakim.py`, `t/unit/test_bakim_takvim.py` | E04-05 kabul 1 (yıl devri); `donem_kapanisini_guncelle` idempotent ve geri açabilir |
| TS-062 | PB üretim motoru, worker, hedef tarih, önizleme, ekipman kimliğiyle eşleşme | E04-06, E04-07, E04-08, E03-07, E14-10 | YOK | P1 | M | TS-061, TS-020 | D1-F | `s/bakim_uretim.py`, `s/bakim_sablonlari.py`, `worker.py` (`pb-uretimi`), `t/integration/test_bakim_uretim.py` | `ON CONFLICT ... DO NOTHING RETURNING`; aynı tur iki kez koşunca 0 yeni PB; gerekçeli `skipped` (SURESI_DOLMUS, EKIPMAN_YOK, SABLON_YOK…); yalnız `equipment_id` dolu ve `pb_uygun` kalemlerde PB; NULL kalem = adet farkı uyarısı; worker `bakim_otomatik_uretim=False` iken çalışmaz, elle üretim `bakim.yaz`; önizleme = SAVEPOINT içinde aynı `uret()` |
| TS-063 | Sözleşme–ekipman ilk eşleştirmesi (sistem önerir, şef onaylar) | E03-D03 | YOK | P1 | M | TS-060, TS-054 | D1-F | `s/bakim.py`, `p/BakimPage.tsx`, `t/integration/test_servis_bakim_eslestirme.py` | tek aday → öneri, çoklu aday → listede; onay `bakim.yaz`; tamamlanma oranı ekranda; `bakim_otomatik_uretim` bu ekranda %100 olmadan açılamaz (409) |
| TS-064 | Dijital bakım formu, ziyaret kaydı, tamamlamada ekipman bağlama | E04-09, E04-13, E04-17 | YOK | P1 | L | TS-062, TS-024 | D1-F | `s/bakim_formu.py`, `a/bakim.py`, `p/BakimFormu.tsx`, `t/integration/test_bakim_formu.py` | E04-09/13/17 revised; BEKLIYOR madde ile tamamlama 409; UYGUNSUZ madde notu zorunlu; tamamlama `durum_degistir(kaynak='BAKIM_FORMU')`; her başarılı tamamlamada değişmez `maintenance_visits` satırı; EXCLUDE ihlali tamamlamayı bloke etmez, uyarı döner; atanmamış teknisyen 404 |
| TS-065 | PB koruma kancası ve dönem kapanışı gece uzlaştırması | E04-10, E04-D02 | YOK | P1 | S | TS-064, TS-021 | D1-F | `s/bakim_formu.py` (`pb_gecis_dogrula`, kanca kaydı), `worker.py` (`bakim-donem-uzlastirma`) | PB'de genel uçtan TAMAMLANDI/IPTAL 409 (Kapsam Dışı yolunu gösteren mesaj); `/sonuc` PB'de 409; TEKRAR_ACILDI/KAPATILDI dönem kancasını çalıştırır; uzlaştırma farkı log'a |
| TS-066 | Cihazın dönem dışı bırakılması (kapsam dışı talebi, şef onayı) | E04-11 | YOK | P1 | S | TS-065 | D1-F | `s/bakim_formu.py`, `a/bakim.py`, `p/BakimPage.tsx` | kendi talebini onaylama 409; onayda `durum_degistir(IPTAL, kaynak='KAPSAM_DISI')`; iptal PB aynı cihaz-dönem için yeniden üretilmez |
| TS-067 | Uygunsuzluk aksiyonları ve bağlı arıza işi | E04-14 | YOK | P2 | M | TS-064, TS-023 | D1-F | `s/bakim_formu.py`, `a/bakim.py`, `p/BakimPage.tsx` | açık aksiyon varken PB TAMAMLANDI 409, BAKIM_UYGUNSUZLUK beklemesi; arıza işi `iliski_turu='BAKIM_BULGUSU'`; TEKLIF aksiyonu Dalga 2'de TS-147 ile açılır (Dalga 1'de pasif düğme) |
| TS-068 | PB yeniden açma ve form/kontrol kayıtlarında kullanıcı kimliği | E04-20 | KISMEN | P2 | M | TS-065 | D1-F | `s/bakim_formu.py` (kanca), `t/integration/test_bakim_formu.py` | `POST /isler/{id}/yeniden-ac` (`servis.kapat`, gerekçe); form TASLAK'a, `YENIDEN_ACMA` ziyaret satırı, dönem sayacı −1, yeniden tamamlanınca +1 |
| TS-069 | Bakım uyarıları, görev kartı, KVKK | E04-23 | KISMEN | P2 | S | TS-061 | D1-F | `s/bakim.py` (uyarı fonksiyonu), kanca kayıtları | geciken dönem, teyit bekleyen, bitişi yaklaşan, açık kapsam dışı (kendi talebi hariç); birim kapsamlı |

**Saha / zaman ve mobil teknisyen (E09)**

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-070 | Zaman kaydı servisi ve manuel kayıt | E09-01 | YOK | P1 | M | TS-018, TS-025 | D1-G | `s/zaman.py`, `a/servis_zaman.py`, `t/integration/test_servis_zaman_kayit.py` | çakışma yazmadan önce sorgulanır, "10:00-10:30 MOLA (SRV-…) ile çakışıyor" mesajı; EXCLUDE yarışta son savunma; geriye >2 gün `servis.planla`; başkası adına `servis.planla`; `sistem.kullanici` tek başına 403 |
| TS-071 | Tek dokunuş saha akışı ve sunucu zamanı | E09-02, E09-16 | YOK | P1 | M | TS-070, TS-021 | D1-G | `s/zaman.py`, `c/SayacDugmeleri.tsx`, `fa/servisZaman.ts` | Yola Çıktım → YOLA_CIKILDI, Sahaya Vardım → SAHADA (`kaynak='sayac'`); açık bölüm varken başlat 409 (açık mesaj); GECIS: kapat → flush → ekle; yanıtta `sunucu_zamani`, istemci ofseti |
| TS-072 | Sayaç düzeltmeleri: unuttum, 5 dk geri alma, uzun sayaç yönetici düzeltmesi | E09-07, E09-08, E09-06 | YOK | P1 | M | TS-071 | D1-G | `s/zaman.py`, `c/AktifSayacBandi.tsx`, `s/zaman.py` uyarı fonksiyonu | sahibi gerçek bitiş + gerekçe ile kapatır (KULLANICI_DUZELTMESI); 5 dk içinde geri alma iz bırakır; ≥10 saat ya da gün değişmiş sayaç uyarısı; worker asla otomatik kapatmaz |
| TS-073 | Sayaç–durum ve sayaç–atama kancaları | E09-10, E09-09 | YOK | P1 | S | TS-071, TS-025 | D1-G | `s/zaman.py` (`acik_sayac_dogrula`, `acik_sayac_cikarma_dogrula`) | açık sayaçlı işte TAMAMLANDI/IPTAL 409; kapalı işte sayaç başlatılamaz; açık sayaçlı kişiyi ekipten çıkarma 409 ("Ali Veli'nin SRV-… sayacını bitirin") |
| TS-074 | Sayacı sonraki işe taşıma | E09-03 | YOK | P2 | S | TS-071 | D1-G | `s/zaman.py` | hedef iş `SAYAC_ACILABILIR` ve kişiye atanmış; değilse 409 |
| TS-075 | İş zaman çizelgesi, `sure_ozeti` tek kaynak, null anlamı | E09-11, E09-D02, E09-13 | KISMEN | P1 | M | TS-070 | D1-G | `s/zaman.py` (`sure_ozeti_toplu`, `sure_eksik_ifadesi`), `t/unit/test_zaman_hesap.py` | Python ve SQL tanımı parametrik testle eşit; kayıt yoksa `kisi_saat_dk=None`, `sure_durumu=EKSIK`; `or 0`/`coalesce(...,0)` yasağı testle; MOLA kişi-saate girmez |
| TS-076 | Kapanışta "süre kaydı eksik" onayı | E09-12 | YOK | P2 | S | TS-075, TS-024 | D1-G | `s/zaman.py` (kanca), `p/ServisIsleriPage.tsx` içindeki onay penceresi (D1-C ile koordineli) | EKSIK/KISMI işte `sure_eksik_onay` yoksa 409 ("Süre kaydı eksik: Ali Veli. Onaylayarak kapatın."); NOT olayı |
| TS-077 | Benim İşlerim: tek mobil ekran (Bugün/Yarın, plan, kart, sayaç bandı) + kamera eki | E09-04, E09-D01, E02-14, E09-D05 | YOK | P1 | M | TS-071, TS-042 | D1-G | `s/mobil.py`, `a/servis_zaman.py` (`GET /benim-islerim`), `p/BenimIslerimPage.tsx`, `p/ServisIsKartiMobil.tsx`, `c/AktifSayacBandi.tsx`, `c/EkYukleyici.tsx` (`capture` prop, yalnız ekleme), `docs/KULLANIM-KILAVUZU.md` §10 | tek uç, tek sayfa (ayrı Ziyaretlerim yok); 279 px içerikte yatay kaydırma yok; menü izni `zaman.yaz`; çevrimdışı yok (bağlantı yoksa düğmeler kilitli) |
| TS-078 | "Bugünüm" özeti ve gün sonu eksik listesi | E09-05 | YOK | P2 | M | TS-075, TS-077 | D1-G | `s/mobil.py`, `p/BenimIslerimPage.tsx` | eksik listesi `sure_eksik_ifadesi` ile; yerel gün |

### 2.3 Dalga 2 — Diğer yeni modüller ve bağlantılar

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-080 | Şema iskeleti Dalga 2 (SLA, atölye, kiralama, parça, teklif/maliyet, eğitim, bağlar) | E05/E06/E07/E08/E10/E11 model bölümleri, E06-D03, E07-D05, E11-D03 | YOK | P1 | L | Dalga 1 bitti | D2-S | §4.2 "D2-S" | 7 migration head→base→head; canlı tablo değişiklikleri §1.12; makineler meta-testte; Dalga 2 dosya iskeletleri; altın kayıt yeşil |
| TS-081 | SLA politikası, işe damgalanan hedef, ilk müdahale, öncelik doğrulama, tek SLA modülü, PB dışı, yürürlük anı | E10-01, E10-10, E10-12, E10-13, E10-18, E10-D02, E09-D04, E10-03 (SLA kısmı) | YOK | P1 | L | TS-080 | D2-G | `s/sla.py`, `s/sla_takvim.py` (yalnız 7/24), `a/servis_operasyon.py`, `p/ServisTanimlarPage.tsx`, `c/SlaEtiketi.tsx`, `t/integration/test_servis_sla*.py`, `t/unit/test_on_yuz_sla_hesabi_yok.py` | kanca kayıtları §1.8; tohum KRITIK 12 / YUKSEK 24 / NORMAL 72 saat; `sla_baslangic_at=clock.now()`; `servis_sla_yururluk_at` boşken damga yok; durduran bekleme hedefi ileri alır; `sla_sonuc` ilk TAMAMLANDI'da donar; PB/ATOLYE SLA dışı (`ck_so_pb_sla`); öncelik/birim değişince yeniden damga; istemcide SLA hesabı yok (grep testi) |
| TS-082 | Operasyon Merkezi ve personel iş yükü | E10-08, E10-09 | YOK | P2 | M | TS-081, TS-035 | D2-G | `s/operasyon.py`, `a/servis_operasyon.py`, `p/OperasyonMerkeziPage.tsx` | sayaçlar `KPI_TANIMLARI` kaydından, liste `/isler?kpi=&siralama=sla`; toplu işlemler TS-025/TS-043 uçlarına bağlanır (yeni uç yok); çalışılan dk sütunu `servis_rapor.personel` ister |
| TS-083 | Kalıcı SLA bildirimi ve rozet | E10-05 | KISMEN | P2 | M | TS-081 | D2-G | `s/uyari_uretimi.py`, `worker.py` (`servis-sla-uyarilari`, `servis-uyari-temizligi`), `s/uyarilar.py` kaydı | rozet sayısı anlık hesap; `service_alerts` yalnız görüldü/tekillik için; kapsam `service_orders` JOIN; GERIYE_DONUK işte bildirim yok |
| TS-084 | Tekrar arıza işareti ve kök neden teyidi (KAPATILDI'da) | E10-04 | YOK | P2 | M | TS-081, TS-030 | D2-G | `s/tekrar_ariza.py` | 30 gün, `seri_norm`; PB ne tetikler ne tetiklenir; elle kurulan bağın üzerine yazmaz; kapsam dışı bağda maske |
| TS-085 | İş beklemesi / personel bekleme ayrımı; Benim İşlerim SLA bloğu | E10-17, E10-16 | YOK | P2 | S | TS-081, TS-077 | D2-G | `s/sla.py`, `s/mobil.py` (yanıta `sla` bloğu — D2-G bu dalgada sahibi) | ekran başlıkları ayrık; BEKLEME faaliyeti işi BEKLEMEDE yapmaz |
| TS-090 | Atölye çekirdeği: kabul (iş + kayıt tek transaction), ATOLYE makinesi, eşleme, olay, iptal yansıması, seri tek kaynak, yetim iş yok | E05-01, -12, -13, -14, -15, -16, -22, -D01, -D02, E14-14 | YOK | P1 | L | TS-080, TS-050 | D2-B | `s/atolye.py`, `a/atolye.py`, `p/AtolyePage.tsx`, `c/AtolyeKabulPenceresi.tsx`, `c/AtolyeDurumPenceresi.tsx`, `fa/atolye.ts`, `t/integration/test_atolye_durum.py`, `t/unit/test_atolye_esleme.py` | atölye durumları → servis işi ATOLYEDE/BEKLEMEDE; TESLIM_EDILDI → TAMAMLANDI (`kaynak='atolye'`, sonuç kanal ATOLYE); iptal/geri alma `servis.kapat`; ATOLYE kategorili işte genel durum/bekleme/yeniden açma uçları 409 + yönlendirme; bileşik FK `fk_atolye_servis_ekipman`; olaylar `ATOLYE` + `veri.alt_tur`; firma/seri değişikliği servis işi geçmişine; kabul zamanı istemciden alınmaz |
| TS-091 | Atölye atama, kapsam, yetki, kapanış kontrolleri | E05-11, E05-19, E05-26 | YOK | P1 | M | TS-090 | D2-B | `s/atolye.py`, `a/atolye.py`, `t/integration/test_atolye_kapsam.py` | atama E01 `atama.ata` (ATOLYE rolü `servis.planla` taşır); liste/tek kayıt/ek/uyarı/rapor/PDF E01 kapsam fonksiyonlarıyla; açık sayaçla teslim 409; KayitTipi `atolye` |
| TS-092 | Tamir bedeli gizliliği | E05-18 | YOK | P1 | S | TS-090 | D2-B | `a/atolye.py`, `s/atolye_rapor.py`, `t/integration/test_atolye_maliyet.py` | `maliyet.gor` yoksa `repair_amount` anahtarı yanıtta/Excel'de/PDF'te YOK; gönderilen tutar sessizce yok sayılır |
| TS-093 | Yapılandırılmış teşhis, onarım, test | E05-02 | YOK | P2 | M | TS-090 | D2-B | `s/atolye.py`, `p/AtolyePage.tsx` | `fault_reason_id` → `service_fault_reasons` (HABERLESME tohumları); KALDI testinden sonra teslim 409 |
| TS-094 | Ücretli onarımda müşteri onayı ve teklif bağı | E05-03 | YOK | P2 | M | TS-093, TS-147 | D2-B | `s/atolye.py`, `c/AtolyeDurumPenceresi.tsx` | bekleme MUSTERI_ONAYI (`beklet()`); bağlı teklif KABUL = onay; onaylayan adı olaya yazılmaz |
| TS-095 | Kabul fişi ve teslim tutanağı PDF | E05-04 | KISMEN | P2 | M | TS-096 | D2-B | `s/atolye.py` (bağlam), `templates/atolye_kabul_fisi.html`, `templates/atolye_teslim_tutanagi.html` | fiyatsız (maliyet.gor yoksa); imzalı tarama IMZA eki |
| TS-096 | Satır bazlı aksesuar ve teslimde karşılaştırma | E05-05 | YOK | P2 | M | TS-090 | D2-B | `s/atolye.py`, `c/AtolyeKabulPenceresi.tsx` | DIGER açıklama zorunlu; teslimde eksik aksesuar uyarısı |
| TS-097 | Seri geçmişi, açık kayıt engeli, tekrar geliş, garanti durumu | E05-06, E05-07 | KISMEN | P2 | M | TS-090, TS-054 | D2-B | `s/atolye.py` | eşleşme tip+marka+serial_key; çoklu aktif eşleşme 409 + aday listesi; `uq_atolye_acik_ekipman`; garanti kabulde dondurulur (BELIRSIZ/ONARIM_GARANTISI kuralları) |
| TS-098 | Atölye listesi, yaşlandırma, KPI kutuları, teslim/kargo kuralları, sunucu doğrulaması | E05-08, E05-10, E05-20, E05-21 | KISMEN | P2 | M | TS-091 | D2-B | `s/atolye_rapor.py`, `a/atolye.py`, `p/AtolyePage.tsx` | KPI sayı = liste; kargo/teslim CHECK'leri; iyimser kilit 409; marka karşılaştırması büyük/küçük harf duyarsız |
| TS-099 | Atölye detayında parça ve süre görünümü | E05-17 | KISMEN | P2 | M | TS-133, TS-075 | D2-B | `a/atolye.py`, `p/AtolyePage.tsx` | salt okunur; parça TS-133 bileşeni gömülü; süre `sure_ozeti` |
| TS-100 | Toplu kabul (kabul grubu) ve toplu atama | E05-25 | YOK | P2 | M | TS-097 | D2-B | `s/atolye.py`, `c/AtolyeKabulPenceresi.tsx` | her cihaz ayrı kayıt + ortak grup no + tek fiş |
| TS-101 | Atölye kişisel verilerinin KVKK kapsamı | E05-D03 | KISMEN | P2 | S | TS-090 | D2-B | `s/atolye.py` (KVKK kancası), `t/integration/test_atolye_kvkk.py` | anonimleştirme `delivered_to_name`, `approved_by_name` temizler |
| TS-102 | Kiralık cihaz → atölye köprüsü ve envanterden çıkış (HURDA) | E05-27, E06-D02 | YOK | P2 | S | TS-090, TS-115 | D2-C (kiralama tarafı), D2-B (atölye kancası) | `s/kiralik_envanter.py`, `s/atolye.py` (yalnız `teslim_edildi` kancası kaydı) | ARIZALI dönüş kontrolünden KIRALAMA_TAKIP atölye kaydı; teslimde ATOLYEDE → (depo, KONTROLDE); HURDA çıkışı gerekçeli hareket |
| TS-110 | Kiralama çekirdeği: başlık, kalem, irtibat, müşteri = hesap, kiralama depoları, birim tutarlılığı | E06-02, E06-15, E06-D03, E06-D04 | YOK | P1 | M | TS-080 | D2-C | `s/kiralama.py`, `a/kiralamalar.py`, `fa/kiralama.ts`, `t/integration/test_kiralama_akis.py` | E06-02/15 revised; mobilite deposuyla kiralama 400; müşteri `is_musteri` 400; `lokasyon_dogrula`; aktif tahsis varken müşteri değişikliği 409; ek olmayan kayda 404 |
| TS-111 | Kiralık envanter, ekleme-yalnız hareket defteri, depo ayrımı, IMEI ürün dışlama | E06-03, E06-18, E06-D01, E06-D05 | KISMEN | P1 | M | TS-110, TS-131 | D2-C | `s/kiralik_envanter.py`, `a/kiralamalar.py`, `t/integration/test_kiralik_envanter.py`, `t/integration/test_kiralama_depo_ayrimi.py` | tek yazıcı `hareket_yaz()`; eşzamanlı iki toplu transfer bakiyeyi eksiye düşürmez; PATCH'te durum/depo/ürün/birim 400; IMEI ürün ve MOBILITE/ARAC_TAKIP birimi 400 |
| TS-112 | Adet bazlı kısmi tahsis, sevk sonrası ek tahsis | E06-04 | YOK | P1 | M | TS-111 | D2-C | `s/kiralama_tahsis.py`, `t/integration/test_kiralama_tahsis.py` | 20+30 tahsis, 51. adet 409; gather ile iki eşzamanlı 30'luktan biri 409; `ex_rtahsis_cihaz_cakisma` |
| TS-113 | KIRALAMA makinesi, sevk şartı, cihaz bazlı kısmi sevk ve iade | E06-05, E06-06, E06-07 | YOK | P1 | L | TS-112 | D2-C | `s/kiralama.py`, `s/kiralama_tahsis.py`, `a/kiralamalar.py` | PUT status kabul etmez; kurulumlu kiralamada son iade önce TOPLANDI ister 409; kapanış için sevk = iade + kayıp; 3+1 KONTROLDE, 1 KAYIP, 5 hareket senaryosu |
| TS-114 | Son aşamayı gerekçeyle geri alma; iptalde tahsis çözme | E06-08, E06-14 | YOK | P2 | S | TS-113 | D2-C | `s/kiralama.py` | KAPANDI/IPTAL geri alınamaz 409; son hareket değilse 409; iptal gerekçesi zorunlu |
| TS-115 | Dönüş kontrol kaydı | E06-11 | YOK | P2 | M | TS-111 | D2-C | `s/kiralik_envanter.py`, `p/KiralikEnvanterPage.tsx` | UYGUN dışında açıklama zorunlu; HAZIR yalnız giriş/kontrol uçlarıyla |
| TS-116 | Tarih bazlı müsaitlik ve rezervasyon, bitiş uzatma | E06-12 | YOK | P2 | M | TS-113 | D2-C | `s/kiralama_tahsis.py`, `t/integration/test_kiralama_musaitlik.py` | 1-5 / 10-12 Kasım örneği; iki kalemli iki kiralama eşzamanlı planlanınca deadlock yok |
| TS-117 | Teslim/iade tutanağı (fiyatsız PDF, TASLAK filigranı) | E06-13 | KISMEN | P2 | S | TS-112 | D2-C | `s/kiralama.py` (bağlam), `templates/kiralama_tutanak.html` | imzalı tutanak IMZA eki; fiyat yok |
| TS-118 | Kiralama kataloğu ve seri takibi koruması | E06-16 | KISMEN | P2 | S | TS-110 | D2-C (+ D2-D `a/catalog.py` satırı) | `a/kiralamalar.py`, `a/catalog.py` | IMEI ürün 400; envanterli üründe identity_kind değişikliği 409 |
| TS-119 | Kiralama uyarıları | E06-17 | KISMEN | P2 | S | TS-112, TS-116 | D2-C | `s/kiralama_raporlar.py` (uyarı fonksiyonu) | geciken iade, eksik tahsis (`/kiralamalar?kpi=eksik_tahsis`), uzun kontrol, müsaitlik açığı; birim kapsamlı |
| TS-120 | Kurulum/toplama işlerinin servis işine bağlanması | E06-19 | YOK | P2 | L | TS-113, TS-043 | D2-C | `s/kiralama.py` (kanca), `a/kiralamalar.py`, `p/KiralamalarPage.tsx`, `t/integration/test_kiralama_servis_isi.py` | `POST /{id}/servis-isi {tur}` (`kiralama.yaz + servis.yaz`); `uq_so_kiralama_tur_acik`; ekip aktif plandan, süre `sure_ozeti`; TAMAMLANDI'da aşama önerisi, onay `kiralama.asama`; `work_orders`'a yazım yok |
| TS-121 | Toplu kiralık envanter girişi (önizlemeli) | E06-22 (a) | KISMEN | P2 | M | TS-111 | D2-C | `s/kiralik_envanter.py`, `a/kiralamalar.py` | önizleme yazmaz; onayda sha256 eşleşmezse 409; mükerrer seri reddi |
| TS-122 | Kiralamalar ve Kiralık Envanter sayfaları | E06-23 | KISMEN | P2 | M | TS-110…TS-116 | D2-C | `p/KiralamalarPage.tsx`, `p/KiralikEnvanterPage.tsx` | KpiKutusu + MusteriLokasyonSecici; depo seçici yalnız `kiralama_deposu=true` |
| TS-130 | Tek stok yazıcısı, hareket türü, defter değişmezliği, maliyet kolonu | E11-01, E11-22, E11-D03 | KISMEN | P1 | M | TS-080 | D2-D | `s/parca.py`, `t/unit/test_parca_tur_kurali.py` | ürünler id sıralı FOR UPDATE; tür→(reason, işaret) CHECK; tetikleyici UPDATE/DELETE reddi; `unit_cost` hareketli ağırlıklı ortalama, yoksa NULL (0 yazılmaz); yazma `parca.yonet`, görme `maliyet.gor` |
| TS-131 | Servis depoları, birim kapsamı, teknisyen araç deposu, mobilite uçlarına sızma önlemi | E11-23, E11-D01, E06-D01 | KISMEN | P1 | S | TS-130 | D2-D | `a/stock.py`, `sv/stock.py`, `a/catalog.py`, `schemas/catalog.py`, `s/parca.py`, `t/integration/test_yedek_parca_kapsam.py` | canlı `POST /api/stok/hareket` servis/kiralama deposuna 409; `/api/stok/hareketler` servis satırı içermez; `/api/stok/depolar` yalnız mobilite depoları; teknisyen depo kümesi = birim depoları + kendi araç deposu; depo tanımı `sistem.ayar` |
| TS-132 | Kapalı işe çıkış engeli; iade ve ters kayıt | E11-02, E11-03, E11-06 | YOK | P1 | M | TS-130 | D2-D | `s/parca.py`, `a/yedek_parca.py` | kapalı işe çıkış 409 (iş satırı `with_for_update(read=True)`); iade ≤ net çıkış; kapalı işte IADE ters kaydı 409; sayım ters kaydı yasak; sabit tohumlu rastgele dizi testi |
| TS-133 | Servis işinde Kullanılan Parçalar; teknisyen çıkışı; PB formu ve atölyeye gömülü bileşen | E11-04, E11-14, E04-21 | YOK | P1 | L | TS-132 | D2-D | `a/yedek_parca.py`, `c/ServisParcalari.tsx`, `fa/yedekParca.ts` | PARCA olayı; maliyet anahtarı yalnız `sees_cost`; PB formunda ve atölyede aynı bileşen; `maintenance_part_reports` açılmaz |
| TS-134 | Açılış stoğu yükleme | E11-07 | KISMEN | P1 | M | TS-130 | D2-D | `sv/imports/parca_acilis.py`, `a/yedek_parca.py` | hepsi-ya-hiç; kullanıcı depo kapsamı kontrolü; (parça, depo) için önceki hareket varsa red + `uq_stok_hareket_acilis` |
| TS-135 | Parça kartı stok alanları, az stok tek fonksiyon, ondalık reddi, düşük stok uyarısı | E11-12, E11-10, E11-11, E11-08 | KISMEN | P2 | M | TS-130 | D2-D | `a/yedek_parca.py` (`POST /kartlar`), `s/parca.py`, uyarı fonksiyonu | kart AKSESUAR/identity YOK/fiyatsız; kod tekrarı 409; tam sayı birimde ondalık 400; uyarı `parca.yonet` sahiplerine, birim kapsamlı |
| TS-136 | Yedek Parça ekranı, giriş belge no, hareket geçmişi (filtre, sayfa, Excel) | E11-09, E11-13, E11-15 | KISMEN | P2 | M | TS-133 | D2-D | `p/YedekParcaPage.tsx`, `c/ParcaHareketPenceresi.tsx`, `a/yedek_parca.py` | not ≤300; belge ILIKE arama; Excel `parca.gor + servis_rapor.disaaktar` |
| TS-137 | Depolar arası transfer ve onaylı stok sayımı | E11-16, E11-17 | KISMEN | P2 | M | TS-130 | D2-D | `s/parca.py`, `a/yedek_parca.py` | transfer çifti `transfer_grup`; sayım anlık görüntü + onay anı farkı; onaysız fark hiçbir şey değiştirmez |
| TS-138 | Parça talebi ve MALZEME beklemesi | E11-19 | YOK | P2 | M | TS-133, TS-023 | D2-D | `s/parca.py` (kanca), `a/yedek_parca.py` | iş kapanınca talep IPTAL; "parça geldi" hesaplanan uyarı; KARSILANDI yalnız talepten sonraki çıkışlarla |
| TS-140 | Teklif kapsamı ve birimi, sayfalama, indeks; sunucu doğrulaması ve yuvarlama | E07-02, E07-19, E07-03 | KISMEN | P1 | M | TS-080 | D2-E | `sv/quotes.py`, `a/quotes.py`, `a/attachments.py` (teklif dalı yok — dokunulmaz), `a/orders.py`, `p/TekliflerPage.tsx`, `t/integration/test_servis_teklif_kapsam.py` | `teklif_kapsami` bilinmeyeni reddeder; birimli teklife yalnız servis rolü/birim üyesi, birimsize servis dışı rol yazar, aksi 404; 500 karakter yalnız birimli kalem; satış testleri yeşil |
| TS-141 | İç onay, TEKLIF makinesi, durum geçmişi, yalnız güncel sürüme karar | E07-04, E07-D01 | KISMEN | P1 | M | TS-140 | D2-E | `sv/quotes.py`, `a/quotes.py`, `a/public_quotes.py`, `t/integration/test_servis_teklif_akisi.py` | E07-04 revised makinesi; öz-onay yasağı; birimli teklifte iskonto-onayla 409; public link ve elle karar yalnız güncel ve karar verilebilir sürümde; satış uçları değişmez |
| TS-142 | Elle gönderildi, yeniden gönderim, ≤3 alıcı, gönderene CC, genel hata mesajı | E07-05, E07-06 | KISMEN | P1 | S | TS-141 | D2-E | `a/quotes.py`, `sv/mail.py` (`_smtp_gonder`), `t/integration/test_servis_teklif_gonderim.py` | kanal + not zorunlu; `quote_sends` günlüğü; SMTP ayrıntısı yalnız log'da (hak ediş e-postası da korunur) |
| TS-143 | Teklif PDF: tüm kalemler, çok sayfa, Türkçe, satır sarma, Sayfa x/y; kurumsal alanlar | E07-07, E07-08 | KISMEN | P1 | M | TS-141 | D2-E | `templates/teklif.html`, `a/quotes.py`, `pyproject.toml` (dev: pypdf) | pypdf ile sayfa ve metin testi; satış PDF alt boşluk değişikliği sürüm notunda |
| TS-144 | Satış panel/rapor/listesinin birimli tekliflerden ayrılması; servis teklifi siparişe dönüşmez | E07-D02, E07 K17 | YOK | P1 | S | TS-140 | D2-E | `sv/reports.py`, `a/reports.py`, `a/quotes.py`, `a/orders.py`, `t/integration/test_raporlar.py` | satış dashboard/rapor `birim IS NULL`; mevcut rapor testleri aynı sayıları verir; birimli teklif sipariş 409 |
| TS-145 | İş geliri ve diğer maliyet kaydı, gelir yok/ücretsiz ayrımı, geçmiş, fatura sonrası kilit | E07-12, E07-17, E07-D04 | YOK | P1 | S | TS-080 | D2-E | `s/maliyet.py`, `a/servis_maliyet.py`, `t/integration/test_servis_maliyet.py` | `maliyet.yaz`; NULL ≠ 0; ÜCRETSİZ_GARANTİ gelir 0 zorunlu; `log_change`; `fatura_iletildi_at` sonrası 409 |
| TS-146 | Maliyet hesabı: eksik veri ayrımı, işçilik tarifesi | E07-10, E07-11, E07-20 | YOK | P1 | M | TS-145, TS-075, TS-130 | D2-E | `s/maliyet.py`, `a/servis_maliyet.py` | yalnız tam işler toplama girer; SURE_EKSIK/MALIYET_EKSIK/TARIFE_EKSIK durumları; tarife `ex_iscilik_tarife_cakisma`; geriye dönük tarife `sistem.ayar`+gerekçe; birim kapsamlı tarife eksik uyarısı |
| TS-147 | Teklif–servis işi bağı, TEKLIF beklemesi, "teklif sunulacak" uyarısı, kabul gelirinin aktarımı, PB bulgu teklifi, Faz B adres bağları | E07-14, E07-15, E07-16, E04-14 (teklif), E14-15 | YOK | P2 | M | TS-141, TS-145, TS-023 | D2-E | `sv/quotes.py`, `s/maliyet.py`, `a/quotes.py` (kısayol), `p/TeklifFormu.tsx` | servis işinden açılan teklifte müşteri/adres sunucuda kopyalanır; aktif TEKLIF beklemesine `quote_id`; kabulde yalnız eşleşen bekleme kapanır; KDV hariç net TL gelire; PB bulgusu kabulünde DEVAM ilişkili düzeltici iş; public kabulde audit `user_id=None` |
| TS-148 | Taslak teklif düzenleme (PUT) ve teklif listesi filtre/KPI/Excel | E07-13, E07-18 | KISMEN | P2 | M | TS-141 | D2-E | `a/quotes.py`, `p/TeklifFormu.tsx`, `p/TekliflerPage.tsx` | PUT başlığı da yazar (sürüm artar); KPI sayı = liste; 3 gün takip uyarısı |
| TS-149 | Servis maliyet analizi ekranı | E07-21 | YOK | P2 | M | TS-146 | D2-E | `s/maliyet.py`, `a/servis_maliyet.py`, `p/ServisMaliyetPage.tsx` | dönem/birim/tür/müşteri filtresi; birim × tür özeti; menü `maliyet.gor` (+ `servis_rapor.gor`) |
| TS-150 | Eğitim çekirdeği: katalog, toplu yıllık plan, oturum/katılım, kişi kartı, plan.xlsx; yetkinlik değerlendirme geçmişi | E08-02, E08-03, E08-18 | YOK | P1 | L | TS-080, TS-003 | D2-F | `s/egitim.py`, `s/egitim_yetkinlik.py`, `a/egitim.py`, `p/EgitimPage.tsx`, `p/EgitimKisiKarti.tsx`, `fa/egitim.ts`, `t/integration/test_egitim_cekirdek.py` | E08-02/03 revised; iptal plandan sonra aynı kişi+kurs+yıl yeni plan; pasif kursa plan/oturum 400; kişi listesi `kapsam_personel`; plan.xlsx denetime |
| TS-151 | Plan tamamlama kuralları ve gözlem sonucunun sunucuda hesaplanması | E08-04, E08-05 | YOK | P1 | S | TS-150 | D2-F | `s/egitim.py`, `s/egitim_gozlem.py`, `t/unit/test_egitim_sonuc.py` | ileri tarihli oturum reddi; en eski açık plan tamamlanır; katılmadı düzeltmesi planı geri açar; sonuç sırası KRITIK → EKSIK_GOZLEM → BASARILI (≥85) → GELISIM_GEREKLI |
| TS-152 | Düzeltme/iptal (gözlem, plan, kurs, kriter, oturum) | E08-06 | YOK | P1 | M | TS-151 | D2-F | `s/egitim.py`, `s/egitim_gozlem.py` | katılımlı oturum silme 409; iptal KPI'dan düşer; audit |
| TS-153 | Eğitim Yönetim Özeti (tıklanabilir KPI) | E08-23 | KISMEN | P1 | M | TS-151 | D2-F | `s/egitim_rapor.py` (`KPI_TANIMLARI`), `p/EgitimPage.tsx` | KpiKutusu; sayı = liste; henüz gelmemiş kutu gösterilmez ('0' değil) |
| TS-154 | Kişisel performans detayının `egitim.detay`'a bağlanması ve Excel denetimi | E08-20, E08-D04 | KISMEN | P2 | S | TS-150 | D2-F | `a/egitim.py`, `s/ek_kapsam.py` (eğitim dalları) | iki katmanlı şema; kart açılışı `erisim_kaydet`; her xlsx denetime |
| TS-155 | Kritik İSG uygunsuzluğu için düzeltici faaliyet | E08-07 | YOK | P2 | M | TS-151 | D2-F | `s/egitim_gozlem.py`, `a/egitim.py` | gözlem başına tek; otomatik kapanış kritik maddeleri 2 olan sonraki gözlemle; KayitTipi kişisel alan içermez |
| TS-156 | Gözlemi servis işinden başlatma; kapsam/aktiflik; gözlemci kimliği; tarih/aşama doğrulaması | E08-08, E08-19, E08-17, E08-15 | YOK | P2 | M | TS-151, TS-027 | D2-F | `s/egitim_gozlem.py`, `c/GozlemFormu.tsx`, `p/ServisIsleriPage.tsx` (yalnız düğme — D2-F'ye bu dalgada devredilir) | kapsam dışı servis işi 404; öz-değerlendirme 409; birim anlık görüntüsü işten |
| TS-157 | Gelişim Kartım ve "Gördüm" onayı | E08-09 | YOK | P2 | M | TS-154 | D2-F | `p/GelisimKartimPage.tsx`, `a/egitim.py` | kendi eki 200, başkasınınki 404; onay geri alınamaz, denetime |
| TS-158 | Toplu katılım girişi | E08-10 | YOK | P2 | S | TS-151 | D2-F | `c/KatilimTablosu.tsx`, `a/egitim.py` | puan 120 → 422 (loc indeksi); kapsam dışı kişi → 400 `satir`; ilk hatada 0 satır |
| TS-159 | Belge geçerlilik, 30/60/90 takibi, uyarı birim süzmesi | E08-11, E08-13, E08-14 | YOK | P2 | M | TS-151 | D2-F | `s/egitim_rapor.py` (`gecerlilik_sorgusu`, `takip_sorgusu`) | üç tüketicide sayı = liste; girişsiz personel uyarıya dahil, ayrılan değil; birimsiz şefte 0 |
| TS-160 | Yetkinlik kataloğu yönetimi | E08-16 (P2 kısmı) | YOK | P2 | M | TS-150 | D2-F | `s/egitim_yetkinlik.py`, `a/egitim.py` | başka birim yetkinliği 403 |
| TS-165 | İşten çıkış akışı, eğitim kayıtlarına etkisi, personel KVKK | E13-09, E08-D02, E13-D03 | YOK | P2 | M | TS-008, TS-073, TS-155 | D2-H | `s/personel.py`, `a/personel.py`, `p/PersonelPage.tsx`, `t/integration/test_personel_cikis.py`, `t/integration/test_personel_kvkk.py` | önizleme + tek transaction; açık sayaç kapatılmaz (uyarı + görev kartı); atamalardan çıkarma `ekip_degisiyor` kuralına uyar; sorumlusuz düzeltici faaliyet uyarısı; ayrılan personel anonimleştirilebilir |
| TS-170 | Eski ad bazlı kayıtların onaylı personel eşlemesi | E13-08 | YOK | P1 | M | TS-010 | D2-I | `s/ad_esleme.py`, `sv/imports/ad_esleme.py`, `deploy/KURULUM.md` (göç bölümü) | öneri Excel'i → İK onayı → `ad_esleme` profili; trgm yalnız öneri; idempotent |
| TS-171 | Serbest metinden müşteri/lokasyon eşleştirmesi Faz 1 (sözleşme + Güvenlik ekipmanı) | E14-09 | KISMEN | P1 | L | TS-014, TS-015, TS-017 | D2-I | `sv/imports/musteri_eslestirme.py`, `s/veri_kalitesi.py`, `p/ServisAnaVeriPage.tsx` | `hesap.birlestir`; aday listesi Excel; onaylı satır takma ad üretir; belirsiz 409 insana döner |
| TS-172 | Ekipman kütüğü göçü (idempotent) | E03-04, E03-10 | KISMEN | P1 | M | TS-050, TS-171 | D2-I | `mg/kaynak_kutuk.py`, `mg/hazirla_kutuk.py`, `mg/yukle_kutuk.py`, `Makefile`, `t/migration/test_kutuk_gocu.py` | `ON CONFLICT DO NOTHING (uq_svceq_kaynak)`; teslim tarihi metinden DATE; mükerrerler aktif kalır, veri kalitesine düşer |
| TS-173 | Bakım sözleşmesi göçü, teyit listesi, ekrandan düzenleneni ezmeme, içe/dışa aktarma güvenliği | E04-03, E04-04, E04-D03 | KISMEN | P1 | M | TS-060, TS-171 | D2-I | `mg/bakim_sozlesme.py`, `sv/imports/bakim_sozlesme.py`, `t/integration/test_bakim_goc.py` | TEYIT_BEKLIYOR dışı kayıt "korundu"; adet 11→8 düzeltmesinde 3 satır `valid_to` alır; ücret kolonları yalnız `sees_cost`; birden çok müşteri adayı karantina |
| TS-174 | Servis işi göçü (POC durum → çözüm kanalı eşlemesi, olay, sonuç, seri, eski numara) | E01-06 (göç), E01 K2, E01 K16 | YOK | P1 | L | TS-024, TS-170, TS-171, TS-172 | D2-I | `mg/servis_goc.py`, `sv/imports/servis_isleri.py`, `t/migration/test_servis_gocu.py` | eşlenemeyen POC durumları raporlanır; eski numara korunur; `customer_id` yoksa `customer_name_raw`; tekrar koşunca 0 yeni |
| TS-175 | Plan göçü (WorkOrderPlans/TPL → visits/plans/members) | E02-D04 | YOK | P2 | M | TS-174, TS-048 | D2-I | `mg/servis_plan.py`, `t/integration/test_goc_servis_plan.py` | kapalıyken planlanmış/çift aktif plan düzeltilmez, raporlanır |
| TS-176 | Zaman kaydı göçü | E09 K21 | YOK | P2 | M | TS-174, TS-170 | D2-I | `mg/servis_zaman.py` | eşleşmeyen ad `user_id NULL + kaynak_personel_adi`; çakışan GOC_CAKISMA olarak saklanır; satır atılmaz |
| TS-177 | Göç uzlaşma raporu ve birim bazlı geçiş provası | §5 | YOK | P1 | S | TS-172…TS-176 | D2-I | `mg/servis_uzlasma.py`, `Makefile` (`goc-servis-onizleme`, `goc-servis-uygula`, `goc-servis-rapor`) | kaynak sayısı = aktarılan + karantina + reddedilen, tablo bazında; canlı kopyada prova, altın kayıt yeşil |

### 2.4 Dalga 3 — Raporlar, KPI ve eksikler

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-180 | Şema Dalga 3 (kiralama sayımı, bildirim/e-posta tabloları, koşullu mesai takvimi, eğitim yetkinlik eşlemesi) | E06-22b, E10-02, E10-06, E08-16/22 | YOK | P1 | S | Dalga 2 bitti | D3-S | §4.3 | head→base→head |
| TS-181 | Sunucu tarafı tek rapor/KPI motoru, `/ozet`, parametre doğrulama, SQL'de toplama | E12-08, E12-10, E12-D04 | KISMEN | P2 | L | TS-035 | D3-A | `s/rapor_tanimlari.py`, `s/rapor_motoru.py`, `a/servis_raporlari.py`, `p/ServisRaporlariPage.tsx`, `c/RaporFiltresi.tsx`, `fa/servisRaporlari.ts` | E01-14 KPI kaydını genişletir; katalog dışı parametre 422, tarih sırası/24 ay 400, yetkisiz birim 403; KPI = `/isler?kpi=` sayısı; ham süre toptan gönderilmez |
| TS-182 | `servis_rapor.personel` uygulaması ve dışa aktarım denetim kaydı | E12-09, E09-D03 | KISMEN | P2 | M | TS-181 | D3-A | `a/servis_raporlari.py`, `s/rapor_excel.py`, `t/integration/test_servis_rapor_rbac.py` | kişi kırılımı/ham süre/iletişim kolonları izinsizde anahtar olarak yok; Excel denetimi filtreler ISO, kişisel sayfa `is_personal_data=True` |
| TS-183 | Hesap doğruluğu, altın KPI veri seti, çapraz testler | E12-03, E12-04, E12-05, E12-07, E12-D03 | KISMEN | P1 | M | TS-181 | D3-A | `t/fixtures/servis_rapor_seed.py`, `t/fixtures/servis_rapor_beklenen.json`, `t/integration/test_servis_rapor_altin.py`, `t/integration/test_servis_rapor_hesap.py` | DB adı `_test` ile bitmiyorsa seed çalışmaz; sıfırlı/19 haneli seri, süresiz çözülmüş, yeniden açılmış, AKYAKA 17 cihaz PB, atölye iptali senaryoları; beklenen tablo eşit |
| TS-184 | Eksik kırılımlar ve rapor boyutu (şef, müşteri, tesis, şehir, öncelik, çözüm kanalı) | E12-11, E14-18 (boyut) | YOK | P2 | M | TS-181 | D3-A | `s/rapor_motoru.py` | müşteri/şehir `lokasyon_anahtari`+`il_normalize`; teknisyen boyutu `servis_rapor.personel`; "Eşleştirilmemiş: metin" satırı |
| TS-185 | Planlı bakım tamamlama raporu ve bakım KPI adım 1–2 | E12-12, E04-18, E04-19 | KISMEN | P2 | M | TS-181 | D3-E | `s/bakim_raporlari.py` (`donem_tamamlama` tek fonksiyon), `a/bakim.py`, `p/BakimPage.tsx` | KPI'lar motor kaydında; "bakım yapıldı, aksiyon açık" kutusu; para alanı yok; `bakim.gor` yoksa 403 |
| TS-186 | SLA ve bekleme raporu | E12-13, E10-07 | KISMEN | P2 | M | TS-181, TS-081 | D3-A | `s/rapor_hesap.py` (E10 `sla_raporu()` çağrısı), `a/servis_raporlari.py` | yalnız GUNLUK_SERVIS; OLCULEMEDI paydada yok, ayrı satır; CSV açılmaz |
| TS-187 | Tekrar arıza/ziyaret ve yeniden açılan iş göstergesi | E12-14, E12-15 | YOK | P2 | M | TS-084, TS-181 | D3-A | `s/rapor_hesap.py` | onaylı oran = teyit AYNI_ARIZA; aday ayrı etiket; tekrar ziyaret = SAHA faaliyetli ≥2 yerel gün |
| TS-188 | Veri Kalitesi sayfası (servis + ana veri KPI + ekipman listeleri) | E12-16, E14-18, E03-13 (listeler) | KISMEN | P2 | M | TS-181, TS-171 | D3-C | `s/rapor_kalite.py`, `s/veri_kalitesi.py`, `p/ServisAnaVeriPage.tsx` | salt okuma; sayı = liste; tanımsız göç karantinasından |
| TS-189 | Saha / Zaman Takibi yönetim ekranı ve veri disiplini sütunları | E09-14, E09-15 | YOK | P2 | M | TS-075, TS-181 | D3-B | `s/rapor_hesap.py` (kişi-saat ortak), `p/ZamanTakibiPage.tsx` | KpiKutusu; kişi sütunları `servis_rapor.personel`; Excel "Personel" sayfası aynı izin |
| TS-190 | Planlama P3: müsaitlik blokları, kaynak görünümü, plan uyumu, kapanmış iş soluk, bölge önerisi, eğitim oturumu blokları | E02-20, E02-21, E02-22, E02-23, E02-16 (öneri), E08-D03 | YOK | P3 | L | TS-045, TS-150 | D3-B | `s/planlama.py`, `s/takvim.py`, `s/cakisma.py`, `p/ServisPlanlamaPage.tsx` | müsaitlik notu ≤200 ve sağlık uyarısı; aynı kilitle yazılır; plan uyumu = aynı İstanbul günü |
| TS-191 | Ekipman birleştirme, saha farkının kütüğe dönüşü, analitik KPI | E03-13, E03-14, E03-15 | KISMEN | P2 | M | TS-064, TS-097 | D3-C | `s/ekipman.py`, `a/servis_ekipman.py`, `p/ServisEkipmanPage.tsx` | açık sözleşme kalemi/iş/atölye varken birleştirme 409 + liste; otomatik bağlama yalnız aynı müşteri+birim+TEK eşleşme |
| TS-192 | Müşteri kartında Lokasyonlar/Servis sekmeleri, hesap/lokasyon birleştirme, kapsam bilgisi, sözleşme mükerrer listesi | E14-07, E14-12, E14-17, E14-11 (liste) | KISMEN | P2 | M | TS-171 | D3-C | `sv/hesap_birlestir.py`, `s/ana_veri.py`, `a/teknik_servis_ana_veri.py`, `c/BirlestirmePenceresi.tsx`, `p/HesaplarPage.tsx` | canlı `/kart` değişmez (ayrı uç); hak ediş referanslı hesapta 409; önizleme çakışmaları gösterir; kapsam anlık görüntüsü değişmez |
| TS-193 | Seri → mobilite cihaz kütüğü bağı ve cihaz kartında servis sekmesi | E01-10 | KISMEN | P3 | S | TS-020 | D3-C | `s/is_emirleri.py` (yalnız okuma fonksiyonu — D3-C'ye devredilir), `p/CihazlarPage.tsx` | MOBILITE/ARAC_TAKIP'te IMEI/seri eşleşmesi; `devices`'a yazım yok |
| TS-194 | Atölye KPI raporları, dış servis takibi, atölye uyarıları | E05-09, E05-24, E05-28 | KISMEN | P3 | M | TS-098 | D3-D | `s/atolye_rapor.py`, `s/atolye.py`, `a/atolye.py` | çevrim süresi `completed_at - received_at`; dış servis RMA köprüsü yok; teslim alınmayan 30 gün uyarısı |
| TS-195 | Kiralama raporları, saha cihaz değişimi, depo sayımı | E06-21, E06-20, E06-22 (b) | KISMEN | P3 | M | TS-113 | D3-D | `s/kiralama_raporlar.py`, `a/kiralamalar.py`, `p/KiralikEnvanterPage.tsx` | raporlar `a/servis_raporlari.py` altında değil, kiralama router'ında (`servis_rapor.gor + kiralama.gor`); mevcut `a/reports.py`'ye dokunulmaz |
| TS-196 | Parça tüketim raporu ve satın alma mal kabulünden serisiz parça girişi | E11-18, E11-D02 | YOK | P2 | M | TS-133 | D3-D | `s/parca.py`, `sv/purchasing.py`, `a/purchasing.py`, `t/integration/test_satinalma*.py` | net çıkış = −Σqty; E07 malzeme maliyeti aynı fonksiyon; mal kabul maliyet dondurur; satın alma testleri yeşil |
| TS-197 | Maliyet Excel, fatura devri işareti, teklif dönüşüm raporu | E07-22, E07-26, E07-24 | YOK | P3 | S | TS-149 | D3-E | `a/servis_maliyet.py`, `p/FaturaDevriPage.tsx`, `sv/reports.py` (dönüşüm, varsayılan `birim IS NULL`) | işaret `tahsilat.yaz`; işaret sonrası gelir kilidi |
| TS-198 | Eğitim etkinlik raporu, kurs↔yetkinlik bağı, atamada yetkinlik uyarısı | E08-12, E08-16 (P3), E08-22 | KISMEN | P2 | M | TS-159, TS-181 | D3-E | `s/egitim_rapor.py`, `s/egitim_yetkinlik.py`, `s/rapor_excel.py` (çağrı) | Excel tek yardımcıyla; not/aksiyon kolonu yalnız `egitim.detay`; atama engellenmez, uyarı |
| TS-199 | "Ekibim" süzgeci ve mobilite BAKIM ad ayrımı | E13-17, E04-D05 | YOK | P3 | S | TS-008 | D3-F | `s/personel.py`, `p/PersonelPage.tsx`, `c/AppLayout.tsx` (etiket), `docs/KULLANIM-KILAVUZU.md` | Ekibim yetki genişletmez; "Planlı Bakım" ile mobilite "Bakım" iş emri ekranda ve raporda ayrışır |
| TS-200 | Mesai takvimi (koşullu) ve e-posta bildirimi | E10-02, E10-06 | KISMEN | P3 | M | TS-081 | D3-F | `s/sla_takvim.py`, `s/eposta.py`, `sv/mail.py` (yardımcı), `worker.py` (`servis-eposta`) | mesai tabloları yalnız bir politika MESAI'ye çekilince kullanılır; outbox saklama + KVKK; GERIYE_DONUK işe e-posta yok |
| TS-201 | Önceki dönem karşılaştırması, 12 aylık trend, native pivot şablonu | E12-18, E12-17 | YOK | P3 | M | TS-181 | D3-A | `s/rapor_motoru.py`, `templates/excel/servis_pivot_sablonu.xlsx` | pivot önbelleği boş; özellik bayrağıyla tipli tablo yedeği |
| TS-205 | Atölye pilot verisi sağlık raporu ve kiralama pilot uzlaştırması | E05-23, E06-09 | YOK | P1 | S | TS-090, TS-113 | D3-G | `mg/atolye_saglik.py`, `sv/imports/kiralama_goc.py` | 4 uyumsuzluk türü raporlanır; kararsız satır aktarılmaz |
| TS-206 | Eğitim göçü | E08 K17 | YOK | P3 | S | TS-150, TS-170 | D3-G | `mg/egitim.py` | ErpUserId eşlemesi; eşleşmeyen karantina; otomatik kullanıcı yok |
| TS-207 | SLA alanlarının geri doldurulması (rapor modu, idempotent) | E10-15 | KISMEN | P2 | M | TS-081, TS-174 | D3-G | `mg/servis_sla_geri_doldur.py` | kapalı göç işi OLCULEMEDI; açık iş yürürlük anından damgalanır; GERIYE_DONUK yalnız rapor |
| TS-208 | Eski serbest metin parça kayıtları ve ana veri eşleştirmesi Faz 2 | E11-21, E14-09 (Faz 2) | YOK | P3 | M | TS-171 | D3-G | `mg/servis_goc.py` eki, `sv/imports/musteri_eslestirme.py` | parça metni not olarak taşınır; Faz 2 diğer birimler |

### 2.5 Dalga 4 — Güvenlik sıkılaştırma ve canlıya çıkış

| ID | Başlık | Kaynak | Canlı | Ö | E | Bağımlılık | Paket | Dosyalar | Kabul |
|---|---|---|---|---|---|---|---|---|---|
| TS-210 | Şema Dalga 4 (denetim tetikleyicisi, süreli vekâlet kolonu) | E13-12, E13-15 | YOK | P2 | S | Dalga 3 bitti | D4-S | §4.3 | head→base→head |
| TS-211 | Denetim kaydının DB seviyesinde değişmezliği ve gerçek IP | E13-12 | KISMEN | P2 | M | TS-210 | D4-A | `sv/kvkk.py` (`SET LOCAL denge.kvkk_imha='1'`), `deploy/db-least-privilege.sql`, `docker-compose.yml`, `deploy/KURULUM.md`, `.env.example`, `t/integration/test_denetim_degismezlik.py` | DELETE her zaman red; UPDATE yalnız imha bayrağıyla ve yalnız old/new_value; `--forwarded-allow-ips=$FORWARDED_ALLOW_IPS`; KVKK testleri yeşil |
| TS-212 | Parola ve giriş yaşam döngüsü | E13-13 | KISMEN | P2 | M | TS-007 | D4-A | `sv/auth.py`, `a/auth.py`, `a/deps.py` (`PAROLA_MUAF_YOLLAR`), `p/ParolaDegistirPage.tsx`, `seeds/dev.py` | kilitli hesap da 401 aynı metin, sabit zamanlama; zorunlu değişim; geçici parola 72 sa tek seferlik; değişen test beklentileri sürüm notunda |
| TS-213 | Süreli vekâlet ve vekâlete kapalı izinler | E13-15, E07-D03 | YOK | P3 | M | TS-210, TS-006 | D4-A | `permissions.py` (`vekalet.ver` + SERVIS_YONETICI), `a/vekalet.py`, `a/deps.py`, `worker.py` | ≤30 gün CHECK; yalnız kendi etkin izinlerinin alt kümesi, `VEKALETE_KAPALI` hariç; alıcının oturumu düşer |
| TS-214 | Erişim gözden geçirme listesi | E13-16 | YOK | P3 | S | TS-212 | D4-A | `a/erisim_gozden.py`, `p/UsersPage.tsx` | tıklanabilir KPI; işaret denetimde; Excel |
| TS-215 | Teklif gönderim sıkılaştırması: SMTP hız sınırı, gönderilen PDF sha256 | E07-25, E07-09 | KISMEN | P3 | S | TS-142 | D4-B | `a/quotes.py` | dakikada 10 gönderim; `quote_sends.pdf_sha256` |
| TS-216 | Fiyat/maliyet ve kişisel veri sızıntısı test seti | E07-23, E07-01, E02-18 | KISMEN | P2 | M | Dalga 3 | D4-B | `t/integration/test_servis_fiyat_sizintisi.py`, `t/unit/test_on_yuz_kisisel_veri.py` | E07-23 anahtar listesi tüm teknik servis uçlarında maliyet.gor'süz rolde anahtar olarak YOK; `seeds/dev.py` adları `frontend/src`'de yok |
| TS-217 | Canlı modüllerdeki kapsam açıkları (RMA eki, RMA liste kapsam/sayfalama, cihaz kartı kapsamı) | E05 ve E03 gözlemleri | KISMEN | P2 | S | TS-012 | D4-B | `a/attachments.py` (RMA dalı), `a/rma.py`, `a/devices.py`, `t/integration/test_kapsam_guvenligi.py` (ek senaryolar) | RMA'ya ek yüklenebilir; RMA listesi `kapsam_musteri` + `sayfala`; cihaz kartı `kapsam_disinda_mi`; mobilite testleri ve altın kayıt yeşil |
| TS-218 | Magic-byte denetiminin diğer ek sahiplerine yayılması ve mobilite Excel'lerinin denetim kaydı | E01 K18, E12 K9 | KISMEN | P3 | S | TS-032 | D4-B | `s/ek_kapsam.py`, `a/reports.py` (`_xlsx` içinde `audit.log`) | mevcut yüklemeleri kıran MIME önce raporlanır (kuru koşu); denetim satırı her xlsx'te |
| TS-219 | Yedek dizini tutarlılığı ve doğrulama/ön kontrol genişletmesi | bu plan (tespit) | KISMEN | P1 | S | – | D4-C | `deploy/yedekle.sh`, `deploy/dogrula.sh`, `deploy/on-kontrol.sh` | `yedekle.sh` `/var/backups/denge-erp`, `dogrula.sh` `/var/yedek/denge-erp` arıyor → tek değişken `YEDEK_DIZIN`; dogrula yeni rolleri, servis tablolarını, worker görevlerini ve `alembic_version` = beklenen head'i denetler; on-kontrol migration alt sınırı güncellenir |
| TS-220 | Canlıya çıkış paketi ve prova | §5 | KISMEN | P1 | M | TS-219, tüm dalgalar | D4-C | `deploy/KURULUM.md` (EK G "Teknik Servis devreye alma"), `deploy/paket-uret.sh` (SURUM.txt'e servis sürümü), `docs/KULLANIM-KILAVUZU.md` | canlı döküm kopyasında: yedek → `kur.sh` → `dogrula.sh` → altın kayıt → servis duman testi → `geri-yukle.sh` provası; adımlar zaman damgalı tutanakla |

**Ertelenen (koda girmez):** E04-22 kontrol şablonlarının veriye taşınması — kullanıcıdan yeni cihaz türü/ölçüm şablonu gelene kadar (S6/S7). Kod sabiti `KONTROL_SABLONLARI` yeterli.

---

## 3. Dalgalar

| Dalga | Amaç | Giriş koşulu | Çıkış (geçit) koşulu | Canlı sürüm |
|---|---|---|---|---|
| **0 — Ortak altyapı** | izinler, roller, birim kapsamı, personel, ana veri, ortak yardımcılar, kayıt noktaları, **Dalga 0+1 şema iskeleti**, menü/açılış | head `b30e012dd879` doğrulandı | TS-001…TS-018 bitti; `make test` (altın kayıt dahil) + `test_migration_zinciri` + `make lint` + `make build` yeşil; yetki matrisi tüm uçları sınar | R0 (isteğe bağlı karanlık yayın: yalnız ADMIN görür) |
| **1 — Çekirdek akış** | servis iş emri yaşam döngüsü, iş havuzu ve panel, planlama/toplu atama, cihaz kütüğü, planlı bakım + dijital form + PB worker, saha zaman kaydı ve mobil ekran | Dalga 0 geçidi | TS-020…TS-078 bitti; mobilite etkisizlik testi (TS-028) yeşil; uçtan uca senaryo: arıza işi aç → planla → yola çık → sahada → sonuç → onay → tamamla → kapat; PB: sözleşme → eşleştir → üret → form → onay → dönem kapanışı | **R1** (pilot birim GUVENLIK, `bakim_otomatik_uretim=False`) |
| **2 — Diğer modüller** | SLA/operasyon, atölye, kiralama, yedek parça, teklif/maliyet, eğitim, işten çıkış, **Göç-1** | Dalga 1 geçidi + R1'de en az 1 hafta kullanım | TS-080…TS-177 bitti; satış teklif/sipariş/rapor testleri aynı sayıları verir; Göç-1 canlı kopyada prova raporu | **R2** (göç uygulanır; birim bazlı geçiş) |
| **3 — Raporlar ve eksikler** | rapor motoru, KPI'lar, veri kalitesi, P2/P3 eksikler, **Göç-2** | Dalga 2 geçidi | TS-180…TS-208 bitti; altın KPI seti (TS-183) yeşil | R3 |
| **4 — Sıkılaştırma ve çıkış** | denetim değişmezliği, parola, vekâlet, sızıntı testleri, canlı modül kapsam açıkları, deploy betikleri, çıkış provası | Dalga 3 geçidi | TS-210…TS-220 bitti; çıkış provası tutanağı | **R4 (son)** |

Dalga içi kritik yol: Dalga 0'da D0-S (şema) ilk 3 iş günü; diğer paketler aynı anda şemadan bağımsız kısımlarla (izin kataloğu, yardımcılar, ölçüm betikleri) başlar. Dalga 1'de D1-B'nin `durum_degistir` ve atama sözleşmesi (TS-021, TS-025) ilk teslimdir; D1-D/F/G kancaları bu imzalara yazılır (imzalar D0-S iskeletinde sabittir).

---

## 4. Kodlama iş paketleri

### 4.1 Paketler ve paralellik

| Dalga | Paket | Kapsam (TS) | Paralel çalışır mı | Ön koşul |
|---|---|---|---|---|
| 0 | **D0-S** Şema-0/1 | TS-018 | ilk başlar | – |
| 0 | D0-A RBAC & oturum | TS-001, 003, 004, 006, 007 | evet (TS-007 D0-S'in `users` kolonlarından sonra) | – |
| 0 | D0-B Ortak altyapı & kabuk | TS-005, 011, 012, 013 | evet | TS-012/013 D0-S iskeletinden sonra |
| 0 | D0-C Ana veri | TS-014, 015, 016 | evet | D0-S migration 2 |
| 0 | D0-D Personel | TS-002, 008, 009, 010 | evet | D0-S migration 1 |
| 0 | D0-E Ölçüm | TS-017 | evet | – |
| 1 | D1-B İş emri arka uç | TS-020…031 | evet | Dalga 0 |
| 1 | D1-C İş emri ön yüz, ekler, onay/PDF, panel, uyarı | TS-032…037 | evet (sözleşme = D1-B Pydantic şemaları, ilk gün yayınlanır; `make openapi`) | Dalga 0 |
| 1 | D1-D Planlama | TS-040…049 | evet | TS-021/025 imzaları |
| 1 | D1-E Ekipman | TS-050…057 | evet | Dalga 0 |
| 1 | D1-F Planlı bakım | TS-060…069 | evet | TS-021 imzası |
| 1 | D1-G Saha/zaman & mobil | TS-070…078 | evet | TS-021/025 imzaları |
| 2 | **D2-S** Şema-2 | TS-080 | ilk başlar | Dalga 1 |
| 2 | D2-B Atölye | TS-090…101 (+TS-102 atölye kancası) | evet | D2-S |
| 2 | D2-C Kiralama | TS-102, 110…122 | evet | D2-S, TS-131 (depo ayrımı) |
| 2 | D2-D Yedek parça | TS-130…138 | evet | D2-S |
| 2 | D2-E Teklif & maliyet | TS-140…149 | evet | D2-S |
| 2 | D2-F Eğitim | TS-150…160 | evet | D2-S |
| 2 | D2-G Operasyon/SLA | TS-081…085 | evet | D2-S |
| 2 | D2-H Personel çıkışı | TS-165 | evet | TS-155 sözleşmesi (stub) |
| 2 | D2-I Göç-1 | TS-170…177 | evet | Dalga 1 modelleri |
| 3 | **D3-S** Şema-3 | TS-180 | ilk başlar | Dalga 2 |
| 3 | D3-A Rapor motoru & servis raporları | TS-181…184, 186, 187, 201 | evet | – |
| 3 | D3-B Zaman ekranı & planlama P3 | TS-189, 190 | evet | – |
| 3 | D3-C Ekipman/ana veri eksikleri | TS-188, 191, 192, 193 | evet | – |
| 3 | D3-D Atölye/kiralama/parça raporları | TS-194, 195, 196 | evet | D3-S (sayım) |
| 3 | D3-E Bakım/maliyet/eğitim raporları | TS-185, 197, 198 | evet | TS-181 kayıt arayüzü |
| 3 | D3-F SLA P3 & küçükler | TS-199, 200 | evet | D3-S |
| 3 | D3-G Göç-2 | TS-205…208 | evet | – |
| 4 | **D4-S** Şema-4 | TS-210 | ilk başlar | Dalga 3 |
| 4 | D4-A Kimlik güvenliği | TS-211…214 | evet | D4-S |
| 4 | D4-B Sızıntı & canlı açıklar | TS-215…218 | evet | – |
| 4 | D4-C Deploy & çıkış | TS-219, 220 | evet (TS-220 en son) | – |

### 4.2 Dosya sahipliği (aynı dalgada bir dosyaya YALNIZ bir paket yazar)

Kural: **Ortak dosyalar** (`permissions.py`, `main.py`, `models/__init__.py`, `statemachine.py`, `c/AppLayout.tsx`, `main.tsx`, `sv/settings.py`, `t/conftest.py`, `s/__init__.py`, `s/kancalar.py`) dalga başında o dalganın **S (şema) paketi** veya aşağıda adı geçen altyapı paketi tarafından hazırlanır ve dalga boyunca **dondurulur**. Bir paket donmuş dosyada değişiklik isterse S paketine "değişiklik talebi" açar; S paketi tek seferde uygular. Dalga bittiğinde sahiplik bir sonraki dalganın tablosuna geçer.

| Dosya / dizin | Dalga 0 | Dalga 1 | Dalga 2 | Dalga 3 | Dalga 4 |
|---|---|---|---|---|---|
| `permissions.py` | D0-A | donmuş | donmuş | donmuş | D4-A |
| `seeds/dev.py` | D0-A | donmuş | donmuş | donmuş | D4-A |
| `main.py`, `models/__init__.py`, `statemachine.py` | D0-S | donmuş | D2-S | D3-S | D4-S |
| `m/*.py` (tüm modeller) | D0-S | donmuş | D2-S | D3-S | D4-S |
| `alembic/versions/*` | D0-S | (talep → D0-S ekler d0a0000000NN) | D2-S | D3-S | D4-S |
| `s/__init__.py`, `s/kancalar.py`, `s/numara.py`, `s/yerel_zaman.py` | D0-S (iskelet) / D0-B (yardımcılar) | donmuş | D2-S | D3-S | – |
| `s/kapsam.py` | D0-A | D1-B | donmuş | donmuş | – |
| `a/users.py`, `a/auth.py`, `sv/auth.py`, `schemas/auth.py`, `sv/yetki.py`, `a/deps.py` | D0-A (`a/deps.py`: D0-B) | donmuş | donmuş | donmuş | D4-A |
| `c/AppLayout.tsx`, `main.tsx`, `c/KpiKutusu.tsx` | D0-B | donmuş (Dalga 1 menü/rotaları D0-B ekledi) | D2-S | D3-S | – |
| `sv/settings.py`, `sv/uyarilar.py`, `sv/gorevler.py`, `a/search.py`, `sv/imports/__init__.py`, `t/conftest.py` | D0-B | donmuş | D2-S (conftest), D2-I (`imports/__init__.py`) | D3-S | D4-B |
| `a/attachments.py`, `s/ek_kapsam.py`, `m/attachment.py` sabitleri | D0-B | D1-C (service_orders + service_equipment dallarını D1-C yazar; D1-E fonksiyonu kendi `ekipman.py`'de sağlar) | D2-F (eğitim dalları), kiralama/atölye dalları D2-S iskelette | donmuş | D4-B |
| `sv/kvkk.py` | D0-C | donmuş (modüller kancayla) | D2-H | donmuş | D4-A |
| `sv/export.py` | – | D1-B | donmuş | D3-A | – |
| `worker.py` | – | D1-F | D2-G | D3-F | D4-A |
| `sv/belgeler.py` | D0-C | donmuş | donmuş | donmuş | – |
| `sv/normalize.py` | D0-B | donmuş | donmuş | donmuş | – |
| `s/ana_veri.py`, `a/lokasyonlar.py`, `a/teknik_servis_ana_veri.py`, `p/HesaplarPage.tsx`, `c/MusteriLokasyonSecici.tsx` | D0-C | D1-C (yalnız `MusteriLokasyonSecici`) | D2-I (`veri_kalitesi`, eşleştirme uçları) | D3-C | – |
| `s/personel.py`, `a/personel.py`, `p/PersonelPage.tsx` | D0-D | donmuş | D2-H | D3-F | D4-A |
| `s/is_emirleri.py`, `gecmis.py`, `bekletme.py`, `sonuc.py`, `atama.py`, `a/teknik_servis.py` | iskelet D0-S | D1-B | donmuş (kanca ile genişler) | D3-C (yalnız TS-193 okuma fonksiyonu) | – |
| `s/onay.py`, `s/panel.py`, `p/ServisIsleriPage.tsx`, `p/ServisIsFormu.tsx`, `p/ServisPaneli.tsx`, `fa/teknikServis.ts`, `templates/servis_formu.html` | iskelet | D1-C | D2-F (yalnız ServisIsleriPage'e gözlem düğmesi) | D3-A (panel KPI kaydı genişletme) | – |
| `s/planlama.py`, `takvim.py`, `cakisma.py`, `a/teknik_servis_planlama.py`, `p/ServisPlanlamaPage.tsx`, `c/PlanPenceresi.tsx`, `fa/servisPlanlama.ts`, `fa/client.ts` | iskelet | D1-D | donmuş | D3-B | – |
| `s/ekipman.py`, `a/servis_ekipman.py`, ekipman sayfaları | iskelet | D1-E | donmuş | D3-C | – |
| `s/bakim*.py`, `a/bakim.py`, `p/Bakim*.tsx`, `fa/bakim.ts` | iskelet | D1-F | donmuş | D3-E | – |
| `s/zaman.py`, `s/mobil.py`, `a/servis_zaman.py`, mobil sayfalar, `c/EkYukleyici.tsx` | iskelet | D1-G | D2-G (yalnız `s/mobil.py` SLA bloğu) | D3-B (`rapor_hesap` kişi-saat çağrısı) | – |
| `s/sla*.py`, `operasyon.py`, `tekrar_ariza.py`, `uyari_uretimi.py`, `a/servis_operasyon.py`, `p/OperasyonMerkeziPage.tsx`, `p/ServisTanimlarPage.tsx` | – | (ServisTanimlarPage arıza nedeni sekmesi: D1-B) | D2-G | D3-F | – |
| atölye dosyaları | – | – | D2-B | D3-D | – |
| kiralama dosyaları | – | – | D2-C | D3-D | – |
| `s/parca.py`, `a/yedek_parca.py`, `a/stock.py`, `sv/stock.py`, `a/catalog.py`, `schemas/catalog.py`, `c/ServisParcalari.tsx` | – | – | D2-D | D3-D (+ `sv/purchasing.py`, `a/purchasing.py`) | – |
| `sv/quotes.py`, `a/quotes.py`, `a/public_quotes.py`, `a/orders.py`, `sv/mail.py`, `templates/teklif.html`, `sv/reports.py`, `a/reports.py`, `s/maliyet.py`, `a/servis_maliyet.py`, teklif/maliyet sayfaları | – | – | D2-E | D3-E (`sv/reports.py` dönüşüm), D3-F (`sv/mail.py`) | D4-B (`a/quotes.py`, `a/reports.py`) |
| eğitim dosyaları | – | – | D2-F | D3-E | – |
| `mg/*`, `sv/imports/<göç profilleri>`, `Makefile` göç hedefleri | D0-E (`mg/ana_veri_olcum.py`, `mg/kutuk_profil.py`) | – | D2-I | D3-G | – |
| `s/rapor_*.py`, `a/servis_raporlari.py`, `p/ServisRaporlariPage.tsx` | – | – | – | D3-A | – |
| `a/rma.py`, `a/devices.py` | – | – | – | – | D4-B |
| `deploy/*`, `docker-compose.yml`, `.env.example`, `deploy/KURULUM.md` | – | – | D2-I (KURULUM göç bölümü) | – | D4-C (D4-A: `db-least-privilege.sql`, compose `forwarded-allow-ips`) |
| `docs/KULLANIM-KILAVUZU.md` | – | D1-G | D2-S | D3-F | D4-C |

### 4.3 Alembic zinciri (çakışmayı önleme)

- **Tek sahip:** her dalgada migration'ları yalnız o dalganın S paketi yazar. Revizyon kimlikleri **önceden ayrılmıştır** ve `alembic revision --rev-id <id> -m "<slug>"` ile üretilir (autogenerate çıktısı elle gözden geçirilir; CHECK/EXCLUDE/tetikleyici/sequence `op.execute` ile).
- **Ek değişiklik:** dalga içinde şema değişikliği gereken paket S'ye talep açar; S zincirin SONUNA `dXa0000000NN` (NN = 10…19 ayrılmış) ekler. Mevcut revizyon dosyası birleştirildikten sonra **değiştirilmez**.
- Her revizyonda: docstring'de NEDEN + bedel, çalışır `downgrade`, head→base→head testi, tek head.

| Sıra | Rev ID | Slug | İçerik | down_revision |
|---|---|---|---|---|
| 1 | `d0a000000001` | ts_birim_ve_personel | `user_units`, `users` personel kolonları, `personnel_name_maps` | `b30e012dd879` |
| 2 | `d0a000000002` | ts_ana_veri_hesap_lokasyon | `accounts/addresses/contacts` kolonları, `addresses.line` NULL (TESIS), `account_aliases`, `account_merges`, `quotes.address_id` | d0a…01 |
| 3 | `d0a000000003` | servis_is_emri_cekirdek | `service_order_no_seq`, `service_orders` (Dalga 0 bilinen tüm kolonlar dahil `first_completed_at`, `customer_name_raw`, `location_raw`, `coverage_status/snapshot`, `contract_item_id`, `maintenance_period_id`, `equipment_id` kolonları — FK'ler 4/6'da eklenir), serials (+GIN trgm), events (+`trg_soe_salt_ekleme`), `service_hold_reasons` (tohumlu) + `service_holds` (FK neden, `beklenen_bitis_at`, `sla_durdurur`, `sure_dk`, `kapanis_notu`), results, fault_reasons (tohumlu), assignments, approvals (`onay_grubu`, `approved_at`) | d0a…02 |
| 4 | `d0a000000004` | servis_ekipman_kutugu | `service_equipment`, `fk_so_ekipman` | d0a…03 |
| 5 | `d0a000000005` | servis_planlama_takvim | `service_visit_no_seq`, visits, plans (`uq_svcplan_aktif`), members, vehicles, unavailability (`ex_svcmusait_cakisma`) | d0a…04 |
| 6 | `d0a000000006` | bakim_sozlesme_donem_form | `seq_bakim_sozlesme_no`, maintenance_* tabloları (`ex_mci_ekipman_cakisma`), `fk_so_sozlesme_kalemi`, `fk_so_bakim_donemi`, `uq_so_pb_cihaz_donem` | d0a…05 |
| 7 | `d0a000000007` | servis_zaman_kaydi | `service_time_entries` (`uq_ste_acik_kisi`, `ex_ste_kisi_cakisma`) | d0a…06 |
| 8 | `d2a000000001` | servis_sla_uyari | `service_sla_policies` (tohum), `service_orders` SLA kolonları + `ck_so_pb_sla`, `service_alerts`, `service_alert_reads` | d0a…07 (veya son ek) |
| 9 | `d2a000000002` | atolye_cekirdek | `atolye_no_seq`, `atolye_kabul_grubu_seq`, `workshop_records` (`fk_atolye_servis_ekipman` bileşik), `workshop_accessories` | d2a…01 |
| 10 | `d2a000000003` | depo_kiralama_cekirdek | `warehouses` kolonları (+`servis_deposu`), `rental_no_seq`, rental_* tabloları (`ex_rtahsis_cihaz_cakisma`) | d2a…02 |
| 11 | `d2a000000004` | yedek_parca_stok_defteri | `stock_movements` kolonları + CHECK'ler + `trg_stok_hareket_degismez` + `uq_stok_hareket_acilis`, `products` kolonları, `stock_count_no_seq`, `stock_counts`, `stock_count_lines`, `service_part_requests` | d2a…03 |
| 12 | `d2a000000005` | servis_teklif_maliyet | `quotes/quote_versions/quote_lines` kolonları, `ck_quote_durum` genişletme (İSTİSNA), `quote_sends`, `service_labor_rates` (`ex_iscilik_tarife_cakisma`), `service_order_financials` | d2a…04 |
| 13 | `d2a000000006` | egitim_cekirdek | training_*, competencies, competency_assessments, personnel_certificates (`training_observations.service_order_id` doğrudan) | d2a…05 |
| 14 | `d2a000000007` | servis_kiralama_atolye_bagi | `service_orders.rental_id` + `uq_so_kiralama_tur_acik`, `workshop_records.rental_asset_id` | d2a…06 |
| 15 | `d3a000000001` | kiralama_sayim | `rental_counts`, `rental_count_lines` (`uq_rsayim_acik`) | d2a…07 |
| 16 | `d3a000000002` | servis_bildirim_eposta | `service_notification_prefs`, `service_mail_outbox` | d3a…01 |
| 17 | `d3a000000003` | servis_mesai_takvimi | `service_work_calendar`, `service_holidays` (yalnız TS-200 MESAI kararı verilirse; verilmezse bu rev atlanır ve 18'in `down_revision`'ı 16 olur) | d3a…02 |
| 18 | `d3a000000004` | egitim_yetkinlik_esleme | `course_competencies`, `service_competency_requirements` | d3a…03 |
| 19 | `d4a000000001` | denetim_degistirilemez | `trg_audit_degistirilemez` | d3a…04 |
| 20 | `d4a000000002` | sureli_vekalet | `user_permissions.bitis_at` + CHECK | d4a…01 |

`t/conftest.py _TRUNCATE`: yeni tablolar `users`/`accounts`'a FK ile bağlı olduğundan CASCADE yeterlidir; FK'siz kalanlar (`service_vehicles`, `service_unavailability`, `service_visits`, `maintenance_generation_runs`, `account_merges`, `rental_catalog_items`) açıkça eklenir. Sequence'ler `OWNED BY` ile bağlanır.

### 4.4 Paket teslim akışı

1. Paket dalı açılır; yalnız §4.2'de sahibi olduğu dosyalara yazar.
2. API sözleşmesi (Pydantic In/Out) ilk gün PR'ında yayınlanır; ön yüz paketi `make openapi` çıktısıyla çalışır.
3. Birleştirme sırası: S paketi → arka uç paketleri (bağımlılık sırasıyla) → ön yüz paketleri. Her birleştirmeden sonra ana dal `make test lint build` ile yeşil kalmalıdır.
4. Kanca kayıtları modül dosyasının sonunda; `s/__init__.py`'deki import sırası S paketindedir.

### 4.5 Bitti tanımı (her paket, her TS maddesi)

- `make test` yeşil — **`t/migration/test_altin_kayit.py` (932 iş / 552.825,00 TL) dahil** — ve `make test-goc` yeşil; `test_migration_zinciri` head→base→head ve tek head.
- `make lint` temiz (`ruff check`, `ruff format --check`, `oxlint`); `make build` (`tsc` + vite) hatasız.
- Her yeni uç: `require_permission` ile korunur; `test_yetki_matrisi` otomatik 403/200 üretir **ve** maddeye özgü RBAC testi vardır (yetkisiz 403, yetkili 2xx).
- Her `{id}` uç: kapsam dışı kullanıcıda 404 **ve** `db.refresh` ile veri değişmedi testi (`test_router_kapsam_taramasi` kapsamına girer).
- Liste/KPI/Excel/uyarı sayıları kapsam fonksiyonlarından geçer; KPI kutusu sayısı = açılan liste `X-Toplam-Kayit`.
- Fiyat/maliyet alanı `sees_cost` false iken yanıtta **anahtar olarak yok** (test).
- Durum değişikliği yalnız makine ile; yeni makine `MAKINELER`'de.
- Denetim izi aynı transaction'da, commit'ten önce; kişisel veri `is_personal_data=True`.
- Saat yalnız `Clock`/`yerel_zaman`; `s/` altında `datetime.now`/`date.today` yok (grep testi).
- Tüm mesaj, etiket, docstring Türkçe; model docstring'i NEDEN'i anlatır; kısıt adları önekli.
- Mobilite regresyonu: TS-028 testi ve mevcut mobilite testleri yeşil.
- Ön yüz: 375 px'te kullanılabilir; `yetkili()` ile buton gizleme; 409'da yenileme mesajı.

---

## 5. Canlıya geçiş ve eski sistem verisinin göçü

### 5.1 Sürüm ve yükseltme (mevcut `kur.sh` / `dogrula.sh` / Caddy / fail2ban ile)

1. **Paket:** `make build && make paket` (`deploy/paket-uret.sh`) → `denge-canli` paketi; `SURUM.txt` göç sürümünü (hedef head) yazar.
2. **Önce yedek:** `sudo UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh` (DB + dosyalar, GPG). Yedek dosyasının adı ve boyutu tutanağa yazılır.
3. **Ön kontrol:** `on-kontrol.sh` (migration sayısı, bozuk `._*.py` yok).
4. **Yükseltme:** `./kur.sh` — kodu `rsync --delete` ile tazeler, `.env`'e dokunmaz, döküm yüklemez; `api` açılışında `alembic upgrade head` **yalnız ileri** migration'ları uygular, ardından `python -m app.seeds.dev` yeni izinleri ve rolleri senkronlar (özelleştirilmiş rollere indirmez, log'a yazar). EK E (en az yetkili DB kullanıcısı) uygulanmışsa `alembic upgrade head` ve seed **sahip kullanıcıyla elle** koşulur.
5. **Doğrulama:** `deploy/dogrula.sh` (TS-219 ile genişletilmiş: `alembic_version` = beklenen head, yeni roller var, servis tabloları erişilebilir, worker görevleri listede, yedek dizini doğru) + `cat SURUM.txt`.
6. **Caddy/fail2ban:** değişiklik gerekmez (yeni uçlar `/api/*` altında, aynı kimlik doğrulama ve CSRF). `forwarded-allow-ips` Dalga 4'te (TS-211) compose'a eklenir; fail2ban jail yorumundaki "15 dk" düzeltilir.
7. **Devreye alma bayrakları (R1):** `bakim_otomatik_uretim=False` (TS-063 eşleştirmesi %100 olunca açılır); `servis_sla_yururluk_at` boş (R2'de göç bittikten sonra şimdiki zamana ayarlanır); `servis_eposta_acik=False`.
8. **Kullanıcı atama:** servis rolleri ve `user_units` önce pilot birime (GUVENLIK) verilir; menü yalnız izinli kullanıcıya görünür, diğer kullanıcılar için ERP değişmemiş görünür.

### 5.2 Geri dönüş

- Üretimde **`alembic downgrade` kullanılmaz** (downgrade'ler testte zorunludur ama canlıda veri kaybı ve yarım durum riski taşır).
- **Kural:** önceki pakete dönmek için **önce DB yedeği geri yüklenir** (`deploy/geri-yukle.sh <yedek.sql.gz.gpg>` — DB + dosyalar), **sonra** önceki paketle `kur.sh`. Sebep: `rsync --delete` yeni migration dosyalarını siler, ama `alembic_version` yeni head'i gösterdiği için eski kod açılışta `Can't locate revision` ile düşer.
- Yükseltmeden sonra servis verisi girilmeye başlandıysa geri dönüş bu verinin kaybı demektir; bu yüzden her R sürümünde ilk gün "yalnız pilot birim + yedek saatlik" uygulanır (`yedekle.sh` cron'u o gün saatlik).
- Her R sürümünden önce `make yedek-prova` / `geri-yukle.sh` provası canlı döküm kopyasında koşulur (TS-220).

### 5.3 Eski .NET DengeERP V1.20.1 (SQL Server) verisinin içe aktarılması

**Altyapı yeniden kullanılır:** (a) `sv/imports/` profil çerçevesi (`Profil.dogrula/uygula`, `staged_rows`, satır kararları `kararlar[satir_no]`, `SatirSonucu.cakisma`, `PROFIL_IZINLERI`, İçe Aktarma ekranı) — insan kararı gereken her şey için; (b) `app/migration/` betik kalıbı (`kaynak_* → hazirla_* → yukle_*`, `make goc-onizleme/goc-uygula/goc-rapor` emsali) — toplu, deterministik dönüşümler için; (c) `SourceMixin` + `uq_<tablo>_kaynak` ile **idempotentlik** (`source_system='DENGEERP_V1'`, `source_ref='<KaynakTablo>:<Id>'`), `ON CONFLICT DO NOTHING`.

**Akış:**

1. **Kaynak çıkarımı (salt okunur):** V1.20.1 `.bak` yedeği ayrı bir SQL Server test örneğine geri yüklenir; `mg/teknik_servis/sql/*.sql` T-SQL `SELECT` sorguları UTF-8 CSV/XLSX üretir (seri no METİN, tarih ISO 8601). Canlı SQL Server'a bağlanılmaz. `DateTime` kolonları yerel saat (Europe/Istanbul) kabul edilir ve hazırlama betiğinde açıkça UTC'ye çevrilir; göç raporunda kaynak ekranla karşılaştırılacak 5 örnek iş listelenir.
2. **Ölçüm:** TS-017 betikleri kaynak ve canlı PG üzerinde sayıları üretir (karar girdisi; sayı uydurulmaz).
3. **Hazırlama:** `mg/hazirla_*` betikleri normalize eder (`normalize_seri`, `unvan_anahtari`, `il_normalize`), eşleştirme önerir, karantina listesi yazar; hiçbir şey yazılmaz.
4. **İnsan kararı (İçe Aktarma profilleri):** sıra zorunlu —
   1. `personel` (TS-010) ve `ad_esleme` (TS-170): eski ad → `users.id`; eşleşmeyen İK onayıyla girişsiz personel olur ya da karantinada kalır.
   2. `musteri_eslestirme` (TS-171): serbest metin müşteri/tesis → `accounts`/`addresses`; onaylı satır `account_aliases` üretir. Faz 1: Güvenlik sözleşmeleri + GUVENLIK ekipmanı; Faz 2 (TS-208): diğer birimler.
   3. `kutuk` (TS-172), `bakim_sozlesme` (TS-173: ekrandan yönetilen kayıt "korundu"; teyit Excel'i `SERVIS_YONETICI`'ye).
   4. `servis_isleri` (TS-174: POC durumları çözüm kanalına eşlenir, eşlenemeyen raporlanır; eski numara korunur; olay geçmişi kaynak log'dan), `servis_plan` (TS-175), `servis_zaman` (TS-176: çakışan satır `GOC_CAKISMA` iptal türüyle saklanır).
   5. Dalga 3: atölye pilot sağlık raporu (TS-205, pilot gerçek veri üretmediyse göç yok), kiralama pilot uzlaştırma, eğitim (TS-206), SLA geri doldurma rapor modunda (TS-207), eski parça metni (TS-208).
5. **Uygulama:** `make goc-servis-onizleme` → karar → `make goc-servis-uygula`; tümü `sistem.goc` (bakım `bakim.yaz`, personel `personel.yaz`, eşleştirme `hesap.birlestir`) ile ve denetime yazılarak.
6. **Uzlaşma:** `make goc-servis-rapor` (TS-177): her tablo için kaynak = aktarılan + karantina + reddedilen; ikinci koşu 0 yeni satır.
7. **Prova sırası:** canlı döküm kopyası (`paket-uret.sh` dökümü) → upgrade → göç → altın kayıt + mobilite testleri → sayım tutanağı → canlı. Birim bazlı geçiş: GUVENLIK → HABERLESME/POC → MOBILITE/ARAC_TAKIP; her birim geçişinde `servis_sla_yururluk_at` yalnız bir kez (ilk birimde) ayarlanır, eski kapalı işler `OLCULEMEDI`.
8. **Kapsam dışı:** eski parça hareketleri (açılış stoğu fiziksel sayımla, TS-134), Logo CRM/Flowick, eski sistem kullanıcı parolaları.

---

## 6. Kararlar

### 6.1 Kesişen (modüller arası) kararlar

| No | Karar | Gerekçe |
|---|---|---|
| KD-01 | Teknik servis ayrı alan olarak canlı katmanlara gömülür; `work_orders`/hak ediş zinciri hiç yazılmaz | hak ediş, panel ve altın kayıt korunur (00 §6.2) |
| KD-02 | Model dosyaları modül bazında bölünür (§1.1), API dosyaları da (servis_ekipman, servis_zaman, servis_operasyon ayrı) | paralel paketlerin aynı dosyaya yazmaması; rehber "büyürse ayrı dosya" |
| KD-03 | Birim = `user_units` + iki yeni kapsam (`KENDI_BIRIMI`, `KENDI_ISLERI`); mevcut yardımcılar değişmez | canlı akış değişmeden kayıt güvenliği; teknisyen kuralı rol adına değil kapsama bağlı |
| KD-04 | Fail-closed: birimsiz birim kapsamlı kullanıcı hiçbir şey görmez; bilinmeyen kapsam = red | sızıntı yerine boş liste |
| KD-05 | Kapsam dışı tek kayıt 404, gövdedeki katalog öğesi 403 | canlı `test_kapsam_guvenligi` kalıbı; kimlik taraması engellenir |
| KD-06 | Servis rollerine `rapor.gor`/`rapor.disaaktar` verilmez; yeni `servis_rapor.gor/disaaktar/personel` | `rapor.disaaktar` mobilite finans Excel'ini kapsamsız açıyor (E12-D01) |
| KD-07 | Servis rollerinden `hesap.yaz` çıkarılır; müşteri hızlı ekleme `servis.yaz + lokasyon.yaz` ile `is_verified=false` | IBAN/VKN düzenleme yetkisi servis personeline gerekmez (E14-D01) |
| KD-08 | ATOLYE rolüne `lokasyon.yaz` (hızlı müşteri) ve `servis.planla` verilir | atölye kabulünde müşteri bulunamazsa iş açılamıyordu; atölye kendi işini atıyor (E05-11) |
| KD-09 | `SERVIS_TEKNISYEN` = `KENDI_ISLERI`; `hesap.gor` yok | KVKK en az erişim; müşteri bilgisi iş detayında gömülü |
| KD-10 | `IK` rolü açılır, eğitim izinleri ona verilir; `EGITIM_SORUMLUSU`, `KIRALAMA_OPERASYON` açılmaz; `KIRALAMA_DEPO` ve `SERVIS_DEPO` açılır | rol sayısı minimum; kiralama talebi SERVIS_OPERASYON'da |
| KD-11 | `maliyet.gor` rol kümesi değişmez; `maliyet.yaz` yalnız ADMIN, kişiye UserPermission | kilitli unit test; fiyat varsayılan gizli |
| KD-12 | Tüm belge numaraları `ÖNEK-YYYYAA-NNNNNN`, global sıfırlanmayan sequence, tek yardımcı | eşzamanlılık güvenli; göç numaralarıyla çakışmaz; modül belgelerindeki farklı biçimler tekleştirildi |
| KD-13 | Servis durum kataloğu tek (§1.7); KARGODA/TEST_KONTROL yok; atölye ayrıntısı atölye tablosunda | E01/E02/E05/E09/E12 arasındaki çelişki (E01-D01, E05-D02) |
| KD-14 | Bekleme nedeni CHECK değil katalog tablosu (FK) ve ilk migration'da | SLA durdurma bayrağı tek kaynakta; sonradan CHECK→FK dönüşümü olmaz |
| KD-15 | Modüller arası bağlantı yalnız `s/kancalar.py` kayıt defteri ile | Dalga 1 dosyaları sonraki dalgalarda düzenlenmez; dosya sahipliği çakışmaz |
| KD-16 | Tüm ayar anahtarları Dalga 0'da tek seferde; yeni anahtarlar sınırla doğrulanır | `settings.py` tek sahiplik; `set_many` doğrulamıyordu |
| KD-17 | Yerel zaman yardımcısı `s/yerel_zaman.py`; `clock.py` değişmez | canlı çekirdek dosyaya dokunmama (E09-16 tercih edildi, E10-12'nin clock.py önerisi alınmadı) |
| KD-18 | PDF bağlamı modül servislerinde; `belgeler.py` yalnız K24 | dosya sahipliği; modül bağımsızlığı |
| KD-19 | `servis_onay_zorunlu_turler` varsayılanı `["PB"]` | E04 S2/S3; ALINAMADI+neden kabul edildiği için saha bloke olmaz (E01 K4 ile uzlaşma) |
| KD-20 | Planlama Dalga 1'de iş emriyle birlikte yayımlanır; "asgari planla" yolu yazılmaz | E01-D03 kararı: birlikte yayın |
| KD-21 | `bakim_otomatik_uretim=False` ile yayın; eşleştirme %100 olunca açılır | yanlış/eksik PB üretimini önler (E03-07, E03-D03) |
| KD-22 | SLA yürürlük anı ayarı boşken damga yok; göçten sonra ayarlanır | canlıya geçişte uyarı/e-posta fırtınası (E10-D02) |
| KD-23 | MESAI takvimi koşullu (Dalga 3); P1'de yalnız 7/24 | veri yok, kullanıcı talebi yok; yapı hazır |
| KD-24 | Faaliyet sözlüğünde `ISCILIK` yok; saha emeği `SAHA` | E09-D02 tek sözlük; E05/E07'deki ISCILIK eşlemesi SAHA'ya |
| KD-25 | Parça maliyeti `stock_movements.unit_cost Numeric(14,4)`, hareketli ağırlıklı ortalama, hareket anında dondurulur | E11-D03 / E07-10 tekleştirmesi |
| KD-26 | Her dalgada model+migration tek S paketinde, önceden ayrılmış rev id'lerle | Alembic çoklu head çakışması imkânsız |
| KD-27 | Canlıda downgrade yok; geri dönüş = yedekten geri yükleme + önceki paket | `rsync --delete` + `alembic_version` uyumsuzluğu |
| KD-28 | Göç idempotent, SourceMixin ile; insan kararı İçe Aktarma profillerinde | mevcut altyapı yeniden kullanılır; uydurma veri yok |
| KD-29 | Menüde "Teknik Servis" ve "İnsan Kaynakları" grupları; canlı öğeler yerinde | 15+ yeni öğe düz listeyi okunmaz yapardı; mobilite kullanıcısı için görünüm değişmez |
| KD-30 | Servis kullanıcısının açılış sayfası izinden türetilir | `/` PanelPage `rapor.gor` istiyor; servis rolü almıyor (KD-06) |
| KD-31 | Kiralık cihaz servis kütüğüne ya da `devices`'a yazılmaz; ayrı envanter | global seri tekilliği ve mobilite stok raporu (E06 K1) |
| KD-32 | Teklif tek tablo (`quotes` + `birim`); `ck_quote_durum` genişletmesi tek onaylı CHECK istisnası | ikinci durum kolonu raporları bölerdi (E07 K2) |
| KD-33 | `addresses.line` NOT NULL gevşetmesi ve `quote_lines.description` genişletmesi onaylı istisnadır | tesis satırı adres metni olmadan da kurulabilmeli; genişletme veri kaybetmez |
| KD-34 | Mobilite `/api/raporlar` Excel denetimi, RMA/cihaz kapsam açıkları Dalga 4'te ve ayrı maddelerde | öncelik sırası: yeni modül → eksik → sıkılaştırma; canlı akış önce bozulmasın |
| KD-35 | Yedek dizini tutarsızlığı (`yedekle.sh` ↔ `dogrula.sh`) Dalga 4'te ama P1 | doğrulama betiği yedeği bulamıyor: çıkış provası için ön koşul |

### 6.2 Modül belgelerini geçersiz kılan kararlar (kodlayıcı için tam liste)

| Modül belgesinde | Bu planda | Kural |
|---|---|---|
| E01/E03/E07/E09/E12: Excel = `rapor.disaaktar`; ekran = `rapor.gor` | `servis_rapor.disaaktar` / `servis_rapor.gor` | KD-06 |
| E12: `rapor.personel` | `servis_rapor.personel` | KD-06 |
| E01: SERVIS_YONETICI/OPERASYON `hesap.yaz`; E03-01: tüm servis rollerine `hesap.gor` | `hesap.yaz` yok; `hesap.gor` yalnız YONETICI/SEF/OPERASYON/DEPO | KD-07, KD-09 |
| E05: SERVIS_TEKNISYEN `KENDI_BIRIMI`; `servis.tumunu_gor`; `atolye.kapat` | `KENDI_ISLERI`; açılmaz; iptal/geri alma `servis.kapat` | KD-09 |
| E14 K15: atölye hızlı ekleme yapamaz | ATOLYE `lokasyon.yaz` alır | KD-08 |
| E02: `servis.ata`, `servis.musaitlik`; E04: `bakim.uret/form/yeniden_ac`; E06: `KIRALAMA_OPERASYON`; E08: `EGITIM_SORUMLUSU` | açılmaz (revised kararlarla zaten kaldırıldı) | KD-10 |
| E02 `ZYR-YYYY-NNNNNN`, E05 `AT-YYYY-NNNNNN`, E06 `KIR-YYYY-#####` | `ÖNEK-YYYYAA-NNNNNN` | KD-12 |
| E10-12: `clock.py`'ye yardımcı | `s/yerel_zaman.py` | KD-17 |
| E01/E04/E05/E06: `belgeler.servis_formu_baglami` vb. | modül servislerinde bağlam | KD-18 |
| E01 K4: onay zorunlu türler `[]` | `["PB"]` | KD-19 |
| E01-D03: asgari planla seçeneği | birlikte yayın | KD-20 |
| E08-02: ayrı `egitim_servis_bagi` migration'ı | `egitim_cekirdek` içinde doğrudan kolon | Dalga sırası E01'i önce kurduğu için |
| E02/E09/E10: `fa/teknikServis.ts` ortak; ayrı ZiyaretlerimPage/BenimIslerimPage | modül başına `fa/*.ts`; tek `BenimIslerimPage` | KD-02, E09-D01 |
| E05/E07: faaliyet `ISCILIK` | `SAHA` | KD-24 |
| E07: `stock_movements.unit_cost_try Numeric(14,2)` | `unit_cost Numeric(14,4)` | KD-25 |
| E13: `servis_birim_uyeligi` migration adı / E01-01 dosya listesi | `d0a000000001_ts_birim_ve_personel` | KD-26 |
| E14: `api/lokasyonlar.py` + `api/teknik_servis_ana_veri.py` | aynen; birim yönetimi ucu `a/personel.py` | – |
| E09-14: zaman takibi menü izni `rapor.gor` | `servis_rapor.gor` | KD-06 |

### 6.3 Ret edilenler ve kapsam dışı (kısa tablo)

Modül denetimlerinde "rejected" listesi boştur; aşağıdakiler revised kararlarla veya bu planla **kaldırılan** öneriler ve kapsam dışı konulardır.

| Öneri / konu | Karar | Neden |
|---|---|---|
| Servis işlerini `work_orders`'a `tur/birim` ile yazmak | RET | hak ediş/panel/altın kayıt kirlenir (00 §6.1-A) |
| Ayrı `customers`/`sites`/`personnel` tabloları | RET | ikinci kimlik kaynağı; hesap ve kullanıcı yeniden kullanılır |
| Güvenlik/haberleşme ekipmanını `devices`'a yazmak | RET | global `uq_devices_seri`, stok yaşam döngüsü |
| `MUSTERI_IMZASI` ek türü | RET | canlı `IMZA` var |
| KARGODA / TEST_KONTROL servis durumları | RET | atölye ayrıntısı atölye kaydında |
| `servis.ata`, `servis.musaitlik`, `bakim.uret`, `bakim.form`, `bakim.yeniden_ac`, `atolye.kapat`, `servis.tumunu_gor`, `lokasyon.gor`, `zaman.gor_tumu`, `timetracking.manage`, `team.view` izinleri | RET | mevcut izinlerle karşılanıyor; izin sayısını artırmadan |
| `KIRALAMA_OPERASYON`, `EGITIM_SORUMLUSU`, ayrı "TS_MUDUR/TEKNISYEN" adları | RET | `SERVIS_*` adları onaylı; IK rolü yeterli |
| `maintenance_part_reports` tablosu, `/parca-bildirimleri` | RET | E11 parça bileşeni (E04-21 revised) |
| E05 `POST /{id}/rma` köprüsü ve `rma_case_id` | RET | RMA cihaz zorunlu; dış servis izlenir |
| `service_alerts`'te denormalize birim/müşteri; KRITIK_ATANMAMIS SLA uyarısı | RET | kapsam JOIN ile; uyarı E01-18'in |
| Worker `saat-farki` görevi; `servis_iscilik_saat_maliyeti_tl` ayarı | RET | NTP konusu; maliyet E07'de |
| Paylaşılan `attachments`'a void kolonu | RET | 24 saat silme + EK_SIL olayı (K19) |
| Kalıcı "görüldü/ack" altyapısı (SLA dışı) | RET | uyarılar hesaplanır (canlı ilke) |
| CSV dışa aktarım | RET | canlı xlsx + formül koruması |
| Kontrol şablonlarının veriye taşınması (E04-22) | ERTELENDİ | kullanıcı yeni şablon verene kadar |
| Mobil uygulama, çevrimdışı mod, GPS konum kaydı | KAPSAM DIŞI | KVKK ve ürün kararı; 375 px duyarlı SPA |
| Logo CRM / Flowick entegrasyonu, muhasebe rücu bildirimi, TCMB kur entegrasyonu | KAPSAM DIŞI | kullanıcı kararı |
| Eski parça hareketlerinin göçü | KAPSAM DIŞI | açılış stoğu fiziksel sayımla |
| M12-07 (parça kullanımı raporu E12'de) | RET | E11'in (TS-196) |
| Mobilite UTC "bugün" kullanımları, `reports.py:81 DEGISTI` değeri | KAPSAM DIŞI (gözlem) | mobilite koduna dokunulmaz; ayrı değişiklik talebi |

---

## Ek A — Kaynak madde → TS eşlemesi

- **E01:** 01→TS-001/002/003/004/027 · 02→TS-018/020 · 03→TS-021 · 04→TS-022 · 05→TS-023 · 06→TS-024/174 · 07→TS-012/032 · 08→TS-036 · 09→TS-029 · 10→TS-193 (normalize_seri TS-011) · 11→TS-030 · 12→TS-025 · 13→TS-031 · 14→TS-035 · 15→TS-026 · 16→TS-020 · 17→TS-020/062 · 18→TS-037 · 19→TS-013 + DoD · 20→TS-027 · D01→TS-018/021 · D02→TS-004 · D03→KD-20 · D04→TS-028
- **E02:** 01→TS-018/040 · 02→TS-040 · 03→TS-041 · 04→TS-009 · 05→TS-042 · 06→TS-042 · 07→TS-043 · 08→TS-025 · 09→TS-015 · 10→TS-045 · 11→TS-047 · 12→TS-044 · 13→TS-046 · 14→TS-077 · 15→TS-045 · 16→TS-042/190 · 17→TS-048 · 18→TS-216 · 19→TS-049 · 20→TS-190 · 21→TS-190 · 22→TS-190 · 23→TS-190 · 24→TS-049 · 25→TS-049 · D01→TS-025 · D02→TS-027/042 · D03→TS-028 · D04→TS-175 · D05→TS-049
- **E03:** 01→TS-001/050 · 02→TS-018/050 · 03→TS-051 · 04→TS-172 · 05→TS-017 · 06→TS-052 · 07→TS-062 · 08→TS-056 · 09→TS-055 · 10→TS-011/172 · 11→TS-053 · 12→TS-011/054 · 13→TS-188/191 · 14→TS-191 · 15→TS-191 · 16→TS-012/057 · D01→TS-011 · D02→TS-050 · D03→TS-063 · D04→TS-050
- **E04:** 01→TS-001 · 02→TS-018/060 · 03→TS-173 · 04→TS-173 · 05→TS-018/061 · 06→TS-062 · 07→TS-062 · 08→TS-062 · 09→TS-064 · 10→TS-065 · 11→TS-066 · 12→TS-043 · 13→TS-064 · 14→TS-067/147 · 15→TS-036 · 16→TS-036 · 17→TS-052/064 · 18→TS-185 · 19→TS-185 · 20→TS-068 · 21→TS-133 · 22→ERTELENDİ · 23→TS-069 · D01→bu plan · D02→TS-065 · D03→TS-173 · D04→TS-060 · D05→TS-199
- **E05:** 01→TS-090 · 02→TS-093 · 03→TS-094 · 04→TS-095 · 05→TS-096 · 06→TS-097 · 07→TS-097 · 08→TS-098 · 09→TS-194 · 10→TS-098 · 11→TS-091 · 12–16→TS-090 · 17→TS-099 · 18→TS-092 · 19→TS-091 · 20→TS-098 · 21→TS-035/098 · 22→TS-090 · 23→TS-205 · 24→TS-194 · 25→TS-100 · 26→TS-001/091 · 27→TS-102 · 28→TS-194 · D01→TS-011/090 · D02→TS-018/090 · D03→TS-101
- **E06:** 01→TS-001 · 02→TS-110 · 03→TS-111 · 04→TS-112 · 05–07→TS-113 · 08→TS-114 · 09→TS-205 · 10→DoD · 11→TS-115 · 12→TS-116 · 13→TS-117 · 14→TS-114 · 15→TS-110 · 16→TS-118 · 17→TS-119 · 18→TS-111 · 19→TS-120 · 20→TS-195 · 21→TS-195 · 22→TS-121/195 · 23→TS-122 · D01→TS-111/131 · D02→TS-102 · D03→TS-110 · D04→TS-110 · D05→TS-111
- **E07:** 01→TS-216 · 02→TS-140 · 03→TS-140 · 04→TS-141 · 05→TS-142 · 06→TS-142 · 07→TS-143 · 08→TS-143 · 09→TS-215 · 10→TS-146 · 11→TS-146 · 12→TS-145 · 13→TS-148 · 14–16→TS-147 · 17→TS-145 · 18→TS-148 · 19→TS-140 · 20→TS-146 · 21→TS-149 · 22→TS-197 · 23→TS-216 · 24→TS-197 · 25→TS-215 · 26→TS-197 · D01→TS-141 · D02→TS-144 · D03→TS-213 · D04→TS-145 · D05→TS-013/080
- **E08:** 01→TS-001/003 · 02→TS-150 · 03→TS-150 · 04→TS-151 · 05→TS-151 · 06→TS-152 · 07→TS-155 · 08→TS-156 · 09→TS-157 · 10→TS-158 · 11→TS-159 · 12→TS-198 · 13→TS-159 · 14→TS-159 · 15→TS-156 · 16→TS-160/198 · 17→TS-156 · 18→TS-150 · 19→TS-156 · 20→TS-154 · 21→DoD (fabrika `t/fixtures/egitim.py`) · 22→TS-198 · 23→TS-153 · D01→bu plan · D02→TS-165 · D03→TS-190 · D04→TS-154
- **E09:** 01→TS-018/070 · 02→TS-071 · 03→TS-074 · 04→TS-077 · 05→TS-078 · 06→TS-072 · 07→TS-072 · 08→TS-072 · 09→TS-025/073 · 10→TS-073 · 11→TS-075 · 12→TS-076 · 13→TS-075 · 14→TS-189 · 15→TS-189 · 16→TS-011/071 · 17→TS-001/070 · 18→TS-013 · D01→TS-077 · D02→TS-075 · D03→TS-182 · D04→TS-081 · D05→TS-077
- **E10:** 01→TS-081 · 02→TS-200 · 03→TS-018/023/081 · 04→TS-084 · 05→TS-083 · 06→TS-200 · 07→TS-186 · 08→TS-082 · 09→TS-082 · 10→TS-081 · 11→TS-021 · 12→TS-011 · 13→TS-081 · 14→TS-001 · 15→TS-207 · 16→TS-085 · 17→TS-085 · 18→TS-081 · 19→TS-013 + DoD · D01→bu plan · D02→TS-081
- **E11:** 01→TS-130 · 02→TS-132 · 03→TS-132 · 04→TS-133 · 05→TS-001 · 06→TS-132 · 07→TS-134 · 08→TS-135 · 09→TS-136 · 10→TS-135 · 11→TS-135 · 12→TS-135 · 13→TS-136 · 14→TS-133 · 15→TS-136 · 16→TS-137 · 17→TS-137 · 18→TS-196 · 19→TS-138 · 20→DoD · 21→TS-208 · 22→TS-130 · 23→TS-131 · D01→TS-131 · D02→TS-196 · D03→TS-130
- **E12:** 01→TS-021 · 02→TS-018/021 · 03→TS-183 · 04→TS-183 · 05→TS-183 · 06→TS-026 · 07→TS-183 · 08→TS-012/181 · 09→TS-001/182 · 10→TS-181 · 11→TS-184 · 12→TS-185 · 13→TS-186 · 14→TS-187 · 15→TS-187 · 16→TS-188 · 17→TS-201 · 18→TS-201 · D01→TS-001/KD-06 · D02→bu plan · D03→TS-183 · D04→TS-181
- **E13:** 01→TS-006 · 02→TS-007 · 03→TS-008 · 04→TS-010 · 05→TS-008 · 06→TS-002 · 07→TS-009 · 08→TS-170 · 09→TS-165 · 10→TS-001 · 11→TS-003 · 12→TS-211 · 13→TS-212 · 14→TS-013 · 15→TS-213 · 16→TS-214 · 17→TS-199 · D01→TS-001 · D02→TS-004/005 · D03→TS-165
- **E14:** 01→TS-014 · 02→TS-015 · 03→TS-016 · 04→TS-015/020 · 05→TS-034 · 06→TS-015/042 · 07→TS-192 · 08→TS-017 · 09→TS-171/208 · 10→TS-062 · 11→TS-060/192 · 12→TS-192 · 13→TS-031 · 14→TS-090 · 15→TS-147 · 16→TS-015/047 · 17→TS-192 · 18→TS-184/188 · D01→TS-001/014 · D02→TS-011
