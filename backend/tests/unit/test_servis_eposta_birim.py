"""Servis e-postası saf yardımcıları ve "Planlı Bakım" ad ayrımı (TS-199, TS-200).

DB'siz: SMTP yapılandırma kararı, hata metninde sır olmaması, gövde içeriği,
worker kaydı ve mobilite `BAKIM` iş emri türü ile teknik servis "Planlı
Bakım"ın ekranda ayrı adla görünmesi (E04-D05).
"""

import re
import smtplib
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from app import worker
from app.models import ServiceOrder
from app.models.workorder import IS_EMRI_TIPLERI
from app.services import mail
from app.services.teknik_servis import eposta, is_emirleri

KOK = Path(__file__).resolve().parents[3]


def test_yapilandirildi_mi() -> None:
    assert not mail.yapilandirildi_mi({})
    assert not mail.yapilandirildi_mi({"smtp_host": "s", "smtp_from": ""})
    assert mail.yapilandirildi_mi({"smtp_host": "s", "smtp_user": "u"})
    assert mail.yapilandirildi_mi({"smtp_host": "s", "smtp_from": "erp@x"})
    assert mail.sunucu_etiketi({"smtp_host": "s"}) == "s:587"


def test_hata_metni_sir_icermez() -> None:
    ayar = {"smtp_host": "smtp.x", "smtp_port": 25, "smtp_user": "kim", "smtp_password": "sir!"}
    try:
        try:
            raise smtplib.SMTPAuthenticationError(535, b"kim sir! reddedildi")
        except smtplib.SMTPAuthenticationError as asil:
            raise mail.MailKapali(mail.GENEL_HATA_MESAJI, "SMTP_KIMLIK") from asil
    except mail.MailKapali as exc:
        metin = eposta.hata_metni(exc, ayar)
    assert metin == "SMTP_KIMLIK SMTPAuthenticationError smtp.x:25"
    assert "sir!" not in metin and "kim " not in metin


def test_anlik_icerik_fiyatsiz_ve_baglantili() -> None:
    hedef = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    so = ServiceOrder(
        id=7,
        so_no="SRV-260101-000007",
        birim="GUVENLIK",
        oncelik="YUKSEK",
        status="ISLEMDE",
        cozum_hedef_at=hedef,
        mudahale_hedef_at=hedef - timedelta(hours=4),
    )
    konu, govde = eposta.anlik_icerik("SLA_ASILDI", so, "Örnek A.Ş.")
    assert "SRV-260101-000007" in konu
    assert "Hedef: 01.01.2026 12:00" in govde  # yerel saat
    assert "Müşteri: Örnek A.Ş." in govde and "/servis-isleri/7" in govde
    assert not re.search(r"fiyat|tutar|maliyet|₺|telefon", govde, re.IGNORECASE)
    _, govde = eposta.anlik_icerik("MUDAHALE_ASILDI", so, None)
    assert "Hedef: 01.01.2026 08:00" in govde and "Müşteri: —" in govde


def test_ozet_saati_ayristirma() -> None:
    assert eposta._ozet_saati("07:30") == time(7, 30)
    assert eposta._ozet_saati(None) == time(7, 30)
    assert eposta._ozet_saati("bozuk") == time(7, 30)


def test_worker_gorevi_kayitli() -> None:
    adlar = {g.ad: g for g in worker.GOREVLER}
    assert adlar["servis-eposta"].periyot == timedelta(minutes=5)


def test_planli_bakim_mobilite_bakimdan_ayri_adla() -> None:
    """E04-D05: mobilite iş emri türü `BAKIM` değişmez (raporlar aynı kalır); teknik
    servis tarafı "Planlı Bakım" adını kullanır, menüde yalın "Bakım" yoktur."""
    assert "BAKIM" in IS_EMRI_TIPLERI
    assert is_emirleri.KATEGORI_ADLARI["PLANLI_BAKIM"] == "Planlı Bakım"
    assert is_emirleri.TUR_ADLARI["PB"] == "Planlı Bakım"
    menu = (KOK / "frontend" / "src" / "components" / "AppLayout.tsx").read_text(encoding="utf-8")
    assert 'label: "Planlı Bakım"' in menu
    assert 'label: "Bakım"' not in menu
