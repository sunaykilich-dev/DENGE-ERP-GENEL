# Canlıya çıkış provası — tutanak biçimi ve kayıtlar

Plan §5, TS-220. Her R sürümünden (teknik servis R1…R4) önce, canlı dökümün
**kopyası** üzerinde ayrı bir prova sunucusunda koşulur. Canlı sunucuya ve
canlı döküme dokunulmaz. Nasıl koşulacağı: `KURULUM.md` EK G.7.

Tutanağı `cikis-provasi.sh` kendisi üretir (`CIKIS-PROVASI-<damga>.md` +
`.log`); bu belge biçimi, kabul ölçütlerini ve imza bölümünü sabitler ve
yapılmış provaların özetini tutar.

## 1. Adımlar ve kabul ölçütleri

| # | Adım | Komut | Kabul |
|---|---|---|---|
| 1 | Parmak izi (önce) | betik içi SQL | hesap, cihaz, araç, hat, iş emri, kalem, cihaz-araç dönemi sayıları; hak ediş dökümü, brüt, satır toplamı ve dönem bazında tutar alındı |
| 2 | Yedek | `yedekle.sh` | `dengeerp-<damga>.sql.gz.gpg` ve `dosyalar-<damga>.tar.gz.gpg` `YEDEK_DIZIN`'de; ad ve boyut tutanakta |
| 3 | Yükseltme | `kur.sh` | `KURULUM BAŞARILI`; göç sürümü = paketin `hedef head`'i (`d4a000000002`) |
| 4 | Doğrulama | `dogrula.sh` | `SISTEM SAGLIKLI`: göç sürümü = head, tüm roller, servis tabloları, tüm worker görevleri, son yedek |
| 5 | Altın kayıt | parmak izi (sonra) | önce = sonra, **satır satır aynı** (hak ediş toplamı kuruşu kuruşuna) |
| 6 | Servis duman testi | `servis_duman.py` | tüm servis uçları kayıtlı; arıza işi açıldı, okundu, olay yazıldı; transaction geri alındı |
| 7 | Geri yükleme provası | `geri-yukle.sh <2. adımın yedeği>` | `PROVA BAŞARILI`; sayılar 1. adımla aynı; dosya arşivi okunuyor |
| 8 | Geri dönüş provası (`--geri-donus`) | `geri-yukle.sh` (ZORLA) → önceki paket `kur.sh` | önceki sürüm açıldı, göç sürümü önceki head, parmak izi 1. adımla aynı |

Bir adım **HATA** ise canlıya çıkılmaz. 4–7 bağımsız koşar (tutanak tam
olsun diye); 1–3'ten biri düşerse sonrası atlanır.

## 2. Tutanak şablonu

`cikis-provasi.sh` çıktısı bu biçimdedir; elle prova yapılırsa aynı tablo
doldurulur.

| Alan | Değer |
|---|---|
| Başlangıç | |
| Sunucu | |
| Hedef dizin | `/opt/denge-erp` |
| Yeni paket (SURUM.txt) | commit, hedef head, teknik servis sürümü |
| Önceki paket | |
| Yürüten | |

| # | Adım | Başlangıç | Bitiş | Sonuç | Not |
|---|---|---|---|---|---|
| 1 | Parmak izi (yükseltme öncesi) | | | | |
| 2 | Yedek (yedekle.sh) | | | | yedek adı, boyutu |
| 3 | Yükseltme (kur.sh) | | | | göç sürümü |
| 4 | Doğrulama (dogrula.sh) | | | | |
| 5 | Altın kayıt (mobilite parmak izi) | | | | hakedis_brut |
| 6 | Servis duman testi | | | | |
| 7 | Geri yükleme provası | | | | |
| 8 | Geri dönüş provası | | | | |

| Rol | Ad Soyad | İmza |
|---|---|---|
| Yürüten | | |
| Onaylayan (servis müdürü) | | |
| Onaylayan (BT / sistem) | | |

## 3. Yapılan provalar

### 3.1 Geliştirme ön provası — Windows, D4-C (2026-10-22)

Prova sunucusu bu ortamda yok (Docker ve Linux kabuğu yok); sunucu
adımları (2, 3, 4, 7, 8) **koşulmadı**. Koşulabilenler kendi test
veritabanında (`dengeerp_test_c`) yapıldı:

| # | Adım | Başlangıç | Bitiş | Sonuç | Not |
|---|---|---|---|---|---|
| 0 | `alembic upgrade head` | — | — | TAMAM | saat kaydı alınmadı; `d3a000000004 → d4a000000001 → d4a000000002`, tek head |
| 1 | Ön kontrol bölüm 2–3 (Git Bash) | — | — | TAMAM | saat kaydı alınmadı; 487 `.py` derlendi; 39 migration (alt sınır 39); tek head `d4a000000002` |
| 2 | Deploy tutarlılık testi + `bash -n` (tüm `.sh`) | 22:30:37 | 22:44:04 | TAMAM | `test_deploy_betikleri.py` (aşağıdaki koşunun içinde) |
| 3 | Servis duman testi (gerçek şemada) | 22:30:37 | 22:44:04 | TAMAM | `test_cikis_provasi_duman.py`: iş açıldı/okundu/olay yazıldı, geri almadan sonra 0 satır |
| 4 | Mobilite etkisizlik + uçtan uca (D1, D2) + servis rapor altın + yetki matrisi + kapsam taraması + `tests/unit` + `tests/migration` | 22:30:37 | 22:44:04 | TAMAM | **670 geçti, 11 atlandı, 0 hata** |
| 5 | Migration zinciri head→base→head | 22:49:13 | 22:52:41 | TAMAM | `test_migration_zinciri.py` geçti |
| 6 | Altın kayıt (932 iş / 552.825,00 TL) | 22:49:13 | 22:52:41 | **ATLANDI** | `tests/fixtures/altin/hakedis-anonim.db` bu çalışma kopyasında yok; prova sunucusunda 5. adımın parmak izi ile, geliştirmede fixture olan makinede `make test-goc` ile koşulmalı |

Sonuç: prova sunucusunda koşulacak betikler sözdizimi ve kodla tutarlılık
bakımından hazır; **canlıya çıkış kararı için 3.2 zorunludur.**

### 3.2 Prova sunucusu — canlı döküm kopyası

Henüz yapılmadı. R4 öncesinde `PROVA_ONAY=evet ./cikis-provasi.sh
--geri-donus <önceki paket>` ile koşulup üretilen tutanak buraya eklenir.
