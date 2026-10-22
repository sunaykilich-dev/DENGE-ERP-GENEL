"""Servis rapor ve KPI tanımları — tek kayıt defteri (E12-08, E12-10).

Maddeler: TS-181 (+ TS-185/TS-198 kayıtları). Doldurur: D3-A.

**İkinci kayıt defteri yok** (kontrol B1): rapor KPI'ları E01-14'ün
`panel.KPI_TANIMLARI` kaydına `grup="RAPOR"` ile eklenir. Böylece her rapor
sayısı tıklanınca açılan `/api/teknik-servis/isler?kpi=<kod>&donem=<aralık>`
listesinin `X-Toplam-Kayit` başlığıyla AYNI süzgeçten gelir; rapor ucu
`/raporlar/kpi-liste` de aynı tanımı çağırır. Kapsam (`kapsam_isler`) süzgeçte
değil çağıranda uygulanır (panel sözleşmesi).

**Dönem** rapor KPI'sında serbest aralıktır: `donem=YYYYAAGG-YYYYAAGG`
(`panel.aralik_gunleri`; Türkiye günleri, iki uç dahil, en çok 24 ay).

**Tanımlar** (eski sistem §2.3 K01…K15 ile E09/E10 düzeltmeleri):
- Gelen = dönemde AÇILAN iş (`created_at`), kategori ayrımı kırılımda.
- Çözülen = ÇÖZÜLDÜ grubunda (TAMAMLANDI+KAPATILDI) ve SON çözüm anı dönemde.
- Dönem sonu açık = dönem bitişinde açık olan iş; olay geçmişinden kurulur
  (`service_order_events` DURUM/OLUSTUR), olayı olmayan göç işinde güncel
  durum + kapanış damgası yedektir (`gecmis_degisebilir`).
- Süre eksik = E09 `zaman.sure_eksik_ifadesi()` (EKSIK ∪ KISMI); TELEFON/
  UZAKTAN çözülen iş "beklenmiyor"dur (kontrol B7). Tahmini süre gerçek süre
  yerine KULLANILMAZ.
- Tekrar arıza ONAYLI = sonraki işte kök neden teyidi `AYNI_ARIZA` (kontrol
  B6); bağ/aday işareti ayrı "onaysız aday" satırıdır. Pencere E10 ayarı
  `servis_tekrar_ariza_gun` (rapor isteğinde 7–180 ile ezilebilir).
- Tekrar ziyaret = çözülen günlük servis işinde SAHA faaliyetli ≥2 farklı
  Türkiye günü (TS-187).
- SLA yalnız GUNLUK_SERVIS; ölçülemedi ve damgasız paydada YOK, ayrı satır.

Diğer paketler (D3-E bakım/eğitim) kendi KPI'larını `rapor_kpi_kaydet` ile
ekler; Excel sütun şemaları `SUTUN_SEMALARI`'ndadır (kişisel kolon işaretli).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, and_, cast, distinct, exists, func, not_, or_, select
from sqlalchemy.orm import aliased

from app.models import (
    ServiceOrder,
    ServiceOrderEvent,
    ServiceResult,
    ServiceTimeEntry,
)
from app.models.teknik_servis import DURUM_GRUPLARI, KISI_SAATE_DAHIL
from app.services.teknik_servis import panel
from app.services.teknik_servis.yerel_zaman import SAAT_DILIMI

_ACIK = sorted(DURUM_GRUPLARI["ACIK"])
_COZULDU = sorted(DURUM_GRUPLARI["COZULDU"])

# Tekrar arıza oranının paydası: saha + atölye (E12 K3; PB/PROJE hariç).
TEKRAR_ARIZA_KATEGORILERI = ("GUNLUK_SERVIS", "ATOLYE")
SLA_KATEGORISI = "GUNLUK_SERVIS"
UZAKTAN_KANALLAR = ("TELEFON", "UZAKTAN")
TEKRAR_GUN_ALT, TEKRAR_GUN_UST = 7, 180

# Rapor ayarları (plan §1.9'da karşılığı yok; ayarlar Dalga 3'te donmuş →
# kod sabiti, talep raporda). Ayar gelirse yalnız buradan okunur.
RAPOR_AZAMI_AY = panel.RAPOR_AZAMI_AY
EXCEL_AZAMI_SATIR = 50_000
JSON_AZAMI_SATIR = 200  # hiçbir JSON uç bundan fazla ham satır dönmez (E12-10)

TARIH_ESASLARI: dict[str, str] = {
    "ACILIS": "Açılış tarihi",
    "COZUM": "Çözüm (tamamlanma) tarihi",
    "KAPANIS": "Kapanış tarihi",
    "PLAN": "Plan tarihi",
}

# Kırılım boyutları (TS-184). `teknisyen` kişiseldir (`servis_rapor.personel`).
BOYUTLAR: dict[str, str] = {
    "birim": "Birim",
    "kategori": "Kategori",
    "tur": "İş türü",
    "oncelik": "Öncelik",
    "durum_grubu": "Durum grubu",
    "sef": "Şef",
    "teknisyen": "Teknisyen",
    "musteri": "Müşteri",
    "sehir": "Şehir",
    "lokasyon": "Lokasyon / tesis",
    "cozum_kanali": "Çözüm kanalı",
}
KISISEL_BOYUTLAR = frozenset({"teknisyen"})


# --- Süzgeç yardımcıları -----------------------------------------------------------


def _aralik(clock, donem):
    if donem is not None and panel.ARALIK_KALIBI.match(donem):
        return panel.donem_araligi(donem, clock)
    return panel.donem_araligi(donem, panel._saat_gerekli(clock))


def _taban(stmt):
    return stmt.where(ServiceOrder.is_deleted.is_(False))


def _arada(sutun, bas, bit):
    return and_(sutun >= bas, sutun < bit)


def _son_durum(an):
    """İşin `an` öncesindeki son durumu (olay geçmişinden; yoksa NULL)."""
    return (
        select(ServiceOrderEvent.yeni_durum)
        .where(
            ServiceOrderEvent.service_order_id == ServiceOrder.id,
            ServiceOrderEvent.olay_turu.in_(("OLUSTUR", "DURUM")),
            ServiceOrderEvent.yeni_durum.is_not(None),
            ServiceOrderEvent.olusma_zamani < an,
        )
        .order_by(ServiceOrderEvent.olusma_zamani.desc(), ServiceOrderEvent.id.desc())
        .limit(1)
        .correlate(ServiceOrder)
        .scalar_subquery()
    )


def acik_kosulu(an):
    """`an` anında AÇIK olan iş (E12-18 dönem sonu açık).

    Olay geçmişi varsa son durum belirler (yeniden açılış da doğru sayılır);
    olayı olmayan (göç) işte güncel durum + ilk kapanış damgası yedektir.
    """
    son = _son_durum(an)
    kapanis = func.coalesce(
        ServiceOrder.cancelled_at, ServiceOrder.completed_at, ServiceOrder.closed_at
    )
    yedek = or_(ServiceOrder.status.in_(_ACIK), kapanis >= an)
    return and_(
        ServiceOrder.created_at < an,
        or_(and_(son.is_not(None), son.in_(_ACIK)), and_(son.is_(None), yedek)),
    )


def uzaktan_kosulu():
    return exists().where(
        ServiceResult.service_order_id == ServiceOrder.id,
        ServiceResult.gecersiz_at.is_(None),
        ServiceResult.cozum_kanali.in_(UZAKTAN_KANALLAR),
    )


def _cozulen(stmt, clock, donem):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(
        ServiceOrder.status.in_(_COZULDU), _arada(ServiceOrder.completed_at, bas, bit)
    )


def yerel_gun_ifadesi(sutun):
    """timestamptz → Türkiye takvim günü (SQL; K13)."""
    return func.date(func.timezone(SAAT_DILIMI, sutun))


def saha_gun_sayisi():
    """İşin SAHA faaliyetli farklı Türkiye günü sayısı (geçerli bölümler)."""
    return (
        select(func.count(distinct(yerel_gun_ifadesi(ServiceTimeEntry.started_at))))
        .where(
            ServiceTimeEntry.service_order_id == ServiceOrder.id,
            ServiceTimeEntry.is_deleted.is_(False),
            ServiceTimeEntry.faaliyet == "SAHA",
        )
        .correlate(ServiceOrder)
        .scalar_subquery()
    )


def tekrar_gun_ifadesi(gun: int | None):
    """Pencere: istekte verilmişse sabit, yoksa E10 ayarı (SQL içinde okunur ki
    sayı ile `/isler?kpi=` listesi aynı anda aynı ayarı görsün)."""
    if gun is not None:
        return gun
    from app.services.teknik_servis import sla

    return sla.ayar_tam_ifadesi("servis_tekrar_ariza_gun")


def _sonraki_tekrar_isi(*, onayli: bool, gun: int | None):
    """Bu işten SONRA, pencere içinde açılıp bu işe bağlanan tekrar arıza işi."""
    yeni = aliased(ServiceOrder)
    pencere = tekrar_gun_ifadesi(gun)
    kosullar = [
        yeni.iliskili_is_id == ServiceOrder.id,
        yeni.id != ServiceOrder.id,
        yeni.is_deleted.is_(False),
        or_(yeni.iliski_turu == "TEKRAR_ARIZA", yeni.tekrar_ariza_aday.is_(True)),
        yeni.created_at >= ServiceOrder.completed_at,
        yeni.created_at
        < ServiceOrder.completed_at + func.make_interval(0, 0, 0, cast(pencere, Integer)),
    ]
    if onayli:
        kosullar.append(yeni.tekrar_ariza_teyit == "AYNI_ARIZA")
    else:
        kosullar.append(yeni.tekrar_ariza_teyit.is_(None))
    return exists().where(*kosullar)


# --- Süzgeçler (panel sözleşmesi: suzgec(stmt, user, clock, donem) -> stmt) -------


def _s_gelen(stmt, user=None, clock=None, donem=None):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(_arada(ServiceOrder.created_at, bas, bit))


def _s_cozulen(stmt, user=None, clock=None, donem=None):
    return _cozulen(stmt, clock, donem)


def _s_ilk_cozulen(stmt, user=None, clock=None, donem=None):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(
        ServiceOrder.tur != "PB", _arada(ServiceOrder.first_completed_at, bas, bit)
    )


def _s_iptal(stmt, user=None, clock=None, donem=None):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(
        ServiceOrder.status == "IPTAL", _arada(ServiceOrder.cancelled_at, bas, bit)
    )


def _s_donem_sonu_acik(stmt, user=None, clock=None, donem=None):
    _, bit = _aralik(clock, donem)
    return _taban(stmt).where(acik_kosulu(bit))


def _s_kritik_acik(stmt, user=None, clock=None, donem=None):
    return _s_donem_sonu_acik(stmt, user, clock, donem).where(ServiceOrder.oncelik == "KRITIK")


def _s_uzaktan_cozulen(stmt, user=None, clock=None, donem=None):
    return _cozulen(stmt, clock, donem).where(uzaktan_kosulu())


def _s_sure_eksik(stmt, user=None, clock=None, donem=None):
    from app.services.teknik_servis import zaman

    return _cozulen(stmt, clock, donem).where(zaman.sure_eksik_ifadesi())


def _s_sure_girilen(stmt, user=None, clock=None, donem=None):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(
        exists().where(
            ServiceTimeEntry.service_order_id == ServiceOrder.id,
            ServiceTimeEntry.is_deleted.is_(False),
            ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
            _arada(ServiceTimeEntry.started_at, bas, bit),
        )
    )


def _yeniden_acilis_olayi(bas, bit):
    return exists().where(
        ServiceOrderEvent.service_order_id == ServiceOrder.id,
        ServiceOrderEvent.olay_turu == "DURUM",
        ServiceOrderEvent.yeni_durum == "TEKRAR_ACILDI",
        _arada(ServiceOrderEvent.olusma_zamani, bas, bit),
    )


def _s_yeniden_acilan(stmt, user=None, clock=None, donem=None):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(ServiceOrder.tur != "PB", _yeniden_acilis_olayi(bas, bit))


def _s_yeniden_acilan_pb(stmt, user=None, clock=None, donem=None):
    bas, bit = _aralik(clock, donem)
    return _taban(stmt).where(ServiceOrder.tur == "PB", _yeniden_acilis_olayi(bas, bit))


def tekrar_paydasi(stmt, clock, donem):
    """Tekrar arıza/ziyaret oranının paydası: dönemde çözülen saha + atölye işi."""
    return _cozulen(stmt, clock, donem).where(ServiceOrder.kategori.in_(TEKRAR_ARIZA_KATEGORILERI))


def tekrar_ariza_suzgeci(*, onayli: bool, gun: int | None = None):
    def _s(stmt, user=None, clock=None, donem=None):
        return tekrar_paydasi(stmt, clock, donem).where(_sonraki_tekrar_isi(onayli=onayli, gun=gun))

    return _s


def _s_tekrar_payda(stmt, user=None, clock=None, donem=None):
    return tekrar_paydasi(stmt, clock, donem)


def _s_tekrar_ziyaret(stmt, user=None, clock=None, donem=None):
    return _cozulen(stmt, clock, donem).where(
        ServiceOrder.kategori == SLA_KATEGORISI, saha_gun_sayisi() >= 2
    )


def _s_ziyaret_kaydi_yok(stmt, user=None, clock=None, donem=None):
    """Tekrar ziyaret ölçülemeyen çözülmüş saha işi: SAHA kaydı yok ve uzaktan
    çözülmemiş ("eksik", 0 değil)."""
    return _cozulen(stmt, clock, donem).where(
        ServiceOrder.kategori == SLA_KATEGORISI,
        saha_gun_sayisi() == 0,
        not_(uzaktan_kosulu()),
    )


def _sla(sonuc: str | None):
    def _s(stmt, user=None, clock=None, donem=None):
        bas, bit = _aralik(clock, donem)
        stmt = _taban(stmt).where(
            ServiceOrder.kategori == SLA_KATEGORISI,
            ServiceOrder.status != "IPTAL",
            _arada(ServiceOrder.first_completed_at, bas, bit),
        )
        if sonuc is None:
            return stmt.where(ServiceOrder.sla_sonuc.is_(None))
        return stmt.where(ServiceOrder.sla_sonuc == sonuc)

    return _s


# --- Kayıt -----------------------------------------------------------------------------

# Bölüm sırası ekrandaki ve Excel "Yönetim Özeti"ndeki sıradır.
BOLUMLER: dict[str, str] = {
    "GENEL": "Genel",
    "SURE": "Süre ve kişi-saat",
    "KALITE": "Kalite (yeniden açılan, tekrar arıza, tekrar ziyaret)",
    "SLA": "SLA (yalnız günlük servis)",
}
# kod → bölüm (eklenme sırası korunur).
RAPOR_KPI_BOLUMU: dict[str, str] = {}


def rapor_kpi_kaydet(tanim: panel.KpiTanimi, bolum: str) -> panel.KpiTanimi:
    """Rapor KPI'sı kaydı — diğer paketlerin (D3-E) TEK giriş noktası.

    Tanım `panel.KPI_TANIMLARI`'na `grup="RAPOR"` ve `donemsel=True` ile girer
    (sayı = `/isler?kpi=` listesi). `tanim.izin` kullanıcıda yoksa kutu
    `/ozet`'te hiç görünmez (ör. bakım KPI'sı `bakim.gor`).
    """
    if tanim.grup != "RAPOR" or not tanim.donemsel:
        raise ValueError("Rapor KPI'sı grup='RAPOR' ve donemsel=True olmalı")
    if bolum not in BOLUMLER:
        BOLUMLER[bolum] = bolum.title()
    panel.kpi_kaydet(tanim)
    RAPOR_KPI_BOLUMU[tanim.kod] = bolum
    return tanim


def _k(kod, baslik, tanim, suzgec, **kw) -> panel.KpiTanimi:
    return panel.KpiTanimi(kod, baslik, tanim, suzgec, grup="RAPOR", donemsel=True, **kw)


for _bolum, _t in (
    ("GENEL", _k("rapor_gelen", "Gelen iş", "Dönemde açılan servis işleri (tüm kategoriler; kategori ayrımı kırılımda).", _s_gelen)),  # noqa: E501
    ("GENEL", _k("rapor_cozulen", "Çözülen iş", "Çözüldü grubunda (Tamamlandı + Kapatıldı) olup son çözüm anı dönemde olan işler.", _s_cozulen)),  # noqa: E501
    ("GENEL", _k("rapor_iptal", "İptal edilen", "Dönemde iptal edilen işler (açık ve geciken listelerine girmez).", _s_iptal)),  # noqa: E501
    ("GENEL", _k("rapor_donem_sonu_acik", "Dönem sonu açık", "Dönemin son günü bittiğinde açık olan işler (olay geçmişinden; yeniden açılanlar dahil).", _s_donem_sonu_acik)),  # noqa: E501
    ("GENEL", _k("rapor_kritik_acik", "Kritik açık", "Dönem sonunda açık ve önceliği KRİTİK olan işler.", _s_kritik_acik, vurgu="kritik")),  # noqa: E501
    ("GENEL", _k("rapor_uzaktan_cozulen", "Telefon/uzaktan çözülen", "Dönemde çözülen ve geçerli sonucun çözüm kanalı TELEFON ya da UZAKTAN olan işler.", _s_uzaktan_cozulen)),  # noqa: E501
    ("SURE", _k("rapor_sure_girilen", "Süre girilen iş", "Dönemde başlayan, kişi-saate dahil (mola hariç) geçerli süre kaydı olan işler.", _s_sure_girilen)),  # noqa: E501
    ("SURE", _k("rapor_sure_eksik", "Süre kaydı eksik", "Dönemde çözülmüş ve süre kaydı hiç olmayan ya da bir teknisyeninin kaydı eksik işler. Telefon/uzaktan çözülen iş eksik sayılmaz; tahmini süre kullanılmaz.", _s_sure_eksik, vurgu="uyari")),  # noqa: E501
    ("KALITE", _k("rapor_ilk_cozulen", "İlk kez çözülen", "İlk çözüm anı (first_completed_at) dönemde olan işler; PB hariç. Yeniden açılma oranının paydası.", _s_ilk_cozulen)),  # noqa: E501
    ("KALITE", _k("rapor_yeniden_acilan", "Yeniden açılan", "Dönemde en az bir kez yeniden açılan işler (iş başına bir sayılır); PB hariç.", _s_yeniden_acilan, vurgu="uyari")),  # noqa: E501
    ("KALITE", _k("rapor_yeniden_acilan_pb", "Yeniden açılan (PB)", "Dönemde yeniden açılan planlı bakım işleri (ayrı satır).", _s_yeniden_acilan_pb)),  # noqa: E501
    ("KALITE", _k("rapor_tekrar_payda", "Tekrar arıza paydası", "Dönemde çözülen günlük servis ve atölye işleri.", _s_tekrar_payda)),  # noqa: E501
    ("KALITE", _k("rapor_tekrar_ariza_onayli", "Tekrar arıza (onaylı)", "Dönemde çözülen saha/atölye işinden sonra pencere içinde açılıp bu işe bağlanan ve kök nedeni AYNI ARIZA olarak teyit edilen iş olanlar.", tekrar_ariza_suzgeci(onayli=True), vurgu="uyari")),  # noqa: E501
    ("KALITE", _k("rapor_tekrar_ariza_aday", "Tekrar arıza adayı (onaysız)", "Sonraki iş bu işe tekrar arıza olarak bağlanmış ya da aday işaretli, ama kök neden teyidi henüz girilmemiş.", tekrar_ariza_suzgeci(onayli=False))),  # noqa: E501
    ("KALITE", _k("rapor_tekrar_ziyaret", "Tekrar ziyaret", "Dönemde çözülen günlük servis işinde SAHA faaliyetli en az iki farklı gün var.", _s_tekrar_ziyaret)),  # noqa: E501
    ("KALITE", _k("rapor_ziyaret_kaydi_yok", "Ziyaret kaydı eksik", "Dönemde çözülen günlük servis işinde SAHA kaydı yok (telefon/uzaktan çözülen hariç): tekrar ziyaret ölçülemedi.", _s_ziyaret_kaydi_yok, vurgu="uyari")),  # noqa: E501
    ("SLA", _k("rapor_sla_zamaninda", "SLA zamanında", "İlk çözümü dönemde olan günlük servis işlerinden SLA sonucu ZAMANINDA olanlar.", _sla("ZAMANINDA"))),  # noqa: E501
    ("SLA", _k("rapor_sla_asildi", "SLA aşıldı", "İlk çözümü dönemde olan günlük servis işlerinden SLA sonucu AŞILDI olanlar.", _sla("ASILDI"), vurgu="kritik")),  # noqa: E501
    ("SLA", _k("rapor_sla_olculemedi", "SLA ölçülemedi", "SLA sonucu ÖLÇÜLEMEDİ olan işler — uyum paydasında YOK, ayrı satır.", _sla("OLCULEMEDI"))),  # noqa: E501
    ("SLA", _k("rapor_sla_damgasiz", "SLA damgası yok", "SLA yürürlüğünden önce açılmış ya da politikası olmayan işler — paydada YOK.", _sla(None))),  # noqa: E501
):  # fmt: skip
    rapor_kpi_kaydet(_t, _bolum)


def rapor_kpileri(user) -> list[panel.KpiTanimi]:
    """Kullanıcının görebileceği rapor KPI'ları (kayıt sırasıyla)."""
    return [
        panel.KPI_TANIMLARI[kod]
        for kod in RAPOR_KPI_BOLUMU
        if user.has(panel.KPI_TANIMLARI[kod].izin)
        and (not panel.KPI_TANIMLARI[kod].kisisel or user.has("servis_rapor.personel"))
    ]


# --- Ölçüler (sayı olmayan göstergeler; pay/payda iki tıklanabilir KPI) -----------------


@dataclass(frozen=True)
class OlcuTanimi:
    kod: str
    baslik: str
    tanim: str
    olcu_birimi: str  # yuzde | saat | kisi_saat
    pay: str | None = None
    payda: str | None = None


OLCULER: dict[str, OlcuTanimi] = {
    o.kod: o
    for o in (
        OlcuTanimi("kisi_saat", "Gerçek kişi-saat", "Dönemde başlayan, iptal edilmemiş, kapalı ve mola dışı süre kayıtlarının toplamı (saat). Bordro değildir; kayıt yoksa \"—\".", "kisi_saat"),  # noqa: E501
        OlcuTanimi("uzaktan_oran", "Uzaktan çözüm oranı", "Telefon/uzaktan çözülen / çözülen.", "yuzde", "rapor_uzaktan_cozulen", "rapor_cozulen"),  # noqa: E501
        OlcuTanimi("yeniden_acilma_orani", "Yeniden açılma oranı", "Yeniden açılan / ilk kez çözülen (PB hariç).", "yuzde", "rapor_yeniden_acilan", "rapor_ilk_cozulen"),  # noqa: E501
        OlcuTanimi("tekrar_ariza_orani", "Tekrar arıza oranı (onaylı)", "Onaylı tekrar arıza / dönemde çözülen saha + atölye işi.", "yuzde", "rapor_tekrar_ariza_onayli", "rapor_tekrar_payda"),  # noqa: E501
        OlcuTanimi("tekrar_ziyaret_orani", "Tekrar ziyaret oranı", "Tekrar ziyaret / (çözülen günlük servis − ziyaret kaydı eksik − uzaktan).", "yuzde", "rapor_tekrar_ziyaret"),  # noqa: E501
        OlcuTanimi("sla_uyum", "SLA uyumu", "Zamanında / (Zamanında + Aşıldı). Ölçülemedi ve damgasız paydada yok.", "yuzde", "rapor_sla_zamaninda"),  # noqa: E501
        OlcuTanimi("cozum_suresi_ort", "Ortalama çözüm süresi", "Günlük servis: bildirim (yoksa SLA başlangıcı / açılış) → ilk çözüm, SLA'yı durduran bekleme düşülmüş (saat).", "saat"),  # noqa: E501
        OlcuTanimi("cozum_suresi_medyan", "Medyan çözüm süresi", "Aynı tanımla medyan (saat).", "saat"),  # noqa: E501
    )
}  # fmt: skip


def tanimlar(user) -> dict[str, Any]:
    """`/tanimlar` — ekrandaki ⓘ metinleri ve Excel "Tanımlar" sayfası aynı kaynaktan."""
    return {
        "bolumler": [{"kod": k, "ad": a} for k, a in BOLUMLER.items()],
        "kpiler": [
            {
                "kod": t.kod,
                "baslik": t.baslik,
                "tanim": t.tanim,
                "bolum": RAPOR_KPI_BOLUMU[t.kod],
                "olcu_birimi": t.olcu_birimi,
                "vurgu": t.vurgu,
            }
            for t in rapor_kpileri(user)
        ],
        "olculer": [
            {"kod": o.kod, "baslik": o.baslik, "tanim": o.tanim, "olcu_birimi": o.olcu_birimi}
            for o in OLCULER.values()
        ],
        "tarih_esaslari": [{"kod": k, "ad": a} for k, a in TARIH_ESASLARI.items()],
        "boyutlar": [
            {"kod": k, "ad": a, "kisisel": k in KISISEL_BOYUTLAR}
            for k, a in BOYUTLAR.items()
            if k not in KISISEL_BOYUTLAR or user.has("servis_rapor.personel")
        ],
        "notlar": list(NOTLAR),
    }


NOTLAR = (
    'Tahmini süre gerçek süre yerine kullanılmaz; süre kaydı olmayan iş "eksik" sayılır, 0 değil.',
    "Kişi-saat bordro değildir: iki kişi 2 saat çalıştıysa 4 kişi-saattir; mola dahil değildir.",
    "Gelen, çözülen ve dönem sonu açık sayıları tarih esasından bağımsızdır; tarih esası "
    "yalnız detay listelerini ve kırılımları süzer.",
    "Ay ve gün gruplamaları Türkiye saatine (Europe/Istanbul) göredir.",
    "Olay geçmişi olmayan göç işlerinde dönem sonu açık sayısı güncel duruma göre "
    "kurulur; geçmiş dönem değerleri değişebilir.",
)


# --- Excel sütun şemaları (tek yer; E12-06 / TS-182) -------------------------------------


@dataclass(frozen=True)
class RaporSutunu:
    """Sayfa sütunu: başlık, satır sözlüğündeki anahtar, hücre tipi
    (`services/export.SUTUN_TIPLERI`), kişisel mi (`servis_rapor.personel`)."""

    baslik: str
    anahtar: str
    tip: str = "metin"
    kisisel: bool = False


_IS_SUTUNLARI: tuple[RaporSutunu, ...] = (
    RaporSutunu("İş Emri No", "so_no"),
    RaporSutunu("Açılış", "acilis", "zaman"),
    RaporSutunu("Birim", "birim"),
    RaporSutunu("Kategori", "kategori"),
    RaporSutunu("İş Türü", "tur"),
    RaporSutunu("Öncelik", "oncelik"),
    RaporSutunu("Durum", "durum"),
    RaporSutunu("Durum Grubu", "durum_grubu"),
    RaporSutunu("Müşteri", "musteri"),
    RaporSutunu("Proje", "proje"),
    RaporSutunu("Lokasyon", "lokasyon"),
    RaporSutunu("Şehir", "sehir"),
    RaporSutunu("İlçe", "ilce"),
    RaporSutunu("Sistem", "sistem"),
    RaporSutunu("Seri No", "seri"),
    RaporSutunu("Konu", "konu"),
    RaporSutunu("Şef", "sef"),
    RaporSutunu("Teknisyenler", "teknisyenler"),
    RaporSutunu("Plan Tarihi", "plan_tarihi", "tarih"),
    RaporSutunu("Tamamlanma", "tamamlanma", "zaman"),
    RaporSutunu("Kapanış", "kapanis", "zaman"),
    RaporSutunu("Çözüm Kanalı", "cozum_kanali"),
    RaporSutunu("Gerçek Kişi-Saat", "kisi_saat", "ondalik"),
    RaporSutunu("Süre Kaydı Durumu", "sure_durumu"),
    RaporSutunu("Saha Yetkilisi", "iletisim_ad", kisisel=True),
    RaporSutunu("Saha Telefonu", "iletisim_telefon", kisisel=True),
)

SUTUN_SEMALARI: dict[str, tuple[RaporSutunu, ...]] = {
    "is_listesi": _IS_SUTUNLARI,
    "birim_durum": (
        RaporSutunu("Birim", "birim"),
        RaporSutunu("Kategori", "kategori"),
        RaporSutunu("Toplam", "toplam", "tamsayi"),
        RaporSutunu("Açık", "acik", "tamsayi"),
        RaporSutunu("Çözülen", "cozuldu", "tamsayi"),
        RaporSutunu("İptal", "iptal", "tamsayi"),
        RaporSutunu("Beklemede", "beklemede", "tamsayi"),
        RaporSutunu("Kritik", "kritik", "tamsayi"),
        RaporSutunu("Süre Kaydı Eksik", "sure_eksik", "tamsayi"),
        RaporSutunu("Kişi-Saat", "kisi_saat", "ondalik"),
    ),
    "aylik_ozet": (
        RaporSutunu("Ay", "ay"),
        RaporSutunu("Gelen", "gelen", "tamsayi"),
        RaporSutunu("Çözülen", "cozulen", "tamsayi"),
        RaporSutunu("İptal", "iptal", "tamsayi"),
        RaporSutunu("Dönem Sonu Açık", "donem_sonu_acik", "tamsayi"),
        RaporSutunu("Kişi-Saat", "kisi_saat", "ondalik"),
    ),
    "personel_kpi": (
        RaporSutunu("Personel", "personel", kisisel=True),
        RaporSutunu("Gerçek Kişi-Saat", "kisi_saat", "ondalik", kisisel=True),
        RaporSutunu("Farklı İş", "farkli_is", "tamsayi", kisisel=True),
        RaporSutunu("Faaliyet Kaydı", "kayit", "tamsayi", kisisel=True),
        RaporSutunu("Saha", "SAHA", "ondalik", kisisel=True),
        RaporSutunu("Yol", "YOL", "ondalik", kisisel=True),
        RaporSutunu("Bekleme", "BEKLEME", "ondalik", kisisel=True),
        RaporSutunu("Uzaktan", "UZAKTAN", "ondalik", kisisel=True),
        RaporSutunu("Atölye", "ATOLYE", "ondalik", kisisel=True),
        RaporSutunu("Test", "TEST", "ondalik", kisisel=True),
        RaporSutunu("Diğer", "DIGER", "ondalik", kisisel=True),
        RaporSutunu("Not", "not", kisisel=True),
    ),
    "sure_hareketleri": (
        RaporSutunu("İş Emri No", "so_no", kisisel=True),
        RaporSutunu("Kategori", "kategori", kisisel=True),
        RaporSutunu("Birim", "birim", kisisel=True),
        RaporSutunu("Teknisyen", "personel", kisisel=True),
        RaporSutunu("Müşteri", "musteri", kisisel=True),
        RaporSutunu("Şehir", "sehir", kisisel=True),
        RaporSutunu("Lokasyon", "lokasyon", kisisel=True),
        RaporSutunu("Faaliyet", "faaliyet", kisisel=True),
        RaporSutunu("Başlangıç", "baslangic", "zaman", kisisel=True),
        RaporSutunu("Bitiş", "bitis", "zaman", kisisel=True),
        RaporSutunu("Süre (dk)", "sure_dk", "tamsayi", kisisel=True),
        RaporSutunu("Gerçek Saat", "saat", "ondalik", kisisel=True),
        RaporSutunu("Konum Notu", "konum_notu", kisisel=True),
        RaporSutunu("Teknisyen Notu", "aciklama", kisisel=True),
        RaporSutunu("Kaynak", "kaynak", kisisel=True),
    ),
    "musteri_lokasyon": (
        RaporSutunu("Müşteri", "musteri"),
        RaporSutunu("Şehir", "sehir"),
        RaporSutunu("Lokasyon", "lokasyon"),
        RaporSutunu("Toplam İş", "toplam", "tamsayi"),
        RaporSutunu("Açık", "acik", "tamsayi"),
        RaporSutunu("Çözülen", "cozuldu", "tamsayi"),
        RaporSutunu("Süre Kaydı Eksik", "sure_eksik", "tamsayi"),
        RaporSutunu("Kişi-Saat", "kisi_saat", "ondalik"),
    ),
    "yeniden_acilan": (
        RaporSutunu("İş Emri No", "so_no"),
        RaporSutunu("Kategori", "kategori"),
        RaporSutunu("İlk Çözüm", "ilk_cozum", "zaman"),
        RaporSutunu("Yeniden Açılış", "yeniden_acilis", "zaman"),
        RaporSutunu("Gün Farkı", "gun_farki", "tamsayi"),
        RaporSutunu("Gerekçe", "gerekce"),
    ),
}


def sutunlar(sema: str, user) -> list[RaporSutunu]:
    """Şemanın kullanıcıya açık sütunları: kişisel sütun izinsizde HİÇ yoktur."""
    kisisel = user.has("servis_rapor.personel")
    return [s for s in SUTUN_SEMALARI[sema] if kisisel or not s.kisisel]


def kisisel_anahtarlar() -> frozenset[str]:
    """JSON yanıtlarında izinsizde bulunmayacak anahtarlar (test kilidi)."""
    return frozenset({"iletisim_ad", "iletisim_telefon", "konum_notu", "aciklama", "personel"})


__all__ = [
    "BOYUTLAR",
    "EXCEL_AZAMI_SATIR",
    "JSON_AZAMI_SATIR",
    "OLCULER",
    "RAPOR_KPI_BOLUMU",
    "SUTUN_SEMALARI",
    "TARIH_ESASLARI",
    "acik_kosulu",
    "rapor_kpi_kaydet",
    "rapor_kpileri",
    "tanimlar",
]
