"""Yönetim dashboard'u ve raporlar.

Her rapor aynı deseni izler: JSON uç + aynı verinin `.xlsx` hali. Excel
çıktısını ayrı bir sorgudan üretmek, ekranda görünen ile indirilen rakamın
ayrışması demekti.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import (
    ClockDep,
    CurrentUser,
    DbDep,
    client_ip,
    donem_dogrula,
    require_permission,
    sees_cost,
)
from app.models import User
from app.services import audit
from app.services import export as export_svc
from app.services import reports as svc
from app.services import rma as rma_svc
from app.services import stock as stok_svc
from app.services import subscriptions as abonelik_svc

router = APIRouter(prefix="/api/raporlar", tags=["rapor"])
# Şirket ayrımı (KARARLAR 2026-11-04 §1): `router` mobilite raporlarıdır ve
# `main.py`'de DENGE MOBİLİTE kapısıyla dahil edilir. Uyarı zili bütün
# modüllerin (teknik servis dahil) ORTAK ucudur; kapısız ayrı yönlendiricide
# durur, mobilite satırlarını `services/uyarilar.topla` şirketle süzer.
ortak_router = APIRouter(prefix="/api/raporlar", tags=["rapor"])

Okuyucu = Annotated[User, Depends(require_permission("rapor.gor"))]
Aktarici = Annotated[User, Depends(require_permission("rapor.disaaktar"))]


async def _xlsx(
    basliklar: list[str],
    satirlar: list[list[Any]],
    ad: str,
    *,
    db: DbDep,
    user: User,
    request: Request,
) -> Response:
    """xlsx yanıtı + denetim satırı (TS-218, E12 K9).

    Mobilite raporlarının Excel'i (müşteri geliri, hak ediş tutarları,
    stok maliyeti) toplu veri çıkışıdır; teknik servis Excel'leri gibi kim,
    ne zaman, kaç satır indirdi denetimde görünmeli. Satır yanıttan ÖNCE
    commit edilir: dosya üretildi ama iz yok durumu oluşmasın."""
    await audit.log(
        db,
        "raporlar",
        "disa_aktar",
        new_value={"rapor": ad, "satir": len(satirlar)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return Response(
        content=await export_svc.satirlari_xlsx_async(basliklar, satirlar, ad[:31]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{ad}.xlsx"'},
    )


def _maliyet_gizle(satirlar: list[dict], alanlar: tuple[str, ...], user: User) -> list[dict]:
    """Maliyet alanlarını yetkisiz kullanıcıdan gizler (plan §3.4)."""
    if sees_cost(user):
        return satirlar
    return [{**s, **{a: None for a in alanlar if a in s}} for s in satirlar]


@router.get("/dashboard")
async def dashboard(db: DbDep, clock: ClockDep, user: Okuyucu) -> dict:
    """Yönetim panelinin özeti (brief §4.14)."""
    veri = await svc.dashboard(db, clock)
    if not sees_cost(user):
        veri["stok_degeri_try"] = None
    return veri


@router.get("/teklif-donusumu")
async def teklif_donusumu(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    gun: int = Query(default=365, ge=7, le=3650),
    birim: str | None = None,
) -> dict:
    """Varsayılan SATIŞ teklifleri (sayılar canlıdaki gibi, E07-D02).
    `birim` verilirse o birimin servis teklifleri, kullanıcının teklif kapsamıyla."""
    from app.models.rbac import BIRIM_KODLARI

    if birim is not None and birim not in BIRIM_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {birim}")
    return await svc.teklif_donusumu(db, gun=gun, clock=clock, birim=birim, user=user)


# Montaj noktası raporundaki para alanları: montaj noktasına ödenen hak ediş.
# `hakedis.gor` ve `maliyet.gor` izinlerinin ikisi de bu sayıları koruyordu;
# rapor ucu ikisini de atlayıp aynı tutarları veriyordu.
_MN_PARA = ("brut", "net", "is_basina_maliyet")


def _hakedis_gorunur(user: User) -> bool:
    return sees_cost(user) and user.has("hakedis.gor")


@router.get("/montaj-noktasi")
async def montaj_noktasi(db: DbDep, user: Okuyucu, donem: str | None = None) -> list[dict]:
    """Montaj noktası maliyet ve performansı."""
    donem_dogrula(donem)
    satirlar = await svc.montaj_noktasi_performansi(db, donem=donem)
    if _hakedis_gorunur(user):
        return satirlar
    return [{**s, **{a: None for a in _MN_PARA if a in s}} for s in satirlar]


@router.get("/montaj-noktasi.xlsx")
async def montaj_noktasi_xlsx(
    request: Request, db: DbDep, user: Aktarici, donem: str | None = None
) -> Response:
    donem_dogrula(donem)
    if not _hakedis_gorunur(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Bu rapor için yetkiniz yok (hakedis.gor, maliyet.gor)"
        )
    satirlar = await svc.montaj_noktasi_performansi(db, donem=donem)
    return await _xlsx(
        ["Montaj Noktası", "Döküm", "İş", "Brüt", "Net", "İş Başına Maliyet"],
        [
            [
                s["unvan"],
                s["dokum_sayisi"],
                s["is_sayisi"],
                s["brut"],
                s["net"],
                s["is_basina_maliyet"],
            ]
            for s in satirlar
        ],
        f"Montaj Noktasi {donem or 'Tumu'}",
        db=db,
        user=user,
        request=request,
    )


@router.get("/musteri-geliri")
async def musteri_geliri(
    db: DbDep, clock: ClockDep, user: Okuyucu, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict]:
    return await svc.musteri_geliri(db, clock, limit=limit)


@router.get("/musteri-geliri.xlsx")
async def musteri_geliri_xlsx(
    request: Request, db: DbDep, clock: ClockDep, user: Aktarici
) -> Response:
    satirlar = await svc.musteri_geliri(db, clock, limit=500)
    return await _xlsx(
        ["Müşteri", "Abonelik Geliri", "Sipariş Geliri", "Toplam Gelir", "Cihaz"],
        [
            [
                s["unvan"],
                s["abonelik_geliri"],
                s["siparis_geliri"],
                s["toplam_gelir"],
                s["cihaz_sayisi"],
            ]
            for s in satirlar
        ],
        "Musteri Geliri",
        db=db,
        user=user,
        request=request,
    )


@router.get("/cihaz-omur-boyu/{device_id}")
async def cihaz_omur_boyu(device_id: int, db: DbDep, user: Okuyucu) -> dict:
    """Cihaz başı ömür boyu gelir ve marj. Maliyet yetkiye bağlı."""
    try:
        veri = await svc.cihaz_omur_boyu(db, device_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if not sees_cost(user):
        for alan in (
            "cihaz_maliyeti",
            "montaj_maliyeti",
            "tek_seferlik_maliyet",
            "aylik_maliyet",
            "aylik_marj",
            "basabas_ay",
        ):
            veri[alan] = None
    return veri


@router.get("/hareketsiz-stok")
async def hareketsiz_stok(
    db: DbDep, clock: ClockDep, user: Okuyucu, gun: int = Query(default=180, ge=1, le=3650)
) -> list[dict]:
    satirlar = await svc.hareketsiz_stok(db, clock, gun=gun)
    return _maliyet_gizle(satirlar, ("landed_cost_try",), user)


@router.get("/hareketsiz-stok.xlsx")
async def hareketsiz_stok_xlsx(
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Aktarici,
    gun: int = Query(default=180, ge=1, le=3650),
) -> Response:
    satirlar = _maliyet_gizle(
        await svc.hareketsiz_stok(db, clock, gun=gun), ("landed_cost_try",), user
    )
    return await _xlsx(
        ["Kimlik", "Ürün", "Durum", "Bekleme (gün)", "Maliyet"],
        [
            [s["kimlik"], s["urun_kodu"], s["status"], s["bekleme_gun"], s["landed_cost_try"]]
            for s in satirlar
        ],
        f"Hareketsiz Stok {gun}g",
        db=db,
        user=user,
        request=request,
    )


@router.get("/bayi-stogu")
async def bayi_stogu(db: DbDep, user: Okuyucu, hesap_id: int | None = None) -> list[dict]:
    """Bayi/montaj noktası stok ve yaşlanma raporu."""
    return await stok_svc.bayi_stogu(db, account_id=hesap_id)


@router.get("/ariza-orani")
async def ariza_orani(
    db: DbDep, clock: ClockDep, user: Okuyucu, gun: int = Query(default=365, ge=1, le=3650)
) -> list[dict]:
    """Model bazında arıza/RMA oranı."""
    return await rma_svc.ariza_orani(db, gun=gun, clock=clock)


@router.get("/mrr/{donem}")
async def mrr_hareketi(
    donem: str,
    db: DbDep,
    user: Annotated[User, Depends(require_permission("rapor.gor", "abonelik.gor"))],
) -> dict:
    """MRR / ARR / churn analizi.

    Abonelik gelir verisidir: `abonelik.gor` da gerekir (rol testi S2; abonelik
    ekranının `/abonelikler/mrr` ucuyla aynı görüntüleme izni).
    """
    try:
        abonelik_svc.donem_araligi(donem)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dönem 'YYYY-AA' olmalı") from exc
    veri = await abonelik_svc.mrr_hareketi(db, donem)
    veri["arr"] = veri["bitis_mrr"] * 12
    return veri


@ortak_router.get("/uyarilar")
async def uyarilar(db: DbDep, clock: ClockDep, user: CurrentUser) -> dict:
    """Kullanıcının görebileceği zamana bağlı uyarılar.

    Ayrı bir izin istemez — her uyarı kendi modülünün iznine tabidir
    (bkz. `services/uyarilar.py`). Yetkisi olmayan kullanıcı o satırı hiç
    görmez; aksi halde uyarı SAYISI bir yetki sızıntısı olurdu.
    """
    from app.services import uyarilar as uyari_svc

    ozet = await uyari_svc.topla(db, clock, user)
    return {
        "toplam": ozet.toplam,
        "uyarilar": [
            {
                "kod": u.kod,
                "baslik": u.baslik,
                "adet": u.adet,
                "yol": u.yol,
                "onem": u.onem,
                "aciklama": u.aciklama,
            }
            for u in ozet.uyarilar
        ],
    }
