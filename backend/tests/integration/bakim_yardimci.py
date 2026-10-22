"""D1-F planlı bakım testlerinin ortak yardımcıları (TS-060…069).

`conftest.py` donmuş olduğu için (plan §4.2) paket yardımcıları burada durur;
fixture değil düz fonksiyonlardır, test dosyaları fixture'ları parametre
olarak geçirir. Sözleşme uç üzerinden açılır (kurulumun kendisi de sınansın);
ekipman ve tesis ORM fixture'larıyla.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models import (
    Account,
    MaintenanceContractItem,
    ServiceOrder,
    ServiceOrderAssignment,
)

PB_DESENI = r"^PB-\d{6}-\d{6,}$"
BAKIM_NO_DESENI = r"^BAKIM-\d{4,}$"
ONEK = "/api/teknik-servis/bakim"


async def giris(client, username: str, password: str = "parola1234") -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


@dataclass
class Ortam:
    musteri: Account
    tesis: Any
    ekipmanlar: dict[str, list[Any]] = field(default_factory=dict)


async def ortam_kur(
    db,
    lokasyon_ac,
    ekipman_ac,
    *,
    birim: str = "GUVENLIK",
    xray: int = 2,
    kapi: int = 3,
    ad: str = "Bakım Müşterisi A.Ş.",
) -> Ortam:
    musteri = Account(title=ad, is_musteri=True)
    db.add(musteri)
    await db.commit()
    await db.refresh(musteri)
    tesis = await lokasyon_ac(musteri, ad=f"{ad} Tesisi")
    o = Ortam(musteri=musteri, tesis=tesis)
    o.ekipmanlar["XRAY"] = [
        await ekipman_ac(
            birim=birim, musteri=musteri, lokasyon=tesis, tip="XRAY", seri=f"XR-{ad[:3]}-{i}"
        )
        for i in range(1, xray + 1)
    ]
    o.ekipmanlar["KAPI_DEDEKTORU"] = [
        await ekipman_ac(
            birim=birim,
            musteri=musteri,
            lokasyon=tesis,
            tip="KAPI_DEDEKTORU",
            seri=f"MD-{ad[:3]}-{i}",
        )
        for i in range(1, kapi + 1)
    ]
    return o


def sozlesme_govdesi(o: Ortam, **kw) -> dict[str, Any]:
    govde: dict[str, Any] = {
        "birim": "GUVENLIK",
        "account_id": o.musteri.id,
        "address_id": o.tesis.id,
        "baslangic": "2026-01-01",
        "bitis": "2027-01-01",
        "annual_frequency": 2,
        "kapsam": {
            "XRAY": len(o.ekipmanlar.get("XRAY", [])),
            "KAPI_DEDEKTORU": len(o.ekipmanlar.get("KAPI_DEDEKTORU", [])),
        },
    }
    govde.update(kw)
    return govde


async def sozlesme_ac(client, o: Ortam, *, aktif: bool = True, **kw) -> dict[str, Any]:
    r = await client.post(f"{ONEK}/sozlesmeler", json=sozlesme_govdesi(o, **kw))
    assert r.status_code == 201, r.text
    sozlesme = r.json()
    if aktif:
        r = await client.post(f"{ONEK}/sozlesmeler/{sozlesme['id']}/durum", json={"hedef": "AKTIF"})
        assert r.status_code == 200, r.text
        sozlesme = r.json()
    return sozlesme


async def hepsini_eslestir(client, sozlesme_id: int, o: Ortam) -> dict[str, Any]:
    """Kalemleri tür sırasıyla ortamın ekipmanlarına bağlar (şef onayı)."""
    r = await client.get(f"{ONEK}/sozlesmeler/{sozlesme_id}/eslestirme")
    assert r.status_code == 200, r.text
    havuz = {t: [e.id for e in liste] for t, liste in o.ekipmanlar.items()}
    eslesmeler = []
    for k in r.json()["kalemler"]:
        if k["equipment_id"] is None and havuz.get(k["equipment_type"]):
            eslesmeler.append(
                {"kalem_id": k["kalem_id"], "equipment_id": havuz[k["equipment_type"]].pop(0)}
            )
    r = await client.put(
        f"{ONEK}/sozlesmeler/{sozlesme_id}/eslestirme", json={"eslesmeler": eslesmeler}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def pb_isleri(db, sozlesme_id: int) -> list[ServiceOrder]:
    return list(
        (
            await db.scalars(
                select(ServiceOrder)
                .join(
                    MaintenanceContractItem,
                    MaintenanceContractItem.id == ServiceOrder.contract_item_id,
                )
                .where(
                    MaintenanceContractItem.contract_id == sozlesme_id,
                    ServiceOrder.tur == "PB",
                )
                .order_by(ServiceOrder.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def pb_sayisi(db) -> int:
    return int(
        await db.scalar(select(func.count(ServiceOrder.id)).where(ServiceOrder.tur == "PB")) or 0
    )


async def ata(db, so: ServiceOrder, kisi) -> None:
    db.add(
        ServiceOrderAssignment(
            service_order_id=so.id,
            user_id=kisi.id,
            rol="TEKNISYEN",
            is_lead=True,
            assigned_at=datetime.fromisoformat("2026-01-01T09:00:00+00:00"),
        )
    )
    await db.commit()


def tum_uygun(form: dict[str, Any], **ozel: tuple[str, str | None]) -> list[dict[str, Any]]:
    """Form maddelerini UYGUN işaretler; `ozel={kod: (sonuc, not)}` istisnaları."""
    satirlar = []
    for m in form["maddeler"]:
        sonuc, not_ = ozel.get(m["kod"], ("UYGUN", None))
        satirlar.append({"kod": m["kod"], "sonuc": sonuc, "not": not_})
    return satirlar
