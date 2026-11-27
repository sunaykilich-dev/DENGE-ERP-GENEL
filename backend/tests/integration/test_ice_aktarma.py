"""Toplu içe aktarma: şablon, okuma tuzakları, önizleme, uygulama, karantina."""

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from app.models import (
    Account,
    Device,
    PartnerTariff,
    Product,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceResult,
    SimCard,
    Subscription,
    Vehicle,
)
from app.services import imports as ice
from app.services.imports.ortak import evet_hayir, tarih_coz, tutar_coz

pytestmark = pytest.mark.integration


def xlsx(satirlar: list[list], *, basliktan_once: int = 0) -> bytes:
    """Test dosyası üretir; `basliktan_once` kadar çöp satır ekler."""
    wb = Workbook()
    ws = wb.active
    for _ in range(basliktan_once):
        ws.append(["Denge Mobilite", "", "rapor"])
    for satir in satirlar:
        ws.append(satir)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def _giris(client, kullanici_ac, username="yonetici", rol="ADMIN"):
    await kullanici_ac(username, rol)
    await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})


async def _yukle(client, kod: str, icerik: bytes, ad: str = "test.xlsx"):
    return await client.post(
        f"/api/ice-aktarma/{kod}",
        files={
            "file": (
                ad,
                icerik,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


# --- Hücre çözümleyiciler (DB'siz) --------------------------------------------


class TestHucreCozumleyiciler:
    def test_turkce_ondalik(self):
        assert tutar_coz("1.250,50") == Decimal("1250.50")

    def test_ingilizce_ondalik(self):
        assert tutar_coz("1,250.50") == Decimal("1250.50")

    def test_tek_ayracli_binlik(self):
        """'1.250' tarife listelerinde binlik ayracıdır, 1,25 değil."""
        assert tutar_coz("1.250") == Decimal("1250")

    def test_para_isareti_temizlenir(self):
        assert tutar_coz("1.250,50 ₺") == Decimal("1250.50")

    def test_sayisal_hucre(self):
        assert tutar_coz(1250.5) == Decimal("1250.5")

    def test_tarih_bicimleri(self):
        assert tarih_coz("15.03.2026") == date(2026, 3, 15)
        assert tarih_coz("2026-03-15") == date(2026, 3, 15)
        assert tarih_coz("15/03/2026") == date(2026, 3, 15)

    def test_excel_tarih_serisi(self):
        # 46096 = 2026-03-15 (1899-12-30 taban)
        assert tarih_coz("46096") == date(2026, 3, 15)

    def test_gecersiz_tarih(self):
        with pytest.raises(ValueError):
            tarih_coz("bilinmiyor")

    def test_evet_hayir(self):
        assert evet_hayir("Evet") is True
        assert evet_hayir("X") is True
        assert evet_hayir("hayır") is False
        assert evet_hayir("", varsayilan=True) is True


# --- Dosya okuma --------------------------------------------------------------


class TestOkuma:
    def test_baslik_ilk_satirda_olmayabilir(self):
        """HYTERA bayi listesinde başlık 9. satırda; sabit varsayım okuyamazdı."""
        icerik = xlsx(
            [["Unvan", "Müşteri mi"], ["ACME", "Evet"]],
            basliktan_once=8,
        )
        okuma = ice.oku("h.xlsx", icerik, ice.PROFILLER["hesap"])
        assert okuma.satirlar == [{"unvan": "ACME", "musteri_mi": "Evet"}]

    def test_turkce_kucultme_tuzagi(self):
        """'Cihaz Imei No'.lower() Türkçe yerelde 'cihaz ımei no' verir."""
        icerik = xlsx([["Cihaz IMEI No", "Ürün Kodu"], ["860000000000001", "L300"]])
        okuma = ice.oku("c.xlsx", icerik, ice.PROFILLER["cihaz"])
        assert okuma.satirlar[0]["imei"] == "860000000000001"

    def test_dolgu_satirlari_temizlenir(self):
        """Canlı dosyalarda 752 satır '…......' dolgusuydu."""
        icerik = xlsx([["Unvan"], ["…......."], ["ACME"]])
        okuma = ice.oku("h.xlsx", icerik, ice.PROFILLER["hesap"])
        assert [s["unvan"] for s in okuma.satirlar] == ["ACME"]
        # Dolgu satırı atıldı ama SAYILDI: kullanıcı eksiği görebilmeli.
        assert okuma.atilan == 1

    def test_zorunlu_sutun_eksikse_reddedilir(self):
        icerik = xlsx([["Müşteri mi"], ["Evet"]])
        with pytest.raises(ice.DosyaHatasi, match="Zorunlu sütunlar"):
            ice.oku("h.xlsx", icerik, ice.PROFILLER["hesap"])

    def test_desteklenmeyen_uzanti(self):
        with pytest.raises(ice.DosyaHatasi, match="xlsx"):
            ice.oku("veri.pdf", b"x", ice.PROFILLER["hesap"])

    def test_csv_cp1254(self):
        icerik = "Unvan;Müşteri mi\nÇAĞRI OTO;Evet\n".encode("cp1254")
        okuma = ice.oku("h.csv", icerik, ice.PROFILLER["hesap"])
        assert okuma.satirlar[0]["unvan"] == "ÇAĞRI OTO"


class TestSablon:
    def test_her_profil_sablon_uretir(self):
        for profil in ice.PROFILLER.values():
            wb = load_workbook(io.BytesIO(ice.sablon_xlsx(profil)))
            basliklar = [h.value for h in wb[wb.sheetnames[0]][1]]
            assert basliklar == [s.baslik for s in profil.sutunlar]
            assert "Açıklama" in wb.sheetnames

    def test_sablon_geri_yuklenebilir(self):
        """İndirilen boş şablon, doldurulup geri yüklendiğinde okunmalı."""
        profil = ice.PROFILLER["hesap"]
        wb = load_workbook(io.BytesIO(ice.sablon_xlsx(profil)))
        ws = wb[wb.sheetnames[0]]
        ws.append(["ACME LTD", "Evet", "", "", "", "", "", "a@b.com"])
        tampon = io.BytesIO()
        wb.save(tampon)
        okuma = ice.oku("dolu.xlsx", tampon.getvalue(), profil)
        assert okuma.satirlar == [{"unvan": "ACME LTD", "musteri_mi": "Evet", "eposta": "a@b.com"}]


# --- Hesap profili ------------------------------------------------------------


class TestHesapProfili:
    async def test_onizleme_hicbir_sey_yazmaz(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hesap", xlsx([["Unvan", "Müşteri mi"], ["ACME LTD", "Evet"]]))
        assert r.status_code == 201, r.text
        assert r.json()["parti"]["valid_rows"] == 1
        assert await db.scalar(select(Account).where(Account.title == "ACME LTD")) is None

    async def test_uygulama_hesap_acar(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "hesap",
            xlsx(
                [
                    ["Unvan", "Müşteri mi", "Montaj Noktası mı", "E-posta", "IBAN"],
                    [
                        "AUTOLAND",
                        "Evet",
                        "Evet",
                        "info@autoland.com",
                        "TR330006100519786457841326",
                    ],
                ]
            ),
        )
        parti_id = r.json()["parti"]["id"]
        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.status_code == 200, u.text
        assert u.json()["sonuc"]["eklendi"] == 1

        hesap = await db.scalar(select(Account).where(Account.title == "AUTOLAND"))
        assert hesap is not None
        # Bayrak seti: aynı hesap hem müşteri hem montaj noktası (plan §2/6).
        assert hesap.is_musteri and hesap.is_montaj_noktasi
        assert hesap.email == "info@autoland.com"

    async def test_gecersiz_iban_hata(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "hesap",
            xlsx([["Unvan", "IBAN"], ["ACME", "TR000000000000000000000000"]]),
        )
        satir = r.json()["satirlar"][0]
        assert any("IBAN" in h for h in satir["hatalar"])

    async def test_kolon_boyunu_asan_segment_onizlemede_hata(self, client, kullanici_ac):
        """Uzun sektör adı "Uygula"da tüm partiyi düşürmesin; önizlemede satır hatası."""
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "hesap",
            xlsx(
                [
                    ["Unvan", "Segment", "Bölge"],
                    ["ACME", "Hayvancılık, Balıkçılık, Avcılık", "İstanbul"],
                    ["BETA", "Enerji", "Ankara"],
                ]
            ),
        )
        satirlar = r.json()["satirlar"]
        assert any("segment" in h for h in satirlar[0]["hatalar"])
        assert satirlar[1]["hatalar"] == []

    async def test_montaj_noktasi_ibansiz_uyarir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hesap", xlsx([["Unvan", "Montaj Noktası mı"], ["X OTO", "Evet"]]))
        uyarilar = r.json()["satirlar"][0]["uyarilar"]
        assert any("IBAN" in u for u in uyarilar)
        assert any("e-posta" in u.lower() for u in uyarilar)

    async def test_mevcut_hesap_cakisma_verir_varsayilan_atlar(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="ACME LTD", title_key="acme ltd", is_musteri=True))
        await db.commit()

        r = await _yukle(client, "hesap", xlsx([["Unvan", "Bayi mi"], ["ACME LTD", "Evet"]]))
        assert r.json()["parti"]["conflict_rows"] == 1
        parti_id = r.json()["parti"]["id"]

        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.json()["sonuc"]["eklendi"] == 0  # karar verilmedi → atlandı

    async def test_guncelle_karari_rolleri_birlestirir(self, client, kullanici_ac, db):
        """Dosyada 'Hayır' yazması, sistemdeki rolü KALDIRMAZ."""
        await _giris(client, kullanici_ac)
        db.add(Account(title="ACME LTD", title_key="acme ltd", is_musteri=True))
        await db.commit()

        r = await _yukle(
            client,
            "hesap",
            xlsx([["Unvan", "Müşteri mi", "Bayi mi"], ["ACME LTD", "Hayır", "Evet"]]),
        )
        parti_id = r.json()["parti"]["id"]
        u = await client.post(
            f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={"kararlar": {"1": "guncelle"}}
        )
        assert u.json()["sonuc"]["guncellendi"] == 1

        hesap = await db.scalar(select(Account).where(Account.title_key == "acme ltd"))
        await db.refresh(hesap)
        assert hesap.is_bayi is True
        assert hesap.is_musteri is True  # kaldırılmadı


# --- Cihaz profili ------------------------------------------------------------


class TestUrunProfili:
    async def test_sirketli_ve_ortak_urun_acar(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "urun",
            xlsx(
                [
                    ["Ürün Kodu", "Tanım", "Tür", "Şirket", "Birim", "ERP Kodu"],
                    ["HYTR.PD685", "HYTERA PD685 TELSİZ", "Cihaz", "DENGE TELEKOM", "ADET", "X1"],
                    ["GUV.000184", "X-RAY CİHAZI", "Cihaz", "ELEKTRONIK", "ADET", ""],
                    ["HZM.0001", "KURULUM HİZMETİ", "Hizmet", "", "AY", ""],
                ]
            ),
        )
        assert r.status_code == 201, r.text
        satirlar = r.json()["satirlar"]
        assert all(not s["hatalar"] for s in satirlar)
        assert any("birimi" in u for u in satirlar[2]["uyarilar"])
        parti_id = r.json()["parti"]["id"]
        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.json()["sonuc"]["eklendi"] == 3
        urunler = {
            p.code: p
            for p in (await db.scalars(select(Product).where(Product.code.like("%.%")))).all()
        }
        assert urunler["HYTR.PD685"].sirket == "TELEKOM"
        assert urunler["HYTR.PD685"].type == "CIHAZ_SERILI"
        assert urunler["HYTR.PD685"].identity_kind == "SERI_NO"
        assert urunler["HYTR.PD685"].supplier_code == "X1"
        assert urunler["GUV.000184"].sirket == "ELEKTRONIK"
        assert urunler["HZM.0001"].sirket is None
        assert urunler["HZM.0001"].type == "HIZMET"

    async def test_mukerrer_kod_ve_taninmayan_deger_hata(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "urun",
            xlsx(
                [
                    ["Ürün Kodu", "Tanım", "Tür", "Şirket"],
                    ["A.1", "Bir", "Aksesuar", ""],
                    ["A.1", "İki", "Aksesuar", ""],
                    ["A.2", "Üç", "Bilinmez", ""],
                    ["A.3", "Dört", "", "BAŞKA ŞİRKET"],
                ]
            ),
        )
        s = r.json()["satirlar"]
        assert s[0]["hatalar"] == []
        assert any("mükerrer" in h for h in s[1]["hatalar"])
        assert any("tür" in h for h in s[2]["hatalar"])
        assert any("şirket" in h for h in s[3]["hatalar"])

    async def test_kayitli_kod_cakisma_verir(self, client, kullanici_ac, urun_ac):
        await urun_ac("VAR.1", identity_kind="YOK", type="AKSESUAR")
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "urun", xlsx([["Ürün Kodu", "Tanım"], ["VAR.1", "Yeni ad"]]))
        assert r.json()["satirlar"][0]["cakisma"]["tip"] == "mevcut"


class TestServisTalepProfili:
    async def test_talep_listesi_servis_isine_doner(self, client, kullanici_ac, db):
        db.add(
            Account(
                title="EREN ENERJİ ELEKTRİK ÜRETİM A.Ş.",
                title_key="eren enerji elektrik uretim a.s.",
                is_musteri=True,
            )
        )
        await db.commit()
        await _giris(client, kullanici_ac)
        basliklar = [
            "Birim",
            "Tür",
            "Talep Tarihi",
            "Müşteri / Firma",
            "Lokasyon",
            "Talep Detayı",
            "Durum",
            "Personel",
        ]
        r = await _yukle(
            client,
            "servis_talep",
            xlsx(
                [
                    basliklar,
                    [
                        "GUVENLIK",
                        "ARIZA",
                        "01.10.2026",
                        "EREN ENERJİ",
                        "ZONGULDAK",
                        "X-RAY ARIZA",
                        "TAMAMLANDI",
                        "ALİ KAYA",
                    ],
                    [
                        "GUVENLIK",
                        "KURULUM",
                        "",
                        "YENİ MÜŞTERİ",
                        "KIBRIS",
                        "BANT KURULUMU",
                        "BEKLEMEDE",
                        "",
                    ],
                    ["GUVENLIK", "", "", "X", "", "", "BİLİNMEZ", ""],
                ]
            ),
        )
        assert r.status_code == 201, r.text
        s = r.json()["satirlar"]
        assert s[0]["hatalar"] == [] and s[0]["veri"]["hesap_id"]
        assert any("bulunamadı" in u for u in s[1]["uyarilar"])
        assert s[2]["hatalar"]
        parti_id = r.json()["parti"]["id"]
        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.status_code == 200, u.text
        assert u.json()["sonuc"]["eklendi"] == 2
        isler = {
            i.konu: i
            for i in (
                await db.scalars(
                    select(ServiceOrder).where(ServiceOrder.source_ref.like("ExcelTalep:%"))
                )
            ).all()
        }
        # KARARLAR 2026-11-27: tamamlanan TAMAMLANDI (onaya düşer), tamamlanmayan
        # PLANLAMADA; ad bulunamazsa açıklamada kalır.
        assert isler["X-RAY ARIZA"].status == "TAMAMLANDI"
        assert "ALİ KAYA" in isler["X-RAY ARIZA"].aciklama
        assert isler["BANT KURULUMU"].status == "PLANLAMADA"
        assert isler["BANT KURULUMU"].customer_name_raw == "YENİ MÜŞTERİ"

        # Aynı dosya ikinci kez: yeni iş açılmaz.
        r2 = await _yukle(
            client,
            "servis_talep",
            xlsx(
                [
                    basliklar,
                    [
                        "GUVENLIK",
                        "ARIZA",
                        "01.10.2026",
                        "EREN ENERJİ",
                        "ZONGULDAK",
                        "X-RAY ARIZA",
                        "TAMAMLANDI",
                        "",
                    ],
                ]
            ),
        )
        assert any("daha önce" in h for h in r2.json()["satirlar"][0]["hatalar"])

    async def test_guvenlik_talep_takip_dosyasi(self, client, kullanici_ac, db):
        """KARARLAR 2026-11-27: Güvenlik Talep Takip Excel'i olduğu gibi yüklenir.

        Birim sütunu yok (GUVENLIK), personel ayraçsız ve yazım hatalı, talep
        tarihi boş (planlanan tarih), not = sonuç, araç = plaka.
        """
        onur = await kullanici_ac("onur demir", "SERVIS_TEKNISYEN")
        timucin = await kullanici_ac("timuçin sekmen", "SERVIS_TEKNISYEN")
        await kullanici_ac("ali kaya", "SERVIS_TEKNISYEN")
        await _giris(client, kullanici_ac)
        basliklar = [
            "NO ",
            "TALEP TARİHİ",
            "MÜŞTERİ / FİRMA",
            "LOKASYON",
            "ARAÇ",
            "PERSONEL",
            "TALEP DETAYI",
            "YETKİLİ KİŞİ",
            "PLANLANAN TARİH",
            "DURUM",
            "NOT / AÇIKLAMA",
        ]
        r = await _yukle(
            client,
            "servis_talep",
            xlsx(
                [
                    basliklar,
                    [
                        "1",
                        "",
                        "ANPA GROSS",
                        "BEYLİKDÜZÜ",
                        "34 GGA 161 / 34 EBC 119",
                        "ONUE DEMİR TUMİÇİN SEKMEN NAZIM KÖSE",
                        "3 ADET BUTON DEĞİŞİMİ",
                        "",
                        "12.11.2026",
                        "TAMAMLANDI",
                        "DEĞİŞİM YAPILDI FAAL",
                    ],
                    [
                        "2",
                        "",
                        "AKKOM CESSAS",
                        "",
                        "",
                        "NURİ DEMİR",
                        "PC KASASI MONTAJI VE KURULUMU",
                        "23.11.2026",
                        "",
                        "ERTELENDİ",
                        "YOĞUNLUK",
                    ],
                ]
            ),
        )
        assert r.status_code == 201, r.text
        s = r.json()["satirlar"]
        assert s[0]["hatalar"] == [] and s[1]["hatalar"] == []
        assert any("NAZIM KOSE" in u for u in s[0]["uyarilar"])
        # "NURİ" ONUR'a benzer ama yazım hatası sayılmaz (uydurma tayin yok).
        assert any("NURI DEMIR" in u for u in s[1]["uyarilar"])
        parti_id = r.json()["parti"]["id"]
        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.status_code == 200, u.text
        assert u.json()["sonuc"]["eklendi"] == 2

        biten = await db.scalar(select(ServiceOrder).where(ServiceOrder.konu.like("3 ADET%")))
        assert biten.birim == "GUVENLIK" and biten.status == "TAMAMLANDI"
        assert biten.arac_plaka == "34 GGA 161"
        assert biten.reported_at.date() == date(2026, 11, 12)
        assert biten.completed_at.date() == date(2026, 11, 12)
        sonuc = await db.scalar(
            select(ServiceResult).where(ServiceResult.service_order_id == biten.id)
        )
        assert sonuc.sonuc == "COZULDU" and sonuc.yapilan_islem == "DEĞİŞİM YAPILDI FAAL"
        atamalar = (
            await db.scalars(
                select(ServiceOrderAssignment)
                .where(ServiceOrderAssignment.service_order_id == biten.id)
                .order_by(ServiceOrderAssignment.id)
            )
        ).all()
        assert [(a.user_id, a.is_lead) for a in atamalar] == [(onur.id, True), (timucin.id, False)]

        bekleyen = await db.scalar(select(ServiceOrder).where(ServiceOrder.konu.like("PC KASASI%")))
        assert bekleyen.status == "PLANLAMADA" and bekleyen.tur == "KURULUM"
        # Yetkili sütunundaki tarih talep tarihi sayılır.
        assert bekleyen.reported_at.date() == date(2026, 11, 23)
        assert "Yetkili:" not in (bekleyen.aciklama or "")


class TestCihazProfili:
    async def test_imei_urunu_imeisiz_kabul_etmez(self, client, kullanici_ac, urun_ac):
        await _giris(client, kullanici_ac)
        await urun_ac("L300", "IMEI")
        r = await _yukle(client, "cihaz", xlsx([["Ürün Kodu", "Seri No"], ["L300", "SN1"]]))
        assert any("IMEI ister" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_seri_no_urunu_imeisiz_gecer(self, client, kullanici_ac, urun_ac, db):
        """Ek kameraların IMEI'si fiziksel olarak yok (plan §2/1)."""
        await _giris(client, kullanici_ac)
        await urun_ac("HMW3200LP", "SERI_NO")
        r = await _yukle(
            client, "cihaz", xlsx([["Ürün Kodu", "Seri No"], ["HMW3200LP", "SN-0001"]])
        )
        assert r.json()["parti"]["valid_rows"] == 1
        parti_id = r.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})

        cihaz = await db.scalar(select(Device).where(Device.serial_no == "SN-0001"))
        assert cihaz is not None
        assert cihaz.identity_kind == "SERI_NO"
        assert cihaz.status == "STOKTA"

    async def test_bilinmeyen_urun_hata(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "cihaz", xlsx([["Ürün Kodu", "IMEI"], ["YOK", "860000000000001"]]))
        assert any("kataloğ" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_bilimsel_gosterim_imei_yakalanir(self, client, kullanici_ac, urun_ac):
        """Excel uzun sayıyı '8.63071E+14' yapıyor; sessizce kabul edilemez."""
        await _giris(client, kullanici_ac)
        await urun_ac("L300", "IMEI")
        r = await _yukle(client, "cihaz", xlsx([["Ürün Kodu", "IMEI"], ["L300", "8.63071E+14"]]))
        assert r.json()["satirlar"][0]["hatalar"]

    async def test_dosya_ici_mukerrer_imei(self, client, kullanici_ac, urun_ac):
        await _giris(client, kullanici_ac)
        await urun_ac("L300", "IMEI")
        r = await _yukle(
            client,
            "cihaz",
            xlsx(
                [
                    ["Ürün Kodu", "IMEI"],
                    ["L300", "860000000000001"],
                    ["L300", "860000000000001"],
                ]
            ),
        )
        satirlar = r.json()["satirlar"]
        assert not satirlar[0]["hatalar"]
        assert any("mükerrer" in h for h in satirlar[1]["hatalar"])

    async def test_aktif_durum_girisi_reddedilir(self, client, kullanici_ac, urun_ac):
        """AKTIF cihaz montajla doğar; Excel'den açmak cihaz-araç dönemi bırakmazdı."""
        await _giris(client, kullanici_ac)
        await urun_ac("L300", "IMEI")
        r = await _yukle(
            client,
            "cihaz",
            xlsx([["Ürün Kodu", "IMEI", "Durum"], ["L300", "860000000000001", "AKTIF"]]),
        )
        assert any("Durum" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_mevcut_cihazin_durumu_degistirilmez(
        self, client, kullanici_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000009", urun=u, status="AKTIF")
        r = await _yukle(
            client,
            "cihaz",
            xlsx([["Ürün Kodu", "IMEI", "Not"], ["L300", "860000000000009", "yeni not"]]),
        )
        parti_id = r.json()["parti"]["id"]
        await client.post(
            f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={"kararlar": {"1": "guncelle"}}
        )
        await db.refresh(c)
        assert c.status == "AKTIF"  # dokunulmadı
        assert c.notes == "yeni not"


# --- Hat profili --------------------------------------------------------------


class TestHatProfili:
    async def test_kalem_bazli_maliyet(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "hat",
            xlsx(
                [
                    ["ICCID", "Numara", "Tarife Ücreti", "Paket Ücreti", "Taahhüt Bitişi"],
                    ["8990011234567890123", "5321234567", "1,89", "12,54", "31.12.2027"],
                ]
            ),
        )
        assert r.status_code == 201, r.text
        parti_id = r.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})

        hat = await db.scalar(select(SimCard).where(SimCard.iccid == "8990011234567890123"))
        assert hat is not None
        assert Decimal(str(hat.tariff_cost)) == Decimal("1.89")
        assert Decimal(str(hat.package_cost)) == Decimal("12.54")
        assert hat.commitment_end_date == date(2027, 12, 31)
        assert hat.msisdn == "+905321234567"

    async def test_taahhutsuz_hat_uyarir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hat", xlsx([["ICCID"], ["8990011234567890123"]]))
        assert any("Taahhüt" in u for u in r.json()["satirlar"][0]["uyarilar"])

    async def test_luhn_hata_degil_uyari(self, client, kullanici_ac):
        """Operatörler kontrol hanesiz 19 haneli ICCID basıyor."""
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hat", xlsx([["ICCID"], ["8990011234567890120"]]))
        satir = r.json()["satirlar"][0]
        assert not satir["hatalar"]


# --- Araç profili -------------------------------------------------------------


class TestAracProfili:
    async def test_musteriyle_birlikte_acar(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="ACME LTD", title_key="acme ltd", is_musteri=True))
        await db.commit()

        r = await _yukle(
            client,
            "arac",
            xlsx([["Plaka", "Firma", "Marka", "Yıl"], ["34 ABC 123", "ACME LTD", "Ford", "2021"]]),
        )
        parti_id = r.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})

        arac = await db.scalar(select(Vehicle).where(Vehicle.plate == "34ABC123"))
        assert arac is not None
        assert arac.brand == "Ford"
        assert arac.model_year == 2021
        assert arac.is_plate_verified is True

    async def test_tanimsiz_plaka_reddedilmez_rozetlenir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "arac", xlsx([["Plaka"], ["GEÇİCİ-7"]]))
        satir = r.json()["satirlar"][0]
        assert not satir["hatalar"]
        assert any("doğrulanmadı" in u for u in satir["uyarilar"])

    async def test_kayitli_arac_cakisma_verir(self, client, kullanici_ac, db):
        """plate_key küçük harfle saklanıyor; arama bunu tahmin etmemeli."""
        await _giris(client, kullanici_ac)
        veri = xlsx([["Plaka", "Marka"], ["34 ABC 123", "Ford"]])
        ilk = await _yukle(client, "arac", veri)
        parti_id = ilk.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        ikinci = await _yukle(client, "arac", veri)
        assert ikinci.json()["parti"]["conflict_rows"] == 1
        assert await db.scalar(select(func.count()).select_from(Vehicle)) == 1

    async def test_bilinmeyen_musteri_hata(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "arac", xlsx([["Plaka", "Firma"], ["34ABC123", "YOK A.Ş."]]))
        assert any("bulunamadı" in h for h in r.json()["satirlar"][0]["hatalar"])


# --- Tarife profili -----------------------------------------------------------


class TestTarifeProfili:
    async def test_yeni_tarife_acilir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="GÜREK OTO", title_key="gurek oto", is_montaj_noktasi=True))
        await db.commit()

        r = await _yukle(
            client,
            "tarife",
            xlsx(
                [
                    ["Montaj Noktası", "İş Tipi", "Birim Fiyat", "Geçerlilik Başlangıcı"],
                    ["GÜREK OTO", "ATS_MONTAJ", "350", "01.01.2026"],
                ]
            ),
        )
        assert r.status_code == 201, r.text
        parti_id = r.json()["parti"]["id"]
        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.json()["sonuc"]["eklendi"] == 1

        tarife = await db.scalar(
            select(PartnerTariff).where(PartnerTariff.work_type == "ATS_MONTAJ")
        )
        assert Decimal(str(tarife.unit_price)) == Decimal("350")
        assert tarife.valid_to is None

    async def test_ikinci_donem_oncekini_kapatir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="GÜREK OTO", title_key="gurek oto", is_montaj_noktasi=True))
        await db.commit()

        for fiyat, tarih in (("350", "01.01.2026"), ("450", "01.07.2026")):
            r = await _yukle(
                client,
                "tarife",
                xlsx(
                    [
                        ["Montaj Noktası", "İş Tipi", "Birim Fiyat", "Geçerlilik Başlangıcı"],
                        ["GÜREK OTO", "ATS_MONTAJ", fiyat, tarih],
                    ]
                ),
            )
            parti_id = r.json()["parti"]["id"]
            await client.post(
                f"/api/ice-aktarma/partiler/{parti_id}/uygula",
                json={"kararlar": {"1": "guncelle"}},
            )

        tarifeler = (
            await db.scalars(
                select(PartnerTariff)
                .where(PartnerTariff.work_type == "ATS_MONTAJ")
                .order_by(PartnerTariff.valid_from)
            )
        ).all()
        assert len(tarifeler) == 2
        assert tarifeler[0].valid_to is not None
        assert tarifeler[1].valid_to is None

    async def test_gecmise_donuk_donem_reddedilir(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="GÜREK OTO", title_key="gurek oto", is_montaj_noktasi=True))
        await db.commit()
        for fiyat, tarih in (("350", "01.07.2026"), ("450", "01.01.2026")):
            r = await _yukle(
                client,
                "tarife",
                xlsx(
                    [
                        ["Montaj Noktası", "İş Tipi", "Birim Fiyat", "Geçerlilik Başlangıcı"],
                        ["GÜREK OTO", "ATS_MONTAJ", fiyat, tarih],
                    ]
                ),
            )
            son = r
            parti_id = r.json()["parti"]["id"]
            await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert any("sonra başlamalı" in h for h in son.json()["satirlar"][0]["hatalar"])

    async def test_montaj_noktasi_olmayan_hesap_hata(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="SADECE MUSTERI", title_key="sadece musteri", is_musteri=True))
        await db.commit()
        r = await _yukle(
            client,
            "tarife",
            xlsx(
                [
                    ["Montaj Noktası", "İş Tipi", "Birim Fiyat", "Geçerlilik Başlangıcı"],
                    ["SADECE MUSTERI", "ATS_MONTAJ", "350", "01.01.2026"],
                ]
            ),
        )
        assert any("bulunamadı" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_sifir_fiyat_uyarir(self, client, kullanici_ac):
        """Canlı veride 44 noktanın tarifelerinin hepsi 0,00 idi."""
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "tarife",
            xlsx(
                [
                    ["İş Tipi", "Birim Fiyat", "Geçerlilik Başlangıcı"],
                    ["ATS_MONTAJ", "0", "01.01.2026"],
                ]
            ),
        )
        assert any("0" in u for u in r.json()["satirlar"][0]["uyarilar"])


# --- Abonelik profili ---------------------------------------------------------


class TestAbonelikProfili:
    async def test_taslak_acar_mrr_uretmez(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="ACME LTD", title_key="acme ltd", is_musteri=True))
        await db.commit()

        r = await _yukle(
            client,
            "abonelik",
            xlsx(
                [
                    ["Müşteri", "Ücret", "Başlangıç", "Periyot"],
                    ["ACME LTD", "1.200", "01.01.2026", "AYLIK"],
                ]
            ),
        )
        parti_id = r.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})

        abonelik = await db.scalar(select(Subscription))
        assert abonelik is not None
        assert abonelik.status == "TASLAK"

        mrr = await client.get("/api/abonelikler/mrr", params={"tarih": "2026-06-01"})
        assert Decimal(mrr.json()["mrr"]) == Decimal("0")

    async def test_kdv_yuzde_isaretsiz_de_cozulur(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="ACME LTD", title_key="acme ltd", is_musteri=True))
        await db.commit()
        r = await _yukle(
            client,
            "abonelik",
            xlsx(
                [
                    ["Müşteri", "Ücret", "Başlangıç", "KDV Oranı"],
                    ["ACME LTD", "1000", "01.01.2026", "20"],
                ]
            ),
        )
        parti_id = r.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        abonelik = await db.scalar(select(Subscription))
        assert Decimal(str(abonelik.vat_rate)) == Decimal("0.2000")

    async def test_bitis_baslangictan_once_hata(self, client, kullanici_ac, db):
        await _giris(client, kullanici_ac)
        db.add(Account(title="ACME LTD", title_key="acme ltd", is_musteri=True))
        await db.commit()
        r = await _yukle(
            client,
            "abonelik",
            xlsx(
                [
                    ["Müşteri", "Ücret", "Başlangıç", "Bitiş"],
                    ["ACME LTD", "1000", "01.06.2026", "01.01.2026"],
                ]
            ),
        )
        assert r.json()["satirlar"][0]["hatalar"]


# --- Parti yaşam döngüsü ------------------------------------------------------


class TestPartiDongusu:
    async def test_ayni_parti_iki_kez_uygulanmaz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hesap", xlsx([["Unvan", "Müşteri mi"], ["ACME", "Evet"]]))
        parti_id = r.json()["parti"]["id"]
        assert (
            await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        ).status_code == 200
        ikinci = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert ikinci.status_code == 409

    async def test_iptal_edilen_parti_uygulanmaz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hesap", xlsx([["Unvan", "Müşteri mi"], ["ACME", "Evet"]]))
        parti_id = r.json()["parti"]["id"]
        await client.post(f"/api/ice-aktarma/partiler/{parti_id}/iptal")
        u = await client.post(f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={})
        assert u.status_code == 409

    async def test_gecersiz_karar_reddedilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hesap", xlsx([["Unvan", "Müşteri mi"], ["ACME", "Evet"]]))
        parti_id = r.json()["parti"]["id"]
        u = await client.post(
            f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={"kararlar": {"1": "sil"}}
        )
        assert u.status_code == 400

    async def test_karantina_raporu_ham_sutunlari_tasir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(
            client,
            "hesap",
            xlsx([["Unvan", "IBAN"], ["ACME", "TR00"], ["İYİ FİRMA", "Evet"]]),
        )
        parti_id = r.json()["parti"]["id"]
        rapor = await client.get(f"/api/ice-aktarma/partiler/{parti_id}/karantina.xlsx")
        assert rapor.status_code == 200
        assert rapor.content[:2] == b"PK"

        wb = load_workbook(io.BytesIO(rapor.content))
        ws = wb.active
        basliklar = [h.value for h in ws[1]]
        assert basliklar[:3] == ["Satır", "Sorun", "Açıklama"]
        assert "Unvan" in basliklar
        # Kullanıcı kendi satırını tanısın diye ham değer aynen taşınır.
        degerler = [h.value for h in ws[2]]
        assert "ACME" in degerler

    async def test_bos_dosya_reddedilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "hesap", xlsx([["Unvan", "Müşteri mi"]]))
        assert r.status_code == 422

    async def test_bilinmeyen_profil_404(self, client, kullanici_ac):
        await _giris(client, kullanici_ac)
        r = await _yukle(client, "uydurma", xlsx([["Unvan"], ["X"]]))
        assert r.status_code == 404


# --- Yetki --------------------------------------------------------------------


class TestYetki:
    async def test_profil_listesi_yetkiye_gore_daralir(self, client, kullanici_ac):
        """Hat yazamayan biri hat profilini hiç görmemeli."""
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        r = await client.get("/api/ice-aktarma/profiller")
        kodlar = {p["kod"] for p in r.json()}
        assert "arac" in kodlar  # SATIS'ta arac.yaz var
        assert "hat" not in kodlar
        assert "cihaz" not in kodlar

    async def test_yetkisiz_profile_yukleme_403(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        r = await _yukle(client, "hat", xlsx([["ICCID"], ["8990011234567890123"]]))
        assert r.status_code == 403

    async def test_yetkisiz_sablon_403(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        r = await client.get("/api/ice-aktarma/profiller/cihaz/sablon.xlsx")
        assert r.status_code == 403

    async def test_depo_cihaz_yukleyebilir(self, client, kullanici_ac, urun_ac):
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        await urun_ac("L300", "IMEI")
        r = await _yukle(
            client, "cihaz", xlsx([["Ürün Kodu", "IMEI"], ["L300", "860000000000001"]])
        )
        assert r.status_code == 201, r.text


class TestKullaniciProfili:
    """Organizasyon listesinden toplu kullanıcı (2026-11-24)."""

    BASLIK = ["Ad Soyad", "Rol", "Birimler", "Şirketler", "Ünvan", "Saha Rolü", "Giriş"]

    async def test_kullanicilar_rol_sirket_ve_giris_ile_acilir(self, client, kullanici_ac, db):
        from app.models import User

        await _giris(client, kullanici_ac)
        await kullanici_ac("ali.veli", "DEPO")  # var olan kullanıcı adı
        r = await _yukle(
            client,
            "kullanici",
            xlsx(
                [
                    self.BASLIK,
                    [
                        "Özgür Çavdar",
                        "SERVIS_TEKNISYEN",
                        "GUVENLIK",
                        "",
                        "Saha",
                        "TEKNISYEN",
                        "Açık",
                    ],
                    ["Nurettin Erzurum", "YONETIM", "", "Hepsi", "Genel Müdür", "", "Açık"],
                    ["Hülya Kaplan", "", "", "Hepsi", "Temizlik", "", "Kapalı"],
                    ["Ali Veli", "DEPO", "", "", "", "", ""],
                    ["Ad Min", "ADMIN", "", "", "", "", ""],
                    ["Şef Yok", "SERVIS_SEF", "", "", "", "", "Açık"],
                    ["Rolsüz", "", "", "", "", "", "Açık"],
                ]
            ),
        )
        assert r.status_code == 201, r.text
        s = r.json()["satirlar"]
        assert [bool(x["hatalar"]) for x in s] == [False, False, False, True, True, True, True]
        assert s[0]["veri"]["username"] == "ozgur.cavdar"
        assert s[0]["veri"]["sirketler"] == "ELEKTRONIK"
        assert any("ADMIN" in h for h in s[4]["hatalar"])
        u = await client.post(
            f"/api/ice-aktarma/partiler/{r.json()['parti']['id']}/uygula", json={}
        )
        assert u.json()["sonuc"]["eklendi"] == 3, u.text

        db.expire_all()
        kisiler = {
            k.username: k
            for k in (
                await db.scalars(
                    select(User).where(
                        User.username.in_(["ozgur.cavdar", "nurettin.erzurum", "hulya.kaplan"])
                    )
                )
            ).all()
        }
        oz = kisiler["ozgur.cavdar"]
        assert oz.giris_acik and oz.parola_degismeli and oz.saha_rolu == "TEKNISYEN"
        assert [b.birim for b in oz.birimler] == ["GUVENLIK"]
        assert sorted(x.sirket_kod for x in kisiler["nurettin.erzurum"].sirket_uyelikleri) == [
            "ELEKTRONIK",
            "MOBILITE",
            "TELEKOM",
        ]
        assert kisiler["hulya.kaplan"].giris_acik is False
        # Parola dosyada yok: rastgele özet, kimse bilmez → giriş yapılamaz.
        r = await client.post(
            "/api/auth/login", json={"username": "ozgur.cavdar", "password": "parola1234"}
        )
        assert r.status_code == 401

    async def test_izin_sistem_kullanici(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, username="depocu", rol="DEPO")
        r = await _yukle(
            client, "kullanici", xlsx([self.BASLIK, ["A B", "DEPO", "", "", "", "", ""]])
        )
        assert r.status_code == 403
