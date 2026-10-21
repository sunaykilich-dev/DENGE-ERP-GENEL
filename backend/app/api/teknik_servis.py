"""Servis işleri, panel, tanımlar (arıza/bekleme nedenleri) uçları (TS-020…037).

İSKELET (D0-S): router `main.py`'de kayıtlıdır ama henüz uç yoktur
(TS-018: uçlar 501 değil, router boş). Uçları D1-B (iş uçları) ve D1-C
(panel, ek, onay, PDF) paketleri yazar; her uç `require_permission` ile
korunur, kapsam dışı tek kayıt 404 döner.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/teknik-servis", tags=["teknik-servis"])
