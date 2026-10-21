"""Kurulu ekipman kütüğü uçları (TS-050…057).

İSKELET (D0-S): router `main.py`'de kayıtlıdır ama henüz uç yoktur
(TS-018: uçlar 501 değil, router boş). Uçları D1-E paketi yazar; her uç
`require_permission` ile korunur, kapsam dışı tek kayıt 404 döner.

Statik yollar (`/ozet`, `/oneri` ...) `/{id}` yolundan ÖNCE tanımlanır.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/teknik-servis/ekipman", tags=["servis-ekipman"])
