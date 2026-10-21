"""Servis işi: açılış, güncelleme ve TEK durum geçiş kapısı (E01-02/03, TS-020/021).

İSKELET (D0-S) — uygulama D1-B paketinindir. İmzalar plan §1.7/§1.8'de
sabittir; Dalga 1'in diğer paketleri (D1-D/F/G) bu imzalara yazar.

Durum geçişi YALNIZ `durum_degistir` ile yapılır:
1. `SERVIS_IS_EMRI.dogrula(onceki, hedef)` (aynı durum → 409);
2. `kaynak` `UC_HEDEFLERI`'nde ve hedef o kaynağın kümesinde olmalı;
3. `kancalar.durum_dogrula` (PB koruması, atölye, açık sayaç → 409);
4. damgalar (TAMAMLANDI → `completed_at`, ilk seferde `first_completed_at`
   — TEKRAR_ACILDI'da SİLİNMEZ; KAPATILDI → `closed_at`; IPTAL →
   `cancelled_at` + gerekçe; TEKRAR_ACILDI → `reopen_count + 1`);
5. DURUM olayı (`gecmis.olay_yaz`) + `kancalar.durum_degisti`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from app.services.teknik_servis.kancalar import ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, User


class IsEmriHatasi(ServisHatasi):
    """Servis işi kural ihlali → 409."""


@dataclass(frozen=True)
class TurKurali:
    """Tür → kategori ve tür kuralları (plan §1.7 `TUR_KURALLARI`).

    `seri_zorunlu`: açılışta en az bir seri ister. `birim_kisiti`: yalnız bu
    birimlerde açılabilir (None = hepsi). `sla_olculur`: yalnız
    GUNLUK_SERVIS. `yalniz_sistem`: kullanıcı ekranından açılamaz (PB'yi
    yalnız bakım üretimi, ATOLYE'yi yalnız atölye kabulü açar).
    """

    kategori: str
    seri_zorunlu: bool = False
    birim_kisiti: frozenset[str] | None = None
    sla_olculur: bool = False
    yalniz_sistem: bool = False


# D1-B `seri_zorunlu`/`birim_kisiti` değerlerini kesinleştirir; kategori ve
# SLA eşlemesi plan §1.7'de sabittir.
TUR_KURALLARI: dict[str, TurKurali] = {
    "ARIZA": TurKurali("GUNLUK_SERVIS", sla_olculur=True),
    "PLANSIZ_BAKIM": TurKurali("GUNLUK_SERVIS", sla_olculur=True),
    "DESTEK": TurKurali("GUNLUK_SERVIS", sla_olculur=True),
    "PB": TurKurali("PLANLI_BAKIM", seri_zorunlu=True, yalniz_sistem=True),
    "ATOLYE": TurKurali("ATOLYE", seri_zorunlu=True, yalniz_sistem=True),
    "KURULUM": TurKurali("PROJE"),
    "TOPLAMA": TurKurali("PROJE"),
    "KESIF": TurKurali("PROJE"),
    "DEMONTAJ": TurKurali("PROJE"),
}

# Kaynak (uç/modül) → sürebileceği hedef durumlar. Makine "hangi geçiş var"ı,
# bu tablo "kim sürebilir"i söyler. TAMAMLANDI yalnız sonuç/uzaktan/atölye/
# bakım formu; KAPATILDI yalnız kapat. D1-B kesinleştirir.
UC_HEDEFLERI: dict[str, frozenset[str]] = {
    "genel": frozenset({"PLANLAMADA", "YOLA_CIKILDI", "SAHADA", "ISLEMDE", "ATOLYEDE"}),
    "planla": frozenset({"PLANLANDI"}),
    "plan_geri_al": frozenset({"PLANLAMADA"}),
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
    "yeniden_ac": frozenset({"TEKRAR_ACILDI"}),
    "iptal": frozenset({"IPTAL"}),
    "kiralama": frozenset({"IPTAL"}),
}


def tur_kategorisi(tur: str) -> str:
    """Kategori YALNIZ buradan türetilir (iş no önekinden tahmin yasak, E12)."""
    try:
        return TUR_KURALLARI[tur].kategori
    except KeyError:
        raise IsEmriHatasi(f"Bilinmeyen servis işi türü: {tur}") from None


@dataclass
class ServisIsiGirdisi:
    """Açılış girdisi (API şeması D1-B'de; burada servis sözleşmesi)."""

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


async def olustur(
    db: AsyncSession,
    girdi: ServisIsiGirdisi,
    *,
    user: User | None,
    clock: Clock,
    baslangic_durumu: str = "MUSTERI_TALEBI",
) -> ServiceOrder:
    """Servis işi açar (numara `numara.belge_no`, OLUSTUR olayı,
    `kancalar.is_olusturuldu`). PB/kiralama işleri `PLANLAMADA` doğar."""
    raise NotImplementedError("is_emirleri.olustur: D1-B paketi (TS-020) uygular")


async def guncelle(
    db: AsyncSession, so: ServiceOrder, degisiklikler: dict, *, user: User, clock: Clock
) -> ServiceOrder:
    """Temel bilgi düzeltme (iyimser kilit; öncelik/birim değişince
    `kancalar.oncelik_birim_degisti`)."""
    raise NotImplementedError("is_emirleri.guncelle: D1-B paketi (TS-031) uygular")


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
    """TEK durum geçiş kapısı (plan §1.7). `user` None = worker/sistem."""
    raise NotImplementedError("is_emirleri.durum_degistir: D1-B paketi (TS-021) uygular")


def sonraki_durumlar(so: ServiceOrder) -> list[str]:
    """Arayüze sunulacak geçerli hedefler (makine + uç kısıtı süzgeci D1-B'de)."""
    raise NotImplementedError("is_emirleri.sonraki_durumlar: D1-B paketi uygular")
