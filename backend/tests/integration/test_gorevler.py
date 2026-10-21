"""Görev panosu — pano, kolon, kart, taşıma, bağlantı, yorum.

Panonun ERP'nin parçası olmasını sağlayan şey, kartın bir kayda
bağlanabilmesi. Buradaki testlerin çoğu o bağlantının sınırlarını çiviliyor:
yarım bağlantı reddedilir, bilinmeyen tip reddedilir, kaynak kayıt silinirse
kart kaybolmaz ama durumu açıkça söyler.
"""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Card

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def _pano(client, baslik="Montaj Planı", kolonlar=None):
    govde = {"title": baslik}
    if kolonlar is not None:
        govde["kolonlar"] = kolonlar
    r = await client.post("/api/gorevler/panolar", json=govde)
    assert r.status_code == 201, r.text
    return r.json()


async def _kart(client, pano, kolon_id, **kw):
    govde = {"column_id": kolon_id, "title": "Bir iş", **kw}
    r = await client.post(f"/api/gorevler/panolar/{pano['id']}/kartlar", json=govde)
    assert r.status_code == 201, r.text
    return r.json()


# --- Pano --------------------------------------------------------------------


async def test_yeni_pano_varsayilan_kolonlarla_acilir(client, kullanici_ac):
    """Kolonsuz pano kullanılamaz halde doğardı: karta kolon gerekiyor."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")

    pano = await _pano(client)
    adlar = [k["title"] for k in pano["kolonlar"]]
    assert adlar == ["Yapılacak", "Devam ediyor", "Bitti"]
    # Son kolon bitiş sayılır; kullanıcı elle işaretlemek zorunda kalmasın.
    assert [k["bitis_mi"] for k in pano["kolonlar"]] == [False, False, True]


async def test_yeni_pano_hazir_etiketlerle_gelir(client, kullanici_ac):
    """Trello gibi: altı ADSIZ renk. Ad zorunlu olsaydı hızlı bir işaretleme
    için önce isim düşünmek gerekirdi."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    assert len(pano["etiketler"]) == 6
    assert all(e["ad"] is None for e in pano["etiketler"])
    assert [e["renk"] for e in pano["etiketler"]] == [
        "green",
        "gold",
        "orange",
        "red",
        "purple",
        "blue",
    ]


async def test_pano_listesi_kart_sayisini_verir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    await _kart(client, pano, pano["kolonlar"][0]["id"])

    liste = (await client.get("/api/gorevler/panolar")).json()
    assert len(liste) == 1
    assert liste[0]["kart_sayisi"] == 1


async def test_arsivlenen_pano_listede_gorunmez(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)

    r = await client.patch(f"/api/gorevler/panolar/{pano['id']}", json={"arsivlendi": True})
    assert r.status_code == 200
    assert (await client.get("/api/gorevler/panolar")).json() == []
    # Arşiv silme değil: istenince görünür.
    assert len((await client.get("/api/gorevler/panolar?arsiv=true")).json()) == 1


async def test_kartli_pano_silinemez(client, kullanici_ac):
    """Kartlı panoyu silmek o işlerin geçmişini de silerdi."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    await _kart(client, pano, pano["kolonlar"][0]["id"])

    r = await client.delete(f"/api/gorevler/panolar/{pano['id']}")
    assert r.status_code == 409
    assert "arşivleyin" in r.json()["detail"]


async def test_bos_pano_silinir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    assert (await client.delete(f"/api/gorevler/panolar/{pano['id']}")).status_code == 204


async def test_pano_iyimser_kilitleme(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    surum = pano["version"]

    assert (
        await client.patch(
            f"/api/gorevler/panolar/{pano['id']}", json={"title": "Birinci", "version": surum}
        )
    ).status_code == 200
    ikinci = await client.patch(
        f"/api/gorevler/panolar/{pano['id']}", json={"title": "İkinci", "version": surum}
    )
    assert ikinci.status_code == 409


# --- Kolon -------------------------------------------------------------------


async def test_kartli_kolon_silinemez(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kolon = pano["kolonlar"][0]
    await _kart(client, pano, kolon["id"])

    r = await client.delete(f"/api/gorevler/kolonlar/{kolon['id']}")
    assert r.status_code == 409


async def test_kolon_eklenir_ve_duzenlenir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)

    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/kolonlar",
        json={"title": "Beklemede", "wip_limit": 5},
    )
    assert r.status_code == 201
    kolon = r.json()
    assert kolon["sira"] == 3 and kolon["wip_limit"] == 5

    r2 = await client.patch(f"/api/gorevler/kolonlar/{kolon['id']}", json={"bitis_mi": True})
    assert r2.status_code == 200 and r2.json()["bitis_mi"] is True


# --- Kart ve bağlantı --------------------------------------------------------


async def test_kart_erp_kaydina_baglanir(client, kullanici_ac, db):
    """Bağlantı kartta ETİKETİYLE ve adresiyle döner; arayüz tıklanabilir yapar."""
    from app.models import Account

    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    hesap = Account(title="ZSR PATLAYICI SANAYİ A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)

    pano = await _pano(client)
    kart = await _kart(
        client,
        pano,
        pano["kolonlar"][0]["id"],
        title="Vergi levhasını iste",
        entity="hesap",
        entity_id=hesap.id,
    )
    assert kart["baglanti"]["ad"] == "Hesap"
    assert kart["baglanti"]["etiket"] == "ZSR PATLAYICI SANAYİ A.Ş."
    assert kart["baglanti"]["var"] is True
    assert str(hesap.id) in kart["baglanti"]["yol"]


async def test_baglantisiz_kart_acilabilir(client, kullanici_ac):
    """ "Vergi levhalarını topla" gibi kayda karşılık gelmeyen iş de panoda durmalı."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kart = await _kart(client, pano, pano["kolonlar"][0]["id"], title="Ofis kirası")
    assert kart["baglanti"] is None


async def test_yarim_baglanti_reddedilir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/kartlar",
        json={"column_id": pano["kolonlar"][0]["id"], "title": "X", "entity": "hesap"},
    )
    assert r.status_code == 400
    assert "hem kayıt tipi hem kimlik" in r.json()["detail"]


async def test_bilinmeyen_kayit_tipi_reddedilir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/kartlar",
        json={
            "column_id": pano["kolonlar"][0]["id"],
            "title": "X",
            "entity": "uzaygemisi",
            "entity_id": 1,
        },
    )
    assert r.status_code == 400
    assert "uzaygemisi" in r.json()["detail"]


async def test_kaynak_kayit_silinirse_kart_durumu_soyler(client, kullanici_ac, db):
    """Polimorfik bağlantıda FK yok; kart öksüz kalabilir.

    Sessizce boş etiket göstermek "bağlantı yok" ile "bağlantı kırık"ı aynı
    şeye çevirirdi.
    """
    from app.models import Account

    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    hesap = Account(title="Silinecek A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)
    hesap_id = hesap.id

    pano = await _pano(client)
    await _kart(client, pano, pano["kolonlar"][0]["id"], entity="hesap", entity_id=hesap_id)

    await db.delete(hesap)
    await db.commit()

    kartlar = (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json()
    assert len(kartlar) == 1, "kart kaybolmamalı"
    assert kartlar[0]["baglanti"]["var"] is False
    assert kartlar[0]["baglanti"]["etiket"] == "kaynak kayıt silinmiş"


async def test_kaydin_kartlari_listelenir(client, kullanici_ac, db):
    """Kayıt ekranındaki "Görevler" paneli bu uca bakar."""
    from app.models import Account

    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    hesap = Account(title="Bir Müşteri", is_musteri=True)
    db.add(hesap)
    await db.commit()
    await db.refresh(hesap)

    pano = await _pano(client)
    await _kart(client, pano, pano["kolonlar"][0]["id"], entity="hesap", entity_id=hesap.id)
    await _kart(client, pano, pano["kolonlar"][0]["id"], title="İlgisiz")

    r = await client.get(f"/api/gorevler/kayit/hesap/{hesap.id}")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_gecersiz_oncelik_reddedilir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/kartlar",
        json={"column_id": pano["kolonlar"][0]["id"], "title": "X", "oncelik": "COK_ACIL"},
    )
    assert r.status_code == 400


async def test_baska_panonun_kolonuna_kart_acilamaz(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    a = await _pano(client, "Pano A")
    b = await _pano(client, "Pano B")
    r = await client.post(
        f"/api/gorevler/panolar/{a['id']}/kartlar",
        json={"column_id": b["kolonlar"][0]["id"], "title": "X"},
    )
    assert r.status_code == 400


# --- Taşıma ------------------------------------------------------------------


async def test_kart_kolonlar_arasi_tasinir_ve_siralar_bozulmaz(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    yapilacak, devam = pano["kolonlar"][0]["id"], pano["kolonlar"][1]["id"]
    k1 = await _kart(client, pano, yapilacak, title="Bir")
    k2 = await _kart(client, pano, yapilacak, title="İki")
    k3 = await _kart(client, pano, yapilacak, title="Üç")
    assert [k1["sira"], k2["sira"], k3["sira"]] == [0, 1, 2]

    r = await client.post(
        f"/api/gorevler/kartlar/{k2['id']}/tasi", json={"column_id": devam, "sira": 0}
    )
    assert r.status_code == 200 and r.json()["column_id"] == devam

    kartlar = {
        k["title"]: k
        for k in (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json()
    }
    # Kaynak kolonda boşluk kalmamalı.
    assert kartlar["Bir"]["sira"] == 0 and kartlar["Üç"]["sira"] == 1
    assert kartlar["İki"]["sira"] == 0


async def test_kolon_ici_siralama(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kolon = pano["kolonlar"][0]["id"]
    k1 = await _kart(client, pano, kolon, title="Bir")
    await _kart(client, pano, kolon, title="İki")
    k3 = await _kart(client, pano, kolon, title="Üç")

    # Üç'ü en başa al.
    await client.post(
        f"/api/gorevler/kartlar/{k3['id']}/tasi", json={"column_id": kolon, "sira": 0}
    )
    kartlar = sorted(
        (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json(),
        key=lambda k: k["sira"],
    )
    assert [k["title"] for k in kartlar] == ["Üç", "Bir", "İki"]
    assert [k["sira"] for k in kartlar] == [0, 1, 2]
    assert k1["id"] != k3["id"]


async def test_bitis_kolonuna_tasinan_kart_damgalanir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kolon, bitti = pano["kolonlar"][0]["id"], pano["kolonlar"][2]["id"]
    kart = await _kart(client, pano, kolon)
    assert kart["tamamlandi_at"] is None

    r = await client.post(
        f"/api/gorevler/kartlar/{kart['id']}/tasi", json={"column_id": bitti, "sira": 0}
    )
    damga = r.json()["tamamlandi_at"]
    assert damga is not None

    # Geri çekilse de "ne zaman bitmişti" cevabı kalmalı.
    r2 = await client.post(
        f"/api/gorevler/kartlar/{kart['id']}/tasi", json={"column_id": kolon, "sira": 0}
    )
    assert r2.json()["tamamlandi_at"] == damga


async def test_baska_panonun_kolonuna_tasinamaz(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    a = await _pano(client, "Pano A")
    b = await _pano(client, "Pano B")
    kart = await _kart(client, a, a["kolonlar"][0]["id"])
    r = await client.post(
        f"/api/gorevler/kartlar/{kart['id']}/tasi",
        json={"column_id": b["kolonlar"][0]["id"], "sira": 0},
    )
    assert r.status_code == 400


async def test_kart_silinince_sira_bosluk_birakmaz(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kolon = pano["kolonlar"][0]["id"]
    await _kart(client, pano, kolon, title="Bir")
    k2 = await _kart(client, pano, kolon, title="İki")
    await _kart(client, pano, kolon, title="Üç")

    assert (await client.delete(f"/api/gorevler/kartlar/{k2['id']}")).status_code == 204
    kartlar = sorted(
        (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json(),
        key=lambda k: k["sira"],
    )
    assert [k["sira"] for k in kartlar] == [0, 1]


# --- Yorum -------------------------------------------------------------------


async def test_yorum_eklenir_ve_sayilir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kart = await _kart(client, pano, pano["kolonlar"][0]["id"])

    r = await client.post(
        f"/api/gorevler/kartlar/{kart['id']}/yorumlar", json={"metin": "Müşteriyle görüşüldü"}
    )
    assert r.status_code == 201
    assert r.json()["yazan"] == "Koord"

    kartlar = (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json()
    assert kartlar[0]["yorum_sayisi"] == 1


# --- Yetki -------------------------------------------------------------------


async def test_gorev_izni_olmayan_goremez(client, kullanici_ac, db):
    """`gorev.gor` rolden kaldırılınca pano kapanmalı."""
    from sqlalchemy import delete

    from app.models import Role, RolePermission

    rol = await db.scalar(select(Role).where(Role.code == "MONTAJ_KOORD"))
    await db.execute(
        delete(RolePermission).where(
            RolePermission.role_id == rol.id,
            RolePermission.permission_code.in_(["gorev.gor", "gorev.yaz"]),
        )
    )
    await db.commit()

    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    assert (await client.get("/api/gorevler/panolar")).status_code == 403


async def test_salt_okunur_rol_kart_acamaz(client, kullanici_ac):
    """YONETIM `gorev.gor` alır, `gorev.yaz` almaz."""
    await kullanici_ac("izleyici", "YONETIM")
    await _giris(client, "izleyici")
    assert (await client.get("/api/gorevler/panolar")).status_code == 200
    r = await client.post("/api/gorevler/panolar", json={"title": "Olmaz"})
    assert r.status_code == 403


async def test_kart_acmak_denetime_yazilir(client, kullanici_ac, db):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    await _kart(client, pano, pano["kolonlar"][0]["id"], title="İzlenecek iş")

    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "cards", AuditLog.action == "olustur")
    )
    assert kayit is not None and kayit.new_value["baslik"] == "İzlenecek iş"


async def test_kart_guncellenince_surum_artar(client, kullanici_ac, db):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    kart = await _kart(client, pano, pano["kolonlar"][0]["id"])

    r = await client.patch(
        f"/api/gorevler/kartlar/{kart['id']}",
        json={"title": "Yeni başlık", "version": kart["version"]},
    )
    assert r.status_code == 200
    assert r.json()["version"] > kart["version"]

    eski = await client.patch(
        f"/api/gorevler/kartlar/{kart['id']}", json={"title": "X", "version": kart["version"]}
    )
    assert eski.status_code == 409

    guncel = await db.get(Card, kart["id"])
    await db.refresh(guncel)
    assert guncel.title == "Yeni başlık"


# --- İlgili kişiler (çoklu) --------------------------------------------------


async def test_karta_birden_cok_kisi_atanir(client, kullanici_ac):
    """Bir montajda koordinatör, tekniker ve satış aynı anda ilgili olabilir."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    a = await kullanici_ac("tekniker", "TEKNIK_SERVIS")
    b = await kullanici_ac("satisci", "SATIS")
    await _giris(client, "koord")
    pano = await _pano(client)

    kart = await _kart(client, pano, pano["kolonlar"][0]["id"], title="Montaj", uyeler=[a.id, b.id])
    assert sorted(u["id"] for u in kart["uyeler"]) == sorted([a.id, b.id])
    assert {u["ad"] for u in kart["uyeler"]} == {"Tekniker", "Satisci"}


async def test_kisi_listesi_esitlenir(client, kullanici_ac):
    """PATCH listeyi EŞİTLER: gönderilmeyen kişi karttan düşer."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    a = await kullanici_ac("tekniker", "TEKNIK_SERVIS")
    b = await kullanici_ac("satisci", "SATIS")
    await _giris(client, "koord")
    pano = await _pano(client)
    kart = await _kart(client, pano, pano["kolonlar"][0]["id"], uyeler=[a.id, b.id])

    r = await client.patch(
        f"/api/gorevler/kartlar/{kart['id']}", json={"uyeler": [b.id], "version": kart["version"]}
    )
    assert r.status_code == 200
    assert [u["id"] for u in r.json()["uyeler"]] == [b.id]


async def test_olmayan_kisi_reddedilir(client, kullanici_ac):
    """Silinmiş bir kullanıcıyı karta yazmak adsız bir rozet üretirdi."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/kartlar",
        json={"column_id": pano["kolonlar"][0]["id"], "title": "X", "uyeler": [999999]},
    )
    assert r.status_code == 400
    assert "Bulunamayan kullanıcı" in r.json()["detail"]


async def test_kisi_silinince_karttan_duser(client, kullanici_ac, db):
    from app.models import User

    await kullanici_ac("koord", "MONTAJ_KOORD")
    a = await kullanici_ac("gidecek", "TEKNIK_SERVIS")
    await _giris(client, "koord")
    pano = await _pano(client)
    kart = await _kart(client, pano, pano["kolonlar"][0]["id"], uyeler=[a.id])
    assert len(kart["uyeler"]) == 1

    await db.delete(await db.get(User, a.id))
    await db.commit()

    kartlar = (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json()
    assert kartlar[0]["uyeler"] == [], "kart kalır, kişi düşer"


# --- Etiketler ---------------------------------------------------------------


async def test_etiket_karta_yapistirilir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    etiket = pano["etiketler"][3]

    kart = await _kart(client, pano, pano["kolonlar"][0]["id"], etiketler=[etiket["id"]])
    assert [e["id"] for e in kart["etiketler"]] == [etiket["id"]]
    assert kart["etiketler"][0]["renk"] == "red"


async def test_baska_panonun_etiketi_yapistirilamaz(client, kullanici_ac):
    """O pano silinseydi buradaki kart sebebi görünmeden etiketsiz kalırdı."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    a = await _pano(client, "Pano A")
    b = await _pano(client, "Pano B")
    r = await client.post(
        f"/api/gorevler/panolar/{a['id']}/kartlar",
        json={
            "column_id": a["kolonlar"][0]["id"],
            "title": "X",
            "etiketler": [b["etiketler"][0]["id"]],
        },
    )
    assert r.status_code == 400
    assert "Bu panoya ait olmayan etiket" in r.json()["detail"]


async def test_etiket_adlandirilir_ve_silinir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    etiket = pano["etiketler"][0]

    r = await client.patch(
        f"/api/gorevler/etiketler/{etiket['id']}", json={"ad": "Saha", "renk": "cyan"}
    )
    assert r.status_code == 200
    assert r.json()["ad"] == "Saha" and r.json()["renk"] == "cyan"

    assert (await client.delete(f"/api/gorevler/etiketler/{etiket['id']}")).status_code == 204
    guncel = (await client.get("/api/gorevler/panolar")).json()[0]
    assert len(guncel["etiketler"]) == 5


async def test_etiket_silinince_kart_silinmez(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    etiket = pano["etiketler"][0]
    kart = await _kart(client, pano, pano["kolonlar"][0]["id"], etiketler=[etiket["id"]])

    await client.delete(f"/api/gorevler/etiketler/{etiket['id']}")
    kartlar = (await client.get(f"/api/gorevler/panolar/{pano['id']}/kartlar")).json()
    assert len(kartlar) == 1 and kartlar[0]["id"] == kart["id"]
    assert kartlar[0]["etiketler"] == []


async def test_yeni_etiket_eklenir(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/etiketler", json={"ad": "Acil", "renk": "magenta"}
    )
    assert r.status_code == 201
    assert r.json()["sira"] == 6


async def test_etiket_yazmak_yetki_ister(client, kullanici_ac):
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)
    await client.post("/api/auth/logout")

    await kullanici_ac("izleyici", "YONETIM")
    await _giris(client, "izleyici")
    r = await client.post(
        f"/api/gorevler/panolar/{pano['id']}/etiketler", json={"ad": "X", "renk": "blue"}
    )
    assert r.status_code == 403


async def test_kolonsuz_pano_acilamaz(client, kullanici_ac):
    """Kolonsuz pano kullanılamaz: karta kolon gerekiyor.

    Varsayılan üçlü var ama istemci boş liste gönderebiliyordu; canlıda bir
    pano bu şekilde kolonsuz doğdu ve ekran sebepsiz boş göründü.
    """
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    r = await client.post("/api/gorevler/panolar", json={"title": "Boş pano", "kolonlar": []})
    assert r.status_code == 400
    assert "en az bir kolon" in r.json()["detail"]


async def test_bos_pano_arsivden_cikarilabilir(client, kullanici_ac):
    """Arşiv tek yönlü bir kapı olmamalı."""
    await kullanici_ac("koord", "MONTAJ_KOORD")
    await _giris(client, "koord")
    pano = await _pano(client)

    await client.patch(f"/api/gorevler/panolar/{pano['id']}", json={"arsivlendi": True})
    assert (await client.get("/api/gorevler/panolar")).json() == []

    r = await client.patch(f"/api/gorevler/panolar/{pano['id']}", json={"arsivlendi": False})
    assert r.status_code == 200 and r.json()["arsivlendi"] is False
    assert len((await client.get("/api/gorevler/panolar")).json()) == 1
