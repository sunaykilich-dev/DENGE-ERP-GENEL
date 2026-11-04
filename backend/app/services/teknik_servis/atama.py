"""Kimlik bazlı çoklu atama, tek sorumlu, toplu atama, ekip senkronu (E01-12, TS-025).

İmzalar sabittir: D1-D (planlama) ve D1-G (zaman) bu fonksiyonları çağırır /
kancalarına yazar.

Akış (`ata` ve `toplu_ata` aynı kuralı paylaşır):
1. atanabilirlik = TS-009 ölçütü (`personel.atanabilir_kosulu`: aktif,
   ayrılmamış, saha rolü SEF/TEKNISYEN/STAJYER, işin birimine üye; girişsiz
   personel atanabilir). Ayrılmış/pasif/saha rolsüz kişi 400; başka birimin
   kişisi 409 (E01-12 kabul 8);
2. çıkan kişiler için `kancalar.ekip_degisiyor` (açık sayaç → 409, HİÇBİR
   iş değişmez — çağıran transaction'ı geri alır);
3. satırlar yazılır (silinmez; çıkan `removed_at` alır; rolü/sorumluluğu
   değişen kişinin eski satırı kapanır, yenisi açılır), ATAMA olayı (kişi
   ADI değil kimlikleri — ad okunurken çözülür);
4. `kancalar.ekip_degisti` (aktif planda EKIP_DEGISIMI satırı, D1-D).

Toplu atama üst sınırı `servis_toplu_atama_ust_sinir` (150; 151 → 422).
Kapalı işe atama 409.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from app.models import (
    BirimSirketi,
    KullaniciSirketi,
    ServiceOrder,
    ServiceOrderAssignment,
    User,
    UserUnit,
)
from app.models.teknik_servis import ATAMA_ROLLERI, SORUMLU_ROLLERI
from app.permissions import ATANABILIR_SAHA_ROLLERI
from app.services.teknik_servis import gecmis, kancalar, kapsam
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


class AtamaHatasi(ServisHatasi):
    """Atama kural ihlali → 409."""


class AtamaSinirHatasi(ValueError):
    """Toplu istek üst sınırı aşıyor → 422 (şema sınırı gibi davranır)."""


class AtamaKapsamDisi(ServisHatasi):
    """Toplu istekte kapsam dışı/bulunamayan iş → 404 (hangisi olduğu söylenmez)."""


@dataclass(frozen=True)
class AtamaSatiri:
    """Bir kişinin işteki rolü. `is_lead` yalnız TEKNISYEN'de."""

    user_id: int
    rol: str  # SEF | TEKNISYEN
    is_lead: bool = False


TopluAtamaModu = Literal["EKLE", "DEGISTIR"]
TOPLU_MODLAR = ("EKLE", "DEGISTIR")

# Atama uyarıları (Dalga 3, TS-198 / E08-22): `_uygula` yeni atanan kişiler için
# `kancalar.atama_uyarilari`'nı çağırır; uyarı atamayı ENGELLEMEZ. Uç katmanı
# (tekli/toplu atama, planlama) `uyari_toplayici()` bağlamında çağırıp yanıta
# `uyarilar` olarak ekler. İmzalar değişmez (planlama/atölye aynı fonksiyonları
# çağırır); toplayıcı yoksa uyarılar yalnız ATAMA olayına yazılır.
_UYARI_TOPLAYICI: ContextVar[list[str] | None] = ContextVar("atama_uyari_toplayici", default=None)


@contextmanager
def uyari_toplayici() -> Iterator[list[str]]:
    """Bağlam içindeki atamaların yetkinlik/belge uyarılarını toplar (tekrarsız)."""
    liste: list[str] = []
    belirtec = _UYARI_TOPLAYICI.set(liste)
    try:
        yield liste
    finally:
        _UYARI_TOPLAYICI.reset(belirtec)


def _uyari_ekle(uyarilar: Sequence[str]) -> None:
    liste = _UYARI_TOPLAYICI.get()
    if liste is None:
        return
    for u in uyarilar:
        if u not in liste:
            liste.append(u)


# Rol testi tur 2 (5_teknisyen B7): yalnız saha sorumlusu (`servis.tamamla` yok)
# tayin edilen iş ekipçe tamamlanamaz. Tayin engellenmez (saha sorumlusu işi
# izler); uyarı döner, sonucu `servis.tamamla` sahibi şef/yönetici girer.
SONUC_GIREN_YOK_UYARISI = (
    "Ekipte sonuç girebilecek (servis.tamamla) kimse yok; işi şef ya da yönetici tamamlar."
)


async def _sonuc_girebilen_var(db: AsyncSession, kimlikler: Sequence[int]) -> bool:
    kisiler = (await db.scalars(select(User).where(User.id.in_(list(kimlikler))))).all()
    return any(k.has("servis.tamamla") for k in kisiler)


def _satirlari_dogrula(atamalar: Sequence[AtamaSatiri]) -> list[AtamaSatiri]:
    kimlikler = [a.user_id for a in atamalar]
    if len(kimlikler) != len(set(kimlikler)):
        raise ServisGirdiHatasi("Aynı kişi ekipte iki kez olamaz")
    for a in atamalar:
        if a.rol not in ATAMA_ROLLERI:
            raise ServisGirdiHatasi(f"Bilinmeyen tayin rolü: {a.rol}")
        # Şef de sorumlu olabilir (rol testi B1): Set Bariyer gibi yalnız şefin
        # sahaya gittiği birimlerde iş hiç "sorumlulu" olamıyordu.
        if a.is_lead and a.rol not in SORUMLU_ROLLERI:
            raise ServisGirdiHatasi("Sorumlu yalnız teknisyen ya da şef rolünde olabilir")
    if sum(1 for a in atamalar if a.is_lead) > 1:
        raise AtamaHatasi("Bir işte tek sorumlu olur")
    return list(atamalar)


async def _sirket_disi_kisiler(db: AsyncSession, birim: str, kimlikler: set[int]) -> set[int]:
    """İşin biriminin şirketiyle hiçbir bağı olmayan kişiler (rol testi B3).

    Bağ: o şirketin bir biriminde üyelik ya da şirket üyeliği
    (`kullanici_sirketleri`). Birim bir şirkete eşlenmemişse (eşleme yok)
    süzgeç uygulanmaz — eski davranış.
    """
    if not kimlikler:
        return set()
    sirket = await db.scalar(select(BirimSirketi.sirket_kod).where(BirimSirketi.birim == birim))
    if sirket is None:
        return set()
    sirket_birimleri = select(BirimSirketi.birim).where(BirimSirketi.sirket_kod == sirket)
    bagli = set(
        (
            await db.scalars(
                select(UserUnit.user_id).where(
                    UserUnit.user_id.in_(kimlikler), UserUnit.birim.in_(sirket_birimleri)
                )
            )
        ).all()
    ) | set(
        (
            await db.scalars(
                select(KullaniciSirketi.user_id).where(
                    KullaniciSirketi.user_id.in_(kimlikler), KullaniciSirketi.sirket_kod == sirket
                )
            )
        ).all()
    )
    return kimlikler - bagli


def _atolye_ustasi_mi(kisi: User) -> bool:
    """Atölye işine saha rolü olmadan tayin edilebilen kişi: atölye yazma izni
    olan (atölye ustası). Rol testi tur 2 (5_teknisyen B5): usta kendi kaydına
    tayin olup ATÖLYE/TEST süresi giremiyordu; atölye işleri hep "süre eksik"
    kapanıyordu. Saha işlerinde kural değişmez (saha rolü şart)."""
    return kisi.has("atolye.yaz")


async def _atanabilirlik_dogrula(
    db: AsyncSession, birim: str, kimlikler: set[int], *, atolye: bool = False
) -> None:
    """TS-009 ölçütü; ihlalin türüne göre okunur mesaj ve kod.

    `atolye=True` (iş kategorisi ATOLYE): saha rolü olmayan atölye ustası da
    tayin edilebilir (`_atolye_ustasi_mi`)."""
    if not kimlikler:
        return
    kisiler = {
        k.id: k for k in (await db.scalars(select(User).where(User.id.in_(kimlikler)))).all()
    }
    sirket_disi = await _sirket_disi_kisiler(db, birim, set(kisiler))
    for kimlik in sorted(kimlikler):
        kisi = kisiler.get(kimlik)
        # Başka şirketin kişisi "yok" ile aynı yanıtı alır: ad, birim ya da
        # durum mesajı şirketler arası ad listesi çıkarmaya yaramasın (B3).
        if kisi is None or kimlik in sirket_disi:
            raise ServisGirdiHatasi(f"Kullanıcı bulunamadı (#{kimlik})")
        if not kisi.is_active or kisi.ayrilis_tarihi is not None:
            raise ServisGirdiHatasi(f"{kisi.full_name} ayrılmış/pasif; tayin edilemez")
        if kisi.saha_rolu not in ATANABILIR_SAHA_ROLLERI and not (
            atolye and _atolye_ustasi_mi(kisi)
        ):
            raise ServisGirdiHatasi(f"{kisi.full_name} saha personeli değil; tayin edilemez")
        if birim not in kisi.birim_kodlari:
            raise AtamaHatasi(f"{kisi.full_name} bu işin biriminde değil")


# Planlama (D1-D) aynı kuralları kullanır: modüller arası açık adlar.
satirlari_dogrula = _satirlari_dogrula
atanabilirlik_dogrula = _atanabilirlik_dogrula


async def aktif_ekip(db: AsyncSession, so: ServiceOrder) -> list[ServiceOrderAssignment]:
    """`removed_at IS NULL` atamalar (sorumlu önce)."""
    return list(
        (
            await db.scalars(
                select(ServiceOrderAssignment)
                .where(
                    ServiceOrderAssignment.service_order_id == so.id,
                    ServiceOrderAssignment.removed_at.is_(None),
                )
                .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
            )
        ).all()
    )


async def _uygula(
    db: AsyncSession,
    so: ServiceOrder,
    atamalar: list[AtamaSatiri],
    *,
    user: User,
    clock: Clock,
) -> tuple[list[ServiceOrderAssignment], bool]:
    """Ekibi verilen listeye eşitler. (yeni ekip, değişti mi)."""
    if so.is_deleted or so.status in ("TAMAMLANDI", "KAPATILDI", "IPTAL"):
        raise AtamaHatasi(f"{so.so_no}: kapalı işe tayin yapılamaz")
    mevcut = await aktif_ekip(db, so)
    mevcut_harita = {a.user_id: a for a in mevcut}
    yeni_harita = {a.user_id: a for a in atamalar}
    cikan = [a for uid, a in mevcut_harita.items() if uid not in yeni_harita]
    degisen = [
        a
        for uid, a in mevcut_harita.items()
        if uid in yeni_harita
        and (a.rol != yeni_harita[uid].rol or a.is_lead != yeni_harita[uid].is_lead)
    ]
    eklenen = [a for uid, a in yeni_harita.items() if uid not in mevcut_harita]
    if not cikan and not degisen and not eklenen:
        return mevcut, False
    await _atanabilirlik_dogrula(
        db,
        so.birim,
        {a.user_id for a in eklenen} | {a.user_id for a in degisen},
        atolye=so.kategori == "ATOLYE",
    )
    await kancalar.ekip_degisiyor(db, so, [a.user_id for a in cikan])

    simdi = clock.now()
    for satir in (*cikan, *degisen):
        satir.removed_at = simdi
        satir.removed_by = user.id
    await db.flush()
    for uid in [a.user_id for a in degisen] + [a.user_id for a in eklenen]:
        hedef = yeni_harita[uid]
        db.add(
            ServiceOrderAssignment(
                service_order_id=so.id,
                user_id=uid,
                rol=hedef.rol,
                is_lead=hedef.is_lead,
                assigned_at=simdi,
                assigned_by=user.id,
            )
        )
    so.updated_by = user.id
    await db.flush()
    sorumlu = next((a.user_id for a in atamalar if a.is_lead), None)
    # Yetkinlik/belge uyarısı yalnız yeni atanan (eklenen + rolü değişen) kişiler için;
    # yalnız okur, atamayı engellemez (E08-22, K11).
    uyarilar = await kancalar.atama_uyarilari(
        db, so, [a.user_id for a in eklenen] + [a.user_id for a in degisen], clock
    )
    ozet = (
        f"Ekip güncellendi: {len(eklenen)} eklendi, {len(cikan)} çıkarıldı, "
        f"{len(degisen)} rol değişti"
    )
    veri: dict = {
        "eklenen": [a.user_id for a in eklenen],
        "cikan": [a.user_id for a in cikan],
        "degisen": [a.user_id for a in degisen],
        "ekip": [{"user_id": a.user_id, "rol": a.rol} for a in atamalar],
        "sorumlu": sorumlu,
    }
    if uyarilar:
        ozet += " — yetkinlik uyarısıyla tayin edildi"
        veri["yetkinlik_uyarisi"] = True
        veri["uyari_sayisi"] = len(uyarilar)
        _uyari_ekle(uyarilar)
    if atamalar and not await _sonuc_girebilen_var(db, [a.user_id for a in atamalar]):
        _uyari_ekle([SONUC_GIREN_YOK_UYARISI])
    await gecmis.olay_yaz(db, so, "ATAMA", ozet, user=user, clock=clock, veri=veri)
    await kancalar.ekip_degisti(db, so, atamalar, clock)
    await db.refresh(so, attribute_names=["atamalar"])
    return await aktif_ekip(db, so), True


async def ata(
    db: AsyncSession,
    so: ServiceOrder,
    atamalar: Sequence[AtamaSatiri],
    *,
    user: User,
    clock: Clock,
) -> list[ServiceOrderAssignment]:
    """İşin ekibini verilen listeye eşitler (çıkanlar pasiflenir).

    Değişiklik yoksa hiçbir şey yazılmaz (olay da yok). Durum DEĞİŞMEZ
    (E01-04 kabul 4: atamada DURUM satırı yok).
    """
    ekip, _ = await _uygula(db, so, _satirlari_dogrula(atamalar), user=user, clock=clock)
    return ekip


async def toplu_ata(
    db: AsyncSession,
    is_idler: Sequence[int],
    atamalar: Sequence[AtamaSatiri],
    *,
    mod: TopluAtamaModu,
    user: User,
    clock: Clock,
) -> list[ServiceOrder]:
    """Çok işe aynı ekip; tek transaction, kural ihlalinde hiçbir iş değişmez.

    - üst sınır aşılırsa `AtamaSinirHatasi` (422);
    - bulunamayan/kapsam dışı iş varsa `AtamaKapsamDisi` (404, hangisi söylenmez);
    - kapalı iş ya da karışık birim varsa 409 ve sorunlu iş numaraları;
    - `EKLE`: mevcut ekibe eklenir (yeni sorumlu verilirse eski sorumlu
      teknisyen olarak kalır); `DEGISTIR`: ekip verilen listeye eşitlenir.
    Hata çağıranın transaction'ını geri aldırır; yazma sonradan geri alınır,
    ama ön kontroller (kapsam, kapalı, birim) yazmadan ÖNCE yapılır.
    """
    from app.services import settings as ayar_svc

    if mod not in TOPLU_MODLAR:
        raise ServisGirdiHatasi(f"Bilinmeyen toplu tayin modu: {mod}")
    kimlikler = list(dict.fromkeys(is_idler))
    if not kimlikler:
        raise ServisGirdiHatasi("En az bir iş seçilmeli")
    ust = int(await ayar_svc.get(db, "servis_toplu_atama_ust_sinir"))
    if len(kimlikler) > ust:
        raise AtamaSinirHatasi(f"Toplu tayinde en çok {ust} iş seçilebilir")
    satirlar = _satirlari_dogrula(atamalar)
    isler = (
        await db.scalars(
            select(ServiceOrder)
            .where(ServiceOrder.id.in_(kimlikler), ServiceOrder.is_deleted.is_(False))
            .order_by(ServiceOrder.id)
        )
    ).all()
    if len(isler) != len(kimlikler):
        raise AtamaKapsamDisi("Seçilen işlerden biri bulunamadı")
    for so in isler:
        if await kapsam.is_erisimi_yok_mu(db, user, so):
            raise AtamaKapsamDisi("Seçilen işlerden biri bulunamadı")
    kapali = [so.so_no for so in isler if so.status in ("TAMAMLANDI", "KAPATILDI", "IPTAL")]
    if kapali:
        raise AtamaHatasi(f"Kapalı işlere tayin yapılamaz: {', '.join(kapali)}")
    birimler = {so.birim for so in isler}
    if len(birimler) > 1:
        raise AtamaHatasi(
            "Toplu tayinde tüm işler aynı birimde olmalı (seçilen birimler: "
            + ", ".join(sorted(birimler))
            + ")"
        )
    await _atanabilirlik_dogrula(
        db,
        next(iter(birimler)),
        {a.user_id for a in satirlar},
        atolye=all(so.kategori == "ATOLYE" for so in isler),
    )

    yeni_sorumlu = next((a.user_id for a in satirlar if a.is_lead), None)
    for so in isler:
        if mod == "DEGISTIR":
            hedef = satirlar
        else:
            mevcut = await aktif_ekip(db, so)
            harita = {
                a.user_id: AtamaSatiri(
                    a.user_id, a.rol, a.is_lead and yeni_sorumlu in (None, a.user_id)
                )
                for a in mevcut
            }
            for a in satirlar:
                harita[a.user_id] = a
            hedef = list(harita.values())
        await _uygula(db, so, hedef, user=user, clock=clock)
    return list(isler)
