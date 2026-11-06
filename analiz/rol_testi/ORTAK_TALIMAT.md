# Rol testi — ajanlar için ortak talimat (2026-11-04)

Amaç: Denge ERP'yi (teknik servis + yeni sol menü + Ana Panel + şirket ayrımı) gerçek rollerin gözünden
**kullanmak**; linkleri, kurguyu, iş akışını, yetki/onay/takibi ve şirketler arası veri sızıntısını denetlemek.
Kod DEĞİŞTİRME — yalnız kullan, ölç, raporla. Düzeltmeleri ana oturum yapacak.

## Ortam (yalnız yerel; canlı sunucuya/canlı veritabanına ASLA dokunma)
- Web arayüzü: http://127.0.0.1:5173 · API: http://127.0.0.1:8000/api (her istekte başlık `X-Requested-With: fetch`)
- Giriş: `POST /api/auth/login {"username","password"}` → çerez oturumu. `GET /api/auth/me` (rol, izinler,
  `aktif_sirket`, `sirketler`). Şirket değiştir: `PUT /api/oturum/aktif-sirket {"kod"}`; liste `GET /api/oturum/sirketler`.
- Kullanıcılar ve parolalar: `C:\Users\skilic\Documents\DengeERP_Gelistirme\.yerel_gizli\rol_test_kullanicilari.txt`
  (sekmeyle ayrılmış: kullanici, rol, parola, birimler, sirketler). Parolaları **hiçbir çıktıya, rapora, ekrana yazma**;
  betiklerin dosyadan okusun. Yönetici: `.yerel_gizli/deneme_admin.txt` (`sifre=` satırı) — yalnız gerekiyorsa.
- Şirket kodları: TELEKOM (birimler HABERLESME, POC), ELEKTRONIK (GUVENLIK, BARIYER), MOBILITE (MOBILITE, ARAC_TAKIP).
- Arayüzü tıklamak için Playwright (headless Chromium) kurulu:
  `C:\Users\skilic\AppData\Local\Temp\claude\C--Users-skilic-Documents-DengeERP-Gelistirme\c9ec6dae-0467-416d-a7b6-190f1738d382\scratchpad\rolvenv\.venv\Scripts\python.exe`
  (paketler: playwright, httpx, openpyxl). Betiklerini kendi alt klasörüne yaz:
  `...\scratchpad\rol_testi\<senin_adın>\`. Ekran görüntüleri de oraya.
- Kod (okumak için): `C:\Users\skilic\Documents\DengeERP_Gelistirme\denge-erp` — API uçları `backend/app/api/*.py`
  (teknik servis: `teknik_servis.py`, `teknik_servis_planlama.py`, `bakim.py`, `atolye.py`, `servis_*`, `ana_panel.py`),
  izinler `backend/app/permissions.py`, kapsam `backend/app/services/teknik_servis/kapsam.py`, menü
  `frontend/src/fiori/menu.ts`, sayfalar `frontend/src/pages/`. Örnek API kullanımı: `araclar/ornek_veri_yukle.py`.
- İş analizi (rol senaryoları §5, talep listesi §7): `analiz/is_analizi/IS_ANALIZI_OZETI.md`.
  Kararlar: `analiz/soru_formu/KARARLAR_2026-11-04_sirket_sayfa_rol.md`, `analiz/soru_formu/KARARLAR_2026-10-28.md`.
- Diğer ajanlar aynı veritabanında aynı anda çalışıyor: başkasının kaydını silme/iptal etme; kendi açtığın
  kayıtların konusuna rol etiketini koymana gerek yok ama raporda kayıt numaralarını yaz.

## İş kuralları (bunları ihlal eden davranış = bulgu)
- 1 cihaz = 1 PB iş emri; seri no metindir; süre kaydı yoksa "eksik" (0 değil); mola kişi-saate dahil değil.
- Maliyet/fiyat varsayılan gizli (`maliyet.gor`); her uçta sunucu tarafı izin; iyimser kilit (`version`).
- Sayı = liste: panelde/kartta gösterilen sayı, tıklanınca açılan listenin satır sayısıyla aynı olmalı.
- Şirket ayrımı: kullanıcı yalnız üyesi olduğu şirketi seçebilir; etkin şirketin birimleri dışındaki kayıtlar
  listede, sayıda, aramada, ayrıntıda (id ile doğrudan erişim dahil), dışa aktarmada, bildirimde GÖRÜNMEMELİ.
  Mobilite modülü (hesaplar/cihazlar/hatlar/hak ediş) yalnız etkin şirket MOBİLİTE iken. Müşteri kartları ortak.
- "Tayin" kelimesi yalnız teknik serviste. Gereksiz onay adımı ve karmaşık ekran istenmez.

## Rapor
`C:\Users\skilic\Documents\DengeERP_Gelistirme\analiz\rol_testi\<rapor_adı>.md` — Türkçe. Bölümler:
1. Ne yaptın (senaryo adımları, açılan/işlenen kayıt numaraları),
2. **Bulgular tablosu**: No | Önem (KRİTİK/YÜKSEK/ORTA/DÜŞÜK) | Tür (sızıntı/yetki/akış/link/UX/veri) | Ekran veya uç |
   Yeniden üretme adımı | Beklenen | Gerçekleşen | Önerilen düzeltme (dosya:satır biliyorsan yaz),
3. İyi çalışanlar (kısa).
Kişisel veri (gerçek kişi adı, telefon, plaka) ve parola rapora girmez. Müşteri FİRMA adları yazılabilir.
Son mesajında: rapor yolu + en önemli 5 bulgu (tek satır) + açtığın/işlediğin kayıt numaraları.
