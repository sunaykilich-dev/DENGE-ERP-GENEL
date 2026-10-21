"""Saha zaman kaydı ve Benim İşlerim uçları (TS-070…078).

İSKELET (D0-S): router `main.py`'de kayıtlıdır ama henüz uç yoktur
(TS-018: uçlar 501 değil, router boş). Uçları D1-G paketi yazar; her uç
`require_permission` ile korunur, kapsam dışı tek kayıt 404 döner.

Yollar: `/zaman/...` ve `/benim-islerim` (prefix `/api/teknik-servis`).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/teknik-servis", tags=["servis-zaman"])
