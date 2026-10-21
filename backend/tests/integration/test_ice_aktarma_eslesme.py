"""Eşleştirme içe aktarımları: IMEI–SIM, IMEI–araç, cihaz zimmeti."""

import io
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import (
    Account,
    DeviceCustodyHistory,
    DeviceVehicleAssignment,
    SettlementLine,
    SimDeviceHistory,
    Vehicle,
    Warehouse,
)

pytestmark = pytest.mark.integration


def xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
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


async def _uygula(client, r, kararlar: dict | None = None):
    parti_id = r.json()["parti"]["id"]
    u = await client.post(
        f"/api/ice-aktarma/partiler/{parti_id}/uygula", json={"kararlar": kararlar or {}}
    )
    assert u.status_code == 200, u.text
    return u.json()["sonuc"]


@pytest.fixture
async def arac_ac(db):
    async def _make(plaka: str, musteri_id: int | None = None) -> Vehicle:
        a = Vehicle(plate=plaka, plate_key=plaka, customer_id=musteri_id)
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a

    return _make


# --- IMEI ↔ SIM ---------------------------------------------------------------


class TestCihazHat:
    async def test_iccid_ile_eslestirme(self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000001", urun=u)
        h = await hat_ac("8990011234567890123")

        r = await _yukle(
            client,
            "cihaz_hat",
            xlsx([["IMEI", "ICCID"], ["860000000000001", "8990011234567890123"]]),
        )
        assert r.status_code == 201, r.text
        assert await _uygula(client, r) == {"eklendi": 1, "guncellendi": 0, "atlandi": 0}

        kayit = await db.scalar(select(SimDeviceHistory).where(SimDeviceHistory.device_id == c.id))
        assert kayit is not None
        assert kayit.sim_id == h.id
        assert kayit.valid_to is None
        await db.refresh(c)
        assert c.current_sim_id == h.id

    async def test_numara_ile_de_bulunur(self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db):
        """Operatör listesi çoğu zaman ICCID değil hat numarası veriyor."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000002", urun=u)
        await hat_ac("8990011234567890124", msisdn="+905321234567")

        r = await _yukle(
            client,
            "cihaz_hat",
            xlsx([["IMEI", "Hat No"], ["860000000000002", "0532 123 45 67"]]),
        )
        assert r.json()["parti"]["valid_rows"] == 1

    async def test_seri_nolu_cihaz_eslestirilebilir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("HMW3200LP", "SERI_NO")
        c = await cihaz_ac(serial_no="SN-0007", urun=u)
        await hat_ac("8990011234567890125")

        r = await _yukle(
            client,
            "cihaz_hat",
            xlsx([["Seri No", "ICCID"], ["SN-0007", "8990011234567890125"]]),
        )
        assert await _uygula(client, r) == {"eklendi": 1, "guncellendi": 0, "atlandi": 0}
        assert await db.scalar(select(SimDeviceHistory).where(SimDeviceHistory.device_id == c.id))

    async def test_gecmise_donuk_tarih_yazilir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000003", urun=u)
        await hat_ac("8990011234567890126")

        r = await _yukle(
            client,
            "cihaz_hat",
            xlsx(
                [
                    ["IMEI", "ICCID", "Takılma Tarihi"],
                    ["860000000000003", "8990011234567890126", "15.03.2024"],
                ]
            ),
        )
        await _uygula(client, r)
        kayit = await db.scalar(select(SimDeviceHistory).where(SimDeviceHistory.device_id == c.id))
        assert kayit.valid_from.date() == date(2024, 3, 15)

    async def test_olmayan_cihaz_yonlendirici_hata(self, client, kullanici_ac, hat_ac):
        await _giris(client, kullanici_ac)
        await hat_ac("8990011234567890127")
        r = await _yukle(
            client,
            "cihaz_hat",
            xlsx([["IMEI", "ICCID"], ["860000000009999", "8990011234567890127"]]),
        )
        hatalar = r.json()["satirlar"][0]["hatalar"]
        assert any("Cihazlar profilini" in h for h in hatalar)

    async def test_dosyada_ayni_cihaza_iki_hat(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac
    ):
        """EXCLUDE kısıtına çarpmadan önce dosyada yakalanmalı."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000004", urun=u)
        await hat_ac("8990011234567890128")
        await hat_ac("8990011234567890129")

        r = await _yukle(
            client,
            "cihaz_hat",
            xlsx(
                [
                    ["IMEI", "ICCID"],
                    ["860000000000004", "8990011234567890128"],
                    ["860000000000004", "8990011234567890129"],
                ]
            ),
        )
        satirlar = r.json()["satirlar"]
        assert not satirlar[0]["hatalar"]
        assert any("ikinci kez" in h for h in satirlar[1]["hatalar"])

    async def test_acik_esleme_cakisma_verir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000005", urun=u)
        h1 = await hat_ac("8990011234567890130")
        h2 = await hat_ac("8990011234567890131")

        ilk = await _yukle(
            client,
            "cihaz_hat",
            xlsx(
                [
                    ["IMEI", "ICCID", "Takılma Tarihi"],
                    ["860000000000005", "8990011234567890130", "01.01.2024"],
                ]
            ),
        )
        await _uygula(client, ilk)

        yeni_hat = xlsx(
            [
                ["IMEI", "ICCID", "Takılma Tarihi"],
                ["860000000000005", "8990011234567890131", "01.06.2024"],
            ]
        )
        ikinci = await _yukle(client, "cihaz_hat", yeni_hat)
        assert ikinci.json()["parti"]["conflict_rows"] == 1
        # Karar verilmezse atlanır.
        assert (await _uygula(client, ikinci))["eklendi"] == 0

        ucuncu = await _yukle(client, "cihaz_hat", yeni_hat)
        await _uygula(client, ucuncu, {"1": "guncelle"})

        donemler = (
            await db.scalars(
                select(SimDeviceHistory)
                .where(SimDeviceHistory.device_id == c.id)
                .order_by(SimDeviceHistory.valid_from)
            )
        ).all()
        assert len(donemler) == 2
        assert donemler[0].sim_id == h1.id and donemler[0].valid_to is not None
        assert donemler[1].sim_id == h2.id and donemler[1].valid_to is None

    async def test_gecmise_donuk_esleme_onizlemede_yakalanir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac
    ):
        """Sıfır uzunluklu dönem aralık kısıtına çarpardı; önce yakalanmalı."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000008", urun=u)
        await hat_ac("8990011234567890140")
        await hat_ac("8990011234567890141")

        await _uygula(
            client,
            await _yukle(
                client,
                "cihaz_hat",
                xlsx(
                    [
                        ["IMEI", "ICCID", "Takılma Tarihi"],
                        ["860000000000008", "8990011234567890140", "01.06.2024"],
                    ]
                ),
            ),
        )
        geri = await _yukle(
            client,
            "cihaz_hat",
            xlsx(
                [
                    ["IMEI", "ICCID", "Takılma Tarihi"],
                    ["860000000000008", "8990011234567890141", "01.01.2024"],
                ]
            ),
        )
        assert any("bundan sonra olmalı" in h for h in geri.json()["satirlar"][0]["hatalar"])

    async def test_ayni_esleme_tekrar_yuklenince_yeni_donem_acmaz(
        self, client, kullanici_ac, urun_ac, cihaz_ac, hat_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000006", urun=u)
        await hat_ac("8990011234567890132")
        veri = xlsx([["IMEI", "ICCID"], ["860000000000006", "8990011234567890132"]])

        await _uygula(client, await _yukle(client, "cihaz_hat", veri))
        ikinci = await _yukle(client, "cihaz_hat", veri)
        assert ikinci.json()["satirlar"][0]["cakisma"]["tip"] == "mevcut"
        await _uygula(client, ikinci, {"1": "guncelle"})

        donemler = (
            await db.scalars(select(SimDeviceHistory).where(SimDeviceHistory.device_id == c.id))
        ).all()
        assert len(donemler) == 1


# --- IMEI ↔ Araç --------------------------------------------------------------


class TestCihazArac:
    async def test_montaj_donemi_acilir_ve_cihaz_aktif_olur(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000010", urun=u)
        a = await arac_ac("34ABC123")
        assert c.status == "STOKTA"

        r = await _yukle(
            client,
            "cihaz_arac",
            xlsx(
                [["IMEI", "Plaka", "Montaj Tarihi"], ["860000000000010", "34ABC123", "01.06.2025"]]
            ),
        )
        assert await _uygula(client, r) == {"eklendi": 1, "guncellendi": 0, "atlandi": 0}

        donem = await db.scalar(
            select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.device_id == c.id)
        )
        assert donem is not None
        assert donem.vehicle_id == a.id
        assert donem.valid_from.date() == date(2025, 6, 1)
        assert donem.valid_to is None

        await db.refresh(c)
        # Araca takılı cihaz STOKTA kalamaz; zincir makineden yürütüldü.
        assert c.status == "AKTIF"
        assert c.current_vehicle_id == a.id

    async def test_hak_edis_satiri_uretmez(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db
    ):
        """Sahada takılı cihazı tanıtmak, montaj noktasına borç doğurmaz."""
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000011", urun=u)
        await arac_ac("34ABC124")
        nokta = Account(title="GÜREK OTO", title_key="gurek oto", is_montaj_noktasi=True)
        db.add(nokta)
        await db.commit()

        r = await _yukle(
            client,
            "cihaz_arac",
            xlsx(
                [
                    ["IMEI", "Plaka", "Montaj Noktası"],
                    ["860000000000011", "34ABC124", "GÜREK OTO"],
                ]
            ),
        )
        await _uygula(client, r)
        assert await db.scalar(select(SettlementLine)) is None

    async def test_montaj_noktasi_kaydedilir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000012", urun=u)
        await arac_ac("34ABC125")
        nokta = Account(title="GÜREK OTO", title_key="gurek oto", is_montaj_noktasi=True)
        db.add(nokta)
        await db.commit()
        await db.refresh(nokta)

        r = await _yukle(
            client,
            "cihaz_arac",
            xlsx(
                [
                    ["IMEI", "Plaka", "Montaj Noktası"],
                    ["860000000000012", "34ABC125", "GÜREK OTO"],
                ]
            ),
        )
        await _uygula(client, r)
        donem = await db.scalar(
            select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.device_id == c.id)
        )
        assert donem.installed_by_id == nokta.id
        assert donem.installed_by_type == "MONTAJ_NOKTASI"

    async def test_aracin_musterisi_doneme_tasinir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db
    ):
        await _giris(client, kullanici_ac)
        musteri = Account(title="ACME LTD", title_key="acme ltd", is_musteri=True)
        db.add(musteri)
        await db.commit()
        await db.refresh(musteri)

        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000013", urun=u)
        await arac_ac("34ABC126", musteri.id)

        r = await _yukle(
            client, "cihaz_arac", xlsx([["IMEI", "Plaka"], ["860000000000013", "34ABC126"]])
        )
        await _uygula(client, r)
        donem = await db.scalar(
            select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.device_id == c.id)
        )
        assert donem.customer_id == musteri.id

    async def test_baska_aracta_olan_cihaz_cakisma_verir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000014", urun=u)
        a1 = await arac_ac("34ABC127")
        a2 = await arac_ac("34ABC128")

        await _uygula(
            client,
            await _yukle(
                client,
                "cihaz_arac",
                xlsx(
                    [
                        ["IMEI", "Plaka", "Montaj Tarihi"],
                        ["860000000000014", "34ABC127", "01.01.2024"],
                    ]
                ),
            ),
        )
        ikinci = await _yukle(
            client,
            "cihaz_arac",
            xlsx(
                [
                    ["IMEI", "Plaka", "Montaj Tarihi"],
                    ["860000000000014", "34ABC128", "01.06.2024"],
                ]
            ),
        )
        assert ikinci.json()["parti"]["conflict_rows"] == 1
        assert "34ABC127" in ikinci.json()["satirlar"][0]["cakisma"]["aciklama"]

        await _uygula(client, ikinci, {"1": "guncelle"})
        donemler = (
            await db.scalars(
                select(DeviceVehicleAssignment)
                .where(DeviceVehicleAssignment.device_id == c.id)
                .order_by(DeviceVehicleAssignment.valid_from)
            )
        ).all()
        assert len(donemler) == 2
        assert donemler[0].vehicle_id == a1.id and donemler[0].valid_to is not None
        assert donemler[1].vehicle_id == a2.id and donemler[1].valid_to is None

    async def test_gecmise_donuk_montaj_onizlemede_yakalanir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac
    ):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000018", urun=u)
        await arac_ac("34ABC140")
        await arac_ac("34ABC141")

        await _uygula(
            client,
            await _yukle(
                client,
                "cihaz_arac",
                xlsx(
                    [
                        ["IMEI", "Plaka", "Montaj Tarihi"],
                        ["860000000000018", "34ABC140", "01.06.2024"],
                    ]
                ),
            ),
        )
        geri = await _yukle(
            client,
            "cihaz_arac",
            xlsx(
                [
                    ["IMEI", "Plaka", "Montaj Tarihi"],
                    ["860000000000018", "34ABC141", "01.01.2024"],
                ]
            ),
        )
        assert any("bundan sonra olmalı" in h for h in geri.json()["satirlar"][0]["hatalar"])

    async def test_hurda_cihaz_takilamaz(self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000015", urun=u, status="HURDA")
        await arac_ac("34ABC129")
        r = await _yukle(
            client, "cihaz_arac", xlsx([["IMEI", "Plaka"], ["860000000000015", "34ABC129"]])
        )
        assert any("HURDA" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_olmayan_arac_yonlendirici_hata(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000016", urun=u)
        r = await _yukle(
            client, "cihaz_arac", xlsx([["IMEI", "Plaka"], ["860000000000016", "99XYZ999"]])
        )
        assert any("Araçlar profilini" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_cihaz_rolu_yazilir(self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db):
        await _giris(client, kullanici_ac)
        u = await urun_ac("HMW3200LP", "SERI_NO")
        c = await cihaz_ac(serial_no="SN-KAM-1", urun=u)
        await arac_ac("34ABC130")
        r = await _yukle(
            client,
            "cihaz_arac",
            xlsx([["Seri No", "Plaka", "Cihaz Rolü"], ["SN-KAM-1", "34ABC130", "YARDIMCI_KAMERA"]]),
        )
        await _uygula(client, r)
        await db.refresh(c)
        assert c.device_role == "YARDIMCI_KAMERA"

    async def test_bir_arac_birden_fazla_cihaz_alabilir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, arac_ac, db
    ):
        """Araçların %96,8'inde birden fazla cihaz var (plan §2/3)."""
        await _giris(client, kullanici_ac)
        u1 = await urun_ac("L300", "IMEI")
        u2 = await urun_ac("HMW3200LP", "SERI_NO")
        await cihaz_ac(imei="860000000000017", urun=u1)
        await cihaz_ac(serial_no="SN-KAM-2", urun=u2)
        a = await arac_ac("34ABC131")

        r = await _yukle(
            client,
            "cihaz_arac",
            xlsx(
                [
                    ["IMEI", "Plaka"],
                    ["860000000000017", "34ABC131"],
                    ["SN-KAM-2", "34ABC131"],
                ]
            ),
        )
        assert await _uygula(client, r) == {"eklendi": 2, "guncellendi": 0, "atlandi": 0}
        donemler = (
            await db.scalars(
                select(DeviceVehicleAssignment).where(DeviceVehicleAssignment.vehicle_id == a.id)
            )
        ).all()
        assert len(donemler) == 2


# --- Cihaz zimmeti ------------------------------------------------------------


class TestCihazZimmet:
    async def test_bayiye_zimmet(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        await _giris(client, kullanici_ac)
        bayi = Account(title="DİYARBAKIR BAYİ", title_key="diyarbakir bayi", is_bayi=True)
        db.add(bayi)
        await db.commit()
        await db.refresh(bayi)

        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000020", urun=u)

        r = await _yukle(
            client,
            "cihaz_zimmet",
            xlsx(
                [
                    ["IMEI", "Konum Tipi", "Hesap", "Sahiplik"],
                    ["860000000000020", "BAYI", "DİYARBAKIR BAYİ", "BAYI_SATILDI"],
                ]
            ),
        )
        assert await _uygula(client, r) == {"eklendi": 1, "guncellendi": 0, "atlandi": 0}

        konum = await db.scalar(
            select(DeviceCustodyHistory).where(DeviceCustodyHistory.device_id == c.id)
        )
        assert konum.location_type == "BAYI"
        assert konum.account_id == bayi.id
        assert konum.ownership == "BAYI_SATILDI"
        assert konum.valid_to is None

    async def test_depo_koduyla(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        await _giris(client, kullanici_ac)
        depo = Warehouse(code="MERKEZ", name="Merkez Depo", location_type="MERKEZ_DEPO")
        db.add(depo)
        await db.commit()
        await db.refresh(depo)

        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000021", urun=u)
        r = await _yukle(
            client,
            "cihaz_zimmet",
            xlsx([["IMEI", "Konum Tipi", "Depo"], ["860000000000021", "MERKEZ_DEPO", "MERKEZ"]]),
        )
        await _uygula(client, r)
        konum = await db.scalar(
            select(DeviceCustodyHistory).where(DeviceCustodyHistory.device_id == c.id)
        )
        assert konum.warehouse_id == depo.id

    async def test_hesapsiz_bayi_konumu_uyarir(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000022", urun=u)
        r = await _yukle(
            client, "cihaz_zimmet", xlsx([["IMEI", "Konum Tipi"], ["860000000000022", "BAYI"]])
        )
        assert any("belirsiz" in u for u in r.json()["satirlar"][0]["uyarilar"])

    async def test_gecersiz_konum_tipi(self, client, kullanici_ac, urun_ac, cihaz_ac):
        await _giris(client, kullanici_ac)
        u = await urun_ac("L300", "IMEI")
        await cihaz_ac(imei="860000000000023", urun=u)
        r = await _yukle(
            client, "cihaz_zimmet", xlsx([["IMEI", "Konum Tipi"], ["860000000000023", "GARAJ"]])
        )
        assert any("Konum tipi" in h for h in r.json()["satirlar"][0]["hatalar"])

    async def test_konum_degisince_onceki_kapanir(
        self, client, kullanici_ac, urun_ac, cihaz_ac, db
    ):
        await _giris(client, kullanici_ac)
        depo = Warehouse(code="MERKEZ", name="Merkez", location_type="MERKEZ_DEPO")
        bayi = Account(title="BAYİ A", title_key="bayi a", is_bayi=True)
        db.add_all([depo, bayi])
        await db.commit()

        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000024", urun=u)

        await _uygula(
            client,
            await _yukle(
                client,
                "cihaz_zimmet",
                xlsx(
                    [
                        ["IMEI", "Konum Tipi", "Depo", "Tarih"],
                        ["860000000000024", "MERKEZ_DEPO", "MERKEZ", "01.01.2025"],
                    ]
                ),
            ),
        )
        ikinci = await _yukle(
            client,
            "cihaz_zimmet",
            xlsx(
                [
                    ["IMEI", "Konum Tipi", "Hesap", "Tarih"],
                    ["860000000000024", "BAYI", "BAYİ A", "01.06.2025"],
                ]
            ),
        )
        assert ikinci.json()["parti"]["conflict_rows"] == 1
        await _uygula(client, ikinci, {"1": "guncelle"})

        konumlar = (
            await db.scalars(
                select(DeviceCustodyHistory)
                .where(DeviceCustodyHistory.device_id == c.id)
                .order_by(DeviceCustodyHistory.valid_from)
            )
        ).all()
        assert len(konumlar) == 2
        assert konumlar[0].valid_to.date() == date(2025, 6, 1)
        assert konumlar[1].valid_to is None

    async def test_sahiplik_bossa_onceki_korunur(self, client, kullanici_ac, urun_ac, cihaz_ac, db):
        """Konum değişikliği tek başına mülkiyeti değiştirmez."""
        await _giris(client, kullanici_ac)
        bayi = Account(title="BAYİ B", title_key="bayi b", is_bayi=True)
        db.add(bayi)
        await db.commit()

        u = await urun_ac("L300", "IMEI")
        c = await cihaz_ac(imei="860000000000025", urun=u)
        await _uygula(
            client,
            await _yukle(
                client,
                "cihaz_zimmet",
                xlsx(
                    [
                        ["IMEI", "Konum Tipi", "Hesap", "Sahiplik", "Tarih"],
                        ["860000000000025", "BAYI", "BAYİ B", "BAYI_SATILDI", "01.01.2025"],
                    ]
                ),
            ),
        )
        ikinci = await _yukle(
            client,
            "cihaz_zimmet",
            xlsx(
                [
                    ["IMEI", "Konum Tipi", "Tarih"],
                    ["860000000000025", "SERVIS", "01.06.2025"],
                ]
            ),
        )
        await _uygula(client, ikinci, {"1": "guncelle"})

        acik = await db.scalar(
            select(DeviceCustodyHistory).where(
                DeviceCustodyHistory.device_id == c.id, DeviceCustodyHistory.valid_to.is_(None)
            )
        )
        assert acik.location_type == "SERVIS"
        assert acik.ownership == "BAYI_SATILDI"


# --- Yetki --------------------------------------------------------------------


class TestYetki:
    async def test_hat_sorumlusu_imei_sim_eslestirebilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "hatci", "HAT_SORUMLUSU")
        r = await client.get("/api/ice-aktarma/profiller")
        kodlar = {p["kod"] for p in r.json()}
        assert "cihaz_hat" in kodlar
        assert "cihaz_arac" not in kodlar  # isemri.yaz yok

    async def test_teknik_servis_montaj_aktarabilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "teknik", "TEKNIK_SERVIS")
        r = await client.get("/api/ice-aktarma/profiller")
        kodlar = {p["kod"] for p in r.json()}
        assert "cihaz_arac" in kodlar
        assert "cihaz_zimmet" not in kodlar  # cihaz.transfer yok

    async def test_depo_zimmet_aktarabilir(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "depocu", "DEPO")
        r = await client.get("/api/ice-aktarma/profiller")
        assert "cihaz_zimmet" in {p["kod"] for p in r.json()}

    async def test_satis_eslestirme_yapamaz(self, client, kullanici_ac):
        await _giris(client, kullanici_ac, "satisci", "SATIS")
        r = await _yukle(
            client, "cihaz_hat", xlsx([["IMEI", "ICCID"], ["860000000000001", "899001"]])
        )
        assert r.status_code == 403
