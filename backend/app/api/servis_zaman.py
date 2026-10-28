"""Saha zaman kaydı ve Benim İşlerim uçları (TS-070…078).

Yollar (`/api/teknik-servis` öneki):

- `GET /zaman/benim`, `GET /zaman/bugunum`: zaman.yaz
- `POST /zaman/baslat`: zaman.yaz + servis.gor
- `GET /isler/{is_id}/zaman`: servis.gor
- `POST /isler/{is_id}/zaman` (manuel): zaman.yaz + servis.gor (başkası adına /
  eski tarih: servis.planla)
- `POST /isler/{is_id}/zaman/bolumler/{bolum_id}/<eylem>` (gecis, mola, devam,
  bitir, geri-al, unuttum): zaman.yaz, yalnız sahibi
- `POST .../bolumler/{bolum_id}/yonetici-kapat`, `POST /isler/{is_id}/zaman/
  kayitlar/{bolum_id}/iptal`: servis.planla
- `GET /benim-islerim`, `GET /benim-islerim/{is_id}`: servis.gor + zaman.yaz
  (`tumu` görünümü: servis.planla)

**Bölüm uçları neden iş altında:** kapsam taraması (`test_router_kapsam_taramasi`)
her `{id}` ucunu yol parametresinden hedefler; bölüm yolu `is_id` taşıdığı için
kapsam dışı iş kimliğiyle çağrı 404 döner ve hiçbir şey yazılmaz. Bölüm
`(bolum_id, is_id)` çiftiyle bulunur; eşleşmezse 404.

**Sahibi istisnası** (E09 §3.2): kişi KENDİ açık bölümünü iş erişimine ve
atamaya bakılmadan bitirir/geri alır/unuttum ile kapatır. Başkasının bölümü:
iş erişimi yoksa 404 (varlık sızdırılmaz), varsa 403.

**Çift basış:** her bölüm eylemi `version` ister; uyuşmazlık 409 (ikinci istek
artık açık olmayan bölümü gösterir). Her yanıt `sunucu_zamani` taşır
(istemci saat farkı, TS-071). `sistem.kullanici` tek başına hiçbir uca yetmez.

**Konum (G7.8, Faz A):** başlat/geçiş/mola/devam/bitir gövdesi isteğe bağlı
`konum` taşır. Gelmezse ya da koordinatsızsa bölüme "alınamadı" yazılır; uç
konum yüzünden ASLA reddetmez. Koordinatı yalnız bölümün sahibi ve
`servis.planla` sahibi görür; diğerleri yalnız durum metnini görür (KVKK).
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import (
    TOPLAM_BASLIGI,
    ClockDep,
    DbDep,
    client_ip,
    require_permission,
    sayfala,
)
from app.models import ServiceOrder, ServiceTimeEntry, User
from app.models.rbac import BIRIM_KODLARI
from app.permissions import BIRIMLER
from app.services import audit
from app.services import export as export_svc
from app.services.teknik_servis import is_emirleri, kapsam, mobil
from app.services.teknik_servis import zaman as svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis", tags=["servis-zaman"])

ZamanYazici = Annotated[User, Depends(require_permission("zaman.yaz"))]
ZamanServis = Annotated[User, Depends(require_permission("zaman.yaz", "servis.gor"))]
Okuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
Yonetici = Annotated[User, Depends(require_permission("servis.planla"))]
# Zaman Takibi yönetim ekranı (TS-189): mobilite `rapor.gor` DEĞİL (KD-06).
RaporOkuyucu = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.gor"))]
RaporAktarici = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.disaaktar"))]

Faaliyet = Literal["YOL", "SAHA", "UZAKTAN", "ATOLYE", "TEST", "BEKLEME", "MOLA", "DIGER"]
BaslatEylemi = Literal["YOLA_CIKTIM", "SAHAYA_VARDIM", "DIGER"]


# --- Şemalar -----------------------------------------------------------------------


class KonumOut(BaseModel):
    durum: str
    metin: str
    enlem: float | None = None
    boylam: float | None = None
    dogruluk_m: int | None = None


class BolumOut(BaseModel):
    id: int
    version: int
    service_order_id: int
    so_no: str | None = None
    user_id: int | None
    kisi_adi: str | None = None
    faaliyet: str
    bekleme_nedeni: str | None
    started_at: datetime
    ended_at: datetime | None
    sure_dk: int | None
    kaynak: str
    kapanis_turu: str | None
    gerekce: str | None
    onceki_bolum_id: int | None
    girildi_at: datetime
    giren_id: int | None
    giren_adi: str | None = None
    konum_notu: str | None
    aciklama: str | None
    iptal_turu: str | None
    iptal_gerekcesi: str | None
    iptal_eden_id: int | None
    iptal_at: datetime | None
    iptal: bool
    bas_konum: KonumOut | None = None
    bit_konum: KonumOut | None = None


class SureOzetiOut(BaseModel):
    kisi_saat_dk: int | None
    sure_durumu: str
    eksik_kisiler: list[str]
    mola_dk: int | None
    faaliyet_kirilimi: dict[str, int]
    kisi_bazli: dict[int, int]
    ilk_yol_at: datetime | None
    ilk_varis_at: datetime | None
    son_bitis_at: datetime | None
    sapma_dk: int | None
    acik_bolum_sayisi: int


class BolumSonucOut(BaseModel):
    sunucu_zamani: datetime
    bolum: BolumOut
    yeni_bolum: BolumOut | None = None
    is_durumu: str | None = None


class IsZamaniOut(BaseModel):
    sunucu_zamani: datetime
    bolumler: list[BolumOut]
    sure_ozeti: SureOzetiOut


class KonumIn(BaseModel):
    """Tarayıcı `navigator.geolocation` okuması. Koordinat yoksa (izin
    reddi, zaman aşımı) `hata` kodu gönderilebilir; durum ALINAMADI olur."""

    # Aralık dışı değer reddedilmez, "alınamadı" sayılır (işlem engellenmez).
    enlem: float | None = None
    boylam: float | None = None
    dogruluk_m: float | None = None
    hata: str | None = None  # yalnız istemci tanısı; saklanmaz

    def okuma(self) -> svc.KonumOkuma:
        return svc.KonumOkuma(self.enlem, self.boylam, self.dogruluk_m)


def _okuma(konum: "KonumIn | None") -> svc.KonumOkuma | None:
    return konum.okuma() if konum is not None else None


class BaslatIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"is_id": 1, "eylem": "YOLA_CIKTIM"}]}
    )

    is_id: int
    eylem: BaslatEylemi
    # Yalnız eylem=DIGER: masaüstü faaliyetleri (Uzaktan/Atölye/Test/Diğer/Bekleme).
    faaliyet: Faaliyet | None = None
    bekleme_nedeni: str | None = Field(default=None, max_length=30)
    konum_notu: str | None = Field(default=None, max_length=200)
    konum: KonumIn | None = None


class SurumIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"version": 1}]})

    version: int


class KonumluSurumIn(SurumIn):
    konum: KonumIn | None = None


class GecisIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"version": 1, "faaliyet": "SAHA"}]})

    version: int
    faaliyet: Faaliyet
    bekleme_nedeni: str | None = Field(default=None, max_length=30)
    # TS-074: sayacı sonraki işe taşı (aynı ziyaretteki sıradaki cihaz).
    hedef_is_id: int | None = None
    konum: KonumIn | None = None


class BitirIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"version": 1}]})

    version: int
    aciklama: str | None = Field(default=None, max_length=2000)
    konum: KonumIn | None = None


class UnuttumIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"version": 1, "gercek_bitis": "2026-01-15T17:00:00+03:00", "gerekce": "Unuttum"}
            ]
        }
    )

    version: int
    gercek_bitis: datetime
    # Boş gerekçe serviste 400 ile reddedilir (şema 422 değil, okunur mesaj).
    gerekce: str = Field(default="", max_length=300)


class YoneticiKapatIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"version": 1, "gerekce": "Sayaç unutulmuş"}]}
    )

    version: int
    gercek_bitis: datetime | None = None
    # Boş gerekçe serviste 400 ile reddedilir (şema 422 değil, okunur mesaj).
    gerekce: str = Field(default="", max_length=300)


class ManuelIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "faaliyet": "SAHA",
                    "started_at": "2026-01-15T09:00:00+03:00",
                    "ended_at": "2026-01-15T10:00:00+03:00",
                    "gerekce": "Sayaç açılamadı",
                }
            ]
        }
    )

    faaliyet: Faaliyet
    started_at: datetime
    ended_at: datetime
    user_id: int | None = None
    bekleme_nedeni: str | None = Field(default=None, max_length=30)
    gerekce: str | None = Field(default=None, max_length=300)
    konum_notu: str | None = Field(default=None, max_length=200)
    aciklama: str | None = Field(default=None, max_length=2000)


class IptalIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"gerekce": "Yanlış iş"}]})

    # Boş gerekçe serviste 400 ile reddedilir (şema 422 değil, okunur mesaj).
    gerekce: str = Field(default="", max_length=300)


# --- Yardımcılar -----------------------------------------------------------------------

_HATALAR = (
    svc.ZamanYetkiHatasi,
    svc.ZamanKapsamDisi,
    mobil.MobilYetkiHatasi,
    mobil.MobilGirdiHatasi,
    ServisHatasi,
    ServisGirdiHatasi,
)


def _hata(exc: Exception) -> HTTPException:
    """Servis hatalarını HTTP koduna çevirir (plan §1.2 yanıt kodları)."""
    if isinstance(
        exc, svc.ZamanYetkiHatasi | mobil.MobilYetkiHatasi | is_emirleri.IsEmriYetkiHatasi
    ):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, svc.ZamanKapsamDisi | is_emirleri.IsEmriKapsamDisi):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc) or "Kayıt bulunamadı")
    if isinstance(exc, ServisHatasi):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


async def _kapsamli_is(db, user: User, is_id: int, *, kilitle: bool = False) -> ServiceOrder:
    """İşi kapsam süzgeciyle getirir; yoksa/kapsam dışıysa 404 (yazmadan ÖNCE)."""
    stmt = kapsam.kapsam_isler(
        select(ServiceOrder).where(ServiceOrder.id == is_id, ServiceOrder.is_deleted.is_(False)),
        user,
        ServiceOrder.id,
    )
    if kilitle:
        stmt = stmt.with_for_update(of=ServiceOrder)
    so = await db.scalar(stmt)
    if so is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    return so


async def _bolum(db, user: User, is_id: int, bolum_id: int, *, sahibi: bool) -> ServiceTimeEntry:
    """Bölümü `(bolum_id, is_id)` ile kilitleyerek getirir.

    `sahibi=True` (sahip eylemleri): kendi bölümü ise iş erişimine bakılmaz;
    başkasınınsa iş erişimi yoksa 404, varsa 403. `sahibi=False` (yönetici
    eylemleri): iş erişimi zorunlu (404).
    """
    bolum = await db.scalar(
        select(ServiceTimeEntry)
        .where(ServiceTimeEntry.id == bolum_id, ServiceTimeEntry.service_order_id == is_id)
        .with_for_update()
    )
    if sahibi and bolum is not None and bolum.user_id == user.id:
        return bolum
    so = await db.get(ServiceOrder, is_id)
    if bolum is None or so is None or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Süre kaydı bulunamadı")
    if sahibi:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Yalnız kendi sayacınızı yönetebilirsiniz")
    return bolum


def _surum(bolum: ServiceTimeEntry, version: int) -> None:
    if bolum.version != version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Sayaç bu arada değişti (çift basış ya da başka cihaz); ekranı yenileyin.",
        )


async def _adlar(db, kimlikler: set[int | None]) -> dict[int, str]:
    kimlikler = {k for k in kimlikler if k is not None}
    if not kimlikler:
        return {}
    return dict(
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(kimlikler)))).all()
    )


def _konum_out(bolum: ServiceTimeEntry, on: str, koordinat: bool) -> KonumOut | None:
    ozet = svc.konum_ozeti(bolum, on, koordinat=koordinat)
    return KonumOut(**ozet) if ozet is not None else None


async def _bolum_out(
    db,
    bolum: ServiceTimeEntry,
    adlar: dict[int, str] | None = None,
    goren: User | None = None,
) -> BolumOut:
    if adlar is None:
        adlar = await _adlar(db, {bolum.user_id, bolum.created_by})
    so_no = await db.scalar(
        select(ServiceOrder.so_no).where(ServiceOrder.id == bolum.service_order_id)
    )
    sure = (
        round((bolum.ended_at - bolum.started_at).total_seconds() / 60)
        if bolum.ended_at is not None
        else None
    )
    # Koordinat kişisel veridir: yalnız sahibi ve planlayıcı görür.
    koordinat = goren is not None and (bolum.user_id == goren.id or goren.has("servis.planla"))
    return BolumOut(
        id=bolum.id,
        version=bolum.version,
        service_order_id=bolum.service_order_id,
        so_no=so_no,
        user_id=bolum.user_id,
        kisi_adi=adlar.get(bolum.user_id) if bolum.user_id else bolum.kaynak_personel_adi,
        faaliyet=bolum.faaliyet,
        bekleme_nedeni=bolum.bekleme_nedeni,
        started_at=bolum.started_at,
        ended_at=bolum.ended_at,
        sure_dk=sure,
        kaynak=bolum.kaynak,
        kapanis_turu=bolum.kapanis_turu,
        gerekce=bolum.gerekce,
        onceki_bolum_id=bolum.onceki_bolum_id,
        girildi_at=bolum.girildi_at,
        giren_id=bolum.created_by,
        giren_adi=adlar.get(bolum.created_by) if bolum.created_by else None,
        konum_notu=bolum.konum_notu,
        aciklama=bolum.aciklama,
        iptal_turu=bolum.iptal_turu,
        iptal_gerekcesi=bolum.iptal_gerekcesi,
        iptal_eden_id=bolum.deleted_by,
        iptal_at=bolum.deleted_at,
        iptal=bolum.is_deleted,
        bas_konum=_konum_out(bolum, "bas", koordinat),
        bit_konum=_konum_out(bolum, "bit", koordinat),
    )


def _ozet_out(ozet: svc.SureOzeti) -> SureOzetiOut:
    return SureOzetiOut(
        kisi_saat_dk=ozet.kisi_saat_dk,
        sure_durumu=ozet.sure_durumu,
        eksik_kisiler=list(ozet.eksik_kisiler),
        mola_dk=ozet.mola_dk,
        faaliyet_kirilimi=dict(ozet.faaliyet_kirilimi),
        kisi_bazli=dict(ozet.kisi_bazli),
        ilk_yol_at=ozet.ilk_yol_at,
        ilk_varis_at=ozet.ilk_varis_at,
        son_bitis_at=ozet.son_bitis_at,
        sapma_dk=ozet.sapma_dk,
        acik_bolum_sayisi=ozet.acik_bolum_sayisi,
    )


async def _sonuc(
    db,
    clock,
    bolum: ServiceTimeEntry,
    yeni: ServiceTimeEntry | None = None,
    goren: User | None = None,
) -> BolumSonucOut:
    hedef = yeni or bolum
    durum = await db.scalar(
        select(ServiceOrder.status).where(ServiceOrder.id == hedef.service_order_id)
    )
    return BolumSonucOut(
        sunucu_zamani=clock.now(),
        bolum=await _bolum_out(db, bolum, goren=goren),
        yeni_bolum=await _bolum_out(db, yeni, goren=goren) if yeni is not None else None,
        is_durumu=durum,
    )


# --- Benim sayacım / Bugünüm ----------------------------------------------------------


@router.get("/zaman/benim", response_model=None)
async def benim_sayacim(db: DbDep, clock: ClockDep, user: ZamanYazici) -> dict[str, Any]:
    """Hafif uç (bant ve kart): açık bölüm + izinli düğmeler + `sunucu_zamani`.
    Süre özeti hesaplanmaz (M09-15 özü)."""
    return await mobil.benim_sayacim(db, user, clock)


@router.get("/zaman/bugunum", response_model=None)
async def bugunum(
    db: DbDep,
    clock: ClockDep,
    user: ZamanYazici,
    gun: date | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """ "Bugünüm": yalnız kendi bölümleri, toplamlar, gün sonu süre eksik listesi.

    Başkasının günü bu uçtan okunamaz: `user_id` verilirse 422 (sessizce yok
    sayılsaydı istemci başkasının gününü gördüğünü sanırdı).
    """
    if user_id is not None:
        raise HTTPException(
            422,
            "Bugünüm yalnız kendi kayıtlarınızı gösterir; kişi seçilemez",
        )
    try:
        return await mobil.bugunum(db, user, clock, gun=gun)
    except _HATALAR as exc:
        raise _hata(exc) from exc


# --- Canlı sayaç -------------------------------------------------------------------------


@router.post("/zaman/baslat", response_model=BolumSonucOut, status_code=status.HTTP_201_CREATED)
async def baslat(payload: BaslatIn, db: DbDep, clock: ClockDep, user: ZamanServis) -> BolumSonucOut:
    """Yola Çıktım → YOL, Sahaya Vardım → SAHA, Diğer → seçilen faaliyet.

    Açık bölüm varken 409 ("Önce açık sayacı bitirin: SRV-…"); kapalı/beklemedeki
    işte 409; atanmamış işte 400; kapsam dışı iş 404.
    """
    so = await _kapsamli_is(db, user, payload.is_id, kilitle=True)
    if payload.eylem == "DIGER":
        if payload.faaliyet is None or payload.faaliyet in ("MOLA",):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Başlatılacak faaliyeti seçin")
        faaliyet = payload.faaliyet
    else:
        faaliyet = {"YOLA_CIKTIM": "YOL", "SAHAYA_VARDIM": "SAHA"}[payload.eylem]
    try:
        bolum = await svc.baslat(
            db,
            so,
            faaliyet,
            user=user,
            clock=clock,
            konum_notu=payload.konum_notu,
            bekleme_nedeni=payload.bekleme_nedeni,
            konum=_okuma(payload.konum),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum, goren=user)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/bolumler/{bolum_id}/gecis", response_model=BolumSonucOut)
async def gecis(
    is_id: int,
    bolum_id: int,
    payload: GecisIn,
    db: DbDep,
    clock: ClockDep,
    user: ZamanYazici,
) -> BolumSonucOut:
    """Faaliyet değiştir; `hedef_is_id` ile sonraki işe taşı (TS-074)."""
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=True)
    _surum(bolum, payload.version)
    hedef = None
    if payload.hedef_is_id is not None:
        hedef = await _kapsamli_is(db, user, payload.hedef_is_id, kilitle=True)
    try:
        yeni = await svc.gecis(
            db,
            bolum,
            payload.faaliyet,
            user=user,
            clock=clock,
            hedef_is=hedef,
            bekleme_nedeni=payload.bekleme_nedeni,
            konum=_okuma(payload.konum),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum, yeni, goren=user)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/bolumler/{bolum_id}/mola", response_model=BolumSonucOut)
async def mola(
    is_id: int,
    bolum_id: int,
    payload: KonumluSurumIn,
    db: DbDep,
    clock: ClockDep,
    user: ZamanYazici,
) -> BolumSonucOut:
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=True)
    _surum(bolum, payload.version)
    try:
        yeni = await svc.mola(db, bolum, user=user, clock=clock, konum=_okuma(payload.konum))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum, yeni, goren=user)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/bolumler/{bolum_id}/devam", response_model=BolumSonucOut)
async def devam(
    is_id: int,
    bolum_id: int,
    payload: KonumluSurumIn,
    db: DbDep,
    clock: ClockDep,
    user: ZamanYazici,
) -> BolumSonucOut:
    """Mola/bekleme sonrası: son mola dışı faaliyet SUNUCUDA bulunur."""
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=True)
    _surum(bolum, payload.version)
    try:
        yeni = await svc.devam(db, bolum, user=user, clock=clock, konum=_okuma(payload.konum))
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum, yeni, goren=user)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/bolumler/{bolum_id}/bitir", response_model=BolumSonucOut)
async def bitir(
    is_id: int, bolum_id: int, payload: BitirIn, db: DbDep, clock: ClockDep, user: ZamanYazici
) -> BolumSonucOut:
    """Sahibi bitirir — atama/erişim aranmaz (iş IPTAL'e alınmış olsa bile)."""
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=True)
    _surum(bolum, payload.version)
    try:
        await svc.bitir(
            db,
            bolum,
            user=user,
            clock=clock,
            aciklama=payload.aciklama,
            konum=_okuma(payload.konum),
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum, goren=user)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/bolumler/{bolum_id}/geri-al", response_model=BolumSonucOut)
async def geri_al(
    is_id: int, bolum_id: int, payload: SurumIn, db: DbDep, clock: ClockDep, user: ZamanYazici
) -> BolumSonucOut:
    """İlk 5 dakikada "Yanlış başlattım" (iz bırakır, kişi-saate girmez)."""
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=True)
    _surum(bolum, payload.version)
    try:
        await svc.geri_al(db, bolum, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/bolumler/{bolum_id}/unuttum", response_model=BolumSonucOut)
async def unuttum(
    is_id: int, bolum_id: int, payload: UnuttumIn, db: DbDep, clock: ClockDep, user: ZamanYazici
) -> BolumSonucOut:
    """Sahibi gerçek bitiş + gerekçeyle kapatır (KULLANICI_DUZELTMESI)."""
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=True)
    _surum(bolum, payload.version)
    try:
        await svc.unuttum(db, bolum, payload.gercek_bitis, payload.gerekce, user=user, clock=clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum)
    await db.commit()
    return sonuc


@router.post(
    "/isler/{is_id}/zaman/bolumler/{bolum_id}/yonetici-kapat", response_model=BolumSonucOut
)
async def yonetici_kapat(
    is_id: int,
    bolum_id: int,
    payload: YoneticiKapatIn,
    db: DbDep,
    clock: ClockDep,
    user: Yonetici,
) -> BolumSonucOut:
    """Uzun sayacı yönetici kapatır: gerçek bitiş varsa düzeltme, yoksa iptal."""
    bolum = await _bolum(db, user, is_id, bolum_id, sahibi=False)
    _surum(bolum, payload.version)
    try:
        await svc.yonetici_kapat(
            db, bolum, payload.gercek_bitis, payload.gerekce, user=user, clock=clock
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, bolum)
    await db.commit()
    return sonuc


# --- İş zaman çizelgesi ve manuel kayıt ------------------------------------------------------


@router.get("/isler/{is_id}/zaman", response_model=IsZamaniOut)
async def is_zamani(is_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> IsZamaniOut:
    """İşin bütün bölümleri (iptaller dahil, işaretli) ve `sure_ozeti` (tek kaynak)."""
    so = await _kapsamli_is(db, user, is_id)
    bolumler = (
        await db.scalars(
            select(ServiceTimeEntry)
            .where(ServiceTimeEntry.service_order_id == so.id)
            .order_by(ServiceTimeEntry.started_at, ServiceTimeEntry.id)
        )
    ).all()
    adlar = await _adlar(db, {b.user_id for b in bolumler} | {b.created_by for b in bolumler})
    return IsZamaniOut(
        sunucu_zamani=clock.now(),
        bolumler=[await _bolum_out(db, b, adlar, goren=user) for b in bolumler],
        sure_ozeti=_ozet_out(await svc.sure_ozeti(db, so.id)),
    )


@router.post(
    "/isler/{is_id}/zaman", response_model=BolumSonucOut, status_code=status.HTTP_201_CREATED
)
async def manuel_kayit(
    is_id: int,
    payload: ManuelIn,
    db: DbDep,
    clock: ClockDep,
    user: ZamanServis,
) -> BolumSonucOut:
    """Elle süre kaydı. Başkası adına ya da geri gün sınırından eski: `servis.planla`."""
    so = await _kapsamli_is(db, user, is_id, kilitle=True)
    if payload.user_id is not None and payload.user_id != user.id:
        if not user.has("servis.planla"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Başkası adına süre kaydı için yetkiniz yok"
            )
        if await kapsam.personel_disinda_mi(db, user, payload.user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    girdi = svc.ManuelKayitGirdisi(
        faaliyet=payload.faaliyet,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        user_id=payload.user_id,
        bekleme_nedeni=payload.bekleme_nedeni,
        gerekce=payload.gerekce,
        konum_notu=payload.konum_notu,
        aciklama=payload.aciklama,
    )
    try:
        kayit = await svc.manuel_kaydet(db, so, girdi, user, clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, kayit)
    await db.commit()
    return sonuc


@router.post("/isler/{is_id}/zaman/kayitlar/{bolum_id}/iptal", response_model=BolumSonucOut)
async def kayit_iptal(
    is_id: int, bolum_id: int, payload: IptalIn, db: DbDep, clock: ClockDep, user: Yonetici
) -> BolumSonucOut:
    """Kapalı kaydı gerekçeyle iptal eder (satır silinmez, iş geçmişine DUZELTME)."""
    kayit = await _bolum(db, user, is_id, bolum_id, sahibi=False)
    try:
        await svc.kaydi_iptal_et(db, kayit, payload.gerekce, user, clock)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    sonuc = await _sonuc(db, clock, kayit)
    await db.commit()
    return sonuc


# --- Benim İşlerim ---------------------------------------------------------------------------


@router.get("/benim-islerim", response_model=None)
async def benim_islerim(
    db: DbDep,
    clock: ClockDep,
    user: ZamanServis,
    gorunum: Literal["benim", "tumu"] = "benim",
    gun: date | None = None,
) -> dict[str, Any]:
    """Teknisyenin tek mobil ekranı: GECIKEN/BUGUN/YARIN/SONRA/PLANSIZ grupları,
    ziyaret kartları, açık sayaç ve `sunucu_zamani`."""
    try:
        return await mobil.benim_islerim(db, user, clock, gun=gun, gorunum=gorunum)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/benim-islerim/{is_id}", response_model=None)
async def benim_isim(is_id: int, db: DbDep, clock: ClockDep, user: ZamanServis) -> dict[str, Any]:
    """Tek sayfa iş kartı (fiyat/maliyet alanı yok; kapsam dışı 404)."""
    so = await _kapsamli_is(db, user, is_id)
    return await mobil.is_karti(db, user, clock, so)


# --- Zaman Takibi yönetim ekranı (TS-189, E09-14/15) -------------------------------
#
# Kişi alanları (kişi adı, `user_id`, konum notu, gerekçe, personel dağılımı,
# kişi süzgeci, Excel "Personel" sayfası) yalnız `servis_rapor.personel` ile;
# izinsizde anahtar olarak YOK (TS-182). Liste/sayı/Excel aynı servis
# sorgusundan: KPI adedi = `X-Toplam-Kayit`, dakika = `X-Toplam-Dakika`.

KayitKpi = Literal["kisi_saat", "yol", "saha", "bekleme", "mola", "aktif_sayac", "uzun_sayac"]
IsKpi = Literal["farkli_is", "sure_eksik"]


def _personel_mi(user: User) -> bool:
    return user.has("servis_rapor.personel")


async def _suzgec(
    db,
    clock,
    user: User,
    *,
    bas: date | None,
    bit: date | None,
    birim: str | None,
    kullanici_id: int | None,
    faaliyet: str | None,
) -> svc.ZamanSuzgeci:
    """Süzgeç doğrulaması: yetkisiz birim 403, kişi süzgeci izinsiz 403 /
    kapsam dışı kişi 404, tarih hatası 400 (plan TS-181 yanıt kodları)."""
    if birim in ("", None):
        birim = None
    elif birim not in BIRIM_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {birim}")
    elif kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bu birimin verisini göremezsiniz")
    if kullanici_id is not None:
        if not _personel_mi(user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Kişi bazlı süzgeç için yetkiniz yok (servis_rapor.personel)",
            )
        if await kapsam.personel_disinda_mi(db, user, kullanici_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Personel bulunamadı")
    try:
        return await svc.zaman_suzgeci(
            db,
            clock,
            bas=bas,
            bit=bit,
            birim=birim,
            kullanici_id=kullanici_id,
            faaliyet=faaliyet,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc


def _kisisiz(user: User, satirlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return satirlar if _personel_mi(user) else svc.kisi_alanlari_cikar(satirlar)


@router.get("/zaman/ozet", response_model=None)
async def zaman_ozeti(
    db: DbDep,
    clock: ClockDep,
    user: RaporOkuyucu,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = Query(default=None, max_length=20),
    kullanici_id: int | None = None,
    faaliyet: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    """KPI kutuları + (yalnız `servis_rapor.personel`) personel dağılımı.

    Parametresiz: son `zaman_rapor_varsayilan_gun` (31) gün. Personel izni
    yoksa `personel` anahtarı yanıtta YOK.
    """
    f = await _suzgec(
        db, clock, user, bas=bas, bit=bit, birim=birim, kullanici_id=kullanici_id,
        faaliyet=faaliyet,
    )  # fmt: skip
    sonuc: dict[str, Any] = {
        "sunucu_zamani": clock.now(),
        "suzgec": f.iso(),
        "kpi": await svc.zaman_ozeti(db, user, f, clock),
    }
    if _personel_mi(user):
        sonuc["personel"] = await svc.personel_dagilimi(db, user, f)
    return sonuc


@router.get("/zaman/aktif", response_model=None)
async def aktif_sayaclar(
    db: DbDep,
    clock: ClockDep,
    user: RaporOkuyucu,
    birim: str | None = Query(default=None, max_length=20),
    kullanici_id: int | None = None,
) -> dict[str, Any]:
    """ "Şu an çalışanlar": açık sayaçlar (kapsamlı; tarih süzgecinden bağımsız).
    Uzun sayaç satırı `uzun=true`; yönetici kapat/düzelt `servis.planla` ister."""
    f = await _suzgec(
        db, clock, user, bas=None, bit=None, birim=birim, kullanici_id=kullanici_id,
        faaliyet=None,
    )  # fmt: skip
    stmt = await svc.kpi_kayit_sorgusu(db, user, f, "aktif_sayac", clock)
    bolumler = (await db.scalars(stmt.order_by(ServiceTimeEntry.started_at))).all()
    satirlar = await svc.kayit_satirlari(db, bolumler, clock)
    return {"sunucu_zamani": clock.now(), "sayaclar": _kisisiz(user, satirlar)}


@router.get("/zaman/kayitlar", response_model=None)
async def zaman_kayitlari(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: RaporOkuyucu,
    kpi: KayitKpi | None = None,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = Query(default=None, max_length=20),
    kullanici_id: int | None = None,
    faaliyet: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Ayrıntı tablosu (sunucu sayfalaması). `kpi=` ile KPI kutusunun listesi;
    katalog dışı `kpi` 422. `X-Toplam-Dakika` = kapanmış bölüm dakika toplamı."""
    f = await _suzgec(
        db, clock, user, bas=bas, bit=bit, birim=birim, kullanici_id=kullanici_id,
        faaliyet=faaliyet,
    )  # fmt: skip
    stmt = (
        await svc.kpi_kayit_sorgusu(db, user, f, kpi, clock)
        if kpi is not None
        else svc.kayit_sorgusu(user, f)
    )
    _, dakika = await svc.adet_ve_dakika(db, stmt)
    satirlar = await sayfala(
        db,
        response,
        stmt.order_by(ServiceTimeEntry.started_at.desc()),
        limit=limit,
        offset=offset,
    )
    response.headers[svc.DAKIKA_BASLIGI] = "" if dakika is None else str(dakika)
    bolumler = [s[0] for s in satirlar]
    return _kisisiz(user, await svc.kayit_satirlari(db, bolumler, clock))


@router.get("/zaman/isler", response_model=None)
async def zaman_isleri(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: RaporOkuyucu,
    kpi: IsKpi,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = Query(default=None, max_length=20),
    kullanici_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """İş KPI'larının listesi (farklı iş, süre kaydı eksik); sayı = `X-Toplam-Kayit`."""
    f = await _suzgec(
        db, clock, user, bas=bas, bit=bit, birim=birim, kullanici_id=kullanici_id,
        faaliyet=None,
    )  # fmt: skip
    try:
        stmt = svc.kpi_is_sorgusu(user, f, kpi)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await svc.is_satirlari(db, [s[0] for s in satirlar])


_KAYIT_SUTUNLARI = [
    export_svc.Sutun("İş No"),
    export_svc.Sutun("Birim"),
    export_svc.Sutun("Faaliyet"),
    export_svc.Sutun("Bekleme Nedeni"),
    export_svc.Sutun("Başlangıç", "zaman"),
    export_svc.Sutun("Bitiş", "zaman"),
    export_svc.Sutun("Süre (dk)", "tamsayi"),
    export_svc.Sutun("Kaynak"),
    export_svc.Sutun("Kapanış"),
    export_svc.Sutun("Girildi", "zaman"),
    export_svc.Sutun("Gecikmeli Manuel"),
]
_KAYIT_KISI_SUTUNLARI = [
    export_svc.Sutun("Personel"),
    export_svc.Sutun("Konum Notu"),
    export_svc.Sutun("Gerekçe"),
]
_PERSONEL_SUTUNLARI = [
    export_svc.Sutun("Personel"),
    export_svc.Sutun("Kişi-saat (dk)", "tamsayi"),
    export_svc.Sutun("Yol (dk)", "tamsayi"),
    export_svc.Sutun("Saha (dk)", "tamsayi"),
    export_svc.Sutun("Bekleme (dk)", "tamsayi"),
    export_svc.Sutun("Mola (dk, hariç)", "tamsayi"),
    export_svc.Sutun("İş Sayısı", "tamsayi"),
    export_svc.Sutun("Canlı Oranı (%)", "ondalik"),
    export_svc.Sutun("Manuel", "tamsayi"),
    export_svc.Sutun("Gecikmeli Manuel", "tamsayi"),
    export_svc.Sutun("Düzeltilen", "tamsayi"),
    export_svc.Sutun("İptal", "tamsayi"),
    export_svc.Sutun("Geri Alınan", "tamsayi"),
]


@router.get("/zaman/kayitlar.xlsx")
async def zaman_excel(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: RaporAktarici,
    kpi: KayitKpi | None = None,
    bas: date | None = None,
    bit: date | None = None,
    birim: str | None = Query(default=None, max_length=20),
    kullanici_id: int | None = None,
    faaliyet: str | None = Query(default=None, max_length=20),
) -> Response:
    """Ekranla AYNI süzgeç: "Süre Kayıtları" + "Özet" (+ izinliyse "Personel").

    Kayıt yoksa süre hücresi BOŞ (0 değil). Formül enjeksiyonu kapalı
    (`export.sayfalari_xlsx_async`). Dışa aktarım denetime yazılır; kişi
    sütunu/sayfası varsa `is_personal_data=True`.
    """
    f = await _suzgec(
        db, clock, user, bas=bas, bit=bit, birim=birim, kullanici_id=kullanici_id,
        faaliyet=faaliyet,
    )  # fmt: skip
    stmt = (
        await svc.kpi_kayit_sorgusu(db, user, f, kpi, clock)
        if kpi is not None
        else svc.kayit_sorgusu(user, f)
    )
    adet, _ = await svc.adet_ve_dakika(db, stmt)
    if adet > svc.ZAMAN_EXCEL_UST_SINIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{adet} kayıt var; Excel en çok {svc.ZAMAN_EXCEL_UST_SINIR} satır alır, "
            "süzgeci daraltın",
        )
    personel = _personel_mi(user)
    bolumler = (
        await db.scalars(stmt.order_by(ServiceTimeEntry.started_at, ServiceTimeEntry.id))
    ).all()
    satirlar = await svc.kayit_satirlari(db, bolumler, clock)
    tablo = []
    for s in satirlar:
        satir = [
            s["so_no"],
            BIRIMLER.get(s["birim"], s["birim"]),
            svc.FAALIYET_ADLARI.get(s["faaliyet"], s["faaliyet"]),
            s["bekleme_nedeni"],
            s["started_at"],
            s["ended_at"],
            s["sure_dk"],
            s["kaynak"],
            s["kapanis_turu"],
            s["girildi_at"],
            "Evet" if s["gecikmeli"] else "",
        ]
        if personel:
            satir += [s["kisi_adi"], s["konum_notu"], s["gerekce"]]
        tablo.append(satir)
    ozet = await svc.zaman_ozeti(db, user, f, clock)
    ozet_satirlari = [[k["baslik"], k["deger"], k["adet"], k["tanim"]] for k in ozet]
    sayfalar = [
        export_svc.Sayfa(
            "Süre Kayıtları",
            list(_KAYIT_SUTUNLARI) + (list(_KAYIT_KISI_SUTUNLARI) if personel else []),
            tablo,
        ),
        export_svc.Sayfa(
            "Özet",
            [
                export_svc.Sutun("Gösterge"),
                export_svc.Sutun("Değer", "ondalik"),
                export_svc.Sutun("Kayıt Sayısı", "tamsayi"),
                export_svc.Sutun("Tanım"),
            ],
            ozet_satirlari,
        ),
    ]
    if personel:
        kisiler = await svc.personel_dagilimi(db, user, f)
        sayfalar.append(
            export_svc.Sayfa(
                "Personel",
                list(_PERSONEL_SUTUNLARI),
                [
                    [
                        k["ad"],
                        k["kisi_saat_dk"],
                        k["yol_dk"],
                        k["saha_dk"],
                        k["bekleme_dk"],
                        k["mola_dk"],
                        k["is_sayisi"],
                        k["canli_orani"],
                        k["manuel_sayisi"],
                        k["gecikmeli_manuel_sayisi"],
                        k["duzeltilen_sayisi"],
                        k["iptal_sayisi"],
                        k["geri_alinan_sayisi"],
                    ]
                    for k in kisiler
                ],
            )
        )
    icerik = await export_svc.sayfalari_xlsx_async(sayfalar)
    await audit.log(
        db,
        "service_time_entries",
        "zaman.disa_aktar",
        new_value={**f.iso(), "kpi": kpi, "satir": len(tablo), "personel_sayfasi": personel},
        user_id=user.id,
        ip=client_ip(request),
        is_personal_data=personel,
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="zaman-takibi-{f.bas:%Y%m%d}-{f.bit:%Y%m%d}.xlsx"'
            ),
            TOPLAM_BASLIGI: str(len(tablo)),
        },
    )
