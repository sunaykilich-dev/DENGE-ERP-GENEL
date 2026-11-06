"""Enjekte edilebilir saat.

ERP'nin en hataya açık bölgeleri zamana bağlı: tarihli tarife çözümlemesi
(iş hangi tarihteyse o tarifeden hesaplanır), abonelikte kıst hesap, hak ediş
dönem kapanışı, teklif süresi dolması, hat taahhüt bitişi. Bunlar FakeClock ile
saniye beklemeden test edilir.

KURAL: uygulama kodunda asla doğrudan datetime.now() kullanmayın — Clock alın."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now += timedelta(**kwargs)

    def set(self, moment: datetime) -> None:
        self._now = moment
