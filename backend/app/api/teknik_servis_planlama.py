"""Planlama takvimi, havuz, plan/toplu plan, araç havuzu uçları (TS-040…049).

İSKELET (D0-S): router `main.py`'de kayıtlıdır ama henüz uç yoktur
(TS-018: uçlar 501 değil, router boş). Uçları D1-D paketi yazar; her uç
`require_permission` ile korunur, kapsam dışı tek kayıt 404 döner.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/teknik-servis/planlama", tags=["teknik-servis-planlama"])
