# Teslim Raporu — Teknik Servis Modülleri (23 Ekim 2026, 05:50)

> **Durum: Kodlama bitti.** Planın 181 maddesinin **175'i TAMAM, 6'sı KISMEN, 0 EKSİK.** KISMEN maddelerin hiçbirinde kod eksiği yok; hepsi bir test ortamı, prova ya da sizin kararınızı bekliyor.
> Son tam test takımı: **2292 geçti / 0 hata / 14 atlandı.** Ruff, TypeScript derlemesi ve oxlint temiz. Son commit `3759772`.
> **Hiçbir şey canlı sunucuya veya canlı veritabanına yüklenmedi.** Tüm iş yerel kopyada: `Documents\DengeERP_Gelistirme\denge-erp` (git).

## Ne yapıldı (dalga dalga)

| Dalga | İçerik | Madde | Commit | Tam suite |
|---|---|---|---|---|
| 0 | Birim kapsamı (Güvenlik, Haberleşme, POC, Mobilite, Araç Takip), 8 servis rolü, 41+ izin, yetki yükseltme önlemi, oturum süresi, personel, müşteri/lokasyon/irtibat ana verisi | 18 | cf192a0 | 1126 ✓ |
| 1 | Servis iş emri yaşam döngüsü, iş havuzu ve tıklanabilir KPI'lar, planlama takvimi + toplu planlama/atama, güvenlik cihaz kütüğü, planlı bakım (1 cihaz = 1 PB iş emri, X-Ray 11 / kapı 10 kontrol formu), saha zaman kaydı, mobil "Benim İşlerim" | 55 | ab60255 | 1473 ✓ |
| 2 | SLA/Operasyon Merkezi, haberleşme atölyesi (+RMA köprüsü), kiralama (çift tahsis engeli, sevk→kurulum→toplama→kontrol), yedek parça/stok (negatif stok engeli), servis işinden teklif + iş bazlı maliyet, eğitim/yetkinlik/saha gözlemi, personel çıkışı, eski .NET verisi göçü (Göç-1) | 71 | be0467f | 1955 ✓ |
| 3 | Servis rapor/KPI motoru (eski 8 sayfalı Excel karşılığı), zaman ekranı, veri kalitesi, atölye/kiralama/parça/bakım/maliyet/eğitim raporları, e-posta bildirimleri, Göç-2 | 26 | 41fec5a | 2173 ✓ |
| 4 | Denetim izi değiştirilemez, parola yaşam döngüsü, süreli vekâlet, sızıntı testleri, canlı modüllerin (RMA, cihaz, rapor) kapsam açıkları, deploy betikleri, KURULUM ve kılavuz | 11 | 3759772 | 2292 ✓ |

Mobilite iş emirleri, hak ediş ve ödeme zincirine dokunulmadı; bunu bir regresyon testi kilitliyor ve her dalgada yeşil kaldı.

## KISMEN maddeler (kod hazır, aşağıdakiler bekleniyor)

| Madde | Bekleyen |
|---|---|
| TS-143 | Teklif/servis formu PDF testleri — bu Windows makinede PDF kütüphanesi yok; Docker/Linux'ta koşulmalı |
| TS-177 | Eski veri göçünün canlı döküm **kopyasında** birim birim provası |
| TS-200 | SLA için mesai/tatil takvimi isteniyor mu? (şu an takvim saati) — **sizin kararınız** |
| TS-201 | Gerçek Excel pivot şablonu Excel'de elle hazırlanmalı (şu an düz tablo) |
| TS-205 | Kiralama uzlaştırmasının gerçek pilot veriyle denenmesi |
| TS-220 | Canlıya çıkış provası (ayrı sunucuda, canlı döküm kopyasıyla) |

## Sizin kararınızı bekleyenler
1. **ATOLYE** rolüne `hesap.gor` verilsin mi? (Verilmezse atölye dış servis firması seçemiyor.)
2. **MUHASEBE_DESTEK** rolüne `servis_rapor.disaaktar` verilsin mi? (Servis fatura devri Excel'i için.)
3. **RMA maliyet alanı** (`cost`) `maliyet.gor` izni olmayanlardan gizlensin mi? Bugün canlıda herkese görünüyor.
4. SLA mesai takvimi (TS-200) ve pivot şablonu (TS-201).

## Doğrulanamayanlar (açıkça)
- **Hak ediş altın kayıt testi (932 iş / 552.825,00 TL)** bu makinede koşamadı (11 test atlandı): anonim veri dosyası gönderilen pakette yok. Kaynağın olduğu makinede ya da canlı kopya ortamında koşulmalı.
- **Ekranlar baştan sona tarayıcıda elle denenmedi.** Dalga 1 sürümü örnek verilerle açılıp temel ekranlar görüldü; Dalga 2–4 ekranları yalnız derleme + otomatik API testleriyle doğrulandı.
- Canlı döküm kopyasında `alembic upgrade` süresi ölçülmedi.

## Canlıda bulunan ve düzeltilen hatalar
- **Yedek doğrulama hiç çalışmıyordu:** `deploy/yedekle.sh` yedekleri `/var/backups/denge-erp`'e yazıyor, `deploy/dogrula.sh` `/var/yedek/denge-erp`'te arıyordu. Düzeltildi. **Canlıda yedeklerin gerçekten alındığını elle kontrol etmenizi öneririm.**
- Ek dosya deposu Windows'ta kullanımdaki dosyayı yetim sanıp silebiliyordu (Linux'ta etkisiz) — düzeltildi.
- Canlı RMA/cihaz uçlarındaki kapsam açıkları kapatıldı (Dalga 4).

## Canlıya geçiş
Adım adım liste: `analiz/CANLIYA_GECIS_KONTROL_LISTESI.md`. Özet:
1. Paketi üret (`paket-uret.sh` yalnız git'teki dosyaları paketler — hepsi commit'li).
2. Ayrı bir sunucuda canlı döküm **kopyasıyla** prova: yedek → `alembic upgrade` (b30e012dd879 → d4a000000002) → altın kayıt testi → PDF testleri → göç provası.
3. Pilot birim **GÜVENLİK** ile başla; `bakim_otomatik_uretim` kapalı başlar, sözleşme–ekipman eşleştirmesi %100 olunca açılır.
4. Geri dönüş: downgrade yok — önce `geri-yukle.sh` ile yedek, sonra önceki paketle `kur.sh`.

## Belgeler
- Madde madde durum (181 madde, kanıt dosya/test): `analiz/TESLIM_MADDE_DURUMU.md`
- Canlıya geçiş kontrol listesi: `analiz/CANLIYA_GECIS_KONTROL_LISTESI.md`
- Plan: `analiz/10_canli_entegrasyon/01_ENTEGRASYON_VE_KODLAMA_PLANI.md`
- Kurulum: `denge-erp/deploy/KURULUM.md` · Kullanım kılavuzu: `denge-erp/docs/KULLANIM-KILAVUZU.md`

## Bu makinede denemek
Deneme ortamı (`denge-erp-deneme`, http://127.0.0.1:5173, API :8000) **son sürümde (3759772)** açık, örnek veri yüklü (3 müşteri, 15 cihaz, 2 sözleşme, 18 PB + 4 servis işi). 16 teknik servis ekranının hepsi açılıyor, konsolda hata yok (yalnız Ant Design eskime uyarıları). Yönetici parolası `.yerel_gizli/deneme_admin.txt`; deneme hesapları rol kodunun küçük harflisi (`servis_yonetici`, `servis_sef`, `servis_teknisyen`…), parola `backend/app/seeds/dev.py` içindeki `DEMO_PAROLA`.
