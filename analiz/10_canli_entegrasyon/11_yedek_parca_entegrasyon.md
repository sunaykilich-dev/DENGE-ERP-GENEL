# E11 — Yedek Parça ve Servis Stoğu: Canlı ERP Entegrasyon Tasarımı

> Tarih: 2026-10-21 · Hazırlayan: entegrasyon tasarımcısı (yalnız RAPOR; kaynak koda dokunulmadı)
> Girdi: `analiz/02_moduller/_ozet/11_yedek_parca.json` (22 onaylı madde, 1'i `dotnet_specific`), `11_yedek_parca_tasarim.md`, `11_yedek_parca_denetim.md`, `10_canli_entegrasyon/00_MIMARI_KURALLAR.md`, kardeş belgeler `01_is_emirleri`, `04_planli_bakim`, `05_haberlesme_atolye`, `06_kiralama_depo`.
> Canlı kod (okunarak doğrulandı): `backend/app/models/stock.py`, `services/stock.py`, `api/stock.py`, `models/catalog.py`, `schemas/catalog.py`, `api/catalog.py`, `permissions.py`, `services/uyarilar.py`, `services/imports/__init__.py`, `api/imports.py`, `frontend/src/pages/StokPage.tsx`, `tests/integration/test_stok_ozet.py`, `tests/conftest.py`.
> Madde kimlikleri `E11-NN`; her maddede eski kimlik (`M11-xx`) yazılıdır.

---

## 1. Özet

Canlıda serisiz stok için **hareket defteri zaten var**: `stock_movements` (`models/stock.py:205-236`). Bakiye ayrı kolonda tutulmaz, hareketlerin toplamıdır (`models/stock.py:200-204`); işaret adetten okunur (`qty <> 0`, `:221, 231-233`). Bu, eski sistemdeki `Quantity>0 + Direction` önerisinin özünü (yönü bilinen, toplamla hesaplanan defter) zaten karşılıyor. Eksik olanlar:

| Konu | Canlı durum | Kanıt |
|---|---|---|
| Hareket nedeni | Yalnız 4 değer `GIRIS/CIKIS/SAYIM/TRANSFER`, CHECK canlı tabloda **değiştirilemez** | `models/stock.py:205-210, 218-220`; 06 belgesi §1 madde 4 |
| Servis işine bağ | Yok (yalnız serbest `document_no`) | `models/stock.py:235` |
| Eşzamanlılık / negatif bakiye | **Yok**: kilit yok, bakiye kontrolü yok; `-500` çıkış kabul edilir | `services/stock.py:300-340` |
| Neden doğrulaması | API'de yok; DB CHECK yakalar (409 `ck_`) | `api/stock.py:281-313` |
| Depo zorunluluğu | `warehouse_id` NULL olabilir | `models/stock.py:228-230` |
| Depo yazma ucu | Yok (yalnız `GET /depolar`) | `api/stock.py:361-371` |
| Hareket listesi | Sayfalama/filtre/Excel/maliyet yok; tek filtre `product_id`, en çok 500 | `api/stock.py:316-343` |
| Parça kartı | Ürün kataloğu var (PATCH, `is_active`, `uq_products_code` → 409); birim, minimum, "yedek parça" bayrağı yok | `models/catalog.py:53-113`, `api/catalog.py:139-178` |
| Yetki | Stok yazma `cihaz.yaz` (DEPO, TEKNIK_SERVIS rolleri); servis teknisyeni için izin yok | `api/stock.py:29-31`, `permissions.py:142-183` |
| Uyarı | Stokla ilgili uyarı yok | `services/uyarilar.py:47-192` |

**Tek öneri:** Yedek parça stoğu **ayrı bir defter tablosu açmadan**, canlı `stock_movements` tablosunun üzerine **yalnız nullable kolonlarla** kurulur ve servis depolarındaki tüm yazmalar **tek bir servis fonksiyonundan** (`services/teknik_servis/parca.py::hareket_yaz`) geçer. Ayrıntılı tür (`hareket_turu`) yeni bir kolonda tutulur, canlı `reason` CHECK'ine dokunulmaz; her ayrıntılı tür canlı 4 nedenden birine ve sabit bir işarete eşlenir. Böylece mobilite stok özeti (`services/stock.py:254-263`, `api/catalog.py:113-136`) hiçbir değişiklik olmadan doğru toplamı vermeye devam eder.

Neden ayrı tablo değil: 00 §5 "Stok — serisiz (`stock_movements`) → **Genişlet**" kararı, E01/E03/E04/E05 belgelerinin hepsi `stock_movements.service_order_id` kolonuna referans veriyor, ve ayrı bir defter "Denge'nin elinde kaç kablo var" sorusunu iki tabloya bölerdi (canlının kendi gerekçesi: `models/stock.py:200-204`).

---

## 2. Veri modeli

### 2.1 Var olan tablolara eklenenler (yalnız nullable / server_default'lu kolon)

**`stock_movements`** (`models/stock.py:213`) — dosya aynı kalır, sınıfa kolon eklenir:

| Kolon | Tip | Not |
|---|---|---|
| `hareket_turu` | String(20) NULL | Servis defteri türü. NULL = canlı mobilite hareketi (bugünkü tüm satırlar) |
| `service_order_id` | BigInteger NULL FK `service_orders.id` ON DELETE RESTRICT | Servis işi bağı (E01 tablosu; soft-delete kullandığı için RESTRICT güvenli) |
| `reversal_of_id` | BigInteger NULL FK `stock_movements.id` ON DELETE RESTRICT | Ters kaydın orijinali |
| `transfer_grup` | UUID NULL | Transferin iki bacağı aynı değeri taşır |
| `stock_count_id` | BigInteger NULL FK `stock_counts.id` ON DELETE RESTRICT | Sayım farkı hareketi |
| `part_request_id` | BigInteger NULL FK `service_part_requests.id` ON DELETE SET NULL | Talebi karşılayan çıkış |
| `unit_cost` | Numeric(14,4) NULL | Hareket anında dondurulan birim maliyet (TL). Yalnız `sees_cost` görür |

Kısıtlar (yeni; mevcut `ck_stok_hareket_neden` ve `ck_stok_hareket_adet` aynen kalır):

```sql
ck_stok_hareket_tur:   hareket_turu IS NULL OR hareket_turu IN
  ('GIRIS','ACILIS','CIKIS_SERVIS','IADE_SERVIS','ZAYI','TERS_KAYIT',
   'TRANSFER_CIKIS','TRANSFER_GIRIS','SAYIM_FAZLASI','SAYIM_EKSIGI')
ck_stok_hareket_tur_yon:  -- tür → canlı neden + işaret eşlemesi şemada kilitli
  hareket_turu IS NULL
  OR (hareket_turu IN ('GIRIS','ACILIS','IADE_SERVIS') AND reason='GIRIS' AND qty>0)
  OR (hareket_turu IN ('CIKIS_SERVIS','ZAYI')          AND reason='CIKIS' AND qty<0)
  OR (hareket_turu = 'TRANSFER_CIKIS' AND reason='TRANSFER' AND qty<0)
  OR (hareket_turu = 'TRANSFER_GIRIS' AND reason='TRANSFER' AND qty>0)
  OR (hareket_turu = 'SAYIM_FAZLASI'  AND reason='SAYIM'    AND qty>0)
  OR (hareket_turu = 'SAYIM_EKSIGI'   AND reason='SAYIM'    AND qty<0)
  OR (hareket_turu = 'TERS_KAYIT'     AND reversal_of_id IS NOT NULL)
ck_stok_hareket_servis_isi: hareket_turu NOT IN ('CIKIS_SERVIS','IADE_SERVIS') OR service_order_id IS NOT NULL
ck_stok_hareket_depo:       hareket_turu IS NULL OR warehouse_id IS NOT NULL
ck_stok_hareket_ters_gerekce: hareket_turu <> 'TERS_KAYIT' OR length(trim(coalesce(notes,''))) > 0
ck_stok_hareket_transfer:   hareket_turu NOT IN ('TRANSFER_CIKIS','TRANSFER_GIRIS') OR transfer_grup IS NOT NULL
ck_stok_hareket_maliyet:    unit_cost IS NULL OR unit_cost >= 0
uq_stok_hareket_ters  (reversal_of_id) UNIQUE WHERE reversal_of_id IS NOT NULL   -- ters kayıt tek seferlik
ix_stok_hareket_servis (service_order_id) WHERE service_order_id IS NOT NULL
ix_stok_hareket_belge  (document_no) gin_trgm_ops  -- belge no ile arama (pg_trgm zaten kurulu)
ix_stok_hareket_depo_urun (warehouse_id, product_id)
```

Not: `TERS_KAYIT` satırı orijinalin `reason`'ını ve işaretinin tersini taşır; ör. `CIKIS -3` → `CIKIS +3`. `reason='CIKIS' AND qty>0` canlı CHECK'leri ihlal etmez (canlı yalnız `qty<>0` ve neden listesini sınar). Mobilite toplamları (`Σqty`) bu yüzden kendiliğinden doğrudur.

Değiştirilemezlik (E11-22): `trg_stok_hareket_degismez` — `BEFORE UPDATE OF product_id, warehouse_id, qty, reason, hareket_turu, service_order_id, reversal_of_id, unit_cost OR DELETE ON stock_movements FOR EACH ROW WHEN (OLD.hareket_turu IS NOT NULL)` → `RAISE EXCEPTION`. Yalnız servis defteri satırlarını korur; mobilite satırlarının bugünkü davranışı değişmez. `created_by` SET NULL kaskadı ve `TRUNCATE` (testler) tetikleyiciye takılmaz. Yalnız `warehouse_id` FK'si `ON DELETE SET NULL`; depo silme ucu olmadığı ve servis depoları yalnız pasifleştirildiği için çakışma yok (depo `DELETE` denemesi tetikleyiciyle reddedilir, bu bilinçli).

**`products`** (`models/catalog.py:53`):

| Kolon | Tip | Kısıt |
|---|---|---|
| `yedek_parca` | Boolean server_default false | Parça seçicilerinde süzgeç. `type` CHECK'i (`ck_products_tip`) değiştirilmez; bayrak ayrı |
| `birim` | String(10) NULL (NULL = ADET) | `ck_products_birim`: NULL veya `('ADET','METRE','TAKIM','LITRE','PAKET','KUTU')` |
| `min_stok` | Integer NULL | `ck_products_min_stok`: NULL veya ≥ 0. NULL/0 = uyarı yok |
| `ck_products_yedek_parca_serisiz` | — | `NOT yedek_parca OR identity_kind = 'YOK'` — seri takipli ürün adetle izlenmez (`services/stock.py:321-325` kuralının şemaya taşınması, yalnız yeni bayrağa uygulanır) |

**`warehouses`** (`models/stock.py:64`): E06'nın eklediği `birim` (NULL = ortak) ve `kiralama_deposu` kolonlarına ek olarak `servis_deposu` Boolean server_default false. `ck_warehouse_tur_tekil`: `NOT (servis_deposu AND coalesce(kiralama_deposu,false))`. Teknisyen araç deposu = `location_type='TEKNISYEN'`, `user_id` dolu, `servis_deposu=true` (canlıdaki kolonlar, `models/stock.py:72-76`).

### 2.2 Yeni tablolar (`models/teknik_servis.py` içinde, `models/__init__.py`'ye eklenir)

| Tablo | Mixin | Kolonlar | Kısıtlar |
|---|---|---|---|
| `stock_counts` (sayım) | Pk, Timestamp, Actor, SoftDelete, Versioned | `count_no` String(24) (`stok_sayim_no_seq` → `SAY-YYYYAA-NNNNNN`), `warehouse_id` FK RESTRICT, `durum` (`SAYIM_DURUMLARI = ("ACIK","ONAYLANDI","IPTAL")`), `baslangic_at`, `onaylayan_id` FK users SET NULL, `onay_at`, `gerekce` String(500), `notes` | `uq_stok_sayim_no`, `ck_stok_sayim_durum`, `uq_stok_sayim_acik` (warehouse_id) WHERE `durum='ACIK' AND NOT is_deleted`, `ck_stok_sayim_onay` (durum<>'ONAYLANDI' OR (onaylayan_id IS NOT NULL AND onay_at IS NOT NULL AND length(trim(gerekce))>0)) |
| `stock_count_lines` | Pk, Timestamp | `stock_count_id` FK CASCADE, `product_id` FK RESTRICT, `sistem_adet` Integer (açılış anı görüntüsü), `sayilan_adet` Integer NULL, `onay_anindaki_adet` Integer NULL | `uq_stok_sayim_satir` (stock_count_id, product_id), `ck_stok_sayim_sayilan` (sayilan_adet IS NULL OR ≥0) |
| `service_part_requests` (parça talebi) | Pk, Timestamp, Actor, SoftDelete, Versioned | `service_order_id` FK RESTRICT, `product_id` FK RESTRICT, `adet` Integer, `durum` (`TALEP_DURUMLARI = ("ACIK","KARSILANDI","IPTAL")`), `karsilanma_at`, `iptal_nedeni` String(200), `notes` String(500), `hold_id` FK `service_holds.id` SET NULL (isteğe bağlı malzeme beklemesi) | `ck_parca_talep_durum`, `ck_parca_talep_adet` (>0), `uq_parca_talep_acik` (service_order_id, product_id) WHERE `durum='ACIK' AND NOT is_deleted` |

Göç: eski V1.20.1 `ServicePartMovements` göçü yapılmayacak (E11-21 kararı: eski serbest metin korunur, hareket üretilmez); bu nedenle `SourceMixin` yalnız `stock_counts` için gereksizdir ve eklenmez.

### 2.3 Migration

- `make makemigration m="yedek_parca_stok_defteri"`; E01 (servis iş emri çekirdeği, `service_orders`, `service_holds`) ve E06 (`warehouses.birim`) migration'larından **sonra** gelir; tek head kuralı.
- Dosya başı NEDEN: "Servis parçası canlı serisiz stok defterine yazılır; canlı `ck_stok_hareket_neden` değiştirilmeden ayrıntılı tür ayrı kolonda tutulur…".
- Var olan tablolara: `op.add_column` (hepsi nullable/server_default), `op.create_check_constraint` (yeni adlı kısıtlar, yalnız yeni kolonları sınar; mevcut satırlarda `hareket_turu IS NULL` olduğu için doğrulama anında geçer), `op.create_index` (`postgresql_where`, gin `gin_trgm_ops`), tetikleyici fonksiyonu `op.execute`.
- Yeni tablolar, `CREATE SEQUENCE stok_sayim_no_seq`.
- `downgrade`: tetikleyici → fonksiyon → indeksler → kısıtlar → kolonlar → tablolar (FK sırası) → sequence. head→base→head testi (`tests/migration/test_migration_zinciri.py`) yeşil kalmalı.
- Uydurma veri yazılmaz; mevcut satırlara `hareket_turu` geriye dönük atanmaz (canlı satırlar mobiliteye ait).

---

## 3. Servis katmanı

`backend/app/services/teknik_servis/parca.py` (alt paket emsali `services/imports/`):

```python
class ParcaHatasi(ValueError): ...           # API 409'a çevirir

HAREKET_TURLERI = ("GIRIS","ACILIS","CIKIS_SERVIS","IADE_SERVIS","ZAYI","TERS_KAYIT",
                   "TRANSFER_CIKIS","TRANSFER_GIRIS","SAYIM_FAZLASI","SAYIM_EKSIGI")
TUR_KURALI = {  # tür -> (canlı reason, işaret); TERS_KAYIT orijinalden türetilir
  "GIRIS": ("GIRIS", +1), "ACILIS": ("GIRIS", +1), "IADE_SERVIS": ("GIRIS", +1),
  "CIKIS_SERVIS": ("CIKIS", -1), "ZAYI": ("CIKIS", -1),
  "TRANSFER_CIKIS": ("TRANSFER", -1), "TRANSFER_GIRIS": ("TRANSFER", +1),
  "SAYIM_FAZLASI": ("SAYIM", +1), "SAYIM_EKSIGI": ("SAYIM", -1)}
KAPALI_SERVIS_DURUMLARI = ("TAMAMLANDI", "KAPATILDI", "IPTAL")   # E01 makinesi
PASIFTE_SERBEST = ("IADE_SERVIS", "TERS_KAYIT")

async def bakiye(db, product_id, warehouse_id) -> int            # Σ qty
async def bakiyeler(db, *, depo_idler, product_id=None) -> dict  # (ürün, depo) -> adet
async def stok_durumu(toplam: int, min_stok: int | None) -> str  # "YOK" | "AZ" | "YETERLI" (E11-10 tek fonksiyon)
async def hareket_yaz(db, *, tur, product_id, warehouse_id, adet, clock, user_id,
                      service_order_id=None, document_no=None, notes=None,
                      unit_cost=None, transfer_grup=None, stock_count_id=None,
                      part_request_id=None, reversal_of=None) -> StockMovement
async def cikis_yap(db, *, so, satirlar, depo_id, clock, user) -> list[StockMovement]
async def iade_al(db, *, so, satirlar, depo_id, clock, user) -> list[StockMovement]
async def ters_kayit(db, *, hareket, gerekce, clock, user) -> list[StockMovement]
async def transfer_yap(db, *, kaynak_id, hedef_id, satirlar, clock, user) -> UUID
async def sayim_ac / sayim_satirlari_yaz / sayim_onayla / sayim_iptal
async def acilis_yukle(db, satirlar, clock, user)                 # içe aktarma profili çağırır
async def net_cikis(db, so_id, product_id) -> int                 # -Σqty (servis işine bağlı satırlar)
async def talep_ac / talepleri_karsila(db, so_id, product_id) / talepleri_kapat(db, so)
async def mutabakat(db, depo_idler) -> list[dict]
```

`hareket_yaz` kuralları (tüm servis deposu yazmalarının **tek** yolu):
1. `select(Product).where(Product.id == product_id).with_for_update()` — ürün satırı kilitlenir; aynı ürüne eşzamanlı yazmalar sıraya girer (canlıda tek satır kilidi emsali `api/imports.py:202`; E06 tahsisinde aynı yöntem). `pg_advisory_xact_lock` kullanılmadı: ürün satırı zaten var, kilit transaction'la birlikte düşer.
2. Ürün: silinmemiş, `yedek_parca=true`, `identity_kind='YOK'`; `is_active=false` ise yalnız `PASIFTE_SERBEST` türleri geçer.
3. Depo: `servis_deposu=true`; `is_active=false` ise yalnız `PASIFTE_SERBEST`.
4. `adet > 0` (API'de `Field(gt=0)`), işaret `TUR_KURALI`'ndan; eksi yönlü hareketten önce `bakiye(...) >= adet` değilse `ParcaHatasi("Stok yetersiz: <depo>'da <kod> için <x> adet var, <y> istendi.")`.
5. `CIKIS_SERVIS`: servis işi silinmemiş ve durumu `KAPALI_SERVIS_DURUMLARI` dışında olmalı (E11-02). `IADE_SERVIS`: `adet <= net_cikis(so, ürün)` (E11-03). İade kapalı işte de serbest (yanlış çıkışın stoğa geri alınması); yeni çıkış serbest değil.
6. `unit_cost`: girişte verilirse yazılır; çıkışta yazıcı aynı ürünün servis depolarındaki son giriş maliyetlerinden **hareketli ağırlıklı ortalama** hesaplayıp dondurur (yoksa NULL). (E11-22/K8)
7. `db.flush()`; commit yok. Denetim izi API'de.

Durum makinesi: yedek parça hareketinin durumu yoktur (defter kaydı). Sayım için `STOK_SAYIM = StateMachine(ad="Stok Sayımı", baslangiclar={"ACIK"}, gecisler={"ACIK": ("ONAYLANDI","IPTAL")})` ve talep için `PARCA_TALEBI = StateMachine(ad="Parça Talebi", baslangiclar={"ACIK"}, gecisler={"ACIK": ("KARSILANDI","IPTAL")})` `MAKINELER`'e eklenir (`services/statemachine.py:189-196`); meta-test otomatik sınar.

Kapsam (`services/teknik_servis/kapsam.py`, E01'de açılır): `erisilebilir_depolar(db, user)` →
- `parca.yonet` + `SCOPE_ALL`: tüm servis depoları;
- `KENDI_BIRIMI`: `birim IS NULL OR birim IN user.birimler`;
- `KENDI_ISLERI` (teknisyen): kendi birim depoları + kendi araç deposu (`user_id = user.id`); başka teknisyenin araç deposu hariç.
Servis işi erişimi E01'in `is_disinda_mi(user, so)` yardımcısıyla (birim + müşteri + atama) kontrol edilir; erişilemeyen iş → 404.

---

## 4. API

Yeni dosya `backend/app/api/yedek_parca.py`, `APIRouter(prefix="/api/teknik-servis/parca", tags=["yedek-parca"])`, `main.py`'de `app.include_router(yedek_parca_api.router)` (00 §6.2: "büyürse api/… olarak bölünür"). Takma adlar: `Okuyucu = require_permission("parca.gor")`, `Kullanici = require_permission("parca.kullan")`, `Yonetici = require_permission("parca.yonet")`. Kural ihlali 409, girdi biçimi 422 (FastAPI/Pydantic, canlıda `RequestValidationError` eşleyicisi yok), kapsam dışı 404, izin 403.

| Uç | İzin | Açıklama |
|---|---|---|
| `GET /stok?q&depo_id&durum=AZ\|YOK\|YETERLI&birim&limit&offset` | parca.gor | Parça başına toplam + depo kırılımı; `sayfala()`; yalnız erişilebilir depolar |
| `GET /stok/ozet` | parca.gor | KPI kutuları: az stok, stok yok, açık talep, açık sayım, bugünkü çıkış adedi |
| `GET /stok.xlsx` | parca.gor + rapor.disaaktar | Aynı filtre, `satirlari_xlsx_async` |
| `GET /hareketler?product_id&depo_id&tur&so_no&belge&bas&bit&limit&offset` | parca.gor | Tarih (created_at, id) sırası; `unit_cost`/`tutar` yalnız `sees_cost` |
| `GET /hareketler.xlsx` | parca.gor + rapor.disaaktar | Formül enjeksiyonu korumalı (`services/export.py:26`) |
| `POST /giris` | parca.yonet (`unit_cost` için ayrıca maliyet.gor) | Çok satırlı: `{depo_id, document_no≤50, notes≤500, satirlar:[{product_id, adet, unit_cost?}]}` |
| `POST /cikis` | parca.kullan | `{service_order_id, depo_id, satirlar:[{product_id, adet}], notes?}` — toplu çıkış tek transaction |
| `POST /iade` | parca.kullan | Aynı gövde; net çıkışla sınırlı |
| `POST /zayi` | parca.yonet | Gerekçe zorunlu |
| `POST /hareketler/{id}/ters-kayit` | parca.yonet | `{gerekce}`; transfer bacağıysa grubun iki bacağı birlikte tersine çevrilir |
| `POST /transfer` | parca.yonet | `{kaynak_depo_id, hedef_depo_id, satirlar}`; kaynak≠hedef, ikisi de aktif |
| `GET/POST /sayimlar`, `GET /sayimlar/{id}`, `PUT /sayimlar/{id}/satirlar`, `POST /sayimlar/{id}/onayla`, `POST /sayimlar/{id}/iptal` | parca.gor / parca.yonet | §E11-17 |
| `GET/POST /talepler`, `POST /talepler/{id}/iptal` | parca.gor / parca.kullan | §E11-19 |
| `GET /mutabakat` | parca.yonet + rapor.gor | §E11-07(b) |
| `GET /depolar` | parca.gor | Erişilebilir servis depoları |
| `POST /depolar`, `PATCH /depolar/{id}` | sistem.ayar | E06 K6 ile aynı; `version` iyimser kilit |
| `PATCH /kartlar/{product_id}` | parca.yonet | Yalnız `yedek_parca`, `birim`, `min_stok` + `version`; `is_active`, ad, kod `urun.yaz` ile katalogdan |

Servis işi tarafı (`api/teknik_servis.py`, E01): `GET /api/teknik-servis/isler/{id}/parcalar` (servis.gor + iş kapsamı) — hareketler, net adet, açık talepler; detay yanıtında `parcalar` bloğu. Rapor: `GET /api/raporlar/parca-tuketimi(.xlsx)` (`api/reports.py`'ye yeni uç; rapor.gor + parca.gor; xlsx için rapor.disaaktar).

Denetim izi: her yazma ucunda commit'ten önce `audit.log(db, "stock_movements", "parca.<cikis|iade|giris|transfer|ters_kayit|zayi|acilis>", entity_id=..., new_value={...})`; sayım `stock_counts` + `sayim.onayla`; talep `service_part_requests`. Servis işine bağlı hareketlerde ayrıca E01 olay tablosuna `service_order_events(tur="PARCA", ...)` satırı yazılır (birleşik iş geçmişi).

Canlı uca koruma (tek yazıcı garantisi): `api/stock.py:296` `POST /api/stok/hareket` gövdesindeki `warehouse_id` bir servis deposuysa 409 "Servis depolarına hareket Yedek Parça ekranından girilir." Mobilite depoları ve `warehouse_id=NULL` hareketleri bugünkü gibi çalışır; `tests/integration/test_stok_ozet.py` değişmeden yeşil kalır.

---

## 5. İzinler ve roller (`permissions.py`)

| Kod | Modül | Açıklama | Roller |
|---|---|---|---|
| `parca.gor` | Yedek Parça | Servis deposu stoğunu, hareket geçmişini, sayımları ve parça taleplerini görür | SERVIS_YONETICI, SERVIS_SEF, SERVIS_TEKNISYEN, ATOLYE, SERVIS_DEPO, YONETIM (otomatik `.gor`), ADMIN |
| `parca.kullan` | Yedek Parça | Erişebildiği açık servis işine parça çıkışı ve iadesi yapar, parça talebi açar | SERVIS_TEKNISYEN, ATOLYE, SERVIS_SEF, SERVIS_YONETICI, SERVIS_DEPO, ADMIN |
| `parca.yonet` | Yedek Parça | Servis deposuna giriş, transfer, zayi, ters kayıt, sayım ve onayı, açılış stoğu, parça kartı stok alanları; düşük stok uyarısını alır | SERVIS_DEPO, SERVIS_YONETICI, ADMIN |

Yeni rol `SERVIS_DEPO` ("Servis Depo Sorumlusu", `KENDI_BIRIMI`): `parca.gor, parca.kullan, parca.yonet, servis.gor, urun.gor, hesap.gor, gorev.gor, gorev.yaz, rapor.gor, rapor.disaaktar`. `maliyet.gor` kümesi değişmez (unit test). Mevcut `DEPO` ve `TEKNIK_SERVIS` rolleri değişmez; mevcut depo personeline `SERVIS_DEPO` rolü ya da `UserPermission` istisnası verilir. Özelleştirilmiş DB rollerine izin inmez; kurulum notunda elle ekleme listesi verilir. İçe aktarma: `PROFIL_IZINLERI["parca_acilis"] = "parca.yonet"`.

---

## 6. Ön yüz

- `frontend/src/api/yedekParca.ts` (tipler + fonksiyonlar).
- `pages/YedekParcaPage.tsx` — rota `/yedek-parca`, menü `{key:"/yedek-parca", label:"Yedek Parça", icon:<ToolOutlined/>, izin:"parca.gor"}` (teknik servis grubunda; mobilite "Stok" kalemi aynen kalır). Sekmeler:
  - **Stok:** üstte **tıklanabilir KPI kutuları** (Az stok, Stok yok, Açık talep, Açık sayım) — tıklama filtreyi/sekmeyi ayarlar, sayfa 1'e döner. `Input.Search` + depo `Select` + birim; `useQuery(["parca-stok", filtre, sayfa])` + `api.getSayfa` + `Table` sunucu sayfalaması; satır → `Drawer size={680}`: depo kırılımı, son 20 hareket, açık talepler, `EkYukleyici` yok (parça kartı ekleri katalogda). "Excel" düğmesi `yetkili("rapor.disaaktar")`.
  - **Hareketler:** filtreler (parça, depo, tür, servis işi no, belge no, tarih aralığı), Excel; maliyet kolonu yalnız yanıtta varsa.
  - **Talepler**, **Sayımlar** (yalnız `parca.yonet` yazabilir), **Mutabakat** (`parca.yonet`).
  - Düğmeler: "Giriş", "Transfer", "Zayi" (`parca.yonet`), "Açılış stoğu yükle" (İçe Aktarma ekranına yönlendirir, profil `parca_acilis`).
- `components/ParcaHareketPenceresi.tsx` (`KartPenceresi` kalıbı, tek form): `Form.List` ile çok satır; parça `Select showSearch` (`/api/urunler?yedek_parca=1&q=`), depo `Select` (erişilebilir depolar; teknisyende varsayılan kendi araç deposu), servis işi `Select showSearch` (`/api/teknik-servis/isler?q=<so_no|müşteri>&acik=1`). **Hiçbir alanda sayısal kimlik yazılmaz.** `layout="vertical"`, 375 px'te tek sütun, `InputNumber min=1 precision=0`.
- `components/ServisParcalari.tsx`: servis işi detayı (E01 `ServisIsleriPage` Drawer "Parçalar" sekmesi), PB formu (E04) ve atölye detayı (E05) aynı bileşeni kullanır: liste + "Parça ekle" (`yetkili("parca.kullan")` ve iş açık) + "İade" + "Parça talep et". Tutar kolonu yalnız `maliyet` anahtarı geldiğinde.
- Tarih `dayjs("tr")` `DD.MM.YYYY HH:mm`, para `tl()`, metinler Türkçe; mutation sonrası `invalidateQueries(["parca-stok"], ["parca-hareketler"], ["servis-isi", id])`.

---

## 7. Uyarı, worker, ayar

- `services/uyarilar.py` `topla()` içine iki blok (izne ve depo kapsamına tabi; sayı = sızıntı ilkesi, `uyarilar.py:14-16`):
  - `if user.has("parca.yonet")`: "Minimum stok altındaki parça" (`kod="parca.az_stok"`, `yol="/yedek-parca?durum=AZ"`, `onem="uyari"`) — sayı `stok_durumu()` ile, yani ekrandaki AZ filtresiyle aynı fonksiyon.
  - `if user.has("parca.kullan")`: "Talep ettiğiniz parça stokta" (`kod="parca.geldi"`, yalnız talep sahibinin `ACIK` talepleri, erişilebilir depolarda bakiye ≥ adet).
  - `if user.has("parca.yonet")`: "Mutabakat farkı" (yalnız fark > 0 ise; normalde görünmez).
- Uyarılar canlıda saklanmaz, hesaplanır; "görüldü" anahtarı tutulmaz (bkz. Karar K6).
- Worker: zorunlu iş yok. İsteğe bağlı `Gorev("parca-mutabakat", timedelta(hours=24), parca_mutabakat)` yalnız özet metni döner (`worker.py:120-125` imzası); idempotent, yazma yapmaz.
- `services/settings.py` `DEFAULTS`: `parca_toplu_satir_ust_sinir: 50`, `parca_sayim_degisim_toleransi: 0` (onay anında görüntüden sapma kabulü; 0 = her sapmada yeniden onay).

---

## 8. Madde bazında entegrasyon (E11-NN)

### E11-01 · M11-D01 · Tek stok yazıcısı ve hareket türü altyapısı · **KISMEN** · P1 · M
- **Canlı:** `stock_movements` işaretli adetli defter, `services/stock.py:300-340` tek yazıcı ama kilitsiz ve bakiye kontrolsüz; `reason` 4 değer (`models/stock.py:218-220`).
- **Yaklaşım:** §2.1 kolonları + `ck_stok_hareket_tur`, `ck_stok_hareket_tur_yon`; §3 `hareket_yaz` (ürün satırı `FOR UPDATE`, negatif bakiye engeli). Canlı `POST /api/stok/hareket` servis depolarına 409 (§4). `Quantity>0 + Direction` önerisi yerine canlı işaretli adet korunur; yön `TUR_KURALI`'ndan gelir ve şemada CHECK ile kilitlidir. Raporlar ve mutabakat `Σqty` kullanır.
- **Kabul:** (1) Servis deposuna yazan tek kod yolu `parca.hareket_yaz`'dır (grep testi: `StockMovement(` yalnız `services/stock.py` ve `services/teknik_servis/parca.py`'de). (2) Bakiye 1 iken iki eşzamanlı 1'lik çıkıştan biri 201, diğeri 409 (`asyncio.gather`). (3) Her `hareket_turu` için `reason` ve işaret CHECK'le zorlanır; aykırı INSERT `ck_` ile 409. (4) Migration sonrası mobilite `GET /api/stok/ozet` ve ürün `stok_adedi` değerleri öncesiyle aynı. (5) `POST /api/stok/hareket` servis deposu kimliğiyle 409, mobilite deposuyla 201.
- **Canlı risk:** Düşük. Yalnız nullable kolon ve yeni adlı kısıt; mevcut satırlar `hareket_turu IS NULL`. `api/stock.py`'ye tek koşul eklenir.

### E11-02 · M11-14 · Kapalı/iptal servis işine parça çıkışı engeli · **YOK** · P1 · S
- **Canlı:** Servis işi yok; mobilite iş emrine stok bağı da yok.
- **Yaklaşım:** `hareket_yaz` içinde `CIKIS_SERVIS` için `so.status in KAPALI_SERVIS_DURUMLARI` → `ParcaHatasi("Kapalı iş emrine parça yazılamaz.")`. `BEKLEMEDE`, `TEKRAR_ACILDI` açık sayılır. Kapalı işe sonradan yazma istisnası yok (K3).
- **Kabul:** TAMAMLANDI / KAPATILDI / IPTAL işe çıkış **409** ve mesaj "Kapalı iş emrine parça yazılamaz."; BEKLEMEDE işe çıkış 201; TEKRAR_ACILDI sonrası 201; 409'da bakiye ve hareket sayısı değişmemiş.
- **Canlı risk:** Yok (yeni kod).

### E11-03 · M11-15 (dotnet_specific) · İade yalnız İade türüyle ve net çıkışla sınırlı · **YOK** · P1 · S
- **Canlı:** Yok. .NET'e özgü "iş emirli Giriş = örtük iade" hatası yeni sistemde oluşmaz, çünkü giriş ucu `service_order_id` kabul etmez.
- **Yaklaşım:** Özü kabul kriterine taşındı: `POST /giris` şemasında `service_order_id` yok (`extra="forbid"` → 422); `IADE_SERVIS` için `adet <= net_cikis(so, ürün)`.
- **Kabul:** 3 çıkış sonrası 4'lük iade 409, 3'lük iade 201; giriş gövdesinde `service_order_id` 422; hiçbir servis işinin `net_cikis` değeri negatif olamaz (property testi: rastgele çıkış/iade/ters dizileri).
- **Canlı risk:** Yok.

### E11-04 · M11-01 · Servis işinde "Kullanılan Parçalar" ve teknisyen parça kullanımı · **YOK** · P1 · L
- **Canlı:** Yok. Stok yazma bugün yalnız `cihaz.yaz` (`api/stock.py:31`).
- **Yaklaşım:** `POST /cikis` (`parca.kullan`) + `GET /api/teknik-servis/isler/{id}/parcalar` (servis.gor + iş kapsamı). Teknisyen yalnız erişebildiği (E01 `KENDI_ISLERI`: aktif ataması olan) açık işe ve erişebildiği depodan çıkış yapar. Toplu çıkış: tek istekte çok satır, tek transaction; bir satır hatalıysa hiçbiri yazılmaz. Servis işi olayına `PARCA` satırı yazılır. Bileşen `ServisParcalari.tsx`.
- **Kabul:** (1) `parca.kullan` sahibi atandığı açık işe çıkış → 201, bakiye düşer, iş detayında satır görünür. (2) Kapalı işe 409. (3) Stok yetersiz 409 ve hiçbir satır yazılmamış. (4) `parca.kullan` yok → 403. (5) Atanmadığı / başka birimin işi → 404 ve bakiye değişmemiş (`db.refresh`). (6) Başka teknisyenin araç deposundan çıkış → 404. (7) `maliyet.gor` olmayan kullanıcının çıkış ve iş-parça yanıtlarında `unit_cost`/`tutar` anahtarı yok.
- **Canlı risk:** Yok (yeni uçlar).

### E11-05 · M11-12 · Stok izinleri ve rol şablonları · **YOK** · P1 · S
- **Canlı:** `permissions.py:14-77` katalogda parça izni yok.
- **Yaklaşım:** §5: `parca.gor`, `parca.kullan`, `parca.yonet` + `SERVIS_DEPO` rolü; E01 servis rollerine dağıtım. Mevcut roller değişmez; mevcut kullanıcı izinleri otomatik değişmez.
- **Kabul:** (1) Üç izin Türkçe açıklamayla katalogda ve kullanıcı yönetimi ekranında. (2) `test_permissions.py` "her izin en az bir role" ve "maliyet görenler sabit" yeşil. (3) Seed sonrası `ozellestirildi=True` rollerin izinleri değişmemiş, log uyarısı var. (4) `SERVIS_TEKNISYEN` düşük stok uyarısı görmez (E11-08).
- **Canlı risk:** Yok.

### E11-06 · M11-02 · İade ve ters kayıt · **YOK** · P1 · M
- **Canlı:** Yok; canlıda düzeltme yalnız ters işaretli serbest hareketle yapılabiliyor ve bağ kurulmuyor.
- **Yaklaşım:** `POST /iade` (E11-03 sınırı) ve `POST /hareketler/{id}/ters-kayit` (`parca.yonet`, gerekçe zorunlu): orijinalin `reason`'ı, ters işareti, `service_order_id`'si, `unit_cost`'u kopyalanır; `uq_stok_hareket_ters` tek seferliği şemada kilitler; ters kaydın ters kaydı 409; transfer bacağında grubun iki bacağı birlikte; ters kayıt bakiyeyi negatife düşürecekse 409. Kapalı işteki çıkışın ters kaydı serbest (düzeltme, stoğa geri alma).
- **Kabul:** (1) Ters kayıt sonrası bakiye ve iş net çıkışı eski hâline döner. (2) İkinci ters kayıt 409 (`uq_`). (3) Gerekçesiz 422/409 (`ck_stok_hareket_ters_gerekce`). (4) Tüketilmiş girişin ters kaydı 409 "Stok yetersiz". (5) Tüketim raporundaki tutar, ters kayıt sonrası orijinal öncesi değere döner (yanlış yöne değişmez).
- **Canlı risk:** Yok.

### E11-07 · M11-17 · Açılış stoğu yükleme (P1) ve defter mutabakatı (P2) · **KISMEN** · P1 · M
- **Canlı:** İçe aktarma çerçevesi var (önizleme, şablon, karantina; `services/imports/__init__.py:30-60`, `api/imports.py:82-273`); bakiye = hareket toplamı olduğu için ayrı "bakiye tablosu" yok.
- **Yaklaşım:** (a) Yeni profil `services/imports/parca_acilis.py` (`ParcaAcilisProfili`, sütunlar: parça kodu, depo kodu, adet, birim maliyet?, not), `PROFILLER`/`PROFIL_IZINLERI`'ne eklenir. Profil bayrağı `hepsi_ya_hic=True`: `api/imports.py` uygulama ucunda bayrak varsa ve hatalı satır > 0 ise 409 "Hatalı satırlar düzeltilmeden açılış yüklenmez: satır 4, 9". Satırlar `hareket_yaz(tur="ACILIS")` ile yazılır. Aynı (parça, depo) için ikinci `ACILIS` → satır hatası (önizlemede `cakisma`). (b) `GET /mutabakat`: (parça, depo) başına `Σqty` < 0 olanlar, toplamı ≠ 0 olan `transfer_grup`'lar, sayım satırı ile sayım hareketi farkı, `service_order_id`'si olup net çıkışı < 0 olan işler. Gerçek bakiye `Σqty`'nin kendisi olduğundan "bakiye–hareket farkı" yapısal olarak 0'dır; rapor bütünlük ihlallerini listeler.
- **Kabul:** (1) 1 hatalı satırlı dosyada hiçbir hareket yazılmaz, hatalı satır numaraları döner. (2) Aynı (parça, depo) ikinci açılış reddedilir. (3) Normal kullanım sonrası mutabakat boş liste; elle bozulmuş test verisinde ilgili satır görünür. (4) Açılış `parca.yonet` olmadan 403.
- **Canlı risk:** Düşük; `api/imports.py`'ye bayrak koşulu eklenir, diğer profillerin `hepsi_ya_hic` değeri False.

### E11-08 · M11-D03 · Düşük stok uyarısının hedef kitlesi · **YOK** · P2 · S
- **Canlı:** Stok uyarısı yok; uyarılar hesaplanır ve izne tabidir (`uyarilar.py:9-17`).
- **Yaklaşım:** §7 `parca.az_stok` bloğu yalnız `parca.yonet` sahiplerine; sayı kullanıcının erişebildiği depolardan. "Görüldü" yerine hesaplanan uyarı: parça eşik üstüne çıkınca kendiliğinden kaybolur, yeniden düşünce yeniden görünür.
- **Kabul:** (1) Yalnız `parca.gor`+`parca.kullan` olan teknisyen uyarıyı görmez. (2) Depo sorumlusu görür; giriş sonrası eşik üstüne çıkan parça listeden düşer; yeniden altına inince tekrar sayılır. (3) Başka birimin deposundaki az stok sayıya girmez.
- **Canlı risk:** Yok (yeni blok).

### E11-09 · M11-09 · Form tabanlı, aranabilir stok ekranı · **KISMEN** · P2 · M
- **Canlı:** `StokPage.tsx:715-775` ürünü aranabilir `Select` ile seçtiriyor (ID yazdırmıyor) ama depo ve iş seçimi yok, çıkış için eksi adet yazdırıyor.
- **Yaklaşım:** §6 `ParcaHareketPenceresi`: parça, depo, servis işi (so_no/müşteri ile arama) seçicileri; adet her zaman pozitif, yön türden; 375 px tek sütun.
- **Kabul:** Hiçbir stok formunda sayısal kimlik veya eksi adet girilmez; servis işi `SRV-` numarası ya da müşteri adıyla bulunur; 375 px'te yatay kaydırma yok (form; tablolar `scroll.x` ile kendi içinde kayar).
- **Canlı risk:** Yok; mobilite `StokPage.tsx` değişmez.

### E11-10 · M11-10 · Az stok hesabının tek fonksiyonla (toplam bazlı) yapılması · **YOK** · P2 · S
- **Canlı:** Minimum stok kavramı yok.
- **Yaklaşım:** `products.min_stok`; `stok_durumu(toplam, min)` tek fonksiyon: toplam ≤ 0 → "YOK", min>0 ve toplam < min → "AZ", aksi "YETERLI". Toplam = kullanıcının erişebildiği servis depolarının toplamı (ekran ve uyarı aynı depo kümesiyle). Depo bazlı minimum P3.
- **Kabul:** Depo1=5, Depo2=0, min=3 → ekran ve uyarı "Yeterli"; min=0/NULL → uyarı yok; hiç hareketi olmayan parça "Stok yok"; `GET /stok?durum=AZ` toplamı (`X-Toplam-Kayit`) = uyarıdaki adet.
- **Canlı risk:** Yok.

### E11-11 · M11-16 · Tam sayı birimlerde ondalık reddi · **KISMEN** · P2 · S
- **Canlı:** `stock_movements.qty` Integer (`models/stock.py:233`); ondalık hiçbir birimde yazılamaz.
- **Yaklaşım:** Bütün servis uçlarında `adet: int = Field(gt=0)`; `products.birim` gösterim amaçlıdır. Kesirli birim (metre kablo) bu aşamada **tam metre** ile tutulur (K7). Kesirli ihtiyaç doğrulanırsa P3: `qty` Integer→Numeric(14,3) genişletme migration'ı + `products.kesirli` bayrağı (mobilite toplamlarının tipi değiştiği için ayrı madde, altın kayıt ve `test_stok_ozet` ile birlikte).
- **Kabul:** `adet=1.5` → 422; `METRE` birimli parçada `adet=3` 201; birim ekranda "3 metre" gösterilir.
- **Canlı risk:** Yok (kolon tipi değişmiyor).

### E11-12 · M11-08 · Parça kartı düzenleme, pasifleştirme, birim, kod tekrarında 409 · **KISMEN** · P2 · M
- **Canlı:** `PATCH /api/urunler/{id}` (ad, `is_active` vb.), POST'ta kod tekrarı 409 (`api/catalog.py:141-142`), PATCH'te `uq_products_code` global eşleyiciyle 409 (`main.py:131-148`); birim/minimum yok; pasif ürüne stok hareketi engeli yok.
- **Yaklaşım:** `products.yedek_parca/birim/min_stok` (§2.1); `schemas/catalog.py` `UrunIn/UrunOut`'a eklenir (ek alan, geriye uyumlu); `PATCH /api/teknik-servis/parca/kartlar/{id}` (`parca.yonet`) yalnız bu 3 alan; `api/catalog.py` PATCH'ine kod tekrarı için açık kontrol: 409 "Bu parça kodu zaten kayıtlı." (bugünkü genel mesaj yerine; yalnız mesaj değişir). Pasif parça/depoya giriş/çıkış/transfer 409, iade ve ters kayıt serbest (`PASIFTE_SERBEST`). Kategori/uyumlu model/üretici no P3 (`family`, `brand`, `supplier_code` canlıda zaten var — yeni alan gerekmez).
- **Kabul:** (1) Birim, minimum, yedek parça bayrağı güncellenir, `version` uyuşmazsa 409. (2) Kod tekrarı POST ve PATCH'te 409 "Bu parça kodu zaten kayıtlı.". (3) Pasif parçaya çıkış 409, iadesi 201. (4) `parca.yonet` sahibi `is_active`'i bu uçtan değiştiremez (422, `extra="forbid"`).
- **Canlı risk:** Düşük; katalog şemasına opsiyonel alan, PATCH'te mesaj iyileştirmesi.

### E11-13 · M11-11 · Giriş hareketinde belge no ve not · **KISMEN** · P2 · S
- **Canlı:** `document_no` String(60), `notes` String(300) var (`models/stock.py:235-236`); belge no ile arama yok.
- **Yaklaşım:** Kolonlar yeniden kullanılır; servis uçlarında `document_no: Field(max_length=50)`, `notes: Field(max_length=300)` (canlı kolon sınırı; 500'e genişletme gerekmez, K9). `GET /hareketler?belge=` `ix_stok_hareket_belge` (trigram) ile `ILIKE`. Giriş maliyeti: `unit_cost` (E11-22, maliyet.gor ister).
- **Kabul:** Belge no ve not kaydedilir; hareket geçmişinde belge no parçasıyla bulunur; 51 karakter belge no 422.
- **Canlı risk:** Yok.

### E11-14 · M11-13 · PB formu ve atölye kaydında yapılandırılmış parça listesi · **YOK** · P2 · M
- **Canlı:** Yok. E04-21 "parça bildirimi + depoda `POST /api/stok/hareket`" geçici yolunu öneriyordu.
- **Yaklaşım:** PB formu (E04) ve atölye detayı (E05-17) `ServisParcalari` bileşenini kullanır; "Parça ekle" doğrudan `POST /cikis` (PB işinin `service_order_id`'siyle). E04-21 bildirimi katalog dışı/stokta olmayan parça için kalır ve "Parça talep et" (E11-19) olarak açılır. Eski serbest metin alanı "Not" olarak salt okunur korunur. İş kapandıktan sonra ekleme 409 (E11-02).
- **Kabul:** PB formunda eklenen parça bakiyeden düşer ve listede görünür; kapalı PB işinde "Parça ekle" düğmesi görünmez ve uç 409; serbest metin değişmeden okunur.
- **Canlı risk:** Yok.

### E11-15 · M11-03 · Hareket geçmişi ekranı ve API (filtreli, sayfalı, Excel) · **KISMEN** · P2 · M
- **Canlı:** `GET /api/stok/hareketler` (yalnız `product_id`, sayfasız, maliyetsiz; `api/stock.py:316-343`).
- **Yaklaşım:** Yeni `GET /api/teknik-servis/parca/hareketler` (+ `.xlsx`): filtreler §4; `sayfala()`; yalnız erişilebilir depolar **ve** servis işine bağlı satırlarda iş kapsamı (`kapsam_birim` + `kapsam_musteri` alt sorgusu) — göremediği birimin işine ait hareket listelenmez. Excel `satirlari_xlsx_async` (CSV yerine canlı standardı xlsx, formül enjeksiyonu korumalı). Canlı uç değişmez.
- **Kabul:** Filtre sonucu `created_at, id` sırasıyla; `X-Toplam-Kayit` doğru; başka birimin işine bağlı hareket listede ve Excel'de yok; `maliyet.gor` yoksa `unit_cost`/`tutar` anahtarı yok; `=HYPERLINK(...)` notu Excel'de metin.
- **Canlı risk:** Yok.

### E11-16 · M11-04 · Depolar arası transfer · **KISMEN** · P2 · S
- **Canlı:** `reason='TRANSFER'` var ama tek satırlık serbest hareket; iki bacak ve bağ yok. Seri takipli transfer (`transfers`) cihazlar içindir, dokunulmaz.
- **Yaklaşım:** `POST /transfer`: her satır için `TRANSFER_CIKIS` (kaynak, −) + `TRANSFER_GIRIS` (hedef, +), aynı `transfer_grup` (uuid4), tek transaction; kaynak=hedef, pasif depo, yetersiz stok → 409, hiçbir satır yazılmaz.
- **Kabul:** Transfer aynı `transfer_grup`'lu iki hareket üretir ve grup toplamı 0; yetersiz stok / kaynak=hedef / pasif depo 409 ve hiçbir bakiye değişmemiş; mobilite `GET /api/stok/ozet` toplamı değişmez.
- **Canlı risk:** Yok.

### E11-17 · M11-05 · Stok sayımı (anlık görüntülü, onaylı) · **KISMEN** · P2 · M
- **Canlı:** `reason='SAYIM'` ile elle fark girilebiliyor; görüntü, onay, açık sayım kilidi yok.
- **Yaklaşım:** `stock_counts` + `stock_count_lines` (§2.2), makine `STOK_SAYIM`. Açılışta depodaki tüm parçalar `sistem_adet` görüntüsüyle satır olur; `PUT /satirlar` sayılan adetleri yazar; `POST /onayla {gerekce, degisimi_kabul?}`: her satır için güncel bakiye okunur (`onay_anindaki_adet`); görüntüden sapma varsa ve `degisimi_kabul` yoksa 409 ve sapan satırlar listesi döner; kabul edilirse fark **güncel bakiyeye göre** hesaplanır ve `SAYIM_FAZLASI/EKSIGI` hareketleri `stock_count_id` ile yazılır. Onaysız sayım bakiyeyi değiştirmez. Onaylayan `parca.yonet` (K4).
- **Kabul:** Sistem 10 / sayılan 8 onayında bakiye 8, `SAYIM_EKSIGI -2` hareketi gerekçe + onaylayanla; onaysız sayımda bakiye aynı; aynı depoda ikinci açık sayım 409 (`uq_stok_sayim_acik`); sayım sırasında 1 çıkış olduysa onay 409 + sapma listesi, `degisimi_kabul=true` ile fark yeniden hesaplanır (bakiye yine 8).
- **Canlı risk:** Yok.

### E11-18 · M11-07 · Parça tüketim raporu ve iş/ekipman bazlı parça geçmişi · **YOK** · P2 · M
- **Canlı:** Yok (`services/reports.py`'de stok tüketim raporu yok).
- **Yaklaşım:** `services/teknik_servis/raporlar.py::parca_tuketimi(db, donem_bas, donem_bit, birim, kirilim)` — net çıkış = `−Σqty` (`hareket_turu IN ('CIKIS_SERVIS','IADE_SERVIS')` + bunların ters kayıtları); kırılım parça × ay, birim, müşteri, iş türü (PB ile diğer servis ayrı). `GET /api/raporlar/parca-tuketimi(.xlsx)`. Ekipman geçmişi (E03 kütük ekranı) parçayı yalnız servis işinin tek `equipment_id`'si varsa o ekipmana atfeder; çok ekipmanlı işlerde "iş bazında" gösterir. Tutar yalnız `sees_cost`.
- **Kabul:** Rapor net çıkışı, aynı filtreli hareket defteri toplamıyla birebir eşit (test); PB ve servis ayrı satırlar; `maliyet.gor` yoksa tutar kolonu yanıtta ve Excel'de yok; çok ekipmanlı işte parça hiçbir ekipmana otomatik bağlanmaz.
- **Canlı risk:** Yok; mevcut rapor sorgularına dokunulmaz.

### E11-19 · M11-06 · Parça talebi ve malzeme beklemesi (daraltılmış) · **YOK** · P2 · M
- **Canlı:** Yok.
- **Yaklaşım:** `service_part_requests` (§2.2), makine `PARCA_TALEBI`. `POST /talepler {service_order_id, product_id, adet, notes, isi_beklet?}` (`parca.kullan`, iş kapsamı); `isi_beklet=true` ise E01 bekleme ucu `PARCA` nedeniyle çağrılır (`uq_hold_aktif` korunur). Çıkış (`cikis_yap`) aynı iş+parçada net çıkış ≥ talep adedine ulaşınca talep `KARSILANDI` (+ `part_request_id` bağı), bağlı bekleme kapatılır. Servis işi KAPATILDI/IPTAL olduğunda E01 `durum_degistir` kancası `talepleri_kapat` ile `IPTAL`. "Parça geldi" uyarısı §7. Depo ekranında açık talep listesi (KPI kutusu).
- **Kabul:** Talep depo listesinde görünür; depo girişinden sonra talep sahibinde "Talep ettiğiniz parça stokta" satırı; aynı işe yeterli çıkışta talep KARSILANDI ve bekleme kapanır; iş iptalinde talep IPTAL; aynı iş+parça için ikinci açık talep 409.
- **Canlı risk:** Yok.

### E11-20 · M11-D02 · Test verisi ve kabul senaryoları · **KISMEN** · P2 · S
- **Canlı:** Test altyapısı var (gerçek PG17, `_test` DB, `client`, `kullanici_ac`, `urun_ac`; `tests/conftest.py`). Seed yalnız test DB'de koşar.
- **Yaklaşım:** `tests/conftest.py`'ye `servis_deposu_ac`, `parca_ac` (urun_ac sarmalayıcı, `yedek_parca=True, identity_kind="YOK"`), `servis_isi_ac` fixture'ları. Dosyalar: `tests/integration/test_yedek_parca.py` (E11-02/03/04/06/12/16/17), `test_yedek_parca_kapsam.py` (404 + veri değişmemiş, liste/Excel/uyarı sayısı), `test_yedek_parca_eszamanli.py` (`asyncio.gather` ile iki çıkış), `test_yedek_parca_maliyet.py`, `test_yedek_parca_acilis.py`; `tests/unit/test_parca_tur_kurali.py` (TUR_KURALI ↔ CHECK uyumu). Yeni tablolar `products/users`'a FK ile bağlı olduğundan `_TRUNCATE`'e eklenmeleri gerekmez (CASCADE); kodlamada doğrulanır.
- **Kabul:** Senaryolar E11 kabul kriterlerine bire bir eşli; bakiye 1 iken iki paralel 1'lik çıkıştan biri 409; `test_stok_ozet.py` ve `test_altin_kayit.py` (932 iş / 552.825,00 TL) değişmeden yeşil.
- **Canlı risk:** Yok.

### E11-21 · M11-18 · Eski serbest metin parça kayıtlarının korunması · **YOK** · P3 · S
- **Canlı:** Eski veri yok.
- **Yaklaşım:** E01/E04/E05 göçlerinde eski `SpareParts`/`RepairInfo` metinleri servis işinin/atölye kaydının not alanına olduğu gibi taşınır; göç **hiçbir** `stock_movements` satırı üretmez.
- **Kabul:** Göç öncesi/sonrası `SELECT count(*) FROM stock_movements` aynı; örnek 10 işte metin karakter karakter aynı.
- **Canlı risk:** Yok.

### E11-22 · M11-19 · Defter değiştirilemezliği, depo adı yetkisi, maliyet yazma yetkisi · **KISMEN** · P3 · S
- **Canlı:** Hareket güncelleme/silme ucu yok (`api/stock.py`); depo yazma ucu yok (`:361`); maliyet görünürlüğü `maliyet.gor` (`api/deps.py:103-105`).
- **Yaklaşım:** (1) `trg_stok_hareket_degismez` (§2.1; yalnız `hareket_turu IS NOT NULL` satırlar). (2) Depo oluşturma/ad değişikliği `sistem.ayar` (E06 K6 ile aynı uç, `servis_deposu` alanı eklenir). (3) `unit_cost` yazmak `parca.yonet` + `maliyet.gor`; yalnız `parca.yonet` olan kullanıcının gövdesindeki `unit_cost` 403. Çıkış maliyeti hareketli ağırlıklı ortalamayla dondurulur (K8).
- **Kabul:** Servis defteri satırına `UPDATE qty` / `DELETE` DB hatası; mobilite satırında davranış aynı; depo adı `sistem.ayar` olmadan 403; `maliyet.gor`'süz `unit_cost` girişi 403; görmeyen kullanıcı yanıtında maliyet anahtarı yok.
- **Canlı risk:** Düşük; tetikleyici koşullu, canlı satırları etkilemez.

### E11-23 · Soru 1/2/3/10 · Servis depoları, birim ve teknisyen araç deposu · **KISMEN** · P1 · S
- **Canlı:** `warehouses` var (`location_type='TEKNISYEN'`, `user_id`; `models/stock.py:64-77`); E06 `birim` ve `kiralama_deposu` ekliyor.
- **Yaklaşım:** `servis_deposu` kolonu; seed ile `SRV-MERKEZ` (birim NULL = ortak havuz) yer tutucu, gerçek depolar `POST /depolar` (`sistem.ayar`) ile açılır. Teknisyen araç deposu isteğe bağlıdır; varsa teknisyenin çıkış formunda varsayılan. Birim kapsamı §3 `erisilebilir_depolar`.
- **Kabul:** KENDI_BIRIMI kullanıcısı yalnız ortak ve kendi birim depolarını görür; başka birim deposu kimliğiyle çıkış 404; teknisyen yalnız kendi araç deposunu görür; kiralama deposu `servis_deposu=true` yapılamaz (`ck_warehouse_tur_tekil`).
- **Canlı risk:** Yok; mobilite depoları `servis_deposu=false` kalır, `GET /api/stok/depolar` değişmez.

---

## 9. Uygulama sırası

Önkoşul: 00 §6.4 adım 1 (RBAC + birim) ve 2 (E01 servis işi çekirdeği), E06 `warehouses.birim` migration'ı.

1. **P1 altyapı:** E11-05 (izin/rol) → E11-23 (depolar) → E11-01 (defter kolonları + `hareket_yaz` + canlı uca koruma) → E11-02, E11-03.
2. **P1 özellik:** E11-04 (çıkış + iş detayı), E11-06 (iade/ters), E11-07(a) (açılış).
3. **P2:** E11-12, E11-10, E11-08, E11-09, E11-11, E11-13, E11-15, E11-16, E11-17, E11-14, E11-18, E11-19, E11-07(b), E11-20.
4. **P3:** E11-21, E11-22, ertelenenler (depo bazlı minimum, kesirli birim, kategori alanları).

Her adım sonunda: `make test` (altın kayıt dahil), `test_migration_zinciri`, `ruff`, `npm run build` + `oxlint`.

---

## 10. Kararlar (kullanıcıya soru sorulmadı)

- **K1 Defter = canlı `stock_movements`.** Ayrı tablo açılmaz; nullable kolonlarla genişletilir. Gerekçe: 00 §5 kararı, E01/E03/E04/E05 referansları ve "Denge'nin elindeki adet tek toplamdır" ilkesi (`models/stock.py:200-204`).
- **K2 Yön = işaretli adet.** `Quantity>0 + Direction` yerine canlı işaretli `qty` korunur; ayrıntılı tür `hareket_turu` kolonunda, tür→(neden, işaret) eşlemesi CHECK ile kilitli. Canlı `ck_stok_hareket_neden` değiştirilmez (mimari kural 11).
- **K3 Kapalı işe parça yazma tamamen yasak (Soru 8).** Kapalı = TAMAMLANDI, KAPATILDI, IPTAL. Gerekirse iş `TEKRAR_ACILDI` yapılır (E01 `servis.kapat`), bu zaten gerekçeli ve olay geçmişine yazılır; ikinci bir istisna yolu açılmaz. İade ve ters kayıt kapalı işte serbesttir.
- **K4 Sayım onayı `parca.yonet` (Soru 7).** Ayrı onay izni açılmaz; onay gerekçe zorunlu, onaylayan ve zaman şemada zorunlu, denetime yazılır. Görev ayrılığı ihtiyacı doğarsa `parca.sayim_onayla` eklenebilir.
- **K5 Parça talebi alınır, daraltılmış (Soru 9).** Ayrı bildirim altyapısı yok; "parça geldi" hesaplanan uyarı. Gerekçe: denetimin daraltılmış önerisi ve E01 `service_holds` PARCA nedeninin zaten var olması.
- **K6 "Görüldü" durumu tutulmaz.** Canlı uyarı merkezi saklamaz, hesaplar (`uyarilar.py:9-12`); eşik üstüne çıkınca uyarı kendiliğinden kaybolur, yeniden düşünce yeniden görünür. Bu, "eşik altına düşüş olayına bağlı" kabulünün canlı mimarideki karşılığıdır.
- **K7 Adet tam sayıdır (M11-16).** `qty` Integer kalır; metre/litre birimli parçalar tam birimle tutulur. Kolon tipini Numeric'e çevirmek mobilite stok özeti ve katalog `stok_adedi: int` alanının tipini değiştirdiği için P3'e ayrı madde olarak bırakıldı.
- **K8 Maliyet yöntemi (Soru 5): hareketli ağırlıklı ortalama, hareket anında dondurulur.** Giriş maliyeti isteğe bağlı (`maliyet.gor` + `parca.yonet`); maliyetsiz girişler ortalamaya katılmaz; hiç maliyet yoksa NULL ("bilinmiyor"), 0 yazılmaz. Gerekçe: canlı landed cost ilkesi "maliyet hesaplanır ve dondurulur" (`models/purchase.py:1-7`).
- **K9 Not uzunluğu 300.** Canlı `notes` String(300); eski öneri 500 idi. Canlı kolonu genişletmek gereksiz risk; servis işi notları E01'de ayrı alanda.
- **K10 Servis depoları ayrı satırlar (Soru 2).** `warehouses.servis_deposu=true`; kiralama depolarıyla (E06 K16) ve mobilite depolarıyla aynı tablo, ayrı satırlar. Bir depo hem kiralama hem servis olamaz.
- **K11 Parça havuzu birim bazlı, ortak depo serbest (Soru 3).** `warehouses.birim` NULL = tüm birimlerin ortak havuzu; dolu = yalnız o birim. Parça kataloğu tüm birimlere ortaktır (ürün tek kayıt).
- **K12 Teknisyen araç stoğu desteklenir ama zorunlu değil (Soru 1).** Canlı `location_type='TEKNISYEN'` + `user_id` kullanılır; varsa çıkış formunda varsayılan depo.
- **K13 Seri numaralı yedek parça adetle izlenmez (Soru 4).** `ck_products_yedek_parca_serisiz`; seri takipli parça (ör. yedek kamera) gerekiyorsa E03 kurulu ekipman / mobilite cihaz akışıyla izlenir.
- **K14 Asıl stok kaydı DengeERP'dir (Soru 6).** Logo/Flowick kapsam dışı; dış sistemle mutabakat yok.
- **K15 Depo adı ve tanımı `sistem.ayar` (Soru 10).** E06 K6 ile aynı; depolar mobilite/kiralama/servis arasında paylaşılan tabloda olduğu için tek yetki.
- **K16 Depo bazlı minimum ve kategori/uyumlu model alanları P3 (Soru 12).** Toplam bazlı `products.min_stok` yeterli; `brand/model/family/supplier_code` canlıda zaten var.
- **K17 Hata kodları canlı sözleşmeye göre.** Eski kabullerdeki "400" kural ihlalleri canlıda 409 (`main.py:131-161`, stok servisinde `TransferHatasi→409` emsali), Pydantic biçim hataları 422. Mesaj metinleri eski kabul kriterindeki gibi korunur.
- **K18 Excel, CSV yerine.** Canlı dışa aktarım standardı xlsx (`services/export.py`); formül enjeksiyonu koruması hazır.
- **K19 Eşzamanlılık kilidi = ürün satırı `FOR UPDATE`.** Bakiye kolonu olmadığı için satır kilidi ürün kaydına alınır; E06 toplu tahsis kalıbıyla aynı.
- **K20 Canlı `POST /api/stok/hareket` servis depolarına kapatılır.** Tek yazıcı ilkesinin tek istisnası mobilite depolarıdır; bu uç ve mobilite `StokPage` aynen kalır.
- **K21 E04-21 ve E05-17 güncellenir.** "Depo `POST /api/stok/hareket` ile çıkış yapar / parça çıkışı `cihaz.yaz`" geçici önerileri yerine E11 uçları (`parca.kullan`) kullanılır.
- **K22 Eski parça hareketi göç edilmez (M11-18).** Açılış stoğu fiziksel sayımla (E11-07) yüklenir; eski metin yalnız not olarak taşınır.

---

## 11. Korunan, kullanıcının doğruladığı işlevler

| İşlev | Bu modüldeki karşılığı |
|---|---|
| Tıklanabilir KPI kutuları | Yedek Parça "Stok" sekmesi: Az stok / Stok yok / Açık talep / Açık sayım kutuları filtreyi ayarlar (`GET /stok/ozet`) |
| Toplu işlem | Çok satırlı toplu çıkış, iade, giriş ve transfer (tek transaction); açılış stoğu toplu yükleme |
| Excel dışa aktarım | `stok.xlsx`, `hareketler.xlsx`, `parca-tuketimi.xlsx` (`rapor.disaaktar`) |
| Cihaz başına PB iş emri | PB işine parça doğrudan `service_order_id` ile bağlanır; ekipman geçmişinde tek ekipmanlı iş üzerinden görünür (E11-18) |

## 12. Dokunulmayanlar

`work_orders` / `work_order_items` / `settlements` zinciri; cihaz durum makinesi; `device_custody_history`, `transfers` ve `device_vehicle_assignments` EXCLUDE'ları; `ck_stok_hareket_neden`, `ck_stok_hareket_adet`, `ck_products_tip`; mobilite `StokPage.tsx`, `GET /api/stok/*` uçları; mevcut `DEPO` ve `TEKNIK_SERVIS` rolleri. Değişen canlı dosyalar yalnız eklemelidir: `models/stock.py`, `models/catalog.py`, `schemas/catalog.py`, `api/catalog.py` (mesaj), `api/stock.py` (servis deposu koruması), `api/imports.py` (`hepsi_ya_hic`), `services/imports/__init__.py`, `services/uyarilar.py`, `services/statemachine.py` (`MAKINELER`), `permissions.py`, `main.py`, `frontend/src/main.tsx`, `components/AppLayout.tsx`.
