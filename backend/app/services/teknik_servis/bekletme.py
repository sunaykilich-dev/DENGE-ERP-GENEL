"""Servis işi bekletme akışı ve bekleme nedeni kataloğu (E01-05, E10-03, TS-023).

Tek aktif bekleme (`uq_hold_aktif`; servis ayrıca önceden sorar ve okunur
409 verir). Neden katalog tablosudur (`service_hold_reasons`, FK): katalog
dışı/pasif neden 400, `sadece_sistem` neden kullanıcıdan 400,
`aciklama_zorunlu` ise açıklama şart (400). `sla_durdurur` açılışta
katalogdan DONDURULUR. BEKLEMEDE dışına HER geçişte aktif bekleme aynı
transaction'da kapanır (`aktif_beklemeyi_kapat` → `durum_degisti` kancası).

`beklemeyi_bitir` işi `onceki_durum`'a döndürür; o geçiş artık makinede
yoksa (ör. YOLA_CIKILDI'dan bekletilmiş iş) PLANLAMADA'ya döner ve olay
özeti bunu söyler (E01-05).

Katalog düzenleme `operasyon.yonet` izniyle API'den yapılır; satır silinmez,
`is_active=false` ile kapanır (FK geçmiş beklemeleri korur).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models import ServiceHold, ServiceHoldReason
from app.services.statemachine import SERVIS_IS_EMRI
from app.services.teknik_servis import gecmis, kancalar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, User


class BeklemeHatasi(ServisHatasi):
    """Bekleme kural ihlali → 409."""


KOD_KALIBI = re.compile(r"^[A-Z][A-Z0-9_]{1,29}$")
ACIKLAMA_UZUNLUGU = 500


def _dakika(bas: datetime, bit: datetime) -> int:
    return max(0, int((bit - bas).total_seconds() // 60))


async def aktif_bekleme(db: AsyncSession, so: ServiceOrder) -> ServiceHold | None:
    return await db.scalar(
        select(ServiceHold).where(
            ServiceHold.service_order_id == so.id, ServiceHold.released_at.is_(None)
        )
    )


async def beklet(
    db: AsyncSession,
    so: ServiceOrder,
    neden: str,
    *,
    user: User | None,
    clock: Clock,
    aciklama: str | None = None,
    beklenen_bitis_at: datetime | None = None,
    sistem: bool = False,
) -> ServiceHold:
    """İşi BEKLEMEDE'ye alır (`durum_degistir(kaynak='bekleme')`).
    `sistem=True` yalnız servis fonksiyonları içindir (ör. BAKIM_UYGUNSUZLUK)."""
    from app.services.teknik_servis import is_emirleri

    katalog = await db.scalar(select(ServiceHoldReason).where(ServiceHoldReason.kod == neden))
    if katalog is None or not katalog.is_active:
        raise ServisGirdiHatasi(f"Bekleme nedeni katalogda yok ya da pasif: {neden}")
    if katalog.sadece_sistem and not sistem:
        raise ServisGirdiHatasi(f"'{katalog.ad}' nedeni yalnız sistem tarafından açılır")
    aciklama = (aciklama or "").strip() or None
    if aciklama is not None and len(aciklama) > ACIKLAMA_UZUNLUGU:
        raise ServisGirdiHatasi(f"Açıklama en çok {ACIKLAMA_UZUNLUGU} karakter olabilir")
    if (katalog.aciklama_zorunlu or katalog.kod == "DIGER") and aciklama is None:
        raise ServisGirdiHatasi(f"'{katalog.ad}' nedeninde açıklama zorunlu")
    simdi = clock.now()
    if beklenen_bitis_at is not None:
        if beklenen_bitis_at.tzinfo is None:
            raise ServisGirdiHatasi("Beklenen bitiş saat dilimi bilgisiyle girilmeli")
        if beklenen_bitis_at < simdi:
            raise ServisGirdiHatasi("Beklenen bitiş geçmiş bir zaman olamaz")
    if await aktif_bekleme(db, so) is not None:
        raise BeklemeHatasi("İşte zaten aktif bir bekleme var")

    onceki = so.status
    await is_emirleri.durum_degistir(db, so, "BEKLEMEDE", kaynak="bekleme", user=user, clock=clock)
    bekleme = ServiceHold(
        service_order_id=so.id,
        neden=katalog.kod,
        aciklama=aciklama,
        onceki_durum=onceki,
        started_at=simdi,
        started_by=user.id if user is not None else None,
        beklenen_bitis_at=beklenen_bitis_at,
        sla_durdurur=katalog.sla_durdurur,
        otomatik_kapandi=False,
    )
    db.add(bekleme)
    await db.flush()
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "BEKLEME",
            f"Bekletildi: {katalog.ad}" + (f" — {aciklama}" if aciklama else ""),
            user=user,
            clock=clock,
            eski_durum=onceki,
            yeni_durum="BEKLEMEDE",
            veri={
                "neden": katalog.kod,
                "sla_durdurur": katalog.sla_durdurur,
                "beklenen_bitis_at": beklenen_bitis_at.isoformat() if beklenen_bitis_at else None,
            },
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Açıklamaya irtibat adı veya telefonu yazılamaz") from exc
    return bekleme


# Rol testi tur 2 (6_satis Y1/Y2/O5, KARARLAR 2026-11-04 §7.1): teklif kararı
# (kabul/red) ve parça gelişi işi sahaya YENİDEN gidilecek noktaya getirir.
# Saha durumundan (yola çıkıldı/sahada/işlemde) bekletilmiş iş bu nedenlerle
# İŞLEMDE'ye değil planlama kuyruğuna (PLANLAMADA) döner: "Plan bekleyen"
# KPI'sında ve planlama havuzunda görünür, zilde `planlamaya_donen` uyarısı
# sorumluya/şefe düşer. İstisna: beklemeyi işin AKTİF ekibinden biri bitiriyorsa
# (ör. teknisyen kendi araç deposundan parçayı çıkarıp işi sürdürüyor) iş önceki
# durumuna döner — kişi zaten sahadadır, yeniden plan gereksiz adım olurdu.
PLANLAMAYA_DONEN_NEDENLER = frozenset({"TEKLIF", "MALZEME"})
SAHA_DURUMLARI = frozenset({"YOLA_CIKILDI", "SAHADA", "ISLEMDE"})


def _donus_durumu(onceki: str, neden: str | None = None, *, ekip_ici: bool = False) -> str:
    """Beklemeden dönülecek durum (tek kural; `beklemeyi_bitir` çağırır)."""
    if neden in PLANLAMAYA_DONEN_NEDENLER and onceki in SAHA_DURUMLARI and not ekip_ici:
        return "PLANLAMADA"
    if SERVIS_IS_EMRI.izinli_mi("BEKLEMEDE", onceki):
        return onceki
    return "PLANLAMADA"


async def _ekip_ici_mi(db: AsyncSession, so: ServiceOrder, user: User | None) -> bool:
    if user is None:
        return False
    from app.models import ServiceOrderAssignment

    return (
        await db.scalar(
            select(ServiceOrderAssignment.id)
            .where(
                ServiceOrderAssignment.service_order_id == so.id,
                ServiceOrderAssignment.user_id == user.id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
            .limit(1)
        )
    ) is not None


async def beklemeyi_bitir(
    db: AsyncSession, so: ServiceOrder, *, user: User | None, clock: Clock, not_: str | None = None
) -> ServiceHold:
    """Beklemeyi kapatır, `onceki_durum`'a döner; `sure_dk` yazılır."""
    from app.services.teknik_servis import is_emirleri

    bekleme = await aktif_bekleme(db, so)
    if bekleme is None or so.status != "BEKLEMEDE":
        raise BeklemeHatasi("İşte aktif bekleme yok")
    not_ = (not_ or "").strip() or None
    if not_ is not None and len(not_) > 200:
        raise ServisGirdiHatasi("Kapanış notu en çok 200 karakter olabilir")
    simdi = clock.now()
    hedef = _donus_durumu(
        bekleme.onceki_durum, bekleme.neden, ekip_ici=await _ekip_ici_mi(db, so, user)
    )
    # Önce bekleme kapanır: `durum_degisti` kancası aktif bekleme bulmasın.
    bekleme.released_at = simdi
    bekleme.released_by = user.id if user is not None else None
    bekleme.sure_dk = _dakika(bekleme.started_at, simdi)
    bekleme.kapanis_notu = not_
    bekleme.otomatik_kapandi = False
    await db.flush()
    await is_emirleri.durum_degistir(db, so, hedef, kaynak="bekleme", user=user, clock=clock)
    katalog = await db.scalar(
        select(ServiceHoldReason).where(ServiceHoldReason.kod == bekleme.neden)
    )
    ozet = f"Bekleme bitti: {katalog.ad if katalog else bekleme.neden} ({bekleme.sure_dk} dk)"
    if hedef == "PLANLAMADA" and bekleme.neden in PLANLAMAYA_DONEN_NEDENLER:
        ozet += "; iş yeniden planlanmak üzere planlama kuyruğuna döndü"
    elif hedef != bekleme.onceki_durum:
        ozet += (
            f"; önceki duruma ({is_emirleri.DURUM_ADLARI[bekleme.onceki_durum]}) dönülemediği "
            f"için {is_emirleri.DURUM_ADLARI[hedef]}"
        )
    if not_:
        ozet += f" — {not_}"
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "BEKLEME_BITTI",
            ozet,
            user=user,
            clock=clock,
            eski_durum="BEKLEMEDE",
            yeni_durum=hedef,
            veri={"neden": bekleme.neden, "sure_dk": bekleme.sure_dk},
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Nota irtibat adı veya telefonu yazılamaz") from exc
    return bekleme


async def aktif_beklemeyi_kapat(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: BEKLEMEDE'den `beklemeyi_bitir` dışı bir yolla
    çıkılırsa aktif beklemeyi `otomatik_kapandi=True` ile kapatır."""
    if onceki != "BEKLEMEDE" or hedef == "BEKLEMEDE":
        return
    bekleme = await aktif_bekleme(db, so)
    if bekleme is None:
        return
    simdi = clock.now()
    bekleme.released_at = simdi
    bekleme.released_by = None
    bekleme.sure_dk = _dakika(bekleme.started_at, simdi)
    bekleme.otomatik_kapandi = True
    await db.flush()


async def bekleme_gecmisi(db: AsyncSession, so: ServiceOrder) -> list[ServiceHold]:
    return list(
        (
            await db.scalars(
                select(ServiceHold)
                .where(ServiceHold.service_order_id == so.id)
                .order_by(ServiceHold.started_at, ServiceHold.id)
            )
        ).all()
    )


async def toplam_bekleme_dk(db: AsyncSession, so_idler: list[int], clock: Clock) -> dict[int, int]:
    """İş başına toplam bekleme dakikası (kapanmış `sure_dk` + açık beklemenin
    şimdiye kadarki süresi). Detay ve Excel aynı fonksiyonu kullanır."""
    if not so_idler:
        return {}
    simdi = clock.now()
    sonuc: dict[int, int] = dict.fromkeys(so_idler, 0)
    kapali = await db.execute(
        select(ServiceHold.service_order_id, func.coalesce(func.sum(ServiceHold.sure_dk), 0))
        .where(ServiceHold.service_order_id.in_(so_idler), ServiceHold.released_at.is_not(None))
        .group_by(ServiceHold.service_order_id)
    )
    for so_id, toplam in kapali.all():
        sonuc[so_id] += int(toplam)
    acik = await db.execute(
        select(ServiceHold.service_order_id, ServiceHold.started_at).where(
            ServiceHold.service_order_id.in_(so_idler), ServiceHold.released_at.is_(None)
        )
    )
    for so_id, bas in acik.all():
        sonuc[so_id] += _dakika(bas, simdi)
    return sonuc


async def neden_katalogu(
    db: AsyncSession, *, yalniz_secilebilir: bool = True
) -> list[ServiceHoldReason]:
    """Ekranda seçilebilir nedenler (aktif ve `sadece_sistem=false`)."""
    stmt = select(ServiceHoldReason).order_by(ServiceHoldReason.sira, ServiceHoldReason.kod)
    if yalniz_secilebilir:
        stmt = stmt.where(
            ServiceHoldReason.is_active.is_(True), ServiceHoldReason.sadece_sistem.is_(False)
        )
    return list((await db.scalars(stmt)).all())


async def neden_kaydet(
    db: AsyncSession,
    *,
    kod: str,
    ad: str,
    sla_durdurur: bool,
    aciklama_zorunlu: bool,
    sira: int,
    is_active: bool,
    version: int | None = None,
) -> tuple[ServiceHoldReason, dict, dict]:
    """Katalog satırını ekler ya da günceller (kod anahtar). (satır, eski, yeni).

    - kod biçimi `^[A-Z][A-Z0-9_]{1,29}$` (400);
    - var olan satırda `version` zorunlu, uyuşmazsa 409;
    - `sadece_sistem` ekrandan değiştirilmez (sistem nedenleri kodla açılır);
    - DIGER'de açıklama zorunluluğu kaldırılamaz (`ck_hold_diger_aciklama`).
    """
    kod = (kod or "").strip().upper()
    ad = (ad or "").strip()
    if not KOD_KALIBI.match(kod):
        raise ServisGirdiHatasi("Kod büyük harf, rakam ve alt çizgiden oluşmalı (2-30 karakter)")
    if not ad or len(ad) > 80:
        raise ServisGirdiHatasi("Ad 1-80 karakter olmalı")
    if not 0 <= sira <= 999:
        raise ServisGirdiHatasi("Sıra 0-999 arasında olmalı")
    if kod == "DIGER" and not aciklama_zorunlu:
        raise ServisGirdiHatasi("'Diğer' nedeninde açıklama zorunluluğu kaldırılamaz")
    satir = await db.scalar(select(ServiceHoldReason).where(ServiceHoldReason.kod == kod))
    alanlar = {
        "ad": ad,
        "sla_durdurur": sla_durdurur,
        "aciklama_zorunlu": aciklama_zorunlu,
        "sira": sira,
        "is_active": is_active,
    }
    if satir is None:
        satir = ServiceHoldReason(kod=kod, sadece_sistem=False, **alanlar)
        db.add(satir)
        await db.flush()
        return satir, {}, {"kod": kod, **alanlar}
    if version is None:
        raise ServisGirdiHatasi("Var olan nedeni düzenlerken sürüm (version) zorunlu")
    if version != satir.version:
        raise BeklemeHatasi("Kayıt başka biri tarafından değiştirildi; yenileyin")
    eski = {k: getattr(satir, k) for k in alanlar}
    for k, v in alanlar.items():
        setattr(satir, k, v)
    await db.flush()
    return satir, eski, alanlar


kancalar.kaydet("durum_degisti", aktif_beklemeyi_kapat)
