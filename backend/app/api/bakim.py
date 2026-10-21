"""Planlı bakım: sözleşme, dönem, PB üretimi, dijital form uçları (TS-060…069).

İSKELET (D0-S): router `main.py`'de kayıtlıdır ama henüz uç yoktur
(TS-018: uçlar 501 değil, router boş). Uçları D1-F paketi yazar; her uç
`require_permission` ile korunur, kapsam dışı tek kayıt 404 döner.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/teknik-servis/bakim", tags=["bakim"])
