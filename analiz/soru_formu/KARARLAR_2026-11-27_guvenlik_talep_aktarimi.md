# Kararlar 2026-11-27: Güvenlik Talep Takip Excel'inin ERP'ye aktarımı

Kullanıcı isteği: Güvenlik Talep Takip Excel'indeki geçmiş ve güncel işler
ERP'de açılsın. Tamamlananlar TAMAMLANDI olsun, tamamlanmayanlar planlamada
beklesin, tamamlananların sonucu ve personeli girilsin. Talep tarihi olmayan
işe planlanan tarih yazılsın.

Uygulama: `servis_talep` içe aktarma profili (İçe Aktarma › Servis Talepleri).
Bu sürüm, 2026-11-23 sürümünün kurallarının yerine geçer. Dal:
`guvenlik-talep-aktarim`.

| Konu | Karar | Gerekçe |
|---|---|---|
| Tamamlandı | KAPATILDI (düzeltme, aynı gün); kapanış anı = planlanan tarih. "Not / Açıklama" sütunu sonuç olur (YERINDE, COZULDU). Not yoksa sabit metin yazılır. | Kullanıcı: "iş emirlerini açmanı ve kapatmanı istedim". Geçmiş iş onaya düşmez; Kapanan İşler'de görünür. |
| Tamamlanmayan | Beklemede, Planlandı, Devam ediyor, Ertelendi ve boş durum PLANLAMADA olur. | İstek: "planlamada bekle". Bekleme kaydı açılmaz. |
| Ertelendi tekrarı | "Ertelendi" satırı, aynı işin sonraki ilk satırına katılır; tek iş açılır. Aynı iş: müşterinin ilk sözcüğü aynı ve detay en az %60 benzer. Durum, plan, sonuç ve ekip son satırdan; talep tarihi ilk satırdan. Erteleme tarihleri ve nedenleri açıklamaya yazılır. Sonrası olmayan erteleme tek başına PLANLAMADA açılır. | Kullanıcı: "ertelendi yazan işleri ayrı ayrı açma tek olsun". |
| İptal edildi | IPTAL | İptal edilmiş iş planlamaya dönmez. |
| Personel | Kayıtlı kullanıcıya tayin edilir. İlk teknisyen sorumlu olur. Ayraçsız yazılmış adlar ve küçük yazım hataları da eşlenir. | İstek: "personellerde gir". |
| Eşleşmeyen ad | Uyarı verilir ve ad açıklamada kalır. Kişi açılmaz. | Uydurma tayin olmaz. Hesap açmak ayrı karardır. |
| Benzer ad | Eşleşme için en az bir sözcük birebir tutmalı, diğerinde 1–2 harf fark olabilir. | Böylece "NURİ DEMİR" Onur Demir'e bağlanmaz. |
| Talep tarihi | Boşsa planlanan tarih kullanılır. Yetkili sütununa tarih yazılmışsa o tarih talep tarihidir. İkisi de yoksa aktarma anı alınır. | İstek. Dosyada tarih Yetkili sütununa kaymış satırlar var. |
| Tamamlanma anı | Planlanan tarih | Excel'de başka bitiş tarihi yok. |
| Araç | Plaka biçimindeyse işin plakası olur. "HAVA YOLU" gibi değerler açıklamaya yazılır. | Plaka alanı 2026-11-25'te eklendi. |
| Birim | Sütun yoksa GUVENLIK | Dosya Güvenlik birimine ait. |
| Tür | Detaydan çıkarılır: kurulum veya devreye alma KURULUM, keşif KESIF, bakım PLANSIZ_BAKIM, diğerleri ARIZA. | Excel'de tür sütunu yok. |
| Müşteri veya detay boş | Yer tutucuyla açılır ve uyarı verilir. İkisi de boşsa satır reddedilir. | Geçmiş iş kaybolmasın. |

Demo sonucu (dosyanın 27.11 13:44 sürümü, 219 satır; demo içe aktarma
öncesi yedeğe döndürülüp yeniden yüklendi): 207 iş açıldı, 12 erteleme satırı
devam satırına katıldı.

- 176 KAPATILDI (176'sının sonucu ve kapanış tarihi var)
- 30 PLANLAMADA
- 1 IPTAL
- 9 işin açıklamasında erteleme geçmişi var

Eşleşmeyen adlar: ERP hesabı olmayan 7 kişi, bir soyadsız ad ve bir "taşıma
ekibi" ifadesi. Hepsi işin açıklamasında duruyor. Ad listesi kişisel veri
olduğu için depoya konmadı.

Açık konu: Demo veritabanında aynı kişi için iki hesap var. Ad sırası farklı
olduğu için 2026-11-25 personel aktarımı yeni bir hesap açmış. Eşleyici,
sözcükleri aynı olan iki hesaptan eskisini seçer. Hangi hesabın kalacağına
kullanıcı karar verir.
