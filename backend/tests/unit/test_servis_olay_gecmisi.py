"""Olay yazıcısı kişisel veri kabul etmez (TS-022, E01-04 kabul 5).

Olay satırı tetikleyiciyle değiştirilemez; KVKK anonimleştirmesi onu
temizleyemez. Bu yüzden irtibat adı/telefonu ve imzalayan adı olaya HİÇ
girmemeli — veritabanına gitmeden reddedilir.
"""

from types import SimpleNamespace

import pytest

from app.clock import FakeClock
from app.services.teknik_servis import gecmis


class _DbYok:
    def add(self, *_):  # pragma: no cover - çağrılırsa test başarısız olmalı
        raise AssertionError("kişisel veri reddedilmeden DB'ye yazılmaya çalışıldı")


def _is(**kw):
    return SimpleNamespace(id=1, iletisim_ad=kw.get("ad"), iletisim_telefon=kw.get("tel"))


@pytest.mark.parametrize(
    "veri",
    [
        {"iletisim_telefon": "+905321112233"},
        {"iletisim_ad": "Ali Veli"},
        {"ic": {"imzalayan_ad": "Ayşe"}},
        {"liste": [{"telefon": "123"}]},
    ],
)
async def test_kisisel_anahtar_reddedilir(veri) -> None:
    with pytest.raises(gecmis.KisiselVeriHatasi):
        await gecmis.olay_yaz(_DbYok(), _is(), "NOT", "x", user=None, clock=FakeClock(), veri=veri)


async def test_ozette_irtibat_degeri_reddedilir() -> None:
    so = _is(ad="Mehmet Kaya", tel="+905551234567")
    for ozet in ("Mehmet Kaya arandı", "Tel +905551234567"):
        with pytest.raises(gecmis.KisiselVeriHatasi):
            await gecmis.olay_yaz(_DbYok(), so, "NOT", ozet, user=None, clock=FakeClock())


async def test_bilinmeyen_olay_turu() -> None:
    with pytest.raises(ValueError):
        await gecmis.olay_yaz(
            _DbYok(), _is(), "MUKERRER_GECILDI", "x", user=None, clock=FakeClock()
        )


def test_olay_adlari_katalogla_ayni() -> None:
    from app.models.teknik_servis import OLAY_TURLERI

    assert set(gecmis.OLAY_ADLARI) == set(OLAY_TURLERI)
