"""Kiralama deposu fiziksel sayımı (TS-195, E06-22 b).

**Onaysız sayım hiçbir durumu/bakiyeyi değiştirmez.** Sayım açılır
(`uq_rsayim_acik`: depo başına tek AÇIK sayım), sayılan seri ve adetler
satırlara yazılır (PUT = satırların tamamı yeniden yazılır), fark OKUMA ANINDA
hareket defterinden hesaplanır ve SAKLANMAZ. Onayda yalnız kullanıcının
ONAYLADIĞI fark satırları `kind=SAYIM` hareketi yazar:

- **seri cihaz sistemde bu depoda ama sayılmadı** → KAYIP (cihaz bir
  kiralamaya tahsisliyse 409: önce tahsis çözülür);
- **toplu ürün eksik** → (depo, durum) → KAYIP; durum sırası HAZIR_DEGIL,
  KONTROLDE, HAZIR (rezervli hazır stok en son düşer);
- **toplu ürün fazla** → (depo, KONTROLDE) girişi (fazla çıkan mal dönüş
  kontrolünden geçmeden HAZIR olmaz — HAZIR yalnız giriş/kontrolle verilir);
- **sayıldı ama sistemde yok / başka yerde görünen seri** yalnız bilgidir:
  giriş ya da transfer kendi ucundan yapılır, sayım envantere cihaz AÇMAZ.

Sayımdan sonra depoda hareket olduysa ve onaylanan satırlara dokunuyorsa onay
409 + liste döner; `degisimi_kabul=true` ile fark GÜNCEL bakiyeyle
yeniden hesaplanmış hâliyle uygulanır (yedek parça sayımıyla aynı kural,
E11-17). Hareket ile sayım arasındaki bağ hareketin notundadır
("Sayım #<id>"; ayrı kolon yok — D3-S talep notu 4).

Kapsam: depo kullanıcının görebileceği kiralama deposu olmalı
(`kiralama_depolari`, birimsiz depo ortak). Kapsam dışı sayım 404, gövdedeki
başka birim ürünü 403. Servis yalnız `flush` eder; commit API'dedir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Product,
    RentalAllocation,
    RentalAsset,
    RentalCatalogItem,
    RentalCount,
    RentalCountLine,
    RentalInventoryMovement,
    Warehouse,
)
from app.services import audit
from app.services.normalize import normalize_seri
from app.services.statemachine import KIRALIK_SAYIM, IzinsizGecis
from app.services.teknik_servis.kapsam import kapsam_birim, katalog_birim_yasak_mi
from app.services.teknik_servis.kiralik_envanter import (
    DEPO_DURUMLARI,
    KiralamaHatasi,
    bakiye,
    bulunamadi,
    cihazlari_kilitle,
    girdi,
    hareket_yaz,
    katalog_kilitle,
    katalog_profili,
    seri_takipli_mi,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

ENTITY = "rental_counts"
SATIR_UST_SINIR = 2000
NOT_UZUNLUGU = 300
# Toplu eksikte düşülecek durum sırası (rezervli HAZIR en son).
EKSIK_DUSME_SIRASI = ("HAZIR_DEGIL", "KONTROLDE", "HAZIR")
FARK_TURLERI = {
    "SAYILMADI": "Sistemde var, sayılmadı",
    "SISTEMDE_YOK": "Sayıldı, sistemde yok",
    "BASKA_YERDE": "Sayıldı, sistemde başka yerde/durumda",
    "EKSIK": "Adet eksik",
    "FAZLA": "Adet fazla",
}
# Onayla uygulanabilen fark türleri (diğerleri bilgi).
UYGULANABILIR = ("SAYILMADI", "EKSIK", "FAZLA")


# --- Kapsam --------------------------------------------------------------------------


def _depo_kosulu(stmt: Select, user: User) -> Select:
    return kapsam_birim(stmt, user, Warehouse.birim, birimsiz_gorunur=True)


def sayim_sorgusu(user: User) -> Select:
    """Kapsamdaki kiralama depolarının sayımları (liste ve sayı aynı sorgu)."""
    stmt = (
        select(RentalCount, Warehouse.name)
        .join(Warehouse, Warehouse.id == RentalCount.warehouse_id)
        .where(RentalCount.is_deleted.is_(False), Warehouse.kiralama_deposu.is_(True))
    )
    return _depo_kosulu(stmt, user).order_by(RentalCount.id.desc())


async def kapsamli_sayim(
    db: AsyncSession, user: User, sayim_id: int, *, kilit: bool = False
) -> RentalCount:
    """Sayımı kapsamıyla getirir; yoksa/kapsam dışıysa 404 (yazma yapılmaz)."""
    stmt = (
        select(RentalCount)
        .join(Warehouse, Warehouse.id == RentalCount.warehouse_id)
        .where(
            RentalCount.id == sayim_id,
            RentalCount.is_deleted.is_(False),
            Warehouse.kiralama_deposu.is_(True),
        )
    )
    stmt = _depo_kosulu(stmt, user)
    if kilit:
        stmt = stmt.with_for_update(of=RentalCount).execution_options(populate_existing=True)
    sayim = await db.scalar(stmt)
    if sayim is None:
        raise bulunamadi("Sayım bulunamadı")
    return sayim


async def _kapsamli_depo(db: AsyncSession, user: User, depo_id: int) -> Warehouse:
    stmt = select(Warehouse).where(
        Warehouse.id == depo_id,
        Warehouse.kiralama_deposu.is_(True),
        Warehouse.is_active.is_(True),
    )
    depo = await db.scalar(_depo_kosulu(stmt, user))
    if depo is None:
        raise bulunamadi("Kiralama deposu bulunamadı")
    return depo


def _gecis(sayim: RentalCount, hedef: str) -> None:
    try:
        KIRALIK_SAYIM.dogrula(sayim.durum, hedef)
    except IzinsizGecis:
        raise KiralamaHatasi(
            "Sayım kapalı (onaylanmış ya da iptal edilmiş); değiştirilemez"
        ) from None


# --- Açma / satırlar ---------------------------------------------------------------------


async def sayim_ac(
    db: AsyncSession,
    user: User,
    clock: Clock,
    *,
    depo_id: int,
    notes: str | None = None,
    ip: str | None = None,
) -> RentalCount:
    """Depoda AÇIK sayım başlatır; ikinci açık sayım 409."""
    depo = await _kapsamli_depo(db, user, depo_id)
    acik = await db.scalar(
        select(RentalCount.id).where(
            RentalCount.warehouse_id == depo.id,
            RentalCount.durum == "ACIK",
            RentalCount.is_deleted.is_(False),
        )
    )
    if acik is not None:
        raise KiralamaHatasi(
            f"{depo.name} deposunda açık bir sayım var (#{acik}); önce onaylayın ya da iptal edin",
            veri={"sayim_id": acik},
        )
    sayim = RentalCount(
        warehouse_id=depo.id,
        durum="ACIK",
        baslangic_at=clock.now(),
        notes=(notes or "").strip() or None,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(sayim)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:  # yarışta ikinci açık sayım
        raise KiralamaHatasi(f"{depo.name} deposunda açık bir sayım var") from exc
    await audit.log(
        db,
        ENTITY,
        "sayim.ac",
        entity_id=sayim.id,
        new_value={"depo_id": depo.id},
        user_id=user.id,
        ip=ip,
    )
    return sayim


@dataclass
class SayimSatiri:
    product_id: int
    seri: str | None = None
    adet: int | None = None
    notes: str | None = None


async def satirlari_yaz(
    db: AsyncSession,
    user: User,
    sayim: RentalCount,
    satirlar: list[SayimSatiri],
    *,
    ip: str | None = None,
) -> list[RentalCountLine]:
    """Sayılan seri/adetleri yazar (önceki satırların YERİNE). Sayım açık değilse
    409; dosya içi mükerrer seri / ürün 400; başka birim ürünü 403."""
    _gecis(sayim, "ONAYLANDI")  # yalnız ACIK sayım değişir
    if len(satirlar) > SATIR_UST_SINIR:
        raise girdi(f"En çok {SATIR_UST_SINIR} satır girilebilir")
    urunler: dict[int, Product] = {}
    gorulen_seri: set[tuple[int, str]] = set()
    gorulen_toplu: set[int] = set()
    yeni: list[RentalCountLine] = []
    depo = await db.get(Warehouse, sayim.warehouse_id)
    for s in satirlar:
        urun = urunler.get(s.product_id) or await db.get(Product, s.product_id)
        if urun is None or urun.is_deleted:
            raise girdi(f"Ürün bulunamadı: {s.product_id}")
        urunler[urun.id] = urun
        profil = await katalog_profili(db, urun.id)
        if profil is None:
            raise girdi(f"'{urun.code}' kiralama kataloğunda değil")
        if katalog_birim_yasak_mi(user, profil.birim):
            raise KiralamaHatasi(f"'{urun.code}' başka bir birimin kiralama kataloğunda", "YASAK")
        if depo is not None and depo.birim is not None and depo.birim != profil.birim:
            raise girdi(f"'{urun.code}' bu deponun biriminde değil")
        not_ = (s.notes or "").strip() or None
        if not_ is not None and len(not_) > NOT_UZUNLUGU:
            raise girdi(f"Not en çok {NOT_UZUNLUGU} karakter olabilir")
        if seri_takipli_mi(urun):
            metin = (s.seri or "").strip()
            anahtar = normalize_seri(metin)
            if not anahtar:
                raise girdi(f"'{urun.code}' seri takipli; seri no girilmeli")
            if (urun.id, anahtar) in gorulen_seri:
                raise girdi(f"'{metin}' iki kez girildi")
            gorulen_seri.add((urun.id, anahtar))
            adet = 1 if s.adet is None else s.adet
            if adet not in (0, 1):
                raise girdi("Seri takipli üründe sayılan adet 0 ya da 1 olur")
            cihaz = await db.scalar(
                select(RentalAsset).where(
                    RentalAsset.product_id == urun.id,
                    RentalAsset.serial_key == anahtar,
                    RentalAsset.is_deleted.is_(False),
                )
            )
            yeni.append(
                RentalCountLine(
                    rental_count_id=sayim.id,
                    product_id=urun.id,
                    asset_id=cihaz.id if cihaz else None,
                    serial_text=None if cihaz else metin,
                    sayilan_adet=adet,
                    notes=not_,
                    created_by=user.id,
                    updated_by=user.id,
                )
            )
        else:
            if s.seri:
                raise girdi(f"'{urun.code}' seri takipli değil; adet girilir")
            if s.adet is None or s.adet < 0:
                raise girdi(f"'{urun.code}' için sayılan adet sıfır ya da pozitif olmalı")
            if urun.id in gorulen_toplu:
                raise girdi(f"'{urun.code}' iki kez girildi")
            gorulen_toplu.add(urun.id)
            yeni.append(
                RentalCountLine(
                    rental_count_id=sayim.id,
                    product_id=urun.id,
                    sayilan_adet=s.adet,
                    notes=not_,
                    created_by=user.id,
                    updated_by=user.id,
                )
            )
    for eski in (
        await db.scalars(select(RentalCountLine).where(RentalCountLine.rental_count_id == sayim.id))
    ).all():
        await db.delete(eski)
    await db.flush()
    db.add_all(yeni)
    sayim.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        ENTITY,
        "sayim.satir",
        entity_id=sayim.id,
        new_value={"satir": len(yeni)},
        user_id=user.id,
        ip=ip,
    )
    return yeni


async def satirlar(db: AsyncSession, sayim_id: int) -> list[RentalCountLine]:
    return list(
        (
            await db.scalars(
                select(RentalCountLine)
                .where(RentalCountLine.rental_count_id == sayim_id)
                .order_by(RentalCountLine.id)
            )
        ).all()
    )


# --- Fark ---------------------------------------------------------------------------------


async def _toplu_sistem(db: AsyncSession, depo_id: int, product_id: int) -> dict[str, int]:
    return {d: await bakiye(db, product_id, depo_id, d) for d in DEPO_DURUMLARI}


async def _depodaki_toplu_urunler(db: AsyncSession, depo_id: int) -> set[int]:
    m = RentalInventoryMovement
    return set(
        (
            await db.scalars(
                select(m.product_id)
                .where(
                    m.asset_id.is_(None),
                    or_(m.to_warehouse_id == depo_id, m.from_warehouse_id == depo_id),
                )
                .distinct()
            )
        ).all()
    )


async def _sonraki_hareketler(
    db: AsyncSession, sayim: RentalCount
) -> list[RentalInventoryMovement]:
    m = RentalInventoryMovement
    return list(
        (
            await db.scalars(
                select(m)
                .where(
                    m.at > sayim.baslangic_at,
                    or_(
                        m.to_warehouse_id == sayim.warehouse_id,
                        m.from_warehouse_id == sayim.warehouse_id,
                    ),
                    or_(m.note.is_(None), m.note.not_like(f"Sayım #{sayim.id}%")),
                )
                .order_by(m.id)
            )
        ).all()
    )


async def fark(db: AsyncSession, user: User, sayim: RentalCount) -> dict[str, Any]:
    """Fark satırları (hesaplanır, saklanmaz). Her satırın `anahtar`'ı onaydaki
    karar kimliğidir: `S:<cihaz>` seri, `T:<ürün>` toplu, `Y:<satır>` sistemde yok.

    Yalnız kullanıcının kataloğunu görebildiği birimlerin ürünleri dahil edilir
    (başka birimin ürünü sayıya sızmaz)."""
    depo_id = sayim.warehouse_id
    satir_listesi = await satirlar(db, sayim.id)
    sayilan_cihaz = {s.asset_id: s for s in satir_listesi if s.asset_id is not None}
    toplu_satir = {
        s.product_id: s for s in satir_listesi if s.asset_id is None and s.serial_key is None
    }
    gorunur = select(RentalCatalogItem.product_id)
    gorunur = kapsam_birim(gorunur, user, RentalCatalogItem.birim, birimsiz_gorunur=False)
    gorunur_urunler = set((await db.scalars(gorunur)).all())

    sonuc: list[dict[str, Any]] = []
    urun_idler: set[int] = set()

    # 1) Seri: sistemde bu depoda (depo durumlarında) olanlar.
    depodaki = (
        await db.scalars(
            select(RentalAsset).where(
                RentalAsset.warehouse_id == depo_id,
                RentalAsset.durum.in_(DEPO_DURUMLARI),
                RentalAsset.is_deleted.is_(False),
            )
        )
    ).all()
    depodaki_idler = set()
    for c in depodaki:
        if c.product_id not in gorunur_urunler:
            continue
        depodaki_idler.add(c.id)
        satir = sayilan_cihaz.get(c.id)
        if satir is not None and satir.sayilan_adet == 1:
            continue
        urun_idler.add(c.product_id)
        sonuc.append(
            {
                "anahtar": f"S:{c.id}",
                "tur": "SAYILMADI",
                "product_id": c.product_id,
                "kiralik_id": c.id,
                "seri": c.serial_no,
                "sistem_durum": c.durum,
                "sistem_adet": 1,
                "sayilan_adet": 0,
                "fark": -1,
                "uygulanabilir": True,
            }
        )
    # 2) Sayılan ama bu depoda görünmeyen seri cihazlar / sistemde olmayan seriler.
    cihaz_haritasi = {
        c.id: c
        for c in (
            await db.scalars(
                select(RentalAsset).where(RentalAsset.id.in_(list(sayilan_cihaz) or [0]))
            )
        ).all()
    }
    for s in satir_listesi:
        if s.sayilan_adet != 1:
            continue
        if s.asset_id is not None and s.asset_id not in depodaki_idler:
            c = cihaz_haritasi.get(s.asset_id)
            urun_idler.add(s.product_id)
            sonuc.append(
                {
                    "anahtar": f"S:{s.asset_id}",
                    "tur": "BASKA_YERDE",
                    "product_id": s.product_id,
                    "kiralik_id": s.asset_id,
                    "seri": c.serial_no if c else None,
                    "sistem_durum": c.durum if c else None,
                    "sistem_adet": 0,
                    "sayilan_adet": 1,
                    "fark": 1,
                    "uygulanabilir": False,
                }
            )
        elif s.asset_id is None and s.serial_key is not None:
            urun_idler.add(s.product_id)
            sonuc.append(
                {
                    "anahtar": f"Y:{s.id}",
                    "tur": "SISTEMDE_YOK",
                    "product_id": s.product_id,
                    "kiralik_id": None,
                    "seri": s.serial_text,
                    "sistem_durum": None,
                    "sistem_adet": 0,
                    "sayilan_adet": 1,
                    "fark": 1,
                    "uygulanabilir": False,
                }
            )
    # 3) Toplu ürünler: depo bakiyesi (HAZIR + KONTROLDE + HAZIR_DEGIL) ↔ sayılan.
    toplu_urunler = (await _depodaki_toplu_urunler(db, depo_id)) | set(toplu_satir)
    for pid in sorted(toplu_urunler):
        if pid not in gorunur_urunler:
            continue
        dagilim = await _toplu_sistem(db, depo_id, pid)
        sistem = sum(dagilim.values())
        satir = toplu_satir.get(pid)
        sayilan = satir.sayilan_adet if satir is not None else 0
        if sistem == sayilan:
            continue
        urun_idler.add(pid)
        sonuc.append(
            {
                "anahtar": f"T:{pid}",
                "tur": "EKSIK" if sayilan < sistem else "FAZLA",
                "product_id": pid,
                "kiralik_id": None,
                "seri": None,
                "sistem_durum": None,
                "sistem_dagilim": dagilim,
                "sistem_adet": sistem,
                "sayilan_adet": sayilan,
                "fark": sayilan - sistem,
                "uygulanabilir": True,
            }
        )
    urunler = {
        u.id: u
        for u in (
            await db.scalars(select(Product).where(Product.id.in_(list(urun_idler) or [0])))
        ).all()
    }
    for r in sonuc:
        u = urunler.get(r["product_id"])
        r["urun_kodu"] = u.code if u else None
        r["urun_adi"] = u.name if u else None
        r["tur_adi"] = FARK_TURLERI[r["tur"]]
    sonraki = await _sonraki_hareketler(db, sayim)
    return {
        "sayim_id": sayim.id,
        "depo_id": depo_id,
        "satirlar": sonuc,
        "sayim_sonrasi_hareket": len(sonraki),
        "ozet": {t: sum(1 for r in sonuc if r["tur"] == t) for t in FARK_TURLERI},
    }


# --- Onay / iptal -------------------------------------------------------------------------


async def _aktif_tahsisli(db: AsyncSession, cihaz_id: int) -> bool:
    return (
        await db.scalar(
            select(func.count())
            .select_from(RentalAllocation)
            .where(RentalAllocation.asset_id == cihaz_id, RentalAllocation.durum == "AKTIF")
        )
        or 0
    ) > 0


async def onayla(
    db: AsyncSession,
    user: User,
    clock: Clock,
    sayim: RentalCount,
    *,
    kararlar: list[str],
    gerekce: str | None = None,
    degisimi_kabul: bool = False,
    ip: str | None = None,
) -> list[RentalInventoryMovement]:
    """Onaylı fark satırlarını `kind=SAYIM` hareketiyle uygular, sayımı ONAYLANDI yapar.

    Onaylanmayan fark satırı HİÇBİR şeyi değiştirmez. Bilinmeyen ya da bilgi
    amaçlı (uygulanamaz) anahtar 400; sayım sonrası hareket görmüş satır
    `degisimi_kabul` olmadan 409.
    """
    _gecis(sayim, "ONAYLANDI")
    secilen = list(dict.fromkeys(k.strip() for k in kararlar if k and k.strip()))
    sonuc = await fark(db, user, sayim)
    satirlar_ = {r["anahtar"]: r for r in sonuc["satirlar"]}
    for anahtar in secilen:
        r = satirlar_.get(anahtar)
        if r is None:
            raise girdi(f"Fark satırı bulunamadı ya da artık fark yok: {anahtar}")
        if not r["uygulanabilir"]:
            raise girdi(f"'{r['tur_adi']}' satırı sayımla uygulanmaz (giriş/transfer ekranı)")
    secili = [satirlar_[a] for a in secilen]
    sonraki = await _sonraki_hareketler(db, sayim)
    if sonraki and not degisimi_kabul:
        etkilenen = {r["anahtar"] for r in secili} & (
            {f"S:{h.asset_id}" for h in sonraki if h.asset_id}
            | {f"T:{h.product_id}" for h in sonraki if h.asset_id is None}
        )
        if etkilenen:
            raise KiralamaHatasi(
                "Sayım başladıktan sonra bu satırlarda hareket oldu; fark güncel bakiyeyle "
                "yeniden hesaplandı. Kontrol edip 'değişimi kabul et' ile onaylayın.",
                veri={"etkilenen": sorted(etkilenen)},
            )
    await katalog_kilitle(db, {r["product_id"] for r in secili})
    cihazlar = await cihazlari_kilitle(db, [r["kiralik_id"] for r in secili if r["kiralik_id"]])
    etiket = f"Sayım #{sayim.id}"
    if gerekce and gerekce.strip():
        etiket = f"{etiket}: {gerekce.strip()}"
    hareketler: list[RentalInventoryMovement] = []
    for r in secili:
        if r["kiralik_id"] is not None:
            cihaz = cihazlar.get(r["kiralik_id"])
            if cihaz is None:
                raise girdi("Sayımdaki cihaz bulunamadı")
            if cihaz.warehouse_id != sayim.warehouse_id or cihaz.durum not in DEPO_DURUMLARI:
                raise KiralamaHatasi(f"'{cihaz.serial_no}' artık bu depoda değil")
            if await _aktif_tahsisli(db, cihaz.id):
                raise KiralamaHatasi(
                    f"'{cihaz.serial_no}' bir kiralamaya tahsisli; kayıp yazmadan önce "
                    "tahsisi çözün"
                )
            hareketler.append(
                await hareket_yaz(
                    db,
                    tur="SAYIM",
                    product_id=cihaz.product_id,
                    qty=1,
                    clock=clock,
                    user=user,
                    asset=cihaz,
                    from_warehouse_id=cihaz.warehouse_id,
                    from_durum=cihaz.durum,
                    to_durum="KAYIP",
                    note=etiket,
                )
            )
            continue
        pid = r["product_id"]
        dagilim = await _toplu_sistem(db, sayim.warehouse_id, pid)
        satir = next(
            (
                s
                for s in await satirlar(db, sayim.id)
                if s.product_id == pid and s.asset_id is None and s.serial_key is None
            ),
            None,
        )
        fark_ = (satir.sayilan_adet if satir else 0) - sum(dagilim.values())
        if fark_ > 0:
            hareketler.append(
                await hareket_yaz(
                    db,
                    tur="SAYIM",
                    product_id=pid,
                    qty=fark_,
                    clock=clock,
                    user=user,
                    to_warehouse_id=sayim.warehouse_id,
                    to_durum="KONTROLDE",
                    note=etiket,
                )
            )
        elif fark_ < 0:
            kalan = -fark_
            for durum in EKSIK_DUSME_SIRASI:
                if kalan <= 0:
                    break
                adet = min(kalan, dagilim.get(durum, 0))
                if adet <= 0:
                    continue
                hareketler.append(
                    await hareket_yaz(
                        db,
                        tur="SAYIM",
                        product_id=pid,
                        qty=adet,
                        clock=clock,
                        user=user,
                        from_warehouse_id=sayim.warehouse_id,
                        from_durum=durum,
                        to_durum="KAYIP",
                        note=etiket,
                    )
                )
                kalan -= adet
    _gecis(sayim, "ONAYLANDI")
    sayim.durum = "ONAYLANDI"
    sayim.onaylayan_id = user.id
    sayim.onay_at = clock.now()
    sayim.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        ENTITY,
        "sayim.onayla",
        entity_id=sayim.id,
        new_value={
            "kararlar": secilen,
            "hareketler": [h.id for h in hareketler],
            "gerekce": (gerekce or "").strip() or None,
            "degisimi_kabul": degisimi_kabul,
        },
        user_id=user.id,
        ip=ip,
    )
    return hareketler


async def iptal(
    db: AsyncSession,
    user: User,
    sayim: RentalCount,
    *,
    gerekce: str,
    ip: str | None = None,
) -> RentalCount:
    """Açık sayımı gerekçeyle iptal eder (hiçbir hareket yazılmaz)."""
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise girdi("İptal gerekçesi zorunlu")
    _gecis(sayim, "IPTAL")
    sayim.durum = "IPTAL"
    sayim.iptal_gerekcesi = gerekce[:500]
    sayim.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        ENTITY,
        "sayim.iptal",
        entity_id=sayim.id,
        new_value={"gerekce": sayim.iptal_gerekcesi},
        user_id=user.id,
        ip=ip,
    )
    return sayim


async def ozet_ciktisi(db: AsyncSession, sayim: RentalCount, *, ayrinti: bool = False) -> dict:
    depo = await db.get(Warehouse, sayim.warehouse_id)
    cikti: dict[str, Any] = {
        "id": sayim.id,
        "depo_id": sayim.warehouse_id,
        "depo_adi": depo.name if depo else None,
        "durum": sayim.durum,
        "baslangic_at": sayim.baslangic_at,
        "onay_at": sayim.onay_at,
        "onaylayan_id": sayim.onaylayan_id,
        "iptal_gerekcesi": sayim.iptal_gerekcesi,
        "notes": sayim.notes,
        "version": sayim.version,
    }
    if ayrinti:
        liste = await satirlar(db, sayim.id)
        urunler = {
            u.id: u
            for u in (
                await db.scalars(
                    select(Product).where(Product.id.in_([s.product_id for s in liste] or [0]))
                )
            ).all()
        }
        cihazlar = {
            c.id: c
            for c in (
                await db.scalars(
                    select(RentalAsset).where(
                        RentalAsset.id.in_([s.asset_id for s in liste if s.asset_id] or [0])
                    )
                )
            ).all()
        }
        cikti["satirlar"] = [
            {
                "id": s.id,
                "product_id": s.product_id,
                "urun_kodu": urunler[s.product_id].code if s.product_id in urunler else None,
                "kiralik_id": s.asset_id,
                "seri": (
                    cihazlar[s.asset_id].serial_no if s.asset_id in cihazlar else s.serial_text
                ),
                "sistemde": s.asset_id is not None,
                "sayilan_adet": s.sayilan_adet,
                "notes": s.notes,
            }
            for s in liste
        ]
    return cikti
