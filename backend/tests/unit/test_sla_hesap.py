"""SLA takvimi ve Python tarafı SLA durumu — DB'siz (TS-081, E10-02/18).

SQL tarafıyla eşitlik PG gerektirir: `tests/integration/test_servis_sla_tutarlilik.py`.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.teknik_servis import (
    GECIKME_NEDENLERI,
    SLA_DURUMLARI,
    SLA_UYARI_KODLARI,
    TEKRAR_ARIZA_TEYITLERI,
)
from app.services.teknik_servis import sla, sla_takvim
from app.services.teknik_servis.kancalar import ServisHatasi

AN = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def _is(**kw):
    varsayilan = {
        "tur": "ARIZA",
        "kategori": "GUNLUK_SERVIS",
        "status": "ISLEMDE",
        "sla_sonuc": None,
        "sla_baslangic_at": AN,
        "cozum_hedef_at": AN + timedelta(hours=12),
        "cozum_hedef_ilk_at": AN + timedelta(hours=12),
        "mudahale_hedef_at": None,
        "ilk_mudahale_at": None,
    }
    varsayilan.update(kw)
    return SimpleNamespace(**varsayilan)


def test_takvim_7_24_ekle_ve_dakika() -> None:
    assert sla_takvim.is_saati_ekle(AN, 720) == AN + timedelta(hours=12)
    assert sla_takvim.takvim_dakika(AN, AN + timedelta(minutes=90, seconds=59)) == 90
    assert sla_takvim.takvim_dakika(AN, AN - timedelta(minutes=5)) == 0
    with pytest.raises(ValueError):
        sla_takvim.is_saati_ekle(AN, -1)
    with pytest.raises(ValueError):
        sla_takvim.is_saati_ekle(datetime(2026, 1, 1), 10)  # saat dilimsiz


def test_mesai_takvimi_bu_dalgada_yok() -> None:
    """KD-23: MESAI sessizce 7/24 sayılmaz → 409 (ServisHatasi)."""
    with pytest.raises(ServisHatasi):
        sla_takvim.is_saati_ekle(AN, 60, "MESAI")
    with pytest.raises(ServisHatasi):
        sla_takvim.takvim_dakika(AN, AN + timedelta(hours=1), "MESAI")


@pytest.mark.parametrize(
    ("simdi_ek", "beklenen", "kalan"),
    [
        (timedelta(hours=1), "ZAMANINDA", 660),
        (timedelta(hours=9, minutes=36), "RISKTE", 144),  # %80 tam sınır
        (timedelta(hours=9, minutes=35), "ZAMANINDA", 145),
        (timedelta(hours=12), "ASILDI", 0),  # hedef anı = aşıldı
        (timedelta(hours=13, seconds=1), "ASILDI", -61),
    ],
)
def test_durum_esikleri(simdi_ek, beklenen, kalan) -> None:
    d = sla.sla_durumu(_is(), None, AN + simdi_ek, 80)
    assert (d.durum, d.kalan_dk) == (beklenen, kalan)


def test_durduran_bekleme_kalani_dondurur() -> None:
    bekleme = SimpleNamespace(sla_durdurur=True, started_at=AN + timedelta(hours=2))
    d = sla.sla_durumu(_is(), bekleme, AN + timedelta(hours=30), 80)
    assert d.durum == "DURDURULDU" and d.kalan_dk == 600
    durdurmayan = SimpleNamespace(sla_durdurur=False, started_at=AN)
    assert sla.sla_durumu(_is(), durdurmayan, AN + timedelta(hours=30), 80).durum == "ASILDI"


def test_kapali_pb_ve_damgasiz() -> None:
    simdi = AN + timedelta(hours=50)
    assert sla.sla_durumu(_is(sla_sonuc="ZAMANINDA"), None, simdi, 80).durum == "KARSILANDI"
    assert sla.sla_durumu(_is(sla_sonuc="ASILDI"), None, simdi, 80).durum == "KARSILANMADI"
    assert sla.sla_durumu(_is(status="IPTAL"), None, simdi, 80).durum == "OLCULEMEDI"
    pb = sla.sla_durumu(_is(tur="PB", kategori="PLANLI_BAKIM"), None, simdi, 80)
    assert pb.durum == "SLA_DISI_PB" and pb.hedef_at is None
    proje = sla.sla_durumu(
        _is(tur="KURULUM", kategori="PROJE", cozum_hedef_at=None), None, simdi, 80
    )
    assert proje.durum == "OLCULEMEDI" and proje.ad == "SLA dışı"


def test_mudahale_durumu() -> None:
    hedef = AN + timedelta(hours=2)
    assert sla.mudahale_durumu(_is(mudahale_hedef_at=hedef), AN) == "BEKLENIYOR"
    assert sla.mudahale_durumu(_is(mudahale_hedef_at=hedef), hedef) == "ASILDI"
    assert (
        sla.mudahale_durumu(_is(mudahale_hedef_at=hedef, ilk_mudahale_at=AN), hedef)
        == "KARSILANDI"
    )
    assert sla.mudahale_durumu(_is(), AN) is None


def test_sozlukler_tek_kaynak() -> None:
    from app.api import servis_operasyon as uc

    assert set(sla.SLA_DURUM_ADLARI) == set(SLA_DURUMLARI)
    assert set(uc.GECIKME_ADLARI) == set(GECIKME_NEDENLERI)
    assert set(uc.TEYIT_ADLARI) == set(TEKRAR_ARIZA_TEYITLERI)
    assert set(uc.UYARI_KODU_ADLARI) == set(SLA_UYARI_KODLARI)
    # E10-17: iki bekleme kavramının başlıkları ayrık.
    assert sla.TERIMLER["IS_BEKLEMESI"] != sla.TERIMLER["PERSONEL_BEKLEME"]
    assert "BEKLEME" not in sla.ILK_MUDAHALE_FAALIYETLERI


def test_vade_ay_metni() -> None:
    assert sla.vade_ay_metni(date(2026, 10, 1)) == "Ekim 2026"
    assert sla.vade_ay_metni(None) is None


def test_kanca_kayitlari() -> None:
    """SLA kancaları kayıtlı; `is_olusturuldu` sırası sla → tekrar_ariza (plan §1.8)."""
    import app.services.teknik_servis  # noqa: F401
    from app.services.teknik_servis import kancalar, tekrar_ariza

    assert sla.damgala in kancalar.kayitlilar("is_olusturuldu")
    olusturuldu = kancalar.kayitlilar("is_olusturuldu")
    assert olusturuldu.index(sla.damgala) < olusturuldu.index(tekrar_ariza.isaretle)
    assert sla.yeniden_damgala in kancalar.kayitlilar("oncelik_birim_degisti")
    assert sla.durum_isle in kancalar.kayitlilar("durum_degisti")
    assert sla.ilk_mudahale_isle in kancalar.kayitlilar("zaman_bolumu_acildi")
    assert sla.kapanis_dogrula in kancalar.kayitlilar("durum_dogrula")


def test_worker_gorevleri_kayitli() -> None:
    from app import worker

    adlar = {g.ad: g for g in worker.GOREVLER}
    assert adlar["servis-sla-uyarilari"].periyot == timedelta(minutes=5)
    assert adlar["servis-uyari-temizligi"].periyot == timedelta(hours=24)
