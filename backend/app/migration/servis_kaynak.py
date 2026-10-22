"""Eski .NET DengeERP V1.20.1 (SQL Server) dökümünün ortak okuyucusu (Göç-1, plan §5.3).

**Canlı SQL Server'a bağlanılmaz.** V1.20.1 `.bak` yedeği ayrı bir test
örneğine geri yüklenir; `teknik_servis/sql/goc_*.sql` T-SQL SELECT'leri
(`disa_aktar.ps1` ile) tablo başına bir UTF-8 CSV üretir: dosya adı = tablo
adı, başlık = kolon adı, seri no METİN, tarih ISO 8601. Bu modül o dizini
okur ve göç adımlarının paylaştığı kuralları tek yerde tutar:

- **Kimlik:** `source_system='DENGEERP_V1'`, `source_ref='<KaynakTablo>:<Id>'`
  (plan §5.3). Her yükleme `ON CONFLICT ON CONSTRAINT uq_<tablo>_kaynak DO
  NOTHING` ile idempotenttir; ekrandan yapılmış düzeltme EZİLMEZ.
- **Saat:** V1 `DATETIME2` kolonları yerel saattir (Europe/Istanbul) ve
  burada AÇIKÇA UTC'ye çevrilir. Naif tarihi UTC sanmak her kaydı 3 saat
  kaydırırdı.
- **Uzlaşma sözleşmesi:** her adım kaynak satırlarını üç kümeye ayırır:
  `aktarilacak` (yüklenir), `karantina` (insan kararı bekler; profil
  Excel'iyle geri gelir), `reddedilen` (kimliksiz/bozuk, hiç yüklenemez).
  `kaynak = aktarılan + karantina + reddedilen` (TS-177). Uyarılar (seri
  no'suz, tarih okunamadı ...) satırı yüklenmekten alıkoymaz.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

GOC_SISTEMI = "DENGEERP_V1"
YEREL = ZoneInfo("Europe/Istanbul")

# Göçün okuduğu V1 tabloları (dosya adı = tablo adı + ".csv").
TABLOLAR = (
    "SecurityDevices",
    "MaintenanceContracts",
    "MaintenancePlans",
    "MaintenanceDeviceItems",
    "WorkOrders",
    "WorkOrderStatusLogs",
    "WorkOrderAssignments",
    "WorkOrderDevices",
    "WorkOrderPlans",
    "WorkOrderTimeLogs",
    "WorkOrderLiveSessions",
)


class KaynakHatasi(ValueError):
    """Kaynak dizini/dosyası okunamadı ya da beklenen kolonu taşımıyor."""


def kaynak_ref(tablo: str, kimlik: Any) -> str:
    """`'<KaynakTablo>:<Id>'` — `source_ref` String(64)'e sığar."""
    ref = f"{tablo}:{str(kimlik).strip()}"
    if len(ref) > 64:
        raise KaynakHatasi(f"Kaynak kimliği 64 karakteri aşıyor: {ref}")
    return ref


def bos(deger: Any) -> bool:
    return deger is None or not str(deger).strip() or str(deger).strip().upper() == "NULL"


def metin(deger: Any, uzunluk: int | None = None) -> str | None:
    """Boş/NULL → None; uzunluk verilirse KESİLMEZ, aşan değer ValueError'dır."""
    if bos(deger):
        return None
    sonuc = str(deger).strip()
    if uzunluk is not None and len(sonuc) > uzunluk:
        raise ValueError(f"{uzunluk} karakteri aşıyor: {sonuc[:30]}…")
    return sonuc


def tamsayi(deger: Any) -> int | None:
    if bos(deger):
        return None
    try:
        return int(float(str(deger).strip()))
    except ValueError as exc:
        raise ValueError(f"tamsayı okunamadı: {deger}") from exc


def bit(deger: Any, *, varsayilan: bool = False) -> bool:
    if bos(deger):
        return varsayilan
    return str(deger).strip().lower() in ("1", "true", "evet", "e")


def _naif_an(ham: str) -> datetime:
    ham = ham.strip().replace(" ", "T", 1)
    if "." in ham:
        ham = ham.split(".", 1)[0]
    if ham.endswith("Z"):
        ham = ham[:-1]
    return datetime.fromisoformat(ham)


def yerel_an(deger: Any) -> datetime | None:
    """V1 yerel saat (ISO 8601, saat dilimsiz) → UTC `datetime`.

    Saat dilimi taşıyan değer olduğu gibi UTC'ye çevrilir. Okunamayan değer
    ValueError'dır (sessizce None yazılmaz; çağıran karantinaya alır).
    """
    if bos(deger):
        return None
    try:
        an = _naif_an(str(deger))
    except ValueError as exc:
        raise ValueError(f"tarih/saat okunamadı: {deger}") from exc
    if an.tzinfo is None:
        an = an.replace(tzinfo=YEREL)
    return an.astimezone(UTC)


def gun(deger: Any) -> date | None:
    """ISO tarih (`YYYY-MM-DD`, saat kısmı yok sayılır)."""
    if bos(deger):
        return None
    try:
        return date.fromisoformat(str(deger).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"tarih okunamadı: {deger}") from exc


def saat(deger: Any) -> time | None:
    """`HH:MM[:SS[.fff]]` → time."""
    if bos(deger):
        return None
    ham = str(deger).strip().split(".", 1)[0]
    try:
        return time.fromisoformat(ham)
    except ValueError as exc:
        raise ValueError(f"saat okunamadı: {deger}") from exc


@dataclass
class KaynakDizini:
    """`<dizin>/<Tablo>.csv` dosyaları. Dosya yoksa tablo boş SAYILMAZ:
    `zorunlu=True` iken hata verir (eksik döküm sessizce 0 aktarım üretmesin)."""

    yol: Path
    _onbellek: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def dosya(self, tablo: str) -> Path:
        return self.yol / f"{tablo}.csv"

    def var_mi(self, tablo: str) -> bool:
        return self.dosya(tablo).is_file()

    def tablo(self, ad: str, *, zorunlu: bool = True) -> list[dict[str, Any]]:
        if ad in self._onbellek:
            return self._onbellek[ad]
        yol = self.dosya(ad)
        if not yol.is_file():
            if zorunlu:
                raise KaynakHatasi(f"Kaynak dosyası yok: {yol}")
            self._onbellek[ad] = []
            return []
        with yol.open(encoding="utf-8-sig", newline="") as f:
            ornek = f.read(4096)
            f.seek(0)
            ayrac = ";" if ornek.count(";") > ornek.count(",") else ","
            satirlar = [
                {(k or "").strip(): (None if bos(v) else str(v)) for k, v in s.items()}
                for s in csv.DictReader(f, delimiter=ayrac)
            ]
        self._onbellek[ad] = satirlar
        return satirlar


# --- Adım sonucu ve uzlaşma ---------------------------------------------------------


@dataclass
class AdimSonucu:
    """Bir göç adımının (tek hedef tablo) hazırlık + yükleme sonucu."""

    kaynak_tablo: str
    hedef_tablo: str
    kaynak: int = 0
    aktarilacak: list[Any] = field(default_factory=list)
    karantina: list[tuple[str, str]] = field(default_factory=list)  # (ref, neden)
    reddedilen: list[tuple[str, str]] = field(default_factory=list)  # (ref|satır, neden)
    uyarilar: list[tuple[str, str, str]] = field(default_factory=list)  # (ref, kod, açıklama)
    yeni: int = 0  # bu koşuda gerçekten eklenen
    mevcut: int = 0  # zaten vardı (ON CONFLICT DO NOTHING)
    # Adıma özgü ek çıktı (ör. karantina satırlarının profil Excel'i için ham hâli).
    ek: dict[str, Any] = field(default_factory=dict)

    def karantinaya(self, ref: str, neden: str) -> None:
        self.karantina.append((ref, neden))

    def reddet(self, ref: str, neden: str) -> None:
        self.reddedilen.append((ref, neden))

    def uyar(self, ref: str, kod: str, aciklama: str = "") -> None:
        self.uyarilar.append((ref, kod, aciklama))

    @property
    def tutarli(self) -> bool:
        return self.kaynak == len(self.aktarilacak) + len(self.karantina) + len(self.reddedilen)

    def uyari_sayilari(self) -> dict[str, int]:
        return dict(Counter(k for _, k, _ in self.uyarilar))

    def ozet(self) -> dict[str, Any]:
        return {
            "kaynak_tablo": self.kaynak_tablo,
            "hedef_tablo": self.hedef_tablo,
            "kaynak": self.kaynak,
            "aktarilacak": len(self.aktarilacak),
            "karantina": len(self.karantina),
            "reddedilen": len(self.reddedilen),
            "yeni": self.yeni,
            "mevcut": self.mevcut,
            "uyarilar": self.uyari_sayilari(),
        }


async def mevcut_refler(
    db: AsyncSession | AsyncConnection, hedef_tablo: str, kaynak_tablo: str
) -> set[str]:
    """Hedef tabloda bu kaynak tablodan gelmiş `source_ref`'ler.

    Tablo adı modül sabitlerinden gelir (kullanıcı girdisi değil); yine de
    beyaz liste ile sınanır.
    """
    if hedef_tablo not in HEDEF_TABLOLAR:
        raise ValueError(f"Bilinmeyen hedef tablo: {hedef_tablo}")
    sonuc = await db.execute(
        text(
            f"SELECT source_ref FROM {hedef_tablo} "  # noqa: S608 — beyaz liste
            "WHERE source_system = :s AND source_ref LIKE :onek"
        ),
        {"s": GOC_SISTEMI, "onek": f"{kaynak_tablo}:%"},
    )
    return {r[0] for r in sonuc.all()}


HEDEF_TABLOLAR = frozenset(
    {
        "service_equipment",
        "maintenance_contracts",
        "maintenance_contract_items",
        "service_orders",
        "service_visits",
        "service_plans",
        "service_time_entries",
    }
)
