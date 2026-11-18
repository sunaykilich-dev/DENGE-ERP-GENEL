"""Operasyon Merkezi, SLA bildirimleri ve SLA tanımları uçları (TS-081…085).

Doldurdu: D2-G. `main.py` kaydı D2-S'tedir.

İzinler (plan §1.3, E10-14):
- `/operasyon/ozet`, `/operasyon/isler`, `/operasyon/personel`: `operasyon.gor` +
  `servis.gor` (ikisi birden; teknisyende `operasyon.gor` yok → 403).
- `/operasyon/bildirimler` ve görüldü: `servis.gor` (kapsam iş tablosuna JOIN).
- `/operasyon/isler/{so_id}/sla`: `servis.gor` (servis işi detayının SLA kartı).
- `/operasyon/isler/{so_id}/kapanis-bilgisi`: `servis.kapat` VEYA `servis.tamamla`
  (gecikme nedeni / tekrar arıza teyidi; kapalı işte yalnız `servis.kapat`).
- `/sla-tanimlari/...`: okuma `servis.gor`, politika ve mesai penceresi yazma
  `operasyon.yonet` (Faz A, TS-200: MESAI takvimi).
- `/bildirim-tercihlerim` (GET/PUT): `servis.gor`; YALNIZ oturumdaki kişinin
  satırı (yolda kimlik yok → başkasının tercihine erişim yolu yok). TS-200.
- `/bildirimler/eposta-kutusu`, `/bildirimler/eposta-ayarlari`: `operasyon.yonet`
  (giden kutusu kişisel veri — alıcı adresi — içerir; SMTP sırları DÖNMEZ).

Kapsam: liste/sayaç SQL'de (`kapsam.kapsam_isler`); `{so_id}` uçlarında kapsam
dışı iş 404 ve HİÇBİR yazma yapılmaz (kapsam yazmadan önce çözülür). Bu
modülde fiyat/maliyet alanı YOKTUR. Toplu atama/plan için yeni uç AÇILMAZ:
ekran mevcut `PUT /isler/toplu-atama` ve `POST /planlama/toplu-plan` uçlarını
çağırır (E10-08). Yol parametresi adları kapsam taramasının sözleşmesindedir
(`so_id`); kimliği yolda olmayan kayıtlar (politika, bildirim) gövdeyle gelir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import (
    ClockDep,
    DbDep,
    client_ip,
    require_any_permission,
    require_permission,
    sayfala,
)
from app.models import (
    ServiceAlert,
    ServiceAlertRead,
    ServiceMailOutbox,
    ServiceNotificationPref,
    ServiceOrder,
    ServiceSlaPolicy,
    User,
)
from app.models.teknik_servis import (
    GECIKME_NEDENLERI,
    ONCELIKLER,
    SLA_SONUCLARI,
    SLA_TAKVIM_TURLERI,
    SLA_UYARI_KODLARI,
    TEKRAR_ARIZA_TEYITLERI,
)
from app.permissions import BIRIMLER
from app.services import audit, mail
from app.services import settings as ayarlar
from app.services.teknik_servis import (
    gecmis,
    is_emirleri,
    kapsam,
    operasyon,
    operasyon_pano,
    panel,
    sla,
)
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

router = APIRouter(prefix="/api/teknik-servis", tags=["servis-operasyon"])

Operasyoncu = Annotated[User, Depends(require_permission("operasyon.gor", "servis.gor"))]
Okuyucu = Annotated[User, Depends(require_permission("servis.gor"))]
Yonetici = Annotated[User, Depends(require_permission("operasyon.yonet"))]
Kapanisci = Annotated[User, Depends(require_any_permission("servis.kapat", "servis.tamamla"))]

GECIKME_ADLARI: dict[str, str] = {
    "MALZEME_TEDARIK": "Malzeme tedariki",
    "MUSTERI_KAYNAKLI": "Müşteri kaynaklı",
    "ULASIM": "Ulaşım",
    "PERSONEL_YETERSIZ": "Personel yetersiz",
    "YOGUNLUK": "İş yoğunluğu",
    "TEKNIK_ZORLUK": "Teknik zorluk",
    "DIGER": "Diğer",
}
TEYIT_ADLARI: dict[str, str] = {
    "AYNI_ARIZA": "Aynı arıza (tekrar)",
    "FARKLI_ARIZA": "Farklı arıza",
    "KULLANICI_HATASI": "Kullanıcı hatası",
}
UYARI_KODU_ADLARI: dict[str, str] = {
    "SLA_RISK": "SLA riskte",
    "SLA_ASILDI": "SLA aşıldı",
    "MUDAHALE_ASILDI": "Müdahale gecikti",
    "BEKLEME_BITIS_GECTI": "Beklenen bitişi geçmiş bekleme",
    "PB_VADE_GECTI": "Bakım vadesi geçti",
    "TAYIN_GECIKTI": "Tayin gecikti",
}
# Sözlük eşitliği (ad tabloları ↔ model tuple'ları) `tests/unit/test_sla_hesap.py`'de kilitli.


# --- Şemalar --------------------------------------------------------------------------


class GorulduIn(BaseModel):
    bildirim_idler: list[int] = Field(min_length=1, max_length=200)

    model_config = {"json_schema_extra": {"examples": [{"bildirim_idler": [1]}]}}


class KapanisBilgisiIn(BaseModel):
    """Gecikme nedeni (SLA aşılmış işte) ve tekrar arıza kök neden teyidi (E10-01/04).

    Gönderilmeyen alan değişmez; `null` gönderilen alan temizlenir.
    """

    version: int | None = None
    gecikme_nedeni: Literal[GECIKME_NEDENLERI] | None = None  # type: ignore[valid-type]
    gecikme_aciklama: str | None = Field(default=None, max_length=300)
    tekrar_ariza_teyit: Literal[TEKRAR_ARIZA_TEYITLERI] | None = None  # type: ignore[valid-type]

    model_config = {"json_schema_extra": {"examples": [{"gecikme_nedeni": "YOGUNLUK"}]}}


class PolitikaIn(BaseModel):
    """SLA politikası ekle (`id` yok) / güncelle (`id` + `version`).

    Öncelik ve birim kimliktir, güncellemede değiştirilemez. Takvim türü
    7/24 ya da MESAI (hafta içi mesai penceresi; Faz A, TS-200). Politikanın
    takvimi VARSAYILANDIR: müşteri (`accounts.sla_takvim_turu`) ve lokasyon
    (`addresses.sla_takvim_turu`) değeri onu ezer.
    """

    id: int | None = None
    version: int | None = None
    oncelik: Literal[ONCELIKLER]  # type: ignore[valid-type]
    birim: str | None = Field(default=None, max_length=20)
    cozum_saat: Decimal = Field(gt=0, le=9999, max_digits=6, decimal_places=2)
    mudahale_saat: Decimal | None = Field(
        default=None, gt=0, le=9999, max_digits=6, decimal_places=2
    )
    takvim_turu: Literal["7_24", "MESAI"] = "7_24"
    is_active: bool = True

    model_config = {
        "json_schema_extra": {
            "examples": [{"oncelik": "KRITIK", "birim": "GUVENLIK", "cozum_saat": "8"}]
        }
    }


# --- Yardımcılar --------------------------------------------------------------------------


def _hata(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, ServisGirdiHatasi):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, ServisHatasi):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


_HATALAR = (ServisHatasi, ServisGirdiHatasi, PermissionError)


async def _kapsamli_is(db, so_id: int, user: User) -> ServiceOrder:
    """İşi kapsam süzgeciyle getirir; yoksa 404 (yazmadan ÖNCE)."""
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servis işi bulunamadı")
    return so


async def _sla_detayi(db, so: ServiceOrder, user: User, clock) -> dict[str, Any]:
    blok = (await sla.sla_bloklari(db, [so], clock))[so.id]
    bag = None
    if so.iliskili_is_id is not None:
        bag = (await is_emirleri.bagli_isler(db, user, so))["ust"]
    return {
        "id": so.id,
        "so_no": so.so_no,
        "status": so.status,
        "oncelik": so.oncelik,
        "version": so.version,
        "sla": blok,
        "gecikme_nedeni": so.gecikme_nedeni,
        "gecikme_aciklama": so.gecikme_aciklama,
        "tekrar_ariza": {
            "aday": so.tekrar_ariza_aday,
            "teyit": so.tekrar_ariza_teyit,
            # Kapsam dışı bağda numara ve kimlik maskelidir ("Kapsam dışı iş").
            "bagli_is": bag,
        },
        "kapanis_icin_gerekenler": _kapanis_eksikleri(so),
    }


def _kapanis_eksikleri(so: ServiceOrder) -> list[str]:
    """Kapatma (KAPATILDI) öncesi girilmesi gerekenler — ekranda uyarı olarak."""
    eksik = []
    if so.sla_sonuc == "ASILDI" and so.sla_kaynak == "CANLI" and so.gecikme_nedeni is None:
        eksik.append("GECIKME_NEDENI")
    if so.tekrar_ariza_aday and so.tekrar_ariza_teyit is None:
        eksik.append("TEKRAR_ARIZA_TEYIDI")
    return eksik


def _politika_cikti(p: ServiceSlaPolicy) -> dict[str, Any]:
    return {
        "id": p.id,
        "oncelik": p.oncelik,
        "birim": p.birim,
        "birim_adi": BIRIMLER.get(p.birim, p.birim) if p.birim else "Tüm birimler",
        "cozum_saat": float(p.cozum_saat),
        "mudahale_saat": float(p.mudahale_saat) if p.mudahale_saat is not None else None,
        "takvim_turu": p.takvim_turu,
        "is_active": p.is_active,
        "version": p.version,
        "updated_at": p.updated_at,
    }


def _politika_denetim(p: ServiceSlaPolicy) -> dict[str, Any]:
    return {
        "oncelik": p.oncelik,
        "birim": p.birim,
        "cozum_saat": format(Decimal(p.cozum_saat), ".2f"),
        "mudahale_saat": (
            format(Decimal(p.mudahale_saat), ".2f") if p.mudahale_saat is not None else None
        ),
        "takvim_turu": p.takvim_turu,
        "is_active": p.is_active,
    }


# --- Operasyon Merkezi ------------------------------------------------------------------


@router.get("/operasyon/ozet", response_model=None)
async def ozet(
    db: DbDep,
    clock: ClockDep,
    user: Operasyoncu,
    birim: str | None = None,
    oncelik: str | None = None,
) -> dict[str, Any]:
    """Sayaçlar (tıklanabilir; sayı = `/operasyon/isler?kpi=` toplamı)."""
    try:
        sayaclar = await operasyon.sayaclar(db, user, clock, birim=birim, oncelik=oncelik)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    return {
        "sunucu_zamani": clock.now(),
        "birim": birim or None,
        "oncelik": operasyon.oncelik_dogrula(oncelik),
        "risk_yuzde": await sla.risk_yuzdesi(db),
        "sayaclar": sayaclar,
    }


@router.get("/operasyon/pano", response_model=None)
async def pano(
    db: DbDep, clock: ClockDep, user: Operasyoncu, birim: str | None = None
) -> dict[str, Any]:
    """Dispeçer panosu: tayin bekleyenler, plandan sapanlar, ekip durumu (2026-11-18)."""
    try:
        veri = await operasyon_pano.pano(db, user, clock, birim=birim)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    return {"sunucu_zamani": clock.now(), "birim": birim or None, **veri}


@router.get("/operasyon/tayin-sayilari", response_model=None)
async def tayin_sayilari(db: DbDep, clock: ClockDep, user: Operasyoncu) -> dict[str, int]:
    """Menü rozeti / sekme başlığı: tayin bekleyen ve süresi geçen iş sayısı."""
    return await operasyon_pano.tayin_sayilari(db, user, clock)


@router.get("/operasyon/isler", response_model=None)
async def isler(
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: Operasyoncu,
    kpi: str | None = None,
    birim: str | None = None,
    oncelik: str | None = None,
    teknisyen_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """SLA kalan süreye göre sıralı liste (önce en acil, durdurulanlar sonda)."""
    try:
        kod = operasyon.sayac_dogrula(kpi)
        birim = panel.birim_dogrula(user, birim)
        oncelik = operasyon.oncelik_dogrula(oncelik)
        stmt = operasyon.liste_sorgusu(
            user,
            clock,
            await sla.risk_yuzdesi(db),
            kpi=kod,
            birim=birim,
            oncelik=oncelik,
            teknisyen_id=teknisyen_id,
        )
    except _HATALAR as exc:
        raise _hata(exc) from exc
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return await operasyon.liste_satirlari(db, [r[0] for r in satirlar], clock)


@router.get("/operasyon/personel", response_model=None)
async def personel(
    db: DbDep, clock: ClockDep, user: Operasyoncu, birim: str | None = None
) -> dict[str, Any]:
    """Personel iş yükü. "Bugün çalışılan dk" yalnız `servis_rapor.personel` ile döner."""
    try:
        satirlar = await operasyon.is_yuku(db, user, clock, birim=birim)
    except _HATALAR as exc:
        raise _hata(exc) from exc
    return {
        "sunucu_zamani": clock.now(),
        "kisi_saat_gorunur": user.has("servis_rapor.personel"),
        "personel": satirlar,
    }


# --- Bildirimler (TS-083) ---------------------------------------------------------------


@router.get("/operasyon/bildirimler", response_model=None)
async def bildirimler(
    response: Response,
    db: DbDep,
    user: Okuyucu,
    acik: bool = True,
    kod: str | None = None,
    goruldu: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Kalıcı SLA bildirimleri (kapsam `service_orders` JOIN'iyle, okuma anında)."""
    if kod is not None and kod not in SLA_UYARI_KODLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen bildirim kodu: {kod}")
    okundu = exists().where(
        ServiceAlertRead.alert_id == ServiceAlert.id, ServiceAlertRead.user_id == user.id
    )
    stmt = (
        select(ServiceAlert, ServiceOrder.so_no, ServiceOrder.birim, okundu.label("goruldu"))
        .join(ServiceOrder, ServiceOrder.id == ServiceAlert.service_order_id)
        .where(ServiceOrder.is_deleted.is_(False))
    )
    stmt = kapsam.kapsam_isler(stmt, user, ServiceAlert.service_order_id)
    if acik:
        stmt = stmt.where(ServiceAlert.kapanis_at.is_(None))
    if kod:
        stmt = stmt.where(ServiceAlert.kod == kod)
    if goruldu is True:
        stmt = stmt.where(okundu)
    elif goruldu is False:
        stmt = stmt.where(~okundu)
    stmt = stmt.order_by(ServiceAlert.acilis_at.desc(), ServiceAlert.id.desc())
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [
        {
            "id": a.id,
            "kod": a.kod,
            "kod_adi": UYARI_KODU_ADLARI[a.kod],
            "onem": a.onem,
            "baslik": a.baslik,
            "service_order_id": a.service_order_id,
            "so_no": so_no,
            "birim": birim,
            "acilis_at": a.acilis_at,
            "kapanis_at": a.kapanis_at,
            "kapanis_nedeni": a.kapanis_nedeni,
            "goruldu": bool(gor),
        }
        for a, so_no, birim, gor in satirlar
    ]


@router.post("/operasyon/bildirimler/goruldu", response_model=None)
async def bildirim_goruldu(
    payload: GorulduIn, db: DbDep, clock: ClockDep, user: Okuyucu
) -> dict[str, Any]:
    """ "Görüldü" işareti (tek INSERT … ON CONFLICT DO NOTHING). Kapsam dışı / olmayan
    bildirim varsa 404 ve HİÇBİR satır yazılmaz."""
    idler = sorted(set(payload.bildirim_idler))
    stmt = (
        select(ServiceAlert.id)
        .join(ServiceOrder, ServiceOrder.id == ServiceAlert.service_order_id)
        .where(ServiceAlert.id.in_(idler), ServiceOrder.is_deleted.is_(False))
    )
    gorunen = set(
        (await db.scalars(kapsam.kapsam_isler(stmt, user, ServiceAlert.service_order_id))).all()
    )
    if gorunen != set(idler):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bildirim bulunamadı")
    an = clock.now()
    sonuc = await db.execute(
        insert(ServiceAlertRead)
        .values([{"alert_id": i, "user_id": user.id, "goruldu_at": an} for i in idler])
        .on_conflict_do_nothing(index_elements=["alert_id", "user_id"])
        .returning(ServiceAlertRead.alert_id)
    )
    yeni = len(sonuc.all())
    await db.commit()
    return {"isaretlenen": yeni, "zaten_goruldu": len(idler) - yeni}


# --- Tek iş: SLA kartı ve kapanış bilgisi -------------------------------------------------


@router.get("/operasyon/isler/{so_id}/sla", response_model=None)
async def is_sla(so_id: int, db: DbDep, clock: ClockDep, user: Okuyucu) -> dict[str, Any]:
    """Servis işinin SLA kartı (durum, hedefler, ilk müdahale, tekrar arıza, eksikler)."""
    so = await _kapsamli_is(db, so_id, user)
    return await _sla_detayi(db, so, user, clock)


@router.put("/operasyon/isler/{so_id}/kapanis-bilgisi", response_model=None)
async def kapanis_bilgisi(
    so_id: int,
    payload: KapanisBilgisiIn,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    user: Kapanisci,
) -> dict[str, Any]:
    """Gecikme nedeni ve tekrar arıza teyidi (KAPATILDI öncesi zorunlu; TAMAMLANDI'da
    isteğe bağlı). Kapsam dışı iş 404, hiçbir şey yazılmaz."""
    so = await _kapsamli_is(db, so_id, user)
    if payload.version is not None and payload.version != so.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin"
        )
    if so.status == "IPTAL":
        raise HTTPException(status.HTTP_409_CONFLICT, "İptal edilmiş işte kapanış bilgisi girilmez")
    if so.status == "KAPATILDI" and not user.has("servis.kapat"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Kapalı işte düzeltme için yetkiniz yok (servis.kapat)"
        )
    alanlar = payload.model_fields_set - {"version"}
    if not alanlar:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Değiştirilecek alan yok")
    yeni_neden = payload.gecikme_nedeni if "gecikme_nedeni" in alanlar else so.gecikme_nedeni
    yeni_aciklama = (
        (payload.gecikme_aciklama or "").strip() or None
        if "gecikme_aciklama" in alanlar
        else so.gecikme_aciklama
    )
    yeni_teyit = (
        payload.tekrar_ariza_teyit if "tekrar_ariza_teyit" in alanlar else so.tekrar_ariza_teyit
    )
    if "gecikme_nedeni" in alanlar and yeni_neden is not None:
        asildi = so.sla_sonuc == "ASILDI" or (
            so.sla_sonuc is None
            and so.cozum_hedef_at is not None
            and so.cozum_hedef_at <= clock.now()
        )
        if not asildi:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "SLA hedefi aşılmamış işte gecikme nedeni girilmez"
            )
    if yeni_neden == "DIGER" and yeni_aciklama is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "'Diğer' gecikme nedeninde açıklama zorunlu"
        )
    if yeni_neden is None:
        yeni_aciklama = None
    if "tekrar_ariza_teyit" in alanlar and yeni_teyit is not None and not so.tekrar_ariza_aday:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Tekrar arıza adayı olmayan işte teyit girilmez"
        )
    if (yeni_neden, yeni_aciklama, yeni_teyit) == (
        so.gecikme_nedeni,
        so.gecikme_aciklama,
        so.tekrar_ariza_teyit,
    ):
        return await _sla_detayi(db, so, user, clock)
    so.gecikme_nedeni = yeni_neden
    so.gecikme_aciklama = yeni_aciklama
    so.tekrar_ariza_teyit = yeni_teyit
    so.updated_by = user.id
    await audit.log_change(db, so, "sla.kapanis_bilgisi", user_id=user.id, ip=client_ip(request))
    await db.flush()
    parcalar = []
    if yeni_neden is not None:
        parcalar.append(f"gecikme nedeni: {GECIKME_ADLARI[yeni_neden]}")
    if yeni_teyit is not None:
        parcalar.append(f"tekrar arıza teyidi: {TEYIT_ADLARI[yeni_teyit]}")
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "SLA",
            "Kapanış bilgisi: " + ("; ".join(parcalar) if parcalar else "temizlendi"),
            user=user,
            clock=clock,
            veri={"gecikme_nedeni": yeni_neden, "tekrar_ariza_teyit": yeni_teyit},
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    cikti = await _sla_detayi(db, so, user, clock)
    await db.commit()
    return cikti


# --- E-posta bildirimi (TS-200, E10-06) ---------------------------------------------------


class TercihIn(BaseModel):
    """Kişinin kendi servis e-posta tercihi (yalnız kendi satırı)."""

    anlik_eposta: bool
    gunluk_ozet: bool

    model_config = {
        "json_schema_extra": {"examples": [{"anlik_eposta": True, "gunluk_ozet": False}]}
    }


class EpostaAyarIn(BaseModel):
    """Servis e-postası genel ayarları (`operasyon.yonet`). Gönderilmeyen alan değişmez."""

    servis_eposta_acik: bool | None = None
    servis_gunluk_ozet_saati: str | None = Field(default=None, max_length=5)
    servis_eposta_deneme: int | None = Field(default=None, ge=1, le=10)

    model_config = {
        "json_schema_extra": {
            "examples": [{"servis_eposta_acik": True, "servis_gunluk_ozet_saati": "07:30"}]
        }
    }


_EPOSTA_AYARLARI = ("servis_eposta_acik", "servis_gunluk_ozet_saati", "servis_eposta_deneme")
_KUTU_DURUMLARI = ("BEKLIYOR", "GONDERILDI", "BASARISIZ")


async def _tercih_cikti(db, user: User) -> dict[str, Any]:
    tercih = await db.get(ServiceNotificationPref, user.id)
    return {
        "anlik_eposta": bool(tercih.anlik_eposta) if tercih else False,
        "gunluk_ozet": bool(tercih.gunluk_ozet) if tercih else False,
        # Kişinin kendi adresinin VAR OLUP OLMADIĞI (adresin kendisi değil).
        "eposta_tanimli": bool((user.email or "").strip()),
        "servis_eposta_acik": bool(await ayarlar.get(db, "servis_eposta_acik")),
        "gunluk_ozet_saati": await ayarlar.get(db, "servis_gunluk_ozet_saati"),
    }


@router.get("/bildirim-tercihlerim", response_model=None)
async def tercihlerim(db: DbDep, user: Okuyucu) -> dict[str, Any]:
    """Kendi e-posta tercihim. Satır yoksa ikisi de kapalı (varsayılan e-posta yok)."""
    return await _tercih_cikti(db, user)


@router.put("/bildirim-tercihlerim", response_model=None)
async def tercihlerim_yaz(
    payload: TercihIn, request: Request, db: DbDep, user: Okuyucu
) -> dict[str, Any]:
    """Kendi tercihimi yazar (başkasının satırına yol yok: kimlik oturumdan)."""
    tercih = await db.get(ServiceNotificationPref, user.id)
    eski = (
        {"anlik_eposta": tercih.anlik_eposta, "gunluk_ozet": tercih.gunluk_ozet}
        if tercih
        else {"anlik_eposta": False, "gunluk_ozet": False}
    )
    yeni = {"anlik_eposta": payload.anlik_eposta, "gunluk_ozet": payload.gunluk_ozet}
    if eski != yeni:
        if tercih is None:
            db.add(ServiceNotificationPref(user_id=user.id, **yeni))
        else:
            tercih.anlik_eposta = payload.anlik_eposta
            tercih.gunluk_ozet = payload.gunluk_ozet
        await audit.log(
            db,
            "service_notification_prefs",
            "servis.bildirim_tercihi",
            entity_id=user.id,
            old_value=eski,
            new_value=yeni,
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
    return await _tercih_cikti(db, user)


@router.get("/bildirimler/eposta-kutusu", response_model=None)
async def eposta_kutusu(
    response: Response,
    db: DbDep,
    user: Yonetici,
    durum: str | None = None,
    tur: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Servis e-posta kutusu (yönetici görünümü; en yeni önce). Gövde dönmez.

    `alici` kişisel veridir; bu görünüm yalnız `operasyon.yonet` içindir.
    """
    if durum is not None and durum not in _KUTU_DURUMLARI:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen durum: {durum}")
    if tur is not None and tur not in ("ANLIK", "GUNLUK_OZET"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen tür: {tur}")
    stmt = select(ServiceMailOutbox, User.full_name).join(
        User, User.id == ServiceMailOutbox.user_id
    )
    if durum:
        stmt = stmt.where(ServiceMailOutbox.durum == durum)
    if tur:
        stmt = stmt.where(ServiceMailOutbox.tur == tur)
    stmt = stmt.order_by(ServiceMailOutbox.created_at.desc(), ServiceMailOutbox.id.desc())
    satirlar = await sayfala(db, response, stmt, limit=limit, offset=offset)
    return [
        {
            "id": k.id,
            "tur": k.tur,
            "alert_id": k.alert_id,
            "ozet_gunu": k.ozet_gunu,
            "kullanici": {"id": k.user_id, "ad": ad},
            "alici": k.alici,
            "konu": k.konu,
            "durum": k.durum,
            "deneme": k.deneme,
            "son_hata": k.son_hata,
            "created_at": k.created_at,
            "gonderildi_at": k.gonderildi_at,
        }
        for k, ad in satirlar
    ]


async def _eposta_ayar_cikti(db) -> dict[str, Any]:
    tum = await ayarlar.get_all(db)
    return {
        **{a: tum.get(a) for a in _EPOSTA_AYARLARI},
        # SMTP'nin TANIMLI olup olmadığı; sunucu/kullanıcı/parola dönmez.
        "smtp_tanimli": mail.yapilandirildi_mi(tum),
    }


@router.get("/bildirimler/eposta-ayarlari", response_model=None)
async def eposta_ayarlari(db: DbDep, user: Yonetici) -> dict[str, Any]:
    return await _eposta_ayar_cikti(db)


@router.put("/bildirimler/eposta-ayarlari", response_model=None)
async def eposta_ayarlari_yaz(
    payload: EpostaAyarIn, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    """Servis e-postasını açar/kapatır, özet saatini ve deneme sınırını yazar.

    SMTP ayarları burada YOK (Parametreler → Bildirim, `sistem.ayar`).
    """
    istenen = {a: v for a, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not istenen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Değiştirilecek ayar yok")
    onceki = {a: await ayarlar.get(db, a) for a in istenen}
    degisen = {a: v for a, v in istenen.items() if onceki[a] != v}
    if degisen:
        try:
            await ayarlar.set_many(db, degisen, user.id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        await audit.log(
            db,
            "settings",
            "servis.eposta_ayari",
            old_value={a: onceki[a] for a in degisen},
            new_value=degisen,
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
    return await _eposta_ayar_cikti(db)


# --- SLA tanımları ------------------------------------------------------------------------


class MesaiIn(BaseModel):
    """MESAI takvimli SLA'nın mesai penceresi (Faz A, TS-200). Günler hafta içidir
    (karar; tatiller fark etmez). Gönderilmeyen alan değişmez."""

    baslangic: str | None = Field(default=None, max_length=5)
    bitis: str | None = Field(default=None, max_length=5)

    model_config = {"json_schema_extra": {"examples": [{"baslangic": "08:30", "bitis": "18:00"}]}}


@router.put("/sla-tanimlari/mesai", response_model=None)
async def mesai_yaz(
    payload: MesaiIn, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    """Mesai penceresini yazar (`operasyon.yonet`; aynı anahtarlar Parametreler'de de var).

    Açık işlerin damgalı hedef anı DEĞİŞMEZ; yeni açılan işler, bekleme kaymaları
    ve "riskte" oranı yeni pencereyle hesaplanır. Bitiş ≤ başlangıç → 400.
    """
    istenen = {
        anahtar: deger
        for anahtar, deger in (
            ("servis_mesai_baslangic", payload.baslangic),
            ("servis_mesai_bitis", payload.bitis),
        )
        if deger is not None
    }
    if not istenen:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Değiştirilecek ayar yok")
    onceki = {a: await ayarlar.get(db, a) for a in istenen}
    degisen = {a: v for a, v in istenen.items() if onceki[a] != v}
    if degisen:
        try:
            await ayarlar.set_many(db, degisen, user.id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        await audit.log(
            db,
            "settings",
            "sla.mesai.degistir",
            old_value={a: onceki[a] for a in degisen},
            new_value=degisen,
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
    mesai = await sla.mesai_takvimi(db)
    return {
        "baslangic": await ayarlar.get(db, "servis_mesai_baslangic"),
        "bitis": await ayarlar.get(db, "servis_mesai_bitis"),
        "metin": mesai.metin(),
    }


@router.get("/sla-tanimlari/sozluk", response_model=None)
async def sozluk(db: DbDep, user: Okuyucu) -> dict[str, Any]:
    """Ekran sözlükleri ve SLA ayarlarının özeti (tek kaynak: model tuple'ları)."""
    yururluk = await sla.yururluk_ani(db)
    mesai = await sla.mesai_takvimi(db)
    return {
        "sla_durumlari": [{"kod": k, "ad": v} for k, v in sla.SLA_DURUM_ADLARI.items()],
        "mudahale_durumlari": [{"kod": k, "ad": v} for k, v in sla.MUDAHALE_DURUM_ADLARI.items()],
        "sla_sonuclari": list(SLA_SONUCLARI),
        "gecikme_nedenleri": [{"kod": k, "ad": v} for k, v in GECIKME_ADLARI.items()],
        "tekrar_ariza_teyitleri": [{"kod": k, "ad": v} for k, v in TEYIT_ADLARI.items()],
        "bildirim_kodlari": [{"kod": k, "ad": v} for k, v in UYARI_KODU_ADLARI.items()],
        "oncelikler": list(ONCELIKLER),
        "terimler": dict(sla.TERIMLER),
        "birimler": [{"kod": k, "ad": v} for k, v in BIRIMLER.items()],
        "yururluk_at": yururluk,
        "sla_yururlukte": yururluk is not None,
        "risk_yuzde": await sla.risk_yuzdesi(db),
        # Faz A (TS-200): takvim türleri ve MESAI penceresi (ayar; tatiller fark etmez).
        "takvim_turleri": [{"kod": k, "ad": sla.takvim_adi(k, mesai)} for k in SLA_TAKVIM_TURLERI],
        "mesai": {
            "baslangic": await ayarlar.get(db, "servis_mesai_baslangic"),
            "bitis": await ayarlar.get(db, "servis_mesai_bitis"),
            "metin": mesai.metin(),
        },
        "tekrar_ariza_gun": int(await ayarlar.get(db, "servis_tekrar_ariza_gun") or 30),
        "operasyon_sayaclari": list(operasyon.OPERASYON_SAYACLARI),
    }


@router.get("/sla-tanimlari/politikalar", response_model=None)
async def politikalar(db: DbDep, user: Okuyucu) -> list[dict[str, Any]]:
    sira = {o: i for i, o in enumerate(ONCELIKLER)}
    satirlar = (await db.scalars(select(ServiceSlaPolicy))).all()
    satirlar = sorted(
        satirlar,
        key=lambda p: (sira.get(p.oncelik, 9), p.birim is not None, p.birim or "", p.id),
    )
    return [_politika_cikti(p) for p in satirlar]


@router.put("/sla-tanimlari/politikalar", response_model=None)
async def politika_kaydet(
    payload: PolitikaIn, request: Request, db: DbDep, user: Yonetici
) -> dict[str, Any]:
    """Politika ekle/güncelle. Değişiklik AÇIK işlerin hedefini DEĞİŞTİRMEZ (hedef işe
    damgalıdır); yalnız sonra açılan / önceliği düzeltilen işleri etkiler."""
    birim = (payload.birim or "").strip().upper() or None
    if birim is not None and birim not in BIRIMLER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {payload.birim}")
    if payload.id is None:
        politika = ServiceSlaPolicy(oncelik=payload.oncelik, birim=birim)
        eski: dict[str, Any] | None = None
    else:
        politika = await db.get(ServiceSlaPolicy, payload.id)
        if politika is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "SLA politikası bulunamadı")
        if payload.version is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sürüm (version) zorunlu")
        if payload.version != politika.version:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Kayıt başka biri tarafından değiştirildi; yenileyin"
            )
        if politika.oncelik != payload.oncelik or politika.birim != birim:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Politikanın önceliği ve birimi değiştirilemez; yeni politika ekleyin",
            )
        eski = _politika_denetim(politika)
    if payload.is_active:
        cakisan = await db.scalar(
            select(ServiceSlaPolicy.id).where(
                ServiceSlaPolicy.oncelik == payload.oncelik,
                ServiceSlaPolicy.is_active.is_(True),
                ServiceSlaPolicy.birim.is_(None)
                if birim is None
                else ServiceSlaPolicy.birim == birim,
                ServiceSlaPolicy.id != (politika.id or 0),
            )
        )
        if cakisan is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Bu öncelik ve birim için aktif politika zaten var; onu düzenleyin",
            )
    elif birim is None and politika.id is not None and politika.is_active:
        # Tüm birimler için öncelik başına en az bir aktif politika kalmalı:
        # yoksa o öncelikte iş açılamaz ("SLA politikası tanımsız" 409).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Tüm birimler için geçerli politika pasifleştirilemez (bu öncelikte iş açılamazdı)",
        )
    politika.cozum_saat = payload.cozum_saat
    politika.mudahale_saat = payload.mudahale_saat
    politika.takvim_turu = payload.takvim_turu
    politika.is_active = payload.is_active
    if politika.id is None:
        db.add(politika)
    await db.flush()
    yeni = _politika_denetim(politika)
    if eski == yeni:
        return _politika_cikti(politika)
    await audit.log(
        db,
        "service_sla_policies",
        "sla.politika.degistir",
        entity_id=politika.id,
        old_value=eski,
        new_value=yeni,
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(politika)
    return _politika_cikti(politika)
