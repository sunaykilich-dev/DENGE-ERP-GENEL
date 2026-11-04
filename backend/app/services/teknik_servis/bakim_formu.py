"""Dijital bakım formu, PB koruması, dönem kapanışı, kapsam dışı, uygunsuzluk
(E04-09…14/20, TS-064…068).

**PB'nin iki kapısı vardır** (`pb_gecis_dogrula`, `durum_dogrula` kancası):
TAMAMLANDI'ya yalnız bakım formu (`kaynak='bakim_formu'`), IPTAL'e yalnız
onaylı kapsam dışı talebi (`kaynak='kapsam_disi'`) götürür. Genel durum ucu,
`/sonuc` ve `/iptal` 409 alır ve kullanıcıya Kapsam Dışı yolunu gösterir:
aksi halde PB formu doldurulmadan "tamamlandı" sayılır ya da sözleşmeli cihaz
sessizce dönemden düşerdi (E04-10). Açık uygunsuzluk aksiyonu varken PB
TAMAMLANDI olamaz.

**Ziyaret kaydı değişmez:** her BAŞARILI tamamlamada `maintenance_visits`
satırı yazılır (o gün sahada ne kaydedildiği); başarısız istek transaction'ı
geri aldığı için iz bırakmaz (E04 kontrol #11). Yeniden açma (E01
`TEKRAR_ACILDI`, `servis.kapat`) formu TASLAK'a döndürür ve `YENIDEN_ACMA`
ziyaret satırı yazar; eski ziyaret silinmez.

**Uygunsuzluk akışı (karar S1):** Uygunsuz madde notu zorunludur; tamamlamada
her uygunsuz madde bir ACIK aksiyon olur ve PB `BAKIM_UYGUNSUZLUK`
beklemesine girer (dönem açık kalır). Son aksiyon kapanınca bekleme biter
ve form zaten tamamlanmışsa PB aynı kapıdan (`bakim_formu`) TAMAMLANDI olur.

**Dönem kapanışı hesaplanır, sayılmaz:** `donem_kapanisi_hesapla` dönemin PB
durumlarından kapanışı yeniden türetir (idempotent, geri açabilir): hepsi
kapalı ve iptal yok → TAMAMLANDI; çözülen + iptal → KISMI; hepsi iptal →
YAPILAMADI; açık PB varsa dönem açılır. Gece uzlaştırması aynı fonksiyonu
koşar ve farkı log'a yazar (E04-D02).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import exists, func, select

from app.models import (
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenanceExclusionRequest,
    MaintenanceForm,
    MaintenanceFormCheck,
    MaintenanceNonconformity,
    MaintenancePeriod,
    MaintenanceVisit,
    ServiceApproval,
    ServiceEquipment,
    ServiceHold,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceOrderSerial,
    ServiceResult,
)
from app.models.servis_bakim import (
    BAKIM_OLCUMLERI,
    BAKIM_SONUCLARI,
    KAPSAM_DISI_NEDENLERI,
    KONTROL_SONUCLARI,
    UYGUNSUZLUK_AKSIYONLARI,
    UYGUNSUZLUK_ONEMLERI,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services import audit
from app.services.normalize import normalize_seri
from app.services.teknik_servis import bekletme, gecmis, is_emirleri, kancalar
from app.services.teknik_servis.bakim import BakimHatasi, BakimKapsamDisi
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

logger = logging.getLogger("denge.bakim")

_KAPALI = DURUM_GRUPLARI["KAPALI"]
_COZULDU = DURUM_GRUPLARI["COZULDU"]
NOT_ZORUNLU_SONUCLAR = frozenset({"UYGUNSUZ", "KONTROL_EDILEMEDI"})
# Bakım sonucu → servis sonucu (E01 `service_results`, tek sonuç kaynağı).
_SERVIS_SONUCU = {
    "TAMAMLANDI": "COZULDU",
    "UYGUNSUZLUK_VAR": "COZULDU",
    "KONTROL_EDILEMEDI": "COZULEMEDI",
}
UYGUNSUZLUK_BEKLEME = "BAKIM_UYGUNSUZLUK"
# Dalga 2'de TS-147 (servis teklifi) ile açılır; Dalga 1'de pasif.
PASIF_AKSIYONLAR = frozenset({"TEKLIF"})
# Bakım formu olan iş türleri (rol testi tur 2, 5_teknisyen B2; KARARLAR
# 2026-11-04 §7.5): sözleşmeli PB'ye ek olarak sözleşmesiz/talep listesi bakımı
# (PLANSIZ_BAKIM). PB formu üretimde açılır; PLANSIZ_BAKIM formu ilk yazmada
# işin cihazının türünden (`equipment_type` → şablon) açılır. PB'ye özgü kapılar
# (dönem kapanışı, kapsam dışı) yalnız PB'de kalır.
BAKIM_FORMU_TURLERI = frozenset({"PB", "PLANSIZ_BAKIM"})
# Uygunsuzluk önemi → bağlı arıza işinin önceliği (KRİTİK bulgu KRİTİK iş).
_ONEM_ONCELIK = {"KRITIK": "KRITIK", "YUKSEK": "YUKSEK"}


# =============================================================================
# PB koruma kancası ve dönem kapanışı (TS-065)
# =============================================================================


async def acik_uygunsuzluk_sayisi(db: AsyncSession, so_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(MaintenanceNonconformity.id)).where(
                MaintenanceNonconformity.service_order_id == so_id,
                MaintenanceNonconformity.status == "ACIK",
                MaintenanceNonconformity.is_deleted.is_(False),
            )
        )
        or 0
    )


async def pb_gecis_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası (yalnız tur='PB')."""
    if so.tur != "PB":
        return
    if hedef == "TAMAMLANDI":
        if kaynak != "bakim_formu":
            raise BakimHatasi(
                "Planlı bakım işi bakım formundan tamamlanır; formu doldurup 'Formu Tamamla' "
                "ile kapatın. Cihaz bu dönem bakılamayacaksa Kapsam Dışı talebi açın."
            )
        if await acik_uygunsuzluk_sayisi(db, so.id):
            raise BakimHatasi(
                "Açık uygunsuzluk aksiyonu varken planlı bakım işi tamamlanamaz; "
                "önce aksiyonları kapatın."
            )
    if hedef == "IPTAL" and kaynak != "kapsam_disi":
        raise BakimHatasi(
            "Planlı bakım işi iptal edilemez. Cihazı bu dönemden çıkarmak için bakım "
            "formundan Kapsam Dışı talebi açın; şef onaylayınca iş kapanır."
        )


async def donem_kapanisi_hesapla(db: AsyncSession, donem: MaintenancePeriod, clock: Clock) -> bool:
    """Dönemin kapanışını PB durumlarından yeniden türetir; değiştiyse True.

    İdempotent ve geri açabilir: aynı durumda ikinci çağrı hiçbir şey
    yazmaz; yeniden açılan PB dönemi açar (sayaç kendiliğinden −1). Göç
    başlangıç kapanışı (`GOC_BASLANGIC`) korunur.
    """
    if donem.closing_kind == "GOC_BASLANGIC":
        return False
    durumlar = list(
        (
            await db.scalars(
                select(ServiceOrder.status).where(
                    ServiceOrder.maintenance_period_id == donem.id,
                    ServiceOrder.tur == "PB",
                    ServiceOrder.is_deleted.is_(False),
                )
            )
        ).all()
    )
    if not durumlar:
        return False
    if all(d in _KAPALI for d in durumlar):
        cozulen = sum(1 for d in durumlar if d in _COZULDU)
        iptal = len(durumlar) - cozulen
        tur = "TAMAMLANDI" if iptal == 0 else ("KISMI" if cozulen else "YAPILAMADI")
        if donem.closing_kind == tur and donem.closed_at is not None:
            return False
        donem.closing_kind = tur
        donem.closed_at = clock.now()
    else:
        if donem.closed_at is None:
            return False
        donem.closing_kind = None
        donem.closed_at = None
    await db.flush()
    return True


async def _yeniden_acma_izi(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """TEKRAR_ACILDI: form TASLAK'a döner, YENIDEN_ACMA ziyaret satırı yazılır.

    Kanca imzasında gerekçe ve kullanıcı yok (plan §1.8); ikisi de E01'in az
    önce yazdığı DURUM olayından okunur (aynı transaction).
    """
    form = await db.scalar(select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id))
    if form is None:
        return
    olay = await db.scalar(
        select(ServiceOrderEvent)
        .where(
            ServiceOrderEvent.service_order_id == so.id,
            ServiceOrderEvent.yeni_durum == so.status,
            ServiceOrderEvent.eski_durum == "TAMAMLANDI"
            if so.status != "TEKRAR_ACILDI"
            else ServiceOrderEvent.yeni_durum == "TEKRAR_ACILDI",
        )
        .order_by(ServiceOrderEvent.id.desc())
        .limit(1)
    )
    gerekce = None
    kisi = None
    if olay is not None:
        kisi = olay.user_id
        veri = olay.veri or {}
        # E01 gerekçeyi DURUM olayının özetine "… — gerekçe: X" olarak yazar.
        gerekce = veri.get("gerekce") or (
            olay.ozet.split("gerekçe:", 1)[1].strip() if "gerekçe:" in olay.ozet else olay.ozet
        )
    form.status = "TASLAK"
    form.completed_at = None
    form.completed_by = None
    seri = await _aktif_seri(db, so.id)
    db.add(
        MaintenanceVisit(
            form_id=form.id,
            service_order_id=so.id,
            visit_no=await _sonraki_ziyaret_no(db, form.id),
            visited_at=clock.now(),
            technician_user_id=kisi,
            tur="YENIDEN_ACMA",
            bakim_sonucu=form.bakim_sonucu,
            serial_no=seri.seri_no if seri else None,
            zone=form.zone,
            performed_work=form.performed_work,
            gerekce=(gerekce or "Yeniden açıldı")[:2000],
            created_by=kisi,
        )
    )
    await db.flush()


async def donem_kapanisini_guncelle(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: dönem kapanışı (idempotent, geri açabilir).

    Yeniden açma ve kalite reddi (rol testi tur 2) formu TASLAK'a döndürür; bu,
    formu olan sözleşmesiz bakım işinde (PLANSIZ_BAKIM) de geçerlidir."""
    if hedef == "TEKRAR_ACILDI" or kaynak == "kalite_red":
        await _yeniden_acma_izi(db, so, clock)
    if so.tur != "PB" or so.maintenance_period_id is None:
        return
    donem = await db.get(MaintenancePeriod, so.maintenance_period_id)
    if donem is not None:
        await donem_kapanisi_hesapla(db, donem, clock)


async def donem_uzlastirma_gorevi(db: AsyncSession, clock: Clock) -> str:
    """Worker görevi `bakim-donem-uzlastirma`: PB'si olan her dönemin kapanışı
    yeniden türetilir. Fark çıkması bir yolun kancayı atladığını gösterir;
    düzeltilir ve log'a yazılır (sessiz kalmasın)."""
    donemler = (
        await db.scalars(
            select(MaintenancePeriod).where(
                MaintenancePeriod.is_deleted.is_(False),
                exists().where(
                    ServiceOrder.maintenance_period_id == MaintenancePeriod.id,
                    ServiceOrder.tur == "PB",
                    ServiceOrder.is_deleted.is_(False),
                ),
            )
        )
    ).all()
    farkli: list[int] = []
    for donem in donemler:
        if await donem_kapanisi_hesapla(db, donem, clock):
            farkli.append(donem.id)
    if farkli:
        logger.warning("bakım dönem uzlaştırması %d farkı düzeltti: %s", len(farkli), farkli[:20])
    return f"{len(donemler)} dönem tarandı, {len(farkli)} kapanış düzeltildi"


# =============================================================================
# Form (TS-064)
# =============================================================================


async def _aktif_seri(db: AsyncSession, so_id: int) -> ServiceOrderSerial | None:
    return await db.scalar(
        select(ServiceOrderSerial)
        .where(
            ServiceOrderSerial.service_order_id == so_id,
            ServiceOrderSerial.is_active.is_(True),
        )
        .order_by(ServiceOrderSerial.id.desc())
        .limit(1)
    )


async def _sonraki_ziyaret_no(db: AsyncSession, form_id: int) -> int:
    en_buyuk = await db.scalar(
        select(func.max(MaintenanceVisit.visit_no)).where(MaintenanceVisit.form_id == form_id)
    )
    return int(en_buyuk or 0) + 1


async def form_getir(db: AsyncSession, so: ServiceOrder) -> MaintenanceForm:
    if so.tur not in BAKIM_FORMU_TURLERI:
        raise BakimKapsamDisi("Bu iş bakım işi değil; bakım formu yok")
    form = await db.scalar(select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id))
    if form is None or form.is_deleted:
        raise BakimKapsamDisi("Bakım formu bulunamadı")
    return form


async def form_ac(
    db: AsyncSession, so: ServiceOrder, *, user: User, clock: Clock
) -> MaintenanceForm:
    """Sözleşmesiz bakım işinde (PLANSIZ_BAKIM) formu ilk kullanımda açar
    (idempotent: varsa onu döner). Şablon işin cihazının türünden gelir;
    cihazı olmayan ya da şablonu olmayan türde 404 (açıklamalı)."""
    from app.services.teknik_servis.bakim_sablonlari import sablon as sablon_bul

    if so.tur not in BAKIM_FORMU_TURLERI:
        raise BakimKapsamDisi("Bu iş bakım işi değil; bakım formu yok")
    mevcut = await db.scalar(
        select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id)
    )
    if mevcut is not None and not mevcut.is_deleted:
        return mevcut
    if so.tur == "PB":
        raise BakimKapsamDisi("Bakım formu bulunamadı")
    ekipman = await db.get(ServiceEquipment, so.equipment_id) if so.equipment_id else None
    if ekipman is None:
        raise BakimKapsamDisi(
            "İşe bağlı cihaz (kütük kaydı) yok; bakım formu cihazın türünden açılır. "
            "Önce işe cihaz bağlayın."
        )
    sablon = sablon_bul(ekipman.equipment_type)
    if sablon is None:
        raise BakimKapsamDisi(f"'{ekipman.equipment_type}' cihaz türü için bakım şablonu yok")
    form = MaintenanceForm(
        service_order_id=so.id,
        template_code=ekipman.equipment_type,
        template_version=sablon.surum,
        zone=ekipman.zone,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(form)
    await db.flush()
    for sira, madde in enumerate(sablon.maddeler, start=1):
        db.add(
            MaintenanceFormCheck(
                form_id=form.id, check_code=madde.kod, label=madde.etiket, sira=sira
            )
        )
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "NOT",
        f"Bakım formu açıldı ({ekipman.equipment_type}, şablon s{sablon.surum})",
        user=user,
        clock=clock,
        veri={"form_id": form.id, "sablon": ekipman.equipment_type},
    )
    return form


def olcumler(form: MaintenanceForm) -> dict[str, str] | None:
    """Dolu ölçümler (metin; ziyaret kaydına kopyalanır). Hiç yoksa None."""
    dolu = {k: str(getattr(form, k)) for k in BAKIM_OLCUMLERI if getattr(form, k) is not None}
    return dolu or None


async def form_maddeleri(db: AsyncSession, form_id: int) -> list[MaintenanceFormCheck]:
    return list(
        (
            await db.scalars(
                select(MaintenanceFormCheck)
                .where(MaintenanceFormCheck.form_id == form_id)
                .order_by(MaintenanceFormCheck.sira)
            )
        ).all()
    )


def _form_acik_mi(form: MaintenanceForm, so: ServiceOrder) -> None:
    if so.status in _KAPALI:
        raise BakimHatasi(f"İş {so.status.replace('_', ' ').lower()}; form değiştirilemez")
    if form.status != "TASLAK":
        raise BakimHatasi(
            "Form tamamlandı; düzeltme için iş yeniden açılmalı (Servis İşleri → Yeniden Aç)"
        )


async def _seri_yaz(
    db: AsyncSession, so: ServiceOrder, yeni: str, *, user: User, clock: Clock
) -> None:
    """PB serisi `service_order_serials`'ta (tek kaynak, E04 kontrol #8); eski
    satır silinmez, pasiflenir. Genel uçta PB serisi düzeltilemez (E01-17);
    bakım formu bağlamında sahadaki gerçek seri buradan girilir."""
    yeni = yeni.strip()
    if not yeni:
        raise ServisGirdiHatasi("Seri no boş olamaz")
    eski = await _aktif_seri(db, so.id)
    if eski is not None and normalize_seri(eski.seri_no) == normalize_seri(yeni):
        if eski.seri_no != yeni:
            eski.seri_no = yeni
            await db.flush()
        return
    simdi = clock.now()
    if eski is not None:
        eski.is_active = False
        eski.removed_at = simdi
        eski.removed_by = user.id
        await db.flush()
    db.add(
        ServiceOrderSerial(service_order_id=so.id, seri_no=yeni, seri_norm="", created_by=user.id)
    )
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "SERI",
        f"Bakım formunda seri no {'değişti' if eski else 'girildi'}: {yeni}",
        user=user,
        clock=clock,
        veri={"eski": eski.seri_no if eski else None, "yeni": yeni, "kaynak": "bakim_formu"},
    )


async def form_kaydet(
    db: AsyncSession,
    form: MaintenanceForm,
    degisiklikler: dict,
    *,
    so: ServiceOrder,
    user: User,
    clock: Clock,
) -> MaintenanceForm:
    """Taslak kaydı (ziyaret kaydı OLUŞTURMAZ). Madde notu zorunluluğu 400;
    tamamlanmış form ve kapalı iş 409."""
    _form_acik_mi(form, so)
    simdi = clock.now()
    for alan in ("zone", "performed_work", "technician_note", "parts_text"):
        if alan in degisiklikler:
            deger = degisiklikler[alan]
            setattr(form, alan, deger.strip() or None if isinstance(deger, str) else deger)
    for alan in BAKIM_OLCUMLERI:
        if alan in degisiklikler:
            deger = degisiklikler[alan]
            if deger is not None and deger < 0:
                raise ServisGirdiHatasi(f"{BAKIM_OLCUMLERI[alan][0]} negatif olamaz")
            setattr(form, alan, deger)
    if "bakim_sonucu" in degisiklikler:
        sonuc = degisiklikler["bakim_sonucu"]
        if sonuc is not None and sonuc not in BAKIM_SONUCLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen bakım sonucu: {sonuc}")
        form.bakim_sonucu = sonuc
    if degisiklikler.get("seri_no") is not None:
        await _seri_yaz(db, so, degisiklikler["seri_no"], user=user, clock=clock)
    kontroller = degisiklikler.get("kontroller") or []
    if kontroller:
        maddeler = {m.check_code: m for m in await form_maddeleri(db, form.id)}
        for k in kontroller:
            madde = maddeler.get(k["kod"])
            if madde is None:
                raise ServisGirdiHatasi(f"Formda olmayan kontrol maddesi: {k['kod']}")
            sonuc = k["sonuc"]
            if sonuc not in KONTROL_SONUCLARI:
                raise ServisGirdiHatasi(f"Bilinmeyen kontrol sonucu: {sonuc}")
            not_ = (k.get("not_") or "").strip() or None
            if sonuc in NOT_ZORUNLU_SONUCLAR and not not_:
                raise ServisGirdiHatasi(
                    f"'{madde.label}' maddesi {sonuc.replace('_', ' ').lower()} işaretlendi; "
                    "açıklama notu zorunlu"
                )
            onem = k.get("onem")
            if onem is not None and onem not in UYGUNSUZLUK_ONEMLERI:
                raise ServisGirdiHatasi(f"Bilinmeyen önem: {onem}")
            # Önem yalnız uygunsuz maddede anlamlıdır (diğerlerinde temizlenir).
            onem = onem if sonuc == "UYGUNSUZ" else None
            if madde.result != sonuc or madde.note != not_ or madde.onem != onem:
                madde.result = sonuc
                madde.note = not_
                madde.onem = onem
                madde.checked_by = user.id
                madde.checked_at = simdi
    form.updated_by = user.id
    await db.flush()
    return form


@dataclass
class TamamlamaSonucu:
    form: MaintenanceForm
    durum: str
    uyarilar: list[str] = field(default_factory=list)
    acilan_uygunsuzluklar: int = 0


async def gecerli_onay(db: AsyncSession, so_id: int) -> ServiceApproval | None:
    """Geçerli (sonradan geçersiz kılınmamış) müşteri onayı — E01 onay
    modülünün tek tanımı (`onay.gecerli_onay`)."""
    from app.services.teknik_servis import onay as onay_svc

    return await onay_svc.gecerli_onay(db, so_id)


async def _servis_sonucu_yaz(
    db: AsyncSession, so: ServiceOrder, form: MaintenanceForm, *, user: User | None
) -> None:
    """E01 sonuç kaynağına PB sonucu (sonuçsuz TAMAMLANDI yoktur)."""
    db.add(
        ServiceResult(
            service_order_id=so.id,
            sonuc=_SERVIS_SONUCU.get(form.bakim_sonucu or "TAMAMLANDI", "COZULDU"),
            cozum_kanali="YERINDE",
            yapilan_islem=(form.performed_work or "Planlı bakım formu tamamlandı").strip(),
            saha_bolge=form.zone,
            kutuk_fark_durumu=form.kutuk_fark_durumu,
            created_by=user.id if user else None,
        )
    )
    await db.flush()


async def _ekipman_bagla(
    db: AsyncSession, so: ServiceOrder, form: MaintenanceForm, seri: str
) -> list[str]:
    """Tamamlamada sahadaki seri kütükle karşılaştırılır (E04-17).

    Farklıysa `kutuk_fark_durumu=ACIK` (kütük düzeltmesi E03 ekranında).
    Aynı cari + tür + birimde TEK ekipman bu seriyi taşıyorsa kalem ona
    bağlanmaya çalışılır; EXCLUDE ihlali (başka sözleşmede kapsamda)
    tamamlamayı BLOKE ETMEZ, uyarı döner.
    """
    uyarilar: list[str] = []
    if so.contract_item_id is None:
        return uyarilar
    kalem = await db.get(MaintenanceContractItem, so.contract_item_id)
    ekipman = await db.get(ServiceEquipment, so.equipment_id) if so.equipment_id else None
    norm = normalize_seri(seri)
    if ekipman is not None and ekipman.serial_key == norm:
        return uyarilar
    form.kutuk_fark_durumu = "ACIK"
    uyarilar.append(
        f"Sahadaki seri ({seri}) kütükteki seriyle "
        f"({ekipman.serial_no if ekipman else 'yok'}) uyuşmuyor; kütük farkı açıldı."
    )
    if kalem is None:
        return uyarilar
    sozlesme = await db.get(MaintenanceContract, kalem.contract_id)
    adaylar = (
        await db.scalars(
            select(ServiceEquipment.id).where(
                ServiceEquipment.serial_key == norm,
                ServiceEquipment.is_deleted.is_(False),
                ServiceEquipment.is_active.is_(True),
                ServiceEquipment.equipment_type == kalem.equipment_type,
                ServiceEquipment.account_id == (sozlesme.account_id if sozlesme else None),
                ServiceEquipment.birim == so.birim,
            )
        )
    ).all()
    if len(adaylar) != 1 or adaylar[0] == kalem.equipment_id:
        return uyarilar
    try:
        async with db.begin_nested():
            kalem.equipment_id = adaylar[0]
            so.equipment_id = adaylar[0]
            await db.flush()
        uyarilar.append("Kalem sahadaki seriyi taşıyan ekipmana bağlandı.")
    except Exception:  # EXCLUDE: ekipman başka sözleşmede kapsamda
        await db.refresh(kalem)
        await db.refresh(so)
        uyarilar.append(
            "Sahadaki seriyi taşıyan ekipman başka bir sözleşmenin kapsamında; "
            "bağ kurulmadı, eşleştirme ekranından düzeltin."
        )
    return uyarilar


async def tamamla(
    db: AsyncSession,
    form: MaintenanceForm,
    *,
    so: ServiceOrder,
    user: User,
    clock: Clock,
    sure_eksik_onay: bool = False,
) -> TamamlamaSonucu:
    """Doğrulama + ziyaret + uygunsuzluk aksiyonu/bekleme + PB kapanışı.

    PB TAMAMLANDI'ya gidecekse süre kaydı eksikliği sorulur (TS-076,
    `zaman.sure_eksik_kapanis_dogrula`): onaysız 409, onaylı NOT olayı.
    """
    _form_acik_mi(form, so)
    if so.status == "BEKLEMEDE":
        raise BakimHatasi("İş beklemede; önce beklemeyi bitirin")
    if await acik_uygunsuzluk_sayisi(db, so.id):
        raise BakimHatasi("Açık uygunsuzluk aksiyonu varken form tamamlanamaz")
    maddeler = await form_maddeleri(db, form.id)
    bekleyen = [m.label for m in maddeler if m.result == "BEKLIYOR"]
    if bekleyen:
        raise BakimHatasi(
            f"{len(bekleyen)} kontrol maddesi işaretlenmedi",
            veri={"kod": "BEKLEYEN_MADDE", "maddeler": bekleyen},
        )
    for m in maddeler:
        if m.result in NOT_ZORUNLU_SONUCLAR and not (m.note or "").strip():
            raise ServisGirdiHatasi(f"'{m.label}' maddesi için açıklama notu zorunlu")
    seri = await _aktif_seri(db, so.id)
    eksik = [
        ad
        for ad, deger in (
            ("seri no", seri.seri_no if seri else None),
            ("bölge", form.zone),
            ("teknisyen notu", form.technician_note),
            ("bakım sonucu", form.bakim_sonucu),
        )
        if not (deger or "").strip()
    ]
    if eksik:
        raise ServisGirdiHatasi(f"Formda eksik alan: {', '.join(eksik)}")
    uygunsuzlar = [m for m in maddeler if m.result == "UYGUNSUZ"]
    if uygunsuzlar and form.bakim_sonucu == "TAMAMLANDI":
        raise ServisGirdiHatasi("Uygunsuz madde varken bakım sonucu 'Uygunsuzluk Var' olmalı")
    if form.bakim_sonucu == "UYGUNSUZLUK_VAR" and not uygunsuzlar:
        raise ServisGirdiHatasi("'Uygunsuzluk Var' sonucu için en az bir madde Uygunsuz olmalı")
    from app.services.teknik_servis import onay as onay_svc

    zorunlu = await onay_svc.onay_zorunlu_mu(db, so)
    onay = await gecerli_onay(db, so.id)
    if zorunlu and onay is None and form.bakim_sonucu != "TEKRAR_GIDILECEK":
        raise BakimHatasi(
            "Müşteri onayı alınmadan form tamamlanamaz (imza, sözlü, basılı form ya da "
            "'alınamadı' + neden)"
        )
    if form.bakim_sonucu != "TEKRAR_GIDILECEK" and not uygunsuzlar:
        from app.services.teknik_servis import zaman

        await zaman.sure_eksik_kapanis_dogrula(db, so, onay=sure_eksik_onay, user=user, clock=clock)

    simdi = clock.now()
    sonuc = TamamlamaSonucu(form, so.status)
    db.add(
        MaintenanceVisit(
            form_id=form.id,
            service_order_id=so.id,
            visit_no=await _sonraki_ziyaret_no(db, form.id),
            visited_at=simdi,
            technician_user_id=user.id,
            tur="TAMAMLAMA",
            bakim_sonucu=form.bakim_sonucu,
            serial_no=seri.seri_no if seri else None,
            zone=form.zone,
            performed_work=form.performed_work,
            checks=[
                {"code": m.check_code, "label": m.label, "result": m.result, "note": m.note}
                for m in maddeler
            ],
            approval_id=onay.id if onay else None,
            olcumler=olcumler(form),
            created_by=user.id,
        )
    )
    await db.flush()

    if form.bakim_sonucu == "TEKRAR_GIDILECEK":
        # Ziyaret kaydedildi ama bakım bitmedi: form taslak, iş açık kalır.
        await gecmis.olay_yaz(
            db,
            so,
            "NOT",
            "Bakım ziyareti kaydedildi; tekrar gidilecek (form açık kaldı)",
            user=user,
            clock=clock,
        )
        sonuc.uyarilar.append("Ziyaret kaydedildi; tekrar gidileceği için iş açık kaldı.")
        await audit.log(
            db,
            "maintenance_forms",
            "bakim.form.ziyaret",
            entity_id=form.id,
            new_value={"so_id": so.id, "bakim_sonucu": form.bakim_sonucu},
            user_id=user.id,
        )
        return sonuc

    form.status = "TAMAMLANDI"
    form.completed_at = simdi
    form.completed_by = user.id
    form.updated_by = user.id
    sonuc.uyarilar.extend(await _ekipman_bagla(db, so, form, seri.seri_no if seri else ""))
    await db.flush()

    for m in uygunsuzlar:
        db.add(
            MaintenanceNonconformity(
                form_id=form.id,
                service_order_id=so.id,
                check_code=m.check_code,
                check_label=m.label,
                description=m.note,
                onem=m.onem,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    await db.flush()
    if uygunsuzlar:
        sonuc.acilan_uygunsuzluklar = len(uygunsuzlar)
        await bekletme.beklet(
            db,
            so,
            UYGUNSUZLUK_BEKLEME,
            user=user,
            clock=clock,
            aciklama=f"{len(uygunsuzlar)} uygunsuz madde için aksiyon bekleniyor",
            sistem=True,
        )
        sonuc.uyarilar.append(
            f"{len(uygunsuzlar)} uygunsuzluk aksiyonu açıldı; iş aksiyonlar kapanana kadar "
            "beklemede."
        )
    else:
        await _servis_sonucu_yaz(db, so, form, user=user)
        await is_emirleri.durum_degistir(
            db, so, "TAMAMLANDI", kaynak="bakim_formu", user=user, clock=clock
        )
    sonuc.durum = so.status
    await audit.log(
        db,
        "maintenance_forms",
        "bakim.form.tamamla",
        entity_id=form.id,
        new_value={
            "so_id": so.id,
            "bakim_sonucu": form.bakim_sonucu,
            "uygunsuzluk": len(uygunsuzlar),
        },
        user_id=user.id,
    )
    return sonuc


# =============================================================================
# Kapsam dışı (TS-066)
# =============================================================================


async def kapsam_disi_talep(
    db: AsyncSession, so: ServiceOrder, neden: str, aciklama: str, *, user: User, clock: Clock
) -> MaintenanceExclusionRequest:
    if so.tur != "PB" or so.contract_item_id is None or so.maintenance_period_id is None:
        raise BakimKapsamDisi("Bu iş planlı bakım işi değil")
    if neden not in KAPSAM_DISI_NEDENLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen kapsam dışı nedeni: {neden}")
    if not (aciklama or "").strip():
        raise ServisGirdiHatasi("Kapsam dışı talebinde açıklama zorunlu")
    if so.status in _KAPALI:
        raise BakimHatasi("Kapalı işte kapsam dışı talebi açılamaz")
    acik = await db.scalar(
        select(MaintenanceExclusionRequest.id).where(
            MaintenanceExclusionRequest.service_order_id == so.id,
            MaintenanceExclusionRequest.status == "TALEP",
            MaintenanceExclusionRequest.is_deleted.is_(False),
        )
    )
    if acik:
        raise BakimHatasi("Bu iş için karar bekleyen bir kapsam dışı talebi zaten var")
    talep = MaintenanceExclusionRequest(
        service_order_id=so.id,
        contract_item_id=so.contract_item_id,
        maintenance_period_id=so.maintenance_period_id,
        reason_code=neden,
        description=aciklama.strip(),
        requested_by=user.id,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(talep)
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "NOT",
        f"Kapsam dışı talebi açıldı ({neden})",
        user=user,
        clock=clock,
        veri={"talep_id": talep.id, "neden": neden},
    )
    await audit.log(
        db,
        "maintenance_exclusion_requests",
        "bakim.kapsam_disi.talep",
        entity_id=talep.id,
        new_value={"so_id": so.id, "neden": neden},
        user_id=user.id,
    )
    return talep


async def kapsam_disi_karar(
    db: AsyncSession,
    talep: MaintenanceExclusionRequest,
    onay: bool,
    *,
    not_: str | None,
    user: User,
    clock: Clock,
) -> MaintenanceExclusionRequest:
    """Şef kararı. Kişi kendi talebine karar veremez (409; şemada
    `ck_mer_kendi_onayi`). Onayda PB `IPTAL` (`kaynak='kapsam_disi'`); satır
    silinmediği için aynı cihaz–dönem yeniden üretilmez."""
    if talep.status != "TALEP":
        raise BakimHatasi("Talep zaten karara bağlanmış")
    if talep.requested_by == user.id:
        raise BakimHatasi(
            "Kendi kapsam dışı talebinize karar veremezsiniz; başka bir şef onaylamalı"
        )
    so = await db.get(ServiceOrder, talep.service_order_id)
    if so is None:  # pragma: no cover - FK bütünlüğü
        raise BakimKapsamDisi("Kayıt bulunamadı")
    talep.status = "ONAYLANDI" if onay else "REDDEDILDI"
    talep.decided_by = user.id
    talep.decided_at = clock.now()
    talep.decision_note = (not_ or "").strip() or None
    talep.updated_by = user.id
    await db.flush()
    if onay:
        await is_emirleri.durum_degistir(
            db,
            so,
            "IPTAL",
            kaynak="kapsam_disi",
            user=user,
            clock=clock,
            gerekce=f"Kapsam dışı ({talep.reason_code}): {talep.description}"[:500],
        )
    else:
        await gecmis.olay_yaz(
            db,
            so,
            "NOT",
            "Kapsam dışı talebi reddedildi",
            user=user,
            clock=clock,
            veri={"talep_id": talep.id},
        )
    await audit.log(
        db,
        "maintenance_exclusion_requests",
        "bakim.kapsam_disi.karar",
        entity_id=talep.id,
        new_value={"onay": onay, "not": talep.decision_note},
        user_id=user.id,
    )
    return talep


# =============================================================================
# Uygunsuzluk aksiyonları (TS-067)
# =============================================================================


async def uygunsuzluk_guncelle(
    db: AsyncSession,
    kayit: MaintenanceNonconformity,
    degisiklikler: dict,
    *,
    user: User,
    clock: Clock,
) -> MaintenanceNonconformity:
    if kayit.status != "ACIK":
        raise BakimHatasi("Kapalı aksiyon değiştirilemez")
    if "action_type" in degisiklikler:
        tur = degisiklikler["action_type"]
        if tur is not None and tur not in UYGUNSUZLUK_AKSIYONLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen aksiyon türü: {tur}")
        if tur in PASIF_AKSIYONLAR:
            raise BakimHatasi("Teklif aksiyonu teklif modülüyle (Dalga 2) açılacak")
        kayit.action_type = tur
    if "responsible_user_id" in degisiklikler:
        kayit.responsible_user_id = degisiklikler["responsible_user_id"]
    if "due_date" in degisiklikler:
        kayit.due_date = degisiklikler["due_date"]
    kayit.updated_by = user.id
    await audit.log_change(db, kayit, "bakim.uygunsuzluk.guncelle", user_id=user.id)
    await db.flush()
    return kayit


async def uygunsuzluk_ariza_isi(
    db: AsyncSession, kayit: MaintenanceNonconformity, *, user: User, clock: Clock
) -> ServiceOrder:
    """Önceden doldurulmuş ARIZA işi; PB'ye `BAKIM_BULGUSU` ile bağlı, tek
    transaction. Otomatik açılmaz (karar 20): şef düğmeye basar."""
    if kayit.status != "ACIK":
        raise BakimHatasi("Kapalı aksiyon için arıza işi açılamaz")
    if kayit.linked_service_order_id is not None:
        raise BakimHatasi("Bu aksiyona bağlı arıza işi zaten var")
    pb = await db.get(ServiceOrder, kayit.service_order_id)
    if pb is None:  # pragma: no cover - FK bütünlüğü
        raise BakimKapsamDisi("Kayıt bulunamadı")
    seri = await _aktif_seri(db, pb.id)
    # Rol testi tur 2 (B3): konu bulgunun KENDİSİ (teknisyenin notu); madde etiketi
    # ("… kontrol edildi") açıklamaya. Önem KRİTİK/YÜKSEK ise iş önceliği de öyle.
    bulgu = " ".join((kayit.description or "").split()) or kayit.check_label
    girdi = is_emirleri.ServisIsiGirdisi(
        birim=pb.birim,
        tur="ARIZA",
        konu=f"Bakım bulgusu: {bulgu}"[:200],
        customer_id=pb.customer_id,
        address_id=pb.address_id,
        contact_id=pb.contact_id,
        talep_kanali="SAHADA_BILDIRILDI",
        oncelik=_ONEM_ONCELIK.get(kayit.onem or "", "NORMAL"),
        aciklama=(
            f"{pb.so_no} bakımında uygunsuzluk ({kayit.check_label}): {kayit.description or ''}"
        ).strip(),
        seriler=[seri.seri_no] if seri else [],
        equipment_id=pb.equipment_id,
        iliskili_is_id=pb.id,
        iliski_turu="BAKIM_BULGUSU",
    )
    ariza = await is_emirleri.olustur(db, girdi, user=user, clock=clock)
    kayit.linked_service_order_id = ariza.id
    kayit.action_type = "ARIZA_IS_EMRI"
    kayit.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "maintenance_nonconformities",
        "bakim.uygunsuzluk.ariza_isi",
        entity_id=kayit.id,
        new_value={"so_id": ariza.id, "so_no": ariza.so_no},
        user_id=user.id,
    )
    return ariza


async def uygunsuzluk_kapat(
    db: AsyncSession, kayit: MaintenanceNonconformity, not_: str, *, user: User, clock: Clock
) -> MaintenanceNonconformity:
    """Aksiyonu kapatır. Son açık aksiyon kapanınca `BAKIM_UYGUNSUZLUK`
    beklemesi biter; form tamamlanmışsa PB bakım formu kapısından
    TAMAMLANDI olur (dönem kapanışı kancayla)."""
    if kayit.status != "ACIK":
        raise BakimHatasi("Aksiyon zaten kapalı")
    if not (not_ or "").strip():
        raise ServisGirdiHatasi("Kapanış notu zorunlu")
    kayit.status = "KAPALI"
    kayit.closing_note = not_.strip()
    kayit.closed_by = user.id
    kayit.closed_at = clock.now()
    kayit.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "maintenance_nonconformities",
        "bakim.uygunsuzluk.kapat",
        entity_id=kayit.id,
        new_value={"not": kayit.closing_note},
        user_id=user.id,
    )
    if await acik_uygunsuzluk_sayisi(db, kayit.service_order_id):
        return kayit
    so = await db.get(ServiceOrder, kayit.service_order_id)
    if so is None:  # pragma: no cover - FK bütünlüğü
        raise BakimKapsamDisi("Kayıt bulunamadı")
    bekleme = await db.scalar(
        select(ServiceHold).where(
            ServiceHold.service_order_id == so.id, ServiceHold.released_at.is_(None)
        )
    )
    if so.status == "BEKLEMEDE" and bekleme is not None and bekleme.neden == UYGUNSUZLUK_BEKLEME:
        await bekletme.beklemeyi_bitir(
            db, so, user=user, clock=clock, not_="Uygunsuzluk aksiyonları kapandı"
        )
    form = await db.scalar(select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id))
    if form is not None and form.status == "TAMAMLANDI" and so.status not in _KAPALI:
        await _servis_sonucu_yaz(db, so, form, user=user)
        await is_emirleri.durum_degistir(
            db, so, "TAMAMLANDI", kaynak="bakim_formu", user=user, clock=clock
        )
    return kayit


async def ziyaretler(db: AsyncSession, form_id: int) -> list[MaintenanceVisit]:
    return list(
        (
            await db.scalars(
                select(MaintenanceVisit)
                .where(MaintenanceVisit.form_id == form_id)
                .order_by(MaintenanceVisit.visit_no)
            )
        ).all()
    )


def ziyaret_satiri(z: MaintenanceVisit) -> dict[str, Any]:
    return {
        "visit_no": z.visit_no,
        "tur": z.tur,
        "visited_at": z.visited_at,
        "technician_user_id": z.technician_user_id,
        "bakim_sonucu": z.bakim_sonucu,
        "serial_no": z.serial_no,
        "zone": z.zone,
        "gerekce": z.gerekce,
        "approval_id": z.approval_id,
    }


# --- Kanca kayıtları (modül sonu; `s/__init__` sabit sırayla import eder) ----------


async def sozlesme_gelirini_yaz(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası (rol testi tur 2 Y4, KARARLAR 2026-11-04 §7.6): PB
    TAMAMLANDI olunca sözleşmenin ziyaret başı ücreti (TRY) işin geliri olarak
    `SOZLESME` kaynağıyla yazılır; böylece kalite onayından sonra fatura devrine
    düşer. Elle girilmiş gelir ya da faturaya iletilmiş iş ASLA ezilmez; ücret
    yoksa (ya da dövizliyse) hiçbir şey yazılmaz (gelir "sözleşme kapsamı" kalır).
    Yeniden tamamlamada tutar aynı kalır (idempotent)."""
    if so.tur != "PB" or hedef != "TAMAMLANDI" or so.contract_item_id is None:
        return
    from app.models.servis_maliyet import ServiceOrderFinancial

    kalem = await db.get(MaintenanceContractItem, so.contract_item_id)
    sozlesme = await db.get(MaintenanceContract, kalem.contract_id) if kalem else None
    if sozlesme is None or sozlesme.fee_per_visit is None or sozlesme.currency != "TRY":
        return
    fin = await db.scalar(
        select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
    )
    if fin is not None and (fin.gelir is not None or fin.fatura_iletildi_at is not None):
        return
    if fin is None:
        fin = ServiceOrderFinancial(
            service_order_id=so.id, created_by=so.updated_by, updated_by=so.updated_by
        )
        db.add(fin)
    fin.gelir = sozlesme.fee_per_visit
    fin.gelir_kaynagi = "SOZLESME"
    fin.gelir_notu = f"Sözleşme {sozlesme.contract_no} ziyaret başı ücreti (otomatik)"
    await db.flush()
    await audit.log(
        db,
        "service_order_financials",
        "gelir.sozlesme_otomatik",
        entity_id=fin.id,
        new_value={"so_id": so.id, "gelir": str(fin.gelir), "sozlesme": sozlesme.contract_no},
        user_id=so.updated_by,
    )


kancalar.kaydet("durum_dogrula", pb_gecis_dogrula)
kancalar.kaydet("durum_degisti", donem_kapanisini_guncelle)
kancalar.kaydet("durum_degisti", sozlesme_gelirini_yaz)
