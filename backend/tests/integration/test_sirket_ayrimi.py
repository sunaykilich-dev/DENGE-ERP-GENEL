"""Şirket ayrımı — gerçek kodla (KARARLAR 2026-11-04 §1).

Bu dosya `sirket_ayrimi` işaretlidir: conftest'in varsayılan testlerde nötr
tuttuğu şirket süzgeci ve mobilite kapısı burada GERÇEK çalışır.

Sınanan kurallar:
- kullanıcının gördüğü birimler = (kapsamı) ∩ (etkin şirketin birimleri);
  liste, KPI ve tek kayıt aynı kuraldan (sayı = liste, tek kayıt 404);
- TUMU kapsamlı yönetici de yalnız etkin şirketi görür; şirket değiştirince
  farklı kayıt görür;
- üye olunmayan şirkete geçiş 403;
- canlı mobilite ekranları DENGE MOBİLİTE dışında 403 `SIRKET_DISI`;
- yeni iş etkin şirkete ait olmayan birimle açılamaz (403);
- `/api/auth/me` ve `/api/oturum/sirketler` sözleşme şekli;
- kullanıcı yönetiminde şirket üyeliği (yalnız `sistem.kullanici`, denetim izi).
"""

import pytest
from servis_yardimci import acilis, giris, musteri
from sqlalchemy import select

from app.models import AuditLog, KullaniciSirketi, Session

pytestmark = [pytest.mark.integration, pytest.mark.sirket_ayrimi]


@pytest.fixture
def uyelik_ver(db):
    async def _ver(user, *kodlar: str) -> None:
        for kod in kodlar:
            db.add(KullaniciSirketi(user_id=user.id, sirket_kod=kod))
        await db.commit()

    return _ver


async def _sec(client, kod: str):
    return await client.put("/api/oturum/aktif-sirket", json={"kod": kod})


async def _liste(client, **params) -> tuple[set[str], int]:
    r = await client.get("/api/teknik-servis/isler", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    govde = r.json()
    satirlar = govde if isinstance(govde, list) else govde.get("satirlar", govde.get("items", []))
    return {s["so_no"] for s in satirlar}, int(r.headers["X-Toplam-Kayit"])


@pytest.fixture
async def isler(servis_isi_ac):
    """Her şirketten bir iş: GUVENLIK (ELEKTRONİK), HABERLESME (TELEKOM),
    BARIYER (ELEKTRONİK), MOBILITE (MOBİLİTE)."""
    return {
        b: await servis_isi_ac(birim=b, konu=f"{b} işi")
        for b in ("GUVENLIK", "HABERLESME", "BARIYER", "MOBILITE")
    }


async def test_oturum_sirketleri_sozlesme_sekli(client, db, kullanici_ac, uyelik_ver) -> None:
    kisi = await kullanici_ac("cok", "SERVIS_YONETICI")
    await uyelik_ver(kisi, "TELEKOM", "ELEKTRONIK")
    await giris(client, "cok")

    r = await client.get("/api/oturum/sirketler")
    assert r.status_code == 200, r.text
    govde = r.json()
    assert set(govde) == {"aktif", "sirketler"}
    # Birimsiz çok şirketli kullanıcı: MOBİLİTE üyesi değil → seçici sırasında ilk.
    assert govde["aktif"] == "TELEKOM"
    assert govde["sirketler"] == [
        {"kod": "TELEKOM", "ad": "DENGE TELEKOM", "birimler": ["HABERLESME", "POC"]},
        {"kod": "ELEKTRONIK", "ad": "DENGE ELEKTRONİK", "birimler": ["BARIYER", "GUVENLIK"]},
    ]

    me = (await client.get("/api/auth/me")).json()
    assert me["aktif_sirket"] == "TELEKOM"
    assert me["sirketler"] == ["TELEKOM", "ELEKTRONIK"]

    r = await _sec(client, "ELEKTRONIK")
    assert r.status_code == 200, r.text
    assert r.json()["aktif"] == "ELEKTRONIK"
    assert (await client.get("/api/auth/me")).json()["aktif_sirket"] == "ELEKTRONIK"
    assert (await client.get("/api/oturum/sirketler")).json()["aktif"] == "ELEKTRONIK"
    # Denetim izi
    iz = await db.scalar(select(AuditLog).where(AuditLog.action == "oturum.sirket_degistir"))
    assert iz is not None
    assert (iz.old_value, iz.new_value) == ({"sirket": "TELEKOM"}, {"sirket": "ELEKTRONIK"})


async def test_uye_olmadigi_sirkete_gecis_403(client, db, kullanici_ac, uyelik_ver) -> None:
    kisi = await kullanici_ac("tek", "SERVIS_YONETICI")
    await uyelik_ver(kisi, "TELEKOM")
    await giris(client, "tek")

    r = await _sec(client, "ELEKTRONIK")
    assert r.status_code == 403
    assert r.json()["detail"]["kod"] == "SIRKET_DISI"
    # Hiçbir şey yazılmadı
    oturum = await db.scalar(select(Session).where(Session.user_id == kisi.id))
    await db.refresh(oturum)
    assert oturum.aktif_sirket == "TELEKOM"
    assert (await _sec(client, "YOKSUN")).status_code == 403


async def test_admin_butun_sirketleri_secer(client, kullanici_ac) -> None:
    # Üyelik satırı olmadan da (karar §1: ADMIN bütün şirketleri görür).
    await kullanici_ac("kok", "ADMIN")
    await giris(client, "kok")
    govde = (await client.get("/api/oturum/sirketler")).json()
    assert [s["kod"] for s in govde["sirketler"]] == ["TELEKOM", "ELEKTRONIK", "MOBILITE"]
    assert govde["aktif"] == "MOBILITE", "canlı sistem mobilite: birimsiz yönetici oraya düşer"


async def test_tumu_yonetici_sirket_degistirince_farkli_kayit_gorur(
    client, kullanici_ac, uyelik_ver, isler
) -> None:
    kisi = await kullanici_ac("mudur", "SERVIS_YONETICI")
    await uyelik_ver(kisi, "TELEKOM", "ELEKTRONIK", "MOBILITE")
    await giris(client, "mudur")

    so = {b: s.so_no for b, s in isler.items()}

    assert (await _sec(client, "TELEKOM")).status_code == 200
    gorunen, toplam = await _liste(client)
    assert gorunen == {so["HABERLESME"]}
    assert toplam == 1, "sayı = liste"
    assert (await client.get(f"/api/teknik-servis/isler/{isler['GUVENLIK'].id}")).status_code == 404
    r = await client.get(f"/api/teknik-servis/isler/{isler['HABERLESME'].id}")
    assert r.status_code == 200

    assert (await _sec(client, "ELEKTRONIK")).status_code == 200
    gorunen, toplam = await _liste(client)
    assert gorunen == {so["GUVENLIK"], so["BARIYER"]}
    assert toplam == 2
    r = await client.get(f"/api/teknik-servis/isler/{isler['HABERLESME'].id}")
    assert r.status_code == 404

    # Form verileri: TUMU da yalnız etkin şirketin birimlerini seçer.
    form = (await client.get("/api/teknik-servis/isler/form-verileri")).json()
    assert [b["kod"] for b in form["birimler"]] == ["GUVENLIK", "BARIYER"]
    # Başka şirketin birimiyle panel 403
    r = await client.get("/api/teknik-servis/panel", params={"birim": "HABERLESME"})
    assert r.status_code == 403


async def test_telekom_kullanicisi_elektronik_isini_goremez(
    client, birimli_kullanici_ac, uyelik_ver, isler
) -> None:
    """İki şirketin birimine üye şef, yalnız TELEKOM üyesiyse GUVENLIK işini
    listede, KPI'da ve tek kayıtta göremez."""
    sef = await birimli_kullanici_ac("sef_t", "SERVIS_SEF", ["HABERLESME", "GUVENLIK"])
    await uyelik_ver(sef, "TELEKOM")
    await giris(client, "sef_t")

    me = (await client.get("/api/auth/me")).json()
    assert me["aktif_sirket"] == "TELEKOM"

    gorunen, toplam = await _liste(client)
    assert gorunen == {isler["HABERLESME"].so_no}
    assert toplam == 1

    # KPI: panel kutusu = liste toplamı, GUVENLIK işi sayılmaz
    panel = (await client.get("/api/teknik-servis/panel")).json()
    kutular = {k["kod"]: k["deger"] for k in panel["kutular"]}
    for kod, deger in kutular.items():
        r = await client.get("/api/teknik-servis/isler", params={"kpi": kod, "limit": 1})
        assert deger == int(r.headers["X-Toplam-Kayit"]), kod
    assert kutular["plan_bekleyen"] == 1

    r = await client.get(f"/api/teknik-servis/isler/{isler['GUVENLIK'].id}")
    assert r.status_code == 404
    # Excel de aynı süzgeçten
    r = await client.get("/api/teknik-servis/isler.xlsx")
    assert r.status_code == 200


async def test_sirketsiz_kullanici_hicbir_sey_gormez(client, kullanici_ac, isler) -> None:
    """Fail-closed: üyeliği olmayan (ADMIN olmayan) TUMU kullanıcı boş liste."""
    await kullanici_ac("bos", "SERVIS_YONETICI")
    await giris(client, "bos")
    assert (await client.get("/api/oturum/sirketler")).json() == {"aktif": None, "sirketler": []}
    gorunen, toplam = await _liste(client)
    assert gorunen == set() and toplam == 0
    assert (await client.get("/api/cihazlar")).status_code == 403


async def test_mobilite_ucu_mobilite_disinda_403(client, kullanici_ac, uyelik_ver) -> None:
    kisi = await kullanici_ac("mob", "SERVIS_YONETICI")
    await uyelik_ver(kisi, "TELEKOM", "MOBILITE")
    await giris(client, "mob")
    # Birimsiz çok şirketli → varsayılan MOBİLİTE (canlı ekranlar açık kalır)
    assert (await client.get("/api/cihazlar")).status_code == 200

    assert (await _sec(client, "TELEKOM")).status_code == 200
    for yol in ("/api/cihazlar", "/api/hatlar", "/api/araclar", "/api/is-emirleri"):
        r = await client.get(yol)
        assert r.status_code == 403, yol
        assert r.json()["detail"]["kod"] == "SIRKET_DISI", yol
    r = await client.get("/api/raporlar/dashboard")
    assert r.status_code == 403 and r.json()["detail"]["kod"] == "SIRKET_DISI"
    # Uyarı zili bütün modüllerin ortak ucu: kapısız (mobilite satırları süzülür)
    assert (await client.get("/api/raporlar/uyarilar")).status_code == 200
    # Hesap/müşteri kartları grup ortaktır
    assert (await client.get("/api/hesaplar")).status_code == 200

    assert (await _sec(client, "MOBILITE")).status_code == 200
    assert (await client.get("/api/cihazlar")).status_code == 200


async def test_yeni_is_yanlis_sirket_birimiyle_reddedilir(
    client, db, kullanici_ac, uyelik_ver
) -> None:
    kisi = await kullanici_ac("acan", "SERVIS_YONETICI")
    await uyelik_ver(kisi, "TELEKOM", "ELEKTRONIK")
    hesap = await musteri(db)
    await giris(client, "acan")
    assert (await _sec(client, "TELEKOM")).status_code == 200

    r = await client.post("/api/teknik-servis/isler", json=acilis(hesap, birim="GUVENLIK"))
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["kod"] == "SIRKET_DISI_BIRIM"
    assert "DENGE TELEKOM" in r.json()["detail"]["mesaj"]

    assert (await _sec(client, "ELEKTRONIK")).status_code == 200
    r = await client.post(
        "/api/teknik-servis/isler", json=acilis(hesap, birim="BARIYER", tur="TASIMA")
    )
    assert r.status_code == 201, r.text


async def test_kullanici_yonetiminde_sirket_uyeligi(client, db, kullanici_ac) -> None:
    yonetici = await kullanici_ac("kok", "ADMIN")
    await giris(client, "kok")

    # Verilmezse birimden türetilir (GUVENLIK → ELEKTRONİK)
    r = await client.post(
        "/api/kullanicilar",
        json={
            "full_name": "Şef Güvenlik",
            "username": "sef_g",
            "password": "gecici12345",
            "role_code": "SERVIS_SEF",
            "birimler": ["GUVENLIK"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["sirketler"] == ["ELEKTRONIK"]
    yeni_id = r.json()["id"]

    # Açıkça verilen üyelik + bilinmeyen kod 400
    r = await client.post(
        "/api/kullanicilar",
        json={
            "full_name": "Finans",
            "username": "finans1",
            "password": "gecici12345",
            "role_code": "FINANS_YONETICI",
            "sirketler": ["TELEKOM", "YOK"],
        },
    )
    assert r.status_code == 400

    r = await client.patch(
        f"/api/kullanicilar/{yeni_id}", json={"sirketler": ["ELEKTRONIK", "TELEKOM"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["sirketler"] == ["ELEKTRONIK", "TELEKOM"]
    iz = await db.scalar(
        select(AuditLog).where(
            AuditLog.action == "sirket_uyeligi", AuditLog.entity_id == str(yeni_id)
        )
    )
    assert iz is not None
    assert iz.old_value == {"sirketler": ["ELEKTRONIK"]}
    assert iz.new_value == {"sirketler": ["ELEKTRONIK", "TELEKOM"]}
    assert iz.user_id == yonetici.id

    # Yalnız `sistem.kullanici`
    await kullanici_ac("mudur2", "SERVIS_YONETICI")
    await giris(client, "mudur2")
    r = await client.patch(f"/api/kullanicilar/{yeni_id}", json={"sirketler": ["MOBILITE"]})
    assert r.status_code == 403


async def test_teklif_sirket_suzgeci(client, db, kullanici_ac, uyelik_ver) -> None:
    """Teklif ortak uç: birimsiz (satış) teklif yalnız MOBİLİTE'de görünür."""
    from app.models import Quote

    hesap = await musteri(db)
    db.add_all(
        [
            Quote(quote_no="T-SATIS", customer_id=hesap.id, birim=None),
            Quote(quote_no="T-GUV", customer_id=hesap.id, birim="GUVENLIK"),
        ]
    )
    await db.commit()
    kisi = await kullanici_ac("tek_ad", "ADMIN")
    await uyelik_ver(kisi, "ELEKTRONIK", "MOBILITE")
    await giris(client, "tek_ad")

    async def nolar() -> set[str]:
        r = await client.get("/api/teklifler", params={"limit": 100})
        assert r.status_code == 200, r.text
        return {t["quote_no"] for t in r.json()}

    assert (await _sec(client, "ELEKTRONIK")).status_code == 200
    assert await nolar() == {"T-GUV"}
    assert (await _sec(client, "MOBILITE")).status_code == 200
    assert await nolar() == {"T-SATIS"}
    assert (await _sec(client, "TELEKOM")).status_code == 200
    assert await nolar() == set()


async def test_genel_aramada_mobilite_sonucu_yalniz_mobilitede(
    client, kullanici_ac, uyelik_ver, cihaz_ac
) -> None:
    """Ekranı 403 olan cihaz, genel aramada da çıkmaz (kapı yan yoldan açılmasın)."""
    await cihaz_ac(imei="356789012345678")
    kisi = await kullanici_ac("arayan", "ADMIN")
    await uyelik_ver(kisi, "TELEKOM", "MOBILITE")
    await giris(client, "arayan")

    async def turler() -> set[str]:
        r = await client.get("/api/arama", params={"q": "35678901"})
        assert r.status_code == 200, r.text
        return {s["tur"] for s in r.json()}

    assert (await _sec(client, "MOBILITE")).status_code == 200
    assert "CIHAZ" in await turler()
    assert (await _sec(client, "TELEKOM")).status_code == 200
    assert "CIHAZ" not in await turler()
