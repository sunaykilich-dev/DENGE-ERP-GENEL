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

**İşten çıkış (TS-165, E13-09, E08-D02)** önizleme + TEK transaction'dır
(`cikis_onizleme`, `cikis_uygula`; ayrıntı bölüm başında). Açık sayaç
kapatılmaz, süre üretilmez (E13 K-11); uyarı ve görev kartıyla yöneticiye
düşer. Ayrılmış personelin KVKK anonimleştirmesi `services/kvkk.py`'dedir.

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

from sqlalchemy import Select, column, exists, false, func, or_, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Board,
    BoardColumn,
    Card,
    CardMember,
    Role,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceTimeEntry,
    Session,
    TrainingCorrectiveAction,
    TrainingPlan,
    User,
    UserUnit,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import DURUM_GRUPLARI
from app.models.user import AYRILIS_NEDENLERI, SAHA_ROLLERI
from app.permissions import ATANABILIR_SAHA_ROLLERI, SCOPE_ALL, SCOPE_OWN_JOBS
from app.services import audit, sirketler, yetki
from app.services import auth as auth_service
from app.services.normalize import tr_normkey
from app.services.teknik_servis import kancalar, kapsam

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


# --- Otomatik sicil (KARARLAR 2026-11-20 §8) ------------------------------------------

SICIL_BASAMAK = 4


async def _sicil_onek(db: AsyncSession) -> str:
    from app.services import settings as ayarlar

    return str(await ayarlar.get(db, "sicil_onek") or "").strip()


def _sicil_sayisi(sicil: str | None, onek: str) -> int | None:
    """Önekten sonrası yalnız rakamsa sayısı; değilse None (elle verilmiş sicil)."""
    if not sicil or not sicil.startswith(onek):
        return None
    govde = sicil[len(onek) :]
    return int(govde) if govde.isdigit() else None


async def sicil_sonraki(db: AsyncSession) -> str:
    """En büyük sayısal sicilin bir fazlası (önekli, 4 hane sıfır dolgulu)."""
    onek = await _sicil_onek(db)
    enbuyuk = 0
    for s in (await db.scalars(select(User.sicil_no).where(User.sicil_no.is_not(None)))).all():
        n = _sicil_sayisi(s, onek)
        if n is not None and n > enbuyuk:
            enbuyuk = n
    return f"{onek}{enbuyuk + 1:0{SICIL_BASAMAK}d}"


async def sicil_numarala(
    db: AsyncSession, *, aktor: User, uygula: bool, ip: str | None = None
) -> list[dict[str, Any]]:
    """Sicilsiz personeli şirket geçmişine göre numaralar.

    Sıra: işe giriş tarihi (boşlar en sonda), eşitse kayıt sırası (id). Var
    olan sicil değişmez. `uygula=False` yalnız önizleme döner.
    """
    onek = await _sicil_onek(db)
    sonraki = int((await sicil_sonraki(db))[len(onek) :])
    kisiler = (
        await db.scalars(
            select(User)
            .where(User.sicil_no.is_(None), User.is_active.is_(True))
            .order_by(User.ise_giris_tarihi.asc().nulls_last(), User.id.asc())
        )
    ).all()
    sonuc: list[dict[str, Any]] = []
    for kisi in kisiler:
        sicil = f"{onek}{sonraki:0{SICIL_BASAMAK}d}"
        sonraki += 1
        sonuc.append(
            {
                "id": kisi.id,
                "ad": kisi.full_name,
                "ise_giris_tarihi": kisi.ise_giris_tarihi,
                "sicil_no": sicil,
            }
        )
        if uygula:
            kisi.sicil_no = sicil
    if uygula and sonuc:
        await db.flush()
        await audit.log(
            db,
            "users",
            "personel.sicil_numarala",
            new_value={
                "adet": len(sonuc),
                "ilk": sonuc[0]["sicil_no"],
                "son": sonuc[-1]["sicil_no"],
            },
            user_id=aktor.id,
            ip=ip,
        )
    return sonuc


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
    if not sicil:
        # KARARLAR 2026-11-20 §8: boş bırakılan sicil otomatik ilerler.
        sicil = await sicil_sonraki(db)
    birimler = birim_satirlarini_dogrula(girdi.birimler)
    if aktor.role.scope != SCOPE_ALL and not birimler:
        raise PersonelGirdiHatasi("Personelin en az bir birimi olmalı.")
    # TUMU da etkin şirketin dışındaki birime personel açamaz (KARARLAR
    # 2026-11-04 §1): açtığı kaydı o şirket seçiliyken göremezdi.
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


# --- Yönetici ilişkisi ve "Ekibim" (TS-199, E13-17) ------------------------------
#
# **"Ekibim" yalnız SÜZGEÇTİR, yetki genişletmez (K-20):** liste önce
# `kapsam_personel` ile süzülür, sonra `yonetici_id = ben` uygulanır. Bağlı
# kişi kapsam dışındaysa (başka birim) görünmez. Yönetici ilişkisi kapsam,
# atama ya da onay yetkisi VERMEZ; yalnız organizasyon bilgisidir.


async def yonetici_dongusu_var_mi(db: AsyncSession, kisi_id: int, yonetici_id: int) -> bool:
    """`yonetici_id`, kişinin (dolaylı) astı mı? (özyinelemeli CTE).

    A'nın yöneticisi B yapılırken B zaten A'nın astının astıysa zincir döngüye
    girer (A→B→…→A) ve "Ekibim"/raporlar sonsuz döngüde dolaşırdı. `UNION`
    (ALL değil) var olan bozuk bir döngüde de sorguyu sonlandırır.
    """
    astlar = select(User.id).where(User.yonetici_id == kisi_id).cte("astlar", recursive=True)
    astlar = astlar.union(select(User.id).join(astlar, User.yonetici_id == astlar.c.id))
    bulunan = await db.scalar(select(astlar.c.id).where(astlar.c.id == yonetici_id).limit(1))
    return bulunan is not None


async def yonetici_ata(
    db: AsyncSession,
    hedef: User,
    yonetici_id: int | None,
    *,
    aktor: User,
    surum: int,
    ip: str | None = None,
) -> User:
    """Kişinin doğrudan yöneticisini yazar ya da kaldırır (`None`).

    - Sürüm farkı 409 (iyimser kilit).
    - Üst yetkili hedef (ADMIN olmayan aktör) 403 (`yetki.hedef_kontrol`).
    - Kendisi 400; döngü (yönetici kişinin astı) 400.
    - Yönetici aktörün kapsamı dışında ya da yok 404 (gövdedeki kişi
      referansı kapsam dışı → 404, plan §1.2).
    - Ayrılmış personel yönetici olamaz 400.

    `flush` yapar, `commit` çağıranın işidir. Denetim `is_personal_data=True`.
    """
    if surum != hedef.version:
        raise PersonelKuralHatasi(
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin."
        )
    yetki.hedef_kontrol(aktor, hedef)
    if yonetici_id is not None:
        if yonetici_id == hedef.id:
            raise PersonelGirdiHatasi("Kişi kendisinin yöneticisi olamaz.")
        if await kapsam.personel_disinda_mi(db, aktor, yonetici_id):
            raise PersonelKapsamDisi("Yönetici bulunamadı")
        yonetici = await db.get(User, yonetici_id)
        if yonetici is None:
            raise PersonelKapsamDisi("Yönetici bulunamadı")
        if _ayrildi_mi(yonetici):
            raise PersonelGirdiHatasi("Ayrılmış personel yönetici olarak seçilemez.")
        if await yonetici_dongusu_var_mi(db, hedef.id, yonetici_id):
            raise PersonelGirdiHatasi(
                "Seçilen kişi bu personelin astı (doğrudan ya da dolaylı); "
                "yönetici zinciri döngüye girerdi."
            )
    eski = hedef.yonetici_id
    if eski == yonetici_id:
        return hedef
    hedef.yonetici_id = yonetici_id
    await db.flush()
    await audit.log(
        db,
        "users",
        "personel.yonetici",
        entity_id=hedef.id,
        old_value={"yonetici_id": eski},
        new_value={"yonetici_id": yonetici_id},
        user_id=aktor.id,
        ip=ip,
        is_personal_data=True,
    )
    return hedef


async def yonetici_ozetleri(
    db: AsyncSession, aktor: User, kisiler: Sequence[User]
) -> dict[int, dict[str, Any]]:
    """Kişi kimliği → yönetici özeti `{id, ad}`; kapsam dışı yönetici maskelenir.

    Yöneticinin adı başka birimin personel bilgisidir: aktörün personel
    kapsamı dışındaysa `{"id": None, "ad": "Kapsam dışı kişi"}` döner.
    """
    yonetici_idler = {k.yonetici_id for k in kisiler if k.yonetici_id is not None}
    if not yonetici_idler:
        return {}
    stmt = kapsam.kapsam_personel(
        select(User.id, User.full_name).where(User.id.in_(sorted(yonetici_idler))),
        aktor,
        User.id,
    )
    gorunen = {i: ad for i, ad in (await db.execute(stmt)).all()}
    sonuc: dict[int, dict[str, Any]] = {}
    for k in kisiler:
        if k.yonetici_id is None:
            continue
        ad = gorunen.get(k.yonetici_id)
        sonuc[k.id] = (
            {"id": k.yonetici_id, "ad": ad}
            if ad is not None
            else {"id": None, "ad": "Kapsam dışı kişi"}
        )
    return sonuc


async def acik_sayaclilar(db: AsyncSession, kisi_idler: Iterable[int]) -> set[int]:
    """Açık sayacı olan kişiler ("Ekibim": şu an sahada mı)."""
    idler = sorted(set(kisi_idler))
    if not idler:
        return set()
    return set(
        (
            await db.scalars(
                select(ServiceTimeEntry.user_id).where(
                    ServiceTimeEntry.user_id.in_(idler),
                    ServiceTimeEntry.ended_at.is_(None),
                    ServiceTimeEntry.is_deleted.is_(False),
                )
            )
        ).all()
    )


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
    ekibim: bool = False,
) -> Select:
    """Personel listesi sorgusu — KAPSAMLI (liste, KPI ve Excel aynı sorgu).

    Sayı = sızıntı: KPI kutusu ve Excel de bu fonksiyondan geçer, böylece
    kutudaki sayı tıklanınca açılan listenin `X-Toplam-Kayit`'ına eşittir.

    `ekibim` (TS-199): yalnız aktörün DOĞRUDAN bağlıları; kapsam süzgecinden
    SONRA uygulanır (yetki genişletmez). Durum verilmezse yalnız çalışanlar.
    """
    stmt = select(User).order_by(User.full_name)
    stmt = kapsam.kapsam_personel(stmt, user, User.id)
    if ekibim:
        stmt = stmt.where(User.yonetici_id == user.id)
        if not durum:
            durum = "CALISIYOR"
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
        raise PersonelGirdiHatasi(f"Tayin edilemeyen saha rolü: {', '.join(sorted(bilinmeyen))}")

    stmt = select(User).where(atanabilir_kosulu(birim, saha_rolleri)).order_by(User.full_name)
    if user.role.scope == SCOPE_OWN_JOBS:
        stmt = stmt.where(User.id == user.id)
    elif user.role.scope != SCOPE_ALL and not kapsam.kullanici_birimleri(user):
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


# --- İşten çıkış (TS-165, E13-09, E08-D02) ---------------------------------------
#
# Akış: `cikis_onizleme` (yazmaz) → kullanıcı onaylar → `cikis_uygula` (TEK
# transaction; `flush` yapar, `commit` çağıranın işi). Herhangi bir adım hata
# verirse çağıran geri alır ve HİÇBİR adım uygulanmamış olur.
#
# Kararlar:
# - **Açık sayaç kapatılmaz** (E13 K-11): gerçek bitiş bilinmeden süre
#   üretmek "tahmini süre gerçek sürenin yerine geçmez" kuralına aykırı.
#   Bölüm açık kalır; kişi pasif olduğu için yeni bölüm açamaz. Uyarı
#   merkezi "İşten çıkış: açık sayaç inceleme bekliyor" sayar, görev
#   panosunda inceleme kartı açılır.
# - **Atamalardan çıkarma `ekip_degisiyor` kuralına uyar** (plan TS-165):
#   kişi açık sayacının bulunduğu işin ekibinden ÇIKARILMAZ (kural: açık
#   sayaçlı kişi ekipten çıkarılamaz). O iş önizlemede ve kartta "sayaç
#   kapatılınca ekipten çıkarın" notuyla görünür; yönetici sayacı
#   `yonetici-kapat` ile kapatıp normal atama ekranından çıkarır. Diğer açık
#   işlerde atama `removed_at` alır (satır silinmez), ATAMA olayı yazılır ve
#   `ekip_degisti` kancası (aktif planda EKIP_DEGISIMI) çalışır. İş durumu
#   DEĞİŞMEZ; sorumlusu kalmayan iş "Atanmamış" (`kpi=atanmamis`) listesine
#   düşer.
# - Kapalı işlerdeki atamalar geçmiştir, dokunulmaz.
# - Mobilite `work_orders.assigned_id` DEĞİŞTİRİLMEZ; yalnız bilgi olarak sayılır.
# - Eğitim (E08-D02): açık planlar ve düzeltici faaliyetler DEĞİŞMEZ (geçmiş
#   ve yeniden işe alımda devam). Önizleme sayıları gösterir; sorumlusu
#   ayrılmış açık düzeltici faaliyet uyarı merkezinde "sorumlusuz" sayılır.
# - `user_units` satırları silinmez (geçmiş raporu birimi kaybetmesin);
#   atanabilirlik zaten `is_active`/`ayrilis_tarihi` ile kesilir.

KAPALI_SERVIS_DURUMLARI = tuple(sorted(DURUM_GRUPLARI["KAPALI"]))
ACIK_DUZELTICI = "ACIK"
ACIK_PLAN_DURUMLARI = ("PLANLANDI", "ERTELENDI", "BASARISIZ_TEKRAR")

# Mobilite iş emirleri YALNIZ OKUNUR ve yalnız sayılır (E13-09). Model import
# EDİLMEZ (`test_servis_bagimsizlik`: teknik servis mobilite zincirine
# bağlanmaz); salt okuma için hafif tablo tanımı yeter, yazma yolu yoktur.
_MOBILITE_IS_EMRI = table(
    "work_orders", column("assigned_id"), column("status"), column("is_deleted")
)
_MOBILITE_ACIK_DURUMLAR = ("ACIK", "ATANDI", "YOLDA", "BASLADI")

CIKIS_PANOSU = "Personel İşten Çıkış İncelemeleri"
CIKIS_KOLON_BEKLIYOR = "İnceleme bekliyor"
CIKIS_KOLON_BITTI = "Tamamlandı"


def ayrilmis_kosulu():
    """Ayrılmış/pasif personel ölçütü (atanabilirliğin tersi; tek tanım)."""
    return or_(User.is_active.is_(False), User.ayrilis_tarihi.is_not(None))


@dataclass
class CikisIsi:
    id: int
    so_no: str
    durum: str
    birim: str
    sorumlu: bool
    sayac_acik: bool  # True → ekipten ÇIKARILMAZ (ekip_degisiyor kuralı)


@dataclass
class CikisOnizleme:
    personel_id: int
    kendisi: bool
    ust_yetkili: bool
    son_admin: bool
    zaten_ayrildi: bool
    aktif_isler: list[CikisIsi]
    kapsam_disi_is_sayisi: int
    acik_sayac: dict[str, Any] | None
    acik_oturum_sayisi: int
    mobilite_acik_is_sayisi: int
    egitim: dict[str, int]
    uyarilar: list[str]
    gorev_karti_acilacak: bool


@dataclass
class CikisSonucu:
    personel_id: int
    cikarilan_isler: list[str]
    ekipte_kalan_isler: list[str]
    acik_sayac_bolum_id: int | None
    gorev_karti_id: int | None
    kapanan_oturum: int


async def _aktif_atamalar(
    db: AsyncSession, kisi_id: int
) -> list[tuple[ServiceOrder, list[ServiceOrderAssignment]]]:
    """Kişinin AÇIK işlerdeki aktif atamaları, iş başına gruplu (iş no sırası)."""
    satirlar = (
        await db.execute(
            select(ServiceOrder, ServiceOrderAssignment)
            .join(ServiceOrder, ServiceOrder.id == ServiceOrderAssignment.service_order_id)
            .where(
                ServiceOrderAssignment.user_id == kisi_id,
                ServiceOrderAssignment.removed_at.is_(None),
                ServiceOrder.is_deleted.is_(False),
                ServiceOrder.status.not_in(KAPALI_SERVIS_DURUMLARI),
            )
            .order_by(ServiceOrder.so_no, ServiceOrderAssignment.id)
        )
    ).all()
    gruplu: dict[int, tuple[ServiceOrder, list[ServiceOrderAssignment]]] = {}
    for so, atama in satirlar:
        gruplu.setdefault(so.id, (so, []))[1].append(atama)
    return list(gruplu.values())


async def _acik_bolum(db: AsyncSession, kisi_id: int) -> ServiceTimeEntry | None:
    """Kişinin açık sayacı (`uq_ste_acik_kisi`: en çok bir tane)."""
    return await db.scalar(
        select(ServiceTimeEntry)
        .where(
            ServiceTimeEntry.user_id == kisi_id,
            ServiceTimeEntry.ended_at.is_(None),
            ServiceTimeEntry.is_deleted.is_(False),
        )
        .limit(1)
    )


async def _egitim_ozeti(db: AsyncSession, kisi_id: int) -> dict[str, int]:
    acik_plan = await db.scalar(
        select(func.count())
        .select_from(TrainingPlan)
        .where(
            TrainingPlan.user_id == kisi_id,
            TrainingPlan.is_deleted.is_(False),
            TrainingPlan.status.in_(ACIK_PLAN_DURUMLARI),
        )
    )
    kendi_faaliyet = await db.scalar(
        select(func.count())
        .select_from(TrainingCorrectiveAction)
        .where(
            TrainingCorrectiveAction.user_id == kisi_id,
            TrainingCorrectiveAction.status == ACIK_DUZELTICI,
        )
    )
    sorumlu_faaliyet = await db.scalar(
        select(func.count())
        .select_from(TrainingCorrectiveAction)
        .where(
            TrainingCorrectiveAction.sorumlu_user_id == kisi_id,
            TrainingCorrectiveAction.status == ACIK_DUZELTICI,
        )
    )
    return {
        "acik_plan": int(acik_plan or 0),
        "acik_duzeltici_faaliyet": int(kendi_faaliyet or 0),
        "sorumlu_oldugu_acik_faaliyet": int(sorumlu_faaliyet or 0),
    }


def _ayrildi_mi(kisi: User) -> bool:
    return (not kisi.is_active) or kisi.ayrilis_tarihi is not None


async def cikis_onizleme(
    db: AsyncSession, kisi: User, *, aktor: User, clock: Clock
) -> CikisOnizleme:
    """İşten çıkışın ne yapacağını gösterir; HİÇBİR ŞEY YAZMAZ.

    Aktörün kapsamı dışındaki işler numarasıyla gösterilmez, yalnız sayılır
    (sayı sızıntı değildir; numara başka birimin müşteri işini açardı).
    Kapsam çağıranın işidir: kişi kapsam dışıysa API önizlemeye gelmeden 404.
    """
    gruplar = await _aktif_atamalar(db, kisi.id)
    bolum = await _acik_bolum(db, kisi.id)
    sayacli_is = bolum.service_order_id if bolum is not None else None

    isler: list[CikisIsi] = []
    kapsam_disi = 0
    for so, atamalar in gruplar:
        if await kapsam.is_erisimi_yok_mu(db, aktor, so):
            kapsam_disi += 1
            continue
        isler.append(
            CikisIsi(
                id=so.id,
                so_no=so.so_no,
                durum=so.status,
                birim=so.birim,
                sorumlu=any(a.is_lead for a in atamalar),
                sayac_acik=so.id == sayacli_is,
            )
        )

    acik_sayac: dict[str, Any] | None = None
    if bolum is not None:
        so = await db.get(ServiceOrder, bolum.service_order_id)
        gorunur = so is not None and not await kapsam.is_erisimi_yok_mu(db, aktor, so)
        acik_sayac = {
            "bolum_id": bolum.id,
            "so_no": so.so_no if gorunur and so is not None else None,
            "baslangic": bolum.started_at,
            "faaliyet": bolum.faaliyet,
        }

    oturum = await db.scalar(
        select(func.count())
        .select_from(Session)
        .where(Session.user_id == kisi.id, Session.expires_at > clock.now())
    )
    mobilite = await db.scalar(
        select(func.count())
        .select_from(_MOBILITE_IS_EMRI)
        .where(
            _MOBILITE_IS_EMRI.c.assigned_id == kisi.id,
            _MOBILITE_IS_EMRI.c.is_deleted.is_(False),
            _MOBILITE_IS_EMRI.c.status.in_(_MOBILITE_ACIK_DURUMLAR),
        )
    )
    egitim = await _egitim_ozeti(db, kisi.id)
    son_admin = await yetki.son_admin_mi(db, kisi)

    uyarilar: list[str] = []
    if kisi.id == aktor.id:
        uyarilar.append("Kendi işten çıkışınızı yapamazsınız.")
    if _ayrildi_mi(kisi):
        uyarilar.append("Personel zaten ayrılmış görünüyor.")
    if son_admin:
        uyarilar.append("Giriş yapabilen son sistem yöneticisi işten çıkarılamaz.")
    if yetki.ust_yetkili_mi(kisi) and not yetki.admin_mi(aktor):
        uyarilar.append("Üst yetkili bir kullanıcıyı yalnız sistem yöneticisi çıkarabilir.")
    if bolum is not None:
        uyarilar.append(
            "Açık sayaç KAPATILMAZ ve süre üretilmez. Gerçek bitişi yönetici girmeli "
            "ya da kaydı iptal etmeli; o işte kişi sayaç kapanana kadar ekipte kalır."
        )
    if egitim["sorumlu_oldugu_acik_faaliyet"]:
        uyarilar.append(
            f"Sorumlusu olduğu {egitim['sorumlu_oldugu_acik_faaliyet']} açık düzeltici "
            "faaliyet sorumlusuz kalacak; yeni sorumlu tayin edin."
        )
    if mobilite:
        uyarilar.append(
            f"Mobilite iş emirlerinde {mobilite} açık tayini var; bu akış onları "
            "değiştirmez (iş emri ekranından devredin)."
        )

    return CikisOnizleme(
        personel_id=kisi.id,
        kendisi=kisi.id == aktor.id,
        ust_yetkili=yetki.ust_yetkili_mi(kisi),
        son_admin=son_admin,
        zaten_ayrildi=_ayrildi_mi(kisi),
        aktif_isler=isler,
        kapsam_disi_is_sayisi=kapsam_disi,
        acik_sayac=acik_sayac,
        acik_oturum_sayisi=int(oturum or 0),
        mobilite_acik_is_sayisi=int(mobilite or 0),
        egitim=egitim,
        uyarilar=uyarilar,
        gorev_karti_acilacak=bool(gruplar) or bolum is not None,
    )


async def _cikis_kurallari(
    db: AsyncSession,
    kisi: User,
    *,
    aktor: User,
    ayrilis_tarihi: date,
    ayrilis_nedeni: str,
    surum: int,
) -> str:
    """E13-01 kuralları + girdi; ihlalde hiçbir şey yazılmadan hata."""
    if kisi.id == aktor.id:
        raise PersonelGirdiHatasi("Kendi işten çıkışınızı yapamazsınız.")
    yetki.hedef_kontrol(aktor, kisi)
    if await yetki.son_admin_mi(db, kisi):
        raise PersonelKuralHatasi("Giriş yapabilen son sistem yöneticisi işten çıkarılamaz.")
    if surum != kisi.version:
        raise PersonelKuralHatasi(
            "Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyip tekrar deneyin."
        )
    if _ayrildi_mi(kisi):
        raise PersonelKuralHatasi("Personel zaten ayrılmış.")
    neden = (ayrilis_nedeni or "").strip().upper()
    if neden not in AYRILIS_NEDENLERI:
        raise PersonelGirdiHatasi(
            f"Bilinmeyen ayrılış nedeni: {ayrilis_nedeni} (geçerli: {', '.join(AYRILIS_NEDENLERI)})"
        )
    if kisi.ise_giris_tarihi is not None and ayrilis_tarihi < kisi.ise_giris_tarihi:
        raise PersonelGirdiHatasi("Ayrılış tarihi işe giriş tarihinden önce olamaz.")
    return neden


async def _ekipten_cikar(
    db: AsyncSession,
    so: ServiceOrder,
    atamalar: list[ServiceOrderAssignment],
    kisi: User,
    *,
    aktor: User,
    clock: Clock,
) -> None:
    """Kişiyi tek işin ekibinden çıkarır — `atama._uygula` ile aynı kanca sırası.

    `ekip_degisiyor` (açık sayaç → 409) → `removed_at` → ATAMA olayı →
    `ekip_degisti` (aktif planda EKIP_DEGISIMI). Olayda kişi ADI yok, kimlik
    var (E01 K15; ad okunurken çözülür).
    """
    from app.services.teknik_servis import atama as atama_svc
    from app.services.teknik_servis import gecmis

    await kancalar.ekip_degisiyor(db, so, [kisi.id])
    simdi = clock.now()
    sorumluydu = any(a.is_lead for a in atamalar)
    for a in atamalar:
        a.removed_at = simdi
        a.removed_by = aktor.id
    so.updated_by = aktor.id
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "ATAMA",
        "İşten çıkış: personel ekipten çıkarıldı"
        + (" (sorumlu teknisyendi; yeni sorumlu tayin edilmeli)" if sorumluydu else ""),
        user=aktor,
        clock=clock,
        veri={"cikan": [kisi.id], "neden": "ISTEN_CIKIS", "sorumluydu": sorumluydu},
    )
    kalan = await atama_svc.aktif_ekip(db, so)
    await kancalar.ekip_degisti(db, so, kalan, clock)


async def _inceleme_karti_ac(
    db: AsyncSession,
    kisi: User,
    *,
    aktor: User,
    ayrilis_tarihi: date,
    cikarilan: list[str],
    ekipte_kalan: list[str],
    bolum: ServiceTimeEntry | None,
    sayacli_so_no: str | None,
    baglanti_so_id: int | None,
) -> Card:
    """Görev panosunda "İşten çıkış incelemesi" kartı (E13-09 adım 5).

    Kart KİŞİ ADI taşımaz (bağlı kaydın etiketi yalnız görebilene döner, bkz.
    `services/gorevler.py`): "personel #id" ve iş numaraları. Pano yoksa
    açılır (iki kolon: bekliyor / tamamlandı). Kart servis işine bağlanır:
    önce açık sayaçlı iş, yoksa ekipten çıkarılan ilk iş.
    """
    # Pano şirkete aittir (rol testi S1): çıkışı yapan kişinin etkin şirketi.
    sirket = sirketler.aktif_sirket(aktor)
    pano = await db.scalar(
        select(Board)
        .where(
            Board.title == CIKIS_PANOSU,
            Board.arsivlendi.is_(False),
            Board.sirket_kod.is_(None) if sirket is None else Board.sirket_kod == sirket,
        )
        .order_by(Board.id)
        .limit(1)
    )
    if pano is None:
        pano = Board(
            title=CIKIS_PANOSU,
            description="İşten çıkışta açık iş ve sayaç incelemeleri (otomatik açılır).",
            sirket_kod=sirket,
            created_by=aktor.id,
            updated_by=aktor.id,
        )
        db.add(pano)
        await db.flush()
        db.add_all(
            [
                BoardColumn(board_id=pano.id, title=CIKIS_KOLON_BEKLIYOR, sira=0),
                BoardColumn(board_id=pano.id, title=CIKIS_KOLON_BITTI, sira=1, bitis_mi=True),
            ]
        )
        await db.flush()
    kolon = await db.scalar(
        select(BoardColumn)
        .where(BoardColumn.board_id == pano.id, BoardColumn.bitis_mi.is_(False))
        .order_by(BoardColumn.sira, BoardColumn.id)
        .limit(1)
    )
    if kolon is None:
        kolon = BoardColumn(board_id=pano.id, title=CIKIS_KOLON_BEKLIYOR, sira=0)
        db.add(kolon)
        await db.flush()
    sira = await db.scalar(
        select(func.coalesce(func.max(Card.sira), -1)).where(Card.column_id == kolon.id)
    )

    satirlar = [f"Personel #{kisi.id} işten çıkarıldı ({ayrilis_tarihi.isoformat()})."]
    if cikarilan:
        satirlar.append(
            "Ekipten çıkarılan açık işler (yeniden tayin edilmeli): " + ", ".join(cikarilan) + "."
        )
    if bolum is not None:
        satirlar.append(
            f"Açık sayaç: bölüm #{bolum.id}"
            + (f" ({sayacli_so_no})" if sayacli_so_no else "")
            + ". Sayaç KAPATILMADI ve süre üretilmedi: gerçek bitişi 'Yönetici kapat' "
            "ile girin ya da kaydı iptal edin; girilmezse rapor 'süre kaydı eksik' sayar."
        )
    if ekipte_kalan:
        satirlar.append(
            "Sayaç kapatılınca kişiyi şu işlerin ekibinden çıkarın: "
            + ", ".join(ekipte_kalan)
            + "."
        )
    kart = Card(
        board_id=pano.id,
        column_id=kolon.id,
        title=f"İşten çıkış incelemesi — personel #{kisi.id}",
        description="\n".join(satirlar),
        sira=int(sira) + 1,
        oncelik="YUKSEK",
        entity="servis_isi" if baglanti_so_id is not None else None,
        entity_id=baglanti_so_id,
        created_by=aktor.id,
        updated_by=aktor.id,
    )
    db.add(kart)
    await db.flush()
    db.add(CardMember(card_id=kart.id, user_id=aktor.id))
    await db.flush()
    return kart


async def cikis_uygula(
    db: AsyncSession,
    kisi: User,
    *,
    aktor: User,
    ayrilis_tarihi: date,
    ayrilis_nedeni: str,
    surum: int,
    clock: Clock,
    ip: str | None = None,
) -> CikisSonucu:
    """İşten çıkışı TEK transaction'da uygular (E13-09).

    1. Kurallar: kendisi 400, üst yetkili + aktör ADMIN değil 403, son admin
       409, sürüm 409, zaten ayrılmış 409, bilinmeyen neden 400.
    2. `is_active=false`, `giris_acik=false`, ayrılış alanları; oturumlar düşer.
    3. Açık işlerdeki aktif atamalar kapanır (açık sayaçlı iş hariç — bkz.
       bölüm başı); iş durumu değişmez.
    4. Açık sayaç KAPATILMAZ.
    5. Atama ya da sayaç varsa görev kartı açılır.
    6. Denetim (`personel.cikis`, kişisel veri).
    """
    neden = await _cikis_kurallari(
        db,
        kisi,
        aktor=aktor,
        ayrilis_tarihi=ayrilis_tarihi,
        ayrilis_nedeni=ayrilis_nedeni,
        surum=surum,
    )
    eski = {
        "is_active": kisi.is_active,
        "giris_acik": kisi.giris_acik,
        "ayrilis_tarihi": None,
        "ayrilis_nedeni": None,
    }

    kisi.is_active = False
    kisi.giris_acik = False
    kisi.ayrilis_tarihi = ayrilis_tarihi
    kisi.ayrilis_nedeni = neden
    kisi.ayrilisi_yapan_id = aktor.id
    await db.flush()
    oturum = await db.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == kisi.id)
    )
    await auth_service.revoke_all_sessions(db, kisi.id)
    # İşten çıkış erişimi (Dalga 4, TS-213): kişiye verilmiş ve kişinin verdiği
    # süreli vekâletler o anda biter (her biri `vekalet.iptal` denetimiyle);
    # kaynağı ayrılan yetki başkasında yaşamaya devam etmez.
    await yetki.kisinin_vekaletlerini_sonlandir(
        db, kisi.id, an=clock.now(), aktor_id=aktor.id, ip=ip
    )

    bolum = await _acik_bolum(db, kisi.id)
    sayacli_is = bolum.service_order_id if bolum is not None else None
    cikarilan: list[str] = []
    ekipte_kalan: list[str] = []
    cikarilan_ilk_id: int | None = None
    for so, atamalar in await _aktif_atamalar(db, kisi.id):
        if so.id == sayacli_is:
            ekipte_kalan.append(so.so_no)
            continue
        await _ekipten_cikar(db, so, atamalar, kisi, aktor=aktor, clock=clock)
        cikarilan.append(so.so_no)
        cikarilan_ilk_id = cikarilan_ilk_id or so.id

    sayacli_so_no: str | None = None
    if bolum is not None:
        sayacli_so = await db.get(ServiceOrder, bolum.service_order_id)
        sayacli_so_no = sayacli_so.so_no if sayacli_so is not None else None

    kart: Card | None = None
    if cikarilan or ekipte_kalan or bolum is not None:
        kart = await _inceleme_karti_ac(
            db,
            kisi,
            aktor=aktor,
            ayrilis_tarihi=ayrilis_tarihi,
            cikarilan=cikarilan,
            ekipte_kalan=ekipte_kalan,
            bolum=bolum,
            sayacli_so_no=sayacli_so_no,
            baglanti_so_id=sayacli_is or cikarilan_ilk_id,
        )

    await audit.log(
        db,
        "users",
        "personel.cikis",
        entity_id=kisi.id,
        old_value=eski,
        new_value={
            "is_active": False,
            "giris_acik": False,
            "ayrilis_tarihi": ayrilis_tarihi.isoformat(),
            "ayrilis_nedeni": neden,
            "cikarilan_is": len(cikarilan),
            "ekipte_kalan_is": len(ekipte_kalan),
            "acik_sayac_bolum_id": bolum.id if bolum is not None else None,
            "gorev_karti_id": kart.id if kart is not None else None,
        },
        user_id=aktor.id,
        ip=ip,
        is_personal_data=True,
    )
    return CikisSonucu(
        personel_id=kisi.id,
        cikarilan_isler=cikarilan,
        ekipte_kalan_isler=ekipte_kalan,
        acik_sayac_bolum_id=bolum.id if bolum is not None else None,
        gorev_karti_id=kart.id if kart is not None else None,
        kapanan_oturum=int(oturum or 0),
    )


# --- Uyarılar (TS-165): ayrılmış personelin açık sayacı ve sorumlusuz faaliyet ------


def cikis_sayac_sorgusu(user: User) -> Select:
    """Ayrılmış personelin açık sayaçları — kapsamlı (uyarı sayısı = liste)."""
    stmt = (
        select(ServiceTimeEntry)
        .join(User, User.id == ServiceTimeEntry.user_id)
        .where(
            ServiceTimeEntry.ended_at.is_(None),
            ServiceTimeEntry.is_deleted.is_(False),
            ayrilmis_kosulu(),
        )
    )
    return kapsam.kapsam_isler(stmt, user, ServiceTimeEntry.service_order_id)


def sorumlusuz_faaliyet_sorgusu(user: User) -> Select:
    """Sorumlusu ayrılmış AÇIK düzeltici faaliyetler (E08-D02) — kapsamlı.

    Kapsam, faaliyetin konusu olan personel üzerinden (eğitim kayıtlarının
    birim kapsamı personelin birimidir).
    """
    sorumlu = select(User.id).where(ayrilmis_kosulu())
    stmt = select(TrainingCorrectiveAction).where(
        TrainingCorrectiveAction.status == ACIK_DUZELTICI,
        TrainingCorrectiveAction.sorumlu_user_id.in_(sorumlu),
    )
    return kapsam.kapsam_personel(stmt, user, TrainingCorrectiveAction.user_id)


async def _sayim(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def cikis_sayac_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    from app.services.uyarilar import Uyari

    return [
        Uyari(
            kod="personel.cikis_sayac",
            baslik="İşten çıkış: açık sayaç inceleme bekliyor",
            adet=await _sayim(db, cikis_sayac_sorgusu(user)),
            yol="/benim-islerim?gorunum=tumu",
            onem="kritik",
            aciklama=(
                "Ayrılan personelin açık sayacı kendiliğinden kapanmaz: gerçek bitişi "
                "girin ya da kaydı iptal edin."
            ),
        )
    ]


async def sorumlusuz_faaliyet_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Any]:
    from app.services.uyarilar import Uyari

    return [
        Uyari(
            kod="personel.sorumlusuz_duzeltici",
            baslik="Sorumlusu ayrılmış düzeltici faaliyet",
            adet=await _sayim(db, sorumlusuz_faaliyet_sorgusu(user)),
            yol="/egitim",
            onem="uyari",
            aciklama="Faaliyetin sorumlusu işten ayrıldı; yeni sorumlu tayin edin.",
        )
    ]


def _uyari_kaydi() -> None:
    from app.services.teknik_servis import uyarilar as ts_uyarilar

    ts_uyarilar.kaydet("personel", "servis.planla", cikis_sayac_uyarisi)
    ts_uyarilar.kaydet("personel", ("egitim.yaz", "egitim.detay"), sorumlusuz_faaliyet_uyarisi)


_uyari_kaydi()
