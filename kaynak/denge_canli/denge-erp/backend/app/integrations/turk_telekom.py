"""Türk Telekom M2M adaptörü.

DİKKAT: Uç nokta adları ve yanıt şeması ÖRNEKTİR; gerçek API sözleşmesi
operatörle netleşmedi (plan §8, açık madde). Bu yüzden adaptör yapılandırma
eksikse sessizce boş dönmez — `AdaptorHazirDegil` yükseltir ve senkron ekranı
"operatör bağlantısı yapılandırılmamış" der.

Erişim gelene kadar hatlar elle veya Excel ile yönetilir; brief §2.3 bunu
açıkça teslimatı engellemeyen bir durum sayıyor.
"""

from dataclasses import dataclass

import httpx

from app.integrations.base import HatDurumu


class AdaptorHazirDegil(RuntimeError):
    pass


# Operatörün döndürdüğü durum adları → ERP durumları.
DURUM_ESLEME = {
    "active": "AKTIF",
    "suspended": "ASKIDA",
    "terminated": "IPTAL",
    "inventory": "STOKTA",
    "test": "TEST",
}


@dataclass
class TurkTelekomAdaptoru:
    base_url: str
    api_key: str
    ad: str = "turk_telekom"
    zaman_asimi: float = 20.0

    def _kontrol(self) -> None:
        if not self.base_url or not self.api_key:
            raise AdaptorHazirDegil(
                "Operatör bağlantısı yapılandırılmamış (Parametreler → Operatör). "
                "Hat bilgileri elle veya Excel ile güncellenebilir."
            )

    async def hat_durumu(self, iccid: str) -> HatDurumu | None:
        self._kontrol()
        async with httpx.AsyncClient(timeout=self.zaman_asimi) as istemci:
            yanit = await istemci.get(
                f"{self.base_url.rstrip('/')}/sims/{iccid}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if yanit.status_code == 404:
            return None
        yanit.raise_for_status()
        return self._cevir(iccid, yanit.json())

    async def toplu_durum(self, iccidler: list[str]) -> list[HatDurumu]:
        self._kontrol()
        sonuc: list[HatDurumu] = []
        async with httpx.AsyncClient(timeout=self.zaman_asimi) as istemci:
            for iccid in iccidler:
                yanit = await istemci.get(
                    f"{self.base_url.rstrip('/')}/sims/{iccid}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if yanit.status_code == 200:
                    sonuc.append(self._cevir(iccid, yanit.json()))
        return sonuc

    @staticmethod
    def _cevir(iccid: str, govde: dict) -> HatDurumu:
        return HatDurumu(
            iccid=iccid,
            status=DURUM_ESLEME.get(str(govde.get("status", "")).lower()),
            enabled_network_tech=govde.get("networkTechnologies"),
            last_seen_network_tech=govde.get("lastSeenTechnology"),
            plan_name=govde.get("ratePlan"),
            data_allowance_mb=govde.get("dataAllowanceMb"),
            data_used_mb=govde.get("dataUsedMb"),
            commitment_end=govde.get("commitmentEndDate"),
        )
