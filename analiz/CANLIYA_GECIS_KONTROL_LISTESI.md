# Canlıya Geçiş Kontrol Listesi — Teknik Servis (R1…R4)

Tarih: 23.10.2026 · Hedef head: `d4a000000002` · Canlıdaki head: `b30e012dd879`
Ayrıntılı komutlar: `deploy/KURULUM.md` EK G (G.0 yükseltme, G.0.1 Dalga 4
güvenlik, G.1–G.5 göç, G.6 geri dönüş, G.7 çıkış provası, G.8 paket).
Madde durumu: `analiz/TESLIM_MADDE_DURUMU.md`.

Kurallar: canlı sunucuda `alembic downgrade` **yok**; her yazan adımdan önce
yedek; "PROVA BAŞARISIZ" yazan tutanakla canlıya çıkılmaz. Her kutunun yanına
tarih, saat ve uygulayanın adı yazılır.

---

## 0. Paket hazırlığı (geliştirme makinesi)

- [ ] Dalga 4 + son bütünleştirme değişiklikleri **commit edildi**
      (`paket-uret.sh` yalnız `git ls-files` dosyalarını paketler; commit
      edilmemiş `ParolaDegistirPage.tsx`, `vekalet.py`, `erisim_gozden.py`,
      `cikis-provasi.sh`, `servis_duman.py` vb. pakete girmez).
- [ ] Tam suite yeşil (`araclar\test.ps1`, iki DB'ye bölünmüş koşu),
      `ruff check` + `ruff format --check`, `npm run build` + `oxlint` temiz.
- [ ] **Altın kayıt fixture'ı** (`backend/tests/fixtures/altin/hakedis-anonim.db`)
      olan makinede `make test-goc` ve `test_altin_kayit.py` koşuldu:
      932 iş / 552.825,00 TL. *(Bu çalışma kopyasında fixture yok; 11 test
      atlanıyor.)*
- [ ] **Docker'da PDF testleri** (Windows'ta WeasyPrint yok, atlanıyor):
      ```bash
      docker compose run --rm api pytest -q tests/integration/test_servis_onay.py \
        tests/integration/test_servis_teklif_gonderim.py tests/integration/test_teklif*.py
      ```
      Türkçe karakter, çok sayfa, "Sayfa x/y", servis formu PB kontrol bloğu
      (TS-036, TS-143) yeşil.
- [ ] Paket WSL/Linux'ta üretildi: `deploy/paket-uret.sh ~/denge-canli`;
      `SURUM.txt` "hedef head = d4a000000002"; `on-kontrol.sh` geçti
      (≥39 migration, tek head).
- [ ] `.sh` dosyaları LF (`test_deploy_betikleri.py` yeşil).

## 1. Yedek

- [ ] Canlıda yükseltme öncesi tam yedek:
      `sudo UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh`
- [ ] Yedek dosyası (`/var/backups/denge-erp/dengeerp-<damga>.sql.gz.gpg`) ve
      `dosyalar-<damga>` dosyası var; ad ve boyut tutanağa yazıldı.
- [ ] `YEDEK_DIZIN` üç betikte aynı (`/etc/default/denge-erp` tek kaynak;
      varsayılan `/var/backups/denge-erp`).
- [ ] Yedeğin geri yüklenebildiği **prova sunucusunda** denendi (madde 2).
- [ ] İlk gün saatlik yedek cron'u açıldı (G.0):
      `0 * * * * UZAK_HEDEF=/mnt/yedek /opt/denge-erp/deploy/yedekle.sh ...`

## 2. Canlı döküm KOPYASINDA prova (ayrı prova sunucusu)

Canlı sunucuya ve canlı dökümün aslına dokunulmaz; döküm kopyası prova
sunucusuna taşınır.

- [ ] Prova sunucusuna canlıdaki **önceki paket** `./kur.sh` ile kuruldu, canlı
      döküm kopyası yüklendi, yedek parolası oluşturuldu.
- [ ] **Migration süresi ölçüldü:** `alembic upgrade b30e012dd879 → head`
      (d4a000000002). Başlangıç/bitiş saati tutanağa; süre bakım penceresine
      sığmalı. Ölçüm: `time docker compose run --rm api alembic upgrade head`
      (ya da `cikis-provasi.sh`'in `kur.sh` adımının süresi).
- [ ] Çıkış provası koşuldu:
      `PROVA_ONAY=evet ./cikis-provasi.sh --geri-donus ~/denge-canli-onceki`
      Adımlar: parmak izi (önce) → `yedekle.sh` → `kur.sh` → `dogrula.sh` →
      **altın kayıt** → **servis duman testi** (`servis_duman.py`,
      `DENGE_PROVA=1`) → `geri-yukle.sh` provası → G.6 geri dönüş → parmak izi.
- [ ] **Altın kayıt o ortamda yeşil:** hesap/cihaz/araç/hat/iş emri sayıları
      ve hak ediş dökümü + dönem bazında tutarlar önce = sonra (kuruşu
      kuruşuna).
- [ ] `dogrula.sh` çıktısı: göç sürümü `d4a000000002` = beklenen head, tek head;
      8 yeni rol var; 26 servis tablosu okunuyor; bayraklar listelendi.
- [ ] 24 saat sonra `dogrula.sh` tekrar: her worker görevi son 25 saatte
      "görev bitti" yazdı (`pb-uretimi`, `bakim-donem-uzlastirma`,
      `servis-sla-uyarilari`, `servis-uyari-temizligi`, `servis-eposta`,
      `vekalet-sona-erme` + mevcut dört görev).
- [ ] Tutanak (`CIKIS-PROVASI-<damga>.md`) `deploy/CIKIS-PROVASI-TUTANAGI.md`
      §3.2'ye eklendi ve imzalandı; sonuç **PROVA BAŞARILI**.

## 3. Göç provaları (canlı döküm kopyasında, eski sistem `.bak` kopyasıyla)

Eski .NET DengeERP V1.20.1 yedeği **ayrı bir SQL Server test örneğine** geri
yüklenir; canlı SQL Server'a bağlanılmaz.

- [ ] TS-017 veri kalitesi ölçümü (salt okunur) canlı kopyada koşuldu; aynı
      VKN'li hesap grupları, il yazım çeşitleri, kütük mükerrer seri sayıları
      rapora geçti.
- [ ] **Göç-1** (G.1–G.4): dışa aktarım → personel → ad eşleme (İK kararı) →
      kütük → bakım sözleşmesi teyidi → müşteri/tesis eşleştirme → servis
      işleri/plan/zaman → karantina. Önizleme → uygula → `rapor`; her tabloda
      kaynak = aktarılan + karantina + reddedilen (+ ertelenen); ikinci
      `uygula` 0 yeni satır. 5 örnek iş eski ekranla karşılaştırıldı.
- [ ] Birim bazlı geçiş provası: `--birim GUVENLIK` önce (TS-177 — bu provası
      henüz yapılmadı).
- [ ] **Göç-2** (G.5): atölye sağlık raporu, kiralama uzlaştırma (yalnız
      rapor), eğitim göçü (önizleme → onay → uygula; ikinci uygula 0), SLA
      geri doldurma (`servis_sla_yururluk_at` ayarlandıktan SONRA), ana veri
      Faz 2 adayları.
- [ ] Göçten sonra `make test-goc` / altın kayıt yine yeşil (mobilite
      etkilenmedi).

## 4. Canlı yükseltme (R1 — pilot)

- [ ] Bakım penceresi duyuruldu; madde 1 yedeği alındı.
- [ ] `./kur.sh` (yeni paket) → `dogrula.sh` yeşil.
- [ ] G.0.1 Dalga 4 adımları: `.env` `FORWARDED_ALLOW_IPS=<docker ağ geçidi>`
      + denetimde gerçek IP doğrulandı; EK E uygulandıysa `audit_logs`
      yetki bloğu (UPDATE yalnız `old_value,new_value`; DELETE/TRUNCATE yok).
- [ ] `python -m app.yonetim canliya-hazirla` yalnız geliştirme dökümü taşınıyorsa;
      yönetici ilk girişte parolasını değiştirir ve MFA kurar.
- [ ] **Pilot birim GUVENLIK:** servis rolleri ve birim üyeliği yalnız
      GUVENLIK personeline verildi; diğer kullanıcılar için menü değişmedi.
- [ ] **`bakim_otomatik_uretim = false` ile başlar.** Planlı Bakım ekranında
      sözleşme–ekipman eşleştirmesi %100 olmadan açılamaz (409); açılış kararı
      servis yöneticisinde.
- [ ] `servis_sla_yururluk_at` boş başlar; GUVENLIK göçü bitince **bir kez**
      şimdiki zaman yazılır.
- [ ] `servis_eposta_acik = false`; SMTP tanımlı ve pilot ilk haftayı
      bitirince açılır.
- [ ] `ek_icerik_denetimi_canli_turler = false` (kuru koşu); bir hafta sonra
      `GET /api/ekler/icerik-denetimi` raporu okunur, temizse açılır.
- [ ] Sürüm notu kullanıcılara iletildi (KURULUM G.0.1 madde 4: kilitli hesap
      401, geçici parola 72 sa/tek giriş, vekâlet, satış temsilcisinin arama
      kapsamı, teklif e-posta hız sınırı, RMA sayfalama/ek).

## 5. Rol ve yetki atamaları

- [ ] Yeni roller atandı: SERVIS_YONETICI, SERVIS_SEF, SERVIS_OPERASYON,
      SERVIS_TEKNISYEN, ATOLYE, SERVIS_DEPO, KIRALAMA_DEPO, IK.
- [ ] Özelleştirilmiş eski rollerin "elle eklenecek izin" listesi `api`
      log'undan okundu ve karara bağlandı.
- [ ] `vekalet.ver` yalnız ADMIN ve SERVIS_YONETICI'de; ilk erişim gözden
      geçirmesi (Kullanıcılar → Erişim gözden geçirme) yapıldı ve işaretlendi.
- [ ] Yüksek yetkili izinler (sistem/denetim/KVKK) yalnız ADMIN'de;
      `maliyet.gor` kümesi {ADMIN, SATIS_MUDURU, MUHASEBE_DESTEK, YONETIM}
      değişmedi.
- [ ] **KULLANICI KARARI — ATOLYE `hesap.gor`:** rolde yok (plan M14-01: VKN/IBAN
      açmasın). Sonuç: atölye dış servis firması (tedarikçi hesabı) seçemiyor.
      Seçenekler: (a) olduğu gibi kalsın, seçimi SERVIS_SEF yapsın; (b) atölye
      kullanıcısına kişiye özel `hesap.gor` istisnası; (c) dış servis için
      hafif tedarikçi arama ucu (geliştirme gerekir). Karar: ______
- [ ] **KULLANICI KARARI — MUHASEBE_DESTEK `servis_rapor.disaaktar`:** rolde
      yok (servis_rapor.* hiç yok). Fatura devri / maliyet Excel'ini muhasebe
      alacaksa `servis_rapor.gor` + `servis_rapor.disaaktar` verilmeli ya da
      kişiye özel istisna. Karar: ______
- [ ] **KULLANICI KARARI — `RmaOut.cost`:** RMA müşteri bedeli `maliyet.gor`
      ile korunmuyor (canlı davranış). Gizlenecekse geliştirme gerekir.
      Karar: ______

## 6. Açık kararlar (koda girmedi)

- [ ] **MESAI takvimi (KD-23, TS-200):** SLA yalnız 7/24 ölçülüyor;
      `d3a000000003` (servis_mesai_takvimi) bilerek atlandı. Bir birim mesai
      saatli SLA isterse: tatil/mesai verisi + yeni migration (zincirin
      sonuna, `d3a000000003` adıyla değil) gerekir. Karar: ______
- [ ] **Pivot şablonu (TS-201):** `templates/excel/servis_pivot_sablonu.xlsx`
      yok; `PIVOT_SABLONU_ETKIN=False`, Excel'de `Veri_IsEmirleri` /
      `Veri_Sureler` tipli tabloları var (Ekle → PivotTable tek tık). Gerçek
      şablon istenirse Excel'de hazırlanıp (önbelleği boş) eklenir. Karar: ____
- [ ] Rapor aralığı sınırı 24 ay kod sabiti; Excel satır sınırı ayar
      (`servis_rapor_excel_azami_satir`, varsayılan 50 000).

## 7. Geri dönüş (gerekirse)

Sıra zorunlu; `alembic downgrade` kullanılmaz.

1. [ ] Yükseltme öncesi yedeği geri yükle:
       `sudo HEDEF_DB=dengeerp ZORLA=1 deploy/geri-yukle.sh /var/backups/denge-erp/dengeerp-<damga>.sql.gz.gpg`
       (api/worker durur, DB `DROP … WITH (FORCE)` ile silinip yeniden
       yaratılır, dosyalar geri açılır).
2. [ ] **Sonra** önceki paketle: `cd ~/denge-canli-onceki && ./kur.sh`
3. [ ] `dogrula.sh`: göç sürümü önceki head'i (`b30e012dd879`) gösterir;
       hak ediş toplamı yükseltme öncesiyle aynı.
4. [ ] Yükseltmeden sonra girilen servis kayıtları kaybolur → pilot
       kullanıcılara bildir, kâğıt kayıtlar yeniden girilecek.

Yeni paketle `api`'yi açmak yanlıştır (açılıştaki `upgrade head` yedeği
yeniden yükseltir); önce `kur.sh` koşmak da yanlıştır (`Can't locate revision`).

## 8. Sonraki sürümler

- [ ] R2: Göç-1 canlıya; birim sırası GUVENLIK → HABERLESME/POC →
      MOBILITE/ARAC_TAKIP; her birimden önce yedek.
- [ ] R3: Göç-2; rapor/KPI ekranları; altın KPI seti (TS-183) yeşil.
- [ ] R4: Dalga 4 sıkılaştırmaları canlıda; ek içerik denetimi açıldı;
      ilk erişim gözden geçirmesi tamamlandı.
