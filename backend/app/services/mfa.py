"""Çok faktörlü kimlik doğrulama (TOTP) — kurulum ve doğrulama.

TOTP sırrı kullanıcıda ŞİFRELİ saklanır (app.crypto). Kurulum akışı:
  1. begin_enrollment → yeni sır üretir, şifreli yazar (mfa_enabled hâlâ False),
     otpauth URI + QR (SVG) döner.
  2. Kullanıcı authenticator uygulamasına ekler, ilk kodu girer.
  3. confirm_enrollment → kod doğruysa mfa_enabled=True.
Yarım kalan kurulum (kod doğrulanmadan) girişi kilitlemez.
"""

import base64
import io

import pyotp
import qrcode
import qrcode.image.svg
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto
from app.models import User

ISSUER = "Denge Mobilite ERP"
# TOTP kod penceresi toleransı (±1 adım = saat kaymasına dayanıklılık)
VALID_WINDOW = 1


def _new_secret() -> str:
    return pyotp.random_base32()


def _otpauth_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def _qr_svg_data_uri(otpauth_uri: str) -> str:
    img = qrcode.make(otpauth_uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/svg+xml;base64,{b64}"


def verify_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=VALID_WINDOW)


async def begin_enrollment(db: AsyncSession, user: User) -> dict:
    secret = _new_secret()
    user.totp_secret = crypto.encrypt(secret)
    user.mfa_enabled = False  # kod doğrulanana dek aktif olmaz
    await db.flush()
    uri = _otpauth_uri(secret, user.username)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": _qr_svg_data_uri(uri)}


async def confirm_enrollment(db: AsyncSession, user: User, code: str) -> bool:
    if not user.totp_secret:
        return False
    secret = crypto.decrypt(user.totp_secret)
    if not verify_code(secret, code):
        return False
    user.mfa_enabled = True
    await db.flush()
    return True


async def disable(db: AsyncSession, user: User) -> None:
    user.mfa_enabled = False
    user.totp_secret = None
    await db.flush()


def check_login_code(user: User, code: str) -> bool:
    if not user.mfa_enabled or not user.totp_secret:
        return False
    return verify_code(crypto.decrypt(user.totp_secret), code)
