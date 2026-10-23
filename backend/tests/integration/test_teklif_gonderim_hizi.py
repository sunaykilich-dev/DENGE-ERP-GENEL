"""Teklif e-posta gönderim hız sınırı (TS-215, E07-25).

Kullanıcı başına dakikada 10 e-posta gönderimi; 11.si 429 ve hiçbir şey
yazılmaz (SMTP'ye gidilmez, günlük satırı açılmaz). Pencere Clock ile
ölçülür: FakeClock 61 saniye ilerletilince yeniden 200. Sınır kullanıcı
başınadır (başka kullanıcı etkilenmez) ve ayarla değişir. Gönderilen PDF'in
SHA-256'sı günlükte (E07-09) `test_servis_teklif_gonderim.py` ile sınanır.
"""

import pytest
from servis_teklif_yardimci import kapat, musteri, onayli, oturum, teklif_ac
from sqlalchemy import func, select

from app.models import QuoteSend

pytestmark = pytest.mark.integration


class _SahteSmtp:
    gonderilen: list = []

    def __init__(self, sunucu, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, mesaj):
        _SahteSmtp.gonderilen.append(mesaj)


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac, monkeypatch):
    from app.services import mail
    from app.services import quotes as teklif_svc
    from app.services import settings as ayar_svc

    await birimli_kullanici_ac("hiz_sef", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("hiz_sef2", "SERVIS_SEF", ["GUVENLIK"])
    await birimli_kullanici_ac("hiz_mudur", "SERVIS_YONETICI", ["GUVENLIK"])
    await ayar_svc.set_many(
        db, {"smtp_host": "smtp.test.local", "smtp_from": "teklif@denge.example"}, None
    )
    await db.commit()
    _SahteSmtp.gonderilen = []
    monkeypatch.setattr(mail.smtplib, "SMTP", _SahteSmtp)

    async def _sahte_pdf(db, t, v):
        return b"%PDF-1.7 sahte " + f"{t.quote_no}-{v.version_no}".encode()

    monkeypatch.setattr(teklif_svc, "teklif_pdf", _sahte_pdf)
    s, s2, m = await oturum("hiz_sef"), await oturum("hiz_sef2"), await oturum("hiz_mudur")
    hesap = await musteri(db, email="musteri@ornek.example")
    t = await teklif_ac(s, hesap.id)
    await onayli(s, m, t["id"])
    yield {"sef": s, "sef2": s2, "teklif": t, "clock": client.clock}
    await kapat(s, s2, m)


async def _gonder(ist, teklif_id):
    return await ist.post(
        f"/api/teklifler/{teklif_id}/gonder", json={"alicilar": ["a@ornek.example"]}
    )


async def _satir_sayisi(db) -> int:
    return await db.scalar(select(func.count()).select_from(QuoteSend))


async def test_dakikada_onbirinci_gonderim_429(ortam, db):
    tid = ortam["teklif"]["id"]
    for i in range(10):
        r = await _gonder(ortam["sef"], tid)
        assert r.status_code == 200, (i, r.text)
        ortam["clock"].advance(seconds=1)
    once = await _satir_sayisi(db)
    smtp_once = len(_SahteSmtp.gonderilen)

    r = await _gonder(ortam["sef"], tid)
    assert r.status_code == 429
    assert "bir dakika sonra" in r.json()["detail"]
    assert await _satir_sayisi(db) == once, "429'da günlük satırı yazıldı"
    assert len(_SahteSmtp.gonderilen) == smtp_once, "429'da SMTP'ye gidildi"

    # Başka kullanıcı etkilenmez (sınır kullanıcı başına).
    assert (await _gonder(ortam["sef2"], tid)).status_code == 200

    # İlk gönderimden 61 sn sonra pencere boşalır.
    ortam["clock"].advance(seconds=52)
    assert (await _gonder(ortam["sef"], tid)).status_code == 200


async def test_sinir_ayardan_gelir(ortam, db):
    from app.services import settings as ayar_svc

    await ayar_svc.set_many(db, {"teklif_gonderim_dakika_limiti": 2}, None)
    await db.commit()
    tid = ortam["teklif"]["id"]
    assert (await _gonder(ortam["sef"], tid)).status_code == 200
    assert (await _gonder(ortam["sef"], tid)).status_code == 200
    assert (await _gonder(ortam["sef"], tid)).status_code == 429


async def test_elle_gonderim_sinira_sayilmaz(ortam, db):
    """Hız sınırı SMTP içindir; elden/kargo işareti e-posta göndermez."""
    from app.services import settings as ayar_svc

    await ayar_svc.set_many(db, {"teklif_gonderim_dakika_limiti": 1}, None)
    await db.commit()
    tid = ortam["teklif"]["id"]
    r = await ortam["sef"].post(
        f"/api/teklifler/{tid}/elle-gonderildi", json={"kanal": "ELDEN", "not": "elden verildi"}
    )
    assert r.status_code == 200, r.text
    assert (await _gonder(ortam["sef"], tid)).status_code == 200
    assert (await _gonder(ortam["sef"], tid)).status_code == 429
