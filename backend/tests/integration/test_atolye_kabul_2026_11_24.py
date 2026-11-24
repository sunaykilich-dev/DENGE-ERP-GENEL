"""2026-11-24 sahip belgesi: atölye cihaz kabulü geliştirmeleri.

- Aksesuar listesi yenilendi (Şarj yuvası, Klips, Adaptör adları; yeni türler);
  toplu kabulde aksesuar HER CİHAZ için ayrı.
- Haberleşme ekipman tipi: Araç Telsizi, Aksesuar.
- Model listesi: `atolye.model_ekle` izniyle eklenir, aynı ad tek satır.
- İrtibat: müşterinin tüm kişileri listelenir; kabul ekranından eklenir.
- Kullanıcının varsayılan iş türü (`/auth/me`'de döner).
- Seri geçmişi garanti başlangıcını da verir (kabul ekranı otomatik doldurur).
"""

import pytest
from atolye_yardimci import ONEK, kabul_et, sef
from servis_yardimci import giris, musteri
from sqlalchemy import select

from app.models import Contact, ServiceEquipment

pytestmark = pytest.mark.integration


async def test_aksesuar_ve_tip_listesi(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    await giris(client, "atl_sef")
    v = (await client.get(f"{ONEK}/form-verileri", params={"birim": "HABERLESME"})).json()
    adlar = {t["kod"]: t["ad"] for t in v["aksesuar_turleri"]}
    assert adlar["SARJ_UNITESI"] == "Şarj yuvası"
    assert adlar["KEMER_KLIPSI"] == "Klips"
    assert adlar["SARJ_ADAPTORU"] == "Adaptör"
    for yeni in (
        "SARJ_KABLOSU",
        "SARJ_TAKIMI",
        "ASKI_IPI",
        "KAPAK",
        "SIM",
        "KUTU",
        "SPEAKER_MIKROFON",
    ):
        assert yeni in adlar
    # Sahip kararı: eski türler de seçilebilir kalır.
    assert {"KILIF", "HARICI_MIKROFON", "KABLO", "DIGER"} <= set(adlar)
    assert {"ARAC_TELSIZI", "AKSESUAR", "TELSIZ"} <= set(v["ekipman_tipleri"])


async def test_toplu_kabulde_cihaz_basina_aksesuar(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    r = await client.post(
        f"{ONEK}/toplu-kabul",
        json={
            "customer_id": hesap.id,
            "service_type": "ARIZA_ONARIMI",
            "receive_type": "KARGO",
            "customer_complaint": "Toplu arıza",
            "cihazlar": [
                {
                    "tip": "ARAC_TELSIZI",
                    "marka": "HYTERA",
                    "seri": "ARC-1",
                    "aksesuarlar": [
                        {"kind": "SARJ_TAKIMI", "qty": 1},
                        {"kind": "SPEAKER_MIKROFON", "qty": 2},
                    ],
                },
                {
                    "tip": "AKSESUAR",
                    "marka": "HYTERA",
                    "seri": "AKS-1",
                    "aksesuarlar": [
                        {"kind": "SIM", "qty": 1},
                        {"kind": "DIGER", "qty": 1, "description": "Bel çantası"},
                    ],
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    kayitlar = r.json()["kayitlar"]
    d1 = (await client.get(f"{ONEK}/{kayitlar[0]['so_id']}")).json()
    d2 = (await client.get(f"{ONEK}/{kayitlar[1]['so_id']}")).json()
    assert sorted((a["kind"], a["qty"]) for a in d1["aksesuarlar"]) == [
        ("SARJ_TAKIMI", 1),
        ("SPEAKER_MIKROFON", 2),
    ]
    assert sorted(a["kind"] for a in d2["aksesuarlar"]) == ["DIGER", "SIM"]
    tipler = set(
        (
            await db.scalars(
                select(ServiceEquipment.equipment_type).where(
                    ServiceEquipment.serial_no.in_(["ARC-1", "AKS-1"])
                )
            )
        ).all()
    )
    assert tipler == {"ARAC_TELSIZI", "AKSESUAR"}


async def test_model_listesi(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("op_model", "SERVIS_OPERASYON", ["HABERLESME"])
    await birimli_kullanici_ac("yon_model", "YONETIM", ["HABERLESME"])
    await giris(client, "op_model")
    r = await client.post(f"{ONEK}/modeller", json={"marka": "HYTERA", "model": " PNC  550 "})
    assert r.status_code == 201, r.text
    ilk = r.json()
    assert ilk["model"] == "PNC 550"
    # Büyük/küçük harf farkı aynı model: yeni satır açılmaz.
    r = await client.post(f"{ONEK}/modeller", json={"marka": "hytera", "model": "pnc 550"})
    assert r.status_code == 201 and r.json()["id"] == ilk["id"]
    await client.post(f"{ONEK}/modeller", json={"marka": "HYTERA", "model": "BD505"})
    await client.post(f"{ONEK}/modeller", json={"marka": "MOTOROLA", "model": "DP4400"})
    liste = (await client.get(f"{ONEK}/modeller", params={"marka": "hytera"})).json()
    assert [m["model"] for m in liste] == ["BD505", "PNC 550"]

    # Salt okunur yönetim listeyi görür, model ekleyemez.
    await giris(client, "yon_model")
    assert (await client.get(f"{ONEK}/modeller", params={"marka": "HYTERA"})).status_code == 200
    r = await client.post(f"{ONEK}/modeller", json={"marka": "HYTERA", "model": "X1"})
    assert r.status_code == 403


async def test_irtibat_listesi_ve_ekleme(client, db, birimli_kullanici_ac) -> None:
    await birimli_kullanici_ac("op_irt", "SERVIS_OPERASYON", ["HABERLESME"])
    hesap = await musteri(db)
    baska = await musteri(db, "Başka Müşteri A.Ş.")
    db.add_all(
        [
            Contact(account_id=hesap.id, full_name="Zeynep Yetkili", is_primary=True),
            Contact(account_id=hesap.id, full_name="Ali Teknik", title="Teknik sorumlu"),
            Contact(account_id=baska.id, full_name="Yabancı Kişi"),
        ]
    )
    await db.commit()
    hesap_id = hesap.id
    await giris(client, "op_irt")
    r = await client.get(f"{ONEK}/irtibatlar", params={"musteri_id": hesap_id})
    assert r.status_code == 200, r.text
    assert [k["ad"] for k in r.json()] == ["Zeynep Yetkili", "Ali Teknik"]

    r = await client.post(
        f"{ONEK}/irtibatlar",
        json={
            "musteri_id": hesap_id,
            "ad": "Yeni  Kişi",
            "unvan": "Depo",
            "telefon": "05321234567",
        },
    )
    assert r.status_code == 201, r.text
    yeni = r.json()
    assert yeni["ad"] == "Yeni Kişi" and yeni["telefon"].startswith("+90")
    assert (
        len((await client.get(f"{ONEK}/irtibatlar", params={"musteri_id": hesap_id})).json()) == 3
    )

    # Eklenen kişi kabulde irtibat olarak kullanılır.
    d = await kabul_et(client, hesap_id, "IRT-1", birim="HABERLESME", contact_id=yeni["id"])
    assert d["contact_id"] == yeni["id"]

    r = await client.post(f"{ONEK}/irtibatlar", json={"musteri_id": 999999, "ad": "Hayalet"})
    assert r.status_code == 400


async def test_seri_gecmisi_garanti_baslangici(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db)
    await giris(client, "atl_sef")
    await kabul_et(
        client,
        hesap.id,
        "GAR-1",
        ekipman={"warranty_start": "2026-01-10", "warranty_end": "2028-01-10"},
    )
    g = (
        await client.get(
            f"{ONEK}/seri-gecmisi", params={"tip": "TELSIZ", "marka": "HYTERA", "seri": "GAR-1"}
        )
    ).json()
    assert g["ekipmanlar"][0]["warranty_start"] == "2026-01-10"
    assert g["ekipmanlar"][0]["warranty_end"] == "2028-01-10"


async def test_kullanici_varsayilan_is_turu(client, db, kullanici_ac, birimli_kullanici_ac) -> None:
    await kullanici_ac("yonetici_vt", "ADMIN")
    op = await birimli_kullanici_ac("op_vt", "SERVIS_OPERASYON", ["HABERLESME"])
    op_id = op.id
    await giris(client, "yonetici_vt")
    r = await client.patch(f"/api/kullanicilar/{op_id}", json={"varsayilan_is_turu": "ARIZA"})
    assert r.status_code == 200, r.text
    assert r.json()["varsayilan_is_turu"] == "ARIZA"
    r = await client.patch(f"/api/kullanicilar/{op_id}", json={"varsayilan_is_turu": "UYDURMA"})
    assert r.status_code == 400

    await giris(client, "op_vt")
    me = (await client.get("/api/auth/me")).json()
    assert me["varsayilan_is_turu"] == "ARIZA"
    assert me["birincil_birim"] == "HABERLESME"

    await giris(client, "yonetici_vt")
    r = await client.patch(f"/api/kullanicilar/{op_id}", json={"varsayilan_is_turu": ""})
    assert r.status_code == 200 and r.json()["varsayilan_is_turu"] is None
