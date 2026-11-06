# E07 — Teklif ve İş Bazlı Maliyet: Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hedef: Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`)
> Girdiler: `analiz/02_moduller/_ozet/07_teklif_maliyet.json` (denetçinin onayladığı 26 madde), `07_teklif_maliyet_tasarim.md`, `07_teklif_maliyet_denetim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`, `03_cihaz_kutugu_entegrasyon.md` (biçim emsali).
> Kaynak koda dokunulmadı. "Canlı karşılık" satırları kod okunarak doğrulandı. Dosya:satır referansları `backend/app/` ve `frontend/src/` köklerine göredir.
> Madde kimlikleri `E07-NN` biçimindedir; her maddenin yanında eski analiz kimliği (`M07-xx`) verilir.

---

## 0. Özet

| | |
|---|---|
| Canlıda karşılık | **Teklif tarafında güçlü, maliyet tarafında yok.** Canlıda sürümlü teklif var (`models/quote.py:60-168`): her revizyon yeni sürüm açar ve eski sürüm kilitlenir. Fiyat ve KDV kalemde dondurulur, KDV kalem bazında hesaplanır (`services/quotes.py:32-62`). Eşiği aşan iskonto onaya düşer (`:65-68`). WeasyPrint ile PDF üretilir (`services/belgeler.py:147-200`, `templates/teklif.html`), SMTP ile gönderilir (`api/quotes.py:342-407`), karar elle ya da linkten verilir (`api/quotes.py:415-448`, `api/public_quotes.py`). Dönüşüm raporu (`services/reports.py:135-181`) ve tekliften sipariş oluşturma (`services/orders.py:64-127`) da çalışıyor. **Olmayanlar:** iç onay durumu (ONAYLANDI), iptal, durum makinesi, birim kapsamı, servis işine bağlantı, gönderim günlüğü, saatlik iç maliyet tarifesi, iş bazlı gelir/maliyet ve maliyet analizi. |
| Yeniden kullanılan | `quotes / quote_versions / quote_lines` (ayrı servis teklifi tablosu **AÇILMAZ**), `services/quotes.py` (hesap, sürüm, kalem dondurma), `belgeler.teklif_pdf` + `teklif.html`, `services/mail.py`, `public_quotes` (online kabul), `audit_logs` (teklif durum geçmişi için ayrı tablo AÇILMAZ), `attachments` (`"quotes"` zaten kayıtlı, `api/attachments.py:48`), görev panosu (`services/gorevler.py:49`), `services/export.py`, `services/uyarilar.py`, `services/settings.py` (`DEFAULTS`), `UserPermission` istisnası (`models/rbac.py:29-52`), `services/statemachine.py`. |
| Yeni tablo | `quote_sends` (gönderim günlüğü), `service_labor_rates` (tarihli birim saatlik iç maliyet), `service_order_financials` (iş bazlı gelir, diğer maliyet ve fatura devri; servis iş emriyle 1:1). |
| Canlı tablolara eklenecek nullable kolonlar | `quotes`: `birim`, `service_order_id`, `contact_id`, `submitted_by/at`, `cancelled_by/at`, `cancel_reason`. `quote_versions`: `approved_by/at`, `sent_channel`, `sent_note`. `quote_lines`: `service_order_id`, `description` alanı 300'den 500 karaktere genişler. `stock_movements`: `unit_cost_try` (Yedek Parça modülüyle ortak; o modül önce açarsa bu modül yalnız okur). |
| Bilinçli sapma (1 adet) | `ck_quote_durum` kısıtına `ONAYLANDI` ve `IPTAL` değerleri **yalnız ekleme** olarak girer. Mevcut değerlerin tamamı korunur, mevcut satırlar kısıtı geçmeye devam eder. Gerekçesi §1.3 ve kararlar listesindedir. |
| Yeni izinler | `teklif.onayla`, `maliyet.yaz`. `maliyet.gor` iznine sahip roller kümesi **DEĞİŞMEZ**. |
| Yeni durum makinesi | `TEKLIF`, `MAKINELER["teklif"]` altına eklenir. Yalnız birimli (teknik servis) tekliflerde zorlanır, satış teklif akışı aynen kalır. |
| Dokunulmayanlar | Satış teklif akışı (TASLAK → iskonto onayı → GONDERILDI → karar → sipariş), `public_quotes` jeton kuralları, `work_orders / work_order_items / settlements`, cihaz durum makinesi, stok EXCLUDE kısıtları, mevcut `TEKNIK_SERVIS` rolü, teklif numarası kalıbı `TKF{yıl}-{sıra}`. |

Kullanıcının eski sistemde bizzat doğruladığı işlevler korunur:
- **Tıklanabilir KPI kutuları:** teklif listesinde Onay Bekliyor, Müşteri Yanıtı Bekleyen, 3 Gün İçinde Dolacak ve Süresi Dolan kutuları (E07-18); maliyet analizinde Süre Eksik, Tarife Tanımsız ve Gelir Yok kutuları (E07-21). Kutuya tıklamak listeyi süzer.
- **Toplu işlem:** teklif listesinden çoklu seçimle Excel (E07-18); fatura devrinde toplu "Faturaya iletildi" işareti (E07-26); bakım bulgusundan toplu "Teklif hazırla", yani birden çok PB işi tek teklifte, kalem bazında servis işine bağlı (E07-14).
- **Excel dışa aktarım:** teklif listesi, maliyet analizi (müşteri kırılımı dahil) ve dönüşüm raporu (E07-18, E07-22, E07-24).
- **Cihaz başına PB iş emri:** bakım bulgusundan doğan teklif, kalem bazında ilgili PB işine (dolayısıyla tek ekipmana) bağlanır. "Teklif Sunulacak" uyarısı ve gelir aktarımı da PB işi bazında yürür (E07-14, E07-15, E07-16).

---

## 1. Veri modeli

### 1.1 Canlı teklif tablolarına eklenecek kolonlar (`models/quote.py`; yalnız nullable)

| Tablo.kolon | Tip | Not |
|---|---|---|
| `quotes.birim` | `String(12)` NULL | Değer `permissions.BIRIMLER` kodlarından biri olur. Kısıt `ck_quote_birim`: `birim IS NULL OR birim IN ('GUVENLIK','HABERLESME','POC','MOBILITE','ARAC_TAKIP')`. **NULL = satış teklifi** ve canlı akış aynen sürer. Birim doluysa teklif teknik servis teklifidir: onay akışı, `TEKLIF` makinesi ve birim kapsamı devreye girer. |
| `quotes.service_order_id` | FK `service_orders.id` `ON DELETE SET NULL`, NULL | Kaynak servis işidir (arıza, PB bulgusu ya da atölye). Aynı işe birden çok teklif bağlanabilir. İndeks: `ix_quote_servis_isi`. |
| `quotes.contact_id` | FK `contacts.id` `ON DELETE SET NULL`, NULL | Müşteri irtibatıdır. PDF'e basılır ve e-posta alıcısına varsayılan olarak gelir. Kişisel veridir. |
| `quotes.submitted_by` / `submitted_at` | FK `users.id SET NULL` / `DateTime(tz)` | Onaya gönderen kişi. Öz-onay yasağı (`ayar teklif_oz_onay_yasak`) bu alana ve `owner_id`'ye bakar. |
| `quotes.cancelled_by` / `cancelled_at` / `cancel_reason` | FK / `DateTime(tz)` / `String(300)` | İptal kaydıdır. Kısıt `ck_quote_iptal_neden`: `status <> 'IPTAL' OR cancel_reason IS NOT NULL`. |
| `quote_versions.approved_by` / `approved_at` | FK `users.id SET NULL` / `DateTime(tz)` | İç onay **sürüm bazında** tutulur. Revizyon yeni sürüm açtığı için onay da yeniden istenir. PDF'teki "Onaylayan" alanı buradan gelir. |
| `quote_versions.sent_channel` / `sent_note` | `String(16)` / `String(300)` | Gönderim kanalı: `EPOSTA`, `ELDEN`, `KARGO`, `HARICI_EPOSTA` ya da `DIGER`. Kısıt `ck_qv_gonderim_kanali` (NULL serbesttir). Elle gönderimde not zorunludur. |
| `quote_lines.service_order_id` | FK `service_orders.id SET NULL`, NULL | Kalemin ait olduğu servis işidir. Birden çok PB bulgusunu tek teklifte toplarken kullanılır. Boşsa kalem teklifin `service_order_id` değerine sayılır. İndeks: `ix_ql_servis_isi`. |
| `quote_lines.description` | `String(300)` → `String(500)` | Eski gereksinim 500 karakter istiyor. PG'de varchar genişletmek yalnız metadata değişikliğidir; tablo yeniden yazılmaz. `KalemIn.description` `max_length=500` olur. |

İndeks: `ix_quote_birim_durum_tarih (birim, status, created_at)`, sunucu tarafı filtre içindir (E07-19).

Python sabiti: `KALEM_TIPLERI` demetine `"ISCILIK"` eklenir (`models/quote.py:57`). `quote_lines.item_type` için DB CHECK'i yok, bu yüzden migration gerekmez. Ekranda kalem tipleri şöyle eşlenir: Parça = `URUN`, İşçilik = `ISCILIK`, Hizmet = `HIZMET`, Diğer = `SERBEST`.

### 1.2 Yeni tablolar

**`quote_sends`**: gönderim günlüğü. Sadece ekleme yapılır; düzenleme ya da silme ucu yoktur. `PkMixin, TimestampMixin, ActorMixin`.

| Kolon | Tip | Not |
|---|---|---|
| `quote_id` | FK `quotes.id` CASCADE | |
| `version_id` | FK `quote_versions.id` CASCADE | Gönderilen sürüm |
| `kanal` | `String(16)` | Kısıt `ck_qsend_kanal`: EPOSTA, ELDEN, KARGO, HARICI_EPOSTA, DIGER |
| `alicilar` | `ARRAY(String(254))` NULL | Yalnız EPOSTA için, en fazla 3 adres (`ck_qsend_alici_sayisi`: `cardinality(alicilar) <= 3`). Kişisel veridir ve KVKK anonimleştirmesine dahildir. |
| `cc` | `String(254)` NULL | Gönderenin e-postası |
| `sonuc` | `String(10)` | Kısıt `ck_qsend_sonuc`: `BASARILI` ya da `HATA` |
| `hata_ozeti` | `String(300)` NULL | Sınıflandırılmış özet tutulur (`SMTP_KAPALI`, `SMTP_BAGLANTI`, `SMTP_KIMLIK`, `SMTP_RED`). İstisna metni ve sunucu adresi **yazılmaz**; ayrıntı sunucu loguna gider. |
| `pdf_sha256` | `String(64)` NULL | Gönderilen PDF'in özeti (E07-09) |
| `notlar` | `String(300)` NULL | Elle gönderimde zorunludur (servis katmanı denetler) |

İndeks: `ix_qsend_teklif (quote_id)` ve `ix_qsend_kullanici_zaman (created_by, created_at)`. İkincisi hız sınırı sorgusu içindir (E07-25).

**`service_labor_rates`**: tarihli birim saatlik iç maliyet. `PkMixin, TimestampMixin, ActorMixin, VersionedMixin`. Silme yoktur: hatalı ileri tarihli satır, gerekçe yazılarak `valid_to = valid_from` yapılıp kapatılır.

| Kolon | Tip | Not |
|---|---|---|
| `birim` | `String(12)` | Kısıt `ck_iscilik_tarife_birim` |
| `valid_from` / `valid_to` | `Date` / `Date` NULL | Yarı açık aralık. Kısıt `ck_iscilik_tarife_aralik`: `valid_to IS NULL OR valid_to > valid_from`. |
| `hourly_cost` | `Numeric(12,2)` | Kısıt `ck_iscilik_tarife_pozitif`: `hourly_cost > 0`. **0 girilemez**; tarife yoksa sonuç "tanımsız" olur, sessizce sıfır yazılmaz. |
| `gerekce` | `String(300)` NULL | Geçmiş tarihli girişte zorunludur |

Kısıtlar:
- `ex_iscilik_tarife_cakisma`: `EXCLUDE USING gist (birim WITH =, daterange(valid_from, valid_to, '[)') WITH &&)`. `btree_gist` zaten kurulu (`alembic/env.py:32-39`).
- `uq_iscilik_tarife_acik`: `(birim) WHERE valid_to IS NULL` koşullu kısmi tekil indeks.

**`service_order_financials`**: iş bazlı gelir, diğer maliyet ve fatura devri; servis iş emriyle 1:1. `PkMixin, TimestampMixin, ActorMixin, VersionedMixin`.

| Kolon | Tip | Not |
|---|---|---|
| `service_order_id` | FK `service_orders.id` RESTRICT | Tekil, `uq_sof_is` |
| `gelir` | `Numeric(14,2)` NULL | **NULL = gelir kaydı yok.** 0 ile aynı şey değildir. `ck_sof_gelir_negatif`: `gelir IS NULL OR gelir >= 0`. |
| `gelir_kaynagi` | `String(16)` NULL | TEKLIF, ELLE, SOZLESME ya da UCRETSIZ_GARANTI (`ck_sof_gelir_kaynagi`). `ck_sof_gelir_kaynak_tutarli`: `(gelir IS NULL) = (gelir_kaynagi IS NULL)`. |
| `gelir_notu` | `Text` NULL | `ck_sof_gelir_notu`: `gelir_kaynagi NOT IN ('ELLE','UCRETSIZ_GARANTI') OR gelir_notu IS NOT NULL`. `ck_sof_ucretsiz_sifir`: `gelir_kaynagi <> 'UCRETSIZ_GARANTI' OR gelir = 0`. |
| `diger_maliyet` / `diger_maliyet_notu` | `Numeric(14,2)` NULL / `Text` | `ck_sof_diger_negatif`. Tutar varsa not zorunludur (`ck_sof_diger_notu`). |
| `fatura_iletildi_at` / `fatura_iletildi_by` / `fatura_notu` | `DateTime(tz)` / FK users / `String(300)` | E07-26 |

Bu tablonun **satırı yoksa** işin gelir ve maliyet girdisi de yoktur. Satır, ilk gelir girişinde ya da teklif kabulünde servis katmanında açılır (`get_or_create`). Aynı anda iki istek gelirse `uq_sof_is` ihlali 409'a döner ve istemci yeniden dener.

**`stock_movements.unit_cost_try`** (`Numeric(14,2)` NULL): yedek parça çıkışında dondurulan birim maliyettir. Değer şu sırayla bulunur: (a) ürünün son mal kabulündeki birim maliyeti (`purchase` satın alma satırı × kur), (b) seri takipli parçada `devices.landed_cost_try` (`models/device.py:133`), (c) hiçbiri yoksa NULL; bu durumda iş "parça maliyeti eksik" sayılır. Kolonun sahibi Yedek Parça modülüdür. Bu modül adı ve anlamı sabitler; hangi migration önce gelirse kolonu o açar.

### 1.3 Durum kısıtının genişletilmesi (bilinçli sapma)

```sql
-- upgrade (op.execute, elle)
ALTER TABLE quotes DROP CONSTRAINT ck_quote_durum;
ALTER TABLE quotes ADD CONSTRAINT ck_quote_durum CHECK (status IN
 ('TASLAK','ONAY_BEKLIYOR','ONAYLANDI','GONDERILDI','GORUNTULENDI','REVIZE_EDILDI',
  'KABUL','RED','SURESI_DOLDU','SIPARISE_DONUSTU','IPTAL'));
-- downgrade: veri kaybı docstring'de yazılır
UPDATE quotes SET status='TASLAK' WHERE status='ONAYLANDI';
UPDATE quotes SET status='RED', lost_reason=COALESCE(cancel_reason,'İptal') WHERE status='IPTAL';
-- ardından eski kısıt geri kurulur
```

Gerekçe: iç onay ve iptal, eski sistemin onaylı gereksinimidir (M07-02). Bunları ayrı bir "servis_durumu" kolonuyla ifade etmek iki ayrı durum alanı doğururdu; panel, rapor ve public uç bu ikisinden hangisine bakacağını bilemezdi. Değişiklik yalnız ekleme yapar: mevcut satırların hepsi geçerli kalır ve satış akışı yeni değerlere hiç ulaşmaz. `00_MIMARI_KURALLAR.md` §2'deki "mevcut CHECK'e dokunan migration yasak" kuralının amacı mobilite zincirini korumaktır; `quotes` bu zincirin dışındadır. Sapmanın sınırı şudur: hiçbir değer çıkarılmaz ve anlamı değiştirilmez.

### 1.4 Durum makinesi (`services/statemachine.py`)

```python
TEKLIF = StateMachine(
    ad="Teklif",
    baslangiclar=frozenset({"TASLAK"}),
    gecisler=_m(
        TASLAK=("ONAY_BEKLIYOR", "GONDERILDI", "IPTAL"),          # GONDERILDI yalnız satış (birimsiz) teklifte
        ONAY_BEKLIYOR=("TASLAK", "ONAYLANDI", "IPTAL"),           # TASLAK = geri çevir / iskonto onayı (satış)
        ONAYLANDI=("GONDERILDI", "TASLAK", "IPTAL"),              # TASLAK = onay geri alındı (düzenleme gerekti)
        GONDERILDI=("GORUNTULENDI", "KABUL", "RED", "REVIZE_EDILDI", "SURESI_DOLDU", "TASLAK", "IPTAL"),
        GORUNTULENDI=("KABUL", "RED", "REVIZE_EDILDI", "SURESI_DOLDU", "TASLAK", "IPTAL"),
        REVIZE_EDILDI=("GONDERILDI", "GORUNTULENDI", "KABUL", "RED", "SURESI_DOLDU", "IPTAL"),
        RED=("TASLAK", "REVIZE_EDILDI"),                           # revizyon
        SURESI_DOLDU=("TASLAK", "REVIZE_EDILDI"),
        KABUL=("SIPARISE_DONUSTU", "IPTAL"),                       # IPTAL yalnız teklif.onayla + neden
        SIPARISE_DONUSTU=(),
        IPTAL=(),
    ),
)
MAKINELER["teklif"] = TEKLIF
```

Kurallar:
- Geçişler tek yardımcıdan yapılır: `services/quotes.py: durum_degistir(db, teklif, hedef, *, user_id, neden=None, kanal=None)`. Bu fonksiyon önce `TEKLIF.dogrula()` çağırır, sonra `audit.log("quotes", "durum", old_value={"durum": eski}, new_value={"durum": hedef, "neden": ..., "kanal": ...})` yazar.
- **Birimli teklifte** her durum değişikliği bu yardımcıdan geçer.
- **Satış teklifinde** (birim NULL) mevcut uçlar (`api/quotes.py:278, 305, 353, 395`, `services/quotes.py:213, 236-241`, `services/orders.py:127`, `api/public_quotes.py:100`) bugünkü gibi doğrudan atamaya devam eder; yalnız geçmiş kaydı için yardımcıyı **doğrulamasız** modda çağırırlar. Sebebi şu: canlıda `karar` ucu `TASLAK → KABUL` geçişine izin veriyor (`api/quotes.py:415-448`) ve bunu kısıtlamak, kabul edilmiş satış akışını değiştirmek olurdu (bkz. Gözlemler).
- API yanıtına `sonraki_durumlar` eklenir (`api/rma.py:103` emsali); ön yüz eylem düğmelerini buradan çizer.
- Meta-test (`tests/unit/test_statemachine.py:8`) yeni makineyi otomatik sınar.

**"Süresi Doldu" hesaplanır, yazılmaz.** Teklif çıktısındaki `etkin_durum` şöyle belirlenir: durum GONDERILDI, GORUNTULENDI ya da REVIZE_EDILDI iken `valid_until < Clock.today` ise `SURESI_DOLDU` döner. Liste filtresi ve raporlar aynı ifadeyi kullanır. `services/quotes.py:193 suresi_dolanlari_isaretle` canlıda worker'a bağlı değil (`worker.py:120-125`); bu modül de bağlamaz (kararlar §K7).

### 1.5 İzinler ve roller (`permissions.py`)

```python
"teklif.onayla": ("Teklif", "Teknik servis teklifini iç onaydan geçirir veya geri çevirir; kabul edilmiş teklifi iptal eder"),
"maliyet.yaz":  ("Özel", "Birim saatlik iç maliyet tarifesi, iş bazlı gelir ve diğer maliyet girer"),
```

| Rol | Teklif | Maliyet | Kapsam |
|---|---|---|---|
| `SERVIS_YONETICI` (yeni) | `teklif.gor`, `teklif.yaz`, `teklif.onayla`, `teklif.iskonto_onayla` | — (aşağıdaki nota bakın) | TUMU |
| `SERVIS_SEF` (yeni) | `teklif.gor`, `teklif.yaz` | — | KENDI_BIRIMI |
| `ATOLYE` (yeni) | `teklif.gor`, `teklif.yaz` | — | KENDI_BIRIMI |
| `SERVIS_TEKNISYEN` (yeni) | — (fiyat görmez) | — | KENDI_BIRIMI |
| `ADMIN` | Tümü (otomatik) | `maliyet.gor`, `maliyet.yaz` | TUMU |
| `YONETIM` | `.gor` izinleri otomatik | `maliyet.gor` (mevcut) | TUMU |
| `MUHASEBE_DESTEK`, `SATIS_MUDURU` | Mevcut liste değişmez | `maliyet.gor` (mevcut) | TUMU |

Notlar:
- `maliyet.gor` iznine sahip roller kümesi **değişmez**: ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK, YONETIM (`permissions.py:138, 243, 247`). Unit test (`tests/unit/test_permissions.py:21-26`) yeşil kalır.
- Teknik servis müdürü ve maliyet sorumlusu `maliyet.gor` ile `maliyet.yaz` izinlerini **kişi bazlı `UserPermission(allow=True, gerekce=...)`** istisnasıyla alır (`models/rbac.py:29-52`). Eski sistemde de `finance.costs.manage` yalnız Admin'deydi.
- `maliyet.yaz` ilk sürümde yalnız ADMIN rolünde bulunur. "Her izin en az bir rolde" testi (`test_permissions.py:43-46`) böylece geçer.
- **Teklif tutarı satış fiyatıdır ve `teklif.gor` ile görünür** (canlı davranış). İç maliyet, işçilik, fark ve gelir alanları `maliyet.gor` ister.

### 1.6 Ayarlar (`services/settings.py` `DEFAULTS`)

| Anahtar | Varsayılan | Kullanım |
|---|---|---|
| `teklif_oz_onay_yasak` | `True` | M07-02 |
| `servis_teklif_onay_zorunlu` | `True` | Birimli teklif ONAYLANDI olmadan gönderilemez |
| `teklif_kdv_oranlari` | `"0,0.01,0.10,0.20"` | Birimli teklifte KDV beyaz listesi |
| `teklif_sure_uyari_gun` | `3` | E07-18 |
| `teklif_azami_alici` | `3` | E07-06 |
| `teklif_gonderim_dakika_limiti` | `10` | E07-25 |
| `servis_teklif_sunulacak_is_gunu` | `2` | E07-15 |

### 1.7 Dosyalar

```
backend/app/models/quote.py                          (EKLEME: kolonlar, QuoteSend, ck_ genişletmesi)
backend/app/models/teknik_servis.py                  (EKLEME: ServiceLaborRate, ServiceOrderFinancial) + models/__init__.py
backend/app/services/quotes.py                       (EKLEME: durum_degistir, onaya_gonder, onayla, geri_cevir, elle_gonderildi,
                                                       iptal, taslak_guncelle, teklif_kapsami, etkin_durum, net_tutar_try)
backend/app/services/teknik_servis/maliyet.py        (iscilik_hesapla, parca_maliyeti, is_finansi, analiz, gelir_aktar)
backend/app/services/teknik_servis/kapsam.py         (RBAC+birim adımından: kapsam_birim, birim_disinda_mi)
backend/app/services/statemachine.py                 (EKLEME: TEKLIF)
backend/app/services/mail.py                         (EKLEME: cc / coklu alıcı kwarg'ları — geriye uyumlu)
backend/app/services/belgeler.py, templates/teklif.html (EKLEME: onaylayan, KDV dökümü, sayfa x/y, irtibat)
backend/app/services/reports.py                      (EKLEME: teklif_donusumu(birim=, kapsam), yeni servis_maliyet raporu)
backend/app/services/uyarilar.py, services/settings.py, services/kvkk.py (EKLEME blokları)
backend/app/api/quotes.py                            (EKLEME: yeni eylem uçları, kapsam yardımcıları, sayfala, xlsx)
backend/app/api/servis_maliyet.py                    (YENİ: /api/teknik-servis/maliyet ..., /api/teknik-servis/fatura-devri)
backend/app/api/attachments.py                       (EKLEME: _kapsam'a "quotes")
backend/app/api/orders.py                            (EKLEME: birimli teklif siparişe dönüştürülemez → 409)
backend/app/permissions.py                           (EKLEME: teklif.onayla, maliyet.yaz, yeni rollere atama)
backend/alembic/versions/<rev>_servis_teklif_maliyet.py
backend/tests/integration/test_servis_teklif_akisi.py, test_servis_teklif_kapsam.py, test_servis_teklif_gonderim.py,
      test_servis_maliyet.py, test_servis_fiyat_sizintisi.py; tests/unit/test_teklif_makinesi.py (meta-test zaten var)
frontend/src/api/teklifler.ts (yeni modül API dosyası), pages/TekliflerPage.tsx, pages/TeklifFormu.tsx (EKLEME),
      pages/ServisMaliyetPage.tsx, pages/FaturaDevriPage.tsx (YENİ), components/AppLayout.tsx MENU, main.tsx rotalar
```

### 1.8 Migration

`make makemigration m="servis_teklif_maliyet"`. Bu migration Servis İş Emri çekirdek migration'ından **sonra** gelir, çünkü `service_orders` FK'si ona bağlıdır. Docstring'de şunlar yazılır:
- NEDEN ayrı servis teklifi tablosu açılmadığı,
- `ck_quote_durum` sapması,
- downgrade'de ONAYLANDI ve IPTAL değerlerinin eşlenmesi,
- `description` alanının 300 karaktere kesilmesiyle oluşan veri kaybı.

İçerik:
- `op.add_column` ile nullable kolonlar,
- `op.create_check_constraint`,
- `ck_quote_durum` için `op.execute` ile drop ve create,
- yeni tablolar; `ex_iscilik_tarife_cakisma` autogenerate biçiminde, ancak `daterange` ile,
- kısmi indeksler.

Doğrulama: head→base→head testi (`tests/migration/test_migration_zinciri.py`) ve tek head kuralı. EXCLUDE sayısı +1 artar; testteki beklenen sayı güncellenir.

---

## 2. Maddeler

### E07-01 · Yetkisiz isteğe tutarlı 403 JSON — P1 · S · (M07-D01, .NET'e özgü; özü kabule taşındı)
- **Canlı durum: VAR.** `require_permission` her uçta `HTTPException(403, "...")` döndürüyor, yanıt JSON (`api/deps.py:79-97`). 500 üreten `Forbid()` benzeri bir yol yok.
- **Yaklaşım:** Kod değişikliği yok. Yeni uçların hepsi `Okuyucu/Yazici/Onaylayici/MaliyetOkuyucu/MaliyetYazici` takma adlarıyla korunur.
- **Kabul:** `teklif.gor` izni olmayan rol (ör. `DEPO`) `GET /api/teklifler` isteğine 403 ve JSON `detail` alır; sunucu logunda istisna oluşmaz. Aynı test her yeni uç için parametrik koşar (E07-23).
- **Bağımlılık:** —
- **Canlı risk:** Yok.

### E07-02 · Teklif kayıt kapsamı ve birim erişim kontrolü (kapsam dışı → 404, yazma olmaz) — P1 · S · (M07-14)
- **Canlı durum: KISMEN.** `listele` ve `getir` yalnız `KENDI_MUSTERILERI` için `owner_id` filtresi uyguluyor (`api/quotes.py:178, 192`). `revize_et`, `iskonto_onayla`, `teklif_pdf`, `gonder` ve `karar` (`api/quotes.py:252-448`) **hiç kapsam kontrolü yapmıyor**: satış temsilcisi başkasının teklifini kimlik numarasıyla revize edebiliyor, gönderebiliyor ya da kabul ettirebiliyor. Ek dosya kapsamı da yalnız `accounts` için var (`api/attachments.py:91-114`). Birim kavramı yok.
- **Yaklaşım:**
  - `services/quotes.py` içine iki yardımcı yazılır:
    - `teklif_kapsami(stmt, user)`: `KENDI_MUSTERILERI` için `Quote.owner_id == user.id` (canlı kural aynen korunur); `KENDI_BIRIMI` için `Quote.birim.in_(user_birimleri)`, böylece **birimsiz satış teklifleri birimli kullanıcıya görünmez**; TUMU için koşulsuz.
    - `teklif_kapsam_disinda_mi(user, t) -> bool`.
  - `api/quotes.py` içinde `_teklif_al(db, id, user)` yardımcısı `db.get` → `is_deleted` → kapsam sırasıyla çalışır ve kapsam dışında 404 döndürür. **Tüm tek kayıt uçları**, mevcut beşi dahil, bu yardımcıyı kullanır; kontrol yazmadan ÖNCE yapılır.
  - Birim değişikliği PATCH/PUT'ta yalnız kullanıcının kendi birimine yapılabilir; aksi halde 403 (`api/accounts.py:441-447` emsali). `service_order_id` verildiyse teklifin birimi işin biriminden alınır ve değiştirilemez.
  - `api/attachments.py:_kapsam` fonksiyonuna `"quotes"` dalı eklenir; aynı yardımcıyı kullanır.
  - `api/orders.py:324 tekliften` de `_teklif_al` ile çağrılır.
- **Kabul:**
  1. Yalnız HABERLESME birimine üye `SERVIS_SEF`, GÜVENLİK teklifi için `GET`, `POST /onayla`, `/karar`, `/revize`, `/pdf` ve `/ekler` isteklerinin hepsinde 404 alır; `db.refresh` sonrasında durum, sürüm ve kalemler değişmemiştir.
  2. `SATIS` kullanıcısı başkasının teklifine `POST /revize` ve `/gonder` gönderince 404 alır (canlıdaki açık kapanır).
  3. Liste ve `X-Toplam-Kayit` yalnız kendi biriminin tekliflerini sayar.
  4. `test_teklif.py` testleri yeşil kalır.
- **Bağımlılık:** RBAC+birim adımı (`BIRIMLER`, `SCOPE_OWN_UNITS`, `user_units`, `kapsam.py`).
- **Canlı risk:** Orta-düşük. `SATIS` rolünün başkasının teklifini değiştirebildiği yol kapanır. Bu bir güvenlik düzeltmesidir; ancak satış müdürü ekibin teklifini düzeltiyorsa etkilenmez, çünkü SATIS_MUDURU kapsamı TUMU. Sürüm notunda belirtilir. Birimsiz satış teklifleri ve TUMU kapsamlı roller değişmez.

### E07-03 · Sunucu doğrulaması ve satır bazlı yuvarlama tutarlılığı — P1 · S · (M07-07)
- **Canlı durum: KISMEN.**
  - Adet `>0`, fiyat `>=0`, iskonto `0-100`, KDV `0-1` sınırları var (`api/quotes.py:25-38`). Ürünsüz kalemde açıklama zorunlu (`services/quotes.py:179-180`). Toplamlar sunucuda hesaplanıyor (`:32-62`).
  - Eksik olanlar: KDV beyaz listesi, geçmiş `valid_until` reddi, kalem sayısı sınırı (0 ve 200), servis işi doğrulaması, döviz teklifinde kur zorunluluğu.
  - **Olası yuvarlama hatası:** `unit_price` ondalık basamak sınırı taşımıyor. 3 ondalıklı fiyat (33,333) DB'de `Numeric(14,2)` olarak 33,33 saklanıyor, ama `versiyon_hesapla` kimlik haritasındaki nesneden 33,333 değeriyle hesap yapıyor (`services/quotes.py:38-59`). Kod okumasına göre 3 × 33,333 kalemde `subtotal=100,00`, `discount_total=0,01`, kalem toplamı ise 99,99 çıkar; yani iskontosuz teklifte 1 kuruş "iskonto" görünür. Test ile doğrulanmalı.
- **Yaklaşım:**
  1. `kalem_alanlari` (`services/quotes.py:148`) `unit_price` ve `qty` değerlerini `yuvarla()` ile 2 haneye indirir. Satış ve servis tekliflerinde aynı davranır; DB zaten 2 hane saklıyor, yani veri değişmez, yalnız hesap DB ile hizalanır.
  2. `KalemIn.description` `min_length=1, max_length=500` olur.
  3. `TeklifIn.kalemler` ve `RevizyonIn.kalemler` için `max_length=200`.
  4. **Birimli teklifte** ek kurallar (servis katmanında `TeklifHatasi(ValueError)` → 400):
     - `vat_rate` değeri `teklif_kdv_oranlari` listesinde olmalı;
     - `valid_until >= Clock.today`;
     - `currency != "TRY"` ise `fx_rate` zorunlu;
     - `service_order_id` verildiyse iş var olmalı, silinmemiş olmalı, kullanıcının müşteri ve birim kapsamında olmalı, müşterisi teklifin müşterisiyle aynı olmalı; aksi halde tek tip 400 "Servis işi bulunamadı veya bu teklife bağlanamaz" (varlık sızdırılmaz);
     - kalem `service_order_id` için de aynı kural geçerli;
     - "Onaya gönder" anında en az 1 kalem şartı.
  5. Pydantic şema hataları canlı kuralla 422 döner; servis kuralı hataları 400 döner. Kabul kriteri "asla 500" olarak okunur.
- **Kabul:**
  1. Negatif adet, %150 iskonto, `vat_rate=0.37` (birimli), boş açıklama, geçmiş `valid_until` (birimli), var olmayan ya da başka birimdeki servis işi isteklerinin her biri 400 veya 422 döner, 500 dönmez ve `quotes` satır sayısı değişmez.
  2. 3 × 33,333 TL kalemde her satır 33,33; `subtotal = Σ line_total + discount_total`; `discount_total = 0,00`; `grand_total = subtotal - discount_total + vat_total`.
  3. 201 kalemli istek 422 döner.
- **Bağımlılık:** E07-02.
- **Canlı risk:** Düşük. 2 hane yuvarlama satış tekliflerinin hesabını DB'de zaten saklanan değerle hizalar. KDV beyaz listesi ve geçmiş tarih kuralı **yalnız birimli** tekliflerde uygulanır (bkz. kararlar).

### E07-04 · İç onay akışı, durum makinesi, durum geçmişi ve teklif detay ekranı — P1 · M · (M07-02)
- **Canlı durum: KISMEN.**
  - `ONAY_BEKLIYOR` yalnız iskonto eşiği aşıldığında `gonder` ucunun yan etkisi olarak oluşuyor (`api/quotes.py:352-359`). Onay `iskonto_onayla` ile yapılıyor (`:293-317`) ve bunda öz-onay kontrolü yok.
  - ONAYLANDI ve IPTAL durumları yok. Teklif makinesi yok (`services/statemachine.py:189` `MAKINELER` içinde teklif bulunmuyor).
  - `karar` ucu her durumdan KABUL/RED'e izin veriyor (`api/quotes.py:415-448`; `services/quotes.py:218-245` önceki durumu denetlemiyor).
  - Geçmiş yalnız `audit_logs` içinde dağınık eylemler olarak duruyor (olustur, revize, gonder, karar, iskonto.onayla); kayıt bazlı geçmiş ucu yok.
  - Detay ekranı Drawer olarak var (`pages/TekliflerPage.tsx:489-634`).
- **Yaklaşım:** §1.3 kısıt genişletmesi, §1.4 makine, §1.5 izinler. Servis katmanındaki fonksiyonlar (hepsi `durum_degistir` üzerinden, hepsi `flush`, commit yok):
  - `onaya_gonder(db, t, user, beklet=False)`: yalnız birimli teklif, TASLAK → ONAY_BEKLIYOR. `submitted_by/at` yazılır. En az 1 kalem gerekir. `beklet=True` ise E07-14 beklemesi açılır.
  - `onayla(db, t, user, clock)`: ONAY_BEKLIYOR → ONAYLANDI. Ayar `teklif_oz_onay_yasak` açıksa ve `user.id in (t.owner_id, t.submitted_by)` ise `TeklifYetkiHatasi` → 403. Sürüme `approved_by/at` yazılır. İskonto eşiği aşılmışsa `discount_approved_by/at` da doldurulur (tek onay, kararlar §K4).
  - `geri_cevir(db, t, user, neden)`: ONAY_BEKLIYOR veya ONAYLANDI → TASLAK. `neden` en az 5 karakter, aksi halde 400.
  - `iptal(db, t, user, neden)`: neden zorunlu. KABUL durumundan iptal yalnız `teklif.onayla` iznine sahip kullanıcı içindir ve E07-16 geliri geri alır. SIPARISE_DONUSTU durumundan iptal 409.
  - `gonder` ve `elle_gonderildi`: birimli teklifte `servis_teklif_onay_zorunlu` açıkken durum ONAYLANDI değilse 409 "Teklif onaylanmadan gönderilemez".
  - `karar`: birimli teklifte `TEKLIF.dogrula`; TASLAK → KABUL 409. Ret nedeni zorunluluğu zaten var (`api/quotes.py:427-428`).
- **API uçları** (hepsi `/api/teklifler/{id}/...`, `_teklif_al` + kapsam): `POST onaya-gonder` (Yazici), `POST onayla` (`Annotated[User, Depends(require_permission("teklif.onayla"))]`), `POST geri-cevir` (Onaylayici, gövdede `neden`), `POST iptal` (Yazici; KABUL ise gövdede `teklif.onayla` denetimi `_izin`), `GET gecmis` (Okuyucu). `gecmis` ucu `audit_logs WHERE entity='quotes' AND entity_id=:id` kayıtlarını `users.full_name` ile birleştirip döndürür; durum, neden, kanal ve sürüm bilgisini içerir. Ayrı `quote_status_history` tablosu AÇILMAZ (E03-03 kararıyla tutarlı). `TeklifOut` alanlarına `birim`, `service_order_id`, `contact_id`, `etkin_durum`, `sonraki_durumlar`, `submitted_by_ad`, `approved_by_ad`, `cancel_reason` eklenir.
- **Ön yüz:** `TekliflerPage` Drawer'ı:
  - Başlıkta durum etiketi ve `etkin_durum`;
  - eylem düğmeleri `sonraki_durumlar` ve `yetkili()` ile çizilir (Onaya Gönder, Onayla, Geri Çevir, Gönder, Elle Gönderildi, Kabul/Ret, Revize, İptal); neden isteyen eylemler `Modal` + `Input.TextArea` (zorunlu) açar;
  - "Geçmiş" sekmesi `Timeline`, her satırda kim, ne zaman, eski → yeni durum ve neden;
  - "Sürümler" sekmesinde eski sürümler salt okunur ve "Revize Edildi" etiketli;
  - `EkYukleyici entity="quotes"` ve `KayitGorevleri`.
- **Kabul:**
  1. Birimli teklifte TASLAK → `/karar` (kabul) 409 döner.
  2. Ayar açıkken hazırlayan kişinin `/onayla` isteği 403; ayar kapalıyken 200.
  3. Neden boş `/geri-cevir` ve `/karar` (ret) istekleri 400.
  4. `SERVIS_SEF` `/onaya-gonder` çağırabilir (200), `/onayla` çağıramaz (403).
  5. Her geçiş `/gecmis` yanıtında eski/yeni durum, kullanıcı ve nedenle görünür.
  6. Gönderilmiş, `valid_until` dünde kalan teklif `etkin_durum = SURESI_DOLDU` döner, `status` alanı değişmez.
  7. Satış teklifinde canlı testler (`tests/integration/test_teklif.py`) değişmeden yeşildir.
  8. `test_statemachine` meta-testi TEKLIF makinesini de sınar.
- **Bağımlılık:** E07-01, E07-02; RBAC+birim adımı.
- **Canlı risk:** Düşük. Yeni durumlara yalnız yeni uçlarla ve yalnız birimli teklifte ulaşılır. `ck_quote_durum` değişikliği yalnız ekleme yapar. Dashboard'daki bekleyen teklif sayısı (`services/reports.py:85-95`) ONAYLANDI ve IPTAL durumlarını saymaz; bu doğrudur.

### E07-05 · SMTP yokken "Elle gönderildi" işareti (kanal + not zorunlu) — P1 · S · (M07-06a)
- **Canlı durum: KISMEN.** SMTP ayarı yoksa `gonder` ucu 503 `MailKapali` veriyor (`services/mail.py:31-34`, `api/quotes.py:390-391`) ve teklif "gönderildi" yapılamıyor. Karar tarafında `kanal="ELLE"` var (`api/quotes.py:435`), ama gönderim tarafında yok.
- **Yaklaşım:** `POST /api/teklifler/{id}/elle-gonderildi` (Yazici + kapsam), gövde `{kanal: "ELDEN"|"KARGO"|"HARICI_EPOSTA"|"DIGER", not: str (min 3, max 300)}`. Servis `elle_gonderildi` şunları yapar:
  - E07-04 onay kuralını denetler;
  - `v.sent_at = clock.now()`, `v.is_locked = True`, `v.sent_channel`, `v.sent_note` alanlarını yazar;
  - durumu GONDERILDI yapar (`durum_degistir`);
  - `quote_sends` tablosuna `sonuc='BASARILI'` satırı ve gönderim anındaki PDF'in `pdf_sha256` değerini yazar (E07-09);
  - `audit` kaydını `gonder` eylemiyle, `kanal` bilgisiyle düşer.

  Satış tekliflerinde de kullanılabilir; makine yalnız birimli teklifte zorlanır. Ön yüz: SMTP 503 dönünce "Elle gönderildi olarak işaretle" bağlantısı gösterilir.
- **Kabul:**
  1. SMTP ayarı boşken birimli ve ONAYLANDI durumundaki teklif `/elle-gonderildi` ile GONDERILDI olur; geçmişte kanal ve not görünür; `quote_sends` tablosunda 1 satır vardır.
  2. Kanal boş ya da geçersizse 422; not boşsa 400.
  3. ONAYLANDI olmayan birimli teklifte 409.
  4. Sonrasında public link karar kabul eder (`sent_at` dolu, `api/public_quotes.py:76-83`).
- **Bağımlılık:** E07-04.
- **Canlı risk:** Yok (yeni uç).

### E07-06 · E-posta yeniden gönderim, en fazla 3 alıcı, gönderene CC, genel hata mesajı, gönderim geçmişi — P2 · S · (M07-06b)
- **Canlı durum: KISMEN.**
  - `gonder` ucu tek alıcıya gönderiyor (`api/quotes.py:337-340`); alıcı biçimi doğrulanmıyor, CC yok.
  - Gönderim günlüğü yok; yalnız `audit` kaydı var (`:396-405`).
  - Hata mesajı istisna metnini, sunucu adını ve portu kullanıcıya döndürüyor (`services/mail.py:56-59`).
  - Aynı teklifin ikinci gönderimi mümkün ama kayıt bırakmıyor.
- **Yaklaşım:**
  - `services/mail.py: gonder(..., alici: str | list[str], cc: list[str] | None = None)` olarak genişler; kwarg eklemesi geriye uyumludur ve hak ediş çağrıları değişmez.
  - `GonderIn` şeması: `alicilar: list[str]`, `min_length=1`, `max_length=ayar teklif_azami_alici` (servis denetler); her adres `pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"`, `max_length=254`; `mesaj` ise `max_length=2000`. Alıcı verilmezse sırayla `contact.email` ve `musteri.email` kullanılır.
  - CC'ye `user.email` eklenir (varsa).
  - GONDERILDI veya GORUNTULENDI durumunda yeniden gönderim serbesttir: durum değişmez, `quote_sends` tablosuna yeni satır eklenir.
  - Hata durumunda `MailKapali` yakalanır, ayrıntı `logger.warning` ile sunucu loguna yazılır; kullanıcıya "E-posta gönderilemedi. Parametreler → Bildirim ayarlarını kontrol edin veya 'Elle gönderildi' kullanın." döner (503). Aynı transaction'da `quote_sends(sonuc='HATA', hata_ozeti=<sınıf>)` satırı **commit edilir**; böylece başarısız deneme de görünür, teklif durumu ise değişmez.
  - `GET /api/teklifler/{id}/gonderimler` (Okuyucu + kapsam).
  - Ön yüz: Drawer'da "Gönderimler" sekmesi (tarih, kanal, alıcılar, sonuç, PDF özeti) ve gönderim penceresinde etiket biçimli alıcı girişi (`Select mode="tags"`, en fazla 3).
- **Kabul:**
  1. İkinci gönderim `quote_sends` tablosunda ikinci satırı oluşturur.
  2. `"abc@"` adresi 422 döner.
  3. Dört alıcı 400 döner.
  4. SMTP hatasında yanıt gövdesinde istisna metni ve SMTP sunucu adı bulunmaz (test `smtplib.SMTP` sahtesiyle `OSError` fırlatır); `quote_sends.sonuc='HATA'` kaydı oluşur.
  5. Gönderen kullanıcının e-postası CC başlığında yer alır.
- **Bağımlılık:** E07-05.
- **Canlı risk:** Düşük. `mail.gonder` imzası geriye uyumlu genişler; hak ediş gönderimi aynı kalır. Hak ediş hata mesajındaki sızıntı bu modülün kapsamı dışında bırakılır (Gözlem G4).

### E07-07 · PDF: tüm kalemler, çok sayfa, Türkçe karakter, satır sarma, satır net tutarı, "Sayfa x/y" — P1 · M · (M07-05a)
- **Canlı durum: KISMEN.**
  - Var olanlar: tüm kalemler döngüyle basılıyor (`templates/teklif.html:196-204`); başlık her sayfada tekrarlanıyor (`:128`); Türkçe karakter için `latin-ext` alt kümeleri ve ₺ aralığı düzeltilmiş (`:28-84`); satır tutarı iskonto sonrası net (`line_total`, `services/belgeler.py:181`); açıklama hücresi `nowrap` değil, dolayısıyla sarıyor; PDF motoru WeasyPrint (`services/pdf.py`).
  - Eksikler: "Sayfa x/y" yok (`@page { margin: 0 }`, `:86`); 500 karakterlik açıklama sığmıyor (kolon 300); uzun kelimede (seri no, URL) taşma riski var.
- **Yaklaşım:**
  - `teklif.html` içine `@page { size: A4; margin: 0 0 10mm 0; @bottom-right { content: "Sayfa " counter(page) "/" counter(pages); font-size: 7.5pt; margin-right: 12mm; } }` eklenir (WeasyPrint destekler); `td.desc { overflow-wrap: anywhere; }`.
  - `description` kolonunun 500 karaktere genişlemesi §1.1'de.
  - Satır net toplamı ile `Ara Toplam − İskonto` eşitliğini E07-03 yuvarlaması sağlar.
  - Test: `pypdf` geliştirme bağımlılığı olarak eklenir. PDF metni çıkarılır; 40 kalemin açıklamaları ve "Sayfa 1/2", "Sayfa 2/2" metinleri aranır; `PdfReader(strict=True)` hatasız açılmalıdır (`qpdf --check` yerine geçer; CI'da qpdf yok).
- **Kabul:**
  1. 40 kalemli teklifte 40 açıklama da PDF metninde bulunur ve "Sayfa x/y" doğru basılır.
  2. `Σ line_total == subtotal − discount_total` kuruşu kuruşuna tutar (servis seviyesinde test).
  3. "Şişli İletişim Çözümleri – Güç Kaynağı" metni aynen çıkarılır (`ş`, `İ`, `–`).
  4. 500 karakterlik açıklama sayfa genişliğini aşmaz (tablo genişliği sabit, satır sarılır).
  5. `pypdf` katı modda hatasız açar.
- **Bağımlılık:** E07-03.
- **Canlı risk:** Düşük. Şablon satış teklifiyle ortaktır; sayfa altı numarası satış PDF'ine de eklenir. Bu bir iyileştirmedir ve yerleşim değişikliği yalnız alt kenar boşluğudur. Kullanıcının "sade form" kararına (`teklif.html:2-21`) uyulur, yeni renk ya da kutu eklenmez.

### E07-08 · Kurumsal PDF içeriği: firma, logo, revizyon no, hazırlayan/onaylayan, ayardan şartlar, KDV oranı dökümü — P2 · S · (M07-05b)
- **Canlı durum: KISMEN.**
  - Var olanlar: firma künyesi ayardan (`services/belgeler.py:119-137`); logo (`teklif.html:150`); "rev n" (`:158`); hazırlayan (`belgeler.py:149, 169`); şartlar ayardan (`:194`).
  - Eksikler: onaylayan, KDV oranı bazında döküm, irtibat kişisi.
- **Yaklaşım:**
  - `teklif_baglami` sözlüğüne şu alanlar eklenir:
    - `onaylayan` (`versiyon.approved_by` → `full_name`, yoksa anahtar yok),
    - `kdv_dokumu = [{oran: "%20", matrah, kdv}]` (kalem netleri oran bazında gruplanır, `yuvarla`),
    - `irtibat` (`contact.full_name`, telefon, e-posta),
    - `teklif_no_gosterim = f"{quote_no}-R{version_no-1}"` (yalnız `version_no > 1` ise).
  - Şablonda "SATIŞ VERGİSİ" satırı oran başına satırlara bölünür, "Onaylayan" alanı hazırlayanın altına konur, irtibat müşteri bloğuna eklenir.
  - Logo dosyası tek kaynaktan gelir (`brand_dir`).
- **Kabul:**
  1. %20 ve %10 kalemli teklifte iki KDV satırı vardır ve toplamları `vat_total` değerine eşittir.
  2. Onaylı teklifte onaylayanın adı basılır; onaysız satış teklifinde alan boş kalır.
  3. Şartlar `teklif_ticari_sartlar` ayarı değişince yeni PDF'te değişir, gönderilmiş sürümün özeti (E07-09) değişmez.
  4. R1 sürümünde `TKF2026-00012-R1` görünür.
- **Bağımlılık:** E07-07, E07-04.
- **Canlı risk:** Düşük. Satış PDF'ine de KDV dökümü ve onaylayan alanı eklenir (onaylayan yalnız doluysa basılır).

### E07-09 · Gönderilen PDF'in SHA-256 özetinin kaydı — P3 · S · (M07-05c)
- **Canlı durum: YOK.** Ek dosyalarda `sha256` hesabı var (`services/storage.py`, ek yüklemede kullanılıyor); teklif gönderiminde yok.
- **Yaklaşım:** `gonder`, `elle_gonderildi` ve yeniden gönderim uçları PDF'i bir kez üretir, `hashlib.sha256(pdf).hexdigest()` değerini `quote_sends.pdf_sha256` alanına yazar. E-postada aynı bayt dizisi ekli gider. Elle gönderimde, gönderim anında üretilen PDF'in özeti yazılır.
- **Kabul:**
  1. Her `quote_sends` satırında 64 karakterlik özet bulunur.
  2. E-posta ekindeki baytların SHA-256 değeri kayıttakiyle aynıdır (sahte SMTP ile test).
- **Bağımlılık:** E07-06.
- **Canlı risk:** Yok.

### E07-10 · Maliyet analizinde eksik veri ayrımı (durum alanları, null değerler, yalnız tam işler toplama girer) — P1 · S · (M07-09)
- **Canlı durum: YOK.** Canlıda servis işi, süre kaydı, tarife ve iş geliri yok. Benzer ilke yalnız stok raporunda var: maliyeti bilinmeyen cihaz sayısı ayrıca veriliyor (`services/reports.py:61-71`).
- **Yaklaşım:** `services/teknik_servis/maliyet.py`:
  - `is_finansi(db, so_ids) -> dict[int, IsFinansi]` iş başına hesap yapar; tek sorguda toplu çalışır, N+1 yoktur.
  - `IsFinansi` alanları:
    - `sure_dakika` (MOLA hariç `service_time_entries` toplamı, `is_deleted=false`);
    - `iscilik` / `iscilik_durumu`: `TAM`, `SURE_EKSIK` (kayıt yok) ya da `TARIFE_TANIMSIZ` (E07-11);
    - `malzeme` / `malzeme_durumu`: `TAM`, `YOK` (parça çıkışı yok → 0, tamdır) ya da `MALIYET_EKSIK` (`stock_movements.unit_cost_try IS NULL` olan çıkış var);
    - `diger` (NULL → 0, tam sayılır);
    - `gelir` / `gelir_durumu` (E07-12);
    - `fark` = `gelir − (malzeme + iscilik + diger)`, **yalnız** tüm durumlar tamsa; aksi halde `None` ve `fark_durumu="HESAPLANAMADI"`.
  - Varsayılan liste kapsamı: kapanmış işler (Servis İş Emri makinesinin terminal "tamamlandı/kapandı" durumları; kapanış tarihi dönem süzgecidir).
  - Özet satırları: `tam_is_sayisi`, `sure_eksik_sayisi`, `tarife_tanimsiz_sayisi`, `gelir_yok_sayisi`, `sozlesme_kapsami_sayisi`. Toplamlar **yalnız `fark` değeri dolu** işlerden alınır.
  - Tahmini süre hiçbir koşulda yerine konmaz.
- **Kabul:**
  1. Süre kaydı olmayan kapalı iş `iscilik: null`, `iscilik_durumu: "SURE_EKSIK"` döner ve ekranda "Süre kaydı eksik" yazar.
  2. Tarifesi tanımsız birimdeki iş `iscilik: null`, `"TARIFE_TANIMSIZ"` döner.
  3. Gelir satırı olmayan iş `gelir: null`, `fark: null` döner.
  4. `UCRETSIZ_GARANTI` işinde gelir 0 kabul edilir ve fark hesaplanır.
  5. Özet `fark_toplami` yalnız tam işlerin toplamıdır ve eksik sayaçları ayrıca döner.
- **Bağımlılık:** E07-11, E07-12, E07-20; Servis İş Emri ve zaman kaydı; Yedek Parça (`stock_movements.service_order_id`, `unit_cost_try`).
- **Canlı risk:** Yok. Yalnız okunur; `stock_movements` için yalnız nullable kolon eklenir.

### E07-11 · Tarife tanımsızken işçiliğin sessizce 0 hesaplanmaması ve tarife eksik uyarısı — P1 · S · (M07-D02)
- **Canlı durum: YOK.**
- **Yaklaşım:**
  - `iscilik_hesapla(db, so_id)` her zaman kaydını, kaydın başladığı **yerel tarihte** (Europe/Istanbul, `Clock` saat dilimi) geçerli tarifeyle çarpar: `daterange @> tarih`, `birim = iş birimi`.
  - Kayıtlardan herhangi birinin tarifesi yoksa işin tamamı `TARIFE_TANIMSIZ` olur (kısmi toplam verilmez) ve fark toplamına girmez.
  - `ck_iscilik_tarife_pozitif` 0 tarifeyi şemada engeller. Bu yüzden "tarife 0" durumu yalnız "tarife yok" olarak ortaya çıkar.
  - Uyarı: `services/uyarilar.py` içinde `if user.has("maliyet.gor") and user.has("rapor.gor"):` bloğu, birim kapsamına göre "İşçilik tarifesi tanımsız birim" ve "tarifesiz süre kaydı olan kapalı iş" sayılarını üretir; yol `/teknik-servis/maliyet?durum=TARIFE_TANIMSIZ`.
- **Kabul:**
  1. HABERLESME biriminde tarife yokken 3 saatlik kaydı olan kapalı iş için API `iscilik: null`, `iscilik_durumu: "TARIFE_TANIMSIZ"` döner ve özet farkına girmez.
  2. `hourly_cost=0` ile tarife girişi 422 döner (Pydantic `gt=0`; DB'de de `ck_`).
  3. Uyarı sayısı yalnız kullanıcının birimlerindeki işleri sayar.
- **Bağımlılık:** E07-20, E07-10.
- **Canlı risk:** Yok.

### E07-12 · "Gelir girilmedi" ile "Ücretsiz-Garanti" ayrımı (gelir NULL olabilir, kaynak, zorunlu not) — P1 · S · (M07-D03)
- **Canlı durum: YOK.**
- **Yaklaşım:**
  - Model `service_order_financials` (§1.2, CHECK'ler şemada).
  - `gelir_durumu` hesaplanır, saklanmaz. Değerleri:
    - `KAYIT_YOK`: satır yok veya `gelir IS NULL`;
    - `TEKLIF`, `ELLE`, `UCRETSIZ_GARANTI`;
    - `SOZLESME_KAPSAMI`: PB işi ve gelir NULL ise. Sözleşme bedeli PB işlerine dağıtılmaz, bkz. kararlar §K9. Fark hesaplanmaz ve ayrı sayaçta gösterilir; "gelir yok" alarmı üretmez.
  - Uç: `PUT /api/teknik-servis/maliyet/isler/{so_id}/gelir` (`MaliyetYazici = require_permission("maliyet.gor", "maliyet.yaz")` + birim/müşteri kapsamı), gövde `{kaynak: "ELLE"|"UCRETSIZ_GARANTI"|"SOZLESME", tutar: Decimal|null, not: str, version: int|null}`. `UCRETSIZ_GARANTI` seçilince tutar 0'a zorlanır. Not boşsa servis 400 döner (DB'deki `ck_` kısıtı ikinci savunma hattıdır). `PUT .../diger-maliyet` uç aynı kalıptadır.
  - İyimser kilit: `version` uyuşmazsa 409.
- **Kabul:**
  1. Yalnız diğer maliyeti girilmiş işte gelir `null` ve `gelir_durumu: "KAYIT_YOK"` döner, ekranda "Gelir kaydı yok" yazar.
  2. Ücretsiz-Garanti işaretli işte gelir 0 kabul edilir ve fark hesaplanır.
  3. Ücretsiz-Garanti ya da Elle seçiminde not boşsa 400 döner, satır oluşmaz.
  4. `maliyet.yaz` izni olmayan kullanıcı 403 alır.
- **Bağımlılık:** E07-04 (iş çekirdeği tarafında: Servis İş Emri), E07-10 ile aynı sürüm.
- **Canlı risk:** Yok (yeni tablo).

### E07-13 · Taslak teklif düzenleme ve revizyon kuralları — P2 · M · (M07-01)
- **Canlı durum: KISMEN.**
  - Revizyon canlıda **aynı teklifin yeni sürümüdür**: eski sürüm kilitlenir, kalemler fiyatlarıyla kopyalanır (`services/quotes.py:71-126`). Kabul edilmiş ya da siparişe dönmüş teklif revize edilemez, 409 (`api/quotes.py:260-264`).
  - Eksikler: taslağı yerinde düzenleme ucu yok, çünkü TASLAK teklifte de revize yeni sürüm açıyor; onay bekleyen ya da onaylı teklifin düzenlenmesi engellenmiyor; revize sonrası durum her zaman REVIZE_EDILDI oluyor (`:278`), yani birimli teklif onaysız gönderilebilir hale geliyor.
  - `ParentOfferId` karşılığı sürüm zinciridir (`quote_id + version_no`); ayrı teklif kaydı açılmaz. Bu, denetçinin "R0→R1 ağacı gereksiz" kararıyla uyumludur.
- **Yaklaşım:**
  - `PUT /api/teklifler/{id}` (Yazici + kapsam), gövde `TeklifIn` + `version`. Yalnız `status == "TASLAK"` ve güncel sürüm kilitli değilse çalışır. Güncel sürümün kalemleri silinip yeniden yazılır (`_kalemleri_yaz`) ve `versiyon_hesapla` çağrılır. Başlık alanları (`title`, `contact_id`, `valid_until`, `currency/fx`) güncellenir. Kalem dışı alanlarda `audit.log_change` kullanılır; kalem değişikliğinde `audit.log("guncelle", old_value={"tutar": eski}, new_value={"tutar": yeni})`.
  - Diğer durumlarda 409 "Yalnız taslak teklif düzenlenebilir; gönderilmiş teklif için revizyon açın".
  - **Birimli teklifte** revize yalnız GONDERILDI, GORUNTULENDI, RED ya da `etkin_durum == SURESI_DOLDU` iken yapılabilir. Yeni sürüm açılır, durum **TASLAK** olur (yeniden onay gerekir). ONAY_BEKLIYOR veya ONAYLANDI durumunda revize 409 döner ("önce geri çevirin").
  - Satış teklifinde canlı davranış korunur (REVIZE_EDILDI).
  - Ekranda R0, R1… gösterimi `version_no − 1` ile yapılır. Eski sürümler "Revize Edildi" etiketiyle salt okunur listelenir. `PUT` uç eski sürüm kimliğiyle çağrılamaz, çünkü uç teklif kimliği alır ve yalnız güncel sürümü düzenler.
  - Ön yüz: `TeklifFormu` hem yeni kayıt hem düzenleme için kullanılır (KartPenceresi kalıbı). TASLAK durumunda Drawer'da "Düzenle", diğer durumlarda "Revizyon aç" düğmesi gösterilir.
- **Kabul:**
  1. Taslakta fiyat değişince `grand_total` sunucuda yeniden hesaplanır ve sürüm sayısı artmaz.
  2. ONAY_BEKLIYOR, ONAYLANDI ve KABUL durumundaki teklife `PUT` isteği 409 döner.
  3. KABUL durumundaki teklif revize edilemez (409, canlı).
  4. Birimli teklifte GONDERILDI → revize sonrası R1 açılır, durum TASLAK olur, R0 kilitlidir ve listede "Revize Edildi" görünür; R1 onaylanmadan `/gonder` isteği 409 döner.
  5. Eski `version` ile gelen `PUT` 409 döner.
- **Bağımlılık:** E07-04.
- **Canlı risk:** Düşük. `PUT` yeni bir uçtur. Satış teklifinin revize akışı değişmez.

### E07-14 · Teklif–servis işi bağlantısı: iş detayında teklifler, bakım bulgusundan kısayol, teklife bağlı bekleme ve yalnız ilgili beklemenin kalkması — P2 · S · (M07-03)
- **Canlı durum: YOK.** Teklif yalnız müşteriye ve siparişe bağlı (`models/order.py:74-78`); servis işi kavramı canlıda yok.
- **Yaklaşım:**
  - **Bağlantı:** `quotes.service_order_id` ve kalem bazında `quote_lines.service_order_id` (§1.1).
  - **İş detayı:** `GET /api/teknik-servis/isler/{id}` yanıtına `teklifler: [{id, quote_no, etkin_durum, versiyon_no, valid_until, grand_total?}]` eklenir; teklif kendisine ya da kalemlerinden birine bağlıysa listede yer alır. `grand_total` **yalnız** `user.has("teklif.gor")` ise anahtar olarak bulunur; teknisyende anahtar hiç yoktur, `None` olarak da gönderilmez.
  - **Kısayol:** Servis sonucu `TEKLIF_SUNULACAK` olan işte (ve PB bakım formunda) "Teklif hazırla" düğmesi `TeklifFormu`'nu `customer_id`, `birim`, `service_order_id` ve `contact_id` önceden dolu açar. Servis işleri listesinde çoklu seçimle "Toplu teklif hazırla" sunulur: aynı müşteri ve birim zorunludur; teklifin ana işi ilk seçilen iştir ve her işe birer boş kalem şablonu açılır (kalem `service_order_id` dolu).
  - **Bekleme:** Servis İş Emri modülünün `service_holds` tablosuna nullable `quote_id` (FK `quotes` SET NULL) ve bekleme nedenleri listesine `TEKLIF_ONAYI` eklenir (kolon adı bu modülde sabitlenir, tablo sahibi o modül). `onaya_gonder(..., beklet=True)` ya da `gonder(..., beklet=True)` çağrısı işin servis katmanı fonksiyonuyla `bekleme_ac(so, neden="TEKLIF_ONAYI", quote_id=t.id)` açar. Tek aktif bekleme kısmi indeksi (`uq_hold_aktif`) varsa ve başka bir bekleme zaten açıksa teklif beklemesi **açılmaz**, yanıta uyarı eklenir.
  - Teklif KABUL, RED ya da IPTAL olunca **yalnız `quote_id = t.id` olan** aktif bekleme kapanır (`bekleme_kapat`). Başka nedenli (ör. MALZEME) bekleme açık kalır ve iş BEKLEMEDE durumunda kalır. Her iki tarafta olay geçmişine yazılır (`service_order_events`).
  - Servis kodu `work_orders` tablosuna yazmaz.
- **Kabul:**
  1. Bir işe bağlı iki teklif iş detayında görünür.
  2. `beklet=true` ile onaya gönderilen teklif işi BEKLEMEDE yapar ve bekleme nedeni "Teklif onayı" olur.
  3. Ayrıca MALZEME beklemesi olan işte teklif kabul edilince iş BEKLEMEDE kalır ve yalnız teklif beklemesi kapanır.
  4. `SERVIS_TEKNISYEN` iş detayında `grand_total` anahtarını görmez.
  5. Başka müşterinin işine teklif bağlama girişimi 400 döner (E07-03).
- **Bağımlılık:** E07-04; Servis İş Emri çekirdeği (`service_orders`, `service_holds`, `service_order_events`, `service_results`).
- **Canlı risk:** Yok.

### E07-15 · "Teklif Sunulacak" sonucu verilmiş ama teklifi açılmamış işler uyarısı (2 iş günü) — P2 · S · (M07-D04)
- **Canlı durum: YOK.**
- **Yaklaşım:**
  - `services/uyarilar.py` içine `if user.has("servis.gor") and user.has("teklif.gor"):` bloğu eklenir: `teklif_bekleyen_bulgular(db, clock, user)`.
  - Sorgu `service_results.sonuc = 'TEKLIF_SUNULACAK'` ve sonuç tarihine `servis_teklif_sunulacak_is_gunu` (Cumartesi ve Pazar atlanır; resmî tatil takvimi ilk sürümde yok, kararlar §K12) eklenmiş tarih `< Clock.today` olan kayıtları alır.
  - Teklifi açılmış sayılmak için IPTAL olmayan **hiçbir** teklif bulunmamalıdır: `NOT EXISTS (quotes q WHERE q.service_order_id = so.id AND q.status <> 'IPTAL' AND NOT q.is_deleted)` ve `NOT EXISTS (quote_lines ql JOIN quote_versions ... WHERE ql.service_order_id = so.id)`.
  - Sayı `kapsam_birim` + `kapsam_musteri` ile süzülür (sayı sızıntısı yasak, `uyarilar.py:14-16`). Yol: `/teknik-servis/isler?teklif_bekleyen=1`. Servis işleri listesine aynı filtre eklenir.
- **Kabul:**
  1. Sonucu 2 iş günü önce girilmiş "Teklif Sunulacak" PB işi uyarıda görünür; Cuma girilen sonuç Salı sabahı görünür, Pazartesi görünmez.
  2. İşe teklif açılınca, ya da işe bağlı kalem içeren bir teklif oluşunca, uyarı düşer.
  3. HABERLESME şefi GÜVENLİK işlerini saymaz.
- **Bağımlılık:** E07-14; Servis İş Emri (`service_results`).
- **Canlı risk:** Yok (yeni blok, izne bağlı).

### E07-16 · Kabul edilen teklifin KDV hariç net tutarının iş gelirine aktarılması (elle gelir korunur, uyarı, iptalde geri alma) — P2 · S · (M07-04)
- **Canlı durum: YOK.**
- **Yaklaşım:**
  - `services/teknik_servis/maliyet.py: gelir_aktar(db, so_id, *, user_id, neden)` işin TEKLIF kaynaklı gelirini **baştan hesaplar**: KABUL durumundaki (SIPARISE_DONUSTU birimli teklifte oluşmaz) birimli tekliflerin **güncel sürüm** kalemlerinden bu işe düşen `line_total` toplamı alınır. Kalem `service_order_id` değeri, yoksa teklifin `service_order_id` değeri kullanılır. Toplam iskonto sonrası ve KDV hariçtir; dövizli teklifte `× fx_rate`, ardından `yuvarla`.
  - Mevcut `gelir_kaynagi` değerine göre:
    - NULL ya da TEKLIF ise gelir yeni toplamla yazılır (toplam 0 ve kabul edilmiş teklif yoksa satır `gelir=NULL, kaynak=NULL` olur);
    - ELLE, UCRETSIZ_GARANTI ya da SOZLESME ise **dokunulmaz**; dönüş değeri `uyari="Elle girilmiş gelir korundu; kabul edilen teklif tutarı: X"` olur.
  - Değişiklik `audit.log_change(db, fin, "gelir.teklif", ...)` ile kaydedilir (E07-17).
  - Çağrı noktaları: `karar` (kabul) ve public link kararı, ancak yalnız birimli teklifte; `iptal` (KABUL → IPTAL). Hepsi aynı transaction'da çalışır.
  - Yanıt `TeklifOut.uyarilar: list[str]` ile döner; ön yüz bunu `message.warning` olarak gösterir.
  - Ayrı teklif–gelir bağlantı tablosu AÇILMAZ (denetçi reddi).
- **Kabul:**
  1. 10.000 TL + %20 KDV'li teklif kabul edilince iş geliri 10.000,00 TL olur, kaynak "Teklif".
  2. Elle 12.000 TL gelir girilmiş işte kabul geliri değiştirmez, yanıtta uyarı bulunur.
  3. Aynı işe ikinci bir 2.500 TL teklif kabul edilince gelir 12.500,00 TL olur.
  4. Kabul edilmiş teklif iptal edilince TEKLIF kaynaklı gelir geri alınır (kalan toplam ya da NULL) ve gelir geçmişinde eski → yeni değer görünür.
  5. İki PB işine kalem bazında bağlı tek teklifin kabulünde her iş yalnız kendi kalemlerinin netini alır.
- **Bağımlılık:** E07-04, E07-12, E07-17 (aynı sürüm).
- **Canlı risk:** Yok. Satış teklifinde (birim NULL) çağrılmaz; `public_quotes` yalnız `if t.birim` dalında çağırır.

### E07-17 · Gelir ve maliyet değişiklik geçmişi (eski/yeni değer, kullanıcı, zaman, not) — P2 · S · (M07-13)
- **Canlı durum: KISMEN.** `audit.log_change` yalnız değişen kolonları eski ve yeni değerleriyle yazıyor (`services/audit.py:55-92`); `audit_logs` için düzenleme ya da silme ucu yok. Kayıt bazlı, izne bağlı okuma ucu yok.
- **Yaklaşım:**
  - `service_order_financials` ve `service_labor_rates` üzerindeki tüm yazmalar commit'ten önce `audit.log_change(db, obj, "<eylem>", user_id, ip)` ile kaydedilir. Eylemler: `gelir.elle`, `gelir.teklif`, `gelir.ucretsiz`, `diger.guncelle`, `fatura.iletildi`, `tarife.ekle`, `tarife.kapat`. Not ve gerekçe `new_value["not"]` alanına yazılır.
  - Uç: `GET /api/teknik-servis/maliyet/isler/{so_id}/gecmis` (`MaliyetOkuyucu = require_permission("maliyet.gor")` + kapsam) → `audit_logs WHERE entity='service_order_financials' AND entity_id=<fin.id>` + `users.full_name`.
  - Ayrı geçmiş tablosu açılmaz (E03-03 ile tutarlı).
- **Kabul:**
  1. Geliri 3 kez değişen işte geçmişte 3 kayıt görünür ve her biri eski → yeni değer, kullanıcı ve notu içerir.
  2. `maliyet.gor` izni olmayan kullanıcı 403 alır.
  3. Servis hatası (`MaliyetHatasi`) ile reddedilen yazmada `audit_logs` satırı oluşmaz.
- **Bağımlılık:** E07-12.
- **Canlı risk:** Yok.

### E07-18 · Teklif listesi: filtreler, tıklanabilir KPI kutuları, 3 gün içinde dolacak uyarısı, Excel — P2 · S · (M07-08)
- **Canlı durum: KISMEN.**
  - Ön yüzde yalnız durum filtresi var (`pages/TekliflerPage.tsx:211-226, 421-431`); liste API'si `limit=50` varsayılanıyla **yalnız son 50 teklifi** getiriyor ve tablo istemci tarafında sayfalıyor (`:440-446`; `api/quotes.py:174`).
  - Panelde yalnız "bekleyen teklif" sayısı var (`services/reports.py:85-96`).
  - Süre uyarısı ve Excel yok.
- **Yaklaşım:**
  - `GET /api/teklifler/ozet` (Okuyucu + `teklif_kapsami`): `{onay_bekleyen, onayli_gonderilmedi, musteri_yaniti_bekleyen, suresi_yaklasan (≤ teklif_sure_uyari_gun), suresi_dolan, bu_ay_kabul}`. Her sayı, listedeki aynı filtre ifadesiyle üretilir; tek kaynak `services/quotes.py: filtre_ifadesi(kod)`.
  - Uyarı: `uyarilar.py` içine `if user.has("teklif.gor"):` bloğu, `teklif.suresi_yaklasan` (yalnız **birimli** teklifler, kapsam süzgeçli), yol `/teklifler?kpi=suresi_yaklasan`.
  - `GET /api/teklifler.xlsx` (Okuyucu + `rapor.disaaktar`), liste filtreleriyle aynı sorguyu kullanır (`services/export.py:45`). Kolonlar: No, Rev, Birim, Müşteri, Servis İşi, Durum, Etkin Durum, Hazırlayan, Onaylayan, Geçerlilik, Ara Toplam, İskonto, KDV, Genel Toplam, Döviz, Gönderim Tarihi, Karar Tarihi.
  - Ön yüz: liste kartının üstünde `Statistic` kutuları; tıklanınca `kpi` filtresi ayarlanır ve sayfa 1'e döner. Filtreler: durum (etkin durum dahil), birim (yalnız birden çok birimi olana), tarih aralığı (`RangePicker`, oluşturma ya da gönderim tarihi), müşteri, servis işi no, hazırlayan. "Excel" düğmesi `yetkili("rapor.disaaktar")` ile görünür. Çoklu seçim ile "Seçilileri Excel'e aktar" (kimlik listesi parametresi).
- **Kabul:**
  1. "Müşteriye Gönderildi + son 30 gün" filtresi yalnız uyan teklifleri gösterir.
  2. 2 gün sonra dolacak birimli teklif uyarıda ve "3 gün içinde dolacak" kutusunda sayılır; kutuya tıklayınca yalnız o teklifler listelenir.
  3. Yetkisiz birimin teklifi liste, özet, Excel ve uyarı yanıtlarında yer almaz.
  4. Excel satır sayısı `X-Toplam-Kayit` değerine eşittir.
- **Bağımlılık:** E07-04, E07-19.
- **Canlı risk:** Düşük. Liste ucu `sayfala` kullanmaya başlar (E07-19); gövde biçimi değişmez (dizi) ve toplam başlıkta gelir. Uyarı yalnız birimli tekliflerde çalışır.

### E07-19 · Teklif listesinde sunucu tarafı filtre, sayfalama ve `(birim, status, created_at)` indeksi — P3 · S · (M07-08b)
- **Canlı durum: KISMEN.** `durum` ve `musteri_id` filtreleri sunucuda (`api/quotes.py:180-183`); `sayfala` ve `offset` yok; tarih ve birim filtresi yok; `ix_quote_durum` var (`models/quote.py:70`).
- **Yaklaşım:**
  - `listele` imzası şunları ekler: `birim`, `kpi`, `tarih_bas/tarih_bit` (+ `tarih_alani: olusturma|gonderim`), `servis_isi_id`, `hazirlayan_id`, `q` (`quote_no ILIKE` / müşteri `title_key`), `offset`.
  - Sorgu `teklif_kapsami` → filtreler → `sayfala(db, response, stmt, limit, offset)` sırasıyla kurulur. N+1'i önlemek için `_cikti(detay=False)`, müşteri adlarını ve sürüm sayılarını toplu sorguyla çeker.
  - İndeks `ix_quote_birim_durum_tarih`.
  - Ön yüz `api.getSayfa` ve `Table` sunucu sayfalaması (`pages/IsEmirleriPage.tsx:66-107` kalıbı).
- **Kabul:**
  1. Birim ve tarih filtreleri SQL'de uygulanır; test `X-Toplam-Kayit` değerini doğrular.
  2. `EXPLAIN` çıktısında birim + durum sorgusu indeksi kullanır (test DB'de 5.000 satırla, bilgi amaçlı).
  3. 51. teklif artık listede ulaşılabilir (canlıdaki 50 sınırı kalkar).
- **Bağımlılık:** E07-18 ile aynı sürüm.
- **Canlı risk:** Düşük. Mevcut istemci `api.get` ile dizi okumaya devam eder; ön yüz aynı sürümde `getSayfa` kullanacak şekilde güncellenir.

### E07-20 · Geçerlilik tarihli birim saatlik iç maliyet tarifesi — P2 · S · (M07-10)
- **Canlı durum: YOK.** Benzer tarihli fiyat kalıpları var: `subscription_prices` `[)` aralıklı (`models/subscription.py:130-160`), hak ediş tarifeleri (`models/settlement.py:120-140`).
- **Yaklaşım:**
  - Model `service_labor_rates` (§1.2).
  - Servis `tarife_ekle(db, birim, valid_from, hourly_cost, *, user, clock, gerekce)`: aynı birimin açık satırı varsa `valid_to = valid_from` yapılarak kapatılır. `valid_from < Clock.today` ise yalnız `sistem.ayar` iznine sahip kullanıcı gerekçeyle girebilir; diğerleri 400 alır. EXCLUDE çakışması 409'a döner (`main.py:131-148`, `ex_` öneki).
  - Uçlar (`api/servis_maliyet.py`, prefix `/api/teknik-servis/maliyet`):
    - `GET /tarifeler?birim=` (MaliyetOkuyucu; yalnız kullanıcının birimleri);
    - `POST /tarifeler` (MaliyetYazici);
    - `POST /tarifeler/{id}/kapat` (MaliyetYazici, gerekçe zorunlu; yalnız henüz başlamamış satır için).
  - Ön yüz: `ServisMaliyetPage` içinde "İşçilik Tarifeleri" sekmesi: birim başına zaman çizelgesi (tarih, ₺/sa, kim, ne zaman) ve "Yeni tarife" formu (KartPenceresi).
  - Göç: eski `OpsLaborRates` değerleri **varsa** `valid_from = eski sistemdeki ilk süre kaydı tarihi` ile taşınır. Uydurma 2026-01-01 yazılmaz; ilk süre kaydı da yoksa göç edilmez, tarife elle girilir (kararlar §K10).
- **Kabul:**
  1. HABERLESME için 1 Ekim 500 TL/sa ve 1 Kasım 600 TL/sa tanımlıyken Ekim'deki 2 saat 1.000 TL, Kasım'daki 2 saat 1.200 TL hesaplanır.
  2. Kasım tarifesi girildikten sonra Ekim analizi değişmez (test aynı sorguyu önce ve sonra koşar).
  3. Geçmişte kullanıcı ve tarih görünür (E07-17).
  4. Aynı birimde çakışan aralık 409 döner.
  5. `sistem.ayar` izni olmayan kullanıcının geçmiş tarihli girişi 400 döner.
- **Bağımlılık:** RBAC+birim adımı.
- **Canlı risk:** Yok.

### E07-21 · Maliyet analizi: dönem/birim/iş türü/müşteri filtresi, birim × iş türü özeti, satır sınırı yok — P2 · M · (M07-11)
- **Canlı durum: YOK.** Rapor altyapısı var (`api/reports.py`, `_maliyet_gizle` `:41-45`, `donem_dogrula` `api/deps.py:125-139`).
- **Yaklaşım:**
  - `GET /api/teknik-servis/maliyet/analiz?donem=YYYY-AA|baslangic=&bitis=&birim=&tur=&musteri_id=&durum=` (izin `require_permission("rapor.gor", "maliyet.gor")` + `kapsam_birim` + `kapsam_musteri`).
  - Dönem zorunludur, en fazla 12 ay. Sayfalama yoktur (denetçi reddi); satır sınırı da yoktur, dönem filtresi sorgu boyutunu sınırlar.
  - Yanıt `{satirlar: [IsFinansi + no, birim, tur, musteri, kapanis_tarihi], ozet: [{birim, tur, adet, tam_adet, gelir, malzeme, iscilik, diger, fark, sure_eksik, tarife_tanimsiz, gelir_yok, sozlesme_kapsami}], genel: {...}}`.
  - Özet ve detay **aynı** `is_finansi` çıktısından toplanır (tek kaynak); özet toplamı detayın tam satır toplamına eşittir.
  - `durum` filtresi KPI kutuları içindir: `SURE_EKSIK`, `TARIFE_TANIMSIZ`, `GELIR_YOK`, `TAM`.
  - Ön yüz `pages/ServisMaliyetPage.tsx` (`/teknik-servis/maliyet`, MENU `{key, label: "Servis Maliyet Analizi", icon, izin: "maliyet.gor"}`):
    - üstte tıklanabilir KPI kutuları (Tam iş, Süre eksik, Tarife tanımsız, Gelir yok, Toplam fark);
    - filtre satırı (`DatePicker picker="month"`, birim, tür, müşteri);
    - özet tablosu (birim × tür) ve detay tablosu;
    - satıra tıklayınca iş finans Drawer'ı açılır (gelir/diğer maliyet düzenleme `yetkili("maliyet.yaz")`, geçmiş `Timeline`);
    - eksik değerler "—" ile ve durum etiketiyle gösterilir, 0 yazılmaz.
- **Kabul:**
  1. Ekim + HABERLESME + ARIZA filtresi yalnız o kapsamdaki, Ekim'de kapanmış işleri getirir.
  2. Özet toplamı detaydaki tam satırların toplamına eşittir.
  3. `maliyet.gor` izni olmayan kullanıcı (ör. `SERVIS_SEF`) 403 alır.
  4. HABERLESME'ye kısıtlı ve kişisel istisnayla `maliyet.gor` almış bir kullanıcı GÜVENLİK satırlarını görmez.
  5. 13 aylık aralık 400 döner.
- **Bağımlılık:** E07-10, E07-11, E07-12, E07-20.
- **Canlı risk:** Yok.

### E07-22 · Maliyet analizi Excel dışa aktarımı ve müşteri kırılımı — P3 · S · (M07-11b)
- **Canlı durum: YOK.** Excel altyapısı VAR (`services/export.py:45` formül enjeksiyonu korumalı, `api/reports.py:33-38`).
- **Yaklaşım:** `GET /api/teknik-servis/maliyet/analiz.xlsx?...&kirilim=is|musteri` (izin `require_permission("rapor.gor", "maliyet.gor", "rapor.disaaktar")`). Aynı `analiz()` çıktısını kullanır. `kirilim=musteri` müşteri bazında gruplar. Durum kolonları (İşçilik Durumu, Gelir Durumu, Malzeme Durumu, Fark Durumu) her zaman bulunur; eksik tutar hücresi boş bırakılır, 0 yazılmaz. CSV yerine xlsx üretilir (canlı kalıp, kararlar §K11).
- **Kabul:**
  1. `rapor.disaaktar` izni olmayan kullanıcı 403 alır.
  2. Dosyada durum sütunları bulunur; eksik işlerde tutar hücresi boştur.
  3. Müşteri kırılımı toplamı iş kırılımı toplamına eşittir.
  4. `=HYPERLINK(...)` içeren müşteri adı metin olarak yazılır.
- **Bağımlılık:** E07-21.
- **Canlı risk:** Yok.

### E07-23 · Fiyat/maliyet sızıntısı için otomatik API yetki testleri — P2 · M · (M07-15)
- **Canlı durum: KISMEN.** `maliyet.gor` sahipleri kümesi unit testle kilitli (`tests/unit/test_permissions.py:21-26`); rapor maliyet gizliliği testi var (`tests/integration/test_raporlar.py`); kapsam testi emsali var (`test_kapsam_guvenligi.py:49-56`). Teknik servis uçları için genel bir tarama yok.
- **Yaklaşım:** `tests/integration/test_servis_fiyat_sizintisi.py`:
  1. `YASAK_ANAHTARLAR = {"iscilik", "malzeme", "diger", "fark", "gelir", "hourly_cost", "unit_cost_try", "landed_cost_try", "maliyet", "grand_total", "subtotal", "unit_price", "line_total"}`.
  2. `SERVIS_TEKNISYEN` kullanıcısıyla `app.routes` içindeki `/api/teknik-servis` önekli tüm GET uçları fixture kimlikleriyle çağrılır; yanıt JSON'u özyinelemeli taranır ve yasak anahtar bulunursa test kırmızıya döner. Bir uca bilerek maliyet alanı eklenince test kırılır; bu durum testin kendisi tarafından da "ekle → kırmızı" alt testiyle kanıtlanır (`monkeypatch` ile çıktıya alan eklenir).
  3. Ayrı senaryolar:
     - `/api/teknik-servis/maliyet/analiz` 403;
     - `PUT .../gelir` 403;
     - teknisyende iş detayında `teklifler[].grand_total` anahtarı yok;
     - bakım sözleşmesi ücret alanları yok (Bakım Sözleşmesi modülü testine bağlanır);
     - stok ve parça listesinde `unit_cost_try` yok;
     - başka birimin teklif durum isteği 404 ve kayıt değişmemiş.
  4. Yeni uç eklendiğinde rota taramasının kapsaması için test, `/api/teknik-servis` altında taranmayan GET rotası kalırsa da kırılır (beyaz liste ile).
- **Kabul:** Senaryoların her biri ayrı test olarak geçer. Maliyet alanı eklenmiş sahte çıktı kırmızı verir. `make test` yeşil kalır (altın kayıt dahil).
- **Bağımlılık:** E07-01, E07-02, E07-21.
- **Canlı risk:** Yok (yalnız test).

### E07-24 · Teklif dönüşüm raporu: birim filtresi, kapsam, tutar ve Excel "Teklifler" sayfası — P3 · S · (M07-12)
- **Canlı durum: KISMEN.**
  - `services/reports.py:135-181` durum dağılımını, kazanılan ile kaybedilen sayısını, dönüşüm oranını (karara bağlanmayan teklif paydaya girmez) ve ret nedenlerini veriyor.
  - Revizyonlar aynı teklifin sürümü olduğu için **teklif zaten bir kez sayılıyor**; bu gereksinimin "son revizyonla say" maddesi kendiliğinden karşılanıyor.
  - Eksikler: birim filtresi, kapsam (uç `rapor.gor` ile tüm teklifleri sayıyor, `api/reports.py:57-61`), hesaplanan SURESI_DOLDU, tutarlar, ortalama yanıt günü, Excel.
- **Yaklaşım:**
  - `teklif_donusumu(db, *, gun, clock, birim=None, user=None)` imzası genişler. `user` verilirse `teklif_kapsami` uygulanır; `birim` filtresi eklenir; durum sayımı `etkin_durum` ifadesiyle yapılır (SURESI_DOLDU hesaplanır). Ek alanlar: `gonderilen_adet`, `kabul_tutari_net`, `ort_yanit_gun` (`sent_at` → `accepted_at`/`rejected_at`), `iptal`. IPTAL kaybedilene sayılmaz, ayrı verilir.
  - Mevcut çağrı `birim=None, user=None` ile **aynı sonucu** verir; yalnız `etkin_durum` farkı yansır (bkz. canlı risk).
  - Uç parametreleri `birim`, `.xlsx` (Aktarici).
  - Rapor ekranında birim seçici.
  - Ön koşul notu: anlamlı oran için onay akışının 2–3 ay çalışmış olması gerekir.
- **Kabul:**
  1. 10 gönderilen, 6 kabul, 2 ret ve 2 süresi dolan birimli teklif örneğinde kabul oranı %60 çıkar.
  2. R1'e revize edilmiş teklif bir kez sayılır.
  3. KENDI_BIRIMI kullanıcısında başka birim rapora girmez.
  4. Excel'de "Teklifler" sayfası satır sayısı rapor toplamına eşittir.
- **Bağımlılık:** E07-04, E07-18.
- **Canlı risk:** Düşük. Satış teklifleri için de "süresi dolmuş" teklifler artık kaybedilen sayılır; şimdiye kadar worker işaretlemediği için GONDERILDI olarak sayılıp paydaya girmiyorlardı. Oran düşebilir; sürüm notunda açıklanır ve bu davranış rapor açıklamasına yazılır. İstenmezse `etkin_durum` yalnız `birim IS NOT NULL` için uygulanır (kararlar §K7).

### E07-25 · SMTP sırları ve gönderim hız sınırı (kullanıcı başına dakikada 10) — P3 · S · (M07-16)
- **Canlı durum: KISMEN.**
  - `smtp_password` DB'de Fernet ile şifreli saklanıyor (`services/settings.py:26-31`). Anahtar `.env` içindeki `settings_enc_key`/`secret_key` değerinden türetiliyor (`crypto.py:4, 22-26`). Arayüze maskeli dönüyor.
  - Dağıtılan dosyalarda parola yok. Hız sınırı yok.
- **Yaklaşım:**
  - Sır yönetimi canlı kalıpla korunur, ek kod yazılmaz. Kabule "parola düz metin olarak hiçbir dosyada ve API yanıtında yok" maddesi eklenir.
  - Hız sınırı: `gonder` ve yeniden gönderim uçları önce `SELECT count(*) FROM quote_sends WHERE created_by=:u AND kanal='EPOSTA' AND created_at > Clock.now() - 60s` sorgusunu çalıştırır. Sayı `teklif_gonderim_dakika_limiti` değerine eşit ya da büyükse 429 "Çok fazla gönderim; bir dakika sonra tekrar deneyin" döner (`HTTPException(429)`). Tek worker ve tek API kopyası olduğu için DB sayımı yeterlidir.
- **Kabul:**
  1. `GET /api/ayarlar` yanıtında `smtp_password` maskelidir; `settings` tablosunda değer `enc:` önekiyle saklanır.
  2. Aynı kullanıcının 1 dakika içindeki 11. gönderimi 429 döner (`FakeClock` ile); 61. saniyede tekrar 200 döner.
- **Bağımlılık:** E07-06.
- **Canlı risk:** Yok.

### E07-26 · Kabul edilmiş veya gelirli kapanmış işler için "Faturaya iletildi" devir işareti (Logo entegrasyonu değil) — P3 · S · (M07-D05)
- **Canlı durum: YOK.** Muhasebe dışa aktarım şablon ayarı var (`services/settings.py:72`), servis işi devri yok.
- **Yaklaşım:**
  - `GET /api/teknik-servis/fatura-devri?durum=bekleyen|iletildi&donem=&birim=` (izin `require_permission("tahsilat.gor")` + birim/müşteri kapsamı). Liste ölçütü: kapanmış servis işi ve (`KABUL` durumunda birimli teklif **veya** `gelir_kaynagi IN ('ELLE','SOZLESME')` ile `gelir > 0`) ve `fatura_iletildi_at IS NULL`. Tutar kolonu yalnız `teklif.gor` ya da `maliyet.gor` izni varsa anahtar olarak yer alır.
  - `POST /api/teknik-servis/fatura-devri/isaretle` (`require_permission("tahsilat.yaz")`), gövde `{is_idler: list[int] (1..200), not: str|None}`. Toplu işlemdir; kapsam dışı ya da uygun olmayan kimlik varsa **tamamı** 409 ile reddedilir ve hangi kimliklerin sorunlu olduğu yazılır. Her iş için `fatura_iletildi_at/by` alanları ve `audit.log_change` yazılır.
  - `POST .../{so_id}/geri-al` (`tahsilat.yaz`, gerekçe zorunlu).
  - Ön yüz `pages/FaturaDevriPage.tsx` (`/teknik-servis/fatura-devri`, MENU izin `tahsilat.gor`): çoklu seçimli tablo, "Faturaya iletildi olarak işaretle" düğmesi, "İletilenler" sekmesi (kim, ne zaman), Excel (`rapor.disaaktar`).
- **Kabul:**
  1. Kabul edilmiş teklifli iş kapanınca listede görünür; işaretlenince listeden düşer ve "İletilenler" sekmesinde kim ve ne zaman bilgisiyle görünür.
  2. `tahsilat.gor` izni olmayan kullanıcı 403 alır.
  3. Bir kimliği kapsam dışı olan toplu istek 409 döner ve hiçbir satır işaretlenmez.
- **Bağımlılık:** E07-04, E07-12, E07-16.
- **Canlı risk:** Yok. `tahsilat.*` izinleri yeni uçta yeniden kullanılır; mevcut rol listeleri değişmez.

---

## 3. Uygulama sırası (genel teknik servis sırasına yerleştirme)

1. **RBAC + birim adımı ile birlikte:** E07-01, E07-02 (teklif kapsamı yalnız birim sütunu geldiğinde tamamlanır; satış tarafındaki `SATIS` açığı aynı PR'da kapanır).
2. **Servis iş emri çekirdeğinden sonra:** migration `servis_teklif_maliyet` (§1.8) → E07-03, E07-04, E07-13, E07-05, E07-14.
3. **Planlama ve zaman kaydıyla:** E07-20, E07-11, E07-12, E07-10, E07-17, E07-16.
4. **Parça, teklif köprüsü ve rapor adımında:** E07-21, E07-15, E07-18, E07-19, E07-07, E07-08, E07-06, E07-09, E07-26.
5. **Güvenlik sıkılaştırma ve son:** E07-23, E07-25, E07-22, E07-24.

Her adımın sonunda `make test` (altın kayıt 932 iş / 552.825,00 TL dahil), `test_migration_zinciri`, `test_teklif.py` (satış akışı değişmedi), `ruff` ve `npm run build` çalıştırılır.

---

## 4. Kararlar (kullanıcıya sorulmadan verilenler)

- **K1. Ayrı servis teklifi tablosu açılmaz.** Canlı `quotes` tablosu `birim` kolonuyla genişletilir. Gerekçe: sürüm, dondurma, PDF, public link ve dönüşüm raporu hazır; kopya varlık üretmek kuralı çiğner. `birim IS NULL` satış teklifi demektir ve canlı akış değişmez.
- **K2. `ck_quote_durum` kısıtına `ONAYLANDI` ve `IPTAL` yalnız ekleme olarak girer** (bilinçli sapma, §1.3). İkinci bir durum kolonu ekranı ve raporları ikiye bölerdi. Downgrade eşlemesi docstring'de yazılır.
- **K3. Teklif tutarı satış fiyatıdır, `teklif.gor` ile görünür; iç maliyet, işçilik, gelir ve fark `maliyet.gor` ister.** (Eski analizin 1. sorusu.) Teknisyen rolüne `teklif.gor` verilmez, bu yüzden teknisyen tutar görmez.
- **K4. Tek kademeli iç onay.** `teklif.onayla` iznini `SERVIS_YONETICI` taşır. Birimli teklifte iç onay, iskonto eşiği onayını da kapsar (aynı anda `discount_approved_*` doldurulur). Öz-onay yasağı varsayılan açıktır (`teklif_oz_onay_yasak=True`). Tutar veya iskonto bazlı ikinci kademe ilk sürümde yoktur; gerekirse ayar ve ikinci izinle eklenir.
- **K5. `maliyet.gor` rol kümesi değişmez.** TS müdürü ve maliyet sorumlusu `maliyet.gor` ile `maliyet.yaz` izinlerini kişi bazlı `UserPermission` istisnasıyla (gerekçeli) alır. `maliyet.yaz` ilk sürümde rol olarak yalnız ADMIN'dedir.
- **K6. Muhasebe fatura devri için mevcut `tahsilat.gor/yaz` izinleri kullanılır** (MUHASEBE_DESTEK bunlara sahip). Yeni `accounting.*` izni açılmaz ve mevcut rol listeleri değişmez.
- **K7. "Süresi Doldu" saklanmaz, hesaplanır** (`etkin_durum`). Canlıdaki `suresi_dolanlari_isaretle` worker'a bağlı değil; bağlamak satış tekliflerinin verisini sessizce değiştirirdi. Bu modül de bağlamaz. Dönüşüm raporunda hesaplanan durum kullanılır; satış teklifleri için oran değişimi sürüm notuna yazılır.
- **K8. Birimli tekliflere ek doğrulamalar** (KDV beyaz listesi, geçmiş geçerlilik reddi, döviz için zorunlu kur) **yalnız birimli teklifte** uygulanır; satış teklifinin girdi kuralları değişmez. Fiyat ve adet için 2 hane yuvarlama **tüm** tekliflerde uygulanır, çünkü DB zaten 2 hane saklıyor; yalnız hesap DB ile hizalanır.
- **K9. PB (planlı bakım) işlerinde sözleşme bedeli işlere dağıtılmaz.** Gelir durumu "Sözleşme kapsamı" olur, fark hesaplanmaz ve ayrı sayaçta gösterilir. Sözleşme kârlılığı Bakım Sözleşmesi modülünün raporudur. Elle `SOZLESME` kaynaklı gelir girişi yine mümkündür.
- **K10. Tarife geçmişi gün bazlıdır** (`Date` + `daterange '[)'`). Saatlik `tstzrange` gereksizdir; yarı açık aralık ilkesi korunur. Eski tarifeler uydurma tarihle (2026-01-01) taşınmaz: ilk süre kaydı tarihi kullanılır, o da yoksa tarife elle girilir.
- **K11. Dışa aktarım CSV yerine xlsx'tir** (canlı kalıp, formül enjeksiyonu korumalı). Kullanıcının doğruladığı "Excel export" bununla karşılanır.
- **K12. "İş günü" ilk sürümde yalnız hafta sonunu atlar.** Resmî tatil takvimi ayara bağlı ayrı bir iyileştirmedir.
- **K13. Döviz desteklenir ama birimli teklifte kur elle ve zorunlu girilir** (`fx_source='MANUEL'`, canlı alan). Gelir aktarımı TL'ye çevrilerek yapılır. Kur kaynağı entegrasyonu (TCMB) bu modülde yoktur.
- **K14. Fiyat listesi ayrı tablo değildir.** Kalemler katalogdan (`products.list_price`; ör. birim başına "İşçilik (saat)" HIZMET ürünü) seçilir ya da elle girilir. Canlı `kalem_alanlari` iki yolu da destekliyor.
- **K15. PDF motoru canlıdaki WeasyPrint'tir.** Yeni lisans onayı gerekmez. Logo ve künye ayarlardan gelir; resmî bilgiler girilene kadar canlıdaki varsayılanlar basılır.
- **K16. Teklif durum geçmişi `audit_logs` üzerinden okunur;** ayrı `quote_status_history` tablosu açılmaz (E03-03 ile tutarlı). Gönderim günlüğü ise ayrı tablodur (`quote_sends`): hız sınırı, özet ve başarısız deneme kaydı sorgulanabilir alanlar ister.
- **K17. Birimli (servis) teklifi siparişe dönüştürülemez** (`api/orders.py` 409). Kabul edilen servis teklifi iş gelirine akar, satış siparişi ve sevkiyat zincirine girmez.
- **K18. Bir teklif tek ana servis işine bağlanır; çoklu PB bulgusu kalem bazında `service_order_id` ile tek teklifte toplanır.** Bağlantı tablosu açılmaz (denetçinin RevenueOfferIds reddiyle uyumlu).
- **K19. Teklif numarası canlı kalıpta kalır** (`TKF{yıl}-{sıra}`, `max(id)+1`, `uq_quote_no` → 409). Değiştirmek satış numaralarını da etkilerdi. Revizyon gösterimi `-R{n}` = `version_no − 1` (yalnız gösterim).
- **K20. SMTP sırları canlıdaki şifreli ayar kalıbıyla kalır** (anahtar `.env`'de). Ayrı ortam değişkenine taşınmaz; özün kabulü ("dağıtılan yapılandırmada parola yok") zaten sağlanıyor.
- **K21. Gelir girişi Muhasebe veya şef rolüne otomatik bağlanmaz.** `maliyet.yaz` istisnası verilen kişi girer: ilk kurulumda TS müdürü ve Muhasebe sorumlusu. "Faturaya iletildi" işaretini `tahsilat.yaz` sahibi (Muhasebe) koyar.
- **K22. İşçilik maliyetine MOLA hariç tüm faaliyetler** (YOL, ISCILIK, BEKLEME) girer. Bordro değil iç maliyettir; kişi bazlı ücret kullanılmaz, birim tarifesi geçerlidir.

---

## 5. Gözlemler (canlı kodda; bu tasarım değiştirmez, kayda geçer)

- **G1.** `api/quotes.py:252-448`: `revize_et`, `iskonto_onayla`, `teklif_pdf`, `gonder` ve `karar` uçlarında kayıt kapsamı kontrolü yok. `SATIS` rolü başkasının teklifini kimlik numarasıyla değiştirebiliyor. E07-02 kapatır.
- **G2.** `api/attachments.py:91-114`: `"quotes"` ekleri kapsam dışı; satış temsilcisi başka temsilcinin teklif eklerini listeleyebiliyor. E07-02 kapatır.
- **G3.** `services/quotes.py:38-59` + `api/quotes.py:33`: `unit_price` ondalık basamak sınırı yok. 3 ondalıklı fiyatta iskontosuz teklife 0,01 "iskonto" yazılabilir (kod okumasına dayalı; test edilmeli). E07-03 kapatır.
- **G4.** `services/mail.py:56-59`: hata mesajı SMTP sunucu adını, portu ve istisna metnini kullanıcıya döndürüyor (hak ediş gönderimi dahil). E07-06 yalnız teklif ucunda genel mesaj döndürür; hak ediş tarafı güvenlik sıkılaştırma adımına bırakılır.
- **G5.** `services/quotes.py:193 suresi_dolanlari_isaretle` testli ama `worker.py:120-125` içinde çağrılmıyor; teklifler hiçbir zaman otomatik SURESI_DOLDU olmuyor.
- **G6.** `api/quotes.py:415-448` + `services/quotes.py:218-245`: elle karar her durumdan veriliyor (TASLAK → KABUL dahil). Satış akışında bilinçli olabilir; birimli teklifte `TEKLIF` makinesi engeller.
- **G7.** `api/quotes.py:174` + `pages/TekliflerPage.tsx:219-221, 445`: liste yalnız son 50 teklifi getiriyor, 51. ve sonrası ekranda ulaşılamıyor. E07-19 kapatır.
- **G8.** `api/quotes.py:201`: teklif numarası `max(id)+1`; eşzamanlı kayıtta `uq_quote_no` 409 döner (genel gözlemle aynı). Değiştirilmedi (K19).
- **G9.** `api/reports.py:57-61`: dönüşüm raporu kapsam uygulamıyor; satış temsilcisi tüm teklif adetlerini görüyor (yalnız sayılar). E07-24 `user` parametresiyle kapatır.
