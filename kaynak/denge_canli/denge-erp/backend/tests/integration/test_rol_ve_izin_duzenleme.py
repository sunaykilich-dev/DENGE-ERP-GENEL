"""Düzenlenebilir roller ve kullanıcıya özel izin istisnaları.

İki ayrı mekanizma var ve karışmamaları gerekiyor:

* **Rol** omurgadır — değişiklik o roldeki HERKESİ etkiler.
* **İstisna** tek kişiliktir ve rolün üstüne biner; gerekçe ister.

Buradaki testler ikisinin sınırlarını çiviliyor: istisna rolü yener, yetki
değişikliği açık oturumları düşürür, yönetici kendi yetkisine dokunamaz ve
elle düzenlenmiş bir rol açılıştaki katalog senkronunda geri alınmaz.
"""

import pytest
from sqlalchemy import delete, select

from app.models import AuditLog, Role, RolePermission, UserPermission

pytestmark = pytest.mark.integration


async def _giris(client, username: str, password: str = "parola1234"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


# --------------------------------------------------------------------------
# Rolün açtığı ekranlar
# --------------------------------------------------------------------------


async def test_rol_yetkileri_sayfa_ve_izin_listesi_verir(client, kullanici_ac):
    """Yönetici rol seçerken ne verdiğini kod okumadan görebilmeli."""
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")

    r = await client.get("/api/roller/DEPO/yetkiler")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["code"] == "DEPO"
    assert "Cihazlar" in d["sayfalar"]
    assert "Hak Ediş" not in d["sayfalar"]
    assert any(i["kod"] == "cihaz.transfer" for i in d["izinler"])
    # Her izin satırı modül ve açıklama taşır; arayüz kod listesi göstermiyor.
    assert all(i["modul"] and i["aciklama"] for i in d["izinler"])


async def test_kapsamli_rolde_kayit_kisiti_aciklamasi_gelir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    d = (await client.get("/api/roller/SATIS/yetkiler")).json()
    assert d["scope"] == "KENDI_MUSTERILERI"
    assert "kendi müşteri" in d["scope_aciklama"]


async def test_kullanici_yetkileri_istisnalari_de_gosterir(client, kullanici_ac):
    """Panel "bu kişi neyi açabilir" sorusuna cevap vermeli, rolün hamına değil."""
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")

    once = (await client.get(f"/api/kullanicilar/{hedef.id}/yetkiler")).json()
    assert "Hak Ediş" not in once["sayfalar"]
    assert once["istisna_kodlari"] == []

    await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[
            {"permission_code": "hakedis.gor", "allow": True, "gerekce": "Ay sonu kontrolü"},
            {"permission_code": "cihaz.transfer", "allow": False, "gerekce": "Transfer kapalı"},
        ],
    )

    sonra = (await client.get(f"/api/kullanicilar/{hedef.id}/yetkiler")).json()
    kodlar = {i["kod"] for i in sonra["izinler"]}
    assert "Hak Ediş" in sonra["sayfalar"], "istisnayla verilen yetki panelde görünmeli"
    assert "hakedis.gor" in kodlar
    assert "cihaz.transfer" not in kodlar, "geri alınan yetki panelde kalmamalı"
    assert sonra["istisna_kodlari"] == ["hakedis.gor"], "yalnız EKLENEN izin işaretlenir"
    assert sonra["code"] == "DEPO"


async def test_kullanici_yetkileri_olmayan_kullanici_404(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    assert (await client.get("/api/kullanicilar/99999/yetkiler")).status_code == 404


async def test_rol_yetkileri_yetki_ister(client, kullanici_ac):
    await kullanici_ac("depocu", "DEPO")
    await _giris(client, "depocu")
    assert (await client.get("/api/roller/DEPO/yetkiler")).status_code == 403
    assert (await client.get("/api/izinler")).status_code == 403
    assert (await client.get("/api/kullanicilar/1/yetkiler")).status_code == 403


# --------------------------------------------------------------------------
# Rol oluşturma / düzenleme / silme
# --------------------------------------------------------------------------


async def test_ozel_rol_acilir_ve_izinleri_isler(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")

    r = await client.post(
        "/api/roller",
        json={
            "code": "BOLGE_MUDURU",
            "name": "Bölge Müdürü",
            "scope": "TUMU",
            "izinler": ["cihaz.gor", "isemri.gor", "hakedis.gor"],
        },
    )
    assert r.status_code == 201, r.text

    d = (await client.get("/api/roller/BOLGE_MUDURU/yetkiler")).json()
    assert {i["kod"] for i in d["izinler"]} == {"cihaz.gor", "isemri.gor", "hakedis.gor"}
    assert "Hak Ediş" in d["sayfalar"]

    # Yeni rolde çalışan biri gerçekten girebilmeli.
    await kullanici_ac("bolge", "BOLGE_MUDURU")
    await client.post("/api/auth/logout")
    assert (await _giris(client, "bolge")).status_code == 200
    assert (await client.get("/api/hakedis")).status_code == 200
    assert (await client.get("/api/kullanicilar")).status_code == 403

    kayit = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "roles", AuditLog.action == "olustur")
    )
    assert kayit is not None and kayit.new_value["kod"] == "BOLGE_MUDURU"


async def test_ayni_rol_kodu_ikinci_kez_acilamaz(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    govde = {"code": "BOLGE_MUDURU", "name": "Bölge Müdürü", "izinler": []}
    assert (await client.post("/api/roller", json=govde)).status_code == 201
    assert (await client.post("/api/roller", json=govde)).status_code == 409


async def test_bilinmeyen_izin_reddedilir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.post(
        "/api/roller",
        json={"code": "SAHTE", "name": "Sahte", "izinler": ["her.sey"]},
    )
    assert r.status_code == 400
    assert "her.sey" in r.json()["detail"]


async def test_rol_kodu_bicimi_zorlanir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.post("/api/roller", json={"code": "kucuk harf", "name": "Kötü", "izinler": []})
    assert r.status_code == 422


async def test_rol_duzenlenince_o_roldeki_herkesin_oturumu_duser(client, kullanici_ac, db):
    """Eski yetkiyle açılmış oturum yeni kısıtı görmezdi."""
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")

    # İki oturum aynı anda açık; çerez kavanozu tek olduğu için el ile
    # değiştiriyoruz. `logout` çağırmıyoruz: oturumu düşüren şeyin rol
    # değişikliği olduğunu kanıtlamak istiyoruz.
    await _giris(client, "depocu")
    depocu_cerezi = dict(client.cookies)
    await _giris(client, "yonetici")
    yonetici_cerezi = dict(client.cookies)

    client.cookies.update(depocu_cerezi)
    assert (await client.get("/api/auth/me")).status_code == 200, "oturum değişiklikten önce açık"

    client.cookies.update(yonetici_cerezi)
    r = await client.patch("/api/roller/DEPO", json={"izinler": ["cihaz.gor"]})
    assert r.status_code == 200, r.text

    from app.models import Session as OturumModel

    kalan = (await db.scalars(select(OturumModel).where(OturumModel.user_id == hedef.id))).all()
    assert kalan == [], "rol değişti, eski oturum ayakta kalmamalı"

    client.cookies.update(depocu_cerezi)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_rol_duzenlenince_kaldirilan_izin_gercekten_gider(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    # DEPO'dan transfer yetkisini al.
    kalan = [
        i["kod"]
        for i in (await client.get("/api/roller/DEPO/yetkiler")).json()["izinler"]
        if i["kod"] != "cihaz.transfer"
    ]
    assert (await client.patch("/api/roller/DEPO", json={"izinler": kalan})).status_code == 200

    await client.post("/api/auth/logout")
    await _giris(client, "depocu")
    me = (await client.get("/api/auth/me")).json()
    assert "cihaz.transfer" not in me["permissions"]
    assert "cihaz.gor" in me["permissions"]


async def test_sistem_rolu_silinemez(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.delete("/api/roller/DEPO")
    assert r.status_code == 409
    assert "Sistem rolü" in r.json()["detail"]


async def test_kullanicisi_olan_ozel_rol_silinemez(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    await client.post("/api/roller", json={"code": "GECICI", "name": "Geçici", "izinler": []})
    await kullanici_ac("gecici_kisi", "GECICI")

    r = await client.delete("/api/roller/GECICI")
    assert r.status_code == 409
    assert "1 kullanıcı" in r.json()["detail"]


async def test_bos_ozel_rol_silinir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    await client.post("/api/roller", json={"code": "GECICI", "name": "Geçici", "izinler": []})
    assert (await client.delete("/api/roller/GECICI")).status_code == 204
    assert (await client.get("/api/roller/GECICI/yetkiler")).status_code == 404


async def test_duzenlenen_rol_acilis_senkronunda_geri_alinmaz(client, kullanici_ac, db):
    """Katalog senkronu her açılışta koşuyor; elle verilen izni silmemeli."""
    from app.seeds.dev import sync_roles

    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")

    mevcut = [i["kod"] for i in (await client.get("/api/roller/DEPO/yetkiler")).json()["izinler"]]
    assert "hakedis.gor" not in mevcut
    r = await client.patch("/api/roller/DEPO", json={"izinler": [*mevcut, "hakedis.gor"]})
    assert r.status_code == 200

    rol = await db.scalar(select(Role).where(Role.code == "DEPO"))
    assert rol.ozellestirildi is True

    await sync_roles(db)
    await db.commit()

    sonra = [i["kod"] for i in (await client.get("/api/roller/DEPO/yetkiler")).json()["izinler"]]
    assert "hakedis.gor" in sonra, "senkron elle verilen izni geri almamalı"


async def test_dokunulmamis_rol_senkronla_hizada_kalir(client, kullanici_ac, db):
    """Özelleştirilmemiş rolden elle silinen izin senkronda geri gelmeli."""
    from app.seeds.dev import sync_roles

    rol = await db.scalar(select(Role).where(Role.code == "DEPO"))
    assert rol.ozellestirildi is False
    await db.execute(
        delete(RolePermission).where(
            RolePermission.role_id == rol.id,
            RolePermission.permission_code == "cihaz.transfer",
        )
    )
    await db.commit()

    await sync_roles(db)
    await db.commit()

    await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    kodlar = [i["kod"] for i in (await client.get("/api/roller/DEPO/yetkiler")).json()["izinler"]]
    assert "cihaz.transfer" in kodlar


# --------------------------------------------------------------------------
# Kullanıcıya özel istisnalar
# --------------------------------------------------------------------------


async def test_istisna_rolun_vermedigi_izni_verir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")

    await _giris(client, "depocu")
    assert (await client.get("/api/hakedis")).status_code == 403
    await client.post("/api/auth/logout")

    await _giris(client, "yonetici")
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[
            {
                "permission_code": "hakedis.gor",
                "allow": True,
                "gerekce": "Ay sonu dökümünü depo kontrol edecek",
            }
        ],
    )
    assert r.status_code == 200, r.text

    await client.post("/api/auth/logout")
    await _giris(client, "depocu")
    assert (await client.get("/api/hakedis")).status_code == 200

    # Arayüz menüyü /me'deki listeye göre çiziyor: istisnayla verilen yetki
    # orada görünmezse sayfa erişilebilir ama menüde YOK olurdu.
    me = (await client.get("/api/auth/me")).json()
    assert "hakedis.gor" in me["permissions"]


async def test_istisna_rolun_verdigi_izni_geri_alir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[
            {
                "permission_code": "cihaz.transfer",
                "allow": False,
                "gerekce": "Transfer yetkisi geçici olarak kaldırıldı",
            }
        ],
    )
    await client.post("/api/auth/logout")
    await _giris(client, "depocu")
    me = (await client.get("/api/auth/me")).json()
    assert "cihaz.transfer" not in me["permissions"]
    assert "cihaz.gor" in me["permissions"], "diğer izinler duruyor"


async def test_istisna_yazinca_hedefin_oturumu_duser(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")

    await _giris(client, "depocu")
    depocu_cerezi = dict(client.cookies)
    await _giris(client, "yonetici")
    yonetici_cerezi = dict(client.cookies)

    client.cookies.update(depocu_cerezi)
    assert (await client.get("/api/auth/me")).status_code == 200

    client.cookies.update(yonetici_cerezi)
    await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "geçici görev"}],
    )

    client.cookies.update(depocu_cerezi)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_istisna_gerekce_ister(client, kullanici_ac):
    """Gerekçesiz istisna altı ay sonra kimsenin açıklayamadığı bir sapma olur."""
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "yok"}],
    )
    assert r.status_code == 422


async def test_yonetici_kendi_izinlerini_degistiremez(client, kullanici_ac):
    """Kendini kilitleyebilir ya da sessizce yükseltebilirdi."""
    admin = await kullanici_ac("yonetici", "ADMIN")
    await _giris(client, "yonetici")
    r = await client.put(
        f"/api/kullanicilar/{admin.id}/izinler",
        json=[{"permission_code": "kvkk.yonet", "allow": True, "gerekce": "kendime yetki"}],
    )
    assert r.status_code == 400
    assert "Kendi izinlerinizi" in r.json()["detail"]


async def test_bilinmeyen_izin_istisnasi_reddedilir(client, kullanici_ac):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "her.sey", "allow": True, "gerekce": "denemedir"}],
    )
    assert r.status_code == 400


async def test_istisna_listesi_bosaltilabilir(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "geçici görev"}],
    )
    assert len((await client.get(f"/api/kullanicilar/{hedef.id}/izinler")).json()) == 1

    assert (await client.put(f"/api/kullanicilar/{hedef.id}/izinler", json=[])).status_code == 200
    assert (await client.get(f"/api/kullanicilar/{hedef.id}/izinler")).json() == []
    kalan = (
        await db.scalars(select(UserPermission).where(UserPermission.user_id == hedef.id))
    ).all()
    assert kalan == []

    await client.post("/api/auth/logout")
    await _giris(client, "depocu")
    assert (await client.get("/api/hakedis")).status_code == 403


async def test_istisna_denetime_gerekcesiyle_yazilir(client, kullanici_ac, db):
    await kullanici_ac("yonetici", "ADMIN")
    hedef = await kullanici_ac("depocu", "DEPO")
    await _giris(client, "yonetici")
    await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "Ay sonu kontrolü"}],
    )
    kayit = await db.scalar(select(AuditLog).where(AuditLog.action == "izin.istisna"))
    assert kayit is not None
    assert kayit.new_value["istisnalar"] == [{"kod": "hakedis.gor", "allow": True}]


async def test_istisna_yazmak_yetki_ister(client, kullanici_ac):
    hedef = await kullanici_ac("depocu", "DEPO")
    await kullanici_ac("depocu2", "DEPO")
    await _giris(client, "depocu2")
    r = await client.put(
        f"/api/kullanicilar/{hedef.id}/izinler",
        json=[{"permission_code": "hakedis.gor", "allow": True, "gerekce": "kendime yetki"}],
    )
    assert r.status_code == 403
