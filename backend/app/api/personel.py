"""Personel kartı, birim üyeliği, atanabilir personel uçları (TS-002/008/009).

Personel = kullanıcı (E13-05): bu uçlar `users` satırının yalnız PERSONEL
alanlarını okur/yazar. Rol, izin, parola ve giriş aç/kapat burada YOK —
onlar `api/users.py` (`sistem.kullanici`). İK personel kartını düzenlerken
kimseye yetki veremez.

- Okuma `personel.gor`, yazma `personel.yaz`; Excel `personel.gor` +
  `servis_rapor.disaaktar` (KD-06: servis rollerine `rapor.disaaktar` yok).
- Atanabilir personel listesi `servis.gor` ister, `personel.gor` istemez:
  şef planlarken kaynak listesini görür ama personel kartlarını görmez.
- Kapsam: liste `kapsam_personel` ile süzülür; kapsam dışı kart 404 ve
  HİÇBİR yazma yapılmaz (kapsam, yazmadan ÖNCE çözülür).
- `PersonelOut`'ta e-posta, kullanıcı adı, personel notu ve ayrılış nedeni
  YALNIZ `personel.yaz` sahibine döner; diğerlerinde anahtar olarak YOK
  (boş değer değil — "anahtar yok" kuralı, maliyet gizleme emsali).
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbDep, client_ip, require_permission, sayfala
from app.models import User
from app.services import audit, kvkk, yetki
from app.services import export as export_svc
from app.services.teknik_servis import kapsam
from app.services.teknik_servis import personel as svc

router = APIRouter(prefix="/api/personel", tags=["personel"])

Okuyucu = Annotated[User, Depends(require_permission("personel.gor"))]
Yazici = Annotated[User, Depends(require_permission("personel.yaz"))]
Aktarici = Annotated[User, Depends(require_permission("personel.gor", "servis_rapor.disaaktar"))]
Planlayici = Annotated[User, Depends(require_permission("servis.gor"))]

# Yalnız `personel.yaz` sahibine dönen alanlar (E13-05, TS-008).
GIZLI_ALANLAR = ("email", "username", "personel_notu", "ayrilis_nedeni")


# --- Şemalar --------------------------------------------------------------------


class BirimOut(BaseModel):
    birim: str
    birincil: bool


class RolOzet(BaseModel):
    code: str
    name: str


class PersonelOut(BaseModel):
    """Personel kartı. `GIZLI_ALANLAR` yalnız `personel.yaz` sahibinde bulunur."""

    id: int
    full_name: str
    sicil_no: str | None = None
    unvan: str | None = None
    saha_rolu: str | None = None
    ise_giris_tarihi: date | None = None
    ayrilis_tarihi: date | None = None
    is_active: bool
    calisiyor: bool
    giris_acik: bool
    birimler: list[BirimOut] = []
    birincil_birim: str | None = None
    rol: RolOzet
    version: int
    # personel.yaz:
    email: str | None = None
    username: str | None = None
    personel_notu: str | None = None
    ayrilis_nedeni: str | None = None


class BirimSatiriIn(BaseModel):
    # Katalog doğrulaması serviste (400 + anlaşılır mesaj); Literal 422 verirdi.
    birim: str = Field(min_length=1, max_length=20)
    birincil: bool = False


class BirimlerIn(BaseModel):
    birimler: list[BirimSatiriIn] = Field(default_factory=list, max_length=10)


class PersonelIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    sicil_no: str | None = Field(default=None, max_length=30)
    unvan: str | None = Field(default=None, max_length=80)
    saha_rolu: str | None = Field(default=None, max_length=12)
    ise_giris_tarihi: date | None = None
    personel_notu: str | None = Field(default=None, max_length=2000)
    birimler: list[BirimSatiriIn] = Field(default_factory=list, max_length=10)


class PersonelPatch(BaseModel):
    """Yalnız personel alanları; rol/izin/parola/giriş bu uçta YOK."""

    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    sicil_no: str | None = Field(default=None, max_length=30)
    unvan: str | None = Field(default=None, max_length=80)
    saha_rolu: str | None = Field(default=None, max_length=12)
    ise_giris_tarihi: date | None = None
    personel_notu: str | None = Field(default=None, max_length=2000)
    # İyimser kilit ZORUNLU: iki İK uzmanı aynı kartı ezmesin.
    version: int


class AtanabilirOut(BaseModel):
    id: int
    ad: str
    saha_rolu: str
    birimler: list[str]
    birincil_birim: str | None
    giris_acik: bool


class KpiOut(BaseModel):
    kod: str
    baslik: str
    adet: int
    suzgec: dict[str, Any]


# --- Yardımcılar ------------------------------------------------------------------


def _hata(exc: Exception) -> HTTPException:
    """Servis hatalarını HTTP koduna çevirir (00 §1.4 tablosu)."""
    if isinstance(exc, yetki.YetkiHatasi):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, svc.PersonelKapsamDisi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, svc.PersonelKuralHatasi):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


_SERVIS_HATALARI = (
    yetki.YetkiHatasi,
    svc.PersonelKapsamDisi,
    svc.PersonelKuralHatasi,
    svc.PersonelGirdiHatasi,
)


async def _kapsamli_personel(db, personel_id: int, user: User) -> User:
    """Kişiyi KAPSAM FİLTRESİ UYGULANARAK getirir; yoksa 404.

    `db.get()` kapsamı atlar; kart uçları (okuma VE yazma) bu yardımcıdan
    geçer ki kapsam dışı bir kişiye yazma, 404 dönerken arkada gerçekleşmesin.
    """
    stmt = kapsam.kapsam_personel(select(User).where(User.id == personel_id), user, User.id)
    kisi = await db.scalar(stmt)
    if kisi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    return kisi


def _cikti(kisi: User, *, tam: bool) -> dict[str, Any]:
    out = PersonelOut(
        id=kisi.id,
        full_name=kisi.full_name,
        sicil_no=kisi.sicil_no,
        unvan=kisi.unvan,
        saha_rolu=kisi.saha_rolu,
        ise_giris_tarihi=kisi.ise_giris_tarihi,
        ayrilis_tarihi=kisi.ayrilis_tarihi,
        is_active=kisi.is_active,
        calisiyor=bool(kisi.is_active) and kisi.ayrilis_tarihi is None,
        giris_acik=kisi.giris_acik,
        birimler=[BirimOut(birim=u.birim, birincil=u.is_primary) for u in kisi.birimler],
        birincil_birim=kisi.birincil_birim,
        rol=RolOzet(code=kisi.role.code, name=kisi.role.name),
        version=kisi.version,
        email=kisi.email,
        username=kisi.username,
        personel_notu=kisi.personel_notu,
        ayrilis_nedeni=kisi.ayrilis_nedeni,
    )
    return out.model_dump(mode="json", exclude=None if tam else set(GIZLI_ALANLAR))


def _birim_satirlari(satirlar: list[BirimSatiriIn]) -> list[svc.BirimSatiri]:
    return [svc.BirimSatiri(birim=s.birim, birincil=s.birincil) for s in satirlar]


# --- Liste, özet, Excel -------------------------------------------------------------


@router.get("", response_model=None)
async def listele(
    db: DbDep,
    user: Okuyucu,
    response: Response,
    q: str | None = Query(default=None, max_length=100),
    birim: str | None = None,
    birimsiz: bool = False,
    saha_rolu: str | None = None,
    durum: str | None = Query(default=None, description="CALISIYOR | AYRILDI"),
    giris: str | None = Query(default=None, description="ACIK | KAPALI"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Personel listesi (kapsamlı, sayfalı; toplam `X-Toplam-Kayit`)."""
    try:
        stmt = svc.personel_sorgusu(
            user,
            q=q,
            birim=birim,
            birimsiz=birimsiz,
            saha_rolu=saha_rolu,
            durum=durum,
            giris=giris,
        )
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    tam = user.has("personel.yaz")
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [_cikti(k, tam=tam) for (k,) in satirlar]


@router.get("/ozet", response_model=list[KpiOut])
async def ozet(db: DbDep, user: Okuyucu) -> list[KpiOut]:
    """Üst KPI kutuları; her kutunun `suzgec`'i listeye aynen uygulanır."""
    return [KpiOut(**k) for k in await svc.kpi_ozeti(db, user)]


@router.get("/liste.xlsx")
async def disa_aktar(
    request: Request,
    db: DbDep,
    user: Aktarici,
    q: str | None = Query(default=None, max_length=100),
    birim: str | None = None,
    birimsiz: bool = False,
    saha_rolu: str | None = None,
    durum: str | None = None,
    giris: str | None = None,
) -> Response:
    """Personel listesi Excel'i — ekrandaki süzgeçle, kapsamlı.

    Kişisel veri dışa aktarımıdır: denetime `is_personal_data=True` ile yazılır.
    Kullanıcı adı ve e-posta yalnız `personel.yaz` sahibinin dosyasında.
    """
    try:
        stmt = svc.personel_sorgusu(
            user,
            q=q,
            birim=birim,
            birimsiz=birimsiz,
            saha_rolu=saha_rolu,
            durum=durum,
            giris=giris,
        )
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    tam = user.has("personel.yaz")
    kisiler = (await db.scalars(stmt.limit(10_000))).all()

    basliklar = [
        "Ad Soyad",
        "Sicil No",
        "Ünvan",
        "Saha Rolü",
        "Birimler",
        "Birincil Birim",
        "Durum",
        "Giriş",
        "İşe Giriş",
    ]
    if tam:
        basliklar += ["Kullanıcı Adı", "E-posta"]
    tablo = []
    for k in kisiler:
        satir = [
            k.full_name,
            k.sicil_no,
            k.unvan,
            k.saha_rolu,
            ", ".join(k.birim_kodlari),
            k.birincil_birim,
            "Çalışıyor" if k.is_active and k.ayrilis_tarihi is None else "Ayrıldı",
            "Açık" if k.giris_acik else "Kapalı",
            k.ise_giris_tarihi,
        ]
        if tam:
            satir += [k.username, k.email]
        tablo.append(satir)

    await audit.log(
        db,
        "users",
        "personel.disa_aktar",
        new_value={
            "satir": len(tablo),
            "suzgec": {
                "q": q,
                "birim": birim,
                "birimsiz": birimsiz,
                "saha_rolu": saha_rolu,
                "durum": durum,
                "giris": giris,
            },
        },
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=True,
    )
    await db.commit()
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, tablo, "Personel"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="personel.xlsx"'},
    )


# --- Atanabilir personel (TS-009) ----------------------------------------------------


@router.get("/atanabilir", response_model=list[AtanabilirOut])
async def atanabilir(
    db: DbDep,
    user: Planlayici,
    birim: str = Query(min_length=1, max_length=20),
    saha_rolu: Annotated[list[str] | None, Query()] = None,
) -> list[AtanabilirOut]:
    """Bir birime atanabilecek saha personeli (planlama kaynak listesi).

    Ölçüt: aktif, ayrılmamış, saha rolü SEF/TEKNISYEN/STAJYER, birim üyesi.
    Girişsiz personel listede (`giris_acik=false` bayrağıyla). Katalog dışı
    birim 400, kapsam dışı birim 404; teknisyen (`KENDI_ISLERI`) yalnız
    kendisini görür.
    """
    try:
        kisiler = await svc.atanabilir_personel(
            db, user, birim, saha_rolu or svc.ATANABILIR_SAHA_ROLLERI
        )
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    return [AtanabilirOut(**k.__dict__) for k in kisiler]


# --- Kart ------------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
async def olustur(payload: PersonelIn, request: Request, db: DbDep, user: Yazici) -> dict:
    """Girişsiz personel açar (`giris_acik=false`, rastgele parola, SERVIS_TEKNISYEN).

    Giriş daha sonra kullanıcı yönetiminden, geçici parolayla açılır.
    """
    girdi = svc.PersonelGirdisi(
        full_name=payload.full_name,
        sicil_no=payload.sicil_no,
        unvan=payload.unvan,
        saha_rolu=payload.saha_rolu,
        ise_giris_tarihi=payload.ise_giris_tarihi,
        personel_notu=payload.personel_notu,
        birimler=_birim_satirlari(payload.birimler),
    )
    try:
        kisi = await svc.personel_olustur(db, girdi, aktor=user, ip=client_ip(request))
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    await db.commit()
    kisi = await _kapsamli_personel(db, kisi.id, user)
    return _cikti(kisi, tam=True)


@router.get("/{personel_id}", response_model=None)
async def getir(personel_id: int, request: Request, db: DbDep, user: Okuyucu) -> dict:
    """Personel kartı. Kişisel veri okuması KVKK erişim loguna yazılır."""
    kisi = await _kapsamli_personel(db, personel_id, user)
    cikti = _cikti(kisi, tam=user.has("personel.yaz"))
    await kvkk.erisim_kaydet(
        db,
        entity="users",
        entity_id=kisi.id,
        amac="personel kartı",
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return cikti


@router.patch("/{personel_id}", response_model=None)
async def guncelle(
    personel_id: int, payload: PersonelPatch, request: Request, db: DbDep, user: Yazici
) -> dict:
    kisi = await _kapsamli_personel(db, personel_id, user)
    degisiklik = payload.model_dump(exclude_unset=True, exclude={"version"})
    try:
        await svc.personel_guncelle(
            db, kisi, degisiklik, aktor=user, surum=payload.version, ip=client_ip(request)
        )
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    await db.commit()
    return _cikti(await _kapsamli_personel(db, personel_id, user), tam=True)


@router.put("/{personel_id}/birimler", response_model=list[BirimOut])
async def birimleri_yaz(
    personel_id: int, payload: BirimlerIn, request: Request, db: DbDep, user: Yazici
) -> list[BirimOut]:
    """Birim üyeliğini verilen listeye eşitler (TS-002).

    Katalog dışı birim 400; iki birincil 409; kendi birimi 403; üst yetkili
    hedef (ADMIN olmayan aktör) 403; kapsam dışı kişi/birim 404. Kişinin
    oturumları düşer (kapsamı değişti).
    """
    kisi = await _kapsamli_personel(db, personel_id, user)
    try:
        yeni = await svc.birimleri_yaz(
            db, kisi, _birim_satirlari(payload.birimler), aktor=user, ip=client_ip(request)
        )
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    await db.commit()
    return [BirimOut(**s) for s in yeni]


@router.post("/{personel_id}/aktiflestir", response_model=None)
async def aktiflestir(personel_id: int, request: Request, db: DbDep, user: Yazici) -> dict:
    """Ayrılmış personeli yeniden aktifleştirir; giriş hesabını AÇMAZ (E13-03)."""
    kisi = await _kapsamli_personel(db, personel_id, user)
    try:
        await svc.personel_aktiflestir(db, kisi, aktor=user, ip=client_ip(request))
    except _SERVIS_HATALARI as exc:
        raise _hata(exc) from exc
    await db.commit()
    kisi = await _kapsamli_personel(db, personel_id, user)
    return {
        "personel": _cikti(kisi, tam=True),
        "giris_acik": kisi.giris_acik,
        "mesaj": (
            "Personel yeniden aktif. Giriş hesabı ayrıca açılmalı."
            if not kisi.giris_acik
            else "Personel yeniden aktif."
        ),
    }
