"""Dalga 1 bütünleştirmesinde paketler arasına çekilen bağlantılar.

- Genel arama servis işini bulur, kapsam dışı işi göstermez (TS-037, D1-C talebi).
- KVKK saklama listesi son N yılda servis işi olan müşteriyi dışarıda tutar (TS-037).
- Servis formu PDF'i üretilemezse 503 (500 değil; teklif ucu emsali).
- Bakım formu tamamlamada süre kaydı eksikliği sorulur (TS-076, D1-G talebi).
- Genel ayar ucu otomatik PB üretimini eşleştirme %100 olmadan açamaz (TS-063).
"""

from __future__ import annotations

import pytest
from bakim_yardimci import ONEK as BAKIM
from bakim_yardimci import ata, hepsini_eslestir, ortam_kur, pb_isleri, sozlesme_ac, tum_uygun
from servis_yardimci import giris, olay_sayisi
from sqlalchemy import select

from app.clock import FakeClock
from app.models import Account, ServiceOrder, ServiceOrderEvent
from app.services import kvkk
from app.services import settings as ayar_svc

pytestmark = pytest.mark.integration

IS = "/api/teknik-servis/isler"


@pytest.fixture
async def kisiler(kullanici_ac, birimli_kullanici_ac):
    return {
        "admin": await kullanici_ac("admin_bt", "ADMIN"),
        "sef": await birimli_kullanici_ac("sef_bt", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF"),
        "sef_h": await birimli_kullanici_ac("sefh_bt", "SERVIS_SEF", ["HABERLESME"]),
        "tek": await birimli_kullanici_ac(
            "tek_bt", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "tek2": await birimli_kullanici_ac(
            "tek2_bt", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "operasyon": await birimli_kullanici_ac("op_bt", "SERVIS_OPERASYON", ["GUVENLIK"]),
    }


async def test_kategori_yalniz_servis_kapat_ile_gerekceli_duzeltilir(
    client, db, kisiler, servis_isi_ac
) -> None:
    """E01-16 / TS-031: kategori türden türetilir; düzeltme `servis.kapat` + gerekçe."""
    so = await servis_isi_ac()
    assert so.kategori == "GUNLUK_SERVIS"
    yol = f"{IS}/{so.id}"
    await giris(client, "op_bt")  # servis.yaz var, servis.kapat yok
    r = await client.patch(yol, json={"version": so.version, "kategori": "PROJE", "gerekce": "x"})
    assert r.status_code == 403
    await giris(client, "sefh_bt")  # başka birim → 404, veri değişmez
    r = await client.patch(
        yol, json={"version": so.version, "kategori": "PROJE", "gerekce": "Proje işi"}
    )
    assert r.status_code == 404
    await giris(client, "sef_bt")
    r = await client.patch(yol, json={"version": so.version, "kategori": "PROJE"})
    assert r.status_code == 400  # gerekçesiz
    r = await client.patch(
        yol, json={"version": so.version, "kategori": "PLANLI_BAKIM", "gerekce": "Yanlış"}
    )
    assert r.status_code == 409
    await db.refresh(so)
    assert so.kategori == "GUNLUK_SERVIS"
    once = await olay_sayisi(db, so.id, "DUZELTME")
    r = await client.patch(
        yol, json={"version": so.version, "kategori": "PROJE", "gerekce": "Proje kapsamında"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["kategori"] == "PROJE"
    assert await olay_sayisi(db, so.id, "DUZELTME") == once + 1


async def test_saha_onerisi_lokasyon_irtibat_listesi(client, db, kisiler, lokasyon_ac) -> None:
    """TS-034: seçicide lokasyonun bütün irtibatları (birincil önce); başka tesisin
    ya da yalnız carinin irtibatı listeye girmez."""
    from app.models import Contact

    hesap = Account(title="İrtibat Listesi A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    tesis = await lokasyon_ac(hesap, ad="Liste Tesisi")
    diger = await lokasyon_ac(hesap, ad="Diğer Tesis")
    a = Contact(
        account_id=hesap.id, address_id=tesis.id, full_name="Ahmet Saha", phone="+905320000001"
    )
    b = Contact(account_id=hesap.id, address_id=tesis.id, full_name="Zeynep Birincil")
    c = Contact(account_id=hesap.id, address_id=diger.id, full_name="Başka Tesis Kişisi")
    d = Contact(account_id=hesap.id, full_name="Cari Muhasebe")
    db.add_all([a, b, c, d])
    await db.commit()
    tesis.primary_contact_id = b.id
    await db.commit()
    await giris(client, "op_bt")
    r = await client.get(
        "/api/teknik-servis/ana-veri/saha-onerisi", params={"lokasyon_id": tesis.id}
    )
    assert r.status_code == 200, r.text
    v = r.json()
    assert [k["ad"] for k in v["irtibatlar"]] == ["Zeynep Birincil", "Ahmet Saha"]
    assert v["irtibat"]["id"] == b.id
    assert v["irtibatlar"][1]["telefon"] == "+905320000001"  # servis.yaz → tam telefon


async def test_kutukten_toplu_servis_isi_ac(client, db, kisiler, lokasyon_ac, ekipman_ac) -> None:
    """TS-053 T2 (E03-11): seçili her ekipman için bir iş; ihlalde hiçbiri açılmaz."""
    from sqlalchemy import func

    hesap = Account(title="Kütük Toplu A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    tesis = await lokasyon_ac(hesap, ad="Kütük Tesisi")
    e1 = await ekipman_ac(musteri=hesap, lokasyon=tesis, seri="KT-001")
    e2 = await ekipman_ac(musteri=hesap, lokasyon=tesis, tip="KAPI_DEDEKTORU", seri="KT-002")
    sahipsiz = await ekipman_ac(musteri=hesap, seri="KT-003")
    sahipsiz.account_id = None
    await db.commit()

    async def is_sayisi() -> int:
        return int(await db.scalar(select(func.count(ServiceOrder.id))) or 0)

    yol = f"{IS}/ekipmandan"
    govde = {"ekipman_idler": [e1.id, e2.id], "konu": "Toplu kontrol", "talep_kanali": "TELEFON"}
    await giris(client, "op_bt")  # ekipman.gor yok
    assert (await client.post(yol, json=govde)).status_code == 403
    await giris(client, "sefh_bt")  # başka birim → 404, hiçbir iş açılmaz
    assert (await client.post(yol, json=govde)).status_code == 404
    await giris(client, "sef_bt")
    assert (await client.post(yol, json=govde)).status_code == 400  # irtibat yok
    r = await client.post(yol, json={**govde, "ekipman_idler": [e1.id, sahipsiz.id],
                                     "iletisim_ad": "Saha Yetkilisi"})  # fmt: skip
    assert r.status_code == 409 and "KT-003" in r.text
    assert await is_sayisi() == 0

    r = await client.post(yol, json={**govde, "iletisim_ad": "Saha Yetkilisi"})
    assert r.status_code == 201, r.text
    assert r.json()["acilan"] == 2
    isler = (await db.scalars(select(ServiceOrder).order_by(ServiceOrder.id))).all()
    assert [(s.equipment_id, s.address_id, s.customer_id, s.birim) for s in isler] == [
        (e1.id, tesis.id, hesap.id, "GUVENLIK"),
        (e2.id, tesis.id, hesap.id, "GUVENLIK"),
    ]
    assert [s.seri_no for s in isler[0].seriler] == ["KT-001"]

    # Açık işte aynı seri: 409 MUKERRER, geçilirse açılır.
    r = await client.post(yol, json={**govde, "iletisim_ad": "Saha Yetkilisi"})
    assert r.status_code == 409 and r.json()["detail"]["kod"] == "MUKERRER"
    assert await is_sayisi() == 2
    r = await client.post(
        yol, json={**govde, "iletisim_ad": "Saha Yetkilisi", "mukerrer_gec": True}
    )
    assert r.status_code == 201
    assert await is_sayisi() == 4


async def test_hesapsiz_ekipman_irtibati_kvkk_ile_imha_edilir(
    client, db, kisiler, ekipman_ac
) -> None:
    """TS-057: hesap anonimleştirmesine girmeyen (göç) ekipmanın irtibatı tek
    yoldan silinir; geçmiş denetim satırlarındaki değerler maskelenir."""
    from app.models import AuditLog

    e = await ekipman_ac(seri="GOC-1")
    e.account_id = None
    e.contact_name_raw = "Mehmet Bey 0532"
    await db.commit()
    db.add(
        AuditLog(
            entity="service_equipment",
            entity_id=str(e.id),
            action="irtibat",
            old_value={"contact_name_raw": None},
            new_value={"contact_name_raw": "Mehmet Bey 0532"},
            is_personal_data=True,
        )
    )
    await db.commit()
    yol = f"/api/teknik-servis/ekipman/{e.id}/irtibat-imha"
    await giris(client, "sef_bt")  # kvkk.yonet yok
    assert (await client.post(yol, json={"gerekce": "Başvuru #1"})).status_code == 403
    await giris(client, "admin_bt")
    assert (await client.post(yol, json={"gerekce": ""})).status_code == 422
    r = await client.post(yol, json={"gerekce": "KVKK başvurusu #1"})
    assert r.status_code == 200, r.text
    assert r.json()["maskelenen_denetim_satiri"] == 1
    await db.refresh(e)
    assert e.contact_name_raw is None
    metin = " ".join(
        str(x)
        for x in (
            await db.scalars(
                select(AuditLog.new_value).where(AuditLog.entity == "service_equipment")
            )
        ).all()
    )
    assert "Mehmet" not in metin


async def test_genel_arama_servis_isi_kapsamli(client, kisiler, servis_isi_ac) -> None:
    so = await servis_isi_ac(atananlar=[kisiler["tek"]], konu="Aranan iş")
    for kullanici, gorur in (("sef_bt", True), ("tek_bt", True), ("tek2_bt", False),
                             ("sefh_bt", False)):  # fmt: skip
        await giris(client, kullanici)
        r = await client.get("/api/arama", params={"q": so.so_no})
        assert r.status_code == 200, (kullanici, r.text)
        bulunan = [s for s in r.json() if s["tur"] == "SERVIS_ISI"]
        assert bool(bulunan) is gorur, kullanici
        if gorur:
            assert bulunan[0]["id"] == so.id and bulunan[0]["yol"] == f"/servis-isleri/{so.id}"


async def test_saklama_listesi_servis_isi_olan_musteriyi_haric_tutar(db, servis_isi_ac) -> None:
    hareketsiz = Account(title="Hareketsiz Müşteri", is_musteri=True)
    servisli = Account(title="Servisli Müşteri", is_musteri=True)
    db.add_all([hareketsiz, servisli])
    await db.commit()
    await servis_isi_ac(musteri=servisli)
    liste = {s["account_id"] for s in await kvkk.saklama_suresi_dolanlar(db, FakeClock(), yil=1)}
    assert hareketsiz.id in liste
    assert servisli.id not in liste


async def test_servis_formu_pdf_uretilemezse_503(
    client, kisiler, servis_isi_ac, monkeypatch
) -> None:
    from app.services.pdf import PdfUretilemedi
    from app.services.teknik_servis import onay

    async def _bozuk(*_a, **_k):
        raise PdfUretilemedi("PDF motoru kurulu değil")

    monkeypatch.setattr(onay, "servis_formu_pdf", _bozuk)
    monkeypatch.setattr(onay, "ziyaret_formu_pdf", _bozuk)
    so = await servis_isi_ac()
    await giris(client, "sef_bt")
    assert (await client.get(f"{IS}/{so.id}/servis-formu.pdf")).status_code == 503
    r = await client.get(f"{IS}/ziyaret-formu.pdf", params={"is_id": so.id})
    assert r.status_code == 503


async def test_bakim_formu_sure_eksikse_onay_ister(
    client, db, kisiler, lokasyon_ac, ekipman_ac
) -> None:
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0, ad="Süre Eksik")
    await giris(client, "sef_bt")
    s = await sozlesme_ac(client, o)
    await hepsini_eslestir(client, s["id"], o)
    assert (await client.post(f"{BAKIM}/uretim")).status_code == 200
    [so] = await pb_isleri(db, s["id"])
    await ata(db, so, kisiler["tek"])
    so.status = "SAHADA"  # sahaya gidildi ama sayaç tutulmadı
    await db.commit()

    await giris(client, "tek_bt")
    form = (await client.get(f"{BAKIM}/formlar/{so.id}")).json()
    r = await client.put(
        f"{BAKIM}/formlar/{so.id}",
        json={
            "version": form["form"]["version"],
            "zone": "Giriş",
            "technician_note": "Sorun yok",
            "bakim_sonucu": "TAMAMLANDI",
            "kontroller": tum_uygun(form),
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{BAKIM}/formlar/{so.id}/onay", json={"tur": "ALINAMADI", "eksik_nedeni": "Yok"}
    )
    assert r.status_code == 201, r.text
    once_not = await olay_sayisi(db, so.id, "NOT")

    r = await client.post(f"{BAKIM}/formlar/{so.id}/tamamla")
    assert r.status_code == 409 and "Süre kaydı eksik" in r.text, r.text
    so_db = await db.get(ServiceOrder, so.id)
    await db.refresh(so_db)
    assert so_db.status == "SAHADA"

    r = await client.post(f"{BAKIM}/formlar/{so.id}/tamamla", json={"sure_eksik_onay": True})
    assert r.status_code == 200, r.text
    assert r.json()["so"]["status"] == "TAMAMLANDI"
    assert await olay_sayisi(db, so.id, "NOT") == once_not + 1
    ozet = await db.scalar(
        select(ServiceOrderEvent.ozet)
        .where(ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "NOT")
        .order_by(ServiceOrderEvent.id.desc())
        .limit(1)
    )
    assert ozet.startswith("Süre kaydı eksik olarak kapatıldı")


async def test_hesap_anonimlestirme_bakim_serbest_metinlerini_siler(
    client, db, kisiler, lokasyon_ac, ekipman_ac
) -> None:
    """TS-069: sözleşme notu ve form teknisyen notu anonimleştirmede silinir;
    sözleşme, PB ve form satırları durur."""
    from app.models import MaintenanceContract, MaintenanceForm

    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0, ad="Anonim Bakım")
    await giris(client, "sef_bt")
    s = await sozlesme_ac(client, o, notes="Kapıda Ahmet Bey'i arayın 0532 000 00 00")
    await hepsini_eslestir(client, s["id"], o)
    assert (await client.post(f"{BAKIM}/uretim")).status_code == 200
    [so] = await pb_isleri(db, s["id"])
    form = await db.scalar(select(MaintenanceForm).where(MaintenanceForm.service_order_id == so.id))
    form.technician_note = "Teslim alan: Ahmet Yılmaz"
    await db.commit()

    sonuc = await kvkk.hesabi_anonimlestir(
        db, o.musteri.id, clock=FakeClock(), gerekce="KVKK silme talebi #12"
    )
    await db.commit()
    assert sonuc  # özet döner
    sozlesme = await db.get(MaintenanceContract, s["id"])
    await db.refresh(sozlesme)
    await db.refresh(form)
    assert sozlesme.notes is None and sozlesme.is_deleted is False
    assert form.technician_note is None
    assert len(await pb_isleri(db, s["id"])) == 1


async def test_genel_ayar_ucu_otomatik_uretimi_eslestirmesiz_acamaz(
    client, db, kisiler, lokasyon_ac, ekipman_ac
) -> None:
    o = await ortam_kur(db, lokasyon_ac, ekipman_ac, xray=1, kapi=0, ad="Ayar Kapısı")
    await giris(client, "sef_bt")
    await sozlesme_ac(client, o)  # eşleştirilmemiş aktif sözleşme
    await giris(client, "admin_bt")
    r = await client.patch("/api/ayarlar", json={"values": {"bakim_otomatik_uretim": True}})
    assert r.status_code == 409
    assert await ayar_svc.get(db, "bakim_otomatik_uretim") is False
    # Kapatmak ve başka anahtarları değiştirmek serbest.
    r = await client.patch(
        "/api/ayarlar",
        json={"values": {"bakim_otomatik_uretim": False, "bakim_sozlesme_bitis_uyari_gun": 45}},
    )
    assert r.status_code == 200, r.text
    assert await ayar_svc.get(db, "bakim_sozlesme_bitis_uyari_gun") == 45
