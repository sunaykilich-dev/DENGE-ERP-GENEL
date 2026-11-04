"""Rol testi düzeltmeleri — arka uç (KARARLAR 2026-11-04 §6).

Bulgu kaynakları `analiz/rol_testi/*.md`. Şirket ayrımına bağlı testler
`sirket_ayrimi` işaretlidir (şirket süzgeci ve mobilite kapısı GERÇEK çalışır);
diğerleri varsayılan (süzgeçsiz) test kipinde.
"""

from datetime import timedelta

import pytest
from planlama_yardim import ortam_fixture, plan_govdesi  # noqa: F401
from servis_yardimci import acilis, giris, musteri, teknisyen
from sqlalchemy import select

from app.models import (
    Address,
    AuditLog,
    Board,
    Card,
    KullaniciSirketi,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceVehicle,
)
from app.permissions import permissions_of
from app.services.teknik_servis import ana_veri

pytestmark = pytest.mark.integration
sirketli = pytest.mark.sirket_ayrimi

GOREV = "/api/gorevler"
TS = "/api/teknik-servis"
PLAN = f"{TS}/planlama"


@pytest.fixture
def uyelik_ver(db):
    async def _ver(user, *kodlar: str) -> None:
        for kod in kodlar:
            db.add(KullaniciSirketi(user_id=user.id, sirket_kod=kod))
        await db.commit()

    return _ver


# --- 6.1 Görev panosu (S1) ---------------------------------------------------------------


@sirketli
async def test_gorev_panosu_sirkete_bagli_ve_bagli_kayit_kapsamli(
    client, db, kullanici_ac, uyelik_ver, servis_isi_ac, sozlesme_ac, cihaz_ac
) -> None:
    tel = await kullanici_ac("g_tel", "SERVIS_YONETICI")
    await uyelik_ver(tel, "TELEKOM")
    elk = await kullanici_ac("g_elk", "SERVIS_YONETICI")
    await uyelik_ver(elk, "ELEKTRONIK")
    is_tel = await servis_isi_ac(birim="HABERLESME")
    is_elk = await servis_isi_ac(birim="GUVENLIK")
    tel_id, tel_no, elk_id, elk_no = is_tel.id, is_tel.so_no, is_elk.id, is_elk.so_no
    soz = await sozlesme_ac(birim="GUVENLIK")
    soz_id, soz_no = soz.id, soz.contract_no
    cihaz = await cihaz_ac(imei="356000000000017")
    cihaz_id = cihaz.id

    await giris(client, "g_tel")
    r = await client.post(f"{GOREV}/panolar", json={"title": "Telekom panosu"})
    assert r.status_code == 201, r.text
    pano = r.json()
    kolon = pano["kolonlar"][0]["id"]
    assert (await db.get(Board, pano["id"])).sirket_kod == "TELEKOM"

    def kart(**kw):
        return client.post(
            f"{GOREV}/panolar/{pano['id']}/kartlar",
            json={"column_id": kolon, "title": "Kart", **kw},
        )

    # Başka şirketin işi / sözleşmesi ve mobilite cihazı karta bağlanamaz (404, numara yok).
    for entity, kimlik in (
        ("servis_isi", elk_id),
        ("bakim_sozlesme", soz_id),
        ("cihaz", cihaz_id),
        ("servis_isi", 999_999),
    ):
        r = await kart(entity=entity, entity_id=kimlik)
        assert r.status_code == 404, (entity, r.text)
        assert elk_no not in r.text and str(soz_no) not in r.text

    # Kendi şirketinin işi bağlanır; etiket iş no.
    r = await kart(entity="servis_isi", entity_id=tel_id)
    assert r.status_code == 201, r.text
    assert r.json()["baglanti"]["etiket"] == tel_no
    kart_id = r.json()["id"]

    # Eskiden (düzeltme öncesi) bağlanmış başka şirket işi: etiket "erişim yok".
    db.add(
        Card(
            board_id=pano["id"],
            column_id=kolon,
            title="eski bağlantı",
            sira=9,
            entity="servis_isi",
            entity_id=elk_id,
        )
    )
    await db.commit()
    r = await client.get(f"{GOREV}/panolar/{pano['id']}/kartlar")
    assert r.status_code == 200
    eski = next(k for k in r.json() if k["title"] == "eski bağlantı")
    assert eski["baglanti"]["etiket"] == "erişim yok"
    assert eski["baglanti"]["yol"] == "" and eski["baglanti"]["var"] is False
    assert elk_no not in r.text
    # Göremediği kaydın kart paneli 404.
    assert (await client.get(f"{GOREV}/kayit/servis_isi/{elk_id}")).status_code == 404

    # ELEKTRONİK kullanıcısı TELEKOM panosunu ve kartlarını göremez.
    await giris(client, "g_elk")
    r = await client.get(f"{GOREV}/panolar")
    assert r.status_code == 200
    assert pano["id"] not in [p["id"] for p in r.json()]
    assert (await client.get(f"{GOREV}/panolar/{pano['id']}/kartlar")).status_code == 404
    assert (await client.get(f"{GOREV}/kartlar/{kart_id}/yorumlar")).status_code == 404
    assert (
        await client.patch(f"{GOREV}/kartlar/{kart_id}", json={"title": "ele geçir"})
    ).status_code == 404
    assert (
        await client.post(f"{GOREV}/kolonlar/{kolon}/kartlar", json={"title": "x"})
    ).status_code in (404, 405)
    assert (await client.patch(f"{GOREV}/kolonlar/{kolon}", json={"title": "x"})).status_code == 404
    assert (await client.get(f"{GOREV}/kayit/servis_isi/{tel_id}")).status_code == 404


async def test_gorev_karti_yetkisiz_kayit_tipine_baglanamaz(client, kullanici_ac) -> None:
    """Okuma izni olmayan kayıt tipine (operasyonda `bakim.gor` yok) bağlantı 404."""
    await kullanici_ac("g_ops", "SERVIS_OPERASYON")
    await giris(client, "g_ops")
    pano = (await client.post(f"{GOREV}/panolar", json={"title": "Ops panosu"})).json()
    r = await client.post(
        f"{GOREV}/panolar/{pano['id']}/kartlar",
        json={
            "column_id": pano["kolonlar"][0]["id"],
            "title": "x",
            "entity": "bakim_sozlesme",
            "entity_id": 1,
        },
    )
    assert r.status_code == 404


# --- 6.2 Mobilite dışa aktarma (S2) -------------------------------------------------------


async def test_mobilite_disa_aktarma_goruntuleme_izni_ister(client, kullanici_ac) -> None:
    assert "rapor.disaaktar" in permissions_of("DEPO")
    assert "hakedis.gor" not in permissions_of("DEPO")
    await kullanici_ac("m_depo", "DEPO")
    await giris(client, "m_depo")
    for yol in (
        "/api/hakedis/donem/2026-11/excel",
        "/api/abonelikler/tahakkuk/2026-11/xlsx",
        "/api/raporlar/mrr/2026-11",
    ):
        r = await client.get(yol)
        assert r.status_code == 403, (yol, r.text)

    await kullanici_ac("m_fin", "FINANS_YONETICI")
    await giris(client, "m_fin")
    for yol in (
        "/api/hakedis/donem/2026-11/excel",
        "/api/abonelikler/tahakkuk/2026-11/xlsx",
        "/api/raporlar/mrr/2026-11",
    ):
        r = await client.get(yol)
        assert r.status_code == 200, (yol, r.text)


# --- 6.3 Personel (S3) --------------------------------------------------------------------


@sirketli
async def test_birimsiz_personel_yalniz_uye_oldugu_sirkette(
    client, kullanici_ac, uyelik_ver
) -> None:
    yon = await kullanici_ac("p_yon", "SERVIS_YONETICI")
    await uyelik_ver(yon, "TELEKOM")
    mob = await kullanici_ac("p_mobdepo", "DEPO")
    await uyelik_ver(mob, "MOBILITE")
    tel = await kullanici_ac("p_telsatis", "SATIS")
    await uyelik_ver(tel, "TELEKOM")
    await giris(client, "p_yon")
    r = await client.get("/api/personel", params={"limit": 200})
    assert r.status_code == 200, r.text
    kimlikler = {k["id"] for k in r.json()}
    assert tel.id in kimlikler
    assert mob.id not in kimlikler
    assert (await client.get(f"/api/personel/{mob.id}")).status_code == 404


# --- 6.4 Planlama kontrolü ve tayin mesajı (B3) ---------------------------------------------


@sirketli
async def test_kontrol_ve_tayin_baska_sirketi_sizdirmaz(
    client, db, kullanici_ac, birimli_kullanici_ac, uyelik_ver, servis_isi_ac
) -> None:
    yon = await kullanici_ac("k_yon", "SERVIS_YONETICI")
    await uyelik_ver(yon, "TELEKOM")
    guv = await teknisyen(birimli_kullanici_ac, "k_tek_guv", ("GUVENLIK",))
    await uyelik_ver(guv, "ELEKTRONIK")
    guv_id, guv_ad = guv.id, guv.full_name
    arac = ServiceVehicle(plate="34 KON 01", plate_key="34KON01", birim="GUVENLIK")
    db.add(arac)
    await db.commit()
    is_tel = await servis_isi_ac(birim="HABERLESME")
    tel_id = is_tel.id

    await giris(client, "k_yon")
    govde = {"plan_tarihi": "2026-01-15", "baslangic_saati": "10:00", "sure_dk": 60}
    r = await client.post(f"{PLAN}/kontrol", json={**govde, "kisi_idler": [guv_id]})
    assert r.status_code == 404
    assert guv_ad not in r.text
    r = await client.post(f"{PLAN}/kontrol", json={**govde, "arac_id": arac.id})
    assert r.status_code == 404

    r = await client.put(
        f"{PLAN}/isler/{tel_id}/plan",
        json=plan_govdesi(ekip={"teknisyen_idler": [guv_id]}),
    )
    assert r.status_code == 400, r.text
    assert "Kullanıcı bulunamadı" in r.text
    assert guv_ad not in r.text


# --- 6.5 Rol yetkileri ---------------------------------------------------------------------


async def test_satis_destek_kurulum_takibi_ve_musteri_karti(
    client, db, birimli_kullanici_ac
) -> None:
    izinler = set(permissions_of("SATIS_DESTEK"))
    assert {"ekipman.yaz", "lokasyon.yaz", "servis.kurulum_ac", "hesap.kart_yaz"} <= izinler
    assert "servis.yaz" not in izinler
    await birimli_kullanici_ac("sd_guv", "SATIS_DESTEK", ["GUVENLIK"])
    await giris(client, "sd_guv")

    r = await client.post(
        f"{TS}/ana-veri/hizli-musteri", json={"unvan": "Satış Müşterisi Ltd", "il": "Ankara"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["hesap"]["dogrulandi"] is False

    hesap = await musteri(db, "Kurulum Müşterisi A.Ş.")
    r = await client.post(f"{TS}/isler", json=acilis(hesap, tur="KURULUM", konu="X-Ray kurulumu"))
    assert r.status_code == 201, r.text
    r = await client.post(f"{TS}/isler", json=acilis(hesap, tur="ARIZA"))
    assert r.status_code == 403
    assert "Kurulum" in r.text


async def test_operasyon_musteri_tesis_ve_atolye_kabulu(client, db, birimli_kullanici_ac) -> None:
    izinler = set(permissions_of("SERVIS_OPERASYON"))
    assert {"hesap.kart_yaz", "atolye.kabul", "atolye.gor"} <= izinler
    assert "atolye.yaz" not in izinler
    await birimli_kullanici_ac("op_guv", "SERVIS_OPERASYON", ["GUVENLIK"])
    await teknisyen(birimli_kullanici_ac, "op_tek")
    await giris(client, "op_guv")

    r = await client.post(
        f"{TS}/ana-veri/hizli-musteri", json={"unvan": "Halkbank Genel", "il": "İstanbul"}
    )
    assert r.status_code == 201, r.text
    hesap_id = r.json()["hesap"]["id"]
    # Benzer kayıt uyarısı korunur (onaysız 409, adaylarla).
    r = await client.post(
        f"{TS}/ana-veri/hizli-musteri", json={"unvan": "Halkbank Genel A.Ş.", "il": "İstanbul"}
    )
    assert r.status_code == 409, r.text

    # Operasyonun açtığı tesis doğrulanmamış doğar.
    r = await client.post(
        "/api/lokasyonlar",
        json={
            "hesap_id": hesap_id,
            "kind": "TESIS",
            "site_name": "Kadıköy Şube",
            "city": "İstanbul",
        },
    )
    assert r.status_code == 201, r.text
    tesis = await db.get(Address, r.json()["id"])
    assert tesis.is_verified is False

    # Atölye kabulü: yetki kapısından geçer (boş gövde → 422, 403 değil).
    assert (await client.post(f"{TS}/atolye", json={})).status_code == 422
    assert (await client.post(f"{TS}/atolye/toplu-kabul", json={})).status_code == 422
    await giris(client, "op_tek")
    assert (await client.post(f"{TS}/atolye", json={})).status_code == 403


# --- 6.6 Şef sorumlu, "tayin edilmemiş" tek tanım (B1) -------------------------------------


async def test_sefin_sahaya_gittigi_plan_tayinli_sayilir(ortam, db, servis_isi_ac) -> None:
    sef = ortam.kisi("sef_g")
    sefli = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    tayinsiz = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sefli_id, tayinsiz_id = sefli.id, tayinsiz.id
    ist = await ortam.ist("sef_g")
    r = await ist.put(
        f"{PLAN}/isler/{sefli_id}/plan",
        json=plan_govdesi(ekip={"sef_idler": [sef.id], "sahaya_giden_sefler": [sef.id]}),
    )
    assert r.status_code == 200, r.text
    tayin = await db.scalar(
        select(ServiceOrderAssignment).where(
            ServiceOrderAssignment.service_order_id == sefli_id,
            ServiceOrderAssignment.removed_at.is_(None),
        )
    )
    assert (tayin.rol, tayin.is_lead) == ("SEF", True)

    async def kimlikler(**params) -> tuple[set[int], int]:
        r = await ist.get(f"{TS}/isler", params={"limit": 200, **params})
        assert r.status_code == 200, r.text
        govde = r.json()
        satirlar = govde if isinstance(govde, list) else govde.get("satirlar", [])
        return {s["id"] for s in satirlar}, int(r.headers["X-Toplam-Kayit"])

    liste, toplam = await kimlikler(atanmamis="true")
    assert sefli_id not in liste and tayinsiz_id in liste
    kpi, kpi_toplam = await kimlikler(kpi="atanmamis")
    assert kpi == liste and kpi_toplam == toplam  # sayı = liste, aynı tanım


async def test_sef_sorumlu_tayin_edilebilir(ortam, servis_isi_ac) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    yon = await ortam.ist("yonetici")
    r = await yon.put(
        f"{TS}/isler/{so.id}/atama",
        json={"atamalar": [{"user_id": ortam.kisi("sef_g").id, "rol": "SEF", "is_lead": True}]},
    )
    assert r.status_code == 200, r.text


# --- 6.7 Kaynak görünümü (B2) ---------------------------------------------------------------


async def test_kaynak_gorunumu_ziyaret_suresini_bir_kez_sayar(ortam, servis_isi_ac) -> None:
    isler = [await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon) for _ in range(3)]
    tek = ortam.kisi("tek1")
    ist = await ortam.ist("sef_g")
    r = await ist.post(
        f"{PLAN}/toplu-plan",
        json=plan_govdesi(
            sure=300, is_idler=[s.id for s in isler], ekip={"teknisyen_idler": [tek.id]}
        ),
    )
    assert r.status_code == 201, r.text
    r = await ist.get(f"{PLAN}/kaynak-gorunumu", params={"hafta": "2026-01-15"})
    assert r.status_code == 200, r.text
    satir = next(s for s in r.json()["satirlar"] if s["user_id"] == tek.id)
    hucre = next(h for h in satir["hucreler"] if h["gun"] == "2026-01-15")
    assert hucre["plan_dk"] == 300
    assert hucre["is_sayisi"] == 3 and hucre["ziyaret_sayisi"] == 1
    assert satir["toplam_plan_dk"] == 300


# --- 6.8 Şef tayin yetkisi (B4) — daraltılmadı ----------------------------------------------


def test_sef_planlama_yetkisi_korundu() -> None:
    """KARARLAR §6.8: lab şefi ve Set Bariyer şefi plan yapar; saha takım lideri
    kişiye özel istisnayla kapatılır (rol daraltılmadı)."""
    assert "servis.planla" in permissions_of("SERVIS_SEF")


# --- 6.9 Planlama doğrulamaları (B6, B7) ----------------------------------------------------


async def test_gecmis_tarihe_plan_gerekce_ister(ortam, db, servis_isi_ac) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    so_id = so.id
    ist = await ortam.ist("sef_g")
    ekip = {"teknisyen_idler": [ortam.kisi("tek1").id]}
    # FakeClock 2026-01-01: 20 Aralık geçmiştir.
    r = await ist.put(
        f"{PLAN}/isler/{so_id}/plan", json=plan_govdesi(tarih="2025-12-20", ekip=ekip)
    )
    assert r.status_code == 409, r.text
    assert r.json()["kod"] == "GECMIS_TARIH"
    r = await ist.put(
        f"{PLAN}/isler/{so_id}/plan",
        json=plan_govdesi(tarih="2025-12-20", ekip=ekip, gecmis_tarih_gerekcesi="kısa"),
    )
    assert r.status_code == 409
    r = await ist.put(
        f"{PLAN}/isler/{so_id}/plan",
        json=plan_govdesi(
            tarih="2025-12-20", ekip=ekip, gecmis_tarih_gerekcesi="Talep listesinden geçiş kaydı"
        ),
    )
    assert r.status_code == 200, r.text
    iz = await db.scalar(
        select(AuditLog).where(AuditLog.entity == "service_plans", AuditLog.action == "planla")
    )
    assert iz.new_value["gecmis_tarih_gerekcesi"] == "Talep listesinden geçiş kaydı"


async def test_sahada_kimsesiz_tekli_plan_reddedilir(ortam, servis_isi_ac) -> None:
    so = await servis_isi_ac(musteri=ortam.musteri, lokasyon=ortam.lokasyon)
    sef = ortam.kisi("sef_g")
    ist = await ortam.ist("sef_g")
    r = await ist.put(f"{PLAN}/isler/{so.id}/plan", json=plan_govdesi(ekip={}))
    assert r.status_code == 400, r.text
    # Yalnız sahaya gitmeyen şef de "sahada kimse yok".
    r = await ist.put(f"{PLAN}/isler/{so.id}/plan", json=plan_govdesi(ekip={"sef_idler": [sef.id]}))
    assert r.status_code == 400, r.text
    assert "Sahada kimse yok" in r.text


# --- 6.10 Veri kalitesi (B6, B9) --------------------------------------------------------------


async def test_seri_eksik_tek_cihazli_isleri_sayar_ve_lokasyon_uyarisi_tek(
    client, db, kullanici_ac
) -> None:
    await kullanici_ac("vk_yon", "SERVIS_YONETICI")
    await giris(client, "vk_yon")
    hesap = await musteri(db, "Kalite Müşterisi A.Ş.")
    for _ in range(3):
        r = await client.post(f"{TS}/isler", json=acilis(hesap, tur="PLANSIZ_BAKIM"))
        assert r.status_code == 201, r.text
    ayni = [u for u in r.json()["uyarilar"] if u["kod"] == "AYNI_LOKASYON"]
    assert len(ayni) == 1
    assert ayni[0]["adet"] == 2 and len(ayni[0]["isler"]) == 2

    r = await client.get(f"{TS}/ana-veri/veri-kalitesi")
    assert r.status_code == 200, r.text
    kodlar = {k["kod"]: k for k in r.json()["kontroller"]}
    assert kodlar["seri_eksik"]["deger"] == 3
    # Seri girilen iş sayılmaz.
    r = await client.post(f"{TS}/isler", json=acilis(hesap, seriler=["SN-1"], mukerrer_gec=True))
    assert r.status_code == 201, r.text
    r = await client.get(f"{TS}/ana-veri/veri-kalitesi")
    assert {k["kod"]: k for k in r.json()["kontroller"]}["seri_eksik"]["deger"] == 3


# --- 6.11 Geçiş kaydı ve yurt dışı il (B5, B14) -----------------------------------------------


async def test_gecis_kaydi_eski_bildirim_tarihini_kabul_eder(
    client, db, kullanici_ac, birimli_kullanici_ac
) -> None:
    await kullanici_ac("gc_yon", "SERVIS_YONETICI")
    await birimli_kullanici_ac("gc_ops", "SERVIS_OPERASYON", ["GUVENLIK"])
    hesap = await musteri(db, "Geçiş Müşterisi A.Ş.")
    eski = (client.clock.now() - timedelta(days=20)).isoformat()

    await giris(client, "gc_yon")
    r = await client.post(f"{TS}/isler", json=acilis(hesap, reported_at=eski))
    assert r.status_code == 400  # normal girişte 7 gün kuralı
    r = await client.post(
        f"{TS}/isler", json=acilis(hesap, reported_at=eski, gecis_kaydi=True, gecis_gerekcesi="x")
    )
    assert r.status_code == 400  # gerekçe kısa
    r = await client.post(
        f"{TS}/isler",
        json=acilis(
            hesap,
            reported_at=eski,
            gecis_kaydi=True,
            gecis_gerekcesi="Güvenlik talep listesi aktarımı",
        ),
    )
    assert r.status_code == 201, r.text
    so = await db.get(ServiceOrder, r.json()["id"])
    await db.refresh(so)
    assert so.sla_kaynak == "GECIS"
    assert so.cozum_hedef_at is None

    await giris(client, "gc_ops")
    r = await client.post(
        f"{TS}/isler",
        json=acilis(
            hesap, reported_at=eski, gecis_kaydi=True, gecis_gerekcesi="Talep listesi aktarımı"
        ),
    )
    assert r.status_code == 403


def test_yurt_disi_il_kabul_edilir() -> None:
    assert ana_veri.il_dogrula("Yurt dışı") == "Yurt dışı"
    assert ana_veri.il_dogrula("YURTDIŞI - Nijerya") == "Yurt dışı (Nijerya)"
    assert ana_veri.il_dogrula("Kıbrıs") == "Yurt dışı (KKTC)"
    assert ana_veri.il_dogrula("istanbul") == "İstanbul"
    with pytest.raises(ana_veri.AnaVeriHatasi):
        ana_veri.il_dogrula("Atlantis")


# --- 6.12 Servis Maliyet sözlükleri (B-07) ----------------------------------------------------


async def test_finans_uzmani_servis_sozluklerini_okur(client, kullanici_ac) -> None:
    await kullanici_ac("f_uzm", "MUHASEBE_DESTEK")
    await giris(client, "f_uzm")
    r = await client.get(f"{TS}/isler/form-verileri")
    assert r.status_code == 200, r.text
    assert r.json()["turler"]
    # Kayıt uçları hâlâ kapalı.
    assert (await client.get(f"{TS}/isler")).status_code == 403
