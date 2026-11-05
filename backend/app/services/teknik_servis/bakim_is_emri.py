"""Planlı bakım iş emirleri: bekleyen liste ve yönetici seçimiyle toplu açma.

Kullanıcı isteği (2026-11-05): "yıllık bakımlar iş emri olarak gözüksün ama
yönetici seçip iş emirlerini aç dediğinde topluca açabilsin."

Kararlar (gerekçeli, `analiz/soru_formu/KARARLAR_2026-10-28.md` §8.7–8.10):

- **Bekleyen iş emri = açık dönem × PB'si açılmamış cihaz.** Takvimdeki her
  dönem satırı, o dönemde açılacak cihaz iş emirlerinin sayısıyla listelenir.
  Henüz açılmamış iş için `service_orders` satırı YAZILMAZ: taslak PB satırı
  numara serisini, iş emri listelerini, KPI'ları ve "1 cihaz = 1 PB" tekilliğini
  bozardı. Liste her istekte dönem + kalem + mevcut PB'den hesaplanır.
- **Açma tek motordan:** seçilen dönemler `bakim_uretim.uret_ayrintili`
  (`donem_idleri`) ile açılır; cihaz başına 1 PB, idempotent (ikinci açma 0),
  ekipmansız kalem "adet farkı" olarak raporlanır. Vade penceresi aranmaz:
  yönetici gelecek ayın işlerini de açabilir.
- **Yetki:** liste `bakim.gor`, açma `bakim.yaz` (servis yöneticisi ve birim
  şefi — mevcut "PB üret" ile aynı izin; ayrı onay adımı yok, G1.9). Kapsam
  `bakim.donem_kapsami`: başka birimin / kapsam dışı müşterinin dönemi listede
  görünmez ve açılmak istenirse "bulunamadı" sayılır.
- **Önizleme aynı kod:** dış SAVEPOINT'te koşup geri alınır.
- **Otomatik görev değişmez:** `bakim_otomatik_uretim` varsayılan kapalı
  kalır; asıl yol yöneticinin toplu açmasıdır.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import (
    Account,
    Address,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceEquipment,
    ServiceOrder,
)
from app.services import settings as ayar_svc
from app.services.teknik_servis import bakim, bakim_sablonlari, bakim_uretim
from app.services.teknik_servis.bakim_karar import GECIKMIS, ILERIDE, ILK_TURDA
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

AZAMI_SECIM = 500
AZAMI_LISTE = 2000
VARSAYILAN_UFUK_AY = 12

# Satır durumu: açılmamış dönem takvim durumunu (GECIKMIS/ILK_TURDA/ILERIDE)
# taşır; tüm cihazların işi açıksa ACILDI, bir kısmı açıksa KISMEN.
ACILDI = "ACILDI"
KISMEN = "KISMEN"


async def planli_isler(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    bit: date | None = None,
    birim: str | None = None,
    yalniz_acilmamis: bool = True,
) -> dict[str, Any]:
    """Aktif sözleşmelerin açık dönemleri (hedef < `bit`; gecikmişler dahil).

    Varsayılan ufuk bugünden 12 ay. Her satır: dönem, müşteri/tesis, hedef,
    planlanan cihaz iş emri, açılmış ve açılacak sayısı, tür özeti.
    """
    bugun = yerel_bugun(clock)
    bit = bit or bakim.ay_ekle(bugun, VARSAYILAN_UFUK_AY)
    on_acilis = int(await ayar_svc.get(db, "bakim_on_acilis_gun") or 0)
    stmt = (
        select(MaintenancePeriod, MaintenanceContract)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .where(
            MaintenancePeriod.is_deleted.is_(False),
            MaintenancePeriod.closed_at.is_(None),
            MaintenanceContract.is_deleted.is_(False),
            MaintenanceContract.status == "AKTIF",
            MaintenancePeriod.target_date < bit,
        )
    )
    if birim:
        stmt = stmt.where(MaintenanceContract.birim == birim)
    stmt = bakim.donem_kapsami(stmt, user).order_by(
        MaintenancePeriod.target_date, MaintenanceContract.contract_no
    )
    kayitlar = (await db.execute(stmt.limit(AZAMI_LISTE))).all()
    sozlesmeler = {s.id: s for _, s in kayitlar}
    donem_idleri = [d.id for d, _ in kayitlar]

    kalemler: dict[int, list[MaintenanceContractItem]] = {}
    for k in (
        await db.scalars(
            select(MaintenanceContractItem)
            .where(
                MaintenanceContractItem.contract_id.in_(list(sozlesmeler)),
                MaintenanceContractItem.is_deleted.is_(False),
                MaintenanceContractItem.valid_to.is_(None),
                MaintenanceContractItem.pb_uygun.is_(True),
            )
            .order_by(MaintenanceContractItem.equipment_type, MaintenanceContractItem.sira)
        )
    ).all():
        kalemler.setdefault(k.contract_id, []).append(k)
    silinmis_ekipman = set(
        (
            await db.scalars(
                select(ServiceEquipment.id).where(
                    ServiceEquipment.id.in_(
                        [k.equipment_id for ks in kalemler.values() for k in ks if k.equipment_id]
                    ),
                    ServiceEquipment.is_deleted.is_(True),
                )
            )
        ).all()
    )
    pbli: dict[int, set[int]] = {}
    if donem_idleri:
        for kalem_id, donem_id in (
            await db.execute(
                select(ServiceOrder.contract_item_id, ServiceOrder.maintenance_period_id).where(
                    ServiceOrder.tur == "PB",
                    ServiceOrder.is_deleted.is_(False),
                    ServiceOrder.maintenance_period_id.in_(donem_idleri),
                )
            )
        ).all():
            pbli.setdefault(donem_id, set()).add(kalem_id)
    hesaplar = {
        a.id: a.title
        for a in (
            await db.scalars(
                select(Account).where(
                    Account.id.in_([s.account_id for s in sozlesmeler.values() if s.account_id])
                )
            )
        ).all()
    }
    tesisler = {
        a.id: a
        for a in (
            await db.scalars(
                select(Address).where(
                    Address.id.in_([s.address_id for s in sozlesmeler.values() if s.address_id])
                )
            )
        ).all()
    }

    simdi = clock.now()
    satirlar: list[dict[str, Any]] = []
    for d, s in kayitlar:
        acilmis = pbli.get(d.id, set())
        planli = acilacak = eslesmemis = 0
        turler: Counter[str] = Counter()
        for k in kalemler.get(s.id, []):
            if not bakim_uretim._kalem_gecerli_mi(k, d, simdi):
                continue
            if bakim_sablonlari.sablon(k.equipment_type) is None:
                continue
            if k.id in acilmis:
                planli += 1
                turler[k.equipment_type] += 1
                continue
            if not k.equipment_id or k.equipment_id in silinmis_ekipman:
                eslesmemis += 1
                continue
            planli += 1
            acilacak += 1
            turler[k.equipment_type] += 1
        acilan = len(acilmis)
        if acilacak == 0 and acilan:
            durum = ACILDI
        elif acilan:
            durum = KISMEN
        elif d.target_date < bugun:
            durum = GECIKMIS
        elif d.target_date - timedelta(days=on_acilis) <= bugun:
            durum = ILK_TURDA
        else:
            durum = ILERIDE
        if yalniz_acilmamis and acilacak == 0 and eslesmemis == 0:
            continue
        tesis = tesisler.get(s.address_id) if s.address_id else None
        satirlar.append(
            {
                "donem_id": d.id,
                "sozlesme_id": s.id,
                "contract_no": s.contract_no,
                "birim": s.birim,
                "musteri": hesaplar.get(s.account_id) or s.customer_name_raw,
                "tesis": (tesis.site_name or tesis.label) if tesis else s.site_name_raw,
                "il": tesis.city if tesis else None,
                "hedef": d.target_date.isoformat(),
                "sira": d.sequence_no,
                "yillik_adet": s.annual_frequency,
                "durum": durum,
                "planli": planli,
                "acilan": acilan,
                "acilacak": acilacak,
                "eslesmemis": eslesmemis,
                "turler": [
                    {
                        "tur": t,
                        "ad": bakim_sablonlari.CIHAZ_TURU_ADLARI.get(t, t),
                        "adet": n,
                    }
                    for t, n in sorted(turler.items())
                ],
            }
        )
    return {
        "bit": bit.isoformat(),
        "on_acilis_gun": on_acilis,
        "kesildi": len(kayitlar) >= AZAMI_LISTE,
        "toplam_acilacak": sum(r["acilacak"] for r in satirlar),
        "satirlar": satirlar,
    }


async def toplu_ac(
    db: AsyncSession,
    user: User,
    clock: Clock,
    donem_idleri: list[int],
    *,
    onizleme: bool,
) -> dict[str, Any]:
    """Seçilen dönemlerin cihaz iş emirlerini (PB) açar. Önizlemede geri alınır."""
    istenen = list(dict.fromkeys(donem_idleri))
    stmt = (
        select(MaintenancePeriod.id)
        .join(MaintenanceContract, MaintenanceContract.id == MaintenancePeriod.contract_id)
        .where(
            MaintenancePeriod.id.in_(istenen),
            MaintenancePeriod.is_deleted.is_(False),
            MaintenanceContract.is_deleted.is_(False),
        )
    )
    bulunan = set((await db.scalars(bakim.donem_kapsami(stmt, user))).all())
    nokta = await db.begin_nested() if onizleme else None
    try:
        sonuc = await bakim_uretim.uret_ayrintili(db, clock, user, "TOPLU_AC", donem_idleri=bulunan)
        sayim: Counter[int] = Counter(u["donem_id"] for u in sonuc.uretilen)
        satirlar = [
            {
                "donem_id": i,
                "sonuc": "BULUNAMADI" if i not in bulunan else "TAMAM",
                "acilan": sayim.get(i, 0),
            }
            for i in istenen
        ]
        cikti = {
            "onizleme": onizleme,
            "run_id": None if onizleme else sonuc.run.id,
            "acilan": len(sonuc.uretilen),
            "is_emirleri": [] if onizleme else [u["so_no"] for u in sonuc.uretilen],
            "satirlar": satirlar,
            "atlanan": sonuc.atlanan,
        }
    finally:
        if nokta is not None:
            await nokta.rollback()
    return cikti
