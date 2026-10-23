from fastapi import APIRouter, HTTPException, Request, Response, status

from app import crypto
from app.api.deps import SESSION_COOKIE, ClockDep, CurrentUser, DbDep, client_ip
from app.config import get_config
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    LoginResult,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaVerifyRequest,
    ParolaDegistirRequest,
    UserOut,
)
from app.services import audit
from app.services import auth as auth_service
from app.services import mfa as mfa_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

# MFA bekleyen giriş jetonunun ömrü (parola doğrulandı, kod bekleniyor).
PENDING_MFA_TTL_SEC = 300


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=not get_config().is_dev,
        max_age=int(auth_service.SESSION_TTL.total_seconds()),
        path="/",
    )


# Hatalı parola, var olmayan kullanıcı, girişi kapalı hesap, süresi dolmuş
# geçici parola ve KİLİTLİ hesap AYNI kodu ve AYNI metni alır (TS-212, K-04).
# Eskiden kilit 423 ile ayrı bildiriliyordu; yalnız var olan kullanıcı
# kilitlendiği için 423 "bu kullanıcı adı var" demekti. Kilit bilgisi
# denetim kaydında ve yönetici ekranındaki "kilitli" rozetinde görünür.
# Metin canlıdakiyle AYNI kalır (istemciler ve testler bu metne bakıyor);
# "kilitlendiyse yöneticinize başvurun" yönlendirmesi giriş ekranının işidir.
GIRIS_HATASI = "Kullanıcı adı veya parola hatalı"


def _oturum_ac(response: Response, token: str, user: User, clock) -> LoginResult:
    user.izin_anini_ata(clock.now())
    _set_session_cookie(response, token)
    return LoginResult(user=UserOut.of(user))


@router.post("/login", response_model=LoginResult)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbDep, clock: ClockDep
) -> LoginResult:
    # 1) Parola doğrulama HER ZAMAN koşar (kilitli hesapta da): yanıt süresi
    # kullanıcı adının varlığını ya da kilidi ele vermesin.
    user = await auth_service.authenticate(db, payload.username, payload.password, clock)
    # 2) Brute-force kilidi — kendiliğinden açılmaz, yönetici açar. Doğru
    # parola da kilidi aşamaz.
    kilitli = await auth_service.kilit_zamani(db, payload.username) is not None
    if user is None or kilitli:
        locked = await auth_service.record_failed_login(db, payload.username, clock)
        await audit.log(
            db,
            "users",
            "giris.basarisiz",
            new_value={
                "username": payload.username,
                "kilitlendi": locked,
                **({"kilitli_hesap": True} if kilitli else {}),
            },
            ip=client_ip(request),
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GIRIS_HATASI)

    await auth_service.reset_login_attempts(db, user.username)

    # 3) MFA açıksa oturumu HENÜZ açma; kodu iste
    if user.mfa_enabled:
        pending = crypto.make_token(str(user.id))
        await db.commit()
        return LoginResult(mfa_required=True, pending_token=pending)

    # 4) MFA yok → oturumu aç
    token = await auth_service.create_session(db, user, clock)
    await auth_service.giris_tamamlandi(db, user, clock)
    await audit.log(db, "users", "giris", entity_id=user.id, user_id=user.id, ip=client_ip(request))
    await db.commit()
    return _oturum_ac(response, token, user, clock)


@router.post("/login/mfa", response_model=LoginResult)
async def login_mfa(
    payload: MfaVerifyRequest, request: Request, response: Response, db: DbDep, clock: ClockDep
) -> LoginResult:
    user_id = crypto.read_token(payload.pending_token, PENDING_MFA_TTL_SEC)
    if user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Doğrulama süresi doldu, tekrar giriş yapın"
        )
    user = await db.get(User, int(user_id))
    # Giriş kuralı tek yerde (`giris_yapabilir_mi`). Yalnız `is_active`'e
    # bakmak, parola adımından SONRA girişi kapatılan hesabın elindeki geçerli
    # pending_token ile oturum açmasına izin veriyordu (E13-02 c).
    if user is None or not user.giris_yapabilir_mi():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum geçersiz")
    # Parola adımından sonra kilitlenen hesap (paralel denemeler) bekleyen
    # jetonla da oturum açamaz.
    if await auth_service.kilit_zamani(db, user.username) is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GIRIS_HATASI)

    if not mfa_service.check_login_code(user, payload.code):
        locked = await auth_service.record_failed_login(db, user.username, clock)
        await audit.log(
            db,
            "users",
            "giris.mfa_basarisiz",
            entity_id=user.id,
            new_value={"kilitlendi": locked},
            user_id=user.id,
            ip=client_ip(request),
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Doğrulama kodu hatalı")

    await auth_service.reset_login_attempts(db, user.username)
    token = await auth_service.create_session(db, user, clock)
    await auth_service.giris_tamamlandi(db, user, clock)
    await audit.log(
        db,
        "users",
        "giris",
        entity_id=user.id,
        new_value={"mfa": True},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _oturum_ac(response, token, user, clock)


@router.post("/logout")
async def logout(request: Request, response: Response, db: DbDep, user: CurrentUser) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await auth_service.revoke_session(db, token)
    await audit.log(db, "users", "cikis", entity_id=user.id, user_id=user.id, ip=client_ip(request))
    await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    # Bayrağı UserOut.of() dolduruyor; burada ayrıca atanmıyor ki giriş
    # yanıtıyla /me arasında fark kalmasın.
    return UserOut.of(user)


@router.post("/parola", response_model=UserOut)
async def parola_degistir(
    payload: ParolaDegistirRequest,
    request: Request,
    response: Response,
    db: DbDep,
    clock: ClockDep,
    user: CurrentUser,
) -> UserOut:
    """Kullanıcı kendi parolasını değiştirir (TS-212, E13-13).

    `parola_degismeli` iken de açıktır (`PAROLA_MUAF_YOLLAR`). Yanlış mevcut
    parola başarısız giriş sayacına girer: çalınmış bir oturumla parola
    denemek de brute-force'tur. Sayaç kilitlerse bütün oturumlar düşer.
    Başarılıysa BU oturum kalır, diğerleri düşer.
    """
    token = request.cookies.get(SESSION_COOKIE)
    try:
        await auth_service.parola_degistir(
            db, user, mevcut=payload.mevcut, yeni=payload.yeni, clock=clock, korunan_oturum=token
        )
    except auth_service.ParolaHatasi as exc:
        # Kurallar yazmadan ÖNCE denetlenir; geri alınacak değişiklik yok.
        if isinstance(exc, auth_service.MevcutParolaHatali):
            locked = await auth_service.record_failed_login(db, user.username, clock)
            await audit.log(
                db,
                "users",
                "parola.degistir_basarisiz",
                entity_id=user.id,
                new_value={"kilitlendi": locked},
                user_id=user.id,
                ip=client_ip(request),
            )
            if locked:
                await auth_service.revoke_all_sessions(db, user.id)
                await db.commit()
                response.delete_cookie(SESSION_COOKIE, path="/")
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, GIRIS_HATASI) from exc
            await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await audit.log(
        db, "users", "parola.degistir", entity_id=user.id, user_id=user.id, ip=client_ip(request)
    )
    await db.commit()
    return UserOut.of(user)


# --- MFA self-servis (giriş yapmış kullanıcı kendi hesabı için) ---


@router.post("/mfa/enroll")
async def mfa_enroll(request: Request, db: DbDep, user: CurrentUser) -> dict:
    """Yeni TOTP sırrı üretir + QR döner. Kod doğrulanana dek MFA aktif olmaz."""
    result = await mfa_service.begin_enrollment(db, user)
    await audit.log(
        db, "users", "mfa.kurulum_baslat", entity_id=user.id, user_id=user.id, ip=client_ip(request)
    )
    await db.commit()
    return result


@router.post("/mfa/confirm")
async def mfa_confirm(
    payload: MfaCodeRequest, request: Request, db: DbDep, user: CurrentUser
) -> dict:
    if not await mfa_service.confirm_enrollment(db, user, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kod hatalı — tekrar deneyin")
    await audit.log(
        db, "users", "mfa.etkinlestir", entity_id=user.id, user_id=user.id, ip=client_ip(request)
    )
    await db.commit()
    return {"mfa_enabled": True}


@router.post("/mfa/disable")
async def mfa_disable(
    payload: MfaDisableRequest, request: Request, db: DbDep, user: CurrentUser
) -> dict:
    # Zorunluyken kimse kendi ikinci faktörünü kapatamaz; kapatabilseydi
    # "zorunlu" olmazdı, kullanıcı bir tıkla eski hâle dönerdi.
    if get_config().mfa_zorunlu:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "İki adımlı doğrulama bu kurulumda zorunlu; kapatılamaz.",
        )
    # MFA kapatmak parola ile yeniden doğrulama ister (çalıntı oturuma karşı)
    if not auth_service.verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Parola hatalı")
    await mfa_service.disable(db, user)
    await audit.log(
        db, "users", "mfa.kapat", entity_id=user.id, user_id=user.id, ip=client_ip(request)
    )
    await db.commit()
    return {"mfa_enabled": False}
