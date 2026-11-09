"""S5 sahada onarımda parça al-ver (KARARLAR_2026-11-09_satis_depo_belge.md S5).

- **S5.1 Kullanım onayı:** teknisyen sahada parçayı KENDİ ARAÇ deposundan işe
  çıkar; çıkış anında yazılır, iş beklemez. Her çıkış satırı için şefin
  sonradan onaylayacağı bir kayıt açılır (`ServicePartUsageReview`, D6.7).
  Ret = fark kaydı (gerekçe) + zimmet sorusu; teknisyen açıklama yazar.
  Onay/ret yetkisi `parca.talep_onay` (amir); kapsam işin kapsamıdır.
- **S5.2 Sökülen parça:** iş emrine yazılır, karar zorunlu (depoya iade:
  tamir edilebilir/hurda, ya da müşteride kaldı). Stok defterine yazılmaz.
- **S5.3 İkmal:** araç deposunda son 30 günde işe çıkılan parça, bugünkü
  bakiyesi bu tüketimin altındaysa öneri olur (`ikmal_onerileri`).
  Teknisyen tek tıkla işe bağlı olmayan ikmal talebi açar; talep amir onaylı
  parça talebi akışından geçer, depo teslimi transferdir (`parca.talep_teslim`).
- **S5.4 Fiş:** her çıkış/iade/transfer işlemi için parça fişi PDF'i
  (`fis_baglami`). Fiyat/maliyet basılmaz.

Sayı = liste: uyarılar listeyle aynı sorguyu sayar.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, func, select

from app.models import (
    Product,
    ServiceOrder,
    ServicePartRequest,
    ServicePartUsageReview,
    ServiceRemovedPart,
    StockMovement,
    User,
    Warehouse,
)
from app.models.servis_parca import PARCA_TALEP_ACIK_DURUMLAR, SOKULEN_KARARLARI
from app.services.teknik_servis import parca
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.parca import (
    ParcaBulunamadi,
    ParcaHatasi,
    _metin,
    birim_uyumu_dogrula,
    erisilebilir_depo_sorgusu,
    is_kapsam_sorgusu,
    say,
)
from app.services.teknik_servis.yerel_zaman import yerel_an
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

IKMAL_GUN = 30
SOKULEN_KARAR_ADLARI = {
    "IADE_TAMIR": "Depoya iade (tamir edilebilir)",
    "IADE_HURDA": "Depoya iade (hurda)",
    "MUSTERIDE": "Müşteride kaldı",
}


def arac_deposu_mu(depo: Warehouse, user: User) -> bool:
    return depo.location_type == "TEKNISYEN" and depo.user_id == user.id


# --- S5.1 Kullanım onayı ----------------------------------------------------------------


async def kullanim_onaylari_ac(
    db: AsyncSession, hareketler: list[StockMovement], *, user: User
) -> list[ServicePartUsageReview]:
    """Araç deposundan işe çıkış satırları için onay kaydı (BEKLIYOR)."""
    kayitlar = []
    for h in hareketler:
        if h.hareket_turu != "CIKIS_SERVIS" or h.service_order_id is None:
            continue
        k = ServicePartUsageReview(
            stock_movement_id=h.id,
            service_order_id=h.service_order_id,
            warehouse_id=h.warehouse_id,
            product_id=h.product_id,
            adet=-h.qty,
            kullanan_id=user.id,
            durum="BEKLIYOR",
        )
        db.add(k)
        kayitlar.append(k)
    await db.flush()
    return kayitlar


def kullanim_sorgusu(user: User) -> Select:
    """Kapsam içi işlerin kullanım onayları (liste ve uyarı aynı sorgu)."""
    return select(ServicePartUsageReview).where(
        ServicePartUsageReview.service_order_id.in_(is_kapsam_sorgusu(user))
    )


async def kullanim_getir(db: AsyncSession, user: User, kimlik: int) -> ServicePartUsageReview:
    k = await db.scalar(kullanim_sorgusu(user).where(ServicePartUsageReview.id == kimlik))
    if k is None:
        raise ParcaBulunamadi("Kullanım kaydı bulunamadı")
    return k


async def kullanim_onayla(
    db: AsyncSession, k: ServicePartUsageReview, *, user: User, clock: Clock
) -> ServicePartUsageReview:
    if k.durum != "BEKLIYOR":
        raise ParcaHatasi("Yalnız onay bekleyen kullanım onaylanır.")
    k.durum = "ONAYLANDI"
    k.onaylayan_id = user.id
    k.onay_at = clock.now()
    await db.flush()
    return k


async def kullanim_reddet(
    db: AsyncSession, k: ServicePartUsageReview, *, neden: str, user: User, clock: Clock
) -> ServicePartUsageReview:
    """Ret = fark kaydı: gerekçe zorunlu, zimmet sorusu açılır (teknisyen açıklar)."""
    neden_ = _metin(neden, 200, "Red gerekçesi")
    if neden_ is None:
        raise ServisGirdiHatasi("Red gerekçesi zorunlu")
    if k.durum != "BEKLIYOR":
        raise ParcaHatasi("Yalnız onay bekleyen kullanım reddedilir.")
    k.durum = "REDDEDILDI"
    k.red_nedeni = neden_
    k.zimmet_durumu = "ACIK"
    k.onaylayan_id = user.id
    k.onay_at = clock.now()
    await db.flush()
    return k


async def zimmet_cevapla(
    db: AsyncSession, k: ServicePartUsageReview, *, aciklama: str, user: User
) -> ServicePartUsageReview:
    """Zimmet sorusunu yalnız parçayı kullanan teknisyen açıklar."""
    if k.kullanan_id != user.id:
        raise ParcaHatasi("Zimmet sorusunu yalnız parçayı kullanan açıklar.")
    if k.zimmet_durumu != "ACIK":
        raise ParcaHatasi("Açık zimmet sorusu yok.")
    metin = _metin(aciklama, 500, "Açıklama")
    if metin is None or len(metin) < 3:
        raise ServisGirdiHatasi("Açıklama zorunlu")
    k.zimmet_aciklama = metin
    k.zimmet_durumu = "CEVAPLANDI"
    await db.flush()
    return k


# --- S5.2 Sökülen parça -----------------------------------------------------------------


async def sokulen_ekle(
    db: AsyncSession,
    *,
    so: ServiceOrder,
    user: User,
    karar: str,
    adet: int,
    product_id: int | None = None,
    tanim: str | None = None,
    seri_no: str | None = None,
    depo: Warehouse | None = None,
    notes: str | None = None,
) -> ServiceRemovedPart:
    if karar not in SOKULEN_KARARLARI:
        raise ServisGirdiHatasi("Sökülen parça için karar seçilmeli (iade ya da müşteride)")
    if isinstance(adet, bool) or not isinstance(adet, int) or adet <= 0:
        raise ServisGirdiHatasi("Adet pozitif tam sayı olmalı")
    tanim = _metin(tanim, 160, "Tanım")
    if product_id is None and not tanim:
        raise ServisGirdiHatasi("Parça seçin ya da tanım yazın")
    if product_id is not None and await db.get(Product, product_id) is None:
        raise ParcaBulunamadi("Parça bulunamadı")
    if karar == "MUSTERIDE":
        depo = None
    elif depo is None:
        raise ServisGirdiHatasi("İade edilecek depo seçilmeli")
    else:
        birim_uyumu_dogrula(depo, so.birim, ne="işinden sökülen parça iadesinde")
    kayit = ServiceRemovedPart(
        service_order_id=so.id,
        product_id=product_id,
        tanim=tanim,
        seri_no=_metin(seri_no, 80, "Seri no"),
        adet=adet,
        karar=karar,
        warehouse_id=depo.id if depo is not None else None,
        notes=_metin(notes, 500, "Not"),
        created_by=user.id,
    )
    db.add(kayit)
    await db.flush()
    return kayit


def sokulen_sorgusu(user: User) -> Select:
    return select(ServiceRemovedPart).where(
        ServiceRemovedPart.service_order_id.in_(is_kapsam_sorgusu(user))
    )


async def sokulen_teslim_al(
    db: AsyncSession, kayit: ServiceRemovedPart, *, user: User
) -> ServiceRemovedPart:
    """Depo sökülen parçayı teslim aldı (yalnız iade kararında)."""
    if kayit.karar == "MUSTERIDE":
        raise ParcaHatasi("Müşteride kalan parça teslim alınmaz.")
    if kayit.teslim_alindi:
        raise ParcaHatasi("Parça zaten teslim alındı.")
    kayit.teslim_alindi = True
    kayit.teslim_alan_id = user.id
    kayit.updated_by = user.id
    await db.flush()
    return kayit


# --- S5.3 Araç deposu ikmali ------------------------------------------------------------


def _arac_depolari_sorgusu(user: User) -> Select:
    """Kullanıcının görebildiği araç depoları (teknisyende yalnız kendisininki)."""
    return select(Warehouse).where(
        Warehouse.id.in_(erisilebilir_depo_sorgusu(user)),
        Warehouse.location_type == "TEKNISYEN",
        Warehouse.is_active.is_(True),
    )


async def ikmal_onerileri(db: AsyncSession, user: User, clock: Clock) -> list[dict[str, Any]]:
    """Son 30 günde araç deposundan işe çıkılan parçalar; bakiye bu tüketimin
    altındaysa öneri = tüketim − bakiye. Açık ikmal talebi olan parça önerilmez."""
    depolar = {d.id: d for d in (await db.scalars(_arac_depolari_sorgusu(user))).all()}
    if not depolar:
        return []
    bas = clock.now() - timedelta(days=IKMAL_GUN)
    tuketim = (
        await db.execute(
            select(
                StockMovement.warehouse_id,
                StockMovement.product_id,
                -func.sum(StockMovement.qty),
            )
            .where(
                StockMovement.warehouse_id.in_(list(depolar)),
                StockMovement.service_order_id.is_not(None),
                StockMovement.created_at >= bas,
            )
            .group_by(StockMovement.warehouse_id, StockMovement.product_id)
        )
    ).all()
    adaylar = [(w, p, int(t)) for w, p, t in tuketim if t and t > 0]
    if not adaylar:
        return []
    bakiye = await parca.bakiyeler(
        db, depo_idler=list(depolar), product_idler=[p for _, p, _ in adaylar]
    )
    acik = set(
        (
            await db.execute(
                select(ServicePartRequest.hedef_depo_id, ServicePartRequest.product_id).where(
                    ServicePartRequest.service_order_id.is_(None),
                    ServicePartRequest.hedef_depo_id.in_(list(depolar)),
                    ServicePartRequest.durum.in_(PARCA_TALEP_ACIK_DURUMLAR),
                    ServicePartRequest.is_deleted.is_(False),
                )
            )
        ).all()
    )
    urunler = {
        u.id: u
        for u in (
            await db.scalars(select(Product).where(Product.id.in_([p for _, p, _ in adaylar])))
        ).all()
    }
    sonuc = []
    for w, p, t in adaylar:
        elde = bakiye.get((p, w), 0)
        if elde >= t or (w, p) in acik:
            continue
        u = urunler[p]
        sonuc.append(
            {
                "hedef_depo_id": w,
                "hedef_depo_adi": depolar[w].name,
                "product_id": p,
                "kod": u.code,
                "ad": u.name,
                "birim": u.birim or "ADET",
                "bakiye": elde,
                "tuketim": t,
                "onerilen_adet": t - elde,
            }
        )
    return sorted(sonuc, key=lambda x: (x["hedef_depo_adi"], x["kod"]))


async def ikmal_talebi_ac(
    db: AsyncSession,
    *,
    hedef: Warehouse,
    kaynak: Warehouse,
    product_id: int,
    adet: int,
    user: User,
    clock: Clock,
    notes: str | None = None,
) -> ServicePartRequest:
    """İşe bağlı olmayan araç ikmali talebi. Kaynak birim deposu (araç değil),
    hedef araç deposuyla aynı birim. Durum amir onayı kuralıyla aynı."""
    if hedef.location_type != "TEKNISYEN":
        raise ServisGirdiHatasi("İkmal hedefi bir araç deposu olmalı")
    if kaynak.location_type == "TEKNISYEN":
        raise ServisGirdiHatasi("İkmal birim deposundan yapılır")
    if kaynak.birim != hedef.birim:
        raise ParcaHatasi(
            "İkmal yalnız aynı birimin deposundan yapılır. Depolar birimlere ayrıdır."
        )
    if isinstance(adet, bool) or not isinstance(adet, int) or adet <= 0:
        raise ServisGirdiHatasi("Adet pozitif tam sayı olmalı")
    urun = await db.get(Product, product_id)
    if urun is None or not urun.yedek_parca:
        raise ParcaBulunamadi("Parça bulunamadı")
    if await db.scalar(
        select(ServicePartRequest.id).where(
            ServicePartRequest.service_order_id.is_(None),
            ServicePartRequest.hedef_depo_id == hedef.id,
            ServicePartRequest.product_id == product_id,
            ServicePartRequest.durum.in_(PARCA_TALEP_ACIK_DURUMLAR),
            ServicePartRequest.is_deleted.is_(False),
        )
    ):
        raise ParcaHatasi(f"{urun.code} için bu araca zaten açık bir ikmal talebi var.")
    kendi_onayi = user.has("parca.talep_onay")
    talep = ServicePartRequest(
        service_order_id=None,
        hedef_depo_id=hedef.id,
        warehouse_id=kaynak.id,
        product_id=product_id,
        adet=adet,
        durum="ACIK" if kendi_onayi else "ONAY_BEKLIYOR",
        onaylayan_id=user.id if kendi_onayi else None,
        onay_at=clock.now() if kendi_onayi else None,
        notes=_metin(notes, 500, "Not") or "Araç deposu ikmali",
        created_by=user.id,
        created_at=clock.now(),
    )
    db.add(talep)
    await db.flush()
    return talep


# --- S5.4 Parça fişi ----------------------------------------------------------------------

FIS_BASLIKLARI = {
    "CIKIS_SERVIS": "PARÇA ÇIKIŞ FİŞİ",
    "IADE_SERVIS": "PARÇA İADE FİŞİ",
    "TRANSFER_CIKIS": "PARÇA TRANSFER FİŞİ",
    "TRANSFER_GIRIS": "PARÇA TRANSFER FİŞİ",
    "GIRIS": "PARÇA GİRİŞ FİŞİ",
    "ZAYI": "PARÇA ZAYİ FİŞİ",
}


async def fis_baglami(db: AsyncSession, user: User, hareket_id: int) -> dict[str, Any]:
    """Aynı işlemin satırları tek fişte: aynı tür, depo, iş, kişi ve an (tek
    transaction); transferde aynı grup. Kapsam dışı hareket 404."""
    from app.services import belgeler

    h = await db.scalar(
        select(StockMovement).where(StockMovement.id == hareket_id, parca.hareket_kapsami(user))
    )
    if h is None or h.hareket_turu is None:
        raise ParcaBulunamadi("Hareket bulunamadı")
    if h.transfer_grup is not None:
        kosul = and_(StockMovement.transfer_grup == h.transfer_grup)
    else:
        kosul = and_(
            StockMovement.hareket_turu == h.hareket_turu,
            StockMovement.warehouse_id == h.warehouse_id,
            StockMovement.service_order_id.is_not_distinct_from(h.service_order_id),
            StockMovement.created_by.is_not_distinct_from(h.created_by),
            StockMovement.created_at == h.created_at,
        )
    satirlar = (
        await db.execute(
            select(StockMovement, Product, Warehouse)
            .join(Product, Product.id == StockMovement.product_id)
            .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
            .where(kosul, parca.hareket_kapsami(user))
            .order_by(StockMovement.id)
        )
    ).all()
    so = await db.get(ServiceOrder, h.service_order_id) if h.service_order_id else None
    kisi = await db.get(User, h.created_by) if h.created_by else None
    musteri = None
    if so is not None and so.customer_id:
        from app.models import Account

        hesap = await db.get(Account, so.customer_id)
        musteri = hesap.title if hesap else None
    kalemler = []
    kaynak = hedef = None
    for m, u, w in satirlar:
        if m.hareket_turu == "TRANSFER_GIRIS":
            hedef = w.name
            continue
        kaynak = w.name if m.hareket_turu != "IADE_SERVIS" else kaynak
        if m.hareket_turu == "IADE_SERVIS":
            hedef = w.name
        kalemler.append(
            {"kod": u.code, "ad": u.name, "adet": abs(m.qty), "birim": u.birim or "ADET"}
        )
    yerel = yerel_an(h.created_at)
    return {
        "baslik": FIS_BASLIKLARI.get(h.hareket_turu, "PARÇA FİŞİ"),
        "fis_no": f"PF-{min(m.id for m, _, _ in satirlar):06d}",
        "tarih": yerel.strftime("%d.%m.%Y %H:%M"),
        "depo": kaynak,
        "hedef": hedef,
        "so_no": so.so_no if so else None,
        "musteri": musteri,
        "kisi": kisi.full_name if kisi else None,
        "not_": h.notes,
        "kalemler": kalemler,
        "firma": belgeler.firma_bilgisi(await belgeler.ayar_haritasi(db)),
    }


# --- Uyarılar -------------------------------------------------------------------------------


async def kullanim_onay_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    adet = await say(db, kullanim_sorgusu(user).where(ServicePartUsageReview.durum == "BEKLIYOR"))
    return [
        Uyari(
            kod="parca.kullanim_onay",
            baslik="Onayınızı bekleyen sahada parça kullanımı",
            adet=adet,
            yol="/yedek-parca?sekme=kullanim&durum=BEKLIYOR",
            onem="uyari",
        )
    ]


async def zimmet_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    adet = await say(
        db,
        kullanim_sorgusu(user).where(
            ServicePartUsageReview.kullanan_id == user.id,
            ServicePartUsageReview.zimmet_durumu == "ACIK",
        ),
    )
    return [
        Uyari(
            kod="parca.zimmet",
            baslik="Açıklamanızı bekleyen reddedilmiş parça kullanımı",
            adet=adet,
            yol="/yedek-parca?sekme=kullanim&durum=REDDEDILDI",
            onem="kritik",
        )
    ]


async def ikmal_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    adet = len(await ikmal_onerileri(db, user, clock))
    return [
        Uyari(
            kod="parca.ikmal",
            baslik="Araç deposunda ikmal önerisi",
            adet=adet,
            yol="/yedek-parca?sekme=talepler",
            onem="bilgi",
        )
    ]


ts_uyarilar.kaydet("parca", "parca.talep_onay", kullanim_onay_uyarisi)
ts_uyarilar.kaydet("parca", "parca.kullan", zimmet_uyarisi)
ts_uyarilar.kaydet("parca", "parca.kullan", ikmal_uyarisi)
