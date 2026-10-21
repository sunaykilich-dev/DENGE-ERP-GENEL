"""Yerel (Europe/Istanbul) gün yardımcıları — teknik servisin TEK saat kapısı (KD-17).

Veritabanı ve `Clock` UTC çalışır; "bugün", "dün", "gün değişmiş sayaç",
planlama günü ve rapor gün kırılımı ise Türkiye günüdür. 22:30 UTC'de açılan
bir iş Türkiye'de ertesi gündür. Her modül kendi `ZoneInfo` sarmalayıcısını
yazsaydı gün sınırı modüller arasında ayrışırdı (E09 kontrol B10). Canlı
`clock.py` DEĞİŞMEZ. `services/teknik_servis/` altında `datetime.now` /
`date.today` yasaktır (grep testi: `tests/unit/test_teknik_servis_saat.py`).

Saat dilimi verisi `tzdata` paketinden gelir (Windows'ta ve ince Docker
imajlarında sistem zoneinfo veritabanı yok; `pyproject.toml`'da bağımlılık).
Türkiye 2016'dan beri sabit UTC+3'tür, ama sabit `+3` yazmak geçmiş tarihli
göç kayıtlarında (2016 öncesi yaz saati) günü kaydırırdı; bu yüzden ZoneInfo.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.clock import Clock

SAAT_DILIMI = "Europe/Istanbul"
YEREL = ZoneInfo(SAAT_DILIMI)


def _aware(an: datetime) -> datetime:
    """Saat dilimsiz an kabul edilmez: hangi güne düştüğü belirsizdir.

    Uygulamadaki her zaman damgası `timestamptz` ve Clock UTC döner; naif bir
    an buraya ancak bir hata sonucu gelir. Sessizce UTC varsaymak, yerel saatle
    yazılmış bir değeri 3 saat kaydırıp yanlış güne koyardı.
    """
    if an.tzinfo is None or an.tzinfo.utcoffset(an) is None:
        raise ValueError("Saat dilimi bilgisi olmayan zaman damgası yerel güne çevrilemez")
    return an


def yerel_an(an: datetime) -> datetime:
    """Anı Türkiye saatine çevirir (gösterim ve saat bazlı kurallar için)."""
    return _aware(an).astimezone(YEREL)


def yerel_bugun(clock: Clock) -> date:
    """Clock'un şimdiki anının Türkiye tarihi."""
    return yerel_gun(clock.now())


def yerel_gun(an: datetime) -> date:
    """Zaman damgalı anın Türkiye tarihi (ör. 2026-10-21T22:30Z → 2026-10-22)."""
    return yerel_an(an).date()


def yerel_gun_araligi(gun: date) -> tuple[datetime, datetime]:
    """Türkiye gününün UTC yarı açık aralığı `[başlangıç, bitiş)`.

    Sorgular `an >= bas AND an < bit` ile yazılır (canlı kural: aralıklar daima
    yarı açık). Bitiş, ertesi günün yerel gece yarısıdır; "23:59:59" yazmak
    son saniyedeki kaydı kaçırırdı.
    """
    bas = datetime.combine(gun, time.min, tzinfo=YEREL)
    bit = datetime.combine(gun + timedelta(days=1), time.min, tzinfo=YEREL)
    return bas.astimezone(UTC), bit.astimezone(UTC)
