"""E-posta gönderimi (SMTP).

SMTP ayarları boşsa gönderim SESSİZCE ATLANMAZ — `MailKapali` yükseltilir ve
çağıran kullanıcıya "e-posta ayarları tanımlı değil" der. Sessiz atlama, hak
ediş dökümünün gittiğini sanıp gitmemesi demek olurdu.

**Hata ayrıntısı yalnız sunucu logunda (E07-06, G4):** eski mesaj SMTP sunucu
adını, portu ve istisna metnini KULLANICIYA döndürüyordu (hak ediş gönderimi
dahil). Kullanıcı artık genel bir mesaj ve sınıflandırılmış bir kod
(`MailKapali.sinif`: SMTP_KAPALI, SMTP_BAGLANTI, SMTP_KIMLIK, SMTP_RED) görür;
ayrıntı `logger.warning` ile loga yazılır. İmza geriye uyumludur: `alici` tek
adres ya da liste olabilir, `cc` isteğe bağlıdır; hak ediş çağrıları değişmez.
"""

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import settings as ayar_svc

logger = logging.getLogger(__name__)

GENEL_HATA_MESAJI = (
    "E-posta gönderilemedi. Parametreler → Bildirim ayarlarını kontrol edin "
    "veya 'Elle gönderildi' kullanın."
)


class MailKapali(RuntimeError):
    """SMTP tanımsız ya da gönderim başarısız. `sinif` kullanıcıya gösterilebilir
    sınıflandırmadır; mesaj sunucu adı/port/istisna metni TAŞIMAZ."""

    def __init__(self, mesaj: str, sinif: str = "SMTP_KAPALI") -> None:
        super().__init__(mesaj)
        self.sinif = sinif


def _hata_sinifi(exc: BaseException) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP_KIMLIK"
    if isinstance(exc, smtplib.SMTPRecipientsRefused | smtplib.SMTPSenderRefused):
        return "SMTP_RED"
    if isinstance(exc, smtplib.SMTPResponseException):
        return "SMTP_RED"
    return "SMTP_BAGLANTI"


def _smtp_gonder(ayarlar: dict, mesaj: EmailMessage) -> None:
    """Asıl SMTP oturumu. Hata ayrıntısı YALNIZ loga; dışarıya genel mesaj."""
    sunucu = ayarlar.get("smtp_host")
    port = int(ayarlar.get("smtp_port") or 587)
    try:
        with smtplib.SMTP(sunucu, port, timeout=20) as s:
            s.starttls()
            if ayarlar.get("smtp_user"):
                s.login(ayarlar["smtp_user"], ayarlar.get("smtp_password") or "")
            s.send_message(mesaj)
    except (OSError, smtplib.SMTPException) as exc:
        # YANLIŞ YAPILANDIRILMIŞ SMTP bir kullanıcı hatasıdır, çökme değil.
        # Ulaşılamayan sunucu/yanlış parola `MailKapali` yakalanmadığı için
        # 500 veriyordu; kullanıcı ayarı düzeltmesi gerektiğini göremiyordu.
        sinif = _hata_sinifi(exc)
        logger.warning("SMTP gönderimi başarısız (%s:%s, %s): %s", sunucu, port, sinif, exc)
        raise MailKapali(GENEL_HATA_MESAJI, sinif) from exc


def yapilandirildi_mi(ayarlar: dict) -> bool:
    """SMTP gönderimi için zorunlu ayarlar dolu mu (sunucu + gönderen)?

    Saf yardımcı (E10-06): servis e-posta kuyruğu SMTP tanımsızken satırlara
    HİÇ dokunmaz (deneme artmaz); karar `gonder` ile aynı ölçütten verilir.
    """
    return bool(ayarlar.get("smtp_host")) and bool(
        ayarlar.get("smtp_from") or ayarlar.get("smtp_user")
    )


def sunucu_etiketi(ayarlar: dict) -> str:
    """`sunucu:port` — hata kaydına yazılabilecek TEK SMTP bilgisi (parola/kullanıcı yok)."""
    return f"{ayarlar.get('smtp_host') or '-'}:{int(ayarlar.get('smtp_port') or 587)}"


def duz_metin_gonder(ayarlar: dict, *, alici: str, konu: str, govde: str) -> None:
    """Eşzamanlı (thread içinde çağrılır) düz metin gönderim — servis e-posta kutusu.

    `gonder`den farkı: olay döngüsünü bloklamamak için `asyncio.to_thread`
    ile çağrılır (worker.py kuralı) ve hata logu istisna METNİNİ YAZMAZ —
    yalnız sınıf adı ve sunucu:port (E10-06 kabul 4: bazı SMTP sunucuları
    kimlik reddinde gönderilen kullanıcı adını yanıtta geri yansıtır).
    Hata `MailKapali(sinif)` olarak yükselir; `__cause__` asıl istisnadır.
    """
    if not yapilandirildi_mi(ayarlar):
        raise MailKapali("E-posta ayarları tanımlı değil.", "SMTP_KAPALI")
    mesaj = EmailMessage()
    mesaj["From"] = ayarlar.get("smtp_from") or ayarlar.get("smtp_user")
    mesaj["To"] = alici
    mesaj["Subject"] = konu
    mesaj.set_content(govde)
    sunucu = ayarlar.get("smtp_host")
    port = int(ayarlar.get("smtp_port") or 587)
    try:
        with smtplib.SMTP(sunucu, port, timeout=20) as s:
            s.starttls()
            if ayarlar.get("smtp_user"):
                s.login(ayarlar["smtp_user"], ayarlar.get("smtp_password") or "")
            s.send_message(mesaj)
    except (OSError, smtplib.SMTPException) as exc:
        sinif = _hata_sinifi(exc)
        logger.warning(
            "Servis e-postası gönderilemedi (%s, %s, %s)",
            sunucu_etiketi(ayarlar),
            sinif,
            type(exc).__name__,
        )
        raise MailKapali(GENEL_HATA_MESAJI, sinif) from exc


async def gonder(
    db: AsyncSession,
    *,
    alici: str | list[str],
    konu: str,
    govde: str,
    ekler: list[tuple[str, bytes, str]] | None = None,
    cc: list[str] | None = None,
    html: str | None = None,
) -> None:
    """`html` verilirse düz metnin yanına HTML seçeneği eklenir (ör. düğmeli
    izin onay e-postası, KARARLAR 2026-11-20 §7); düz metin her zaman vardır."""
    ayarlar = await ayar_svc.get_all(db)
    sunucu = ayarlar.get("smtp_host")
    gonderen = ayarlar.get("smtp_from") or ayarlar.get("smtp_user")
    if not sunucu or not gonderen:
        raise MailKapali(
            "E-posta ayarları tanımlı değil (Parametreler → Bildirim). Döküm gönderilmedi.",
            "SMTP_KAPALI",
        )

    alicilar = [alici] if isinstance(alici, str) else list(alici)
    mesaj = EmailMessage()
    mesaj["From"] = gonderen
    mesaj["To"] = ", ".join(alicilar)
    if cc:
        mesaj["Cc"] = ", ".join(cc)
    mesaj["Subject"] = konu
    mesaj.set_content(govde)
    if html:
        mesaj.add_alternative(html, subtype="html")
    for ad, veri, mime in ekler or []:
        ana, _, alt = mime.partition("/")
        mesaj.add_attachment(veri, maintype=ana, subtype=alt, filename=ad)

    _smtp_gonder(ayarlar, mesaj)
