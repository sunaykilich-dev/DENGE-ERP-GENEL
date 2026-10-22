"""Serbest metin müşteri/lokasyon eşleştirmesi Faz 1 (TS-171, E14-09).

Kabul:
1. Aday üretimi veriyi değiştirmez (satır ve `version` aynı).
2. Yalnız onaylı satırlar `account_id/address_id` ve takma ada yazılır.
3. Ham metin kolonları korunur.
4. Müşterisi boş ekipman ayrı sayfadadır.
5. Aynı dosya ikinci kez uygulanırsa 0 satır yazılır.
6. Sonuç tablo bazında yazılan satır sayısını verir.
7. `hesap.birlestir` olmayan kullanıcı 403.
Ek: belirsiz ad öneri üretmez (insana döner); müşteri olmayan hedef ve
başka hesaba ait tesis karantinaya düşer; başka hesaba bağlı kayıt çakışmadır.
"""

import io

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import Account, AccountAlias, Address, MaintenanceContract, ServiceEquipment
from app.services import imports as ice
from app.services.imports.musteri_eslestirme import MusteriEslestirmeProfili
from app.services.teknik_servis import numara, veri_kalitesi

pytestmark = pytest.mark.integration

URL = "/api/teknik-servis/ana-veri/eslestirme"


async def _kurulum(db):
    akyaka = Account(title="Akyaka Park AVM", is_musteri=True)
    tedarikci = Account(title="Tedarikçi A.Ş.", is_musteri=False, is_tedarikci=True)
    ortak1 = Account(title="Ortak Ad", is_musteri=True)
    ortak2 = Account(title="ORTAK AD", is_musteri=True)
    db.add_all([akyaka, tedarikci, ortak1, ortak2])
    await db.flush()
    yabanci_tesis = Address(
        account_id=ortak1.id, kind="TESIS", label="Tesis", site_name="Yabancı Tesis"
    )
    db.add(yabanci_tesis)
    s1 = MaintenanceContract(
        contract_no=await numara.bakim_sozlesme_no(db),
        status="TEYIT_BEKLIYOR",
        teyit_gerekcesi="Göç",
        customer_name_raw="Akyaka Park AVM",
        site_name_raw="Akyaka Park AVM",
    )
    s2 = MaintenanceContract(
        contract_no=await numara.bakim_sozlesme_no(db),
        status="TEYIT_BEKLIYOR",
        teyit_gerekcesi="Göç",
        customer_name_raw="ORTAK AD",
    )
    e1 = ServiceEquipment(
        birim="GUVENLIK",
        equipment_type="XRAY",
        serial_no="E-1",
        customer_name_raw="Akyaka AVM Güvenlik Birimi",
        location_raw="Akyaka Kuzey Girişi",
    )
    e2 = ServiceEquipment(birim="GUVENLIK", equipment_type="XRAY", serial_no="E-2")
    e3 = ServiceEquipment(
        birim="GUVENLIK", equipment_type="XRAY", serial_no="E-3", customer_name_raw="Tedarik Yazımı"
    )
    db.add_all([s1, s2, e1, e2, e3])
    await db.commit()
    return {
        "akyaka": akyaka,
        "tedarikci": tedarikci,
        "yabanci_tesis": yabanci_tesis,
        "s1": s1,
        "s2": s2,
        "e1": e1,
        "e2": e2,
        "e3": e3,
    }


async def _giris(client, birimli_kullanici_ac, ad: str, rol: str):
    await birimli_kullanici_ac(ad, rol, ["GUVENLIK"])
    r = await client.post("/api/auth/login", json={"username": ad, "password": "parola1234"})
    assert r.status_code == 200, r.text


def _sayfa(icerik: bytes, ad: str) -> list[list]:
    ws = load_workbook(io.BytesIO(icerik))[ad]
    return [list(s) for s in ws.iter_rows(values_only=True)]


def _xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    for s in satirlar:
        wb.active.append(s)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def _uygula(db, satirlar: list[list], kararlar=None):
    profil = MusteriEslestirmeProfili()
    okuma = ice.oku("eslestirme.xlsx", _xlsx(satirlar), profil)
    staged = [s.sozluk() for s in await profil.dogrula(db, okuma.satirlar)]
    sayac = await profil.yaz(db, staged, clock=FakeClock(), user_id=None, kararlar=kararlar or {})
    await db.commit()
    return staged, sayac


async def test_yetkisiz_403_yetkili_200_ve_aday_veriyi_degistirmez(
    client, seeded, birimli_kullanici_ac
):
    db = seeded
    k = await _kurulum(db)
    await _giris(client, birimli_kullanici_ac, "tekno", "SERVIS_TEKNISYEN")
    assert (await client.get(f"{URL}/ozet")).status_code == 403
    assert (await client.get(f"{URL}/adaylar.xlsx?kaynak=ekipman")).status_code == 403
    await client.post("/api/auth/logout")

    await _giris(client, birimli_kullanici_ac, "yonetici", "SERVIS_YONETICI")
    surumler = {
        "s1": k["s1"].version,
        "e1": k["e1"].version,
    }
    r = await client.get(f"{URL}/adaylar.xlsx?kaynak=ekipman")
    assert r.status_code == 200
    adaylar = _sayfa(r.content, "Adaylar")
    assert adaylar[0] == veri_kalitesi.ADAY_BASLIKLARI
    ids = {satir[1] for satir in adaylar[1:]}
    assert k["e1"].id in ids and k["e2"].id not in ids
    bos = _sayfa(r.content, "Musterisi Bos")
    assert [satir[1] for satir in bos[1:]] == [k["e2"].id]  # kabul 4

    r = await client.get(f"{URL}/adaylar.xlsx?kaynak=sozlesme")
    satirlar = {s[1]: s for s in _sayfa(r.content, "Adaylar")[1:]}
    assert satirlar[k["s1"].id][4] == k["akyaka"].id and satirlar[k["s1"].id][6] == "UNVAN_ANAHTARI"
    assert satirlar[k["s2"].id][4] is None and str(satirlar[k["s2"].id][6]).startswith("BELIRSIZ")
    assert (await client.get(f"{URL}/adaylar.xlsx?kaynak=yanlis")).status_code == 422

    ozet = (await client.get(f"{URL}/ozet")).json()
    assert ozet["sozlesme"]["belirsiz"] == 1 and ozet["ekipman"]["musterisiz"] == 1

    for ad in ("s1", "e1"):
        await db.refresh(k[ad])
        assert k[ad].version == surumler[ad]  # kabul 1
    assert await db.scalar(select(func.count()).select_from(AccountAlias)) == 0


async def test_onayli_satir_yazar_onaysiz_yazmaz_ve_idempotent(seeded):
    db = seeded
    k = await _kurulum(db)
    satirlar = [
        list(veri_kalitesi.ADAY_BASLIKLARI),
        # Onaylı: öneriyle.
        [
            "maintenance_contracts",
            k["s1"].id,
            None,
            None,
            k["akyaka"].id,
            None,
            None,
            None,
            None,
            "E",
            None,
            None,
            None,
        ],
        # Onaylı: hedef + yeni tesis; ham metin takma ada gider.
        [
            "service_equipment",
            k["e1"].id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "E",
            k["akyaka"].id,
            None,
            "Akyaka Kuzey",
        ],
        # Onaysız: hiçbir şey yazılmaz.
        [
            "maintenance_contracts",
            k["s2"].id,
            None,
            None,
            k["akyaka"].id,
            None,
            None,
            None,
            None,
            "",
            None,
            None,
            None,
        ],
    ]
    staged, sayac = await _uygula(db, satirlar)
    assert [s["hatalar"] for s in staged] == [[], [], []]
    assert sayac["tablolar"]["maintenance_contracts"]["yazilan"] == 1
    assert sayac["tablolar"]["service_equipment"]["yazilan"] == 1

    for ad in ("s1", "s2", "e1"):
        await db.refresh(k[ad])
    assert k["s1"].account_id == k["akyaka"].id
    assert k["s2"].account_id is None  # onaysız
    assert k["e1"].account_id == k["akyaka"].id and k["e1"].address_id is not None
    tesis = await db.get(Address, k["e1"].address_id)
    assert (
        tesis.kind == "TESIS" and tesis.site_name == "Akyaka Kuzey" and tesis.is_verified is False
    )
    # Ham metin korunur (kabul 3).
    assert k["e1"].customer_name_raw == "Akyaka AVM Güvenlik Birimi"
    assert k["e1"].location_raw == "Akyaka Kuzey Girişi"
    takma = (await db.scalars(select(AccountAlias).order_by(AccountAlias.id))).all()
    assert {(t.alias_text, t.kaynak, t.kaynak_tablo) for t in takma} == {
        ("Akyaka AVM Güvenlik Birimi", "ESLESTIRME", "service_equipment"),
        ("Akyaka Kuzey Girişi", "ESLESTIRME", "service_equipment"),
    }

    _, ikinci = await _uygula(db, satirlar)
    assert ikinci["guncellendi"] == 0 and ikinci["takma_ad"] == 0  # kabul 5
    assert await db.scalar(select(func.count()).select_from(AccountAlias)) == 2
    assert (
        await db.scalar(
            select(func.count()).select_from(Address).where(Address.site_name == "Akyaka Kuzey")
        )
        == 1
    )


async def test_karantina_ve_cakisma(seeded):
    db = seeded
    k = await _kurulum(db)
    k["e3"].account_id = k["akyaka"].id
    await db.commit()
    satirlar = [
        list(veri_kalitesi.ADAY_BASLIKLARI),
        [
            "maintenance_contracts",
            k["s1"].id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "E",
            k["tedarikci"].id,
            None,
            None,
        ],
        [
            "maintenance_contracts",
            k["s2"].id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "E",
            k["akyaka"].id,
            k["yabanci_tesis"].id,
            None,
        ],
        [
            "service_equipment",
            k["e3"].id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "E",
            k["tedarikci"].id,
            None,
            None,
        ],
    ]
    staged, sayac = await _uygula(db, satirlar)
    assert "müşteri değil" in staged[0]["hatalar"][0]
    assert "başka hesaba ait" in staged[1]["hatalar"][0]
    assert sayac["tablolar"]["maintenance_contracts"]["karantina"] == 2
    await db.refresh(k["s1"])
    assert k["s1"].account_id is None

    # Başka hesaba bağlı kayıt: hedef müşteri olsa bile çakışma → varsayılan atla.
    tedarikci = k["tedarikci"]
    tedarikci.is_musteri = True
    await db.commit()
    staged, sayac = await _uygula(db, [satirlar[0], satirlar[3]])
    assert staged[0]["cakisma"]["tip"] == "farkli_hesap"
    await db.refresh(k["e3"])
    assert k["e3"].account_id == k["akyaka"].id
