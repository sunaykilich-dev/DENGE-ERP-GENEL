"""Hak ediş hesabı ve dönem kapanışı.

DİKKAT — VERGİ: aşağıdaki formüller Türkiye'deki yaygın uygulamaya göre
yazıldı ve CANLIYA ÇIKMADAN ÖNCE MALİ MÜŞAVİRE TEYİT ETTİRİLMELİDİR.
Oranların hiçbiri koda gömülü değil; `settings` tablosundan gelir ve
hesaplama anında dökümün `tax_snapshot` alanına DONDURULUR — oran sonradan
değişse bile geçmiş döküm aynı sonucu üretir.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Account,
    InstallationPartner,
    PartnerSettlement,
    SettlementLine,
    WorkOrder,
    WorkOrderItem,
)
from app.models.settlement import is_tipi_coz
from app.services import settings as ayar_svc

KURUS = Decimal("0.01")


def yuvarla(deger: Decimal | int) -> Decimal:
    """Kuruşa yuvarlama — SATIR BAZINDA, banker's rounding değil.

    Muhasebe 1 kuruşu tartışır; yöntem testle çivilenmiştir.

    `int` de kabul edilir: boş bir dizinin `sum()`'ı `Decimal` değil `int 0`
    döndürür ve kayıt olmayan dönemde panel bu yüzden 500 veriyordu. `float`
    KABUL EDİLMEZ — ikilik kesir para tutarını sessizce kaydırır.
    """
    return Decimal(deger).quantize(KURUS, rounding=ROUND_HALF_UP)


@dataclass
class VergiProfili:
    """Belge tipine göre kesinti kuralları."""

    belge_tipi: str
    kdv_oran: Decimal = Decimal("0")
    stopaj_oran: Decimal = Decimal("0")
    damga_oran: Decimal = Decimal("0")


@dataclass
class HesapSonucu:
    brut: Decimal
    kesinti: Decimal
    stopaj: Decimal
    damga: Decimal
    kdv: Decimal
    net: Decimal
    snapshot: dict = field(default_factory=dict)


async def vergi_profili(db: AsyncSession, belge_tipi: str) -> VergiProfili:
    ayarlar = await ayar_svc.get_all(db)
    kdv = Decimal(str(ayarlar["kdv_oran_varsayilan"]))
    if belge_tipi == "FATURA":
        # Şirket faturası: stopaj yok, KDV faturaya eklenir.
        return VergiProfili("FATURA", kdv_oran=kdv)
    if belge_tipi == "SERBEST_MESLEK_MAKBUZU":
        return VergiProfili(
            "SERBEST_MESLEK_MAKBUZU",
            kdv_oran=kdv,
            stopaj_oran=Decimal(str(ayarlar["stopaj_smm_oran"])),
            damga_oran=Decimal(str(ayarlar["damga_vergisi_oran"])),
        )
    if belge_tipi == "GIDER_PUSULASI":
        # Esnaf muafiyeti kapsamında stopaj; KDV yok.
        return VergiProfili(
            "GIDER_PUSULASI",
            stopaj_oran=Decimal(str(ayarlar["stopaj_gider_pusulasi_oran"])),
        )
    # BELİRSİZ: kesinti uygulanmaz, döküm brütle çıkar ve belge tipi
    # netleşene kadar onaya düşmez.
    return VergiProfili("BELIRSIZ")


def hesapla(*, brut: Decimal, kesinti: Decimal, profil: VergiProfili) -> HesapSonucu:
    """Döküm tutarlarını hesaplar.

    Matrah = brüt − kesinti. KDV matrah üzerine EKLENİR; stopaj ve damga
    matrahtan DÜŞÜLÜR.
    """
    matrah = yuvarla(brut - kesinti)
    kdv = yuvarla(matrah * profil.kdv_oran)
    stopaj = yuvarla(matrah * profil.stopaj_oran)
    damga = yuvarla(matrah * profil.damga_oran)
    net = yuvarla(matrah + kdv - stopaj - damga)
    return HesapSonucu(
        brut=yuvarla(brut),
        kesinti=yuvarla(kesinti),
        stopaj=stopaj,
        damga=damga,
        kdv=kdv,
        net=net,
        snapshot={
            "belge_tipi": profil.belge_tipi,
            "kdv_oran": str(profil.kdv_oran),
            "stopaj_oran": str(profil.stopaj_oran),
            "damga_oran": str(profil.damga_oran),
        },
    )


async def dokum_tutarlarini_guncelle(db: AsyncSession, dokum: PartnerSettlement) -> HesapSonucu:
    """Satırlardan dökümün toplamlarını yeniden hesaplar."""
    satirlar = (
        await db.scalars(select(SettlementLine).where(SettlementLine.settlement_id == dokum.id))
    ).all()
    brut = sum((Decimal(str(s.amount)) for s in satirlar if not s.is_deduction), Decimal("0"))
    kesinti = sum((Decimal(str(s.amount)) for s in satirlar if s.is_deduction), Decimal("0"))

    ortak = await db.get(InstallationPartner, dokum.partner_id)
    profil = await vergi_profili(db, ortak.document_type if ortak else "BELIRSIZ")
    sonuc = hesapla(brut=brut, kesinti=kesinti, profil=profil)

    dokum.gross_amount = sonuc.brut
    dokum.deduction_amount = sonuc.kesinti
    dokum.withholding_amount = sonuc.stopaj
    dokum.stamp_tax_amount = sonuc.damga
    dokum.vat_amount = sonuc.kdv
    dokum.net_payable = sonuc.net
    dokum.tax_snapshot = sonuc.snapshot
    await db.flush()
    return sonuc


class DonemKilitli(Exception):
    """Ödenmiş dönem değiştirilemez."""


@dataclass
class KapanisSonucu:
    """`donem_kapat` çıktısı.

    `kilitli_atlanan`, ÖDENMİŞ bir döküme ait olduğu için bu kapanışta
    yazılamayan iş emri kalemleridir. Eskiden bunlar `continue` ile sessizce
    atlanıyor ve uç boş liste döndürüyordu: montaj noktası, kapanmış bir
    döneme sonradan giren işin parasını HİÇBİR ZAMAN almıyordu ve kimse
    fark etmiyordu. Kapanmış dönem hâlâ değişmez — ama artık görünür.
    """

    dokumler: list["PartnerSettlement"] = field(default_factory=list)
    kilitli_atlanan: list[dict] = field(default_factory=list)


async def donem_kapat(
    db: AsyncSession, *, period: str, clock: Clock, partner_id: int | None = None
) -> KapanisSonucu:
    """Dönemdeki onaylı iş emirlerinden hak ediş dökümlerini üretir.

    Tekrar çalıştırılabilir: var olan TASLAK dökümün satırları
    `uq_sl_kalem` sayesinde kopyalanmaz, yalnız eksikler eklenir.
    ÖDENMİŞ döküm asla değiştirilmez — ona düşen kalemler `kilitli_atlanan`
    ile RAPORLANIR; kullanıcı iş emrinin hak ediş dönemini sonraki aya alıp
    (`PATCH /api/is-emirleri/{id}/hakedis-donemi`) yeniden kapatır.
    """
    stmt = (
        select(WorkOrder, WorkOrderItem)
        .join(WorkOrderItem, WorkOrderItem.work_order_id == WorkOrder.id)
        .where(
            WorkOrder.settlement_period == period,
            WorkOrder.status.in_(("TAMAMLANDI", "ONAYLANDI")),
            WorkOrder.assigned_type == "MONTAJ_NOKTASI",
            WorkOrder.assigned_id.is_not(None),
            WorkOrder.is_deleted.is_(False),
            WorkOrderItem.payability == "ODENECEK",
        )
    )
    if partner_id is not None:
        stmt = stmt.where(WorkOrder.assigned_id == partner_id)

    gruplar: dict[int, list[tuple[WorkOrder, WorkOrderItem]]] = {}
    for wo, kalem in (await db.execute(stmt)).all():
        gruplar.setdefault(wo.assigned_id, []).append((wo, kalem))

    sonuc = KapanisSonucu()
    for nokta_id, kayitlar in gruplar.items():
        dokum = await db.scalar(
            select(PartnerSettlement).where(
                PartnerSettlement.partner_id == nokta_id, PartnerSettlement.period == period
            )
        )
        if dokum is None:
            ortak = await db.get(InstallationPartner, nokta_id)
            dokum = PartnerSettlement(
                partner_id=nokta_id,
                period=period,
                status="TASLAK",
                billing_account_id=ortak.billing_account_id if ortak else None,
            )
            db.add(dokum)
            await db.flush()
        elif dokum.kilitli:
            # Ödenmiş dönem DEĞİŞMEZ (plan §3.3/3). Ama düşen kalemler
            # sayılır ve geri bildirilir; sessizce atmak, hak edişin
            # kaybolması demekti.
            yazili = {
                s_.work_order_item_id
                for s_ in (
                    await db.scalars(
                        select(SettlementLine).where(SettlementLine.settlement_id == dokum.id)
                    )
                ).all()
            }
            for wo, kalem in kayitlar:
                if kalem.id in yazili or kalem.unit_price is None:
                    continue
                sonuc.kilitli_atlanan.append(
                    {
                        "montaj_noktasi_id": nokta_id,
                        "dokum_id": dokum.id,
                        "is_emri_id": wo.id,
                        "is_emri_no": wo.wo_no,
                        "kalem_id": kalem.id,
                        "tutar": float(kalem.unit_price),
                        "neden": "Dönem ödendi ve kilitli; kalem sonraki döneme taşınmalı.",
                    }
                )
            continue

        mevcut = {
            s.work_order_item_id
            for s in (
                await db.scalars(
                    select(SettlementLine).where(SettlementLine.settlement_id == dokum.id)
                )
            ).all()
        }
        ziyaretler: set[int] = set()
        for wo, kalem in kayitlar:
            if kalem.id not in mevcut and kalem.unit_price is not None:
                tutar = yuvarla(Decimal(str(kalem.unit_price)))
                db.add(
                    SettlementLine(
                        settlement_id=dokum.id,
                        work_order_id=wo.id,
                        work_order_item_id=kalem.id,
                        work_type=_is_tipi(wo, kalem),
                        description=f"{wo.wo_no} · {kalem.action}",
                        unit_price=tutar,
                        quantity=1,
                        amount=tutar,
                        price_source=kalem.price_source,
                    )
                )
            ziyaretler.add(wo.id)

        # Ziyaret başına TEK yol satırı (kalem başına değil).
        for wo_id in ziyaretler:
            wo = next(w for w, _ in kayitlar if w.id == wo_id)
            if not wo.travel_km or not wo.travel_unit_price:
                continue
            anahtar = f"yol:{wo.id}"
            var_mi = await db.scalar(
                select(SettlementLine).where(
                    SettlementLine.settlement_id == dokum.id,
                    SettlementLine.work_order_id == wo.id,
                    SettlementLine.work_type == "YOL_KM",
                )
            )
            if var_mi is None:
                km = Decimal(str(wo.travel_km))
                birim = Decimal(str(wo.travel_unit_price))
                db.add(
                    SettlementLine(
                        settlement_id=dokum.id,
                        work_order_id=wo.id,
                        work_type="YOL_KM",
                        description=f"{wo.wo_no} · yol {km} km",
                        unit_price=birim,
                        quantity=km,
                        amount=yuvarla(km * birim),
                        price_source="TARIFE",
                    )
                )
            del anahtar

        await db.flush()
        await dokum_tutarlarini_guncelle(db, dokum)
        sonuc.dokumler.append(dokum)

    return sonuc


def _is_tipi(wo: WorkOrder, kalem: WorkOrderItem) -> str:
    return is_tipi_coz(wo.type, kalem.device_role)


async def kilitle(db: AsyncSession, dokum: PartnerSettlement, clock: Clock) -> None:
    """Döküm ödenince satırları kilitler."""
    for satir in (
        await db.scalars(select(SettlementLine).where(SettlementLine.settlement_id == dokum.id))
    ).all():
        satir.locked_at = clock.now()
    await db.flush()


async def nokta_adi(db: AsyncSession, partner_id: int) -> str:
    hesap = await db.get(Account, partner_id)
    return hesap.title if hesap else f"#{partner_id}"


# --- Dönem paneli (canlı uygulamadaki "ay özeti") ---------------------------


# Ay kapanmadan önce gözden geçirilmesi gerekenler. Canlı uygulamanın en
# değerli ekranı buydu: bunların her biri hak edişin EKSİK ya da FAZLA
# ödenmesine yol açar ve döküm çıktıktan sonra düzeltmek pahalıdır
# (kapanmış dönem değişmez, düzeltme sonraki aya satır olarak girer).
async def donem_paneli(db: AsyncSession, donem: str) -> dict:
    """Bir hak ediş döneminin özeti, dağılımı ve kontrol listesi."""
    kayitlar = (
        await db.execute(
            select(WorkOrder, WorkOrderItem)
            .join(WorkOrderItem, WorkOrderItem.work_order_id == WorkOrder.id)
            .where(WorkOrder.is_deleted.is_(False), WorkOrder.settlement_period == donem)
        )
    ).all()

    ziyaretler = {wo.id: wo for wo, _ in kayitlar}
    kalemler = [k for _, k in kayitlar]

    odenecek = [k for k in kalemler if k.payability == "ODENECEK"]
    bekleyen = [k for k in kalemler if k.payability == "KARAR_BEKLIYOR"]
    odenmeyecek = [k for k in kalemler if k.payability == "ODENMEYECEK"]

    tutar = sum((Decimal(str(k.unit_price or 0)) for k in odenecek), Decimal(0))
    yol = sum(
        (
            Decimal(str(wo.travel_km or 0)) * Decimal(str(wo.travel_unit_price or 0))
            for wo in ziyaretler.values()
        ),
        Decimal(0),
    )

    # --- montaj noktasına göre ödenecek tutar ---
    noktalar: dict[int | None, Decimal] = {}
    for wo, k in kayitlar:
        if k.payability != "ODENECEK":
            continue
        noktalar[wo.assigned_id] = noktalar.get(wo.assigned_id, Decimal("0")) + Decimal(
            str(k.unit_price or 0)
        )
    unvanlar = {}
    if idler := [i for i in noktalar if i]:
        unvanlar = {
            h.id: h.title
            for h in (await db.scalars(select(Account).where(Account.id.in_(idler)))).all()
        }

    # --- iş tipi dağılımı ---
    tipler: dict[str, int] = {}
    for wo, k in kayitlar:
        tip = _is_tipi(wo, k)
        tipler[tip] = tipler.get(tip, 0) + 1

    # --- kontroller ---
    ayni_cihaz: dict[int, int] = {}
    for k in kalemler:
        if k.device_id:
            ayni_cihaz[k.device_id] = ayni_cihaz.get(k.device_id, 0) + 1

    kontroller = [
        (
            "Ödenecek ama tutarı girilmemiş",
            len([k for k in odenecek if not k.unit_price]),
            "Bu kalemler döküme 0 TL olarak girer.",
        ),
        (
            "Karar bekleyen kalem",
            len(bekleyen),
            "Ödenecek mi ödenmeyecek mi işaretlenmeden döküme GİRMEZ.",
        ),
        (
            "Montaj noktası boş",
            len([wo for wo in ziyaretler.values() if not wo.assigned_id]),
            "Hangi noktaya ödeneceği belli değil; bu işler hiçbir döküme düşmez.",
        ),
        (
            "Cihazı eşleşmemiş kalem",
            len([k for k in kalemler if not k.device_id]),
            "IMEI/seri no sistemde bulunamamış.",
        ),
        (
            "Cihaz rolü boş",
            len([k for k in kalemler if not k.device_role]),
            "Rol, hak ediş iş tipini ve tarifeyi belirler.",
        ),
        (
            "Aynı cihaz birden fazla kalemde",
            sum(adet for adet in ayni_cihaz.values() if adet > 1),
            "Sök-tak ziyaretinde normaldir; değilse mükerrer kayıt olabilir.",
        ),
    ]

    return {
        "donem": donem,
        "ziyaret": len(ziyaretler),
        "kalem": len(kalemler),
        "odenecek_kalem": len(odenecek),
        "odenmeyecek_kalem": len(odenmeyecek),
        "karar_bekleyen": len(bekleyen),
        "tutar": yuvarla(tutar),
        "yol_tutari": yuvarla(yol),
        "genel_toplam": yuvarla(tutar + yol),
        "aktif_nokta": len({wo.assigned_id for wo in ziyaretler.values() if wo.assigned_id}),
        "noktalar": sorted(
            (
                {
                    "partner_id": pid,
                    "unvan": unvanlar.get(pid, "(montaj noktası yok)") if pid else "(atanmamış)",
                    "tutar": yuvarla(t),
                }
                for pid, t in noktalar.items()
            ),
            key=lambda x: x["tutar"],
            reverse=True,
        ),
        "is_tipleri": sorted(
            ({"tip": t, "adet": a} for t, a in tipler.items()),
            key=lambda x: x["adet"],
            reverse=True,
        ),
        "kontroller": [
            {"ad": ad, "adet": adet, "aciklama": aciklama}
            for ad, adet, aciklama in kontroller
            if adet
        ],
    }
