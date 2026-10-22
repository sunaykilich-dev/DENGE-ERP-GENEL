"""Servis rapor tanımları birim testleri (TS-181, TS-182, E12-06, E12-09).

- Rapor KPI'ları panelin TEK kayıt defterinde (`grup="RAPOR"`, dönemli),
  panel kutusu olarak çizilmez; tanım metinleri dolu.
- `servis_rapor.personel` yalnız SERVIS_YONETICI / SERVIS_SEF (+ADMIN);
  YONETIM'e otomatik inmez (kontrol B17: "her izin bir rolde" testi yetmez).
- Kişisel sütun izinsiz kullanıcının şemasında HİÇ yoktur.
- Rapor aralığı doğrulaması (ters sıra, 24 ay, geçersiz gün) ve tipli Excel
  (sıfırlı/19 haneli seri METİN, formül metin, adlı tablo).
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.models.teknik_servis import GECIKME_NEDENLERI
from app.permissions import ROLES
from app.services import export
from app.services.teknik_servis import panel, rapor_hesap
from app.services.teknik_servis import rapor_tanimlari as rt


class _Kisi:
    def __init__(self, *izinler: str) -> None:
        self.izinler = set(izinler)

    def has(self, kod: str) -> bool:
        return kod in self.izinler


def test_rapor_kpileri_tek_kayitta_ve_donemli():
    assert rt.RAPOR_KPI_BOLUMU, "rapor KPI kaydı boş"
    for kod, bolum in rt.RAPOR_KPI_BOLUMU.items():
        tanim = panel.KPI_TANIMLARI[kod]
        assert tanim.grup == "RAPOR" and tanim.donemsel, kod
        assert len(tanim.tanim) > 20, kod
        assert bolum in rt.BOLUMLER
    assert "RAPOR" in panel.PANEL_DISI_GRUPLAR
    for olcu in rt.OLCULER.values():
        for kod in (olcu.pay, olcu.payda):
            assert kod is None or kod in panel.KPI_TANIMLARI


def test_rapor_kpi_kaydi_grup_ve_donem_ister():
    yanlis = panel.KpiTanimi("x_test", "X", "Test tanımı uzun metin", lambda s, *a: s)
    with pytest.raises(ValueError):
        rt.rapor_kpi_kaydet(yanlis, "GENEL")


def test_personel_izni_yalniz_yonetici_ve_sefte():
    sahipler = {kod for kod, (_, izinler, _) in ROLES.items() if "servis_rapor.personel" in izinler}
    assert sahipler == {"ADMIN", "SERVIS_YONETICI", "SERVIS_SEF"}
    assert "servis_rapor.personel" not in ROLES["YONETIM"][1]
    # Servis rollerine mobilite rapor izni verilmez (KD-06).
    for kod in ("SERVIS_YONETICI", "SERVIS_SEF", "SERVIS_TEKNISYEN"):
        assert "rapor.gor" not in ROLES[kod][1] and "rapor.disaaktar" not in ROLES[kod][1]


def test_kisisel_sutunlar_izinsizde_yok():
    kisisiz = _Kisi("servis.gor", "servis_rapor.gor")
    kisili = _Kisi("servis.gor", "servis_rapor.gor", "servis_rapor.personel")
    for sema in rt.SUTUN_SEMALARI:
        izinsiz = rt.sutunlar(sema, kisisiz)
        assert all(not s.kisisel for s in izinsiz), sema
        assert len(rt.sutunlar(sema, kisili)) == len(rt.SUTUN_SEMALARI[sema])
        for s in rt.SUTUN_SEMALARI[sema]:
            assert s.tip in export.SUTUN_TIPLERI, (sema, s)
    assert rt.sutunlar("personel_kpi", kisisiz) == []
    basliklar = {s.baslik for s in rt.sutunlar("is_listesi", kisisiz)}
    assert "Saha Telefonu" not in basliklar and "Saha Yetkilisi" not in basliklar
    boyutlar = {b["kod"] for b in rt.tanimlar(kisisiz)["boyutlar"]}
    assert "teknisyen" not in boyutlar


def test_gecikme_nedeni_adlari_tek_sozluk():
    assert set(rapor_hesap.GECIKME_NEDENI_ADLARI) == set(GECIKME_NEDENLERI)


@pytest.mark.parametrize(
    "donem",
    ["20260331-20260301", "20240101-20260131", "20260230-20260301", "2026-03-01", "x"],
)
def test_rapor_araligi_gecersiz(donem):
    with pytest.raises(panel.PanelHatasi):
        panel.donem_dogrula(donem)


def test_rapor_araligi_gecerli_ve_ay_ekle():
    assert panel.aralik_gunleri("20260301-20260331") == (date(2026, 3, 1), date(2026, 3, 31))
    assert panel.donem_dogrula("20240201-20260131") == "20240201-20260131"  # 24 ay - 1 gün
    assert panel.ay_ekle(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert panel.ay_ekle(date(2026, 3, 1), -3) == date(2025, 12, 1)
    assert panel.ay_ekle(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_tipli_excel_seri_metin_formul_ve_tablo():
    sayfa = export.Sayfa(
        "Veri_IsEmirleri",
        [export.Sutun("Seri No"), export.Sutun("Not"), export.Sutun("Kişi-Saat", "ondalik")],
        [["0012345", "=1+1", 1.5], ["1234567890123456789", "+905321112233", None]],
        tablo_adi="Veri_IsEmirleri",
        ust_bilgi=[],
    )
    bos = export.Sayfa("Bos", [export.Sutun("A")], [], tablo_adi="Bos_Tablo")
    kitap = load_workbook(BytesIO(export.sayfalari_xlsx([sayfa, bos])))
    ws = kitap["Veri_IsEmirleri"]
    assert ws["A2"].value == "0012345" and ws["A2"].data_type == "s"
    assert ws["A3"].value == "1234567890123456789" and ws["A3"].data_type == "s"
    assert ws["B2"].value == "=1+1" and ws["B2"].data_type == "s"
    assert ws["C2"].value == 1.5
    assert ws.tables["Veri_IsEmirleri"].ref == "A1:C3"
    assert kitap["Bos"]["A2"].value == "Kayıt yok"
    assert kitap["Bos"].tables["Bos_Tablo"].ref == "A1:A2"
