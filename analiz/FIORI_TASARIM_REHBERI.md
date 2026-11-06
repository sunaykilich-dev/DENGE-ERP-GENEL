# SAP Fiori Görünüm Rehberi (kullanıcı fotoğraflarından)

Kaynak ekran görüntüleri: `kaynak/fiori_ornekleri/*.jpeg` (İGA Havalimanı SAP Fiori Launchpad — "Arıza Bildirim", "Bakım Bildirim", "Başlangıç sayfası"). Her ajan bu 10 fotoğrafı **kendisi açıp bakmalı** (Read aracı resim gösterir).

Hedef: Teknik servis ekranları ve genel kabuk (shell) SAP Fiori (Quartz Light / Horizon) görünümünde olsun; "atama" dili yerine SAP'deki gibi **"tayin"** dili kullanılsın.

## 1. Kabuk (Shell Bar) — tüm sayfalarda
- Beyaz/çok açık gri üst çubuk, ince alt kenar çizgisi; yükseklik ~48–56 px.
- Sol: geri ok `<` (tarayıcı geçmişi), şirket logosu (mevcut Denge logosu, küçük kare), yanında **uygulama başlığı + ▾** ("Servis İşleri ▾"). Başlığa tıklayınca açılan menü: bulunulan grubun diğer uygulamaları + "Başlangıç sayfası".
- Orta: yuvarlatılmış (pill) arama kutusu, yer tutucu **"Arama yeri: "Uygulamalar""**, sağda büyüteç. Mevcut genel arama (GlobalSearch) buraya taşınır.
- Sağ: bildirim zili (mevcut UyariZili) ve kullanıcı **baş harfleri dairesi** (ör. "VK"), tıklayınca profil/çıkış/parola değiştir menüsü.
- **Sol kenar menüsü kaldırılır.** Gezinme Başlangıç sayfası (launchpad) ve başlık açılır menüsüyle yapılır. (375 px'te arama ikonlaşır.)

## 2. Başlangıç sayfası (Launchpad) — `/` ve `/baslangic`
- Kabukta başlık **"Başlangıç sayfası ▾"**.
- Altında **sekme çubuğu** (grup adları, seçili olan altı çizili mavi): ör. "Teknik Servis Uygulamaları", "Bakım", "Operasyon", "Depo ve Kiralama", "İnsan Kaynakları", "Raporlar", "Mobilite" (mevcut mobilite ekranları: Hesaplar, Cihazlar, Hatlar, Araçlar, İş Emirleri, Hak Ediş, Teklifler, Siparişler, Abonelikler, Tahsilat, Stok, RMA, Satın Alma, Görevler, Raporlar, Ayarlar…). Sekmeye tıklamak ilgili grup başlığına kaydırır (Fiori "anchor bar").
- Her grup: büyük başlık ("Onay İşlemleri" gibi, 20 px, koyu gri) + **kutucuklar (tile)**.
- Kutucuk: ~176×176 px (mobilde 148), beyaz (ya da çok açık), 8–12 px köşe, hafif gölge, üzerine gelince gölge artar/mavi kenar. Sol üstte **kalın başlık** (ör. "Arıza Bildirim"), altında isteğe bağlı küçük gri alt başlık; sol altta **çizgi ikon** (AntD outlined ikon, 28–32 px, Fiori mavisi/gri); ikonun yanında varsa **büyük KPI sayısı** (ör. "0", 36 px ince). KPI'lı kutucuklar: açık servis işleri, bana tayin edilenler, geciken, bekleyen onay, plan bekleyen PB vb. (mevcut panel/uyarı uçlarından).
- Yalnız kullanıcının yetkisi olan kutucuklar görünür (mevcut `MENU` izinleri).

## 3. Liste raporu (List Report) — Servis İşleri, Planlı Bakım ve diğer liste ekranları
Fotoğraf 0–6 ve 9'daki düzen birebir:
1. **Kategori ikon şeridi:** Yatayda dairesel ikon düğmeler (~48 px daire, 2 px kenar, içinde anahtar/araç ikonu), altında BÜYÜK HARF kısa etiket (ARIZA, İSTEK, BİLGİ…). Renkler: arıza/plansız türleri **kırmızı** (#bb0000 / Horizon #d20a0a) dış çizgi; planlı türleri **yeşil** (#107e3e) dış çizgi. Seçili olan **dolu** (daire içi renkli, ikon beyaz) ve altında 3 px renkli çizgi. Bizdeki karşılık: Servis İşleri için `SERVIS_TURLERI` → ARIZA, PLANSIZ BAKIM, DESTEK, KURULUM, KEŞİF, TOPLAMA, DEMONTAJ, ATÖLYE (PB ayrı ekran). Planlı Bakım ekranı için: PLANSIZ (kırmızı) ve PLANLI (yeşil) dönem türleri ya da sözleşme/dönem durumları. "TÜMÜ" de bulunsun.
2. **"Kayıt Sayısı: N"** (kalın, 14 px) — sunucunun `X-Toplam-Kayit` değeri.
3. **Durum filtre çubuğu:** Tek satır, ince kenarlı grup: [👤 bana tayin edilenler] [⟳ yenile] **YENİ  TAYİN  İŞLEM  ASKIDA  TAMAMLANDI  YAPILAMADI** [filtre ikonu ▽+ (gelişmiş süzgeç paneli açar)]. Metin düğmeler BÜYÜK HARF, Fiori mavisi (#0a6ed1), seçili olan altı çizili/koyu. Durum grupları servis durum kataloğundan eşlenir (`DURUM_GRUPLARI`).
4. **Tablo:**
   - İlk sütun **radyo düğmesi** (tek satır seçimi); seçili satır açık mavi zemin + alt mavi çizgi.
   - Başlıklar: ortalı, gri, 13 px, iki satıra kırılabilir ("Bildirim\nTarihi").
   - **Durum** sütunu: mavi, kalın, BÜYÜK HARF, tıklanabilir (ör. "YENİ KAYIT", "TAYİN EDİLDİ", "İŞLEM-BAŞLADI", "İŞLEM-ARA VERİLDİ", "ASKIDA-…").
   - **No** sütunu: sarı vurgulu rozet (#ffeb3b benzeri açık sarı zemin, koyu yazı, kalın) — ör. "SRV-202610-000019".
   - Tarih (GG/AA/YYYY), Saat (SS:DD:ss) ayrı sütunlar.
   - **Açıklama/Konu:** mavi, kalın, BÜYÜK HARF, tek satır kesilir (…); tıklayınca detay.
   - Ekipman, Mahal/Lokasyon (küçük, ortalı, BÜYÜK HARF, 2–3 satıra kırılır), Sistem (birim/ekipman türü), **Personel** (küçük kişi ikonlu kare düğme → tayin edilen ekip açılır penceresi), Bildiren Kişi/Tel (küçük gri).
   - Satır yüksekliği sıkışık (~44 px), zebra yok, ince satır çizgileri; boşsa ortada "Veri yok".
5. **Alt eylem çubuğu (footer toolbar):** sayfa altına yapışık beyaz çubuk; metin düğmeler + ikonlar: **Liste**, **Saat Aç** (seçili iş için zaman sayacını başlat), **Saat Kapa** (sayacı bitir), **Tayin Et** (ikon), Sil/İptal (ikon), Düzenle (ikon), **PDF** (servis formu). Seçim yoksa pasif.
6. Detay: satır tıklanınca mevcut Drawer yerine Fiori "Object Page" hissi veren tam yükseklikte sağ panel veya sayfa: üstte büyük başlık + durum rozeti, bölüm sekmeleri (Genel, Tayin, Zaman, Parçalar, Geçmiş, Ekler…).

## 4. Renk ve tipografi (Fiori Quartz Light)
- Arka plan #f7f7f7 (sayfa), içerik kutuları #ffffff; kenar #e5e5e5.
- Ana renk (bağlantı/aksiyon) **#0a6ed1**; vurgulu metin mavi #0854a0.
- Olumsuz/kırmızı #bb0000, olumlu/yeşil #107e3e, uyarı/turuncu #e9730c, bilgi #0a6ed1.
- Yazı: `"72", "72full", Arial, Helvetica, sans-serif` (72 yoksa Arial), temel 14 px; başlıklar 16–20 px.
- Köşe yuvarlaklığı: kutucuk 8–12 px, düğme 4 px (Horizon: 8 px), arama 18 px (pill).
- AntD tema token'ları (`theme.ts` / ConfigProvider) bu değerlere ayarlanır; mobilite ekranları da otomatik yeni temayı alır.

## 5. "Atama" → "Tayin" terim değişikliği (yalnız kullanıcıya görünen metin)
| Eski | Yeni |
|---|---|
| Ata / Atama yap | **Tayin Et** |
| Atandı / Atanmış | **Tayin Edildi** |
| Atanmamış | **Tayin Edilmemiş** |
| Atama (isim) | **Tayin** |
| Toplu Atama | **Toplu Tayin** |
| Atama değiştir / Yeniden ata | **Tayini Değiştir / Yeniden Tayin Et** |
| Atanabilir kişiler | **Tayin edilebilir personel** |
| Atanan / Atanan ekip | **Tayin edilen / Tayin edilen ekip** |
| Atamayı kaldır | **Tayini Kaldır** |
| "… atanamaz" (hata) | "… tayin edilemez" |
| "yetkinlik uyarısıyla atandı" | "yetkinlik uyarısıyla tayin edildi" |
| Bana atananlar | **Bana Tayin Edilenler** |
| Vekil atama (yetki devri) | **Vekil Tayini** |

Kurallar: **Kod sabitleri, API alan adları, izin kodları, olay türü kodları (ör. `ATAMA`), tablo/kolon adları DEĞİŞMEZ**; yalnız etiketler, düğmeler, başlıklar, Türkçe hata/uyarı mesajları, olay özet metinleri, Excel sütun başlıkları, kılavuz ve PDF metni değişir. Mobilite modülündeki "montaj noktası ataması" gibi canlı mobilite metinlerine de aynı dil uygulanabilir ama hak ediş/altın kayıt testlerini etkileyen dışa aktarım sütun adları değişmez. Testlerde değişen mesajlara bağlı iddialar güncellenir.

Durum etiketleri (yalnız gösterim, kod aynı kalır) SAP diline yaklaştırılır: MUSTERI_TALEBI → "YENİ KAYIT", tayin bekleyen/planlanacak → "TAYİN BEKLİYOR", ekip tayin edilmiş → "TAYİN EDİLDİ", sahada/işlemde → "İŞLEM-BAŞLADI", beklemede → "İŞLEM-ARA VERİLDİ" ya da "ASKIDA-<neden>", tamamlandı → "TAMAMLANDI", çözülemedi/iptal → "YAPILAMADI". Kesin eşleme `SERVIS_DURUMLARI` kataloğuna bakılarak yapılır ve tek bir ön yüz sözlüğünde (`frontend/src/fiori/etiketler.ts`) tutulur.
