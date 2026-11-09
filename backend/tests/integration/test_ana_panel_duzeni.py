"""Ana Panel kişisel ve rol varsayılanı düzeni (KARARLAR 2026-11-09 S8).

- S8.1 kişisel düzen sunucuda: oluştur / güncelle / varsayılana dön; iyimser
  kilit (`version`) — eski sürümle kayıt 409.
- S8.2 bileşen yetkisi: katalog izinle süzülür; izinsiz bileşen kaydı 403;
  kayıtta kalmış izinsiz/bilinmeyen bileşen okumada düşer.
- S8.3 rol varsayılanı (`panel.yonet`): kullanıcı düzeni rolün üstüne yazar;
  kişisel düzen silinince rol varsayılanı, o da yoksa bugünkü panel geçer.
"""

from __future__ import annotations

import pytest
from servis_yardimci import giris
from sqlalchemy import select

from app.models import AnaPanelDuzeni, AuditLog, Role
from app.services import ana_panel_duzeni as svc

pytestmark = pytest.mark.integration

YOL = "/api/ana-panel/duzen"
ROL = "/api/ana-panel/rol-duzenleri"


def _kodlar(govde: dict) -> list[str]:
    return [o["kod"] for o in govde["bilesenler"]]


def _katalog(govde: dict) -> set[str]:
    return {k["kod"] for k in govde["katalog"]}


def _sistem(*eksik: str) -> list[str]:
    return [k for k, _ in svc.SISTEM_VARSAYILANI if k not in eksik]


@pytest.fixture
async def kisiler(kullanici_ac, birimli_kullanici_ac) -> dict:
    return {
        "admin": await kullanici_ac("admin_p", "ADMIN"),
        "mudur": await birimli_kullanici_ac("mudur_p", "SERVIS_YONETICI", ["GUVENLIK"]),
        "sef": await birimli_kullanici_ac("sef_p", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF"),
        "tek": await birimli_kullanici_ac(
            "tek_p", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "tek2": await birimli_kullanici_ac(
            "tek_p2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "satis_muduru": await kullanici_ac("satismd_p", "SATIS_MUDURU"),
        "depo": await kullanici_ac("depo_p", "DEPO"),
    }


# --- Varsayılan ve izinle süzme (S8.2) ---------------------------------------------------------


async def test_duzen_yoksa_bugunku_panel_izinle_suzulur(client, kisiler) -> None:
    await giris(client, "sef_p")
    r = await client.get(YOL)
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["kaynak"] == "SISTEM" and g["version"] is None
    assert _kodlar(g) == _sistem()  # şefte operasyon.gor var → ekip kartı dahil
    assert g["varsayilan"] == {"kaynak": "SISTEM", "bilesenler": g["bilesenler"]}
    assert "tekliflerim" in _katalog(g)  # teklif.gor var; varsayılanda değil, katalogda
    assert g["rol_duzenleyebilir"] is False

    # Teknisyende operasyon.gor ve teklif.gor yok: ekip kartı ve teklif bileşeni yok.
    await giris(client, "tek_p")
    g = (await client.get(YOL)).json()
    assert _kodlar(g) == _sistem("ekip_durumu")
    assert {"ekip_durumu", "tekliflerim"} & _katalog(g) == set()


async def test_servis_izni_olmayan_yalniz_izinli_bilesenleri_gorur(client, kisiler) -> None:
    """servis.gor'u olmayan satış müdürü panelde yalnız teklif bileşenini görür;
    servis verisi ucu ona yine kapalıdır, teklif özeti açıktır."""
    await giris(client, "satismd_p")
    g = (await client.get(YOL)).json()
    assert _kodlar(g) == ["tekliflerim"]
    assert _katalog(g) == {"tekliflerim"}
    assert g["rol_duzenleyebilir"] is True
    assert (await client.get("/api/teknik-servis/ana-panel")).status_code == 403
    r = await client.get(f"/api/teklifler/ozet?hazirlayan_id={kisiler['satis_muduru'].id}")
    assert r.status_code == 200, r.text

    # Hiçbir bileşeni göremeyen (mobilite depo): boş katalog, boş panel.
    await giris(client, "depo_p")
    g = (await client.get(YOL)).json()
    assert g["bilesenler"] == [] and g["katalog"] == []


async def test_izinsiz_bilesen_kaydedilemez(client, kisiler) -> None:
    await giris(client, "tek_p")
    for kod in ("ekip_durumu", "tekliflerim"):
        r = await client.put(YOL, json={"bilesenler": [{"kod": kod, "boyut": "DAR"}]})
        assert r.status_code == 403, (kod, r.text)
    r = await client.put(YOL, json={"bilesenler": [{"kod": "olmayan", "boyut": "DAR"}]})
    assert r.status_code == 400
    iki = [{"kod": "aktif_isler", "boyut": "DAR"}, {"kod": "aktif_isler", "boyut": "GENIS"}]
    assert (await client.put(YOL, json={"bilesenler": iki})).status_code == 400
    r = await client.put(YOL, json={"bilesenler": [{"kod": "aktif_isler", "boyut": "DEV"}]})
    assert r.status_code == 422
    # Hiçbiri kaydedilmedi.
    assert (await client.get(YOL)).json()["kaynak"] == "SISTEM"


async def test_kayitta_kalan_izinsiz_ve_bilinmeyen_bilesen_okumada_duser(
    client, db, kisiler
) -> None:
    db.add(
        AnaPanelDuzeni(
            user_id=kisiler["tek"].id,
            bilesenler=[
                {"kod": "ekip_durumu", "boyut": "GENIS", "gorunur": True},
                {"kod": "kaldirilmis_bilesen", "boyut": "DAR", "gorunur": True},
                {"kod": "aktif_isler", "boyut": "GENIS", "gorunur": True},
            ],
        )
    )
    await db.commit()
    await giris(client, "tek_p")
    g = (await client.get(YOL)).json()
    assert g["kaynak"] == "KULLANICI"
    assert g["bilesenler"] == [{"kod": "aktif_isler", "boyut": "GENIS", "gorunur": True}]


# --- Kişisel düzen CRUD + iyimser kilit (S8.1) -------------------------------------------------


async def test_kisisel_duzen_olustur_guncelle_varsayilana_don(client, db, kisiler) -> None:
    await giris(client, "sef_p")
    duzen = [
        {"kod": "aktif_isler", "boyut": "GENIS", "gorunur": True},
        {"kod": "tekliflerim", "boyut": "DAR", "gorunur": True},
        {"kod": "kpi_acik_is", "boyut": "GENIS", "gorunur": False},
    ]
    r = await client.put(YOL, json={"bilesenler": duzen, "version": None})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["kaynak"] == "KULLANICI" and g["version"] == 1
    assert g["bilesenler"] == duzen
    assert g["varsayilan"]["kaynak"] == "SISTEM"

    # Başka cihazda da aynı düzen (sunucuda).
    assert (await client.get(YOL)).json()["bilesenler"] == duzen

    # Kayıt varken sürümsüz (varsayılandan başlamış eski sekme) kayıt → 409.
    r = await client.put(YOL, json={"bilesenler": duzen[:1]})
    assert r.status_code == 409

    r = await client.put(YOL, json={"bilesenler": duzen[:2], "version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and _kodlar(r.json()) == ["aktif_isler", "tekliflerim"]

    # Eski sürümle kayıt (iki sekme) → 409; düzen değişmez.
    r = await client.put(YOL, json={"bilesenler": duzen[:1], "version": 1})
    assert r.status_code == 409
    assert _kodlar((await client.get(YOL)).json()) == ["aktif_isler", "tekliflerim"]

    # Varsayılana dön: eski sürüm 409, doğru sürüm kişisel düzeni siler.
    assert (await client.delete(f"{YOL}?version=1")).status_code == 409
    r = await client.delete(f"{YOL}?version=2")
    assert r.status_code == 200, r.text
    assert r.json()["kaynak"] == "SISTEM" and _kodlar(r.json()) == _sistem()
    # İdempotent.
    assert (await client.delete(YOL)).status_code == 200
    # Silinmiş düzene eski sürümle kayıt → 409 (sıfırlanmış düzen sessizce geri gelmez).
    assert (await client.put(YOL, json={"bilesenler": duzen, "version": 2})).status_code == 409

    eylemler = (
        await db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "ana_panel_duzeni")
            .order_by(AuditLog.id)
        )
    ).all()
    assert eylemler == ["olustur", "guncelle", "sifirla"]


async def test_kullanici_duzeni_kisiye_ozel(client, kisiler) -> None:
    await giris(client, "tek_p")
    tek_duzen = [{"kod": "grafik_durum", "boyut": "GENIS", "gorunur": True}]
    assert (await client.put(YOL, json={"bilesenler": tek_duzen})).status_code == 200
    await giris(client, "tek_p2")
    assert (await client.get(YOL)).json()["kaynak"] == "SISTEM"


# --- Rol varsayılanı (S8.3, G7.3) ---------------------------------------------------------------


async def test_rol_varsayilani_kullaniciya_gecer_kisisel_duzen_ustune_yazar(
    client, kisiler
) -> None:
    rol_duzen = [
        {"kod": "aktif_isler", "boyut": "GENIS", "gorunur": True},
        {"kod": "kpi_acik_is", "boyut": "DAR", "gorunur": True},
    ]
    await giris(client, "mudur_p")
    r = await client.get(f"{ROL}/SERVIS_TEKNISYEN")
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["kaynak"] == "SISTEM" and g["version"] is None
    assert _kodlar(g) == _sistem("ekip_durumu")
    # Katalog = rolün izni ∩ düzenleyenin izni (teknisyende operasyon.gor yok).
    assert "ekip_durumu" not in _katalog(g) and "tekliflerim" not in _katalog(g)

    r = await client.put(f"{ROL}/SERVIS_TEKNISYEN", json={"bilesenler": rol_duzen})
    assert r.status_code == 200, r.text
    assert r.json()["kaynak"] == "ROL" and r.json()["version"] == 1

    # Teknisyen (kişisel düzeni yok) rol varsayılanını görür.
    await giris(client, "tek_p")
    g = (await client.get(YOL)).json()
    assert g["kaynak"] == "ROL" and g["bilesenler"] == rol_duzen
    assert g["varsayilan"] == {"kaynak": "ROL", "bilesenler": rol_duzen}

    # Kişisel düzen rolün üstüne yazar; varsayılana dön → rol düzeni.
    kendi = [{"kod": "grafik_haftalik", "boyut": "DAR", "gorunur": True}]
    g = (await client.put(YOL, json={"bilesenler": kendi})).json()
    assert g["kaynak"] == "KULLANICI" and g["bilesenler"] == kendi
    assert g["varsayilan"]["kaynak"] == "ROL"
    g = (await client.delete(YOL)).json()
    assert g["kaynak"] == "ROL" and g["bilesenler"] == rol_duzen

    # Rol varsayılanı kaldırılınca sistem varsayılanı (bugünkü panel) geçer.
    await giris(client, "mudur_p")
    r = await client.delete(f"{ROL}/SERVIS_TEKNISYEN?version=1")
    assert r.status_code == 200 and r.json()["kaynak"] == "SISTEM"
    await giris(client, "tek_p")
    g = (await client.get(YOL)).json()
    assert g["kaynak"] == "SISTEM" and _kodlar(g) == _sistem("ekip_durumu")


async def test_rol_varsayilani_yetki_ve_dogrulama(client, kisiler) -> None:
    # panel.yonet yok → 403.
    await giris(client, "sef_p")
    assert (await client.get(ROL)).status_code == 403
    assert (await client.get(f"{ROL}/SERVIS_SEF")).status_code == 403
    r = await client.put(f"{ROL}/SERVIS_SEF", json={"bilesenler": []})
    assert r.status_code == 403

    await giris(client, "admin_p")
    # Rolün izni olmayan bileşen (teknisyende operasyon.gor yok) → 403.
    r = await client.put(
        f"{ROL}/SERVIS_TEKNISYEN", json={"bilesenler": [{"kod": "ekip_durumu", "boyut": "DAR"}]}
    )
    assert r.status_code == 403
    assert (await client.get(f"{ROL}/OLMAYAN_ROL")).status_code == 404
    satirlar = {s["rol_kodu"]: s for s in (await client.get(ROL)).json()}
    assert {"SERVIS_TEKNISYEN", "SATIS_MUDURU", "ADMIN"} <= set(satirlar)
    assert satirlar["SERVIS_TEKNISYEN"]["ozel"] is False

    # Düzenleyen kendi göremediği bileşeni başka role dayatamaz: satış müdürü
    # (servis.gor yok) servis şefi rolüne servis bileşeni koyamaz.
    await giris(client, "satismd_p")
    r = await client.put(
        f"{ROL}/SERVIS_SEF", json={"bilesenler": [{"kod": "aktif_isler", "boyut": "DAR"}]}
    )
    assert r.status_code == 403
    r = await client.put(
        f"{ROL}/SERVIS_SEF", json={"bilesenler": [{"kod": "tekliflerim", "boyut": "GENIS"}]}
    )
    assert r.status_code == 200, r.text


async def test_rol_varsayilani_iyimser_kilit(client, db, kisiler) -> None:
    await giris(client, "admin_p")
    bir = [{"kod": "aktif_isler", "boyut": "DAR"}]
    assert (await client.put(f"{ROL}/SERVIS_SEF", json={"bilesenler": bir})).status_code == 200
    # İki yönetici aynı anda: ikisi de sürüm 1'den başlar, ikincisi 409.
    iki = [{"kod": "grafik_durum", "boyut": "GENIS"}]
    r = await client.put(f"{ROL}/SERVIS_SEF", json={"bilesenler": iki, "version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2
    r = await client.put(f"{ROL}/SERVIS_SEF", json={"bilesenler": bir, "version": 1})
    assert r.status_code == 409
    # Sürümsüz yeniden oluşturma da 409 (kayıt varken).
    assert (await client.put(f"{ROL}/SERVIS_SEF", json={"bilesenler": bir})).status_code == 409
    assert (await client.delete(f"{ROL}/SERVIS_SEF?version=1")).status_code == 409

    satirlar = {s["rol_kodu"]: s for s in (await client.get(ROL)).json()}
    assert satirlar["SERVIS_SEF"] == {
        "rol_kodu": "SERVIS_SEF",
        "rol_adi": satirlar["SERVIS_SEF"]["rol_adi"],
        "ozel": True,
        "version": 2,
    }
    rol = await db.scalar(select(Role).where(Role.code == "SERVIS_SEF"))
    kayit = await db.scalar(select(AnaPanelDuzeni).where(AnaPanelDuzeni.role_id == rol.id))
    assert kayit.bilesenler == [{"kod": "grafik_durum", "boyut": "GENIS", "gorunur": True}]
    denetim = (
        await db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "ana_panel_duzeni")
            .order_by(AuditLog.id)
        )
    ).all()
    assert denetim == ["rol_olustur", "rol_guncelle"]
