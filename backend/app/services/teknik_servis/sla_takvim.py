"""SLA takvimi — saf fonksiyonlar, DB'siz (E10-02; Faz A: 7/24 + MESAI, TS-200).

Maddeler: TS-081, TS-200 (M5.1, M5.4, M12.2). Doldurdu: D2-G; MESAI: Faz A.

**Neden ayrı ve saf:** hedef anı (`cozum_hedef_at`) ve bekleme kayması
(`service_holds.sla_kayma_dk`) aynı takvim kuralıyla hesaplanmalı; ikisi ayrı
yerde yazılsaydı biri güncellenip diğeri unutulurdu. Fonksiyonlar DB okumaz;
mesai saatleri çağıran tarafından bir kez okunup DEĞER olarak geçirilir
(`mesai=MesaiTakvimi(...)`, `sla.mesai_takvimi(db)`). İmzalar geriye uyumlu:
`mesai` verilmezse varsayılan 08:30–18:00 kullanılır.

**MESAI kuralı (karar 2026-10-28 §7 Faz A-1, M5.1/M5.4):** SLA müşteri
sözleşmesine göre ya 7/24 ya MESAI sayılır. MESAI = hafta içi (Pzt–Cum)
08:30–18:00, Europe/Istanbul yerel saati. **Resmî/dinî tatiller FARK ETMEZ**
(kullanıcı kararı) — bu yüzden tatil tablosu YOK (`d3a000000003`'te
öngörülen `service_work_calendar`/`service_holidays` tabloları açılmadı).
Saatler ayardır (`servis_mesai_baslangic`, `servis_mesai_bitis`); günler
karar gereği kod sabitidir (hafta içi).

**Sınır kuralları (testle kilitli, `tests/unit/test_sla_takvim_mesai.py`):**
- Mesai dışında başlayan sayaç bir sonraki mesai başlangıcından işler
  (Cumartesi açılan iş Pazartesi 08:30'dan sayar).
- Hedef tam mesai bitişine düşüyorsa o an döner (Cuma 17:00 + 60 dk = Cuma
  18:00, Pazartesi 08:30 DEĞİL).
- `takvim_dakika` aralığın mesaiye düşen saniyelerini toplar, sonra TAM
  dakikaya aşağı yuvarlar (7/24 ile aynı yuvarlama; SQL `servis_mesai_dk`
  fonksiyonu da böyle).
- `is_saati_ekle(x, 0)` = x (kayma yoksa hedef oynamaz).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.models.teknik_servis import SLA_TAKVIM_TURLERI
from app.services.teknik_servis.yerel_zaman import YEREL

TAKVIM_7_24 = "7_24"
TAKVIM_MESAI = "MESAI"

# Ekran adları (tek sözlük; API `takvim_adi` bunu döner).
TAKVIM_ADLARI: dict[str, str] = {TAKVIM_7_24: "7/24", TAKVIM_MESAI: "Mesai"}

# Hafta içi (date.weekday(): 0=Pzt … 4=Cum). Karar: tatiller fark etmez.
MESAI_GUNLERI = frozenset({0, 1, 2, 3, 4})
MESAI_BASLANGIC_VARSAYILAN = "08:30"
MESAI_BITIS_VARSAYILAN = "18:00"


def saat_dk(metin: str) -> int:
    """ "SS:DD" → gün içi dakika."""
    saat, dakika = str(metin).split(":")
    return int(saat) * 60 + int(dakika)


@dataclass(frozen=True)
class MesaiTakvimi:
    """Mesai penceresi (gün içi dakika, yerel saat). `bitis_dk > baslangic_dk`."""

    baslangic_dk: int = 8 * 60 + 30
    bitis_dk: int = 18 * 60

    def __post_init__(self) -> None:
        if not 0 <= self.baslangic_dk < self.bitis_dk <= 24 * 60:
            raise ValueError("Mesai başlangıcı bitişten önce olmalı (ör. 08:30–18:00)")

    @classmethod
    def metinden(cls, baslangic: str | None, bitis: str | None) -> MesaiTakvimi:
        return cls(
            saat_dk(baslangic or MESAI_BASLANGIC_VARSAYILAN),
            saat_dk(bitis or MESAI_BITIS_VARSAYILAN),
        )

    @property
    def gunluk_dk(self) -> int:
        return self.bitis_dk - self.baslangic_dk

    def metin(self) -> str:
        def _s(dk: int) -> str:
            return f"{dk // 60:02d}:{dk % 60:02d}"

        return f"hafta içi {_s(self.baslangic_dk)}–{_s(self.bitis_dk)}"

    def _pencere(self, gun: date) -> tuple[datetime, datetime]:
        gece = datetime.combine(gun, time(0), tzinfo=YEREL)
        return (
            gece + timedelta(minutes=self.baslangic_dk),
            gece + timedelta(minutes=self.bitis_dk),
        )


VARSAYILAN_MESAI = MesaiTakvimi()


def _tur_dogrula(tur: str | None) -> str:
    tur = tur or TAKVIM_7_24
    if tur not in SLA_TAKVIM_TURLERI:
        raise ValueError(f"Bilinmeyen SLA takvim türü: {tur}")
    return tur


def _aware(an: datetime) -> datetime:
    if an.tzinfo is None or an.tzinfo.utcoffset(an) is None:
        raise ValueError("SLA hesabında saat dilimsiz zaman kullanılamaz")
    return an


def _mesai_ekle(baslangic: datetime, dakika: int, mesai: MesaiTakvimi) -> datetime:
    if dakika == 0:
        return baslangic
    an = baslangic.astimezone(YEREL)
    kalan = timedelta(minutes=dakika)
    gun = an.date()
    while True:
        if gun.weekday() in MESAI_GUNLERI:
            bas, bit = mesai._pencere(gun)
            imlec = max(an, bas)
            if imlec < bit:
                bosluk = bit - imlec
                if kalan <= bosluk:
                    return (imlec + kalan).astimezone(baslangic.tzinfo)
                kalan -= bosluk
        gun += timedelta(days=1)


def _mesai_saniye(bas: datetime, bit: datetime, mesai: MesaiTakvimi) -> float:
    yb, yt = bas.astimezone(YEREL), bit.astimezone(YEREL)
    toplam = 0.0
    gun = yb.date()
    son = yt.date()
    while gun <= son:
        if gun.weekday() in MESAI_GUNLERI:
            p_bas, p_bit = mesai._pencere(gun)
            alt, ust = max(yb, p_bas), min(yt, p_bit)
            if ust > alt:
                toplam += (ust - alt).total_seconds()
        gun += timedelta(days=1)
    return toplam


def is_saati_ekle(
    baslangic: datetime,
    dakika: int,
    tur: str = "7_24",
    *,
    mesai: MesaiTakvimi | None = None,
) -> datetime:
    """`baslangic`'tan itibaren `dakika` ÇALIŞILAN dakika sonraki an.

    7_24: duvar saati. MESAI: yalnız hafta içi mesai penceresi sayılır.
    Negatif dakika programlama hatasıdır (hedef geriye alınmaz).
    """
    tur = _tur_dogrula(tur)
    if dakika < 0:
        raise ValueError("SLA dakikası negatif olamaz")
    baslangic = _aware(baslangic)
    if tur == TAKVIM_MESAI:
        return _mesai_ekle(baslangic, int(dakika), mesai or VARSAYILAN_MESAI)
    return baslangic + timedelta(minutes=int(dakika))


def takvim_dakika(
    bas: datetime,
    bit: datetime,
    tur: str = "7_24",
    *,
    mesai: MesaiTakvimi | None = None,
) -> int:
    """Aralıktaki çalışılan dakika (tam dakika, alttan).

    7_24: duvar saati. MESAI: mesai penceresine düşen kısım.
    Bitiş başlangıçtan önceyse 0 (kayma negatif olmaz).
    """
    tur = _tur_dogrula(tur)
    bas, bit = _aware(bas), _aware(bit)
    if bit <= bas:
        return 0
    if tur == TAKVIM_MESAI:
        saniye = _mesai_saniye(bas, bit, mesai or VARSAYILAN_MESAI)
    else:
        saniye = (bit - bas).total_seconds()
    return max(0, int(saniye // 60))
