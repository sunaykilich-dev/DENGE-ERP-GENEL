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

7. Süreli vekâlet (TS-213): kurallar ve yazma yardımcıları dosyanın sonunda.
   Yazan yardımcılar (`vekaleti_sonlandir` ...) `flush` eder, `commit` etmez.
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


# --- Süreli vekâlet (TS-213, E13-15) ----------------------------------------------
#
# Vekâlet AYRI TABLO DEĞİLDİR: `user_permissions` satırına `baslangic_at` /
# `bitis_at` / `veren_id` (d4a000000002). `User.has()` tek kural olarak kalır;
# süreli satır yalnız istek anı aralıktayken sayılır. Kurallar (API
# `api/vekalet.py` uygular):
#   - `VEKALETE_KAPALI` izinler (yüksek yetki, maliyet, hak ediş ödeme/onay,
#     tahsilat, teklif onayı, `vekalet.ver`) vekâletle verilemez (403);
#   - veren yalnız KENDİ KALICI etkin izinlerinin alt kümesini verir — kendisine
#     vekâletle gelmiş izni zincirleme devredemez (403);
#   - en fazla `VEKALET_AZAMI_GUN` gün (CHECK + 400); kendine 400;
#   - verme ve iptalde alıcının oturumları düşer (yetki değişti).


def kalici_etkin_izinler(kisi: User) -> set[str]:
    """Rol + KALICI istisnalar (süreli vekâletler hariç).

    Vekâlet verilebilir izin kümesi budur: vekâletle gelen izin yeniden
    devredilseydi zincir 30 günlük sınırı ve "veren" izini anlamsızlaştırırdı.
    """
    kodlar = {rp.permission_code for rp in kisi.role.permissions}
    for ui in kisi.izin_istisnalari:
        if ui.sureli_mi:
            continue
        if ui.allow:
            kodlar.add(ui.permission_code)
        else:
            kodlar.discard(ui.permission_code)
    return kodlar


def vekalet_verilemeyenler(aktor: User, kodlar) -> tuple[list[str], list[str]]:
    """(vekâlete kapalı olanlar, aktörde kalıcı olarak bulunmayanlar), sıralı."""
    from app.permissions import VEKALETE_KAPALI

    istenen = set(kodlar)
    kapali = sorted(istenen & VEKALETE_KAPALI)
    sahip = kalici_etkin_izinler(aktor)
    eksik = sorted((istenen - VEKALETE_KAPALI) - sahip)
    return kapali, eksik


def zaman_metni(an) -> str:
    """Denetim kayıtlarında kıyaslanabilir zaman: UTC ISO 8601."""
    from datetime import UTC

    return an.astimezone(UTC).isoformat()


VEKALET_SONA_ERDI = "vekalet.sona_erdi"
VEKALET_IPTAL = "vekalet.iptal"


async def vekaleti_sonlandir(
    db: AsyncSession,
    satir,
    *,
    an,
    aktor_id: int | None,
    ip: str | None,
    neden: str,
) -> dict:
    """Süreli vekâleti `an` anında bitirir (iptal / işten çıkış).

    Başlamamışsa satır silinir (aralık boş kalırdı; CHECK `bitis > baslangic`);
    başlamışsa `bitis_at = an` — satır denetim için kalır, artık sayılmaz.
    Denetime `vekalet.iptal` yazılır; günlük "sona erdi" görevi aynı bitiş
    anını iptal kaydında bulduğu için ikinci satır yazmaz.
    """
    from app.services import audit

    kayit = {
        "izin": satir.permission_code,
        "onceki_bitis": zaman_metni(satir.bitis_at),
        "veren_id": satir.veren_id,
        "neden": neden,
    }
    if satir.baslangic_at >= an:
        kayit["bitis"] = None
        await db.delete(satir)
    else:
        satir.bitis_at = an
        kayit["bitis"] = zaman_metni(an)
    await db.flush()
    await audit.log(
        db,
        "users",
        VEKALET_IPTAL,
        entity_id=satir.user_id,
        new_value=kayit,
        user_id=aktor_id,
        ip=ip,
    )
    return kayit


async def kisinin_vekaletlerini_sonlandir(
    db: AsyncSession, kisi_id: int, *, an, aktor_id: int | None, ip: str | None
) -> int:
    """İşten çıkışta: kişiye verilmiş VE kişinin verdiği yürürlükteki/ileri
    tarihli vekâletler biter (TS-213 "işten çıkış erişimi").

    Ayrılan kişinin verdiği vekâlet, yetkinin kaynağı gittiği için sürmez;
    alıcının oturumları düşer.
    """
    from app.models import UserPermission
    from app.services import auth as auth_service

    satirlar = (
        await db.scalars(
            select(UserPermission).where(
                UserPermission.bitis_at.is_not(None),
                UserPermission.bitis_at > an,
                (UserPermission.user_id == kisi_id) | (UserPermission.veren_id == kisi_id),
            )
        )
    ).all()
    alicilar: set[int] = set()
    for s in satirlar:
        alicilar.add(s.user_id)
        await vekaleti_sonlandir(db, s, an=an, aktor_id=aktor_id, ip=ip, neden="isten_cikis")
    for alici in alicilar - {kisi_id}:
        await auth_service.revoke_all_sessions(db, alici)
    return len(satirlar)


async def suresi_dolan_vekaletleri_kaydet(db: AsyncSession, clock) -> str:
    """Worker görevi (günlük): süresi dolan vekâleti denetime BİR KEZ yazar.

    Süre kontrolü istek anında yapıldığı için yetki bu göreve bağlı DEĞİLDİR;
    görev yalnız "vekâlet şu anda sona erdi" olayını denetim izinde görünür
    kılar. İdempotent: aynı (kişi, izin, bitiş) için `vekalet.sona_erdi` ya da
    aynı bitişli `vekalet.iptal` kaydı varsa yazılmaz — tekrar koşan tur
    ikinci satır üretmez.
    """
    from app.models import AuditLog, UserPermission
    from app.services import audit

    an = clock.now()
    satirlar = (
        await db.scalars(
            select(UserPermission).where(
                UserPermission.bitis_at.is_not(None), UserPermission.bitis_at <= an
            )
        )
    ).all()
    if not satirlar:
        return "süresi dolan vekâlet yok"
    kayitli = {
        (r.entity_id, (r.new_value or {}).get("izin"), (r.new_value or {}).get("bitis"))
        for r in (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.entity == "users",
                    AuditLog.action.in_((VEKALET_SONA_ERDI, VEKALET_IPTAL)),
                    AuditLog.entity_id.in_(sorted({str(s.user_id) for s in satirlar})),
                )
            )
        ).all()
    }
    yazilan = 0
    for s in satirlar:
        bitis = zaman_metni(s.bitis_at)
        if (str(s.user_id), s.permission_code, bitis) in kayitli:
            continue
        await audit.log(
            db,
            "users",
            VEKALET_SONA_ERDI,
            entity_id=s.user_id,
            new_value={
                "izin": s.permission_code,
                "baslangic": zaman_metni(s.baslangic_at),
                "bitis": bitis,
                "veren_id": s.veren_id,
            },
        )
        yazilan += 1
    return f"süresi dolan vekâlet={len(satirlar)}, yeni denetim kaydı={yazilan}"
