SHELL := /bin/bash
UV := $(HOME)/.local/bin/uv

.PHONY: help kur db db-durdur api worker web test test-goc migrate makemigration \
        seed lint build paket audit goc-onizleme goc-uygula goc-rapor pdf-ornek \
        openapi yedek-prova

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
