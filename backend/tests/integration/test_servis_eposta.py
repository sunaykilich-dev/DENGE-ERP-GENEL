"""Servis e-posta bildirimi: tercih, giden kutusu, gönderim ve saklama (TS-200, E10-06).

Kabul ölçütleri:
(1) SMTP tanımsızken kutu BEKLIYOR kalır, `deneme=0`, görev hata değil bilgi yazar.
(2) Worker kaç tur koşarsa koşsun aynı bildirim aynı kişiye BİR satır/gönderim.
(3) Ayardaki deneme sayısına ulaşan satır BASARISIZ, `son_hata` dolu.
(4) `son_hata`, log ve kutuda SMTP parolası/kullanıcı adı yok.
(5) Gövdede fiyat/tutar/maliyet/₺ ve telefon yok.
(6) `anlik_eposta=false` kullanıcıya satır yok; e-postası boş kullanıcı özet
    satırında "e-postası olmayan alıcı" olarak sayılır.
Ayrıca: kapsam (başka birimin bildirimi gelmez), GERIYE_DONUK işe e-posta yok,
RBAC (tercih `servis.gor`, kutu/ayar `operasyon.yonet`), saklama/KVKK.
"""

import logging
import re
import smtplib
from datetime import UTC, date, datetime, timedelta

import pytest
from servis_yardimci import giris
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import ServiceAlert, ServiceMailOutbox, ServiceNotificationPref
from app.services import mail
from app.services import settings as ayar_svc
from app.services.teknik_servis import eposta

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)  # yerel 03:00
TS = "/api/teknik-servis"
PAROLA = "GizliParola!123"
SMTP_KULLANICI = "smtpkullanici"
YASAK_GOVDE = re.compile(r"fiyat|tutar|maliyet|₺|\+90|0532", re.IGNORECASE)


def _sla(bas_saat_once: float, sure_saat: int = 12, kaynak: str = "CANLI") -> dict:
    bas = AN - timedelta(hours=bas_saat_once)
    hedef = bas + timedelta(hours=sure_saat)
    return {
        "sla_baslangic_at": bas,
        "cozum_hedef_at": hedef,
        "cozum_hedef_ilk_at": hedef,
        "sla_kaynak": kaynak,
        "created_at": bas,
    }


class _SahteSMTP:
    """smtplib.SMTP yerine: gönderileni kaydeder ya da verilen hatayı atar."""

    gonderilen: list = []
    hata: Exception | None = None

    def __init__(self, host, port, timeout=None) -> None:
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a) -> bool:
        return False

    def starttls(self) -> None:
        pass

    def login(self, kullanici, parola) -> None:
        if _SahteSMTP.hata is not None:
            raise _SahteSMTP.hata

    def send_message(self, mesaj) -> None:
        _SahteSMTP.gonderilen.append(mesaj)


@pytest.fixture
def sahte_smtp(monkeypatch):
    _SahteSMTP.gonderilen = []
    _SahteSMTP.hata = None
    monkeypatch.setattr(mail.smtplib, "SMTP", _SahteSMTP)
    return _SahteSMTP


async def _smtp_tanimla(db) -> None:
    await ayar_svc.set_many(
        db,
        {
            "smtp_host": "smtp.ornek.test",
            "smtp_port": 587,
            "smtp_user": SMTP_KULLANICI,
            "smtp_password": PAROLA,
            "smtp_from": "erp@ornek.test",
        },
        None,
    )
    await db.commit()


async def _eposta_ac(db, saat: str = "02:00", deneme: int = 3) -> None:
    await ayar_svc.set_many(
        db,
        {
            "servis_eposta_acik": True,
            "servis_gunluk_ozet_saati": saat,
            "servis_eposta_deneme": deneme,
        },
        None,
    )
    await db.commit()


async def _kutu(db) -> list[ServiceMailOutbox]:
    stmt = (
        select(ServiceMailOutbox)
        .order_by(ServiceMailOutbox.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


@pytest.fixture
async def veri(client, db, kullanici_ac, birimli_kullanici_ac, servis_isi_ac):
    sef_a = await birimli_kullanici_ac("sef_a", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    sef_b = await birimli_kullanici_ac("sef_b", "SERVIS_SEF", ["HABERLESME"], saha_rolu="SEF")
    sef_c = await birimli_kullanici_ac("sef_c", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    tek = await birimli_kullanici_ac("tek", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN")
    mudur = await kullanici_ac("mudur", "SERVIS_YONETICI")
    await kullanici_ac("satis", "SATIS")
    for u, adres in ((sef_a, "sef.a@ornek.test"), (sef_b, "sef.b@ornek.test"),
                     (sef_c, "sef.c@ornek.test"), (mudur, "mudur@ornek.test")):  # fmt: skip
        u.email = adres
    db.add_all(
        [
            ServiceNotificationPref(user_id=sef_a.id, anlik_eposta=True, gunluk_ozet=True),
            ServiceNotificationPref(user_id=sef_b.id, anlik_eposta=True, gunluk_ozet=False),
            ServiceNotificationPref(user_id=sef_c.id, anlik_eposta=False, gunluk_ozet=False),
            ServiceNotificationPref(user_id=tek.id, anlik_eposta=True, gunluk_ozet=True),
        ]
    )
    await db.commit()
    so_a = await servis_isi_ac(durum="ISLEMDE", oncelik="KRITIK", atananlar=[tek], **_sla(13))
    so_b = await servis_isi_ac(birim="HABERLESME", durum="SAHADA", **_sla(20))
    so_geri = await servis_isi_ac(durum="ISLEMDE", **_sla(30, kaynak="GERIYE_DONUK"))
    alarmlar = {}
    for ad, so, kod in (
        ("a", so_a, "SLA_ASILDI"),
        ("a_risk", so_a, "SLA_RISK"),
        ("b", so_b, "SLA_ASILDI"),
        ("geri", so_geri, "SLA_ASILDI"),
    ):
        alarm = ServiceAlert(
            kod=kod,
            service_order_id=so.id,
            onem="KRITIK",
            baslik=f"{so.so_no}: test",
            acilis_at=AN,
        )
        db.add(alarm)
        alarmlar[ad] = alarm
    await db.commit()
    return {
        "sef_a": sef_a,
        "sef_b": sef_b,
        "sef_c": sef_c,
        "tek": tek,
        "mudur": mudur,
        "so_a": so_a,
        "so_b": so_b,
        "so_geri": so_geri,
        "alarm": alarmlar,
    }


async def test_kapali_iken_satir_uretilmez(db, veri) -> None:
    sonuc = await eposta.kuyruga_al(db, FakeClock())
    await db.commit()
    assert sonuc == {"kapali": True}
    assert await _kutu(db) == []


async def test_kuyruk_kapsam_tekil_geriye_donuk_ve_eposta_yok(db, veri) -> None:
    """Kabul (2)(6) + kapsam + GERIYE_DONUK: üç tur → aynı satırlar."""
    await _eposta_ac(db)
    saat = FakeClock()
    ilk = await eposta.kuyruga_al(db, saat)
    await db.commit()
    assert ilk == {"anlik": 2, "ozet": 1, "eposta_yok": 1}
    for _ in range(2):
        tekrar = await eposta.kuyruga_al(db, saat)
        await db.commit()
        assert tekrar == {"anlik": 0, "ozet": 0, "eposta_yok": 1}
    kutu = await _kutu(db)
    anlik = {(k.user_id, k.alert_id) for k in kutu if k.tur == "ANLIK"}
    assert anlik == {
        (veri["sef_a"].id, veri["alarm"]["a"].id),
        (veri["sef_b"].id, veri["alarm"]["b"].id),
    }
    ozet = [k for k in kutu if k.tur == "GUNLUK_OZET"]
    assert [(k.user_id, k.ozet_gunu) for k in ozet] == [(veri["sef_a"].id, date(2026, 1, 1))]
    # Özet kapsamlıdır: kendi biriminin işi var, başka birimin işi yok.
    assert veri["so_a"].so_no in ozet[0].govde
    assert veri["so_b"].so_no not in ozet[0].govde
    assert "SLA aşıldı: 1" in ozet[0].govde
    for k in kutu:
        assert k.durum == "BEKLIYOR" and k.deneme == 0
        assert not YASAK_GOVDE.search(k.govde), k.govde
        assert veri["so_geri"].so_no not in k.govde
    assert all(k.user_id not in (veri["sef_c"].id, veri["mudur"].id) for k in kutu)


async def test_ozet_saati_gelmeden_ozet_yok(db, veri) -> None:
    await _eposta_ac(db, saat="23:00")
    sonuc = await eposta.kuyruga_al(db, FakeClock())
    await db.commit()
    assert sonuc["ozet"] == 0 and sonuc["anlik"] == 2


async def test_smtp_tanimsizken_kutuya_dokunulmaz(db, veri, caplog) -> None:
    """Kabul (1): BEKLIYOR, deneme=0; görev bilgi satırı döner, hata loglamaz."""
    await _eposta_ac(db)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            ozet = await eposta.gorev(db, FakeClock())
    assert ozet.startswith("BİLGİ: SMTP tanımlı değil")
    assert "e-postası olmayan alıcı=1" in ozet
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    kutu = await _kutu(db)
    assert len(kutu) == 3
    assert all(k.durum == "BEKLIYOR" and k.deneme == 0 and k.son_hata is None for k in kutu)


async def test_hata_basarisiz_ve_parola_sizmaz(db, veri, sahte_smtp, caplog) -> None:
    """Kabul (3)(4): 3 hatalı denemede BASARISIZ; parola/kullanıcı adı hiçbir yerde yok."""
    await _eposta_ac(db, deneme=3)
    await _smtp_tanimla(db)
    sahte_smtp.hata = smtplib.SMTPAuthenticationError(
        535, f"5.7.8 {SMTP_KULLANICI} {PAROLA} rejected".encode()
    )
    saat = FakeClock()
    with caplog.at_level(logging.DEBUG):
        for tur in range(3):
            await eposta.gorev(db, saat)
            kutu = await _kutu(db)
            assert all(k.deneme == tur + 1 for k in kutu)
    kutu = await _kutu(db)
    assert kutu and all(k.durum == "BASARISIZ" for k in kutu)
    for k in kutu:
        assert k.son_hata and "SMTP_KIMLIK" in k.son_hata
        assert "SMTPAuthenticationError" in k.son_hata and "smtp.ornek.test:587" in k.son_hata
        for alan in (k.son_hata, k.govde, k.konu, k.alici):
            assert PAROLA not in alan and SMTP_KULLANICI not in alan
    assert PAROLA not in caplog.text and SMTP_KULLANICI not in caplog.text
    # BASARISIZ satır bir daha denenmez.
    await eposta.gorev(db, saat)
    assert all(k.deneme == 3 for k in await _kutu(db))
    assert sahte_smtp.gonderilen == []


async def test_basarili_gonderim_bir_kez(db, veri, sahte_smtp) -> None:
    """Kabul (2)(5): her satır bir kez gider; gövde fiyatsız ve bağlantılı."""
    await _eposta_ac(db)
    await _smtp_tanimla(db)
    saat = FakeClock()
    for _ in range(3):
        await eposta.gorev(db, saat)
    assert len(sahte_smtp.gonderilen) == 3
    alicilar = sorted(m["To"] for m in sahte_smtp.gonderilen)
    assert alicilar == ["sef.a@ornek.test", "sef.a@ornek.test", "sef.b@ornek.test"]
    kutu = await _kutu(db)
    assert all(k.durum == "GONDERILDI" and k.gonderildi_at == AN for k in kutu)
    anlik_a = next(
        m for m in sahte_smtp.gonderilen
        if m["To"] == "sef.a@ornek.test" and veri["so_a"].so_no in m["Subject"]
    )  # fmt: skip
    govde = anlik_a.get_content()
    assert f"/servis-isleri/{veri['so_a'].id}" in govde
    assert "Öncelik: KRITIK" in govde and "Güvenlik Sistemleri" in govde
    assert not YASAK_GOVDE.search(govde)


async def test_kapanan_bildirim_ve_pasif_kullanici_dusurulur(db, veri, sahte_smtp) -> None:
    await _eposta_ac(db, saat="23:00")
    saat = FakeClock()
    await eposta.kuyruga_al(db, saat)
    await db.commit()
    alarm = veri["alarm"]["a"]
    alarm.kapanis_at = AN
    alarm.kapanis_nedeni = "KOSUL_KALKTI"
    veri["sef_b"].is_active = False
    await db.commit()
    await _smtp_tanimla(db)
    sonuc = await eposta.gonder_bekleyenler(db, saat)
    assert sonuc["dusurulen"] == 2 and sonuc["gonderilen"] == 0
    assert sahte_smtp.gonderilen == []
    assert await _kutu(db) == []


async def test_saklama_temizligi(db, veri) -> None:
    """KVKK: süresi dolan sonuçlanmış satır ve pasif kullanıcının kutusu silinir."""
    eski = AN - timedelta(days=200)
    db.add_all(
        [
            ServiceMailOutbox(
                tur="GUNLUK_OZET", user_id=veri["sef_a"].id, ozet_gunu=date(2025, 6, 1),
                alici="sef.a@ornek.test", konu="k", govde="g", durum="GONDERILDI",
                gonderildi_at=eski, created_at=eski,
            ),
            ServiceMailOutbox(
                tur="GUNLUK_OZET", user_id=veri["sef_a"].id, ozet_gunu=date(2025, 12, 31),
                alici="sef.a@ornek.test", konu="k", govde="g", durum="BASARISIZ",
                deneme=3, created_at=AN - timedelta(days=1),
            ),
            ServiceMailOutbox(
                tur="GUNLUK_OZET", user_id=veri["sef_b"].id, ozet_gunu=date(2025, 12, 31),
                alici="sef.b@ornek.test", konu="k", govde="g", created_at=AN,
            ),
        ]
    )  # fmt: skip
    veri["sef_b"].is_active = False
    await db.commit()
    silinen = await eposta.temizle(db, FakeClock())
    await db.commit()
    assert silinen == 2
    kalan = await _kutu(db)
    assert [(k.user_id, k.durum) for k in kalan] == [(veri["sef_a"].id, "BASARISIZ")]


# --- Uçlar -------------------------------------------------------------------------------


async def test_tercihlerim_rbac_ve_yalniz_kendi_satiri(client, db, veri) -> None:
    await giris(client, "satis")
    assert (await client.get(f"{TS}/bildirim-tercihlerim")).status_code == 403
    r = await client.put(
        f"{TS}/bildirim-tercihlerim", json={"anlik_eposta": True, "gunluk_ozet": True}
    )
    assert r.status_code == 403

    await giris(client, "mudur")
    r = await client.get(f"{TS}/bildirim-tercihlerim")
    assert r.status_code == 200, r.text
    assert r.json()["anlik_eposta"] is False and r.json()["eposta_tanimli"] is True
    r = await client.put(
        f"{TS}/bildirim-tercihlerim", json={"anlik_eposta": True, "gunluk_ozet": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["anlik_eposta"] is True and r.json()["gunluk_ozet"] is False
    # Yalnız kendi satırı: başka kişinin tercihi değişmedi.
    sef_a = await db.get(ServiceNotificationPref, veri["sef_a"].id, populate_existing=True)
    assert (sef_a.anlik_eposta, sef_a.gunluk_ozet) == (True, True)
    mudur = await db.get(ServiceNotificationPref, veri["mudur"].id, populate_existing=True)
    assert (mudur.anlik_eposta, mudur.gunluk_ozet) == (True, False)
    toplam = await db.scalar(select(func.count()).select_from(ServiceNotificationPref))
    assert toplam == 5


async def test_eposta_kutusu_ve_ayarlar(client, db, veri) -> None:
    await _eposta_ac(db)
    await _smtp_tanimla(db)
    await eposta.kuyruga_al(db, FakeClock())
    await db.commit()

    await giris(client, "sef_a")  # operasyon.yonet yok
    assert (await client.get(f"{TS}/bildirimler/eposta-kutusu")).status_code == 403
    assert (await client.get(f"{TS}/bildirimler/eposta-ayarlari")).status_code == 403
    r = await client.put(f"{TS}/bildirimler/eposta-ayarlari", json={"servis_eposta_acik": False})
    assert r.status_code == 403

    await giris(client, "mudur")
    r = await client.get(f"{TS}/bildirimler/eposta-kutusu", params={"durum": "BEKLIYOR"})
    assert r.status_code == 200, r.text
    assert int(r.headers["X-Toplam-Kayit"]) == 3
    assert all("govde" not in s for s in r.json())
    r = await client.get(f"{TS}/bildirimler/eposta-kutusu", params={"tur": "GUNLUK_OZET"})
    assert int(r.headers["X-Toplam-Kayit"]) == 1
    assert (
        await client.get(f"{TS}/bildirimler/eposta-kutusu", params={"durum": "YOK"})
    ).status_code == 400

    r = await client.get(f"{TS}/bildirimler/eposta-ayarlari")
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["servis_eposta_acik"] is True and govde["smtp_tanimli"] is True
    assert PAROLA not in r.text and SMTP_KULLANICI not in r.text
    r = await client.put(
        f"{TS}/bildirimler/eposta-ayarlari",
        json={"servis_eposta_acik": False, "servis_gunluk_ozet_saati": "08:15"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["servis_eposta_acik"] is False
    assert r.json()["servis_gunluk_ozet_saati"] == "08:15"
    r = await client.put(
        f"{TS}/bildirimler/eposta-ayarlari", json={"servis_gunluk_ozet_saati": "25:00"}
    )
    assert r.status_code == 400
    assert (await client.put(f"{TS}/bildirimler/eposta-ayarlari", json={})).status_code == 400
