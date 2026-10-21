# Denge Mobilite ERP

Araç takip cihazı ve araç içi kamera işine özel iç ERP. Cihazın ömür boyu
geçmişini tarihli tutar, montaj noktası hak edişini uçtan uca yönetir.

Kapsam ve gerekçeler: `~/.claude/plans/users-muaz-downloads-denge-mobil-erp-br-nested-dawn.md`

## Hızlı başlangıç

```bash
make kur          # bagimliliklar + .env
make db           # PostgreSQL 17 (Docker)
make migrate      # sema
make seed         # roller, izinler, ilk yonetici (parolayi kaydedin)
make api          # http://localhost:8000
make web          # http://localhost:5173
```

Geliştirme sırasında her rolden birer deneme hesabı:

```bash
cd backend && uv run python -m app.seeds.dev --demo   # parola: deneme1234
```

Kullanıcı adları rol kodunun küçük harflisidir: `depo`, `satis`, `montaj_koord`…
`--demo` yalnız `ENV=dev` ortamında çalışır.

## Neden Docker

`pgserver` (Docker'sız gömülü PostgreSQL) PostgreSQL 16.2 getiriyor ve uzantı
listesinde **`btree_gist` yok**. ERP'nin çekirdek kısıtı — "aynı cihaz için
çakışan dönem olamaz" — `EXCLUDE USING gist (device_id WITH =, tstzrange(...)
WITH &&)` ile yazılır ve o uzantı olmadan ifade edilemez. Ayrıca WeasyPrint'in
Pango/HarfBuzz bağımlılıkları (Türkçe karakterlerin PDF'te doğru şekillenmesi)
Mac'te kurulu değil. Aynı imaj hem geliştirme makinesinde hem Linux sunucuda
çalışır.

## Mimari kararlar

| Karar | Gerekçe |
|---|---|
| **İyimser kilitleme** her ana kayıtta (`version`) | 6-15 kişi eşzamanlı çalışıyor. Bu olmadan iki kişi aynı kaydı açtığında son kaydedenin dışındaki değişiklik sessizce kaybolur. Çakışma 409 döner. |
| **Vergi/fiyat dondurma** | Oranlar `settings`'ten değişebiliyor; teklif, sipariş, abonelik ve hak ediş satırı oluşturulduğu andaki oranı kendi içinde saklar. Ayar değişince geçmiş belgeler değişmez. |
| **Kapanmış dönem değişmez** | Ödenen döküm kilitlenir; düzeltme sonraki döneme devreden ayrı satır olarak girer. Kilit kırma yolu yok — denetim izi anlamını korusun diye. |
| **RBAC uygulama katmanında, RLS değil** | RLS çok kiracılı izolasyon içindir (takip platformunda öyle kullanılıyor). Burada ihtiyaç "satış temsilcisi kendi müşterilerini görür" gibi alan bazlı filtre; RLS bu iş için hem aşırı hem hata ayıklaması zor. |
| **Maliyet varsayılan gizli** | `maliyet.gor` ayrı bir izin. "Varsayılan açık, bazılarında gizle" tasarımı güvenlik açısından yanlış olurdu. |
| **Hesap rolü bayrak seti** | Tekil enum gerçeği taşımıyordu: kendi aracına kendi montajını yapan müşteri hem müşteri hem montaj noktası. Kaynak veride beş hesap aynı anda hem bayi hem montaj noktası. |
| **Kimlik tipi ürüne bağlı, kural ŞEMADA** | Ek kameralar analog (HDCVI) — modemleri yok, IMEI'leri fiziksel olarak yok. `identity_kind` ürün kartından kopyalanır, bileşik yabancı anahtarla ürüne bağlanır ve CHECK ile zorlanır: hatalı bir servis, elle SQL ya da göç betiği bile IMEI'siz takip cihazı kaydedemez. |
| **Tarihli kayıtlarda EXCLUDE kısıtı** | `EXCLUDE USING gist (... WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)`. Aralık yarı açık: `[]` olsaydı aynı gün sök-tak yapılan gerçek kayıtlar reddedilirdi. |
| **Konum ve sahiplik ayrı boyut** | Cihaz fiziksel olarak bayide dururken ticari olarak Denge'nin malı olabilir. Tek alanda birleştirmek bu ayrımı kaybettirirdi; konum değişikliği tek başına mülkiyeti değiştirmez. |
| **Elle girilen hat alanı senkronda ezilmez** | `field_sources` haritası alan bazında kaynağı tutar. Ezilseydi ekibin düzelttiği değer her gece geri alınırdı. |
| **Sahte kimlik üretilmez** | IMEI bulunamayan cihaz için yer tutucu numara ÜRETİLMEZ; kayıt açılmaz ve düzeltme listesine düşer. Sahte IMEI zamanla gerçek sanılır — bugünkü `…......` dolgusunun daha kötüsü olurdu. |
| **Celery/Redis yok** | Yılda ~2.500 iş emri için Postgres `FOR UPDATE SKIP LOCKED` fazlasıyla yeter; tek sunucuda ek bileşen işletme yüküdür. |

## İzinler ve roller

Tek kaynak: `backend/app/permissions.py` (40 izin, 9 rol). Seed betiği DB'yi bu
katalogdan senkronlar — katalogdan silinen izin DB'den de düşer. Menü kalemleri
izne göre gizlenir, ama **sunucu her uçta kendi kontrolünü ayrıca yapar**;
arayüz kısıtı yalnız görsel kolaylıktır.

## Test

```bash
make test
```

Testler **ayrı bir veritabanında** koşar (`dengeerp_test`) ve geliştirme
verisine asla dokunmaz. Şema `alembic upgrade head` ile kurulur — böylece her
koşu migration zincirini de doğrular.

## Durum

| Dilim | İçerik | Durum |
|---|---|---|
| D0 | İskelet, kimlik/MFA, RBAC, denetim izi, parametreler | **bitti** |
| D1 | Hesaplar, ürün kataloğu, genel arama, veri göçü çekirdeği | **bitti** |
| D2 | Araçlar, cihazlar, hatlar, tarihli geçmişler, dosya ekleri | **bitti** |
| D3 | İş emri (= ziyaret), cihaz-araç ömür boyu geçmişi | **bitti** |
| D4 | Tarifeler ve hak ediş | **bitti** |
| D5 | PDF + e-posta + ödeme kaydı → **devir noktası** | **bitti** |
| D6 | Stok, transfer, konum/sahiplik geçmişi, bayi stoğu | **bitti** |
| D7 | Hat tam kapsam: paket geçmişi, kota/2G/atıl/kârlılık raporları, operatör adaptörü | **bitti** |
| D8 | Teklif: versiyonlama, iskonto onayı, PDF, e-posta, online kabul | **bitti** |
| D9 | Sipariş, IMEI rezervasyonu, sevkiyat; abonelik, kıst hesap, MRR | **bitti** |
| D9b | Tahsilat, bakiye takibi, toplu fiyat güncelleme | **bitti** |
| — | Toplu içe aktarma: dokuz profil (varlıklar + tarihli eşleştirmeler) | **bitti** |
| D10 | Takip platformu entegrasyonu | **ertelendi** (platform hazır olunca) |
| D11 | RMA/garanti, satın alma, ithalat/landed cost, BTK | **bitti** |
| D12 | Raporlar, yönetim paneli, KVKK | **bitti** |
| D13 | Sertleştirme, sunucuya çıkış, yedek provası, kılavuz | **bitti** |

## Altın kayıt

ERP'nin hak ediş rakamı canlı uygulamayla **kuruşu kuruşuna** aynı:

| Dönem | İş | Tutar |
|---|---:|---:|
| 2026-01 | 208 | 152.700,00 |
| 2026-02 | 190 | 98.475,00 |
| 2026-03 | 132 | 60.950,00 |
| 2026-04 | 149 | 89.300,00 |
| 2026-05 | 150 | 96.000,00 |
| 2026-06 | 91 | 51.100,00 |
| 2026-07 | 12 | 4.300,00 |
| **Toplam** | **932** | **552.825,00** |

`make test-goc` bunu her koşuda doğrular. Girdi, canlı veritabanının
anonimleştirilmiş kopyasıdır (`tests/fixtures/altin/`): plaka, firma ve IMEI'nin
son haneleri maskeli; tarih, tutar, montaj noktası adı ve ödeme durumu aynen
korunuyor — test tam olarak bunları doğruluyor.

İki bilinçli sapma:
- **Nisan 2026: 146/86.300 yerine 149/89.300.** Canlı uygulama `odemeDurumu`
  karşılaştırmasını tam eşleşmeyle yaptığı için küçük harfle yazılmış 3 kaydı
  (3.000 TL) hak edişe hiç almamıştı. Kullanıcı kararı: bu bir hataydı.
- **Döküm 84 yerine 83.** `ANTALYA RAMAZAN CULLU` ile `ÇULLU` 2026-02'de ikisi
  de iş yapmış; montaj noktası birleştirmesi sonrası tek döküme iniyorlar.
  Para toplamı değişmiyor.

## Veri göçü

```bash
make goc-onizleme   # HİÇBİR ŞEY yazmaz, ne olacağını anlatır
make goc-uygula     # tek transaction
```

İki kaynaktan (hak ediş veritabanı + Esenyurt montaj dosyası) aktarılan:

| | |
|---|---:|
| Montaj noktası (44'ten, 5 birleştirme) | 39 |
| Müşteri | 192 |
| Bayi (5'i zaten montaj noktası — aynı hesaba ikinci bayrak) | 9 |
| Ürün (25 serbest metin değerinden) | 13 |
| Araç | 1.458 |
| Cihaz | 1.696 |
| Hat | 1.657 |
| İş emri (= ziyaret) | 1.226 |
| Cihaz–araç dönemi (çıkarımla) | 963 |

39 IMEI aynı hattın geçtiği başka satırdan kurtarıldı. Ek kameraların seri
numarası kaynakta yok — sahadan toplanması gereken bir **süreç işi**,
yazılım işi değil.

`--uygula` sonunda türetilmiş alanlar (`devices.current_*`,
`first_activation_date`) tarihli tablolardan yeniden hesaplanır. Bu adım
atlanırsa göçten gelen her cihazın RMA garanti kararı "belirsiz" çıkar.

Göç tekrar çalıştırılabilir: her kayıt `source_system`/`source_ref` taşır,
ikinci koşu kopya üretmez. Birleştirme kararları `app/migration/esleme.py`
içinde elle yazılmıştır — otomatik benzerlik yalnız aday üretir. Bunun neden
şart olduğunun kanıtı aynı dosyada: `BALIKESİR KOÇ OTO` ile `BURSA 3D MOBİL`
aynı telefonu taşıyor ama farklı firmalar.

## Belgeler

| Belge | Kim için |
|---|---|
| [deploy/KURULUM.md](deploy/KURULUM.md) | Sunucuya kurulum, yedekleme, sertleştirme |
| [docs/KULLANIM-KILAVUZU.md](docs/KULLANIM-KILAVUZU.md) | ERP'yi günlük kullanan ekip |
| [docs/openapi.json](docs/openapi.json) | Entegrasyon yazacak geliştirici (`make openapi` ile üretilir) |

Üretimde `/api/docs` **kapalıdır** — API yüzeyini dışarı sergilememek için.
Şema repodan alınır, sunucudan değil.

## Dizin yapısı

```
backend/app/
├── permissions.py     # izin katalogu ve rol tanimlari (tek kaynak)
├── config.py          # altyapi ayarlari (.env)
├── clock.py           # enjekte edilebilir saat — tarihli mantik bununla test edilir
├── crypto.py          # hassas ayar sifreleme, sureli jeton
├── models/            # ORM + ortak mixin'ler (surum, denetim, yumusak silme)
├── services/          # auth, mfa, audit, settings
├── api/               # FastAPI yonlendiricileri + deps (izin fabrikasi)
├── seeds/             # referans veri (idempotent)
└── migration/         # veri gocu (D2'den itibaren)
frontend/src/
├── theme.ts           # Denge kurumsal kimligi → Ant Design
├── api/client.ts      # CSRF basligi, 409 cakisma ayrimi
└── pages/             # ekranlar
```
