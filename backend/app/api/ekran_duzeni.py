"""Kişisel ekran kutucuk düzeni (2026-11-18, kullanıcı isteği).

`GET/PUT/DELETE /api/ekran-duzeni/{ekran}`: oturumdaki kullanıcının o ekrandaki
kutucuk sırası, boyutu (DAR/GENIS) ve gizlenenleri. Herkes yalnız KENDİ
düzenini görür/yazar; başka bir izin gerekmez (düzen veri açmaz, kutucuk
verisi ekranın kendi ucundan ve iznine göre gelir). Kutucuk kodlarının
kataloğu ön yüzdedir: bilinmeyen kod saklanır ama çizilmez, yeni kutucuk
düzende yoksa varsayılan yerinde görünür.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DbDep
from app.models import EkranDuzeni

router = APIRouter(prefix="/api/ekran-duzeni", tags=["ekran-duzeni"])

EkranKodu = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")]


class Kutu(BaseModel):
    kod: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.:-]+$")
    gizli: bool = False
    boyut: Literal["DAR", "GENIS"] = "DAR"


class DuzenGirdisi(BaseModel):
    kutular: list[Kutu] = Field(max_length=60)


class DuzenYaniti(BaseModel):
    ekran: str
    # null = kişisel düzen yok (ekran varsayılanıyla çizer).
    kutular: list[Kutu] | None


async def _satir(db, user_id: int, ekran: str) -> EkranDuzeni | None:
    return await db.scalar(
        select(EkranDuzeni).where(EkranDuzeni.user_id == user_id, EkranDuzeni.ekran == ekran)
    )


@router.get("/{ekran}", response_model=DuzenYaniti)
async def oku(ekran: EkranKodu, db: DbDep, user: CurrentUser) -> DuzenYaniti:
    satir = await _satir(db, user.id, ekran)
    return DuzenYaniti(ekran=ekran, kutular=None if satir is None else satir.kutular)


@router.put("/{ekran}", response_model=DuzenYaniti)
async def kaydet(
    ekran: EkranKodu, payload: DuzenGirdisi, db: DbDep, user: CurrentUser
) -> DuzenYaniti:
    # Yinelenen kod ilkiyle kalır (sıra kullanıcının sırası).
    tekil: list[dict] = []
    gorulen: set[str] = set()
    for k in payload.kutular:
        if k.kod not in gorulen:
            gorulen.add(k.kod)
            tekil.append(k.model_dump())
    satir = await _satir(db, user.id, ekran)
    if satir is None:
        satir = EkranDuzeni(user_id=user.id, ekran=ekran, kutular=tekil)
        db.add(satir)
    else:
        satir.kutular = tekil
    await db.commit()
    return DuzenYaniti(ekran=ekran, kutular=tekil)


@router.delete("/{ekran}", response_model=DuzenYaniti)
async def sifirla(ekran: EkranKodu, db: DbDep, user: CurrentUser) -> DuzenYaniti:
    """Varsayılan düzene dön (kişisel satır silinir)."""
    await db.execute(
        delete(EkranDuzeni).where(EkranDuzeni.user_id == user.id, EkranDuzeni.ekran == ekran)
    )
    await db.commit()
    return DuzenYaniti(ekran=ekran, kutular=None)
