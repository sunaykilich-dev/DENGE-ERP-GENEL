"""Servis işi ekleri (TS-032, E01-07 revised, K18/K19, B9).

Kurallar: okuma birim + kendi işi; yazma (yükleme/silme) KENDI_ISLERI'nde
yalnız AKTİF ATAMA; içerik türüyle uyuşmazsa 400 (yalnız servis işi); kapalı
işe ekleme/silme yalnız `servis.kapat`; yükleyen kişi 24 saat içinde siler
(saat EK olayının Clock zamanından); onaya bağlı ek silinemez (409); EK ve
EK_SIL olayları geçmişte (EK_SIL dosya adı + sha256 tutar).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import (
    Attachment,
    ServiceApproval,
    ServiceOrderEvent,
    ServicePlan,
    ServicePlanMember,
)

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
SAHTE_JPEG = b"<html><script>alert(1)</script></html>"


async def _giris(client, username: str) -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _yukle(
    client, so_id: int, icerik: bytes = JPEG, kind: str = "SERVIS_ONCESI", ad="foto.jpg"
):
    mime = "image/png" if icerik.startswith(b"\x89PNG") else "image/jpeg"
    return await client.post(
        f"/api/ekler/service_orders/{so_id}",
        params={"kind": kind},
        files={"file": (ad, icerik, mime)},
    )


async def _ek_say(db) -> int:
    return int(await db.scalar(select(func.count()).select_from(Attachment)) or 0)


async def _olaylar(db, so_id: int, tur: str) -> list[ServiceOrderEvent]:
    return list(
        (
            await db.scalars(
                select(ServiceOrderEvent)
                .where(
                    ServiceOrderEvent.service_order_id == so_id,
                    ServiceOrderEvent.olay_turu == tur,
                )
                .order_by(ServiceOrderEvent.id)
            )
        ).all()
    )


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac, kullanici_ac, servis_isi_ac):
    kisiler = {
        "tek": await birimli_kullanici_ac(
            "tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "tek2": await birimli_kullanici_ac(
            "tek2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
        ),
        "sef": await birimli_kullanici_ac("sef", "SERVIS_SEF", ["GUVENLIK"]),
        "sef_b": await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"]),
        "yonetim": await kullanici_ac("yonetim", "YONETIM"),
        "satis": await kullanici_ac("satis", "SATIS"),
    }
    isi = await servis_isi_ac(birim="GUVENLIK", durum="ISLEMDE", atananlar=[kisiler["tek"]])
    return {"k": kisiler, "is": isi}


class TestOkumaVeYazmaKapsami:
    async def test_atanan_teknisyen_yukler_listeler_ve_ek_olayi_yazilir(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "tek")
        r = await _yukle(client, so.id)
        assert r.status_code == 201, r.text
        ek_id = r.json()["id"]
        liste = await client.get(f"/api/ekler/service_orders/{so.id}")
        assert liste.status_code == 200
        assert [e["id"] for e in liste.json()] == [ek_id]
        (olay,) = await _olaylar(db, so.id, "EK")
        assert olay.veri["ek_id"] == ek_id and olay.veri["sha256"]
        assert olay.olusma_zamani == client.clock.now()  # Clock'tan (B9)
        indir = await client.get(f"/api/ekler/dosya/{ek_id}")
        assert indir.status_code == 200 and indir.content == JPEG

    async def test_atanmamis_teknisyen_404_ve_hicbir_sey_yazilmaz(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "tek")
        ek_id = (await _yukle(client, so.id)).json()["id"]

        await _giris(client, "tek2")
        once = await _ek_say(db)
        assert (await client.get(f"/api/ekler/service_orders/{so.id}")).status_code == 404
        assert (await client.get(f"/api/ekler/dosya/{ek_id}")).status_code == 404
        assert (await _yukle(client, so.id)).status_code == 404
        assert (await client.delete(f"/api/ekler/{ek_id}")).status_code == 404
        assert await _ek_say(db) == once
        assert len(await _olaylar(db, so.id, "EK_SIL")) == 0

    async def test_plan_uyesi_okur_ama_yukleyemez(self, client, db, ortam):
        """KENDI_ISLERI: plan üyeliği okuma için yeterli, yazma için aktif atama şart."""
        so, tek2 = ortam["is"], ortam["k"]["tek2"]
        plan = ServicePlan(
            service_order_id=so.id,
            plan_date=date(2026, 1, 2),
            duration_min=60,
            change_type="ILK_PLAN",
        )
        db.add(plan)
        await db.flush()
        db.add(ServicePlanMember(plan_id=plan.id, user_id=tek2.id, rol="TEKNISYEN"))
        await db.commit()

        await _giris(client, "tek2")
        assert (await client.get(f"/api/ekler/service_orders/{so.id}")).status_code == 200
        assert (await _yukle(client, so.id)).status_code == 404
        assert await _ek_say(db) == 0

    async def test_baska_birim_sefi_404_veri_degismedi(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "sef")
        ek_id = (await _yukle(client, so.id)).json()["id"]
        await _giris(client, "sef_b")
        assert (await client.get(f"/api/ekler/service_orders/{so.id}")).status_code == 404
        assert (await client.delete(f"/api/ekler/{ek_id}")).status_code == 404
        ek = await db.get(Attachment, ek_id)
        await db.refresh(ek)
        assert ek.entity_id == so.id
        await db.refresh(so)
        assert so.status == "ISLEMDE"

    async def test_rbac_okuma_izni_yukleme_izni(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "yonetim")  # servis.gor var, servis.yaz yok (TUMU)
        assert (await client.get(f"/api/ekler/service_orders/{so.id}")).status_code == 200
        assert (await _yukle(client, so.id)).status_code == 403
        await _giris(client, "satis")  # servis.gor yok
        assert (await client.get(f"/api/ekler/service_orders/{so.id}")).status_code == 403
        assert await _ek_say(db) == 0


class TestIcerikDogrulama:
    async def test_uzantisi_jpg_icerigi_html_400(self, client, db, ortam):
        await _giris(client, "tek")
        r = await _yukle(client, ortam["is"].id, SAHTE_JPEG)
        assert r.status_code == 400
        assert "uyuşmuyor" in r.json()["detail"]
        assert await _ek_say(db) == 0

    async def test_png_imza_kabul(self, client, ortam):
        await _giris(client, "tek")
        r = await _yukle(client, ortam["is"].id, PNG, kind="IMZA", ad="imza.png")
        assert r.status_code == 201, r.text


class TestKapaliIs:
    async def test_kapali_ise_ek_yalniz_servis_kapat_ile(self, client, db, ortam, servis_isi_ac):
        tek = ortam["k"]["tek"]
        so = await servis_isi_ac(birim="GUVENLIK", durum="TAMAMLANDI", atananlar=[tek])
        await _giris(client, "tek")
        r = await _yukle(client, so.id)
        assert r.status_code == 409
        assert "servis.kapat" in r.json()["detail"]
        assert await _ek_say(db) == 0
        await _giris(client, "sef")
        assert (await _yukle(client, so.id)).status_code == 201


class TestSilme:
    async def test_yukleyen_24_saat_icinde_siler_ve_ek_sil_olayi(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "tek")
        yuklenen = (await _yukle(client, so.id, ad="kapı fotoğrafı.jpg")).json()
        client.clock.advance(hours=23)
        await _giris(client, "tek")  # oturum boşta kalma süresi doldu
        r = await client.delete(f"/api/ekler/{yuklenen['id']}")
        assert r.status_code == 204, r.text
        assert await db.get(Attachment, yuklenen["id"]) is None
        (olay,) = await _olaylar(db, so.id, "EK_SIL")
        assert olay.veri["dosya"] == "kapı fotoğrafı.jpg"
        assert len(olay.veri["sha256"]) == 64

    async def test_24_saat_sonra_yukleyen_silemez_sef_siler(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "tek")
        ek_id = (await _yukle(client, so.id)).json()["id"]
        client.clock.advance(hours=25)
        await _giris(client, "tek")
        r = await client.delete(f"/api/ekler/{ek_id}")
        assert r.status_code == 409
        assert await db.get(Attachment, ek_id) is not None
        await _giris(client, "sef")
        assert (await client.delete(f"/api/ekler/{ek_id}")).status_code == 204

    async def test_baskasinin_ekini_silemez(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "sef")
        ek_id = (await _yukle(client, so.id)).json()["id"]
        await _giris(client, "tek")  # atanmış ama yükleyen değil, servis.kapat yok
        assert (await client.delete(f"/api/ekler/{ek_id}")).status_code == 409
        assert await db.get(Attachment, ek_id) is not None

    async def test_onaya_bagli_ek_silinemez(self, client, db, ortam):
        so = ortam["is"]
        await _giris(client, "sef")
        ek_id = (await _yukle(client, so.id, PNG, kind="IMZA", ad="imza.png")).json()["id"]
        db.add(
            ServiceApproval(
                service_order_id=so.id,
                tur="IMZA",
                imzalayan_ad="Müşteri Yetkilisi",
                ek_id=ek_id,
                approved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await db.commit()
        r = await client.delete(f"/api/ekler/{ek_id}")
        assert r.status_code == 409
        assert "onay" in r.json()["detail"]
        assert await db.get(Attachment, ek_id) is not None

    async def test_kapali_iste_teknisyen_silemez(self, client, db, ortam, servis_isi_ac):
        tek = ortam["k"]["tek"]
        so = await servis_isi_ac(birim="GUVENLIK", durum="ISLEMDE", atananlar=[tek])
        await _giris(client, "tek")
        ek_id = (await _yukle(client, so.id)).json()["id"]
        so.status = "TAMAMLANDI"  # kurulum: durum makinesi bu testin konusu değil
        so.completed_at = client.clock.now() + timedelta(minutes=1)
        so.first_completed_at = so.completed_at
        await db.commit()
        r = await client.delete(f"/api/ekler/{ek_id}")
        assert r.status_code == 409
        assert "Kapalı" in r.json()["detail"]


async def test_diger_sahiplerin_davranisi_degismedi(client, kullanici_ac, db):
    """Canlı tür (hesap): içerik denetimi yok, olay yok, silme serbest (regresyon)."""
    from app.models import Account

    await kullanici_ac("admin", "ADMIN")
    hesap = Account(title="Regresyon A.Ş.", is_musteri=True)
    db.add(hesap)
    await db.commit()
    await _giris(client, "admin")
    r = await client.post(
        f"/api/ekler/accounts/{hesap.id}",
        params={"kind": "DIGER"},
        files={"file": ("x.jpg", SAHTE_JPEG, "image/jpeg")},
    )
    assert r.status_code == 201
    assert (await client.delete(f"/api/ekler/{r.json()['id']}")).status_code == 204
