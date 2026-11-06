# E12 — Teknik Servis Raporları ve KPI: Canlı ERP Entegrasyon Tasarımı

> **Tarih:** 2026-10-21 · **Hedef:** Denge Mobilite ERP (`C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp`). Kod yalnız OKUNDU, hiçbir dosya değiştirilmedi.
> **Girdi:** `analiz\02_moduller\_ozet\12_raporlama.json` (17 onaylı, 1 reddedilen madde), `12_raporlama_tasarim.md`, `12_raporlama_denetim.md`, `10_canli_entegrasyon\00_MIMARI_KURALLAR.md` (bağlayıcı), E01/E02/E03/E04/E05/E06 entegrasyon belgeleri (tablo ve izin adları buradan alındı).
> **Dosya:satır** referansları `backend/app/...` ve `frontend/src/...` köklerine göredir; 2026-10-21'de kod okunarak doğrulandı.
> `dotnet_specific=true` madde yok; tüm maddeler işlendi. Reddedilen **M12-07** (parça kullanımı sayfası) E11'in işidir; E12 yalnız Excel yazıcısını ve filtre modelini ona sunar.

---

## 1. Özet

### 1.1 Canlıda ne var?

| Öğe | Canlı karşılık | E12 için anlamı |
|---|---|---|
| Rapor uçları | `api/reports.py:27-30` (`/api/raporlar`, `rapor.gor` / `rapor.disaaktar`), her rapor JSON + `.xlsx` aynı servis fonksiyonundan (`api/reports.py:1-6`) | **Kalıp aynen kullanılır.** "Ekran = Excel" ilkesi canlıda zaten var. |
| Rapor servisleri | `services/reports.py` (mobilite: dashboard, montaj noktası, müşteri geliri, hareketsiz stok) | **Dokunulmaz.** Servis raporları ayrı dosyada (`services/teknik_servis/rapor_*.py`). |
| Excel üretimi | `services/export.py:45-87` (`satirlari_xlsx_async`, openpyxl, `asyncio.to_thread`), formül enjeksiyonu koruması `:26-42` | **Yeniden kullanılır + yanına tipli yazıcı eklenir.** Mevcut fonksiyon değiştirilmez. Hücre tipi bugün Python değer tipinden geliyor; şema yok. |
| Maliyet gizleme | `api/reports.py:41-46` `_maliyet_gizle`, `api/deps.py:103-105` `sees_cost` | Servis raporlarında fiyat/maliyet kolonu **hiç yok** (M12-05: sözleşme tutarı yer almaz). |
| Panel | `services/reports.py:43` `dashboard`, `pages/PanelPage.tsx:96-207` | Mobilite paneli. KPI kartları **tıklanamıyor** (onClick/navigate yok). E01 K17: servis paneli AYRI (`ServisPaneli`). |
| Rapor sayfası | `pages/RaporlarPage.tsx` (717 satır, 7 sekme, `window.open` ile xlsx indirme `:178`) | Mobilite raporları. Servis raporları ayrı sayfada. |
| Denetim izi | `services/audit.py:26` `log`, `:55` `log_change` | Dışa aktarım kaydı için kullanılır. **Bugün hiçbir rapor `.xlsx` ucu denetime yazmıyor** (yalnız KVKK dökümü `api/kvkk.py:94-101` `erisim_kaydet`). |
| KVKK | `services/kvkk.py:40` `erisim_kaydet`, `:398` `maskele` | Kişi bazlı rapor dışa aktarımında `is_personal_data=True`. |
| Sayfalama | `api/deps.py:170` `sayfala` | KPI tıklanınca açılan listeler. |
| Ayarlar | `services/settings.py:33-93` `DEFAULTS` (anahtar biçimi `alt_cizgili_turkce`) | Rapor parametreleri. |
| Uyarılar | `services/uyarilar.py:47` `topla` | Veri kalitesi uyarısı bloğu. |
| Hesap normalizasyonu | `accounts.title_key` (ORM olayı), `services/accounts.py:84` `mukerrer_adaylari` | Müşteri varyantı kontrolü (M12-14) buradan; yeni normalizasyon yazılmaz. |
| Teknik servis verisi | YOK (E01–E11 tasarlandı, kodlanmadı) | E12 tamamen **okuyucu** modüldür; kendi iş tablosu yoktur. |

**Sonuç:** 18 maddenin 6'sı **KISMEN** (rapor/Excel/denetim altyapısı var, servis verisine uygulanmamış), 12'si **YOK**. E12 yeni iş tablosu açmaz; yalnız `service_orders`'a 1 nullable kolon (`first_completed_at`) ve bir rapor-tanım modülü ekler.

### 1.2 Bağımlılık

```
RBAC+birim (E01-01) → Servis iş emri çekirdeği (E01) → Plan (E02) → Zaman kaydı (E09) → Ekipman (E03)
  → PB/sözleşme (E04) → Atölye (E05) → SLA (E10) → E12
```
E12 maddeleri kademeli açılır: çekirdek (E12-01..08) E01+E09 ile; SLA bölümü E10 ile; PB tamamlama E04 ile. Bağımlı modül yoksa ilgili sekme/sayfa **gizlenir**, sıfır gösterilmez (ilke: "eksik veri sıfır yazılmaz").

### 1.3 Kullanıcının bizzat doğruladığı işlevler (kaybedilmez)

| İşlev | E12'deki yeri |
|---|---|
| KPI kutuları **tıklanabilir** (sayı = açılan liste) | E12-08: her KPI bir `kpi` kodu döner; tıklanınca `/servis-isleri?kpi=...&<aynı filtre>` açılır; parametrik test "KPI sayısı = liste `X-Toplam-Kayit`". |
| **Excel export** | E12-06 / E12-08 / E12-17: çok sayfalı servis kitabı, aynı motor, tipli hücreler, pivot. |
| Toplu planlama / atama | E12 yazmaz; KPI listesinden açılan `ServisIsleriPage` çoklu seçim + toplu atama (E01-12 / E02) aynen çalışır. KPI tıklaması o sayfaya filtreyle gider. |
| **Cihaz başına PB iş emri** | E12-12: PB tamamlama sayımı cihaz PB iş emirleri (`uq_so_pb_cihaz_donem`) üzerinden; AKYAKA 17 cihaz senaryosu test. |

---

## 2. Yerleşim

### 2.1 Dosyalar (yeni / değişen)

```
backend/app/models/teknik_servis.py              # + SERVIS_DURUM_GRUPLARI, durum_grubu(), first_completed_at kolonu (E01 modeli)
backend/app/services/teknik_servis/
    rapor_tanimlari.py     # KPI sözlüğü (kod, başlık, Türkçe tanım, birim), sütun şemaları, sayfa listesi — TEK KAYNAK
    rapor_motoru.py        # RaporFiltresi, filtre_dogrula, temel_sorgu (kapsam), ozet, kirilim, trend, liste_kpi
    rapor_hesap.py         # kişi-saat, eksik süre, dönem sonu açık, tekrar arıza, yeniden açılan, SLA okuma
    rapor_kalite.py        # veri kalitesi kontrolleri (yalnız listeler)
    rapor_excel.py         # tipli Excel yazıcı (sütun şeması), kitap üretimi, pivot şablonu doldurma
backend/app/templates/excel/servis_pivot_sablonu.xlsx   # bir kez Excel'de hazırlanmış pivot şablonu (sürüm numaralı)
backend/app/services/teknik_servis/is_emirleri.py       # durum_degistir(): first_completed_at yazımı (E01 fonksiyonu, 3 satır)
backend/app/api/servis_raporlari.py      # APIRouter(prefix="/api/teknik-servis/raporlar", tags=["servis-rapor"])
backend/app/main.py                      # import + include_router (main.py:182-209 bloğu)
backend/app/permissions.py               # + rapor.personel; SERVIS_YONETICI / SERVIS_SEF rollerine
backend/app/services/settings.py         # + servis_rapor_* anahtarları
backend/app/services/uyarilar.py         # + veri kalitesi uyarı bloğu
backend/alembic/versions/<rev>_servis_rapor_zaman_damgasi.py
backend/tests/unit/test_servis_rapor_tanimlari.py
backend/tests/integration/test_servis_rapor*.py, tests/fixtures/servis_rapor_seed.py, tests/fixtures/servis_rapor_beklenen.json
frontend/src/api/servisRaporlari.ts
frontend/src/pages/ServisRaporlariPage.tsx
frontend/src/components/KpiKutusu.tsx    # tıklanabilir Statistic kartı (E01/E02/E03/E04/E05 ortak kullanır)
frontend/src/components/RaporFiltresi.tsx
frontend/src/main.tsx (rota /servis-raporlari), components/AppLayout.tsx (MENU)
```

**Dokunulmayanlar:** `services/reports.py`, `api/reports.py`, `services/export.py` (yalnız `_formulu_metne_cevir` import edilir), `PanelPage.tsx`, `RaporlarPage.tsx`, `work_orders` / `work_order_items` / `settlements`, altın kayıt testi.

### 2.2 Veri modeli değişikliği (tek)

`service_orders` (E01 tablosu, yeni, canlı verisi yok):

| Kolon | Tip | Not |
|---|---|---|
| `first_completed_at` | timestamptz NULL | İşin **ilk kez** TAMAMLANDI olduğu an. Yeniden açılışta **temizlenmez**. SLA sonucu ve "yeniden açılan iş" bununla ölçülür. `ck_so_ilk_cozum`: `first_completed_at IS NULL OR completed_at IS NULL OR completed_at >= first_completed_at`. İndeks `ix_so_ilk_cozum(first_completed_at)`. |

- `completed_at` (E01) = **son çözüm anı** (yeniden açılışta NULL, ikinci çözümde yeniden yazılır).
- `closed_at`, `cancelled_at`, `reopen_count` E01'de var; E12 yeni kolon açmaz.
- E01 migration'ı henüz yazılmadıysa kolon doğrudan E01'in `servis_is_emri_cekirdek` migration'ına eklenir (tercih); yazıldıysa `make makemigration m="servis_rapor_zaman_damgasi"` ile ayrı migration, `op.add_column` + `op.create_check_constraint`, downgrade `drop_constraint` + `drop_column`.
- Göç (E01 `migration/servis_goc.py`): `first_completed_at` = eski durum logundaki ilk çözüm; log yoksa eski `CompletedAt`; atölye kaydı için atölye tamamlanma tarihi; PB için cihaz `CompletedAt`. **Hiçbiri yoksa NULL** — tarih uydurulmaz; iş Veri Kalitesi'nde "çözüm zamanı eksik" listesine düşer.

### 2.3 Tek kaynak sözlükler (`models/teknik_servis.py`, `rapor_tanimlari.py`)

```python
# models/teknik_servis.py — SERVIS_DURUMLARI (E01) ile birlikte
SERVIS_DURUM_GRUPLARI: dict[str, tuple[str, ...]] = {
    "ACIK":    ("MUSTERI_TALEBI","PLANLAMADA","PLANLANDI","YOLA_CIKILDI","SAHADA","ISLEMDE",
                "ATOLYEDE","KARGODA","TEST_KONTROL","BEKLEMEDE","TEKRAR_ACILDI"),
    "COZULDU": ("TAMAMLANDI","KAPATILDI"),
    "IPTAL":   ("IPTAL",),
}
DURUM_GRUBU_ADLARI = {"ACIK":"Açık","COZULDU":"Çözüldü","IPTAL":"İptal","TANIMSIZ":"Tanımsız durum"}
def durum_grubu(status: str) -> str: ...            # katalog dışı → "TANIMSIZ"
def durum_grubu_ifadesi(sutun) -> ColumnElement: ...  # aynı eşlemeden SQL CASE üretir
```

```python
# rapor_tanimlari.py
@dataclass(frozen=True)
class KpiTanimi:
    kod: str; baslik: str; tanim: str; birim: str        # "adet" | "kisi_saat" | "yuzde" | "saat"
    kategori_ayri: bool; kisisel: bool                     # kisisel=True → rapor.personel ister
KPI_TANIMLARI: dict[str, KpiTanimi]   # K01..K15 (eski §2.3) — ekranda ⓘ, Excel "Tanımlar" sayfası aynı metin
SUTUN_SEMALARI: dict[str, tuple[Sutun, ...]]  # sayfa → (başlık, anahtar, tip: METIN|TAMSAYI|ONDALIK|TARIH|TARIH_SAAT, kisisel)
TARIH_ESASLARI = ("ACILIS","PLAN","COZUM","KAPANIS")
KATEGORILER = ("GUNLUK_SERVIS","PLANLI_BAKIM","ATOLYE","KURULUM","DIGER")   # E01 ck_so_kategori ile aynı tuple import edilir
```

---

## 3. İzinler, kapsam, roller

| Kod | Modül | Açıklama | Roller |
|---|---|---|---|
| `rapor.gor` (mevcut) | Rapor | Ekran raporları | SERVIS_YONETICI, SERVIS_SEF (E01'de zaten verildi) |
| `rapor.disaaktar` (mevcut) | Rapor | Excel | SERVIS_YONETICI, SERVIS_SEF (E01'de verildi) |
| **`rapor.personel`** (yeni) | Rapor | Kişi bazlı süre, teknisyen notu, konum notu, saha irtibatı içeren rapor alanlarını ve sayfalarını görür / dışa aktarır | **SERVIS_YONETICI, SERVIS_SEF** (+ ADMIN otomatik) |

- Servis rapor uçları **iki izni birlikte** ister: okuma `rapor.gor` + `servis.gor`; Excel `rapor.disaaktar` + `servis.gor` (`require_permission` birden çok kod = hepsi gerekli, `api/deps.py:79-97`).
  ```python
  Okuyucu  = Annotated[User, Depends(require_permission("rapor.gor", "servis.gor"))]
  Aktarici = Annotated[User, Depends(require_permission("rapor.disaaktar", "servis.gor"))]
  ```
- `rapor.personel` `.gor` ile bitmediği için **YONETIM'e otomatik inmez** (`permissions.py:84`) — Genel Koordinatör/Muhasebe/Yönetim toplamları görür, kişi detayını görmez (eski S2 kararının özü).
- `maliyet.gor` kümesi **değişmez**; `tests/unit/test_permissions.py` "her izin en az bir role atanmış" testi `rapor.personel` için SERVIS_YONETICI ile geçer.
- `ozellestirildi=True` DB rollerine yeni izin inmez (`models/rbac.py:64-69`); kurulum notuna elle ekleme listesi yazılır.
- **Kapsam:** her rapor sorgusu `rapor_motoru.temel_sorgu()` içinden geçer: `kapsam_musteri(stmt, user, ServiceOrder.customer_id)` (`services/accounts.py:29`) → `kapsam_birim` → `kapsam_kendi_isleri` (E01 `services/teknik_servis/kapsam.py`). Rapor ucu kendi WHERE'ini kapsamsız kuramaz (kod incelemesi + test).
- İstekte kullanıcının yetkisiz olduğu `birim` → **403** (`birim_disinda_mi`); boş birim listesi = "yetkili olduğum tüm birimler".

---

## 4. API (`api/servis_raporlari.py`, prefix `/api/teknik-servis/raporlar`)

Ortak sorgu parametreleri (`RaporFiltresiIn`, Pydantic): `baslangic`, `bitis` (date, zorunlu), `tarih_esasi` (TARIH_ESASLARI, vars. ACILIS), `kategori[]`, `birim[]`, `durum_grubu[]`, `tur[]`, `oncelik[]`, `musteri_id`, `sef_id`, `teknisyen_id`, `sehir`, `tekrar_gun` (7–180). Bilinmeyen değer → Pydantic `Literal` ile **400** (sessizce "tümü" sayılmaz); `baslangic > bitis` → 400; aralık > `servis_rapor_azami_ay` (24) → 400.

| Uç | İzin | İçerik | Madde |
|---|---|---|---|
| `GET /ozet` | Okuyucu | Yönetim özeti: K01–K15 değerleri (kategori ayrı), toplam eşitliği, önceki dönem, `generated_at`, `filtreler`, `kapsam` ("Birimler: …"), her KPI'da `kpi` kodu | E12-08, E12-05, E12-18 |
| `GET /kirilim?boyut=` | Okuyucu | `boyut` ∈ (birim, sef, teknisyen*, musteri, sehir, oncelik, cozum_kanali, tur, bekleme_nedeni) → satırlar; `*` kişisel boyut `rapor.personel` ister | E12-11 |
| `GET /kpi-liste?kpi=` | Okuyucu | KPI'ya ait iş listesi (`sayfala`) — `ServisIsleriPage` aynı fonksiyonu `GET /api/teknik-servis/is-emirleri?kpi=` ile de kullanır | E12-08 |
| `GET /kisi-saat` | Okuyucu + `rapor.personel` | Teknisyen × faaliyet kişi-saat; süre kaydı olmayan atanmış teknisyen "eksik" satırıyla | E12-05, E12-09 |
| `GET /sla` | Okuyucu | SLA uyumu, geciken, gecikme nedeni dağılımı (E10 yoksa 404 "SLA modülü etkin değil") | E12-13 |
| `GET /tekrar-ariza` | Okuyucu | Onaylı oran + "onaysız" geçmiş satırı + tekrar ziyaret | E12-14 |
| `GET /yeniden-acilan` | Okuyucu | sayı/oran + liste (PB ayrı) | E12-15 |
| `GET /bakim-tamamlama` | Okuyucu + `bakim.gor` | Sözleşme dönemi satırları (E04 fonksiyonu) | E12-12 |
| `GET /trend` | Okuyucu | 12 ay gelen/çözülen/kişi-saat (kişi-saat toplamdır, kişisel değil) | E12-18 |
| `GET /veri-kalitesi` | Okuyucu | Kontrol başına sayı; `?kontrol=` ile sayfalı liste | E12-16 |
| `GET /tanimlar` | Okuyucu | `KPI_TANIMLARI` (ön yüz ⓘ metni) | E12-08 |
| `GET /kitap.xlsx` | Aktarici | Çok sayfalı servis kitabı (§5); kişisel sayfalar yalnız `rapor.personel` ile | E12-06, E12-09, E12-17 |
| `GET /{rapor}.xlsx` | Aktarici | Tek sekmenin Excel'i (sla, tekrar-ariza, bakim-tamamlama, veri-kalitesi, kpi-liste) | ilgili maddeler |

Her `.xlsx` ucu, yanıt üretilmeden önce aynı transaction'da `audit.log(db, "servis_rapor", "rapor.disaaktar", new_value={rapor, filtreler, satir_sayisi, kapsam, kisisel_sayfalar}, user_id, ip=client_ip(request), is_personal_data=<kişisel sayfa var mı>)` + `db.commit()` yapar (KVKK emsali `api/kvkk.py:94-101`).

---

## 5. Excel kitabı (`rapor_excel.py`)

| # | Sayfa | Kaynak fonksiyon | Kişisel? |
|---|---|---|---|
| 1 | Yönetim Özeti (dönem + önceki dönem, generated_at, filtre, kapsam, "bordro değildir" notu, "n işte eksik veri var") | `rapor_motoru.ozet` | Hayır |
| 2 | Günlük Servis | `liste_satirlari(kategori=GUNLUK_SERVIS)` | Hayır (irtibat kolonları yalnız `rapor.personel` ile) |
| 3 | Planlı Bakım | `liste_satirlari(kategori=PLANLI_BAKIM)` + dönem, form sonucu (E04) | Hayır |
| 4 | Atölye | `liste_satirlari(kategori=ATOLYE)` | Hayır |
| 5 | Birim Durum (birim × kategori: toplam/açık/çözülen/iptal/tanımsız/beklemede/geciken/kritik) | `kirilim("birim")` | Hayır |
| 6 | Aylık Özet (açılan ve çözülen **ayrı** akış) | `trend` | Hayır |
| 7 | Personel KPI | `kisi_saat` | **Evet** |
| 8 | Süre Hareketleri | `sure_satirlari` | **Evet** |
| 9 | Müşteri Lokasyon (müşteri → tesis/adres → şehir; kişi-saat toplam) | `kirilim("musteri","lokasyon")` | Hayır |
| 10 | SLA ve Gecikme | `sla` (E10 yoksa sayfa yok) | Hayır |
| 11 | Tekrar Arıza | `tekrar_ariza` | Hayır (teknisyen kolonu yalnız `rapor.personel` ile) |
| 12 | Yeniden Açılan | `yeniden_acilan` | Hayır |
| 13 | Bakım Tamamlama | E04 `bakim_raporlari.donem_tamamlama` (E04 yoksa yok) | Hayır |
| 14 | Veri Kalitesi | `rapor_kalite.kontroller` | Hayır |
| 15 | Tanımlar | `KPI_TANIMLARI` + LibreOffice pivot sınırı notu | Hayır |
| 16 | `Veri_IsEmirleri` (Excel Tablosu) | `liste_satirlari` (tüm kategori) | Hayır |
| 17 | `Veri_Sureler` (Excel Tablosu) | `sure_satirlari` | **Evet** |
| 18 | `Pivot_Birim`, `Pivot_Ay`, `Pivot_KisiSaat` | şablondan; `Pivot_KisiSaat` yalnız `rapor.personel` ile | (3. pivot evet) |

Tip kuralları (tek yer: `SUTUN_SEMALARI`): METIN hücre `data_type="s"`, `number_format="@"` (seri no, iş no, telefon, plaka); TARIH `datetime.date` + `"DD.MM.YYYY"`; TARIH_SAAT Europe/Istanbul'a çevrilmiş naive datetime + `"DD.MM.YYYY HH:MM"`; ONDALIK `float` + `"#,##0.00"`; TAMSAYI `int`. Formül enjeksiyonu: `export._formulu_metne_cevir` aynen çağrılır. Başlık dondurma + otomatik filtre. Üretim `asyncio.to_thread` (canlı ilke `services/export.py:45-53`). Satır sınırı `servis_rapor_excel_azami_satir` (50.000) aşılırsa 400 + "filtreyi daraltın".

---

## 6. Ön yüz

- **Rota** `main.tsx`: `<Route path="/servis-raporlari" element={<ServisRaporlariPage/>} />` (AppLayout altında, `main.tsx:67-69` yanına).
- **Menü** `AppLayout.tsx:45-120` `MENU`: `{ key: "/servis-raporlari", label: "Servis Raporları", icon: <BarChartOutlined/>, izin: "servis.gor" }`. Menü bugün "herhangi biri" mantığıyla çalışır (`AppLayout.tsx:49-50`); iki iznin birlikte gerekmesi için sayfada `yetkili("rapor.gor")` yoksa `Alert` gösterilir ve hiçbir sorgu atılmaz (karar K5).
- **`RaporFiltresi.tsx`**: tarih aralığı + hazır düğmeler (Bugün / Bu Hafta / Bu Ay / Son 30 gün / Geçen ay), tarih esası, kategori, birim (yalnız `auth/me.birimler`), durum grubu, şef, teknisyen (kullanıcı `Select`'i, **id** ile — tam eşleşme), müşteri (hesap arama), şehir, öncelik. Filtre URL query'de tutulur (paylaşılabilir bağlantı).
- **`KpiKutusu.tsx`**: `Card hoverable onClick` + `components/Statistic.tsx` + ⓘ `Tooltip` (metin `/tanimlar`'dan). Tıklama → `navigate("/servis-isleri?kpi=<kod>&<filtre>")`. Sayısı `null` olan (ölçülemedi) kutu "—" ve "n iş eksik veri" alt yazısı gösterir. E01-14 / E02-06 / E03-11 / E04-18 / E05-08 aynı bileşeni kullanır.
- **`ServisRaporlariPage.tsx`** sekmeleri: Özet (KPI kutuları + önceki dönem farkı ±n/±%), Kırılımlar, Kişi-Saat (yalnız `yetkili("rapor.personel")`), SLA (E10 varsa), Tekrar Arıza, Yeniden Açılan, Bakım Tamamlama (`bakim.gor` varsa), Trend (AntD `Table` + basit çubuk; yeni grafik kütüphanesi eklenmez), Veri Kalitesi. Her sekmede `ExcelBtn` (`RaporlarPage.tsx:178-185` kalıbı, `window.open`) yalnız `yetkili("rapor.disaaktar")`.
- `useQuery({ queryKey: ["servis-rapor", sekme, filtre] })`; tarih `dayjs("tr")`, gösterim `DD.MM.YYYY`, sayı `Statistic` (Türkçe ayırıcı). Para alanı yoktur.

---

## 7. Ayarlar, uyarılar, worker

`services/settings.py` `DEFAULTS`:
- `servis_rapor_azami_ay: 24`
- `servis_rapor_excel_azami_satir: 50000`
- `servis_rapor_tekrar_ariza_gun: 30` (istek parametresi 7–180 ile ezilebilir)
- `servis_rapor_yas_kovalari: [2, 7, 14, 30]` (0-2 / 3-7 / 8-14 / 15-30 / 30+)
- `servis_seri_zorunlu_turler: ["ARIZA","PB","ATOLYE_ONARIM"]` (Veri Kalitesi "seri no eksik" kontrolü; E01 kapanış kuralıyla aynı anahtar — E01 tanımladıysa yeniden tanımlanmaz)
- `servis_sla_durduran_bekleme_nedenleri: ["MUSTERI_ONAYI","MUSTERI_ERISIMI","TEKLIF"]` (E10 sahibi; E10 tanımladıysa yalnız okunur)

`services/uyarilar.py:47` `topla()` → `if user.has("servis.gor") and user.has("rapor.gor"):` bloğu: "Veri kalitesi: n servis işinde eksik veri" (`yol="/servis-raporlari?sekme=kalite"`), sayı kapsamlı sorgudan.

**Worker:** E12 için worker işi YOK (rapor anlık hesaplanır; ay kapanışı/arşiv açılmaz — karar K7). PB üretimi E04'e aittir.

---

## 8. Maddeler

### E12-01 · Durum grupları tek katalogdan; katalog dışı "Tanımsız" (M12-11) — P1 · S
- **Canlı:** YOK. Servis durumu yok; mobilite `work_orders` durumları ayrı ve dokunulmaz.
- **Yaklaşım:** §2.3 `SERVIS_DURUM_GRUPLARI` + `durum_grubu()` + `durum_grubu_ifadesi()` (SQL CASE aynı sözlükten). Ekran, Excel, servis paneli (E01-14), atölye (E05), PB (E04) yalnız bunu çağırır; başka dosyada durum listesi yazılmaz. POC'nin "İnceleniyor / Telefonla Destek / Uzaktan / Yerinde Müdahale" durumları E01 K2 gereği **durum değil çözüm kanalıdır** (`service_results.cozum_kanali`); göçte eşlenir, eşlenemeyen karantinaya düşer. "Çözüldü" ayrı durum değildir: TAMAMLANDI = çözüldü (karar K1).
- **Kabul:** (1) Unit test: `SERVIS_DURUMLARI`'nın her değeri tam bir gruptadır, grup sözlüğünde katalog dışı değer yoktur. (2) TAMAMLANDI ve KAPATILDI işler ekran, panel ve Excel'de aynı "Çözüldü" grubunda. (3) Göç önizlemesinde `Iptal` gibi eşlenemeyen eski değer "Tanımsız durum" sayısında ve Veri Kalitesi listesinde görünür. (4) Toplam = Açık + Çözüldü + İptal + Tanımsız.
- **Canlı risk:** Yok (yeni tablo).

### E12-02 · Çözüm/kapanış/iptal zaman damgaları ve tek geçiş noktası (M12-12) — P1 · M
- **Canlı:** YOK. E01 `completed_at`, `closed_at`, `cancelled_at`, `reopen_count` ve tek giriş noktası `durum_degistir()` tasarladı; ilk çözüm anı yok.
- **Yaklaşım:** §2.2 `first_completed_at` kolonu. `durum_degistir()` TAMAMLANDI'ya geçişte `if so.first_completed_at is None: so.first_completed_at = clock.now()`; TEKRAR_ACILDI'da `completed_at/closed_at` NULL olur (E01), `first_completed_at` kalır. SLA sonucu (E10) yalnız ilk çözümde damgalanır ve değişmez. Tüm durum değişimleri `service_order_events` DURUM satırı yazar (E01); doğrudan atama yasak (unit test: `grep "\.status ="` yalnız `durum_degistir` içinde). Göç: §2.2 kuralları, uydurma tarih yok.
- **Kabul:** (1) Çöz → yeniden aç → çöz senaryosunda `first_completed_at` ilk an, `completed_at` son an (FakeClock). (2) Göçte kaynağı olmayan iş NULL ve Veri Kalitesi'nde. (3) `ck_so_ilk_cozum` ihlali 409.
- **Canlı risk:** Yok. Migration yalnız yeni tabloya dokunur; head→base→head testi.

### E12-03 · Lokasyon kavramları ayrımı (M12-13) — P1 · S
- **Canlı:** YOK (servis verisi yok). `addresses` (`models/account.py:177-187`: label, line, district, city) mevcut.
- **Yaklaşım:** Kavramlar ayrı tablolardadır, ezme yapısal olarak imkânsız: **tesis/lokasyon** = `service_orders.address_id` → `addresses` (şehir `addresses.city`); **cihaz bölgesi** = E04 `maintenance_forms.zone` / `service_equipment` konumu; **teknisyen konum notu** = E09 `service_time_entries` not alanı (kişisel). PB bakım formu kaydı `service_orders`'ın `address_id`, `konu`, `aciklama` alanlarına yazmaz (E04 servis fonksiyonunda test). Raporda tek öncelik kuralı `lokasyon_anahtari()`: `address_id` → (yoksa) ekipmanın `address_id`'si → "Lokasyon belirtilmemiş". Teknisyen notu hiçbir gruplamada anahtar olmaz.
- **Kabul:** (1) PB formu kaydı sonrası iş emrinin adres/konu/açıklaması değişmemiş (`db.refresh`). (2) Müşteri Lokasyon sayfası adrese göre gruplar; notu değişen iş başka gruba geçmez. (3) Boş şehir "Şehir belirtilmemiş" satırında.
- **Canlı risk:** Yok; `addresses`'e yazma yok.

### E12-04 · Kategori tek fonksiyon; iptal atölye işi açık sayılmaz (M12-D02) — P1 · S
- **Canlı:** YOK.
- **Yaklaşım:** Kategori E01 `service_orders.kategori` kolonudur, yalnız `tur_kategorisi(tur)` doldurur (CHECK `ck_so_kategori`); rapor kategoriyi yeniden türetmez (iş no öneki "PB-" ile tahmin yasak). Atölye kaydı IPTAL olunca E05 `atolye.durum_degistir` servis işini `durum_degistir(hedef="IPTAL", kaynak="ATOLYE")` ile iptal eder; rapor "IPTAL" grubunda sayar, açık/geciken listelerine girmez.
- **Kabul:** (1) Unit test: her `SERVIS_TURLERI` değerinin kategorisi tanımlı. (2) Atölye iptali sonrası `/ozet` açık sayısı ve geciken listesi işi içermez, iptal sayısı +1.
- **Canlı risk:** Yok.

### E12-05 · Hesaplama doğruluğu: eksik süre, aylık akış, personel listesi, toplam eşitliği (M12-09) — P1 · S
- **Canlı:** YOK.
- **Yaklaşım (`rapor_hesap.py`):**
  - `sure_eksik_mi`: grup = COZULDU **ve** hiçbir tarihte geçerli (iptal edilmemiş, MOLA dışı) `service_time_entries` satırı yok → `NOT EXISTS` alt sorgusu, **tarih filtresinden bağımsız**. Açık ve iptal işler eksik sayılmaz. Hesaplanır, saklanmaz.
  - Aylık özet: `gelen` = `created_at` ayına, `cozulen` = `completed_at` ayına göre iki ayrı `GROUP BY date_trunc('month', … AT TIME ZONE 'Europe/Istanbul')`; kohort sayımı yok.
  - Personel listesi: dönemdeki işlere aktif/geçmiş ataması olan (`service_order_assignments`) teknisyenler ∪ süre kaydı olanlar; kaydı olmayan "kişi-saat: eksik" satırıyla.
  - Kişi-saat: `sum(extract(epoch from bitis-baslangic))/3600` yalnız `faaliyet <> 'MOLA'`, iptal edilmemiş, bitişi dolu kayıtlar; gece yarısını aşan kayıt başlangıç gününe yazılır (eski kural korunur).
  - Özet eşitliği: `toplam = acik + cozuldu + iptal + tanimsiz` sunucuda `assert` değil, test ile kilitlenir; yanıtta dört sayı ve toplam birlikte döner.
- **Kabul:** Eski kabul kriterleri birebir: eksik = çözülmüş ve hiç kaydı olmayan; aylık özet açılan/çözülen ayrı; kaydı olmayan atanmış teknisyen listede "eksik"; eşitlik her filtrede sağlanır (parametrik test).
- **Canlı risk:** Yok.

### E12-06 · Excel hücre tipleri sütun şemasından (M12-10) — P1 · S
- **Canlı:** KISMEN. `services/export.py` openpyxl ile yazıyor; Python `str` metin kalıyor (yani `"0012345"` bozulmaz), formül enjeksiyonu kapalı (`:26-42`). Ama şema yok: tarih biçimi ayarlanmıyor, sütun bazında tip garantisi yok, `Decimal` → `float` (`:20-23`).
- **Yaklaşım:** `rapor_excel.py` içinde `tipli_sayfa(ws, sema, satirlar)`: her hücrenin tipi `SUTUN_SEMALARI`'ndan gelir (§5). Seri no/iş no/telefon her zaman METIN (`number_format "@"`), tarih gerçek `date`, kişi-saat ONDALIK. `export.satirlari_xlsx` **değiştirilmez** (mobilite raporları etkilenmez).
- **Kabul:** (1) `0012345`, 18–19 haneli ve harfli seri no ile `+905…` telefon, openpyxl ile geri okunduğunda `data_type == "s"` ve değer birebir. (2) Tarih hücreleri `is_date` ve `DD.MM.YYYY`. (3) Kişi-saat sütunu sayısal; toplamı Yönetim Özeti ile eşit.
- **Canlı risk:** Yok (yeni modül).

### E12-07 · Rapor doğrulama test veri seti ve KPI regresyon testi (M12-D01) — P1 · M
- **Canlı:** KISMEN. Test altyapısı (gerçek PG17, `_test` DB, FakeClock, fixture'lar `tests/conftest.py:126-250`) ve altın kayıt emsali (`tests/migration/test_altin_kayit.py`) var; servis verisi yok.
- **Yaklaşım:** `tests/fixtures/servis_rapor_seed.py`: yalnız test DB'sinde, servis fonksiyonları üzerinden (doğrudan INSERT değil) idempotent veri kurar — 3 birim, tüm durum grupları, POC çözüm kanalları, yeniden açılmış iş, TEKRAR_ARIZA bağlı iş, `0012345` ve 19 haneli seri, süre kaydı olmayan çözülmüş iş, **AKYAKA sözleşmesi 17 cihazlı PB dönemi (15 tamamlanmış)**, atölye iptali, parça çıkış/iade (E11 hazırsa). `servis_rapor_beklenen.json`: elle hesaplanmış beklenen tablo. `tests/integration/test_servis_rapor_altin.py`: 6 filtre kombinasyonunda `/ozet`, `/kirilim`, `kitap.xlsx` (openpyxl ile okunur) değerleri beklenenle **ve** birbirleriyle karşılaştırılır. Seed `seeds/dev.py`'ye eklenmez; üretim DB'sinde çalışamaz (`settings.env != "test"` ise `RuntimeError`).
- **Kabul:** Seed iki kez koşunca satır sayısı aynı; tüm beklenen değerler eşit; altın kayıt testi (932 iş / 552.825,00 TL) yeşil.
- **Canlı risk:** Yok; yeni tablolar `_TRUNCATE` kuralına uyar (E01 ekler).

### E12-08 · Sunucu tarafı tek KPI/rapor motoru, `/ozet`, parametre doğrulama, tıklanabilir KPI (M12-01) — P2 · L
- **Canlı:** KISMEN. "JSON + aynı fonksiyondan xlsx" kalıbı (`api/reports.py:1-6, 33-38`), `donem_dogrula` (`api/deps.py:128`), `sayfala` (`:170`) var. Servis motoru, KPI sözlüğü, tıklanabilir kutu yok (`PanelPage.tsx` kartları tıklanamaz).
- **Yaklaşım:** `rapor_motoru.py`:
  - `@dataclass RaporFiltresi` + `filtre_dogrula(f, user, clock)` → `RaporHatasi(ValueError)` (API 400), yetkisiz birim `RaporYetkiHatasi` (403), 24 ay sınırı.
  - `temel_sorgu(user, f) -> Select` (kapsam üçlüsü + filtre; tarih esası yalnız detay listesini süzer, gelen/çözülen/dönem sonu açık sayıları esastan bağımsız).
  - `KPI_FILTRELERI: dict[str, Callable[[Select, RaporFiltresi, Clock], Select]]` — sayı (`count`) ve liste (`sayfala`) **aynı** fonksiyondan.
  - `ozet()` yanıtı: `{generated_at, filtreler, kapsam, kpiler:[{kod, baslik, deger, birim, onceki, fark, fark_yuzde, eksik, kpi}], toplamlar}`.
  - E01-14 servis paneli (`services/teknik_servis/panel.py`) ve E02/E03/E04/E05 KPI'ları bu motoru çağırır; kendi sayaç SQL'i yazmaz.
  - Ön yüz: §6 `KpiKutusu`, `ServisRaporlariPage`.
- **Kabul:** (1) Aynı filtrede `/ozet` ile `kitap.xlsx` Yönetim Özeti değerleri eşit (otomatik). (2) Her KPI kodu için `/ozet` değeri = `/kpi-liste?kpi=` `X-Toplam-Kayit` (parametrik test). (3) Bilinmeyen `tarih_esasi/kategori/birim/durum_grubu` → 400; yetkisiz birim → 403; 25 aylık aralık → 400. (4) Yanıtta `generated_at` (FakeClock) ve `kapsam`. (5) 403/200 matrisi: SERVIS_TEKNISYEN (rapor.gor yok) 403, SATIS (servis.gor yok) 403, SERVIS_SEF 200.
- **Canlı risk:** Yok — mobilite `dashboard` ve `/api/raporlar/*` değişmez.

### E12-09 · Kişi bazlı rapor izni ve dışa aktarımın denetim kaydı (M12-16) — P2 (üretim öncesi zorunlu) · M
- **Canlı:** KISMEN. `audit.log` (`services/audit.py:26`) ve `is_personal_data` bayrağı var; KVKK dökümü erişim kaydı yazıyor (`api/kvkk.py:94-101`). Rapor `.xlsx` uçları denetime **yazmıyor** (`api/reports.py:84-180`); kişi bazlı rapor izni yok.
- **Yaklaşım:** `permissions.py` + `rapor.personel` (§3). `SUTUN_SEMALARI`'ndaki `kisisel=True` kolonlar (teknisyen adı bazlı süre, teknisyen notu, konum notu, `iletisim_ad/telefon`) ve sayfalar (Personel KPI, Süre Hareketleri, Veri_Sureler, Pivot_KisiSaat) izin yoksa **yanıtta/çıktıda hiç yer almaz** (anahtar silinir, `None` yazılmaz). Teknisyen boyutlu kırılım ve `teknisyen_id` filtresi izin yoksa 403. Her `.xlsx` ucu §4 sonundaki `audit.log` kaydını yazar (ayrı log tablosu açılmaz). Mevcut mobilite rapor uçlarına aynı denetim kaydı **bu aşamada eklenmez** (güvenlik sıkılaştırma aşamasına not; karar K9).
- **Kabul:** (1) `rapor.personel` olmayan SERVIS_YONETICI kopyası rolde `/ozet`, `/kirilim`, `kitap.xlsx` çıktısında kişisel anahtar/sayfa yok (anahtar kümesi testi). (2) Her Excel indirmesi `audit_logs`'a `action="rapor.disaaktar"`, filtreler, satır sayısı ile tam bir satır yazar; kişisel sayfa varsa `is_personal_data=True`. (3) YONETIM rolü `rapor.personel` almaz (unit test).
- **Canlı risk:** Düşük — yalnız yeni izin ve yeni uçlar; `test_permissions.py` maliyet kümesi değişmez.

### E12-10 · Süzme ve toplama veritabanında; ham süre kayıtları toptan gönderilmez (M12-15) — P2 (üretim öncesi zorunlu) · M
- **Canlı:** KISMEN. Canlı raporlar `GROUP BY` ile DB'de topluyor (`services/reports.py`); liste uçları `limit le=200` + `sayfala`. Eski sistemdeki "tüm süre kayıtları" ucu canlıda yok, servis tarafında henüz hiçbir uç yok.
- **Yaklaşım:** Tüm KPI ve kırılımlar SQL `count/sum/percentile_cont` ile; Python döngüsünde satır toplama yok. E09'un zaman listesi ucu sayfalı ve tarih zorunlu; "tüm süre kayıtları" ucu açılmaz. Ham süre satırları yalnız `kitap.xlsx` `Veri_Sureler` sayfasında, `rapor.personel` + 24 ay + `servis_rapor_excel_azami_satir` sınırıyla. İndeksler: E01 `ix_so_durum_olusma`, `ix_so_kapanis`, `ix_so_birim_durum` + E12 `ix_so_ilk_cozum`; E09'dan `ix_ste_is_baslangic(service_order_id, baslangic)` istenir.
- **Kabul:** (1) Kod incelemesi + test: hiçbir JSON uç 200'den fazla süre satırı dönmez. (2) 24 ay sınırı tüm uçlarda 400. (3) 10.000 işlik test verisinde `/ozet` < 1 sn (EXPLAIN'de seq scan yok — performans testi `-m perf`, CI dışı).
- **Canlı risk:** Yok.

### E12-11 · Eksik kırılımlar ve tam eşleşen personel filtresi (M12-08) — P2 · M
- **Canlı:** YOK.
- **Yaklaşım:** `kirilim(boyut)`: **şef** = aktif `service_order_assignments.rol='SEF'` (yoksa "Şef atanmamış"); **müşteri** = `customer_id` → `accounts.title` (iş bazlı; M14 kimliği = canlı hesap kimliği); **şehir** = `addresses.city` (boş → "Şehir belirtilmemiş"); **öncelik** = `service_orders.oncelik`; **çözüm şekli** = geçerli (`gecersiz_at IS NULL`) `service_results.cozum_kanali`. Personel filtresi `teknisyen_id: int` (users.id) → `EXISTS assignments WHERE user_id = :id`; ad üzerinden `LIKE` yok.
- **Kabul:** Süre kaydı olmayan işli müşteri "n iş / kişi-saat: eksik"; şef toplamları + "Şef atanmamış" = filtrelenen iş; "Ali Veli" (id) seçimi "Aliye"yi getirmez; boş şehir ayrı satır.
- **Canlı risk:** Yok.

### E12-12 · Planlı bakım tamamlama raporu (sözleşme/dönem) (M12-05) — P2 · M
- **Canlı:** YOK.
- **Yaklaşım:** Hesap tek yerde: E04 `services/teknik_servis/bakim_raporlari.py` içinde `donem_tamamlama(db, user, f)` (E04-18 aynı fonksiyonu kullanır; E12 ikinci kopya yazmaz). Satır = `maintenance_periods`; payda = döneme bağlı PB işleri (`tur='PB' AND maintenance_period_id = …`, iptal hariç — `uq_so_pb_cihaz_donem` sayesinde cihaz başına tek iş); pay = COZULDU grubundakiler; dönem durumu `closed_at/closing_kind`'dan (kapanmamışsa "Açık"); dönem tamamlanma tarihi `maintenance_periods.closed_at`. Sözleşme tutarı kolonu yok. Gecikme: `target_date` + `bakim_tolerans_gun` (E04 ayarı) geçmiş ve kapanmamış.
- **Kabul:** AKYAKA 17 cihaz senaryosunda satır `%88,2 (15/17) — Açık`; sayım iş emirlerinden; tarih plan kapanışından; yanıtta para alanı yok; `bakim.gor` yoksa 403.
- **Canlı risk:** Yok.

### E12-13 · SLA ve gecikme raporu (günlük servis) (M12-03) — P2 · M
- **Canlı:** YOK. SLA modülü (E10) tasarlanmadı; E01 yalnız `sla_due_at` için yer ayırdı.
- **Yaklaşım:** E12 SLA **hesaplamaz, okur.** Beklenen E10 alanları (`service_orders`, nullable): `sla_due_at` (M10 ResolveDueAt), `first_completed_at` (ResolvedAt — E12-02), `sla_paused_minutes` (yalnız `servis_sla_durduran_bekleme_nedenleri`'ndeki `service_holds` sürelerinden), `sla_result` (`ck_so_sla_sonuc` IN ('ICINDE','ASILDI','OLCULEMEDI'), ilk çözümde damgalanır), `delay_reason` (`ck_so_gecikme_nedeni`). Rapor: kategori = GUNLUK_SERVIS (PB ve ATOLYE ayrı/hariç), iptal paydada yok, `sla_result='OLCULEMEDI'` ayrı satır; uyum = ICINDE / (ICINDE+ASILDI); geciken açık = `sla_due_at < now` ve ACIK grup; gecikme nedeni dağılımı. E10 alanları şemada yoksa uç 404 "SLA modülü etkin değil", sekme gizli.
- **Kabul:** PB-… numaralı iş hiç görünmez; yalnız SLA'yı durduran bekleme düşülür (test: MALZEME beklemesi düşülmez, MUSTERI_ONAYI düşülür); "Geciken" sayısı servis panelindeki `geciken` KPI'sıyla aynı veride eşit; gecikme nedeni dağılımı Excel'de.
- **Canlı risk:** Yok.

### E12-14 · Tekrar arıza ve tekrar ziyaret raporu (M12-04) — P2 · M
- **Canlı:** YOK.
- **Yaklaşım:** **Onaylı oran:** E01 K7 `iliski_turu='TEKRAR_ARIZA'` bağı (şef/kapat yetkilisi kurar = M10-04 "şef onaylı" işaretin canlı karşılığı). Pay = dönemde çözülmüş GUNLUK_SERVIS+ATOLYE işlerinden, çözümden sonraki `tekrar_gun` içinde kendisine TEKRAR_ARIZA ile bağlanan yeni iş olanlar; payda = dönemde çözülenler. **Onaysız (geçmiş) satır:** E01 göçünden gelen ve bağ kurulmamış işlerde aynı `equipment_id` (yoksa aynı `seri_norm`) + `tekrar_gun` penceresi ile otomatik hesap, ayrı satırda "onaysız" etiketi; seri no'suz iş hesaba girmez. **Tekrar ziyaret:** çözülen işte saha faaliyetli (`YOL` hariç) `service_time_entries`'in farklı gün sayısı ≥ 2 (E02 plan ziyaretleri yedek kaynak); süre kaydı olmayan "eksik". Kırılımlar: teknisyen (`rapor.personel`), müşteri, marka/model (E03 ekipman → ürün), birim.
- **Kabul:** Onaylı oran yalnız bağdan; onaysız satır ayrı ve etiketli; yeniden açılan iş (E12-15) tekrar arıza sayılmaz; tekrar ziyaret ayrı sayı; `tekrar_gun=200` → 400.
- **Canlı risk:** Yok.

### E12-15 · Yeniden açılan iş göstergesi (M12-D03) — P2 · S
- **Canlı:** YOK.
- **Yaklaşım:** Kaynak `service_order_events` (silinemez): `olay_turu='DURUM' AND yeni_durum='TEKRAR_ACILDI'` olayı dönemde olan işler. Liste kolonları: iş no, ilk çözüm (`first_completed_at`), yeniden açılış anı (olay zamanı), gün farkı, gerekçe (olay `ozet`'i; E01 gerekçeyi zorunlu tutar). Oran = yeniden açılan / dönemde ilk kez çözülen. PB (kategori PLANLI_BAKIM) ayrı satır. Tekrar arıza hesabı bağ (`iliski_turu`) kullandığı için çift sayım yapısal olarak yok.
- **Kabul:** Aynı iş iki kez yeniden açılsa listede iki olay, sayıda bir iş; PB ayrı satır; bu işler tekrar arıza oranında yok.
- **Canlı risk:** Yok.

### E12-16 · Veri Kalitesi sayfası (yalnız listeler) (M12-14) — P2 · M
- **Canlı:** KISMEN. Hesap mükerrer adayı (`services/accounts.py:84` `mukerrer_adaylari`, `title_key`), `eksik_alanlar` (`:64`) var; servis kontrolleri yok.
- **Yaklaşım:** `rapor_kalite.py` `KONTROLLER: dict[kod, KaliteKontrolu(baslik, filtre)]`: `tanimsiz_durum` (göç karantinası/grup dışı), `cozum_zamani_eksik` (COZULDU ve `completed_at`/`first_completed_at` NULL), `sure_kaydi_eksik` (E12-05 tanımı = E09 süre disiplini tanımıyla aynı fonksiyon), `seri_eksik` (`servis_seri_zorunlu_turler` türünde aktif `service_order_serials` yok), `lokasyonsuz` (`address_id` NULL), `sef_atanmamis`, `musteri_varyanti` (`mukerrer_adaylari` / `title_key` eşleşmesi — yeni normalizasyon yazılmaz), `sla_olculemedi` (E10 varsa). Sayfa hiçbir veriyi düzeltmez; satırdaki iş no `/servis-isleri/{id}`'ye gider. Yönetim Özeti'nde "Bu raporda n işte eksik veri var" + bağlantı. Uyarı bloğu §7.
- **Kabul:** Her kontrolün sayısı = listesinin `X-Toplam-Kayit`'i; sayfa çağrısından önce/sonra tablo satırları değişmemiş; müşteri varyantı canlı `mukerrer_adaylari` sonucuyla aynı küme.
- **Canlı risk:** Yok (salt okuma).

### E12-17 · Native Excel PivotTable ve tipli ham veri tabloları (M12-02) — P2 · M
- **Canlı:** YOK. openpyxl (`pyproject.toml` `openpyxl>=3.1`) PivotTable **oluşturamaz**; yalnız yüklenen dosyadaki pivotları korur ve önbellek tanımını düzenlemeye izin verir.
- **Yaklaşım:** Yeni bağımlılık eklenmez (karar K2). `templates/excel/servis_pivot_sablonu.xlsx` bir kez Excel 365'te hazırlanır: `Veri_IsEmirleri` ve `Veri_Sureler` adlı Excel Tabloları (tek örnek satır) + 3 pivot (`Pivot_Birim`: birim × kategori × durum grubu; `Pivot_Ay`: ay × gelen/çözülen; `Pivot_KisiSaat`: teknisyen × faaliyet kişi-saat). Çalışma anında `rapor_excel.pivot_kitabi()`: şablonu `load_workbook` ile açar, tabloları tipli satırlarla doldurur, `table.ref`'i yeni satır sayısına günceller, her pivot önbelleğinde `cacheSource.worksheetSource` tablo adını gösterir ve `refreshOnLoad=True` yapar; okunabilir sayfaları (§5) aynı kitaba ekler. `rapor.personel` yoksa `Veri_Sureler` ve `Pivot_KisiSaat` kitaptan silinir. Boş sonuçta tablolar tek "Kayıt yok" satırı taşır ve pivot hata vermez. Şablon dosyası sürüm numarası `Tanımlar` sayfasında yazılır; şablon değişikliği PR'da ikili dosya olarak gözden geçirilir.
- **Kabul:** (1) Excel 365 masaüstünde "onarım" uyarısı olmadan açılır, pivot alan bölmesi gelir (elle kabul testi, sürüm notuna yazılır). (2) Otomatik test: zip içinde `pivotCacheDefinition*.xml` `refreshOnLoad="1"`, tablo `ref` satır sayısı = veri + 1. (3) Pivot kişi-saat toplamı (veri tablosu toplamı) = Yönetim Özeti kişi-saati. (4) 0 satırlı filtrede dosya açılır, "Kayıt yok". (5) LibreOffice'te açılır; pivot yenilemesinin garanti olmadığı Tanımlar'da yazılı.
- **Canlı risk:** Yok (yeni dosya ve uç).

### E12-18 · Önceki dönem karşılaştırması ve 12 aylık trend (M12-06) — P3 · M
- **Canlı:** YOK.
- **Yaklaşım:** `ozet()` önceki **eşit uzunlukta** dönemi aynı motorla hesaplar; fark ±n ve ±% (önceki 0/boşsa "—"). `trend()`: `generate_series` ile 12 ay; gelen (`created_at`), çözülen (`completed_at`), kişi-saat (E12-05 tanımı, toplam). **Dönem sonu açık** sayısı `service_order_events` DURUM olaylarından aralık kurarak hesaplanır (açılış ≤ ay sonu < çözüm/iptal anı); olay geçmişi olmayan göç işlerinde yanıt `gecmis_degisebilir: true` ve ekranda "geçmiş değerler değişebilir" notu. SLA/tekrar arıza trendi sonraki dilime bırakılır.
- **Kabul:** Önceki dönem boşsa "—"; trend 12 satır, boş ay 0 değil "0 iş" olarak döner (akış sayısı için 0 doğrudur, kişi-saat kaydı yoksa "—"); dönem sonu açık, olay tablosuyla elle hesaplanan beklenen değere eşit.
- **Canlı risk:** Yok.

---

## 9. Testler

| Dosya | Kapsam |
|---|---|
| `tests/unit/test_servis_rapor_tanimlari.py` | Durum grubu kapsayıcılığı; her `SERVIS_TURLERI` kategorili; her KPI'nın tanım metni dolu; kişisel kolon listesi; `rapor.personel` en az bir rolde, YONETIM'de değil; maliyet kümesi değişmemiş. |
| `tests/integration/test_servis_rapor_rbac.py` | Her uç için 403/200 matrisi (SERVIS_TEKNISYEN, SATIS, YONETIM, SERVIS_SEF, SERVIS_YONETICI); `rapor.personel` yokken kişisel anahtar/sayfa yok. |
| `tests/integration/test_servis_rapor_kapsam.py` | İki birimden iki şef: rapor sayıları yalnız kendi birimi; yetkisiz `birim` 403; `KENDI_MUSTERILERI` satış rolü (servis.gor verilirse) yalnız kendi müşterisi; Excel satırları kapsamlı. |
| `tests/integration/test_servis_rapor_hesap.py` | E12-01..05, 11, 14, 15, 18 kabul kriterleri (FakeClock). |
| `tests/integration/test_servis_rapor_excel.py` | Tip testleri (E12-06), denetim kaydı (E12-09), pivot XML (E12-17), satır sınırı 400. |
| `tests/integration/test_servis_rapor_altin.py` | E12-07 seed + beklenen tablo; ekran = Excel. |
| `tests/migration/test_migration_zinciri.py` | `first_completed_at` migration'ı head→base→head. |
| `tests/migration/test_altin_kayit.py` | Değişmeden yeşil. |

Ön yüz: `npm run build` + `oxlint`.

---

## 10. Uygulama sırası

1. E12-01, E12-02 (E01 çekirdeği ile aynı PR'da; kolon E01 migration'ına).
2. E12-04, E12-03, E12-05, E12-06, E12-07 (P1; E09 zaman kaydı geldikten sonra).
3. E12-08 motor + `ServisRaporlariPage` + `KpiKutusu`; E12-09 izin + denetim; E12-10 performans.
4. E12-11, E12-15, E12-16, E12-14; E12-12 (E04 ile); E12-13 (E10 ile).
5. E12-17 pivot; E12-18 trend.

Her adımda `make test` (altın kayıt dahil), `test_migration_zinciri`, `ruff`, `npm run build`.

---

## 11. Kararlar (kullanıcıya soru sorulmadı)

- **K1 "Çözüldü" durumu.** Yeni katalogda ayrı durum yok; TAMAMLANDI = çözüldü, KAPATILDI = idari kapanış; ikisi "Çözüldü" grubunda. *Gerekçe:* E01 durum makinesi böyle tasarlandı; ayrı durum eski sistemdeki grup çelişkisinin (M12-11) kaynağıydı.
- **K2 Excel/pivot kütüphanesi (S4).** Mevcut openpyxl + Excel'de bir kez hazırlanmış pivot şablonu; XlsxWriter veya ticari kütüphane eklenmez. *Gerekçe:* Python kütüphanelerinin hiçbiri sıfırdan native pivot üretmiyor; şablon + `refreshOnLoad` onarım uyarısız açılıyor ve bağımlılık/lisans riski yok.
- **K3 Atölye kategorisi (S7).** Atölye Günlük Servis'ten ayrı kategori (E01 `kategori='ATOLYE'`); SLA raporu yalnız GUNLUK_SERVIS'i ölçer, tekrar arıza GUNLUK_SERVIS+ATOLYE'yi. *Gerekçe:* atölye çevrim süresi gün ölçeğinde, saha SLA'sı saat ölçeğinde; birleştirmek iki oranı da bozar.
- **K4 PB gecikme toleransı (S5).** Ayrı ayar açılmaz; E04'ün `bakim_tolerans_gun` (30) ayarı okunur. *Gerekçe:* aynı kural iki yerde tanımlanırsa ekran ve PB modülü farklı "geciken" sayısı verir.
- **K5 Menü izni.** Menü kalemi `servis.gor` ile görünür; sayfa `rapor.gor` yoksa uyarı gösterir; backend her uçta ikisini birlikte ister. `AppLayout` MENU yapısı (tek kod / herhangi biri) değiştirilmez. *Gerekçe:* canlı menü bileşenine dokunmadan yetkiyi API'de kesin uygulamak.
- **K6 Şef Excel'i (S1).** SERVIS_SEF kendi birimi için Excel alabilir (`rapor.disaaktar` E01'de verildi); kapsam motorda uygulanır, her indirme denetime yazılır.
- **K7 Ay kapanışı / arşiv.** Yayınlanmış rapor arşivi açılmaz; her çıktıda `generated_at` + filtre + kapsam yazılır, Excel indirmesi denetim izinde iz bırakır. *Gerekçe:* eski kararla uyumlu, depolama ve "hangi sürüm doğru" tartışması doğurmaz; dönem sonu açık sayısı olay tablosundan yeniden kurulabildiği için geçmiş tutarlıdır.
- **K8 Kişi bazlı veri (S2, KVKK).** Yeni izin `rapor.personel` yalnız SERVIS_YONETICI ve SERVIS_SEF'e; YONETIM (Genel Koordinatör/Muhasebe dahil) toplamları görür. *Gerekçe:* `.gor` ile bitmeyen izin YONETIM'e otomatik inmez; KVKK en az erişim.
- **K9 Mevcut rapor uçlarının denetimi.** Mobilite `/api/raporlar/*.xlsx` uçlarına denetim kaydı bu aşamada eklenmez; güvenlik sıkılaştırma aşamasına bırakılır. *Gerekçe:* "canlı akışı bozma" ve öncelik sırası (yeni modül → eksik → güvenlik).
- **K10 Tekrar arıza penceresi.** Rapor varsayılanı 30 gün (`servis_rapor_tekrar_ariza_gun`), istekte 7–180. E03'ün "90 günde ≥2 arıza" ekipman KPI'sı ayrı göstergedir ve kendi ayarını kullanır. *Gerekçe:* farklı sorulara cevap veren iki gösterge; aynı ayara bağlamak birini bozar.
- **K11 Onaylı tekrar arıza işareti.** M10-04 "şef onaylı aynı arıza" işaretinin canlı karşılığı E01 `iliski_turu='TEKRAR_ARIZA'` bağıdır (yalnız `servis.kapat` sahibi kurar); ayrı onay kolonu açılmaz.
- **K12 Maliyet gizleme biçimi.** Yeni servis raporlarında gizlenen alan **anahtar olarak çıkarılır** (`None` yazılmaz). Canlı `_maliyet_gizle` (`api/reports.py:41-46`) `None` yazıyor; mimari rehberin "alan hiç yer almaz" kuralıyla çelişen bu davranış gözlem olarak not edilir, dokunulmaz.
- **K13 Zaman dilimi.** Ay/gün gruplamaları `Europe/Istanbul` ile yapılır (`AT TIME ZONE`), Excel'e yerel saat yazılır. *Gerekçe:* timestamptz UTC tutulur; gece 00-03 arası kayıtlar aksi halde önceki güne düşer.
- **K14 İlk çözüm anı kolonu.** `first_completed_at` saklanır (olaylardan türetilmez). *Gerekçe:* SLA sonucu ve yeniden açılan iş her raporda gerekli; olay tablosundan her seferinde türetmek pahalı ve göç verisinde olay yok.
- **K15 Operasyon Merkezi.** Eski "Operasyon Merkezi" = E01-14 `ServisPaneli`; ayrı sayfa açılmaz, panel E12 motorunu çağırır.
- **K16 Test verisi.** Kullanıcıdan gelecek test verisi beklenmez; sentetik ama gerçek senaryoları (AKYAKA 17 cihaz, sıfırlı/uzun seri) içeren seed yazılır; kullanıcı verisi gelince beklenen tabloya ek senaryo olarak eklenir.

## 12. Gözlemler (değiştirilmedi)

- `services/reports.py:81` `"DEGISTI"` değeri `KALEM_EYLEMLERI`'nde `DEGISTIRILDI` olarak geçiyor; mobilite panelinde değişimler sayılmıyor olabilir (00 rehberinde de kayıtlı).
- `api/reports.py:41-46` maliyet alanlarını `None` yapıyor, anahtarı silmiyor (K12).
- Hiçbir mevcut `.xlsx` ucu dışa aktarımı denetime yazmıyor (K9).
- `export.satirlari_xlsx` sütun genişliği için tüm satırları `str()`'e çeviriyor (`services/export.py:73-78`); büyük kitapta maliyetli — yeni yazıcıda örneklem (ilk 500 satır) ile hesaplanır.
