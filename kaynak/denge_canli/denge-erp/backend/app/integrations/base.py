"""Operatör M2M adaptör protokolü.

Gerçek veride hatların **%98,4'ü Türk Telekom** (1.096/1.114). Brief üç
operatör için ayrı adaptör öngörüyordu; iki adaptörün maliyeti kodda değil
operatörle yazışmada. Bu yüzden ortak iç model + tek gerçek adaptör + mock.

Operatör bir alanı DÖNDÜRMEZSE elle girilen değerin üzerine yazılmaz
(brief §4.4). Bunu `SimCard.field_sources` haritası sağlar: alan "MANUEL"
işaretliyse senkron o alana dokunmaz.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class HatDurumu:
    """Operatörden dönen ortak iç model. Alan None = operatör vermedi."""

    iccid: str
    status: str | None = None
    enabled_network_tech: list[str] | None = None
    last_seen_network_tech: str | None = None
    plan_name: str | None = None
    data_allowance_mb: int | None = None
    data_used_mb: int | None = None
    # Taahhüt bilgisi — indirim buna bağlı, düşerse maliyet kat kat artar.
    commitment_end: str | None = None

    def dolu_alanlar(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items() if k != "iccid" and v is not None and v != []
        }


class OperatorAdaptoru(Protocol):
    ad: str

    async def hat_durumu(self, iccid: str) -> HatDurumu | None: ...

    async def toplu_durum(self, iccidler: list[str]) -> list[HatDurumu]: ...


@dataclass
class MockAdaptor:
    """Operatör API'si olmadan tüm akışı çalıştırmaya yarar.

    Brief §2.3: "API'den gelmeyen hat bilgileri elle veya Excel ile
    girilebilmeli; bu durum teslimatı engellememeli." Mock, entegrasyon
    beklerken ekranların ve raporların geliştirilebilmesini sağlar.
    """

    ad: str = "mock"
    veri: dict[str, HatDurumu] = field(default_factory=dict)

    async def hat_durumu(self, iccid: str) -> HatDurumu | None:
        return self.veri.get(iccid)

    async def toplu_durum(self, iccidler: list[str]) -> list[HatDurumu]:
        return [self.veri[i] for i in iccidler if i in self.veri]
