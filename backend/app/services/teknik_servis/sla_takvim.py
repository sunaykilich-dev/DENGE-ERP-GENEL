"""SLA takvimi — saf fonksiyonlar, DB'siz (E10-02; P1'de yalnız 7/24, KD-23).

Maddeler: TS-081. Doldurdu: D2-G.

**Neden ayrı ve saf:** hedef anı (`cozum_hedef_at`) ve bekleme kayması
(`service_holds.sla_kayma_dk`) aynı takvim kuralıyla hesaplanmalı; ikisi ayrı
yerde yazılsaydı MESAI takvimi geldiğinde (Dalga 3, TS-200) biri güncellenip
diğeri unutulurdu. Fonksiyonlar DB okumaz; takvim/tatil verisi gerekirse
çağıran bir kez okuyup değer olarak geçirir.

**MESAI bu dalgada YOK** (KD-23): politika `takvim_turu='MESAI'` olamaz
(tanım ucu 400 verir); yine de veri yoluyla gelirse burada `ServisHatasi`
(409) atılır — sessizce 7/24 saymak hedefi yanlış damgalardı.

**Dalga 3 (TS-200, D3-F):** MESAI kararı verilmedi (plan §6 KD-23 "koşullu");
`d3a000000003` atlandı, `service_work_calendar`/`service_holidays` tabloları
YOK. Karar gelirse tablolar zincirin sonuna ek revizyonla gelir ve
`is_saati_ekle`/`takvim_dakika` buradan genişler (imza değişmez: takvim ve
tatil verisi çağıran tarafından değer olarak geçirilir).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.teknik_servis import SLA_TAKVIM_TURLERI
from app.services.teknik_servis.kancalar import ServisHatasi

TAKVIM_7_24 = "7_24"


def _tur_dogrula(tur: str | None) -> str:
    tur = tur or TAKVIM_7_24
    if tur not in SLA_TAKVIM_TURLERI:
        raise ValueError(f"Bilinmeyen SLA takvim türü: {tur}")
    if tur != TAKVIM_7_24:
        raise ServisHatasi(
            "Mesai takvimli SLA bu sürümde desteklenmiyor; politika 7/24 olmalı (KD-23)"
        )
    return tur


def _aware(an: datetime) -> datetime:
    if an.tzinfo is None or an.tzinfo.utcoffset(an) is None:
        raise ValueError("SLA hesabında saat dilimsiz zaman kullanılamaz")
    return an


def is_saati_ekle(baslangic: datetime, dakika: int, tur: str = "7_24") -> datetime:
    """7_24: baslangic + dakika. MESAI Dalga 3'te (koşullu).

    Negatif dakika programlama hatasıdır (hedef geriye alınmaz).
    """
    _tur_dogrula(tur)
    if dakika < 0:
        raise ValueError("SLA dakikası negatif olamaz")
    return _aware(baslangic) + timedelta(minutes=int(dakika))


def takvim_dakika(bas: datetime, bit: datetime, tur: str = "7_24") -> int:
    """Aralıktaki çalışılan dakika (7_24: duvar saati, tam dakika, alttan).

    Bitiş başlangıçtan önceyse 0 (kayma negatif olmaz).
    """
    _tur_dogrula(tur)
    saniye = (_aware(bit) - _aware(bas)).total_seconds()
    return max(0, int(saniye // 60))
