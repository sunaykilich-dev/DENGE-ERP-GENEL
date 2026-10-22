"""Saha zaman / Benim İşlerim testlerinin ortak kurulumu (E09-18, TS-070…078).

Kapsam testleri "iki birimden iki şef" kalıbıyla yazılır: GUVENLIK şefi
GUVENLIK işinin sayacını yönetebilir, HABERLESME şefi aynı kaydı GÖREMEZ (404)
ve DEĞİŞTİREMEZ. Bölümler doğrudan ORM ile kurulur (konu uç, kurulum değil).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import ServiceTimeEntry, User

# Türkiye 10:00 (UTC 07:00) — gün sınırından uzak, okunur saatler.
SABAH = datetime(2026, 3, 10, 7, 0, tzinfo=UTC)
TS = "/api/teknik-servis"


async def giris(client, username: str, password: str = "parola1234") -> None:
    """Aynı istemcide oturumu değiştirir (çerez üzerine yazılır)."""
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


@dataclass
class Ortam:
    tek: User  # Ali Veli — GUVENLIK teknisyeni
    tek2: User  # Ayşe Kaya — GUVENLIK teknisyeni
    sef: User  # GUVENLIK şefi (servis.planla)
    sef_b: User  # HABERLESME şefi (kapsam dışı aktör)
    operasyon: User  # zaman.yaz YOK


async def ortam_kur(db, birimli_kullanici_ac) -> Ortam:
    tek = await birimli_kullanici_ac(
        "tek1", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    tek2 = await birimli_kullanici_ac(
        "tek2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    sef = await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    sef_b = await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"], saha_rolu="SEF")
    operasyon = await birimli_kullanici_ac("operasyon", "SERVIS_OPERASYON", ["GUVENLIK"])
    tek.full_name = "Ali Veli"
    tek2.full_name = "Ayşe Kaya"
    await db.commit()
    return Ortam(tek=tek, tek2=tek2, sef=sef, sef_b=sef_b, operasyon=operasyon)


async def bolum_ac(
    db,
    so,
    kisi: User,
    faaliyet: str,
    bas: datetime,
    bit: datetime | None = None,
    *,
    kaynak: str | None = None,
    **kw: Any,
) -> ServiceTimeEntry:
    bolum = ServiceTimeEntry(
        service_order_id=so.id,
        user_id=kisi.id,
        faaliyet=faaliyet,
        started_at=bas,
        ended_at=bit,
        kaynak=kaynak or ("CANLI" if bit is None else "MANUEL"),
        girildi_at=bit or bas,
        created_by=kisi.id,
        **kw,
    )
    db.add(bolum)
    await db.commit()
    await db.refresh(bolum)
    return bolum


def iso(an: datetime) -> str:
    return an.isoformat()


def dk(n: int) -> timedelta:
    return timedelta(minutes=n)
