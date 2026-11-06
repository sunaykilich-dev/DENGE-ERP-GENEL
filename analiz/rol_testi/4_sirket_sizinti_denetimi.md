# 4 — Şirket ayrımı ve yetki sızıntısı denetimi (kırmızı takım, 2026-11-04)

Denetçi: "şirket ayrımı ve yetki sızıntısı denetçisi" ajanı. Ortam: yalnız yerel (API 127.0.0.1:8000, web 127.0.0.1:5173,
yerel PostgreSQL salt okunur sorgu). Kod değiştirilmedi; canlıya dokunulmadı; parola hiçbir çıktıya yazılmadı
(betikler `.yerel_gizli/rol_test_kullanicilari.txt` dosyasından okur).

Betikler ve ham sonuçlar: `C:\Users\skilic\AppData\Local\Temp\claude\ff375d97b5e42a31\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rol_testi\sizinti\`
(`lib.py` oturum/DB yardımcısı, `gercek.py` şirket bazlı gerçek kimlik/numara kümesi, `tarama.py` bütün GET uçları taraması,
`yazma.py` / `yazma2.py` yazma sınırları, `ek_testler.py` şirket seçimi/iki oturum/mobilite kapısı/arama, `musteri.py`
ortak müşteri kartı, `maliyet.py` maliyet alanı taraması, `arayuz.py` Playwright, `ozet.py` / `matris.py` tablolar;
`tarama_<kullanici>_<sirket>.json`, `yazma_sonuc.json`, `yazma2_sonuc.json`, `ek_sonuc.json`, `musteri_sonuc.json`, `ui_*.png`).

## 1. Ne yaptım

**Gerçek küme (salt okunur DB):** TELEKOM = 15 servis işi (HABERLESME, id 112–126), ekipman/sözleşme yok.
ELEKTRONIK = 117 iş (GUVENLIK 114 + BARIYER 3), 158 ekipman, 2 bakım sözleşmesi (BAKIM-0001/0002), 4 bakım dönemi, 2 plan,
18 PB formu. MOBİLİTE = teknik servis kaydı yok; mobilite modülü tabloları (cihaz, hat, araç, iş emri, hak ediş) yerelde **boş**.
Kiralama, kiralık envanter, yedek parça deposu/stok, teklif, atölye kaydı, ziyaret, zaman kaydı tabloları da boş — bu kanallar
yalnız "boş liste / 404 / 403" yapısıyla doğrulanabildi (veri olmadan içerik sızıntısı ölçülemez).

**A) Bütün GET uçları taraması (`tarama.py`).** `/api/openapi.json`'dan 321 GET ucu çıkarıldı (87'si yol parametreli).
Her kullanıcı için her uç çağrıldı; yol parametreleri KARŞI şirketin gerçek kimlikleriyle dolduruldu (iş: ilk/orta/son +
plan bağlı iş; ekipman 1–2; sözleşme 1; dönem; karşı şirket personel id'leri; karşı şirket müşterisi); zorunlu sorgu
parametreleri dolduruldu; `birim` süzgeci olan her liste ucu ayrıca `?birim=<karşı birim>` ile çağrıldı. Yanıt (JSON ve
Excel içeriği openpyxl ile açılarak) karşı şirketin iş numaraları, ekipman seri noları, sözleşme noları, personel adları ve
kullanıcı adlarıyla taranıp işaretlendi. 23 kullanıcı×şirket bileşimi, toplam 10.723 istek, **5xx yok**.

Kullanıcılar: TELEKOM → ELEKTRONIK: t_ops_hab, t_tek_hab, t_sdestek_hab, t_yon_hab, t_sef_hab.
ELEKTRONIK → TELEKOM: t_ops_guv, t_tek_guv1, t_sdestek_guv, t_yon_guv, t_sef_guv, t_sef_bar, t_saha_guv, t_atolye_guv,
t_depo_guv, t_satis_guv, t_finans_uzm. MOBİLİTE → teknik servis: t_mob_depo. Çok şirketli: t_yonetim ve t_finans_yon
her üç şirkette ayrı ayrı.

**B) Yazma sınırları (`yazma.py`, `yazma2.py`).** Kendi test kayıtlarım açıldı, karşı şirket kullanıcılarıyla saldırıldı, sonra geri alındı
(bkz. kayıt listesi). Denenenler: karşı birimle iş açma (normal, uzaktan çözüldü, ekipmandan), işin/ekipmanın birimini taşıma,
karşı şirket işine not/PATCH/durum/iptal/plan/ek yükleme/toplu atama/ilişki kurma, karşı şirket personelini atama/plan ekibine
koyma, atanmamış teknisyenin ve karşı şirket teknisyeninin sonuç girmesi/zaman başlatması, YONETIM ile yazma, karşı şirket
ekinin indirilmesi/silinmesi, karşı şirket ekipmanının ayrıntı/geçmiş/pasife alma/ondan iş açma, aynı seriyle ekipman açma,
görev panosu üzerinden kayda bağlanma.

**C) Şirket seçimi ve oturum (`ek_testler.py`, `t6.py`).** Üye olunmayan şirkete PUT (büyük/küçük harf, boşluklu, olmayan kod);
t_yonetim/t_finans_yon için üç şirkette liste ve sayaçların değişmesi; aynı kullanıcının iki oturumu farklı şirkette;
yeniden girişte varsayılan şirket.

**D) Mobilite kapısı:** 18 mobilite/ortak uç × 7 kullanıcı; arayüzde menü ve URL ile doğrudan açma (Playwright, `ui_*.png`).

**E) Arama:** `/api/arama` (Ctrl+K bu ucu kullanır, `frontend/src/components/GlobalSearch.tsx:115`) karşı şirketin tam iş no'su,
seri no'su, sözleşme no'su ve önekleriyle.

**F) Ortak müşteri kartı (`musteri.py`):** ELEKTRONIK işi/ekipmanı/sözleşmesi olan 10 müşteri TELEKOM ve MOBİLİTE kullanıcılarıyla;
TELEKOM işi olan 6 müşteri ELEKTRONIK kullanıcılarıyla — hesap kartı, servis kartı, kapsam bilgisi, lokasyonlar, takma adlar,
müşteri süzgeçli iş/ekipman/sözleşme listeleri. Toplam 828 istek.

**G) Maliyet alanı (`maliyet.py`):** maliyet.gor olmayan 12 rolün eriştiği bütün JSON yanıtlarında maliyet/fiyat/tutar/ücret/marj
anahtarları (dolu değer) arandı; ayrıca maliyet.gor sahibi (t_finans_yon) ile karşılaştırma.

**Açılan / işlenen kayıtlar (hepsi geri alındı):**
- SRV-202611-000133 (id 133, GUVENLIK, t_ops_guv açtı; t_sef_guv t_tek_guv1'i atadı) → **İPTAL** edildi (t_sef_guv).
- SRV-202611-000134 (id 134, HABERLESME, t_ops_hab açtı) → **İPTAL** edildi (t_sef_hab).
- Ek dosya #1 (`sizinti_test.txt`, iş 134'e) → silindi.
- Ekipman #159 (HABERLESME, TELSIZ, seri `SIZINTI-TEST-HAB-77`, müşteri İGDAŞ) → **pasife alındı** (silme ucu yok).
- Görev panosu #1 "SIZINTI-TEST pano" ve kartlar #1–#3 → silindi.
- Ayrıca her test oturumu için `oturum.sirket_degistir` denetim kayıtları oluştu (beklenen davranış).

## 2. Bulgular

| No | Önem | Tür | Ekran veya uç | Yeniden üretme adımı (parolasız) | Beklenen | Gerçekleşen | Önerilen düzeltme |
|---|---|---|---|---|---|---|---|
| S1 | **KRİTİK** | sızıntı | Görevler: `POST /api/gorevler/panolar/{id}/kartlar`, `GET /api/gorevler/panolar`, `GET /api/gorevler/panolar/{id}/kartlar`, `GET /api/gorevler/kayit/{entity}/{id}` | 1) t_ops_hab (TELEKOM) giriş → `POST /api/gorevler/panolar {"title":"X","kolonlar":["Yapılacak"]}` → `POST /api/gorevler/panolar/1/kartlar {"column_id":1,"title":"x","entity":"servis_isi","entity_id":133}` (133 = ELEKTRONIK işi). 2) Aynı istek `entity":"bakim_sozlesme","entity_id":1`. 3) t_ops_guv (ELEKTRONIK) ve t_mob_depo (MOBİLİTE) giriş → `GET /api/gorevler/panolar`, `GET /api/gorevler/panolar/1/kartlar`, `GET /api/gorevler/kayit/servis_isi/134`. (Betik: `yazma.py` §8) | Kart yalnız etkin şirketin/kapsamın kaydına bağlanabilmeli (aksi 404); pano ve kartlar başka şirkette görünmemeli; bağlantı etiketi kapsam dışı kayıtta numara vermemeli | 1–2) 201; yanıttaki `baglanti.etiket` = **SRV-202611-000133** ve **BAKIM-0001** (başka şirketin kayıt numarası id ile sayılabiliyor). 3) TELEKOM panosu ELEKTRONIK ve MOBİLİTE kullanıcılarına 200 ile listeleniyor; kart başlığı/açıklaması, yorumlar ve bağlı TELEKOM işinin numarası (SRV-202611-000134) okunuyor. Kod gereği aynı yol mobilite kapısını da aşar: `cihaz` (IMEI/seri), `arac` (**plaka**), `hat` (**MSISDN/ICCID**), `isemri`, `rma`, `teklif` tiplerinde etiket kaydın kendi alanıdır → TELEKOM/ELEKTRONIK kullanıcısı id sayarak mobilite kişisel verisini okuyabilir (yerelde mobilite verisi boş olduğu için bu kısım koddan çıkarım; servis_isi ve bakim_sozlesme canlı doğrulandı) | `api/gorevler.py:6-10` "kapsam filtresi uygulanmaz" kararı şirket ayrımından önce; `:199-208` `_baglantiyi_dogrula` yalnız tipi doğruluyor; `:643-655` kart açılışında kayıt kapsamı yok; `:378-396` pano listesi süzgeçsiz; `:614-641` kart/kayıt listeleri süzgeçsiz; `services/gorevler.py:54-75` etiket alanları (plaka, MSISDN, IMEI), `:95-140` `baglanti_cozumle` kapsamsız. Öneri: (a) `boards.sirket_kod` ekle, pano/kart/yorum uçlarını etkin şirketle süz; (b) kart açılışında/güncellemesinde bağlı kaydı tipine göre kapsamdan geçir (servis_isi → `kapsam.is_erisimi_yok_mu`, ekipman/sözleşme/kiralama → `kapsam.birim_disinda_mi`, mobilite tipleri → `sirketler.mobilite_acik_mi` + `hesap_svc.kapsam_musteri`), değilse 404; (c) `baglanti_cozumle` okuyana göre çalışsın: erişemediği kayıtta etiket "erişim yok", `yol` boş |
| S2 | **YÜKSEK** | yetki | Mobilite: `GET /api/hakedis/donem/{period}/excel`, `GET /api/abonelikler/tahakkuk/{donem}/xlsx`, `GET /api/raporlar/mrr/{donem}` | t_mob_depo (DEPO, MOBİLİTE) giriş → `GET /api/hakedis` (403 hakedis.gor) → `GET /api/hakedis/donem/2026-11/excel` (200, xlsx) → `GET /api/abonelikler` (403 abonelik.gor) → `GET /api/abonelikler/tahakkuk/2026-11/xlsx` (200) → `GET /api/raporlar/mrr/2026-11` (200) | Hak ediş ödeme listesi ve abonelik tahakkuku, ekranını göremeyen role dışa aktarılamamalı | DEPO rolü yalnız `rapor.disaaktar`/`rapor.gor` ile bayi ödeme listesini, tahakkuk satırlarını ve MRR/ARR'ı indirebiliyor (yerelde dönem verisi boş; yetki yapısı doğrulandı, dosya başlıkları döndü) | `api/settlements.py:528-532` yalnız `rapor.disaaktar`; `api/subscriptions.py:250-252` yalnız `rapor.disaaktar`; `api/reports.py:36,251-252` yalnız `rapor.gor`. Öneri: `require_permission("rapor.disaaktar","hakedis.gor")`, `("rapor.disaaktar","abonelik.gor")`, MRR'a `abonelik.gor`. Not: mobilite modülüne dokunma kuralı (G2.5) nedeniyle karar ana oturumda — değişiklik yalnız izin bağımlılığıdır, iş kuralı değişmez |
| S3 | ORTA | sızıntı | Personel: `GET /api/personel`, `GET /api/personel/liste.xlsx`, `GET /api/personel/ozet` | t_yon_hab (TELEKOM, TUMU) giriş → `GET /api/personel?limit=200` | Yalnız etkin şirketin (üyelik/birim) personeli | 20 satırın 15'i birimsiz kişiler; aralarında **yalnız MOBİLİTE üyesi t_mob_depo** ve **yalnız ELEKTRONİK üyesi t_finans_uzm** var; ELEKTRONİK listesinde de aynı kişiler + bütün canlı birimsiz roller (depo, satış, muhasebe, hat sorumlusu…). Şirket üyeliği (`kullanici_sirketleri`) hiç dikkate alınmıyor | `services/teknik_servis/kapsam.py:285-301` `sirket_personel_kosulu`: birimsiz kişi "ortak" sayılıyor. Öneri: birimsiz kişide `kullanici_sirketleri.sirket_kod = etkin şirket` koşulu (ADMIN/ortak roller için açık liste tutulabilir) |
| S4 | ORTA | UX | Mobilite ekranları URL ile: `/cihazlar`, `/hatlar`, `/is-emirleri` (TELEKOM/ELEKTRONİK etkinken) | t_ops_hab giriş → tarayıcıda `http://127.0.0.1:5173/cihazlar` (ekran: `ui_t_ops_hab_cihazlar.png`) | "Bu ekran yalnız DENGE MOBİLİTE şirketinde kullanılır…" mesajı + şirket değiştirme yolu | Menüde gizli (doğru), ama URL ile açılınca tablo **"Veri Yok"** gösteriyor; sunucunun döndürdüğü 403 `SIRKET_DISI` mesajı hiç görünmüyor → kullanıcı veri yok sanar | Ön yüzde `SIRKET_DISI` hiç ele alınmıyor (`frontend/src` içinde kod yok); `pages/CihazlarPage.tsx:39` liste sorgusu hatayı göstermiyor (yalnız mutasyon `:205`). Öneri: `api/client.ts` `ApiError.govde.detail.kod === "SIRKET_DISI"` → ortak `<Result status=403>` + "DENGE MOBİLİTE'ye geç" düğmesi; mobilite rotalarına şirket koruyucusu |
| S5 | DÜŞÜK | sızıntı | Mükerrer seri: `POST /api/teknik-servis/ekipman` 409, `GET /api/teknik-servis/isler/mukerrer-kontrol`, iş açılışı 409 | t_sef_hab TELEKOM'da seri X ile ekipman açar; t_yon_guv (ELEKTRONİK) `POST /api/teknik-servis/ekipman {"birim":"GUVENLIK","equipment_type":"TELSIZ","account_id":4,"serial_no":X}` | Başka şirketin kaydı ne varlık ne adet olarak belli olmamalı; şirketler birbirinin seri kaydını engellememeli | 409 "Aynı seri no ile başka bir birimde aktif kayıt var", `kapsam_disi: 1` → başka şirkette o serinin varlığı/adedi öğreniliyor (numara/id sızmıyor); ayrıca ELEKTRONİK, TELEKOM'daki seri yüzünden gerekçe yazmadan kayıt açamıyor | `services/teknik_servis/ekipman.py:325-352` ve `services/teknik_servis/is_emirleri.py:1181-1215` mükerrer araması şirket süzgeçsiz. Öneri: mükerrer kontrolünü etkin şirketin birimleriyle sınırla (şirketler arası aynı seri meşru: farklı tüzel kişilik); kapsam dışı bayrağını yalnız aynı şirket içi için ver |

**Bulgu sayısı:** 1 KRİTİK, 1 YÜKSEK, 2 ORTA, 1 DÜŞÜK. Teknik servis uçlarının **hiçbirinde** (liste, sayaç, arama, ayrıntı,
Excel, PDF, rapor, bildirim, takvim, denetim) karşı şirket kaydı sızmadı.

### 2.1 Uç × kullanıcı özeti (karşı şirket kimlikleriyle tarama)

Kullanıcı başına durum dağılımı ("işaretli 200" = yanıtta karşı şirketin iş/seri/sözleşme no'su ya da personel adı var).
t_sef_hab ve t_mob_depo'daki 2'şer işaretli yanıtın tamamı S1'dir (tarama sırasında açık duran test panosundaki BAKIM-0001 bağlantısı).

| Kullanıcı @ şirket | Rol | GET isteği | 200 | 403 | 404 | 400/422 | 5xx | Karşı şirket işaretli 200 |
|---|---|---|---|---|---|---|---|---|
| t_ops_hab @ TELEKOM | SERVIS_OPERASYON | 477 | 66 | 330 | 76 | 5 | 0 | 0 |
| t_tek_hab @ TELEKOM | SERVIS_TEKNISYEN | 477 | 56 | 336 | 81 | 4 | 0 | 0 |
| t_sdestek_hab @ TELEKOM | SATIS_DESTEK | 477 | 66 | 314 | 93 | 4 | 0 | 0 |
| t_yon_hab @ TELEKOM | SERVIS_YONETICI | 477 | 202 | 140 | 130 | 5 | 0 | 0 |
| t_sef_hab @ TELEKOM | SERVIS_SEF | 477 | 194 | 154 | 124 | 5 | 0 | 2 |
| t_ops_guv @ ELEKTRONIK | SERVIS_OPERASYON | 439 | 64 | 309 | 61 | 5 | 0 | 0 |
| t_tek_guv1 @ ELEKTRONIK | SERVIS_TEKNISYEN | 439 | 54 | 325 | 56 | 4 | 0 | 0 |
| t_sdestek_guv @ ELEKTRONIK | SATIS_DESTEK | 439 | 64 | 305 | 66 | 4 | 0 | 0 |
| t_yon_guv @ ELEKTRONIK | SERVIS_YONETICI | 439 | 202 | 138 | 94 | 5 | 0 | 0 |
| t_sef_guv @ ELEKTRONIK | SERVIS_SEF | 439 | 190 | 152 | 92 | 5 | 0 | 0 |
| t_sef_bar @ ELEKTRONIK | SERVIS_SEF | 439 | 190 | 152 | 92 | 5 | 0 | 0 |
| t_saha_guv @ ELEKTRONIK | SAHA_SORUMLUSU | 439 | 59 | 321 | 55 | 4 | 0 | 0 |
| t_atolye_guv @ ELEKTRONIK | ATOLYE | 439 | 75 | 283 | 76 | 5 | 0 | 0 |
| t_depo_guv @ ELEKTRONIK | SERVIS_DEPO | 439 | 82 | 304 | 49 | 4 | 0 | 0 |
| t_satis_guv @ ELEKTRONIK | SATIS | 439 | 19 | 404 | 16 | 0 | 0 | 0 |
| t_finans_uzm @ ELEKTRONIK | MUHASEBE_DESTEK | 439 | 30 | 392 | 17 | 0 | 0 | 0 |
| t_mob_depo @ MOBILITE | DEPO | 559 | 68 | 482 | 9 | 0 | 0 | 2 |
| t_yonetim @ TELEKOM | YONETIM | 477 | 159 | 187 | 124 | 7 | 0 | 0 |
| t_yonetim @ ELEKTRONIK | YONETIM | 439 | 157 | 185 | 90 | 7 | 0 | 0 |
| t_finans_yon @ TELEKOM | FINANS_YONETICI | 477 | 118 | 259 | 91 | 9 | 0 | 0 |
| t_finans_yon @ ELEKTRONIK | FINANS_YONETICI | 439 | 116 | 245 | 69 | 9 | 0 | 0 |
| t_yonetim @ MOBILITE | YONETIM | 559 | 226 | 129 | 197 | 7 | 0 | 0 |
| t_finans_yon @ MOBILITE | FINANS_YONETICI | 559 | 176 | 228 | 146 | 9 | 0 | 0 |

Yol parametreli 87 uç × kullanıcı grubu (hücre = görülen durum kodları; `200!` = karşı şirket verisi içeren 200).
Mobilite sütunları (t_mob_depo, *@MOB) mobilite uçlarında kendi şirketidir; teknik servis uçlarında 403/404 beklenir.
`/api/hesaplar/*`, `/api/lokasyonlar/*` müşteri kartı ortaktır (karar §1) — içerik taramasında karşı şirket işi/ekipmanı/sözleşmesi yok.

| Uç (id'li GET) | TELEKOM→ELK (ops,tek,sdestek,yon,sef _hab) | ELK→TELEKOM (11 kullanıcı _guv/_bar/finans_uzm) | t_mob_depo (MOB→TS) | t_yonetim@TEL/ELK | t_finans_yon@TEL/ELK | yonetim+finans@MOB→TS |
|---|---|---|---|---|---|---|
| `/api/roller/{kod}/yetkiler` | 403 | 403 | 403 | 403 | 403 | 403 |
| `/api/kullanicilar/{user_id}/yetkiler` | 403 | 403 | 403 | 403 | 403 | 403 |
| `/api/kullanicilar/{user_id}/izinler` | 403 | 403 | 403 | 403 | 403 | 403 |
| `/api/vekalet/{personel_id}` | 403/404 | 403/404 | 403 | 403 | 403 | 403 |
| `/api/hesaplar/{hesap_id}` | 200/403 | 200/403/404 | 200 | 200 | 200 | 200 |
| `/api/hesaplar/{hesap_id}/kart` | 200/403 | 200/403/404 | 200 | 200 | 200 | 200 |
| `/api/hesaplar/{hesap_id}/mukerrer-adaylari` | 200/403 | 200/403/404 | 200 | 200 | 200 | 200 |
| `/api/urunler/{urun_id}` | 404 | 404 | 404 | 404 | 404 | 404 |
| `/api/cihazlar/{kimlik}` | 403 | 403 | 404 | 403 | 403 | 404 |
| `/api/hatlar/{hat_id}/paket-gecmisi` | 403 | 403 | 200 | 403 | 403 | 200/403 |
| `/api/is-emirleri/cihaz/{device_id}/gecmis` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/is-emirleri/arac/{vehicle_id}/gecmis` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/is-emirleri/cihaz/{device_id}/tarihinde` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/hakedis/panel/{donem}` | 403 | 403 | 403 | 403 | 403 | 200 |
| `/api/hakedis/{dokum_id}` | 403 | 403 | 403 | 403 | 403 | 404 |
| `/api/hakedis/{dokum_id}/pdf` | 403 | 403 | 403 | 403 | 403 | 404 |
| `/api/hakedis/donem/{period}/excel` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/stok/cihaz/{device_id}/konum-gecmisi` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/stok/cihaz/{device_id}/tarihinde` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/teklifler/{teklif_id}` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teklifler/{teklif_id}/pdf` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teklifler/{teklif_id}/gecmis` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teklifler/{teklif_id}/gonderimler` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/siparisler/{siparis_id}` | 403 | 403 | 403 | 403 | 403 | 404 |
| `/api/siparisler/{siparis_id}/uygun-cihazlar` | 403 | 403 | 403 | 403 | 403 | 404 |
| `/api/abonelikler/mrr/{donem}` | 403 | 403 | 403 | 403 | 403 | 200 |
| `/api/abonelikler/tahakkuk/{donem}` | 403 | 403 | 403 | 403 | 403 | 200 |
| `/api/abonelikler/tahakkuk/{donem}/xlsx` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/abonelikler/{abonelik_id}` | 403 | 403 | 403 | 403 | 403 | 404 |
| `/api/toplu-zam/{parti_id}` | 403 | 403 | 403 | 403 | 403 | 404 |
| `/api/tahsilat/bakiye/{hesap_id}` | 403 | 403 | 403 | 403 | 403 | 200 |
| `/api/ice-aktarma/profiller/{kod}/sablon.xlsx` | 404 | 404 | 404 | 404 | 404 | 404 |
| `/api/ice-aktarma/partiler/{parti_id}` | 404 | 404 | 404 | 404 | 404 | 404 |
| `/api/ice-aktarma/partiler/{parti_id}/karantina.xlsx` | 404 | 404 | 404 | 404 | 404 | 404 |
| `/api/rma/{rma_id}` | 403 | 403 | 403 | 403 | 403 | 403/404 |
| `/api/satinalma/siparisler/{siparis_id}` | 403 | 403 | 404 | 403 | 403 | 404 |
| `/api/satinalma/siparisler/{siparis_id}/mal-kabuller` | 403 | 403 | 404 | 403 | 403 | 404 |
| `/api/satinalma/ithalat/{dosya_id}/cihazlar` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/raporlar/cihaz-omur-boyu/{device_id}` | 403 | 403 | 404 | 403 | 403 | 404 |
| `/api/raporlar/mrr/{donem}` | 403 | 403 | 200 | 403 | 403 | 200 |
| `/api/ekler/dosya/{ek_id}` | 404 | 404 | 404 | 404 | 404 | 404 |
| `/api/ekler/{entity}/{entity_id}` | 403/404 | 403/404 | 403 | 404 | 403/404 | 403/404 |
| `/api/gorevler/panolar/{board_id}/kartlar` | 200!/404 | 200/404 | 200! | 404 | 404 | 404 |
| `/api/gorevler/kayit/{entity}/{entity_id}` | 200/200! | 200 | 200/200! | 200 | 200 | 200 |
| `/api/gorevler/kartlar/{card_id}/yorumlar` | 200/404 | 200/404 | 200 | 404 | 404 | 404 |
| `/api/personel/{personel_id}` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/personel/{personel_id}/cikis-onizleme` | 403/404 | 403/404 | 403 | 403 | 403 | 403 |
| `/api/hesaplar/{hesap_id}/lokasyonlar` | 200/403 | 200/403/404 | 200 | 200 | 200 | 200 |
| `/api/lokasyonlar/{lokasyon_id}` | 200/403 | 200/403/404 | 200 | 200 | 200 | 200 |
| `/api/teknik-servis/ana-veri/musteriler/{hesap_id}/servis-karti` | 200/403 | 200/403 | 403 | 200 | 200 | 200 |
| `/api/teknik-servis/planlama/isler/{is_id}/plan` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/planlama/isler/{is_id}/plan-gecmisi` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/planlama/isler/{is_id}/saha-onerisi` | 403/404 | 403/404 | 403 | 403 | 403 | 403 |
| `/api/teknik-servis/ekipman/{ekipman_id}` | 403/404 | — | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/ekipman/{ekipman_id}/birlestirme-engelleri` | 403/404 | — | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/ekipman/{ekipman_id}/gecmis` | 403/404 | — | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/ekipman/{ekipman_id}/degisiklikler` | 403/404 | — | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/bakim/sozlesmeler/{id}` | 403/404 | — | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/bakim/sozlesmeler/{id}/eslestirme` | 403/404 | — | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/bakim/sozlesmeler/{sozlesme_id}/donemler` | 403/404 | — | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/bakim/sozlesmeler/{sozlesme_id}/donemler/{donem_id}/cihazlar` | 403/404 | — | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/bakim/formlar/{so_id}` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/bakim/ekipman/{ekipman_id}/bakim-gecmisi` | 404 | — | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{is_id}/zaman` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/benim-islerim/{is_id}` | 403/404 | 403/404 | 403 | 403 | 403 | 403 |
| `/api/teknik-servis/operasyon/isler/{so_id}/sla` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/atolye/{so_id}` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/atolye/{so_id}/kabul-fisi.pdf` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/atolye/{so_id}/teslim-tutanagi.pdf` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/parca/isler/{so_id}/parcalar` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/maliyet/isler/{so_id}` | 403 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/maliyet/isler/{so_id}/gecmis` | 403 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/kiralama/envanter/{kiralik_id}` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/kiralama/envanter/{kiralik_id}/hareketler` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/kiralama/{kiralama_id}` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/kiralama/{kiralama_id}/gecmis` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/kiralama/{kiralama_id}/tutanak.pdf` | 403/404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/egitim/kisiler/{personel_id}/gozlemler/{gozlem_id}` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/egitim/kisiler/{personel_id}/yetkinlik-gecmisi` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/egitim/kisiler/{personel_id}/kart` | 403/404 | 403/404 | 403 | 404 | 403 | 403/404 |
| `/api/teknik-servis/isler/{so_id}` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{so_id}/beklemeler` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{so_id}/gecmis` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{so_id}/ekip` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{so_id}/onaylar` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{so_id}/servis-formu.pdf` | 404 | 403/404 | 403 | 404 | 404 | 404 |
| `/api/teknik-servis/isler/{so_id}/cihaz-eslesmeleri` | 404 | 403/404 | 403 | 404 | 404 | 404 |

### 2.2 Senaryo sonuçları (özet)

- **Çapraz şirket okuma:** 87 id'li uçta karşı şirket kimliğiyle bütün kullanıcılarda 403/404 (S1 hariç). Liste uçları ve
  `?birim=<karşı birim>` denemeleri boş/403; sayaç uçları (ana panel 8 KPI, servis paneli, operasyon özeti, planlama KPI,
  rapor özeti) karşı birimle 403 "Bu birimin panelini görme yetkiniz yok"; `sef_id`/`personel_id`/`lokasyon_id` süzgecine
  karşı şirket kimliği verilince 0. Excel'lerin içi açılarak tarandı: karşı şirket satırı yok. PDF (servis formu, ziyaret formu,
  kabul fişi, teslim tutanağı, kiralama tutanağı): 404. Bildirim/uyarı (`/api/raporlar/uyarilar`, operasyon bildirimleri):
  şirkete göre süzülüyor. Personel: S3 dışında karşı şirket teknisyeni görünmüyor (`/api/personel/{id}` 404, `atanabilir?birim=GUVENLIK` 404).
  Denetim izi `/api/denetim` yalnız yöneticide (diğerlerine 403).
- **Arama / Ctrl+K:** karşı şirketin tam iş no'su, seri no'su (XR-001…), sözleşme no'su ve test serisi `SIZINTI-TEST-HAB` ile
  boş; `SRV` aramasında yalnız etkin şirketin işleri. t_mob_depo'ya teknik servis sonucu dönmüyor.
- **Şirket seçimi:** üye olunmayan şirket (ELEKTRONIK/MOBİLİTE/TELEKOM, `telekom`, `TELEKOM `, `YOK`) → 403 `SIRKET_DISI`,
  etkin şirket değişmiyor. t_yonetim / t_finans_yon: TELEKOM 16 iş (yalnız HABERLESME), ELEKTRONİK 118 (GUVENLIK 115 + BARIYER 3),
  MOBİLİTE 0; ekipman 0/158/0, sözleşme 0/2/0; Ana Panel "Açık iş" 16/100/0 ve servis paneli aynı — sayaç listeyle tutarlı.
  **İki oturum:** aynı kullanıcı oturum-1 TELEKOM, oturum-2 ELEKTRONİK→MOBİLİTE; oturum-1 TELEKOM'da kaldı (birbirini etkilemiyor).
  Yeni girişte varsayılan: birimsiz t_yonetim → MOBİLİTE (karar §1 ile uyumlu).
- **Yazma uçları:** karşı birimle iş açma (t_ops_hab, t_yon_hab [TUMU], t_ops_guv; uzaktan-çözüldü dahil) → 403
  `SIRKET_DISI_BIRIM` anlamlı mesajla; karşı şirket ekipmanından iş açma 404; iş birimi taşıma → 400 "Servis işinin birimi
  değiştirilemez"; ekipman birimi taşıma ve karşı birimde ekipman açma → 404; karşı şirket işine not/PATCH/iptal/plan/ek/toplu
  atama/ilişki → 404 (izni yoksa 403); karşı şirket teknisyenini atama → 409 "… bu işin biriminde değil".
- **Mobilite kapısı:** TELEKOM/ELEKTRONİK etkinken cihaz, hat, araç, iş emri, hak ediş, stok, sipariş, abonelik, tarife,
  tahsilat, RMA, satın alma, mobilite raporları, toplu zam → 403 `SIRKET_DISI` (t_yonetim, t_finans_yon, t_depo_guv, t_sdestek_hab);
  MOBİLİTE'de 200. Arayüz menüsünde Mobilite grubu gizli (t_ops_hab, t_ops_guv); URL ile açılınca S4.
- **Rol yetkisi:** maliyet.gor olmayan 12 rolde (teknisyen, operasyon, saha sorumlusu, satış destek, şef, TS müdürü, atölye,
  servis depo, satış, mobilite depo) hiçbir yanıtta dolu maliyet/fiyat alanı yok; bakım sözleşmesinde `fee_per_visit`,
  `contract_total`, `legacy_fee_text` anahtarları maliyet.gor'suz yanıtta **hiç yok**, t_finans_yon'da var (yerelde değerler boş).
  YONETIM (t_yonetim) iş/ekipman/hesap/görev panosu açma, not, PATCH, iptal, ek silme → 403 (rolde hiç yazma izni yok).
  Teknisyen: atanmamış t_tek_guv2 ve TELEKOM'lu t_tek_hab, t_tek_guv1'e atanmış işe sonuç giremiyor/zaman başlatamıyor/ayrıntı
  açamıyor → 404.
- **Ortak müşteri kartı:** 828 istekte karşı şirketin işi, ekipmanı, sözleşmesi, açık iş sayısı ya da lokasyon açık iş sayısı
  görünmedi (servis kartı `servis_isleri`, `sozlesmeler`, `kiralamalar` ve sayılar etkin şirkete göre süzülüyor).

## 3. İyi çalışanlar

- Birim → şirket kesişimi tek yerde (`kapsam.py`) ve fail-closed; TUMU kapsamlı yönetici/finans da yalnız etkin şirketi görüyor.
- Tek kayıt yardımcıları liste koşulunun aynısını kullanıyor: id ile doğrudan erişim 87 uçta tutarlı 404.
- `?birim=<karşı birim>` ile süzgeç zorlaması: ya boş ya 403 — hiçbir uçta karşı birimin verisi açılmadı.
- Excel ve PDF dışa aktarmaları listeyle aynı kapsamda; sayaçlar listeyle tutarlı (sayı = liste).
- Şirket seçici sunucu tarafında üyelik kontrolü yapıyor; etkin şirket oturum başına (iki tarayıcı bağımsız); değişim denetim izine yazılıyor.
- Yazma uçlarında şirket dışı birim için makine okunur `SIRKET_DISI_BIRIM` + anlaşılır Türkçe mesaj; birim taşıma kapalı.
- Mobilite kapısı yönlendirici düzeyinde ve bütün mobilite uçlarında tutarlı 403 `SIRKET_DISI`; arama mobilite arayıcılarını da kapatıyor.
- Maliyet alanları rol yetkisi yoksa anahtar düzeyinde çıkarılıyor (null değil, hiç yok).
- Mükerrer kontrolleri karşı kaydın numarasını/kimliğini vermiyor (yalnız varlık bayrağı — S5).
- Tarama boyunca 10.723 istekte hiç 5xx yok.
