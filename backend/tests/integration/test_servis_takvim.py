"""Takvim, havuz, KPI, irtibat gizliliği, Excel, uyarı ve KVKK (TS-042, TS-049).

Kabul: tarih aralıklı yükleme (≤62 gün, 63 → 400); havuz `lokasyon_anahtari`
ve il/ilçe ile gruplanır; KPI sayısı = liste (`X-Toplam-Kayit`); birim
kapsamı ve KENDI_ISLERI; kapalı işin planı soluk bayrakla döner; irtibat
alanları izinsizde null; Excel `?baslangic=` boşta 200 ve satır = takvim;
uyarı birim + KENDI_ISLERI kapsamlı; anonimleştirme plan metinlerini temizler.
"""

import io

import pytest
from openpyxl import load_workbook
from planlama_yardim import ortam_fixture, plan_govdesi  # noqa: F401
from sqlalchemy import select

from app.models import Contact, ServicePlan, ServiceVisit
from app.services import kvkk
from app.services.teknik_servis import planlama, takvim
from app.services.teknik_servis import uyarilar as ts_uyarilar

pytestmark = pytest.mark.integration

ON = "/api/teknik-servis/planlama"


async def _planla(ist, so_id, **kw):
    r = await ist.put(f"{ON}/isler/{so_id}/plan", json=plan_govdesi(**kw))
    assert r.status_code == 200, r.text
    return r.json()["plan"]["id"]


async def test_aralik_siniri_ve_birim_kapsami(ortam, servis_isi_ac) -> None:
    guv = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    hab = await servis_isi_ac(birim="HABERLESME")
    await _planla(await ortam.ist("sef_g"), guv.id)
    await _planla(await ortam.ist("sef_h"), hab.id)
    sef = await ortam.ist("sef_g")
    r = await sef.get(f"{ON}/takvim", params={"baslangic": "2026-01-01", "bitis": "2026-03-04"})
    assert r.status_code == 400  # 63 gün
    r = await sef.get(f"{ON}/takvim", params={"baslangic": "2026-01-01", "bitis": "2026-03-03"})
    assert r.status_code == 200
    assert [s["is_id"] for s in r.json()] == [guv.id]
    yon = await ortam.ist("yonetici")
    r = await yon.get(f"{ON}/takvim", params={"baslangic": "2026-01-15", "bitis": "2026-01-15"})
    assert {s["is_id"] for s in r.json()} == {guv.id, hab.id}


async def test_teknisyen_yalniz_kendi_islerini_gorur(ortam, servis_isi_ac) -> None:
    benim = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    baskasi = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = await ortam.ist("sef_g")
    await _planla(sef, benim.id, ekip={"teknisyen_idler": [ortam.kisi("tek1").id]})
    await _planla(sef, baskasi.id, ekip={"teknisyen_idler": [ortam.kisi("tek2").id]})
    tek = await ortam.ist("tek1")
    r = await tek.get(f"{ON}/takvim", params={"baslangic": "2026-01-15", "bitis": "2026-01-15"})
    assert [s["is_id"] for s in r.json()] == [benim.id]
    # Ekibinde olduğu işte irtibatı izinden bağımsız görür (anahtar var).
    assert "irtibat_telefon" in r.json()[0]
    r = await tek.get(f"{ON}/kpi", params={"gun": "2026-01-15"})
    kutular = {k["kod"]: k["deger"] for k in r.json()}
    assert kutular["bugun_planli"] == 1


async def test_kapali_isin_plani_soluk_bayrakla_doner(ortam, servis_isi_ac, db) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = await ortam.ist("sef_g")
    await _planla(sef, so.id)
    await db.refresh(so)
    so.status = "TAMAMLANDI"  # ORM ile kurulum: kapanış akışı D1-B'nin konusu
    await db.commit()
    r = await sef.get(f"{ON}/takvim", params={"baslangic": "2026-01-15", "bitis": "2026-01-15"})
    assert r.json()[0]["kapali"] is True
    r = await sef.get(f"{ON}/kpi", params={"gun": "2026-01-15"})
    kutular = {k["kod"]: k["deger"] for k in r.json()}
    assert kutular["bugun_planli"] == 0 and kutular["bugun_tamamlanan"] == 1


async def test_kpi_sayisi_liste_toplamina_esit(ortam, servis_isi_ac) -> None:
    sef = await ortam.ist("sef_g")
    t1, t2 = ortam.kisi("tek1").id, ortam.kisi("tek2").id
    a = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    b = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    c = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)  # havuzda
    await _planla(sef, a.id, ekip={"teknisyen_idler": [t1]})
    r = await sef.put(
        f"{ON}/isler/{b.id}/plan",
        json=plan_govdesi(
            ekip={"teknisyen_idler": [t1]}, cakisma_gerekcesi="Bilerek çakıştırıldı (test)"
        ),
    )
    assert r.status_code == 200, r.text
    await _planla(sef, c.id, saat=None, ekip={"teknisyen_idler": [t2]})
    r = await sef.get(f"{ON}/kpi", params={"gun": "2026-01-15"})
    kutular = {k["kod"]: k["deger"] for k in r.json()}
    assert kutular["cakismali"] == 2 and kutular["saat_belirsiz"] == 1
    assert kutular["havuz"] == 1 and kutular["bugun_planli"] == 3
    for kod, deger in kutular.items():
        r = await sef.get(f"{ON}/kpi-liste", params={"kod": kod, "gun": "2026-01-15"})
        assert r.status_code == 200, (kod, r.text)
        assert int(r.headers["X-Toplam-Kayit"]) == deger == len(r.json()), kod
    r = await sef.get(f"{ON}/kpi-liste", params={"kod": "yok"})
    assert r.status_code == 400


async def test_havuz_lokasyon_ve_sehir_gruplamasi(ortam, servis_isi_ac, lokasyon_ac) -> None:
    a = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    b = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sehirsiz = await servis_isi_ac(musteri=ortam.musteri)
    diger = await servis_isi_ac(
        musteri=ortam.musteri,
        lokasyon=await lokasyon_ac(ortam.musteri, ad="Kadıköy Şube", district="Kadıköy"),
    )
    sef = await ortam.ist("sef_g")
    r = await sef.get(f"{ON}/havuz")
    assert r.status_code == 200 and r.headers["X-Toplam-Kayit"] == "4"
    grup = {s["is_id"]: s["grup_anahtari"] for s in r.json()}
    assert grup[a.id] == grup[b.id] != grup[diger.id]
    r = await sef.get(f"{ON}/havuz", params={"gruplama": "sehir"})
    etiket = {s["is_id"]: s["grup_etiketi"] for s in r.json()}
    assert etiket[sehirsiz.id] == "Şehir girilmemiş"
    assert etiket[a.id] == "İstanbul / Üsküdar" and etiket[diger.id] == "İstanbul / Kadıköy"
    r = await sef.get(f"{ON}/havuz", params={"q": a.so_no})
    assert [s["is_id"] for s in r.json()] == [a.id]
    r = await sef.get(f"{ON}/havuz", params={"gruplama": "yanlis"})
    assert r.status_code == 400


async def test_irtibat_alanlari_izinsizde_null(ortam, servis_isi_ac, db) -> None:
    kisi = Contact(account_id=ortam.musteri.id, full_name="Saha Kişisi", phone="+905321234567")
    db.add(kisi)
    await db.commit()
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon, contact_id=kisi.id)
    await _planla(await ortam.ist("sef_g"), so.id)
    params = {"baslangic": "2026-01-15", "bitis": "2026-01-15"}
    yonetim = await ortam.ist("yonetim")  # servis.gor var, servis.irtibat_gor yok
    satir = (await yonetim.get(f"{ON}/takvim", params=params)).json()[0]
    assert satir["irtibat_adi"] is None and satir["irtibat_telefon"] is None
    assert satir["acik_adres"] is None and satir["il"] == "İstanbul"
    sef = await ortam.ist("sef_g")
    satir = (await sef.get(f"{ON}/takvim", params=params)).json()[0]
    assert satir["irtibat_adi"] == "Saha Kişisi" and satir["irtibat_telefon"] == "+905321234567"


async def test_excel_bos_tarihte_200_satir_takvime_esit_ve_rbac(ortam, servis_isi_ac) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = await ortam.ist("sef_g")
    await _planla(sef, so.id, tarih="2026-01-02")
    r = await sef.get(f"{ON}/takvim.xlsx?baslangic=&bitis=")
    assert r.status_code == 200, r.text
    takvim_satirlari = (
        await sef.get(f"{ON}/takvim", params={"baslangic": "2026-01-01", "bitis": "2026-01-07"})
    ).json()
    sayfa = load_workbook(io.BytesIO(r.content)).active
    assert sayfa.max_row - 1 == len(takvim_satirlari) == 1
    basliklar = [h.value for h in sayfa[1]]
    assert "Planlanan süre (dk)" in basliklar and "Telefon" in basliklar  # şef irtibat görür
    r = await sef.get(f"{ON}/takvim.xlsx", params={"baslangic": "2026-01-01"})
    assert r.status_code == 200
    op = await ortam.ist("operasyon")  # servis_rapor.disaaktar yok
    r = await op.get(f"{ON}/takvim.xlsx")
    assert r.status_code == 403
    yon = await ortam.ist("yonetici")
    r = await yon.get(
        f"{ON}/takvim.xlsx", params={"baslangic": "2026-01-02", "bitis": "2026-01-02"}
    )
    assert r.status_code == 200


async def test_uyarilar_birim_kapsamli(ortam, servis_isi_ac, db, client) -> None:
    from app.models import User

    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    await _planla(await ortam.ist("sef_g"), so.id, tarih="2026-01-02")  # yarın
    for ad, beklenen in (("sef_g", 1), ("sef_h", 0)):
        kisi = await db.scalar(select(User).where(User.username == ad))
        uyarilar = await takvim.planlama_uyarilari(db, kisi, client.clock)
        yarin = next(u for u in uyarilar if u.kod == "servis.yarin_plan")
        assert yarin.adet == beklenen, ad
    assert any(f is takvim.planlama_uyarilari for _, f in ts_uyarilar.kayitlar()["planlama"])


async def test_kvkk_anonimlestirme_plan_metinlerini_temizler(
    ortam, servis_isi_ac, db, client
) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    plan_id = await _planla(
        await ortam.ist("sef_g"),
        so.id,
        saha_notu="Kapıda Ahmet Bey'i arayın",
        saha_bolgesi="Ahmet Bey'in ofisi",
        plan_notu="Not",
    )
    db.add(
        ServiceVisit(
            visit_no="ZYR-202601-999999",
            birim="GUVENLIK",
            customer_id=ortam.musteri.id,
            notes="Ahmet Bey",
        )
    )
    await db.commit()
    assert planlama._plan_metinlerini_anonimlestir in kvkk.ANONIMLESTIRME_KANCALARI
    sonuc = await planlama._plan_metinlerini_anonimlestir(db, ortam.musteri.id, client.clock)
    await db.commit()
    assert sonuc["servis_plan_notu"] == 1 and sonuc["servis_ziyaret_notu"] == 1
    plan = await db.get(ServicePlan, plan_id)
    await db.refresh(plan)
    assert plan.site_note is None and plan.site_area is None and plan.plan_note is None
