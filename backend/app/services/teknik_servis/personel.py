"""Personel kartı, birim üyeliği ve atanabilir personel (TS-002, TS-008, TS-009).

**Personel = kullanıcı** (plan §1.1, E13-05): ayrı `personnel` tablosu yok;
girişi olmayan saha personeli de bir `users` satırıdır (`giris_acik=false`).
Bu modül yalnız PERSONEL alanlarını (sicil, ünvan, saha rolü, birim, işe
giriş, not) yazar. Rol, izin, parola ve giriş aç/kapat kullanıcı yönetiminin
(`api/users.py`, `sistem.kullanici`) işidir; burada YOKTUR. Böylece İK
personel kartını düzenlerken kimseye yetki veremez.

Kurallar (hepsi burada, tek yerde; `flush` yapar, `commit` YAPMAZ):

- **Üst yetkili hedef** (ADMIN ya da yüksek yetkili izin sahibi) yalnız ADMIN
  tarafından değiştirilebilir — birim yazma, aktifleştirme ve ad değişikliği
  403 (`yetki.hedef_kontrol`). İstisna (E13 kontrol E13-05b): ünvan ve sicil
  gibi künye alanları İK tarafından da düzeltilebilir; ad DEĞİŞTİRİLEMEZ, aksi
  halde İK yöneticinin adını değiştirip denetim izini karıştırabilirdi.
- **Kendi birimini değiştiremez** (403): birim kapsamı belirler; kişi kendi
  kapsamını genişletemesin.
- **Birim değişince oturumlar düşer** (E13-02): eski oturum eski kapsamı
  taşırdı.
- **Yeniden aktifleştirme girişi AÇMAZ** (E13-03): `is_active=true` olur,
  `giris_acik` olduğu gibi kalır. Giriş ayrıca ve geçici parolayla açılır.
- Kişisel veri değişiklikleri denetime `is_personal_data=True` ile yazılır
  (sicil, not, ayrılış nedeni kişisel veridir; işaretsiz satır ileride KVKK
  imhasında maskelenemez).

**Atanabilir personel (TS-009)** tek kaynaktır: planlama kaynak listesi,
plan penceresi ve atama (D1-B/D1-D) kişi seçicileri yalnız buradan beslenir;
gömülü isim listesi kalmaz. Ölçüt: aktif, ayrılmamış, saha rolü
SEF/TEKNISYEN/STAJYER, birim üyesi. `giris_acik` SÜZÜLMEZ — girişsiz stajyer
de sahaya gider; listede "giriş yok" bayrağıyla görünür.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Select, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, User, UserUnit
from app.models.rbac import BIRIM_KODLARI
from app.models.user import SAHA_ROLLERI
from app.permissions import ATANABILIR_SAHA_ROLLERI, SCOPE_ALL, SCOPE_OWN_JOBS
from app.services import audit, yetki
from app.services import auth as auth_service
from app.services.normalize import tr_normkey
from app.services.teknik_servis import kapsam

# Girişsiz personelin rolü (E13 K-12): giriş kapalıyken etkisizdir; giriş
# açılırken rol bilinçli seçilir.
VARSAYILAN_PERSONEL_ROLU = "SERVIS_TEKNISYEN"

# Personel kartında düzenlenebilen alanlar. Rol/izin/parola/giriş/e-posta
# BURADA YOK (kullanıcı yönetimi). Ayrılış alanları işten çıkış akışının
# (TS-165), yönetici ilişkisi "Ekibim"in (TS-199) işidir.
KART_ALANLARI = ("full_name", "sicil_no", "unvan", "saha_rolu", "ise_giris_tarihi", "personel_notu")
# Üst yetkili hedefte ADMIN olmayan aktörün de düzeltebileceği künye alanları.
UST_YETKILIDE_SERBEST = frozenset({"sicil_no", "unvan", "ise_giris_tarihi"})

PERSONEL_DURUMLARI = ("CALISIYOR", "AYRILDI")
GIRIS_DURUMLARI = ("ACIK", "KAPALI")
# Saha rolü süzgecinin özel değerleri: ATANABILIR = SEF/TEKNISYEN/STAJYER,
# EKSIK = saha rolü girilmemiş (atanamaz; KPI'da ayrıca sayılır).
SAHA_SUZGECLERI = (*SAHA_ROLLERI, "ATANABILIR", "EKSIK")


class PersonelGirdiHatasi(ValueError):
    """Girdi hatası (katalog dışı birim, eksik birincil) — API 400."""


class PersonelKuralHatasi(ValueError):
    """İş kuralı ihlali (iki birincil, aynı sicil, sürüm çakışması) — API 409."""


class PersonelKapsamDisi(ValueError):
    """Hedef kişi ya da birim aktörün kapsamı dışında — API 404."""


# --- Birim üyeliği (TS-002) ---------------------------------------------------


@dataclass(frozen=True)
class BirimSatiri:
    birim: str
    birincil: bool = False


def birim_satirlarini_dogrula(satirlar: Sequence[BirimSatiri]) -> list[BirimSatiri]:
    """Katalog, tekrar ve birincil kurallarını sınar; temiz listeyi döner.

    - Katalog dışı birim → 400 (CHECK de yakalar ama kullanıcıya kısıt adı
      değil anlaşılır mesaj gitsin).
    - Aynı birim iki kez → 400.
    - İki birincil → 409 (`uq_user_units_birincil` kuralının erken hâli).
    - Birim varsa tam bir birincil zorunlu → 400: birincil, ekranın
      varsayılan birimi ve rapor kırılımıdır; boş kalırsa kişi raporda
      "birimsiz" sayılırdı.
    """
    temiz: list[BirimSatiri] = []
    gorulen: set[str] = set()
    for s in satirlar:
        birim = (s.birim or "").strip().upper()
        if birim not in BIRIM_KODLARI:
            raise PersonelGirdiHatasi(
                f"Bilinmeyen birim: {s.birim} (geçerli: {', '.join(BIRIM_KODLARI)})"
            )
        if birim in gorulen:
            raise PersonelGirdiHatasi(f"Birim iki kez yazılmış: {birim}")
        gorulen.add(birim)
        temiz.append(BirimSatiri(birim=birim, birincil=bool(s.birincil)))
    birincil_sayisi = sum(1 for s in temiz if s.birincil)
    if birincil_sayisi > 1:
        raise PersonelKuralHatasi("Bir kişinin yalnız bir birincil birimi olabilir.")
    if temiz and birincil_sayisi == 0:
        raise PersonelGirdiHatasi("Birimlerden biri birincil olarak işaretlenmeli.")
    return temiz


def _birim_ozeti(satirlar: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {
            "birim": s.birim,
            "birincil": bool(getattr(s, "is_primary", getattr(s, "birincil", False))),
        }
        for s in sorted(satirlar, key=lambda x: x.birim)
    ]


async def birimleri_yaz(
    db: AsyncSession,
    hedef: User,
    satirlar: Sequence[BirimSatiri],
    *,
    aktor: User,
    ip: str | None = None,
    yeni_kayit: bool = False,
) -> list[dict[str, Any]]:
    """Kişinin birim üyeliğini verilen listeye eşitler (TS-002, E13-06).

    Sıra önemlidir: önce yetki (kendi birimi 403, üst yetkili 403), sonra
    kapsam (aktörün göremediği birime ekleme/çıkarma 404), en son girdi.
    Kapsamlı aktör (ör. `KENDI_BIRIMI`) yalnız kendi birimlerini ekleyip
    çıkarabilir — kişiyi başka birime taşıyıp kapsamını genişletemesin
    (`api/accounts.py` temsilci ataması emsali).

    Denetim kaydı ve oturum düşürme burada: kullanıcı ekranı da aynı
    fonksiyonu çağırdığında ikisi unutulamaz.
    """
    if hedef.id == aktor.id:
        raise yetki.YetkiHatasi("Kendi biriminizi değiştiremezsiniz.")
    yetki.hedef_kontrol(aktor, hedef)

    temiz = birim_satirlarini_dogrula(satirlar)
    eski = _birim_ozeti(hedef.birimler)
    eski_kume = {s["birim"] for s in eski}
    yeni_kume = {s.birim for s in temiz}
    for birim in eski_kume ^ yeni_kume:
        if kapsam.birim_disinda_mi(aktor, birim):
            raise PersonelKapsamDisi("Personel bulunamadı")

    mevcut = {u.birim: u for u in hedef.birimler}
    # Önce birincil bayrakları indirilir: kısmi tekil indeks
    # (`uq_user_units_birincil`) satır satır denetlendiği için birincili
    # A'dan B'ye taşırken ara durumda iki birincil oluşup flush patlardı.
    for u in mevcut.values():
        if u.is_primary:
            u.is_primary = False
    await db.flush()
    for birim, u in list(mevcut.items()):
        if birim not in yeni_kume:
            hedef.birimler.remove(u)
    await db.flush()
    for s in temiz:
        if s.birim in mevcut and s.birim in yeni_kume:
            mevcut[s.birim].is_primary = s.birincil
            mevcut[s.birim].updated_by = aktor.id
        else:
            hedef.birimler.append(
                UserUnit(
                    user_id=hedef.id,
                    birim=s.birim,
                    is_primary=s.birincil,
                    created_by=aktor.id,
                    updated_by=aktor.id,
                )
            )
    await db.flush()

    yeni = _birim_ozeti(temiz)
    if eski != yeni:
        if not yeni_kayit:
            # Kapsam değişti: açık oturum eski birimlerle yetki taşırdı.
            await auth_service.revoke_all_sessions(db, hedef.id)
        await audit.log(
            db,
            "users",
            "birim.degistir",
            entity_id=hedef.id,
            old_value={"birimler": eski},
            new_value={"birimler": yeni},
            user_id=aktor.id,
            ip=ip,
            is_personal_data=True,
        )
    return yeni


# --- Personel kartı (TS-008) ---------------------------------------------------


@dataclass
class PersonelGirdisi:
    """Girişsiz personel açılışı (`POST /api/personel`)."""

    full_name: str
    sicil_no: str | None = None
    unvan: str | None = None
    saha_rolu: str | None = None
    ise_giris_tarihi: date | None = None
    personel_notu: str | None = None
    birimler: list[BirimSatiri] = field(default_factory=list)


def _saha_rolu_dogrula(deger: str | None) -> str | None:
    if deger is None:
        return None
    deger = deger.strip().upper()
    if deger not in SAHA_ROLLERI:
        raise PersonelGirdiHatasi(
            f"Bilinmeyen saha rolü: {deger} (geçerli: {', '.join(SAHA_ROLLERI)})"
        )
    return deger


def _sicil_temizle(deger: str | None) -> str | None:
    if deger is None:
        return None
    deger = deger.strip()
    return deger or None


async def sicil_cakisiyor_mu(db: AsyncSession, sicil_no: str, haric_id: int | None = None) -> bool:
    stmt = select(User.id).where(User.sicil_no == sicil_no)
    if haric_id is not None:
        stmt = stmt.where(User.id != haric_id)
    return (await db.scalar(stmt.limit(1))) is not None


def rastgele_parola_ozeti() -> str:
    """Kimsenin bilmediği bir sırrın argon2 özeti.

    `password_hash` NOT NULL. "!" gibi GEÇERSİZ bir özet KULLANILMAZ:
    `verify_password` geçersiz özette `VerifyMismatchError` değil
    `InvalidHash` fırlatır ve giriş denemesi 500 doğururdu (E13 kontrol).
    """
    return auth_service.hash_password(secrets.token_urlsafe(32))


async def kullanici_adi_uret(db: AsyncSession, sicil_no: str | None) -> str:
    """`p.<sicil>` ya da `p.<rastgele>` — girişsiz personelin teknik adı.

    Kullanıcı adı yalnız tekillik için var (giriş kapalı). `p.<id>` olamaz:
    insert öncesi id bilinmez ve iki adımlı güncelleme gerekirdi.
    """
    taban = ""
    if sicil_no:
        taban = re.sub(r"[^a-z0-9]+", "", tr_normkey(sicil_no))[:40]
    aday = f"p.{taban}" if taban else f"p.{secrets.token_hex(4)}"
    while await db.scalar(select(User.id).where(User.username == aday).limit(1)) is not None:
        aday = f"p.{taban + '.' if taban else ''}{secrets.token_hex(3)}"
    return aday


async def personel_olustur(
    db: AsyncSession, girdi: PersonelGirdisi, *, aktor: User, ip: str | None = None
) -> User:
    """Girişsiz personel açar (E13-05): `giris_acik=false`, rastgele parola.

    Rol `SERVIS_TEKNISYEN`; giriş kapalıyken etkisizdir. Aynı sicil 409
    (`uq_users_sicil_no` de korur; önceden sorulur ki mesaj anlaşılır olsun).
    Kapsamlı aktör birimsiz ya da kapsamı dışında birimli kişi açamaz:
    açtığı kaydı bir daha göremezdi (birimsiz personel yalnız TUMU'ya görünür).
    """
    ad = (girdi.full_name or "").strip()
    if len(ad) < 2:
        raise PersonelGirdiHatasi("Ad soyad en az 2 karakter olmalı.")
    sicil = _sicil_temizle(girdi.sicil_no)
    if sicil and await sicil_cakisiyor_mu(db, sicil):
        raise PersonelKuralHatasi(f"Bu sicil numarası başka bir personelde kayıtlı: {sicil}")
    birimler = birim_satirlarini_dogrula(girdi.birimler)
    if aktor.role.scope != SCOPE_ALL:
        if not birimler:
            raise PersonelGirdiHatasi("Personelin en az bir birimi olmalı.")
        for s in birimler:
            if kapsam.birim_disinda_mi(aktor, s.birim):
                raise PersonelKapsamDisi("Birim bulunamadı")

    rol = await db.scalar(select(Role).where(Role.code == VARSAYILAN_PERSONEL_ROLU))
    if rol is None:
        raise PersonelKuralHatasi(
            f"Varsayılan personel rolü ({VARSAYILAN_PERSONEL_ROLU}) tanımlı değil."
        )

    kisi = User(
        full_name=ad,
        username=await kullanici_adi_uret(db, sicil),
        password_hash=rastgele_parola_ozeti(),
        role_id=rol.id,
        is_active=True,
        giris_acik=False,
        sicil_no=sicil,
        unvan=(girdi.unvan or "").strip() or None,
        saha_rolu=_saha_rolu_dogrula(girdi.saha_rolu),
        ise_giris_tarihi=girdi.ise_giris_tarihi,
        personel_notu=girdi.personel_notu,
    )
    db.add(kisi)
    await db.flush()
    await db.refresh(kisi, ["birimler", "role", "izin_istisnalari"])
    await audit.log(
        db,
        "users",
        "personel.olustur",
        entity_id=kisi.id,
        new_value={
            "ad": kisi.full_name,
            "sicil_no": kisi.sicil_no,
            "saha_rolu": kisi.saha_rolu,
            "giris_acik": False,
        },
        user_id=aktor.id,
        ip=ip,
        is_personal_data=True,
    )
    if birimler:
        await birimleri_yaz(db, kisi, birimler, aktor=aktor, ip=ip, yeni_kayit=True)
    return kisi


async def personel_guncelle(
    db: AsyncSession,
    hedef: User,
    degisiklik: dict[str, Any],
    *,
    aktor: User,
    surum: int,
    ip: str | None = None,
) -> User:
    """Personel kartı alanlarını günceller (yalnız `KART_ALANLARI`).

    `surum` zorunlu: iki İK uzmanı aynı kartı aynı anda düzenlerse ikincisi
    409 alır (iyimser kilit), sessizce üzerine yazmaz.
    """
    if surum != hedef.version:
        raise PersonelKuralHatasi(
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin."
        )
    bilinmeyen = set(degisiklik) - set(KART_ALANLARI)
    if bilinmeyen:
        raise PersonelGirdiHatasi(f"Bu uçta değiştirilemeyen alan: {', '.join(sorted(bilinmeyen))}")
    if yetki.ust_yetkili_mi(hedef) and not yetki.admin_mi(aktor):
        yasak = sorted(
            a
            for a, v in degisiklik.items()
            if a not in UST_YETKILIDE_SERBEST and getattr(hedef, a) != v
        )
        if yasak:
            raise yetki.YetkiHatasi(
                "Üst yetkili bir kullanıcının bu alanlarını yalnız sistem yöneticisi "
                f"değiştirebilir: {', '.join(yasak)}"
            )

    if "full_name" in degisiklik:
        ad = (degisiklik["full_name"] or "").strip()
        if len(ad) < 2:
            raise PersonelGirdiHatasi("Ad soyad en az 2 karakter olmalı.")
        degisiklik["full_name"] = ad
    if "sicil_no" in degisiklik:
        sicil = _sicil_temizle(degisiklik["sicil_no"])
        if sicil and await sicil_cakisiyor_mu(db, sicil, haric_id=hedef.id):
            raise PersonelKuralHatasi(f"Bu sicil numarası başka bir personelde kayıtlı: {sicil}")
        degisiklik["sicil_no"] = sicil
    if "saha_rolu" in degisiklik:
        degisiklik["saha_rolu"] = _saha_rolu_dogrula(degisiklik["saha_rolu"])
    if "unvan" in degisiklik:
        degisiklik["unvan"] = (degisiklik["unvan"] or "").strip() or None

    for alan, deger in degisiklik.items():
        setattr(hedef, alan, deger)
    # Ad değişikliği atamaları bozmaz: atamalar `users.id` ile (E01 K15).
    await audit.log_change(
        db, hedef, "personel.guncelle", user_id=aktor.id, ip=ip, is_personal_data=True
    )
    await db.flush()
    return hedef


async def personel_aktiflestir(
    db: AsyncSession, hedef: User, *, aktor: User, ip: str | None = None
) -> User:
    """Ayrılmış personeli yeniden aktifleştirir; GİRİŞİ AÇMAZ (E13-03).

    `is_active=true`, ayrılış alanları temizlenir; `giris_acik` olduğu gibi
    kalır (çıkışta false yapılmıştı). Giriş yalnız kullanıcı yönetiminden ve
    geçici parolayla açılır: tek düğmeyle ikisini birden açmak, çıkışı
    yapılmış birinin eski parolasıyla geri girmesi demekti.
    """
    yetki.hedef_kontrol(aktor, hedef)
    if hedef.is_active and hedef.ayrilis_tarihi is None:
        raise PersonelKuralHatasi("Personel zaten çalışıyor görünüyor.")
    eski = {
        "is_active": hedef.is_active,
        "ayrilis_tarihi": hedef.ayrilis_tarihi.isoformat() if hedef.ayrilis_tarihi else None,
        "ayrilis_nedeni": hedef.ayrilis_nedeni,
        "giris_acik": hedef.giris_acik,
    }
    hedef.is_active = True
    hedef.ayrilis_tarihi = None
    hedef.ayrilis_nedeni = None
    hedef.ayrilisi_yapan_id = None
    await db.flush()
    await audit.log(
        db,
        "users",
        "personel.aktiflestir",
        entity_id=hedef.id,
        old_value=eski,
        new_value={"is_active": True, "giris_acik": hedef.giris_acik},
        user_id=aktor.id,
        ip=ip,
        is_personal_data=True,
    )
    return hedef


# --- Liste ve süzgeçler --------------------------------------------------------


def _birim_uyesi(birim: str):
    return exists().where(UserUnit.user_id == User.id, UserUnit.birim == birim)


def personel_sorgusu(
    user: User,
    *,
    q: str | None = None,
    birim: str | None = None,
    birimsiz: bool = False,
    saha_rolu: str | None = None,
    durum: str | None = None,
    giris: str | None = None,
) -> Select:
    """Personel listesi sorgusu — KAPSAMLI (liste, KPI ve Excel aynı sorgu).

    Sayı = sızıntı: KPI kutusu ve Excel de bu fonksiyondan geçer, böylece
    kutudaki sayı tıklanınca açılan listenin `X-Toplam-Kayit`'ına eşittir.
    """
    stmt = select(User).order_by(User.full_name)
    stmt = kapsam.kapsam_personel(stmt, user, User.id)
    if q:
        desen = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(desen),
                User.sicil_no.ilike(desen),
                User.unvan.ilike(desen),
            )
        )
    if birim:
        if birim not in BIRIM_KODLARI:
            raise PersonelGirdiHatasi(f"Bilinmeyen birim: {birim}")
        stmt = stmt.where(_birim_uyesi(birim))
    if birimsiz:
        stmt = stmt.where(~exists().where(UserUnit.user_id == User.id))
    if saha_rolu:
        if saha_rolu not in SAHA_SUZGECLERI:
            raise PersonelGirdiHatasi(f"Bilinmeyen saha rolü süzgeci: {saha_rolu}")
        if saha_rolu == "ATANABILIR":
            stmt = stmt.where(User.saha_rolu.in_(ATANABILIR_SAHA_ROLLERI))
        elif saha_rolu == "EKSIK":
            stmt = stmt.where(User.saha_rolu.is_(None))
        else:
            stmt = stmt.where(User.saha_rolu == saha_rolu)
    if durum:
        if durum not in PERSONEL_DURUMLARI:
            raise PersonelGirdiHatasi(f"Bilinmeyen durum: {durum}")
        calisiyor = (User.is_active.is_(True)) & (User.ayrilis_tarihi.is_(None))
        stmt = stmt.where(calisiyor if durum == "CALISIYOR" else ~calisiyor)
    if giris:
        if giris not in GIRIS_DURUMLARI:
            raise PersonelGirdiHatasi(f"Bilinmeyen giriş durumu: {giris}")
        stmt = stmt.where(User.giris_acik.is_(giris == "ACIK"))
    return stmt


@dataclass(frozen=True)
class KpiTanimi:
    kod: str
    baslik: str
    suzgec: dict[str, Any]


def kpi_tanimlari() -> list[KpiTanimi]:
    """Personel sayfası üst kutuları; her biri listenin bir süzgecidir.

    Kutu sayısı `personel_sorgusu(**suzgec)` ile hesaplanır, tıklanınca aynı
    süzgeç listeye uygulanır: sayı ile liste ayrışamaz.
    """
    tanimlar = [
        KpiTanimi(
            f"SAHA_{b}",
            f"{b.replace('_', ' ').title()}: aktif saha personeli",
            {"birim": b, "saha_rolu": "ATANABILIR", "durum": "CALISIYOR"},
        )
        for b in BIRIM_KODLARI
    ]
    tanimlar += [
        KpiTanimi("BIRIMSIZ", "Birimsiz personel", {"birimsiz": True, "durum": "CALISIYOR"}),
        KpiTanimi("GIRISSIZ", "Girişsiz personel", {"giris": "KAPALI", "durum": "CALISIYOR"}),
        KpiTanimi(
            "SAHA_ROLU_EKSIK", "Saha rolü girilmemiş", {"saha_rolu": "EKSIK", "durum": "CALISIYOR"}
        ),
    ]
    return tanimlar


async def kpi_ozeti(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    sonuc = []
    for t in kpi_tanimlari():
        stmt = personel_sorgusu(user, **t.suzgec)
        adet = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        sonuc.append({"kod": t.kod, "baslik": t.baslik, "adet": int(adet or 0), "suzgec": t.suzgec})
    return sonuc


# --- Atanabilir personel (TS-009) ----------------------------------------------


@dataclass(frozen=True)
class AtanabilirKisi:
    """Kaynak listesi satırı. E-posta, kullanıcı adı, telefon, not, fiyat YOK."""

    id: int
    ad: str
    saha_rolu: str
    birimler: list[str]
    birincil_birim: str | None
    giris_acik: bool


def atanabilir_kosulu(birim: str, saha_rolleri: Sequence[str] = ATANABILIR_SAHA_ROLLERI):
    """Atanabilirlik ölçütü — TEK TANIM (TS-009; D1-B atama kuralı da bunu kullanır).

    Aktif, ayrılmamış, saha rolü atanabilir, birim üyesi. `giris_acik`
    bilinçli olarak YOK.
    """
    return (
        User.is_active.is_(True)
        & User.ayrilis_tarihi.is_(None)
        & User.saha_rolu.in_(tuple(saha_rolleri))
        & _birim_uyesi(birim)
    )


def birim_dogrula(birim: str | None) -> str:
    deger = (birim or "").strip().upper()
    if deger not in BIRIM_KODLARI:
        raise PersonelGirdiHatasi(
            f"Bilinmeyen birim: {birim} (geçerli: {', '.join(BIRIM_KODLARI)})"
        )
    return deger


async def atanabilir_personel(
    db: AsyncSession,
    user: User,
    birim: str,
    saha_rolleri: Sequence[str] = ATANABILIR_SAHA_ROLLERI,
) -> list[AtanabilirKisi]:
    """Bir birime atanabilecek kişiler (planlama kaynak listesi).

    - Birim katalog dışı → 400; aktörün kapsamı dışında → 404 (tek kayıt /
      parametre kapsam dışı = 404, K-08).
    - `KENDI_ISLERI` (teknisyen) yalnız KENDİSİNİ görür: ekip arkadaşlarının
      listesi ona gerekmez, KVKK en az erişim.
    - `personel.gor` gerektirmez; çağıran uç kendi iznini ister.
    """
    birim = birim_dogrula(birim)
    if kapsam.birim_disinda_mi(user, birim):
        raise PersonelKapsamDisi("Birim bulunamadı")
    bilinmeyen = set(saha_rolleri) - set(ATANABILIR_SAHA_ROLLERI)
    if bilinmeyen:
        raise PersonelGirdiHatasi(f"Atanamayan saha rolü: {', '.join(sorted(bilinmeyen))}")

    stmt = select(User).where(atanabilir_kosulu(birim, saha_rolleri)).order_by(User.full_name)
    if user.role.scope == SCOPE_OWN_JOBS:
        stmt = stmt.where(User.id == user.id)
    elif user.role.scope != SCOPE_ALL and not user.birim_kodlari:
        # Savunma (fail-closed): birimsiz kapsamlı rol hiçbir kişiyi görmez.
        stmt = stmt.where(false())
    kisiler = (await db.scalars(stmt)).all()
    return [
        AtanabilirKisi(
            id=k.id,
            ad=k.full_name,
            saha_rolu=k.saha_rolu or "",
            birimler=k.birim_kodlari,
            birincil_birim=k.birincil_birim,
            giris_acik=k.giris_acik,
        )
        for k in kisiler
    ]


async def atanabilir_mi(
    db: AsyncSession,
    kisi_id: int,
    birim: str,
    saha_rolleri: Sequence[str] = ATANABILIR_SAHA_ROLLERI,
) -> bool:
    """Tek kişi için aynı ölçüt (atama doğrulaması; kapsam çağıranın işidir)."""
    return (
        await db.scalar(
            select(User.id).where(User.id == kisi_id, atanabilir_kosulu(birim, saha_rolleri))
        )
    ) is not None
