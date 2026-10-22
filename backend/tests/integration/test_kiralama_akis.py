"""Kiralama uçtan uca akış (TS-110, TS-113, TS-114, TS-117; E06-02/05/06/07/08/14/15).

Senaryolar envanter durumunu ve hareket sayısını doğrular: talep → planla →
tahsis → sevk → kısmi iade (3 depo-1, 1 depo-2, 1 kayıp) → kontrol →
kapanış; kurulumlu kiralamada TOPLANDI kuralı; iptal; aşama geri alma.
"""

import re

import pytest
from kiralama_ortak import (
    NUMARA,
    URL,
    bakiye,
    cihaz_durumlari,
    depo_ac,
    hareket_sayisi,
    hazir_kiralama,
    istemci,
    kalem_id,
    kiralama_ac,
    kiralik_urun_ac,
    musteri_ac,
    planla,
    seri_idleri,
    stok_gir,
    tahsis,
)
from sqlalchemy import func, select

from app.models import Rental, RentalEvent, RentalItem, WorkOrder

pytestmark = pytest.mark.integration


@pytest.fixture
async def ist(client, kullanici_ac):
    await kullanici_ac("kir_yon", "SERVIS_YONETICI")
    i = await istemci("kir_yon")
    yield i
    await i.aclose()


async def test_olustur_dogrulamalari_ve_numara(ist, db) -> None:
    urun = await kiralik_urun_ac(db, "TLS-1", seri=True)
    musteri = await musteri_ac(db)
    musteri_degil = await musteri_ac(db, "Tedarikçi Ltd.", musteri=False)

    # Müşterisiz → 400 (422 değil), müşteri olmayan hesap → 400.
    r = await ist.post(
        URL,
        json={
            "birim": "GUVENLIK",
            "baslangic": "2026-11-01",
            "bitis": "2026-11-05",
            "kalemler": [{"product_id": urun.id, "qty": 1}],
        },
    )
    assert r.status_code == 400, r.text
    await kiralama_ac(ist, musteri_degil, [(urun, 1)], beklenen=400)
    # Bitiş başlangıçtan önce → 400; mobilite biriminde kiralama → 400.
    await kiralama_ac(ist, musteri, [(urun, 1)], bas="2026-11-05", bit="2026-11-01", beklenen=400)
    await kiralama_ac(ist, musteri, [(urun, 1)], birim="MOBILITE", beklenen=400)
    # Başka birimin kataloğundaki ürün → 400 (E06-D04).
    hab = await kiralik_urun_ac(db, "HAB-1", seri=True, birim="HABERLESME")
    await kiralama_ac(ist, musteri, [(hab, 1)], beklenen=400)

    k = await kiralama_ac(ist, musteri, [(urun, 2)], seri_listesi=["YOKSAYILIR"], proje_adi="Fuar")
    assert re.match(NUMARA, k["rental_no"])
    assert k["status"] == "TALEP"
    assert k["sonraki_durumlar"] == ["IPTAL", "PLANLANDI"]
    assert k["kalem_ozeti"] == ["TLS-1 ×2"]
    # Kalem rental_items'ta; başlıkta kopya ürün/seri alanı yok.
    assert await db.scalar(select(func.count()).select_from(RentalItem)) == 1
    assert not hasattr(Rental, "product_id") and not hasattr(Rental, "serial_no")
    olaylar = (await ist.get(f"{URL}/{k['id']}/gecmis")).json()
    assert [o["tur"] for o in olaylar] == ["OLUSTUR"]


async def test_put_durum_birim_kabul_etmez_ve_version(ist, db) -> None:
    urun = await kiralik_urun_ac(db, "TLS-2", seri=True)
    k = await kiralama_ac(ist, await musteri_ac(db), [(urun, 1)])
    yol = f"{URL}/{k['id']}"
    r = await ist.put(yol, json={"version": k["version"], "status": "KAPANDI"})
    assert r.status_code == 400, r.text
    r = await ist.put(yol, json={"version": k["version"], "birim": "HABERLESME"})
    assert r.status_code == 400
    r = await ist.put(yol, json={"version": k["version"], "customer_id": None})
    assert r.status_code == 400  # müşterisiz istek 400 (K12)
    r = await ist.put(yol, json={"version": k["version"] + 5, "proje_adi": "Eski"})
    assert r.status_code == 409
    r = await ist.put(yol, json={"version": k["version"], "proje_adi": "Yeni proje"})
    assert r.status_code == 200 and r.json()["proje_adi"] == "Yeni proje"


async def test_put_tek_islem_gecersiz_ucuncu_kalem_hepsini_geri_alir(ist, db) -> None:
    u1 = await kiralik_urun_ac(db, "PG-1", seri=False)
    u2 = await kiralik_urun_ac(db, "PG-2", seri=False)
    k = await kiralama_ac(ist, await musteri_ac(db), [(u1, 3)])
    r = await ist.put(
        f"{URL}/{k['id']}",
        json={
            "version": k["version"],
            "proje_adi": "Değişmemeli",
            "kalemler": [
                {"id": k["kalemler"][0]["id"], "product_id": u1.id, "qty": 4},
                {"product_id": u2.id, "qty": 1},
                {"product_id": 987654, "qty": 1},
            ],
        },
    )
    assert r.status_code == 400, r.text
    kart = (await ist.get(f"{URL}/{k['id']}")).json()
    assert kart["proje_adi"] is None
    assert [(x["product_id"], x["qty"]) for x in kart["kalemler"]] == [(u1.id, 3)]
    # Geçerli kalem güncellemesi kimliği korur.
    r = await ist.put(
        f"{URL}/{k['id']}",
        json={
            "version": kart["version"],
            "kalemler": [
                {"id": k["kalemler"][0]["id"], "product_id": u1.id, "qty": 4},
                {"product_id": u2.id, "qty": 1},
            ],
        },
    )
    assert r.status_code == 200, r.text
    kalemler = {x["product_id"]: x for x in r.json()["kalemler"]}
    assert kalemler[u1.id]["id"] == k["kalemler"][0]["id"] and kalemler[u1.id]["qty"] == 4
    olaylar = [o["tur"] for o in (await ist.get(f"{URL}/{k['id']}/gecmis")).json()]
    assert "KALEM" in olaylar


async def test_irtibat_musterinin_kisisi_olmali_ve_kimlik_korunur(ist, db) -> None:
    from app.models import Contact

    urun = await kiralik_urun_ac(db, "TLS-3", seri=True)
    musteri = await musteri_ac(db)
    baska = await musteri_ac(db, "Başka A.Ş.")
    kisi = Contact(account_id=musteri.id, full_name="Ayşe Saha")
    yabanci = Contact(account_id=baska.id, full_name="Yabancı Kişi")
    db.add_all([kisi, yabanci])
    await db.commit()
    await kiralama_ac(
        ist,
        musteri,
        [(urun, 1)],
        irtibatlar=[{"contact_id": yabanci.id, "rol": "SATIN_ALMA"}],
        beklenen=400,
    )
    k = await kiralama_ac(
        ist, musteri, [(urun, 1)], irtibatlar=[{"contact_id": kisi.id, "rol": "SATIN_ALMA"}]
    )
    irtibat = k["irtibatlar"][0]
    r = await ist.put(
        f"{URL}/{k['id']}",
        json={
            "version": k["version"],
            "irtibatlar": [{"id": irtibat["id"], "contact_id": kisi.id, "rol": "SAHA_OPERASYON"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["irtibatlar"][0]["id"] == irtibat["id"]
    assert r.json()["irtibatlar"][0]["rol"] == "SAHA_OPERASYON"


async def test_aktif_tahsis_varken_musteri_degismez(ist, db) -> None:
    h = await hazir_kiralama(db, ist, toplu_adet=2, on_ek="MD")
    yeni = await musteri_ac(db, "Yeni Müşteri")
    k = h["k"]
    r = await ist.put(f"{URL}/{k['id']}", json={"version": k["version"], "customer_id": yeni.id})
    assert r.status_code == 409, r.text


async def test_tam_akis_kismi_iade_kontrol_kapanis(ist, db) -> None:
    """5 seri cihaz: 3 depo-1, 1 depo-2, 1 kayıp → 4 KONTROLDE + 1 KAYIP, 5 hareket."""
    h = await hazir_kiralama(db, ist, seri_adet=5, on_ek="AK")
    depo2 = await depo_ac(db, "AK-D2", birim="GUVENLIK")
    k = h["k"]
    assert k["status"] == "HAZIRLANIYOR"
    # Sevksiz depoya alma (iade) yasak geçiş → 409.
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={"satirlar": [{"tahsis_id": k["tahsisler"][0]["id"], "sonuc": "KAYIP"}]},
    )
    assert r.status_code == 409
    r = await ist.post(f"{URL}/{k['id']}/sevk", json={})
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["status"] == "SEVK_EDILDI"
    assert await cihaz_durumlari(db, h["seri"]) == {"KIRADA": 5}
    t = [x["id"] for x in k["tahsisler"]]
    # Kısmi iade: 2 cihaz depo-1'e → durum değişmez, gösterim KISMI.
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {"tahsis_id": t[0], "sonuc": "IADE_ALINDI", "depo_id": h["depo"].id},
                {"tahsis_id": t[1], "sonuc": "IADE_ALINDI", "depo_id": h["depo"].id},
                {"tahsis_id": t[4], "sonuc": "MUSTERIDE", "not": "Müşteri bir hafta daha"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SEVK_EDILDI" and r.json()["iade_gosterimi"] == "KISMI"
    # Kalan: 1 depo-1, 1 depo-2, 1 kayıp → DEPOYA_ALINDI.
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {"tahsis_id": t[2], "sonuc": "IADE_ALINDI", "depo_id": h["depo"].id},
                {"tahsis_id": t[3], "sonuc": "IADE_ALINDI", "depo_id": depo2.id},
                {"tahsis_id": t[4], "sonuc": "KAYIP"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["status"] == "DEPOYA_ALINDI" and k["iade_gosterimi"] == "TAM"
    assert await cihaz_durumlari(db, h["seri"]) == {"KONTROLDE": 4, "KAYIP": 1}
    assert await hareket_sayisi(db, "IADE", "KAYIP") == 5
    # Sevk edilmemiş (artık AKTİF olmayan) tahsise iade 400.
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={"satirlar": [{"tahsis_id": t[0], "sonuc": "KAYIP"}]},
    )
    assert r.status_code == 409  # DEPOYA_ALINDI'da iade yok
    # Kontrol: 4 cihaz tek istekle.
    cihazlar = await seri_idleri(db, h["seri"])
    kontroldekiler = [
        c["id"] for c in (await ist.get(f"{URL}/envanter", params={"durum": "KONTROLDE"})).json()
    ]
    assert sorted(kontroldekiler) == sorted(cihazlar[:4])
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={"satirlar": [{"kiralik_id": c, "sonuc": "UYGUN"} for c in kontroldekiler]},
    )
    assert r.status_code == 200, r.text
    assert await cihaz_durumlari(db, h["seri"]) == {"HAZIR": 4, "KAYIP": 1}
    r = await ist.post(f"{URL}/{k['id']}/kapat")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "KAPANDI" and r.json()["kapanis_at"]
    assert r.json()["sonraki_durumlar"] == []
    # Kapalı kiralamada tahsis/sevk 409; geri alma 409.
    r = await ist.post(f"{URL}/{k['id']}/sevk", json={})
    assert r.status_code == 409
    r = await ist.post(f"{URL}/{k['id']}/geri-al", json={"gerekce": "deneme"})
    assert r.status_code == 409
    # Mobilite hak ediş zincirine yazım yok.
    assert await db.scalar(select(func.count()).select_from(WorkOrder)) == 0


async def test_kurulumlu_kiralamada_son_iade_once_toplandi_ister(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=2, on_ek="KR", sevk=True)
    k = h["k"]
    r = await ist.post(f"{URL}/{k['id']}/asama", json={"asama": "KURULUM_YAPILDI"})
    assert r.status_code == 200, r.text
    # Aynı aşama ikinci kez → 409.
    r = await ist.post(f"{URL}/{k['id']}/asama", json={"asama": "KURULUM_YAPILDI"})
    assert r.status_code == 409
    # Sevk/iade aşama ucundan girilemez → 400.
    r = await ist.post(f"{URL}/{k['id']}/asama", json={"asama": "DEPOYA_ALINDI"})
    assert r.status_code == 400
    t = [x["id"] for x in k["tahsisler"]]
    iade = {
        "satirlar": [{"tahsis_id": x, "sonuc": "IADE_ALINDI", "depo_id": h["depo"].id} for x in t]
    }
    # Kısmi iade serbest; son iade TOPLANDI ister.
    r = await ist.post(f"{URL}/{k['id']}/iade", json={"satirlar": iade["satirlar"][:1]})
    assert r.status_code == 200, r.text
    r = await ist.post(f"{URL}/{k['id']}/iade", json={"satirlar": iade["satirlar"][1:]})
    assert r.status_code == 409, r.text
    assert await cihaz_durumlari(db, h["seri"]) == {"KONTROLDE": 1, "KIRADA": 1}
    r = await ist.post(f"{URL}/{k['id']}/asama", json={"asama": "TOPLANDI"})
    assert r.status_code == 200
    r = await ist.post(f"{URL}/{k['id']}/iade", json={"satirlar": iade["satirlar"][1:]})
    assert r.status_code == 200 and r.json()["status"] == "DEPOYA_ALINDI"


async def test_telsiz_kurulumsuz_sevkten_depoya(ist, db) -> None:
    h = await hazir_kiralama(db, ist, toplu_adet=10, on_ek="TL", sevk=True)
    k = h["k"]
    assert await bakiye(db, h["toplu"], None, "KIRADA") == 10
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {
                    "tahsis_id": k["tahsisler"][0]["id"],
                    "sonuc": "IADE_ALINDI",
                    "adet": 10,
                    "depo_id": h["depo"].id,
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DEPOYA_ALINDI"
    assert await bakiye(db, h["toplu"], h["depo"], "KONTROLDE") == 10
    assert await bakiye(db, h["toplu"], None, "KIRADA") == 0


async def test_tam_sevk_her_kalemin_tamamen_tahsisini_ister(ist, db) -> None:
    depo = await depo_ac(db, "TS-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "TS-SERI", seri=True)
    toplu = await kiralik_urun_ac(db, "TS-TOPLU", seri=False)
    await stok_gir(ist, seri, depo, seriler=["A1", "A2", "A3"])
    await stok_gir(ist, toplu, depo, adet=5)
    k = await kiralama_ac(ist, await musteri_ac(db), [(seri, 3), (toplu, 5)])
    await planla(ist, k)
    cihazlar = await seri_idleri(db, seri)
    k = await tahsis(
        ist,
        k,
        [
            {"kalem_id": kalem_id(k, seri), "kiralik_idler": cihazlar[:2]},
            {"kalem_id": kalem_id(k, toplu), "depo_id": depo.id, "adet": 5},
        ],
    )
    r = await ist.post(f"{URL}/{k['id']}/sevk", json={})
    assert r.status_code == 400, r.text
    assert "TS-SERI: 1 adet eksik" in r.json()["detail"]
    await tahsis(ist, k, [{"kalem_id": kalem_id(k, seri), "kiralik_idler": cihazlar[2:]}])
    # İlk sevk tüm tahsisi göndermek zorunda değil: yalnız toplu tahsis.
    k = (await ist.get(f"{URL}/{k['id']}")).json()
    toplu_tahsis = next(t["id"] for t in k["tahsisler"] if t["kiralik_id"] is None)
    r = await ist.post(
        f"{URL}/{k['id']}/sevk", json={"satirlar": [{"tahsis_id": toplu_tahsis, "adet": 3}]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SEVK_EDILDI"
    # Ek sevk: kalan 2 toplu + seriler.
    kart = r.json()
    r = await ist.post(f"{URL}/{k['id']}/sevk", json={})
    assert r.status_code == 400  # ek sevkte satır seçimi zorunlu
    kalanlar = [{"tahsis_id": t["id"]} for t in kart["tahsisler"] if t["qty"] > t["sevk_adet"]]
    assert len(kalanlar) == 4  # 3 seri + kalan 2 adetlik toplu
    r = await ist.post(f"{URL}/{k['id']}/sevk", json={"satirlar": kalanlar})
    assert r.status_code == 200, r.text
    assert await cihaz_durumlari(db, seri) == {"KIRADA": 3}
    assert await bakiye(db, toplu, None, "KIRADA") == 5


async def test_iptal_gerekce_ve_tahsis_cozme(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="IP")
    k = h["k"]
    r = await ist.post(f"{URL}/{k['id']}/iptal", json={"gerekce": "  "})
    assert r.status_code == 400
    r = await ist.post(f"{URL}/{k['id']}/iptal", json={"gerekce": "Müşteri vazgeçti"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "IPTAL"
    assert all(t["durum"] == "COZULDU" for t in r.json()["tahsisler"])
    assert await hareket_sayisi(db, "TAHSIS_COZ") == 1
    # Cihaz başka kiralamaya aynı tarihlerde tahsis edilebilir.
    k2 = await kiralama_ac(ist, h["musteri"], [(h["seri"], 1)])
    await planla(ist, k2)
    await tahsis(ist, k2, [{"kalem_id": kalem_id(k2, h["seri"]), "kiralik_idler": h["cihazlar"]}])
    # IPTAL'de tahsis/sevk 409.
    r = await ist.post(
        f"{URL}/{k['id']}/tahsis",
        json={"satirlar": [{"kalem_id": kalem_id(k, h["seri"]), "kiralik_idler": h["cihazlar"]}]},
    )
    assert r.status_code == 409
    # Sevk edilmiş kiralama iptal edilemez.
    r = await ist.post(f"{URL}/{k2['id']}/sevk", json={})
    assert r.status_code == 200
    r = await ist.post(f"{URL}/{k2['id']}/iptal", json={"gerekce": "Geç kaldık"})
    assert r.status_code == 409


async def test_asama_geri_alma(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=2, toplu_adet=4, on_ek="GA", sevk=True)
    k = h["k"]
    iade = [
        {
            "tahsis_id": t["id"],
            "sonuc": "IADE_ALINDI",
            "depo_id": h["depo"].id,
            **({} if t["kiralik_id"] else {"adet": 4}),
        }
        for t in k["tahsisler"]
    ]
    r = await ist.post(f"{URL}/{k['id']}/iade", json={"satirlar": iade})
    assert r.status_code == 200 and r.json()["status"] == "DEPOYA_ALINDI"
    hareket_once = await hareket_sayisi(db)
    olaylar = (await ist.get(f"{URL}/{k['id']}/gecmis")).json()
    sevk_olayi = next(o for o in olaylar if o["tur"] == "SEVK")
    # Gerekçesiz 400; son olay dışında hedef 409.
    assert (await ist.post(f"{URL}/{k['id']}/geri-al", json={})).status_code == 400
    r = await ist.post(
        f"{URL}/{k['id']}/geri-al", json={"gerekce": "x", "olay_id": sevk_olayi["id"]}
    )
    assert r.status_code == 409
    r = await ist.post(f"{URL}/{k['id']}/geri-al", json={"gerekce": "Yanlış iade"})
    assert r.status_code == 200, r.text
    kart = r.json()
    assert kart["status"] == "SEVK_EDILDI"
    assert all(t["iade_adet"] == 0 and t["durum"] == "AKTIF" for t in kart["tahsisler"])
    assert await cihaz_durumlari(db, h["seri"]) == {"KIRADA": 2}
    assert await bakiye(db, h["toplu"], None, "KIRADA") == 4
    assert await bakiye(db, h["toplu"], h["depo"], "KONTROLDE") == 0
    # Hiçbir kayıt silinmedi: ters hareketler eklendi.
    assert await hareket_sayisi(db) == hareket_once + 3
    olaylar = (await ist.get(f"{URL}/{k['id']}/gecmis")).json()
    duzeltme = [o for o in olaylar if o["tur"] == "DUZELTME"]
    assert len(duzeltme) == 1 and duzeltme[0]["gerekce"] == "Yanlış iade"
    assert next(o for o in olaylar if o["tur"] == "IADE")["geri_alindi"] is True
    # Sevki de geri al → HAZIRLANIYOR, cihazlar depoda HAZIR.
    r = await ist.post(f"{URL}/{k['id']}/geri-al", json={"gerekce": "Sevk yanlış girildi"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "HAZIRLANIYOR"
    assert await cihaz_durumlari(db, h["seri"]) == {"HAZIR": 2}
    assert await bakiye(db, h["toplu"], h["depo"], "HAZIR") == 4


async def test_geri_alma_sonraki_islem_varsa_409(ist, db) -> None:
    h = await hazir_kiralama(db, ist, seri_adet=1, on_ek="GS", sevk=True)
    k = h["k"]
    r = await ist.post(
        f"{URL}/{k['id']}/iade",
        json={
            "satirlar": [
                {
                    "tahsis_id": k["tahsisler"][0]["id"],
                    "sonuc": "IADE_ALINDI",
                    "depo_id": h["depo"].id,
                }
            ]
        },
    )
    assert r.status_code == 200
    r = await ist.post(
        f"{URL}/envanter/kontrol",
        json={"satirlar": [{"kiralik_id": h["cihazlar"][0], "sonuc": "UYGUN"}]},
    )
    assert r.status_code == 200
    r = await ist.post(f"{URL}/{k['id']}/geri-al", json={"gerekce": "Geç fark edildi"})
    assert r.status_code == 409, r.text
    assert "sonraki" in r.json()["detail"]
    assert (
        await db.scalar(
            select(func.count()).select_from(RentalEvent).where(RentalEvent.tur == "DUZELTME")
        )
        == 0
    )


async def test_kapanis_cihaz_musterideyken_409(ist, db) -> None:
    h = await hazir_kiralama(db, ist, toplu_adet=3, on_ek="KP", sevk=True)
    k = h["k"]
    r = await ist.post(f"{URL}/{k['id']}/kapat")
    assert r.status_code == 409
    assert "Müşteride 3" in r.json()["detail"]


async def test_tutanak_baglami_fiyatsiz_yalniz_tahsisli_taslak(ist, db) -> None:
    from app.clock import FakeClock
    from app.services.teknik_servis import kiralama as svc

    depo = await depo_ac(db, "TT-D1", birim="GUVENLIK")
    seri = await kiralik_urun_ac(db, "TT-SERI", seri=True)
    await stok_gir(ist, seri, depo, seriler=["T-1", "T-2", "T-3"])
    k = await kiralama_ac(ist, await musteri_ac(db), [(seri, 2)])
    await planla(ist, k)
    cihazlar = await seri_idleri(db, seri)
    await tahsis(ist, k, [{"kalem_id": kalem_id(k, seri), "kiralik_idler": cihazlar[:2]}])
    kayit = await db.get(Rental, k["id"])
    baglam = await svc.tutanak_baglami(db, kayit, tur="TESLIM", clock=FakeClock())
    assert baglam["taslak"] is True
    seriler = [s["seri"] for x in baglam["kalemler"] for s in x["satirlar"]]
    assert sorted(seriler) == ["T-1", "T-2"]  # T-3 tahsisli değil

    def anahtarlar(d):
        if isinstance(d, dict):
            for a, v in d.items():
                yield a
                yield from anahtarlar(v)
        elif isinstance(d, list):
            for v in d:
                yield from anahtarlar(v)

    yasak = {"fiyat", "tutar", "maliyet", "birim_fiyat", "list_price", "unit_cost"}
    assert not (set(anahtarlar(baglam)) & yasak)
    assert (await ist.post(f"{URL}/{k['id']}/sevk", json={})).status_code == 200
    await db.refresh(kayit)
    baglam = await svc.tutanak_baglami(db, kayit, tur="TESLIM", clock=FakeClock())
    assert baglam["taslak"] is False
    r = await ist.get(f"{URL}/{k['id']}/tutanak.pdf", params={"tur": "TESLIM"})
    assert r.status_code in (200, 503)  # Windows'ta PDF motoru olmayabilir
