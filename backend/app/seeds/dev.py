"""Referans veri yükleyici — tekrar çalıştırılabilir (idempotent).

Roller ve izinler `app/permissions.py` kataloğundan senkronlanır: katalogdan
silinen izin DB'den de silinir, eklenen eklenir. Böylece katalog tek kaynak
olarak kalır ve rol tanımı koddan sürüklenmez.

    uv run python -m app.seeds.dev                  # roller + izinler
    uv run python -m app.seeds.dev --admin ad soyad # ilk yöneticiyi de aç
"""

import argparse
import asyncio
import logging
import secrets
import sys

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import (
    BirimSirketi,
    KullaniciSirketi,
    Permission,
    Role,
    RolePermission,
    Sirket,
    User,
    UserUnit,
)
from app.permissions import (
    BIRIM_KAPSAMLARI,
    PERMISSIONS,
    ROLES,
    SIRKETLER,
    VARSAYILAN_BIRIM_SIRKETLERI,
    YALNIZ_OFIS_ROLLERI,
)
from app.services import auth as auth_service


async def sync_permissions(db: AsyncSession) -> tuple[int, int]:
    mevcut = {p.code: p for p in (await db.scalars(select(Permission))).all()}
    eklenen = guncellenen = 0
    for code, (module, description) in PERMISSIONS.items():
        row = mevcut.pop(code, None)
        if row is None:
            db.add(Permission(code=code, module=module, description=description))
            eklenen += 1
        elif (row.module, row.description) != (module, description):
            row.module, row.description = module, description
            guncellenen += 1
    # Katalogdan çıkarılan izinler: rol bağları CASCADE ile düşer.
    for code in mevcut:
        await db.execute(delete(Permission).where(Permission.code == code))
    await db.flush()
    return eklenen, guncellenen


async def sync_roles(db: AsyncSession) -> None:
    """Rol katalogunu senkronlar — ÖZELLEŞTİRİLMİŞ rollere dokunmadan.

    Senkron her açılışta koşuyor ve rolün izinlerini koddaki listeye
    EŞİTLİYORDU. Roller arayüzden düzenlenebilir hale gelince bu, yöneticinin
    değişikliğini bir sonraki yeniden başlatmada sessizce geri alırdı.

    Artık `ozellestirildi` işaretli roller atlanır. Bedeli gerçek: koda YENİ
    bir izin eklendiğinde bu rollere kendiliğinden inmez. Sessiz kalmasın
    diye log'a UYARI düşer — KVKK menüsü tam olarak böyle, kimsenin fark
    etmediği bir senkron eksiğinden kaybolmuştu.

    **ADMIN istisnadır** (E13-01 (3), TS-006): ADMIN her açılışta katalogdaki
    TÜM izinlere eşitlenir ve `ozellestirildi` bayrağı indirilir. ADMIN rolü
    bir kez arayüzden düzenlenmiş bir kurulumda yeni izinler (ör. `personel.*`)
    yöneticiye hiç inmez, sistemi yönetecek kimse kalmazdı. ADMIN rolünün
    API'den düzenlenmesi zaten 409'dur; bu satır eski kurulumları onarır.
    """
    atlanan: list[str] = []
    for code, (name, perms, scope) in ROLES.items():
        role = await db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(
                code=code,
                name=name,
                scope=scope,
                is_system=True,
                yalniz_ofis=code in YALNIZ_OFIS_ROLLERI,
            )
            db.add(role)
            await db.flush()
        elif code == "ADMIN":
            role.name, role.scope = name, scope
            role.ozellestirildi = False
            # Yönetici her yerden girer: ADMIN'i ofise kilitlemek (yanlış CIDR
            # girilince) sistemi yönetecek kimseyi bırakmazdı.
            role.yalniz_ofis = False
        elif role.ozellestirildi:
            # Ad ve kapsam da elle değiştirilmiş olabilir; ikisine de dokunma.
            eksik = set(perms) - {
                rp
                for rp in (
                    await db.scalars(
                        select(RolePermission.permission_code).where(
                            RolePermission.role_id == role.id
                        )
                    )
                ).all()
            }
            if eksik:
                atlanan.append(f"{code}: {', '.join(sorted(eksik))}")
            continue
        else:
            role.name, role.scope = name, scope
            # G3.8: erişim yeri kısıtı da katalogdan (özelleştirilmiş role dokunulmaz).
            role.yalniz_ofis = code in YALNIZ_OFIS_ROLLERI

        istenen = set(perms)
        # İlişkiye (role.permissions) DOKUNMUYORUZ: yeni eklenmiş bir nesnede
        # bu erişim tembel yükleme tetikler ve asenkron bağlamda MissingGreenlet
        # ile patlar. Açık sorgu hem güvenli hem de niyeti görünür kılıyor.
        var_olan = set(
            (
                await db.scalars(
                    select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
                )
            ).all()
        )
        for missing in istenen - var_olan:
            db.add(RolePermission(role_id=role.id, permission_code=missing))
        if fazla := var_olan - istenen:
            await db.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_code.in_(fazla),
                )
            )
    if atlanan:
        logging.getLogger("denge").warning(
            "Özelleştirilmiş rollere YENİ izinler inmedi — elle eklenecek "
            "(Kullanıcılar → Roller): %s",
            " | ".join(atlanan),
        )
    await db.flush()


async def sync_sirketler(db: AsyncSession) -> None:
    """Şirket kataloğu (KARARLAR 2026-11-04 §1): `SIRKETLER`'deki şirketler
    yoksa açılır, adı eşitlenir; `aktif` bayrağına DOKUNULMAZ (yönetici kararı).
    Birim → şirket eşlemesi yalnız EKSİK birim için varsayılandan yazılır;
    var olan eşleme (yönetici değiştirmiş olabilir) korunur."""
    mevcut = {s.kod: s for s in (await db.scalars(select(Sirket))).all()}
    for kod, ad in SIRKETLER.items():
        if kod not in mevcut:
            db.add(Sirket(kod=kod, ad=ad, aktif=True))
        elif mevcut[kod].ad != ad:
            mevcut[kod].ad = ad
    await db.flush()
    eslenen = set((await db.scalars(select(BirimSirketi.birim))).all())
    for birim, sirket in VARSAYILAN_BIRIM_SIRKETLERI.items():
        if birim not in eslenen:
            db.add(BirimSirketi(birim=birim, sirket_kod=sirket))
    await db.flush()


async def ensure_admin(db: AsyncSession, full_name: str) -> str | None:
    """İlk yöneticiyi açar. Kullanıcı zaten varsa dokunmaz ve None döner.

    Parola konsola bir kez basılır; kurulumu yapan kişi onu görmüş olur.
    Bu yüzden ilk girişte değiştirmek ZORUNLUDUR (`parola_degismeli`, TS-212).
    Süre sınırı (`gecici_parola_bitis`) konmaz: kurulum ile ilk giriş
    arasında kaç gün geçeceği belli değil, süresi dolan tek yönetici
    parolası sunucuda elle kurtarma gerektirirdi.
    """
    if await db.scalar(select(User).limit(1)):
        return None
    role = await db.scalar(select(Role).where(Role.code == "ADMIN"))
    parola = secrets.token_urlsafe(12)
    db.add(
        User(
            full_name=full_name,
            username="admin",
            password_hash=auth_service.hash_password(parola),
            role_id=role.id,
            parola_degismeli=True,
            # ADMIN bütün şirketleri seçer (üyelik satırı rol değişirse kaybolmasın).
            sirket_uyelikleri=[KullaniciSirketi(sirket_kod=k) for k in SIRKETLER],
        )
    )
    await db.flush()
    return parola


DEMO_PAROLA = "deneme1234"
# Canlıya geçişte pilot birim GUVENLIK (plan §5.1 adım 8); deneme de aynısı.
DEMO_BIRIM = "GUVENLIK"
DEMO_SAHA_ROLU = {"SERVIS_SEF": "SEF", "SERVIS_TEKNISYEN": "TEKNISYEN", "ATOLYE": "TEKNISYEN"}


async def ensure_demo_users(db: AsyncSession) -> int:
    """Her rolden bir kullanıcı — menünün role göre daraldığını elle görmek için.

    YALNIZ GELİŞTİRME. Sabit parola kullanır; üretimde asla çalıştırmayın
    (config.is_dev kontrolü çağıranın sorumluluğunda değil, bu yüzden burada
    yapılır).
    """
    from app.config import get_config

    if not get_config().is_dev:
        raise RuntimeError("--demo yalnız ENV=dev ortamında çalıştırılabilir")

    acilan = 0
    for code in ROLES:
        username = code.lower()
        if await db.scalar(select(User).where(User.username == username)):
            continue
        role = await db.scalar(select(Role).where(Role.code == code))
        kisi = User(
            full_name=f"Deneme {ROLES[code][0]}",
            username=username,
            password_hash=auth_service.hash_password(DEMO_PAROLA),
            role_id=role.id,
        )
        # Birim kapsamlı rol birimsiz HİÇBİR servis kaydı görmez (fail-closed);
        # deneme hesabı boş ekranla açılmasın diye pilot birim verilir.
        if ROLES[code][2] in BIRIM_KAPSAMLARI:
            kisi.birimler = [UserUnit(birim=DEMO_BIRIM, is_primary=True)]
        # Şirket üyeliği: deneme hesapları bütün şirketleri seçebilir (menünün
        # şirkete göre daraldığını elle görmek için).
        kisi.sirket_uyelikleri = [KullaniciSirketi(sirket_kod=k) for k in SIRKETLER]
        # Saha rolü olmayan kişi plana/işe atanamaz; deneme şef ve teknisyeni
        # boş atama listesiyle açılmasın.
        kisi.saha_rolu = DEMO_SAHA_ROLU.get(code)
        db.add(kisi)
        acilan += 1
    await db.flush()
    return acilan


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Denge ERP referans verisi")
    parser.add_argument("--admin", metavar="AD", help="İlk yöneticiyi bu adla aç")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Her rolden birer deneme kullanıcısı aç (YALNIZ GELİŞTİRME)",
    )
    args = parser.parse_args(argv)

    async with get_session_factory()() as db:
        eklenen, guncellenen = await sync_permissions(db)
        await sync_roles(db)
        await sync_sirketler(db)
        print(f"İzinler: {eklenen} eklendi, {guncellenen} güncellendi, toplam {len(PERMISSIONS)}")
        print(f"Roller : {len(ROLES)} rol senkronlandı")

        if args.demo:
            acilan = await ensure_demo_users(db)
            print(f"Deneme kullanıcıları: {acilan} hesap (parola: {DEMO_PAROLA})")

        if args.admin:
            parola = await ensure_admin(db, args.admin)
            if parola is None:
                print("Yönetici: zaten kullanıcı var, dokunulmadı")
            else:
                print("\n" + "=" * 52)
                print("  İlk yönetici açıldı")
                print("  Kullanıcı : admin")
                print(f"  Parola    : {parola}")
                print("  Bu parolayı şimdi kaydedin — bir daha gösterilmeyecek.")
                print("  İlk girişte parolayı değiştirmeniz istenecek.")
                print("=" * 52 + "\n")
        await db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
