"""Kiralık envanter: giriş, transfer, kontrol, bakiye, tek hareket yazıcısı (E06-03/11).

Maddeler: TS-111, TS-115, TS-118, TS-121, TS-102 (kiralama tarafı). D2-C.

**Neden ayrı defter:** kiralık cihaz `devices`'a ve servis kütüğüne YAZILMAZ
(KD-31): global `uq_devices_seri`, mobilite stok yaşam döngüsü ve stok
raporu bozulurdu. Seri takipli cihaz `rental_assets` satırıdır; seri takipsiz
(toplu) ürünün bakiyesi saklanmaz, `rental_inventory_movements` defterinden
hesaplanır (canlının serisiz stok ilkesi).

**Tek yazıcı:** envanterde durum/depo değiştiren HER işlem `hareket_yaz()`
üzerinden geçer. Fonksiyon seri cihazın denormalize `durum/warehouse_id`
alanlarını da günceller ve toplu üründe kaynak bakiyeyi, ürünün katalog
satırını `FOR UPDATE` kilitleyerek yazım ANINDA doğrular (E06 kontrol
§2.2/10): eşzamanlı iki transfer bakiyeyi eksiye düşüremez. Gece
uzlaştırması yalnız ikinci savunma hattıdır. Defter ekleme-yalnızdır
(`trg_rhareket_degismez`); düzeltme ters hareketle yapılır.

**Kilit sırası:** katalog satırları her zaman `product_id` sırasıyla, seri
cihazlar `id` sırasıyla kilitlenir; iki kiralamanın aynı ürünleri ters
sırada istemesi deadlock üretmez (E06 kontrol §2.2/9).

**Kapsam:** envanter satırının birimi katalog profilinden kopyalanır ve
değişmez; liste/tek kayıt `kapsam_birim(RentalAsset.birim)`; toplu stok
katalog birimiyle süzülür. URL'deki kapsam dışı kayıt 404 (yazma yok),
gövdedeki başka birim ürünü (katalog öğesi) 403.

Saat yalnız `Clock`; servis yalnız `flush` eder, commit API'dedir.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import aliased

from app.models import (
    Product,
    RentalAllocation,
    RentalAsset,
    RentalCatalogItem,
    RentalCheck,
    RentalInventoryMovement,
    RentalItem,
    Warehouse,
)
from app.models.servis_kiralama import (
    KIRALAMA_DISI_BIRIMLER,
    KIRALIK_DURUMLARI,
    KIRALIK_HAREKET_TURLERI,
    KONTROL_SONUCLARI,
)
from app.permissions import BIRIMLER
from app.services import audit
from app.services.normalize import normalize_seri
from app.services.teknik_servis.kapsam import (
    birim_disinda_mi,
    kapsam_birim,
    katalog_birim_yasak_mi,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User


class KiralamaHatasi(ValueError):
    """Kiralama iş kuralı ihlali.

    `kod` uçta HTTP durumuna çevrilir: `KURAL` → 409, `GIRDI` → 400,
    `YOK` → 404 (kapsam dışı/bulunamadı; yazma yapılmaz), `YASAK` → 403
    (gövdedeki katalog öğesi başka birimin). Kiralama, tahsis ve envanter
    modülleri tek sınıfı paylaşır (`kiralama.KiralamaHatasi` aynı nesnedir).
    """

    def __init__(self, mesaj: str, kod: str = "KURAL", *, veri: dict[str, Any] | None = None):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.kod = kod
        self.veri = veri or {}


def girdi(mesaj: str) -> KiralamaHatasi:
    return KiralamaHatasi(mesaj, "GIRDI")


def bulunamadi(mesaj: str) -> KiralamaHatasi:
    return KiralamaHatasi(mesaj, "YOK")


# Yeni giriş yalnız bu durumlarla yapılabilir; KIRADA/KAYIP girişte 400 (E06-18).
# HAZIR başka hiçbir yazma ucundan verilmez: yalnız giriş ve kontrol (E06-11).
GIRIS_DURUMLARI = ("HAZIR", "KONTROLDE", "HAZIR_DEGIL")
# Depoda duran (depo kolonu anlamlı) durumlar.
DEPO_DURUMLARI = ("HAZIR", "KONTROLDE", "HAZIR_DEGIL")
KONTROL_KAYNAK_DURUMLARI = ("KONTROLDE", "HAZIR_DEGIL")
HURDA_KAYNAK_DURUMLARI = ("HAZIR_DEGIL", "KONTROLDE", "KAYIP", "ATOLYEDE")
DURUM_ETIKETLERI = {
    "HAZIR": "Hazır",
    "HAZIR_DEGIL": "Hazır değil",
    "KONTROLDE": "Kontrolde",
    "KIRADA": "Kirada",
    "KAYIP": "Kayıp",
    "ATOLYEDE": "Atölyede",
    "HURDA": "Hurda",
}
KIMLIK_SERI = "SERI_NO"
KIMLIK_TOPLU = "YOK"
TOPLU_GIRIS_UST_SINIR = 2000
ENTITY_KIRALIK = "rental_assets"


def seri_takipli_mi(urun: Product) -> bool:
    return urun.identity_kind == KIMLIK_SERI


def urun_dogrula(urun: Product | None) -> Product:
    """Kiralık envantere girebilecek ürün mü? IMEI'li ürün 400 (E06-D05)."""
    if urun is None:
        raise girdi("Ürün bulunamadı")
    if urun.identity_kind == "IMEI":
        raise girdi(
            f"'{urun.code}' IMEI takipli bir ürün; kiralık envantere giremez "
            "(mobilite cihazı `devices`'ta izlenir)"
        )
    if urun.identity_kind not in (KIMLIK_SERI, KIMLIK_TOPLU):
        raise girdi(f"'{urun.code}' ürününün kimlik tipi kiralamaya uygun değil")
    return urun


def birim_dogrula(birim: str | None) -> str:
    if not birim or birim not in BIRIMLER:
        raise girdi(f"Bilinmeyen birim: {birim}")
    if birim in KIRALAMA_DISI_BIRIMLER:
        raise girdi(
            f"'{BIRIMLER[birim]}' biriminde kiralık envanter tutulmaz "
            "(o birimin kiralık cihazı mobilite tarafında izlenir)"
        )
    return birim


# --- Kapsam ------------------------------------------------------------------------


def kiralik_kosulu(stmt: Select, user: User) -> Select:
    """Seri kiralık cihaz listesine birim kapsamı (birim NOT NULL)."""
    return kapsam_birim(stmt, user, RentalAsset.birim, birimsiz_gorunur=False)


def katalog_kosulu(stmt: Select, user: User) -> Select:
    """Katalog profili (ve toplu stok) için birim kapsamı."""
    return kapsam_birim(stmt, user, RentalCatalogItem.birim, birimsiz_gorunur=False)


async def kapsamli_kiralik(
    db: AsyncSession, user: User, kiralik_id: int, *, kilit: bool = False
) -> RentalAsset:
    """Kiralık cihazı kapsamıyla getirir; yoksa ya da kapsam dışıysa 404."""
    stmt = select(RentalAsset).where(
        RentalAsset.id == kiralik_id, RentalAsset.is_deleted.is_(False)
    )
    stmt = kiralik_kosulu(stmt, user)
    if kilit:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    cihaz = await db.scalar(stmt)
    if cihaz is None:
        raise bulunamadi("Kiralık cihaz bulunamadı")
    return cihaz


async def kapsamli_katalog(db: AsyncSession, user: User, katalog_id: int) -> RentalCatalogItem:
    stmt = select(RentalCatalogItem).where(
        RentalCatalogItem.id == katalog_id, RentalCatalogItem.is_deleted.is_(False)
    )
    kalem = await db.scalar(katalog_kosulu(stmt, user))
    if kalem is None:
        raise bulunamadi("Katalog kaydı bulunamadı")
    return kalem


# --- Kilitler ----------------------------------------------------------------------


async def katalog_kilitle(
    db: AsyncSession, product_idler: list[int] | set[int] | tuple[int, ...]
) -> dict[int, RentalCatalogItem]:
    """Ürünlerin katalog satırlarını `product_id` sırasıyla FOR UPDATE kilitler.

    Aynı ürüne eşzamanlı tahsis/transfer/sevk bu kilitte sıraya girer;
    READ COMMITTED'da kilidi alan ifade sonrası sorgular öncekinin commit'ini
    görür. Sıra sabit olduğu için iki işlem birbirini ters sırada bekleyemez.
    """
    idler = sorted({int(i) for i in product_idler})
    if not idler:
        return {}
    satirlar = (
        await db.scalars(
            select(RentalCatalogItem)
            .where(RentalCatalogItem.product_id.in_(idler))
            .order_by(RentalCatalogItem.product_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    return {s.product_id: s for s in satirlar}


async def cihazlari_kilitle(db: AsyncSession, cihaz_idler: list[int]) -> dict[int, RentalAsset]:
    idler = sorted({int(i) for i in cihaz_idler})
    if not idler:
        return {}
    satirlar = (
        await db.scalars(
            select(RentalAsset)
            .where(RentalAsset.id.in_(idler), RentalAsset.is_deleted.is_(False))
            .order_by(RentalAsset.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    return {s.id: s for s in satirlar}


# --- Katalog profili (TS-118) --------------------------------------------------------


async def katalog_profili(db: AsyncSession, product_id: int) -> RentalCatalogItem | None:
    return await db.scalar(
        select(RentalCatalogItem).where(
            RentalCatalogItem.product_id == product_id,
            RentalCatalogItem.is_deleted.is_(False),
        )
    )


async def aktif_katalog(db: AsyncSession, product_id: int) -> RentalCatalogItem:
    profil = await katalog_profili(db, product_id)
    if profil is None or not profil.is_active:
        urun = await db.get(Product, product_id)
        ad = urun.code if urun is not None else f"#{product_id}"
        raise girdi(f"'{ad}' kiralama kataloğunda değil ya da pasif")
    return profil


async def _urunun_envanteri_var_mi(db: AsyncSession, product_id: int) -> bool:
    hareket = await db.scalar(
        select(RentalInventoryMovement.id)
        .where(RentalInventoryMovement.product_id == product_id)
        .limit(1)
    )
    if hareket is not None:
        return True
    kalem = await db.scalar(
        select(RentalItem.id).where(RentalItem.product_id == product_id).limit(1)
    )
    return kalem is not None


async def katalog_ekle(
    db: AsyncSession,
    user: User,
    *,
    product_id: int,
    birim: str,
    kategori: str | None = None,
    sira: int = 0,
    ip: str | None = None,
) -> RentalCatalogItem:
    """Ürünü kiralama kataloğuna ekler (profil). Ürün kartı canlı katalogdadır."""
    urun = urun_dogrula(await db.get(Product, product_id))
    birim_dogrula(birim)
    if katalog_birim_yasak_mi(user, birim) or birim_disinda_mi(user, birim, birimsiz_gorunur=False):
        raise KiralamaHatasi("Bu birimde katalog tanımlama yetkiniz yok", "YASAK")
    if sira < 0:
        raise girdi("Sıra negatif olamaz")
    if await katalog_profili(db, product_id) is not None:
        raise KiralamaHatasi(f"'{urun.code}' zaten kiralama kataloğunda")
    profil = RentalCatalogItem(
        product_id=product_id,
        birim=birim,
        kategori=(kategori or "").strip() or None,
        sira=sira,
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(profil)
    await db.flush()
    await audit.log(
        db,
        "rental_catalog_items",
        "olustur",
        entity_id=profil.id,
        new_value={"product_id": product_id, "birim": birim, "kategori": profil.kategori},
        user_id=user.id,
        ip=ip,
    )
    return profil


async def katalog_guncelle(
    db: AsyncSession,
    user: User,
    profil: RentalCatalogItem,
    alanlar: dict[str, Any],
    *,
    ip: str | None = None,
) -> RentalCatalogItem:
    """Profil düzenleme. Birim değişikliği yalnız ürünün envanteri/kalemi yokken (409)."""
    if "birim" in alanlar and alanlar["birim"] != profil.birim:
        yeni = birim_dogrula(alanlar["birim"])
        if birim_disinda_mi(user, yeni, birimsiz_gorunur=False):
            raise bulunamadi("Katalog kaydı bulunamadı")
        if await _urunun_envanteri_var_mi(db, profil.product_id):
            raise KiralamaHatasi(
                "Bu ürünün kiralık envanteri ya da kiralama kalemi var; birimi değiştirilemez"
            )
        profil.birim = yeni
    if "kategori" in alanlar:
        profil.kategori = (alanlar["kategori"] or "").strip() or None
    if "sira" in alanlar and alanlar["sira"] is not None:
        if alanlar["sira"] < 0:
            raise girdi("Sıra negatif olamaz")
        profil.sira = alanlar["sira"]
    if "is_active" in alanlar and alanlar["is_active"] is not None:
        profil.is_active = bool(alanlar["is_active"])
    profil.updated_by = user.id
    await audit.log_change(db, profil, "guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return profil


# --- Depo ----------------------------------------------------------------------------


async def kiralama_deposu(
    db: AsyncSession, depo_id: int | None, birim: str, *, alan: str = "Depo"
) -> Warehouse:
    """Depo bir AKTİF kiralama deposu ve birimi uyumlu mu (E06-D01/D04)?

    Mobilite ya da servis deposu kiralamada kullanılamaz (400). Depo birimi
    NULL (ortak) ya da kaydın birimiyle aynı olmalı.
    """
    if depo_id is None:
        raise girdi(f"{alan} seçilmedi")
    depo = await db.get(Warehouse, depo_id)
    if depo is None or not depo.is_active:
        raise girdi(f"{alan} bulunamadı")
    if not depo.kiralama_deposu:
        raise girdi(f"'{depo.name}' bir kiralama deposu değil; kiralık envanter orada tutulamaz")
    if depo.birim is not None and depo.birim != birim:
        raise girdi(
            f"'{depo.name}' {BIRIMLER.get(depo.birim, depo.birim)} biriminin deposu; "
            f"{BIRIMLER.get(birim, birim)} envanteri oraya yazılamaz"
        )
    return depo


async def kiralama_depolari(db: AsyncSession, user: User) -> list[Warehouse]:
    """Kullanıcının görebileceği aktif kiralama depoları (birimsiz = ortak)."""
    stmt = select(Warehouse).where(
        Warehouse.kiralama_deposu.is_(True), Warehouse.is_active.is_(True)
    )
    stmt = kapsam_birim(stmt, user, Warehouse.birim, birimsiz_gorunur=True)
    return list((await db.scalars(stmt.order_by(Warehouse.code))).all())


# --- Bakiye --------------------------------------------------------------------------


async def bakiye(db: AsyncSession, product_id: int, warehouse_id: int | None, durum: str) -> int:
    """Toplu bakiye = Σ giriş − Σ çıkış (asset_id IS NULL).

    `warehouse_id` None: KIRADA/KAYIP/ATOLYEDE/HURDA gibi depo dışı durumlar.
    """
    m = RentalInventoryMovement
    giren = await db.scalar(
        select(func.coalesce(func.sum(m.qty), 0)).where(
            m.asset_id.is_(None),
            m.product_id == product_id,
            m.to_durum == durum,
            m.to_warehouse_id.is_not_distinct_from(warehouse_id),
        )
    )
    cikan = await db.scalar(
        select(func.coalesce(func.sum(m.qty), 0)).where(
            m.asset_id.is_(None),
            m.product_id == product_id,
            m.from_durum == durum,
            m.from_warehouse_id.is_not_distinct_from(warehouse_id),
        )
    )
    return int(giren or 0) - int(cikan or 0)


def _bakiye_alt_sorgusu():
    """(product_id, warehouse_id, durum, adet) toplu bakiye satırları."""
    m = RentalInventoryMovement
    giris = select(
        m.product_id.label("product_id"),
        m.to_warehouse_id.label("warehouse_id"),
        m.to_durum.label("durum"),
        m.qty.label("adet"),
    ).where(m.asset_id.is_(None), m.to_durum.is_not(None))
    cikis = select(
        m.product_id.label("product_id"),
        m.from_warehouse_id.label("warehouse_id"),
        m.from_durum.label("durum"),
        (-m.qty).label("adet"),
    ).where(m.asset_id.is_(None), m.from_durum.is_not(None))
    birlesik = union_all(giris, cikis).subquery()
    return (
        select(
            birlesik.c.product_id,
            birlesik.c.warehouse_id,
            birlesik.c.durum,
            func.sum(birlesik.c.adet).label("adet"),
        )
        .group_by(birlesik.c.product_id, birlesik.c.warehouse_id, birlesik.c.durum)
        .subquery()
    )


async def durum_sayilari(db: AsyncSession, product_id: int) -> dict[str, int]:
    """Ürünün (depo fark etmeksizin) durum → adet dağılımı (seri + toplu)."""
    sayilar = dict.fromkeys(KIRALIK_DURUMLARI, 0)
    seri = (
        await db.execute(
            select(RentalAsset.durum, func.count())
            .where(RentalAsset.product_id == product_id, RentalAsset.is_deleted.is_(False))
            .group_by(RentalAsset.durum)
        )
    ).all()
    for durum, adet in seri:
        sayilar[durum] += int(adet)
    alt = _bakiye_alt_sorgusu()
    toplu = (
        await db.execute(
            select(alt.c.durum, func.sum(alt.c.adet))
            .where(alt.c.product_id == product_id)
            .group_by(alt.c.durum)
        )
    ).all()
    for durum, adet in toplu:
        if durum in sayilar:
            sayilar[durum] += int(adet or 0)
    return sayilar


async def bakiye_tablosu(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Depo × ürün × durum adetleri (seri sayım + toplu bakiye), kapsamlı.

    Kiralık Envanter ekranının depo kartları ve sayaçları bu tek sorgudan
    gelir. Sıfır satırlar dönmez.
    """
    alt = _bakiye_alt_sorgusu()
    toplu = select(
        alt.c.product_id, alt.c.warehouse_id, alt.c.durum, alt.c.adet, literal(False).label("seri")
    ).join(RentalCatalogItem, RentalCatalogItem.product_id == alt.c.product_id)
    toplu = katalog_kosulu(toplu, user).where(alt.c.adet != 0)
    seri = (
        select(
            RentalAsset.product_id,
            RentalAsset.warehouse_id,
            RentalAsset.durum,
            func.count().label("adet"),
        )
        .where(RentalAsset.is_deleted.is_(False))
        .group_by(RentalAsset.product_id, RentalAsset.warehouse_id, RentalAsset.durum)
    )
    seri = kiralik_kosulu(seri, user)
    # Depo dışı durumlarda (KIRADA, KAYIP...) cihazın "son depo"su sayılmaz.
    seri_toplam: dict[tuple, int] = {}
    for product_id, depo_id, durum, adet in (await db.execute(seri)).all():
        anahtar = (product_id, depo_id if durum in DEPO_DURUMLARI else None, durum)
        seri_toplam[anahtar] = seri_toplam.get(anahtar, 0) + int(adet)
    satirlar = [
        *(await db.execute(toplu)).all(),
        *((p, d, du, a, True) for (p, d, du), a in seri_toplam.items()),
    ]
    urun_idler = {r[0] for r in satirlar}
    depo_idler = {r[1] for r in satirlar if r[1] is not None}
    urunler = (
        {u.id: u for u in (await db.scalars(select(Product).where(Product.id.in_(urun_idler))))}
        if urun_idler
        else {}
    )
    depolar = (
        {d.id: d for d in (await db.scalars(select(Warehouse).where(Warehouse.id.in_(depo_idler))))}
        if depo_idler
        else {}
    )
    sonuc = []
    for product_id, depo_id, durum, adet, seri_mi in satirlar:
        urun = urunler.get(product_id)
        depo = depolar.get(depo_id) if depo_id is not None else None
        sonuc.append(
            {
                "product_id": product_id,
                "urun_kodu": urun.code if urun else None,
                "urun_adi": urun.name if urun else None,
                "depo_id": depo_id,
                "depo_adi": depo.name if depo else None,
                "durum": durum,
                "adet": int(adet),
                "seri_takipli": bool(seri_mi),
            }
        )
    sonuc.sort(key=lambda r: (r["depo_adi"] or "~", r["urun_kodu"] or "", r["durum"]))
    return sonuc


async def rezerve_toplu(
    db: AsyncSession,
    product_id: int,
    depo_id: int,
    *,
    baslangic=None,
    bitis=None,
) -> int:
    """Depodaki AKTİF, sevk edilmemiş toplu tahsis adedi (tarih verilirse çakışanlar)."""
    a = RentalAllocation
    stmt = select(func.coalesce(func.sum(a.qty - a.sevk_adet), 0)).where(
        a.asset_id.is_(None),
        a.product_id == product_id,
        a.from_warehouse_id == depo_id,
        a.durum == "AKTIF",
    )
    if baslangic is not None and bitis is not None:
        stmt = stmt.where(a.baslangic < bitis, a.bitis > baslangic)
    return int(await db.scalar(stmt) or 0)


# --- Tek yazıcı ----------------------------------------------------------------------


async def hareket_yaz(
    db: AsyncSession,
    *,
    tur: str,
    product_id: int,
    qty: int,
    clock: Clock,
    user: User | None,
    asset: RentalAsset | None = None,
    from_warehouse_id: int | None = None,
    to_warehouse_id: int | None = None,
    from_durum: str | None = None,
    to_durum: str | None = None,
    rental_id: int | None = None,
    allocation_id: int | None = None,
    check_id: int | None = None,
    reverses_id: int | None = None,
    note: str | None = None,
    bakiye_dogrula: bool = True,
) -> RentalInventoryMovement:
    """TEK yazıcı (ekleme-yalnız defter); kaynak bakiyeyi kilitleyip yeterliliği doğrular.

    - Seri cihaz (`asset`): `qty=1`; cihazın şu anki durumu `from_durum` ile
      aynı olmalı (409); cihazın `durum`'u `to_durum` olur, `to_warehouse_id`
      verilmişse depo da güncellenir (depo dışı durumlarda son depo kalır).
    - Toplu: `from_durum` verilmişse ürünün katalog satırı kilitlenir ve
      `(from_warehouse_id, from_durum)` bakiyesi `qty`'yi karşılamalı (409).
    """
    if tur not in KIRALIK_HAREKET_TURLERI:
        raise ValueError(f"Bilinmeyen hareket türü: {tur}")
    for d in (from_durum, to_durum):
        if d is not None and d not in KIRALIK_DURUMLARI:
            raise ValueError(f"Bilinmeyen kiralık durum: {d}")
    if qty <= 0:
        raise girdi("Adet sıfırdan büyük olmalı")
    if asset is not None:
        if qty != 1:
            raise girdi("Seri takipli cihaz hareketi tek adettir")
        if asset.product_id != product_id:
            raise ValueError("Cihazın ürünü hareketin ürünüyle aynı değil")
        if from_durum is not None and asset.durum != from_durum:
            raise KiralamaHatasi(
                f"'{asset.serial_no}' şu an {DURUM_ETIKETLERI.get(asset.durum, asset.durum)}; "
                f"bu işlem {DURUM_ETIKETLERI.get(from_durum, from_durum)} cihaz ister"
            )
        if (
            from_durum in DEPO_DURUMLARI
            and from_warehouse_id is not None
            and asset.warehouse_id != from_warehouse_id
        ):
            raise KiralamaHatasi(f"'{asset.serial_no}' seçilen depoda değil")
    elif from_durum is not None and bakiye_dogrula:
        await katalog_kilitle(db, [product_id])
        mevcut = await bakiye(db, product_id, from_warehouse_id, from_durum)
        if mevcut < qty:
            urun = await db.get(Product, product_id)
            yer = ""
            if from_warehouse_id is not None:
                depo = await db.get(Warehouse, from_warehouse_id)
                yer = f"{depo.name if depo else 'depo'} deposunda "
            raise KiralamaHatasi(
                f"Yetersiz bakiye: {urun.code if urun else product_id} için {yer}"
                f"{DURUM_ETIKETLERI.get(from_durum, from_durum)} durumunda {mevcut} adet var, "
                f"{qty} istendi"
            )
    hareket = RentalInventoryMovement(
        at=clock.now(),
        kind=tur,
        product_id=product_id,
        asset_id=asset.id if asset is not None else None,
        qty=qty,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        from_durum=from_durum,
        to_durum=to_durum,
        rental_id=rental_id,
        allocation_id=allocation_id,
        check_id=check_id,
        reverses_id=reverses_id,
        note=(note or None) and note[:300],
        created_by=user.id if user is not None else None,
    )
    db.add(hareket)
    if asset is not None:
        if to_durum is not None:
            asset.durum = to_durum
        if to_warehouse_id is not None:
            asset.warehouse_id = to_warehouse_id
        if user is not None:
            asset.updated_by = user.id
    await db.flush()
    return hareket


async def ters_hareket_yaz(
    db: AsyncSession,
    hareket: RentalInventoryMovement,
    *,
    user: User | None,
    clock: Clock,
    note: str | None = None,
) -> RentalInventoryMovement:
    """Hareketi ters çevirir (kaynak ↔ hedef; `uq_rhareket_ters` bir kez).

    Seri cihazın o hareketten SONRA başka hareketi varsa 409: "önce sonraki
    işlemi geri alın" (E06-08). Toplu üründe ters hareket de bakiye
    doğrulamasından geçer (iade sonrası kontrol edilmiş adet geri alınamaz).
    """
    zaten = await db.scalar(
        select(RentalInventoryMovement.id).where(RentalInventoryMovement.reverses_id == hareket.id)
    )
    if zaten is not None:
        raise KiralamaHatasi("Bu hareket zaten geri alınmış")
    cihaz = None
    if hareket.asset_id is not None:
        cihaz = (await cihazlari_kilitle(db, [hareket.asset_id])).get(hareket.asset_id)
        if cihaz is None:
            raise KiralamaHatasi("Hareketin cihazı bulunamadı")
        # Sonradan yazılıp kendisi de geri alınmış hareket (ve ters kaydı) engel
        # değildir: çok adımlı geri alma (önce iade, sonra sevk) mümkün olsun.
        ters = aliased(RentalInventoryMovement)
        m = RentalInventoryMovement
        sonraki = await db.scalar(
            select(m.id).where(
                m.asset_id == hareket.asset_id,
                m.id > hareket.id,
                m.kind.not_in(("TAHSIS", "TAHSIS_COZ")),
                m.reverses_id.is_(None),
                ~exists().where(ters.reverses_id == m.id),
            )
        )
        if sonraki is not None:
            raise KiralamaHatasi(
                f"'{cihaz.serial_no}' bu işlemden sonra başka bir harekete konu oldu; "
                "önce sonraki işlemi geri alın"
            )
    ters = await hareket_yaz(
        db,
        tur=hareket.kind,
        product_id=hareket.product_id,
        qty=hareket.qty,
        clock=clock,
        user=user,
        asset=cihaz,
        from_warehouse_id=hareket.to_warehouse_id,
        to_warehouse_id=hareket.from_warehouse_id,
        from_durum=hareket.to_durum,
        to_durum=hareket.from_durum,
        rental_id=hareket.rental_id,
        allocation_id=hareket.allocation_id,
        reverses_id=hareket.id,
        note=note or "Geri alma",
    )
    if cihaz is not None and hareket.from_warehouse_id is not None:
        cihaz.warehouse_id = hareket.from_warehouse_id
    return ters


# --- Giriş (TS-111) -------------------------------------------------------------------


async def _seri_var_mi(db: AsyncSession, product_id: int, anahtar: str) -> RentalAsset | None:
    return await db.scalar(
        select(RentalAsset).where(
            RentalAsset.product_id == product_id,
            RentalAsset.serial_key == anahtar,
            RentalAsset.is_deleted.is_(False),
        )
    )


@dataclass
class GirisSonucu:
    cihazlar: list[RentalAsset] = field(default_factory=list)
    hareketler: list[RentalInventoryMovement] = field(default_factory=list)

    @property
    def adet(self) -> int:
        return sum(h.qty for h in self.hareketler)


async def giris(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    product_id: int,
    depo_id: int,
    durum: str = "HAZIR",
    seriler: list[str] | None = None,
    adet: int | None = None,
    note: str | None = None,
    ip: str | None = None,
) -> GirisSonucu:
    """Envanter girişi (`kind=GIRIS`). Seri üründe her seri bir cihaz satırı."""
    urun = urun_dogrula(await db.get(Product, product_id))
    profil = await aktif_katalog(db, product_id)
    if katalog_birim_yasak_mi(user, profil.birim):
        raise KiralamaHatasi("Bu ürün başka bir birimin kiralama kataloğunda", "YASAK")
    if durum not in GIRIS_DURUMLARI:
        raise girdi(
            "Giriş durumu yalnız Hazır, Kontrolde ya da Hazır değil olabilir "
            f"({DURUM_ETIKETLERI.get(durum, durum)} girişte kullanılamaz)"
        )
    depo = await kiralama_deposu(db, depo_id, profil.birim)
    sonuc = GirisSonucu()
    temiz = [s.strip() for s in (seriler or []) if s and s.strip()]
    if seri_takipli_mi(urun):
        if adet is not None and adet != len(temiz):
            raise girdi("Seri takipli üründe adet seri sayısına eşittir")
        if not temiz:
            raise girdi(f"'{urun.code}' seri takipli; en az bir seri numarası girin")
        if len(temiz) > TOPLU_GIRIS_UST_SINIR:
            raise girdi(f"Tek seferde en çok {TOPLU_GIRIS_UST_SINIR} seri girilebilir")
        gorulen: set[str] = set()
        for seri in temiz:
            if len(seri) > 200:
                raise girdi("Seri numarası en çok 200 karakter olabilir")
            anahtar = normalize_seri(seri)
            if not anahtar:
                raise girdi(f"Geçersiz seri: {seri!r}")
            if anahtar in gorulen:
                raise girdi(f"Seri listede iki kez var: {seri}")
            gorulen.add(anahtar)
            if await _seri_var_mi(db, product_id, anahtar) is not None:
                raise KiralamaHatasi(f"'{seri}' bu ürün için zaten kiralık envanterde")
        await katalog_kilitle(db, [product_id])
        for seri in temiz:
            cihaz = RentalAsset(
                product_id=product_id,
                identity_kind=KIMLIK_SERI,
                serial_no=seri,
                serial_key=normalize_seri(seri),
                birim=profil.birim,
                warehouse_id=depo.id,
                durum=durum,
                created_by=user.id,
                updated_by=user.id,
            )
            db.add(cihaz)
            await db.flush()
            sonuc.cihazlar.append(cihaz)
            sonuc.hareketler.append(
                await hareket_yaz(
                    db,
                    tur="GIRIS",
                    product_id=product_id,
                    qty=1,
                    clock=clock,
                    user=user,
                    asset=cihaz,
                    to_warehouse_id=depo.id,
                    to_durum=durum,
                    note=note,
                )
            )
    else:
        if temiz:
            raise girdi(f"'{urun.code}' seri takipli değil; seri numarası girilmez, adet girilir")
        if adet is None or adet <= 0:
            raise girdi("Toplu üründe adet sıfırdan büyük olmalı")
        await katalog_kilitle(db, [product_id])
        sonuc.hareketler.append(
            await hareket_yaz(
                db,
                tur="GIRIS",
                product_id=product_id,
                qty=adet,
                clock=clock,
                user=user,
                to_warehouse_id=depo.id,
                to_durum=durum,
                note=note,
            )
        )
    await audit.log(
        db,
        ENTITY_KIRALIK,
        "giris",
        new_value={
            "product_id": product_id,
            "depo_id": depo.id,
            "durum": durum,
            "adet": sonuc.adet,
            "seri_sayisi": len(sonuc.cihazlar),
        },
        user_id=user.id,
        ip=ip,
    )
    return sonuc


# --- Düzenleme (E06-18) ------------------------------------------------------------


async def aktif_tahsisi_var_mi(db: AsyncSession, cihaz_id: int) -> bool:
    return (
        await db.scalar(
            select(RentalAllocation.id).where(
                RentalAllocation.asset_id == cihaz_id, RentalAllocation.durum == "AKTIF"
            )
        )
    ) is not None


async def cihaz_guncelle(
    db: AsyncSession,
    user: User,
    clock: Clock,
    cihaz: RentalAsset,
    alanlar: dict[str, Any],
    *,
    ip: str | None = None,
) -> RentalAsset:
    """Yalnız seri no, eksik notu ve not düzenlenir; durum/depo/ürün/birim 400.

    Durum yalnız hareket uçlarıyla, depo yalnız transferle değişir.
    """
    yasak = [
        k for k in ("durum", "warehouse_id", "product_id", "birim") if alanlar.get(k) is not None
    ]
    if yasak:
        raise girdi(
            f"Bu alanlar düzenlemeyle değiştirilemez: {', '.join(yasak)} "
            "(durum hareket uçlarıyla, depo transferle değişir)"
        )
    if "serial_no" in alanlar and alanlar["serial_no"] is not None:
        yeni = alanlar["serial_no"].strip()
        anahtar = normalize_seri(yeni)
        if not anahtar:
            raise girdi("Seri numarası boş olamaz")
        if anahtar != cihaz.serial_key:
            if cihaz.durum == "KIRADA" or await aktif_tahsisi_var_mi(db, cihaz.id):
                raise KiralamaHatasi("Tahsisli ya da kiradaki cihazın seri numarası değiştirilemez")
            baska = await _seri_var_mi(db, cihaz.product_id, anahtar)
            if baska is not None and baska.id != cihaz.id:
                raise KiralamaHatasi(f"'{yeni}' bu ürün için zaten kiralık envanterde")
            eski = cihaz.serial_no
            cihaz.serial_no = yeni
            await hareket_yaz(
                db,
                tur="DUZENLEME",
                product_id=cihaz.product_id,
                qty=1,
                clock=clock,
                user=user,
                asset=cihaz,
                from_warehouse_id=cihaz.warehouse_id,
                to_warehouse_id=cihaz.warehouse_id,
                from_durum=cihaz.durum,
                to_durum=cihaz.durum,
                note=f"Seri düzeltildi: {eski} → {yeni}",
            )
        elif yeni != cihaz.serial_no:
            cihaz.serial_no = yeni
    if "eksik_notu" in alanlar:
        cihaz.eksik_notu = (alanlar["eksik_notu"] or "").strip() or None
    if "notes" in alanlar:
        cihaz.notes = (alanlar["notes"] or "").strip() or None
    cihaz.updated_by = user.id
    await audit.log_change(db, cihaz, "guncelle", user_id=user.id, ip=ip)
    await db.flush()
    return cihaz


# --- Transfer (TS-111) ----------------------------------------------------------------


async def transfer(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    hedef_depo_id: int,
    cihaz_idler: list[int] | None = None,
    product_id: int | None = None,
    kaynak_depo_id: int | None = None,
    adet: int | None = None,
    durum: str = "HAZIR",
    note: str | None = None,
    ip: str | None = None,
) -> list[RentalInventoryMovement]:
    """Depo değişimi YALNIZ transferle (`kind=TRANSFER`); durum korunur.

    Seri: cihaz listesi (tahsisli, kiradaki cihaz 409). Toplu: ürün + adet +
    kaynak depo; kaynaktaki serbest bakiye (sevk edilmemiş tahsisler düşülerek)
    yetmeli (409). Katalog satırı kilitlidir: eşzamanlı iki transfer bakiyeyi
    eksiye düşüremez.
    """
    hareketler: list[RentalInventoryMovement] = []
    if cihaz_idler:
        if product_id is not None or adet is not None:
            raise girdi("Seri transferinde ürün/adet değil cihaz listesi verilir")
        kapsamli = []
        for cid in sorted(set(cihaz_idler)):
            kapsamli.append(await kapsamli_kiralik(db, user, cid))
        await katalog_kilitle(db, {c.product_id for c in kapsamli})
        cihazlar = await cihazlari_kilitle(db, [c.id for c in kapsamli])
        for cid in sorted(cihazlar):
            cihaz = cihazlar[cid]
            if cihaz.durum not in DEPO_DURUMLARI:
                raise KiralamaHatasi(
                    f"'{cihaz.serial_no}' {DURUM_ETIKETLERI[cihaz.durum]}; depoda olmayan cihaz "
                    "transfer edilemez"
                )
            if await aktif_tahsisi_var_mi(db, cihaz.id):
                raise KiralamaHatasi(
                    f"'{cihaz.serial_no}' bir kiralamaya tahsisli; önce tahsisi çözün"
                )
            hedef = await kiralama_deposu(db, hedef_depo_id, cihaz.birim, alan="Hedef depo")
            if hedef.id == cihaz.warehouse_id:
                raise girdi(f"'{cihaz.serial_no}' zaten {hedef.name} deposunda")
            hareketler.append(
                await hareket_yaz(
                    db,
                    tur="TRANSFER",
                    product_id=cihaz.product_id,
                    qty=1,
                    clock=clock,
                    user=user,
                    asset=cihaz,
                    from_warehouse_id=cihaz.warehouse_id,
                    to_warehouse_id=hedef.id,
                    from_durum=cihaz.durum,
                    to_durum=cihaz.durum,
                    note=note,
                )
            )
    else:
        if product_id is None or kaynak_depo_id is None or adet is None:
            raise girdi("Toplu transferde ürün, kaynak depo ve adet zorunlu")
        if adet <= 0:
            raise girdi("Adet sıfırdan büyük olmalı")
        if durum not in DEPO_DURUMLARI:
            raise girdi("Yalnız depodaki (Hazır, Kontrolde, Hazır değil) stok transfer edilir")
        urun = urun_dogrula(await db.get(Product, product_id))
        if seri_takipli_mi(urun):
            raise girdi(f"'{urun.code}' seri takipli; transfer cihaz listesiyle yapılır")
        profil = await aktif_katalog(db, product_id)
        if katalog_birim_yasak_mi(user, profil.birim):
            raise KiralamaHatasi("Bu ürün başka bir birimin kiralama kataloğunda", "YASAK")
        kaynak = await kiralama_deposu(db, kaynak_depo_id, profil.birim, alan="Kaynak depo")
        hedef = await kiralama_deposu(db, hedef_depo_id, profil.birim, alan="Hedef depo")
        if kaynak.id == hedef.id:
            raise girdi("Kaynak ve hedef depo aynı")
        await katalog_kilitle(db, [product_id])
        serbest = await bakiye(db, product_id, kaynak.id, durum)
        if durum == "HAZIR":
            serbest -= await rezerve_toplu(db, product_id, kaynak.id)
        if serbest < adet:
            raise KiralamaHatasi(
                f"Yetersiz bakiye: {urun.code} için {kaynak.name} deposunda "
                f"{DURUM_ETIKETLERI[durum]} serbest {max(serbest, 0)} adet var, {adet} istendi"
            )
        hareketler.append(
            await hareket_yaz(
                db,
                tur="TRANSFER",
                product_id=product_id,
                qty=adet,
                clock=clock,
                user=user,
                from_warehouse_id=kaynak.id,
                to_warehouse_id=hedef.id,
                from_durum=durum,
                to_durum=durum,
                note=note,
            )
        )
    await audit.log(
        db,
        ENTITY_KIRALIK,
        "transfer",
        new_value={"hareketler": [h.id for h in hareketler], "hedef_depo_id": hedef_depo_id},
        user_id=user.id,
        ip=ip,
    )
    return hareketler


# --- Dönüş kontrolü (TS-115) ----------------------------------------------------------


@dataclass
class KontrolSatiri:
    sonuc: str
    kiralik_id: int | None = None
    product_id: int | None = None
    depo_id: int | None = None
    adet: int | None = None
    kaynak_durum: str = "KONTROLDE"
    aciklama: str | None = None
    rental_id: int | None = None
    atolye_kaydi_ac: bool = False


def _kontrol_hedefi(sonuc: str) -> str:
    return "HAZIR" if sonuc == "UYGUN" else "HAZIR_DEGIL"


async def _atolye_kaydi_ac(
    db: AsyncSession, cihaz: RentalAsset, aciklama: str, *, user: User, clock: Clock
) -> int:
    """ARIZALI kiralık cihaz için atölye kaydı (KIRALAMA_TAKIP, TS-102).

    Kabul atölye modülünün işidir (D2-B, `atolye.kiralik_kabul`); kiralama
    tarafı yalnız cihazı ATOLYEDE yapar. Fonksiyon yoksa ya da henüz
    uygulanmadıysa 409 döner — kontrol atölye seçeneği olmadan girilir.
    """
    from app.services.teknik_servis import atolye

    kabul = getattr(atolye, "kiralik_kabul", None)
    hazir_degil = KiralamaHatasi(
        "Kiralık cihaz için atölye kabulü bu sürümde hazır değil; kontrolü atölye "
        "seçeneği olmadan kaydedip cihazı atölyeye ayrıca kabul ettirin"
    )
    if kabul is None:
        raise hazir_degil
    try:
        kayit = await kabul(db, cihaz, aciklama=aciklama, user=user, clock=clock)
    except NotImplementedError as exc:
        raise hazir_degil from exc
    return int(kayit.id)


async def kontrol(
    db: AsyncSession,
    user: User,
    clock: Clock,
    satirlar: list[KontrolSatiri],
    *,
    ip: str | None = None,
) -> list[RentalCheck]:
    """Dönüş kontrolü: KONTROLDE/HAZIR_DEGIL → UYGUN=HAZIR, EKSIK/ARIZALI=HAZIR_DEGIL.

    UYGUN dışında açıklama zorunlu (400; ayrıca `ck_rkontrol_aciklama`).
    KIRADA/KAYIP/HAZIR cihaz kontrol edilemez (400). Hepsi ya da hiçbiri.
    """
    if not satirlar:
        raise girdi("Kontrol satırı yok")
    for s in satirlar:
        if s.sonuc not in KONTROL_SONUCLARI:
            raise girdi(f"Bilinmeyen kontrol sonucu: {s.sonuc}")
        if s.sonuc != "UYGUN" and not (s.aciklama or "").strip():
            raise girdi("Uygun dışındaki sonuçta açıklama zorunlu")
        if s.atolye_kaydi_ac and (s.sonuc != "ARIZALI" or s.kiralik_id is None):
            raise girdi("Atölye kaydı yalnız arızalı seri cihaz için açılır")
    seri_idler = [s.kiralik_id for s in satirlar if s.kiralik_id is not None]
    if len(seri_idler) != len(set(seri_idler)):
        raise girdi("Aynı cihaz listede iki kez var")
    kapsamli: dict[int, RentalAsset] = {}
    for cid in sorted(set(seri_idler)):
        kapsamli[cid] = await kapsamli_kiralik(db, user, cid)
    toplu_urunler = {s.product_id for s in satirlar if s.kiralik_id is None and s.product_id}
    await katalog_kilitle(db, {c.product_id for c in kapsamli.values()} | toplu_urunler)
    cihazlar = await cihazlari_kilitle(db, list(kapsamli))
    kayitlar: list[RentalCheck] = []
    an = clock.now()
    for s in satirlar:
        aciklama = (s.aciklama or "").strip() or None
        if s.rental_id is not None:
            from app.models import Rental

            if await db.get(Rental, s.rental_id) is None:
                raise girdi("Kontrolde belirtilen kiralama bulunamadı")
        hedef = _kontrol_hedefi(s.sonuc)
        if s.kiralik_id is not None:
            cihaz = cihazlar[s.kiralik_id]
            if cihaz.durum not in KONTROL_KAYNAK_DURUMLARI:
                raise girdi(
                    f"'{cihaz.serial_no}' {DURUM_ETIKETLERI[cihaz.durum]}; yalnız Kontrolde ya da "
                    "Hazır değil durumundaki cihaz kontrol edilir"
                )
            kayit = RentalCheck(
                at=an,
                product_id=cihaz.product_id,
                asset_id=cihaz.id,
                warehouse_id=cihaz.warehouse_id,
                qty=1,
                sonuc=s.sonuc,
                aciklama=aciklama,
                rental_id=s.rental_id,
                created_by=user.id,
            )
            db.add(kayit)
            await db.flush()
            await hareket_yaz(
                db,
                tur="KONTROL",
                product_id=cihaz.product_id,
                qty=1,
                clock=clock,
                user=user,
                asset=cihaz,
                from_warehouse_id=cihaz.warehouse_id,
                to_warehouse_id=cihaz.warehouse_id,
                from_durum=cihaz.durum,
                to_durum=hedef,
                rental_id=s.rental_id,
                check_id=kayit.id,
                note=aciklama,
            )
            if s.sonuc == "UYGUN":
                cihaz.eksik_notu = None
            elif s.sonuc == "EKSIK":
                cihaz.eksik_notu = aciklama[:300] if aciklama else None
            if s.atolye_kaydi_ac:
                kayit.workshop_record_id = await _atolye_kaydi_ac(
                    db, cihaz, aciklama or "", user=user, clock=clock
                )
                await hareket_yaz(
                    db,
                    tur="ATOLYE",
                    product_id=cihaz.product_id,
                    qty=1,
                    clock=clock,
                    user=user,
                    asset=cihaz,
                    from_warehouse_id=cihaz.warehouse_id,
                    from_durum="HAZIR_DEGIL",
                    to_durum="ATOLYEDE",
                    check_id=kayit.id,
                    note="Atölyeye gönderildi",
                )
        else:
            if s.product_id is None or s.depo_id is None or not s.adet or s.adet <= 0:
                raise girdi("Toplu kontrolde ürün, depo ve adet zorunlu")
            if s.kaynak_durum not in KONTROL_KAYNAK_DURUMLARI:
                raise girdi("Yalnız Kontrolde ya da Hazır değil stok kontrol edilir")
            urun = urun_dogrula(await db.get(Product, s.product_id))
            if seri_takipli_mi(urun):
                raise girdi(f"'{urun.code}' seri takipli; kontrol cihaz seçilerek yapılır")
            profil = await aktif_katalog(db, s.product_id)
            if katalog_birim_yasak_mi(user, profil.birim):
                raise KiralamaHatasi("Bu ürün başka bir birimin kiralama kataloğunda", "YASAK")
            depo = await kiralama_deposu(db, s.depo_id, profil.birim)
            kayit = RentalCheck(
                at=an,
                product_id=s.product_id,
                warehouse_id=depo.id,
                qty=s.adet,
                sonuc=s.sonuc,
                aciklama=aciklama,
                rental_id=s.rental_id,
                created_by=user.id,
            )
            db.add(kayit)
            await db.flush()
            await hareket_yaz(
                db,
                tur="KONTROL",
                product_id=s.product_id,
                qty=s.adet,
                clock=clock,
                user=user,
                from_warehouse_id=depo.id,
                to_warehouse_id=depo.id,
                from_durum=s.kaynak_durum,
                to_durum=hedef,
                rental_id=s.rental_id,
                check_id=kayit.id,
                note=aciklama,
            )
        kayitlar.append(kayit)
    await audit.log(
        db,
        ENTITY_KIRALIK,
        "kontrol",
        new_value={"kontroller": [k.id for k in kayitlar]},
        user_id=user.id,
        ip=ip,
    )
    return kayitlar


# --- Kayıp bulundu, hurda, atölye dönüşü (E06-07, TS-102) ------------------------------


async def bulundu(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    gerekce: str,
    depo_id: int,
    kiralik_id: int | None = None,
    product_id: int | None = None,
    adet: int | None = None,
    ip: str | None = None,
) -> RentalInventoryMovement:
    """KAYIP → (depo, KONTROLDE), `kind=BULUNDU`; gerekçe zorunlu (400)."""
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise girdi("Bulundu kaydında gerekçe zorunlu")
    if kiralik_id is not None:
        cihaz = await kapsamli_kiralik(db, user, kiralik_id)
        cihaz = (await cihazlari_kilitle(db, [cihaz.id]))[cihaz.id]
        if cihaz.durum != "KAYIP":
            raise KiralamaHatasi(f"'{cihaz.serial_no}' kayıp değil")
        depo = await kiralama_deposu(db, depo_id, cihaz.birim)
        hareket = await hareket_yaz(
            db,
            tur="BULUNDU",
            product_id=cihaz.product_id,
            qty=1,
            clock=clock,
            user=user,
            asset=cihaz,
            from_durum="KAYIP",
            to_warehouse_id=depo.id,
            to_durum="KONTROLDE",
            note=gerekce,
        )
    else:
        if product_id is None or not adet or adet <= 0:
            raise girdi("Toplu bulunduda ürün ve adet zorunlu")
        urun = urun_dogrula(await db.get(Product, product_id))
        if seri_takipli_mi(urun):
            raise girdi(f"'{urun.code}' seri takipli; cihaz seçilerek işlenir")
        profil = await aktif_katalog(db, product_id)
        if katalog_birim_yasak_mi(user, profil.birim):
            raise KiralamaHatasi("Bu ürün başka bir birimin kiralama kataloğunda", "YASAK")
        depo = await kiralama_deposu(db, depo_id, profil.birim)
        hareket = await hareket_yaz(
            db,
            tur="BULUNDU",
            product_id=product_id,
            qty=adet,
            clock=clock,
            user=user,
            from_durum="KAYIP",
            to_warehouse_id=depo.id,
            to_durum="KONTROLDE",
            note=gerekce,
        )
    await audit.log(
        db,
        ENTITY_KIRALIK,
        "bulundu",
        entity_id=hareket.asset_id,
        new_value={"hareket_id": hareket.id, "gerekce": gerekce},
        user_id=user.id,
        ip=ip,
    )
    return hareket


async def hurda(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    gerekce: str,
    kiralik_id: int | None = None,
    product_id: int | None = None,
    depo_id: int | None = None,
    kaynak_durum: str = "HAZIR_DEGIL",
    adet: int | None = None,
    ip: str | None = None,
) -> RentalInventoryMovement:
    """Envanterden gerekçeli çıkış (`kind=HURDA`, E06-D02). Kayıt silinmez."""
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise girdi("Hurda çıkışında gerekçe zorunlu")
    if kiralik_id is not None:
        cihaz = await kapsamli_kiralik(db, user, kiralik_id)
        cihaz = (await cihazlari_kilitle(db, [cihaz.id]))[cihaz.id]
        if cihaz.durum not in HURDA_KAYNAK_DURUMLARI:
            raise KiralamaHatasi(
                f"'{cihaz.serial_no}' {DURUM_ETIKETLERI[cihaz.durum]}; yalnız hazır olmayan, "
                "kontroldeki, kayıp ya da atölyedeki cihaz hurdaya ayrılır"
            )
        if await aktif_tahsisi_var_mi(db, cihaz.id):
            raise KiralamaHatasi(f"'{cihaz.serial_no}' bir kiralamaya tahsisli")
        hareket = await hareket_yaz(
            db,
            tur="HURDA",
            product_id=cihaz.product_id,
            qty=1,
            clock=clock,
            user=user,
            asset=cihaz,
            from_warehouse_id=cihaz.warehouse_id if cihaz.durum in DEPO_DURUMLARI else None,
            from_durum=cihaz.durum,
            to_durum="HURDA",
            note=gerekce,
        )
    else:
        if product_id is None or not adet or adet <= 0:
            raise girdi("Toplu hurdada ürün ve adet zorunlu")
        if kaynak_durum not in ("HAZIR_DEGIL", "KONTROLDE", "KAYIP"):
            raise girdi("Toplu hurda yalnız hazır olmayan, kontroldeki ya da kayıp stoktan yapılır")
        urun = urun_dogrula(await db.get(Product, product_id))
        if seri_takipli_mi(urun):
            raise girdi(f"'{urun.code}' seri takipli; cihaz seçilerek işlenir")
        profil = await aktif_katalog(db, product_id)
        if katalog_birim_yasak_mi(user, profil.birim):
            raise KiralamaHatasi("Bu ürün başka bir birimin kiralama kataloğunda", "YASAK")
        kaynak_depo = None
        if kaynak_durum != "KAYIP":
            kaynak_depo = (await kiralama_deposu(db, depo_id, profil.birim)).id
        hareket = await hareket_yaz(
            db,
            tur="HURDA",
            product_id=product_id,
            qty=adet,
            clock=clock,
            user=user,
            from_warehouse_id=kaynak_depo,
            from_durum=kaynak_durum,
            to_durum="HURDA",
            note=gerekce,
        )
    await audit.log(
        db,
        ENTITY_KIRALIK,
        "hurda",
        entity_id=hareket.asset_id,
        new_value={"hareket_id": hareket.id, "gerekce": gerekce},
        user_id=user.id,
        ip=ip,
    )
    return hareket


async def atolyeden_dondu(
    db: AsyncSession,
    rental_asset_id: int,
    depo_id: int,
    *,
    user: User | None,
    clock: Clock,
    note: str | None = None,
) -> RentalInventoryMovement:
    """Atölye teslimi → (depo, KONTROLDE) (TS-102).

    Atölye modülünün `teslim_edildi` kancası (D2-B) çağırır; dönüşte cihaz
    yeniden dönüş kontrolünden geçer (HAZIR yalnız kontrolle verilir).
    """
    cihaz = (await cihazlari_kilitle(db, [rental_asset_id])).get(rental_asset_id)
    if cihaz is None:
        raise KiralamaHatasi("Kiralık cihaz bulunamadı")
    if cihaz.durum != "ATOLYEDE":
        raise KiralamaHatasi(f"'{cihaz.serial_no}' atölyede değil")
    depo = await kiralama_deposu(db, depo_id, cihaz.birim)
    return await hareket_yaz(
        db,
        tur="ATOLYE",
        product_id=cihaz.product_id,
        qty=1,
        clock=clock,
        user=user,
        asset=cihaz,
        from_durum="ATOLYEDE",
        to_warehouse_id=depo.id,
        to_durum="KONTROLDE",
        note=note or "Atölyeden döndü",
    )


# --- Listeler -----------------------------------------------------------------------


@dataclass
class EnvanterSuzgeci:
    q: str | None = None
    durum: str | None = None
    depo_id: int | None = None
    product_id: int | None = None
    birim: str | None = None
    uzun: bool = False


def _son_kontrole_giris():
    """Cihazın KONTROLDE'ye son giriş anı (alt sorgu)."""
    m = RentalInventoryMovement
    return (
        select(func.max(m.at))
        .where(m.asset_id == RentalAsset.id, m.to_durum == "KONTROLDE")
        .correlate(RentalAsset)
        .scalar_subquery()
    )


def envanter_sorgusu(user: User, s: EnvanterSuzgeci, *, an=None, uzun_gun: int = 7) -> Select:
    """Seri kiralık cihaz listesi; liste, sayı ve Excel AYNI sorgu."""
    stmt = (
        select(RentalAsset, Product.code, Product.name, Warehouse.name)
        .join(Product, Product.id == RentalAsset.product_id)
        .outerjoin(Warehouse, Warehouse.id == RentalAsset.warehouse_id)
        .where(RentalAsset.is_deleted.is_(False))
    )
    if s.durum:
        stmt = stmt.where(RentalAsset.durum == s.durum)
    if s.depo_id:
        stmt = stmt.where(RentalAsset.warehouse_id == s.depo_id)
    if s.product_id:
        stmt = stmt.where(RentalAsset.product_id == s.product_id)
    if s.birim:
        stmt = stmt.where(RentalAsset.birim == s.birim)
    if s.q:
        anahtar = normalize_seri(s.q)
        kosul = [Product.code.ilike(f"%{s.q.strip()}%"), Product.name.ilike(f"%{s.q.strip()}%")]
        if anahtar:
            kosul.append(RentalAsset.serial_key.contains(anahtar))
        stmt = stmt.where(or_(*kosul))
    if s.uzun and an is not None:
        stmt = stmt.where(
            RentalAsset.durum == "KONTROLDE",
            _son_kontrole_giris() < an - timedelta(days=uzun_gun),
        )
    return kiralik_kosulu(stmt, user).order_by(RentalAsset.id.desc())


async def cihaz_hareketleri(db: AsyncSession, cihaz_id: int) -> list[RentalInventoryMovement]:
    """Cihazın bütün hareketleri `at, id` sırasıyla (E06-03 kabulü)."""
    return list(
        (
            await db.scalars(
                select(RentalInventoryMovement)
                .where(RentalInventoryMovement.asset_id == cihaz_id)
                .order_by(RentalInventoryMovement.at, RentalInventoryMovement.id)
            )
        ).all()
    )


def toplu_hareket_sorgusu(user: User, *, product_id: int | None, depo_id: int | None) -> Select:
    m = RentalInventoryMovement
    stmt = (
        select(m)
        .join(RentalCatalogItem, RentalCatalogItem.product_id == m.product_id)
        .where(m.asset_id.is_(None))
    )
    if product_id:
        stmt = stmt.where(m.product_id == product_id)
    if depo_id:
        stmt = stmt.where(or_(m.from_warehouse_id == depo_id, m.to_warehouse_id == depo_id))
    return katalog_kosulu(stmt, user).order_by(m.at.desc(), m.id.desc())


async def kontrolde_gun(db: AsyncSession, cihaz_idler: list[int], an) -> dict[int, int]:
    """Cihaz → KONTROLDE'de geçen gün (son `to_durum=KONTROLDE` hareketinden)."""
    if not cihaz_idler:
        return {}
    m = RentalInventoryMovement
    satirlar = (
        await db.execute(
            select(m.asset_id, func.max(m.at))
            .where(m.asset_id.in_(cihaz_idler), m.to_durum == "KONTROLDE")
            .group_by(m.asset_id)
        )
    ).all()
    return {cid: max((an - zaman).days, 0) for cid, zaman in satirlar if zaman is not None}


async def aktif_tahsis_kiralamalari(db: AsyncSession, cihaz_idler: list[int]) -> dict[int, int]:
    """Cihaz → AKTİF tahsisli olduğu kiralama."""
    if not cihaz_idler:
        return {}
    satirlar = (
        await db.execute(
            select(RentalAllocation.asset_id, RentalAllocation.rental_id).where(
                RentalAllocation.asset_id.in_(cihaz_idler), RentalAllocation.durum == "AKTIF"
            )
        )
    ).all()
    return {a: r for a, r in satirlar}


# --- Toplu giriş (TS-121) -------------------------------------------------------------


def _toplu_profil():
    from app.services.imports.cekirdek import Profil, Sutun

    class KiralikTopluGiris(Profil):
        kod = "kiralik_toplu_giris"
        ad = "Kiralık envanter toplu giriş"
        aciklama = "Ürün kodu, seri no (seri takipli üründe) ya da adet, depo kodu, durum"
        sutunlar = (
            Sutun("urun_kodu", ("Ürün Kodu", "Urun Kodu", "Ürün"), zorunlu=True),
            Sutun("seri_no", ("Seri No", "Seri Numarası", "Seri")),
            Sutun("adet", ("Adet", "Miktar")),
            Sutun("depo_kodu", ("Depo Kodu", "Depo"), zorunlu=True),
            Sutun("durum", ("Durum",), aciklama="HAZIR, KONTROLDE ya da HAZIR_DEGIL"),
            Sutun("not", ("Not", "Açıklama")),
        )
        guncelleme_destekli = False

    return KiralikTopluGiris()


def toplu_sablon() -> bytes:
    from app.services.imports.cekirdek import sablon_xlsx

    return sablon_xlsx(_toplu_profil())


def dosya_ozeti(icerik: bytes) -> str:
    return hashlib.sha256(icerik).hexdigest()


async def _toplu_dogrula(
    db: AsyncSession, user: User, satirlar: list[dict]
) -> list[dict[str, Any]]:
    """Satır doğrulaması (önizleme ve onay AYNI fonksiyon). Hiçbir şey yazmaz."""
    urunler: dict[str, Product | None] = {}
    depolar: dict[str, Warehouse | None] = {}
    gorulen: set[tuple[int, str]] = set()
    sonuc = []
    for no, ham in enumerate(satirlar, start=1):
        hatalar: list[str] = []
        kod = (ham.get("urun_kodu") or "").strip()
        seri = (ham.get("seri_no") or "").strip()
        depo_kodu = (ham.get("depo_kodu") or "").strip()
        durum = (ham.get("durum") or "HAZIR").strip().upper() or "HAZIR"
        adet_ham = (ham.get("adet") or "").strip()
        adet: int | None = None
        if kod not in urunler:
            urunler[kod] = await db.scalar(select(Product).where(Product.code == kod))
        urun = urunler[kod]
        if depo_kodu not in depolar:
            depolar[depo_kodu] = await db.scalar(
                select(Warehouse).where(Warehouse.code == depo_kodu)
            )
        depo = depolar[depo_kodu]
        profil = None
        if urun is None:
            hatalar.append(f"Ürün bulunamadı: {kod}")
        else:
            try:
                urun_dogrula(urun)
                profil = await aktif_katalog(db, urun.id)
                if katalog_birim_yasak_mi(user, profil.birim):
                    hatalar.append("Başka birimin ürünü")
                    profil = None
            except KiralamaHatasi as exc:
                hatalar.append(exc.mesaj)
        if durum not in GIRIS_DURUMLARI:
            hatalar.append(f"Geçersiz durum: {durum}")
        if depo is None:
            hatalar.append(f"Depo bulunamadı: {depo_kodu}")
        elif profil is not None:
            try:
                await kiralama_deposu(db, depo.id, profil.birim)
            except KiralamaHatasi as exc:
                hatalar.append(exc.mesaj)
        if adet_ham:
            try:
                sayi = float(adet_ham.replace(",", "."))
            except ValueError:
                sayi = None
            if sayi is None or not sayi.is_integer() or sayi <= 0:
                hatalar.append(f"Adet pozitif tam sayı olmalı: {adet_ham}")
            else:
                adet = int(sayi)
        if urun is not None and urun.identity_kind == KIMLIK_SERI:
            if not seri:
                hatalar.append("Seri takipli üründe seri no zorunlu")
            elif adet not in (None, 1):
                hatalar.append("Seri takipli üründe adet 1 olmalı")
            else:
                anahtar = normalize_seri(seri)
                if (urun.id, anahtar) in gorulen:
                    hatalar.append(f"Dosyada mükerrer seri: {seri}")
                elif await _seri_var_mi(db, urun.id, anahtar) is not None:
                    hatalar.append(f"Seri zaten envanterde: {seri}")
                gorulen.add((urun.id, anahtar))
            adet = 1
        elif urun is not None:
            if seri:
                hatalar.append("Seri takipsiz üründe seri no girilmez")
            if adet is None and not any("Adet" in h for h in hatalar):
                hatalar.append("Toplu üründe adet zorunlu")
        sonuc.append(
            {
                "satir_no": no,
                "urun_kodu": kod,
                "seri_no": seri or None,
                "adet": adet,
                "depo_kodu": depo_kodu,
                "durum": durum,
                "not": (ham.get("not") or "").strip() or None,
                "hatalar": hatalar,
                "_product_id": urun.id if urun is not None else None,
                "_depo_id": depo.id if depo is not None else None,
            }
        )
    return sonuc


def _oku(dosya_adi: str, icerik: bytes) -> list[dict]:
    from app.services.imports.cekirdek import DosyaHatasi, oku

    try:
        okuma = oku(dosya_adi, icerik, _toplu_profil())
    except DosyaHatasi as exc:
        raise girdi(str(exc)) from exc
    if len(okuma.satirlar) > TOPLU_GIRIS_UST_SINIR:
        raise girdi(f"Dosyada en çok {TOPLU_GIRIS_UST_SINIR} satır olabilir")
    return okuma.satirlar


async def toplu_onizleme(
    db: AsyncSession, user: User, dosya_adi: str, icerik: bytes
) -> dict[str, Any]:
    """Önizleme: dosya ayrıştırılır ve doğrulanır, HİÇBİR ŞEY YAZILMAZ."""
    import asyncio

    satirlar = await asyncio.to_thread(_oku, dosya_adi, icerik)
    dogrulanmis = await _toplu_dogrula(db, user, satirlar)
    return {
        "sha256": dosya_ozeti(icerik),
        "toplam": len(dogrulanmis),
        "gecerli": sum(1 for s in dogrulanmis if not s["hatalar"]),
        "hatali": sum(1 for s in dogrulanmis if s["hatalar"]),
        "satirlar": [{k: v for k, v in s.items() if not k.startswith("_")} for s in dogrulanmis],
    }


async def toplu_onayla(
    db: AsyncSession,
    user: User,
    clock: Clock,
    dosya_adi: str,
    icerik: bytes,
    sha256: str,
    *,
    ip: str | None = None,
) -> dict[str, Any]:
    """Onay: dosya YENİDEN doğrulanır; özet önizlemeninkiyle aynı değilse 409.

    Yalnız hatasız satırlar, her biri `kind=GIRIS` hareketiyle yazılır.
    """
    import asyncio

    if dosya_ozeti(icerik) != (sha256 or "").strip().lower():
        raise KiralamaHatasi("Dosya önizlemeden sonra değişmiş; yeniden önizleyin")
    satirlar = await asyncio.to_thread(_oku, dosya_adi, icerik)
    dogrulanmis = await _toplu_dogrula(db, user, satirlar)
    yazilan = 0
    adet = 0
    for s in dogrulanmis:
        if s["hatalar"]:
            continue
        sonuc = await giris(
            db,
            user,
            clock,
            product_id=s["_product_id"],
            depo_id=s["_depo_id"],
            durum=s["durum"],
            seriler=[s["seri_no"]] if s["seri_no"] else None,
            adet=None if s["seri_no"] else s["adet"],
            note=s["not"] or f"Toplu giriş satır {s['satir_no']}",
            ip=ip,
        )
        yazilan += 1
        adet += sonuc.adet
    return {
        "yazilan_satir": yazilan,
        "atlanan_satir": len(dogrulanmis) - yazilan,
        "toplam_adet": adet,
        "hatalar": [
            {"satir_no": s["satir_no"], "hatalar": s["hatalar"]}
            for s in dogrulanmis
            if s["hatalar"]
        ],
    }


__all__ = [
    "DURUM_ETIKETLERI",
    "GIRIS_DURUMLARI",
    "KiralamaHatasi",
    "aktif_katalog",
    "bakiye",
    "bakiye_tablosu",
    "cihazlari_kilitle",
    "giris",
    "hareket_yaz",
    "kapsamli_kiralik",
    "katalog_kilitle",
    "kiralama_deposu",
    "kontrol",
    "transfer",
]
