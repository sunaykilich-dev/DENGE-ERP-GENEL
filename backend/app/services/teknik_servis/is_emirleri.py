"""Servis işi: açılış, güncelleme, liste sorgusu ve TEK durum geçiş kapısı
(E01-02/03/09/11/13/15/16, TS-020/021/026/029/030/031).

Durum geçişi YALNIZ `durum_degistir` ile yapılır:
1. `kaynak` `UC_HEDEFLERI`'nde ve hedef o kaynağın kümesinde olmalı;
2. `SERVIS_IS_EMRI.dogrula(onceki, hedef)` (aynı durum → 409, olay YOK);
3. kaynak-izin kuralı (KAPATILDI/IPTAL yalnız `servis.kapat`, `sonuc` yolu
   yalnız `servis.tamamla`) — kullanıcısız (worker) çağrıda yok;
4. `kancalar.durum_dogrula` (sonuçsuz TAMAMLANDI, PB koruması, atölye, açık
   sayaç → 409) — YAZMADAN ÖNCE;
5. damgalar (TAMAMLANDI → `completed_at`, ilk seferde `first_completed_at`;
   KAPATILDI → `closed_at`; IPTAL → `cancelled_at` + gerekçe);
6. DURUM olayı (`gecmis.olay_yaz`) + `kancalar.durum_degisti` (aktif
   beklemenin kapanması, sonucun geçersiz kılınması ... aynı transaction).

**Kapanmış iş yeniden açılmaz (M1.7, Faz A):** makinede TAMAMLANDI/KAPATILDI
→ TEKRAR_ACILDI geçişi yoktur; kapanmış işin devamı `bagli_yeni_is` ile YENİ
iş olarak açılır (`onceki_is_id`). TEKRAR_ACILDI yalnız eski kayıtlarda kalır.

Servis fonksiyonları `flush` eder, `commit` ETMEZ; transaction sınırı API'dir.
Kapsam (404) API'nin işidir; burada yalnız iş kuralı vardır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import ColumnElement, Select, and_, exists, false, func, not_, or_, select

from app.models import (
    Account,
    Address,
    ServiceHold,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderSerial,
    ServicePlan,
    ServicePlanMember,
    ServiceResult,
    ServiceTimeEntry,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import (
    DURUM_GRUPLARI,
    ILISKI_TURLERI,
    ONCELIKLER,
    SERVIS_DURUMLARI,
    SERVIS_KATEGORILERI,
    SERVIS_SONUCLARI,
    TALEP_KANALLARI,
)
from app.permissions import SCOPE_OWN_JOBS
from app.services import settings as ayar_svc
from app.services.normalize import normalize_seri, tr_normkey
from app.services.statemachine import SERVIS_IS_EMRI, IzinsizGecis
from app.services.teknik_servis import (
    cihaz_bilgisi,
    gecmis,
    kancalar,
    kapsam,
    numara,
    role_montaj,
)
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_gun_araligi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User


class IsEmriHatasi(ServisHatasi):
    """Servis işi kural ihlali → 409."""


class IsEmriYetkiHatasi(ServisHatasi):
    """İşlem için gereken izin yok → API'de 403 (diğer API'lerde 409'a düşer).

    Uç kapısı (`require_permission`) çoğu durumu zaten keser; bu sınıf aynı
    servis fonksiyonunu iki farklı izinle çağıran yollar içindir (ör. açık
    işte `servis.yaz`, kapalı işte `servis.kapat` ile düzeltme).
    """


class IsEmriKapsamDisi(ServisHatasi):
    """Gövdedeki referans iş/hesap kullanıcının kapsamı dışında → API'de 404."""


@dataclass(frozen=True)
class TurKurali:
    """Tür → kategori ve tür kuralları (plan §1.7 `TUR_KURALLARI`).

    `seri_zorunlu`: açılışta en az bir seri ister. `azami_seri`: işte en çok
    bu kadar aktif seri olur (GUNLUK_SERVIS: 1 — "arıza işinde tek cihaz",
    M1.6; None = genel üst sınır `SERI_UST_SINIR`). `birim_kisiti`: yalnız bu
    birimlerde açılabilir (None = hepsi). `sla_olculur`: yalnız
    GUNLUK_SERVIS. `yalniz_sistem`: kullanıcı ekranından açılamaz (PB'yi
    yalnız bakım üretimi, ATOLYE'yi yalnız atölye kabulü açar) ve ekrandan
    bu türe/bu türden geçiş yapılamaz. `tek_seri`: işte tam bir seri olur
    (PB: 1 cihaz = 1 iş) ve seri değiştirilemez.
    """

    kategori: str
    seri_zorunlu: bool = False
    birim_kisiti: frozenset[str] | None = None
    sla_olculur: bool = False
    yalniz_sistem: bool = False
    tek_seri: bool = False
    azami_seri: int | None = None


# Kategori YALNIZ buradan türetilir (iş no önekinden tahmin yasak, E12-04).
# Birim kısıtı Dalga 1'de yok: her tür her birimde açılabilir (pilot GUVENLIK).
TUR_KURALLARI: dict[str, TurKurali] = {
    # M1.6 (Faz A): günlük servis işinde en çok bir cihaz; seri zorunlu değil.
    "ARIZA": TurKurali("GUNLUK_SERVIS", sla_olculur=True, azami_seri=1),
    "PLANSIZ_BAKIM": TurKurali("GUNLUK_SERVIS", sla_olculur=True, azami_seri=1),
    "DESTEK": TurKurali("GUNLUK_SERVIS", sla_olculur=True, azami_seri=1),
    "PB": TurKurali(
        "PLANLI_BAKIM", seri_zorunlu=True, yalniz_sistem=True, tek_seri=True, azami_seri=1
    ),
    "ATOLYE": TurKurali("ATOLYE", seri_zorunlu=True, yalniz_sistem=True),
    "KURULUM": TurKurali("PROJE"),
    "TOPLAMA": TurKurali("PROJE"),
    "KESIF": TurKurali("PROJE"),
    "DEMONTAJ": TurKurali("PROJE"),
    # KARARLAR 2026-11-04 §2 (Set Bariyer): KURULUM/TOPLAMA ile aynı kural —
    # PROJE kategorisi, SLA yok, seri zorunlu değil, birim kısıtı yok.
    "TASIMA": TurKurali("PROJE"),
    # KARARLAR 2026-11-09 S4.1: satıştan açılan teslimat işi (KURULUM kuralı).
    "TESLIMAT": TurKurali("PROJE"),
}

# Kaynak (uç/modül) → sürebileceği hedef durumlar. Makine "hangi geçiş var"ı,
# bu tablo "kim sürebilir"i söyler. TAMAMLANDI yalnız sonuç/uzaktan/atölye/
# bakım formu; KAPATILDI yalnız kapat; PLANLANDI yalnız planla/sayaç geri alma.
UC_HEDEFLERI: dict[str, frozenset[str]] = {
    "genel": frozenset({"PLANLAMADA", "YOLA_CIKILDI", "SAHADA", "ISLEMDE", "ATOLYEDE"}),
    "planla": frozenset({"PLANLANDI"}),
    "plan_geri_al": frozenset({"PLANLAMADA"}),
    # Tayin = iş verildi (2026-11-20): ekip gelince PLANLANDI, ekip boşalınca geri.
    "tayin": frozenset({"PLANLANDI", "PLANLAMADA"}),
    "sayac": frozenset({"YOLA_CIKILDI", "SAHADA", "PLANLANDI"}),
    "bekleme": frozenset(
        {
            "BEKLEMEDE",
            "MUSTERI_TALEBI",
            "PLANLAMADA",
            "PLANLANDI",
            "SAHADA",
            "ISLEMDE",
            "ATOLYEDE",
            "TEKRAR_ACILDI",
        }
    ),
    "sonuc": frozenset({"TAMAMLANDI"}),
    "uzaktan": frozenset({"TAMAMLANDI"}),
    "atolye": frozenset({"ATOLYEDE", "BEKLEMEDE", "TAMAMLANDI", "IPTAL"}),
    "bakim_formu": frozenset({"TAMAMLANDI"}),
    "kapsam_disi": frozenset({"IPTAL"}),
    "kapat": frozenset({"KAPATILDI"}),
    "iptal": frozenset({"IPTAL"}),
    "kiralama": frozenset({"IPTAL"}),
    # Kalite reddi: TAMAMLANDI → düzeltme durumu (rol testi tur 2, §7.3).
    "kalite_red": frozenset({"ISLEMDE", "PLANLAMADA"}),
    # Yönetici "yola çıkışı geri al" (rol testi tur 2, §7.4): YOLA_CIKILDI → PLANLANDI.
    "yola_cikis_geri_al": frozenset({"PLANLANDI"}),
}

# Hedef → ekranda kullanılacak uç (arayüz düğmeleri `gecis_secenekleri`'nden).
_HEDEF_UCU: dict[str, tuple[str, str]] = {
    "PLANLAMADA": ("genel", "servis.yaz"),
    "YOLA_CIKILDI": ("genel", "servis.yaz"),
    "SAHADA": ("genel", "servis.yaz"),
    "ISLEMDE": ("genel", "servis.yaz"),
    "ATOLYEDE": ("genel", "servis.yaz"),
    "PLANLANDI": ("planla", "servis.planla"),
    "BEKLEMEDE": ("bekleme", "servis.yaz"),
    "TAMAMLANDI": ("sonuc", "servis.tamamla"),
    "KAPATILDI": ("kapat", "servis.kapat"),
    "IPTAL": ("iptal", "servis.kapat"),
}

# Kaynak → kullanıcı çağırıyorsa gereken izin (worker/sistem çağrısında aranmaz).
_KAYNAK_IZNI: dict[str, str] = {
    "kapat": "servis.kapat",
    "iptal": "servis.kapat",
    "sonuc": "servis.tamamla",
    "uzaktan": "servis.uzaktan_coz",
    "kalite_red": "servis.kalite_onay",
    "yola_cikis_geri_al": "servis.planla",
}

# Gerekçesi zorunlu kaynaklar (iptal gerekçesi ayrıca `ck_so_iptal_gerekce`).
_GEREKCE_ZORUNLU = frozenset(
    {"iptal", "kapsam_disi", "kiralama", "kalite_red", "yola_cikis_geri_al"}
)

# M1.7 kullanıcı mesajı (API'nin eski `yeniden-ac` ucu da bunu döner).
YENIDEN_ACMA_YOK = "Kapanmış iş yeniden açılamaz; bu işe bağlı yeni iş açın"
# Bağlı yeni iş yalnız kapanmış işten açılır (açık işte mevcut iş sürdürülür).
BAGLI_IS_KAYNAK_DURUMLARI = DURUM_GRUPLARI["KAPALI"]

DURUM_ADLARI: dict[str, str] = {
    "MUSTERI_TALEBI": "Müşteri Talebi",
    "PLANLAMADA": "Planlamada",
    "PLANLANDI": "Planlandı",
    "YOLA_CIKILDI": "Yola Çıkıldı",
    "SAHADA": "Sahada",
    "ISLEMDE": "İşlemde",
    "ATOLYEDE": "Atölyede",
    "BEKLEMEDE": "Beklemede",
    "TAMAMLANDI": "Tamamlandı",
    "KAPATILDI": "Kapatıldı",
    "TEKRAR_ACILDI": "Tekrar Açıldı",
    "IPTAL": "İptal",
}
TUR_ADLARI: dict[str, str] = {
    "ARIZA": "Arıza",
    "PLANSIZ_BAKIM": "Bakım",
    "DESTEK": "Destek",
    "PB": "Planlı Bakım",
    "ATOLYE": "Atölye",
    "KURULUM": "Kurulum",
    "TOPLAMA": "Toplama",
    "KESIF": "Keşif",
    "DEMONTAJ": "Demontaj",
    "TASIMA": "Taşıma",
    "TESLIMAT": "Teslimat",
}
KATEGORI_ADLARI: dict[str, str] = {
    "GUNLUK_SERVIS": "Günlük Servis",
    "PLANLI_BAKIM": "Planlı Bakım",
    "ATOLYE": "Atölye",
    "PROJE": "Proje",
}
KANAL_ADLARI: dict[str, str] = {
    "TELEFON": "Telefon",
    "WHATSAPP": "WhatsApp",
    "EPOSTA": "E-posta",
    "SAHADA_BILDIRILDI": "Sahada bildirildi",
    "BAKIM_OTOMATIK": "Bakım (otomatik)",
    "DIGER": "Diğer",
}
ILISKI_ADLARI: dict[str, str] = {
    "MUKERRER": "Mükerrer",
    "TEKRAR_ARIZA": "Tekrar arıza",
    "DEVAM": "Devam",
    "BAKIM_BULGUSU": "Bakım bulgusu",
}
# Ekrandan seçilebilen ilişki türleri (BAKIM_BULGUSU yalnız bakım modülünden).
EKRAN_ILISKI_TURLERI = ("MUKERRER", "TEKRAR_ARIZA", "DEVAM")

# Bildirim anı en çok bu kadar geriye girilebilir (E01-09, plan TS-029).
BILDIRIM_GERIYE_GUN = 7
# Parametresiz liste: açık işler + son N günde kapananlar (E01-15).
LISTE_KAPALI_GUN = 90
# Düzeltilebilen temel alanlar (E01-13). `birim` YOK (400).
DUZELTILEBILIR = (
    "konu",
    "aciklama",
    "oncelik",
    "tur",
    # E01-16: kategori türden türetilir; yalnız `servis.kapat` gerekçeyle düzeltir.
    "kategori",
    "proje",
    "sistem",
    "nitelikler",
    "talep_kanali",
    "reported_at",
    "iletisim_ad",
    "iletisim_telefon",
    "customer_id",
    "address_id",
    "contact_id",
)
MUSTERI_ALANLARI = frozenset({"customer_id", "address_id", "contact_id"})
KISISEL_ALANLAR = frozenset({"iletisim_ad", "iletisim_telefon"})
SERI_UST_SINIR = 50


def tur_kategorisi(tur: str) -> str:
    """Kategori YALNIZ buradan türetilir (iş no önekinden tahmin yasak, E12)."""
    try:
        return TUR_KURALLARI[tur].kategori
    except KeyError:
        raise IsEmriHatasi(f"Bilinmeyen servis işi türü: {tur}") from None


def kapali_mi(so: ServiceOrder) -> bool:
    return so.status in DURUM_GRUPLARI["KAPALI"]


def seri_sayisi_dogrula(tur: str, seriler: list[str]) -> None:
    """Tür kuralının seri üst sınırı (M1.6). Eski çok cihazlı kayıtlar
    OKUNUR kalır; yalnız yeni yazım (açılış, seri değişikliği, tür geçişi)
    sınırı aşamaz → 400."""
    azami = TUR_KURALLARI[tur].azami_seri
    if azami is not None and len(seriler) > azami:
        raise ServisGirdiHatasi(
            f"'{TUR_ADLARI[tur]}' işinde en çok {azami} cihaz (seri numarası) olur; "
            "her cihaz için ayrı iş açın"
        )


@dataclass
class ServisIsiGirdisi:
    """Açılış girdisi (API şeması `api/teknik_servis.py IsAcIn`).

    Sistem açılışları (PB üretimi, atölye kabulü, kiralama) için ek alanlar
    sona eklenmiştir; ekran açılışı bunları göndermez.
    """

    birim: str
    tur: str
    konu: str
    customer_id: int
    address_id: int | None = None
    contact_id: int | None = None
    oncelik: str = "NORMAL"
    talep_kanali: str | None = None
    reported_at: datetime | None = None
    iletisim_ad: str | None = None
    iletisim_telefon: str | None = None
    proje: str | None = None
    sistem: str | None = None
    aciklama: str | None = None
    seriler: list[str] = field(default_factory=list)
    equipment_id: int | None = None
    iliskili_is_id: int | None = None
    iliski_turu: str | None = None
    # Geçiş/içe aktarma kaydı (rol testi B5): bildirim tarihi geriye sınırsız,
    # SLA damgalanmaz (`sla_kaynak=GECIS`, sonuç ÖLÇÜLEMEDİ). Yetki API'de.
    gecis_kaydi: bool = False
    # Haberleşme saha işinin niteliği (çoktan seçmeli; KARARLAR §10). Ekran
    # açılışında zorunlu (`nitelik_zorunlu`); sistem açılışında türden doldurulur.
    nitelikler: list[str] | None = None
    nitelik_zorunlu: bool = False
    # --- sistem açılışları (PB/atölye/kiralama) ---
    contract_item_id: int | None = None
    maintenance_period_id: int | None = None
    coverage_status: str | None = None
    coverage_snapshot: dict | None = None
    # Numaranın ay bilgisi (PB: dönemin hedef ayı); None = açılış anı.
    numara_tarihi: date | None = None


def _bos(deger: str | None) -> str | None:
    if deger is None:
        return None
    temiz = deger.strip()
    return temiz or None


def seri_listesi(seriler: list[str] | tuple[str, ...]) -> list[str]:
    """Boşları atar, `seri_norm`'a göre tekilleştirir (ilk yazım korunur)."""
    sonuc: list[str] = []
    gorulen: set[str] = set()
    for ham in seriler or ():
        temiz = (ham or "").strip()
        if not temiz:
            continue
        if len(temiz) > 200:
            raise ServisGirdiHatasi("Seri numarası en çok 200 karakter olabilir")
        anahtar = normalize_seri(temiz)
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        sonuc.append(temiz)
    if len(sonuc) > SERI_UST_SINIR:
        raise ServisGirdiHatasi(f"Bir işe en çok {SERI_UST_SINIR} seri girilebilir")
    return sonuc


def _bildirim_dogrula(reported_at: datetime | None, clock: Clock, *, geriye_sinir: bool) -> None:
    if reported_at is None:
        return
    if reported_at.tzinfo is None:
        raise ServisGirdiHatasi("Bildirim zamanı saat dilimi bilgisiyle girilmeli")
    simdi = clock.now()
    if reported_at > simdi + timedelta(minutes=5):
        raise ServisGirdiHatasi("Bildirim zamanı ileri bir tarih olamaz")
    if geriye_sinir and reported_at < simdi - timedelta(days=BILDIRIM_GERIYE_GUN):
        raise ServisGirdiHatasi(
            f"Bildirim zamanı en çok {BILDIRIM_GERIYE_GUN} gün geriye girilebilir"
        )


async def _musteri_dogrula(
    db: AsyncSession, customer_id: int | None, address_id: int | None, contact_id: int | None
) -> None:
    from app.services.teknik_servis import ana_veri

    try:
        await ana_veri.lokasyon_dogrula(db, customer_id, address_id, contact_id)
    except ana_veri.AnaVeriHatasi as exc:
        raise ServisGirdiHatasi(str(exc)) from exc


async def olustur(
    db: AsyncSession,
    girdi: ServisIsiGirdisi,
    *,
    user: User | None,
    clock: Clock,
    baslangic_durumu: str = "MUSTERI_TALEBI",
) -> ServiceOrder:
    """Servis işi açar (numara `numara.belge_no`, OLUSTUR olayı,
    `kancalar.is_olusturuldu`). PB/kiralama işleri `PLANLAMADA` doğar.

    Girdi hatası → `ServisGirdiHatasi` (400). Kapsam ve "yalnız sistem
    açar" türleri API'de denetlenir; bu fonksiyon worker'dan da çağrılır.
    """
    if baslangic_durumu not in SERVIS_IS_EMRI.baslangiclar:
        raise ValueError(f"Servis işi '{baslangic_durumu}' durumunda doğamaz")
    if girdi.birim not in BIRIM_KODLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {girdi.birim}")
    if girdi.tur not in TUR_KURALLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen servis işi türü: {girdi.tur}")
    kural = TUR_KURALLARI[girdi.tur]
    if kural.birim_kisiti is not None and girdi.birim not in kural.birim_kisiti:
        raise ServisGirdiHatasi(f"'{TUR_ADLARI[girdi.tur]}' bu birimde açılamaz")
    if girdi.oncelik not in ONCELIKLER:
        raise ServisGirdiHatasi(f"Bilinmeyen öncelik: {girdi.oncelik}")
    if girdi.talep_kanali is not None and girdi.talep_kanali not in TALEP_KANALLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen talep kanalı: {girdi.talep_kanali}")
    konu = _bos(girdi.konu)
    if konu is None:
        raise ServisGirdiHatasi("Konu boş olamaz")
    seriler = seri_listesi(girdi.seriler)
    if kural.seri_zorunlu and not seriler:
        raise ServisGirdiHatasi(f"'{TUR_ADLARI[girdi.tur]}' işinde seri numarası zorunlu")
    if kural.tek_seri and len(seriler) != 1:
        raise ServisGirdiHatasi(f"'{TUR_ADLARI[girdi.tur]}' işinde tam bir seri olur")
    seri_sayisi_dogrula(girdi.tur, seriler)
    _bildirim_dogrula(
        girdi.reported_at, clock, geriye_sinir=user is not None and not girdi.gecis_kaydi
    )
    await _musteri_dogrula(db, girdi.customer_id, girdi.address_id, girdi.contact_id)

    onek = "PB" if girdi.tur == "PB" else "SRV"
    so = ServiceOrder(
        so_no=await numara.belge_no(
            db, "service_order_no_seq", onek, girdi.numara_tarihi or clock.now()
        ),
        birim=girdi.birim,
        tur=girdi.tur,
        kategori=kural.kategori,
        oncelik=girdi.oncelik,
        status=baslangic_durumu,
        customer_id=girdi.customer_id,
        address_id=girdi.address_id,
        contact_id=girdi.contact_id,
        iletisim_ad=_bos(girdi.iletisim_ad),
        iletisim_telefon=_bos(girdi.iletisim_telefon),
        talep_kanali=girdi.talep_kanali,
        reported_at=girdi.reported_at,
        proje=_bos(girdi.proje),
        sistem=_bos(girdi.sistem),
        nitelikler=role_montaj.nitelik_dogrula(
            girdi.birim, girdi.tur, girdi.nitelikler, zorunlu=girdi.nitelik_zorunlu
        ),
        konu=konu,
        aciklama=_bos(girdi.aciklama),
        equipment_id=girdi.equipment_id,
        contract_item_id=girdi.contract_item_id,
        maintenance_period_id=girdi.maintenance_period_id,
        coverage_status=girdi.coverage_status,
        coverage_snapshot=girdi.coverage_snapshot,
        # GECIS: `sla.damgala` bu işi damgalamaz (hedef yok → ÖLÇÜLEMEDİ).
        sla_kaynak="GECIS" if girdi.gecis_kaydi else None,
        reopen_count=0,
        created_by=user.id if user is not None else None,
        updated_by=user.id if user is not None else None,
    )
    db.add(so)
    await db.flush()
    for seri in seriler:
        db.add(
            ServiceOrderSerial(
                service_order_id=so.id,
                seri_no=seri,
                seri_norm=normalize_seri(seri),
                created_by=user.id if user is not None else None,
            )
        )
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "OLUSTUR",
        f"Servis işi açıldı: {TUR_ADLARI[so.tur]} ({DURUM_ADLARI[so.status]})",
        user=user,
        clock=clock,
        yeni_durum=so.status,
        veri={
            "birim": so.birim,
            "tur": so.tur,
            "kategori": so.kategori,
            "oncelik": so.oncelik,
            "talep_kanali": so.talep_kanali,
            "seri_sayisi": len(seriler),
        },
    )
    if girdi.iliskili_is_id is not None or girdi.iliski_turu is not None:
        await iliski_kur(
            db,
            so,
            girdi.iliskili_is_id,
            girdi.iliski_turu,
            user=user,
            clock=clock,
            kapsam_user=user,
        )
    # Kütükten seri (Güvenlik) / kayıtlı frekans (Haberleşme) — KARARLAR §12.
    await cihaz_bilgisi.kutukten_doldur(db, so, user=user, clock=clock)
    await kancalar.is_olusturuldu(db, so, clock)
    await db.refresh(so, attribute_names=["seriler", "atamalar"])
    return so


# --- Tek durum kapısı (TS-021) ---------------------------------------------------


async def durum_degistir(
    db: AsyncSession,
    so: ServiceOrder,
    hedef: str,
    *,
    kaynak: str,
    user: User | None,
    clock: Clock,
    gerekce: str | None = None,
) -> ServiceOrder:
    """TEK durum geçiş kapısı (plan §1.7). `user` None = worker/sistem.

    Hatalar: makine/uç/kural ihlali `IsEmriHatasi` (409), izin
    `IsEmriYetkiHatasi` (403), eksik gerekçe `ServisGirdiHatasi` (400).
    Hiçbir hata yolunda kayda yazılmış bir şey kalmaz (kontroller yazmadan önce).
    """
    if kaynak not in UC_HEDEFLERI:
        raise ValueError(f"Bilinmeyen geçiş kaynağı: {kaynak}")
    if hedef not in SERVIS_DURUMLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen durum: {hedef}")
    if so.is_deleted:
        raise IsEmriHatasi("Silinmiş servis işinin durumu değiştirilemez")
    onceki = so.status
    try:
        SERVIS_IS_EMRI.dogrula(onceki, hedef)
    except IzinsizGecis:
        izinli = ", ".join(DURUM_ADLARI[d] for d in sorted(SERVIS_IS_EMRI.sonraki(onceki)))
        if onceki == hedef:
            raise IsEmriHatasi(f"İş zaten '{DURUM_ADLARI[hedef]}' durumunda") from None
        raise IsEmriHatasi(
            f"'{DURUM_ADLARI[onceki]}' durumundan '{DURUM_ADLARI[hedef]}' durumuna geçilemez. "
            f"İzin verilenler: {izinli or 'yok (terminal durum)'}"
        ) from None
    if hedef not in UC_HEDEFLERI[kaynak]:
        raise IsEmriHatasi(
            f"'{DURUM_ADLARI[hedef]}' durumuna bu işlemle geçilemez; ilgili işlemi kullanın"
        )
    # Tamamlanmış işten geri dönüş YALNIZ kalite reddiyle (makine kenarı tek kapıdan).
    if onceki == "TAMAMLANDI" and hedef != "KAPATILDI" and kaynak != "kalite_red":
        raise IsEmriHatasi(
            "Tamamlanmış iş yalnız kalite reddiyle düzeltmeye döner; "
            "kapanmış işin devamı için bağlı yeni iş açın"
        )
    if kaynak == "kalite_red" and onceki != "TAMAMLANDI":
        raise IsEmriHatasi("Kalite reddi yalnız tamamlanmış (kapatılmamış) işe uygulanır")
    if kaynak == "yola_cikis_geri_al" and onceki != "YOLA_CIKILDI":
        raise IsEmriHatasi("Yola çıkış yalnız 'Yola Çıkıldı' durumundaki işte geri alınır")
    # Bekleme kaynağı beklemeden ÇIKIŞ yalnız BEKLEMEDE'deki işte sürer.
    if kaynak == "bekleme" and hedef != "BEKLEMEDE" and onceki != "BEKLEMEDE":
        raise IsEmriHatasi("İş beklemede değil")
    # Beklemeden TEKRAR_ACILDI'ya yalnız `beklemeyi_bitir` döner.
    if hedef == "TEKRAR_ACILDI" and onceki == "BEKLEMEDE" and kaynak != "bekleme":
        raise IsEmriHatasi("Beklemedeki iş önce beklemeden çıkarılmalı")
    izin = _KAYNAK_IZNI.get(kaynak)
    if user is not None and izin is not None and not user.has(izin):
        raise IsEmriYetkiHatasi(f"Bu işlem için yetkiniz yok ({izin})")
    gerekce = _bos(gerekce)
    if kaynak in _GEREKCE_ZORUNLU and gerekce is None:
        raise ServisGirdiHatasi("Bu işlem için gerekçe zorunlu")
    if gerekce is not None and len(gerekce) > 500:
        raise ServisGirdiHatasi("Gerekçe en çok 500 karakter olabilir")

    if hedef == "KAPATILDI":
        await role_montaj.kapanis_dogrula(db, so)
        await cihaz_bilgisi.kapanis_dogrula(db, so)
    if hedef == "KAPATILDI" and user is not None:
        await kapanis_zinciri_dogrula(db, so, user)
    if hedef == "ISLEMDE" and kaynak == "genel" and user is not None:
        from app.services.teknik_servis import ulasim

        await ulasim.islem_dogrula(db, so)

    await kancalar.durum_dogrula(db, so, hedef, kaynak)

    simdi = clock.now()
    kimlik = user.id if user is not None else None
    if hedef == "TAMAMLANDI":
        so.completed_at = simdi
        so.completed_by = kimlik
        if so.first_completed_at is None:
            so.first_completed_at = simdi
    elif hedef == "KAPATILDI":
        so.closed_at = simdi
        so.closed_by = kimlik
    elif hedef == "IPTAL":
        so.cancelled_at = simdi
        so.cancelled_by = kimlik
        so.cancel_reason = gerekce
    so.status = hedef
    if kimlik is not None:
        so.updated_by = kimlik
    await db.flush()

    ozet = f"{DURUM_ADLARI[onceki]} → {DURUM_ADLARI[hedef]}"
    if gerekce:
        ozet += f" — gerekçe: {gerekce}"
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "DURUM",
            ozet,
            user=user,
            clock=clock,
            eski_durum=onceki,
            yeni_durum=hedef,
            veri={"kaynak": kaynak},
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Gerekçeye irtibat adı veya telefonu yazılamaz") from exc
    await kancalar.durum_degisti(db, so, onceki, hedef, kaynak, clock)
    return so


SON_ONAY_IZNI = "servis.son_onay"


async def kapanis_zinciri_dogrula(db: AsyncSession, so: ServiceOrder, user: User) -> None:
    """İki aşamalı kapanış (KARARLAR 2026-11-05 §9, `servis_kapanis_onay_zinciri`).

    Açıkken: teknisyen tamamlar → ekip lideri kalite onayı verir → teknik servis
    müdürü (`servis.son_onay`) son onayla kapatır. Sıra atlanamaz (409/403).
    Kapalıyken eski tek adımlı kapanış (`servis.kapat`) aynen sürer.
    """
    if not await ayar_svc.get(db, "servis_kapanis_onay_zinciri"):
        return
    if so.kalite_onay_at is None:
        raise IsEmriHatasi("Kapatmadan önce ekip liderinin onayı (kalite onayı) gerekli")
    if not user.has(SON_ONAY_IZNI):
        raise IsEmriYetkiHatasi(f"Son onay ve kapatma teknik servis müdüründedir ({SON_ONAY_IZNI})")


def sonraki_durumlar(so: ServiceOrder) -> list[str]:
    """Arayüze sunulacak geçerli hedefler (makine + uç kısıtı süzgeci).

    Beklemedeki işte TEKRAR_ACILDI ve diğer "geri dönüş" hedefleri yalnız
    `beklemeyi_bitir` ile olur; arayüz onları ayrı "Beklemeyi bitir"
    düğmesinden sunar, buradaki listede yer almaz.
    """
    hedefler = set(SERVIS_IS_EMRI.sonraki(so.status))
    if so.status == "BEKLEMEDE":
        hedefler &= {"IPTAL", "PLANLANDI", "SAHADA", "ISLEMDE", "ATOLYEDE", "PLANLAMADA"}
    if so.status == "TAMAMLANDI":
        # Kalite reddi kendi ucundan (`kalite-reddi`); genel geçiş düğmesi olmaz.
        hedefler &= {"KAPATILDI"}
    return [d for d in SERVIS_DURUMLARI if d in hedefler]


def gecis_secenekleri(so: ServiceOrder, user: User) -> list[dict[str, Any]]:
    """Her geçerli hedef için hangi uç ve izin; kullanıcının yetkisi var mı.

    Yola çıkılmış işte PLANLANDI'ya dönüş `yola-cikis-geri-al` ucudur (rol testi
    tur 2 Y6: eskiden "planla" vaat ediliyordu ama planla durumu değiştirmiyordu)."""
    sonuc = []
    for hedef in sonraki_durumlar(so):
        uc, izin = _HEDEF_UCU[hedef]
        if so.status == "YOLA_CIKILDI" and hedef == "PLANLANDI":
            uc, izin = "yola_cikis_geri_al", "servis.planla"
        sonuc.append(
            {"hedef": hedef, "ad": DURUM_ADLARI[hedef], "uc": uc, "yetkili": user.has(izin)}
        )
    return sonuc


# --- Temel bilgi / müşteri / seri düzeltme (TS-031) --------------------------------


def _deger_metni(deger: Any) -> Any:
    if isinstance(deger, datetime | date):
        return deger.isoformat()
    return deger


async def guncelle(
    db: AsyncSession, so: ServiceOrder, degisiklikler: dict, *, user: User, clock: Clock
) -> ServiceOrder:
    """Temel bilgi düzeltme (iyimser kilit; öncelik/birim değişince
    `kancalar.oncelik_birim_degisti`).

    `degisiklikler` içinde `version` (zorunlu) ve isteğe bağlı `gerekce`
    taşınır. Kurallar (E01-13, TS-031):
    - sürüm uyuşmazlığı 409; `birim` alanı 400; bilinmeyen alan 400;
    - KENDI_ISLERI kapsamlı (teknisyen) 403;
    - kapalı işte yalnız `servis.kapat` + gerekçe (403 / 400);
    - açık işte müşteri/lokasyon/irtibat düzeltmesi `servis.planla` (403);
    - PB işinde tür ve müşteri düzeltmesi 409; PB/ATOLYE'ye ya da bunlardan
      tür geçişi 409;
    - her değişiklik tek DUZELTME olayında (kişisel alanlarda yalnız alan adı).
    """
    degisiklikler = dict(degisiklikler)
    surum = degisiklikler.pop("version", None)
    gerekce = _bos(degisiklikler.pop("gerekce", None))
    if surum is None:
        raise ServisGirdiHatasi("Sürüm (version) zorunlu")
    if surum != so.version:
        raise IsEmriHatasi("Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin")
    if "birim" in degisiklikler:
        raise ServisGirdiHatasi("Servis işinin birimi değiştirilemez")
    bilinmeyen = set(degisiklikler) - set(DUZELTILEBILIR)
    if bilinmeyen:
        raise ServisGirdiHatasi(f"Düzeltilemeyen alan: {', '.join(sorted(bilinmeyen))}")
    if user.role is not None and user.role.scope == SCOPE_OWN_JOBS:
        raise IsEmriYetkiHatasi("Servis işinin temel bilgilerini teknisyen düzeltemez")

    # Yalnız gerçekten değişen alanlar.
    yeni: dict[str, Any] = {}
    for alan, deger in degisiklikler.items():
        if isinstance(deger, str):
            deger = _bos(deger)
        if getattr(so, alan) != deger:
            yeni[alan] = deger
    if not yeni:
        return so

    kapali = kapali_mi(so)
    if kapali:
        if not user.has("servis.kapat"):
            raise IsEmriYetkiHatasi("Kapalı işte düzeltme için yetkiniz yok (servis.kapat)")
        if gerekce is None:
            raise ServisGirdiHatasi("Kapalı işte düzeltme gerekçesi zorunlu")
    musteri_degisti = bool(MUSTERI_ALANLARI & set(yeni))
    if musteri_degisti and not kapali and not user.has("servis.planla"):
        raise IsEmriYetkiHatasi("Müşteri/lokasyon düzeltmesi için yetkiniz yok (servis.planla)")
    if so.tur == "PB" and (musteri_degisti or "tur" in yeni):
        raise IsEmriHatasi("Planlı bakım işinde tür ve müşteri/lokasyon düzeltilemez")
    if "tur" in yeni:
        hedef_tur = yeni["tur"]
        if hedef_tur not in TUR_KURALLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen servis işi türü: {hedef_tur}")
        if TUR_KURALLARI[hedef_tur].yalniz_sistem or TUR_KURALLARI[so.tur].yalniz_sistem:
            raise IsEmriHatasi(
                f"'{TUR_ADLARI[so.tur]}' → '{TUR_ADLARI[hedef_tur]}' tür geçişi yapılamaz"
            )
        seri_sayisi_dogrula(hedef_tur, [s.seri_no for s in await aktif_seriler(db, so)])
    if "kategori" in yeni:
        if not user.has("servis.kapat"):
            raise IsEmriYetkiHatasi("Kategori düzeltmesi için yetkiniz yok (servis.kapat)")
        if gerekce is None:
            raise ServisGirdiHatasi("Kategori düzeltmesi için gerekçe zorunlu")
        if yeni["kategori"] not in SERVIS_KATEGORILERI:
            raise ServisGirdiHatasi(f"Bilinmeyen kategori: {yeni['kategori']}")
        if so.tur == "PB" or yeni["kategori"] == "PLANLI_BAKIM":
            raise IsEmriHatasi("Planlı bakım kategorisi yalnız PB işine aittir; düzeltilemez")
    if "nitelikler" in yeni or "tur" in yeni:
        hedef_tur = yeni.get("tur", so.tur)
        eski = so.nitelikler if role_montaj.nitelik_sorulur_mu(so.birim, hedef_tur) else None
        yeni["nitelikler"] = role_montaj.nitelik_dogrula(
            so.birim, hedef_tur, yeni.get("nitelikler", eski), zorunlu="nitelikler" in yeni
        )
        if yeni["nitelikler"] == so.nitelikler:
            del yeni["nitelikler"]
    if "oncelik" in yeni and yeni["oncelik"] not in ONCELIKLER:
        raise ServisGirdiHatasi(f"Bilinmeyen öncelik: {yeni['oncelik']}")
    if "talep_kanali" in yeni and yeni["talep_kanali"] not in (None, *TALEP_KANALLARI):
        raise ServisGirdiHatasi(f"Bilinmeyen talep kanalı: {yeni['talep_kanali']}")
    if "konu" in yeni and yeni["konu"] is None:
        raise ServisGirdiHatasi("Konu boş olamaz")
    if "reported_at" in yeni:
        _bildirim_dogrula(yeni["reported_at"], clock, geriye_sinir=False)
    if musteri_degisti:
        hesap = yeni.get("customer_id", so.customer_id)
        adres = yeni.get("address_id", so.address_id)
        kisi = yeni.get("contact_id", so.contact_id)
        if "customer_id" in yeni:
            # Müşteri değişince eski lokasyon/irtibat yeni hesaba ait olamaz.
            adres = yeni.get("address_id") if "address_id" in yeni else None
            kisi = yeni.get("contact_id") if "contact_id" in yeni else None
            yeni["address_id"], yeni["contact_id"] = adres, kisi
        from app.services.accounts import kapsam_disinda_mi

        if hesap is not None and await kapsam_disinda_mi(db, user, hesap):
            raise IsEmriKapsamDisi("Müşteri bulunamadı")
        await _musteri_dogrula(db, hesap, adres, kisi)

    kayit = []
    for alan, deger in yeni.items():
        if alan in KISISEL_ALANLAR:
            kayit.append({"alan": alan})
        else:
            kayit.append(
                {"alan": alan, "eski": _deger_metni(getattr(so, alan)), "yeni": _deger_metni(deger)}
            )
        setattr(so, alan, deger)
    if "tur" in yeni and "kategori" not in yeni:
        eski_kategori = so.kategori
        so.kategori = tur_kategorisi(so.tur)
        if so.kategori != eski_kategori:
            kayit.append({"alan": "kategori", "eski": eski_kategori, "yeni": so.kategori})
    so.updated_by = user.id

    from app.services import audit

    await audit.log_change(
        db,
        so,
        "service_orders.duzelt",
        user_id=user.id,
        is_personal_data=bool(KISISEL_ALANLAR & set(yeni)),
    )
    await db.flush()
    ozet = "Temel bilgi düzeltildi: " + ", ".join(k["alan"] for k in kayit)
    if gerekce:
        ozet += f" — gerekçe: {gerekce}"
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "DUZELTME",
            ozet,
            user=user,
            clock=clock,
            veri={"alanlar": kayit, "kapali_iste": kapali},
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Gerekçeye irtibat adı veya telefonu yazılamaz") from exc
    # Öncelik ya da tür/kategori (SLA'nın ölçülüp ölçülmediği) değişince SLA
    # yeniden damgalanır (TS-081; birim bu uçta değiştirilemez). Dalga 2: Clock.
    if {"oncelik", "tur", "kategori"} & set(yeni):
        await kancalar.oncelik_birim_degisti(db, so, clock)
    return so


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


async def serileri_yaz(
    db: AsyncSession,
    so: ServiceOrder,
    seriler: list[str],
    *,
    user: User,
    clock: Clock,
    gerekce: str | None = None,
) -> list[ServiceOrderSerial]:
    """Seri listesini verilene eşitler; eski satır SİLİNMEZ, pasiflenir (E01-13).

    PB işinde seri değişikliği 409 (1 cihaz = 1 PB). Kapalı işte
    `servis.kapat` + gerekçe. Seri zorunlu türde liste boş olamaz. Teknisyen
    (KENDI_ISLERI) sahada gördüğü seriyi girebilir: seri, temel bilgiden
    farklı olarak saha verisidir.
    """
    kural = TUR_KURALLARI[so.tur]
    gerekce = _bos(gerekce)
    yeni_liste = seri_listesi(seriler)
    mevcut = await aktif_seriler(db, so)
    mevcut_norm = {s.seri_norm: s for s in mevcut}
    yeni_norm = {normalize_seri(s): s for s in yeni_liste}
    cikan = [s for n, s in mevcut_norm.items() if n not in yeni_norm]
    eklenen = [s for n, s in yeni_norm.items() if n not in mevcut_norm]
    if not cikan and not eklenen:
        return mevcut
    if kural.tek_seri:
        raise IsEmriHatasi("Planlı bakım işinde seri değiştirilemez (1 cihaz = 1 iş)")
    if kural.seri_zorunlu and not yeni_liste:
        raise ServisGirdiHatasi(f"'{TUR_ADLARI[so.tur]}' işinde seri numarası zorunlu")
    seri_sayisi_dogrula(so.tur, yeni_liste)
    kapali = kapali_mi(so)
    if kapali:
        if not user.has("servis.kapat"):
            raise IsEmriYetkiHatasi("Kapalı işte seri değişikliği için yetkiniz yok (servis.kapat)")
        if gerekce is None:
            raise ServisGirdiHatasi("Kapalı işte seri değişikliği gerekçesi zorunlu")
    simdi = clock.now()
    for satir in cikan:
        satir.is_active = False
        satir.removed_at = simdi
        satir.removed_by = user.id
    await db.flush()
    for seri in eklenen:
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
    ozet = f"Seri değişti: {len(eklenen)} eklendi, {len(cikan)} çıkarıldı"
    if gerekce:
        ozet += f" — gerekçe: {gerekce}"
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "SERI",
            ozet,
            user=user,
            clock=clock,
            veri={
                "eklenen": eklenen,
                "cikan": [s.seri_no for s in cikan],
                "kapali_iste": kapali,
            },
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Gerekçeye irtibat adı veya telefonu yazılamaz") from exc
    # Yeni seri kütükte varsa ekipman bağı ve kayıtlı frekans gelir (KARARLAR §12).
    await cihaz_bilgisi.kutukten_doldur(db, so, user=user, clock=clock)
    return await aktif_seriler(db, so)


# --- Bağlı iş (TS-030) ------------------------------------------------------------


async def iliski_kur(
    db: AsyncSession,
    so: ServiceOrder,
    iliskili_is_id: int | None,
    iliski_turu: str | None,
    *,
    user: User | None,
    clock: Clock,
    kapsam_user: User | None = None,
) -> ServiceOrder:
    """Tek üst bağ kurar/kaldırır (E01-11). İki taraf da ILISKI olayı alır.

    - bağ ve tür birlikte (biri boşsa 400); tür sözlükte (400);
    - kendine bağ 409 (`ck_so_kendine_bagli` son savunma);
    - hedef yok/silinmiş ya da `kapsam_user`'ın kapsamı dışında → kapsam dışı
      (API 404; kapsam dışı işin numarası hiçbir mesaja girmez);
    - döngü (hedefin üst zinciri bu işe dönüyor) 409.
    """
    if (iliskili_is_id is None) != (iliski_turu is None):
        raise ServisGirdiHatasi("Bağlı iş ve ilişki türü birlikte verilmeli")
    if iliski_turu is not None and iliski_turu not in ILISKI_TURLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen ilişki türü: {iliski_turu}")
    if iliskili_is_id == so.id:
        raise IsEmriHatasi("İş kendisine bağlanamaz")
    eski_id = so.iliskili_is_id
    if iliskili_is_id == eski_id and iliski_turu == so.iliski_turu:
        return so
    hedef: ServiceOrder | None = None
    if iliskili_is_id is not None:
        hedef = await db.get(ServiceOrder, iliskili_is_id)
        if hedef is None or hedef.is_deleted:
            raise IsEmriKapsamDisi("Bağlanacak iş bulunamadı")
        if kapsam_user is not None and await kapsam.is_erisimi_yok_mu(db, kapsam_user, hedef):
            raise IsEmriKapsamDisi("Bağlanacak iş bulunamadı")
        # Döngü: hedefin üst zinciri bu işe dönmemeli.
        adim, gorulen = hedef, {so.id}
        while adim is not None and adim.iliskili_is_id is not None:
            if adim.iliskili_is_id in gorulen:
                raise IsEmriHatasi("Bu bağ döngü oluşturur")
            gorulen.add(adim.iliskili_is_id)
            adim = await db.get(ServiceOrder, adim.iliskili_is_id)
    so.iliskili_is_id = iliskili_is_id
    so.iliski_turu = iliski_turu
    if user is not None:
        so.updated_by = user.id
    await db.flush()
    if hedef is not None:
        ad = ILISKI_ADLARI[iliski_turu or ""]
        await gecmis.olay_yaz(
            db,
            so,
            "ILISKI",
            f"Bağlı iş: {hedef.so_no} ({ad})",
            user=user,
            clock=clock,
            veri={"iliskili_is_id": hedef.id, "iliski_turu": iliski_turu, "yon": "ust"},
        )
        await gecmis.olay_yaz(
            db,
            hedef,
            "ILISKI",
            f"Bu işe bağlandı: {so.so_no} ({ad})",
            user=user,
            clock=clock,
            veri={"iliskili_is_id": so.id, "iliski_turu": iliski_turu, "yon": "alt"},
        )
    else:
        await gecmis.olay_yaz(
            db,
            so,
            "ILISKI",
            "Bağlı iş kaldırıldı",
            user=user,
            clock=clock,
            veri={"onceki_is_id": eski_id, "yon": "ust"},
        )
    return so


async def bagli_isler(db: AsyncSession, user: User, so: ServiceOrder) -> dict[str, Any]:
    """Üst bağ + bu işe bağlananlar. Kapsam dışı işin numarası MASKELİDİR."""

    async def _satir(diger: ServiceOrder, tur: str | None) -> dict[str, Any]:
        gizli = await kapsam.is_erisimi_yok_mu(db, user, diger)
        return {
            "id": None if gizli else diger.id,
            "so_no": "Kapsam dışı iş" if gizli else diger.so_no,
            "iliski_turu": tur,
            "status": None if gizli else diger.status,
            "kapsam_disi": gizli,
        }

    ust = None
    if so.iliskili_is_id is not None:
        hedef = await db.get(ServiceOrder, so.iliskili_is_id)
        if hedef is not None and not hedef.is_deleted:
            ust = await _satir(hedef, so.iliski_turu)
    altlar = (
        await db.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.iliskili_is_id == so.id, ServiceOrder.is_deleted.is_(False))
            .order_by(ServiceOrder.id)
        )
    ).all()
    # M1.7: kapanmış işin devamı zinciri (iki yön).
    onceki = None
    if so.onceki_is_id is not None:
        hedef = await db.get(ServiceOrder, so.onceki_is_id)
        if hedef is not None and not hedef.is_deleted:
            onceki = await _satir(hedef, None)
    sonrakiler = (
        await db.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.onceki_is_id == so.id, ServiceOrder.is_deleted.is_(False))
            .order_by(ServiceOrder.id)
        )
    ).all()
    return {
        "ust": ust,
        "alt": [await _satir(a, a.iliski_turu) for a in altlar],
        "onceki": onceki,
        "sonrakiler": [await _satir(a, None) for a in sonrakiler],
    }


# --- Bağlı yeni iş (M1.7, Faz A) -------------------------------------------------


def bagli_is_girdisi(onceki: ServiceOrder, seriler: list[str]) -> ServisIsiGirdisi:
    """Kapanmış işten yeni işin varsayılan girdisi: müşteri, lokasyon,
    irtibat, cihaz ve konu kopyalanır. Yalnız sistemin açtığı türlerin (PB,
    atölye) devamı ARIZA olarak açılır — ekrandan PB/atölye açılamaz."""
    tur = "ARIZA" if TUR_KURALLARI[onceki.tur].yalniz_sistem else onceki.tur
    return ServisIsiGirdisi(
        birim=onceki.birim,
        tur=tur,
        konu=onceki.konu,
        customer_id=onceki.customer_id,  # type: ignore[arg-type]
        address_id=onceki.address_id,
        contact_id=onceki.contact_id,
        oncelik=onceki.oncelik,
        talep_kanali=onceki.talep_kanali
        if onceki.talep_kanali not in (None, "BAKIM_OTOMATIK")
        else None,
        iletisim_ad=onceki.iletisim_ad,
        iletisim_telefon=onceki.iletisim_telefon,
        proje=onceki.proje,
        sistem=onceki.sistem,
        seriler=list(seriler),
        equipment_id=onceki.equipment_id,
    )


async def bagli_yeni_is(
    db: AsyncSession,
    onceki: ServiceOrder,
    girdi: ServisIsiGirdisi,
    *,
    user: User,
    clock: Clock,
) -> ServiceOrder:
    """Kapanmış işe bağlı YENİ iş açar (yeniden açma yerine, M1.7).

    Kaynak iş kapalı olmalı (TAMAMLANDI/KAPATILDI/IPTAL; açık işte 409 —
    mevcut iş sürdürülür). Yeni iş normal açılış kurallarıyla açılır
    (`olustur`), `onceki_is_id` ile öncekine bağlanır; iki iş de ILISKI olayı
    alır. Önceki işin durumu, sonucu ve SLA damgaları DEĞİŞMEZ.
    """
    if onceki.is_deleted:
        raise IsEmriHatasi("Silinmiş işe bağlı iş açılamaz")
    if onceki.status not in BAGLI_IS_KAYNAK_DURUMLARI:
        raise IsEmriHatasi(
            "İş henüz kapanmadı; bağlı yeni iş yalnız kapanmış işten açılır, "
            "açık işte mevcut iş sürdürülür"
        )
    so = await olustur(db, girdi, user=user, clock=clock)
    so.onceki_is_id = onceki.id
    so.updated_by = user.id
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "ILISKI",
        f"Kapanmış işin devamı olarak açıldı: {onceki.so_no}",
        user=user,
        clock=clock,
        veri={"onceki_is_id": onceki.id, "yon": "onceki"},
    )
    await gecmis.olay_yaz(
        db,
        onceki,
        "ILISKI",
        f"Bu işe bağlı yeni iş açıldı: {so.so_no}",
        user=user,
        clock=clock,
        veri={"sonraki_is_id": so.id, "yon": "sonraki"},
    )
    return so


# --- Kalite onayı (D3.4, G4.6; Faz A) --------------------------------------------

KALITE_IZNI = "servis.kalite_onay"
KALITE_DURUMLARI = DURUM_GRUPLARI["COZULDU"]
KALITE_SUZGECLERI = ("BEKLEYEN", "ONAYLI")


async def kalite_engeli(db: AsyncSession, so: ServiceOrder, user: User) -> str | None:
    """Görevler ayrılığı (G4.6): kullanıcı bu işte çalıştıysa engel metni.

    Çalışmış sayılan: işe teknisyen/stajyer olarak tayin edilmiş olmak
    (kaldırılmış tayin dahil), işte iptal edilmemiş süre kaydı olmak ya da
    sonucu girmiş olmak. Ekip liderinin ŞEF rolündeki tayini (müdür işi ekip
    liderine verir, lider planlar; KARARLAR 2026-11-05 §9) tek başına engel
    değildir: lider sahaya gittiyse süre kaydı onu zaten engeller.
    """
    tayinli = await db.scalar(
        select(
            exists().where(
                ServiceOrderAssignment.service_order_id == so.id,
                ServiceOrderAssignment.user_id == user.id,
                ServiceOrderAssignment.rol != "SEF",
            )
        )
    )
    if tayinli:
        return "Bu işe tayin edildiğiniz için kalite onayını veremezsiniz (görevler ayrılığı)"
    sureli = await db.scalar(
        select(
            exists().where(
                ServiceTimeEntry.service_order_id == so.id,
                ServiceTimeEntry.user_id == user.id,
                ServiceTimeEntry.is_deleted.is_(False),
            )
        )
    )
    if sureli:
        return "Bu işte süre kaydınız olduğu için kalite onayını veremezsiniz (görevler ayrılığı)"
    if so.completed_by is not None and so.completed_by == user.id:
        return "İşi siz tamamladığınız için kalite onayını veremezsiniz (görevler ayrılığı)"
    return None


async def kalite_durumu(db: AsyncSession, so: ServiceOrder, user: User) -> dict[str, Any]:
    """Detay ekranı için kalite onayı bilgisi ve düğme durumu."""
    engel: str | None = None
    if so.kalite_onay_at is not None:
        engel = "Kalite onayı verilmiş"
    elif so.status not in KALITE_DURUMLARI:
        engel = "Kalite onayı iş tamamlandıktan sonra verilir"
    elif not user.has(KALITE_IZNI):
        engel = f"Yetkiniz yok ({KALITE_IZNI})"
    else:
        engel = await kalite_engeli(db, so, user)
    ad = None
    if so.kalite_onaylayan_id is not None:
        from app.models import User as _User

        ad = await db.scalar(select(_User.full_name).where(_User.id == so.kalite_onaylayan_id))
    return {
        "onay_at": so.kalite_onay_at,
        "onaylayan": (
            {"id": so.kalite_onaylayan_id, "ad": ad} if so.kalite_onaylayan_id is not None else None
        ),
        "notu": so.kalite_notu,
        "bekliyor": so.kalite_onay_at is None and so.status in KALITE_DURUMLARI,
        "verebilir": engel is None,
        "engel": engel,
    }


async def kalite_onayla(
    db: AsyncSession,
    so: ServiceOrder,
    *,
    user: User,
    clock: Clock,
    version: int,
    notu: str | None = None,
) -> ServiceOrder:
    """Tamamlanan işe kalite onayı (yeni durum YOK; iş TAMAMLANDI/KAPATILDI kalır).

    Hatalar: sürüm uyuşmazlığı / tamamlanmamış iş / onay zaten var → 409;
    izin yok ya da görevler ayrılığı → 403; not 500 karakteri aşarsa 400.
    """
    if version != so.version:
        raise IsEmriHatasi("Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin")
    if not user.has(KALITE_IZNI):
        raise IsEmriYetkiHatasi(f"Kalite onayı için yetkiniz yok ({KALITE_IZNI})")
    if so.is_deleted:
        raise IsEmriHatasi("Silinmiş işe kalite onayı verilemez")
    if so.status not in KALITE_DURUMLARI:
        raise IsEmriHatasi("Kalite onayı yalnız tamamlanmış ya da kapatılmış işe verilir")
    if so.kalite_onay_at is not None:
        raise IsEmriHatasi("Bu işin kalite onayı zaten verilmiş")
    engel = await kalite_engeli(db, so, user)
    if engel is not None:
        raise IsEmriYetkiHatasi(engel)
    notu = _bos(notu)
    if notu is not None and len(notu) > 500:
        raise ServisGirdiHatasi("Kalite notu en çok 500 karakter olabilir")
    so.kalite_onay_at = clock.now()
    so.kalite_onaylayan_id = user.id
    so.kalite_notu = notu
    so.updated_by = user.id
    await db.flush()
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "KALITE",
            "Kalite onayı verildi" + (f" — not: {notu}" if notu else ""),
            user=user,
            clock=clock,
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Kalite notuna irtibat adı veya telefonu yazılamaz") from exc
    return so


# --- Kalite reddi (rol testi tur 2 Y5, KARARLAR 2026-11-04 §7.3) -------------------

KALITE_RED_HEDEFLERI = ("ISLEMDE", "PLANLAMADA")
KALITE_RED_GEREKCE_ASGARI = 10


async def kalite_reddet(
    db: AsyncSession,
    so: ServiceOrder,
    *,
    user: User,
    clock: Clock,
    version: int,
    gerekce: str | None,
    hedef: str = "PLANLAMADA",
) -> ServiceOrder:
    """Tamamlanmış işin kalitesini reddeder ve işi düzeltmeye geri alır.

    `hedef`: ISLEMDE (kayıt/sonuç düzeltmesi, yeniden ziyaret yok) ya da
    PLANLAMADA (yeniden ziyaret planlanacak). Geçerli sonuç geçersiz kılınır
    (`sonuc` kancası), bakım formu varsa TASLAK'a döner ve YENIDEN_ACMA ziyaret
    satırı yazılır (`bakim_formu` kancası). SLA ilk tamamlanmada dondurulduğu
    için değişmez. Kurallar: gerekçe ≥10 karakter (400); `servis.kalite_onay`
    ve görevler ayrılığı (403, onayla aynı); sürüm, tamamlanmamış/kapatılmış
    iş, verilmiş kalite onayı, faturaya iletilmiş iş ve atölye işi 409.
    """
    if version != so.version:
        raise IsEmriHatasi("Kayıt başka biri tarafından değiştirildi; sayfayı yenileyin")
    if not user.has(KALITE_IZNI):
        raise IsEmriYetkiHatasi(f"Kalite reddi için yetkiniz yok ({KALITE_IZNI})")
    if so.is_deleted:
        raise IsEmriHatasi("Silinmiş işin kalitesi reddedilemez")
    if hedef not in KALITE_RED_HEDEFLERI:
        raise ServisGirdiHatasi(f"Geçersiz dönüş durumu: {hedef} (İşlemde ya da Planlamada)")
    gerekce = _bos(gerekce)
    if gerekce is None or len(gerekce) < KALITE_RED_GEREKCE_ASGARI:
        raise ServisGirdiHatasi(
            f"Kalite reddinde gerekçe zorunlu (en az {KALITE_RED_GEREKCE_ASGARI} karakter)"
        )
    if len(gerekce) > 500:
        raise ServisGirdiHatasi("Gerekçe en çok 500 karakter olabilir")
    if so.status != "TAMAMLANDI":
        raise IsEmriHatasi(
            "Kalite reddi yalnız tamamlanmış ve henüz kapatılmamış işe verilir; "
            "kapatılmış işte bağlı yeni iş açın"
        )
    if so.kalite_onay_at is not None:
        raise IsEmriHatasi("Bu işin kalite onayı verilmiş; reddedilemez")
    if so.kategori == "ATOLYE":
        raise IsEmriHatasi(
            "Atölye işinin kalitesi atölye kaydından düzeltilir (teslime hazır → onarımda "
            "geri alma); kapanmışsa bağlı yeni iş açın"
        )
    engel = await kalite_engeli(db, so, user)
    if engel is not None:
        raise IsEmriYetkiHatasi(
            engel.replace("kalite onayını veremezsiniz", "kaliteyi reddedemezsiniz")
        )
    from app.models.servis_maliyet import ServiceOrderFinancial

    iletildi = await db.scalar(
        select(ServiceOrderFinancial.fatura_iletildi_at).where(
            ServiceOrderFinancial.service_order_id == so.id
        )
    )
    if iletildi is not None:
        raise IsEmriHatasi("İş faturaya iletilmiş; önce fatura devrini geri alın")
    await durum_degistir(
        db, so, hedef, kaynak="kalite_red", user=user, clock=clock, gerekce=gerekce
    )
    so.kalite_red_at = clock.now()
    so.kalite_red_by = user.id
    so.kalite_red_gerekcesi = gerekce
    so.updated_by = user.id
    await db.flush()
    try:
        await gecmis.olay_yaz(
            db,
            so,
            "KALITE",
            f"Kalite onayı reddedildi, iş {DURUM_ADLARI[hedef]} durumuna döndü — "
            f"gerekçe: {gerekce}",
            user=user,
            clock=clock,
            veri={"karar": "RED", "hedef": hedef},
        )
    except gecmis.KisiselVeriHatasi as exc:
        raise ServisGirdiHatasi("Gerekçeye irtibat adı veya telefonu yazılamaz") from exc
    return so


def kalite_kosulu(suzgec: str) -> Any:
    """Liste süzgeci: BEKLEYEN = tamamlanmış/kapatılmış, onaysız ve göç
    kaydı olmayan iş (eski sistemden gelen kapalı işler onay kuyruğunu
    doldurmasın); ONAYLI = kalite onayı verilmiş iş."""
    if suzgec == "ONAYLI":
        return ServiceOrder.kalite_onay_at.is_not(None)
    return and_(
        ServiceOrder.status.in_(sorted(KALITE_DURUMLARI)),
        ServiceOrder.kalite_onay_at.is_(None),
        ServiceOrder.source_system.is_(None),
    )


# --- Mükerrer kontrolü (TS-029) ----------------------------------------------------


async def mukerrer_adaylari(
    db: AsyncSession,
    user: User,
    seriler: list[str],
    *,
    haric_id: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Açık işte aynı `seri_norm`. (kapsam içi işler, kapsam dışında da var mı).

    Kapsam dışı mükerrerin numarası verilmez (sayı da sızmasın diye yalnız
    "başka kayıt var" bayrağı döner).
    """
    normlar = sorted({normalize_seri(s) for s in seri_listesi(seriler)})
    if not normlar:
        return [], False
    stmt = (
        select(ServiceOrder)
        .where(
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
            exists().where(
                ServiceOrderSerial.service_order_id == ServiceOrder.id,
                ServiceOrderSerial.is_active.is_(True),
                ServiceOrderSerial.seri_norm.in_(normlar),
            ),
        )
        .order_by(ServiceOrder.id)
    )
    if haric_id is not None:
        stmt = stmt.where(ServiceOrder.id != haric_id)
    hepsi = (await db.scalars(stmt)).all()
    ici = (await db.scalars(kapsam.kapsam_isler(stmt, user, ServiceOrder.id))).all()
    ici_idler = {s.id for s in ici}
    return (
        [{"id": s.id, "so_no": s.so_no, "status": s.status, "birim": s.birim} for s in ici],
        any(s.id not in ici_idler for s in hepsi),
    )


def tayinsiz_is_kosulu() -> ColumnElement[bool]:
    """ "Tayin edilmemiş iş" TEK tanımı (rol testi B1; liste, KPI, panel aynı).

    Tayinli sayılan iş: aktif TEKNISYEN tayini VEYA aktif sorumlu (teknisyen
    ya da şef) VEYA sahaya giden en az bir kişisi olan aktif plan. Yalnız
    şefin sahaya gittiği planlı iş (Set Bariyer) böylece tayinli sayılır;
    listede "TAYİN EDİLDİ" (PLANLANDI) görünen iş KPI'da "tayin edilmemiş"
    sayılmaz. Sahaya gitmeyen, sorumlu olmayan şef tek başına tayin değildir.
    """
    tayinli = exists().where(
        ServiceOrderAssignment.service_order_id == ServiceOrder.id,
        ServiceOrderAssignment.removed_at.is_(None),
        or_(
            ServiceOrderAssignment.rol == "TEKNISYEN",
            ServiceOrderAssignment.is_lead.is_(True),
        ),
    )
    sahada_planli = exists().where(
        ServicePlan.service_order_id == ServiceOrder.id,
        ServicePlan.is_active.is_(True),
        ServicePlan.is_deleted.is_(False),
        ServicePlanMember.plan_id == ServicePlan.id,
        ServicePlanMember.sahaya_gidiyor.is_(True),
    )
    return not_(or_(tayinli, sahada_planli))


async def ayni_lokasyon_acik_isler(
    db: AsyncSession,
    user: User,
    customer_id: int | None,
    address_id: int | None,
    *,
    haric_id: int | None = None,
) -> list[dict[str, Any]]:
    """Aynı müşteri + lokasyonda açık işler (yalnız UYARI, engel değil)."""
    if customer_id is None:
        return []
    stmt = select(ServiceOrder).where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
        ServiceOrder.customer_id == customer_id,
    )
    if address_id is not None:
        stmt = stmt.where(ServiceOrder.address_id == address_id)
    if haric_id is not None:
        stmt = stmt.where(ServiceOrder.id != haric_id)
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id).order_by(ServiceOrder.id).limit(20)
    return [
        {"id": s.id, "so_no": s.so_no, "status": s.status, "konu": s.konu}
        for s in (await db.scalars(stmt)).all()
    ]


# --- Liste sorgusu (TS-026) ----------------------------------------------------------


@dataclass
class ListeFiltresi:
    """Liste, Excel ve KPI için TEK süzgeç (E01-15). Kapsam her zaman uygulanır."""

    birim: str | None = None
    kategori: str | None = None
    tur: str | None = None
    durum: list[str] = field(default_factory=list)
    durum_grubu: str | None = None
    oncelik: str | None = None
    musteri_id: int | None = None
    adres_id: int | None = None
    teknisyen_id: int | None = None
    atanmamis: bool = False
    bas: date | None = None
    bit: date | None = None
    q: str | None = None
    kapali_dahil: bool = False
    kpi: str | None = None
    donem: str | None = None
    siralama: str = "yeni"
    # Faz A: "kalite onayı bekleyenler" (BEKLEYEN) / onaylılar (ONAYLI).
    kalite: str | None = None
    # Ana Panel (2026-11-04 §4): aktif ŞEF tayini olan işler (`teknisyen_id`
    # rol ayırmaz; şef süzgeci yalnız SEF rolüne bakar).
    sef_id: int | None = None
    # Rol testi tur 2 (6_satis O11): geçerli sonucu bu olan işler (ör.
    # `TEKLIF_SUNULACAK` = satış destek "teklif hazırlanacak" listesi).
    sonuc: str | None = None


SIRALAMALAR = ("yeni", "eski", "oncelik", "no")
_ONCELIK_SIRASI = {"KRITIK": 0, "YUKSEK": 1, "NORMAL": 2}


def _filtre_dogrula(f: ListeFiltresi) -> None:
    if f.birim is not None and f.birim not in BIRIM_KODLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {f.birim}")
    if f.kategori is not None and f.kategori not in SERVIS_KATEGORILERI:
        raise ServisGirdiHatasi(f"Bilinmeyen kategori: {f.kategori}")
    if f.tur is not None and f.tur not in TUR_KURALLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen tür: {f.tur}")
    bilinmeyen = [d for d in f.durum if d not in SERVIS_DURUMLARI]
    if bilinmeyen:
        raise ServisGirdiHatasi(f"Bilinmeyen durum: {', '.join(bilinmeyen)}")
    if f.durum_grubu is not None and f.durum_grubu not in DURUM_GRUPLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen durum grubu: {f.durum_grubu}")
    if f.oncelik is not None and f.oncelik not in ONCELIKLER:
        raise ServisGirdiHatasi(f"Bilinmeyen öncelik: {f.oncelik}")
    if f.siralama not in SIRALAMALAR:
        raise ServisGirdiHatasi(f"Bilinmeyen sıralama: {f.siralama}")
    if f.kalite is not None and f.kalite not in KALITE_SUZGECLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen kalite süzgeci: {f.kalite}")
    if f.sonuc is not None and f.sonuc not in SERVIS_SONUCLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen sonuç: {f.sonuc}")
    if f.bas is not None and f.bit is not None and f.bit < f.bas:
        raise ServisGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")


def liste_sorgusu(user: User, f: ListeFiltresi, clock: Clock) -> Select:
    """Servis işi listesi — liste ucu, Excel ve KPI aynı sorguyu kullanır.

    Kapsam SQL'de uygulanır (`kapsam.kapsam_isler`). Parametresiz çağrı açık
    işleri + son `LISTE_KAPALI_GUN` günde kapananları döndürür; durum, durum
    grubu, KPI ya da `kapali_dahil` verilirse bu varsayılan uygulanmaz.
    """
    _filtre_dogrula(f)
    stmt = select(ServiceOrder).where(ServiceOrder.is_deleted.is_(False))
    stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
    if f.birim:
        stmt = stmt.where(ServiceOrder.birim == f.birim)
    if f.kategori:
        stmt = stmt.where(ServiceOrder.kategori == f.kategori)
    if f.tur:
        stmt = stmt.where(ServiceOrder.tur == f.tur)
    if f.durum:
        stmt = stmt.where(ServiceOrder.status.in_(f.durum))
    if f.durum_grubu:
        stmt = stmt.where(ServiceOrder.status.in_(sorted(DURUM_GRUPLARI[f.durum_grubu])))
    if f.oncelik:
        stmt = stmt.where(ServiceOrder.oncelik == f.oncelik)
    if f.musteri_id is not None:
        stmt = stmt.where(ServiceOrder.customer_id == f.musteri_id)
    if f.adres_id is not None:
        stmt = stmt.where(ServiceOrder.address_id == f.adres_id)
    if f.teknisyen_id is not None:
        stmt = stmt.where(
            exists().where(
                ServiceOrderAssignment.service_order_id == ServiceOrder.id,
                ServiceOrderAssignment.user_id == f.teknisyen_id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    if f.sef_id is not None:
        stmt = stmt.where(
            exists().where(
                ServiceOrderAssignment.service_order_id == ServiceOrder.id,
                ServiceOrderAssignment.user_id == f.sef_id,
                ServiceOrderAssignment.rol == "SEF",
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    if f.atanmamis:
        stmt = stmt.where(tayinsiz_is_kosulu())
    if f.sonuc:
        stmt = stmt.where(
            exists().where(
                ServiceResult.service_order_id == ServiceOrder.id,
                ServiceResult.gecersiz_at.is_(None),
                ServiceResult.sonuc == f.sonuc,
            )
        )
    if f.bas is not None:
        stmt = stmt.where(ServiceOrder.created_at >= yerel_gun_araligi(f.bas)[0])
    if f.bit is not None:
        stmt = stmt.where(ServiceOrder.created_at < yerel_gun_araligi(f.bit)[1])
    q = _bos(f.q)
    if q:
        desen = f"%{q}%"
        seri_desen = f"%{normalize_seri(q)}%"
        anahtar = tr_normkey(q)
        stmt = stmt.where(
            or_(
                ServiceOrder.so_no.ilike(desen),
                ServiceOrder.konu.ilike(desen),
                exists().where(
                    ServiceOrderSerial.service_order_id == ServiceOrder.id,
                    ServiceOrderSerial.is_active.is_(True),
                    ServiceOrderSerial.seri_norm.like(seri_desen),
                ),
                exists().where(
                    Account.id == ServiceOrder.customer_id,
                    or_(Account.title.ilike(desen), Account.title_key.contains(anahtar))
                    if anahtar
                    else Account.title.ilike(desen),
                ),
            )
        )
    if f.kpi:
        from app.services.teknik_servis import panel

        stmt = panel.kpi_uygula(stmt, f.kpi, user=user, clock=clock, donem=f.donem)
    if f.kalite:
        stmt = stmt.where(kalite_kosulu(f.kalite))
    varsayilan = not (f.durum or f.durum_grubu or f.kpi or f.kapali_dahil or f.kalite)
    if varsayilan:
        sinir = clock.now() - timedelta(days=LISTE_KAPALI_GUN)
        kapanis = func.coalesce(
            ServiceOrder.closed_at, ServiceOrder.cancelled_at, ServiceOrder.completed_at
        )
        stmt = stmt.where(
            or_(
                ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
                and_(
                    ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["KAPALI"])),
                    kapanis >= sinir,
                ),
            )
        )
    if f.siralama == "eski":
        stmt = stmt.order_by(ServiceOrder.created_at.asc())
    elif f.siralama == "no":
        stmt = stmt.order_by(ServiceOrder.so_no.asc())
    elif f.siralama == "oncelik":
        from sqlalchemy import case

        stmt = stmt.order_by(
            case(_ONCELIK_SIRASI, value=ServiceOrder.oncelik, else_=9),
            ServiceOrder.created_at.desc(),
        )
    else:
        stmt = stmt.order_by(ServiceOrder.created_at.desc())
    return stmt


async def aktif_bekleme_nedenleri(db: AsyncSession, so_idler: list[int]) -> dict[int, str]:
    """İş → aktif bekleme nedeni kodu (liste satırı için tek sorgu)."""
    if not so_idler:
        return {}
    satirlar = await db.execute(
        select(ServiceHold.service_order_id, ServiceHold.neden).where(
            ServiceHold.service_order_id.in_(so_idler), ServiceHold.released_at.is_(None)
        )
    )
    return {so_id: neden for so_id, neden in satirlar.all()}


async def lokasyon_ozetleri(db: AsyncSession, adres_idler: set[int]) -> dict[int, dict[str, Any]]:
    if not adres_idler:
        return {}
    adresler = (await db.scalars(select(Address).where(Address.id.in_(adres_idler)))).all()
    return {a.id: {"id": a.id, "ad": a.site_name or a.label, "il": a.city} for a in adresler}


async def musteri_ozetleri(db: AsyncSession, hesap_idler: set[int]) -> dict[int, dict[str, Any]]:
    if not hesap_idler:
        return {}
    satirlar = await db.execute(
        select(Account.id, Account.title).where(Account.id.in_(hesap_idler))
    )
    return {i: {"id": i, "title": t} for i, t in satirlar.all()}


def bos_sorgu() -> Select:
    """Kapsam dışı/boş sonuç için yardımcı."""
    return select(ServiceOrder).where(false())


# --- Seri → mobilite cihaz kütüğü bağı (TS-193, E01-10; D3-C — YALNIZ OKUMA) ----------
#
# MOBILITE / ARAC_TAKIP işlerinde seri, canlı `devices` kütüğüyle IMEI ya da
# seri no üzerinden eşleşir. Eşleşme OKUMA ANINDA kurulur: `devices`'a ve
# `service_order_serials.device_id`'ye HİÇBİR ŞEY YAZILMAZ (cihaz durum
# makinesi, `uq_devices_seri` ve mobilite stok raporları etkilenmez). Güvenlik,
# Haberleşme ve POC işleri cihaz kütüğüne bakmaz (bağları `service_equipment`).
# Kurallar (E01 kontrol): IMEI aynen (`devices.imei` 15 hane, normalize
# edilmiş saklanır), seri `upper(trim(devices.serial_no))` = `seri_norm`.

CIHAZ_KUTUGU_BIRIMLERI = ("MOBILITE", "ARAC_TAKIP")


def _cihaz_seri_kosulu(cihaz_tablosu, seri_sutunu) -> Any:
    """Bir `service_order_serials` satırının bir cihaza eşleşme koşulu."""
    return or_(
        cihaz_tablosu.imei == seri_sutunu,
        func.upper(func.trim(cihaz_tablosu.serial_no)) == seri_sutunu,
    )


def _cihaz_anahtarlari(imei: str | None, seri: str | None) -> list[str]:
    anahtarlar = []
    if imei:
        anahtarlar.append(imei.strip())
    if seri and seri.strip():
        anahtarlar.append(seri.strip().upper())
    return anahtarlar


def cihaz_servis_isleri_sorgusu(user: User, imei: str | None, seri: str | None) -> Select:
    """Bir mobilite cihazının servis işleri (kapsamla). Cihaz kartının
    "Servis İşleri" sekmesi ve sayısı aynı sorgudan gelir."""
    anahtarlar = _cihaz_anahtarlari(imei, seri)
    if not anahtarlar:
        return bos_sorgu()
    stmt = select(ServiceOrder).where(
        ServiceOrder.is_deleted.is_(False),
        ServiceOrder.birim.in_(CIHAZ_KUTUGU_BIRIMLERI),
        exists().where(
            ServiceOrderSerial.service_order_id == ServiceOrder.id,
            ServiceOrderSerial.is_active.is_(True),
            ServiceOrderSerial.seri_norm.in_(anahtarlar),
        ),
    )
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id).order_by(ServiceOrder.created_at.desc())


async def seri_cihaz_eslesmeleri(db: AsyncSession, so: ServiceOrder) -> list[dict[str, Any]]:
    """İşin her aktif serisi için cihaz kütüğü eşleşmesi: `cihaz_id` ya da
    `None` ("kütükte yok"). Birim MOBILITE/ARAC_TAKIP değilse boş liste."""
    from app.models import Device

    if so.birim not in CIHAZ_KUTUGU_BIRIMLERI:
        return []
    seriler = (
        await db.scalars(
            select(ServiceOrderSerial)
            .where(
                ServiceOrderSerial.service_order_id == so.id,
                ServiceOrderSerial.is_active.is_(True),
            )
            .order_by(ServiceOrderSerial.id)
        )
    ).all()
    sonuc = []
    for s in seriler:
        cihazlar = (
            await db.execute(
                select(Device.id, Device.imei, Device.serial_no)
                .where(Device.is_deleted.is_(False), _cihaz_seri_kosulu(Device, s.seri_norm))
                .order_by(Device.id)
                .limit(2)
            )
        ).all()
        tek = cihazlar[0] if len(cihazlar) == 1 else None
        sonuc.append(
            {
                "seri_id": s.id,
                "seri_no": s.seri_no,
                "cihaz_id": tek.id if tek else None,
                "imei": tek.imei if tek else None,
                "durum": "TEK" if tek else ("BELIRSIZ" if cihazlar else "KUTUKTE_YOK"),
            }
        )
    return sonuc


def kutukte_olmayan_seri_kosulu() -> Any:
    """MOBILITE/ARAC_TAKIP işinde cihaz kütüğünde karşılığı olmayan aktif seri
    var mı (rapor: `kutukte_olmayan_seriler`; kayıt engellenmez)."""
    from sqlalchemy.orm import aliased

    from app.models import Device

    cihaz = aliased(Device)
    return and_(
        ServiceOrder.birim.in_(CIHAZ_KUTUGU_BIRIMLERI),
        exists().where(
            ServiceOrderSerial.service_order_id == ServiceOrder.id,
            ServiceOrderSerial.is_active.is_(True),
            ~exists().where(
                cihaz.is_deleted.is_(False),
                _cihaz_seri_kosulu(cihaz, ServiceOrderSerial.seri_norm),
            ),
        ),
    )
