"""Müşteri onayı (tekil + ziyaret grubu) ve servis formu PDF bağlamı (E01-08, E04-15/16, TS-036).

**Onay DEĞİŞMEZ.** Bir onay satırı güncellenmez; yeni onay eskisini
`gecersiz_kilan_id` ile (YENİ satırda, eskisini işaret ederek) geçersiz kılar
ve ikisi de geçmişte kalır. "Müşteri imzaladı mı" sorusu sonradan yeniden
yazılabilseydi, imzalı formun hukuki değeri kalmazdı.

**Biçimler** (K4): IMZA (ekranda canvas → PNG, mevcut `IMZA` ek türü;
`MUSTERI_IMZASI` açılmaz), BASILI_FORM (imzalı kâğıt formun fotoğrafı,
`SERVIS_FORMU` eki), SOZLU (telefonda/yüz yüze sözlü onay; kim verdi
yazılır) ve ALINAMADI + neden. ALINAMADI da geçerli bir onay KAYDIDIR:
sahada müşteri yokken iş bloke olmaz, ama raporda görünür (KD-19).

**Zorunluluk:** `servis_onay_zorunlu_turler` (varsayılan `["PB"]`) ayarındaki
türlerde geçerli onay olmadan TAMAMLANDI'ya geçilemez (409). Kontrol
`kancalar.durum_dogrula` kaydıyla yapılır; çekirdek `durum_degistir`
değişmez (KD-15).

**Ziyaret onayı** (E04-15): aynı müşteri + aynı lokasyon + aynı gündeki
işler (ör. bir binadaki 12 dedektörün PB işi) tek imzayla onaylanır; satırlar
tek transaction'da aynı `onay_grubu` ile yazılır. Farklı müşteri/lokasyon/gün
→ 409; listedeki işlerden biri kapsam dışıysa → 404 (hangisi olduğu
söylenmez, kimlik taraması engellenir).

**PDF bağlamı bu modüldedir** (KD-18): `belgeler.py` yalnız `firma_bilgisi()`
için çağrılır. Form FİYATSIZDIR (sahada müşteriye imzalatılan belge ticari
koşul taşımaz); süre kaydı yoksa "0" değil "Süre kaydı eksik" yazar; PB'de
bakım formunun kontrol listesi basılır.

**KVKK** (E01-18 (5), B6): imzalayan adı/unvanı, servis işinin irtibat adı ve
telefonu ve imza PNG'si kişisel veridir. Hesap anonimleştirilince temizlenir,
imza eki indirilemez hâle gelir; denetim satırları maskelenir. Kancalar bu
dosyanın sonunda `services/kvkk.py` kayıt defterlerine kaydolur (servis işi
çekirdeği `is_emirleri.py` D1-B paketinindir; dosya sahipliği gereği burada).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.models import (
    Account,
    Address,
    Attachment,
    MaintenanceForm,
    MaintenanceFormCheck,
    ServiceApproval,
    ServiceFaultReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
    User,
)
from app.models.teknik_servis import ONAY_TURLERI
from app.services import audit
from app.services.teknik_servis import ek_kapsam, gecmis, kancalar
from app.services.teknik_servis.is_emirleri import IsEmriKapsamDisi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_an, yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


class OnayHatasi(ServisHatasi):
    """Onay iş kuralı ihlali → 409."""


class OnayGirdiHatasi(ServisGirdiHatasi):
    """Onay girdisi hatalı (ek bu işin değil, imzalayan adı yok ...) → 400."""


class OnayKapsamDisi(IsEmriKapsamDisi):
    """İş yok ya da kullanıcının (yazma) kapsamı dışında → 404.

    KENDI_ISLERI teknisyeni yalnız AKTİF ATANDIĞI işe onay girer; plan
    üyeliği okuma için yeterlidir, yazma için değil (ek kuralıyla aynı)."""


TUR_ADLARI = {
    "IMZA": "Müşteri imzası",
    "SOZLU": "Sözlü onay",
    "BASILI_FORM": "İmzalı basılı form",
    "ALINAMADI": "Onay alınamadı",
}
# Onay türü → kabul edilen ek türü (imza canvas'ı ya da basılı formun fotoğrafı).
_EK_TURU = {"IMZA": "IMZA", "BASILI_FORM": "SERVIS_FORMU"}
_AD_ZORUNLU = frozenset({"IMZA", "SOZLU"})
ZIYARET_UST_SINIR = 150  # toplu atama sınırıyla aynı mertebede

SERVIS_TURU_ADLARI = {
    "ARIZA": "Arıza",
    "PLANSIZ_BAKIM": "Bakım",
    "DESTEK": "Destek",
    "PB": "Planlı bakım",
    "ATOLYE": "Atölye",
    "KURULUM": "Kurulum",
    "TOPLAMA": "Toplama",
    "KESIF": "Keşif",
    "DEMONTAJ": "Demontaj",
    "TASIMA": "Taşıma",
    "TESLIMAT": "Teslimat",
}
SONUC_ADLARI = {
    "COZULDU": "Çözüldü",
    "COZULEMEDI": "Çözülemedi",
    "TEKRAR_GIDILECEK": "Tekrar gidilecek",
    "TEKLIF_SUNULACAK": "Teklif sunulacak",
}
COZUM_KANALI_ADLARI = {
    "YERINDE": "Yerinde",
    "UZAKTAN": "Uzaktan",
    "TELEFON": "Telefonla",
    "ATOLYE": "Atölyede",
}
KONTROL_SONUC_ADLARI = {
    "BEKLIYOR": "Kontrol edilmedi",
    "UYGUN": "Uygun",
    "UYGUNSUZ": "Uygun değil",
    "KONTROL_EDILEMEDI": "Kontrol edilemedi",
}
BAKIM_SONUC_ADLARI = {
    "TAMAMLANDI": "Tamamlandı",
    "UYGUNSUZLUK_VAR": "Uygunsuzluk var",
    "KONTROL_EDILEMEDI": "Kontrol edilemedi",
    "TEKRAR_GIDILECEK": "Tekrar gidilecek",
}


@dataclass
class OnayGirdisi:
    tur: str  # IMZA | SOZLU | BASILI_FORM | ALINAMADI
    imzalayan_ad: str | None = None
    imzalayan_unvan: str | None = None
    ek_id: int | None = None
    eksik_nedeni: str | None = None


def _bos_mu(deger: str | None) -> bool:
    return deger is None or not deger.strip()


# --- Okuma ---------------------------------------------------------------------------


def _gecerli_kosulu() -> ColumnElement[bool]:
    """Geçerli onay: başka hiçbir onay satırı onu geçersiz kılmamış."""
    yeni = aliased(ServiceApproval)
    return ~exists().where(yeni.gecersiz_kilan_id == ServiceApproval.id)


async def gecerli_onay(db: AsyncSession, so_id: int) -> ServiceApproval | None:
    """İşin geçerli (en son, geçersiz kılınmamış) onayı."""
    return await db.scalar(
        select(ServiceApproval)
        .where(ServiceApproval.service_order_id == so_id, _gecerli_kosulu())
        .order_by(ServiceApproval.id.desc())
        .limit(1)
    )


async def onay_listesi(db: AsyncSession, so_id: int) -> list[tuple[ServiceApproval, bool]]:
    """İşin bütün onayları (yeniden eskiye) ve her birinin geçerli olup olmadığı."""
    yeni = aliased(ServiceApproval)
    gecerli = ~exists().where(yeni.gecersiz_kilan_id == ServiceApproval.id)
    satirlar = (
        await db.execute(
            select(ServiceApproval, gecerli)
            .where(ServiceApproval.service_order_id == so_id)
            .order_by(ServiceApproval.id.desc())
        )
    ).all()
    return [(onay, bool(g)) for onay, g in satirlar]


async def onay_zorunlu_mu(db: AsyncSession, so: ServiceOrder) -> bool:
    """`servis_onay_zorunlu_turler` ayarına göre (varsayılan ["PB"])."""
    from app.services import settings as ayar_svc

    turler = await ayar_svc.get(db, "servis_onay_zorunlu_turler") or []
    return so.tur in set(turler)


# --- Yazma -----------------------------------------------------------------------------


async def _ek_dogrula(
    db: AsyncSession, girdi: OnayGirdisi, izinli_isler: Sequence[int]
) -> Attachment | None:
    beklenen = _EK_TURU.get(girdi.tur)
    if beklenen is None:
        if girdi.ek_id is not None:
            raise OnayGirdiHatasi(f"{TUR_ADLARI[girdi.tur]} için ek verilmez.")
        return None
    if girdi.ek_id is None:
        raise OnayGirdiHatasi(
            f"{TUR_ADLARI[girdi.tur]} için ek zorunlu ({beklenen} türünde, önce yükleyin)."
        )
    ek = await db.get(Attachment, girdi.ek_id)
    if ek is None or ek.entity != "service_orders" or ek.entity_id not in set(izinli_isler):
        raise OnayGirdiHatasi("Seçilen ek bu servis işine ait değil.")
    if ek.kind != beklenen:
        raise OnayGirdiHatasi(f"{TUR_ADLARI[girdi.tur]} için ekin türü {beklenen} olmalı.")
    return ek


def _girdi_dogrula(girdi: OnayGirdisi) -> None:
    if girdi.tur not in ONAY_TURLERI:
        raise OnayGirdiHatasi(f"Bilinmeyen onay türü: {girdi.tur}")
    if girdi.tur == "ALINAMADI" and _bos_mu(girdi.eksik_nedeni):
        raise OnayGirdiHatasi("Onay alınamadıysa nedeni yazılmalı.")
    if girdi.tur in _AD_ZORUNLU and _bos_mu(girdi.imzalayan_ad):
        raise OnayGirdiHatasi("Onayı veren kişinin adı yazılmalı.")


def _onaylanabilir(so: ServiceOrder) -> None:
    if so.status in ("IPTAL", "KAPATILDI"):
        raise OnayHatasi(
            "İptal edilmiş ya da kapatılmış işe müşteri onayı girilemez (önce iş yeniden açılmalı)."
        )


async def _onay_yaz(
    db: AsyncSession,
    so: ServiceOrder,
    girdi: OnayGirdisi,
    *,
    user: User,
    clock: Clock,
    onay_grubu: uuid.UUID | None,
) -> ServiceApproval:
    onceki = await gecerli_onay(db, so.id)
    onay = ServiceApproval(
        service_order_id=so.id,
        tur=girdi.tur,
        imzalayan_ad=None if _bos_mu(girdi.imzalayan_ad) else girdi.imzalayan_ad.strip(),
        imzalayan_unvan=None if _bos_mu(girdi.imzalayan_unvan) else girdi.imzalayan_unvan.strip(),
        ek_id=girdi.ek_id,
        eksik_nedeni=None if _bos_mu(girdi.eksik_nedeni) else girdi.eksik_nedeni.strip(),
        gecersiz_kilan_id=onceki.id if onceki is not None else None,
        onay_grubu=onay_grubu,
        approved_at=clock.now(),
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(onay)
    await db.flush()
    # Olay geçmişine KİŞİSEL VERİ YAZILMAZ (imzalayan adı yok): tetikleyici
    # yüzünden anonimleştirme o satırı temizleyemezdi.
    veri: dict[str, Any] = {"onay_id": onay.id, "tur": onay.tur}
    if onceki is not None:
        veri["gecersiz_kilinan_id"] = onceki.id
    if onay_grubu is not None:
        veri["onay_grubu"] = str(onay_grubu)
    ozet = f"Müşteri onayı: {TUR_ADLARI[onay.tur]}"
    if onceki is not None:
        ozet += " (önceki onayın yerine)"
    await gecmis.olay_yaz(db, so, "ONAY", ozet, user=user, clock=clock, veri=veri)
    await audit.log(
        db,
        "service_approvals",
        "servis.onay",
        entity_id=onay.id,
        new_value={
            "is": so.id,
            "hesap": so.customer_id,
            "tur": onay.tur,
            "imzalayan_ad": onay.imzalayan_ad,
            "imzalayan_unvan": onay.imzalayan_unvan,
            "ek_id": onay.ek_id,
            "eksik_nedeni": onay.eksik_nedeni,
            "gecersiz_kilinan_id": onay.gecersiz_kilan_id,
            "onay_grubu": str(onay_grubu) if onay_grubu else None,
        },
        user_id=user.id,
        is_personal_data=True,
    )
    return onay


async def onay_al(
    db: AsyncSession, so: ServiceOrder, girdi: OnayGirdisi, *, user: User, clock: Clock
) -> ServiceApproval:
    """Tekil onay. Kapsam (404) ve izin (403) API'de; burada iş kuralı.
    Commit ÇAĞIRANIN işidir (denetim aynı transaction'da)."""
    if not await ek_kapsam.servis_isi_erisimi(db, user, so, yazma=True):
        raise OnayKapsamDisi("Servis işi bulunamadı")
    _girdi_dogrula(girdi)
    _onaylanabilir(so)
    await _ek_dogrula(db, girdi, [so.id])
    return await _onay_yaz(db, so, girdi, user=user, clock=clock, onay_grubu=None)


async def _ziyaret_gunu(db: AsyncSession, so: ServiceOrder, clock: Clock) -> date:
    """İşin ziyaret günü: aktif planın tarihi; plan yoksa bugün (Türkiye)."""
    gun = await db.scalar(
        select(ServicePlan.plan_date).where(
            ServicePlan.service_order_id == so.id,
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
        )
    )
    return gun or yerel_bugun(clock)


async def ziyaret_isleri(
    db: AsyncSession, is_idler: Sequence[int], *, user: User, yazma: bool
) -> list[ServiceOrder]:
    """Ziyaret listesindeki işler — biri yoksa ya da kapsam dışıysa `OnayKapsamDisi`."""
    kimlikler = list(dict.fromkeys(int(i) for i in is_idler))
    if not kimlikler:
        raise OnayGirdiHatasi("En az bir servis işi seçilmeli.")
    if len(kimlikler) > ZIYARET_UST_SINIR:
        raise OnayGirdiHatasi(f"Bir ziyarette en çok {ZIYARET_UST_SINIR} iş onaylanabilir.")
    isler = list(
        (await db.scalars(select(ServiceOrder).where(ServiceOrder.id.in_(kimlikler)))).all()
    )
    if len(isler) != len(kimlikler):
        raise OnayKapsamDisi("Servis işi bulunamadı")
    for so in isler:
        if not await ek_kapsam.servis_isi_erisimi(db, user, so, yazma=yazma):
            raise OnayKapsamDisi("Servis işi bulunamadı")
    sira = {k: i for i, k in enumerate(kimlikler)}
    return sorted(isler, key=lambda s: sira[s.id])


async def ziyaret_onayi(
    db: AsyncSession, is_idler: Sequence[int], girdi: OnayGirdisi, *, user: User, clock: Clock
) -> list[ServiceApproval]:
    """Aynı müşteri + lokasyon + gündeki işlere TEK onay (tek transaction,
    ortak `onay_grubu`). Biri bile kuralı bozarsa hiçbiri yazılmaz."""
    _girdi_dogrula(girdi)
    isler = await ziyaret_isleri(db, is_idler, user=user, yazma=True)
    musteriler = {(so.customer_id, so.address_id) for so in isler}
    if len(musteriler) > 1:
        raise OnayHatasi(
            "Ziyaret onayı yalnız aynı müşteri ve aynı lokasyondaki işler için verilebilir."
        )
    gunler = {await _ziyaret_gunu(db, so, clock) for so in isler}
    if len(gunler) > 1:
        raise OnayHatasi("Ziyaret onayı yalnız aynı gün planlanmış işler için verilebilir.")
    for so in isler:
        _onaylanabilir(so)
    await _ek_dogrula(db, girdi, [so.id for so in isler])
    grup = uuid.uuid4()
    return [await _onay_yaz(db, so, girdi, user=user, clock=clock, onay_grubu=grup) for so in isler]


# --- Kapanış kontrolü (kanca) ------------------------------------------------------------


async def _onay_kontrolu(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası: zorunlu türde onaysız TAMAMLANDI → 409."""
    if hedef != "TAMAMLANDI":
        return
    if not await onay_zorunlu_mu(db, so):
        return
    if await gecerli_onay(db, so.id) is None:
        raise OnayHatasi(
            f"{SERVIS_TURU_ADLARI.get(so.tur, so.tur)} işinde müşteri onayı zorunlu: imza, "
            "basılı form, sözlü onay ya da 'Onay alınamadı + neden' kaydı girin."
        )


kancalar.kaydet("durum_dogrula", _onay_kontrolu)


# --- Servis formu (PDF bağlamı) -------------------------------------------------------------


def _bicim(an: datetime | None) -> str | None:
    return yerel_an(an).strftime("%d.%m.%Y %H:%M") if an is not None else None


def _sure_metni(dakika: int) -> str:
    saat, dk = divmod(int(dakika), 60)
    if saat and dk:
        return f"{saat} sa {dk} dk"
    return f"{saat} sa" if saat else f"{dk} dk"


async def _sure_ozeti(db: AsyncSession, so_id: int) -> dict[str, Any]:
    """Kişi başı süre. Kayıt yoksa `kayit_var=False` → "Süre kaydı eksik" (0 DEĞİL)."""
    bitis = ServiceTimeEntry.ended_at
    dakika = func.sum(func.extract("epoch", bitis - ServiceTimeEntry.started_at) / 60.0)
    satirlar = (
        await db.execute(
            select(
                ServiceTimeEntry.user_id,
                ServiceTimeEntry.kaynak_personel_adi,
                dakika,
                func.count(),
            )
            .where(
                ServiceTimeEntry.service_order_id == so_id,
                ServiceTimeEntry.is_deleted.is_(False),
                ServiceTimeEntry.faaliyet != "MOLA",
            )
            .group_by(ServiceTimeEntry.user_id, ServiceTimeEntry.kaynak_personel_adi)
        )
    ).all()
    if not satirlar:
        return {"kayit_var": False, "kisiler": [], "toplam": None, "acik_bolum": False}
    adlar = await _kullanici_adlari(db, [s[0] for s in satirlar if s[0] is not None])
    kisiler = []
    toplam = 0
    acik = False
    for user_id, ham_ad, dk, _adet in satirlar:
        if dk is None:  # yalnız açık (bitişsiz) bölüm
            acik = True
            dk = 0
        toplam += int(round(dk))
        kisiler.append({"ad": adlar.get(user_id) or ham_ad or "—", "sure": _sure_metni(round(dk))})
    return {
        "kayit_var": True,
        "kisiler": kisiler,
        "toplam": _sure_metni(toplam),
        "acik_bolum": acik,
    }


async def _kullanici_adlari(db: AsyncSession, idler: Sequence[int]) -> dict[int, str]:
    if not idler:
        return {}
    return dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(idler)))).all())


async def _imza_gorseli(db: AsyncSession, ek_id: int | None) -> str | None:
    """İmza PNG'si PDF'e gömülür (data URI). Anonimleştirilmiş/kayıp dosyada None."""
    from app.services import storage as depo

    if ek_id is None:
        return None
    ek = await db.get(Attachment, ek_id)
    if ek is None or ek.mime_type not in depo.GORSEL_TIPLERI:
        return None
    try:
        icerik = depo.yol(ek.storage_path).read_bytes()
    except (depo.DepoHatasi, OSError):
        return None
    return f"data:{ek.mime_type};base64,{base64.b64encode(icerik).decode()}"


async def _kontrol_listesi(db: AsyncSession, so: ServiceOrder) -> dict[str, Any] | None:
    """PB işinde bakım formunun kontrol listesi bloğu (E04-16)."""
    if so.tur != "PB":
        return None
    form = await db.scalar(
        select(MaintenanceForm).where(
            MaintenanceForm.service_order_id == so.id, MaintenanceForm.is_deleted.is_(False)
        )
    )
    if form is None:
        return {"var": False, "maddeler": [], "sonuc": None, "bolge": None}
    maddeler = (
        await db.scalars(
            select(MaintenanceFormCheck)
            .where(MaintenanceFormCheck.form_id == form.id)
            .order_by(MaintenanceFormCheck.sira, MaintenanceFormCheck.id)
        )
    ).all()
    return {
        "var": True,
        "sonuc": BAKIM_SONUC_ADLARI.get(form.bakim_sonucu or "", form.bakim_sonucu),
        "bolge": form.zone,
        "yapilan": form.performed_work,
        "maddeler": [
            {
                "etiket": m.label,
                "sonuc": KONTROL_SONUC_ADLARI.get(m.result, m.result),
                "not": m.note,
            }
            for m in maddeler
        ],
    }


async def _is_bolumu(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    from app.permissions import BIRIMLER

    hesap = await db.get(Account, so.customer_id) if so.customer_id else None
    adres = await db.get(Address, so.address_id) if so.address_id else None
    sonuc = await db.scalar(
        select(ServiceResult)
        .where(ServiceResult.service_order_id == so.id, ServiceResult.gecersiz_at.is_(None))
        .order_by(ServiceResult.id.desc())
        .limit(1)
    )
    ariza = (
        await db.get(ServiceFaultReason, sonuc.ariza_nedeni_id)
        if sonuc is not None and sonuc.ariza_nedeni_id
        else None
    )
    ekip_idleri = list(
        await db.scalars(
            select(ServiceOrderAssignment.user_id)
            .where(
                ServiceOrderAssignment.service_order_id == so.id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
            .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
        )
    )
    adlar = await _kullanici_adlari(db, ekip_idleri)
    seriler = [s.seri_no for s in so.seriler if s.is_active]
    onay = await gecerli_onay(db, so.id)
    return {
        "id": so.id,
        "so_no": so.so_no,
        "birim": BIRIMLER.get(so.birim, so.birim),
        "tur": SERVIS_TURU_ADLARI.get(so.tur, so.tur),
        "pb": so.tur == "PB",
        "konu": so.konu,
        "aciklama": so.aciklama,
        "acilis": _bicim(so.reported_at or so.created_at),
        "tamamlanma": _bicim(so.completed_at),
        "musteri": hesap.title if hesap else so.customer_name_raw,
        "lokasyon": {
            "ad": adres.site_name if adres else None,
            "adres": adres.line if adres else so.location_raw,
            "ilce": adres.district if adres else None,
            "il": adres.city if adres else None,
        },
        "irtibat": so.iletisim_ad,
        "seriler": seriler,
        "ekip": [adlar[i] for i in ekip_idleri if i in adlar],
        "sonuc": (
            {
                "sonuc": SONUC_ADLARI.get(sonuc.sonuc, sonuc.sonuc),
                "kanal": COZUM_KANALI_ADLARI.get(sonuc.cozum_kanali, sonuc.cozum_kanali),
                "yapilan": sonuc.yapilan_islem,
                "ariza_nedeni": ariza.ad if ariza else None,
            }
            if sonuc is not None
            else None
        ),
        "sure": await _sure_ozeti(db, so.id),
        # Parça çıkışları Dalga 2'de (E11 stok hareketleri) gelir.
        "parcalar": [],
        "kontrol_listesi": await _kontrol_listesi(db, so),
        "onay": await _onay_bolumu(db, onay),
    }


async def _onay_bolumu(db: AsyncSession, onay: ServiceApproval | None) -> dict[str, Any] | None:
    if onay is None:
        return None
    return {
        "tur": TUR_ADLARI[onay.tur],
        "kod": onay.tur,
        "imzalayan_ad": onay.imzalayan_ad,
        "imzalayan_unvan": onay.imzalayan_unvan,
        "eksik_nedeni": onay.eksik_nedeni,
        "tarih": _bicim(onay.approved_at),
        "imza": await _imza_gorseli(db, onay.ek_id) if onay.tur == "IMZA" else None,
    }


async def _firma(db: AsyncSession) -> dict[str, Any]:
    from app.services import belgeler

    return belgeler.firma_bilgisi(await belgeler.ayar_haritasi(db))


async def servis_formu_baglami(
    db: AsyncSession, so: ServiceOrder, *, clock: Clock | None = None
) -> dict[str, Any]:
    """`templates/servis_formu.html` bağlamı (tekil iş; FİYATSIZ)."""
    return {
        "firma": await _firma(db),
        "baslik": "SERVİS FORMU",
        "toplu": False,
        "belge_tarihi": yerel_bugun(clock).strftime("%d.%m.%Y") if clock else None,
        "isler": [await _is_bolumu(db, so)],
    }


async def ziyaret_formu_baglami(
    db: AsyncSession, is_idler: Sequence[int], *, clock: Clock | None = None
) -> dict[str, Any]:
    """Ziyaret toplu formu (E04-16): aynı müşteri/lokasyondaki işler tek belgede.
    Kapsam kontrolü çağıranda (`ziyaret_isleri`)."""
    isler = list(
        (await db.scalars(select(ServiceOrder).where(ServiceOrder.id.in_(list(is_idler))))).all()
    )
    sira = {k: i for i, k in enumerate(is_idler)}
    isler.sort(key=lambda s: sira.get(s.id, 0))
    return {
        "firma": await _firma(db),
        "baslik": "SERVİS FORMU — ZİYARET",
        "toplu": True,
        "belge_tarihi": yerel_bugun(clock).strftime("%d.%m.%Y") if clock else None,
        "isler": [await _is_bolumu(db, so) for so in isler],
    }


async def servis_formu_pdf(db: AsyncSession, so: ServiceOrder, *, clock: Clock) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async(
        "servis_formu.html", **await servis_formu_baglami(db, so, clock=clock)
    )


async def ziyaret_formu_pdf(db: AsyncSession, is_idler: Sequence[int], *, clock: Clock) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async(
        "servis_formu.html", **await ziyaret_formu_baglami(db, is_idler, clock=clock)
    )


# --- KVKK kancaları (E01-18 (5), B6) ------------------------------------------------------


async def _servis_kvkk_anonimlestir(db: AsyncSession, account_id: int, clock: Clock) -> dict:
    """Hesabın servis işlerinde irtibat adı/telefonu, onaylarda imzalayan
    adı/unvanı temizlenir; imza PNG'leri indirilemez hâle getirilir.

    İşin kendisi (ticari kayıt, olay geçmişi) DURUR. İmza eki satırı onaya FK
    ile bağlı olduğu için silinmez; depo yolu geçersiz kılınır (indirme 404)
    ve dosya çöp toplamada yetim olarak kalkar. Olay geçmişinde zaten kişisel
    veri yoktur (`gecmis.olay_yaz` reddeder)."""
    from app.services.kvkk import ANONIM_ISARETI

    isler = list(
        await db.scalars(select(ServiceOrder).where(ServiceOrder.customer_id == account_id))
    )
    irtibat = 0
    for so in isler:
        if so.iletisim_ad is not None or so.iletisim_telefon is not None:
            so.iletisim_ad = None
            so.iletisim_telefon = None
            irtibat += 1
    is_idleri = [so.id for so in isler]
    onaylar = (
        list(
            await db.scalars(
                select(ServiceApproval).where(ServiceApproval.service_order_id.in_(is_idleri))
            )
        )
        if is_idleri
        else []
    )
    imza = 0
    for onay in onaylar:
        onay.imzalayan_ad = None
        onay.imzalayan_unvan = None
    imza_ekleri = (
        list(
            await db.scalars(
                select(Attachment).where(
                    Attachment.entity == "service_orders",
                    Attachment.entity_id.in_(is_idleri),
                    Attachment.kind == "IMZA",
                )
            )
        )
        if is_idleri
        else []
    )
    for ek in imza_ekleri:
        ek.storage_path = f"anonim/{ek.id}"
        ek.file_name = f"{ANONIM_ISARETI} imza {ek.id}.png"
        ek.sha256 = None
        ek.notes = None
        imza += 1
    return {"servis_irtibat": irtibat, "servis_onay": len(onaylar), "servis_imza": imza}


async def _servis_denetim_kosulu(db: AsyncSession, account_id: int) -> list[ColumnElement[bool]]:
    from app.services.kvkk import denetim_hesap_kosulu

    idler = list(
        await db.scalars(select(ServiceOrder.id).where(ServiceOrder.customer_id == account_id))
    )
    return [denetim_hesap_kosulu("service_orders", account_id, idler)]


async def _onay_denetim_kosulu(db: AsyncSession, account_id: int) -> list[ColumnElement[bool]]:
    from app.services.kvkk import denetim_hesap_kosulu

    idler = list(
        await db.scalars(
            select(ServiceApproval.id)
            .join(ServiceOrder, ServiceOrder.id == ServiceApproval.service_order_id)
            .where(ServiceOrder.customer_id == account_id)
        )
    )
    kosul = denetim_hesap_kosulu("service_approvals", account_id, idler)
    return [kosul]


async def _servis_veri_bul(db: AsyncSession, arama) -> list[dict]:
    """İlgili kişi başvurusu: servis işlerinin irtibat adı/telefonu ve onaylardaki
    imzalayan adı; bulunan hesapların servis işleri de listelenir."""
    from app.services.kvkk import _sql_katla

    onayli = select(ServiceApproval.service_order_id).where(
        _sql_katla(ServiceApproval.imzalayan_ad).contains(arama.anahtar)
    )
    kosullar = [
        _sql_katla(ServiceOrder.iletisim_ad).contains(arama.anahtar),
        ServiceOrder.id.in_(onayli),
    ]
    if arama.telefon:
        kosullar.append(ServiceOrder.iletisim_telefon == arama.telefon)
    if arama.hesap_idleri:
        kosullar.append(ServiceOrder.customer_id.in_(arama.hesap_idleri))
    isler = (
        await db.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.is_deleted.is_(False), or_(*kosullar))
            .order_by(ServiceOrder.id)
            .limit(200)
        )
    ).all()
    return [
        {
            "id": so.id,
            "so_no": so.so_no,
            "account_id": so.customer_id,
            "irtibat_ad": so.iletisim_ad,
            "irtibat_telefon": so.iletisim_telefon,
            "acilis": so.created_at,
        }
        for so in isler
    ]


def _servis_saklama_haric(sinir):
    """Saklama listesi (E01-18 (5)): son N yılda servis işi açılmış ya da
    tamamlanmış müşteri listeye girmez. NULL müşteri ayıklanır (NOT IN tuzağı)."""
    from sqlalchemy import func

    return select(ServiceOrder.customer_id).where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.customer_id.is_not(None),
        or_(
            func.date(ServiceOrder.created_at) >= sinir,
            func.date(ServiceOrder.completed_at) >= sinir,
        ),
    )


def _kvkk_kaydet() -> None:
    from app.services import kvkk

    kvkk.saklama_haric_kaydet("servis_isleri", _servis_saklama_haric)
    kvkk.anonimlestirme_kaydet(_servis_kvkk_anonimlestir)
    kvkk.denetim_maske_kaydet("service_orders", _servis_denetim_kosulu)
    kvkk.denetim_maske_kaydet("service_approvals", _onay_denetim_kosulu)
    kvkk.veri_bul_kaydet("servis_isleri", _servis_veri_bul)


_kvkk_kaydet()

__all__ = [
    "OnayGirdiHatasi",
    "OnayGirdisi",
    "OnayHatasi",
    "OnayKapsamDisi",
    "gecerli_onay",
    "onay_al",
    "onay_listesi",
    "onay_zorunlu_mu",
    "servis_formu_baglami",
    "ziyaret_formu_baglami",
    "ziyaret_onayi",
]
