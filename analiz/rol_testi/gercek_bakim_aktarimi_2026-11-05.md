# Gerçek bakım listesi, güncel talepler ve onay zinciri (2026-11-05)

Ortam: yerel deneme (`denge-erp-deneme`, 8df9107). Adres: http://127.0.0.1:5173. Canlıya dokunulmadı.

Kaynaklar:
- BAKIMLAR_2025-2026.xlsx (90 satır);
- Güvenlik talep takip listesi (35 açık satır);
- X-RAY KÜTÜK;
- organizasyon şeması.

Kararlar ve gerekçeleri: `analiz/soru_formu/KARARLAR_2026-10-28.md` §9.

## 1. Kullanıcılar (organizasyon şeması)

| Kişi | Rol | Birim / şirket | Yönetici |
|---|---|---|---|
| Sunay Kılıç | Teknik Servis Müdürü (`SERVIS_YONETICI`; son onay `servis.son_onay`) | Güvenlik + Haberleşme / ELEKTRONİK + TELEKOM | — |
| Hakan Erdal | Güvenlik Sistemleri Saha ve Operasyon Takım Lideri (`SERVIS_SEF`) | Güvenlik / ELEKTRONİK | Sunay Kılıç |
| Ertuğrul Çakır | Haberleşme Sistemleri Takım Lideri (`SERVIS_SEF`) | Haberleşme / TELEKOM | Sunay Kılıç |
| Umut Can Yıldırım | Satış Destek (bakım/servis teklifleri) | Güvenlik / ELEKTRONİK | — |
| 11 Güvenlik teknisyeni (2 stajyer) | `SERVIS_TEKNISYEN` | Güvenlik | Hakan Erdal |
| 6 Haberleşme teknisyeni | `SERVIS_TEKNISYEN` | Haberleşme | Ertuğrul Çakır |
| Ebrar Yayla Alınkarı | Teknik Servis Operasyon Uzmanı | Haberleşme | Ertuğrul Çakır |

Hesap ve rol kararları:
- Nazım Köse adına hesap açılmadı.
- Çağatay Koruç'un Haberleşme teknik servis yönetimi yerinde Sunay Kılıç yetkili.

Kullanıcı adları `ad.soyad` biçiminde (örnek: `sunay.kilic`). Geçici parolalar `.yerel_gizli/deneme_kullanicilari_2026-11-05.txt` dosyasında; ilk girişte değiştirilir.

## 2. Akış (uçtan uca denendi, 15/15 adım beklendiği gibi)

1. Satış destek servis teklifi hazırlar ve "Kabul edilince açılacak iş" türünü seçer. Kendi teklifini onaylayamaz (403).
2. Müdür iç onayı verir. Teklif müşteriye gönderilir, müşteri kabul eder.
3. İş teknik servise `PLANLAMADA` durumunda düşer (SRV-202611-000816) ve teklife bağlanır.
4. Müdür işi ekip liderine verir (ŞEF tayini).
5. Ekip lideri Servis Planlama'da planlar ve teknisyene tayin eder.
6. Teknisyen işi kendi listesinde görür, servis formunu (sonucu) girer ve işi tamamlar.
7. Ekip lideri onaysız kapatmayı dener → 409. Onay verir. Yine kapatmayı dener → 403 (son onay müdürde).
8. Müdür son onayı verir ve iş kapanır.

Planlı bakım işinde 6. adımda servis formu yerine bakım formu doldurulur ve "Formu Tamamla" ile iş tamamlanır; onay ve kapanış aynıdır.

İki aşamalı kapanış `servis_kapanis_onay_zinciri` ayarıyla çalışır. Deneme ortamında açık, kod varsayılanı kapalı; canlıya geçişte açılmalı.

Not: Ayar açılmadan önceki ilk denemede SRV-202611-000815 şef tarafından eski tek adımlı kurala göre kapatıldı. Bu bir deneme kaydıdır.

## 3. Bakım listesi

| Sonuç | Adet |
|---|---|
| Aktif sözleşme (karar tarihi = başlangıç, yıllık adet, yapılan adet) | 57. Önceki örnek aktarımın 5 sözleşmesi yeni tarihlere göre güncellendi. |
| Taslak (süresi dolmuş, 2026-2027 bedeli yok) | 31 |
| Açılmadı | Ziraat Bankası (cihaz adedi yok); Kazancı Holdİng / Koni İnşaat satırı listede iki kez geçiyor, bir kez alındı. |
| Açılan cihaz iş emri (PB) | Her aktif sözleşmede ilk açık dönemin bütün cihazlarına cihaz başına 1. Güvenlik'te şu an 469 açık PB var. |

Özel satırlar:
- **Karşıyaka Hilltown:** son sütunda 2026-2027 bedeli var. 01.04.2025-31.03.2026 sözleşmesi 01.04.2026-31.03.2027 olarak yenilendi.
- **İstanbul Darphane:** 3 ayda bir, çeyreğin ilk 10 günü. Sabit aylar Ocak, Nisan, Temmuz ve Ekim.
- **Kartal Belediyesi:** bakım ayları 5 ve 11.
- **Eren Holding:** bakım ayları Mart ve Eylül.
- **Sanko Holding:** "21 Eylül'de bakım istiyor" notuna göre karar tarihi 21.09.2026, yılda 1.
- **Başlangıcı ve bitişi aynı gün yazılan satırlar** (Darphane, MNG Kemerburgaz) bir yıllık sayıldı.

Kalan dönemler "Planlı Bakım › Bakım İş Emirleri" sekmesinde açılmayı bekliyor: 425 cihaz iş emri, 40 gecikmiş dönem. Yönetici bunları seçip "İş emirlerini aç" ile açar.

Taslak kalan sözleşmeler (yeni karar tarihi verilince aktifleşir): Rami Kütüphanesi, Axis Eyüp, Axis Kağıthane, İSKİ, Halkbank, Küçükyalı Ofispark, Tüdaş, Atatürk Kültür Merkezi, Kartal Belediyesi (2025 satırı), Highway AVM, Optima Avrupa Yakası, Partsec, Metro City A Blok, Anpa Gross, Gamak Makina, Isparta Şehir Hastanesi, TCDD Haydarpaşa, Edirne Göç İdaresi, ZSR Patlayıcı, Tekstilkent Koza Plaza, Skyland, Özdilek Eskişehir, ISS Tesis Yönetim, Mega AVM, MNG Kargo, Defacto, İzmirpark AVM, KİPA AVM, Güllük Mandalya, Özdilek Kocaeli, Eskidji Çarşı.

## 4. Güncel talepler (139 iş emri)

Yetkili kişi sütunları boş olduğu için işler "geçiş kaydı" olarak açıldı (KARARLAR §9.8). Talep tarihi, listedeki durum ve planlanan tarih açıklamaya yazıldı.

Türlere göre:
- **Kurulum, 117 iş:** satılan cihazlar, cihaz başına bir iş. Örnekler: Adana Raylı Sistemler 48, Metro İstanbul 33, İhlas ve Migros 6'şar, MKE 4.
- **Bakım, 16 iş:** İSKİ 6, Rönesans Ankara 5, Pimser/Baykar 3, KİPA Keşan 1, Espark (kalibrasyon) 1.
- **Arıza, 5 iş:** Vakıf Katılım klavye, Kartal Anpa Gross, Özdilek Levent, İzmir Optimum, Arasta Park.
- **Taşıma, 1 iş:** Çağan Elektronik.

Atlananlar:
- Girne, Eren Enerji, Esan Balya ve KİPA Derince: önceki aktarımda açılmıştı.
- Palladium Tower bakımı: aktif sözleşmenin PB iş emirleri var.
- Büyükçekmece Adliyesi: talep detayı boş.

## 5. Veri kalitesi: düzeltilmesi gerekenler

- **İl kaynakta yok, İstanbul varsayıldı (39 tesis).** Tesis notuna "doğrulayın" yazıldı. Tesisler: Rami Kütüphanesi, Kazancı Holding (2), Metro Properties, Oyak, Sodexo, Albil, Segatech, İşmer, Coca Cola, Halkbank, Tüdaş, AKM, USO Center, Highway, Akyaka, Optima, Partsec, Metro City, Anpa, Gamak, Eren Holding, Meteksan, ZSR, Tekstilkent, ISS, Mega AVM, MNG Kargo, MNG Kemerburgaz, Defacto, İzmirpark (İzmir olmalı), KİPA, Kozzy, Eskidji, Vakıf Katılım, Eczacıbaşı, Çamsan Park, Sanko, PAM Mülk.
- **Seri no:** yalnız 7 tesiste kütükten alındı. Tesisler: İzmir Optimum, Gamak, Isparta Şehir Hastanesi, Defacto, Kozzy, İzmir Ticaret Odası, Çiftçi Tower. Diğer cihazların notunda "iş emri kapanırken sahada girilecek" yazıyor.
- **Mükerrer adayı:** Akyaka AVM için iki sözleşme var. BAKIM-0001 (Akyaka AVM Yönetimi) önceden vardı; BAKIM-0066 (Akasya Alçı Maden) listeden açıldı. Hesap birleştirme ile tekilleştirilmeli.
- **Hilltown AVM:** önceki örnek aktarımda il İzmir girilmişti; doğrulanmalı.
- **Ziraat Bankası:** cihaz adedi verilirse sözleşme açılır.
