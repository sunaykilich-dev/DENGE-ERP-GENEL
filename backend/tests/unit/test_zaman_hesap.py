"""Süre özeti kuralları ve "eksik ≠ 0" sözleşmesi (TS-075, E09-13/D02).

- `sure_durumu_hesapla` tablosu: kayıt yoksa EKSIK ya da BEKLENMIYOR, asla
  "0 dakika TAM" değil; KISMI'de eksik teknisyenin adı döner.
- `or 0` / `coalesce(…, 0)` zaman ve mobil servislerinde YASAK (kayıt yoksa
  None döner; 0'a çevirmek "süre kaydı eksik" bilgisini yok eder).
- Faaliyet sözlüğü tek kaynak; mola kişi-saate dahil değil.
- SQL/Python eşitliği DB gerektirdiği için entegrasyon testindedir
  (`test_servis_zaman_kayit.test_sql_ve_python_eksik_tanimi_esit`).
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models import teknik_servis as m
from app.services.teknik_servis import zaman

KAYNAK = Path(zaman.__file__).parent


@pytest.mark.parametrize(
    ("durum", "uzaktan", "olanlar", "teknisyenler", "beklenen"),
    [
        # kayıt yok
        ("TAMAMLANDI", False, set(), {1: "Ali Veli"}, ("EKSIK", ("Ali Veli",))),
        ("SAHADA", False, set(), {}, ("EKSIK", ())),
        ("PLANLANDI", False, set(), {1: "Ali Veli"}, ("BEKLENMIYOR", ())),
        ("MUSTERI_TALEBI", False, set(), {}, ("BEKLENMIYOR", ())),
        ("IPTAL", False, set(), {1: "Ali Veli"}, ("BEKLENMIYOR", ())),
        ("TAMAMLANDI", True, set(), {1: "Ali Veli"}, ("BEKLENMIYOR", ())),
        # kayıt var
        ("SAHADA", False, {1}, {1: "Ali Veli"}, ("TAM", ())),
        ("KAPATILDI", False, {1}, {1: "Ali Veli", 2: "Ayşe Kaya"}, ("KISMI", ("Ayşe Kaya",))),
        ("SAHADA", False, {9}, {}, ("TAM", ())),  # yalnız şef çalıştı, teknisyen yok
        ("IPTAL", False, {1}, {1: "Ali Veli", 2: "Ayşe Kaya"}, ("BEKLENMIYOR", ())),
        ("TAMAMLANDI", True, {1}, {1: "Ali Veli", 2: "Ayşe Kaya"}, ("TAM", ())),
    ],
)
def test_sure_durumu_tablosu(durum, uzaktan, olanlar, teknisyenler, beklenen) -> None:
    assert (
        zaman.sure_durumu_hesapla(
            durum=durum,
            uzaktan_cozum=uzaktan,
            dahil_bolumu_olanlar=olanlar,
            teknisyenler=teknisyenler,
        )
        == beklenen
    )


def test_beklenmiyor_durumlari_katalogdan() -> None:
    assert zaman.BEKLENMIYOR_DURUMLAR <= set(m.SERVIS_DURUMLARI)
    # tamamlanan/kapatılan iş her zaman süre bekler
    assert not (m.DURUM_GRUPLARI["COZULDU"] & zaman.BEKLENMIYOR_DURUMLAR)
    assert set(zaman.SURE_DURUMLARI) == {"TAM", "KISMI", "EKSIK", "BEKLENMIYOR"}


def test_mola_kisi_saate_dahil_degil() -> None:
    assert "MOLA" not in m.KISI_SAATE_DAHIL
    assert m.KISI_SAATE_DAHIL == frozenset(m.ZAMAN_FAALIYETLERI) - {"MOLA"}


def test_bos_ozet_sifir_degil() -> None:
    ozet = zaman.SureOzeti(kisi_saat_dk=None, sure_durumu="EKSIK")
    assert ozet.kisi_saat_dk is None and ozet.sure_eksik
    assert not zaman.SureOzeti(kisi_saat_dk=None, sure_durumu="BEKLENMIYOR").sure_eksik


@pytest.mark.parametrize("dosya", ["zaman.py", "mobil.py"])
def test_or_0_ve_coalesce_yasak(dosya: str) -> None:
    kod = (KAYNAK / dosya).read_text(encoding="utf-8")
    # docstring/yorum dışı satırlar
    satirlar = [s for s in kod.splitlines() if not s.strip().startswith(("#", '"', "`", "-"))]
    govde = "\n".join(satirlar)
    assert not re.search(r"\bor 0\b", govde), f"{dosya}: `or 0` kullanılmış"
    assert "coalesce" not in govde.lower(), f"{dosya}: coalesce kullanılmış"


@pytest.mark.parametrize(
    ("ad", "beklenen"),
    [
        ("Ali Veli", "Ali Veli'nin"),
        ("Ayşe Kaya", "Ayşe Kaya'nın"),
        ("Mert", "Mert'in"),
        ("Ufuk Koç", "Ufuk Koç'un"),
        ("Gül", "Gül'ün"),
        ("Burak", "Burak'ın"),
    ],
)
def test_iyelik_eki(ad: str, beklenen: str) -> None:
    assert zaman.iyelik(ad) == beklenen


def test_uzun_sayac_kosulu() -> None:
    an = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)  # yerel 15:00
    bolum = m.ServiceTimeEntry(started_at=an - timedelta(hours=10), ended_at=None, is_deleted=False)
    assert zaman.uzun_sayac_mi(bolum, an, 10)
    bolum.started_at = an - timedelta(hours=2)
    assert not zaman.uzun_sayac_mi(bolum, an, 10)
    # dünden kalmış (yerel): 10.03 20:30 UTC = 23:30 yerel; an 11.03 01:00 yerel
    gece = datetime(2026, 3, 10, 22, 0, tzinfo=UTC)
    bolum.started_at = datetime(2026, 3, 10, 20, 30, tzinfo=UTC)
    assert zaman.uzun_sayac_mi(bolum, gece, 10)


def test_otomatik_durum_yalniz_sayac_hedefleri() -> None:
    from app.services.teknik_servis.is_emirleri import UC_HEDEFLERI

    hedefler = {h for _, h in zaman._OTOMATIK_DURUM.values()}
    assert hedefler <= UC_HEDEFLERI["sayac"]
