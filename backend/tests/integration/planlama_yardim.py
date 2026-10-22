"""Planlama testlerinin ortak kurulumu (D1-D, TS-040…049).

İki birim (GUVENLIK, HABERLESME), iki şef, teknisyenler, salt okuyan yönetim
ve plan izni olmayan operasyon kullanıcısı. Kayıtlar ORM yardımcılarıyla
(conftest) kurulur; plan yazımı UÇTAN yapılır ki testin konusu uç olsun.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy import func, select

from app.models import Account, ServicePlan

PAROLA = "parola1234"


async def oturum(username: str) -> httpx.AsyncClient:
    """Oturum açmış istemci (conftest `client` fixture'ının saat/oturum geçersiz
    kılmaları uygulamada olduğu sürece aynı FakeClock'u görür)."""
    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert r.status_code == 200, r.text
    return ist


@dataclass
class Ortam:
    kisiler: dict[str, Any] = field(default_factory=dict)
    istemciler: dict[str, httpx.AsyncClient] = field(default_factory=dict)
    musteri: Any = None
    lokasyon: Any = None

    def kisi(self, ad: str) -> Any:
        return self.kisiler[ad]

    async def ist(self, ad: str) -> httpx.AsyncClient:
        if ad not in self.istemciler:
            self.istemciler[ad] = await oturum(ad)
        return self.istemciler[ad]


@pytest_asyncio.fixture(name="ortam")
async def ortam_fixture(client, db, birimli_kullanici_ac, kullanici_ac, lokasyon_ac):
    o = Ortam()
    o.kisiler["sef_g"] = await birimli_kullanici_ac(
        "sef_g", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF"
    )
    o.kisiler["sef_h"] = await birimli_kullanici_ac(
        "sef_h", "SERVIS_SEF", ["HABERLESME"], saha_rolu="SEF"
    )
    o.kisiler["tek1"] = await birimli_kullanici_ac(
        "tek1", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    o.kisiler["tek2"] = await birimli_kullanici_ac(
        "tek2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    # İki birime üye (birimler arası çakışma).
    o.kisiler["tek_ortak"] = await birimli_kullanici_ac(
        "tek_ortak", "SERVIS_TEKNISYEN", ["GUVENLIK", "HABERLESME"], saha_rolu="TEKNISYEN"
    )
    o.kisiler["tek_h"] = await birimli_kullanici_ac(
        "tek_h", "SERVIS_TEKNISYEN", ["HABERLESME"], saha_rolu="TEKNISYEN"
    )
    o.kisiler["operasyon"] = await birimli_kullanici_ac(
        "operasyon", "SERVIS_OPERASYON", ["GUVENLIK"]
    )
    o.kisiler["yonetim"] = await kullanici_ac("yonetim", "YONETIM")
    o.kisiler["yonetici"] = await kullanici_ac("yonetici", "SERVIS_YONETICI")
    o.musteri = Account(title="Planlama Müşterisi A.Ş.", is_musteri=True)
    db.add(o.musteri)
    await db.commit()
    o.lokasyon = await lokasyon_ac(o.musteri, ad="Akyaka AVM", il="İstanbul", district="Üsküdar")
    yield o
    for ist in o.istemciler.values():
        await ist.aclose()


def plan_govdesi(tarih: str = "2026-01-15", saat: str | None = "10:00", sure: int = 60, **kw):
    govde: dict[str, Any] = {"plan_tarihi": tarih, "baslangic_saati": saat, "sure_dk": sure}
    govde.update(kw)
    return govde


async def aktif_plan_sayisi(db, so_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(ServicePlan).where(ServicePlan.is_active.is_(True))
    if so_id is not None:
        stmt = stmt.where(ServicePlan.service_order_id == so_id)
    return int(await db.scalar(stmt) or 0)


async def plan_sayisi(db, so_id: int | None = None) -> int:
    stmt = select(func.count()).select_from(ServicePlan)
    if so_id is not None:
        stmt = stmt.where(ServicePlan.service_order_id == so_id)
    return int(await db.scalar(stmt) or 0)
