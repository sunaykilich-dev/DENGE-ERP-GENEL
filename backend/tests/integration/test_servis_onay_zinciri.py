"""İki aşamalı kapanış ve tekliften teknik servise geçiş (KARARLAR 2026-11-05 §9).

Kurgu: müdür işi ekip liderine verir → lider planlar ve teknisyene tayin eder →
teknisyen yapar ve tamamlar → ekip lideri onaylar (kalite onayı) → müdür son
onayı verip kapatır. Satış destek servis teklifi hazırlar; teklif iç onaydan
geçip müşteri kabul edince iş teknik servise PLANLAMADA olarak düşer.

Korunanlar: `servis_kapanis_onay_zinciri` kapalıyken eski tek adımlı kapanış
aynen sürer; açıkken lider onayı olmadan kapanmaz (409), şef kapatamaz (403);
liderin ŞEF tayini onu kalite onayından men etmez, teknisyen tayini eder.
"""

from datetime import datetime

import pytest
from servis_teklif_yardimci import elle_gonder, kapat, musteri, onayli, oturum, teklif_ac
from servis_yardimci import giris, tazele, teknisyen
from sqlalchemy import select

from app.models import ServiceOrder, ServiceOrderAssignment
from app.permissions import permissions_of
from app.services import settings as ayar_svc

pytestmark = pytest.mark.integration

IS = "/api/teknik-servis/isler"
SONUC = {
    "sonuc": "COZULDU",
    "cozum_kanali": "YERINDE",
    "yapilan_islem": "Kablo yenilendi",
    "sure_eksik_onay": True,
}


def test_son_onay_yalniz_mudurde() -> None:
    assert "servis.son_onay" in permissions_of("SERVIS_YONETICI")
    assert "servis.son_onay" in permissions_of("ADMIN")
    for rol in ("SERVIS_SEF", "SERVIS_TEKNISYEN", "SERVIS_OPERASYON", "SATIS_DESTEK"):
        assert "servis.son_onay" not in permissions_of(rol), rol


async def _zincir_ac(db) -> None:
    await ayar_svc.set_many(db, {"servis_kapanis_onay_zinciri": True}, None)
    await db.commit()


async def test_iki_asamali_kapanis_lider_sonra_mudur(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("mudur_k", "SERVIS_YONETICI", ["GUVENLIK", "HABERLESME"])
    lider = await birimli_kullanici_ac("lider_k", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    tek = await teknisyen(birimli_kullanici_ac, "tek_z1")
    so = await servis_isi_ac(atananlar=[tek])
    # Müdür işi ekip liderine verdi: liderin ŞEF tayini (koordinatör).
    db.add(
        ServiceOrderAssignment(
            service_order_id=so.id,
            user_id=lider.id,
            rol="SEF",
            is_lead=False,
            assigned_at=datetime.fromisoformat("2026-01-01T09:00:00+03:00"),
        )
    )
    await db.commit()
    await _zincir_ac(db)

    await giris(client, "tek_z1")
    r = await client.post(f"{IS}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    surum = r.json()["version"]

    # Lider onayı olmadan müdür de kapatamaz.
    await giris(client, "mudur_k")
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 409 and "ekip liderinin onayı" in r.json()["detail"]

    # Lider (ŞEF tayinli, sahada çalışmadı) onay verebilir; ama kapatamaz.
    await giris(client, "lider_k")
    r = await client.get(f"{IS}/{so.id}")
    assert r.json()["kalite"]["verebilir"] is True
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": surum})
    assert r.status_code == 200, r.text
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 403 and "servis.son_onay" in r.json()["detail"]
    assert (await tazele(db, so)).status == "TAMAMLANDI"

    # Müdür son onayı: kapanır.
    await giris(client, "mudur_k")
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 200, r.text
    so = await tazele(db, so)
    assert so.status == "KAPATILDI" and so.kalite_onay_at is not None


async def test_teknisyen_tayinli_lider_onaylayamaz(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    lider = await birimli_kullanici_ac("lider_k2", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    so = await servis_isi_ac(atananlar=[lider])  # sahaya teknisyen olarak gitti
    await _zincir_ac(db)
    await giris(client, "lider_k2")
    r = await client.post(f"{IS}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": r.json()["version"]})
    assert r.status_code == 403 and "görevler ayrılığı" in r.json()["detail"]


async def test_zincir_kapaliyken_eski_kapanis_surer(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_eski", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(durum="TAMAMLANDI")
    await giris(client, "sef_eski")
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 200, r.text


async def test_kabul_edilen_servis_teklifi_teknik_servise_duser(
    client, db, birimli_kullanici_ac
) -> None:
    await birimli_kullanici_ac("satis_dk", "SATIS_DESTEK", ["GUVENLIK"])
    await birimli_kullanici_ac("mudur_t", "SERVIS_YONETICI", ["GUVENLIK"])
    h = await musteri(db, "Teklif Bakım Müşterisi")
    satis = await oturum("satis_dk")
    mudur = await oturum("mudur_t")
    try:
        # Seçilmemiş tür ya da geçersiz tür.
        await teklif_ac(satis, h.id, servis_turu="PB", beklenen=400)
        await teklif_ac(satis, h.id, birim=None, servis_turu="ARIZA", beklenen=400)
        t = await teklif_ac(
            satis, h.id, title="X-Ray yıllık bakım teklifi", servis_turu="PLANSIZ_BAKIM"
        )
        assert t["servis_turu"] == "PLANSIZ_BAKIM" and t["service_order_id"] is None
        await onayli(satis, mudur, t["id"])
        await elle_gonder(satis, t["id"])
        r = await satis.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
        assert r.status_code == 200, r.text
        y = r.json()
        assert y["status"] == "KABUL" and y["service_order_id"] is not None
        assert any("servis işi açıldı" in u for u in y["uyarilar"])
        so = await db.scalar(
            select(ServiceOrder)
            .where(ServiceOrder.id == y["service_order_id"])
            .execution_options(populate_existing=True)
        )
        assert so.tur == "PLANSIZ_BAKIM" and so.status == "PLANLAMADA"
        assert so.birim == "GUVENLIK" and so.customer_id == h.id
        assert t["quote_no"] in (so.aciklama or "")
        # Müdür işi görür (teknik servis havuzunda).
        r = await mudur.get(f"{IS}/{so.id}")
        assert r.status_code == 200

        # Türü seçilmemiş teklif kabulde iş açmaz (eski davranış).
        t2 = await teklif_ac(satis, h.id, title="Bilgi teklifi")
        await onayli(satis, mudur, t2["id"])
        await elle_gonder(satis, t2["id"])
        r = await satis.post(f"/api/teklifler/{t2['id']}/karar", json={"kabul": True})
        assert r.status_code == 200 and r.json()["service_order_id"] is None
    finally:
        await kapat(satis, mudur)


async def test_gecis_kaydinda_talep_eden_yoksa_is_acilir(
    client, db, birimli_kullanici_ac, lokasyon_ac, ekipman_ac
) -> None:
    """KARARLAR 2026-11-05 §9.8: kaynak listede talep eden kişi yoksa iş yalnız
    geçiş kaydı (`servis.gecis_kaydi` + gerekçe) olarak açılır; lokasyon yine
    zorunlu, sıradan açılış ve izinsiz geçiş eskisi gibi reddedilir."""
    await birimli_kullanici_ac("mudur_g", "SERVIS_YONETICI", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    h = await musteri(db, "Talep Listesi Müşterisi")
    tesis = await lokasyon_ac(h, ad="Talep Listesi AVM")
    e = await ekipman_ac(musteri=h, lokasyon=tesis, seri=None)
    govde = {"ekipman_idler": [e.id], "tur": "KURULUM", "konu": "Kurulum", "talep_kanali": "DIGER"}
    gerekce = "Güvenlik talep takip listesinden aktarım; yetkili listede yok"

    await giris(client, "sef_g")
    r = await client.post(f"{IS}/ekipmandan", json=govde)
    assert r.status_code == 400 and "Talep eden" in r.json()["detail"]
    r = await client.post(
        f"{IS}/ekipmandan", json={**govde, "gecis_kaydi": True, "gecis_gerekcesi": gerekce}
    )
    assert r.status_code == 403  # şefte servis.gecis_kaydi yok

    await giris(client, "mudur_g")
    r = await client.post(f"{IS}/ekipmandan", json={**govde, "gecis_kaydi": True})
    assert r.status_code == 400 and "gerekçe" in r.json()["detail"]
    r = await client.post(
        f"{IS}/ekipmandan", json={**govde, "gecis_kaydi": True, "gecis_gerekcesi": gerekce}
    )
    assert r.status_code == 201, r.text
    so = await db.get(ServiceOrder, r.json()["isler"][0]["id"])
    assert so.sla_kaynak == "GECIS" and so.equipment_id == e.id
