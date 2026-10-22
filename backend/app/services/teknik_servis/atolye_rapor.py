"""Atölye listesi, özet/KPI ve Excel satırları — TEK süzgeç kaynağı (E05-08/09/18, TS-092/098).

**Sayı = liste (plan §4.5):** liste ucu, KPI kutuları (`ozet`) ve Excel AYNI
`filtreli_sorgu`'yu kullanır; kutudaki sayı, tıklanınca açılan listenin
`X-Toplam-Kayit` başlığıyla aynıdır. Kapsam SQL'de uygulanır
(`kapsam.kapsam_isler` — atölye kaydı servis işinin bağlısıdır, plan §1.2):
kapsam dışı birimin kaydı ne listede ne sayıda ne Excel'de görünür.

**Yaşlandırma** kabul anından (sunucu Clock'u) Türkiye günüyle hesaplanır;
yaş kovaları ve "tahmini bitişi geçen" yalnız AÇIK kayıtlara uygulanır.

**Tamir bedeli (TS-092):** `repair_amount` satıra yalnız `maliyet_gorur`
true iken ANAHTAR olarak girer (None değil, anahtar yok). Excel sütunu da
aynı kuralla eklenir; kural çağıranın hatırlamasına bırakılmaz.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, exists, func, or_, select

from app.models import (
    Account,
    ServiceEquipment,
    ServiceFaultReason,
    ServiceOrder,
    ServiceOrderAssignment,
    User,
    WorkshopRecord,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.servis_atolye import (
    ATOLYE_ACIK_OLMAYAN,
    ATOLYE_DURUMLARI,
    ATOLYE_SERVIS_TURLERI,
)
from app.services.normalize import normalize_seri, tr_normkey
from app.services.teknik_servis import kapsam
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun, yerel_gun_araligi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

ACIK_DURUMLAR = tuple(d for d in ATOLYE_DURUMLARI if d not in ATOLYE_ACIK_OLMAYAN)

# Yaş kovası → (en az gün, en çok gün; None = üst sınır yok). Kabul günü 0. gündür.
YAS_KOVALARI: dict[str, tuple[int, int | None]] = {
    "0-3": (0, 3),
    "4-7": (4, 7),
    "8-14": (8, 14),
    "15+": (15, None),
}
DURUM_GRUPLARI = ("ACIK", "KAPALI")

DURUM_ADLARI: dict[str, str] = {
    "KABUL_EDILDI": "Kabul edildi",
    "TESHISTE": "Teşhiste",
    "ONAY_BEKLIYOR": "Onay bekliyor",
    "ONARIMDA": "Onarımda",
    "PARCA_BEKLIYOR": "Parça bekliyor",
    "DIS_SERVISTE": "Dış serviste",
    "TEST_KONTROL": "Test / kontrol",
    "TESLIME_HAZIR": "Teslime hazır",
    "ONARILMADAN_IADE": "Onarılmadan iade",
    "KARGOYA_VERILDI": "Kargoya verildi",
    "TESLIM_EDILDI": "Teslim edildi",
    "IPTAL": "İptal",
}
SERVIS_TURU_ADLARI: dict[str, str] = {
    "ARIZA_ONARIMI": "Arıza onarımı",
    "GARANTI_ONARIMI": "Garanti onarımı",
    "DIS_SERVIS": "Dış servis",
    "YAZILIM_FREKANS": "Yazılım / frekans",
    "KIRALAMA_TAKIP": "Kiralama takip",
}
GARANTI_ADLARI: dict[str, str] = {
    "GARANTI_ICI": "Garanti içi",
    "GARANTI_DISI": "Garanti dışı",
    "ONARIM_GARANTISI": "Onarım garantisi",
    "BELIRSIZ": "Belirsiz",
}

# Liste/Excel/özet süzgecinin kabul ettiği anahtarlar (tek tanım).
FILTRE_ANAHTARLARI = (
    "durum",
    "durum_grubu",
    "birim",
    "teknisyen_id",
    "marka",
    "servis_turu",
    "q",
    "yas",
    "geciken",
    "kabul_grubu",
    "musteri_id",
)


def _bos(deger: Any) -> Any:
    if isinstance(deger, str):
        return deger.strip() or None
    return deger


def filtre_dogrula(filtre: dict[str, Any]) -> dict[str, Any]:
    """Süzgeç sözlüğünü doğrular ve temizler (bilinmeyen değer → 400)."""
    f = {k: _bos(filtre.get(k)) for k in FILTRE_ANAHTARLARI}
    durumlar = [d for d in (f.get("durum") or []) if d]
    bilinmeyen = [d for d in durumlar if d not in ATOLYE_DURUMLARI]
    if bilinmeyen:
        raise ServisGirdiHatasi(f"Bilinmeyen atölye durumu: {', '.join(bilinmeyen)}")
    f["durum"] = durumlar
    if f["durum_grubu"] is not None and f["durum_grubu"] not in DURUM_GRUPLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen durum grubu: {f['durum_grubu']}")
    if f["birim"] is not None and f["birim"] not in BIRIM_KODLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {f['birim']}")
    if f["servis_turu"] is not None and f["servis_turu"] not in ATOLYE_SERVIS_TURLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen servis türü: {f['servis_turu']}")
    if f["yas"] is not None and f["yas"] not in YAS_KOVALARI:
        raise ServisGirdiHatasi(f"Bilinmeyen yaş kovası: {f['yas']}")
    f["geciken"] = bool(f.get("geciken"))
    return f


def _gun_baslangici(gun: date):
    return yerel_gun_araligi(gun)[0]


def filtreli_sorgu(user: User, filtre: dict[str, Any], clock: Clock) -> Select:
    """Liste, özet ve Excel AYNI sorguyu kullanır (sayı = liste).

    Dönen sorgu `WorkshopRecord` seçer (sayfalama kırılması birincil anahtara
    eklenir); servis işi ve ekipman süzgeç için JOIN'lidir. Kapsam her
    zaman uygulanır.
    """
    f = filtre_dogrula(filtre)
    stmt = (
        select(WorkshopRecord)
        .join(ServiceOrder, ServiceOrder.id == WorkshopRecord.service_order_id)
        .join(ServiceEquipment, ServiceEquipment.id == WorkshopRecord.equipment_id)
        .where(WorkshopRecord.is_deleted.is_(False), ServiceOrder.is_deleted.is_(False))
    )
    stmt = kapsam.kapsam_isler(stmt, user, WorkshopRecord.service_order_id)
    acik = WorkshopRecord.status.in_(ACIK_DURUMLAR)
    if f["durum"]:
        stmt = stmt.where(WorkshopRecord.status.in_(f["durum"]))
    if f["durum_grubu"] == "ACIK":
        stmt = stmt.where(acik)
    elif f["durum_grubu"] == "KAPALI":
        stmt = stmt.where(WorkshopRecord.status.in_(ATOLYE_ACIK_OLMAYAN))
    if f["birim"]:
        stmt = stmt.where(ServiceOrder.birim == f["birim"])
    if f["musteri_id"] is not None:
        stmt = stmt.where(ServiceOrder.customer_id == int(f["musteri_id"]))
    if f["servis_turu"]:
        stmt = stmt.where(WorkshopRecord.service_type == f["servis_turu"])
    if f["kabul_grubu"] is not None:
        stmt = stmt.where(WorkshopRecord.intake_group_no == int(f["kabul_grubu"]))
    if f["teknisyen_id"] is not None:
        stmt = stmt.where(
            exists().where(
                ServiceOrderAssignment.service_order_id == WorkshopRecord.service_order_id,
                ServiceOrderAssignment.user_id == int(f["teknisyen_id"]),
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    if f["marka"]:
        # Marka serbest metindir; karşılaştırma Türkçe katlamalı ve harf duyarsız (E05-20).
        stmt = stmt.where(ServiceEquipment.brand_key == tr_normkey(f["marka"]))
    if f["q"]:
        desen = f"%{f['q']}%"
        seri = normalize_seri(f["q"])
        anahtar = tr_normkey(f["q"])
        kosullar = [
            WorkshopRecord.atolye_no.ilike(desen),
            ServiceOrder.so_no.ilike(desen),
            exists().where(
                Account.id == ServiceOrder.customer_id,
                or_(Account.title.ilike(desen), Account.title_key.contains(anahtar))
                if anahtar
                else Account.title.ilike(desen),
            ),
        ]
        if seri:
            kosullar.append(ServiceEquipment.serial_key.like(f"%{seri}%"))
        stmt = stmt.where(or_(*kosullar))
    bugun = yerel_bugun(clock)
    if f["yas"]:
        alt, ust = YAS_KOVALARI[f["yas"]]
        # yaş = bugün − kabul günü; kabul günü ≤ bugün − alt  ve  > bugün − ust − 1
        kosul = [
            acik,
            WorkshopRecord.received_at < yerel_gun_araligi(bugun - timedelta(days=alt))[1],
        ]
        if ust is not None:
            kosul.append(WorkshopRecord.received_at >= _gun_baslangici(bugun - timedelta(days=ust)))
        stmt = stmt.where(and_(*kosul))
    if f["geciken"]:
        stmt = stmt.where(acik, WorkshopRecord.estimated_finish_date < bugun)
    return stmt.order_by(WorkshopRecord.received_at.desc())


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


def kpi_tanimlari() -> list[dict[str, Any]]:
    """KPI kutuları: kod, başlık, tanım ve kutunun açtığı liste süzgeci."""
    kutular: list[dict[str, Any]] = [
        {
            "kod": "ACIK",
            "baslik": "Atölyede",
            "tanim": "Teslim edilmemiş ve iptal edilmemiş bütün atölye kayıtları",
            "sorgu": {"durum_grubu": "ACIK"},
        }
    ]
    for d in ACIK_DURUMLAR:
        kutular.append(
            {
                "kod": d,
                "baslik": DURUM_ADLARI[d],
                "tanim": f"Atölye durumu '{DURUM_ADLARI[d]}' olan kayıtlar",
                "sorgu": {"durum": [d]},
            }
        )
    for kova, (alt, ust) in YAS_KOVALARI.items():
        aralik = f"{alt}+ gün" if ust is None else f"{alt}-{ust} gün"
        kutular.append(
            {
                "kod": f"YAS_{kova}",
                "baslik": f"Bekleyen {aralik}",
                "tanim": f"Kabulünden bu yana {aralik} geçmiş AÇIK kayıtlar (Türkiye günü)",
                "sorgu": {"yas": kova},
            }
        )
    kutular.append(
        {
            "kod": "GECIKEN",
            "baslik": "Tahmini bitişi geçen",
            "tanim": "Tahmini bitiş tarihi bugünden önce olan AÇIK kayıtlar",
            "sorgu": {"geciken": True},
        }
    )
    return kutular


_KPI_EZEN = ("durum", "durum_grubu", "yas", "geciken")


async def ozet(
    db: AsyncSession, user: User, filtre: dict[str, Any], clock: Clock
) -> list[dict[str, Any]]:
    """KPI kutuları: her kutu = taban süzgeç + kutunun süzgeci ile `filtreli_sorgu` sayısı."""
    taban = {k: v for k, v in filtre.items() if k not in _KPI_EZEN}
    sonuc = []
    for kutu in kpi_tanimlari():
        stmt = filtreli_sorgu(user, {**taban, **kutu["sorgu"]}, clock)
        sonuc.append({**kutu, "deger": await say(db, stmt)})
    return sonuc


# --- Satır üretimi (liste ve Excel ortak) -------------------------------------------


def bekleme_gunu(kayit: WorkshopRecord, clock: Clock) -> int:
    """Kabul gününden bugüne (açık kayıt) ya da teslim/iptal gününe gün sayısı."""
    bitis = yerel_bugun(clock)
    if kayit.status in ATOLYE_ACIK_OLMAYAN:
        son = kayit.delivered_at or kayit.updated_at
        if son is not None:
            bitis = yerel_gun(son)
    return max(0, (bitis - yerel_gun(kayit.received_at)).days)


async def satirlar(
    db: AsyncSession,
    kayitlar: list[WorkshopRecord],
    clock: Clock,
    *,
    maliyet_gorur: bool,
) -> list[dict[str, Any]]:
    """Liste satırları (toplu sorgularla). `repair_amount` yalnız `maliyet_gorur`."""
    if not kayitlar:
        return []
    so_idler = [k.service_order_id for k in kayitlar]
    isler = {
        s.id: s
        for s in (await db.scalars(select(ServiceOrder).where(ServiceOrder.id.in_(so_idler)))).all()
    }
    ekipmanlar = {
        e.id: e
        for e in (
            await db.scalars(
                select(ServiceEquipment).where(
                    ServiceEquipment.id.in_({k.equipment_id for k in kayitlar})
                )
            )
        ).all()
    }
    hesap_idler = {s.customer_id for s in isler.values() if s.customer_id}
    hesaplar = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(Account.id.in_(hesap_idler or {0}))
            )
        ).all()
    )
    atamalar: dict[int, list[ServiceOrderAssignment]] = {i: [] for i in so_idler}
    for a in (
        await db.scalars(
            select(ServiceOrderAssignment)
            .where(
                ServiceOrderAssignment.service_order_id.in_(so_idler),
                ServiceOrderAssignment.removed_at.is_(None),
            )
            .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
        )
    ).all():
        atamalar[a.service_order_id].append(a)
    kisi_idler = {a.user_id for e in atamalar.values() for a in e}
    adlar = dict(
        (
            await db.execute(select(User.id, User.full_name).where(User.id.in_(kisi_idler or {0})))
        ).all()
    )
    neden_idler = {k.fault_reason_id for k in kayitlar if k.fault_reason_id}
    nedenler = dict(
        (
            await db.execute(
                select(ServiceFaultReason.id, ServiceFaultReason.ad).where(
                    ServiceFaultReason.id.in_(neden_idler or {0})
                )
            )
        ).all()
    )
    bugun = yerel_bugun(clock)
    sonuc = []
    for k in kayitlar:
        so = isler[k.service_order_id]
        e = ekipmanlar.get(k.equipment_id)
        ekip = atamalar.get(so.id, [])
        sorumlu = next((a for a in ekip if a.is_lead), ekip[0] if ekip else None)
        acik = k.status not in ATOLYE_ACIK_OLMAYAN
        satir: dict[str, Any] = {
            "id": so.id,
            "so_id": so.id,
            "kayit_id": k.id,
            "atolye_no": k.atolye_no,
            "so_no": so.so_no,
            "birim": so.birim,
            "servis_durumu": so.status,
            "musteri": (
                {"id": so.customer_id, "title": hesaplar.get(so.customer_id)}
                if so.customer_id
                else None
            ),
            "service_type": k.service_type,
            "status": k.status,
            "acik": acik,
            "ekipman": (
                {
                    "id": e.id,
                    "tip": e.equipment_type,
                    "marka": e.brand,
                    "model": e.model,
                    "seri": e.serial_no,
                }
                if e
                else None
            ),
            "sorumlu": (
                {"id": sorumlu.user_id, "ad": adlar.get(sorumlu.user_id)} if sorumlu else None
            ),
            "ekip": [{"id": a.user_id, "ad": adlar.get(a.user_id)} for a in ekip],
            "received_at": k.received_at,
            "estimated_finish_date": k.estimated_finish_date,
            "bekleme_gunu": bekleme_gunu(k, clock),
            "geciken": bool(
                acik and k.estimated_finish_date is not None and k.estimated_finish_date < bugun
            ),
            "warranty_status": k.warranty_status,
            "intake_group_no": k.intake_group_no,
            "ariza_nedeni": nedenler.get(k.fault_reason_id) if k.fault_reason_id else None,
            "repair_category": k.repair_category,
            "test_result": k.test_result,
            "completed_at": k.completed_at,
            "delivered_at": k.delivered_at,
            "version": k.version,
        }
        if maliyet_gorur:
            satir["repair_amount"] = k.repair_amount
        sonuc.append(satir)
    return sonuc


def excel_sutunlari(maliyet_gorur: bool) -> list[Any]:
    from app.services.export import Sutun

    sutunlar = [
        Sutun("Atölye No"),
        Sutun("Servis İşi No"),
        Sutun("Birim"),
        Sutun("Müşteri"),
        Sutun("Servis Türü"),
        Sutun("Durum"),
        Sutun("Ekipman Tipi"),
        Sutun("Marka"),
        Sutun("Model"),
        Sutun("Seri No"),
        Sutun("Sorumlu"),
        Sutun("Kabul", "zaman"),
        Sutun("Tahmini Bitiş", "tarih"),
        Sutun("Bekleme (gün)", "tamsayi"),
        Sutun("Gecikmiş"),
        Sutun("Garanti"),
        Sutun("Arıza Nedeni"),
        Sutun("Onarım Kategorisi"),
        Sutun("Test"),
        Sutun("Tamamlanma", "zaman"),
        Sutun("Teslim", "zaman"),
        Sutun("Kabul Grubu"),
    ]
    if maliyet_gorur:
        sutunlar.append(Sutun("Tamir Bedeli", "ondalik"))
    return sutunlar


def excel_satiri(s: dict[str, Any], *, maliyet_gorur: bool) -> list[Any]:
    from app.permissions import BIRIMLER

    e = s["ekipman"] or {}
    satir = [
        s["atolye_no"],
        s["so_no"],
        BIRIMLER.get(s["birim"], s["birim"]),
        (s["musteri"] or {}).get("title"),
        SERVIS_TURU_ADLARI.get(s["service_type"], s["service_type"]),
        DURUM_ADLARI.get(s["status"], s["status"]),
        e.get("tip"),
        e.get("marka"),
        e.get("model"),
        e.get("seri"),
        (s["sorumlu"] or {}).get("ad"),
        s["received_at"],
        s["estimated_finish_date"],
        s["bekleme_gunu"],
        "Evet" if s["geciken"] else "Hayır",
        GARANTI_ADLARI.get(s["warranty_status"], s["warranty_status"]),
        s["ariza_nedeni"],
        s["repair_category"],
        s["test_result"],
        s["completed_at"],
        s["delivered_at"],
        s["intake_group_no"],
    ]
    if maliyet_gorur:
        satir.append(s.get("repair_amount"))
    return satir
