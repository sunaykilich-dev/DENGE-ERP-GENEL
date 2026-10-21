"""E-posta gönderimi (SMTP).

SMTP ayarları boşsa gönderim SESSİZCE ATLANMAZ — `MailKapali` yükseltilir ve
çağıran kullanıcıya "e-posta ayarları tanımlı değil" der. Sessiz atlama, hak
ediş dökümünün gittiğini sanıp gitmemesi demek olurdu.
"""

import smtplib
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import settings as ayar_svc


class MailKapali(RuntimeError):
    pass


async def gonder(
    db: AsyncSession,
    *,
    alici: str,
    konu: str,
    govde: str,
    ekler: list[tuple[str, bytes, str]] | None = None,
) -> None:
    ayarlar = await ayar_svc.get_all(db)
    sunucu = ayarlar.get("smtp_host")
    gonderen = ayarlar.get("smtp_from") or ayarlar.get("smtp_user")
    if not sunucu or not gonderen:
        raise MailKapali(
            "E-posta ayarları tanımlı değil (Parametreler → Bildirim). Döküm gönderilmedi."
        )

    mesaj = EmailMessage()
    mesaj["From"] = gonderen
    mesaj["To"] = alici
    mesaj["Subject"] = konu
    mesaj.set_content(govde)
    for ad, veri, mime in ekler or []:
        ana, _, alt = mime.partition("/")
        mesaj.add_attachment(veri, maintype=ana, subtype=alt, filename=ad)

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
        raise MailKapali(
            f"E-posta gönderilemedi ({sunucu}:{port}): {exc}. "
            "Parametreler ekranındaki SMTP ayarlarını kontrol edin."
        ) from exc
