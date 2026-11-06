# DengeERP Geliştirme

Hedef (2026-10-21, kullanıcı kararı): DengeERP V1.20.1'de tasarlanan **teknik servis iş akışı**, canlıdaki **Denge Mobilite ERP**'ye (`denge-erp/`) yeni modüller olarak eklenecek. Önceki "Django'ya yeniden yazım" kararı GEÇERSİZ.

## Klasörler
- `denge-erp/` — ÇALIŞMA KOPYASI (git). Tüm geliştirme burada. Yığın: FastAPI + SQLAlchemy 2 (async) + Alembic + PostgreSQL 17 (btree_gist) + React 19/TS + Ant Design 6 + TanStack Query, WeasyPrint PDF, uv.
- `kaynak/denge_canli/` — canlı paket ve kaynağın SALT OKUNUR kopyası (canlı veritabanı dökümü içerir: KVKK, paylaşma/commit etme).
- `kaynak/V1_20_1_orijinal/` — eski .NET DengeERP, SALT OKUNUR; iş kuralları referansı.
- `analiz/` — denetim ve modül raporları, `_ozet/*.json` onaylı maddeler, entegrasyon planı.
- `.yerel_gizli/` — yerel parolalar (git dışı).

## Kurallar
- Canlı ERP'nin kendi kurallarına uy: izinler tek kaynak `backend/app/permissions.py`; her uçta sunucu tarafı izin kontrolü; iyimser kilitleme (`version`); maliyet varsayılan gizli (`maliyet.gor`); denetim izi; Türkçe adlandırma; her değişiklik Alembic migration + test ile.
- Kapsam (2026-10-28, soru formu G1.1/G1.2): önce teknik servis bitirilir, sonra şirket geneli (satış/CRM, satın alma, İK, idari, muhasebe, Logo yerine geçiş) fazlarla eklenir. Bağlayıcı kararlar ve fazlar: `analiz/soru_formu/KARARLAR_2026-10-28.md`. Öncelik: yeni modül/özellik → mevcut eksikler → güvenlik/üretime hazırlık.
- Denge Mobil / Mobilite modülüne dokunma (G2.5, D8.6); "tayin" dili yalnız teknik serviste (G7.10). Fazla onay adımı ve karmaşık ekran olmasın (G1.9).
- Korunacak iş kararları: 1 cihaz = 1 PB iş emri; seri no metin; zaman takibi bordro değildir, mola kişi-saate dahil değil; süre kaydı yoksa "eksik", 0 değil.
- Kullanıcı "soru sorma, tüm sorularını onaylıyorum" dedi (2026-10-21): kararları gerekçesiyle belgeleyerek ilerle. Canlı sunucuya/canlı veritabanına dokunma.
