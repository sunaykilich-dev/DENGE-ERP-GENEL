"""Personel KPI'sı: saha rolü beklenen roller ve birim kutuları (UI/UX I2).

- "Saha rolü girilmemiş" yalnız saha/servis rollerindeki personeli sayar; ön yüz
  satır rozeti için sunucunun `saha_rolu_bekleniyor` alanını kullanır (tek liste).
- Birim kutuları yalnız etkin şirketin birimleridir ve Türkçe adı taşır.
"""

from __future__ import annotations

from app.permissions import ATANABILIR_SAHA_ROLLERI, BIRIMLER, ROLES, SAHA_ROLU_BEKLENEN_ROLLER
from app.services.teknik_servis.personel import kpi_tanimlari


def test_beklenen_roller_tanimli_roller():
    assert set(SAHA_ROLU_BEKLENEN_ROLLER) <= set(ROLES)
    for ofis in ("FINANS_YONETICI", "SATIS", "DEPO", "IK", "YONETIM", "MUHASEBE_DESTEK"):
        assert ofis not in SAHA_ROLU_BEKLENEN_ROLLER


def test_birim_kutulari_etkin_sirketle_sinirli_ve_turkce():
    kutular = {t.kod: t.baslik for t in kpi_tanimlari(frozenset({"GUVENLIK", "BARIYER"}))}
    birim_kutulari = {k for k in kutular if k.startswith("SAHA_") and k != "SAHA_ROLU_EKSIK"}
    assert birim_kutulari == {"SAHA_GUVENLIK", "SAHA_BARIYER"}
    assert kutular["SAHA_GUVENLIK"].startswith(BIRIMLER["GUVENLIK"])
    assert "SAHA_ROLU_EKSIK" in kutular and "BIRIMSIZ" in kutular


def test_suzgecsiz_kullanicida_butun_birimler():
    kodlar = {t.kod for t in kpi_tanimlari(None)}
    assert {f"SAHA_{b}" for b in BIRIMLER} <= kodlar


def test_atanabilirlik_kurali_degismedi():
    assert ATANABILIR_SAHA_ROLLERI == ("SEF", "TEKNISYEN", "STAJYER")
