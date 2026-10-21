"""Göç eşleme tablolarının gerçek veriye karşı tutarlılığı (DB gerektirmez)."""

import pytest

from app.migration.esleme import (
    BAYI_BELIRSIZ,
    BAYI_DEGIL,
    BAYI_ISARETI,
    BIRLESTIRILMEYECEK,
    MONTAJ_NOKTASI_BIRLESTIRME,
    URUN_DEGIL,
    URUN_ESLEME,
    URUN_KARTLARI,
    firma_ayristir,
    kaynak_ref,
    montaj_noktasi_kanonik,
)


class TestFirmaAyristirma:
    def test_bayi_cikarilir(self):
        assert firma_ayristir("BZL OTOMOTİV (GAZİANTEP EVA)") == (
            "BZL OTOMOTİV",
            "GAZİANTEP EVA",
            None,
        )

    def test_parantezsiz_ad_degismez(self):
        assert firma_ayristir("ESENYURT BELEDİYESİ") == ("ESENYURT BELEDİYESİ", None, None)

    def test_aciklama_bayi_sayilmaz(self):
        """`ALTINORDU (ORDU BELEDİYESİ)` bir açıklama; bayi uydurulmamalı."""
        ad, bayi, neden = firma_ayristir("ALTINORDU (ORDU BELEDİYESİ)")
        assert ad == "ALTINORDU (ORDU BELEDİYESİ)"
        assert bayi is None and neden is None

    def test_yazim_hatasi_ayni_bayiye_gider(self):
        assert firma_ayristir("X (GAZİANTP EVA)")[1] == "GAZİANTEP EVA"

    def test_belirsiz_karantinaya_duser(self):
        _, bayi, neden = firma_ayristir("ENVER SEDAT ÜNVER (CKR LOJİSTİK SATIŞI)")
        assert bayi is None
        assert neden and "belirsiz" in neden.lower()

    def test_taninmayan_parantez_karantinaya_duser(self):
        _, bayi, neden = firma_ayristir("FOO (HİÇ GÖRÜLMEMİŞ)")
        assert bayi is None
        assert neden and "tanınmadı" in neden


class TestMontajNoktasiBirlestirme:
    def test_bes_birlestirme_tanimli(self):
        assert len(MONTAJ_NOKTASI_BIRLESTIRME) == 5

    def test_kanonik_ad(self):
        assert montaj_noktasi_kanonik("ANTALYA RAMAZAN ÇULLU") == "ANTALYA RAMAZAN CULLU"
        assert montaj_noktasi_kanonik("BİLİNMEYEN NOKTA") == "BİLİNMEYEN NOKTA"

    def test_birlestirme_hedefi_kendisi_birlesmez(self):
        """Zincir olmamalı: A→B ve B→C aynı anda tanımlıysa sonuç belirsizleşir."""
        for hedef in MONTAJ_NOKTASI_BIRLESTIRME.values():
            assert hedef not in MONTAJ_NOKTASI_BIRLESTIRME

    def test_yanlis_pozitif_kayit_altinda(self):
        """Aynı telefonu taşıyan ama farklı olan çift açıkça işaretli olmalı ki
        betik tekrar tekrar önermesin."""
        assert frozenset({"BALIKESİR KOÇ OTO-SELÇUK KOÇ", "BURSA 3D MOBİL"}) in BIRLESTIRILMEYECEK


class TestUrunEsleme:
    def test_blokaj_ayri_urun_degil(self):
        """Blokaj bir montaj özelliği (röle ile marş kesme), ürün değil."""
        assert URUN_ESLEME["L300 BLK."] == ("L300", True)
        assert URUN_ESLEME["L300"] == ("L300", False)
        assert URUN_ESLEME["GS900 BLOKAJLI"][0] == URUN_ESLEME["GS900"][0]

    def test_yazim_varyantlari_ayni_urune_gider(self):
        for varyant in ("L300BLK", "L300BLK.", "L300 BLK."):
            assert URUN_ESLEME[varyant][0] == "L300"
        for varyant in ("GS900 STD", "GS900STD", "GS900"):
            assert URUN_ESLEME[varyant][0] == "GS900"

    def test_ek_kamera_seri_no_ile_tanimli(self):
        """Dahua HMW3200LP analog (HDCVI) — modemi yok, IMEI'si fiziksel
        olarak yok. 898 montaj satırının 898'inde boş."""
        kart = next(k for k in URUN_KARTLARI if k["code"] == "DAHUA-HMW3200LP")
        assert kart["identity_kind"] == "SERI_NO"
        assert kart["requires_parent"] is True

    def test_takip_cihazlari_imei_ile(self):
        for kod in ("L300", "GS900", "DAHUA-CDR8213", "H20P"):
            kart = next(k for k in URUN_KARTLARI if k["code"] == kod)
            assert kart["identity_kind"] == "IMEI"

    def test_her_eslesme_bir_urun_kartina_isaret_eder(self):
        kodlar = {k["code"] for k in URUN_KARTLARI}
        for ham, (kod, _) in URUN_ESLEME.items():
            assert kod in kodlar, f"{ham} → {kod} kartı tanımsız"

    def test_urun_olmayanlar_ayri_tutulur(self):
        assert "ARIZA ONARIM" in URUN_DEGIL
        assert "ARIZA ONARIM" not in URUN_ESLEME
        assert URUN_DEGIL["VF1RJK00670151708"] == "sase_no"


class TestKaynakRef:
    def test_sabit_uzunluk(self):
        uzun = "D YEDİ YİRMİDÖRT BİLİŞİM HİZMETLERİ TİCARET ANONİM ŞİRKETİ VE ORTAKLARI"
        assert len(kaynak_ref("musteri", uzun)) <= 64

    def test_turkce_varyantlari_ayni_kimlige_duser(self):
        """`KARDEŞLER REFTEKE` ve `KARDESLER REFTEKE` aynı firma."""
        assert kaynak_ref("musteri", "KARDEŞLER REFTEKE") == kaynak_ref(
            "musteri", "KARDESLER REFTEKE"
        )

    def test_farkli_turler_carismaz(self):
        assert kaynak_ref("musteri", "ACME") != kaynak_ref("bayi", "ACME")

    def test_kararli(self):
        assert kaynak_ref("nokta", "HOPA ELEKTRONİK") == kaynak_ref("nokta", "HOPA ELEKTRONİK")


@pytest.mark.parametrize("kume", [BAYI_ISARETI.keys(), BAYI_DEGIL, BAYI_BELIRSIZ.keys()])
def test_bayi_kategorileri_ortusmez(kume):
    """Bir parantez içeriği yalnız BİR kategoriye ait olmalı; aksi halde
    davranış tanım sırasına bağlı kalır."""
    diger = (set(BAYI_ISARETI) | BAYI_DEGIL | set(BAYI_BELIRSIZ)) - set(kume)
    assert not (set(kume) & diger)
