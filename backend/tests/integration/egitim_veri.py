"""Eğitim testleri için veri fabrikası (E08-21; YALNIZ test paketinde).

Kayıtlar ORM ile kurulur (kapsam testinin konusu uç, kurulum değil). İki
birim (GUVENLIK, HABERLESME), birimsiz ve ayrılmış personel, kritik maddeli
kurs gibi kapsam/uyarı testlerinin ihtiyaç duyduğu tipik durumlar burada tek
yerde üretilir; her test dosyası kendi kurulumunu yazsaydı zorunlu alanlar
dosyadan dosyaya ayrışırdı.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    Role,
    TrainingCourse,
    TrainingCriterion,
    TrainingPlan,
    User,
    UserUnit,
)

PAROLA_OZETI = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"


def an(yil: int, ay: int, gun: int, saat: int = 9) -> datetime:
    """UTC an (Türkiye saati = +3)."""
    return datetime(yil, ay, gun, saat, tzinfo=UTC)


async def giris(client, username: str, password: str = "parola1234") -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def personel(
    db,
    ad: str,
    *birimler: str,
    ayrildi: bool = False,
    aktif: bool = True,
    rol: str = "SERVIS_TEKNISYEN",
) -> User:
    """Girişsiz saha personeli; ilk birim birincil."""
    r = await db.scalar(select(Role).where(Role.code == rol))
    kisi = User(
        full_name=ad,
        username=ad.lower().replace(" ", "."),
        password_hash=PAROLA_OZETI,
        role_id=r.id,
        giris_acik=False,
        is_active=aktif and not ayrildi,
        saha_rolu="TEKNISYEN",
        ayrilis_tarihi=date(2025, 12, 31) if ayrildi else None,
        ayrilis_nedeni="ISTIFA" if ayrildi else None,
    )
    db.add(kisi)
    await db.flush()
    kimlik = kisi.id
    for i, b in enumerate(birimler):
        db.add(UserUnit(user_id=kimlik, birim=b, is_primary=i == 0))
    await db.commit()
    db.expire(kisi)
    return await db.scalar(select(User).where(User.id == kimlik))


async def kurs(
    db,
    kod: str,
    *,
    birim: str | None = None,
    kritik: int = 1,
    normal: int = 3,
    aktif: bool = True,
    yenileme_ay: int | None = None,
    esik: Decimal | None = None,
    sinav: int | None = None,
) -> tuple[TrainingCourse, list[TrainingCriterion]]:
    """Kurs + maddeler: önce `kritik` adet kritik madde, sonra `normal` adet."""
    k = TrainingCourse(
        kod=kod,
        baslik=f"{kod} Eğitimi",
        kategori="ISG",
        birim=birim,
        sure_saat=Decimal("2"),
        is_active=aktif,
        yenileme_ay=yenileme_ay,
        gozlem_esik_yuzde=esik,
        sinav_gecme_puani=sinav,
    )
    db.add(k)
    await db.flush()
    maddeler = []
    for i in range(kritik + normal):
        m = TrainingCriterion(
            course_id=k.id, sira=i + 1, metin=f"Madde {i + 1}", is_critical=i < kritik
        )
        db.add(m)
        maddeler.append(m)
    await db.commit()
    for m in maddeler:
        await db.refresh(m)
    await db.refresh(k)
    return k, maddeler


async def plan(
    db,
    kisi: User,
    k: TrainingCourse,
    yil: int,
    *,
    hedef: date | None = None,
    durum: str = "PLANLANDI",
    tamamlandi: date | None = None,
) -> TrainingPlan:
    p = TrainingPlan(
        user_id=kisi.id,
        course_id=k.id,
        plan_yili=yil,
        hedef_tarih=hedef or date(yil, 12, 15),
        status="TAMAMLANDI" if tamamlandi else durum,
        completed_on=tamamlandi,
        durum_gerekcesi="test" if durum in ("ERTELENDI", "IPTAL") else None,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


def puanlar(maddeler, *degerler: int, gerekce: str | None = "görülmedi") -> list[dict]:
    """Madde sırasıyla puan listesi (-1 için gerekçe eklenir)."""
    return [
        {
            "criterion_id": m.id,
            "puan": p,
            **({"gozlenmedi_gerekcesi": gerekce} if p == -1 and gerekce else {}),
        }
        for m, p in zip(maddeler, degerler, strict=False)
    ]
