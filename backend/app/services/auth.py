import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import LoginAttempt, Session, User

# Kayan pencere: her istekte tazelenir, ama 4 saat hareketsiz kalan oturum
# düşer. Ofiste açık unutulan bir ekran akşama kadar açık kalmasın diye
# 12 saatten indirildi (kullanıcı kararı, 23 Eyl 2026).
SESSION_TTL = timedelta(hours=4)
# Oturum bu süreden eskiyse expires_at ileri kaydırılır (kayan pencere,
# her istekte UPDATE atmamak için eşikli).
SLIDE_THRESHOLD = timedelta(minutes=30)

# Brute-force kilidi: art arda bu kadar başarısız girişten sonra hesap kapanır
# ve YÖNETİCİ AÇANA KADAR kapalı kalır. Süreli kilitte saldırgan bekleyip
# kaldığı yerden devam edebiliyordu.
MAX_LOGIN_ATTEMPTS = 5

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except VerifyMismatchError:
        return False


async def authenticate(db: AsyncSession, username: str, password: str) -> User | None:
    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        return None
    return user if verify_password(password, user.password_hash) else None


async def kilit_zamani(db: AsyncSession, username: str) -> datetime | None:
    """Hesap kilitliyse kilitlendiği anı, değilse None döner.

    Kilit kendiliğinden açılmaz; `kilidi_ac` çağrılmalıdır.
    """
    row = await db.get(LoginAttempt, username)
    return row.kilitlendi_at if row is not None else None


async def kilidi_ac(db: AsyncSession, username: str) -> bool:
    """Yönetici kilidi açar. Açılacak kilit yoksa False döner."""
    row = await db.get(LoginAttempt, username)
    if row is None or row.kilitlendi_at is None:
        return False
    await db.execute(delete(LoginAttempt).where(LoginAttempt.username == username))
    return True


async def kilitli_kullanicilar(db: AsyncSession) -> list[str]:
    return list(
        (
            await db.scalars(
                select(LoginAttempt.username).where(LoginAttempt.kilitlendi_at.is_not(None))
            )
        ).all()
    )


async def record_failed_login(db: AsyncSession, username: str, clock: Clock) -> bool:
    """Başarısız giriş sayacını artırır. Eşik aşılırsa kilitler ve True döner.

    VAR OLMAYAN kullanıcı için satır AÇILMAZ. Eskiden açılıyordu ve iki
    sonucu vardı: (1) kimliksiz bir istek `login_attempts` tablosunu
    istediği kadar şişirebiliyordu, (2) "kilitlendi" cevabı, o kullanıcı
    adının var olup olmadığını ele veriyordu. Gerçek kullanıcıya karşı
    kilitleme (kasıtlı hizmet engelleme) yine mümkün — kilit tasarım gereği
    yönetici açana kadar sürüyor — ama kurtarma yolu sunucuda her zaman
    açık: `docker compose exec api python -m app.yonetim kilit-ac <kullanıcı>`.
    """
    now = clock.now()
    row = await db.get(LoginAttempt, username)
    if row is None:
        if await db.scalar(select(User.id).where(User.username == username)) is None:
            return False
        row = LoginAttempt(username=username, fail_count=0)
        db.add(row)
    row.fail_count += 1
    row.last_attempt_at = now
    locked = row.fail_count >= MAX_LOGIN_ATTEMPTS
    if locked and row.kilitlendi_at is None:
        row.kilitlendi_at = now
    await db.flush()
    return locked


async def reset_login_attempts(db: AsyncSession, username: str) -> None:
    await db.execute(delete(LoginAttempt).where(LoginAttempt.username == username))


async def create_session(db: AsyncSession, user: User, clock: Clock) -> str:
    token = secrets.token_hex(32)
    now = clock.now()
    db.add(
        Session(
            token=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
        )
    )
    await db.flush()
    return token


async def resolve_session(db: AsyncSession, token: str, clock: Clock) -> User | None:
    now = clock.now()
    sess = await db.get(Session, token)
    if sess is None or sess.expires_at <= now:
        return None
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    if now - sess.last_seen_at > SLIDE_THRESHOLD:
        sess.last_seen_at = now
        sess.expires_at = now + SESSION_TTL
        await db.flush()
    return user


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token == token))


async def revoke_all_sessions(db: AsyncSession, user_id: int) -> None:
    """Kullanıcı pasifleştirilince/parolası sıfırlanınca tüm oturumları düşür."""
    await db.execute(delete(Session).where(Session.user_id == user_id))


async def suresi_dolan_oturumlari_sil(db: AsyncSession, clock: Clock) -> int:
    """Süresi geçmiş oturum satırlarını siler; silinen sayısını döner.

    `resolve_session` zaten süresi geçmiş jetonu kabul etmiyor, yani bu bir
    yetki sıkılaştırması değil temizliktir: satırlar birikince tablo büyür ve
    "kim ne zaman giriş yaptı" sorgusu yavaşlar. Arka plan görevi çağırır.
    """
    sonuc = await db.execute(delete(Session).where(Session.expires_at <= clock.now()))
    return sonuc.rowcount or 0
