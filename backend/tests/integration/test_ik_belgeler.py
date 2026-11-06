"""İK "Bordro ve Belgeler" (KARARLAR_2026-10-28 §11).

Kilitlenen kurallar:
- Bordro kişi başına PDF; personel yalnız kendi belgesini görür (başkasınınki 404).
- Açılmamış belge onaylanamaz (409); açmak GORULDU olayı yazar.
- Onay/itiraz parola tekrarı ister; yanlış parola 400 ve giriş sayacına işlenir;
  5. yanlışta hesap kilitlenir (423). Yanıt bir daha değişmez (409).
- İtiraz gerekçesi zorunlu; İK takip ekranında görünür.
- Bordro gizli: YONETIM (bütün `.gor`) kapıdan geçemez; yalnız `ik_belge.yonet`
  sahibi bordro gönderimini listede görmez, tekil istekte 404, göndermede 403.
- Aynı dönem bordrosu kişiye iki kez gitmez (409); geri alınınca gider.
  Yanıtlanmış belge geri alınamaz.
- Olay zinciri doğrulanır; veritabanı olay satırının değiştirilmesini reddeder.
- Şablondan form gönderimi, hatırlatma sayacı, PDF dışı dosya reddi,
  girişi kapalı kişiye gönderim reddi, dosya adından eşleştirme.
"""

import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, IkBelgeOlayi, LoginAttempt, User
from app.services import ik_belge as svc

pytestmark = pytest.mark.integration


def pdf(etiket: str) -> bytes:
    return b"%PDF-1.4\n% " + etiket.encode() + b"\n%%EOF\n"


async def giris(client, kullanici: str, parola: str = "parola1234") -> None:
    await client.post("/api/auth/logout")
    r = await client.post("/api/auth/login", json={"username": kullanici, "password": parola})
    assert r.status_code == 200, r.text


async def gonder(client, veri: dict, dosyalar: list[tuple[str, bytes, str]]):
    return await client.post(
        "/api/ik/gonderimler",
        data={"veri": json.dumps(veri)},
        files=[("dosyalar", d) for d in dosyalar],
    )


@pytest.fixture
async def ortam(client, db, kullanici_ac):
    ik = await kullanici_ac("ik", "IK")
    ali = await kullanici_ac("ali", "SERVIS_TEKNISYEN")
    ayse = await kullanici_ac("ayse", "SERVIS_SEF")
    await kullanici_ac("yonetim", "YONETIM")
    ali.sicil_no = "S-1001"
    ali.full_name = "Ali Yılmaz"
    ayse.full_name = "Ayşe Şahin"
    await db.commit()
    return {"ik": ik, "ali": ali, "ayse": ayse}


async def _bordro(client, o, donem="2026-10"):
    await giris(client, "ik")
    r = await gonder(
        client,
        {
            "tur": "BORDRO",
            "baslik": f"{donem} bordrosu",
            "donem": donem,
            "alicilar": [o["ali"].id, o["ayse"].id],
        },
        [("ali.pdf", pdf("ali"), "application/pdf"), ("ayse.pdf", pdf("ayse"), "application/pdf")],
    )
    return r


async def _belgem(client) -> dict:
    r = await client.get("/api/ik/belgelerim")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    return r.json()[0]


async def test_bordro_gonder_gor_onayla_itiraz(client, db, ortam) -> None:
    r = await _bordro(client, ortam)
    assert r.status_code == 201, r.text
    gid = r.json()["gonderim"]["id"]
    assert r.json()["gonderim"]["sayilar"] == {"GONDERILDI": 2}

    # Ali: açmadan onay yok; açınca GORULDU; yanlış parola; doğru parola onaylar.
    await giris(client, "ali")
    assert (await client.get("/api/ik/belgelerim/ozet")).json() == {"bekleyen": 1}
    belge = await _belgem(client)
    assert belge["tur"] == "BORDRO" and belge["durum"] == "GONDERILDI"
    r = await client.post(f"/api/ik/belgelerim/{belge['id']}/onayla", json={"parola": "parola1234"})
    assert r.status_code == 409
    r = await client.get(f"/api/ik/belgelerim/{belge['id']}/dosya")
    assert r.status_code == 200 and r.content == pdf("ali")
    assert r.headers["cache-control"].startswith("no-store")
    r = await client.post(f"/api/ik/belgelerim/{belge['id']}/onayla", json={"parola": "yanlis"})
    assert r.status_code == 400
    r = await client.post(f"/api/ik/belgelerim/{belge['id']}/onayla", json={"parola": "parola1234"})
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "ONAYLANDI"
    r = await client.post(
        f"/api/ik/belgelerim/{belge['id']}/itiraz",
        json={"parola": "parola1234", "gerekce": "Sonradan"},
    )
    assert r.status_code == 409

    # Ayşe: gerekçeli itiraz.
    await giris(client, "ayse")
    b2 = await _belgem(client)
    await client.get(f"/api/ik/belgelerim/{b2['id']}/dosya")
    r = await client.post(f"/api/ik/belgelerim/{b2['id']}/itiraz", json={"parola": "parola1234"})
    assert r.status_code == 422  # gerekçe zorunlu
    r = await client.post(
        f"/api/ik/belgelerim/{b2['id']}/itiraz",
        json={"parola": "parola1234", "gerekce": "Fazla mesai eksik yazılmış"},
    )
    assert r.status_code == 200 and r.json()["durum"] == "ITIRAZ"
    # Başkasının belgesi yok sayılır.
    assert (await client.get(f"/api/ik/belgelerim/{belge['id']}/dosya")).status_code == 404

    # İK takibi.
    await giris(client, "ik")
    d = (await client.get(f"/api/ik/gonderimler/{gid}")).json()
    assert d["sayilar"] == {"ONAYLANDI": 1, "ITIRAZ": 1}
    satir = {s["ad"]: s for s in d["belgeler"]}
    assert satir["Ayşe Şahin"]["itiraz_gerekcesi"] == "Fazla mesai eksik yazılmış"
    assert satir["Ali Yılmaz"]["goruldu_at"] is not None

    k = (await client.get(f"/api/ik/belgeler/{belge['id']}/kanit")).json()
    assert k["zincir_gecerli"] is True
    assert [o["olay"] for o in k["olaylar"]] == ["GONDERILDI", "GORULDU", "ONAYLANDI"]
    assert k["olaylar"][2]["dogrulama"] == "PAROLA"
    assert all(o["belge_ozeti"] == k["belge_ozeti"] for o in k["olaylar"])

    # İK'nın bordroyu açması KVKK erişim loguna düşer; itiraz metni denetim izinde yok.
    await client.get(f"/api/ik/belgeler/{belge['id']}/dosya")
    assert await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "kisisel.eris")
    )
    izler = (await db.scalars(select(AuditLog).where(AuditLog.entity == "ik_belge"))).all()
    assert izler and all("Fazla mesai" not in json.dumps(i.new_value or {}) for i in izler)


async def test_bordro_gizliligi(client, db, ortam, rol_ac, kullanici_ac) -> None:
    gid = (await _bordro(client, ortam)).json()["gonderim"]["id"]

    await giris(client, "yonetim")
    assert (await client.get("/api/ik/gonderimler")).status_code == 403

    rol = await rol_ac("T_FORMCU", ["ik_belge.yonet"])
    formcu = await kullanici_ac("formcu", "IK")
    formcu.role_id = rol.id
    await db.commit()
    await giris(client, "formcu")
    assert (await client.get("/api/ik/gonderimler")).json() == []
    assert (await client.get(f"/api/ik/gonderimler/{gid}")).status_code == 404
    r = await gonder(
        client,
        {
            "tur": "BORDRO",
            "baslik": "x bordrosu",
            "donem": "2026-11",
            "alicilar": [ortam["ali"].id],
        },
        [("a.pdf", pdf("a"), "application/pdf")],
    )
    assert r.status_code == 403


async def test_ayni_donem_tekrar_ve_geri_alma(client, db, ortam) -> None:
    assert (await _bordro(client, ortam)).status_code == 201
    r = await _bordro(client, ortam)
    assert r.status_code == 409 and "geri alın" in r.json()["detail"]

    gid = (await client.get("/api/ik/gonderimler")).json()[0]["id"]
    belgeler = (await client.get(f"/api/ik/gonderimler/{gid}")).json()["belgeler"]
    ali_b = next(b for b in belgeler if b["user_id"] == ortam["ali"].id)
    ayse_b = next(b for b in belgeler if b["user_id"] == ortam["ayse"].id)

    # Ali onaylar → geri alınamaz.
    await giris(client, "ali")
    await client.get(f"/api/ik/belgelerim/{ali_b['id']}/dosya")
    await client.post(f"/api/ik/belgelerim/{ali_b['id']}/onayla", json={"parola": "parola1234"})
    await giris(client, "ik")
    r = await client.post(
        f"/api/ik/belgeler/{ali_b['id']}/geri-al", json={"gerekce": "Hatalı tutar"}
    )
    assert r.status_code == 409
    r = await client.post(
        f"/api/ik/belgeler/{ayse_b['id']}/geri-al", json={"gerekce": "Hatalı tutar"}
    )
    assert r.status_code == 204
    # Ayşe artık görmez; düzeltilmiş bordro yalnız ona gider.
    r = await gonder(
        client,
        {"tur": "BORDRO", "baslik": "Düzeltme", "donem": "2026-10", "alicilar": [ortam["ayse"].id]},
        [("ayse2.pdf", pdf("ayse2"), "application/pdf")],
    )
    assert r.status_code == 201, r.text
    await giris(client, "ayse")
    assert (await _belgem(client))["baslik"] == "Düzeltme"


async def test_sablondan_form_hatirlatma_ve_dosya_kurallari(
    client, db, ortam, kullanici_ac
) -> None:
    await giris(client, "ik")
    r = await client.post(
        "/api/ik/sablonlar",
        data={"ad": "İSG Talimatı", "tur": "TALIMAT"},
        files={"dosya": ("isg.pdf", pdf("isg"), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = await client.post(
        "/api/ik/sablonlar",
        data={"ad": "Word", "tur": "FORM"},
        files={"dosya": ("a.docx", b"PK\x03\x04xx", "application/octet-stream")},
    )
    assert r.status_code == 400

    r = await gonder(
        client,
        {
            "tur": "TALIMAT",
            "baslik": "İSG talimatı 2026",
            "son_tarih": "2026-12-31",
            "sablon_id": sid,
            "alicilar": [ortam["ali"].id, ortam["ayse"].id],
        },
        [],
    )
    assert r.status_code == 201, r.text
    gid = r.json()["gonderim"]["id"]

    r = await client.post(f"/api/ik/gonderimler/{gid}/hatirlat", json={})
    assert r.json() == {"hatirlatilan": 2, "bildirilen": 0}  # SMTP yok
    d = (await client.get(f"/api/ik/gonderimler/{gid}")).json()
    assert {b["hatirlatma_sayisi"] for b in d["belgeler"]} == {1}

    # Girişi kapalı kişiye gönderilmez.
    saha = await kullanici_ac("saha", "SERVIS_TEKNISYEN")
    saha.giris_acik = False
    await db.commit()
    r = await gonder(
        client,
        {"tur": "FORM", "baslik": "Form", "alicilar": [saha.id]},
        [("f.pdf", pdf("f"), "application/pdf")],
    )
    assert r.status_code == 400 and "girişi kapalı" in r.json()["detail"]

    # Personel itirazında belge şablon dosyasının aynısıdır.
    await giris(client, "ali")
    b = await _belgem(client)
    assert b["tur_adi"] == "Talimat" and b["son_tarih"] == "2026-12-31"
    assert (await client.get(f"/api/ik/belgelerim/{b['id']}/dosya")).content == pdf("isg")


async def test_yanlis_parola_kilitler(client, db, ortam) -> None:
    await _bordro(client, ortam)
    await giris(client, "ali")
    b = await _belgem(client)
    await client.get(f"/api/ik/belgelerim/{b['id']}/dosya")
    kodlar = [
        (
            await client.post(f"/api/ik/belgelerim/{b['id']}/onayla", json={"parola": "x"})
        ).status_code
        for _ in range(5)
    ]
    assert kodlar == [400, 400, 400, 400, 423]
    sayac = await db.get(LoginAttempt, "ali")
    await db.refresh(sayac)
    assert sayac.kilitlendi_at is not None
    r = await client.post(f"/api/ik/belgelerim/{b['id']}/onayla", json={"parola": "parola1234"})
    assert r.status_code == 423


async def test_olay_zinciri_degistirilemez(client, db, ortam) -> None:
    await _bordro(client, ortam)
    oid = await db.scalar(select(IkBelgeOlayi.id).limit(1))
    with pytest.raises(DBAPIError):
        await db.execute(
            text("UPDATE ik_belge_olaylari SET ip = '1.2.3.4' WHERE id = :i"), {"i": oid}
        )
    await db.rollback()
    with pytest.raises(DBAPIError):
        await db.execute(text("DELETE FROM ik_belge_olaylari WHERE id = :i"), {"i": oid})
    await db.rollback()
    olay = await db.scalar(select(IkBelgeOlayi).where(IkBelgeOlayi.id == oid))
    assert svc.zincir_dogrula([olay], olay.belge_ozeti)
    olay.ip = "9.9.9.9"  # bellekte kurcalama zinciri bozar
    assert not svc.zincir_dogrula([olay], olay.belge_ozeti)
    await db.rollback()


async def test_dosya_adindan_eslestirme(client, db, ortam, kullanici_ac) -> None:
    ikinci = await kullanici_ac("ali2", "SERVIS_TEKNISYEN")
    ikinci.full_name = "Ali Yılmaz"  # aynı ad: belirsiz
    await db.commit()
    await giris(client, "ik")
    r = await client.post(
        "/api/ik/eslestir",
        json={
            "dosya_adlari": ["2026-10_S-1001.pdf", "AYSE_SAHIN_EKIM.pdf", "ALI YILMAZ.pdf", "x.pdf"]
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s[0]["user_id"], s[0]["yontem"]) == (ortam["ali"].id, "SICIL")
    assert (s[1]["user_id"], s[1]["yontem"]) == (ortam["ayse"].id, "AD")
    assert (s[2]["user_id"], s[2]["yontem"]) == (None, "BELIRSIZ")
    assert s[3]["yontem"] == "YOK"
    alicilar = (await client.get("/api/ik/alicilar")).json()
    assert {a["ad"] for a in alicilar} >= {"Ali Yılmaz", "Ayşe Şahin"}
    assert await db.scalar(select(func.count()).select_from(User)) >= 5
