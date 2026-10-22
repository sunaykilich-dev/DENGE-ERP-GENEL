"""D1-B servis işi testlerinin ortak yardımcıları (giriş, kullanıcı ve iş kurulumu).

`conftest.py` donmuş olduğu için (plan §4.2) paket yardımcıları burada durur;
fixture değil düz fonksiyonlardır, test dosyaları fixture'ları parametre
olarak geçirir.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.models import Account, ServiceOrderEvent

SRV_DESENI = r"^SRV-\d{6}-\d{6,}$"


async def giris(client, username: str, password: str = "parola1234") -> None:
    """Aynı istemcide oturumu `username`'e çevirir."""
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def musteri(db, ad: str = "Servis Müşterisi A.Ş.", **kw) -> Account:
    kw.setdefault("is_musteri", True)
    hesap = Account(title=ad, **kw)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)
    return hesap


async def olay_sayisi(db, so_id: int, tur: str | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(ServiceOrderEvent)
        .where(ServiceOrderEvent.service_order_id == so_id)
    )
    if tur is not None:
        stmt = stmt.where(ServiceOrderEvent.olay_turu == tur)
    return int(await db.scalar(stmt) or 0)


async def teknisyen(birimli_kullanici_ac, username: str, birimler=("GUVENLIK",), **kw):
    """Atanabilir saha teknisyeni (SERVIS_TEKNISYEN, saha rolü TEKNISYEN)."""
    return await birimli_kullanici_ac(
        username, "SERVIS_TEKNISYEN", list(birimler), saha_rolu="TEKNISYEN", **kw
    )


def acilis(hesap_id: int, **kw) -> dict[str, Any]:
    """Geçerli bir ekran açılış gövdesi."""
    govde: dict[str, Any] = {
        "birim": "GUVENLIK",
        "tur": "ARIZA",
        "konu": "Kamera görüntü vermiyor",
        "customer_id": hesap_id,
        "talep_kanali": "TELEFON",
        "iletisim_ad": "Saha Yetkilisi",
        "iletisim_telefon": "+905321112233",
    }
    govde.update(kw)
    return govde


async def tazele(db, kayit):
    await db.refresh(kayit)
    return kayit
