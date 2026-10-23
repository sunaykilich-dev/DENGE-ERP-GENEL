import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.clock import Clock
from app.models import LoginAttempt, Session, User

# Kayan pencere: her istekte tazelenir, ama 4 saat hareketsiz kalan oturum
# düşer. Ofiste açık unutulan bir ekran akşama kadar açık kalmasın diye
# 12 saatten indirildi (kullanıcı kararı, 23 Eyl 2026).
SESSION_TTL = timedelta(hours=4)
# MUTLAK üst sınır (E13-02, TS-007): kayan pencere her istekte uzadığı için
# sürekli kullanılan (ya da çalınıp açık tutulan) bir oturum hiç bitmiyordu.
# Açılıştan 12 saat sonra oturum ne olursa olsun düşer; kullanıcı yeniden
# girer (MFA dahil). KOD SABİTİDİR, ayar değil: arayüzden gevşetilemesin (K-05).
SESSION_MAX = timedelta(hours=12)
# Oturum bu süreden eskiyse expires_at ileri kaydırılır (kayan pencere,
# her istekte UPDATE atmamak için eşikli).
SLIDE_THRESHOLD = timedelta(minutes=30)

# Brute-force kilidi: art arda bu kadar başarısız girişten sonra hesap kapanır
# ve YÖNETİCİ AÇANA KADAR kapalı kalır. Süreli kilitte saldırgan bekleyip
# kaldığı yerden devam edebiliyordu.
MAX_LOGIN_ATTEMPTS = 5

_hasher = PasswordHasher()

# --- Parola yaşam döngüsü (TS-212, E13-13) -------------------------------------
# Yönetici belirlediği/ürettiği parola GEÇİCİDİR: 72 saat içinde ve yalnız BİR
# girişte kullanılabilir, kullanıcı ilk girişte değiştirmek zorundadır. Kod
# sabitidir (K-05 gerekçesi: güvenlik süresi arayüzden gevşetilmesin).
GECICI_PAROLA_SURESI = timedelta(hours=72)
PAROLA_ASGARI_UZUNLUK = 10
PAROLA_AZAMI_UZUNLUK = 200


class ParolaHatasi(ValueError):
    """Yeni parola kurala uymuyor ya da mevcut parola yanlış (API → 400)."""


class MevcutParolaHatali(ParolaHatasi):
    """Mevcut parola yanlış — çağıran başarısız giriş sayacına yazar."""


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """Parola özete uyuyor mu. Bozuk/geçersiz özet de `False` (500 değil).

    `InvalidHash` (ör. elle yazılmış "!" özeti) eskiden yakalanmıyordu ve
    girişte 500 üretiyordu (E13-04 kontrol notu).
    """
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


_sahte_ozet: str | None = None


def _sahte_parola_ozeti() -> str:
    """Var olmayan kullanıcı için argon2'nin YİNE koşacağı sabit özet (tembel)."""
    global _sahte_ozet
    if _sahte_ozet is None:
        _sahte_ozet = _hasher.hash(secrets.token_urlsafe(16))
    return _sahte_ozet


def gecici_parola_gecersiz_mi(user: User, an: datetime) -> bool:
    """Geçici parolanın süresi doldu (ya da tek kullanımı harcandı) mı."""
    return (
        user.parola_degismeli
        and user.gecici_parola_bitis is not None
        and user.gecici_parola_bitis <= an
    )


async def authenticate(
    db: AsyncSession, username: str, password: str, clock: Clock | None = None
) -> User | None:
    """Parola doğrulama. Giriş kuralı `User.giris_yapabilir_mi()`'dedir.

    `is_active` tek başına yetmez: kaydı canlı ama girişi kapalı personel
    (`giris_acik=false`, ör. girişsiz saha personeli) de reddedilir.

    **Sabit zamanlama (E13-13):** kullanıcı yoksa ya da giremiyorsa argon2
    yine (sahte özetle) koşar. Eskiden bu durumda doğrudan dönülüyordu;
    yanıt süresi "bu kullanıcı adı var mı" sorusunu cevaplıyordu.

    Süresi dolmuş/harcanmış geçici parola da reddedilir (`clock` verilirse).
    """
    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not user.giris_yapabilir_mi():
        verify_password(password, _sahte_parola_ozeti())
        return None
    if not verify_password(password, user.password_hash):
        return None
    if clock is not None and gecici_parola_gecersiz_mi(user, clock.now()):
        return None
    return user


def gecici_parola_uret() -> str:
    """Yöneticinin kullanıcıya ileteceği tek seferlik parola (12 karakter)."""
    return secrets.token_urlsafe(9)


def gecici_parola_ata(user: User, parola: str, clock: Clock) -> None:
    """Yönetici parolası = geçici: zorunlu değişim + 72 sa süre (TS-212).

    Yönetici parolayı biliyor; kullanıcının kendi parolasına geçmesi
    zorunludur. Oturum düşürme çağıranın işidir.
    """
    user.password_hash = hash_password(parola)
    user.parola_degismeli = True
    user.gecici_parola_bitis = clock.now() + GECICI_PAROLA_SURESI


async def giris_tamamlandi(db: AsyncSession, user: User, clock: Clock) -> None:
    """Oturum açılırken: son giriş anı yazılır, geçici parola HARCANIR.

    Geçici parola tek seferliktir: bu oturum yalnız parola değiştirmeye
    yarar (`PAROLA_MUAF_YOLLAR`); kullanıcı değiştirmeden çıkarsa aynı
    parolayla bir daha giremez, yönetici yeniden üretir.

    **Sürüm sayacı ARTMAZ:** yazım doğrudan UPDATE ile yapılır. ORM nesnesi
    üzerinden yazılsaydı her giriş `users.version`'ı artırır ve o sırada
    personel kartını ya da kullanıcıyı düzenleyen yönetici, kişi yalnız
    giriş yaptı diye iyimser kilit çakışması (409) alırdı.
    """
    an = clock.now()
    degerler: dict = {"son_giris_at": an}
    if user.parola_degismeli and user.gecici_parola_bitis is not None:
        degerler["gecici_parola_bitis"] = min(user.gecici_parola_bitis, an)
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(**degerler)
        .execution_options(synchronize_session=False)
    )
    for alan, deger in degerler.items():
        set_committed_value(user, alan, deger)


def parola_kurali_hatalari(user: User, yeni: str) -> list[str]:
    """Yeni parola kuralları; boş liste = uygun.

    En az 10 karakter, kullanıcı adını ya da adının bir parçasını (3+ harf)
    içermez. Karmaşıklık kuralı bilerek YOK: uzunluk tahmin direncini
    belirler, zorunlu sembol kuralı "Parola1!" türü kalıpları çoğaltır.
    """
    hatalar: list[str] = []
    if len(yeni) < PAROLA_ASGARI_UZUNLUK:
        hatalar.append(f"Parola en az {PAROLA_ASGARI_UZUNLUK} karakter olmalı.")
    if len(yeni) > PAROLA_AZAMI_UZUNLUK:
        hatalar.append(f"Parola en çok {PAROLA_AZAMI_UZUNLUK} karakter olabilir.")
    katli = yeni.casefold()
    parcalar = [user.username, *(user.full_name or "").split()]
    if any(len(p) >= 3 and p.casefold() in katli for p in parcalar):
        hatalar.append("Parola kullanıcı adınızı ya da adınızı içeremez.")
    return hatalar


async def parola_degistir(
    db: AsyncSession,
    user: User,
    *,
    mevcut: str,
    yeni: str,
    clock: Clock,
    korunan_oturum: str | None,
) -> None:
    """Kullanıcının kendi parolasını değiştirmesi (TS-212).

    Mevcut parola yanlışsa `ParolaHatasi` (çağıran başarısız giriş sayacına
    yazar: çalınmış oturumla parola denemesi de brute-force'tur). Başarılıysa
    zorunlu değişim kalkar ve BU oturum dışındaki bütün oturumlar düşer.
    """
    if not verify_password(mevcut, user.password_hash):
        raise MevcutParolaHatali("Mevcut parola hatalı.")
    if mevcut == yeni:
        raise ParolaHatasi("Yeni parola mevcut paroladan farklı olmalı.")
    if hatalar := parola_kurali_hatalari(user, yeni):
        raise ParolaHatasi(" ".join(hatalar))
    user.password_hash = hash_password(yeni)
    user.parola_degismeli = False
    user.gecici_parola_bitis = None
    user.parola_degisti_at = clock.now()
    kosul = Session.user_id == user.id
    if korunan_oturum:
        kosul = kosul & (Session.token != korunan_oturum)
    await db.execute(delete(Session).where(kosul))
    await db.flush()


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
            expires_at=_bitis(now, now),
            last_seen_at=now,
        )
    )
    await db.flush()
    return token


def _bitis(acilis: datetime, now: datetime) -> datetime:
    """Kayan bitiş, mutlak üst sınırı (`acilis + SESSION_MAX`) aşamaz."""
    return min(now + SESSION_TTL, acilis + SESSION_MAX)


async def resolve_session(db: AsyncSession, token: str, clock: Clock) -> User | None:
    """Oturum jetonunu kullanıcıya çözer; geçersizse None (→ 401).

    Üç bağımsız düşürme koşulu: hareketsizlik (`expires_at`), mutlak süre
    (`SESSION_MAX`, kaydırma bunu aşamaz) ve giriş kuralı
    (`giris_yapabilir_mi`: pasifleştirilen ya da girişi kapatılan kişinin
    açık oturumu da bir sonraki istekte düşer).
    """
    now = clock.now()
    sess = await db.get(Session, token)
    if sess is None or sess.expires_at <= now or now - sess.created_at >= SESSION_MAX:
        return None
    user = await db.get(User, sess.user_id)
    if user is None or not user.giris_yapabilir_mi():
        return None
    if now - sess.last_seen_at > SLIDE_THRESHOLD:
        sess.last_seen_at = now
        sess.expires_at = _bitis(sess.created_at, now)
        # COMMIT burada bilinçli (servis katmanında istisna): kaydırma eskiden
        # yalnız flush ediliyordu ve yazma yapmayan uçlarda (GET) istek
        # sonunda geri alınıyordu — salt okuyan kullanıcının oturumu girişten
        # 4 saat sonra kullanım ortasında düşüyordu (TS-007 testi yakaladı).
        # Çağrı isteğin BAŞINDA, kimlik çözümünde yapılır; oturumda bekleyen
        # başka bir yazma yoktur.
        await db.commit()
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
