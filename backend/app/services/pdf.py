"""PDF üretimi — WeasyPrint + Jinja2.

Şablonlar HTML/CSS olduğu için arayüzle aynı marka değişkenlerinden beslenir
ve CSS Paged Media sayesinde çok sayfalı tabloda başlık tekrarı ile sayfa
numarası hazır gelir (hak ediş dökümü 30+ satıra çıkabiliyor).

WeasyPrint'in Pango/HarfBuzz bağımlılıkları Docker imajının içinde. Mac'te
kurulu olmadığı için `render_pdf` import anında değil ÇAĞRI anında yüklenir;
böylece PDF üretmeyen kod yolları (testlerin çoğu) makinede çalışmaya devam
eder ve anlaşılır bir hata verir.
"""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

SABLON_DIZINI = Path(__file__).resolve().parent.parent / "templates"
VARLIK_DIZINI = Path(__file__).resolve().parent.parent / "static_assets"

_env = Environment(
    loader=FileSystemLoader(SABLON_DIZINI),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def tl(deger: Decimal | float | None) -> str:
    """Türkçe para biçimi: 1.234.567,89"""
    if deger is None:
        return "0,00"
    return f"{Decimal(str(deger)):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


_env.filters["tl"] = tl


class PdfUretilemedi(RuntimeError):
    """WeasyPrint sistem bağımlılıkları yok."""


def html_uret(sablon: str, **baglam: Any) -> str:
    baglam.setdefault("font_dir", (VARLIK_DIZINI / "fonts").as_uri())
    baglam.setdefault("brand_dir", (VARLIK_DIZINI / "brand").as_uri())
    baglam.setdefault("bugun", date.today().strftime("%d.%m.%Y"))
    return _env.get_template(sablon).render(**baglam)


async def pdf_uret_async(sablon: str, **baglam: Any) -> bytes:
    """PDF'i AYRI BİR İŞ PARÇACIĞINDA üretir.

    WeasyPrint saf CPU işidir ve olay döngüsünü bloke eder — ölçüldü: PDF
    üretilirken `/api/auth/me` 9 ms yerine **632 ms** sürüyor ve üretim
    boyunca yalnız bir istek tamamlanabiliyordu. Yani bir kişi hak ediş
    dökümü alırken API'nin tamamı duruyordu; ay sonunda 39 montaj noktasına
    döküm gönderilirken bu dakikalara çıkardı (plan §3.5'in uyardığı hata).

    Eşzamanlı (senkron) `pdf_uret` testler ve CLI için duruyor; HTTP
    uçlarından DAİMA bu sarmalayıcı çağrılmalı.
    """
    return await asyncio.to_thread(pdf_uret, sablon, **baglam)


def pdf_uret(sablon: str, **baglam: Any) -> bytes:
    html = html_uret(sablon, **baglam)
    try:
        from weasyprint import HTML  # noqa: PLC0415 — çağrı anında yüklenir
    except OSError as exc:  # pragma: no cover - ortam bağımlı
        raise PdfUretilemedi(
            "PDF üretimi için Pango/Cairo kitaplıkları gerekli. Bu makinede yoklar; "
            "PDF'ler Docker imajında üretilir (docker compose run --rm api ...)."
        ) from exc
    return HTML(string=html, base_url=str(VARLIK_DIZINI)).write_pdf()
