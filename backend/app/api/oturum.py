"""Oturumun etkin şirketi — şirket seçici (KARARLAR 2026-11-04 §1).

Yanıt şekli ön yüz paketiyle SÖZLEŞMEDİR (değiştirilmez):

    {"aktif": "TELEKOM",
     "sirketler": [{"kod": "TELEKOM", "ad": "DENGE TELEKOM", "birimler": ["HABERLESME", "POC"]}]}

`sirketler` yalnız kullanıcının seçebileceği AKTİF şirketlerdir (ADMIN: hepsi).
Etkin şirket oturum satırında (`sessions.aktif_sirket`) tutulur; aynı kişinin
iki cihazdaki oturumu birbirini etkilemez. İzin gerektirmez: her oturum kendi
şirketini görür/değiştirir, üyelik kuralı sunucudadır (üye değilse 403).
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import SESSION_COOKIE, CurrentUser, DbDep, client_ip
from app.models import Session
from app.services import audit, sirketler

router = APIRouter(prefix="/api/oturum", tags=["oturum"])


class SirketSatiri(BaseModel):
    kod: str
    ad: str
    birimler: list[str]


class OturumSirketleri(BaseModel):
    aktif: str | None
    sirketler: list[SirketSatiri]


class AktifSirketIn(BaseModel):
    kod: str = Field(min_length=1, max_length=20)


async def _yanit(db, user) -> OturumSirketleri:
    kat = await sirketler.katalog(db)
    secilebilir = set(sirketler.uye_sirketler(user, kat))
    return OturumSirketleri(
        aktif=sirketler.aktif_sirket(user),
        sirketler=[
            SirketSatiri(kod=s.kod, ad=s.ad, birimler=list(s.birimler))
            for s in kat
            if s.kod in secilebilir
        ],
    )


@router.get("/sirketler", response_model=OturumSirketleri)
async def oturum_sirketleri(db: DbDep, user: CurrentUser) -> OturumSirketleri:
    return await _yanit(db, user)


@router.put("/aktif-sirket", response_model=OturumSirketleri)
async def aktif_sirket_degistir(
    payload: AktifSirketIn, request: Request, db: DbDep, user: CurrentUser
) -> OturumSirketleri:
    """Etkin şirketi değiştirir; üye olunmayan/pasif şirket 403 (hiçbir şey yazılmaz)."""
    kat = await sirketler.katalog(db)
    if payload.kod not in sirketler.uye_sirketler(user, kat):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "kod": sirketler.SIRKET_DISI_KODU,
                "mesaj": "Bu şirkete erişiminiz yok. Şirket üyeliği için yöneticinize başvurun.",
            },
        )
    token = request.cookies.get(SESSION_COOKIE)
    sess = await db.get(Session, token) if token else None
    if sess is None:  # pragma: no cover - current_user oturumu zaten doğruladı
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum bulunamadı")
    onceki = sess.aktif_sirket
    if onceki != payload.kod:
        sess.aktif_sirket = payload.kod
        await audit.log(
            db,
            "users",
            "oturum.sirket_degistir",
            entity_id=user.id,
            old_value={"sirket": onceki},
            new_value={"sirket": payload.kod},
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
    await sirketler.oturuma_bagla(db, user, payload.kod)
    return await _yanit(db, user)
