-- En az yetkili veritabanı kullanıcısı.
--
-- Varsayılan kurulumda uygulama şema sahibi 'dengeerp' ile bağlanır; bu
-- kullanıcı DROP TABLE de yapabilir. Ayrım şu: migration'ı SAHİP çalıştırır,
-- uygulama ve worker yalnız veri okuyup yazan 'dengeerp_app' ile bağlanır.
-- Böylece uygulamadaki bir açık şemayı silemez.
--
-- Kurulum (sunucuda, bir kez):
--   docker compose exec -T db psql -U dengeerp -d dengeerp < deploy/db-least-privilege.sql
--
-- DOGRULANDI (25 Eyl 2026, gelistirme veritabaninda calistirilarak):
--   okuma            -> calisiyor (480 hesap)
--   yazma            -> calisiyor (audit_logs insert)
--   CREATE TEMP TABLE-> calisiyor (yonetim komutlari gecici tablo kullaniyor)
--   DROP TABLE       -> ENGELLENDI ("must be owner of table accounts")
--   CREATE TABLE     -> ENGELLENDI ("permission denied for schema public")

CREATE ROLE dengeerp_app LOGIN PASSWORD 'GUCLU_BIR_PAROLA';

GRANT CONNECT ON DATABASE dengeerp TO dengeerp_app;
GRANT USAGE ON SCHEMA public TO dengeerp_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dengeerp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dengeerp_app;

-- Bundan sonra migration'ların oluşturacağı tablolara da otomatik yetki.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dengeerp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO dengeerp_app;

-- DIKKAT: ERP'de silme YUMUŞAKTIR (`is_deleted`), denetim izi ve kapanmış
-- dönem satırları hiç silinmez. Yine de DELETE yetkisi veriliyor: içe aktarma
-- partisi geri alma ve toplu zam geri alma gerçek satır siler.
--
-- Uygulama tarafı (.env):
--   DATABASE_URL=postgresql+psycopg://dengeerp_app:GUCLU_BIR_PAROLA@db:5432/dengeerp
-- Migration'ı sahibiyle çalıştırmaya devam edin:
--   docker compose run --rm -e DATABASE_URL=postgresql+psycopg://dengeerp:SAHIP_PAROLA@db:5432/dengeerp api alembic upgrade head
--
-- İzin katalogu senkronu (app/permissions.py) da sahibiyle çalışmalı:
--   docker compose run --rm api python -m app.seeds.dev
