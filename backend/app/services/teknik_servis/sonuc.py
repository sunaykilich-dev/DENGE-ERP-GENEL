"""Kapanış sonucu, çözüm kanalı, arıza nedeni kataloğu, açılışta çözüldü (E01-06, TS-024).

Sonuçsuz TAMAMLANDI yok (409): `durum_dogrula` kancası, hangi yoldan gelirse
gelsin (sonuç ucu, uzaktan çözüm, atölye teslimi, bakım formu) TAMAMLANDI'dan
önce geçerli bir "tamamlayan" sonuç arar. Atölye/bakım modülleri durumu
değiştirmeden önce `sonuc_kaydet` ile sonucu yazar.

`cozum_kanali` NOT NULL. Teknisyen yalnız TAMAMLANDI yapar (KAPATILDI
`servis.kapat`). `servis.uzaktan_coz` tek istekte açılış + TAMAMLANDI (iki
olay: OLUSTUR ve DURUM; sonuç DURUM özetinde). Arıza nedeni birim bazlıdır.

Sonucun etkisi (E01-06):

| Sonuç | Etki |
|---|---|
| COZULDU / COZULEMEDI | TAMAMLANDI (`kaynak='sonuc'`) |
| TEKRAR_GIDILECEK | iş açık kalır; makine izin veriyorsa PLANLAMADA'ya döner |
|  | (aksi hâlde durum değişmez, yeni plan planlama ekranından verilir) |
| TEKLIF_SUNULACAK | TEKLIF nedenli bekleme açılır |

Yeniden açılışta önceki sonuç SİLİNMEZ, `gecersiz_at` ile geçersiz kılınır
(`durum_degisti` kancası).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models import ServiceFaultReason, ServiceResult
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import COZUM_KANALLARI, SERVIS_SONUCLARI
from app.services.statemachine import SERVIS_IS_EMRI
from app.services.teknik_servis import gecmis, kancalar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, User
    from app.services.teknik_servis.is_emirleri import ServisIsiGirdisi


class SonucHatasi(ServisHatasi):
    """Sonuç kural ihlali → 409."""


# TAMAMLANDI'ya götüren sonuçlar.
TAMAMLAYAN_SONUCLAR = frozenset({"COZULDU", "COZULEMEDI"})
UZAKTAN_KANALLAR = frozenset({"TELEFON", "UZAKTAN"})

SONUC_ADLARI = {
    "COZULDU": "Çözüldü",
    "COZULEMEDI": "Çözülemedi",
    "TEKRAR_GIDILECEK": "Tekrar gidilecek",
    "TEKLIF_SUNULACAK": "Teklif sunulacak",
}
KANAL_ADLARI = {
    "YERINDE": "Yerinde",
    "UZAKTAN": "Uzaktan",
    "TELEFON": "Telefonla",
    "ATOLYE": "Atölyede",
}


@dataclass
class SonucGirdisi:
    sonuc: str
    cozum_kanali: str
    yapilan_islem: str
    ariza_nedeni_id: int | None = None
    saha_seri_no: str | None = None
    saha_bolge: str | None = None
    sure_eksik_onay: bool = False


async def _ariza_nedeni_dogrula(db: AsyncSession, so: ServiceOrder, neden_id: int | None) -> None:
    if neden_id is None:
        return
    neden = await db.get(ServiceFaultReason, neden_id)
    if neden is None or not neden.is_active:
        raise ServisGirdiHatasi("Arıza nedeni katalogda yok ya da pasif")
    if neden.birim != so.birim:
        raise ServisGirdiHatasi("Arıza nedeni bu işin birimine ait değil")


async def sonuc_kaydet(
    db: AsyncSession,
    so: ServiceOrder,
    girdi: SonucGirdisi,
    *,
    user: User | None,
    clock: Clock,
    olay: bool = True,
) -> ServiceResult:
    """Sonucu DURUM DEĞİŞTİRMEDEN yazar (önceki geçerli sonuç geçersiz kılınır).

    Atölye teslimi ve bakım formu gibi kendi geçişini yapan modüller bunu
    çağırır, ardından `durum_degistir(TAMAMLANDI, kaynak=...)`.
    """
    if girdi.sonuc not in SERVIS_SONUCLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen sonuç: {girdi.sonuc}")
    if girdi.cozum_kanali not in COZUM_KANALLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen çözüm kanalı: {girdi.cozum_kanali}")
    islem = (girdi.yapilan_islem or "").strip()
    if not islem:
        raise ServisGirdiHatasi("Yapılan işlem boş olamaz")
    if len(islem) > 4000:
        raise ServisGirdiHatasi("Yapılan işlem en çok 4000 karakter olabilir")
    if so.status in ("TAMAMLANDI", "KAPATILDI", "IPTAL"):
        raise SonucHatasi("Kapalı işe sonuç girilemez")
    await _ariza_nedeni_dogrula(db, so, girdi.ariza_nedeni_id)
    simdi = clock.now()
    kimlik = user.id if user is not None else None
    eskiler = (
        await db.scalars(
            select(ServiceResult).where(
                ServiceResult.service_order_id == so.id, ServiceResult.gecersiz_at.is_(None)
            )
        )
    ).all()
    for eski in eskiler:
        eski.gecersiz_at = simdi
        eski.gecersiz_by = kimlik
    saha_seri = (girdi.saha_seri_no or "").strip() or None
    saha_bolge = (girdi.saha_bolge or "").strip() or None
    sonuc = ServiceResult(
        service_order_id=so.id,
        sonuc=girdi.sonuc,
        cozum_kanali=girdi.cozum_kanali,
        yapilan_islem=islem,
        ariza_nedeni_id=girdi.ariza_nedeni_id,
        saha_seri_no=saha_seri,
        saha_bolge=saha_bolge,
        kutuk_fark_durumu="ACIK" if (saha_seri or saha_bolge) else None,
        created_by=kimlik,
        updated_by=kimlik,
    )
    db.add(sonuc)
    await db.flush()
    if olay:
        await gecmis.olay_yaz(
            db,
            so,
            "SONUC",
            f"Sonuç: {SONUC_ADLARI[girdi.sonuc]} ({KANAL_ADLARI[girdi.cozum_kanali]})",
            user=user,
            clock=clock,
            veri={
                "sonuc": girdi.sonuc,
                "cozum_kanali": girdi.cozum_kanali,
                "ariza_nedeni_id": girdi.ariza_nedeni_id,
                "sonuc_id": sonuc.id,
            },
        )
    return sonuc


async def sonuc_gir(
    db: AsyncSession, so: ServiceOrder, girdi: SonucGirdisi, *, user: User, clock: Clock
) -> ServiceResult:
    """Sonuç yazar ve sonucun etkisini uygular (modül docstring tablosu).

    TAMAMLANDI yolunda geçiş önceden sınanır ki geçersiz durumdaki işe
    (ör. BEKLEMEDE) sonuç satırı yazılıp sonra 409 dönülmesin — transaction
    geri alınsa da kontrol sırası okunur hata mesajı içindir.
    TAMAMLANDI yolunda süre kaydı eksikse `sure_eksik_onay` istenir (TS-076,
    `zaman.sure_eksik_kapanis_dogrula`; onaysız 409, onaylı NOT olayı). Kontrol
    sonuç yazıldıktan SONRA yapılır: telefon/uzaktan kanallı sonuç "süre
    beklenmiyor" sayılır.
    """
    from app.services.teknik_servis import bekletme, is_emirleri, zaman

    if not user.has("servis.tamamla"):
        raise is_emirleri.IsEmriYetkiHatasi("Sonuç girmek için yetkiniz yok (servis.tamamla)")
    if girdi.sonuc in TAMAMLAYAN_SONUCLAR and not SERVIS_IS_EMRI.izinli_mi(so.status, "TAMAMLANDI"):
        raise SonucHatasi(f"'{is_emirleri.DURUM_ADLARI[so.status]}' durumundaki iş tamamlanamaz")
    sonuc = await sonuc_kaydet(db, so, girdi, user=user, clock=clock)
    if girdi.sonuc in TAMAMLAYAN_SONUCLAR:
        await zaman.sure_eksik_kapanis_dogrula(
            db, so, onay=bool(girdi.sure_eksik_onay), user=user, clock=clock
        )
        await is_emirleri.durum_degistir(
            db, so, "TAMAMLANDI", kaynak="sonuc", user=user, clock=clock
        )
    elif girdi.sonuc == "TEKLIF_SUNULACAK":
        await bekletme.beklet(
            db,
            so,
            "TEKLIF",
            user=user,
            clock=clock,
            aciklama="Sonuç: teklif sunulacak",
        )
    elif girdi.sonuc == "TEKRAR_GIDILECEK" and SERVIS_IS_EMRI.izinli_mi(so.status, "PLANLAMADA"):
        await is_emirleri.durum_degistir(
            db, so, "PLANLAMADA", kaynak="genel", user=user, clock=clock
        )
    return sonuc


async def uzaktan_coz(
    db: AsyncSession,
    girdi: ServisIsiGirdisi,
    sonuc: SonucGirdisi,
    *,
    user: User,
    clock: Clock,
) -> ServiceOrder:
    """Açılışta telefonla/uzaktan çözüldü: aç + TAMAMLANDI (`kaynak='uzaktan'`).

    Tek transaction, iki olay (OLUSTUR, DURUM "Müşteri Talebi → Tamamlandı
    (Telefonla)"). Kanal TELEFON/UZAKTAN, sonuç COZULDU olmalı (400).
    İş otomatik KAPANMAZ; şef ayrıca kapatır (E01 K1/K3).
    """
    from app.services.teknik_servis import is_emirleri

    if not user.has("servis.uzaktan_coz"):
        raise is_emirleri.IsEmriYetkiHatasi("Bu işlem için yetkiniz yok (servis.uzaktan_coz)")
    if sonuc.cozum_kanali not in UZAKTAN_KANALLAR:
        raise ServisGirdiHatasi("Açılışta çözüm yalnız telefon ya da uzaktan kanalla olur")
    if sonuc.sonuc != "COZULDU":
        raise ServisGirdiHatasi("Açılışta çözüm kaydının sonucu 'Çözüldü' olmalı")
    so = await is_emirleri.olustur(db, girdi, user=user, clock=clock)
    await sonuc_kaydet(db, so, sonuc, user=user, clock=clock, olay=False)
    await is_emirleri.durum_degistir(
        db,
        so,
        "TAMAMLANDI",
        kaynak="uzaktan",
        user=user,
        clock=clock,
        gerekce=f"açılışta çözüldü ({KANAL_ADLARI[sonuc.cozum_kanali]})",
    )
    return so


async def gecerli_sonuc(db: AsyncSession, so: ServiceOrder) -> ServiceResult | None:
    """Geçersiz kılınmamış son sonuç."""
    return await db.scalar(
        select(ServiceResult)
        .where(ServiceResult.service_order_id == so.id, ServiceResult.gecersiz_at.is_(None))
        .order_by(ServiceResult.id.desc())
        .limit(1)
    )


async def ariza_nedenleri(
    db: AsyncSession, birim: str | None, *, yalniz_aktif: bool = True
) -> list[ServiceFaultReason]:
    stmt = select(ServiceFaultReason).order_by(
        ServiceFaultReason.birim, ServiceFaultReason.sira, ServiceFaultReason.ad
    )
    if birim is not None:
        if birim not in BIRIM_KODLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen birim: {birim}")
        stmt = stmt.where(ServiceFaultReason.birim == birim)
    if yalniz_aktif:
        stmt = stmt.where(ServiceFaultReason.is_active.is_(True))
    return list((await db.scalars(stmt)).all())


async def ariza_nedeni_kaydet(
    db: AsyncSession,
    *,
    id: int | None,
    birim: str,
    ad: str,
    sira: int,
    is_active: bool,
    version: int | None = None,
) -> tuple[ServiceFaultReason, dict, dict]:
    """Arıza nedeni ekler (`id` yok) ya da günceller. (satır, eski, yeni).

    Birim değiştirilemez (geçmiş sonuçlar o birimin nedenine bağlı); aynı
    birimde aynı ad `uq_sfr_birim_ad` (409). Silme yok, pasifleme var.
    """
    ad = (ad or "").strip()
    if birim not in BIRIM_KODLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {birim}")
    if not ad or len(ad) > 80:
        raise ServisGirdiHatasi("Ad 1-80 karakter olmalı")
    if not 0 <= sira <= 999:
        raise ServisGirdiHatasi("Sıra 0-999 arasında olmalı")
    ayni = await db.scalar(
        select(ServiceFaultReason).where(
            ServiceFaultReason.birim == birim, ServiceFaultReason.ad == ad
        )
    )
    if id is None:
        if ayni is not None:
            raise SonucHatasi(f"Bu birimde '{ad}' adlı arıza nedeni zaten var")
        satir = ServiceFaultReason(birim=birim, ad=ad, sira=sira, is_active=is_active)
        db.add(satir)
        await db.flush()
        return satir, {}, {"birim": birim, "ad": ad, "sira": sira, "is_active": is_active}
    satir = await db.get(ServiceFaultReason, id)
    if satir is None:
        raise ServisGirdiHatasi("Arıza nedeni bulunamadı")
    if satir.birim != birim:
        raise ServisGirdiHatasi("Arıza nedeninin birimi değiştirilemez")
    if version is None:
        raise ServisGirdiHatasi("Var olan nedeni düzenlerken sürüm (version) zorunlu")
    if version != satir.version:
        raise SonucHatasi("Kayıt başka biri tarafından değiştirildi; yenileyin")
    if ayni is not None and ayni.id != satir.id:
        raise SonucHatasi(f"Bu birimde '{ad}' adlı arıza nedeni zaten var")
    eski = {"ad": satir.ad, "sira": satir.sira, "is_active": satir.is_active}
    satir.ad, satir.sira, satir.is_active = ad, sira, is_active
    await db.flush()
    return satir, eski, {"ad": ad, "sira": sira, "is_active": is_active}


# --- Kancalar --------------------------------------------------------------------------


async def tamamlama_sonucu_dogrula(
    db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str
) -> None:
    """`durum_dogrula`: sonuçsuz TAMAMLANDI yok (hangi yoldan gelirse gelsin)."""
    if hedef != "TAMAMLANDI":
        return
    sonuc = await gecerli_sonuc(db, so)
    if sonuc is None or sonuc.sonuc not in TAMAMLAYAN_SONUCLAR:
        raise SonucHatasi("Sonuç girilmeden iş tamamlanamaz")


async def yeniden_acilista_gecersiz_kil(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti`: TEKRAR_ACILDI'da ve kalite reddinde (rol testi tur 2) geçerli
    sonuç geçersiz kılınır (silinmez); düzeltilen iş yeni sonuçla tamamlanır."""
    if hedef != "TEKRAR_ACILDI" and kaynak != "kalite_red":
        return
    simdi = clock.now()
    for satir in (
        await db.scalars(
            select(ServiceResult).where(
                ServiceResult.service_order_id == so.id, ServiceResult.gecersiz_at.is_(None)
            )
        )
    ).all():
        satir.gecersiz_at = simdi
        satir.gecersiz_by = so.updated_by
    await db.flush()


kancalar.kaydet("durum_dogrula", tamamlama_sonucu_dogrula)
kancalar.kaydet("durum_degisti", yeniden_acilista_gecersiz_kil)
