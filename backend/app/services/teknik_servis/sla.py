"""SLA çekirdeği — TEK SLA modülü (E10-01/10/12/13/17/18, TS-081/085).

Doldurdu: D2-G. İmzalar plan §1.8/§4 sözleşmesidir.

**Neden tek modül:** Operasyon Merkezi sayaçları, Servis Paneli, liste
sıralaması, uyarı zili, kalıcı bildirim üretimi, "Benim İşlerim" ve (Dalga 3)
SLA raporu aynı "bu iş gecikti mi" sorusunu soruyor. Her ekran kendi hesabını
yazsaydı panel "3 geciken" derken zil "2" derdi. Bu yüzden hesap iki yüzlü
ama TEK kurallıdır: Python tarafı `sla_durumu()` (tek kayıt, detay/kart) ve
SQL tarafı `sla_ifadeleri()` (liste, sayaç, uyarı). İkisinin aynı sonucu
verdiği karışık veri setiyle test edilir (`test_servis_sla_tutarlilik`).
İstemci SLA HESAPLAMAZ (öncelik → saat eşlemesi ön yüzde yok; grep testi).

**Damga kuralları (TS-081):**
- Yalnız GUNLUK_SERVIS kategorisinde ölçülür; PB ve atölye şemada da
  yasak (`ck_so_pb_sla`), proje türleri (KURULUM…) burada damgalanmaz.
- `servis_sla_yururluk_at` boşken (ya da açılış anı yürürlükten önceyse)
  damga YOK (KD-22: canlıya geçişte göç işleri uyarı fırtınası üretmesin).
- Başlangıç = açılış anı, `clock.now()` (K1/B8: elle girilen `reported_at`
  ya da DB saati `created_at` değil).
- Politika işe DONDURULUR: politika sonradan değişse de açık işin hedefi
  değişmez; yalnız öncelik/tür/kategori düzeltmesi yeniden damgalar.
- SLA durduran İŞ BEKLEMESİ (`service_holds.sla_durdurur`) bitince hedef,
  beklenen süre kadar İLERİ alınır (`sla_kayma_dk`); hedef geriye alınmaz.
  "Personel Bekleme Süresi" (zaman kaydındaki BEKLEME faaliyeti) SLA'yı
  durdurmaz ve ilk müdahale sayılmaz (E10-17).
- `sla_sonuc` İLK TAMAMLANDI'da donar; yeniden açılış silmez (E10 kontrol
  B3). Hedefi olmayan GUNLUK_SERVIS işi OLCULEMEDI'dir (uyum paydasına girmez).
- Hedefi aşılmış (CANLI damgalı) iş gecikme nedeni girilmeden KAPATILAMAZ (409).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Integer,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
)

from app.models import (
    ServiceHold,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceSlaPolicy,
    Setting,
)
from app.models.teknik_servis import (
    DURUM_GRUPLARI,
    SLA_DURUMLARI,
)
from app.services import audit
from app.services import settings as ayarlar
from app.services.teknik_servis import gecmis, kancalar, sla_takvim
from app.services.teknik_servis.kancalar import ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_an

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceTimeEntry


class SlaHatasi(ServisHatasi):
    """SLA kural ihlali (politika tanımsız, gecikme nedeni eksik) → 409."""


# --- Sabitler -------------------------------------------------------------------------

SLA_KATEGORISI = "GUNLUK_SERVIS"
# İlk müdahale sayılan faaliyetler (E10 kontrol B4): YOL, MOLA, BEKLEME, DIGER sayılmaz.
ILK_MUDAHALE_FAALIYETLERI = frozenset({"SAHA", "UZAKTAN", "ATOLYE", "TEST"})
# İşin bu durumlara geçişi de ilk müdahaledir (sayaç kullanılmasa bile).
MUDAHALE_DURUMLARI = frozenset({"SAHADA", "ISLEMDE", "ATOLYEDE"})
RISK_VARSAYILAN = 80
_KAPALI = sorted(DURUM_GRUPLARI["KAPALI"])
_ACIK = sorted(DURUM_GRUPLARI["ACIK"])

SLA_DURUM_ADLARI: dict[str, str] = {
    "ZAMANINDA": "Zamanında",
    "RISKTE": "Riskte",
    "ASILDI": "Gecikti",
    "DURDURULDU": "Durduruldu",
    "KARSILANDI": "Karşılandı",
    "KARSILANMADI": "Karşılanmadı",
    "OLCULEMEDI": "Ölçülemedi",
    "SLA_DISI_PB": "SLA dışı (planlı bakım)",
}
# Ad tablosu = SLA_DURUMLARI (tek sözlük; `tests/unit/test_sla_hesap.py` kilitler).

MUDAHALE_DURUM_ADLARI: dict[str, str] = {
    "BEKLENIYOR": "Bekleniyor",
    "ASILDI": "Gecikti",
    "KARSILANDI": "Karşılandı",
    "KARSILANMADI": "Karşılanmadı",
}

# E10-17: iki farklı "bekleme" kavramının ekran/rapor başlıkları (ayrık kalır).
TERIMLER: dict[str, str] = {
    "IS_BEKLEMESI": "İş Beklemesi",
    "PERSONEL_BEKLEME": "Personel Bekleme Süresi",
}

AY_ADLARI = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


@dataclass(frozen=True)
class SlaDurumu:
    """Ekranda gösterilen HESAPLANMIŞ SLA durumu (istemci SLA hesaplamaz)."""

    durum: str  # SLA_DURUMLARI
    hedef_at: datetime | None
    kalan_dk: int | None
    mudahale_durumu: str | None
    # Ek bilgiler (varsayılanlı; imza sözleşmesindeki dört alan aynı kalır).
    olculur: bool = True
    ek: dict[str, Any] = field(default_factory=dict)

    @property
    def ad(self) -> str:
        if not self.olculur and self.durum == "OLCULEMEDI":
            return "SLA dışı"
        return SLA_DURUM_ADLARI[self.durum]


# --- Küçük yardımcılar ---------------------------------------------------------------


def sla_olculur_mu(so: ServiceOrder) -> bool:
    """SLA yalnız GUNLUK_SERVIS kategorisinde ölçülür (PB/ATOLYE hiçbir zaman)."""
    return so.kategori == SLA_KATEGORISI and so.tur not in ("PB", "ATOLYE")


def _dk(saniye: float) -> int:
    """Saniye → dakika, aşağı yuvarlama (SQL `floor(epoch/60)` ile aynı)."""
    return math.floor(saniye / 60)


def _yerel_metin(an: datetime | None) -> str:
    return yerel_an(an).strftime("%d.%m.%Y %H:%M") if an is not None else "—"


def _iso(an: datetime | None) -> str | None:
    return an.isoformat() if an is not None else None


def _saat_dk(saat: Any) -> int | None:
    if saat is None:
        return None
    return int(round(float(saat) * 60))


def vade_ay_metni(gun: date | None) -> str | None:
    """PB vadesinin ay gösterimi ("Ekim 2026") — K14."""
    if gun is None:
        return None
    return f"{AY_ADLARI[gun.month - 1]} {gun.year}"


async def yururluk_ani(db: AsyncSession) -> datetime | None:
    """`servis_sla_yururluk_at` (ISO, saat dilimli); boşsa None → damga yok."""
    deger = await ayarlar.get(db, "servis_sla_yururluk_at")
    if not deger:
        return None
    an = datetime.fromisoformat(str(deger))
    return an if an.tzinfo is not None else None


async def risk_yuzdesi(db: AsyncSession) -> int:
    return int(await ayarlar.get(db, "servis_sla_risk_yuzde") or RISK_VARSAYILAN)


def ayar_tam_ifadesi(anahtar: str) -> Any:
    """Tam sayı ayarın SQL ifadesi (yoksa `DEFAULTS` değeri).

    KPI süzgeçleri senkron ve DB'siz çağrılır (`panel.KPI_TANIMLARI`); eşik
    sorgunun İÇİNDE okunursa sayaç, liste ve uyarı aynı anda aynı ayarı görür.
    """
    varsayilan = int(ayarlar.DEFAULTS[anahtar])
    alt = (
        select(cast(literal_column("settings.value #>> '{}'"), Integer))
        .select_from(Setting.__table__)
        .where(Setting.key == anahtar)
        .scalar_subquery()
    )
    return func.coalesce(alt, varsayilan)


async def _acilis_ani(db: AsyncSession, so: ServiceOrder) -> datetime | None:
    """İşin Clock'la yazılmış açılış anı (OLUSTUR olayı; `created_at` DB saatidir)."""
    return await db.scalar(
        select(func.min(ServiceOrderEvent.olusma_zamani)).where(
            ServiceOrderEvent.service_order_id == so.id,
            ServiceOrderEvent.olay_turu == "OLUSTUR",
        )
    )


async def aktif_bekleme(db: AsyncSession, so_id: int) -> ServiceHold | None:
    return await db.scalar(
        select(ServiceHold).where(
            ServiceHold.service_order_id == so_id, ServiceHold.released_at.is_(None)
        )
    )


async def _kaymalar(db: AsyncSession, so: ServiceOrder) -> tuple[int, int]:
    """(çözüm kayması, müdahale kayması) — kapanmış beklemelerin `sla_kayma_dk` toplamı.

    Müdahale hedefi yalnız ilk müdahaleden ÖNCE başlamış beklemelerle kayar.
    """
    satirlar = (
        await db.execute(
            select(ServiceHold.started_at, ServiceHold.sla_kayma_dk).where(
                ServiceHold.service_order_id == so.id,
                ServiceHold.released_at.is_not(None),
                ServiceHold.sla_kayma_dk.is_not(None),
            )
        )
    ).all()
    cozum = sum(int(k) for _, k in satirlar)
    mudahale = sum(
        int(k) for bas, k in satirlar if so.ilk_mudahale_at is None or bas < so.ilk_mudahale_at
    )
    return cozum, mudahale


# --- Politika ----------------------------------------------------------------------------


async def politika_bul(db: AsyncSession, oncelik: str, birim: str) -> ServiceSlaPolicy:
    """Önce birim+öncelik, yoksa öncelik (birim NULL) aktif politika; yoksa SlaHatasi (409)."""
    politika = await db.scalar(
        select(ServiceSlaPolicy)
        .where(
            ServiceSlaPolicy.oncelik == oncelik,
            ServiceSlaPolicy.is_active.is_(True),
            or_(ServiceSlaPolicy.birim == birim, ServiceSlaPolicy.birim.is_(None)),
        )
        # Birime özel satır önce (NULL sonda), eşitlikte en yeni.
        .order_by(ServiceSlaPolicy.birim.is_(None), ServiceSlaPolicy.id.desc())
        .limit(1)
    )
    if politika is None:
        raise SlaHatasi(f"SLA politikası tanımsız: {oncelik} öncelik ({birim})")
    return politika


def _hedefleri_yaz(
    so: ServiceOrder,
    politika: ServiceSlaPolicy,
    bas: datetime,
    *,
    cozum_kayma: int,
    mudahale_kayma: int,
) -> None:
    tur = politika.takvim_turu or sla_takvim.TAKVIM_7_24
    cozum_dk = _saat_dk(politika.cozum_saat) or 0
    mudahale_dk = _saat_dk(politika.mudahale_saat)
    so.sla_policy_id = politika.id
    so.sla_baslangic_at = bas
    so.sla_takvim_turu = tur
    so.cozum_hedef_dk = cozum_dk
    so.mudahale_hedef_dk = mudahale_dk
    so.cozum_hedef_at = sla_takvim.is_saati_ekle(bas, cozum_dk + cozum_kayma, tur)
    so.mudahale_hedef_at = (
        sla_takvim.is_saati_ekle(bas, mudahale_dk + mudahale_kayma, tur)
        if mudahale_dk is not None
        else None
    )


def _damga_ozeti(so: ServiceOrder) -> dict[str, Any]:
    return {
        "sla_policy_id": so.sla_policy_id,
        "oncelik": so.oncelik,
        "cozum_hedef_at": _iso(so.cozum_hedef_at),
        "mudahale_hedef_at": _iso(so.mudahale_hedef_at),
    }


# --- Kancalar ------------------------------------------------------------------------------


async def damgala(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """`is_olusturuldu` kancası: yalnız GUNLUK_SERVIS ve `servis_sla_yururluk_at` doluyken
    hedef damgalar. Aktif politika yoksa açılış 409 ("SLA politikası tanımsız")."""
    if not sla_olculur_mu(so) or so.sla_policy_id is not None:
        return
    simdi = clock.now()
    yururluk = await yururluk_ani(db)
    if yururluk is None or simdi < yururluk:
        return
    politika = await politika_bul(db, so.oncelik, so.birim)
    _hedefleri_yaz(so, politika, simdi, cozum_kayma=0, mudahale_kayma=0)
    so.cozum_hedef_ilk_at = so.cozum_hedef_at
    so.sla_kaynak = "CANLI"
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "SLA",
        f"SLA hedefi damgalandı: {_yerel_metin(so.cozum_hedef_at)} ({so.oncelik})",
        user=None,
        clock=clock,
        veri=_damga_ozeti(so),
    )


def _damgayi_temizle(so: ServiceOrder) -> None:
    so.sla_policy_id = None
    so.sla_baslangic_at = None
    so.sla_takvim_turu = None
    so.cozum_hedef_dk = None
    so.mudahale_hedef_dk = None
    so.cozum_hedef_ilk_at = None
    so.cozum_hedef_at = None
    so.mudahale_hedef_at = None
    so.sla_kaynak = None


async def yeniden_damgala(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """`oncelik_birim_degisti` kancası: politika ve hedef yeniden hesaplanır (SLA olayı).

    - Sonuç donmuşsa (ilk TAMAMLANDI geçti) hiçbir şey değişmez.
    - İş artık SLA dışıysa (tür/kategori düzeltmesi) damga temizlenir.
    - Hedef `sla_baslangic_at`'ten yeni politikayla hesaplanır, biriken bekleme
      kayması eklenir; `cozum_hedef_ilk_at` DEĞİŞMEZ.
    - Hiç damgalanmamış iş yalnız açılışı yürürlükten sonraysa damgalanır.
    """
    if so.sla_sonuc is not None:
        return
    eski = _damga_ozeti(so)
    if not sla_olculur_mu(so):
        if so.sla_policy_id is None and so.cozum_hedef_at is None:
            return
        _damgayi_temizle(so)
        await db.flush()
        await gecmis.olay_yaz(
            db,
            so,
            "SLA",
            "İş SLA dışına çıktı (tür/kategori değişti); SLA hedefi kaldırıldı",
            user=None,
            clock=clock,
            veri={"eski": eski},
        )
        await audit.log(
            db,
            "service_orders",
            "sla.yeniden_damga",
            entity_id=so.id,
            old_value=eski,
            new_value=_damga_ozeti(so),
            user_id=so.updated_by,
        )
        return
    if so.sla_policy_id is None:
        acilis = await _acilis_ani(db, so)
        yururluk = await yururluk_ani(db)
        if acilis is None or yururluk is None or acilis < yururluk:
            return
        bas = acilis
    else:
        bas = so.sla_baslangic_at or await _acilis_ani(db, so) or clock.now()
    politika = await politika_bul(db, so.oncelik, so.birim)
    eski_hedef = so.cozum_hedef_at
    cozum_kayma, mudahale_kayma = await _kaymalar(db, so)
    _hedefleri_yaz(so, politika, bas, cozum_kayma=cozum_kayma, mudahale_kayma=mudahale_kayma)
    if so.cozum_hedef_ilk_at is None:
        so.cozum_hedef_ilk_at = so.cozum_hedef_at
    if so.sla_kaynak is None:
        so.sla_kaynak = "CANLI"
    yeni = _damga_ozeti(so)
    if yeni == eski:
        return
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "SLA",
        f"SLA hedefi yeniden hesaplandı: {_yerel_metin(eski_hedef)} → "
        f"{_yerel_metin(so.cozum_hedef_at)} ({so.oncelik})",
        user=None,
        clock=clock,
        veri={"eski": eski, "yeni": yeni},
    )
    await audit.log(
        db,
        "service_orders",
        "sla.yeniden_damga",
        entity_id=so.id,
        old_value=eski,
        new_value=yeni,
        user_id=so.updated_by,
    )


async def _bekleme_kaymasi_isle(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """Az önce kapanan beklemenin SLA kaymasını yazar; durduruyorsa hedefi ileri alır."""
    bekleme = await db.scalar(
        select(ServiceHold)
        .where(
            ServiceHold.service_order_id == so.id,
            ServiceHold.released_at.is_not(None),
            ServiceHold.sla_kayma_dk.is_(None),
        )
        .order_by(ServiceHold.released_at.desc(), ServiceHold.id.desc())
        .limit(1)
    )
    if bekleme is None:
        return
    tur = so.sla_takvim_turu or sla_takvim.TAKVIM_7_24
    kayma = (
        sla_takvim.takvim_dakika(bekleme.started_at, bekleme.released_at, tur)
        if bekleme.sla_durdurur
        else 0
    )
    bekleme.sla_kayma_dk = kayma
    if kayma <= 0 or so.cozum_hedef_at is None or so.sla_sonuc is not None:
        await db.flush()
        return
    eski = so.cozum_hedef_at
    so.cozum_hedef_at = sla_takvim.is_saati_ekle(eski, kayma, tur)
    if so.mudahale_hedef_at is not None and so.ilk_mudahale_at is None:
        so.mudahale_hedef_at = sla_takvim.is_saati_ekle(so.mudahale_hedef_at, kayma, tur)
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "SLA",
        f"SLA hedefi {_yerel_metin(eski)} → {_yerel_metin(so.cozum_hedef_at)} "
        f"(iş beklemesi: {bekleme.neden}, {kayma} dk)",
        user=None,
        clock=clock,
        veri={
            "neden": bekleme.neden,
            "kayma_dk": kayma,
            "eski_hedef": _iso(eski),
            "yeni_hedef": _iso(so.cozum_hedef_at),
        },
    )


async def _sonucu_dondur(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """İlk TAMAMLANDI'da `sla_sonuc` ve `sla_durdurulan_dk` (yalnız bir kez)."""
    toplam = await db.scalar(
        select(func.coalesce(func.sum(ServiceHold.sla_kayma_dk), 0)).where(
            ServiceHold.service_order_id == so.id
        )
    )
    so.sla_durdurulan_dk = int(toplam or 0)
    if so.cozum_hedef_at is None:
        # Damgasız iş (yürürlük öncesi / politika yok) — sessizce ölçülemedi.
        so.sla_sonuc = "OLCULEMEDI"
        await db.flush()
        return
    if so.ilk_mudahale_at is None:
        so.ilk_mudahale_at = so.completed_at
    so.sla_sonuc = "ASILDI" if so.completed_at > so.cozum_hedef_at else "ZAMANINDA"
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "SLA",
        f"SLA sonucu: {'Aşıldı' if so.sla_sonuc == 'ASILDI' else 'Zamanında'} "
        f"(hedef {_yerel_metin(so.cozum_hedef_at)})",
        user=None,
        clock=clock,
        veri={"sla_sonuc": so.sla_sonuc, "durdurulan_dk": so.sla_durdurulan_dk},
    )


async def durum_isle(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: bekleme kayması, ilk müdahale, ilk TAMAMLANDI'da sonucu
    dondurma. `bekletme` kancasından SONRA çağrılır (aktif bekleme kapanmış olur)."""
    if onceki == "BEKLEMEDE" and hedef != "BEKLEMEDE":
        await _bekleme_kaymasi_isle(db, so, clock)
    if not sla_olculur_mu(so):
        return
    if hedef in MUDAHALE_DURUMLARI and so.ilk_mudahale_at is None:
        so.ilk_mudahale_at = clock.now()
        await db.flush()
    if (
        hedef == "TAMAMLANDI"
        and so.sla_sonuc is None
        and so.completed_at is not None
        and so.first_completed_at == so.completed_at
    ):
        await _sonucu_dondur(db, so, clock)


async def ilk_mudahale_isle(db: AsyncSession, bolum: ServiceTimeEntry) -> None:
    """`zaman_bolumu_acildi` kancası: SAHA/UZAKTAN/ATOLYE/TEST faaliyetinde ilk müdahale.

    BEKLEME (personel bekleme süresi), YOL, MOLA ve DIGER ilk müdahale sayılmaz.
    İlk değer bir daha değişmez.
    """
    if bolum.faaliyet not in ILK_MUDAHALE_FAALIYETLERI:
        return
    so = await db.get(ServiceOrder, bolum.service_order_id)
    if so is None or so.ilk_mudahale_at is not None or not sla_olculur_mu(so):
        return
    so.ilk_mudahale_at = bolum.started_at
    await db.flush()


async def kapanis_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası: SLA'sı aşılmış (CANLI) iş gecikme nedenisiz KAPATILAMAZ.

    GECIS/GERIYE_DONUK işlerde zorunluluk yoktur (E10-D02: göç işleri kapanışı
    bloke etmesin). Neden `PUT /operasyon/isler/{so_id}/kapanis-bilgisi` ile girilir.
    """
    if hedef != "KAPATILDI":
        return
    if so.sla_sonuc == "ASILDI" and so.sla_kaynak == "CANLI" and so.gecikme_nedeni is None:
        raise SlaHatasi(
            "SLA hedefi aşılmış işte kapatmadan önce gecikme nedeni girilmeli "
            "(Operasyon Merkezi → Kapanış bilgisi)"
        )


# --- Hesap: Python tarafı --------------------------------------------------------------


def _risk_mi(so: ServiceOrder, simdi: datetime, risk_yuzde: int) -> bool:
    if so.sla_baslangic_at is None or so.cozum_hedef_at is None:
        return False
    gecen = (simdi - so.sla_baslangic_at).total_seconds()
    toplam = (so.cozum_hedef_at - so.sla_baslangic_at).total_seconds()
    return gecen * 100 >= toplam * risk_yuzde


def mudahale_durumu(so: ServiceOrder, simdi: datetime) -> str | None:
    if so.mudahale_hedef_at is None:
        return None
    if so.ilk_mudahale_at is not None:
        return "KARSILANDI" if so.ilk_mudahale_at <= so.mudahale_hedef_at else "KARSILANMADI"
    if so.status in DURUM_GRUPLARI["KAPALI"]:
        return None
    return "ASILDI" if so.mudahale_hedef_at <= simdi else "BEKLENIYOR"


def sla_durumu(so: Any, aktif_bekleme: Any, simdi: datetime, risk_yuzde: int) -> SlaDurumu:
    """Python tarafı tek hesap (SQL `sla_ifadeleri` ile AYNI sonucu verir).

    `aktif_bekleme`: işin açık `service_holds` satırı (yoksa None).
    """
    olculur = sla_olculur_mu(so)
    mud = mudahale_durumu(so, simdi)

    def _sonuc(durum: str, kalan: int | None = None) -> SlaDurumu:
        return SlaDurumu(durum, so.cozum_hedef_at, kalan, mud, olculur)

    if so.tur == "PB":
        return SlaDurumu("SLA_DISI_PB", None, None, None, False)
    if so.sla_sonuc == "ZAMANINDA":
        return _sonuc("KARSILANDI")
    if so.sla_sonuc == "ASILDI":
        return _sonuc("KARSILANMADI")
    if (
        so.sla_sonuc == "OLCULEMEDI"
        or so.cozum_hedef_at is None
        or so.status in DURUM_GRUPLARI["KAPALI"]
    ):
        return _sonuc("OLCULEMEDI")
    if aktif_bekleme is not None and aktif_bekleme.sla_durdurur:
        return _sonuc(
            "DURDURULDU", _dk((so.cozum_hedef_at - aktif_bekleme.started_at).total_seconds())
        )
    kalan = _dk((so.cozum_hedef_at - simdi).total_seconds())
    if so.cozum_hedef_at <= simdi:
        return _sonuc("ASILDI", kalan)
    if _risk_mi(so, simdi, risk_yuzde):
        return _sonuc("RISKTE", kalan)
    return _sonuc("ZAMANINDA", kalan)


# --- Hesap: SQL tarafı ------------------------------------------------------------------


def _durdurucu_bekleme():
    return exists().where(
        ServiceHold.service_order_id == ServiceOrder.id,
        ServiceHold.released_at.is_(None),
        ServiceHold.sla_durdurur.is_(True),
    )


def _bekleme_baslangici():
    return (
        select(ServiceHold.started_at)
        .where(ServiceHold.service_order_id == ServiceOrder.id, ServiceHold.released_at.is_(None))
        .limit(1)
        .scalar_subquery()
    )


def _epoch(ifade):
    return func.extract("epoch", ifade)


def sla_ifadeleri(simdi: datetime, risk_yuzde: Any) -> dict[str, Any]:
    """SQL tarafı: durum/kalan/sıralama ifadeleri (liste, sayaç, Excel, uyarı aynı ifadeyi
    kullanır). `risk_yuzde` tam sayı ya da SQL ifadesi (`ayar_tam_ifadesi`) olabilir.

    Dönüş: `durum` (CASE → SLA_DURUMLARI), `kalan_dk` (açık ölçülen işte, yoksa
    NULL), `acik_olculen` (koşul), `durdurulmus` (koşul), `siralama` (order_by
    listesi: önce işleyen SLA en yakın hedef, sonra durdurulmuşlar, en sonda
    ölçülmeyenler).
    """
    an = literal(simdi, DateTime(timezone=True))
    durdurucu = _durdurucu_bekleme()
    kapali = ServiceOrder.status.in_(_KAPALI)
    acik_olculen = and_(
        ServiceOrder.tur != "PB",
        ServiceOrder.sla_sonuc.is_(None),
        ServiceOrder.cozum_hedef_at.is_not(None),
        ServiceOrder.status.in_(_ACIK),
    )
    risk = (
        _epoch(an - ServiceOrder.sla_baslangic_at) * 100
        >= _epoch(ServiceOrder.cozum_hedef_at - ServiceOrder.sla_baslangic_at) * risk_yuzde
    )
    durum = case(
        (ServiceOrder.tur == "PB", "SLA_DISI_PB"),
        (ServiceOrder.sla_sonuc == "ZAMANINDA", "KARSILANDI"),
        (ServiceOrder.sla_sonuc == "ASILDI", "KARSILANMADI"),
        (
            or_(
                ServiceOrder.sla_sonuc == "OLCULEMEDI",
                ServiceOrder.cozum_hedef_at.is_(None),
                kapali,
            ),
            "OLCULEMEDI",
        ),
        (durdurucu, "DURDURULDU"),
        (ServiceOrder.cozum_hedef_at <= an, "ASILDI"),
        (risk, "RISKTE"),
        else_="ZAMANINDA",
    )
    kalan = case(
        (
            and_(acik_olculen, durdurucu),
            func.floor(_epoch(ServiceOrder.cozum_hedef_at - _bekleme_baslangici()) / 60),
        ),
        (acik_olculen, func.floor(_epoch(ServiceOrder.cozum_hedef_at - an) / 60)),
        else_=None,
    )
    grup = case((and_(acik_olculen, ~durdurucu), 0), (acik_olculen, 1), else_=2)
    return {
        "durum": durum,
        "kalan_dk": cast(kalan, Integer),
        "acik_olculen": acik_olculen,
        "durdurulmus": durdurucu,
        "siralama": [grup, ServiceOrder.cozum_hedef_at.asc().nulls_last(), ServiceOrder.id],
    }


# --- Çıktı ------------------------------------------------------------------------------


def sla_blogu(
    so: ServiceOrder,
    aktif_bekleme: ServiceHold | None,
    simdi: datetime,
    risk_yuzde: int,
    *,
    vade: date | None = None,
) -> dict[str, Any]:
    """API'nin `sla` bloğu (detay, liste, Benim İşlerim). Fiyat/maliyet YOK."""
    d = sla_durumu(so, aktif_bekleme, simdi, risk_yuzde)
    return {
        "durum": d.durum,
        "ad": d.ad,
        "olculur": d.olculur,
        "hedef_at": d.hedef_at,
        "ilk_hedef_at": so.cozum_hedef_ilk_at,
        "kalan_dk": d.kalan_dk,
        "mudahale_durumu": d.mudahale_durumu,
        "mudahale_hedef_at": so.mudahale_hedef_at,
        "ilk_mudahale_at": so.ilk_mudahale_at,
        "durdurulan_dk": so.sla_durdurulan_dk,
        "sonuc": so.sla_sonuc,
        "kaynak": so.sla_kaynak,
        "gecikme_nedeni": so.gecikme_nedeni,
        "vade": vade,
        "vade_ay": vade_ay_metni(vade),
    }


async def sla_bloklari(
    db: AsyncSession, sos: list[ServiceOrder], clock: Clock
) -> dict[int, dict[str, Any]]:
    """Çok iş için `sla` blokları (aktif bekleme ve PB vadesi tek sorguyla)."""
    if not sos:
        return {}
    from datetime import timedelta

    from app.models import MaintenancePeriod

    idler = [s.id for s in sos]
    beklemeler = {
        b.service_order_id: b
        for b in (
            await db.scalars(
                select(ServiceHold).where(
                    ServiceHold.service_order_id.in_(idler), ServiceHold.released_at.is_(None)
                )
            )
        ).all()
    }
    donem_idler = {
        s.maintenance_period_id for s in sos if s.tur == "PB" and s.maintenance_period_id
    }
    vadeler: dict[int, date] = {}
    if donem_idler:
        tolerans = int(await ayarlar.get(db, "bakim_tolerans_gun") or 0)
        for donem_id, hedef in (
            await db.execute(
                select(MaintenancePeriod.id, MaintenancePeriod.target_date).where(
                    MaintenancePeriod.id.in_(donem_idler)
                )
            )
        ).all():
            if hedef is not None:
                vadeler[donem_id] = hedef + timedelta(days=tolerans)
    simdi = clock.now()
    risk = await risk_yuzdesi(db)
    return {
        s.id: sla_blogu(
            s,
            beklemeler.get(s.id),
            simdi,
            risk,
            vade=vadeler.get(s.maintenance_period_id) if s.tur == "PB" else None,
        )
        for s in sos
    }


# --- Kanca kayıtları (plan §1.8; sıra `s/__init__.py` import sırasıdır) -----------------
kancalar.kaydet("is_olusturuldu", damgala)
kancalar.kaydet("oncelik_birim_degisti", yeniden_damgala)
kancalar.kaydet("durum_degisti", durum_isle)
kancalar.kaydet("zaman_bolumu_acildi", ilk_mudahale_isle)
kancalar.kaydet("durum_dogrula", kapanis_dogrula)
