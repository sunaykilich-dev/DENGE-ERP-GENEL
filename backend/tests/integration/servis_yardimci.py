"""D1-B servis işi testlerinin ortak yardımcıları (giriş, kullanıcı ve iş kurulumu).

`conftest.py` donmuş olduğu için (plan §4.2) paket yardımcıları burada durur;
fixture değil düz fonksiyonlardır, test dosyaları fixture'ları parametre
olarak geçirir.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect

from app.models import Account, Address, ServiceOrderEvent

SRV_DESENI = r"^SRV-\d{6}-\d{6,}$"


async def giris(client, username: str, password: str = "parola1234") -> None:
    """Aynı istemcide oturumu `username`'e çevirir."""
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def musteri(db, ad: str = "Servis Müşterisi A.Ş.", **kw) -> Account:
    """Müşteri + bir tesis (lokasyon). Faz A (M1.2) ekran açılışında lokasyon
    zorunlu olduğundan tesis kimliği `hesap.lokasyon_id` olarak taşınır;
    `acilis(hesap)` onu gövdeye koyar."""
    kw.setdefault("is_musteri", True)
    hesap = Account(title=ad, **kw)
    db.add(hesap)
    await db.flush()
    tesis = Address(account_id=hesap.id, kind="TESIS", label="Tesis", site_name=f"{ad} Tesisi")
    db.add(tesis)
    await db.commit()
    await db.refresh(hesap)
    hesap.lokasyon_id = tesis.id  # type: ignore[attr-defined]  # eşlenmeyen test özniteliği
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


def acilis(hesap: Account | int, **kw) -> dict[str, Any]:
    """Geçerli bir ekran açılış gövdesi. `musteri()` ile açılan hesap
    verilirse tesisi `address_id` olur (M1.2: lokasyon zorunlu)."""
    # Kimlik eşleme anahtarından okunur: commit sonrası süresi dolmuş nesnede
    # `hesap.id` senkron bağlamda yükleme deneyip MissingGreenlet verirdi.
    hesap_id = hesap if isinstance(hesap, int) else sa_inspect(hesap).identity[0]
    govde: dict[str, Any] = {
        "birim": "GUVENLIK",
        "tur": "ARIZA",
        "konu": "Kamera görüntü vermiyor",
        "customer_id": hesap_id,
        "address_id": getattr(hesap, "lokasyon_id", None),
        "talep_kanali": "TELEFON",
        "iletisim_ad": "Saha Yetkilisi",
        "iletisim_telefon": "+905321112233",
    }
    govde.update(kw)
    return govde


async def tazele(db, kayit):
    await db.refresh(kayit)
    return kayit
