"""FastAPI bağımlılıkları: oturum, CSRF, izin kontrolü, kayıt bazlı kapsam."""

import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock, RealClock
from app.db import get_session
from app.models import User
from app.permissions import SCOPE_OWN_CUSTOMERS
from app.services import auth as auth_service
from app.services import erisim_yeri

SESSION_COOKIE = "dngerp_session"
_real_clock = RealClock()


def get_clock() -> Clock:
    return _real_clock


DbDep = Annotated[AsyncSession, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# MFA kurulmadan erişilebilen TEK yollar. Parola doğru olsa da oturum bundan
# fazlasını yapamaz: kullanıcı ya MFA'sını kurar ya da çıkar.
#
# `/mfa/disable` bilerek YOK — zorunluyken kimse kendi ikinci faktörünü
# kapatamaz. `/me` listede çünkü arayüz kurulum ekranına yönlendirmek için
# kullanıcının durumunu okumak zorunda.
MFA_MUAF_YOLLAR = frozenset(
    {
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/mfa/enroll",
        "/api/auth/mfa/confirm",
    }
)


# Parola değiştirilmeden erişilebilen TEK yollar (TS-212, E13-13). Yönetici
# parolayı belirlediyse/ürettiyse ya da ilk kurulumun yönetici parolasıysa
# (`parola_degismeli`) oturum yalnız parolayı değiştirmeye yarar. MFA kurulum
# yolları da açıktır: iki kapı birlikte kapalıysa sıra MFA → parola olur;
# aksi hâlde biri diğerinin çıkışını kapatırdı.
PAROLA_MUAF_YOLLAR = frozenset(
    {
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/parola",
        "/api/auth/mfa/enroll",
        "/api/auth/mfa/confirm",
    }
)


def mfa_kurulumu_gerekli(user: User) -> bool:
    # Kural User.mfa_kurulumu_gerekli()'de; burada yalnız devredilir.
    return user.mfa_kurulumu_gerekli()


async def current_user(request: Request, db: DbDep, clock: ClockDep) -> User:
    # CSRF koruması: SameSite=Lax çerez + mutasyonlarda özel başlık şartı.
    # frontend/src/api/client.ts her isteğe X-Requested-With ekler; form-post
    # tabanlı cross-site istekler bu başlığı ekleyemez.
    if request.method in _MUTATING and request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Eksik istek başlığı")
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum bulunamadı")
    user = await auth_service.resolve_session(db, token, clock)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Oturum geçersiz veya süresi dolmuş")
    # G3.8: ofise bağlı rol dışarıdan istek atamaz (oturum ofiste açılmış olsa da).
    # Oturum düşürülmez: kullanıcı ofise dönünce aynı oturumla devam eder.
    # Çıkış her yerden yapılabilir (oturumu kapatmak kısıtı gevşetmez).
    if request.url.path != "/api/auth/logout" and await erisim_yeri.ofis_disinda_mi(
        db, user, client_ip(request)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, {"kod": erisim_yeri.KOD, "mesaj": erisim_yeri.MESAJ}
        )
    if mfa_kurulumu_gerekli(user) and request.url.path not in MFA_MUAF_YOLLAR:
        # 403 + makine okunur kod: arayüz bunu görünce kurulum ekranına geçer.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "kod": "MFA_KURULUMU_GEREKLI",
                "mesaj": "İki adımlı doğrulama kurulmadan işlem yapılamaz.",
            },
        )
    if user.parola_degismeli and request.url.path not in PAROLA_MUAF_YOLLAR:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "kod": "PAROLA_DEGISMELI",
                "mesaj": "Devam etmeden önce parolanızı değiştirmelisiniz.",
            },
        )
    # Süreli vekâlet (TS-213): kullanıcının süreli istisnaları İSTEK anına göre
    # değerlendirilir. An atanmazsa süreli satırlar hiç sayılmaz (fail-closed);
    # süre dolunca ek bir iş gerekmeden bir sonraki istek 403 alır.
    user.izin_anini_ata(clock.now())
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_permission(*codes: str):
    """Verilen izinlerin TAMAMINI isteyen bir bağımlılık üretir.

        @router.post("/hakedis/{id}/onayla")
        async def onayla(user: Annotated[User, Depends(require_permission("hakedis.onayla"))]):

    Varsayılan daima reddetmektir: rolün izin listesinde yoksa 403.
    """

    async def _guard(user: CurrentUser) -> User:
        eksik = [c for c in codes if not user.has(c)]
        if eksik:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Bu işlem için yetkiniz yok ({', '.join(eksik)})",
            )
        return user

    # Otomatik yetki matrisi (`tests/integration/test_yetki_matrisi.py`) her
    # ucun hangi izinleri istediğini buradan okur: matris elle tutulan bir
    # tablo olsaydı yeni uç eklendiğinde unutulurdu (TS-013).
    _guard.izinler = codes  # type: ignore[attr-defined]
    return _guard


def require_any_permission(*codes: str):
    """Verilen izinlerden EN AZ BİRİNİ isteyen bağımlılık.

    Aynı ekranı iki ayrı yetkiyle yöneten uçlar için (ör. Servis Tanımları:
    arıza nedeni `servis.tanim`, bekleme nedeni `operasyon.yonet`). Uçta hangi
    alt işlemin hangi izni istediği ayrıca gövdede kontrol edilir; bu kapı
    yalnız "hiçbiri yoksa 403"tür. Varsayılan yine RED.
    """
    if not codes:
        raise ValueError("En az bir izin kodu verilmeli")

    async def _guard(user: CurrentUser) -> User:
        if not any(user.has(c) for c in codes):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Bu işlem için yetkiniz yok ({' veya '.join(codes)})",
            )
        return user

    _guard.izinler_herhangi = codes  # type: ignore[attr-defined]
    return _guard


AdminUser = Annotated[User, Depends(require_permission("sistem.kullanici"))]


def sees_cost(user: User) -> bool:
    """Maliyet/alış fiyatı/marj alanları gösterilsin mi. Varsayılan: hayır."""
    return user.has("maliyet.gor")


def scope_filter(user: User):
    """Kayıt bazlı filtre için kullanılacak müşteri temsilcisi kimliği.

    None → kısıt yok (tüm kayıtlar). Değer → yalnız o temsilciye ait hesaplar.
    Çağıran sorgu `.where(Account.sales_rep_id == rep)` şeklinde uygular;
    filtreyi uygulamayı unutmamak için liste uçlarında ortak bir yardımcı
    kullanılır (hesaplar modülü geldiğinde eklenecek).
    """
    if user.role.scope == SCOPE_OWN_CUSTOMERS:
        return user.id
    return None


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


DONEM_KALIBI = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def donem_dogrula(donem: str | None) -> None:
    """Dönem YYYY-AA olmalı; değilse 400.

    Doğrulanmayan dönem Excel SAYFA ADINA ve `Content-Disposition` başlığına
    doğrudan giriyordu: `2026/06` "Invalid character / in sheet title" ile,
    Türkçe harf ise başlık latin-1 kodlanırken `UnicodeEncodeError` ile 500
    veriyordu. `2026-13` ve `abc` ise sessizce 200 + boş dosya dönüyordu.
    Kullanıcının yazım hatası ne uygulamayı çökertmeli ne de boş bir dosyayı
    doğru cevap gibi sunmalı.
    """
    if donem is not None and not DONEM_KALIBI.match(donem):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Dönem YYYY-AA biçiminde olmalı: {donem}")


TOPLAM_BASLIGI = "X-Toplam-Kayit"


def _kirilma_ekle(stmt: Select) -> Select:
    """Sıralamaya birincil anahtarı SON kriter olarak ekler.

    LIMIT/OFFSET ile sayfalanan bir sorgunun sıralaması tekil değilse
    PostgreSQL sayfalar arasında tutarlılık vaat etmez: aynı satır iki
    sayfada çıkar, başka bir satır HİÇBİR sayfada çıkmaz. Hata da vermez.

    Gerçek ölçüm: `is-emirleri` `completed_at` ile sıralanıyordu (tek bir
    zaman damgasında 49 iş emri var). 1.232 kaydın tamamı sayfa sayfa
    gezildiğinde 1.215 benzersiz kayıt geldi — **17 iş emri hiç görünmedi**.
    Muhasebe listeden gezerken bunu fark edemez.

    Kırılma burada, tek yerde eklenir; yeni bir liste ucu yazan kimsenin
    hatırlaması gerekmez.
    """
    ana = stmt.column_descriptions[0]["entity"] if stmt.column_descriptions else None
    if ana is None:
        return stmt
    try:
        anahtar = sa_inspect(ana).primary_key
    except Exception:  # ORM varlığı değilse (ham kolon seçimi) dokunma
        return stmt
    return stmt.order_by(*anahtar) if anahtar else stmt


async def sayfala(
    db: AsyncSession,
    response: Response,
    stmt: Select,
    *,
    limit: int,
    offset: int,
):
    """Sorguyu sayfalar ve TOPLAM kayıt sayısını `X-Toplam-Kayit` başlığına yazar.

    Liste uçları bugüne kadar yalnız `limit` uyguluyordu ve arayüz gelen diziyi
    kendi içinde sayfalıyordu: 17.350 cihazın 100'ü görünüyor, gerisi yokmuş
    gibi davranıyordu. Sessiz kesme, hata vermeyen ve kimsenin fark etmediği
    türden bir veri kaybıdır.

    Toplam gövdeye değil başlığa yazılır; böylece uçların dönüş şekli (düz
    dizi) ve mevcut çağıranlar bozulmadan kalır.
    """
    toplam = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers[TOPLAM_BASLIGI] = str(toplam or 0)
    return (await db.execute(_kirilma_ekle(stmt).limit(limit).offset(offset))).all()
