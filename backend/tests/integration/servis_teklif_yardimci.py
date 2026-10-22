"""Servis teklifi ve maliyet testlerinin ortak yardımcıları (D2-E).

`conftest.py` bu dalgada donmuş olduğu için ortak kurulum burada durur;
`yetki_tarama.py` gibi düz modüldür (fixture değil). Her kullanıcı kendi
çerezini taşıyan ayrı istemciyle oturum açar — tek `client` çerezini
paylaşsaydı "hazırlayan ≠ onaylayan" senaryoları yazılamazdı. Ek istemciler
`client` fixture'ının uygulamaya kurduğu oturum/saat geçersiz kılmalarını
paylaşır (aynı FakeClock).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.models import Account

KALEM = {
    "item_type": "HIZMET",
    "description": "Arıza onarım işçiliği",
    "qty": 1,
    "unit_price": 1000,
    "vat_rate": 0.20,
}


async def oturum(username: str, password: str = "parola1234") -> httpx.AsyncClient:
    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return ist


async def musteri(db, ad: str = "Servis Teklif Müşterisi A.Ş.", email: str | None = None) -> Account:
    h = Account(title=ad, is_musteri=True, email=email)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def teklif_ac(
    ist: httpx.AsyncClient,
    musteri_id: int,
    *,
    birim: str | None = "GUVENLIK",
    kalemler: list[dict[str, Any]] | None = None,
    beklenen: int = 201,
    **kw: Any,
) -> dict[str, Any]:
    govde = {
        "customer_id": musteri_id,
        "kalemler": [dict(KALEM)] if kalemler is None else kalemler,
        **kw,
    }
    if birim is not None:
        govde["birim"] = birim
    r = await ist.post("/api/teklifler", json=govde)
    assert r.status_code == beklenen, r.text
    return r.json()


async def onayli(
    hazirlayan: httpx.AsyncClient, onaylayan: httpx.AsyncClient, teklif_id: int, **kw: Any
) -> dict[str, Any]:
    r = await hazirlayan.post(f"/api/teklifler/{teklif_id}/onaya-gonder", json=kw)
    assert r.status_code == 200, r.text
    r = await onaylayan.post(f"/api/teklifler/{teklif_id}/onayla")
    assert r.status_code == 200, r.text
    return r.json()


async def elle_gonder(ist: httpx.AsyncClient, teklif_id: int) -> dict[str, Any]:
    r = await ist.post(
        f"/api/teklifler/{teklif_id}/elle-gonderildi",
        json={"kanal": "ELDEN", "not": "Müşteriye elden teslim edildi"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def kapat(*istemciler: httpx.AsyncClient) -> None:
    for ist in istemciler:
        await ist.aclose()
