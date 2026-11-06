# Otonom Döngü Durumu (gece çalışması 2026-10-21 → 22)

Kullanıcı talimatı (2026-10-21 akşam): "Kendini loopa al. Sistem kusursuz çalışana kadar eksikleri ve yanlışları düzelt. Benden onay alma. Yarına kadar uğraş, sabah eksiksiz görmek istiyorum. Token limiti biterse yenilenince loopa devam et."

## Her döngü adımında
1. Bu dosyayı oku; "Sıradaki" bölümündeki ilk işi yap.
2. Arka planda çalışan workflow varsa bitmesini bekle. Token limiti nedeniyle düştüyse aynı scriptPath + resumeFromRunId ile devam ettir (biten ajanlar önbellekten gelir).
3. Dalga bitince: doğrulayıcı raporunu oku, kendi kontrolünü yap (`araclar/test.ps1 -Vt dengeerp_test_v`, ruff, build) → `git add -A; git commit` → bu dosyayı güncelle → sonraki dalga workflow'u (dalga0 script'ini şablon al: S paketi → paralel paketler → doğrulayıcı).
4. Canlı sunucuya / canlı veritabanı dökümüne dokunma. Çalışma kopyası: `denge-erp/` (git).

## Ortam
- PostgreSQL 17 servis `postgresql-x64-17`. DB: `dengeerp` (geliştirme), test DB'leri `dengeerp_test`, `dengeerp_test_{s,a,b,c,d,e,f,g,h,i,v}` (paket başına ayrı). Parolalar `.yerel_gizli/`.
- Test yardımcısı: `powershell -NoProfile -ExecutionPolicy Bypass -File araclar\test.ps1 -Vt <db> [-Komut pytest|ruff|format|alembic|build] [argümanlar]`
- Araçlar: uv, Node 24, git (PATH yenile: `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`).

## Belgeler
- Plan: `analiz/10_canli_entegrasyon/01_ENTEGRASYON_VE_KODLAMA_PLANI.md` (181 TS maddesi, D0 18 · D1 55 · D2 71 · D3 26 · D4 11; 32 paket)
- Mimari kurallar: `analiz/10_canli_entegrasyon/00_MIMARI_KURALLAR.md`

## Yapılanlar
- [x] Çalışma kopyası + git; Windows uyumu (commit 02c51f8); temel suite 116/116, unit 146/146
- [x] Entegrasyon analizi (30 ajan) + birleşik plan
- [x] Dalga 0 (≈4 saat): TS-001..018 TAMAM. Tam suite 1126 geçti / 0 kaldı / 11 atlandı. Commit cf192a0 (+6c6fa78). Açık: altın kayıt fixture'ı (`tests/fixtures/altin/hakedis-anonim.db`) pakette yok → 11 test atlandı, hak ediş 932/552.825 doğrulanamadı; 375px görünüm denenmedi; TS-017 ölçüm canlı kopyada koşulmadı.
- [x] Dalga 1 (≈7 saat): TS-020..078 TAMAM. Tam suite 1473 geçti / 0 hata / 12 atlandı; uçtan uca 2 senaryo yeşil. Commit ab60255. SABAH_RAPORU.md yazıldı (08:00).
- [~] Dalga 2 workflow (run wf_2fa696f3-726, script `.../workflows/scripts/dalga2-kodlama-wf_2fa696f3-726.js`), 08:05'te başladı. D2-S şema bitti; 10:40 civarı kullanım limiti → 8 paket + doğrulayıcı düştü. Yarım iş WIP commit 8661c04. Aynı run id ile resume edildi (task wuzdkp8fm); paketler önceki yarım dosyaların üstünden devam ediyor.

- [x] Dalga 2: TS-080..177 TAMAM (TS-143 PDF testi ve TS-177 canlı kopya provası ortam nedeniyle KISMEN). Tam suite 1955 geçti / 0 hata / 13 atlandı. Commit be0467f; seed düzeltmesi cherry-pick a0403ee.
- [x] Dalga 3: TS-180..208 TAMAM (TS-200 mesai takvimi, TS-201 pivot şablonu, TS-205 kiralama göç profilleri KISMEN). Tam suite 2173 geçti / 0 hata / 13 atlandı. Commit 41fec5a.
- [x] DÖNGÜ BİTTİ (23.10 05:50): Dalga 4 commit 3759772; 2292 geçti / 0 hata; 175 TAMAM / 6 KISMEN / 0 EKSİK. SABAH_RAPORU.md nihai.
- [x] Dalga 4 (son) workflow (task w5e8smqs8, run wf_9dee22f4-293, script `.../workflows/scripts/dalga4-kodlama-wf_9dee22f4-293.js`), 21:55'te başladı. Çıktılar: analiz/TESLIM_MADDE_DURUMU.md, analiz/CANLIYA_GECIS_KONTROL_LISTESI.md.
- Açık karar: ATOLYE rolünde `hesap.gor` yok → atölye dış servis firması seçemiyor (rol kataloğu değişmedi).

## Kullanıcı kabul denemesi (22.10 öğleden itibaren)
- Ayrı worktree `denge-erp-deneme` (Dalga 1 = ab60255, dal `deneme-duzeltmeleri`), API :8000, Vite :5173, DB `dengeerp` (sıfırlanıp örnek veri yüklendi: `araclar/ornek_veri_yukle.py`; yönetici parolası `.yerel_gizli/deneme_admin.txt`).
- Kullanıcının bulduğu hatalar `deneme-duzeltmeleri` dalında düzeltilir; Dalga 2 commit'inden sonra ana dala cherry-pick edilir.
- Bekleyen aktarım: seed --demo saha_rolu düzeltmesi.

## Sıradaki
1. Dalga 2 bitince doğrula + commit + SABAH_RAPORU.md güncelle; `deneme-duzeltmeleri` dalını ana dala cherry-pick et.
3. Dalga 2 (D2-S → B..I), Dalga 3 (D3-S → A..G), Dalga 4 (D4-S → A..C).
4. Her dalga sonunda tam test + ruff + build + duman testi + commit.
5. Bitişte: `analiz/SABAH_RAPORU.md` + döngüyü durdur.
