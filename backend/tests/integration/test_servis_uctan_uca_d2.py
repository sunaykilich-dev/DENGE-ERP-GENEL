"""Dalga 2 uçtan uca senaryoları (plan §3 Dalga 2 geçidi; doğrulayıcı).

Paketler kendi modüllerini ayrı ayrı sınadı; burada modüller arası zincirler
GERÇEK uçlardan, tek akışta yürütülür:

1. Atölye: kabul → teşhis → onarım → test → teslim; servis işi TAMAMLANDI,
   maliyet görmeyen şefte `repair_amount` anahtarı YOK.
2. Kiralama: oluştur → seri tahsis (aynı seri çakışan ikinci kiralamaya 409)
   → sevk → kurulum işi + aşama → toplama işi + aşama → depoya iade →
   dönüş kontrolü → kapanış.
3. Kiralık cihaz → atölye köprüsü (TS-102): arızalı dönüş kontrolünden
   KIRALAMA_TAKIP atölye kaydı; atölye teslimi cihazı son deposuna
   KONTROLDE döndürür.
4. Servis işine parça çıkışı: stok düşer, negatif stok 409 ve defter
   değişmez; maliyet anahtarları yalnız `maliyet.gor` sahibinde.
5. Servis işinden teklif: müşteri sunucuda kopyalanır, iç onay + kabul
   gelir olarak işe aktarılır.
"""

from __future__ import annotations

import httpx
import pytest
from atolye_yardimci import ONEK as ATOLYE
from atolye_yardimci import detay, gec, kabul_et, sef, teslim_govdesi, teslime_hazirla
from kiralama_ortak import URL as KIRALAMA
from kiralama_ortak import (
    cihaz_durumlari,
    depo_ac,
    kalem_id,
    kiralama_ac,
    kiralik_urun_ac,
    musteri_ac,
    planla,
    seri_idleri,
    stok_gir,
    tahsis,
)
from servis_teklif_yardimci import elle_gonder, onayli, teklif_ac
from servis_yardimci import giris, musteri
from sqlalchemy import func, select

from app.models import (
    Product,
    RentalAsset,
    ServiceOrder,
    ServiceOrderFinancial,
    ServiceResult,
    StockMovement,
    Warehouse,
    WorkOrder,
    WorkshopRecord,
)

pytestmark = pytest.mark.integration


async def _oturum(username: str) -> httpx.AsyncClient:
    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return ist


@pytest.fixture
async def oturumlar():
    acik: list[httpx.AsyncClient] = []

    async def _ac(username: str) -> httpx.AsyncClient:
        ist = await _oturum(username)
        acik.append(ist)
        return ist

    yield _ac
    for ist in acik:
        await ist.aclose()


async def _tamamla(db, clock, so_id: int, islem: str) -> None:
    """Kurulum/toplama işini sahada bitmiş say (sonuç + TAMAMLANDI; çekirdek akış
    Dalga 1 uçtan uca testinde ayrıca sınanıyor)."""
    from app.services.teknik_servis import is_emirleri

    db.add(
        ServiceResult(
            service_order_id=so_id, sonuc="COZULDU", cozum_kanali="YERINDE", yapilan_islem=islem
        )
    )
    await db.commit()
    so = await db.get(ServiceOrder, so_id, populate_existing=True)
    await is_emirleri.durum_degistir(db, so, "TAMAMLANDI", kaynak="sonuc", user=None, clock=clock)
    await db.commit()


# --- 1. Atölye -----------------------------------------------------------------------------


async def test_atolye_kabul_teshis_onarim_teslim(client, db, birimli_kullanici_ac) -> None:
    await sef(birimli_kullanici_ac)
    hesap = await musteri(db, "Uçtan Uca Atölye Müşterisi")
    await giris(client, "atl_sef")

    d = await kabul_et(client, hesap.id, "UU-ATL-1")
    so_id = d["so_id"]
    assert d["status"] == "KABUL_EDILDI"
    so = await db.get(ServiceOrder, so_id, populate_existing=True)
    assert so.tur == "ATOLYE" and so.status == "ATOLYEDE"
    # Genel durum ucu atölye işinde kilitli (TS-090).
    r = await client.post(
        f"/api/teknik-servis/isler/{so_id}/durum",
        json={"hedef": "ISLEMDE", "beklenen_durum": so.status},
    )
    assert r.status_code in (400, 409, 422), r.text

    await teslime_hazirla(client, db, so_id)
    dd = await detay(client, so_id)
    assert dd["status"] == "TESLIME_HAZIR"
    # SERVIS_SEF maliyet görmez: tamir bedeli anahtarı yanıtta yok (TS-092).
    assert "repair_amount" not in dd
    r = await gec(client, so_id, "TESLIM_EDILDI", teslim=teslim_govdesi(dd), sure_eksik_onay=True)
    kayit = await db.scalar(
        select(WorkshopRecord)
        .where(WorkshopRecord.service_order_id == so_id)
        .execution_options(populate_existing=True)
    )
    assert kayit.status == "TESLIM_EDILDI" and kayit.delivered_at is not None
    so = await db.get(ServiceOrder, so_id, populate_existing=True)
    assert so.status == "TAMAMLANDI"
    sonuc = await db.scalar(select(ServiceResult).where(ServiceResult.service_order_id == so_id))
    assert sonuc is not None and sonuc.cozum_kanali == "ATOLYE"
    # Liste ve Excel de bedel taşımaz.
    liste = (await client.get(ATOLYE)).json()
    satirlar = liste["kayitlar"] if isinstance(liste, dict) and "kayitlar" in liste else liste
    assert all("repair_amount" not in s for s in satirlar)


# --- 2. Kiralama ---------------------------------------------------------------------------


async def test_kiralama_tahsis_sevk_kurulum_toplama_depoya_kontrol(
    client, db, kullanici_ac, birimli_kullanici_ac, oturumlar
) -> None:
    await kullanici_ac("uu_kir_yon", "SERVIS_YONETICI")
    await birimli_kullanici_ac("uu_kir_depo", "KIRALAMA_DEPO", ["GUVENLIK"])
    ist = await oturumlar("uu_kir_yon")
    depocu = await oturumlar("uu_kir_depo")

    depo = await depo_ac(db, "UU-KIR-D1", birim="GUVENLIK")
    m1 = await musteri_ac(db, "Uçtan Uca Kiracı 1")
    m2 = await musteri_ac(db, "Uçtan Uca Kiracı 2")
    urun = await kiralik_urun_ac(db, "UU-KIR-SERI", seri=True)
    # Üçüncü cihaz ikinci kiralamanın müsaitlik kontrolünü geçirsin diye var.
    await stok_gir(ist, urun, depo, seriler=["UU-K-1", "UU-K-2", "UU-K-3"])
    cihazlar = (await seri_idleri(db, urun))[:2]

    k = await kiralama_ac(ist, m1, [(urun, 2)], bas="2026-11-01", bit="2026-11-10")
    await planla(ist, k)
    k = await tahsis(ist, k, [{"kalem_id": kalem_id(k, urun), "kiralik_idler": cihazlar}])
    assert len(k["tahsisler"]) == 2

    # Aynı seri çakışan tarihte ikinci kiralamaya tahsis edilemez (TS-112).
    k2 = await kiralama_ac(ist, m2, [(urun, 1)], bas="2026-11-05", bit="2026-11-08")
    await planla(ist, k2)
    r = await ist.post(
        f"{KIRALAMA}/{k2['id']}/tahsis",
        json={"satirlar": [{"kalem_id": kalem_id(k2, urun), "kiralik_idler": [cihazlar[0]]}]},
    )
    assert r.status_code == 409, r.text
    r = await ist.post(f"{KIRALAMA}/{k2['id']}/iptal", json={"gerekce": "Cihaz başka kiralamada"})
    assert r.status_code == 200, r.text

    r = await ist.post(f"{KIRALAMA}/{k['id']}/sevk", json={})
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["status"] == "SEVK_EDILDI"
    assert await cihaz_durumlari(db, urun) == {"KIRADA": 2, "HAZIR": 1}

    # Kurulum işi → tamamlanınca aşama önerisi → depo sorumlusu onaylar (TS-120).
    r = await ist.post(f"{KIRALAMA}/{k['id']}/servis-isi", json={"tur": "KURULUM"})
    assert r.status_code == 201, r.text
    kurulum_id = r.json()["id"]
    await _tamamla(db, client.clock, kurulum_id, "Kurulum yapıldı")
    kart = (await ist.get(f"{KIRALAMA}/{k['id']}")).json()
    assert kart["onerilen_asama"] == "KURULUM_YAPILDI"
    r = await depocu.post(
        f"{KIRALAMA}/{k['id']}/asama",
        json={"asama": "KURULUM_YAPILDI", "service_order_id": kurulum_id},
    )
    assert r.status_code == 200, r.text

    # Kurulumlu kiralamada son iade TOPLANDI ister (TS-113).
    iade = {
        "satirlar": [
            {"tahsis_id": t["id"], "sonuc": "IADE_ALINDI", "depo_id": depo.id}
            for t in k["tahsisler"]
        ]
    }
    r = await ist.post(f"{KIRALAMA}/{k['id']}/iade", json=iade)
    assert r.status_code == 409, r.text
    assert await cihaz_durumlari(db, urun) == {"KIRADA": 2, "HAZIR": 1}

    r = await ist.post(f"{KIRALAMA}/{k['id']}/servis-isi", json={"tur": "TOPLAMA"})
    assert r.status_code == 201, r.text
    toplama_id = r.json()["id"]
    await _tamamla(db, client.clock, toplama_id, "Toplandı")
    r = await depocu.post(
        f"{KIRALAMA}/{k['id']}/asama", json={"asama": "TOPLANDI", "service_order_id": toplama_id}
    )
    assert r.status_code == 200, r.text

    r = await ist.post(f"{KIRALAMA}/{k['id']}/iade", json=iade)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DEPOYA_ALINDI"
    assert await cihaz_durumlari(db, urun) == {"KONTROLDE": 2, "HAZIR": 1}

    r = await ist.post(
        f"{KIRALAMA}/envanter/kontrol",
        json={"satirlar": [{"kiralik_id": c, "sonuc": "UYGUN"} for c in cihazlar]},
    )
    assert r.status_code == 200, r.text
    assert await cihaz_durumlari(db, urun) == {"HAZIR": 3}
    r = await ist.post(f"{KIRALAMA}/{k['id']}/kapat")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "KAPANDI"
    # Kiralama mobilite hak ediş zincirine yazmaz.
    assert await db.scalar(select(func.count()).select_from(WorkOrder)) == 0


# --- 3. Kiralık cihaz → atölye köprüsü (TS-102) ---------------------------------------------


async def test_kiralik_arizali_donus_atolye_ve_depoya_kontrole_doner(
    client, db, kullanici_ac, birimli_kullanici_ac, oturumlar
) -> None:
    await kullanici_ac("uu_kopru_yon", "SERVIS_YONETICI")
    ist = await oturumlar("uu_kopru_yon")
    depo = await depo_ac(db, "UU-KOP-D1", birim="HABERLESME")
    kiraci = await musteri_ac(db, "Köprü Kiracısı A.Ş.")
    urun = await kiralik_urun_ac(db, "UU-KOP-TLS", seri=True, birim="HABERLESME")
    urun_db = await db.get(Product, urun.id)
    urun_db.brand = "HYTERA"
    await db.commit()
    await stok_gir(ist, urun, depo, seriler=["UU-KOP-1"])
    (cihaz_id,) = await seri_idleri(db, urun)

    k = await kiralama_ac(ist, kiraci, [(urun, 1)], birim="HABERLESME")
    await planla(ist, k)
    k = await tahsis(ist, k, [{"kalem_id": kalem_id(k, urun), "kiralik_idler": [cihaz_id]}])
    k = (await ist.post(f"{KIRALAMA}/{k['id']}/sevk", json={})).json()
    r = await ist.post(
        f"{KIRALAMA}/{k['id']}/iade",
        json={
            "satirlar": [
                {"tahsis_id": k["tahsisler"][0]["id"], "sonuc": "IADE_ALINDI", "depo_id": depo.id}
            ]
        },
    )
    assert r.status_code == 200, r.text

    r = await ist.post(
        f"{KIRALAMA}/envanter/kontrol",
        json={
            "satirlar": [
                {
                    "kiralik_id": cihaz_id,
                    "sonuc": "ARIZALI",
                    "aciklama": "Ekran yanmıyor",
                    "atolye_kaydi_ac": True,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    cihaz = await db.get(RentalAsset, cihaz_id, populate_existing=True)
    assert cihaz.durum == "ATOLYEDE" and cihaz.warehouse_id == depo.id
    kayit = await db.scalar(
        select(WorkshopRecord).where(WorkshopRecord.rental_asset_id == cihaz_id)
    )
    assert kayit is not None and kayit.service_type == "KIRALAMA_TAKIP"
    so = await db.get(ServiceOrder, kayit.service_order_id)
    assert so.customer_id == kiraci.id and so.birim == "HABERLESME" and so.tur == "ATOLYE"

    # Atölye akışı: teslimde cihaz son deposuna KONTROLDE döner (HAZIR yalnız kontrolle).
    await teslime_hazirla(ist, db, so.id)
    dd = await detay(ist, so.id)
    await gec(ist, so.id, "TESLIM_EDILDI", teslim=teslim_govdesi(dd), sure_eksik_onay=True)
    cihaz = await db.get(RentalAsset, cihaz_id, populate_existing=True)
    assert cihaz.durum == "KONTROLDE" and cihaz.warehouse_id == depo.id
    r = await ist.post(
        f"{KIRALAMA}/envanter/kontrol",
        json={"satirlar": [{"kiralik_id": cihaz_id, "sonuc": "UYGUN"}]},
    )
    assert r.status_code == 200, r.text
    assert (await db.get(RentalAsset, cihaz_id, populate_existing=True)).durum == "HAZIR"


async def test_kiralanmamis_cihaz_atolyeye_kopruyle_gitmez(client, db, kullanici_ac, oturumlar):
    await kullanici_ac("uu_kopru2", "SERVIS_YONETICI")
    ist = await oturumlar("uu_kopru2")
    depo = await depo_ac(db, "UU-KOP-D2", birim="HABERLESME")
    urun = await kiralik_urun_ac(db, "UU-KOP-YENI", seri=True, birim="HABERLESME")
    await stok_gir(ist, urun, depo, seriler=["UU-YENI-1"], durum="KONTROLDE")
    (cihaz_id,) = await seri_idleri(db, urun)
    r = await ist.post(
        f"{KIRALAMA}/envanter/kontrol",
        json={
            "satirlar": [
                {
                    "kiralik_id": cihaz_id,
                    "sonuc": "ARIZALI",
                    "aciklama": "Kutudan arızalı",
                    "atolye_kaydi_ac": True,
                }
            ]
        },
    )
    assert r.status_code == 409, r.text
    assert (await db.get(RentalAsset, cihaz_id, populate_existing=True)).durum == "KONTROLDE"
    assert await db.scalar(select(func.count()).select_from(WorkshopRecord)) == 0


# --- 4. Parça ------------------------------------------------------------------------------

PARCA = "/api/teknik-servis/parca"


async def test_servis_isine_parca_cikisi_stok_duser_negatif_409(
    client, db, birimli_kullanici_ac, kullanici_ac, servis_isi_ac, oturumlar
) -> None:
    from app.services.teknik_servis import parca as parca_svc

    await birimli_kullanici_ac("uu_depocu", "SERVIS_DEPO", ["GUVENLIK"])
    await birimli_kullanici_ac("uu_parca_sef", "SERVIS_SEF", ["GUVENLIK"])
    await kullanici_ac("uu_parca_admin", "ADMIN")
    depocu = await oturumlar("uu_depocu")
    sef_ist = await oturumlar("uu_parca_sef")
    admin = await oturumlar("uu_parca_admin")
    depo = Warehouse(code="UU-SRV", name="UU Servis Deposu", birim="GUVENLIK", servis_deposu=True)
    urun = Product(
        code="UU-YP-1",
        name="UU Yedek Parça",
        type="AKSESUAR",
        identity_kind="YOK",
        yedek_parca=True,
    )
    db.add_all([depo, urun])
    await db.commit()
    so = await servis_isi_ac(birim="GUVENLIK")

    r = await depocu.post(
        f"{PARCA}/giris",
        json={
            "depo_id": depo.id,
            "satirlar": [{"product_id": urun.id, "adet": 3, "unit_cost": "40"}],
        },
    )
    assert r.status_code == 201, r.text
    assert await parca_svc.bakiye(db, urun.id, depo.id) == 3

    def cikis(adet: int) -> dict:
        return {
            "service_order_id": so.id,
            "depo_id": depo.id,
            "satirlar": [{"product_id": urun.id, "adet": adet}],
        }

    r = await depocu.post(f"{PARCA}/cikis", json=cikis(2))
    assert r.status_code == 201, r.text
    assert await parca_svc.bakiye(db, urun.id, depo.id) == 1

    once = await db.scalar(select(func.count()).select_from(StockMovement))
    r = await depocu.post(f"{PARCA}/cikis", json=cikis(2))
    assert r.status_code == 409 and "Stok yetersiz" in r.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(StockMovement)) == once
    assert await parca_svc.bakiye(db, urun.id, depo.id) == 1

    # Maliyet anahtarları yalnız maliyet.gor sahibinde (TS-133, sees_cost).
    gizli = (await sef_ist.get(f"{PARCA}/isler/{so.id}/parcalar")).json()
    assert gizli["ozet"][0]["net"] == 2
    assert all("tutar" not in x and "unit_cost" not in x for x in gizli["ozet"])
    assert all("unit_cost" not in x and "tutar" not in x for x in gizli["hareketler"])
    acik = (await admin.get(f"{PARCA}/isler/{so.id}/parcalar")).json()
    assert acik["ozet"][0]["tutar"] == 80.0


# --- 5. Servis işinden teklif ----------------------------------------------------------------


async def test_servis_isinden_teklif_onay_kabul_gelir(
    client, db, birimli_kullanici_ac, servis_isi_ac, lokasyon_ac, oturumlar
) -> None:
    await birimli_kullanici_ac("uu_tkl_sef", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("uu_tkl_mudur", "SERVIS_YONETICI", ["GUVENLIK"])
    sef_ist = await oturumlar("uu_tkl_sef")
    mudur = await oturumlar("uu_tkl_mudur")
    hesap = await musteri(db, "Uçtan Uca Teklif Müşterisi")
    tesis = await lokasyon_ac(hesap)
    so = await servis_isi_ac(musteri=hesap, lokasyon=tesis, birim="GUVENLIK")

    t = await teklif_ac(sef_ist, hesap.id, birim=None, service_order_id=so.id)
    assert t["birim"] == "GUVENLIK" and t["address_id"] == tesis.id
    liste = (await sef_ist.get(f"/api/teklifler?servis_isi_id={so.id}")).json()
    kayitlar = liste["kayitlar"] if isinstance(liste, dict) and "kayitlar" in liste else liste
    assert [x["id"] for x in kayitlar] == [t["id"]]
    # Servis teklifi siparişe dönüşmez (TS-144).
    await onayli(sef_ist, mudur, t["id"])
    await elle_gonder(sef_ist, t["id"])
    r = await sef_ist.post(f"/api/teklifler/{t['id']}/karar", json={"kabul": True})
    assert r.status_code == 200 and r.json()["status"] == "KABUL"
    fin = await db.scalar(
        select(ServiceOrderFinancial).where(ServiceOrderFinancial.service_order_id == so.id)
    )
    assert fin is not None and fin.gelir_kaynagi == "TEKLIF" and fin.gelir is not None
    # Maliyet ekranı maliyet.gor ister: şefte 403, iş finansı sızmaz.
    r = await sef_ist.get(f"/api/teknik-servis/maliyet/isler/{so.id}")
    assert r.status_code == 403, r.text


# --- Görev panosu kayıt tipleri (TS-091, TS-110, TS-155, TS-165) ---------------------------


def test_dalga2_gorev_kayit_tipleri_kisisel_alan_tasimaz() -> None:
    """Görev uçları kayıt kapsamı uygulamaz: etiket yalnız belge numarasıdır;
    düzeltici faaliyet ve personel kartı kişi adı/notu taşımaz ("#id")."""
    from app.services import gorevler

    assert gorevler.tip("atolye").alanlar == ("atolye_no",)
    assert gorevler.tip("kiralama").alanlar == ("rental_no",)
    assert gorevler.tip("egitim_faaliyet").alanlar == ()
    assert gorevler.tip("personel").alanlar == ()
    assert gorevler.tip("kiralama").yol.format(id=7, etiket="") == "/kiralamalar/7"


async def test_teklif_sunulacak_uyarisi_teklif_acilinca_duser(
    client, db, kullanici_ac, servis_isi_ac, oturumlar
) -> None:
    """TS-147: TEKLIF beklemesindeki işe N iş günü içinde teklif açılmadıysa
    uyarı listesine düşer; iptal olmayan teklif açılınca düşer."""
    from datetime import timedelta

    from app.models import ServiceHold, User
    from app.services.teknik_servis import maliyet

    await kullanici_ac("uu_tkl_yon", "SERVIS_YONETICI")
    yon = await db.scalar(select(User).where(User.username == "uu_tkl_yon"))
    hesap = await musteri(db, "Teklif Bekleyen Müşteri")
    so = await servis_isi_ac(musteri=hesap, birim="GUVENLIK", durum="BEKLEMEDE")
    db.add(
        ServiceHold(
            service_order_id=so.id,
            neden="TEKLIF",
            onceki_durum="ISLEMDE",
            started_at=client.clock.now() - timedelta(days=10),
            sla_durdurur=True,
        )
    )
    await db.commit()
    assert so.id in await maliyet.teklif_sunulacak_isler(db, yon, client.clock)

    ist = await oturumlar("uu_tkl_yon")
    await teklif_ac(ist, hesap.id, birim=None, service_order_id=so.id)
    assert so.id not in await maliyet.teklif_sunulacak_isler(db, yon, client.clock)
