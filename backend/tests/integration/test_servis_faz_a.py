"""Faz A servis işi kuralları (KARARLAR_2026-10-28 §7 madde 2, 6, 7; e1a000000001).

- M1.6: günlük servis işinde (arıza/destek/plansız bakım) en çok bir cihaz;
  proje türleri (keşif/kurulum) cihazsız ya da çok cihazlı olabilir; eski çok
  cihazlı kayıtlar okunur kalır.
- M1.7: kapanmış iş yeniden açılmaz; bağlı yeni iş açılır, bağ iki yönlü görünür.
- M1.2: ekrandan açılışta talep eden kişi + telefon, müşteri + lokasyon, arıza
  tanımı zorunlu; sistem açılışları muaf.
- D3.4 + G4.6: kalite onayı (görevler ayrılığı: işte çalışan onaylayamaz).
- G7.8: iş başlat/bitir konumu; alınamazsa "Konum bilgisi alınamadı".
- M1.10 / M9.4: süre kaydı olmadan kapanış uyarıyla serbest, iş "süre eksik".
"""

from datetime import timedelta

import pytest
from servis_yardimci import giris, olay_sayisi, tazele, teknisyen
from sqlalchemy import select

from app.clock import FakeClock
from app.models import Contact, ServiceOrder, ServiceOrderEvent, ServiceOrderSerial
from app.permissions import permissions_of
from app.services.statemachine import SERVIS_IS_EMRI, IzinsizGecis
from app.services.teknik_servis import is_emirleri
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

pytestmark = pytest.mark.integration

IS = "/api/teknik-servis/isler"
TS = "/api/teknik-servis"
SONUC = {
    "sonuc": "COZULDU",
    "cozum_kanali": "YERINDE",
    "yapilan_islem": "Kablo yenilendi",
    "sure_eksik_onay": True,
}


def _govde(hesap_id: int, lokasyon_id: int | None, **kw) -> dict:
    govde = {
        "birim": "GUVENLIK",
        "tur": "ARIZA",
        "konu": "Kamera görüntü vermiyor",
        "customer_id": hesap_id,
        "address_id": lokasyon_id,
        "talep_kanali": "TELEFON",
        "iletisim_ad": "Saha Yetkilisi",
        "iletisim_telefon": "+905321112233",
    }
    govde.update(kw)
    return govde


async def _seri_ekle(db, so: ServiceOrder, *seriler: str) -> None:
    from app.services.normalize import normalize_seri

    for s in seriler:
        db.add(ServiceOrderSerial(service_order_id=so.id, seri_no=s, seri_norm=normalize_seri(s)))
    await db.commit()


# --- M1.6: arıza işinde tek cihaz -------------------------------------------------


async def test_ariza_isinde_en_cok_bir_cihaz(client, db, birimli_kullanici_ac, lokasyon_ac) -> None:
    await birimli_kullanici_ac("op_a1", "SERVIS_OPERASYON", ["GUVENLIK"])
    lok = await lokasyon_ac()
    await giris(client, "op_a1")
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, seriler=["SN-1", "SN-2"]))
    assert r.status_code == 400, r.text
    assert "en çok 1 cihaz" in r.json()["detail"]
    for tur in ("DESTEK", "PLANSIZ_BAKIM"):
        r = await client.post(IS, json=_govde(lok.account_id, lok.id, tur=tur, seriler=["A", "B"]))
        assert r.status_code == 400, tur
    # Tek cihaz ve cihazsız arıza açılır.
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, seriler=["SN-1"]))
    assert r.status_code == 201, r.text
    ariza = r.json()
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, seriler=[]))
    assert r.status_code == 201, r.text
    # Keşif cihazsız, kurulum çok cihazlı olabilir.
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, tur="KESIF", seriler=[]))
    assert r.status_code == 201, r.text
    r = await client.post(
        IS, json=_govde(lok.account_id, lok.id, tur="KURULUM", seriler=["K1", "K2", "K3"])
    )
    assert r.status_code == 201, r.text
    kurulum = r.json()
    # Seri değişikliği de sınırı aşamaz.
    r = await client.put(f"{IS}/{ariza['id']}/seriler", json={"seriler": ["SN-1", "SN-9"]})
    assert r.status_code == 400
    # Çok cihazlı kurulum arızaya çevrilemez.
    await birimli_kullanici_ac("sef_a1", "SERVIS_SEF", ["GUVENLIK"])
    await giris(client, "sef_a1")
    r = await client.patch(
        f"{IS}/{kurulum['id']}", json={"version": kurulum["version"], "tur": "ARIZA"}
    )
    assert r.status_code == 400
    assert "en çok 1 cihaz" in r.json()["detail"]


async def test_eski_cok_cihazli_ariza_okunur(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    """Göçten/Faz A öncesinden gelen çok cihazlı arıza kaydı okunur; seri
    listesi azaltılabilir ama artırılamaz."""
    await birimli_kullanici_ac("sef_a2", "SERVIS_SEF", ["GUVENLIK"])
    so = await servis_isi_ac(seri=None)
    await _seri_ekle(db, so, "ESKI-1", "ESKI-2", "ESKI-3")
    await giris(client, "sef_a2")
    r = await client.get(f"{IS}/{so.id}")
    assert r.status_code == 200
    assert [s["seri_no"] for s in r.json()["seriler"]] == ["ESKI-1", "ESKI-2", "ESKI-3"]
    r = await client.get(IS, params={"q": "ESKI-2"})
    assert [x["id"] for x in r.json()] == [so.id]
    r = await client.put(f"{IS}/{so.id}/seriler", json={"seriler": ["ESKI-1", "ESKI-2"]})
    assert r.status_code == 400
    r = await client.put(f"{IS}/{so.id}/seriler", json={"seriler": ["ESKI-1"]})
    assert r.status_code == 200, r.text


# --- M1.2: zorunlu talep bilgisi --------------------------------------------------


async def test_acilista_lokasyon_ve_talep_eden_zorunlu(
    client, db, birimli_kullanici_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("op_a3", "SERVIS_OPERASYON", ["GUVENLIK"])
    lok = await lokasyon_ac()
    await giris(client, "op_a3")
    r = await client.post(IS, json=_govde(lok.account_id, None))
    assert r.status_code == 400 and "lokasyon" in r.json()["detail"]
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, iletisim_telefon=None))
    assert r.status_code == 400 and "telefonu" in r.json()["detail"]
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, iletisim_ad="  "))
    assert r.status_code == 400 and "adı" in r.json()["detail"]
    r = await client.post(IS, json=_govde(lok.account_id, lok.id, konu="   "))
    assert r.status_code == 400
    # Uzaktan çözüldü açılışı da aynı kapıdan geçer.
    r = await client.post(
        f"{IS}/uzaktan-cozuldu",
        json={
            **_govde(lok.account_id, None),
            "cozum_kanali": "TELEFON",
            "yapilan_islem": "Yönlendirildi",
        },
    )
    assert r.status_code in (400, 403)
    # Telefonu kayıtlı irtibat kişisi ad/telefonun yerini tutar.
    kisi = Contact(account_id=lok.account_id, full_name="Tesis Sorumlusu", phone="+905551112233")
    db.add(kisi)
    await db.commit()
    r = await client.post(
        IS,
        json=_govde(
            lok.account_id, lok.id, contact_id=kisi.id, iletisim_ad=None, iletisim_telefon=None
        ),
    )
    assert r.status_code == 201, r.text
    assert await db.scalar(select(ServiceOrder).where(ServiceOrder.id == r.json()["id"]))


async def test_sistem_acilisi_talep_bilgisinden_muaf(db, lokasyon_ac) -> None:
    """PB/sistem açılışları ekran kapısından geçmez: irtibatsız/lokasyonsuz
    servis fonksiyonu çağrısı açılır (bakım bulgusu, kiralama, atölye)."""
    lok = await lokasyon_ac()
    so = await is_emirleri.olustur(
        db,
        is_emirleri.ServisIsiGirdisi(
            birim="GUVENLIK", tur="KURULUM", konu="Kiralama kurulumu", customer_id=lok.account_id
        ),
        user=None,
        clock=FakeClock(),
    )
    await db.commit()
    assert so.iletisim_ad is None and so.address_id is None


# --- M1.7: yeniden açma yok, bağlı yeni iş ----------------------------------------


def test_makinede_yeniden_acma_gecisi_yok() -> None:
    for kaynak in ("TAMAMLANDI", "KAPATILDI"):
        assert "TEKRAR_ACILDI" not in SERVIS_IS_EMRI.sonraki(kaynak)
        with pytest.raises(IzinsizGecis):
            SERVIS_IS_EMRI.dogrula(kaynak, "TEKRAR_ACILDI")
    # Eski yeniden açılmış işler ilerleyebilir (katalogda kalır).
    assert "TAMAMLANDI" in SERVIS_IS_EMRI.sonraki("TEKRAR_ACILDI")
    assert "KAPATILDI" in SERVIS_IS_EMRI.terminaller


async def test_yeniden_ac_ucu_409_ve_bagli_yeni_is(
    client, db, birimli_kullanici_ac, servis_isi_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("sef_a4", "SERVIS_SEF", ["GUVENLIK"])
    lok = await lokasyon_ac()
    hesap_id = lok.account_id
    from app.models import Account

    hesap = await db.get(Account, hesap_id)
    so = await servis_isi_ac(
        musteri=hesap,
        lokasyon=lok,
        durum="KAPATILDI",
        iletisim_ad="Saha Yetkilisi",
        iletisim_telefon="+905321112233",
        talep_kanali="TELEFON",
        seri=None,
    )
    await _seri_ekle(db, so, "CIHAZ-7")
    await giris(client, "sef_a4")

    r = await client.post(f"{IS}/{so.id}/yeniden-ac", json={"gerekce": "Arıza sürüyor"})
    assert r.status_code == 409
    assert "yeniden açılamaz" in r.json()["detail"]
    r = await client.post(f"{IS}/{so.id}/durum", json={"hedef": "TEKRAR_ACILDI"})
    assert r.status_code == 400
    so = await tazele(db, so)
    assert so.status == "KAPATILDI" and so.reopen_count == 0
    r = await client.get(f"{IS}/{so.id}")
    assert r.json()["sonraki_durumlar"] == []
    assert all(g["hedef"] != "TEKRAR_ACILDI" for g in r.json()["gecisler"])

    r = await client.post(f"{IS}/{so.id}/bagli-yeni-is", json={"konu": "Arıza tekrarladı"})
    assert r.status_code == 201, r.text
    yeni = r.json()
    assert yeni["onceki_is_id"] == so.id
    assert yeni["status"] == "MUSTERI_TALEBI"
    assert yeni["konu"] == "Arıza tekrarladı"
    assert yeni["customer_id"] == hesap_id and yeni["address_id"] == lok.id
    assert [s["seri_no"] for s in yeni["seriler"]] == ["CIHAZ-7"]
    assert yeni["iliskili_isler"]["onceki"]["id"] == so.id
    # Önceki iş değişmez; bağ iki yönlü görünür.
    so = await tazele(db, so)
    assert so.status == "KAPATILDI"
    r = await client.get(f"{IS}/{so.id}")
    assert [s["id"] for s in r.json()["iliskili_isler"]["sonrakiler"]] == [yeni["id"]]
    assert await olay_sayisi(db, so.id, "ILISKI") == 1
    assert await olay_sayisi(db, yeni["id"], "ILISKI") == 1


async def test_bagli_yeni_is_kurallari(
    client, db, birimli_kullanici_ac, servis_isi_ac, lokasyon_ac
) -> None:
    await birimli_kullanici_ac("op_a5", "SERVIS_OPERASYON", ["GUVENLIK"])
    lok = await lokasyon_ac()
    from app.models import Account

    hesap = await db.get(Account, lok.account_id)
    acik = await servis_isi_ac(musteri=hesap, lokasyon=lok)
    eski = await servis_isi_ac(musteri=hesap, lokasyon=lok, durum="TAMAMLANDI", seri=None)
    await _seri_ekle(db, eski, "E-1", "E-2")
    await giris(client, "op_a5")
    # Açık işten bağlı iş açılmaz.
    r = await client.post(f"{IS}/{acik.id}/bagli-yeni-is", json={})
    assert r.status_code == 409
    # Önceki işte talep bilgisi yoksa açılış kuralı ister (M1.2).
    r = await client.post(f"{IS}/{eski.id}/bagli-yeni-is", json={"talep_kanali": "TELEFON"})
    assert r.status_code == 400
    govde = {
        "talep_kanali": "TELEFON",
        "iletisim_ad": "Yeni Yetkili",
        "iletisim_telefon": "+905320000000",
    }
    # Çok cihazlı eski işin devamı tek cihaz seçmeli (M1.6).
    r = await client.post(f"{IS}/{eski.id}/bagli-yeni-is", json=govde)
    assert r.status_code == 400 and "en çok 1 cihaz" in r.json()["detail"]
    r = await client.post(f"{IS}/{eski.id}/bagli-yeni-is", json={**govde, "seriler": ["E-2"]})
    assert r.status_code == 201, r.text
    assert [s["seri_no"] for s in r.json()["seriler"]] == ["E-2"]


async def test_pb_isinin_devami_ariza_olarak_acilir(db, servis_isi_ac, lokasyon_ac) -> None:
    lok = await lokasyon_ac()
    from app.models import Account

    hesap = await db.get(Account, lok.account_id)
    pb = await servis_isi_ac(musteri=hesap, lokasyon=lok, durum="KAPATILDI")
    pb.tur = "ATOLYE"
    pb.kategori = "ATOLYE"
    await db.commit()
    girdi = is_emirleri.bagli_is_girdisi(pb, ["X"])
    assert girdi.tur == "ARIZA" and girdi.address_id == lok.id


# --- D3.4 + G4.6: kalite onayı ----------------------------------------------------


def test_kalite_izni_rollerde() -> None:
    assert "servis.kalite_onay" in permissions_of("SERVIS_YONETICI")
    assert "servis.kalite_onay" in permissions_of("SERVIS_SEF")
    for rol in ("SERVIS_TEKNISYEN", "SERVIS_OPERASYON", "YONETIM"):
        assert "servis.kalite_onay" not in permissions_of(rol), rol


async def test_kalite_onayi_ve_gorevler_ayriligi(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    from zaman_ortam import bolum_ac

    tek = await teknisyen(birimli_kullanici_ac, "tek_k1")
    sef_ekipte = await birimli_kullanici_ac("sef_k1", "SERVIS_SEF", ["GUVENLIK"])
    sef_sureli = await birimli_kullanici_ac("sef_k2", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("sef_k3", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("op_k1", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(atananlar=[tek, sef_ekipte])
    an = client.clock.now() - timedelta(hours=3)
    await bolum_ac(db, so, sef_sureli, "SAHA", an, an + timedelta(hours=1))

    # Tamamlanmamış işe onay verilmez.
    await giris(client, "sef_k3")
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": so.version})
    assert r.status_code == 409
    await giris(client, "tek_k1")
    r = await client.post(f"{IS}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    surum = r.json()["version"]
    # Teknisyende izin yok; operasyonda izin yok.
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": surum})
    assert r.status_code == 403
    await giris(client, "op_k1")
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": surum})
    assert r.status_code == 403
    # Ekipte olan şef ve süre kaydı olan şef: görevler ayrılığı (403, Türkçe gerekçe).
    for kisi in ("sef_k1", "sef_k2"):
        await giris(client, kisi)
        r = await client.get(f"{IS}/{so.id}")
        assert r.json()["kalite"]["bekliyor"] is True
        assert r.json()["kalite"]["verebilir"] is False
        r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": surum})
        assert r.status_code == 403, kisi
        assert "görevler ayrılığı" in r.json()["detail"]
    # Liste süzgeci: kalite onayı bekleyenler.
    await giris(client, "sef_k3")
    r = await client.get(IS, params={"kalite": "BEKLEYEN"})
    assert [x["id"] for x in r.json()] == [so.id]
    r = await client.get(IS, params={"kalite": "UYDURMA"})
    assert r.status_code == 400
    # Eski sürüm 409.
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": surum - 1})
    assert r.status_code == 409
    r = await client.post(
        f"{IS}/{so.id}/kalite-onayi", json={"version": surum, "not": "Saha temiz"}
    )
    assert r.status_code == 200, r.text
    kalite = r.json()["kalite"]
    assert kalite["onay_at"] is not None and kalite["notu"] == "Saha temiz"
    assert kalite["bekliyor"] is False
    assert r.json()["status"] == "TAMAMLANDI"  # yeni durum yok
    so = await tazele(db, so)
    assert so.kalite_onaylayan_id is not None
    assert await olay_sayisi(db, so.id, "KALITE") == 1
    # İkinci onay 409; süzgeçten düşer, "onaylı"da görünür.
    r = await client.post(f"{IS}/{so.id}/kalite-onayi", json={"version": so.version})
    assert r.status_code == 409
    r = await client.get(IS, params={"kalite": "BEKLEYEN"})
    assert r.json() == []
    r = await client.get(IS, params={"kalite": "ONAYLI"})
    assert [x["id"] for x in r.json()] == [so.id]
    # Kapatılmış iş de onay süzgecinde kalır; kapatma onayı silmez.
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 200
    assert r.json()["kalite"]["onay_at"] is not None


async def test_kalite_kapsam_disi_404(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    await birimli_kullanici_ac("sef_k4", "SERVIS_SEF", ["GUVENLIK"])
    yabanci = await servis_isi_ac(birim="HABERLESME", durum="TAMAMLANDI")
    await giris(client, "sef_k4")
    r = await client.post(f"{IS}/{yabanci.id}/kalite-onayi", json={"version": yabanci.version})
    assert r.status_code == 404
    r = await client.post(f"{IS}/{yabanci.id}/bagli-yeni-is", json={})
    assert r.status_code == 404
    yabanci = await tazele(db, yabanci)
    assert yabanci.kalite_onay_at is None
    assert await olay_sayisi(db, yabanci.id) == 0


# --- G7.8: iş başlat/bitir konumu -------------------------------------------------


async def test_baslat_bitir_konumu(client, db, birimli_kullanici_ac, servis_isi_ac) -> None:
    tek = await teknisyen(birimli_kullanici_ac, "tek_g1")
    await birimli_kullanici_ac("op_g1", "SERVIS_OPERASYON", ["GUVENLIK"])
    so = await servis_isi_ac(atananlar=[tek])
    await giris(client, "tek_g1")
    r = await client.post(
        f"{TS}/zaman/baslat",
        json={
            "is_id": so.id,
            "eylem": "SAHAYA_VARDIM",
            "konum": {"enlem": 41.015137, "boylam": 28.97953, "dogruluk_m": 12.4},
        },
    )
    assert r.status_code == 201, r.text
    bolum = r.json()["bolum"]
    assert bolum["bas_konum"] == {
        "durum": "ALINDI",
        "metin": "Konum alındı",
        "enlem": 41.015137,
        "boylam": 28.97953,
        "dogruluk_m": 12,
    }
    assert bolum["bit_konum"] is None
    client.clock.advance(minutes=30)
    # Konum yok (izin reddi) → işlem engellenmez, "alınamadı" yazılır.
    r = await client.post(
        f"{IS}/{so.id}/zaman/bolumler/{bolum['id']}/gecis",
        json={"version": bolum["version"], "faaliyet": "TEST", "konum": {"hata": "IZIN_YOK"}},
    )
    assert r.status_code == 200, r.text
    eski, yeni = r.json()["bolum"], r.json()["yeni_bolum"]
    assert eski["bit_konum"]["durum"] == "ALINAMADI"
    assert eski["bit_konum"]["metin"] == "Konum bilgisi alınamadı"
    assert yeni["bas_konum"]["durum"] == "ALINAMADI"
    client.clock.advance(minutes=20)
    # Aralık dışı değer reddedilmez, "alınamadı" sayılır.
    r = await client.post(
        f"{IS}/{so.id}/zaman/bolumler/{yeni['id']}/bitir",
        json={"version": yeni["version"], "konum": {"enlem": 400, "boylam": 29}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["bolum"]["bit_konum"]["durum"] == "ALINAMADI"
    # Gövdesiz (eski istemci) bitiş de alınamadı sayılır.
    client.clock.advance(minutes=5)
    r = await client.post(f"{TS}/zaman/baslat", json={"is_id": so.id, "eylem": "SAHAYA_VARDIM"})
    assert r.status_code == 201
    assert r.json()["bolum"]["bas_konum"]["durum"] == "ALINAMADI"
    # Koordinat kişisel veri: servis.planla'sız başka kullanıcı yalnız durumu görür.
    await giris(client, "op_g1")
    r = await client.get(f"{IS}/{so.id}/zaman")
    assert r.status_code == 200, r.text
    ilk = next(b for b in r.json()["bolumler"] if b["id"] == bolum["id"])
    assert ilk["bas_konum"]["durum"] == "ALINDI"
    assert ilk["bas_konum"].get("enlem") is None


# --- M1.10 / M9.4: süre kaydı olmadan kapanış ----------------------------------------


async def test_suresiz_kapanis_uyari_ve_sure_eksik(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("sef_s1", "SERVIS_SEF", ["GUVENLIK"])
    tek = await teknisyen(birimli_kullanici_ac, "tek_s1")
    so = await servis_isi_ac(atananlar=[tek])
    await giris(client, "sef_s1")
    govde = {k: v for k, v in SONUC.items() if k != "sure_eksik_onay"}
    r = await client.post(f"{IS}/{so.id}/sonuc", json=govde)
    assert r.status_code == 409 and "Süre kaydı eksik" in r.json()["detail"]
    so = await tazele(db, so)
    assert so.status == "MUSTERI_TALEBI"
    r = await client.post(f"{IS}/{so.id}/sonuc", json=SONUC)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "TAMAMLANDI"
    assert r.json()["sure_durumu"] == "EKSIK"  # 0 değil, "eksik"
    notlar = (
        await db.scalars(
            select(ServiceOrderEvent.ozet).where(
                ServiceOrderEvent.service_order_id == so.id, ServiceOrderEvent.olay_turu == "NOT"
            )
        )
    ).all()
    assert any("Süre kaydı eksik" in n for n in notlar)
    r = await client.get(IS, params={"kpi": "sure_eksik", "donem": "bugun"})
    assert so.id in [x["id"] for x in r.json()]


async def test_servis_seri_siniri_servis_katmaninda(db, lokasyon_ac) -> None:
    lok = await lokasyon_ac()
    with pytest.raises(ServisGirdiHatasi):
        await is_emirleri.olustur(
            db,
            is_emirleri.ServisIsiGirdisi(
                birim="GUVENLIK",
                tur="ARIZA",
                konu="İki cihaz",
                customer_id=lok.account_id,
                seriler=["A", "B"],
            ),
            user=None,
            clock=FakeClock(),
        )
