FROM python:3.13-slim

# WeasyPrint'in (teklif ve hak edis dokumu PDF'leri) sistem bagimliliklari.
# Turkce karakterlerin dogru sekillenmesi Pango + HarfBuzz ile saglanir;
# Mac'te bu kutuphaneler yok, bu yuzden PDF uretimi imaj icinde calisir.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfribidi0 \
        libcairo2 libffi8 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./

# Ikinci emniyet kemeri: .dockerignore bir sekilde atlanirsa diye imajin
# icinde de temizle. macOS AppleDouble dosyalari (._*.py) alembic'in versions
# dizininde durursa api acilista "source code string cannot contain null bytes"
# ile duser; adlari *.py ile bittigi icin alembic onlari migration sanar.
RUN find . -name '._*' -delete -o -name '.DS_Store' -delete

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
