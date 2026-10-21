"""Teknik servisin yerel gün yardımcısı ve "saat yalnız Clock'tan" kuralı (TS-011).

22:30 UTC'de açılan iş Türkiye'de ERTESİ gündür. Her modül kendi gün
sınırını hesaplasaydı "bugünün planı" ile "bugün kapanan işler" farklı günleri
sayardı. Ayrıca `datetime.now()` testte FakeClock'u atlar: zamana bağlı her
kural (SLA, gecikme, uyarı) canlıda başka, testte başka davranırdı.
"""

import re
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.clock import FakeClock
from app.services.teknik_servis import yerel_zaman

TS_DIZINI = Path(__file__).resolve().parents[2] / "app" / "services" / "teknik_servis"


def test_utc_gece_yerel_ertesi_gun() -> None:
    assert yerel_zaman.yerel_gun(datetime(2026, 10, 21, 22, 30, tzinfo=UTC)) == date(2026, 10, 22)
    assert yerel_zaman.yerel_gun(datetime(2026, 10, 21, 20, 59, tzinfo=UTC)) == date(2026, 10, 21)


def test_yerel_bugun_clocktan() -> None:
    saat = FakeClock(datetime(2026, 12, 31, 21, 0, tzinfo=UTC))
    assert yerel_zaman.yerel_bugun(saat) == date(2027, 1, 1)


def test_gun_araligi_yari_acik_ve_utc() -> None:
    bas, bit = yerel_zaman.yerel_gun_araligi(date(2026, 10, 22))
    assert bas == datetime(2026, 10, 21, 21, 0, tzinfo=UTC)
    assert bit == datetime(2026, 10, 22, 21, 0, tzinfo=UTC)
    assert bas.utcoffset() == timedelta(0)
    # Aralığın içindeki her an aynı yerel güne düşer, bitiş anı ertesi güne.
    assert yerel_zaman.yerel_gun(bas) == date(2026, 10, 22)
    assert yerel_zaman.yerel_gun(bit - timedelta(microseconds=1)) == date(2026, 10, 22)
    assert yerel_zaman.yerel_gun(bit) == date(2026, 10, 23)


def test_gecmis_yaz_saati_dikkate_alinir() -> None:
    """2016 öncesi Türkiye yaz saati uyguluyordu; sabit +3 göç kayıtlarında günü kaydırırdı."""
    bas, _ = yerel_zaman.yerel_gun_araligi(date(2015, 1, 15))
    assert bas == datetime(2015, 1, 14, 22, 0, tzinfo=UTC)  # kış: UTC+2


def test_baska_dilimdeki_an_dogru_cevrilir() -> None:
    an = datetime(2026, 10, 22, 1, 0, tzinfo=timezone(timedelta(hours=5)))
    assert yerel_zaman.yerel_gun(an) == date(2026, 10, 21)


def test_saat_dilimsiz_an_reddedilir() -> None:
    with pytest.raises(ValueError, match="Saat dilimi"):
        yerel_zaman.yerel_gun(datetime(2026, 10, 21, 22, 30))


# `datetime.now`, `datetime.utcnow`, `date.today` ve `time.time` çağrıları —
# yorum satırları ve docstring içindeki adlar hariç (yalnız kod satırı).
_YASAK = re.compile(r"\b(datetime\.(now|utcnow|today)|date\.today|time\.time)\s*\(")


def test_teknik_servis_paketinde_saat_okunmaz() -> None:
    """`services/teknik_servis/` altında saat YALNIZ Clock/yerel_zaman'dan okunur."""
    ihlaller: list[str] = []
    dosyalar = sorted(TS_DIZINI.rglob("*.py"))
    assert dosyalar, "teknik servis paketi bulunamadı"
    for dosya in dosyalar:
        docstring_icinde = False
        for no, satir in enumerate(dosya.read_text(encoding="utf-8").splitlines(), 1):
            kod = satir.strip()
            tirnak = kod.count('"""') + kod.count("'''")
            if docstring_icinde or kod.startswith("#"):
                if tirnak % 2:
                    docstring_icinde = not docstring_icinde
                continue
            if tirnak % 2:
                docstring_icinde = True
                continue
            if _YASAK.search(kod.split("#", 1)[0]):
                ihlaller.append(f"{dosya.name}:{no}: {kod}")
    assert not ihlaller, "Clock yerine doğrudan saat okunuyor:\n" + "\n".join(ihlaller)


def test_grep_kurali_kendini_dogrular() -> None:
    """Desen gerçekten yakalıyor mu (boş geçen test güvence vermez)."""
    assert _YASAK.search("x = datetime.now(UTC)")
    assert _YASAK.search("bugun = date.today()")
    assert not _YASAK.search("an = clock.now()")
