"""Kullanıcı ve rol yönetimi (izin: sistem.kullanici)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.api.deps import DbDep, client_ip, require_permission
from app.models import Role, RolePermission, User, UserPermission
from app.permissions import PERMISSIONS, SCOPE_ALL, SCOPE_OWN_CUSTOMERS
from app.schemas.auth import RoleOut, UserCreate, UserOut, UserPatch
from app.services import audit
from app.services import auth as auth_service

router = APIRouter(prefix="/api", tags=["kullanicilar"])

AdminDep = Annotated[User, Depends(require_permission("sistem.kullanici"))]


@router.get("/roller", response_model=list[RoleOut])
async def list_roles(db: DbDep, _: AdminDep) -> list[RoleOut]:
    roles = (await db.scalars(select(Role).order_by(Role.code))).all()
    return [RoleOut.model_validate(r) for r in roles]


class IzinSatiri(BaseModel):
    kod: str
    modul: str
    aciklama: str


class RolYetkisi(BaseModel):
    code: str
    name: str
    scope: str
    scope_aciklama: str
    sayfalar: list[str]
    izinler: list[IzinSatiri]
    # Kullanıcı görünümünde doldurulur: bu izinlerin hangileri rolden değil,
    # kişiye özel istisnadan geliyor. Rol görünümünde daima boş.
    istisna_kodlari: list[str] = []


# Menüdeki ekran → onu açan izin. Arayüzdeki `MENU` tablosunun sunucu
# tarafındaki karşılığı: "bu kullanıcı hangi sayfaları görür" sorusu
# yöneticiye kod okumadan cevaplanabilmeli.
_SAYFA_IZINLERI: list[tuple[str, str]] = [
    ("Panel", "rapor.gor"),
    ("Hesaplar", "hesap.gor"),
    ("Ürün Kataloğu", "urun.gor"),
    ("Cihazlar", "cihaz.gor"),
    ("Stok ve Transfer", "cihaz.gor"),
    ("Hatlar (SIM)", "hat.gor"),
    ("Araçlar", "arac.gor"),
    ("İş Emirleri", "isemri.gor"),
    ("Hak Ediş", "hakedis.gor"),
    ("Teklifler", "teklif.gor"),
    ("Siparişler", "siparis.gor"),
    ("Abonelikler", "abonelik.gor"),
    ("RMA / Servis", "rma.gor"),
    ("Satın Alma", "satinalma.gor"),
    ("Tahsilat", "tahsilat.gor"),
    ("Görevler", "gorev.gor"),
    ("İçe Aktarma", "rapor.gor"),
    ("Raporlar", "rapor.gor"),
    ("KVKK", "kvkk.yonet"),
    ("Kullanıcılar", "sistem.kullanici"),
    ("Parametreler", "sistem.ayar"),
    ("Denetim İzi", "sistem.denetim"),
]

_KAPSAM_ACIKLAMA = {
    SCOPE_ALL: "Tüm kayıtları görür",
    SCOPE_OWN_CUSTOMERS: "Yalnız kendi müşterilerini ve onlara bağlı araç, cihaz, iş emrini görür",
}


@router.get("/roller/{kod}/yetkiler", response_model=RolYetkisi)
async def rol_yetkileri(kod: str, db: DbDep, _: AdminDep) -> RolYetkisi:
    """Bir rolün AÇTIĞI EKRANLAR ve verdiği izinler.

    Kullanıcı açarken/düzenlerken yöneticiye "bu rol neyi görür, neyi
    yapabilir" sorusunun cevabı gösterilmeli. Aksi halde rol seçimi kör bir
    tercih olur ve gereğinden geniş yetki verilir — yetki modelinin varlık
    sebebi tam olarak bunu engellemek.
    """
    rol = await db.scalar(select(Role).where(Role.code == kod))
    if rol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rol bulunamadı: {kod}")
    return _yetki_gorunumu(rol, {rp.permission_code for rp in rol.permissions})


def _yetki_gorunumu(rol: Role, kodlar: set[str], istisna: list[str] | None = None) -> RolYetkisi:
    """İzin kümesini "hangi sayfalar + hangi aksiyonlar" görünümüne çevirir.

    Hem rol hem kullanıcı görünümü buradan çıkıyor: ikisi ayrı yazılsaydı
    sayfa eşlemesi ikiye bölünür ve biri güncellenmeden kalırdı.
    """
    return RolYetkisi(
        code=rol.code,
        name=rol.name,
        scope=rol.scope,
        scope_aciklama=_KAPSAM_ACIKLAMA.get(rol.scope, rol.scope),
        sayfalar=[ad for ad, izin in _SAYFA_IZINLERI if izin in kodlar],
        izinler=[
            IzinSatiri(kod=k, modul=PERMISSIONS[k][0], aciklama=PERMISSIONS[k][1])
            for k in sorted(kodlar)
            if k in PERMISSIONS
        ],
        istisna_kodlari=sorted(istisna or []),
    )


@router.get("/kullanicilar/{user_id}/yetkiler", response_model=RolYetkisi)
async def kullanici_yetkileri(user_id: int, db: DbDep, _: AdminDep) -> RolYetkisi:
    """Bu KİŞİNİN gerçekten açabildiği ekranlar ve yapabildiği işler.

    Rolün ham listesini göstermek yanıltıcıydı: istisnayla verilen yetki
    listede görünmez, geri alınan yetki hâlâ görünürdü. Kaynak `etkin_izinler`
    — yetki kontrolünün kullandığı kuralın ta kendisi.
    """
    kisi = await db.get(User, user_id)
    if kisi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")
    return _yetki_gorunumu(
        kisi.role,
        set(kisi.etkin_izinler()),
        [u.permission_code for u in kisi.izin_istisnalari if u.allow],
    )


@router.get("/izinler", response_model=list[IzinSatiri])
async def izin_katalogu(_: AdminDep) -> list[IzinSatiri]:
    """Tüm izinler — rol düzenleme ekranı seçenekleri buradan alır."""
    return [IzinSatiri(kod=k, modul=m, aciklama=a) for k, (m, a) in sorted(PERMISSIONS.items())]


class RolIn(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=2, max_length=80)
    scope: str = SCOPE_ALL
    izinler: list[str] = []


class RolPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    scope: str | None = None
    izinler: list[str] | None = None


async def _rol_izinlerini_yaz(db, rol: Role, kodlar: list[str]) -> None:
    gecersiz = [k for k in kodlar if k not in PERMISSIONS]
    if gecersiz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen izin: {', '.join(gecersiz)}")
    istenen = set(kodlar)
    var_olan = {
        rp
        for rp in (
            await db.scalars(
                select(RolePermission.permission_code).where(RolePermission.role_id == rol.id)
            )
        ).all()
    }
    for eksik in istenen - var_olan:
        db.add(RolePermission(role_id=rol.id, permission_code=eksik))
    if fazla := var_olan - istenen:
        await db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == rol.id,
                RolePermission.permission_code.in_(fazla),
            )
        )
    # Bundan sonra açılıştaki katalog senkronu bu role dokunmaz.
    rol.ozellestirildi = True


@router.post("/roller", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def rol_olustur(payload: RolIn, request: Request, db: DbDep, user: AdminDep) -> RoleOut:
    """Yeni rol. Kod BÜYÜK HARF ve değiştirilemez — yetki kontrolleri ona bakar."""
    if payload.scope not in (SCOPE_ALL, SCOPE_OWN_CUSTOMERS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz kapsam")
    if await db.scalar(select(Role).where(Role.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bu rol kodu zaten var: {payload.code}")

    rol = Role(
        code=payload.code,
        name=payload.name,
        scope=payload.scope,
        is_system=False,
        ozellestirildi=True,
    )
    db.add(rol)
    await db.flush()
    await _rol_izinlerini_yaz(db, rol, payload.izinler)
    await audit.log(
        db,
        "roles",
        "olustur",
        entity_id=rol.id,
        new_value={"kod": rol.code, "ad": rol.name, "izin": len(payload.izinler)},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return RoleOut.model_validate(rol)


@router.patch("/roller/{kod}", response_model=RoleOut)
async def rol_guncelle(
    kod: str, payload: RolPatch, request: Request, db: DbDep, user: AdminDep
) -> RoleOut:
    """Rolün adını, kapsamını ve izinlerini değiştirir.

    SİSTEM ROLLERİ de düzenlenebilir — ama düzenlenen rol `ozellestirildi`
    işaretlenir ve açılıştaki katalog senkronu ona bir daha dokunmaz; aksi
    halde değişiklik bir sonraki yeniden başlatmada sessizce geri alınırdı.

    Değişiklik o roldeki HERKESİ etkiler, bu yüzden açık oturumlar düşürülür:
    eski yetkiyle açılmış bir oturum yeni kısıtı görmezdi.
    """
    rol = await db.scalar(select(Role).where(Role.code == kod))
    if rol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rol bulunamadı: {kod}")
    if payload.scope is not None and payload.scope not in (SCOPE_ALL, SCOPE_OWN_CUSTOMERS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz kapsam")

    eski = {"ad": rol.name, "kapsam": rol.scope}
    if payload.name is not None:
        rol.name = payload.name
    if payload.scope is not None:
        rol.scope = payload.scope
    if payload.izinler is not None:
        await _rol_izinlerini_yaz(db, rol, payload.izinler)
    else:
        rol.ozellestirildi = True

    etkilenen = (await db.scalars(select(User).where(User.role_id == rol.id))).all()
    for k in etkilenen:
        await auth_service.revoke_all_sessions(db, k.id)

    await audit.log(
        db,
        "roles",
        "guncelle",
        entity_id=rol.id,
        old_value=eski,
        new_value={
            "ad": rol.name,
            "kapsam": rol.scope,
            "izin": len(payload.izinler) if payload.izinler is not None else None,
            "etkilenen_kullanici": len(etkilenen),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return RoleOut.model_validate(rol)


@router.delete("/roller/{kod}", status_code=status.HTTP_204_NO_CONTENT)
async def rol_sil(kod: str, request: Request, db: DbDep, user: AdminDep) -> None:
    """Yalnız ÖZEL rol ve yalnız kullanıcısı yoksa silinir.

    Sistem rolü silinemez: kod içindeki katalog onu yeniden açar ve silme
    kalıcı olmaz. Kullanıcısı olan rol de silinemez — o kullanıcılar yetkisiz
    kalırdı.
    """
    rol = await db.scalar(select(Role).where(Role.code == kod))
    if rol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rol bulunamadı: {kod}")
    if rol.is_system:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Sistem rolü silinemez; izinlerini boşaltabilir ya da kullanmayabilirsiniz.",
        )
    adet = await db.scalar(select(func.count()).select_from(User).where(User.role_id == rol.id))
    if adet:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Bu rolde {adet} kullanıcı var; önce başka bir role taşıyın.",
        )
    await audit.log(
        db,
        "roles",
        "sil",
        entity_id=rol.id,
        old_value={"kod": rol.code, "ad": rol.name},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.delete(rol)
    await db.commit()


class IstisnaIn(BaseModel):
    permission_code: str
    allow: bool
    gerekce: str = Field(min_length=5, max_length=300)


@router.put("/kullanicilar/{user_id}/izinler", response_model=list[IstisnaIn])
async def istisnalari_yaz(
    user_id: int,
    payload: list[IstisnaIn],
    request: Request,
    db: DbDep,
    user: AdminDep,
) -> list[IstisnaIn]:
    """Kullanıcıya özel izin istisnalarını topluca yazar.

    Rol omurgadır; bu istisnadır. Her istisna GEREKÇE ister: aynı roldeki iki
    kişinin neden farklı şey gördüğü altı ay sonra da okunabilmeli.

    Kendi yetkisini değiştirmek ENGELLİDİR — yönetici kendini kilitleyebilir
    ya da sessizce yükseltebilirdi.
    """
    hedef = await db.get(User, user_id)
    if hedef is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")
    if hedef.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendi izinlerinizi değiştiremezsiniz.")
    gecersiz = [i.permission_code for i in payload if i.permission_code not in PERMISSIONS]
    if gecersiz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen izin: {', '.join(gecersiz)}")

    eski = [
        {"kod": u.permission_code, "allow": u.allow}
        for u in (
            await db.scalars(select(UserPermission).where(UserPermission.user_id == user_id))
        ).all()
    ]
    await db.execute(delete(UserPermission).where(UserPermission.user_id == user_id))
    for i in payload:
        db.add(
            UserPermission(
                user_id=user_id,
                permission_code=i.permission_code,
                allow=i.allow,
                gerekce=i.gerekce,
            )
        )
    # Yetki değişti: açık oturumlar eski yetkiyi taşıyor.
    await auth_service.revoke_all_sessions(db, user_id)
    await audit.log(
        db,
        "users",
        "izin.istisna",
        entity_id=user_id,
        old_value={"istisnalar": eski},
        new_value={"istisnalar": [{"kod": i.permission_code, "allow": i.allow} for i in payload]},
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return payload


@router.get("/kullanicilar/{user_id}/izinler", response_model=list[IstisnaIn])
async def istisnalari_getir(user_id: int, db: DbDep, _: AdminDep) -> list[IstisnaIn]:
    kayitlar = (
        await db.scalars(select(UserPermission).where(UserPermission.user_id == user_id))
    ).all()
    return [
        IstisnaIn(permission_code=u.permission_code, allow=u.allow, gerekce=u.gerekce or "—")
        for u in kayitlar
    ]


@router.get("/kullanicilar", response_model=list[UserOut])
async def list_users(db: DbDep, _: AdminDep) -> list[UserOut]:
    users = (await db.scalars(select(User).order_by(User.username))).all()
    return [UserOut.of(u) for u in users]


@router.post("/kullanicilar", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, request: Request, db: DbDep, admin: AdminDep) -> UserOut:
    if await db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu kullanıcı adı zaten var")
    role = await db.scalar(select(Role).where(Role.code == payload.role_code))
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen rol: {payload.role_code}")

    user = User(
        full_name=payload.full_name,
        username=payload.username,
        email=payload.email,
        password_hash=auth_service.hash_password(payload.password),
        role_id=role.id,
    )
    db.add(user)
    await db.flush()
    await audit.log(
        db,
        "users",
        "olustur",
        entity_id=user.id,
        new_value={"username": user.username, "rol": role.code},
        user_id=admin.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(user)
    return UserOut.of(user)


@router.patch("/kullanicilar/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: int, payload: UserPatch, request: Request, db: DbDep, admin: AdminDep
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")

    # İyimser kilitleme: istemci gördüğü sürümü gönderdiyse, arada değişmiş mi bak.
    if payload.version is not None and payload.version != user.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin.",
        )

    # Kendi yetkisini elinden almayı ve kendini kapatmayı engelle — yönetici
    # kilitlenmesi (lockout) en sık görülen kaza.
    if user.id == admin.id:
        if payload.is_active is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendi hesabınızı kapatamazsınız")
        if payload.role_code is not None and payload.role_code != user.role.code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendi rolünüzü değiştiremezsiniz")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.role_code is not None:
        role = await db.scalar(select(Role).where(Role.code == payload.role_code))
        if role is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen rol: {payload.role_code}")
        user.role_id = role.id
    if payload.password is not None:
        user.password_hash = auth_service.hash_password(payload.password)
    if payload.reset_mfa:
        user.mfa_enabled = False
        user.totp_secret = None

    # Değişiklik ne olursa olsun eski/yeni değerleriyle loglanır.
    await audit.log_change(db, user, "guncelle", user_id=admin.id, ip=client_ip(request))

    # Yetki, parola veya aktiflik değiştiyse açık oturumları düşür: eski yetkiyle
    # açılmış bir oturum yeni kısıtı görmezdi.
    if (
        payload.role_code is not None
        or payload.password is not None
        or payload.is_active is False
        or payload.reset_mfa
    ):
        await auth_service.revoke_all_sessions(db, user.id)

    await db.commit()
    await db.refresh(user)
    return UserOut.of(user)


@router.get("/kullanicilar/kilitli", response_model=list[str])
async def kilitli_kullanicilar(db: DbDep, _: AdminDep) -> list[str]:
    """Kilitli hesapların kullanıcı adları. Kilit kendiliğinden açılmaz."""
    return await auth_service.kilitli_kullanicilar(db)


@router.post("/kullanicilar/{username}/kilidi-ac")
async def kilidi_ac(username: str, request: Request, db: DbDep, admin: AdminDep) -> dict:
    """Brute-force kilidini açar.

    Kilit süreli olmadığı için bu uç olmadan kilitlenen kullanıcı bir daha
    giremez. Kim açtı denetim izine yazılır — kilidi açmak bir yetki kullanımıdır.
    """
    if not await auth_service.kilidi_ac(db, username):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bu kullanıcıda açık kilit yok")
    await audit.log(
        db,
        "users",
        "kilit.acildi",
        new_value={"username": username},
        user_id=admin.id,
        ip=client_ip(request),
    )
    await db.commit()
    return {"acildi": True}
