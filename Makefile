SHELL := /bin/bash
UV := $(HOME)/.local/bin/uv

.PHONY: help kur db db-durdur api worker web test test-goc migrate makemigration \
        seed lint build paket audit goc-onizleme goc-uygula goc-rapor pdf-ornek \
        openapi yedek-prova goc-servis-onizleme goc-servis-uygula goc-servis-rapor \
        goc-servis-ad-oner goc-servis-ad-uygula goc-servis-bakim-teyit \
        goc-atolye-saglik goc-kiralama-uzlastirma goc-egitim-onizleme goc-egitim-uygula \
        goc-egitim-rapor goc-servis-sla-rapor goc-servis-sla-uygula goc-ana-veri-faz2

help:
	@echo "make kur            - Bagimliliklari kur (uv sync + npm ci), .env yoksa uret"
	@echo "make db             - PostgreSQL 17'yi Docker ile ayaga kaldir"
	@echo "make db-durdur      - Veritabanini durdur"
	@echo "make migrate        - Alembic migration'lari uygula"
	@echo "make makemigration m=aciklama - Yeni migration olustur (autogenerate)"
	@echo "make seed           - Roller, izinler ve ilk yonetici"
	@echo "make api            - Backend'i lokalde calistir (uvicorn --reload)"
	@echo "make worker         - Arka plan iscisini calistir"
	@echo "make web            - Arayuzu lokalde calistir (vite dev)"
	@echo "make test           - Testler"
	@echo "make test-goc       - Yalnizca veri gocu (altin kayit) testleri"
	@echo "make goc-onizleme   - Veri gocu onizlemesi (HICBIR SEY YAZMAZ)"
	@echo "make goc-uygula     - Veri gocunu uygula (tek transaction)"
	@echo "make goc-rapor      - Karantina raporu (xlsx)"
	@echo "make goc-servis-onizleme KAYNAK=dizin - Eski .NET servis verisi gocu onizlemesi (YAZMAZ)"
	@echo "make goc-servis-uygula   KAYNAK=dizin - Servis gocunu uygula (tek transaction, idempotent)"
	@echo "make goc-servis-rapor    KAYNAK=dizin - Uzlasma raporu: kaynak = aktarilan+karantina+reddedilen"
	@echo "make goc-servis-ad-oner  KAYNAK=dizin - Personel ad esleme onerisi (IK Excel'i)"
	@echo "make goc-servis-ad-uygula            - Onayli ad eslemesini goc zaman kayitlarina isle"
	@echo "make goc-servis-bakim-teyit KAYNAK=dizin - Bakim sozlesmesi teyit Excel'i (ucretsiz)"
	@echo "make goc-atolye-saglik KAYNAK=dizin      - Atolye pilot saglik raporu (7 bolum, YAZMAZ)"
	@echo "make goc-kiralama-uzlastirma KAYNAK=dizin - Kiralama pilot uzlastirma (4 tur, YAZMAZ)"
	@echo "make goc-egitim-onizleme|uygula|rapor KAYNAK=dizin - Egitim gocu ve uzlasma"
	@echo "make goc-servis-sla-rapor|uygula [KAYNAK=dizin] - Goc islerinde SLA geri doldurma"
	@echo "make goc-ana-veri-faz2 FAZ2=servis_isi|ekipman_diger - Eslestirme Faz 2 aday Excel'i"
	@echo "make lint           - ruff + oxlint"
	@echo "make build          - Arayuz build + docker compose build"
	@echo "make paket          - Canliya cikis paketini uret (~/Downloads/denge-canli)"
	@echo "make audit          - Bagimlilik zafiyet taramasi"
	@echo "make openapi        - docs/openapi.json uret (uretimde /api/docs kapali)"
	@echo "make yedek-prova    - Yedekten geri yukleme provasi (gecici DB, canliya dokunmaz)"

kur:
	@test -f .env || (cp .env.example .env && \
		sed -i '' "s/degistir-openssl-rand-hex-32/$$(openssl rand -hex 32)/" .env && \
		echo ".env uretildi — POSTGRES_PASSWORD'u elle doldurun")
	cd backend && $(UV) sync
	@test -d frontend/node_modules || (cd frontend && npm install)

db:
	docker compose up -d db
	@echo "PostgreSQL 17 hazir: localhost:5433"

db-durdur:
	docker compose stop db

api:
	cd backend && $(UV) run uvicorn app.main:app --reload --port 8000

worker:
	cd backend && $(UV) run python -m app.worker

web:
	cd frontend && npm run dev

test:
	cd backend && $(UV) run pytest -q

test-goc:
	cd backend && $(UV) run pytest tests/migration -q

migrate:
	cd backend && $(UV) run alembic upgrade head

makemigration:
	cd backend && $(UV) run alembic revision --autogenerate -m "$(m)"

seed:
	cd backend && $(UV) run python -m app.seeds.dev --admin "Sistem Yoneticisi"

goc-onizleme:
	cd backend && $(UV) run python -m app.migration.yukle

goc-uygula:
	cd backend && $(UV) run python -m app.migration.yukle --uygula

goc-rapor:
	cd backend && $(UV) run python -m app.migration.rapor

# --- Eski .NET DengeERP V1.20.1 servis verisi gocu (Goc-1, plan §5.3, TS-170…177) ---
# KAYNAK: teknik_servis/sql/disa_aktar.ps1 ile uretilmis CSV dizini (tablo basina bir dosya).
# Sira: ad-oner -> (IK karari, Ice Aktarma) -> onizleme -> uygula -> rapor. ONCE YEDEK AL.
KAYNAK ?= ../goc/v1
CIKTI ?= goc_servis_rapor.xlsx
BIRIM ?=

goc-servis-onizleme:
	cd backend && $(UV) run python -m app.migration.servis_uzlasma onizleme --kaynak "$(KAYNAK)" --cikti "$(CIKTI)" $(if $(BIRIM),--birim $(BIRIM),)

goc-servis-uygula:
	cd backend && $(UV) run python -m app.migration.servis_uzlasma uygula --kaynak "$(KAYNAK)" --cikti "$(CIKTI)" $(if $(BIRIM),--birim $(BIRIM),)

goc-servis-rapor:
	cd backend && $(UV) run python -m app.migration.servis_uzlasma rapor --kaynak "$(KAYNAK)" --cikti "$(CIKTI)" $(if $(BIRIM),--birim $(BIRIM),)

goc-servis-ad-oner:
	cd backend && $(UV) run python -m app.migration.servis_ad_esleme oner --kaynak "$(KAYNAK)" --cikti ad_esleme_oneri.xlsx

goc-servis-ad-uygula:
	cd backend && $(UV) run python -m app.migration.servis_ad_esleme uygula

goc-servis-bakim-teyit:
	cd backend && $(UV) run python -m app.migration.bakim_sozlesme --kaynak "$(KAYNAK)" --cikti bakim_teyit.xlsx

# --- Goc-2 (Dalga 3, D3-G, TS-205…208). Goc-1'den SONRA; ONCE YEDEK AL. ---
# Atolye/kiralama: salt okunur saglik/uzlastirma raporu (pilot veri yoksa goc yok).
# Egitim: onizleme -> uygula -> rapor. SLA: rapor -> (onay) -> uygula (yururluk ani ayarlandiktan sonra).
FAZ2 ?= servis_isi

goc-atolye-saglik:
	cd backend && $(UV) run python -m app.migration.atolye_saglik --kaynak "$(KAYNAK)" --cikti atolye_saglik.xlsx

goc-kiralama-uzlastirma:
	cd backend && $(UV) run python -m app.migration.kiralama_uzlastirma --kaynak "$(KAYNAK)" --cikti kiralama_uzlastirma.xlsx

goc-egitim-onizleme:
	cd backend && $(UV) run python -m app.migration.egitim onizleme --kaynak "$(KAYNAK)" --cikti goc_egitim_rapor.xlsx

goc-egitim-uygula:
	cd backend && $(UV) run python -m app.migration.egitim uygula --kaynak "$(KAYNAK)" --cikti goc_egitim_rapor.xlsx

goc-egitim-rapor:
	cd backend && $(UV) run python -m app.migration.egitim rapor --kaynak "$(KAYNAK)" --cikti goc_egitim_rapor.xlsx

goc-servis-sla-rapor:
	cd backend && $(UV) run python -m app.migration.servis_sla_geri_doldur rapor --kaynak "$(KAYNAK)" --cikti sla_geri_doldur.xlsx

goc-servis-sla-uygula:
	cd backend && $(UV) run python -m app.migration.servis_sla_geri_doldur uygula --kaynak "$(KAYNAK)" --cikti sla_geri_doldur.xlsx

goc-ana-veri-faz2:
	cd backend && $(UV) run python -m app.migration.ana_veri_faz2 --kaynak $(FAZ2) --cikti eslestirme_faz2_$(FAZ2).xlsx

lint:
	cd backend && $(UV) run ruff check . && $(UV) run ruff format --check .
	@test -d frontend/node_modules && (cd frontend && npx oxlint) || true

build:
	cd frontend && npm run build
	rm -rf backend/app/static && cp -r frontend/dist backend/app/static
	docker compose build

paket:
	deploy/paket-uret.sh

openapi:
	cd backend && $(UV) run python -m app.openapi_disaaktar

# Yedegin geri yuklenebildigini KANITLAR: canliyi dump edip yanina gecici bir
# veritabanina yukler, sayilari ve tarihli kisitlari dogrular, sonra siler.
# Denenmemis yedek, yedek degildir.
yedek-prova:
	@set -euo pipefail; \
	TMP=$$(mktemp -d); \
	docker compose exec -T db pg_dump -U dengeerp --clean --if-exists dengeerp | gzip > $$TMP/prova.sql.gz; \
	echo "Dump: $$(du -h $$TMP/prova.sql.gz | cut -f1)"; \
	docker compose exec -T db psql -U dengeerp -d postgres -v ON_ERROR_STOP=1 \
		-c "DROP DATABASE IF EXISTS dengeerp_prova;" -c "CREATE DATABASE dengeerp_prova OWNER dengeerp;"; \
	gunzip -c $$TMP/prova.sql.gz | docker compose exec -T db psql -U dengeerp -d dengeerp_prova -v ON_ERROR_STOP=1 > /dev/null; \
	docker compose exec -T db psql -U dengeerp -d dengeerp_prova -P pager=off -c \
		"SELECT 'hesap' ne, count(*) FROM accounts \
		 UNION ALL SELECT 'cihaz', count(*) FROM devices \
		 UNION ALL SELECT 'is_emri', count(*) FROM work_orders \
		 UNION ALL SELECT 'dokum', count(*) FROM partner_settlements \
		 UNION ALL SELECT 'hakedis_toplam', sum(gross_amount)::bigint FROM partner_settlements \
		 UNION ALL SELECT 'exclude_kisiti', count(*) FROM pg_constraint WHERE contype='x' \
		 UNION ALL SELECT 'cakisan_acik_donem', count(*) FROM ( \
		   SELECT device_id FROM device_vehicle_assignments WHERE valid_to IS NULL \
		   GROUP BY device_id HAVING count(*)>1) x;"; \
	docker compose exec -T db psql -U dengeerp -d postgres -c "DROP DATABASE dengeerp_prova;"; \
	rm -rf $$TMP; \
	echo "PROVA BASARILI"

audit:
	@echo "=== Backend (pip-audit) ==="
	cd backend && $(UV) run pip-audit || true
	@echo "=== Frontend (npm audit) ==="
	cd frontend && npm audit || true
