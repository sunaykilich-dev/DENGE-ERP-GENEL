"""Müşteri onayı ve servis formu (TS-036, E01-08, E04-15/16) + KVKK (TS-037 (5)).

- Onay DEĞİŞMEZ: yeni onay eskisini `gecersiz_kilan_id` ile geçersiz kılar,
  ikisi de durur; olay geçmişinde ONAY (kişisel veri olmadan).
- Biçimler: IMZA (IMZA eki), BASILI_FORM (SERVIS_FORMU eki), SOZLU (kim
  verdi), ALINAMADI + neden.
- `servis_onay_zorunlu_turler` türünde onaysız TAMAMLANDI → 409.
- Ziyaret onayı: aynı müşteri + lokasyon + gün (aksi 409), kapsam dışı iş
  404 ve hiçbiri yazılmaz, tek `onay_grubu`.
- Servis formu: fiyatsız, Türkçe, süre yoksa "Süre kaydı eksik", PB'de
  kontrol listesi bloğu.
- Anonimleştirme: irtibat ve imzalayan adı temizlenir, imza eki indirilemez,
  denetim satırları maskelenir.
"""

import re
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    MaintenanceContractItem,
    MaintenanceForm,
    MaintenanceFormCheck,
    MaintenancePeriod,
    ServiceApproval,
    ServiceOrderEvent,
    ServicePlan,
    ServiceTimeEntry,
    Setting,
)
from app.services import pdf as pdf_svc
from app.services.teknik_servis import onay

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"0" * 64
AN = datetime(2026, 1, 1, tzinfo=UTC)


async def _giris(client, username: str) -> None:
    r = await client.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text


async def _ek(client, so_id: int, kind: str = "IMZA") -> int:
    icerik, ad, mime = (
        (PNG, "imza.png", "image/png") if kind == "IMZA" else (JPEG, "f.jpg", "image/jpeg")
    )
    r = await client.post(
        f"/api/ekler/service_orders/{so_id}",
        params={"kind": kind},
        files={"file": (ad, icerik, mime)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _onay_say(db) -> int:
    return int(await db.scalar(select(func.count()).select_from(ServiceApproval)) or 0)


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac, kullanici_ac, servis_isi_ac, lokasyon_ac):
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    await birimli_kullanici_ac("tek2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    await birimli_kullanici_ac("sef", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"])
    await kullanici_ac("yonetim", "YONETIM")
    tesis = await lokasyon_ac(ad="Akyaka AVM")
    from app.models import Account

    hesap = await db.get(Account, tesis.account_id)
    so = await servis_isi_ac(
        musteri=hesap,
        lokasyon=tesis,
        durum="ISLEMDE",
        atananlar=[tek],
        iletisim_ad="Ayşe Yılmaz",
        iletisim_telefon="+905321112233",
    )
    return {"tek": tek, "so": so, "hesap": hesap, "tesis": tesis}


class TestTekilOnay:
    async def test_imza_sonra_sozlu_eskisini_gecersiz_kilar(self, client, db, ortam):
        so = ortam["so"]
        await _giris(client, "tek")
        ek_id = await _ek(client, so.id)
        r = await client.post(
            f"/api/teknik-servis/isler/{so.id}/onay",
            json={"tur": "IMZA", "ek_id": ek_id, "imzalayan_ad": "Ayşe Yılmaz"},
        )
        assert r.status_code == 201, r.text
        ilk = r.json()
        r = await client.post(
            f"/api/teknik-servis/isler/{so.id}/onay",
            json={"tur": "SOZLU", "imzalayan_ad": "Mehmet Öztürk", "imzalayan_unvan": "Müdür"},
        )
        assert r.status_code == 201, r.text
        ikinci = r.json()
        assert ikinci["gecersiz_kilan_id"] == ilk["id"]
        eski = await db.get(ServiceApproval, ilk["id"])
        await db.refresh(eski)
        assert eski.tur == "IMZA" and eski.imzalayan_ad == "Ayşe Yılmaz"  # değişmedi
        gecerli = await onay.gecerli_onay(db, so.id)
        assert gecerli.id == ikinci["id"]
        olaylar = (
            await db.scalars(
                select(ServiceOrderEvent).where(
                    ServiceOrderEvent.service_order_id == so.id,
                    ServiceOrderEvent.olay_turu == "ONAY",
                )
            )
        ).all()
        assert len(olaylar) == 2
        assert all("Ayşe" not in (o.ozet + str(o.veri)) for o in olaylar)
        liste = (await client.get(f"/api/teknik-servis/isler/{so.id}/onaylar")).json()
        assert {o["id"] for o in liste} == {ilk["id"], ikinci["id"]}

    @pytest.mark.parametrize(
        ("govde", "beklenen"),
        [
            ({"tur": "ALINAMADI"}, 400),
            ({"tur": "ALINAMADI", "eksik_nedeni": "   "}, 400),
            ({"tur": "IMZA", "imzalayan_ad": "X"}, 400),  # ek yok
            ({"tur": "SOZLU"}, 400),  # kim verdi yok
            ({"tur": "UYDURMA"}, 422),
        ],
    )
    async def test_girdi_hatalari(self, client, db, ortam, govde, beklenen):
        await _giris(client, "tek")
        r = await client.post(f"/api/teknik-servis/isler/{ortam['so'].id}/onay", json=govde)
        assert r.status_code == beklenen, r.text
        assert await _onay_say(db) == 0

    async def test_baska_isin_eki_ve_yanlis_ek_turu_400(self, client, db, ortam, servis_isi_ac):
        diger = await servis_isi_ac(durum="ISLEMDE", atananlar=[ortam["tek"]])
        await _giris(client, "tek")
        yabanci_ek = await _ek(client, diger.id)
        foto = await _ek(client, ortam["so"].id, kind="SERVIS_ONCESI")
        for ek_id in (yabanci_ek, foto):
            r = await client.post(
                f"/api/teknik-servis/isler/{ortam['so'].id}/onay",
                json={"tur": "IMZA", "ek_id": ek_id, "imzalayan_ad": "X Y"},
            )
            assert r.status_code == 400, r.text
        assert await _onay_say(db) == 0

    async def test_alinamadi_neden_ile_kabul(self, client, ortam):
        await _giris(client, "tek")
        r = await client.post(
            f"/api/teknik-servis/isler/{ortam['so'].id}/onay",
            json={"tur": "ALINAMADI", "eksik_nedeni": "Yetkili sahada değildi"},
        )
        assert r.status_code == 201
        assert r.json()["tur"] == "ALINAMADI"

    async def test_kapsam_ve_rbac(self, client, db, ortam):
        so = ortam["so"]
        govde = {"tur": "ALINAMADI", "eksik_nedeni": "Yok"}
        await _giris(client, "tek2")  # atanmamış teknisyen
        assert (
            await client.post(f"/api/teknik-servis/isler/{so.id}/onay", json=govde)
        ).status_code == 404
        await _giris(client, "sef_b")  # başka birim
        assert (
            await client.post(f"/api/teknik-servis/isler/{so.id}/onay", json=govde)
        ).status_code == 404
        await _giris(client, "yonetim")  # servis.yaz yok
        assert (
            await client.post(f"/api/teknik-servis/isler/{so.id}/onay", json=govde)
        ).status_code == 403
        assert await _onay_say(db) == 0
        await db.refresh(so)
        assert so.status == "ISLEMDE"

    async def test_iptal_iste_onay_409(self, client, db, servis_isi_ac, ortam):
        so = await servis_isi_ac(durum="IPTAL", cancel_reason="Vazgeçildi", cancelled_at=AN)
        await _giris(client, "sef")
        r = await client.post(
            f"/api/teknik-servis/isler/{so.id}/onay",
            json={"tur": "ALINAMADI", "eksik_nedeni": "Yok"},
        )
        assert r.status_code == 409
        assert await _onay_say(db) == 0


async def test_zorunlu_turde_onaysiz_tamamlama_409(client, db, ortam):
    """Kabul (1): ayarda zorunlu türde onaysız TAMAMLANDI 409; ALINAMADI+neden yeter."""
    db.add(Setting(key="servis_onay_zorunlu_turler", value=["PB", "ARIZA"]))
    await db.commit()
    so = ortam["so"]
    await _giris(client, "tek")
    sonuc = {
        "sonuc": "COZULDU",
        "cozum_kanali": "YERINDE",
        "yapilan_islem": "Kablo yenilendi",
        "sure_eksik_onay": True,
    }
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=sonuc)
    assert r.status_code == 409, r.text
    assert "onay" in r.json()["detail"].lower()
    await db.refresh(so)
    assert so.status == "ISLEMDE"
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/onay",
        json={"tur": "ALINAMADI", "eksik_nedeni": "Yetkili yoktu"},
    )
    assert r.status_code == 201
    r = await client.post(f"/api/teknik-servis/isler/{so.id}/sonuc", json=sonuc)
    assert r.status_code == 200, r.text
    await db.refresh(so)
    assert so.status == "TAMAMLANDI"


class TestZiyaretOnayi:
    async def _isler(self, servis_isi_ac, ortam, adet=2, **kw):
        return [
            await servis_isi_ac(
                musteri=ortam["hesap"],
                lokasyon=kw.get("lokasyon", ortam["tesis"]),
                durum="ISLEMDE",
                atananlar=[ortam["tek"]],
            )
            for _ in range(adet)
        ]

    async def test_ayni_musteri_lokasyon_gun_tek_grup(self, client, db, servis_isi_ac, ortam):
        isler = [ortam["so"], *await self._isler(servis_isi_ac, ortam)]
        await _giris(client, "tek")
        ek_id = await _ek(client, isler[1].id)
        r = await client.post(
            "/api/teknik-servis/isler/ziyaret-onayi",
            json={
                "is_idler": [s.id for s in isler],
                "tur": "IMZA",
                "ek_id": ek_id,
                "imzalayan_ad": "Ayşe Yılmaz",
            },
        )
        assert r.status_code == 201, r.text
        onaylar = r.json()
        assert len(onaylar) == 3
        assert len({o["onay_grubu"] for o in onaylar}) == 1 and onaylar[0]["onay_grubu"]
        assert {o["service_order_id"] for o in onaylar} == {s.id for s in isler}

    async def test_farkli_lokasyon_409_hicbiri_yazilmaz(
        self, client, db, servis_isi_ac, lokasyon_ac, ortam
    ):
        from app.models import Account

        hesap = await db.get(Account, ortam["tesis"].account_id)
        baska_tesis = await lokasyon_ac(hesap, ad="Başka Tesis")
        (baska,) = await self._isler(servis_isi_ac, ortam, adet=1, lokasyon=baska_tesis)
        await _giris(client, "tek")
        r = await client.post(
            "/api/teknik-servis/isler/ziyaret-onayi",
            json={"is_idler": [ortam["so"].id, baska.id], "tur": "ALINAMADI", "eksik_nedeni": "Y"},
        )
        assert r.status_code == 409
        assert await _onay_say(db) == 0

    async def test_farkli_gun_409(self, client, db, servis_isi_ac, ortam):
        (ikinci,) = await self._isler(servis_isi_ac, ortam, adet=1)
        db.add(
            ServicePlan(
                service_order_id=ikinci.id,
                plan_date=date(2026, 1, 5),
                duration_min=60,
                change_type="ILK_PLAN",
            )
        )
        await db.commit()
        await _giris(client, "tek")
        r = await client.post(
            "/api/teknik-servis/isler/ziyaret-onayi",
            json={"is_idler": [ortam["so"].id, ikinci.id], "tur": "ALINAMADI", "eksik_nedeni": "Y"},
        )
        assert r.status_code == 409
        assert "gün" in r.json()["detail"]
        assert await _onay_say(db) == 0

    async def test_kapsam_disi_is_404_hicbiri_yazilmaz(self, client, db, servis_isi_ac, ortam):
        yabanci = await servis_isi_ac(musteri=ortam["hesap"], lokasyon=ortam["tesis"])  # atanmamış
        await _giris(client, "tek")
        r = await client.post(
            "/api/teknik-servis/isler/ziyaret-onayi",
            json={
                "is_idler": [ortam["so"].id, yabanci.id],
                "tur": "ALINAMADI",
                "eksik_nedeni": "Y",
            },
        )
        assert r.status_code == 404
        assert await _onay_say(db) == 0


class TestServisFormu:
    async def test_form_baglami_fiyatsiz_turkce_sure_eksik(self, client, db, ortam):
        so = ortam["so"]
        baglam = await onay.servis_formu_baglami(db, so, clock=client.clock)
        html = pdf_svc.html_uret("servis_formu.html", **baglam)
        assert "Süre kaydı eksik" in html
        assert "Akyaka AVM" in html and "SERVİS FORMU" in html
        assert not re.search(r"fiyat|tutar|₺|\bTL\b", html, flags=re.IGNORECASE)
        assert "Kayıt yok" in html  # parçalar
        assert "0 sa" not in html and "0 dk" not in html

    async def test_sure_kaydi_varsa_kisi_bazli_sure(self, client, db, ortam):
        so = ortam["so"]
        db.add(
            ServiceTimeEntry(
                service_order_id=so.id,
                user_id=ortam["tek"].id,
                faaliyet="SAHA",
                started_at=AN,
                ended_at=AN + timedelta(minutes=95),
                kaynak="MANUEL",
                girildi_at=AN,
            )
        )
        await db.commit()
        baglam = await onay.servis_formu_baglami(db, so)
        sure = baglam["isler"][0]["sure"]
        assert sure["kayit_var"] and sure["toplam"] == "1 sa 35 dk"
        html = pdf_svc.html_uret("servis_formu.html", **baglam)
        assert "Süre kaydı eksik" not in html and "Tek" in html

    async def test_pb_kontrol_listesi_blogu(self, client, db, servis_isi_ac, sozlesme_ac):
        sozlesme = await sozlesme_ac()
        kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
        donem = MaintenancePeriod(
            contract_id=sozlesme.id, cycle_start=AN, sequence_no=1, target_date=date(2026, 1, 15)
        )
        db.add_all([kalem, donem])
        await db.commit()
        pb = await servis_isi_ac(
            tur="PB",
            durum="PLANLAMADA",
            contract_item_id=kalem.id,
            maintenance_period_id=donem.id,
        )
        html = pdf_svc.html_uret("servis_formu.html", **await onay.servis_formu_baglami(db, pb))
        assert "Bakım formu doldurulmamış" in html
        form = MaintenanceForm(service_order_id=pb.id, template_code="XRAY", template_version=1)
        db.add(form)
        await db.flush()
        db.add(
            MaintenanceFormCheck(
                form_id=form.id, check_code="K1", label="Işın güvenliği kontrolü", sira=1
            )
        )
        await db.commit()
        html = pdf_svc.html_uret("servis_formu.html", **await onay.servis_formu_baglami(db, pb))
        assert "Bakım kontrol listesi" in html and "Işın güvenliği kontrolü" in html

    async def test_ziyaret_formu_toplu(self, client, db, servis_isi_ac, ortam):
        ikinci = await servis_isi_ac(musteri=ortam["hesap"], lokasyon=ortam["tesis"])
        baglam = await onay.ziyaret_formu_baglami(db, [ortam["so"].id, ikinci.id])
        html = pdf_svc.html_uret("servis_formu.html", **baglam)
        assert "Ziyaretteki işler (2)" in html
        assert ortam["so"].so_no in html and ikinci.so_no in html

    async def test_pdf_ucu_kapsam_ve_rbac(self, client, kullanici_ac, ortam):
        so = ortam["so"]
        await kullanici_ac("satis", "DEPO")  # servis.gor yok (SATIS artık kendi müşterisini görür)
        await _giris(client, "satis")
        assert (
            await client.get(f"/api/teknik-servis/isler/{so.id}/servis-formu.pdf")
        ).status_code == 403
        await _giris(client, "sef_b")
        assert (
            await client.get(f"/api/teknik-servis/isler/{so.id}/servis-formu.pdf")
        ).status_code == 404
        await _giris(client, "sef")
        try:
            r = await client.get(f"/api/teknik-servis/isler/{so.id}/servis-formu.pdf")
        except pdf_svc.PdfUretilemedi:
            pytest.skip("WeasyPrint sistem kitaplıkları bu makinede yok")
        if r.status_code == 503:
            pytest.skip("WeasyPrint sistem kitaplıkları bu makinede yok")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"


async def test_anonimlestirme_servis_ve_onay_kisisel_verisi(client, db, ortam):
    from app.models import Attachment
    from app.services import kvkk

    so = ortam["so"]
    await _giris(client, "tek")
    ek_id = await _ek(client, so.id)
    r = await client.post(
        f"/api/teknik-servis/isler/{so.id}/onay",
        json={"tur": "IMZA", "ek_id": ek_id, "imzalayan_ad": "Ayşe Yılmaz"},
    )
    assert r.status_code == 201
    onay_id = r.json()["id"]
    assert (await client.get(f"/api/ekler/dosya/{ek_id}")).status_code == 200

    bulunan = await kvkk.veri_bul(db, "Ayşe Yılmaz")
    assert [s["id"] for s in bulunan["servis_isleri"]] == [so.id]

    await kvkk.hesabi_anonimlestir(
        db, ortam["hesap"].id, clock=client.clock, gerekce="KVKK silme talebi #1"
    )
    await db.commit()
    await db.refresh(so)
    assert so.iletisim_ad is None and so.iletisim_telefon is None
    kayit = await db.get(ServiceApproval, onay_id)
    await db.refresh(kayit)
    assert kayit.imzalayan_ad is None
    ek = await db.get(Attachment, ek_id)
    await db.refresh(ek)
    assert "Ayşe" not in ek.file_name
    # Anonimleştirme sonrası imza eki indirilemez.
    assert (await client.get(f"/api/ekler/dosya/{ek_id}")).status_code == 404
    # Denetim satırlarında kişisel değer kalmadı.
    satirlar = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.entity == "service_approvals", AuditLog.is_personal_data.is_(True)
            )
        )
    ).all()
    assert satirlar and all("Ayşe" not in str(s.new_value) for s in satirlar)
