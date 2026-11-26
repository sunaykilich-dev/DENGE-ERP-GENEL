"""Servis işine kütükten cihaz bilgisi (KARARLAR 2026-10-28 §12).

Kullanıcı isteği (2026-11-06):
- Haberleşme arıza işinde müşterinin KAYITLI FREKANSI, o seri numaralı cihaz /
  röle için kütükten alınıp işe otomatik gelir.
- Güvenlikte X-ray / kapı dedektörü SERİ NUMARASI kütükten alınıp işe gelir.
- Kütükte yoksa iş KAPATILMADAN teknisyen girer.

Kurallar:
- Yalnız saha ARIZA işi (`tur == ARIZA` ya da Haberleşme niteliklerinde ARIZA).
  Atölye, planlı bakım (PB), geçiş kaydı (`sla_kaynak == GECIS`) ve iptal işi
  kural dışıdır.
- Engel tek durum kapısında, KAPATILDI'ya geçişte (`kapanis_dogrula`): her
  kapatma yolu buradan geçer; kısmi giriş serbesttir.
- Kütükten gelen frekans işe KOPYALANIR (`service_frekans_bilgisi`): kütük
  sonradan değişse de işte o gün bilinen frekans kalır. Teknisyenin girdiği
  kayıt (`TEKNISYEN`) kütükten gelenle asla ezilmez.
- Kütük öğrenir: teknisyenin girdiği frekans, kütükteki cihazın frekansı BOŞSA
  kütüğe yazılır; doluysa ve farklıysa yalnız iş geçmişine not düşülür (sahadaki
  tek gözlem kütüğü sessizce değiştirmez).
- Güvenlik seri numarası işin seri listesinde (`service_order_serials`) tutulur.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    ServiceEquipment,
    ServiceFrekansBilgisi,
    ServiceOrder,
    ServiceOrderSerial,
    ServiceRoleMontaj,
    User,
)
from app.services.normalize import normalize_seri
from app.services.teknik_servis import gecmis, role_montaj
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

FREKANS = "FREKANS"
SERI = "SERI"
_GRUPLAR = ("Frekans ve mod", "Simpleks")
FREKANS_ALANLARI: tuple[str, ...] = tuple(
    a["kod"] for a in role_montaj.ALANLAR if a["grup"] in _GRUPLAR
)
FREKANS_TANIMLARI: list[dict[str, Any]] = [a for a in role_montaj.ALANLAR if a["grup"] in _GRUPLAR]
ZORUNLU_FREKANS = ("role_tx", "role_rx")
_AD = {a["kod"]: a["ad"] for a in FREKANS_TANIMLARI}
SERI_ADI = "Cihaz seri numarası"
# Kütük cihaz seçicisinde birime göre gösterilen ekipman tipleri.
KUTUK_TIPLERI = {
    "GUVENLIK": ("XRAY", "KAPI_DEDEKTORU", "EL_DEDEKTORU", "DIGER_GUVENLIK"),
    "HABERLESME": ("ROLE_TEKRARLAYICI", "TELSIZ", "ARAC_TELSIZI", "AKSESUAR", "TELSIZ_DIGER"),
}


class CihazBilgisiEksikHatasi(ServisHatasi):
    """Kütükte olmayan, teknisyenin de girmediği cihaz bilgisiyle kapanış (409)."""


def kural(so: ServiceOrder) -> str | None:
    """İşe uygulanan kural: FREKANS (Haberleşme), SERI (Güvenlik) ya da None."""
    if so.kategori == "ATOLYE" or so.tur in ("PB", "ATOLYE"):
        return None
    if so.sla_kaynak == "GECIS" or so.status == "IPTAL":
        return None
    ariza = so.tur == "ARIZA" or "ARIZA" in (so.nitelikler or [])
    if not ariza:
        return None
    if so.birim == "HABERLESME":
        return FREKANS
    if so.birim == "GUVENLIK":
        return SERI
    return None


def frekans_temizle(girdi: dict[str, Any]) -> dict[str, Any]:
    """Yalnız frekans alanları; biçim `role_montaj.temizle` ile aynı."""
    bilinmeyen = set(girdi) - set(FREKANS_ALANLARI)
    if bilinmeyen:
        raise ServisGirdiHatasi(f"Bilinmeyen frekans alanı: {', '.join(sorted(bilinmeyen))}")
    return role_montaj.temizle(girdi)


def frekans_eksikleri(frekans: dict[str, Any] | None) -> list[str]:
    f = frekans or {}
    return [_AD[k] for k in ZORUNLU_FREKANS if not str(f.get(k) or "").strip()]


def _kutuk_frekansi(frekans: dict[str, Any] | None) -> dict[str, Any] | None:
    """Kütükteki frekanstan işe kopyalanacak kısım; TX/RX yoksa kullanılmaz."""
    if not frekans:
        return None
    secili = {k: v for k, v in frekans.items() if k in FREKANS_ALANLARI and v not in (None, "")}
    return secili if not frekans_eksikleri(secili) else None


async def aktif_seriler(db: AsyncSession, so: ServiceOrder) -> list[ServiceOrderSerial]:
    return list(
        (
            await db.scalars(
                select(ServiceOrderSerial)
                .where(
                    ServiceOrderSerial.service_order_id == so.id,
                    ServiceOrderSerial.is_active.is_(True),
                )
                .order_by(ServiceOrderSerial.id)
            )
        ).all()
    )


async def ekipman_bul(
    db: AsyncSession, so: ServiceOrder, seri: str | None
) -> ServiceEquipment | None:
    """İşin kütük kaydı: bağlı ekipman; yoksa aynı birimde aynı seri anahtarlı
    TEK aktif kayıt (önce aynı müşteri). Birden çok aday → bağlanmaz."""
    if so.equipment_id is not None:
        e = await db.get(ServiceEquipment, so.equipment_id)
        if e is not None and not e.is_deleted:
            return e
    anahtar = normalize_seri(seri) if seri else ""
    if not anahtar:
        return None
    temel = select(ServiceEquipment).where(
        ServiceEquipment.serial_key == anahtar,
        ServiceEquipment.birim == so.birim,
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.is_deleted.is_(False),
    )
    if so.customer_id is not None:
        adaylar = (
            await db.scalars(temel.where(ServiceEquipment.account_id == so.customer_id).limit(2))
        ).all()
        if len(adaylar) == 1:
            return adaylar[0]
        if adaylar:
            return None
    adaylar = (await db.scalars(temel.limit(2))).all()
    return adaylar[0] if len(adaylar) == 1 else None


async def _kayit(db: AsyncSession, so: ServiceOrder) -> ServiceFrekansBilgisi | None:
    return await db.scalar(
        select(ServiceFrekansBilgisi).where(ServiceFrekansBilgisi.service_order_id == so.id)
    )


async def role_montaj_frekansi(
    db: AsyncSession, seri: str | None, *, haric_is: int | None = None
) -> dict[str, Any] | None:
    """O seri için girilmiş SON röle montaj kaydının frekansı (TX/RX dolu)."""
    anahtar = normalize_seri(seri) if seri else ""
    if not anahtar:
        return None
    stmt = (
        select(ServiceRoleMontaj)
        .join(ServiceOrder, ServiceOrder.id == ServiceRoleMontaj.service_order_id)
        .where(
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.birim == role_montaj.BIRIM,
            ServiceRoleMontaj.alanlar.has_key("role_seri_no"),
        )
        .order_by(ServiceRoleMontaj.updated_at.desc(), ServiceRoleMontaj.id.desc())
    )
    if haric_is is not None:
        stmt = stmt.where(ServiceRoleMontaj.service_order_id != haric_is)
    for kayit in (await db.scalars(stmt)).all():
        if normalize_seri(str(kayit.alanlar.get("role_seri_no") or "")) != anahtar:
            continue
        secili = _kutuk_frekansi(kayit.alanlar)
        if secili:
            return secili
    return None


async def kutukten_doldur(
    db: AsyncSession, so: ServiceOrder, *, user: User | None, clock: Clock
) -> None:
    """Açılışta ve seri değişince: kütükten seri / frekans getirir. Teknisyen
    kaydını ve var olan seriyi değiştirmez; kural dışı işte hiçbir şey yapmaz."""
    k = kural(so)
    if k is None or so.status in ("KAPATILDI", "IPTAL"):
        return
    seriler = await aktif_seriler(db, so)
    seri = seriler[0].seri_no if seriler else None
    ekipman = await ekipman_bul(db, so, seri)
    if ekipman is not None and so.equipment_id is None:
        so.equipment_id = ekipman.id
        await db.flush()

    if k == SERI:
        if seriler or ekipman is None or not ekipman.serial_no:
            return
        db.add(
            ServiceOrderSerial(
                service_order_id=so.id,
                seri_no=ekipman.serial_no,
                seri_norm=normalize_seri(ekipman.serial_no),
                created_by=user.id if user is not None else None,
            )
        )
        await db.flush()
        await gecmis.olay_yaz(
            db,
            so,
            "SERI",
            "Cihaz seri numarası kütükten alındı",
            user=user,
            clock=clock,
            veri={"kaynak": "KUTUK", "equipment_id": ekipman.id},
        )
        return

    kayit = await _kayit(db, so)
    if kayit is not None and (kayit.kaynak == "TEKNISYEN" or not frekans_eksikleri(kayit.frekans)):
        return
    frekans, kaynak = None, None
    if ekipman is not None:
        frekans = _kutuk_frekansi(ekipman.frekans)
        kaynak = "KUTUK" if frekans else None
    if frekans is None:
        frekans = await role_montaj_frekansi(
            db, seri or (ekipman.serial_no if ekipman else None), haric_is=so.id
        )
        kaynak = "ROLE_MONTAJ" if frekans else None
    if frekans is None or kaynak is None:
        return
    if kayit is None:
        kayit = ServiceFrekansBilgisi(
            service_order_id=so.id,
            created_by=user.id if user is not None else None,
            kaynak=kaynak,
            frekans=frekans,
        )
        db.add(kayit)
    else:
        kayit.kaynak, kayit.frekans = kaynak, frekans
    kayit.seri_no = seri or (ekipman.serial_no if ekipman else None)
    kayit.equipment_id = ekipman.id if ekipman else None
    kayit.updated_by = user.id if user is not None else None
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "NOT",
        "Kayıtlı frekans "
        + ("cihaz kütüğünden" if kaynak == "KUTUK" else "son röle montaj kaydından")
        + f" alındı (TX {frekans.get('role_tx')} / RX {frekans.get('role_rx')})",
        user=user,
        clock=clock,
        veri={"kaynak": kaynak},
    )


async def eksikler(db: AsyncSession, so: ServiceOrder) -> list[str] | None:
    """Kapanışı engelleyen eksikler; kural dışı iş → None."""
    k = kural(so)
    if k is None:
        return None
    if k == SERI:
        return [] if await aktif_seriler(db, so) else [SERI_ADI]
    kayit = await _kayit(db, so)
    return frekans_eksikleri(kayit.frekans if kayit else None)


async def kapanis_dogrula(db: AsyncSession, so: ServiceOrder) -> None:
    """Tek durum kapısından (KAPATILDI) çağrılır; eksik varsa 409."""
    eksik = await eksikler(db, so)
    if not eksik:
        return
    if kural(so) == SERI:
        mesaj = (
            "Güvenlik arıza işi cihaz seri numarası olmadan kapatılamaz: seri kütükte "
            "bulunamadı, teknisyen cihazın seri numarasını girmeli."
        )
    else:
        mesaj = (
            "Haberleşme arıza işi kayıtlı frekans olmadan kapatılamaz: frekans kütükte "
            f"bulunamadı, teknisyen girmeli. Eksik: {', '.join(eksik)}"
        )
    raise CihazBilgisiEksikHatasi(mesaj)


def _ekipman_ozeti(e: ServiceEquipment | None) -> dict[str, Any] | None:
    if e is None:
        return None
    return {
        "id": e.id,
        "equipment_type": e.equipment_type,
        "brand": e.brand,
        "model": e.model,
        "serial_no": e.serial_no,
        "frekans": e.frekans,
    }


async def durum(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    k = kural(so)
    seriler = await aktif_seriler(db, so)
    kayit = await _kayit(db, so) if k == FREKANS else None
    ekipman = await ekipman_bul(db, so, seriler[0].seri_no if seriler else None)
    return {
        "kural": k,
        "seri_no": seriler[0].seri_no if seriler else None,
        "ekipman": _ekipman_ozeti(ekipman),
        "frekans": kayit.frekans if kayit else {},
        "kaynak": kayit.kaynak if kayit else ("KUTUK" if k == SERI and seriler else None),
        "version": kayit.version if kayit else None,
        "eksikler": await eksikler(db, so) or [],
        "alanlar": FREKANS_TANIMLARI if k == FREKANS else [],
    }


async def _kutuge_ogret(
    db: AsyncSession,
    so: ServiceOrder,
    ekipman: ServiceEquipment | None,
    frekans: dict[str, Any],
    *,
    user: User,
    clock: Clock,
) -> None:
    """Teknisyen frekansını kütüğe yazar (boşsa); doluysa ve farklıysa not düşer."""
    from app.services.teknik_servis import ekipman as ekipman_svc

    secili = _kutuk_frekansi(frekans)
    if ekipman is None or secili is None:
        return
    if not _kutuk_frekansi(ekipman.frekans):
        eski = ekipman.frekans
        ekipman.frekans = secili
        ekipman.updated_by = user.id
        await db.flush()
        await ekipman_svc._denetim_yaz(  # noqa: SLF001 — aynı paketin denetim yardımcısı
            db,
            ekipman,
            "guncelle",
            eski={"frekans": eski},
            yeni={"frekans": secili},
            user_id=user.id,
        )
        await gecmis.olay_yaz(
            db, so, "NOT", "Girilen frekans cihaz kütüğüne yazıldı", user=user, clock=clock
        )
    elif any(ekipman.frekans.get(k) != secili.get(k) for k in ZORUNLU_FREKANS):
        await gecmis.olay_yaz(
            db,
            so,
            "NOT",
            "Sahada girilen frekans kütüktekinden farklı; kütük değiştirilmedi",
            user=user,
            clock=clock,
        )


async def _seri_yaz(
    db: AsyncSession, so: ServiceOrder, seri: str, *, user: User, clock: Clock
) -> None:
    """Eksik seri, kapanış şartı olarak teknisyence EKLENİR: tamamlanmış işte de
    gerekçe istenmez (kayıt düzeltmesi değil, eksik tamamlama). Var olan seriyi
    değiştirmek normal seri kuralıyla (`serileri_yaz`) olur."""
    from app.services.teknik_servis import is_emirleri

    if await aktif_seriler(db, so):
        await is_emirleri.serileri_yaz(db, so, [seri], user=user, clock=clock)
        return
    db.add(
        ServiceOrderSerial(
            service_order_id=so.id,
            seri_no=seri,
            seri_norm=normalize_seri(seri),
            created_by=user.id,
        )
    )
    so.updated_by = user.id
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "SERI",
        "Kütükte olmayan cihaz seri numarası girildi",
        user=user,
        clock=clock,
        veri={"kaynak": "TEKNISYEN"},
    )
    await kutukten_doldur(db, so, user=user, clock=clock)


async def kaydet(
    db: AsyncSession,
    so: ServiceOrder,
    *,
    seri_no: str | None,
    frekans: dict[str, Any] | None,
    version: int | None,
    user: User,
    clock: Clock,
) -> None:
    """Teknisyen girişi. SERI: işin serisi yazılır (`serileri_yaz`). FREKANS:
    kayıt TEKNISYEN kaynağıyla yazılır (iyimser kilit), kütük öğrenir."""
    k = kural(so)
    if k is None:
        raise ServisGirdiHatasi("Bu işte kütük cihaz bilgisi istenmez")
    if so.is_deleted or so.status in ("KAPATILDI", "IPTAL"):
        raise ServisHatasi("Kapanmış ya da iptal edilmiş işin cihaz bilgisi değiştirilemez")
    seri = (seri_no or "").strip() or None
    if k == SERI:
        if seri is None:
            raise ServisGirdiHatasi("Cihaz seri numarası boş olamaz")
        await _seri_yaz(db, so, seri, user=user, clock=clock)
        return

    temiz = frekans_temizle(frekans or {})
    if seri is not None and not await aktif_seriler(db, so):
        await _seri_yaz(db, so, seri, user=user, clock=clock)
    kayit = await _kayit(db, so)
    if kayit is None:
        if version is not None:
            raise ServisHatasi("Kayıt bulunamadı; sayfayı yenileyin")
        kayit = ServiceFrekansBilgisi(
            service_order_id=so.id, kaynak="TEKNISYEN", frekans=temiz, created_by=user.id
        )
        db.add(kayit)
    else:
        if version != kayit.version:
            raise ServisHatasi("Frekans bilgisi başka biri tarafından değişmiş; sayfayı yenileyin")
        if kayit.frekans != temiz:
            kayit.kaynak = "TEKNISYEN"
        kayit.frekans = temiz
    seriler = await aktif_seriler(db, so)
    kayit.seri_no = seriler[0].seri_no if seriler else seri
    ekipman = await ekipman_bul(db, so, kayit.seri_no)
    if ekipman is not None and so.equipment_id is None:
        so.equipment_id = ekipman.id
    kayit.equipment_id = ekipman.id if ekipman else None
    kayit.updated_by = user.id
    await db.flush()
    eksik = frekans_eksikleri(temiz)
    await gecmis.olay_yaz(
        db,
        so,
        "NOT",
        "Frekans bilgisi girildi" + (f" ({', '.join(eksik)} eksik)" if eksik else ""),
        user=user,
        clock=clock,
        veri={"kaynak": "TEKNISYEN"},
    )
    await _kutuge_ogret(db, so, ekipman, temiz, user=user, clock=clock)


async def role_montajdan_kutuge(
    db: AsyncSession, so: ServiceOrder, alanlar: dict[str, Any], *, user: User, clock: Clock
) -> None:
    """Röle montaj kaydı TX/RX ile tamamsa o serideki Haberleşme cihazının
    kütük frekansı (boşsa) doldurulur."""
    seri = str(alanlar.get("role_seri_no") or "").strip() or None
    if seri is None or _kutuk_frekansi(alanlar) is None:
        return
    ekipman = await ekipman_bul(db, so, seri)
    if ekipman is None or ekipman.birim != role_montaj.BIRIM:
        return
    if _kutuk_frekansi(ekipman.frekans):
        return
    await _kutuge_ogret(db, so, ekipman, alanlar, user=user, clock=clock)


async def musteri_cihazlari(
    db: AsyncSession,
    user: User,
    *,
    birim: str,
    musteri_id: int,
    adres_id: int | None = None,
) -> list[dict[str, Any]]:
    """İş açma formundaki kütük seçicisi: müşterinin (tesisin) aktif cihazları."""
    from app.services.teknik_servis import ekipman as ekipman_svc

    tipler = KUTUK_TIPLERI.get(birim)
    if not tipler:
        return []
    stmt = select(ServiceEquipment).where(
        ServiceEquipment.birim == birim,
        ServiceEquipment.equipment_type.in_(tipler),
        ServiceEquipment.account_id == musteri_id,
        ServiceEquipment.is_active.is_(True),
        ServiceEquipment.is_deleted.is_(False),
    )
    if adres_id is not None:
        stmt = stmt.where(ServiceEquipment.address_id == adres_id)
    stmt = ekipman_svc.ekipman_kosulu(user)(stmt).order_by(
        ServiceEquipment.equipment_type, ServiceEquipment.serial_no
    )
    sonuc = []
    for e in (await db.scalars(stmt.limit(200))).all():
        ozet = _ekipman_ozeti(e) or {}
        if birim == "HABERLESME" and not _kutuk_frekansi(e.frekans):
            ozet["frekans"] = await role_montaj_frekansi(db, e.serial_no)
        sonuc.append(ozet)
    return sonuc
