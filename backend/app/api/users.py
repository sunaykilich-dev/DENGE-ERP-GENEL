"""Kullanıcı ve rol yönetimi (izin: sistem.kullanici).

Yetki yükseltme önlemi (TS-006, E13-01) burada uygulanır, kuralları
`services/yetki.py`'dedir: yüksek yetkili izinler yalnız ADMIN rolünde, ADMIN
rolünü yalnız ADMIN atar, ADMIN rolü katalogdan yönetilir (409), son aktif
ADMIN korunur (409), üst yetkili hedefe yalnız ADMIN dokunur (403). Her ret
`yetki.ret` eylemiyle denetime yazılır — ret de bir güvenlik olayıdır.

Dalga 4 (D4-A): yöneticinin belirlediği/ürettiği parola geçicidir (TS-212:
zorunlu değişim, 72 sa, tek giriş; üretilen parola yanıtta BİR KEZ döner);
kullanıcı düzenleme denetimi kişisel veri işaretlidir (E13-D03); istisna
uçları yalnız KALICI istisnaları yazar, süreli vekâlet `/api/vekalet`'tedir
(TS-213); erişim gözden geçirme `/api/erisim-gozden` (TS-214).
"""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.api.deps import ClockDep, DbDep, client_ip, require_permission
from app.models import (
    KullaniciSirketi,
    Role,
    RolePermission,
    Sirket,
    User,
    UserPermission,
    UserUnit,
)
from app.permissions import (
    BIRIM_KAPSAMLARI,
    BIRIMLER,
    PERMISSIONS,
    SCOPE_ALL,
    SCOPE_OWN_CUSTOMERS,
    SCOPE_OWN_JOBS,
    SCOPE_OWN_UNITS,
    SCOPES,
)
from app.schemas.auth import (
    KullaniciGuncellemeSonucu,
    RoleOut,
    UserCreate,
    UserOut,
    UserPatch,
)
from app.services import audit, yetki
from app.services import auth as auth_service
from app.services import sirketler as sirket_svc

router = APIRouter(prefix="/api", tags=["kullanicilar"])

AdminDep = Annotated[User, Depends(require_permission("sistem.kullanici"))]


async def _reddet(
    db,
    request: Request,
    aktor: User,
    *,
    entity: str,
    entity_id: int | str | None,
    durum: int,
    mesaj: str,
    ayrinti: dict | None = None,
) -> NoReturn:
    """Yetki reddini denetime yazar ve HTTP hatası fırlatır.

    Çağrı noktasında henüz HİÇBİR yazma yapılmamış olmalı: commit yalnız
    denetim satırını kalıcı kılar. Ret yazılmasaydı, kullanıcı yönetimi
    yetkisini zorlayan biri iz bırakmadan deneme yapabilirdi (E13-01 (8)).
    """
    await audit.log(
        db,
        entity,
        "yetki.ret",
        entity_id=entity_id,
        new_value={"neden": mesaj, **(ayrinti or {})},
        user_id=aktor.id,
        ip=client_ip(request),
    )
    await db.commit()
    raise HTTPException(durum, mesaj)


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
    # G3.8: rol yalnız ofis ağından kullanılır.
    yalniz_ofis: bool = False
    sayfalar: list[str]
    izinler: list[IzinSatiri]
    # Kullanıcı görünümünde doldurulur: bu izinlerin hangileri rolden değil,
    # kişiye özel istisnadan geliyor. Rol görünümünde daima boş.
    istisna_kodlari: list[str] = []


# Menüdeki ekran → onu açan izin. Arayüzdeki `MENU` tablosunun sunucu
# tarafındaki karşılığı: "bu kullanıcı hangi sayfaları görür" sorusu
# yöneticiye kod okumadan cevaplanabilmeli. İzin bir demetse "herhangi biri"
# yeter (MENU'deki liste izniyle aynı anlam).
_SAYFA_IZINLERI: list[tuple[str, str | tuple[str, ...]]] = [
    # Ana Panel (KARARLAR 2026-11-09 S8): bileşenleri izinle süzülür; servis ya
    # da teklif bileşeni görebilen her rol açar (`services/ana_panel_duzeni`).
    ("Ana Panel", ("servis.gor", "teklif.gor")),
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
    # --- Teknik Servis (plan §1.10; menü grubu "Teknik Servis") -------------
    ("Servis Paneli", "servis.gor"),
    ("Operasyon Merkezi", "operasyon.gor"),
    ("Servis İşleri", "servis.gor"),
    ("Planlama", "servis.gor"),
    ("Benim İşlerim", "zaman.yaz"),
    ("Ekipman Kütüğü", "ekipman.gor"),
    ("Planlı Bakım", "bakim.gor"),
    ("Atölye", "atolye.gor"),
    ("Kiralamalar", "kiralama.gor"),
    ("Kiralık Envanter", "kiralama.gor"),
    ("Yedek Parça", "parca.gor"),
    ("Saha / Zaman Takibi", "servis_rapor.gor"),
    ("Servis Raporları", "servis_rapor.gor"),
    ("Servis Maliyet", "maliyet.gor"),
    ("Fatura Devri", "tahsilat.gor"),
    ("Ana Veri Kalitesi", "hesap.birlestir"),
    ("Servis Tanımları", ("servis.tanim", "operasyon.yonet")),
    # --- İnsan Kaynakları ---------------------------------------------------
    ("Personel", "personel.gor"),
    ("Eğitim ve Gelişim", "egitim.gor"),
    ("Gelişim Kartım", "egitim.kendim"),
]


def _sayfa_acik(izin: str | tuple[str, ...], kodlar: set[str]) -> bool:
    return any(k in kodlar for k in izin) if isinstance(izin, tuple) else izin in kodlar


# Kapsam = (kısa etiket, açıklama). Yeni kapsamlar canlı ekranlarda (hesap,
# cihaz, hat, mobilite iş emri) TÜM kayıtları görür; kısıt yalnız teknik
# servis kayıtlarındadır — yönetici bunu rol seçerken bilmeli (plan §1.2).
_KAPSAMLAR: dict[str, tuple[str, str]] = {
    SCOPE_ALL: ("Tüm kayıtlar", "Tüm kayıtları görür"),
    SCOPE_OWN_CUSTOMERS: (
        "Yalnız kendi müşterileri",
        "Yalnız kendi müşterilerini ve onlara bağlı araç, cihaz, iş emrini görür",
    ),
    SCOPE_OWN_UNITS: (
        "Yalnız kendi birimi",
        "Servis işlerinde ve diğer teknik servis kayıtlarında yalnız üyesi olduğu "
        "birimleri görür (birimi yoksa hiçbirini); diğer modüllerde tüm kayıtlar",
    ),
    SCOPE_OWN_JOBS: (
        "Yalnız kendi işleri",
        "Servis işlerinde yalnız tayin edildiği ya da planında olduğu işleri, diğer teknik "
        "servis kayıtlarında üyesi olduğu birimleri görür (birimi yoksa hiçbirini); "
        "diğer modüllerde tüm kayıtlar",
    ),
}
_KAPSAM_ACIKLAMA = {kod: aciklama for kod, (_, aciklama) in _KAPSAMLAR.items()}


class KapsamSatiri(BaseModel):
    kod: str
    ad: str
    aciklama: str
    birim_zorunlu: bool


class BirimSatiri(BaseModel):
    kod: str
    ad: str


class SirketSecenegi(BaseModel):
    kod: str
    ad: str
    birimler: list[str] = []


class KapsamKatalogu(BaseModel):
    kapsamlar: list[KapsamSatiri]
    birimler: list[BirimSatiri]
    # Kullanıcı formundaki şirket üyeliği seçenekleri (aktif şirketler).
    sirketler: list[SirketSecenegi] = []


@router.get("/kapsamlar", response_model=KapsamKatalogu)
async def kapsam_katalogu(db: DbDep, _: AdminDep) -> KapsamKatalogu:
    """Rol kapsamları, birimler ve şirketler — rol/kullanıcı ekranının seçenekleri.

    Liste sunucudan gelir (E13-D02): ön yüzde sabit iki seçenek vardı ve yeni
    kapsamlar rol ekranından hiç seçilemiyordu.
    """
    return KapsamKatalogu(
        kapsamlar=[
            KapsamSatiri(kod=k, ad=ad, aciklama=ac, birim_zorunlu=k in BIRIM_KAPSAMLARI)
            for k, (ad, ac) in _KAPSAMLAR.items()
        ],
        birimler=[BirimSatiri(kod=k, ad=ad) for k, ad in BIRIMLER.items()],
        sirketler=[
            SirketSecenegi(kod=s.kod, ad=s.ad, birimler=list(s.birimler))
            for s in await sirket_svc.katalog(db)
        ],
    )


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
        yalniz_ofis=bool(rol.yalniz_ofis),
        sayfalar=[ad for ad, izin in _SAYFA_IZINLERI if _sayfa_acik(izin, kodlar)],
        izinler=[
            IzinSatiri(kod=k, modul=PERMISSIONS[k][0], aciklama=PERMISSIONS[k][1])
            for k in sorted(kodlar)
            if k in PERMISSIONS
        ],
        istisna_kodlari=sorted(istisna or []),
    )


@router.get("/kullanicilar/{user_id}/yetkiler", response_model=RolYetkisi)
async def kullanici_yetkileri(user_id: int, db: DbDep, clock: ClockDep, _: AdminDep) -> RolYetkisi:
    """Bu KİŞİNİN gerçekten açabildiği ekranlar ve yapabildiği işler.

    Rolün ham listesini göstermek yanıltıcıydı: istisnayla verilen yetki
    listede görünmez, geri alınan yetki hâlâ görünürdü. Kaynak `etkin_izinler`
    — yetki kontrolünün kullandığı kuralın ta kendisi. Yürürlükteki süreli
    vekâlet de (TS-213) "rolünden farklı" sayılır.
    """
    kisi = await db.get(User, user_id)
    if kisi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kullanıcı bulunamadı")
    an = clock.now()
    kisi.izin_anini_ata(an)
    return _yetki_gorunumu(
        kisi.role,
        set(kisi.etkin_izinler()),
        [u.permission_code for u in kisi.izin_istisnalari if u.allow and u.gecerli_mi(an)],
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
    # G3.8: rol yalnız ofis ağından (`ofis_ag_listesi`) kullanılır.
    yalniz_ofis: bool = False


class RolPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    scope: str | None = None
    izinler: list[str] | None = None
    yalniz_ofis: bool | None = None


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


def _bilinmeyenleri_reddet(kodlar: list[str]) -> None:
    gecersiz = [k for k in kodlar if k not in PERMISSIONS]
    if gecersiz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen izin: {', '.join(gecersiz)}")


async def _verilemeyenleri_reddet(
    db, request: Request, aktor: User, kodlar: list[str], *, entity: str, entity_id
) -> None:
    """Yüksek yetkili ya da aktörde olmayan izin istenirse 403 + denetim."""
    if verilemez := yetki.verilemeyen_izinler(aktor, kodlar):
        await _reddet(
            db,
            request,
            aktor,
            entity=entity,
            entity_id=entity_id,
            durum=status.HTTP_403_FORBIDDEN,
            mesaj=f"Bu izinleri veremezsiniz: {', '.join(verilemez)}",
            ayrinti={"izinler": verilemez},
        )


@router.post("/roller", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def rol_olustur(payload: RolIn, request: Request, db: DbDep, user: AdminDep) -> RoleOut:
    """Yeni rol. Kod BÜYÜK HARF ve değiştirilemez — yetki kontrolleri ona bakar.

    Yüksek yetkili izin (`sistem.*`, `kvkk.yonet`) özel role konamaz (403):
    yalnız ADMIN rolünde bulunur.
    """
    if payload.scope not in SCOPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz kapsam")
    if await db.scalar(select(Role).where(Role.code == payload.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bu rol kodu zaten var: {payload.code}")
    _bilinmeyenleri_reddet(payload.izinler)
    await _verilemeyenleri_reddet(
        db, request, user, payload.izinler, entity="roles", entity_id=payload.code
    )

    rol = Role(
        code=payload.code,
        name=payload.name,
        scope=payload.scope,
        is_system=False,
        ozellestirildi=True,
        yalniz_ofis=payload.yalniz_ofis,
    )
    db.add(rol)
    await db.flush()
    await _rol_izinlerini_yaz(db, rol, payload.izinler)
    await audit.log(
        db,
        "roles",
        "olustur",
        entity_id=rol.id,
        new_value={
            "kod": rol.code,
            "ad": rol.name,
            "izin": len(payload.izinler),
            "yalniz_ofis": rol.yalniz_ofis,
        },
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
    if rol.code == yetki.ROL_ADMIN:
        # İzinleri boşaltılabilen ADMIN herkesi kilitlerdi; ADMIN her açılışta
        # katalogdaki tüm izinlere eşitlenir (seeds/dev.py sync_roles).
        await _reddet(
            db,
            request,
            user,
            entity="roles",
            entity_id=rol.id,
            durum=status.HTTP_409_CONFLICT,
            mesaj="Sistem yöneticisi rolü katalogdan yönetilir; düzenlenemez.",
            ayrinti={"kod": rol.code},
        )
    if payload.scope is not None and payload.scope not in SCOPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Geçersiz kapsam")
    if payload.izinler is not None:
        _bilinmeyenleri_reddet(payload.izinler)
        await _verilemeyenleri_reddet(
            db, request, user, payload.izinler, entity="roles", entity_id=rol.id
        )

    eski = {"ad": rol.name, "kapsam": rol.scope, "yalniz_ofis": rol.yalniz_ofis}
    if payload.name is not None:
        rol.name = payload.name
    if payload.scope is not None:
        rol.scope = payload.scope
    if payload.yalniz_ofis is not None:
        rol.yalniz_ofis = payload.yalniz_ofis
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
            "yalniz_ofis": rol.yalniz_ofis,
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
    _bilinmeyenleri_reddet([i.permission_code for i in payload])
    # Üst yetkili hedefin (kısma dahil) istisnasına yalnız ADMIN dokunur.
    try:
        yetki.hedef_kontrol(user, hedef)
    except yetki.YetkiHatasi as e:
        await _reddet(
            db,
            request,
            user,
            entity="users",
            entity_id=hedef.id,
            durum=status.HTTP_403_FORBIDDEN,
            mesaj=str(e),
            ayrinti={"islem": "izin.istisna"},
        )
    # Kısma (`allow=False`) her zaman serbest; VERME alt küme ve yüksek yetki
    # kuralına tabi.
    if verilemez := yetki.verilemeyen_izinler(
        user,
        [i.permission_code for i in payload if i.allow],
        hedef_admin=yetki.admin_mi(hedef),
    ):
        await _reddet(
            db,
            request,
            user,
            entity="users",
            entity_id=hedef.id,
            durum=status.HTTP_403_FORBIDDEN,
            mesaj=f"Bu izinleri veremezsiniz: {', '.join(verilemez)}",
            ayrinti={"islem": "izin.istisna", "izinler": verilemez},
        )

    # Yalnız KALICI istisnalar bu ucun konusudur. Süreli vekâlet satırları
    # (`bitis_at` dolu, TS-213) `/api/vekalet` ile yönetilir; toptan silme
    # onları da götürüyordu. Aynı izin için kalıcı istisna yazılırsa o izindeki
    # vekâlet satırı kalıcı karara yer açmak için kaldırılır ve denetime girer.
    istenen_kodlar = {i.permission_code for i in payload}
    mevcut = (
        await db.scalars(select(UserPermission).where(UserPermission.user_id == user_id))
    ).all()
    eski = [{"kod": u.permission_code, "allow": u.allow} for u in mevcut if not u.sureli_mi]
    ezilen_vekalet = sorted(
        u.permission_code for u in mevcut if u.sureli_mi and u.permission_code in istenen_kodlar
    )
    await db.execute(
        delete(UserPermission).where(
            UserPermission.user_id == user_id,
            or_(
                UserPermission.bitis_at.is_(None),
                UserPermission.permission_code.in_(istenen_kodlar),
            ),
        )
    )
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
        new_value={
            "istisnalar": [{"kod": i.permission_code, "allow": i.allow} for i in payload],
            **({"kaldirilan_vekalet": ezilen_vekalet} if ezilen_vekalet else {}),
        },
        user_id=user.id,
        ip=client_ip(request),
    )
    await db.commit()
    return payload


@router.get("/kullanicilar/{user_id}/izinler", response_model=list[IstisnaIn])
async def istisnalari_getir(user_id: int, db: DbDep, _: AdminDep) -> list[IstisnaIn]:
    """Kalıcı istisnalar (süreli vekâletler `/api/vekalet/{personel_id}`)."""
    kayitlar = (
        await db.scalars(
            select(UserPermission).where(
                UserPermission.user_id == user_id, UserPermission.bitis_at.is_(None)
            )
        )
    ).all()
    return [
        IstisnaIn(permission_code=u.permission_code, allow=u.allow, gerekce=u.gerekce or "—")
        for u in kayitlar
    ]


class KullaniciSatiri(UserOut):
    """Liste satırı: kullanıcı + rolünden sapma göstergesi (E13-10).

    `sapma_sayisi` kişiye özel istisna satırı sayısıdır; aynı roldeki iki
    kişinin neden farklı şey gördüğü listede rozetle görünür. `UserOut`'a
    değil yalnız listeye eklenir: giriş yanıtı bunu taşımaz.
    """

    sapma_sayisi: int = 0
    # Yürürlükteki süreli vekâlet sayısı (TS-213); kalıcı sapmadan ayrı
    # gösterilir: biri yönetici kararı, öteki süresi dolunca kendiliğinden biter.
    vekalet_sayisi: int = 0
    rol_ozellestirildi: bool = False
    version: int | None = None


@router.get("/kullanicilar", response_model=list[KullaniciSatiri])
async def list_users(db: DbDep, clock: ClockDep, _: AdminDep) -> list[KullaniciSatiri]:
    an = clock.now()
    users = (await db.scalars(select(User).order_by(User.username))).all()
    satirlar = []
    for u in users:
        u.izin_anini_ata(an)
        satirlar.append(
            KullaniciSatiri(
                **UserOut.of(u).model_dump(),
                sapma_sayisi=sum(1 for i in u.izin_istisnalari if not i.sureli_mi),
                vekalet_sayisi=sum(
                    1 for i in u.izin_istisnalari if i.sureli_mi and i.gecerli_mi(an)
                ),
                rol_ozellestirildi=bool(u.role.ozellestirildi),
                version=u.version,
            )
        )
    return satirlar


def _birimleri_dogrula(
    rol: Role, birimler: list[str], birincil: str | None
) -> tuple[list[str], str | None]:
    """Açılışta verilen birimleri doğrular; (sıralı birimler, birincil) döner.

    Birim kapsamlı rolde birimsiz hesap 400 (E13-11): birimsiz şef hiçbir servis
    kaydı görmezdi (fail-closed) ve bunu kimse fark etmezdi.
    """
    if bilinmeyen := sorted(set(birimler) - set(BIRIMLER)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bilinmeyen birim: {', '.join(bilinmeyen)}"
        )
    temiz = sorted(set(birimler))
    if rol.scope in BIRIM_KAPSAMLARI and not temiz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bu rol için en az bir birim seçilmeli")
    if birincil is not None and birincil not in temiz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Birincil birim seçili birimlerden olmalı")
    if birincil is None and temiz:
        birincil = temiz[0]
    return temiz, birincil


async def _sirketleri_dogrula(db, kodlar: list[str]) -> list[str]:
    """Şirket kodları katalogda (DB) olmalı; boş liste 400 — üyeliksiz kullanıcı
    hiçbir şirkete giremez, bunu sessizce açmak yerine yönetici açıkça seçer."""
    temiz = sorted(set(kodlar))
    if not temiz:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "En az bir şirket seçilmeli")
    var = set((await db.scalars(select(Sirket.kod).where(Sirket.kod.in_(temiz)))).all())
    if bilinmeyen := [k for k in temiz if k not in var]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Bilinmeyen şirket: {', '.join(bilinmeyen)}"
        )
    return temiz


@router.post("/kullanicilar", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, request: Request, db: DbDep, clock: ClockDep, admin: AdminDep
) -> UserOut:
    """Yeni kullanıcı. Yöneticinin verdiği parola GEÇİCİDİR (TS-212): kullanıcı
    ilk girişte değiştirir; 72 saat içinde ve tek girişte geçerlidir."""
    if await db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu kullanıcı adı zaten var")
    role = await db.scalar(select(Role).where(Role.code == payload.role_code))
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen rol: {payload.role_code}")
    birimler, birincil = _birimleri_dogrula(role, payload.birimler, payload.birincil_birim)
    if payload.sirketler is not None:
        sirket_kodlari = await _sirketleri_dogrula(db, payload.sirketler)
    else:
        sirket_kodlari = await sirket_svc.varsayilan_uyelik(db, role, birimler)
    if not yetki.rol_atanabilir_mi(admin, role):
        await _reddet(
            db,
            request,
            admin,
            entity="users",
            entity_id=None,
            durum=status.HTTP_403_FORBIDDEN,
            mesaj=f"Bu rolü atayamazsınız: {role.code}",
            ayrinti={"islem": "olustur", "username": payload.username, "rol": role.code},
        )

    user = User(
        full_name=payload.full_name,
        username=payload.username,
        email=payload.email,
        role_id=role.id,
    )
    auth_service.gecici_parola_ata(user, payload.password, clock)
    user.birimler = [
        UserUnit(birim=b, is_primary=(b == birincil), created_by=admin.id) for b in birimler
    ]
    user.sirket_uyelikleri = [
        KullaniciSirketi(sirket_kod=k, created_by=admin.id) for k in sirket_kodlari
    ]
    db.add(user)
    await db.flush()
    yeni = {"username": user.username, "rol": role.code, "sirketler": sirket_kodlari}
    if birimler:
        yeni["birimler"] = birimler
    await audit.log(
        db,
        "users",
        "olustur",
        entity_id=user.id,
        new_value=yeni,
        user_id=admin.id,
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(user)
    return UserOut.of(user)


@router.patch("/kullanicilar/{user_id}", response_model=KullaniciGuncellemeSonucu)
async def patch_user(
    user_id: int,
    payload: UserPatch,
    request: Request,
    db: DbDep,
    clock: ClockDep,
    admin: AdminDep,
) -> KullaniciGuncellemeSonucu:
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
        if payload.giris_acik is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendi girişinizi kapatamazsınız")
        if payload.role_code is not None and payload.role_code != user.role.code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kendi rolünüzü değiştiremezsiniz")
        if payload.password is not None or payload.parola_sifirla:
            # Kendi parolası `POST /api/auth/parola` ile (mevcut parola ister);
            # burada geçici parola üretmek kendini "zorunlu değişime" kilitlerdi.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Kendi parolanızı Parola Değiştir ekranından değiştirin.",
            )
    if payload.password is not None and payload.parola_sifirla:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Parola belirleme ve geçici parola üretme birlikte istenemez.",
        )

    # --- Yetki yükseltme önlemi: HİÇBİR şey yazılmadan önce ------------------
    role = None
    rol_degisiyor = False
    if payload.role_code is not None:
        role = await db.scalar(select(Role).where(Role.code == payload.role_code))
        if role is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bilinmeyen rol: {payload.role_code}")
        rol_degisiyor = role.id != user.role_id
    ret = {"entity": "users", "entity_id": user.id}
    if (
        payload.is_active is False or payload.giris_acik is False or rol_degisiyor
    ) and await yetki.son_admin_mi(db, user):
        await _reddet(
            db,
            request,
            admin,
            **ret,
            durum=status.HTTP_409_CONFLICT,
            mesaj="Giriş yapabilen son sistem yöneticisi kapatılamaz ve rolü değiştirilemez.",
            ayrinti={"islem": "guncelle"},
        )
    if user.id != admin.id:
        try:
            yetki.hedef_kontrol(admin, user)
        except yetki.YetkiHatasi as e:
            await _reddet(
                db,
                request,
                admin,
                **ret,
                durum=status.HTTP_403_FORBIDDEN,
                mesaj=str(e),
                ayrinti={"islem": "guncelle"},
            )
    if rol_degisiyor:
        if not yetki.rol_atanabilir_mi(admin, role):
            await _reddet(
                db,
                request,
                admin,
                **ret,
                durum=status.HTTP_403_FORBIDDEN,
                mesaj=f"Bu rolü atayamazsınız: {role.code}",
                ayrinti={"islem": "guncelle", "rol": role.code},
            )
        if role.scope in BIRIM_KAPSAMLARI and not user.birimler:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Bu rol için en az bir birim gerekli; önce personel kartından birim verin.",
            )

    yeni_sirketler = (
        await _sirketleri_dogrula(db, payload.sirketler) if payload.sirketler is not None else None
    )

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.giris_acik is not None:
        user.giris_acik = payload.giris_acik
    if role is not None:
        user.role_id = role.id
    # Yönetici parolası GEÇİCİDİR (TS-212): zorunlu değişim + 72 sa + tek giriş.
    gecici: str | None = None
    if payload.password is not None:
        auth_service.gecici_parola_ata(user, payload.password, clock)
    elif payload.parola_sifirla:
        gecici = auth_service.gecici_parola_uret()
        auth_service.gecici_parola_ata(user, gecici, clock)
    if payload.reset_mfa:
        user.mfa_enabled = False
        user.totp_secret = None

    # Değişiklik ne olursa olsun eski/yeni değerleriyle loglanır. Kişisel veri
    # (ad, e-posta) taşıdığı için `is_personal_data=True` (E13-D03): denetim
    # tetikleyicisi (`trg_audit_degistirilemez`) yalnız bu satırları KVKK
    # anonimleştirmesinde maskelemeye izin verir; bayraksız satır bir daha
    # maskelenemezdi. Parola özeti ve geçici parola ZATEN yazılmaz (`***`).
    await audit.log_change(
        db, user, "guncelle", user_id=admin.id, ip=client_ip(request), is_personal_data=True
    )
    # Şirket üyeliği (KARARLAR 2026-11-04 §1) ilişki tablosundadır; `log_change`
    # yalnız kolonları gördüğü için ayrı denetim satırı yazılır.
    if yeni_sirketler is not None and yeni_sirketler != user.sirket_kodlari:
        eski_sirketler = user.sirket_kodlari
        mevcut = {u.sirket_kod: u for u in user.sirket_uyelikleri}
        for kod, uyelik in mevcut.items():
            if kod not in yeni_sirketler:
                user.sirket_uyelikleri.remove(uyelik)
        for kod in yeni_sirketler:
            if kod not in mevcut:
                user.sirket_uyelikleri.append(KullaniciSirketi(sirket_kod=kod, created_by=admin.id))
        await audit.log(
            db,
            "users",
            "sirket_uyeligi",
            entity_id=user.id,
            old_value={"sirketler": eski_sirketler},
            new_value={"sirketler": yeni_sirketler},
            user_id=admin.id,
            ip=client_ip(request),
        )

    # Yetki, parola, aktiflik veya giriş değiştiyse açık oturumları düşür: eski
    # yetkiyle açılmış bir oturum yeni kısıtı görmezdi; girişi kapatılan kişinin
    # açık oturumu da hemen düşmeli (TS-007).
    if (
        payload.role_code is not None
        or payload.password is not None
        or payload.parola_sifirla
        or payload.is_active is False
        or payload.giris_acik is False
        or payload.reset_mfa
    ):
        await auth_service.revoke_all_sessions(db, user.id)

    await db.commit()
    await db.refresh(user)
    user.izin_anini_ata(clock.now())
    return KullaniciGuncellemeSonucu(
        **UserOut.of(user).model_dump(),
        gecici_parola=gecici,
        gecici_parola_bitis=user.gecici_parola_bitis if gecici else None,
    )


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


# --- Dalga 4 alt router'ları (TS-213, TS-214) -------------------------------------
# `main.py` Dalga 4'te D4-S'te donmuş olduğu için yeni kimlik güvenliği uçları
# bu router'a bağlanır; yollar yine `/api/vekalet` ve `/api/erisim-gozden`.
# İçe aktarma dosya SONUNDA: alt modüller bu dosyaya bağımlı değildir.
from app.api import erisim_gozden as _erisim_gozden  # noqa: E402
from app.api import vekalet as _vekalet  # noqa: E402

router.include_router(_vekalet.router)
router.include_router(_erisim_gozden.router)
