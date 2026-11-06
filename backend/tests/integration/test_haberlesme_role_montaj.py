"""Haberleşme saha işi: işin niteliği ve röle montaj bilgileri (KARARLAR §10).

Kullanıcı isteği (2026-11-06):
- Haberleşme saha işi açılırken işin niteliği çoktan seçmeli ve zorunlu.
- "Repeater Montaj Bilgileri" kütüğünün sütunları yalnız kurulum/montaj
  işlerinde zorunlu; eksikse iş kapatılamaz (her kapatma yolu tek kapıdan).
- Moda bağlı alanlar (analog/dijital, simpleks) yalnız ilgili modda aranır.
- Sorumlu kişi bilgisi denetim izine yazılmaz.
"""

import pytest
from servis_yardimci import acilis, giris, musteri, tazele
from sqlalchemy import select

from app.models import AuditLog
from app.services.teknik_servis import role_montaj

pytestmark = pytest.mark.integration

IS = "/api/teknik-servis/isler"

TAM = {
    "alt_yapi_bildirim_durumu": "BİLDİRİM YAPILDI",
    "kurulum_tarihi": "2026-11-06",
    "yetki_belgesi": "DÜZ. TRH. 21.06.2018",
    "btk_bildirim": "26.06.2019 B-ALT-34-002",
    "firma_adi": "Deneme Güvenlik",
    "proje_adi": "Deneme AVM",
    "role_sahiplik": "ABONEYE AİT",
    "adres": "Deneme Mah. 1",
    "koordinat": "40°56'14\"N 29°19'32\"E",
    "yerel_bolgesel": "MARMARA BÖLGESEL",
    "sorumlu_ad": "Saha Sorumlusu",
    "sorumlu_telefon": "+905321112233",
    "role_kurulum_yeri": "-2 elektrik şaftı",
    "anten_sayisi": "2",
    "anten_tipi": "OMNİ",
    "anten_yerleri": "Çatı",
    "kablo_tipi": "RG213",
    "kablo_metraji": 70,
    "diger_malzemeler": "Yok",
    "alt_yapi_durumu": "RÖLE",
    "role_marka_model": "HYTERA RD625",
    "role_seri_no": "18908A1229",
    "yazilim_versiyon": "V1.0",
    "montaj_yapan": "Teknisyen",
    "role_tx": "427,1125",
    "role_rx": "417.1125",
    "calisma_modu": "DIJITAL",
    "role_dijital_cc": "1",
    "role_dijital_slot": "1",
    "role_dijital_grup": "1",
    "telsiz_cc": "1",
    "telsiz_slot": "1",
    "telsiz_grup": "1",
    "simpleks": "YOK",
    "el_telsizi": 10,
    "arac_telsizi": 0,
    "sabit_telsiz": 1,
}


def test_eksik_alan_kurali_moda_baglidir() -> None:
    assert role_montaj.eksik_alanlar(TAM) == []
    # Analog modda analog ton ister, dijital alanlar aranmaz.
    analog = {k: v for k, v in TAM.items() if "dijital" not in k and "telsiz_" not in k}
    analog["calisma_modu"] = "ANALOG"
    assert role_montaj.eksik_alanlar(analog) == ["Röle analog mod RX / TX ton"]
    # Simpleks VAR: frekans ve moda uyan simpleks alanları zorunlu.
    simp = {**TAM, "simpleks": "VAR"}
    assert role_montaj.eksik_alanlar(simp) == [
        "Simpleks frekans (MHz)",
        "Simpleks dijital CC",
        "Simpleks dijital slot no",
        "Simpleks dijital grup no",
    ]
    # E-posta isteğe bağlı; toplam telsiz hesaplanır.
    assert "Sorumlu kişi e-posta" not in role_montaj.eksik_alanlar({})
    assert role_montaj.toplam_telsiz(TAM) == 11


def test_girdi_bicim_dogrulamasi() -> None:
    from app.services.teknik_servis.kancalar import ServisGirdiHatasi

    for kotu in ({"role_tx": "çok"}, {"anten_sayisi": "iki"}, {"calisma_modu": "X"}, {"yok": 1}):
        with pytest.raises(ServisGirdiHatasi):
            role_montaj.temizle(kotu)
    assert role_montaj.temizle({"role_tx": "427,1125", "anten_tipi": " "}) == {
        "role_tx": "427.1125"
    }


async def test_haberlesme_saha_isinde_nitelik_zorunlu_ve_coktan_secmeli(
    client, db, birimli_kullanici_ac
) -> None:
    await birimli_kullanici_ac("op_hab", "SERVIS_OPERASYON", ["HABERLESME"])
    hesap = await musteri(db)
    await giris(client, "op_hab")
    govde = acilis(hesap, birim="HABERLESME", tur="ARIZA", konu="Röle sinyal vermiyor")
    r = await client.post(IS, json=govde)
    assert r.status_code == 400 and "niteliği" in r.json()["detail"]
    r = await client.post(IS, json={**govde, "nitelikler": ["UCAN"]})
    assert r.status_code == 400
    r = await client.post(IS, json={**govde, "nitelikler": ["MONTAJ", "ARIZA", "MONTAJ"]})
    assert r.status_code == 201, r.text
    is_ = r.json()
    assert is_["nitelikler"] == ["MONTAJ", "ARIZA"]
    assert is_["nitelik_sorulur"] is True
    assert is_["role_montaj_eksik"]  # montaj seçildi → bilgiler aranır

    # Güvenlikte nitelik sorulmaz; gönderilirse 400.
    await birimli_kullanici_ac("op_guv", "SERVIS_OPERASYON", ["GUVENLIK"])
    await giris(client, "op_guv")
    r = await client.post(IS, json=acilis(hesap))
    assert r.status_code == 201 and r.json()["nitelikler"] is None
    r = await client.post(IS, json=acilis(hesap, nitelikler=["KURULUM"]))
    assert r.status_code == 400


async def test_kurulum_isi_montaj_bilgisi_eksikken_kapanmaz(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("mud_hab", "SERVIS_YONETICI", ["HABERLESME"])
    so = await servis_isi_ac(
        birim="HABERLESME", tur="KURULUM", durum="TAMAMLANDI", nitelikler=["KURULUM"]
    )
    await db.commit()
    await giris(client, "mud_hab")

    r = await client.get(f"{IS}/{so.id}/role-montaj")
    assert r.status_code == 200
    d = r.json()
    assert d["uygulanir"] is True and d["kayitli"] is False
    assert d["degerler"]["firma_adi"]  # işin müşterisinden önerildi

    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 409 and "röle montaj" in r.json()["detail"]

    # Kısmi kayıt serbest; kapanış yine engelli.
    kismi = {k: v for k, v in TAM.items() if k != "btk_bildirim"}
    r = await client.put(f"{IS}/{so.id}/role-montaj", json={"degerler": kismi})
    assert r.status_code == 200, r.text
    assert r.json()["eksikler"] == ["BTK bildirim tarih / sayı"]
    surum = r.json()["version"]
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 409 and "BTK bildirim" in r.json()["detail"]

    # Eski sürümle yazma 409; doğru sürümle tamamlanır ve iş kapanır.
    r = await client.put(f"{IS}/{so.id}/role-montaj", json={"degerler": TAM, "version": 99})
    assert r.status_code == 409
    r = await client.put(f"{IS}/{so.id}/role-montaj", json={"degerler": TAM, "version": surum})
    assert r.status_code == 200 and r.json()["eksikler"] == []
    assert r.json()["toplam_telsiz"] == 11
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 200, r.text
    assert (await tazele(db, so)).status == "KAPATILDI"

    # Denetim izinde sorumlu kişi bilgisi yok.
    kayitlar = (
        await db.scalars(select(AuditLog).where(AuditLog.entity == "service_role_montaj"))
    ).all()
    assert kayitlar
    for k in kayitlar:
        assert "sorumlu_telefon" not in (k.new_value or {})
        assert "sorumlu_ad" not in (k.new_value or {})

    # Kapanmış işte değiştirilemez.
    r = await client.put(f"{IS}/{so.id}/role-montaj", json={"degerler": TAM, "version": surum + 1})
    assert r.status_code == 409


async def test_kurulum_montaj_disi_haberlesme_isi_serbest_kapanir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("mud_hab2", "SERVIS_YONETICI", ["HABERLESME"])
    ariza = await servis_isi_ac(
        birim="HABERLESME", tur="ARIZA", durum="TAMAMLANDI", nitelikler=["ARIZA", "PROGRAMLAMA"]
    )
    await db.commit()
    await giris(client, "mud_hab2")
    r = await client.get(f"{IS}/{ariza.id}")
    assert r.json()["role_montaj_eksik"] is None
    r = await client.post(f"{IS}/{ariza.id}/kapat", json={})
    assert r.status_code == 200, r.text


async def test_nitelik_duzeltilince_kural_degisir(
    client, db, birimli_kullanici_ac, servis_isi_ac
) -> None:
    await birimli_kullanici_ac("mud_hab3", "SERVIS_YONETICI", ["HABERLESME"])
    so = await servis_isi_ac(
        birim="HABERLESME", tur="ARIZA", durum="TAMAMLANDI", nitelikler=["ARIZA"]
    )
    await db.commit()
    await giris(client, "mud_hab3")
    r = await client.patch(f"{IS}/{so.id}", json={"version": so.version, "nitelikler": []})
    assert r.status_code == 400
    r = await client.patch(
        f"{IS}/{so.id}",
        json={
            "version": so.version,
            "nitelikler": ["ARIZA", "MONTAJ"],
            "gerekce": "Röle montajı da yapıldı",
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{IS}/{so.id}/kapat", json={})
    assert r.status_code == 409 and "röle montaj" in r.json()["detail"]
