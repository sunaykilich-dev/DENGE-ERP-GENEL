"""Çıkış provasının servis duman testi (deploy/servis_duman.py, TS-220).

Prova sunucusunda koşacak yazma denetimi burada gerçek şemada bir kez
koşturulur: açılan servis işi okunabilmeli ve geri alma sonrası hiçbir
satır kalmamalı (betik "kalıcı kayıt yok" iddiasını taşır).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

DUMAN = Path(__file__).resolve().parents[3] / "deploy" / "servis_duman.py"


def _modul():
    spec = importlib.util.spec_from_file_location("servis_duman", DUMAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_duman_yazma_denetimi_gecer_ve_iz_birakmaz(db, seeded):
    from app.models.account import Account
    from app.models.teknik_servis import ServiceOrder, ServiceOrderEvent

    mod = _modul()
    once_hesap = await db.scalar(select(func.count()).select_from(Account))
    try:
        sonuc = await mod.yazma_denetimi(db)
    finally:
        await db.rollback()
    assert sonuc and all(tamam for tamam, _ in sonuc), sonuc
    assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == 0
    assert await db.scalar(select(func.count()).select_from(ServiceOrderEvent)) == 0
    # Boş veritabanında açılan geçici müşteri de geri alınır.
    assert await db.scalar(select(func.count()).select_from(Account)) == once_hesap


async def test_duman_var_olan_musteriyi_kullanir(db, seeded):
    from app.models.account import Account
    from app.models.teknik_servis import ServiceOrder

    hesap = Account(title="Prova Müşterisi A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    hesap_id = hesap.id  # rollback nesneyi bayatlatır; kimlik önceden alınır
    mod = _modul()
    try:
        sonuc = await mod.yazma_denetimi(db)
        musteri = await db.scalar(select(ServiceOrder.customer_id))
    finally:
        await db.rollback()
    assert all(t for t, _ in sonuc), sonuc
    assert musteri == hesap_id
    assert await db.scalar(select(func.count()).select_from(Account)) == 1
