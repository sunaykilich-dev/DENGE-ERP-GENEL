"""Göç-2 (D3-G, TS-205…208) saf kuralları — DB'siz.

- Atölye sağlık raporu yedi bölümü üretir; pilot verisi yoksa göç gerekmez.
- Kiralama uzlaştırması dört uyumsuzluk türünün HER BİRİNİ bulur, eski
  "Teklif" → TALEP, aşama geçmişi varsa son aşama durumdur.
- SLA geri doldurmada serbest metin bekleme nedeni anahtar kelimeyle eşlenir.
- Parça metni karakter karakter korunur; olay özeti 500 karakterle sınırlı.
- Göç-2 dışa aktarım betikleri yalnız SELECT'tir ve kişisel iletişim/parola almaz.
"""

import re
from pathlib import Path

from app.migration import atolye_saglik, servis_goc_parca, servis_sla_geri_doldur
from app.migration.servis_kaynak import KaynakDizini
from app.services.imports import kiralama_goc
from app.services.teknik_servis import ad_esleme

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "goc_v1_d3"
SQL_DIZINI = Path(__file__).resolve().parents[2] / "app" / "migration" / "teknik_servis" / "sql"


def test_atolye_saglik_yedi_bolum():
    kisiler = {ad_esleme.normal_ad("Ali Veli"): 7}
    r = atolye_saglik.saglik_raporu(KaynakDizini(FIXTURE), kisiler)
    assert r.kayit_sayisi == 5 and r.goc_gerekli
    s = r.sayilar
    assert set(s) == {kod for kod, _ in atolye_saglik.BOLUMLER}
    # 703 (Teslim Edildi / iş açık) ve 705 (İptal / iş açık).
    assert s["DURUM_UYUSMAZLIGI"] == 2
    assert [x[0] for x in r.bolumler["IPTAL_ACIK_IS"]] == ["AT-0005"]
    assert [x[0] for x in r.bolumler["SERI_FARKI"]] == ["AT-0003"]  # X-9 ≠ S-202
    assert [x[1] for x in r.bolumler["ESLESMEYEN_ATANAN"]] == ["Bilinmeyen Usta"]
    yetim = {x[2] for x in r.bolumler["YETIM_IS"]}
    assert yetim == {"Atölye kaydının iş emri dökümde yok", "Atölye işinin atölye kaydı yok"}
    assert r.bolumler["MUKERRER_ACIK_SERI"][0][1] == 2  # T-1 iki açık kayıtta
    dagilim = {x[0]: x[1] for x in r.bolumler["DURUM_DAGILIMI"]}
    assert dagilim["Onarımda"] == "ONARIMDA" and dagilim["Garip Durum"] == "EŞLENEMEDİ"
    assert atolye_saglik.rapor_xlsx(r)[:2] == b"PK"


def test_atolye_saglik_pilot_yoksa_goc_yok(tmp_path):
    r = atolye_saglik.saglik_raporu(KaynakDizini(tmp_path), {})
    assert r.kayit_sayisi == 0 and not r.goc_gerekli and r.notlar


def test_kiralama_dort_uyumsuzluk_turu():
    u = kiralama_goc.uzlastirma(KaynakDizini(FIXTURE))
    assert u.sayilar == {
        "TAHSISSIZ_KIRADA": 1,
        "KAPALI_KIRALAMAYA_BAGLI": 1,
        "ENVANTERSIZ_SERI": 1,
        "DURUM_ASAMA_UYUMSUZ": 1,
    }
    assert u.satirlar["TAHSISSIZ_KIRADA"][0]["ref"] == "RentalInventory:1003"
    assert u.satirlar["KAPALI_KIRALAMAYA_BAGLI"][0]["ref"] == "RentalInventory:1001"
    assert u.satirlar["ENVANTERSIZ_SERI"][0]["seri"] == "SN-404"
    assert u.satirlar["DURUM_ASAMA_UYUMSUZ"][0]["kiralama"] == "KR-0011"
    yeni = {k["kiralama"]: k["yeni_durum"] for k in u.kiralamalar}
    assert yeni == {"KR-0011": "KAPANDI", "KR-0012": "DEVREYE_ALINDI", "KR-0013": "TALEP"}
    assert u.envanter_uyumsuz == {
        "RentalInventory:1001": ["KAPALI_KIRALAMAYA_BAGLI"],
        "RentalInventory:1003": ["TAHSISSIZ_KIRADA"],
    }
    assert kiralama_goc.uzlastirma_xlsx(u)[:2] == b"PK"
    satirlar = {s[0]: s for s in kiralama_goc.envanter_karar_satirlari(KaynakDizini(FIXTURE), u)}
    assert satirlar["RentalInventory:1003"][8] == "TAHSISSIZ_KIRADA"
    assert satirlar["RentalInventory:1004"][8] is None
    assert satirlar["RentalInventory:1004"][7] == "HAZIR"
    assert satirlar["RentalInventory:1003"][7] is None  # Kirada girişte seçilmez
    assert satirlar["RentalInventory:1005"][4] == 5 and satirlar["RentalInventory:1005"][3] is None


def test_kiralama_uzlastirma_komut_satiri_iki_dosya(tmp_path):
    from app.migration import kiralama_uzlastirma

    cikti = tmp_path / "kiralama.xlsx"
    assert kiralama_uzlastirma.komut_satiri(["--kaynak", str(FIXTURE), "--cikti", str(cikti)]) == 0
    assert cikti.read_bytes()[:2] == b"PK"
    assert (tmp_path / "kiralama_kiralik_envanter.xlsx").read_bytes()[:2] == b"PK"


def test_bekleme_nedeni_anahtar_kelime():
    esle = servis_sla_geri_doldur.bekleme_nedeni_esle
    assert esle("Malzeme bekleniyor") == "MALZEME"
    assert esle("Müşteri ONAYI") == "MUSTERI_ONAYI"
    assert esle("müşteri yerinde yok") == "DIGER"


def test_parca_metni_karakter_karakter_ve_ozet_siniri():
    isler = {"WorkOrders:201": {"id": 1}, "WorkOrders:202": {"id": 2}}
    ss = servis_goc_parca.hazirla(KaynakDizini(FIXTURE), isler)
    mdi = next(s for s in ss if s.kaynak_tablo == "MaintenanceDeviceItems")
    assert mdi.kaynak == 4  # boş parça alanı kayıt sayılmaz
    assert {t.ref for t in mdi.aktarilacak} == {
        "MaintenanceDeviceItems:501",
        "MaintenanceDeviceItems:504",
    }
    assert {r for r, _ in mdi.karantina} == {
        "MaintenanceDeviceItems:502",
        "MaintenanceDeviceItems:505",
    }
    t501 = next(t for t in mdi.aktarilacak if t.ref.endswith(":501"))
    assert t501.metin == '2 adet sigorta, 1 röle; "kablo" 3m  '
    uzun = next(t for t in mdi.aktarilacak if t.ref.endswith(":504"))
    assert len(uzun.metin) > 500
    assert len(servis_goc_parca.ozet_metni("Bakım", uzun.metin)) == 500


def test_goc2_disa_aktarim_yalniz_select_ve_kisisel_veri_yok():
    yasak = re.compile(
        r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE)\b", re.I
    )
    dosyalar = sorted(SQL_DIZINI.glob("goc2_*.sql"))
    assert len(dosyalar) == 18
    for dosya in dosyalar:
        govde = re.sub(r"/\*.*?\*/|--[^\n]*", "", dosya.read_text(encoding="utf-8-sig"), flags=re.S)
        assert not yasak.search(govde), dosya.name
        assert "SELECT" in govde.upper()
        for kolon in ("PasswordHash", "PasswordSalt", "Phone", "Email", "Address"):
            assert kolon.lower() not in govde.lower(), (dosya.name, kolon)
