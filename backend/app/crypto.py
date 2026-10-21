"""Uygulama seviyesi simetrik şifreleme — hassas ayarlar ve TOTP sırları için.

Fernet (AES-128-CBC + HMAC) kullanır: kimlik doğrulamalı, zamana dayanıklı.
Anahtar .env'deki settings_enc_key'den, yoksa secret_key'den türetilir
(SHA-256 → base64url 32 bayt). Şifreli değerler `enc:v1:` önekiyle işaretlenir;
öneksiz (eski/düz metin) değerler olduğu gibi kabul edilir → geriye uyum ve
kademeli geçiş (bir sonraki kaydetmede şifrelenir).
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_config

PREFIX = "enc:v1:"


@lru_cache
def _fernet() -> Fernet:
    config = get_config()
    raw = config.settings_enc_key or config.secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    if plaintext == "":
        return ""  # boş değeri şifreleme (görsel/mantıksal olarak "tanımsız")
    token = _fernet().encrypt(plaintext.encode()).decode()
    return PREFIX + token


def decrypt(value: str) -> str:
    """Şifreli (`enc:v1:`) değeri çözer. Öneksizse düz metindir → olduğu gibi
    döner (geriye uyum). Çözme başarısızsa boş döner (bozuk/yanlış anahtar)."""
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        return ""


def is_encrypted(value: str) -> bool:
    return value.startswith(PREFIX)


def make_token(payload: str) -> str:
    """Süreli, kimlik doğrulamalı jeton üretir (Fernet zaman damgalı).
    MFA 'bekleyen giriş' jetonu gibi kısa ömürlü kullanımlar için."""
    return _fernet().encrypt(payload.encode()).decode()


def read_token(token: str, max_age_sec: int) -> str | None:
    """Jeton geçerli ve max_age_sec'ten yeni ise yükü, değilse None döner."""
    try:
        return _fernet().decrypt(token.encode(), ttl=max_age_sec).decode()
    except InvalidToken:
        return None
