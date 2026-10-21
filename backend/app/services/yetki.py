"""Yetki yükseltme önlemi (E13-01 revised, TS-006).

**Neden:** `sistem.kullanici` sahibi bugüne kadar başkasına ADMIN rolü,
istisnayla `sistem.denetim`/`sistem.kullanici`, ya da kendisinde olmayan
izinlerle yeni bir rol verebiliyordu; ADMIN rolünün izinleri boşaltılabiliyor
(herkes kilitlenir), son yönetici kapatılabiliyordu. Kullanıcı yönetimi yetkisi
böylece bütün yetkilere açılan bir kapıydı.

Kurallar (hepsi burada, saf fonksiyon; `flush`/`commit` yok):

1. `YUKSEK_YETKILI_IZINLER` yalnız ADMIN rolünde bulunur — özel role eklenemez,
   ADMIN olmayana istisnayla verilemez (aktör kim olursa olsun).
2. ADMIN rolünü yalnız ADMIN aktör atar.
3. ADMIN rolü katalogdan yönetilir; API ile düzenlenemez (çağıran 409 döner).
4. Son aktif ADMIN (`is_active AND giris_acik`) kapatılamaz, girişi
   kapatılamaz, rolü değiştirilemez (409).
5. Üst yetkili hedef (ADMIN rolünde ya da yüksek yetkili bir izni olan) yalnız
   ADMIN aktör tarafından değiştirilebilir; personel uçları (`personel.yaz`,
   `personel.cikis`, birim yazma) da bu kuralı `hedef_kontrol` ile uygular.
6. Alt küme savunması: ADMIN olmayan aktör kendisinde olmayan izni veremez.
   Bugün `sistem.kullanici` yalnız ADMIN'de olduğu için canlıda tetiklenmez
   (K-02); eski kurulumda elle açılmış özel rol için savunma olarak durur.

Retler çağıran API tarafından `yetki.ret` eylemiyle denetime yazılır (8).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, User
from app.permissions import YUKSEK_YETKILI_IZINLER

ROL_ADMIN = "ADMIN"


class YetkiHatasi(ValueError):
    """Yetki yükseltme reddi — API 403'e çevirir."""


def admin_mi(kisi: User) -> bool:
    """Kişi ADMIN rolünde mi (istisnayla kazanılmış izin ADMIN yapmaz)."""
    return kisi.role is not None and kisi.role.code == ROL_ADMIN


def ust_yetkili_mi(hedef: User) -> bool:
    """Hedef üst yetkili mi: ADMIN rolünde ya da yüksek yetkili bir izni var.

    Yalnız `sistem.kullanici`'ye bakmak yetmez (E13 kontrol §1.3): denetim
    izini ya da KVKK yetkisini taşıyan kişi de ADMIN olmayan biri tarafından
    pasifleştirilmemeli, parolası değiştirilmemeli.
    """
    return admin_mi(hedef) or bool(YUKSEK_YETKILI_IZINLER & set(hedef.etkin_izinler()))


def verilemeyen_izinler(aktor: User, kodlar, *, hedef_admin: bool = False) -> list[str]:
    """Aktörün veremeyeceği izinler, sıralı (boş liste = hepsi verilebilir).

    - Yüksek yetkili izin yalnız ADMIN rolündeki hedefe "verilebilir" (ki orada
      zaten var); başka role veya kişiye ASLA — aktör ADMIN olsa bile.
    - ADMIN olmayan aktör yalnız kendi etkin izinlerinin alt kümesini verir.
    """
    istenen = set(kodlar)
    ret = set() if hedef_admin else istenen & YUKSEK_YETKILI_IZINLER
    if not admin_mi(aktor):
        ret |= istenen - set(aktor.etkin_izinler())
    return sorted(ret)


def rol_atanabilir_mi(aktor: User, rol: Role) -> bool:
    """Aktör bu rolü birine atayabilir mi.

    ADMIN rolünü yalnız ADMIN atar. Yüksek yetkili izin taşıyan (eski
    kurulumda elle açılmış) bir özel rol de yalnız ADMIN tarafından atanır.
    ADMIN olmayan aktör yalnız kendi izinlerinin alt kümesi olan rolü atar.
    """
    if admin_mi(aktor):
        return True
    if rol.code == ROL_ADMIN:
        return False
    rol_izinleri = {rp.permission_code for rp in rol.permissions}
    if rol_izinleri & YUKSEK_YETKILI_IZINLER:
        return False
    return rol_izinleri <= set(aktor.etkin_izinler())


async def aktif_admin_sayisi(db: AsyncSession) -> int:
    """Giriş yapabilen ADMIN sayısı (`is_active AND giris_acik`)."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(User)
            .join(Role, Role.id == User.role_id)
            .where(Role.code == ROL_ADMIN, User.is_active.is_(True), User.giris_acik.is_(True))
        )
        or 0
    )


async def son_admin_mi(db: AsyncSession, hedef: User) -> bool:
    """Hedef, giriş yapabilen SON ADMIN mi.

    Son yönetici kapatılırsa (ya da rolü/girişi alınırsa) sistemde kullanıcı
    ve rol yönetecek kimse kalmaz; kurtarma ancak sunucuda elle yapılır.
    """
    if not (admin_mi(hedef) and hedef.giris_yapabilir_mi()):
        return False
    return await aktif_admin_sayisi(db) <= 1


def hedef_kontrol(aktor: User, hedef: User) -> None:
    """Üst yetkili hedefe ADMIN olmayan aktörün dokunmasını reddeder.

    Personel uçları (`personel.yaz`, `personel.cikis`, birim yazma) ve
    kullanıcı düzenleme bunu çağırır: İK, ADMIN'i pasifleştiremez, adını
    değiştiremez, birimini yazamaz. Reddi `YetkiHatasi` ile bildirir; API 403.
    """
    if ust_yetkili_mi(hedef) and not admin_mi(aktor):
        raise YetkiHatasi("Üst yetkili bir kullanıcıyı yalnız sistem yöneticisi değiştirebilir.")
