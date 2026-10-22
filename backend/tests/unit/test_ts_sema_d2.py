"""Teknik servis Dalga 2 şema iskeletinin tek-kaynak sözleşmeleri (TS-080).

Durum makinesinin durum kümesi ile CHECK kısıtının değer kümesi AYNI
tuple'dan gelmeli: makinede olup CHECK'te olmayan durum 409 yerine anlamsız
bir DB hatası, CHECK'te olup makinede olmayan durum "ulaşılamayan durum"
üretir. Kanca imzaları ve kanca kayıt (import) sırası da paketler arası
sözleşmedir; bir paket sırayı ya da imzayı sessizce değiştirirse burada kırılır.
"""

import inspect
from pathlib import Path

from app.models.egitim import DUZELTICI_DURUMLARI, PLAN_DURUMLARI
from app.models.quote import TEKLIF_DURUMLARI
from app.models.servis_atolye import ATOLYE_ACIK_OLMAYAN, ATOLYE_DURUMLARI
from app.models.servis_kiralama import KIRALAMA_DURUMLARI
from app.models.servis_parca import PARCA_TALEP_DURUMLARI, SAYIM_DURUMLARI
from app.models.stock import SERVIS_HAREKET_TURLERI, SERVIS_HAREKET_YONU
from app.models.teknik_servis import (
    ONCELIKLER,
    SERVIS_DURUMLARI,
    VARSAYILAN_SLA_POLITIKALARI,
)
from app.services import statemachine as sm
from app.services.teknik_servis import kancalar


def test_dalga2_makineleri_kayitli() -> None:
    for ad in (
        "atolye",
        "kiralama",
        "teklif",
        "egitim_plani",
        "duzeltici_faaliyet",
        "stok_sayim",
        "parca_talebi",
    ):
        assert ad in sm.MAKINELER, ad


def test_makine_durumlari_check_kumesiyle_ayni() -> None:
    assert sm.ATOLYE.durumlar == frozenset(ATOLYE_DURUMLARI)
    assert sm.KIRALAMA.durumlar == frozenset(KIRALAMA_DURUMLARI)
    assert sm.EGITIM_PLANI.durumlar == frozenset(PLAN_DURUMLARI)
    assert sm.DUZELTICI_FAALIYET.durumlar == frozenset(DUZELTICI_DURUMLARI)
    assert sm.STOK_SAYIM.durumlar == frozenset(SAYIM_DURUMLARI)
    assert sm.PARCA_TALEBI.durumlar == frozenset(PARCA_TALEP_DURUMLARI)


def test_atolye_terminalleri_acik_olmayan_kumesi() -> None:
    assert sm.ATOLYE.terminaller == frozenset(ATOLYE_ACIK_OLMAYAN)


def test_teklif_makinesi_yalniz_birimli_teklif_durumlari() -> None:
    """Birimli teklif makinesi CHECK kümesinin alt kümesidir; satış durumları
    (revizyon, süre dolumu, siparişe dönüşme) makinede YOK (E07 kontrol)."""
    assert sm.TEKLIF.durumlar <= frozenset(TEKLIF_DURUMLARI)
    assert {"ONAYLANDI", "IPTAL"} <= frozenset(TEKLIF_DURUMLARI)
    assert not {"REVIZE_EDILDI", "SURESI_DOLDU", "SIPARISE_DONUSTU"} & sm.TEKLIF.durumlar
    assert sm.TEKLIF.sonraki("IPTAL") == frozenset()
    assert "IPTAL" in sm.TEKLIF.sonraki("KABUL")


def test_egitim_plani_ikinci_ertelemeyi_makineden_gecirmez() -> None:
    assert "ERTELENDI" not in sm.EGITIM_PLANI.sonraki("ERTELENDI")
    assert sm.EGITIM_PLANI.sonraki("TAMAMLANDI") == frozenset({"PLANLANDI"})


def test_kiralama_kurulumlu_son_iade_once_toplandi() -> None:
    assert "DEPOYA_ALINDI" not in sm.KIRALAMA.sonraki("KURULUM_YAPILDI")
    assert "DEPOYA_ALINDI" in sm.KIRALAMA.sonraki("SEVK_EDILDI")


def test_atolye_iptali_servis_isi_makinesinde_mumkun() -> None:
    """E05-D02: atölye iptali servis işini ATOLYEDE'den IPTAL'e taşır."""
    assert "IPTAL" in sm.SERVIS_IS_EMRI.sonraki("ATOLYEDE")
    assert "ATOLYEDE" in SERVIS_DURUMLARI


def test_stok_hareket_turu_yon_eslemesi_tam() -> None:
    assert set(SERVIS_HAREKET_YONU) | {"TERS_KAYIT"} == set(SERVIS_HAREKET_TURLERI)
    for tur, (neden, isaret) in SERVIS_HAREKET_YONU.items():
        assert neden in ("GIRIS", "CIKIS", "SAYIM", "TRANSFER"), tur
        assert isaret in (1, -1), tur


def test_sla_tohumu_plan_degerleri() -> None:
    assert dict(VARSAYILAN_SLA_POLITIKALARI) == {"KRITIK": 12, "YUKSEK": 24, "NORMAL": 72}
    assert {o for o, _ in VARSAYILAN_SLA_POLITIKALARI} == set(ONCELIKLER)


def test_kanca_imzalari_clock_tasir() -> None:
    """Dalga 1 doğrulayıcı talebi: `ekip_degisti` (ve SLA için
    `oncelik_birim_degisti`) Clock taşır."""
    assert "clock" in inspect.signature(kancalar.ekip_degisti).parameters
    assert "clock" in inspect.signature(kancalar.oncelik_birim_degisti).parameters
    assert "clock" in inspect.signature(kancalar.durum_degisti).parameters


def test_kanca_kayit_sirasi_sabit() -> None:
    """`durum_degisti`: sla → parca → kiralama; `is_olusturuldu`: sla → tekrar_ariza."""
    kaynak = (
        Path(kancalar.__file__).with_name("__init__.py").read_text(encoding="utf-8").splitlines()
    )

    def sira(modul: str) -> int:
        return next(
            i
            for i, s in enumerate(kaynak)
            if s.startswith(f"from app.services.teknik_servis import {modul} ")
        )

    assert sira("bekletme") < sira("bakim_formu") < sira("sla") < sira("parca") < sira("kiralama")
    assert sira("sla") < sira("tekrar_ariza")
    assert sira("is_emirleri") < sira("atolye")
