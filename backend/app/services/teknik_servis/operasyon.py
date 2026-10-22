"""Operasyon Merkezi sayaçları, SLA sıralı liste ve personel iş yükü (E10-08/09/10, TS-082).

Doldurdu: D2-G.

**Ayrı veri katmanı YOK** (E10 kontrol E10-08): sayaçlar Servis Paneli'nin
TEK KPI kaydına (`panel.KPI_TANIMLARI`) eklenir ve sayım/liste aynı süzgeçten
gelir — `/operasyon/ozet` kutusu = `/operasyon/isler?kpi=` = `/isler?kpi=`
`X-Toplam-Kayit`. Servis Paneli de yeni SLA kutularını kendiliğinden gösterir
(K15: iki ekran aynı sayıyı verir).

Yeni KPI'lar:
- `sla_riskte`, `sla_asildi`, `sla_durduruldu` (grup SLA): açık, PB dışı,
  CANLI/GECIS damgalı işler; durum `sla.sla_ifadeleri`'nden (tek SLA modülü).
  Risk eşiği `servis_sla_risk_yuzde` ayarıdır ve sorgunun içinde okunur.
- `mudahale_asildi` (SLA): müdahale hedefi tanımlı, geçmiş, ilk müdahale yok.
- `bekleme_bitis_gecti` (UYARI): aktif iş beklemesinin beklenen bitişi geçmiş.
- `vadesi_gecen_bakim` (BAKIM): açık PB işi, vade = dönem hedefi +
  `bakim_tolerans_gun` (K14; `bakim.gecikme_kosulu` ile aynı tanım, tolerans
  sorgu içinde okunur). Panelin eski `bakim_geciken` kutusu toleranssızdır
  (D1 dosyası, bu dalgada donmuş — rapor: talep).

**Personel iş yükü:** açık sayaç, bugün/yarın planlı iş, açık atanmış iş
operasyonel bilgidir (`operasyon.gor`). "Bugün çalışılan dk" KİŞİSEL VERİDİR
(E10 kontrol B10) ve yalnız `servis_rapor.personel` iznine anahtar olarak
döner; izin yoksa anahtar YOKTUR. Kayıt yoksa `None` ("eksik"), 0 yazılmaz.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, exists, func, select

from app.models import (
    MaintenancePeriod,
    ServiceHold,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServicePlanMember,
    ServiceTimeEntry,
    User,
    UserUnit,
)
from app.models.teknik_servis import DURUM_GRUPLARI, KISI_SAATE_DAHIL, ONCELIKLER
from app.permissions import ATANABILIR_SAHA_ROLLERI, BIRIMLER
from app.services.teknik_servis import is_emirleri, kapsam, panel, sla
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun_araligi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

_ACIK = sorted(DURUM_GRUPLARI["ACIK"])


class OperasyonGirdiHatasi(ServisGirdiHatasi):
    """Bilinmeyen sayaç / öncelik / birim → 400."""


# --- KPI süzgeçleri (panel sözleşmesi: suzgec(stmt, user, clock, donem) -> stmt) ---------


def _saat(clock):
    if clock is None:
        raise panel.PanelHatasi("SLA sayaçları saate bağlı; clock verilmeli")
    return clock


def _acik_servis(stmt: Select) -> Select:
    return stmt.where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.tur != "PB",
        ServiceOrder.status.in_(_ACIK),
    )


def _bildirim_kaynagi():
    """GERIYE_DONUK (göç geri doldurması) işler bildirim/rozet üretmez (TS-083)."""
    return ServiceOrder.sla_kaynak.is_distinct_from("GERIYE_DONUK")


def _sla_durum_suzgeci(durum: str):
    def _s(stmt, user=None, clock=None, donem=None):
        ifade = sla.sla_ifadeleri(_saat(clock).now(), sla.ayar_tam_ifadesi("servis_sla_risk_yuzde"))
        return _acik_servis(stmt).where(
            ServiceOrder.cozum_hedef_at.is_not(None),
            _bildirim_kaynagi(),
            ifade["durum"] == durum,
        )

    return _s


def _s_mudahale_asildi(stmt, user=None, clock=None, donem=None):
    simdi = _saat(clock).now()
    return _acik_servis(stmt).where(
        _bildirim_kaynagi(),
        ServiceOrder.sla_sonuc.is_(None),
        ServiceOrder.mudahale_hedef_at.is_not(None),
        ServiceOrder.mudahale_hedef_at <= simdi,
        ServiceOrder.ilk_mudahale_at.is_(None),
    )


def _s_bekleme_bitis_gecti(stmt, user=None, clock=None, donem=None):
    simdi = _saat(clock).now()
    return stmt.where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.status == "BEKLEMEDE",
        exists().where(
            ServiceHold.service_order_id == ServiceOrder.id,
            ServiceHold.released_at.is_(None),
            ServiceHold.beklenen_bitis_at.is_not(None),
            ServiceHold.beklenen_bitis_at < simdi,
        ),
    )


def vade_gecti_kosulu(bugun):
    """Açık PB işinin dönemi `hedef + tolerans < bugün` (bakim.gecikme_kosulu tanımı)."""
    tolerans = sla.ayar_tam_ifadesi("bakim_tolerans_gun")
    return exists().where(
        MaintenancePeriod.id == ServiceOrder.maintenance_period_id,
        MaintenancePeriod.closed_at.is_(None),
        MaintenancePeriod.is_deleted.is_(False),
        MaintenancePeriod.target_date + tolerans < bugun,
    )


def _s_vadesi_gecen_bakim(stmt, user=None, clock=None, donem=None):
    bugun = yerel_bugun(_saat(clock))
    return stmt.where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.tur == "PB",
        ServiceOrder.status.in_(_ACIK),
        vade_gecti_kosulu(bugun),
    )


YENI_KPI: tuple[panel.KpiTanimi, ...] = (
    panel.KpiTanimi("sla_riskte", "SLA riskte", "Çözüm hedef süresinin risk eşiği (varsayılan %80) dolmuş, henüz aşılmamış açık işler; PB hariç.", _sla_durum_suzgeci("RISKTE"), grup="SLA", vurgu="uyari"),  # noqa: E501
    panel.KpiTanimi("sla_asildi", "SLA aşıldı", "Çözüm hedefi geçmiş açık işler (Geciken); PB hariç, SLA'yı durduran bekleme dışında.", _sla_durum_suzgeci("ASILDI"), grup="SLA", vurgu="kritik"),  # noqa: E501
    panel.KpiTanimi("sla_durduruldu", "SLA durduruldu", "SLA'yı durduran bir iş beklemesindeki (müşteri onayı, teklif, saha erişimi) açık işler.", _sla_durum_suzgeci("DURDURULDU"), grup="SLA"),  # noqa: E501
    panel.KpiTanimi("mudahale_asildi", "Müdahale gecikti", "Müdahale hedefi tanımlı ve geçmiş, henüz ilk müdahale yapılmamış açık işler.", _s_mudahale_asildi, grup="SLA", vurgu="uyari"),  # noqa: E501
    panel.KpiTanimi("bekleme_bitis_gecti", "Beklenen bitişi geçmiş bekleme", "Aktif iş beklemesinin beklenen bitiş zamanı geçmiş işler.", _s_bekleme_bitis_gecti, grup="UYARI", vurgu="uyari"),  # noqa: E501
    panel.KpiTanimi("vadesi_gecen_bakim", "Vadesi geçen bakım", "Dönem hedef tarihi + tolerans günü geçmiş açık planlı bakım (PB) işleri.", _s_vadesi_gecen_bakim, grup="BAKIM", vurgu="uyari"),  # noqa: E501
)  # fmt: skip
for _t in YENI_KPI:
    panel.kpi_kaydet(_t)

# Operasyon Merkezi'nin sayaç sırası (E10-08). `plan_bekleyen` = plansız.
OPERASYON_SAYACLARI = (
    "acik",
    "atanmamis",
    "plan_bekleyen",
    "sla_riskte",
    "sla_asildi",
    "sla_durduruldu",
    "mudahale_asildi",
    "sahada",
    "beklemede",
    "bekleme_bitis_gecti",
    "vadesi_gecen_bakim",
    "bugun_acilan",
    "bugun_planli",
)


def oncelik_dogrula(oncelik: str | None) -> str | None:
    if oncelik is None or oncelik == "":
        return None
    deger = oncelik.strip().upper()
    if deger not in ONCELIKLER:
        raise OperasyonGirdiHatasi(f"Bilinmeyen öncelik: {oncelik}")
    return deger


def sayac_dogrula(kod: str | None) -> str:
    kod = kod or "acik"
    if kod not in OPERASYON_SAYACLARI:
        raise OperasyonGirdiHatasi(
            f"Bilinmeyen sayaç: {kod}. Geçerliler: {', '.join(OPERASYON_SAYACLARI)}"
        )
    return kod


def _yol(kod: str, birim: str | None, oncelik: str | None) -> str:
    yol = f"/operasyon?kpi={kod}"
    if birim:
        yol += f"&birim={birim}"
    if oncelik:
        yol += f"&oncelik={oncelik}"
    return yol


def sayac_sorgusu(
    kod: str,
    user: User,
    clock: Clock,
    *,
    birim: str | None = None,
    oncelik: str | None = None,
) -> Select:
    """Sayaç süzgeci + kapsam + birim/öncelik — sayı ve liste BU sorgudan."""
    stmt = panel.kapsamli_sorgu(panel.kpi_suzgeci(kod), user, clock, birim=birim)
    if oncelik:
        stmt = stmt.where(ServiceOrder.oncelik == oncelik)
    return stmt


async def sayaclar(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    birim: str | None = None,
    oncelik: str | None = None,
) -> list[dict[str, Any]]:
    """KPI_TANIMLARI kaydından sayaçlar; sayı = `/operasyon/isler?kpi=` liste sayısı (kapsamlı).

    Birim kullanıcının birimi değilse `PermissionError` (403, panel kuralı)."""
    birim = panel.birim_dogrula(user, birim)
    oncelik = oncelik_dogrula(oncelik)
    sonuc = []
    for kod in OPERASYON_SAYACLARI:
        tanim = panel.kpi_suzgeci(kod)
        stmt = sayac_sorgusu(kod, user, clock, birim=birim, oncelik=oncelik)
        deger = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        sonuc.append(
            {
                "kod": kod,
                "baslik": tanim.baslik,
                "tanim": tanim.tanim,
                "deger": deger,
                "yol": _yol(kod, birim, oncelik),
                "grup": tanim.grup,
                "vurgu": tanim.vurgu,
            }
        )
    return sonuc


def liste_sorgusu(
    user: User,
    clock: Clock,
    risk_yuzde: int,
    *,
    kpi: str,
    birim: str | None = None,
    oncelik: str | None = None,
    teknisyen_id: int | None = None,
) -> Select:
    """SLA sıralı iş listesi: önce işleyen SLA'sı en yakın, sonra durdurulmuş, sonra
    ölçülmeyen (E10-08 (2)). Süzgeç sayaçla aynıdır (`sayac_sorgusu`)."""
    kimlikler = sayac_sorgusu(kpi, user, clock, birim=birim, oncelik=oncelik)
    stmt = select(ServiceOrder).where(ServiceOrder.id.in_(kimlikler))
    if teknisyen_id is not None:
        stmt = stmt.where(
            exists().where(
                ServiceOrderAssignment.service_order_id == ServiceOrder.id,
                ServiceOrderAssignment.user_id == teknisyen_id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    ifade = sla.sla_ifadeleri(clock.now(), risk_yuzde)
    return stmt.order_by(*ifade["siralama"])


async def liste_satirlari(
    db: AsyncSession, sos: list[ServiceOrder], clock: Clock
) -> list[dict[str, Any]]:
    """Operasyon listesi satırları (müşteri unvanı, sorumlu, SLA bloğu). Fiyat YOK."""
    musteriler = await is_emirleri.musteri_ozetleri(
        db, {s.customer_id for s in sos if s.customer_id}
    )
    sla_bloklari = await sla.sla_bloklari(db, sos, clock)
    idler = [s.id for s in sos]
    sorumlular: dict[int, dict[str, Any]] = {}
    ekip_sayisi: dict[int, int] = dict.fromkeys(idler, 0)
    if idler:
        for so_id, kisi_id, ad, lead in (
            await db.execute(
                select(
                    ServiceOrderAssignment.service_order_id,
                    ServiceOrderAssignment.user_id,
                    User.full_name,
                    ServiceOrderAssignment.is_lead,
                )
                .join(User, User.id == ServiceOrderAssignment.user_id)
                .where(
                    ServiceOrderAssignment.service_order_id.in_(idler),
                    ServiceOrderAssignment.removed_at.is_(None),
                )
            )
        ).all():
            ekip_sayisi[so_id] += 1
            if lead:
                sorumlular[so_id] = {"id": kisi_id, "ad": ad}
    beklemeler = await is_emirleri.aktif_bekleme_nedenleri(db, idler)
    return [
        {
            "id": s.id,
            "so_no": s.so_no,
            "birim": s.birim,
            "tur": s.tur,
            "kategori": s.kategori,
            "status": s.status,
            "oncelik": s.oncelik,
            "konu": s.konu,
            "musteri": musteriler.get(s.customer_id) if s.customer_id else None,
            "customer_name_raw": s.customer_name_raw,
            "sorumlu": sorumlular.get(s.id),
            "ekip_sayisi": ekip_sayisi.get(s.id, 0),
            "aktif_bekleme": beklemeler.get(s.id),
            "created_at": s.created_at,
            "tekrar_ariza_aday": s.tekrar_ariza_aday,
            "sla": sla_bloklari[s.id],
            "version": s.version,
        }
        for s in sos
    ]


# --- Personel iş yükü (E10-09) ----------------------------------------------------------


async def is_yuku(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    birim: str | None = None,
) -> list[dict[str, Any]]:
    """Kimlik bazlı canlı sayaç durumu, bugün/yarın planlı yük, açık atanmış iş.

    Kişi listesi: aktif, sahaya atanabilir (`saha_rolu` SEF/TEKNISYEN/STAJYER)
    ve kullanıcının personel kapsamındaki kişiler (aynı ad iki kişiyse iki
    satır — kimlik bazlı). Açık sayacın işi okuyucunun kapsamı dışındaysa iş
    numarası maskelenir.
    """
    birim = panel.birim_dogrula(user, birim)
    stmt = select(User).where(User.is_active.is_(True), User.saha_rolu.in_(ATANABILIR_SAHA_ROLLERI))
    stmt = kapsam.kapsam_personel(stmt, user, User.id)
    if birim:
        stmt = stmt.where(exists().where(UserUnit.user_id == User.id, UserUnit.birim == birim))
    kisiler = list((await db.scalars(stmt.order_by(User.full_name, User.id))).all())
    if not kisiler:
        return []
    kimlikler = [k.id for k in kisiler]
    bugun = yerel_bugun(clock)
    yarin = bugun + timedelta(days=1)

    sayaclar_: dict[int, tuple[ServiceTimeEntry, ServiceOrder]] = {}
    for bolum, so in (
        await db.execute(
            select(ServiceTimeEntry, ServiceOrder)
            .join(ServiceOrder, ServiceOrder.id == ServiceTimeEntry.service_order_id)
            .where(
                ServiceTimeEntry.user_id.in_(kimlikler),
                ServiceTimeEntry.ended_at.is_(None),
                ServiceTimeEntry.is_deleted.is_(False),
            )
        )
    ).all():
        sayaclar_[bolum.user_id] = (bolum, so)
    gorunen_isler: set[int] = set()
    if sayaclar_:
        is_idler = [so.id for _, so in sayaclar_.values()]
        gorunen_isler = set(
            (
                await db.scalars(
                    kapsam.kapsam_isler(
                        select(ServiceOrder.id).where(ServiceOrder.id.in_(is_idler)),
                        user,
                        ServiceOrder.id,
                    )
                )
            ).all()
        )

    planlar: dict[tuple[int, Any], int] = {}
    for kisi_id, gun, adet in (
        await db.execute(
            select(
                ServicePlanMember.user_id,
                ServicePlan.plan_date,
                func.count(func.distinct(ServicePlan.service_order_id)),
            )
            .join(ServicePlan, ServicePlan.id == ServicePlanMember.plan_id)
            .join(ServiceOrder, ServiceOrder.id == ServicePlan.service_order_id)
            .where(
                ServicePlanMember.user_id.in_(kimlikler),
                ServicePlan.is_active.is_(True),
                ServicePlan.is_deleted.is_(False),
                ServicePlan.plan_date.in_([bugun, yarin]),
                ServiceOrder.is_deleted.is_(False),
                ServiceOrder.status != "IPTAL",
            )
            .group_by(ServicePlanMember.user_id, ServicePlan.plan_date)
        )
    ).all():
        planlar[(kisi_id, gun)] = int(adet)

    atanmis = dict(
        (
            await db.execute(
                select(ServiceOrderAssignment.user_id, func.count())
                .join(ServiceOrder, ServiceOrder.id == ServiceOrderAssignment.service_order_id)
                .where(
                    ServiceOrderAssignment.user_id.in_(kimlikler),
                    ServiceOrderAssignment.removed_at.is_(None),
                    ServiceOrder.is_deleted.is_(False),
                    ServiceOrder.status.in_(_ACIK),
                )
                .group_by(ServiceOrderAssignment.user_id)
            )
        ).all()
    )

    kisi_saat_gorur = user.has("servis_rapor.personel")
    calisilan: dict[int, int] = {}
    if kisi_saat_gorur:
        bas, bit = yerel_gun_araligi(bugun)
        sure = func.sum(
            func.extract("epoch", ServiceTimeEntry.ended_at - ServiceTimeEntry.started_at)
        )
        for kisi_id, saniye in (
            await db.execute(
                select(ServiceTimeEntry.user_id, sure)
                .where(
                    ServiceTimeEntry.user_id.in_(kimlikler),
                    ServiceTimeEntry.is_deleted.is_(False),
                    ServiceTimeEntry.ended_at.is_not(None),
                    ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
                    and_(ServiceTimeEntry.started_at >= bas, ServiceTimeEntry.started_at < bit),
                )
                .group_by(ServiceTimeEntry.user_id)
            )
        ).all():
            calisilan[kisi_id] = round(float(saniye or 0) / 60)

    satirlar = []
    for k in kisiler:
        acik = sayaclar_.get(k.id)
        acik_sayac = None
        if acik is not None:
            bolum, so = acik
            gizli = so.id not in gorunen_isler
            acik_sayac = {
                "service_order_id": None if gizli else so.id,
                "so_no": "Kapsam dışı iş" if gizli else so.so_no,
                "faaliyet": bolum.faaliyet,
                "started_at": bolum.started_at,
            }
        satir: dict[str, Any] = {
            "user_id": k.id,
            "ad": k.full_name,
            "saha_rolu": k.saha_rolu,
            "birimler": sorted(u.birim for u in k.birimler),
            "acik_sayac": acik_sayac,
            "bugun_planli": planlar.get((k.id, bugun), 0),
            "yarin_planli": planlar.get((k.id, yarin), 0),
            "acik_atanmis": int(atanmis.get(k.id, 0)),
        }
        if kisi_saat_gorur:
            # Kayıt yoksa None ("eksik"); 0 yazılmaz (korunacak iş kararı).
            satir["bugun_calisilan_dk"] = calisilan.get(k.id)
        satirlar.append(satir)
    return satirlar


def birimler_sozlugu() -> list[dict[str, str]]:
    return [{"kod": k, "ad": v} for k, v in BIRIMLER.items()]
