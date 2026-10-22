"""KVKK: kişisel veri erişim logu, veri bulma, anonimleştirme, saklama."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import User
from app.services import export as export_svc
from app.services import kvkk as svc

router = APIRouter(prefix="/api/kvkk", tags=["kvkk"])

Yonetici = Annotated[User, Depends(require_permission("kvkk.yonet"))]


class AnonimIn(BaseModel):
    gerekce: str = Field(min_length=5, max_length=300)
    # Kullanıcının ne yaptığını bildiğini doğrulayan açık onay: geri alınamaz.
    onay: bool = False


class ErisimOut(BaseModel):
    id: int
    user_id: int | None
    entity: str
    entity_id: str | None
    action: str
    amac: str | None
    ip: str | None
    created_at: datetime


@router.get("/erisim-logu", response_model=list[ErisimOut])
async def erisim_logu(
    db: DbDep,
    user: Yonetici,
    entity: str | None = None,
    entity_id: str | None = None,
    kullanici_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[ErisimOut]:
    """Kişisel veriye kimin, ne zaman, neden eriştiği (brief §8)."""
    return [
        ErisimOut(**k)
        for k in await svc.erisim_gecmisi(
            db, entity=entity, entity_id=entity_id, user_id=kullanici_id, limit=limit
        )
    ]


@router.get("/veri-bul")
async def veri_bul(arama: str, request: Request, db: DbDep, user: Yonetici) -> dict:
    """Silme/erişim talebi için bir kişiye ait tüm kayıtları bulur.

    Aramanın kendisi de kişisel veri erişimidir ve loglanır.
    """
    try:
        sonuc = await svc.veri_bul(db, arama)
    except svc.KvkkHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await svc.erisim_kaydet(
        db,
        entity="kvkk",
        entity_id=None,
        amac=f"Veri bulma talebi: {arama}",
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {**sonuc, "ozet": svc.ozet(sonuc)}


@router.get("/veri-bul.xlsx")
async def veri_bul_xlsx(arama: str, request: Request, db: DbDep, user: Yonetici) -> Response:
    """Talep sahibine verilecek kayıt dökümü."""
    try:
        sonuc = await svc.veri_bul(db, arama)
    except svc.KvkkHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    satirlar: list[list] = []
    for h in sonuc["hesaplar"]:
        satirlar.append(["Hesap", h["id"], h["unvan"], h["telefon"] or "", h["eposta"] or ""])
    for k in sonuc["kisiler"]:
        satirlar.append(["Kişi", k["id"], k["ad"], k["telefon"] or "", k["eposta"] or ""])
    for a in sonuc["araclar"]:
        satirlar.append(["Araç", a["id"], a["plaka"], a["sase"] or "", ""])
    for c in sonuc["cihazlar"]:
        satirlar.append(["Cihaz", c["device_id"], c["kimlik"] or "", c["status"], ""])
    # Teknik servis ana verisi (TS-016): kayıt defterinden gelen tesis ve
    # takma adlar da talep sahibine verilecek dökümde yer almalı.
    for t in sonuc.get("lokasyonlar", []):
        ad = " / ".join(x for x in (t["tesis_adi"], t["adres"], t["il"]) if x)
        satirlar.append(["Lokasyon", t["id"], ad, "", ""])
    for t in sonuc.get("takma_adlar", []):
        satirlar.append(["Takma ad", t["id"], t["metin"], "", ""])
    # Personel (TS-165, E13-D03): çalışan / eski çalışan kaydı.
    for p in sonuc.get("personel", []):
        ad = p["ad"] + (f" (sicil {p['sicil_no']})" if p.get("sicil_no") else "")
        if p.get("ayrildi"):
            ad += " — ayrıldı"
        satirlar.append(["Personel", p["id"], ad, "", p.get("eposta") or ""])

    await svc.erisim_kaydet(
        db,
        entity="kvkk",
        entity_id=None,
        amac=f"Veri dökümü dışa aktarıldı: {arama}",
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return Response(
        content=await export_svc.satirlari_xlsx_async(
            ["Kayıt Tipi", "ID", "Ad / Kimlik", "Telefon / Şase", "E-posta"],
            satirlar,
            "KVKK Veri Dokumu",
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="kvkk-veri-dokumu.xlsx"'},
    )


@router.get("/saklama-suresi-dolanlar")
async def saklama_suresi_dolanlar(
    db: DbDep, clock: ClockDep, user: Yonetici, yil: int | None = Query(default=None, ge=1, le=30)
) -> dict:
    """Saklama süresi dolmuş hareketsiz kayıtlar.

    OTOMATİK SİLİNMEZ — liste çıkarılır, karar insana bırakılır.
    """
    satirlar = await svc.saklama_suresi_dolanlar(db, clock, yil=yil)
    return {"adet": len(satirlar), "kayitlar": satirlar}


@router.post("/hesaplar/{hesap_id}/anonimlestir")
async def anonimlestir(
    hesap_id: int,
    payload: AnonimIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
) -> dict:
    """Hesabı ve bağlı kişi/araç kayıtlarını anonimleştirir. GERİ ALINAMAZ.

    Ticari kayıt (cihaz geçmişi, iş emri, hak ediş) korunur; yalnız kişiyi
    tanımlayan alanlar maskelenir.
    """
    if not payload.onay:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Anonimleştirme geri alınamaz; onay kutusu işaretlenmeden uygulanmaz.",
        )
    try:
        sonuc = await svc.hesabi_anonimlestir(
            db,
            hesap_id,
            clock=clock,
            gerekce=payload.gerekce,
            user_id=user.id,
            ip=client_ip(request),
        )
    except svc.KvkkHatasi as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return sonuc
