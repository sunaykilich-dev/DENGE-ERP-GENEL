"""Teklif gönderimi ve PDF (TS-142, TS-143).

- Elle gönderildi: kanal + not zorunlu, onay kuralı `gonder` ile aynı,
  `quote_sends` günlüğü, sonrasında public link karar alır (E07-05).
- E-posta: en çok 3 alıcı, biçim doğrulaması, gönderene CC, yeniden gönderim
  günlükte ikinci satır, SMTP hatasında genel mesaj (sunucu adı/istisna
  metni yanıtta YOK) ve HATA satırı commit edilir (E07-06). Gerçek SMTP yok:
  `smtplib.SMTP` sahtesi.
- PDF: tüm kalemler, çok sayfa, Türkçe karakter, "Sayfa x/y", KDV dökümü,
  onaylayan, `-R1` numarası (E07-07/08) — `pypdf` ile metin çıkarılır.
"""

import hashlib
import io
from decimal import Decimal

import pytest
from servis_teklif_yardimci import KALEM, elle_gonder, kapat, musteri, onayli, oturum, teklif_ac
from sqlalchemy import select

from app.models import Quote, QuoteSend, QuoteVersion, User

pytestmark = pytest.mark.integration


@pytest.fixture
async def ortam(client, db, birimli_kullanici_ac):
    sef = await birimli_kullanici_ac("sef_g", "SERVIS_SEF", ["GUVENLIK"])
    sef.email = "sef@denge.example"
    await birimli_kullanici_ac("mudur", "SERVIS_YONETICI", ["GUVENLIK"])
    await db.commit()
    s, m = await oturum("sef_g"), await oturum("mudur")
    hesap = await musteri(db, email="musteri@ornek.example")
    yield {"sef": s, "mudur": m, "musteri": hesap}
    await kapat(s, m)


class _SahteSmtp:
    """`smtplib.SMTP` yerine; gönderilen mesajları toplar ya da hata fırlatır."""

    gonderilen: list = []
    hata: Exception | None = None

    def __init__(self, sunucu, port, timeout=None):
        if _SahteSmtp.hata is not None:
            raise _SahteSmtp.hata

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
async def smtp(db, monkeypatch):
    from app.services import mail
    from app.services import settings as ayar_svc

    await ayar_svc.set_many(
        db, {"smtp_host": "smtp.gizli-sunucu.local", "smtp_from": "teklif@denge.example"}, None
    )
    await db.commit()
    _SahteSmtp.gonderilen = []
    _SahteSmtp.hata = None
    monkeypatch.setattr(mail.smtplib, "SMTP", _SahteSmtp)
    # E-posta testleri PDF motorundan bağımsız: WeasyPrint sistem kitaplıkları
    # (Pango/Cairo) olmayan makinede de koşsun. PDF içeriği `TestPdf`'te.
    from app.services import quotes as teklif_svc

    async def _sahte_pdf(db, t, v):
        return b"%PDF-1.7 sahte " + f"{t.quote_no}-{v.version_no}".encode()

    monkeypatch.setattr(teklif_svc, "teklif_pdf", _sahte_pdf)
    return _SahteSmtp


async def _onayli_teklif(ortam, **kw):
    t = await teklif_ac(ortam["sef"], ortam["musteri"].id, **kw)
    await onayli(ortam["sef"], ortam["mudur"], t["id"])
    return t


async def _gonderimler(db, teklif_id):
    return list(
        (
            await db.scalars(
                select(QuoteSend).where(QuoteSend.quote_id == teklif_id).order_by(QuoteSend.id)
            )
        ).all()
    )


class TestElleGonderim:
    async def test_kanal_ve_not_zorunlu(self, ortam):
        t = await _onayli_teklif(ortam)
        yol = f"/api/teklifler/{t['id']}/elle-gonderildi"
        assert (await ortam["sef"].post(yol, json={"kanal": "FAKS", "not": "x"})).status_code == 422
        assert (await ortam["sef"].post(yol, json={"not": "elden verildi"})).status_code == 422
        assert (
            await ortam["sef"].post(yol, json={"kanal": "ELDEN", "not": " "})
        ).status_code == 400

    async def test_onaysiz_birimli_409(self, ortam, db):
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id)
        r = await ortam["sef"].post(
            f"/api/teklifler/{t['id']}/elle-gonderildi", json={"kanal": "KARGO", "not": "kargo"}
        )
        assert r.status_code == 409
        assert await _gonderimler(db, t["id"]) == []

    async def test_smtp_yokken_elle_gonderildi_ve_link_karar_alir(self, ortam, client, db):
        t = await _onayli_teklif(ortam)
        r = await elle_gonder(ortam["sef"], t["id"])
        assert r["status"] == "GONDERILDI"
        assert r["guncel"]["sent_channel"] == "ELDEN"
        assert r["guncel"]["sent_note"] == "Müşteriye elden teslim edildi"
        kayitlar = await _gonderimler(db, t["id"])
        assert len(kayitlar) == 1 and kayitlar[0].sonuc == "BASARILI"
        assert kayitlar[0].pdf_sha256 is None or len(kayitlar[0].pdf_sha256) == 64
        gecmis = (await ortam["sef"].get(f"/api/teklifler/{t['id']}/gecmis")).json()
        assert any(g["kanal"] == "ELDEN" and g["yeni_durum"] == "GONDERILDI" for g in gecmis)

        v = await db.get(QuoteVersion, r["guncel"]["id"])
        await db.refresh(v)
        karar = await client.post(
            f"/api/public/teklif/{v.public_token}/karar", json={"kabul": True}
        )
        assert karar.status_code == 200, karar.text


class TestEpostaGonderim:
    async def test_alici_kurallari(self, ortam, smtp):
        t = await _onayli_teklif(ortam)
        yol = f"/api/teklifler/{t['id']}/gonder"
        assert (await ortam["sef"].post(yol, json={"alicilar": ["abc@"]})).status_code == 422
        dort = [f"k{i}@ornek.example" for i in range(4)]
        assert (await ortam["sef"].post(yol, json={"alicilar": dort})).status_code == 400
        assert smtp.gonderilen == []

    async def test_cc_gunluk_sha_ve_yeniden_gonderim(self, ortam, smtp, db):
        t = await _onayli_teklif(ortam)
        yol = f"/api/teklifler/{t['id']}/gonder"
        r = await ortam["sef"].post(
            yol, json={"alicilar": ["a@ornek.example", "b@ornek.example"], "mesaj": "Merhaba"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "GONDERILDI"
        mesaj = smtp.gonderilen[0]
        assert mesaj["To"] == "a@ornek.example, b@ornek.example"
        assert mesaj["Cc"] == "sef@denge.example"
        ek = next(mesaj.iter_attachments()).get_content()
        kayitlar = await _gonderimler(db, t["id"])
        assert len(kayitlar) == 1
        assert kayitlar[0].pdf_sha256 == hashlib.sha256(ek).hexdigest()
        assert kayitlar[0].alicilar == ["a@ornek.example", "b@ornek.example"]

        # Yeniden gönderim: durum değişmez, günlükte ikinci satır.
        r2 = await ortam["sef"].post(yol, json={"alicilar": ["a@ornek.example"]})
        assert r2.status_code == 200 and r2.json()["status"] == "GONDERILDI"
        assert len(await _gonderimler(db, t["id"])) == 2
        liste = (await ortam["sef"].get(f"/api/teklifler/{t['id']}/gonderimler")).json()
        assert [g["sonuc"] for g in liste] == ["BASARILI", "BASARILI"]

    async def test_varsayilan_alici_musteri_epostasi(self, ortam, smtp):
        t = await _onayli_teklif(ortam)
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/gonder", json={})
        assert r.status_code == 200, r.text
        assert smtp.gonderilen[0]["To"] == "musteri@ornek.example"

    async def test_smtp_hatasi_genel_mesaj_ve_hata_satiri(self, ortam, smtp, db):
        smtp.hata = OSError("smtp.gizli-sunucu.local:587 bağlantı reddedildi (iç ayrıntı)")
        t = await _onayli_teklif(ortam)
        r = await ortam["sef"].post(f"/api/teklifler/{t['id']}/gonder", json={})
        assert r.status_code == 503
        govde = r.text
        assert "gizli-sunucu" not in govde and "587" not in govde and "ayrıntı" not in govde
        kayitlar = await _gonderimler(db, t["id"])
        assert len(kayitlar) == 1
        assert kayitlar[0].sonuc == "HATA" and kayitlar[0].hata_ozeti == "SMTP_BAGLANTI"
        q = await db.get(Quote, t["id"])
        await db.refresh(q)
        assert q.status == "ONAYLANDI"


class TestHakEdisMesaji:
    async def test_smtp_hatasi_ayrintiyi_sizdirmaz(self, db, smtp):
        """Hak ediş e-postası da aynı `_smtp_gonder`'den geçer (G4 kaynağında)."""
        from app.services import mail

        smtp.hata = OSError("smtp.gizli-sunucu.local:587 yanlış parola")
        with pytest.raises(mail.MailKapali) as exc:
            await mail.gonder(db, alici="x@ornek.example", konu="Döküm", govde="...")
        assert "gizli-sunucu" not in str(exc.value)
        assert exc.value.sinif == "SMTP_BAGLANTI"


class TestPdf:
    async def test_kirk_kalem_cok_sayfa_turkce_ve_sayfa_numarasi(self, ortam, db):
        pypdf = pytest.importorskip("pypdf")
        from app.services import quotes as svc

        kalemler = [
            {**KALEM, "description": f"Şişli İletişim Çözümleri – Güç Kaynağı {i:02d}"}
            for i in range(40)
        ]
        kalemler[0]["description"] = "Ç" * 10 + " " + "X" * 480  # 500 karakter, sarılır
        t = await teklif_ac(ortam["sef"], ortam["musteri"].id, kalemler=kalemler)
        await onayli(ortam["sef"], ortam["mudur"], t["id"])
        q = await db.get(Quote, t["id"])
        v = await db.get(QuoteVersion, q.current_version_id)
        await db.refresh(v)
        from app.services.pdf import PdfUretilemedi

        try:
            pdf = await svc.teklif_pdf(db, q, v)
        except PdfUretilemedi:
            pytest.skip("WeasyPrint sistem kitaplıkları bu makinede yok")
        okuyucu = pypdf.PdfReader(io.BytesIO(pdf), strict=True)
        sayfa = len(okuyucu.pages)
        assert sayfa >= 2
        metin = "\n".join(p.extract_text() for p in okuyucu.pages)
        duz = " ".join(metin.split())
        for i in range(1, 40):
            assert f"Güç Kaynağı {i:02d}" in duz, i
        assert "Şişli İletişim Çözümleri – Güç Kaynağı" in duz
        assert f"Sayfa 1/{sayfa}" in duz and f"Sayfa {sayfa}/{sayfa}" in duz
        mudur = await db.scalar(select(User).where(User.username == "mudur"))
        assert mudur.full_name in duz, "onaylayan basılmalı"

    async def test_kdv_dokumu_toplami_vat_total(self, ortam, db):
        from app.services import quotes as svc

        t = await teklif_ac(
            ortam["sef"],
            ortam["musteri"].id,
            kalemler=[{**KALEM, "vat_rate": 0.20}, {**KALEM, "unit_price": 333, "vat_rate": 0.10}],
        )
        q = await db.get(Quote, t["id"])
        v = await db.get(QuoteVersion, q.current_version_id)
        baglam = await svc.teklif_pdf_baglami(db, q, v)
        assert [d["oran"] for d in baglam["kdv_dokumu"]] == ["%20", "%10"]
        from app.models import QuoteLine

        satirlar = (await db.scalars(select(QuoteLine).where(QuoteLine.version_id == v.id))).all()
        dokum = svc.kdv_dokumu(list(satirlar))
        assert sum((d["kdv"] for d in dokum), Decimal("0")) == Decimal(str(v.vat_total))
        assert "onaylayan" not in baglam  # onaysız teklifte alan yok

    async def test_revizyon_numarasi(self, ortam, db):
        from app.services import quotes as svc

        t = await _onayli_teklif(ortam)
        await elle_gonder(ortam["sef"], t["id"])
        await ortam["sef"].post(f"/api/teklifler/{t['id']}/revize", json={"kalemler": [KALEM]})
        q = await db.get(Quote, t["id"])
        await db.refresh(q)
        v = await db.get(QuoteVersion, q.current_version_id)
        baglam = await svc.teklif_pdf_baglami(db, q, v)
        assert baglam["teklif_no_gosterim"] == f"{q.quote_no}-R1"
