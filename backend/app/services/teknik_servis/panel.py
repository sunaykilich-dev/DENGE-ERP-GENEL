"""Servis Paneli ve TEK KPI tanım kaydı (E01-14, E05-21, TS-035).

**Sayı = liste.** Her kutunun sayısı, tıklanınca açılan
`/api/teknik-servis/isler?kpi=<kod>` listesinin `X-Toplam-Kayit` başlığıyla
AYNI süzgeçten gelir: kutu kendi sorgusunu yazmaz, `KPI_TANIMLARI[kod].suzgec`
hem panelin `count`'una hem listenin sorgusuna uygulanır. Eski sistemde kutu
"12" deyip liste 9 satır gösterdiğinde hangisine güvenileceği belli değildi.

**Kapsam süzgeçte YOK, çağıranda.** Süzgeç yalnız iş kuralıdır (durum, tür,
dönem); birim/iş kapsamı `kapsam.kapsam_isler` ile panelde de listede de aynı
fonksiyondan uygulanır (sayı = sızıntı: başka birimin işi sayıya da girmez).

**Süzgeç sözleşmesi:** `suzgec(stmt, user=None, clock=None, donem=None) -> stmt`.
`stmt` `ServiceOrder` varlığını seçen herhangi bir sorgu olabilir (liste
`select(ServiceOrder)`, panel `select(ServiceOrder.id)`); süzgeç yalnız
`ServiceOrder` kolonları ve alt sorgularla `WHERE` ekler, JOIN eklemez — böylece
`sayfala()` sayımı ve listenin sıralaması bozulmaz.

**Servis kutuları PB saymaz** (E01-14): planlı bakım işleri ayrı "Bakım"
grubundadır; servis açığına girerse arıza yükü şişkin görünürdü.
"Atölyede" = kategori ATOLYE ∧ açık (plan TS-035). Dönemsel kutular Türkiye
gününe göre (`yerel_zaman`) — 22:30 UTC'de kapanan iş Türkiye'de ertesi gündür.

Mobilite `PanelPage` ve `services/reports.dashboard` DEĞİŞMEZ (K17).
Operasyon Merkezi (Dalga 2) ve raporlar (Dalga 3) bu kaydı GENİŞLETİR, yeni
sayım yazmaz.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, exists, func, not_, or_, select
from sqlalchemy.orm import aliased

from app.models import (
    MaintenancePeriod,
    ServiceHold,
    ServiceOrder,
    ServiceOrderSerial,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.permissions import BIRIMLER
from app.services.teknik_servis import kapsam
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.yerel_zaman import YEREL, yerel_bugun, yerel_gun_araligi
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

# Dönem seçimi (E01-14): bugün / bu hafta / bu ay / son 30 gün.
DONEMLER: dict[str, str] = {
    "bugun": "Bugün",
    "hafta": "Bu hafta",
    "ay": "Bu ay",
    "son30": "Son 30 gün",
}
VARSAYILAN_DONEM = "ay"

# Uyarı eşikleri (E01-18). Plan §1.9 ayar listesinde karşılığı YOK; ayarlar
# Dalga 1'de donmuş olduğu için kod sabitidir (rapor: ayar talebi).
KAPANIS_BEKLEME_UYARI_GUN = 3
BEKLEME_UYARI_GUN = 7
TEKRAR_ARIZA_GUN = 30

_ACIK = sorted(DURUM_GRUPLARI["ACIK"])
_COZULDU = sorted(DURUM_GRUPLARI["COZULDU"])


class PanelHatasi(ServisGirdiHatasi):
    """Bilinmeyen KPI kodu / dönem / birim → 400."""


Suzgec = Callable[..., Select[Any]]


@dataclass(frozen=True)
class KpiTanimi:
    """`KpiKutusu` bileşeninin beslendiği tanım: `{kod, baslik, tanim, deger, yol}`.

    `donemsel`: sayı seçilen döneme göre değişir (yol `&donem=` taşır).
    `grup`: SERVIS | DONEM | BAKIM — ekrandaki bölüm.
    """

    kod: str
    baslik: str
    tanim: str
    # (stmt, user, clock, donem) -> stmt: listeye ve sayıya aynı süzgeç uygulanır.
    suzgec: Suzgec
    izin: str = "servis.gor"
    grup: str = "SERVIS"
    donemsel: bool = False
    vurgu: str = "normal"
    # Dalga 3 rapor genişletmesi (E12-08, kontrol B1): ikinci kayıt defteri
    # açılmaz, bu tanım genişler. `olcu_birimi` adet KPI'larında "adet";
    # `kisisel` kutu `servis_rapor.personel` ister.
    olcu_birimi: str = "adet"
    kisisel: bool = False


# --- Dönem -----------------------------------------------------------------------


def donem_dogrula(donem: str | None) -> str:
    if donem is None or donem == "":
        return VARSAYILAN_DONEM
    if donem in DONEMLER:
        return donem
    if ARALIK_KALIBI.match(donem):
        aralik_gunleri(donem)  # tarih, sıra ve azami uzunluk doğrulaması
        return donem
    raise PanelHatasi(
        f"Bilinmeyen dönem: {donem}. Geçerliler: {', '.join(DONEMLER)} ya da YYYYAAGG-YYYYAAGG"
    )


# Rapor dönemi (Dalga 3, TS-181): `donem=20260101-20260131` — rapor KPI'sının
# sayısı `/isler?kpi=<kod>&donem=<aralık>` listesinin toplamıyla aynı süzgeçten
# gelsin diye serbest aralık da bir "dönem"dir. Uç: Türkiye günleri, iki uç dahil.
ARALIK_KALIBI = re.compile(r"^(\d{8})-(\d{8})$")
RAPOR_AZAMI_AY = 24


def ay_ekle(gun: date, ay: int) -> date:
    """Takvim ayı ekler; hedef ayda o gün yoksa ayın son günü (31 Oca + 1 = 28 Şub)."""
    yil, ay_no = divmod(gun.month - 1 + ay, 12)
    yeni_yil, yeni_ay = gun.year + yil, ay_no + 1
    son = (date(yeni_yil + yeni_ay // 12, yeni_ay % 12 + 1, 1) - timedelta(days=1)).day
    return date(yeni_yil, yeni_ay, min(gun.day, son))


def aralik_metni(bas: date, bit: date) -> str:
    return f"{bas:%Y%m%d}-{bit:%Y%m%d}"


def aralik_gunleri(donem: str) -> tuple[date, date]:
    """`YYYYAAGG-YYYYAAGG` → (ilk gün, son gün). Geçersiz tarih, ters sıra ya da
    `RAPOR_AZAMI_AY` aydan uzun aralık → `PanelHatasi` (400)."""
    eslesme = ARALIK_KALIBI.match(donem or "")
    if eslesme is None:
        raise PanelHatasi(f"Dönem aralığı YYYYAAGG-YYYYAAGG biçiminde olmalı: {donem}")
    try:
        bas, bit = (date(int(m[:4]), int(m[4:6]), int(m[6:])) for m in eslesme.groups())
    except ValueError:
        raise PanelHatasi(f"Geçersiz tarih: {donem}") from None
    if bit < bas:
        raise PanelHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if bit >= ay_ekle(bas, RAPOR_AZAMI_AY):
        raise PanelHatasi(f"Rapor aralığı en çok {RAPOR_AZAMI_AY} ay olabilir")
    return bas, bit


def donem_araligi(donem: str | None, clock: Clock) -> tuple[datetime, datetime]:
    """Dönemin UTC yarı açık aralığı `[bas, bit)` — Türkiye günlerine göre."""
    donem = donem_dogrula(donem)
    if ARALIK_KALIBI.match(donem):
        ilk, son = aralik_gunleri(donem)
        return yerel_gun_araligi(ilk)[0], yerel_gun_araligi(son)[1]
    bugun = yerel_bugun(clock)
    if donem == "bugun":
        ilk = bugun
    elif donem == "hafta":
        ilk = bugun - timedelta(days=bugun.weekday())  # Pazartesi
    elif donem == "ay":
        ilk = bugun.replace(day=1)
    else:  # son30: bugün dahil 30 gün
        ilk = bugun - timedelta(days=29)
    bas, _ = yerel_gun_araligi(ilk)
    _, bit = yerel_gun_araligi(bugun)
    return bas, bit


def _ay_araligi(clock: Clock) -> tuple[date, date]:
    bugun = yerel_bugun(clock)
    ilk = bugun.replace(day=1)
    sonraki = (ilk + timedelta(days=32)).replace(day=1)
    return ilk, sonraki


# --- Süzgeç parçaları ----------------------------------------------------------------


def _servis(stmt: Select) -> Select:
    """Servis kutularının tabanı: silinmemiş, PB OLMAYAN işler."""
    return stmt.where(ServiceOrder.is_deleted.is_(False), ServiceOrder.tur != "PB")


def _bakim(stmt: Select) -> Select:
    return stmt.where(ServiceOrder.is_deleted.is_(False), ServiceOrder.tur == "PB")


def _acik(stmt: Select) -> Select:
    return stmt.where(ServiceOrder.status.in_(_ACIK))


def _atanmamis_kosulu():
    """Liste süzgeciyle (`/isler?atanmamis=true`) AYNI tanım (rol testi B1)."""
    from app.services.teknik_servis.is_emirleri import tayinsiz_is_kosulu

    return tayinsiz_is_kosulu()


def _saat_gerekli(clock: Clock | None) -> Clock:
    if clock is None:
        raise PanelHatasi("Bu KPI saate bağlı; clock verilmeli")
    return clock


def _durum(*durumlar: str) -> Suzgec:
    def _s(stmt, user=None, clock=None, donem=None):
        return _servis(stmt).where(ServiceOrder.status.in_(durumlar))

    return _s


def _s_acik(stmt, user=None, clock=None, donem=None):
    return _acik(_servis(stmt))


def _s_atolyede(stmt, user=None, clock=None, donem=None):
    return _acik(_servis(stmt)).where(ServiceOrder.kategori == "ATOLYE")


def _s_atanmamis(stmt, user=None, clock=None, donem=None):
    return _acik(_servis(stmt)).where(_atanmamis_kosulu())


def _s_kritik_acik(stmt, user=None, clock=None, donem=None):
    return _acik(_servis(stmt)).where(ServiceOrder.oncelik == "KRITIK")


def _s_kritik_atanmamis(stmt, user=None, clock=None, donem=None):
    return _s_kritik_acik(stmt).where(_atanmamis_kosulu())


def _s_bugun_acilan(stmt, user=None, clock=None, donem=None):
    bas, bit = yerel_gun_araligi(yerel_bugun(_saat_gerekli(clock)))
    return _servis(stmt).where(ServiceOrder.created_at >= bas, ServiceOrder.created_at < bit)


def _bugun_plan_kosulu(gun_bas: date, gun_bit: date):
    return exists().where(
        ServicePlan.service_order_id == ServiceOrder.id,
        ServicePlan.is_active.is_(True),
        ServicePlan.is_deleted.is_(False),
        ServicePlan.plan_date >= gun_bas,
        ServicePlan.plan_date < gun_bit,
    )


def _s_bugun_planli(stmt, user=None, clock=None, donem=None):
    bugun = yerel_bugun(_saat_gerekli(clock))
    return _acik(_servis(stmt)).where(_bugun_plan_kosulu(bugun, bugun + timedelta(days=1)))


def _s_kapanis_gecikmis(stmt, user=None, clock=None, donem=None):
    sinir = _saat_gerekli(clock).now() - timedelta(days=KAPANIS_BEKLEME_UYARI_GUN)
    return _servis(stmt).where(
        ServiceOrder.status == "TAMAMLANDI", ServiceOrder.completed_at < sinir
    )


def _s_uzun_beklemede(stmt, user=None, clock=None, donem=None):
    sinir = _saat_gerekli(clock).now() - timedelta(days=BEKLEME_UYARI_GUN)
    return _servis(stmt).where(
        ServiceOrder.status == "BEKLEMEDE",
        exists().where(
            ServiceHold.service_order_id == ServiceOrder.id,
            ServiceHold.released_at.is_(None),
            ServiceHold.started_at < sinir,
        ),
    )


# Dönemsel


def _tamamlanan(stmt: Select, clock: Clock | None, donem: str | None) -> Select:
    bas, bit = donem_araligi(donem, _saat_gerekli(clock))
    return stmt.where(
        ServiceOrder.status.in_(_COZULDU),
        ServiceOrder.completed_at >= bas,
        ServiceOrder.completed_at < bit,
    )


def _s_tamamlanan(stmt, user=None, clock=None, donem=None):
    return _tamamlanan(_servis(stmt), clock, donem)


def _uzaktan_kosulu():
    return exists().where(
        ServiceResult.service_order_id == ServiceOrder.id,
        ServiceResult.gecersiz_at.is_(None),
        ServiceResult.cozum_kanali.in_(("UZAKTAN", "TELEFON")),
    )


def _s_uzaktan_cozulen(stmt, user=None, clock=None, donem=None):
    return _s_tamamlanan(stmt, user, clock, donem).where(_uzaktan_kosulu())


def _s_tekrar_ariza(stmt, user=None, clock=None, donem=None):
    """Dönemde AÇILAN ve tekrar arıza sayılan işler: TEKRAR_ARIZA bağı VAR ya
    da aynı `seri_norm` ile son 30 günde açılmış başka bir (PB olmayan) iş var."""
    bas, bit = donem_araligi(donem, _saat_gerekli(clock))
    onceki = aliased(ServiceOrder)
    bu_seri = aliased(ServiceOrderSerial)
    onceki_seri = aliased(ServiceOrderSerial)
    ayni_seri = exists().where(
        bu_seri.service_order_id == ServiceOrder.id,
        bu_seri.is_active.is_(True),
        onceki_seri.seri_norm == bu_seri.seri_norm,
        onceki_seri.is_active.is_(True),
        onceki_seri.service_order_id == onceki.id,
        onceki.id != ServiceOrder.id,
        onceki.is_deleted.is_(False),
        onceki.tur != "PB",
        onceki.created_at < ServiceOrder.created_at,
        onceki.created_at >= ServiceOrder.created_at - timedelta(days=TEKRAR_ARIZA_GUN),
    )
    return _servis(stmt).where(
        ServiceOrder.created_at >= bas,
        ServiceOrder.created_at < bit,
        or_(ServiceOrder.iliski_turu == "TEKRAR_ARIZA", ayni_seri),
    )


def _sure_kaydi_yok():
    return not_(
        exists().where(
            ServiceTimeEntry.service_order_id == ServiceOrder.id,
            ServiceTimeEntry.is_deleted.is_(False),
        )
    )


def _s_sure_eksik(stmt, user=None, clock=None, donem=None):
    """Dönemde tamamlanan ve süre kaydı EKSİK ya da KISMİ iş ("0 saat" değil "eksik").

    Rol testi tur 2 (5_teknisyen B4): tanım Zaman Takibi KPI'sı, iş detayı ve
    kapanış uyarısıyla AYNI (`zaman.sure_eksik_ifadesi` = EKSIK ∪ KISMI); eskiden
    yalnız hiç kaydı olmayanı sayıyordu ve 3 kişilik ekipte 1 kişinin süresi
    eksik kapanan iş panelde görünmüyordu."""
    from app.services.teknik_servis.zaman import sure_eksik_ifadesi

    return _s_tamamlanan(stmt, user, clock, donem).where(sure_eksik_ifadesi())


def _s_planlamaya_donen(stmt, user=None, clock=None, donem=None):
    """Teklif kararı ya da parça gelişiyle saha durumundan planlama kuyruğuna
    dönmüş, henüz yeniden planlanmamış işler (rol testi tur 2, Y1/O5)."""
    from app.services.teknik_servis.bekletme import PLANLAMAYA_DONEN_NEDENLER, SAHA_DURUMLARI

    return _servis(stmt).where(
        ServiceOrder.status == "PLANLAMADA",
        exists().where(
            ServiceHold.service_order_id == ServiceOrder.id,
            ServiceHold.released_at.is_not(None),
            ServiceHold.otomatik_kapandi.is_(False),
            ServiceHold.neden.in_(sorted(PLANLAMAYA_DONEN_NEDENLER)),
            ServiceHold.onceki_durum.in_(sorted(SAHA_DURUMLARI)),
        ),
    )


def _s_kalite_reddedilen(stmt, user=None, clock=None, donem=None):
    """Kalitesi reddedilip düzeltme için açık duruma dönmüş işler (Y5)."""
    return _acik(stmt.where(ServiceOrder.is_deleted.is_(False))).where(
        ServiceOrder.kalite_red_at.is_not(None)
    )


# Bakım (yalnız PB)


def _s_bakim_acik(stmt, user=None, clock=None, donem=None):
    return _acik(_bakim(stmt))


def _s_bakim_bu_ay_planli(stmt, user=None, clock=None, donem=None):
    ilk, sonraki = _ay_araligi(_saat_gerekli(clock))
    return _bakim(stmt).where(ServiceOrder.status != "IPTAL", _bugun_plan_kosulu(ilk, sonraki))


def _s_bakim_geciken(stmt, user=None, clock=None, donem=None):
    bugun = yerel_bugun(_saat_gerekli(clock))
    return _acik(_bakim(stmt)).where(
        exists().where(
            MaintenancePeriod.id == ServiceOrder.maintenance_period_id,
            MaintenancePeriod.target_date < bugun,
        )
    )


def _s_bakim_tamamlanan(stmt, user=None, clock=None, donem=None):
    return _tamamlanan(_bakim(stmt), clock, donem)


# --- Kayıt ---------------------------------------------------------------------------

KPI_TANIMLARI: dict[str, KpiTanimi] = {}
# Panelde kutu olarak çizilmeyen gruplar (uyarı zili ve servis raporları).
# ANA_PANEL: Ana Panel'in birleşik kutuları (`ana_panel.py`); `/isler?kpi=` liste
# süzgeci olarak çalışır, Servis Paneli'nde ikinci kez çizilmez.
PANEL_DISI_GRUPLAR = frozenset({"UYARI", "RAPOR", "ANA_PANEL"})


def kpi_kaydet(tanim: KpiTanimi) -> KpiTanimi:
    """KPI ekler (Dalga 2 Operasyon / Dalga 3 rapor genişletmesi buradan).
    Aynı kod iki farklı tanımla kaydedilemez: iki ekran aynı adı farklı sayardı."""
    if tanim.kod in KPI_TANIMLARI and KPI_TANIMLARI[tanim.kod] != tanim:
        raise ValueError(f"KPI kodu zaten kayıtlı: {tanim.kod}")
    KPI_TANIMLARI[tanim.kod] = tanim
    return tanim


for _t in (
    KpiTanimi("acik", "Açık işler", "Kapanmamış (TAMAMLANDI/KAPATILDI/İPTAL dışı) servis işleri; PB hariç.", _s_acik),  # noqa: E501
    KpiTanimi("plan_bekleyen", "Plan bekleyen", "Müşteri talebi, planlamada ya da tekrar açılmış işler.", _durum("MUSTERI_TALEBI", "PLANLAMADA", "TEKRAR_ACILDI")),  # noqa: E501
    KpiTanimi("planlandi", "Planlandı", "Planlanmış, henüz sahaya çıkılmamış işler.", _durum("PLANLANDI")),  # noqa: E501
    KpiTanimi("sahada", "Sahada", "Yola çıkıldı, sahada ya da işlemde olan işler.", _durum(*sorted(DURUM_GRUPLARI["SAHA"]))),  # noqa: E501
    KpiTanimi("atolyede", "Atölyede", "Kategorisi ATÖLYE olan açık işler.", _s_atolyede),
    KpiTanimi("beklemede", "Beklemede", "Beklemeye alınmış işler (neden kırılımı listede).", _durum("BEKLEMEDE")),  # noqa: E501
    KpiTanimi("atanmamis", "Tayin Edilmemiş", "Aktif teknisyen tayini olmayan açık işler.", _s_atanmamis, vurgu="uyari"),  # noqa: E501
    KpiTanimi("kritik_acik", "Kritik açık", "Önceliği KRİTİK olan açık işler.", _s_kritik_acik, vurgu="kritik"),  # noqa: E501
    KpiTanimi("bugun_acilan", "Bugün açılan", "Bugün (Türkiye günü) sisteme açılan işler.", _s_bugun_acilan),  # noqa: E501
    KpiTanimi("bugun_planli", "Bugün planlı", "Aktif planı bugüne olan açık işler.", _s_bugun_planli),  # noqa: E501
    KpiTanimi("kapanis_bekleyen", "Kapanış bekleyen", "TAMAMLANDI durumunda, şef kapanışı bekleyen işler.", _durum("TAMAMLANDI")),  # noqa: E501
    # Uyarı listeleri (E01-18) — panelde gösterilmez, zil buradan sayar.
    KpiTanimi("kritik_atanmamis", "Tayin edilmemiş kritik iş", "Önceliği KRİTİK olup aktif teknisyen tayini olmayan açık işler.", _s_kritik_atanmamis, grup="UYARI", vurgu="kritik"),  # noqa: E501
    KpiTanimi("kapanis_gecikmis", "Kapanışı gecikmiş iş", f"{KAPANIS_BEKLEME_UYARI_GUN} günden uzun süredir TAMAMLANDI durumunda bekleyen işler.", _s_kapanis_gecikmis, grup="UYARI", vurgu="uyari"),  # noqa: E501
    KpiTanimi("uzun_beklemede", "Uzun süredir beklemede", f"{BEKLEME_UYARI_GUN} günden uzun süredir beklemede olan işler.", _s_uzun_beklemede, grup="UYARI", vurgu="uyari"),  # noqa: E501
    KpiTanimi("planlamaya_donen", "Yeniden planlanacak iş", "Teklif kararı ya da parça gelişiyle planlama kuyruğuna dönmüş, henüz planlanmamış işler; PB hariç.", _s_planlamaya_donen, grup="UYARI", vurgu="uyari"),  # noqa: E501
    KpiTanimi("kalite_reddedilen", "Kalitesi reddedilen iş", "Kalite onayı reddedilip düzeltme için açık duruma dönmüş işler.", _s_kalite_reddedilen, grup="UYARI", vurgu="uyari"),  # noqa: E501
    # Dönemsel
    KpiTanimi("tamamlanan", "Tamamlanan", "Seçilen dönemde tamamlanan/kapatılan işler (son tamamlanma anı).", _s_tamamlanan, grup="DONEM", donemsel=True),  # noqa: E501
    KpiTanimi("uzaktan_cozulen", "Telefon/uzaktan çözülen", "Dönemde tamamlanan ve çözüm kanalı TELEFON ya da UZAKTAN olan işler.", _s_uzaktan_cozulen, grup="DONEM", donemsel=True),  # noqa: E501
    KpiTanimi("tekrar_ariza", "Tekrar arıza", f"Dönemde açılan; TEKRAR ARIZA bağı olan ya da aynı seri ile son {TEKRAR_ARIZA_GUN} günde başka iş açılmış işler.", _s_tekrar_ariza, grup="DONEM", donemsel=True, vurgu="uyari"),  # noqa: E501
    KpiTanimi("sure_eksik", "Süre kaydı eksik", "Dönemde tamamlanan ve süre kaydı eksik (hiç yok) ya da kısmi (ekipte süresi olmayan teknisyen var) işler; 0 saat sayılmaz.", _s_sure_eksik, grup="DONEM", donemsel=True, vurgu="uyari"),  # noqa: E501
    # Bakım (yalnız PB)
    KpiTanimi("bakim_acik", "Açık bakım", "Açık planlı bakım (PB) işleri.", _s_bakim_acik, grup="BAKIM"),  # noqa: E501
    KpiTanimi("bakim_bu_ay_planli", "Bu ay planlı bakım", "Aktif planı bu aya düşen PB işleri.", _s_bakim_bu_ay_planli, grup="BAKIM"),  # noqa: E501
    KpiTanimi("bakim_geciken", "Geciken bakım", "Bakım döneminin hedef tarihi geçmiş açık PB işleri.", _s_bakim_geciken, grup="BAKIM", vurgu="uyari"),  # noqa: E501
    KpiTanimi("bakim_tamamlanan", "Tamamlanan bakım", "Seçilen dönemde tamamlanan PB işleri.", _s_bakim_tamamlanan, grup="BAKIM", donemsel=True),  # noqa: E501
):  # fmt: skip
    kpi_kaydet(_t)


def kpi_suzgeci(kod: str) -> KpiTanimi:
    """`/isler?kpi=` için tanım; bilinmeyen kod → `PanelHatasi` (ValueError, 400)."""
    try:
        return KPI_TANIMLARI[kod]
    except KeyError:
        raise PanelHatasi(f"Bilinmeyen KPI kodu: {kod}") from None


def kpi_uygula(
    stmt: Select,
    kod: str,
    *,
    user: User | None = None,
    clock: Clock | None = None,
    donem: str | None = None,
) -> Select:
    """Liste ucunun TEK çağrısı: `stmt = panel.kpi_uygula(stmt, kpi, clock=..., donem=...)`.

    Kapsam UYGULAMAZ (liste kendi `kapsam_isler`'ini zaten uygular)."""
    tanim = kpi_suzgeci(kod)
    return tanim.suzgec(stmt, user, clock, donem_dogrula(donem) if tanim.donemsel else donem)


def kpi_yolu(tanim: KpiTanimi, donem: str | None = None, birim: str | None = None) -> str:
    yol = f"/servis-isleri?kpi={tanim.kod}"
    if tanim.donemsel:
        yol += f"&donem={donem_dogrula(donem)}"
    if birim:
        yol += f"&birim={birim}"
    return yol


# --- Sayım -----------------------------------------------------------------------------


def birim_dogrula(user: User, birim: str | None) -> str | None:
    """Panel birim süzgeci: katalog dışı → 400; kullanıcının birimi değilse →
    `PermissionError` (403). TUMU kapsamı her birimi seçebilir."""
    if birim is None or birim == "":
        return None
    if birim not in BIRIMLER:
        raise PanelHatasi(f"Bilinmeyen birim: {birim}")
    # TUMU her birimi seçer — etkin şirketin birimleri içinde (KARARLAR 2026-11-04 §1).
    if kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise PermissionError(f"Bu birimin panelini görme yetkiniz yok: {birim}")
    return birim


def kapsamli_sorgu(
    tanim: KpiTanimi,
    user: User,
    clock: Clock,
    *,
    donem: str | None = None,
    birim: str | None = None,
) -> Select:
    """KPI sorgusu (iş kimlikleri) — kapsam + isteğe bağlı birim süzgeciyle."""
    stmt = tanim.suzgec(select(ServiceOrder.id), user, clock, donem)
    if birim:
        stmt = stmt.where(ServiceOrder.birim == birim)
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id)


async def kpi_sayisi(
    db: AsyncSession,
    kod: str,
    user: User,
    clock: Clock,
    *,
    donem: str | None = None,
    birim: str | None = None,
) -> int:
    stmt = kapsamli_sorgu(kpi_suzgeci(kod), user, clock, donem=donem, birim=birim)
    return int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


async def _ortalama_cozum(
    db: AsyncSession, user: User, clock: Clock, donem: str, birim: str | None
) -> dict[str, Any]:
    """Ortalama çözüm süresi (saat): `reported_at` (yoksa `created_at`, "tahmini"
    sayılır) → `completed_at`. Tamamlanan iş yoksa `None` ("0" değil)."""
    kimlikler = kapsamli_sorgu(KPI_TANIMLARI["tamamlanan"], user, clock, donem=donem, birim=birim)
    baslangic = func.coalesce(ServiceOrder.reported_at, ServiceOrder.created_at)
    sure = func.extract("epoch", ServiceOrder.completed_at - baslangic) / 3600.0
    satir = (
        await db.execute(
            select(
                func.avg(sure),
                func.count(),
                func.count().filter(ServiceOrder.reported_at.is_(None)),
            ).where(ServiceOrder.id.in_(kimlikler))
        )
    ).one()
    ortalama, adet, tahmini = satir
    return {
        "ortalama_cozum_saat": round(float(ortalama), 1) if adet and ortalama is not None else None,
        "cozum_olculen": int(adet or 0),
        "cozum_tahmini": int(tahmini or 0),
    }


async def panel_ozeti(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    donem: str | None = None,
    birim: str | None = None,
) -> dict[str, Any]:
    """Panel kutuları + dönem ölçüleri. Her kutu: `{kod, baslik, tanim, deger,
    yol, grup, donemsel, vurgu}`; `deger` = aynı süzgecin kapsamlı sayısı."""
    donem = donem_dogrula(donem)
    birim = birim_dogrula(user, birim)
    kutular: list[dict[str, Any]] = []
    sayilar: dict[str, int] = {}
    for tanim in KPI_TANIMLARI.values():
        # RAPOR grubu (Dalga 3) servis raporlarının dönemli KPI'larıdır; panelde
        # aynı dönem ile ikinci bir kutu dizisi çizilmez.
        if tanim.grup in PANEL_DISI_GRUPLAR or not user.has(tanim.izin):
            continue
        deger = await kpi_sayisi(db, tanim.kod, user, clock, donem=donem, birim=birim)
        sayilar[tanim.kod] = deger
        kutular.append(
            {
                "kod": tanim.kod,
                "baslik": tanim.baslik,
                "tanim": tanim.tanim,
                "deger": deger,
                "yol": kpi_yolu(tanim, donem, birim),
                "grup": tanim.grup,
                "donemsel": tanim.donemsel,
                "vurgu": tanim.vurgu,
            }
        )
    tamamlanan = sayilar.get("tamamlanan", 0)
    olcumler: dict[str, Any] = {
        # Oran: payı ve paydası iki kutunun sayısıdır (ikisi de tıklanabilir).
        "uzaktan_oran_yuzde": (
            round(100.0 * sayilar.get("uzaktan_cozulen", 0) / tamamlanan, 1) if tamamlanan else None
        ),
        **await _ortalama_cozum(db, user, clock, donem, birim),
    }
    bas, bit = donem_araligi(donem, clock)
    return {
        "donem": donem,
        "donem_adi": DONEMLER[donem],
        "donem_baslangic": bas.astimezone(YEREL).date(),
        "donem_bitis": (bit.astimezone(YEREL) - timedelta(days=1)).date(),
        "birim": birim,
        "kutular": kutular,
        "olcumler": olcumler,
    }


def tanimlar() -> list[dict[str, Any]]:
    """KPI sözlüğü (ⓘ ipuçları ve liste başlığı için)."""
    return [
        {
            "kod": t.kod,
            "baslik": t.baslik,
            "tanim": t.tanim,
            "grup": t.grup,
            "donemsel": t.donemsel,
        }
        for t in KPI_TANIMLARI.values()
    ]


# --- Uyarılar (E01-18) ------------------------------------------------------------------
#
# Zil uyarısı = bir KPI listesinin sayısı; yol aynı listeye gider. Birim/iş
# kapsamı `kpi_sayisi` içinde uygulanır (A biriminin şefi B'nin işini saymaz).

_UYARI_KPI = (
    ("kritik_atanmamis", "kritik", "Kritik öncelikli işe teknisyen tayin edilmemiş."),
    (
        "kapanis_gecikmis",
        "uyari",
        f"Tamamlanan iş {KAPANIS_BEKLEME_UYARI_GUN} günden uzun süredir şef kapanışı bekliyor.",
    ),
    ("uzun_beklemede", "uyari", f"İş {BEKLEME_UYARI_GUN} günden uzun süredir beklemede."),
    (
        "planlamaya_donen",
        "uyari",
        "Teklif kabul/red ya da parça gelişiyle iş planlama kuyruğuna döndü; yeniden planlayın.",
    ),
    (
        "kalite_reddedilen",
        "uyari",
        "Kalite onayı reddedilen iş düzeltme bekliyor; gerekçe iş geçmişinde.",
    ),
)


async def servis_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    sonuc: list[Uyari] = []
    for kod, onem, aciklama in _UYARI_KPI:
        tanim = KPI_TANIMLARI[kod]
        sonuc.append(
            Uyari(
                kod=f"servis.{kod}",
                baslik=tanim.baslik,
                adet=await kpi_sayisi(db, kod, user, clock),
                yol=kpi_yolu(tanim),
                onem=onem,
                aciklama=aciklama,
            )
        )
    return sonuc


ts_uyarilar.kaydet("servis", "servis.gor", servis_uyarilari)


# --- Genel arama (E01-18 (4)) ----------------------------------------------------------


async def servis_ara(db: AsyncSession, user: User, terim: str, limit: int) -> list[dict[str, Any]]:
    """Genel arama için servis işi sonuçları: iş no (`so_no`) ya da seri
    (`seri_norm`, tek normalizasyon fonksiyonu). KAPSAMLI — kullanıcının
    göremeyeceği iş sonuç listesine de girmez (E01-18 (4)). Silinmiş iş yok.

    Arayıcı kaydı API katmanındadır (`api/search.arayici_kaydet`); bu fonksiyon
    `AramaSonucu` alanlarını sözlük olarak döner.
    """
    from app.services.normalize import normalize_seri
    from app.services.teknik_servis import is_emirleri

    terim = (terim or "").strip()
    if len(terim) < 2:
        return []
    seri = normalize_seri(terim)
    kosullar = [ServiceOrder.so_no.ilike(f"%{terim}%")]
    if seri:
        kosullar.append(
            exists().where(
                ServiceOrderSerial.service_order_id == ServiceOrder.id,
                ServiceOrderSerial.is_active.is_(True),
                ServiceOrderSerial.seri_norm.contains(seri),
            )
        )
    stmt = select(ServiceOrder).where(ServiceOrder.is_deleted.is_(False), or_(*kosullar))
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    stmt = stmt.order_by(ServiceOrder.created_at.desc(), ServiceOrder.id.desc()).limit(limit)
    sonuc = []
    for so in (await db.scalars(stmt)).all():
        seriler = [s.seri_no for s in so.seriler if s.is_active]
        sonuc.append(
            {
                "tur": "SERVIS_ISI",
                "id": so.id,
                "baslik": so.so_no,
                "alt_baslik": so.konu,
                "etiketler": [
                    is_emirleri.DURUM_ADLARI.get(so.status, so.status),
                    BIRIMLER.get(so.birim, so.birim),
                    *seriler[:2],
                ],
                "yol": f"/servis-isleri/{so.id}",
            }
        )
    return sonuc


__all__ = [
    "DONEMLER",
    "KPI_TANIMLARI",
    "KpiTanimi",
    "PanelHatasi",
    "donem_araligi",
    "kpi_sayisi",
    "kpi_suzgeci",
    "kpi_uygula",
    "panel_ozeti",
]
