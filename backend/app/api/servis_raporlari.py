"""Teknik servis raporları ve KPI uçları (`/api/teknik-servis/raporlar`).

Maddeler: TS-181, TS-182, TS-184, TS-186, TS-187, TS-201. Doldurur: D3-A
(iskelet + `main.py` kaydı D3-S).

İzinler (KD-06, plan §6.2): ekran `servis.gor` + `servis_rapor.gor`, Excel
`servis.gor` + `servis_rapor.disaaktar`, kişi kırılımı / ham süre / iletişim
kolonları `servis_rapor.personel`; mobilite `rapor.gor`/`rapor.disaaktar`
KULLANILMAZ. Servis raporlarında para alanı YOKTUR (maliyet anahtarı hiçbir
yanıtta yer almaz). Her liste/KPI kapsam fonksiyonlarından geçer (KPI sayısı =
açılan liste `X-Toplam-Kayit`; `/kpi-liste` ve `/isler?kpi=&donem=` aynı süzgeç).

Parametre doğrulaması (kontrol B14): katalog dışı değer `Literal` ile 422;
tarih sırası / 24 ay sınırı 400; kullanıcının birimi olmayan `birim` ve
izinsiz `teknisyen_id` 403. Yolda `{id}` YOK (rapor uçları kayıt açmaz;
iş satırı `/servis-isleri/{id}`'ye gider).

Kayıt sırası: router `main.py`'de genel `/api/teknik-servis` routerından
ÖNCE eklenir (`/isler/{id}` kalıbı `/raporlar/...` yolunu yutmasın).
Kiralama raporları burada DEĞİL, kiralama routerında (TS-195).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission, sayfala
from app.models import Account, Address, ServiceOrder, User
from app.models.teknik_servis import ONCELIKLER, SERVIS_KATEGORILERI, SERVIS_TURLERI
from app.permissions import BIRIMLER
from app.services.normalize import il_normalize
from app.services.teknik_servis import panel
from app.services.teknik_servis import rapor_excel as rx
from app.services.teknik_servis import rapor_hesap as rh
from app.services.teknik_servis import rapor_motoru as rm
from app.services.teknik_servis import rapor_tanimlari as rt
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

router = APIRouter(prefix="/api/teknik-servis/raporlar", tags=["servis-raporlari"])

Okuyucu = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.gor"))]
Kisisel = Annotated[
    User,
    Depends(require_permission("servis.gor", "servis_rapor.gor", "servis_rapor.personel")),
]
Aktarici = Annotated[User, Depends(require_permission("servis.gor", "servis_rapor.disaaktar"))]

Kategori = Literal[SERVIS_KATEGORILERI]  # type: ignore[valid-type]
Birim = Literal[tuple(BIRIMLER)]  # type: ignore[valid-type]
DurumGrubu = Literal[rm.RAPOR_DURUM_GRUPLARI]  # type: ignore[valid-type]
Tur = Literal[SERVIS_TURLERI]  # type: ignore[valid-type]
Oncelik = Literal[ONCELIKLER]  # type: ignore[valid-type]
TarihEsasi = Literal[tuple(rt.TARIH_ESASLARI)]  # type: ignore[valid-type]
Boyut = Literal[tuple(rt.BOYUTLAR)]  # type: ignore[valid-type]
BasitBoyut = Literal[rm.BASIT_BOYUTLAR]  # type: ignore[valid-type]


class RaporParametreleri:
    """Tüm rapor uçlarının ortak sorgu parametreleri (paylaşılabilir URL)."""

    def __init__(
        self,
        baslangic: date | None = None,
        bitis: date | None = None,
        tarih_esasi: TarihEsasi = "ACILIS",  # type: ignore[valid-type]
        kategori: Annotated[list[Kategori] | None, Query()] = None,  # type: ignore[valid-type]
        birim: Annotated[list[Birim] | None, Query()] = None,  # type: ignore[valid-type]
        durum_grubu: Annotated[list[DurumGrubu] | None, Query()] = None,  # type: ignore[valid-type]
        tur: Annotated[list[Tur] | None, Query()] = None,  # type: ignore[valid-type]
        oncelik: Annotated[list[Oncelik] | None, Query()] = None,  # type: ignore[valid-type]
        musteri_id: int | None = Query(default=None, ge=1),
        sef_id: int | None = Query(default=None, ge=1),
        teknisyen_id: int | None = Query(default=None, ge=1),
        sehir: str | None = Query(default=None, max_length=60),
        tekrar_gun: int | None = Query(default=None, ge=rt.TEKRAR_GUN_ALT, le=rt.TEKRAR_GUN_UST),
    ) -> None:
        self.ham = {
            "baslangic": baslangic,
            "bitis": bitis,
            "tarih_esasi": tarih_esasi,
            "kategori": kategori or (),
            "birim": birim or (),
            "durum_grubu": durum_grubu or (),
            "tur": tur or (),
            "oncelik": oncelik or (),
            "musteri_id": musteri_id,
            "sef_id": sef_id,
            "teknisyen_id": teknisyen_id,
            "sehir": sehir,
            "tekrar_gun": tekrar_gun,
        }


Parametreler = Annotated[RaporParametreleri, Depends()]


def _hata(exc: Exception) -> HTTPException:
    if isinstance(exc, rm.RaporYetkiHatasi | PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


_HATALAR = (rm.RaporHatasi, rm.RaporYetkiHatasi, ServisGirdiHatasi, PermissionError)


async def _filtre(db, user: User, clock, p: RaporParametreleri) -> rm.RaporFiltresi:
    try:
        return await rm.filtre_hazirla(db, user, clock, **p.ham)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/tanimlar", response_model=None)
async def tanimlar(user: Okuyucu) -> dict[str, Any]:
    """KPI sözlüğü (ⓘ metinleri), tarih esasları, kırılım boyutları, notlar."""
    return rt.tanimlar(user)


@router.get("/ozet", response_model=None)
async def ozet(db: DbDep, clock: ClockDep, user: Okuyucu, p: Parametreler) -> dict[str, Any]:
    """Yönetim özeti: her KPI'da `kpi` kodu (tıklanınca `/kpi-liste?kpi=`),
    önceki eşit dönem, `generated_at`, `filtreler`, `kapsam`, toplam eşitliği."""
    f = await _filtre(db, user, clock, p)
    try:
        return await rm.ozet(db, user, clock, f)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/kirilim", response_model=None)
async def kirilim(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    p: Parametreler,
    boyut: Boyut = "birim",  # type: ignore[valid-type]
    ikinci: BasitBoyut | None = None,  # type: ignore[valid-type]
) -> dict[str, Any]:
    """Kırılım (birim, kategori, şef, müşteri, şehir, lokasyon, öncelik, çözüm
    kanalı …); `teknisyen` boyutu `servis_rapor.personel` ister (403)."""
    f = await _filtre(db, user, clock, p)
    try:
        return await rm.kirilim(db, user, clock, f, boyut, ikinci)
    except _HATALAR as exc:
        raise _hata(exc) from exc


async def _is_satirlari(db, isler: list[ServiceOrder]) -> list[dict[str, Any]]:
    """KPI listesinin satırları — kişisel/iletişim/para alanı YOK."""
    from app.services.teknik_servis import is_emirleri

    musteriler = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(
                    Account.id.in_({s.customer_id for s in isler if s.customer_id} or {0})
                )
            )
        ).all()
    )
    adresler = {
        a.id: a
        for a in (
            await db.scalars(
                select(Address).where(
                    Address.id.in_({s.address_id for s in isler if s.address_id} or {0})
                )
            )
        ).all()
    }
    satirlar = []
    for s in isler:
        adres = adresler.get(s.address_id) if s.address_id else None
        satirlar.append(
            {
                "id": s.id,
                "so_no": s.so_no,
                "birim": s.birim,
                "birim_adi": BIRIMLER.get(s.birim, s.birim),
                "kategori": s.kategori,
                "kategori_adi": is_emirleri.KATEGORI_ADLARI.get(s.kategori, s.kategori),
                "tur": s.tur,
                "tur_adi": is_emirleri.TUR_ADLARI.get(s.tur, s.tur),
                "oncelik": s.oncelik,
                "durum": s.status,
                "durum_adi": is_emirleri.DURUM_ADLARI.get(s.status, s.status),
                "musteri": musteriler.get(s.customer_id) or s.customer_name_raw,
                "lokasyon": (adres.site_name or adres.label) if adres else s.location_raw,
                "sehir": (il_normalize(adres.city) or adres.city) if adres else None,
                "konu": s.konu,
                "acilis": s.created_at,
                "tamamlanma": s.completed_at,
                "kapanis": s.closed_at,
                "yol": f"/servis-isleri/{s.id}",
            }
        )
    return satirlar


@router.get("/kpi-liste", response_model=None)
async def kpi_liste(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    response: Response,
    p: Parametreler,
    kpi: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=50, ge=1, le=rt.JSON_AZAMI_SATIR),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """KPI kutusunun listesi: `X-Toplam-Kayit` = `/ozet`'teki sayı (aynı sorgu)."""
    if kpi not in panel.KPI_TANIMLARI:
        # Kayıt defteri çalışma anında genişler (D3-E); Literal yerine elle 422.
        raise HTTPException(422, f"Bilinmeyen KPI kodu: {kpi}")
    f = await _filtre(db, user, clock, p)
    try:
        stmt = rm.kpi_liste_sorgusu(user, clock, f, kpi)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await _is_satirlari(db, [s for (s,) in satirlar])


@router.get("/kisi-saat", response_model=None)
async def kisi_saat(db: DbDep, clock: ClockDep, user: Kisisel, p: Parametreler) -> dict[str, Any]:
    """Teknisyen × faaliyet kişi-saat (KİŞİSEL); kaydı olmayan atanmış teknisyen
    "eksik" satırıyla. Toplam satırı kişisel olmayan özetle aynıdır."""
    f = await _filtre(db, user, clock, p)
    try:
        return {
            "satirlar": await rh.kisi_saat_personel(db, user, f),
            "toplam": await rh.kisi_saat_toplami(db, user, f),
            "generated_at": clock.now(),
            "kapsam": rm.kapsam_metni(user),
        }
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/sure-hareketleri", response_model=None)
async def sure_hareketleri(
    db: DbDep,
    clock: ClockDep,
    user: Kisisel,
    response: Response,
    p: Parametreler,
    limit: int = Query(default=50, ge=1, le=rt.JSON_AZAMI_SATIR),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Ham süre satırları (KİŞİSEL, sayfalı; toptan gönderilmez)."""
    f = await _filtre(db, user, clock, p)
    try:
        satirlar, toplam = await rh.sure_hareketleri(db, user, f, limit=limit, offset=offset)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    response.headers["X-Toplam-Kayit"] = str(toplam)
    return satirlar


@router.get("/sla", response_model=None)
async def sla(db: DbDep, clock: ClockDep, user: Okuyucu, p: Parametreler) -> dict[str, Any]:
    """SLA ve bekleme raporu (yalnız günlük servis; ölçülemedi ayrı satır)."""
    f = await _filtre(db, user, clock, p)
    try:
        return await rh.sla_raporu(db, user, clock, f)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/tekrar-ariza", response_model=None)
async def tekrar_ariza(
    db: DbDep, clock: ClockDep, user: Okuyucu, p: Parametreler
) -> dict[str, Any]:
    """Onaylı tekrar arıza (teyit AYNI_ARIZA), onaysız aday, tekrar ziyaret."""
    f = await _filtre(db, user, clock, p)
    try:
        return await rh.tekrar_ariza_raporu(db, user, clock, f)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/yeniden-acilan", response_model=None)
async def yeniden_acilan(
    db: DbDep, clock: ClockDep, user: Okuyucu, p: Parametreler
) -> dict[str, Any]:
    """Yeniden açılan işler (sayı = iş, liste = olay; PB ayrı)."""
    f = await _filtre(db, user, clock, p)
    try:
        return await rh.yeniden_acilan_raporu(db, user, clock, f)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/trend", response_model=None)
async def trend(db: DbDep, clock: ClockDep, user: Okuyucu, p: Parametreler) -> dict[str, Any]:
    """Bitiş ayıyla biten 12 ay: gelen, çözülen, iptal, dönem sonu açık, kişi-saat."""
    f = await _filtre(db, user, clock, p)
    try:
        return await rm.trend(db, user, clock, f)
    except _HATALAR as exc:
        raise _hata(exc) from exc


@router.get("/kitap.xlsx")
async def kitap(
    request: Request, db: DbDep, clock: ClockDep, user: Aktarici, p: Parametreler
) -> Response:
    """Çok sayfalı servis kitabı (eski 8 sayfa + SLA, tekrar arıza, yeniden
    açılan, tanımlar, tipli veri tabloları). Kişisel sayfalar yalnız
    `servis_rapor.personel` ile. İndirme denetime yazılır (commit yanıttan önce).

    `servis_rapor.gor` olmayan aktarıcı (ör. yalnız Excel izni) da özet
    sayfalarını görür: dosya ekranla aynı fonksiyonlardan üretilir."""
    f = await _filtre(db, user, clock, p)
    try:
        icerik, ozet_ = await rx.kitap(db, user, clock, f)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    await rx.disa_aktarim_denetimi(
        db,
        user=user,
        ip=client_ip(request),
        rapor="kitap",
        filtreler=f.iso(),
        satir_sayisi=ozet_["satir_sayisi"],
        kapsam=ozet_["kapsam"],
        kisisel_sayfalar=ozet_["kisisel_sayfalar"],
    )
    await db.commit()
    return Response(
        content=icerik,
        media_type=rx.XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{rx.dosya_adi("servis-raporu", f)}"',
            "X-Toplam-Kayit": str(ozet_["satir_sayisi"]),
        },
    )
