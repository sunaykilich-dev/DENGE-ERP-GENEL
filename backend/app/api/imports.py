"""Toplu içe aktarma: profil seç → şablon indir → yükle → önizle → uygula."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, CurrentUser, DbDep, client_ip, require_permission
from app.models import ImportBatch, User
from app.services import audit
from app.services import export as export_svc
from app.services import imports as ice

router = APIRouter(prefix="/api/ice-aktarma", tags=["ice-aktarma"])

Kullanici = CurrentUser
Gormeye = Annotated[User, Depends(require_permission("rapor.gor"))]

MAKS_DOSYA = 10 * 1024 * 1024  # 10 MB ≈ on binlerce satır


class UygulaIn(BaseModel):
    # satır no → "guncelle" | "atla". Belirtilmeyen çakışmalı satır ATLANIR.
    kararlar: dict[int, str] = Field(default_factory=dict)


class ProfilOut(BaseModel):
    kod: str
    ad: str
    aciklama: str
    izin: str
    sutunlar: list[dict]


class PartiOut(BaseModel):
    id: int
    profile: str
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    conflict_rows: int
    created_rows: int
    updated_rows: int
    skipped_rows: int
    # Dosyada bir şey yazıyordu ama tanınan hiçbir sütuna düşmedi; okunamadı.
    dropped_rows: int = 0

    model_config = {"from_attributes": True}


def _profil(kod: str) -> ice.Profil:
    profil = ice.PROFILLER.get(kod)
    if profil is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Bilinmeyen profil: {kod} (geçerli: {', '.join(ice.PROFILLER)})",
        )
    return profil


def _izin_kontrol(user: User, kod: str) -> None:
    """İçe aktarma, ilgili modülün YAZMA iznine tabidir."""
    gereken = ice.PROFIL_IZINLERI[kod]
    if not user.has(gereken):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Bu işlem için yetkiniz yok ({gereken})")


def _ozet(satirlar: list[dict], atilan: int = 0) -> dict[str, int]:
    return {
        "total_rows": len(satirlar),
        "dropped_rows": atilan,
        "error_rows": sum(1 for s in satirlar if s["hatalar"]),
        "conflict_rows": sum(1 for s in satirlar if not s["hatalar"] and s.get("cakisma")),
        "valid_rows": sum(1 for s in satirlar if not s["hatalar"] and not s.get("cakisma")),
    }


@router.get("/profiller", response_model=list[ProfilOut])
async def profiller(user: Kullanici) -> list[ProfilOut]:
    """Kullanıcının YAZABİLDİĞİ profiller. Yetkisi olmayan profil listelenmez."""
    return [
        ProfilOut(
            kod=p.kod,
            ad=p.ad,
            aciklama=p.aciklama,
            izin=ice.PROFIL_IZINLERI[p.kod],
            sutunlar=[
                {
                    "alan": s.alan,
                    "baslik": s.baslik,
                    "zorunlu": s.zorunlu,
                    "aciklama": s.aciklama,
                }
                for s in p.sutunlar
            ],
        )
        for p in ice.PROFILLER.values()
        if user.has(ice.PROFIL_IZINLERI[p.kod])
    ]


@router.get("/profiller/{kod}/sablon.xlsx")
async def sablon(kod: str, user: Kullanici) -> Response:
    """Doldurulup geri yüklenecek boş Excel şablonu."""
    profil = _profil(kod)
    _izin_kontrol(user, kod)
    return Response(
        content=await asyncio.to_thread(ice.sablon_xlsx, profil),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="sablon-{kod}.xlsx"'},
    )


@router.post("/{kod}", status_code=status.HTTP_201_CREATED)
async def yukle(kod: str, file: UploadFile, request: Request, db: DbDep, user: Kullanici) -> dict:
    """Dosyayı ayrıştırır ve doğrular. HİÇBİR ŞEY YAZMAZ — önizleme döner."""
    profil = _profil(kod)
    _izin_kontrol(user, kod)

    icerik = await file.read()
    if len(icerik) > MAKS_DOSYA:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Dosya 10 MB'ı aşamaz")
    try:
        # AYRI İŞ PARÇACIĞINDA: openpyxl saf CPU işi. 20.000 satırlık bir
        # dosyayı olay döngüsünde ayrıştırmak, süresi boyunca TÜM istekleri
        # bekletir — plan §3.5'in "deseni kopyalarken yapılabilecek tek
        # gerçek hata" dediği yer.
        okuma = await asyncio.to_thread(ice.oku, file.filename or "dosya", icerik, profil)
    except ice.DosyaHatasi as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if not okuma.satirlar:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dosyada veri satırı yok")

    sonuclar = await profil.dogrula(db, okuma.satirlar)
    staged = [s.sozluk() for s in sonuclar]
    ozet = _ozet(staged, okuma.atilan)

    parti = ImportBatch(
        profile=kod,
        filename=file.filename or "dosya",
        status="HAZIR",
        staged_rows=staged,
        created_by=user.id,
        **ozet,
    )
    db.add(parti)
    await db.flush()
    await audit.log(
        db,
        "import_batches",
        "yukle",
        entity_id=parti.id,
        new_value={"profil": kod, "dosya": parti.filename, **ozet},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"parti": PartiOut.model_validate(parti), "satirlar": staged}


@router.get("/partiler", response_model=list[PartiOut])
async def partileri_listele(
    db: DbDep,
    user: Gormeye,
    profil: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[PartiOut]:
    stmt = select(ImportBatch).order_by(ImportBatch.id.desc()).limit(limit)
    if profil:
        stmt = stmt.where(ImportBatch.profile == profil)
    return [PartiOut.model_validate(p) for p in (await db.scalars(stmt)).all()]


@router.get("/partiler/{parti_id}")
async def parti_getir(parti_id: int, db: DbDep, user: Kullanici) -> dict:
    parti = await db.get(ImportBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parti bulunamadı")
    _izin_kontrol(user, parti.profile)
    return {"parti": PartiOut.model_validate(parti), "satirlar": parti.staged_rows or []}


@router.post("/partiler/{parti_id}/uygula")
async def uygula(
    parti_id: int,
    payload: UygulaIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Kullanici,
) -> dict:
    """Onaylanan satırları yazar. Tek transaction — yarım parti kalmaz."""
    # SATIR KİLİDİ ŞART. `db.get()` kilitlemiyordu: "Uygula"ya çift tıklama,
    # iki sekme ya da zaman aşımı sonrası tekrar deneme, üç isteğin de
    # `HAZIR` görmesine ve aynı partinin ÜÇ KEZ yazılmasına yol açıyordu
    # (2 satırlık dosya → 6 hesap). Sıralı ikinci istek zaten 409 alıyordu;
    # kaçak yalnız eşzamanlılıktaydı.
    parti = await db.get(ImportBatch, parti_id, with_for_update=True)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parti bulunamadı")
    _izin_kontrol(user, parti.profile)
    if parti.status != "HAZIR":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{parti.status} durumundaki parti yeniden uygulanamaz."
        )

    profil = _profil(parti.profile)
    gecersiz = {k: v for k, v in payload.kararlar.items() if v not in ("guncelle", "atla")}
    if gecersiz:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Karar yalnız 'guncelle' veya 'atla' olabilir"
        )

    try:
        sayac = await profil.yaz(
            db,
            parti.staged_rows or [],
            clock=clock,
            user_id=user.id,
            kararlar=payload.kararlar,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    parti.status = "AKTARILDI"
    parti.applied_at = clock.now()
    parti.applied_by = user.id
    parti.created_rows = sayac["eklendi"]
    parti.updated_rows = sayac["guncellendi"]
    parti.skipped_rows = sayac["atlandi"]

    await audit.log(
        db,
        "import_batches",
        "uygula",
        entity_id=parti.id,
        new_value={"profil": parti.profile, **sayac},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"parti": PartiOut.model_validate(parti), "sonuc": sayac}


@router.post("/partiler/{parti_id}/iptal", response_model=PartiOut)
async def iptal(parti_id: int, request: Request, db: DbDep, user: Kullanici) -> PartiOut:
    parti = await db.get(ImportBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parti bulunamadı")
    _izin_kontrol(user, parti.profile)
    if parti.status != "HAZIR":
        raise HTTPException(status.HTTP_409_CONFLICT, "Yalnız bekleyen parti iptal edilebilir.")

    parti.status = "IPTAL"
    await audit.log(
        db,
        "import_batches",
        "iptal",
        entity_id=parti.id,
        new_value={"dosya": parti.filename},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return PartiOut.model_validate(parti)


@router.get("/partiler/{parti_id}/karantina.xlsx")
async def karantina(parti_id: int, db: DbDep, user: Kullanici) -> Response:
    """Hatalı ve çakışmalı satırlar — ekip düzeltip geri yükler.

    Ham sütunlar AYNEN taşınır; kullanıcı kendi dosyasındaki satırı tanısın
    ve düzeltip doğrudan geri yükleyebilsin diye.
    """
    parti = await db.get(ImportBatch, parti_id)
    if parti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parti bulunamadı")
    _izin_kontrol(user, parti.profile)

    profil = _profil(parti.profile)
    sorunlular = [
        s for s in (parti.staged_rows or []) if s["hatalar"] or s.get("cakisma") or s["uyarilar"]
    ]
    basliklar = ["Satır", "Sorun", "Açıklama"] + [s.baslik for s in profil.sutunlar]
    tablo = []
    for s in sorunlular:
        if s["hatalar"]:
            tip, aciklama = "HATA", " · ".join(s["hatalar"])
        elif s.get("cakisma"):
            tip, aciklama = "ÇAKIŞMA", s["cakisma"]["aciklama"]
        else:
            tip, aciklama = "UYARI", " · ".join(s["uyarilar"])
        tablo.append(
            [s["satir_no"], tip, aciklama] + [s["ham"].get(c.alan, "") for c in profil.sutunlar]
        )

    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, tablo, f"Karantina {parti_id}"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="karantina-parti-{parti_id}.xlsx"'},
    )
