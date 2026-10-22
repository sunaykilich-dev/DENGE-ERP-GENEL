"""Göç-1 saf kuralları (TS-170…177) — veritabanı gerektirmez.

Kilitlenen kurallar: tip/teslim tarihi tekleştirmesi (E03-10), POC durumunun
çözüm kanalına taşınması (E01 K2), yerel saat → UTC, uydurma yapılmaması
(tanınmayan değer karantina/uyarı, tarih/adet uydurulmaz), deterministik
müşteri eşleştirmesi (belirsiz → insana), uzlaşma eşitliği
`kaynak = aktarılan + karantina + reddedilen`, T-SQL betiklerinin yalnız
SELECT olması.
"""

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.migration import bakim_sozlesme, hazirla_kutuk, servis_goc, servis_plan, servis_zaman
from app.migration.kaynak_kutuk import kutuk_satirlari
from app.migration.servis_kaynak import KaynakDizini, KaynakHatasi, kaynak_ref, yerel_an
from app.services.teknik_servis import ad_esleme
from app.services.teknik_servis.veri_kalitesi import HesapEsleyici

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "goc_v1"
SQL_DIZINI = Path(__file__).resolve().parents[2] / "app" / "migration" / "teknik_servis" / "sql"


def _esleyici() -> HesapEsleyici:
    # unvan_anahtari("Akyaka Park AVM") ve "Örnek Lojistik" → tek hesap; "Ortak" iki hesap.
    from app.services.teknik_servis.ana_veri import unvan_anahtari

    return HesapEsleyici(
        unvan={
            unvan_anahtari("Akyaka Park AVM"): [1],
            unvan_anahtari("Örnek Lojistik"): [2],
            unvan_anahtari("Ortak Ad"): [3, 4],
        },
        takma={unvan_anahtari("AKYAKA AVM GÜVENLİK"): (1, 10)},
        tesis={unvan_anahtari("Depo Girişi"): [(2, 20)]},
    )


class TestKaynakOkuma:
    def test_yerel_saat_utc_ye_cevrilir(self):
        # Kış saati yok: Türkiye UTC+3. 09:30 yerel = 06:30 UTC.
        assert yerel_an("2026-01-05T09:30:00") == datetime(2026, 1, 5, 6, 30, tzinfo=UTC)
        assert yerel_an("2026-01-05 09:30:00.123") == datetime(2026, 1, 5, 6, 30, tzinfo=UTC)
        assert yerel_an("") is None
        with pytest.raises(ValueError):
            yerel_an("05/01/2026 aa")

    def test_eksik_dosya_sessizce_bos_sayilmaz(self, tmp_path):
        with pytest.raises(KaynakHatasi):
            KaynakDizini(tmp_path).tablo("WorkOrders")
        assert KaynakDizini(tmp_path).tablo("WorkOrderDevices", zorunlu=False) == []

    def test_kaynak_ref_bicimi(self):
        assert kaynak_ref("WorkOrders", 101) == "WorkOrders:101"
        with pytest.raises(KaynakHatasi):
            kaynak_ref("X" * 60, 123456)


class TestKutukHazirlama:
    def test_tip_tekillestirme(self):
        assert hazirla_kutuk.ekipman_tipi("X-Ray") == "XRAY"
        assert hazirla_kutuk.ekipman_tipi("XRAY Cihazı") == "XRAY"
        assert hazirla_kutuk.ekipman_tipi("Kapı Tipi Metal Dedektörü") == "KAPI_DEDEKTORU"
        assert hazirla_kutuk.ekipman_tipi("El Tipi Dedektör") == "EL_DEDEKTORU"
        assert hazirla_kutuk.ekipman_tipi("Turnike") is None

    def test_teslim_tarihi_metinden_uydurmadan(self):
        assert hazirla_kutuk.excel_gun_tarihi("44083") == date(2020, 9, 9)
        assert hazirla_kutuk.excel_gun_tarihi("15.03.2021") == date(2021, 3, 15)
        assert hazirla_kutuk.excel_gun_tarihi("00.00.2015") is None
        assert hazirla_kutuk.excel_gun_tarihi("2019") is None
        assert hazirla_kutuk.excel_gun_tarihi(None) is None

    def test_fixture_uzlasma_ve_uyarilar(self):
        sonuc = hazirla_kutuk.hazirla(kutuk_satirlari(KaynakDizini(FIXTURE)), _esleyici())
        assert sonuc.kaynak == 6
        assert len(sonuc.aktarilacak) == 5
        assert len(sonuc.reddedilen) == 1  # kimliksiz satır
        assert sonuc.tutarli
        uyarilar = sonuc.uyari_sayilari()
        assert uyarilar["MUKERRER_SERI"] == 2  # KD-777 iki aktif satırda; ikisi de yüklenir
        assert uyarilar["SERISIZ"] == 1
        assert uyarilar["TIP_TANIMSIZ"] == 1
        assert uyarilar["TESLIM_TARIHI_OKUNAMADI"] == 2  # "2019" ve "00.00.2015"
        satirlar = {r["source_ref"]: r for r in sonuc.aktarilacak}
        ilk = satirlar["SecurityDevices:1"]
        assert ilk["delivery_date"] == date(2020, 9, 9)
        assert ilk["delivery_date_raw"] == "44083"
        assert ilk["serial_no"] == "00123-A"  # baştaki sıfır korunur
        assert ilk["account_id"] == 1
        assert satirlar["SecurityDevices:3"]["address_id"] == 20  # tesis adıyla
        pasif = satirlar["SecurityDevices:5"]
        assert pasif["is_active"] is False and pasif["lifecycle_status"] == "HURDA"
        assert pasif["equipment_type"] == "DIGER_GUVENLIK"
        assert pasif["account_id"] is None
        assert pasif["customer_name_raw"] == "Bilinmeyen Müşteri Ltd"


class TestMusteriEsleyici:
    def test_kesin_yontemler_ve_belirsiz(self):
        es = _esleyici()
        assert es.esle("Akyaka Park AVM").account_id == 1
        takma = es.esle("Akyaka AVM Güvenlik")
        assert (takma.account_id, takma.address_id, takma.yontem) == (1, 10, "TAKMA_AD")
        belirsiz = es.esle("ORTAK AD")
        assert belirsiz.belirsiz and belirsiz.account_id is None and belirsiz.adaylar == (3, 4)
        assert es.esle("Hiç Yok").account_id is None
        tesisle = es.esle(None, "Depo Girişi")
        assert (tesisle.account_id, tesisle.address_id) == (2, 20)


class TestServisIsiEsleme:
    def test_poc_durumu_kanala(self):
        assert servis_goc.durum_esle("Telefonla Destek") == "ISLEMDE"
        assert servis_goc.kanal_esle("Telefonla Destek") == "TELEFON"
        assert servis_goc.kanal_esle("Uzaktan Müdahale") == "UZAKTAN"
        assert servis_goc.kanal_esle("Yerinde Müdahale") == "YERINDE"

    def test_kd13_kargoda_ve_test_kontrol(self):
        assert servis_goc.durum_esle("Kargoda") == "ATOLYEDE"
        assert servis_goc.durum_esle("Test / Kontrol") == "ISLEMDE"
        assert servis_goc.durum_esle("Garip Durum") is None

    def test_kapsam_disi_turler_karantina(self):
        assert servis_goc.tur_esle("Planlı Bakım")[0] is None
        assert servis_goc.tur_esle("Atölye Tamir")[0] is None
        assert servis_goc.tur_esle("Saha Arızası")[0] == "ARIZA"
        tur, neden = servis_goc.tur_esle("Uydurma Tür")
        assert tur is None and "Eşlenemeyen" in neden

    def test_fixture_hazirlama(self):
        sonuc = servis_goc.hazirla(KaynakDizini(FIXTURE), _esleyici())
        assert sonuc.kaynak == 9
        assert len(sonuc.aktarilacak) == 6
        assert len(sonuc.karantina) == 2
        assert len(sonuc.reddedilen) == 1
        assert sonuc.tutarli
        isler = {t.ref: t for t in sonuc.aktarilacak}
        kapali = isler["WorkOrders:101"]
        assert kapali.durum == "KAPATILDI" and kapali.eski_no == "SRV-202601-0001"
        assert kapali.oncelik == "KRITIK"
        assert kapali.seriler == ["00123-A", "00123-B"]  # tekrar eden seri tek
        assert kapali.tamamlanma == datetime(2026, 1, 6, 9, 0, tzinfo=UTC)
        assert kapali.kanal is None  # kanal uydurulmaz
        assert [o["yeni_durum"] for o in kapali.olaylar] == [
            "MUSTERI_TALEBI",
            "SAHADA",
            "TAMAMLANDI",
            "KAPATILDI",
        ]
        telefon = isler["WorkOrders:102"]
        assert (telefon.durum, telefon.kanal, telefon.tur) == ("TAMAMLANDI", "TELEFON", "DESTEK")
        assert isler["WorkOrders:103"].durum == "ISLEMDE"
        bekleyen = isler["WorkOrders:107"]
        assert bekleyen.durum == "BEKLEMEDE" and bekleyen.onceki_durum == "SAHADA"
        nedenler = dict(sonuc.karantina)
        assert "Planlı bakım" in nedenler["WorkOrders:104"]
        assert "Garip Durum" in nedenler["WorkOrders:105"]
        assert sonuc.uyari_sayilari()["SONUCSUZ_KAPALI"] == 2  # 101 ve 108
        assert len(servis_goc.karantina_excel_satirlari(sonuc)) == 2


class TestPlanVeZaman:
    def _isler(self):
        an = datetime(2026, 1, 13, 12, 0, tzinfo=UTC)
        return {
            f"WorkOrders:{i}": {"id": i, "status": "X", "closed_at": an if i == 108 else None}
            for i in (101, 102, 103, 106, 107, 108)
        }

    def test_plan_cift_aktif_ve_kapali_iken_planli_raporlanir(self):
        sonuc = servis_plan.hazirla(KaynakDizini(FIXTURE), self._isler())
        assert sonuc.kaynak == 5 and sonuc.tutarli
        assert len(sonuc.karantina) == 1  # WO104 aktarılmadı
        planlar = {t.ref: t for t in sonuc.aktarilacak}
        assert planlar["WorkOrderPlans:702"].aktif is False
        assert planlar["WorkOrderPlans:702"].change_type == "ILK_PLAN"
        assert planlar["WorkOrderPlans:703"].aktif is True
        assert planlar["WorkOrderPlans:703"].change_type == "YENIDEN_PLAN"
        assert planlar["WorkOrderPlans:702"].duration_min == servis_plan.VARSAYILAN_SURE_DK
        u = sonuc.uyari_sayilari()
        assert u["CIFT_AKTIF_PLAN"] == 2 and u["KAPALI_IKEN_PLANLI"] == 1
        assert u["SURE_VARSAYILAN"] == 1

    def test_zaman_faaliyet_ve_karantina(self):
        kayitlar, oturumlar = servis_zaman.hazirla(KaynakDizini(FIXTURE), self._isler())
        assert kayitlar.kaynak == 5 and kayitlar.tutarli
        assert len(kayitlar.karantina) == 1  # WO104
        assert {t.faaliyet for t in kayitlar.aktarilacak} == {"SAHA", "YOL", "BEKLEME", "DIGER"}
        assert oturumlar.kaynak == 1 and oturumlar.aktarilacak[0].faaliyet == "MOLA"
        assert servis_zaman.faaliyet_esle("İşçilik") is None  # ISCILIK yok (KD-24)


class TestBakimTeyitListesi:
    def test_urun_ve_donem_ayristirma(self):
        assert bakim_sozlesme.urun_adetleri("9 X-RAY + 8 KAPI DEDEKTÖRÜ") == {"xray": 9, "kapi": 8}
        assert bakim_sozlesme.urun_adetleri("X-RAY (2)") == {"xray": 2, "kapi": None}
        assert bakim_sozlesme.donem_coz("01.01.2026 - 31.12.2026") == (
            date(2026, 1, 1),
            date(2026, 12, 31),
        )
        assert bakim_sozlesme.donem_coz("2026 yılı") == (None, None)

    def test_ucret_kolonlari_varsayilan_yok(self):
        satirlar, red = bakim_sozlesme.teyit_satirlari(
            KaynakDizini(FIXTURE).tablo("MaintenanceContracts")
        )
        assert red == []
        assert len(satirlar) == 3
        assert all("12.500 TL" not in [str(h) for h in s] for s in satirlar)
        ucretli, _ = bakim_sozlesme.teyit_satirlari(
            KaynakDizini(FIXTURE).tablo("MaintenanceContracts"), ucret=True
        )
        assert any("12.500 TL" in [str(h) for h in s] for s in ucretli)
        # Pasif eski sözleşme PASIF gelir; dönemi eksik olan teyit bekler.
        assert satirlar[2][12] == "PASIF"
        assert "eksik" in satirlar[1][13]


class TestAdEsleme:
    def test_normal_ad_ve_benzerlik(self):
        assert ad_esleme.normal_ad("  ALİ   veli ") == ad_esleme.normal_ad("Ali Veli")
        assert ad_esleme.benzerlik("Ali Veli", "Ali Veli") == 1.0
        assert ad_esleme.benzerlik("Ali Veli", "Ali Vel") > ad_esleme.benzerlik("Ali Veli", "Ayşe")

    def test_iki_alanda_farkli_onay_belirsizdir(self):
        harita = {("A", "ALI VELI"): 1, ("B", "ALI VELI"): 2, ("A", "AYSE"): 3}
        assert ad_esleme.ada_gore(harita, ["A", "B"]) == {"ALI VELI": None, "AYSE": 3}


def test_disa_aktarim_betikleri_yalniz_select():
    """Kaynak sisteme yazan komut yok (canlıya bağlanılsa bile zarar vermesin)."""
    yasak = re.compile(
        r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE)\b", re.I
    )
    dosyalar = sorted(SQL_DIZINI.glob("goc_*.sql"))
    assert len(dosyalar) == 11
    for dosya in dosyalar:
        govde = re.sub(r"/\*.*?\*/|--[^\n]*", "", dosya.read_text(encoding="utf-8-sig"), flags=re.S)
        assert not yasak.search(govde), dosya.name
        assert "SELECT" in govde.upper()
