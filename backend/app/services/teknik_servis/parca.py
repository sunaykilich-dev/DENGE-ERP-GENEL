"""Yedek parça ve servis stoğu: tek stok yazıcısı, iade/ters kayıt, transfer,
sayım, açılış stoğu, parça talebi (E11, TS-130…138).

**Defter = canlı `stock_movements`** (KD-25, K1). Ayrı tablo yok; servis
satırları `hareket_turu` ile ayrılır ve tür → (canlı `reason`, işaret)
eşlemesi şemada kilitlidir (`ck_stok_hareket_tur_yon`). Bakiye kolonu YOKTUR:
bakiye = Σqty. Servis deposuna yazan TEK kod yolu bu dosyadır
(`_hareket_ekle`); canlı `POST /api/stok/hareket` servis/kiralama deposuna
409 verir (`services/stock.py`).

**Eşzamanlılık (E11-01/02, K19):** her yazma isteğindeki BÜTÜN ürünler tek
sorguda, kimliğe göre SIRALI `FOR UPDATE` ile kilitlenir. Rastgele sırada
kilitlenseydi ters sıralı iki çok satırlı çıkış birbirini kilitlerdi
(deadlock). Servis işine çıkışta iş satırı `FOR SHARE` ile kilitlenir; işi
kapatan güncelleme çıkış commit edilene kadar bekler — "kapalı işe parça
kaldı" yarışı olmaz.

**Kurallar:**
- Kapalı işe (TAMAMLANDI/KAPATILDI/IPTAL) çıkış YOK (K3); iade ve ters kayıt
  serbest, ama kapalı işte İADE'nin ters kaydı fiilen yeni çıkıştır → 409.
- İade ≤ net çıkış (`net_cikis = −Σqty`, iş + parça); ters kayıt dahil hiçbir
  dizi net çıkışı eksiye düşüremez.
- Sayım farkının ters kaydı yok (düzeltme yeni sayımla).
- Pasif parça/depoya yalnız iade ve ters kayıt (sayım farkı pasif PARÇADA da
  serbest: sayım fiziksel gerçeği yazar).
- Maliyet (`unit_cost`) hareket anında DONDURULUR: girişte kullanıcı verir,
  diğer hareketlerde `birim_maliyet` (maliyetli girişlerin kümülatif ağırlıklı
  ortalaması) yazılır; bilinmiyorsa NULL — 0 YAZILMAZ (K8). Yanıtta yalnız
  `maliyet.gor` sahibine döner (API katmanı).

**Kapsam:** depo kümesi `depo_kosulu` (liste, KPI, uyarı, Excel aynı ifade —
sayı = sızıntı). Teknisyen (KENDI_ISLERI): birim depoları + KENDİ araç deposu;
başka teknisyenin araç deposu görünmez. Birimsiz birim kapsamlı kullanıcı
hiçbir depo görmez (fail-closed).

Saat yalnız `Clock`: hareket, talep ve sayımın `created_at`'i Clock'tan yazılır
(bugünkü çıkış sayısı ve "talepten sonraki çıkış" aynı saatle ölçülsün).

**Kanca kayıtları** (dosyanın en altında): `durum_degisti → talepleri_kapat`;
uyarılar `parca.az_stok` (parca.yonet), `parca.geldi` (parca.kullan).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    exists,
    false,
    func,
    not_,
    or_,
    select,
    text,
)
from sqlalchemy.orm import aliased

from app.models import (
    Product,
    ServiceHold,
    ServiceOrder,
    ServicePartRequest,
    StockCount,
    StockCountLine,
    StockMovement,
    Warehouse,
)
from app.models.stock import SERVIS_HAREKET_TURLERI, SERVIS_HAREKET_YONU
from app.models.teknik_servis import DURUM_GRUPLARI
from app.permissions import BIRIMLER, SCOPE_ALL, SCOPE_OWN_JOBS, SCOPES
from app.services import sirketler
from app.services.statemachine import PARCA_TALEBI, STOK_SAYIM
from app.services.teknik_servis import gecmis, kancalar, kapsam
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun_araligi
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User


class ParcaHatasi(ServisHatasi):
    """Parça iş kuralı ihlali → 409. `veri` makine okunur ek alanlar taşır
    (ör. sayım onayında sapan satırlar, açılışta hatalı satırlar)."""

    def __init__(self, mesaj: str, veri: dict[str, Any] | None = None) -> None:
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.veri = veri or {}


class ParcaBulunamadi(ValueError):
    """Kayıt yok ya da kullanıcının kapsamı dışında → 404 (varlığı gizlenir)."""


# --- Sözlükler ----------------------------------------------------------------------

HAREKET_TURU_ADLARI: dict[str, str] = {
    "GIRIS": "Giriş",
    "ACILIS": "Açılış stoğu",
    "CIKIS_SERVIS": "Servis çıkışı",
    "IADE_SERVIS": "Servis iadesi",
    "ZAYI": "Zayi",
    "TERS_KAYIT": "Ters kayıt",
    "TRANSFER_CIKIS": "Transfer çıkışı",
    "TRANSFER_GIRIS": "Transfer girişi",
    "SAYIM_FAZLASI": "Sayım fazlası",
    "SAYIM_EKSIGI": "Sayım eksiği",
}

STOK_DURUMLARI = ("YOK", "AZ", "YETERLI")
STOK_DURUM_ADLARI = {"YOK": "Stok yok", "AZ": "Az stok", "YETERLI": "Yeterli"}

KAPALI_SERVIS_DURUMLARI = DURUM_GRUPLARI["KAPALI"]
# Pasif DEPOYA yazılabilen türler; pasif PARÇAYA ek olarak sayım farkı serbest.
PASIF_DEPODA_SERBEST = frozenset({"IADE_SERVIS", "TERS_KAYIT"})
PASIF_PARCADA_SERBEST = PASIF_DEPODA_SERBEST | {"SAYIM_FAZLASI", "SAYIM_EKSIGI"}
# Kullanıcının maliyet verebildiği türler (diğerlerinde maliyet hesaplanır).
MALIYETLI_GIRIS_TURLERI = ("GIRIS", "ACILIS")

NOT_UZUNLUGU = 300  # canlı `stock_movements.notes` String(300) (K9)
BELGE_UZUNLUGU = 50
TOPLU_SATIR_UST_SINIR = 50
_MALIYET_HASSASIYETI = Decimal("0.0001")


@dataclass(frozen=True)
class Satir:
    """Yazma isteğinin bir satırı. Adet daima POZİTİF; yön türden gelir."""

    product_id: int
    adet: int
    unit_cost: Decimal | None = None


# --- Az stok: TEK fonksiyon (E11-10) ---------------------------------------------------


def stok_durumu(toplam: int, min_stok: int | None) -> str:
    """Ekran, filtre, KPI ve uyarının tek kuralı (SQL karşılığı `durum_ifadesi`).

    toplam ≤ 0 → YOK; asgari > 0 ve toplam < asgari → AZ; aksi YETERLI.
    """
    if toplam <= 0:
        return "YOK"
    if min_stok is not None and min_stok > 0 and toplam < min_stok:
        return "AZ"
    return "YETERLI"


def durum_ifadesi(toplam, min_stok) -> ColumnElement[str]:
    """`stok_durumu`'nun SQL karşılığı (aynı eşikler; birim testle kilitli)."""
    asgari = func.coalesce(min_stok, 0)
    return case(
        (toplam <= 0, "YOK"),
        (and_(asgari > 0, toplam < asgari), "AZ"),
        else_="YETERLI",
    )


# --- Depo kapsamı (TS-131) ---------------------------------------------------------------


def _kapsam_kodu(user: User) -> str | None:
    kod = user.role.scope if user.role is not None else None
    return kod if kod in SCOPES else None


def depo_kosulu(user: User) -> ColumnElement[bool]:
    """Kullanıcının görebildiği SERVİS depoları (pasifler dahil).

    - TUMU: bütün servis depoları (birimi henüz atanmamış eski depolar dahil —
      yönetici onları görüp birime bağlayabilsin);
    - KENDI_BIRIMI / KENDI_MUSTERILERI: kendi birim depoları + kendi araç deposu;
    - KENDI_ISLERI (teknisyen): kendi birim depoları (başka teknisyenlerin
      araç depoları HARİÇ) + kendi araç deposu;
    - birimsiz birim kapsamlı kullanıcı ya da bilinmeyen kapsam: hiçbiri.

    **Birim ayrımı (kullanıcı isteği 2026-11-09, migration fba000000001):**
    depolar birimlere tamamen ayrılır; "ortak (birimsiz) depo herkese
    görünür" kuralı KALDIRILDI. Birimi olmayan eski servis deposu yalnız
    TUMU kapsamına görünür. Yeni servis deposu birimsiz açılamaz
    (`ck_warehouse_servis_birim_zorunlu`).
    """
    temel = Warehouse.servis_deposu.is_(True)
    kod = _kapsam_kodu(user)
    if kod == SCOPE_ALL:
        # Şirket ayrımı: TUMU da etkin şirketin birim depoları + atanmamışlar.
        sirket = sirketler.etkin_birimler(user)
        if sirket is None:
            return temel
        return and_(temel, or_(Warehouse.birim.is_(None), Warehouse.birim.in_(sorted(sirket))))
    birimler = kapsam.kullanici_birimleri(user)
    if kod is None or not birimler:
        return false()
    birim_uygun = Warehouse.birim.in_(sorted(birimler))
    arac_deposu = and_(Warehouse.location_type == "TEKNISYEN", Warehouse.user_id.is_not(None))
    kendi_araci = and_(arac_deposu, Warehouse.user_id == user.id)
    if kod == SCOPE_OWN_JOBS:
        return and_(temel, or_(kendi_araci, and_(birim_uygun, not_(arac_deposu))))
    return and_(temel, or_(kendi_araci, birim_uygun))


def erisilebilir_depo_sorgusu(user: User) -> Select:
    # correlate(None): depoyu JOIN eden dış sorguya bağlanmasın (bağımsız alt sorgu).
    return select(Warehouse.id).where(depo_kosulu(user)).correlate(None)


async def erisilebilir_depolar(db: AsyncSession, user: User) -> list[int]:
    """Teknisyen: birim depoları + kendi araç deposu; birimsiz KENDI_BIRIMI → boş."""
    return list((await db.scalars(erisilebilir_depo_sorgusu(user).order_by(Warehouse.id))).all())


def birim_adi(birim: str | None) -> str:
    return BIRIMLER.get(birim, birim) if birim else "birimsiz"


def birim_uyumu_dogrula(depo: Warehouse, birim: str | None, *, ne: str) -> None:
    """Depo ile işin/öteki deponun birimi aynı mı? Değilse 409 (stok karışmaz).

    Kullanıcı isteği (2026-11-09): Haberleşme ve Güvenlik depoları tamamen
    ayrı; Güvenlik deposundan Haberleşme işine parça çıkılamaz, birimler arası
    transfer yapılamaz. Birimi atanmamış eski depo da (yalnız TUMU görür)
    birimli kayıtla eşleşmez: önce depo birime bağlanmalı.
    """
    if birim is None or depo.birim == birim:
        return
    raise ParcaHatasi(
        f"'{depo.name}' {birim_adi(depo.birim)} deposu; {birim_adi(birim)} {ne} "
        "kullanılamaz. Depolar birimlere ayrıdır."
    )


async def depo_getir(db: AsyncSession, user: User, depo_id: int) -> Warehouse:
    """Kapsam içi servis deposu; yoksa/kapsam dışıysa ParcaBulunamadi (404)."""
    depo = await db.scalar(select(Warehouse).where(Warehouse.id == depo_id, depo_kosulu(user)))
    if depo is None:
        raise ParcaBulunamadi("Depo bulunamadı")
    return depo


def is_kapsam_sorgusu(user: User) -> Select:
    """Kullanıcının görebildiği servis işlerinin kimlikleri (alt sorgu)."""
    return kapsam.kapsam_isler(select(ServiceOrder.id), user, ServiceOrder.id).correlate(None)


async def is_getir(db: AsyncSession, user: User, so_id: int) -> ServiceOrder:
    """Kapsam içi servis işi; yoksa/silinmiş/kapsam dışıysa ParcaBulunamadi (404)."""
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise ParcaBulunamadi("Servis işi bulunamadı")
    return so


# --- Bakiye ve maliyet ---------------------------------------------------------------------


async def bakiye(db: AsyncSession, product_id: int, warehouse_id: int) -> int:
    """(Parça, depo) bakiyesi = Σqty. Çağıran ürünü kilitlediyse kesindir."""
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                StockMovement.product_id == product_id,
                StockMovement.warehouse_id == warehouse_id,
            )
        )
        or 0
    )


async def bakiyeler(
    db: AsyncSession, *, depo_idler: Sequence[int], product_idler: Sequence[int] | None = None
) -> dict[tuple[int, int], int]:
    """(ürün, depo) → adet; yalnız sıfırdan farklı bakiyeler."""
    if not depo_idler:
        return {}
    stmt = (
        select(StockMovement.product_id, StockMovement.warehouse_id, func.sum(StockMovement.qty))
        .where(StockMovement.warehouse_id.in_(list(depo_idler)))
        .group_by(StockMovement.product_id, StockMovement.warehouse_id)
    )
    if product_idler is not None:
        if not product_idler:
            return {}
        stmt = stmt.where(StockMovement.product_id.in_(list(product_idler)))
    return {(p, w): int(t) for p, w, t in (await db.execute(stmt)).all() if t}


async def net_cikis(db: AsyncSession, so_id: int, product_id: int) -> int:
    """İşe net çıkış = −Σqty (iş + parça). Ters kayıtlar `service_order_id`'yi
    kopyaladığı için kendiliğinden dahildir (E11-03)."""
    toplam = await db.scalar(
        select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
            StockMovement.service_order_id == so_id, StockMovement.product_id == product_id
        )
    )
    return -int(toplam or 0)


async def birim_maliyet(db: AsyncSession, product_id: int) -> Decimal | None:
    """Kümülatif ağırlıklı ortalama: Σ(adet × maliyet) / Σadet, yalnız maliyetli
    GIRIS/ACILIS satırları ve onların ters kayıtları (servis defteri). Hiç
    maliyetli giriş yoksa None — 0 yazılmaz (K8). E07 maliyeti bunu okur.
    """
    orj = aliased(StockMovement)
    satir = (
        await db.execute(
            select(
                func.sum(StockMovement.qty * StockMovement.unit_cost),
                func.sum(StockMovement.qty),
            )
            .select_from(StockMovement)
            .outerjoin(orj, orj.id == StockMovement.reversal_of_id)
            .where(
                StockMovement.product_id == product_id,
                StockMovement.unit_cost.is_not(None),
                or_(
                    StockMovement.hareket_turu.in_(MALIYETLI_GIRIS_TURLERI),
                    and_(
                        StockMovement.hareket_turu == "TERS_KAYIT",
                        orj.hareket_turu.in_(MALIYETLI_GIRIS_TURLERI),
                    ),
                ),
            )
        )
    ).one()
    tutar, adet = satir
    if not adet or adet <= 0 or tutar is None:
        return None
    return (Decimal(tutar) / Decimal(adet)).quantize(_MALIYET_HASSASIYETI, ROUND_HALF_UP)


# --- Tek yazıcı ----------------------------------------------------------------------------


async def _urunleri_kilitle(db: AsyncSession, idler: Iterable[int]) -> dict[int, Product]:
    """İsteğe giren bütün ürünler tek sorguda, kimliğe göre SIRALI kilitlenir."""
    sirali = sorted(set(idler))
    if not sirali:
        return {}
    urunler = (
        await db.scalars(
            select(Product)
            .where(Product.id.in_(sirali))
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    return {u.id: u for u in urunler}


def _parca_dogrula(urun: Product | None, tur: str, product_id: int) -> Product:
    if urun is None or urun.is_deleted:
        raise ParcaBulunamadi(f"Parça bulunamadı: {product_id}")
    if not urun.yedek_parca or urun.identity_kind != "YOK":
        raise ParcaHatasi(
            f"{urun.code} yedek parça kartı değil; servis deposunda yalnız serisiz yedek "
            "parça izlenir."
        )
    if not urun.is_active and tur not in PASIF_PARCADA_SERBEST:
        raise ParcaHatasi(f"{urun.code} pasif; yalnız iade ve ters kayıt yapılabilir.")
    return urun


def _depo_dogrula(depo: Warehouse | None, tur: str) -> Warehouse:
    if depo is None or not depo.servis_deposu:
        raise ParcaBulunamadi("Depo bulunamadı")
    if not depo.is_active and tur not in PASIF_DEPODA_SERBEST:
        raise ParcaHatasi(f"{depo.name} deposu pasif; yalnız iade ve ters kayıt yapılabilir.")
    return depo


def _adet_dogrula(adet: Any) -> int:
    if isinstance(adet, bool) or not isinstance(adet, int) or adet <= 0:
        raise ServisGirdiHatasi("Adet pozitif tam sayı olmalı")
    return adet


def _metin(deger: str | None, uzunluk: int, alan: str) -> str | None:
    deger = (deger or "").strip() or None
    if deger is not None and len(deger) > uzunluk:
        raise ServisGirdiHatasi(f"{alan} en çok {uzunluk} karakter olabilir")
    return deger


def _maliyet(deger: Any) -> Decimal | None:
    if deger is None:
        return None
    try:
        tutar = Decimal(str(deger))
    except (InvalidOperation, ValueError) as exc:
        raise ServisGirdiHatasi("Birim maliyet sayı olmalı") from exc
    if not tutar.is_finite() or tutar < 0:
        raise ServisGirdiHatasi("Birim maliyet negatif olamaz")
    return tutar.quantize(_MALIYET_HASSASIYETI, ROUND_HALF_UP)


def _hareket_ekle(db: AsyncSession, *, user: User | None, clock: Clock, **alanlar: Any):
    """Servis defterine satır ekleyen TEK yer (grep testi: `StockMovement(`
    yalnız `services/stock.py` ve bu dosyada)."""
    hareket = StockMovement(
        created_by=user.id if user is not None else None,
        created_at=clock.now(),
        **alanlar,
    )
    db.add(hareket)
    return hareket


async def hareket_yaz(
    db: AsyncSession,
    *,
    tur: str,
    satirlar: Sequence[Satir],
    user: User | None,
    clock: Clock,
    warehouse_id: int,
    service_order_id: int | None = None,
    document_no: str | None = None,
    notes: str | None = None,
    transfer_grup: uuid.UUID | None = None,
    stock_count_id: int | None = None,
    part_request_ids: dict[int, int] | None = None,
) -> list[StockMovement]:
    """TEK stok yazıcısı: ürünler id sıralı FOR UPDATE, tür→(neden, işaret),
    negatif bakiye engeli, `unit_cost` dondurma.

    Kapsam ve iş kuralları (kapalı iş, net çıkış) ÇAĞIRANDADIR; burada yalnız
    defterin kendi kuralları uygulanır. Commit yok (flush).
    """
    if tur not in SERVIS_HAREKET_YONU:
        raise ValueError(f"hareket_yaz bu türü yazmaz: {tur}")
    if not satirlar:
        raise ServisGirdiHatasi("En az bir satır girilmeli")
    neden, isaret = SERVIS_HAREKET_YONU[tur]
    urunler = await _urunleri_kilitle(db, (s.product_id for s in satirlar))
    depo = _depo_dogrula(await db.get(Warehouse, warehouse_id), tur)
    document_no = _metin(document_no, BELGE_UZUNLUGU, "Belge no")
    notes = _metin(notes, NOT_UZUNLUGU, "Not")
    yazilan: list[StockMovement] = []
    for s in satirlar:
        urun = _parca_dogrula(urunler.get(s.product_id), tur, s.product_id)
        adet = _adet_dogrula(s.adet)
        if s.unit_cost is not None and tur not in MALIYETLI_GIRIS_TURLERI:
            raise ServisGirdiHatasi("Birim maliyet yalnız giriş ve açılışta yazılır")
        if isaret < 0:
            mevcut = await bakiye(db, urun.id, depo.id)
            if mevcut < adet:
                raise ParcaHatasi(
                    f"Stok yetersiz: {depo.name} deposunda {urun.code} için {mevcut} adet var, "
                    f"{adet} istendi."
                )
        maliyet = (
            _maliyet(s.unit_cost)
            if tur in MALIYETLI_GIRIS_TURLERI
            else await birim_maliyet(db, urun.id)
        )
        hareket = _hareket_ekle(
            db,
            user=user,
            clock=clock,
            product_id=urun.id,
            warehouse_id=depo.id,
            qty=isaret * adet,
            reason=neden,
            hareket_turu=tur,
            service_order_id=service_order_id,
            document_no=document_no,
            notes=notes,
            transfer_grup=transfer_grup,
            stock_count_id=stock_count_id,
            part_request_id=(part_request_ids or {}).get(urun.id),
            unit_cost=maliyet,
        )
        # Her satırdan sonra flush: aynı istekte aynı parçanın ikinci satırı
        # bir önceki çıkışı görerek bakiye kontrolü yapsın.
        await db.flush()
        yazilan.append(hareket)
    return yazilan


# --- Servis işi: çıkış / iade / talep (TS-132, 133, 138) ------------------------------------


def _birlestir(satirlar: Sequence[Satir]) -> list[Satir]:
    """Aynı parçanın satırlarını toplar (sıra korunur)."""
    toplam: dict[int, int] = {}
    for s in satirlar:
        toplam[s.product_id] = toplam.get(s.product_id, 0) + _adet_dogrula(s.adet)
    return [Satir(pid, adet) for pid, adet in toplam.items()]


async def _isi_kilitle(db: AsyncSession, so: ServiceOrder) -> ServiceOrder:
    """İş satırı `FOR SHARE`: kapanış güncellemesi bu transaction bitene kadar
    bekler (E11-02). Güncel durum okunur (`populate_existing`)."""
    kilitli = await db.scalar(
        select(ServiceOrder)
        .where(ServiceOrder.id == so.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if kilitli is None:
        raise ParcaBulunamadi("Servis işi bulunamadı")
    return kilitli


def _kapali_mi(so: ServiceOrder) -> bool:
    return so.is_deleted or so.status in KAPALI_SERVIS_DURUMLARI


async def _acik_talepler(
    db: AsyncSession, so_id: int, product_idler: Iterable[int]
) -> dict[int, ServicePartRequest]:
    idler = sorted(set(product_idler))
    if not idler:
        return {}
    talepler = (
        await db.scalars(
            select(ServicePartRequest)
            .where(
                ServicePartRequest.service_order_id == so_id,
                ServicePartRequest.product_id.in_(idler),
                ServicePartRequest.durum == "ACIK",
                ServicePartRequest.is_deleted.is_(False),
            )
            .with_for_update()
        )
    ).all()
    return {t.product_id: t for t in talepler}


def _olay_ozeti(baslik: str, satirlar: Sequence[Satir], urunler: dict[int, Product]) -> str:
    parcalar = ", ".join(
        f"{urunler[s.product_id].code} × {s.adet}" for s in satirlar if s.product_id in urunler
    )
    return f"{baslik}: {parcalar}"


async def _parca_olayi(
    db: AsyncSession,
    so: ServiceOrder,
    baslik: str,
    tur: str,
    hareketler: Sequence[StockMovement],
    *,
    user: User | None,
    clock: Clock,
) -> None:
    """Birleşik iş geçmişine PARCA olayı (maliyet YOK: olay herkese görünür)."""
    urunler = {
        u.id: u
        for u in (
            await db.scalars(
                select(Product).where(Product.id.in_({h.product_id for h in hareketler}))
            )
        ).all()
    }
    satirlar = [Satir(h.product_id, abs(h.qty)) for h in hareketler]
    await gecmis.olay_yaz(
        db,
        so,
        "PARCA",
        _olay_ozeti(baslik, satirlar, urunler),
        user=user,
        clock=clock,
        veri={
            "alt_tur": tur,
            "depo_id": hareketler[0].warehouse_id if hareketler else None,
            "hareketler": [
                {"id": h.id, "product_id": h.product_id, "adet": h.qty} for h in hareketler
            ],
        },
    )


async def _talepleri_degerlendir(
    db: AsyncSession,
    so: ServiceOrder,
    talepler: Iterable[ServicePartRequest],
    *,
    user: User | None,
    clock: Clock,
) -> None:
    """Bağlı çıkışların neti talep adedine ulaşan talep KARSILANDI olur; bağlı
    MALZEME beklemesinde başka açık talep kalmadıysa bekleme biter."""
    from app.services.teknik_servis import bekletme

    biten_beklemeler: set[int] = set()
    for talep in talepler:
        if talep.durum != "ACIK":
            continue
        net = -int(
            await db.scalar(
                select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
                    StockMovement.part_request_id == talep.id
                )
            )
            or 0
        )
        if net < talep.adet:
            continue
        PARCA_TALEBI.dogrula(talep.durum, "KARSILANDI")
        talep.durum = "KARSILANDI"
        talep.karsilanma_at = clock.now()
        talep.updated_by = user.id if user is not None else None
        if talep.hold_id is not None:
            biten_beklemeler.add(talep.hold_id)
    await db.flush()
    for hold_id in biten_beklemeler:
        bekleme = await db.get(ServiceHold, hold_id)
        if bekleme is None or bekleme.released_at is not None or so.status != "BEKLEMEDE":
            continue
        baska_acik = await db.scalar(
            select(func.count()).where(
                ServicePartRequest.hold_id == hold_id,
                ServicePartRequest.durum == "ACIK",
                ServicePartRequest.is_deleted.is_(False),
            )
        )
        if baska_acik:
            continue
        # Sistem kapatır (user=None): beklemeyi açan izin (servis.yaz) çıkışı
        # yapan depo sorumlusunda olmayabilir; karşılanma olgusu kişiye bağlı değil.
        await bekletme.beklemeyi_bitir(
            db, so, user=None, clock=clock, not_="Talep edilen parça karşılandı"
        )


async def cikis_yap(
    db: AsyncSession,
    *,
    so: ServiceOrder,
    depo: Warehouse,
    satirlar: Sequence[Satir],
    user: User,
    clock: Clock,
    notes: str | None = None,
) -> list[StockMovement]:
    """Açık servis işine toplu parça çıkışı (tek transaction; bir satır hatalıysa
    hiçbiri yazılmaz). Kapalı işe 409 "Kapalı iş emrine parça yazılamaz."."""
    so = await _isi_kilitle(db, so)
    if _kapali_mi(so):
        raise ParcaHatasi("Kapalı iş emrine parça yazılamaz.")
    birim_uyumu_dogrula(depo, so.birim, ne="işine parça çıkışında")
    satirlar = _birlestir(satirlar)
    talepler = await _acik_talepler(db, so.id, (s.product_id for s in satirlar))
    hareketler = await hareket_yaz(
        db,
        tur="CIKIS_SERVIS",
        satirlar=satirlar,
        user=user,
        clock=clock,
        warehouse_id=depo.id,
        service_order_id=so.id,
        document_no=so.so_no,
        notes=notes,
        part_request_ids={pid: t.id for pid, t in talepler.items()},
    )
    await _parca_olayi(db, so, "Parça çıkışı", "CIKIS_SERVIS", hareketler, user=user, clock=clock)
    await _talepleri_degerlendir(db, so, talepler.values(), user=user, clock=clock)
    return hareketler


async def iade_al(
    db: AsyncSession,
    *,
    so: ServiceOrder,
    depo: Warehouse,
    satirlar: Sequence[Satir],
    user: User,
    clock: Clock,
    notes: str | None = None,
) -> list[StockMovement]:
    """İşten depoya iade; adet ≤ net çıkış (E11-03). Kapalı işte de serbest
    (yanlış çıkışın stoğa geri alınması)."""
    so = await _isi_kilitle(db, so)
    birim_uyumu_dogrula(depo, so.birim, ne="işinden iadede")
    satirlar = _birlestir(satirlar)
    await _urunleri_kilitle(db, (s.product_id for s in satirlar))
    for s in satirlar:
        net = await net_cikis(db, so.id, s.product_id)
        if s.adet > net:
            urun = await db.get(Product, s.product_id)
            kod = urun.code if urun is not None else str(s.product_id)
            raise ParcaHatasi(
                f"İade net çıkışı aşamaz: {kod} için bu işe net {net} adet çıktı, "
                f"{s.adet} iade istendi."
            )
    talepler = await _acik_talepler(db, so.id, (s.product_id for s in satirlar))
    hareketler = await hareket_yaz(
        db,
        tur="IADE_SERVIS",
        satirlar=satirlar,
        user=user,
        clock=clock,
        warehouse_id=depo.id,
        service_order_id=so.id,
        document_no=so.so_no,
        notes=notes,
        part_request_ids={pid: t.id for pid, t in talepler.items()},
    )
    await _parca_olayi(db, so, "Parça iadesi", "IADE_SERVIS", hareketler, user=user, clock=clock)
    return hareketler


async def talep_ac(
    db: AsyncSession,
    *,
    so: ServiceOrder,
    product_id: int,
    adet: int,
    user: User,
    clock: Clock,
    notes: str | None = None,
    isi_beklet: bool = False,
) -> ServicePartRequest:
    """Açık işe parça talebi (E11-19). `isi_beklet` → MALZEME beklemesi (iş
    zaten MALZEME'de bekliyorsa ona bağlanır). İş + parça başına tek açık talep."""
    from app.services.teknik_servis import bekletme

    so = await _isi_kilitle(db, so)
    if _kapali_mi(so):
        raise ParcaHatasi("Kapalı iş emrine parça talebi açılamaz.")
    adet = _adet_dogrula(adet)
    notes = _metin(notes, 500, "Not")
    urun = _parca_dogrula(await db.get(Product, product_id), "TALEP", product_id)
    if not urun.is_active:
        raise ParcaHatasi(f"{urun.code} pasif; talep açılamaz.")
    if await _acik_talepler(db, so.id, [urun.id]):
        raise ParcaHatasi(f"Bu işte {urun.code} için zaten açık bir talep var.")
    hold_id: int | None = None
    if isi_beklet:
        aktif = await bekletme.aktif_bekleme(db, so)
        if aktif is not None:
            if aktif.neden != "MALZEME":
                raise ParcaHatasi("İş başka bir nedenle bekliyor; malzeme beklemesi açılamaz.")
            hold_id = aktif.id
        else:
            bekleme = await bekletme.beklet(
                db,
                so,
                "MALZEME",
                user=user,
                clock=clock,
                aciklama=f"Parça talebi: {urun.code} × {adet}",
            )
            hold_id = bekleme.id
    talep = ServicePartRequest(
        service_order_id=so.id,
        product_id=urun.id,
        adet=adet,
        durum="ACIK",
        notes=notes,
        hold_id=hold_id,
        created_by=user.id,
        created_at=clock.now(),
    )
    db.add(talep)
    await db.flush()
    await gecmis.olay_yaz(
        db,
        so,
        "PARCA",
        f"Parça talebi: {urun.code} × {adet}",
        user=user,
        clock=clock,
        veri={"alt_tur": "TALEP", "talep_id": talep.id, "product_id": urun.id, "adet": adet},
    )
    return talep


async def talep_iptal(
    db: AsyncSession, talep: ServicePartRequest, *, neden: str, user: User, clock: Clock
) -> ServicePartRequest:
    neden_ = _metin(neden, 200, "İptal nedeni")
    if neden_ is None:
        raise ServisGirdiHatasi("İptal nedeni zorunlu")
    if talep.durum != "ACIK":
        raise ParcaHatasi("Yalnız açık talep iptal edilir.")
    PARCA_TALEBI.dogrula(talep.durum, "IPTAL")
    talep.durum = "IPTAL"
    talep.iptal_nedeni = neden_
    talep.updated_by = user.id
    await db.flush()
    return talep


async def talepleri_kapat(
    db: AsyncSession, so: ServiceOrder, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: iş kapanınca (TAMAMLANDI/KAPATILDI/IPTAL) açık
    parça talepleri IPTAL olur — kapalı işe çıkış yasak olduğundan talep
    karşılanamaz ve "parça geldi" uyarısı boşa çalardı."""
    if hedef not in KAPALI_SERVIS_DURUMLARI:
        return
    talepler = (
        await db.scalars(
            select(ServicePartRequest).where(
                ServicePartRequest.service_order_id == so.id,
                ServicePartRequest.durum == "ACIK",
                ServicePartRequest.is_deleted.is_(False),
            )
        )
    ).all()
    for talep in talepler:
        PARCA_TALEBI.dogrula(talep.durum, "IPTAL")
        talep.durum = "IPTAL"
        talep.iptal_nedeni = f"İş kapandı ({hedef})"
    if talepler:
        await db.flush()


# --- Ters kayıt (TS-132) --------------------------------------------------------------------


async def ters_kayit(
    db: AsyncSession, *, hareket: StockMovement, gerekce: str, user: User, clock: Clock
) -> list[StockMovement]:
    """Tek seferlik ters kayıt (E11-06). Transfer bacağında grubun aynı parçalı
    iki bacağı birlikte ters çevrilir. Orijinalin nedeni, ters işareti, işi,
    maliyeti, talebi ve transfer grubu kopyalanır."""
    gerekce_ = _metin(gerekce, NOT_UZUNLUGU, "Gerekçe")
    if gerekce_ is None:
        raise ServisGirdiHatasi("Ters kayıt gerekçesi zorunlu")
    tur = hareket.hareket_turu
    if tur is None:
        raise ParcaBulunamadi("Hareket bulunamadı")
    if tur == "TERS_KAYIT":
        raise ParcaHatasi("Ters kaydın ters kaydı yapılamaz.")
    if tur in ("SAYIM_FAZLASI", "SAYIM_EKSIGI"):
        raise ParcaHatasi("Sayım farkı ters kayıtla düzeltilmez; yeni sayım yapın.")
    bacaklar = [hareket]
    if tur in ("TRANSFER_CIKIS", "TRANSFER_GIRIS"):
        bacaklar = list(
            (
                await db.scalars(
                    select(StockMovement)
                    .where(
                        StockMovement.transfer_grup == hareket.transfer_grup,
                        StockMovement.product_id == hareket.product_id,
                        StockMovement.hareket_turu.in_(("TRANSFER_CIKIS", "TRANSFER_GIRIS")),
                    )
                    .order_by(StockMovement.id)
                )
            ).all()
        )
    urunler = await _urunleri_kilitle(db, [hareket.product_id])
    urun = urunler[hareket.product_id]
    zaten = await db.scalar(
        select(func.count()).where(StockMovement.reversal_of_id.in_([b.id for b in bacaklar]))
    )
    if zaten:
        raise ParcaHatasi("Bu hareketin ters kaydı zaten yapılmış.")
    so: ServiceOrder | None = None
    if hareket.service_order_id is not None:
        so = await _isi_kilitle(db, await db.get(ServiceOrder, hareket.service_order_id))
        if tur == "IADE_SERVIS" and _kapali_mi(so):
            raise ParcaHatasi(
                "Kapalı işteki iadenin ters kaydı yeni bir çıkıştır; kapalı iş emrine parça "
                "yazılamaz."
            )
        if tur == "CIKIS_SERVIS":
            net = await net_cikis(db, so.id, hareket.product_id)
            if net < -hareket.qty:
                raise ParcaHatasi(
                    f"Ters kayıt net çıkışı eksiye düşürür: {urun.code} için bu işte net {net} "
                    "adet var; önce iadenin ters kaydını yapın."
                )
    # Önce stoğu ARTIRAN ters kayıt (orijinali eksi olan bacak), sonra azaltan.
    yazilan: list[StockMovement] = []
    for bacak in sorted(bacaklar, key=lambda b: b.qty):
        if bacak.qty > 0:
            mevcut = await bakiye(db, bacak.product_id, bacak.warehouse_id)
            if mevcut < bacak.qty:
                depo = await db.get(Warehouse, bacak.warehouse_id)
                raise ParcaHatasi(
                    f"Stok yetersiz: {depo.name if depo else 'depo'} deposunda {urun.code} için "
                    f"{mevcut} adet var, ters kayıt {bacak.qty} adet düşecek."
                )
        ters = _hareket_ekle(
            db,
            user=user,
            clock=clock,
            product_id=bacak.product_id,
            warehouse_id=bacak.warehouse_id,
            qty=-bacak.qty,
            reason=bacak.reason,
            hareket_turu="TERS_KAYIT",
            reversal_of_id=bacak.id,
            service_order_id=bacak.service_order_id,
            document_no=bacak.document_no,
            notes=gerekce_,
            transfer_grup=bacak.transfer_grup,
            part_request_id=bacak.part_request_id,
            unit_cost=bacak.unit_cost,
        )
        await db.flush()
        yazilan.append(ters)
    if so is not None:
        await _parca_olayi(
            db, so, "Parça ters kaydı", "TERS_KAYIT", yazilan, user=user, clock=clock
        )
    return yazilan


# --- Transfer (TS-137) ----------------------------------------------------------------------


async def transfer_yap(
    db: AsyncSession,
    *,
    kaynak: Warehouse,
    hedef: Warehouse,
    satirlar: Sequence[Satir],
    user: User,
    clock: Clock,
    notes: str | None = None,
) -> tuple[uuid.UUID, list[StockMovement]]:
    """Her parça için TRANSFER_CIKIS (kaynak, −) + TRANSFER_GIRIS (hedef, +),
    aynı `transfer_grup`; grup toplamı 0. Yetersiz stok / aynı depo / pasif
    depo → 409, hiçbir satır yazılmaz."""
    if kaynak.id == hedef.id:
        raise ParcaHatasi("Kaynak ve hedef depo aynı olamaz.")
    if kaynak.birim != hedef.birim:
        raise ParcaHatasi(
            f"Birimler arası transfer yapılamaz: '{kaynak.name}' {birim_adi(kaynak.birim)}, "
            f"'{hedef.name}' {birim_adi(hedef.birim)} deposu. Depolar birimlere ayrıdır."
        )
    satirlar = _birlestir(satirlar)
    grup = uuid.uuid4()
    cikislar = await hareket_yaz(
        db,
        tur="TRANSFER_CIKIS",
        satirlar=satirlar,
        user=user,
        clock=clock,
        warehouse_id=kaynak.id,
        transfer_grup=grup,
        notes=notes,
    )
    girisler = await hareket_yaz(
        db,
        tur="TRANSFER_GIRIS",
        satirlar=satirlar,
        user=user,
        clock=clock,
        warehouse_id=hedef.id,
        transfer_grup=grup,
        notes=notes,
    )
    return grup, cikislar + girisler


# --- Açılış stoğu (TS-134) --------------------------------------------------------------------


@dataclass
class AcilisSatiri:
    satir_no: int
    product_id: int | None
    depo_id: int | None
    adet: int
    unit_cost: Decimal | None = None
    notes: str | None = None
    hatalar: list[str] = field(default_factory=list)


async def acilis_yukle(
    db: AsyncSession, satirlar: Sequence[AcilisSatiri], *, user: User, clock: Clock
) -> list[StockMovement]:
    """Hepsi-ya-hiç açılış: tek hatalı satırda HİÇBİR hareket yazılmaz ve hatalı
    satır numaraları döner (409). Kullanıcının depo kapsamı denetlenir; (parça,
    depo) için önceden HERHANGİ bir hareket varsa satır reddedilir (açılış
    ancak ilk kayıttır; tekillik ayrıca `uq_stok_hareket_acilis`)."""
    if not satirlar:
        raise ServisGirdiHatasi("Açılış dosyası boş")
    depolar = set(await erisilebilir_depolar(db, user))
    await _urunleri_kilitle(db, (s.product_id for s in satirlar if s.product_id))
    gorulen: dict[tuple[int, int], int] = {}
    for s in satirlar:
        if s.depo_id is None or s.depo_id not in depolar:
            s.hatalar.append("Depo bulunamadı ya da yetkiniz dışında")
        else:
            depo = await db.get(Warehouse, s.depo_id)
            if depo is None or not depo.is_active:
                s.hatalar.append("Depo pasif")
        urun = await db.get(Product, s.product_id) if s.product_id else None
        if urun is None or urun.is_deleted:
            s.hatalar.append("Parça bulunamadı")
        elif not urun.yedek_parca or urun.identity_kind != "YOK" or not urun.is_active:
            s.hatalar.append(f"{urun.code} aktif bir serisiz yedek parça kartı değil")
        if isinstance(s.adet, bool) or not isinstance(s.adet, int) or s.adet <= 0:
            s.hatalar.append("Adet pozitif tam sayı olmalı")
        if s.product_id and s.depo_id:
            anahtar = (s.product_id, s.depo_id)
            if anahtar in gorulen:
                s.hatalar.append(f"Aynı parça ve depo {gorulen[anahtar]}. satırda da var")
            else:
                gorulen[anahtar] = s.satir_no
                onceki = await db.scalar(
                    select(func.count()).where(
                        StockMovement.product_id == s.product_id,
                        StockMovement.warehouse_id == s.depo_id,
                    )
                )
                if onceki:
                    s.hatalar.append("Bu parça ve depo için önceden hareket var; açılış yapılamaz")
        try:
            s.unit_cost = _maliyet(s.unit_cost)
        except ServisGirdiHatasi as exc:
            s.hatalar.append(str(exc))
        if s.notes is not None and len(s.notes) > NOT_UZUNLUGU:
            s.hatalar.append(f"Not en çok {NOT_UZUNLUGU} karakter olabilir")
    hatali = [s for s in satirlar if s.hatalar]
    if hatali:
        raise ParcaHatasi(
            "Hatalı satırlar düzeltilmeden açılış yüklenmez: satır "
            + ", ".join(str(s.satir_no) for s in hatali),
            {"hatalar": [{"satir_no": s.satir_no, "hatalar": s.hatalar} for s in hatali]},
        )
    yazilan: list[StockMovement] = []
    for s in satirlar:
        yazilan += await hareket_yaz(
            db,
            tur="ACILIS",
            satirlar=[Satir(int(s.product_id or 0), s.adet, s.unit_cost)],
            user=user,
            clock=clock,
            warehouse_id=s.depo_id,
            document_no="ACILIS",
            notes=s.notes,
        )
    return yazilan


# --- Sayım (TS-137) ----------------------------------------------------------------------------


async def _sayim_no(db: AsyncSession, clock: Clock) -> str:
    """`SAY-YYYYAA-NNNNNN` (`stock_count_no_seq`; numara.py biçimiyle aynı)."""
    sira = await db.scalar(text("SELECT nextval('stock_count_no_seq')"))
    return f"SAY-{yerel_bugun(clock):%Y%m}-{int(sira):06d}"


async def sayim_ac(
    db: AsyncSession, *, depo: Warehouse, user: User, clock: Clock, notes: str | None = None
) -> StockCount:
    """Açılış anı görüntüsü: depoda hareketi olan her parça `sistem_adet` ile
    satır olur. Depo başına tek açık sayım."""
    if not depo.is_active:
        raise ParcaHatasi(f"{depo.name} deposu pasif; sayım açılamaz.")
    acik = await db.scalar(
        select(StockCount.id).where(
            StockCount.warehouse_id == depo.id,
            StockCount.durum == "ACIK",
            StockCount.is_deleted.is_(False),
        )
    )
    if acik is not None:
        raise ParcaHatasi("Bu depoda zaten açık bir sayım var.")
    sayim = StockCount(
        count_no=await _sayim_no(db, clock),
        warehouse_id=depo.id,
        durum="ACIK",
        baslangic_at=clock.now(),
        notes=_metin(notes, 2000, "Not"),
        created_by=user.id,
        created_at=clock.now(),
    )
    db.add(sayim)
    await db.flush()
    goruntu = await bakiyeler(db, depo_idler=[depo.id])
    urun_idler = set(
        (
            await db.scalars(
                select(StockMovement.product_id)
                .where(StockMovement.warehouse_id == depo.id)
                .distinct()
            )
        ).all()
    )
    for pid in sorted(urun_idler):
        db.add(
            StockCountLine(
                stock_count_id=sayim.id, product_id=pid, sistem_adet=goruntu.get((pid, depo.id), 0)
            )
        )
    await db.flush()
    return sayim


async def sayim_satirlari_yaz(
    db: AsyncSession, sayim: StockCount, satirlar: Sequence[tuple[int, int | None]]
) -> None:
    """Sayılan adetleri yazar; görüntüde olmayan parça eklenirse sistem adedi o
    anki bakiyedir. Onaysız sayım hiçbir bakiyeyi DEĞİŞTİRMEZ."""
    if sayim.durum != "ACIK":
        raise ParcaHatasi("Yalnız açık sayımın satırları yazılır.")
    mevcut = {
        s.product_id: s
        for s in (
            await db.scalars(
                select(StockCountLine).where(StockCountLine.stock_count_id == sayim.id)
            )
        ).all()
    }
    for pid, sayilan in satirlar:
        if sayilan is not None and (isinstance(sayilan, bool) or sayilan < 0):
            raise ServisGirdiHatasi("Sayılan adet negatif olamaz")
        satir = mevcut.get(pid)
        if satir is None:
            urun = await db.get(Product, pid)
            _parca_dogrula(urun, "SAYIM_FAZLASI", pid)
            satir = StockCountLine(
                stock_count_id=sayim.id,
                product_id=pid,
                sistem_adet=await bakiye(db, pid, sayim.warehouse_id),
            )
            db.add(satir)
            mevcut[pid] = satir
        satir.sayilan_adet = sayilan
    await db.flush()


async def sayim_onayla(
    db: AsyncSession,
    sayim: StockCount,
    *,
    gerekce: str,
    degisimi_kabul: bool,
    user: User,
    clock: Clock,
) -> list[StockMovement]:
    """Onay anında güncel bakiye okunur (`onay_anindaki_adet`). Görüntüden
    sapma varsa ve `degisimi_kabul` yoksa 409 + sapan satırlar; kabul edilirse
    fark GÜNCEL bakiyeye göre hesaplanır ve SAYIM_FAZLASI/EKSIGI yazılır."""
    gerekce_ = _metin(gerekce, 500, "Gerekçe")
    if gerekce_ is None:
        raise ServisGirdiHatasi("Sayım onay gerekçesi zorunlu")
    STOK_SAYIM.dogrula(sayim.durum, "ONAYLANDI")
    satirlar = (
        await db.scalars(
            select(StockCountLine)
            .where(StockCountLine.stock_count_id == sayim.id)
            .order_by(StockCountLine.product_id)
        )
    ).all()
    sayilanlar = [s for s in satirlar if s.sayilan_adet is not None]
    if not sayilanlar:
        raise ParcaHatasi("Sayılan adet girilmemiş; onaylanacak satır yok.")
    await _urunleri_kilitle(db, (s.product_id for s in sayilanlar))
    sapmalar: list[dict[str, Any]] = []
    for s in sayilanlar:
        s.onay_anindaki_adet = await bakiye(db, s.product_id, sayim.warehouse_id)
        if s.onay_anindaki_adet != s.sistem_adet:
            sapmalar.append(
                {
                    "product_id": s.product_id,
                    "sistem_adet": s.sistem_adet,
                    "onay_anindaki_adet": s.onay_anindaki_adet,
                }
            )
    if sapmalar and not degisimi_kabul:
        raise ParcaHatasi(
            "Sayım açıldıktan sonra stok değişti; farkı güncel bakiyeye göre almak için "
            "değişimi kabul ederek yeniden onaylayın.",
            {"sapmalar": sapmalar},
        )
    yazilan: list[StockMovement] = []
    for s in sayilanlar:
        fark = s.sayilan_adet - s.onay_anindaki_adet
        if fark == 0:
            continue
        yazilan += await hareket_yaz(
            db,
            tur="SAYIM_FAZLASI" if fark > 0 else "SAYIM_EKSIGI",
            satirlar=[Satir(s.product_id, abs(fark))],
            user=user,
            clock=clock,
            warehouse_id=sayim.warehouse_id,
            stock_count_id=sayim.id,
            document_no=sayim.count_no,
            notes=gerekce_[:NOT_UZUNLUGU],
        )
    sayim.durum = "ONAYLANDI"
    sayim.onaylayan_id = user.id
    sayim.onay_at = clock.now()
    sayim.gerekce = gerekce_
    sayim.updated_by = user.id
    await db.flush()
    return yazilan


async def sayim_iptal(db: AsyncSession, sayim: StockCount, *, gerekce: str, user: User) -> None:
    gerekce_ = _metin(gerekce, 500, "Gerekçe")
    if gerekce_ is None:
        raise ServisGirdiHatasi("İptal gerekçesi zorunlu")
    STOK_SAYIM.dogrula(sayim.durum, "IPTAL")
    sayim.durum = "IPTAL"
    sayim.gerekce = gerekce_
    sayim.updated_by = user.id
    await db.flush()


# --- Stok listesi / KPI / uyarı (TS-135, 136) — tek sorgu ---------------------------------


@dataclass(frozen=True)
class StokSuzgeci:
    q: str | None = None
    depo_id: int | None = None
    durum: str | None = None
    # Yalnız asgari stoku tanımlı parçalar (uyarı listesi).
    esikli: bool = False
    pasifler: bool = False


def stok_sorgusu(user: User, s: StokSuzgeci) -> Select:
    """(Product, toplam, durum) — ekran, Excel, KPI ve uyarı AYNI sorgu.

    Toplam yalnız kullanıcının erişebildiği servis depolarından (ve verilmişse
    tek depodan) alınır: başka birimin deposundaki adet sayıya girmez.
    """
    from app.services.normalize import tr_normkey

    alt = select(
        StockMovement.product_id.label("pid"),
        func.sum(StockMovement.qty).label("toplam"),
    ).where(StockMovement.warehouse_id.in_(erisilebilir_depo_sorgusu(user)))
    if s.depo_id is not None:
        alt = alt.where(StockMovement.warehouse_id == s.depo_id)
    alt = alt.group_by(StockMovement.product_id).subquery()
    toplam = func.coalesce(alt.c.toplam, 0)
    durum = durum_ifadesi(toplam, Product.min_stok)
    stmt = (
        select(Product, toplam.label("toplam"), durum.label("durum"))
        .outerjoin(alt, alt.c.pid == Product.id)
        .where(Product.yedek_parca.is_(True), Product.is_deleted.is_(False))
        .order_by(Product.code)
    )
    if not s.pasifler:
        stmt = stmt.where(Product.is_active.is_(True))
    if s.durum:
        if s.durum not in STOK_DURUMLARI:
            raise ServisGirdiHatasi(f"Durum {', '.join(STOK_DURUMLARI)} içinden olmalı")
        stmt = stmt.where(durum == s.durum)
    if s.esikli:
        stmt = stmt.where(Product.min_stok > 0)
    if s.q:
        anahtar = tr_normkey(s.q)
        desen = f"%{s.q.strip()}%"
        stmt = stmt.where(
            Product.name_key.contains(anahtar)
            | Product.code.ilike(desen)
            | Product.brand.ilike(desen)
            | Product.model.ilike(desen)
            | Product.supplier_code.ilike(desen)
        )
    return stmt


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


def talep_sorgusu(user: User) -> Select:
    """Kapsam içi işlerin parça talepleri (liste ve KPI aynı sorgu)."""
    return kapsam.kapsam_isler(
        select(ServicePartRequest).where(ServicePartRequest.is_deleted.is_(False)),
        user,
        ServicePartRequest.service_order_id,
    )


def sayim_sorgusu(user: User) -> Select:
    return select(StockCount).where(
        StockCount.is_deleted.is_(False),
        StockCount.warehouse_id.in_(erisilebilir_depo_sorgusu(user)),
    )


def hareket_kapsami(user: User) -> ColumnElement[bool]:
    """Servis defteri satırı görünür mü: depo erişilebilir VE (işe bağlı değil
    ya da iş kapsam içi). Başka birimin işine ait hareket listelenmez."""
    return and_(
        StockMovement.hareket_turu.is_not(None),
        StockMovement.warehouse_id.in_(erisilebilir_depo_sorgusu(user)),
        or_(
            StockMovement.service_order_id.is_(None),
            StockMovement.service_order_id.in_(is_kapsam_sorgusu(user)),
        ),
    )


@dataclass(frozen=True)
class HareketSuzgeci:
    product_id: int | None = None
    depo_id: int | None = None
    tur: str | None = None
    so_no: str | None = None
    belge: str | None = None
    bas: date | None = None
    bit: date | None = None


def hareket_sorgusu(user: User, s: HareketSuzgeci) -> Select:
    """(StockMovement, Product, Warehouse, so_no, ters_var) — liste ve Excel."""
    ters = aliased(StockMovement)
    ters_var = exists().where(ters.reversal_of_id == StockMovement.id)
    stmt = (
        select(
            StockMovement,
            Product,
            Warehouse,
            ServiceOrder.so_no,
            ters_var.label("ters_var"),
        )
        .join(Product, Product.id == StockMovement.product_id)
        .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
        .outerjoin(ServiceOrder, ServiceOrder.id == StockMovement.service_order_id)
        .where(hareket_kapsami(user))
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
    )
    if s.product_id is not None:
        stmt = stmt.where(StockMovement.product_id == s.product_id)
    if s.depo_id is not None:
        stmt = stmt.where(StockMovement.warehouse_id == s.depo_id)
    if s.tur:
        if s.tur not in SERVIS_HAREKET_TURLERI:
            raise ServisGirdiHatasi("Bilinmeyen hareket türü")
        stmt = stmt.where(StockMovement.hareket_turu == s.tur)
    if s.so_no:
        stmt = stmt.where(ServiceOrder.so_no.ilike(f"%{s.so_no.strip()}%"))
    if s.belge:
        stmt = stmt.where(StockMovement.document_no.ilike(f"%{s.belge.strip()}%"))
    if s.bas is not None and s.bit is not None and s.bit < s.bas:
        raise ServisGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if s.bas is not None:
        stmt = stmt.where(StockMovement.created_at >= yerel_gun_araligi(s.bas)[0])
    if s.bit is not None:
        stmt = stmt.where(StockMovement.created_at < yerel_gun_araligi(s.bit)[1])
    return stmt


async def ozet(db: AsyncSession, user: User, clock: Clock) -> dict[str, int]:
    """Yedek Parça KPI kutuları; her sayı tıklanınca açılan listenin toplamıdır."""
    bugun = yerel_bugun(clock)
    return {
        "az_stok": await say(db, stok_sorgusu(user, StokSuzgeci(durum="AZ"))),
        "stok_yok": await say(db, stok_sorgusu(user, StokSuzgeci(durum="YOK"))),
        "acik_talep": await say(db, talep_sorgusu(user).where(ServicePartRequest.durum == "ACIK")),
        "acik_sayim": await say(db, sayim_sorgusu(user).where(StockCount.durum == "ACIK")),
        "bugun_cikis": await say(
            db, hareket_sorgusu(user, HareketSuzgeci(tur="CIKIS_SERVIS", bas=bugun, bit=bugun))
        ),
    }


async def az_stok_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """`parca.yonet` sahibine (E11-08); depo kapsamlı, ekrandaki filtreyle aynı
    sorgu. Saklanmaz: eşik üstüne çıkınca kaybolur, yeniden düşünce döner."""
    az = await say(db, stok_sorgusu(user, StokSuzgeci(durum="AZ")))
    yok = await say(db, stok_sorgusu(user, StokSuzgeci(durum="YOK", esikli=True)))
    return [
        Uyari(
            kod="parca.az_stok",
            baslik="Asgari stok altındaki yedek parça",
            adet=az,
            yol="/yedek-parca?durum=AZ",
            onem="uyari",
        ),
        Uyari(
            kod="parca.stok_yok",
            baslik="Asgari stoku tanımlı ama stokta olmayan yedek parça",
            adet=yok,
            yol="/yedek-parca?durum=YOK&esikli=1",
            onem="uyari",
        ),
    ]


async def parca_geldi_uyarisi(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Kullanıcının kendi AÇIK talepleri içinde erişebildiği depolarda bakiyesi
    talep adedini karşılayanlar ("Talep ettiğiniz parça stokta")."""
    talepler = (
        await db.scalars(
            talep_sorgusu(user).where(
                ServicePartRequest.durum == "ACIK", ServicePartRequest.created_by == user.id
            )
        )
    ).all()
    if not talepler:
        return []
    depolar = await erisilebilir_depolar(db, user)
    stok = await bakiyeler(db, depo_idler=depolar, product_idler=[t.product_id for t in talepler])
    toplam: dict[int, int] = {}
    for (pid, _w), adet in stok.items():
        toplam[pid] = toplam.get(pid, 0) + adet
    adet = sum(1 for t in talepler if toplam.get(t.product_id, 0) >= t.adet)
    return [
        Uyari(
            kod="parca.geldi",
            baslik="Talep ettiğiniz parça stokta",
            adet=adet,
            yol="/yedek-parca?sekme=talepler",
            onem="bilgi",
        )
    ]


# --- Parça tüketim raporu (TS-196, E11-18) -------------------------------------------------
#
# Net çıkış = −Σqty WHERE service_order_id IS NOT NULL (çıkış eksi, iade artı;
# ters kayıtlar `service_order_id`'yi kopyaladığı için kendiliğinden girer).
# Tutar = −Σ(qty × unit_cost) — `unit_cost` hareket anında dondurulmuştur
# (KD-25); maliyeti NULL satır varsa grubun tutarı None ve "maliyet eksik"
# (E07 `MALIYET_EKSIK` anlamı; 0 yazılmaz). E07 iş malzeme maliyeti ile bu
# raporun tutarı AYNI fonksiyondan (`malzeme_maliyeti_toplu`) gelir.
# Tutar yalnız `maliyet_gorur` iken yanıtta ANAHTAR olarak bulunur.

TUKETIM_KIRILIMLARI = ("parca_ay", "birim", "musteri", "is_turu", "is", "ekipman")
IS_GRUPLARI = ("PLANLI_BAKIM", "SERVIS")
IS_GRUBU_ADLARI = {"PLANLI_BAKIM": "Planlı bakım (PB)", "SERVIS": "Diğer servis işleri"}
TUKETIM_VARSAYILAN_GUN = 30
TUKETIM_AZAMI_GUN = 731


@dataclass(frozen=True)
class TuketimSuzgeci:
    bas: date | None = None
    bit: date | None = None
    birim: str | None = None
    musteri_id: int | None = None
    is_grubu: str | None = None
    product_id: int | None = None
    depo_id: int | None = None
    ekipman_id: int | None = None
    so_id: int | None = None


def tuketim_donemi(s: TuketimSuzgeci, clock: Clock) -> tuple[date, date]:
    """Varsayılan son 31 gün; bitiş < başlangıç ya da 24 aydan uzun dönem 400."""
    bit = s.bit or yerel_bugun(clock)
    bas = s.bas or bit - timedelta(days=TUKETIM_VARSAYILAN_GUN)
    if bit < bas:
        raise ServisGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if (bit - bas).days > TUKETIM_AZAMI_GUN:
        raise ServisGirdiHatasi("Rapor dönemi en çok 24 ay olabilir")
    return bas, bit


def is_grubu_ifadesi() -> ColumnElement[str]:
    return case((ServiceOrder.tur == "PB", "PLANLI_BAKIM"), else_="SERVIS")


def tuketim_sorgusu(user: User, s: TuketimSuzgeci, clock: Clock) -> Select:
    """Servis işine yazılmış defter satırları (kapsamlı): rapor ve "aynı filtreli
    hareket defteri" karşılaştırmasının TEK sorgusu. `StockMovement` + iş
    alanları seçer."""
    from app.models.rbac import BIRIM_KODLARI

    bas, bit = tuketim_donemi(s, clock)
    stmt = (
        select(StockMovement)
        .join(ServiceOrder, ServiceOrder.id == StockMovement.service_order_id)
        .where(
            StockMovement.service_order_id.is_not(None),
            hareket_kapsami(user),
            StockMovement.created_at >= yerel_gun_araligi(bas)[0],
            StockMovement.created_at < yerel_gun_araligi(bit)[1],
        )
    )
    if s.birim:
        if s.birim not in BIRIM_KODLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen birim: {s.birim}")
        stmt = stmt.where(ServiceOrder.birim == s.birim)
    if s.musteri_id is not None:
        stmt = stmt.where(ServiceOrder.customer_id == s.musteri_id)
    if s.is_grubu:
        if s.is_grubu not in IS_GRUPLARI:
            raise ServisGirdiHatasi(f"İş grubu {', '.join(IS_GRUPLARI)} içinden olmalı")
        stmt = stmt.where(is_grubu_ifadesi() == s.is_grubu)
    if s.product_id is not None:
        stmt = stmt.where(StockMovement.product_id == s.product_id)
    if s.depo_id is not None:
        stmt = stmt.where(StockMovement.warehouse_id == s.depo_id)
    if s.ekipman_id is not None:
        # Parça yalnız TEK ekipmanlı işte (işin `equipment_id`'si) ekipmana
        # atfedilir; çok ekipmanlı iş hiçbir ekipmana otomatik bağlanmaz.
        stmt = stmt.where(ServiceOrder.equipment_id == s.ekipman_id)
    if s.so_id is not None:
        stmt = stmt.where(ServiceOrder.id == s.so_id)
    return stmt


def _tutar_ifadeleri():
    tutar = func.sum(-StockMovement.qty * StockMovement.unit_cost)
    eksik = func.count().filter(StockMovement.unit_cost.is_(None))
    return tutar, eksik


async def malzeme_maliyeti_toplu(
    db: AsyncSession, so_idler: Sequence[int]
) -> dict[int, tuple[Decimal | None, str]]:
    """İş → (malzeme tutarı, durum) — E07 iş finansı ve E11-18 raporunun TEK
    hesabı. Durum: `TAM` | `YOK` (hareket yok, tutar 0) | `MALIYET_EKSIK`
    (maliyeti bilinmeyen satır var, tutar None)."""
    idler = sorted({int(i) for i in so_idler})
    if not idler:
        return {}
    tutar, eksik = _tutar_ifadeleri()
    satirlar = (
        await db.execute(
            select(StockMovement.service_order_id, tutar, eksik)
            .where(StockMovement.service_order_id.in_(idler))
            .group_by(StockMovement.service_order_id)
        )
    ).all()
    sonuc: dict[int, tuple[Decimal | None, str]] = {i: (Decimal("0.00"), "YOK") for i in idler}
    for so_id, t, e in satirlar:
        if e:
            sonuc[so_id] = (None, "MALIYET_EKSIK")
        else:
            sonuc[so_id] = (
                Decimal(str(t or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP),
                "TAM",
            )
    return sonuc


def _kirilim_sutunlari(kirilim: str) -> list[Any]:
    ay = func.to_char(func.timezone("Europe/Istanbul", StockMovement.created_at), "YYYY-MM")
    grup = is_grubu_ifadesi().label("is_grubu")
    if kirilim == "parca_ay":
        return [StockMovement.product_id.label("product_id"), ay.label("ay"), grup]
    if kirilim == "birim":
        return [ServiceOrder.birim.label("birim"), grup]
    if kirilim == "musteri":
        return [ServiceOrder.customer_id.label("musteri_id"), grup]
    if kirilim == "is_turu":
        return [ServiceOrder.tur.label("is_turu"), grup]
    if kirilim == "is":
        return [
            ServiceOrder.id.label("so_id"),
            StockMovement.product_id.label("product_id"),
            grup,
        ]
    if kirilim == "ekipman":
        return [
            ServiceOrder.equipment_id.label("ekipman_id"),
            StockMovement.product_id.label("product_id"),
            grup,
        ]
    raise ServisGirdiHatasi(f"Kırılım {', '.join(TUKETIM_KIRILIMLARI)} içinden olmalı")


async def parca_tuketimi(
    db: AsyncSession,
    user: User,
    s: TuketimSuzgeci,
    clock: Clock,
    *,
    kirilim: str = "parca_ay",
    maliyet_gorur: bool = False,
) -> dict[str, Any]:
    """Parça tüketim raporu (SQL'de toplanır). PB ve diğer servis işleri her
    kırılımda ayrı satırdır (`is_grubu`)."""
    from app.models import Account, ServiceEquipment

    bas, bit = tuketim_donemi(s, clock)
    sutunlar = _kirilim_sutunlari(kirilim)
    # Kırılım aynı JOIN'li sorgunun kendisinde gruplanır (kapsam ve süzgeç tek
    # kaynakta: `tuketim_sorgusu`). GROUP BY sıra numarasıyla: ifadeler bağlı
    # parametre taşıdığı için (`'PB'`, `'YYYY-MM'`) metin olarak tekrarlanamaz.
    tutar, eksik = _tutar_ifadeleri()
    stmt = (
        tuketim_sorgusu(user, s, clock)
        .with_only_columns(
            *sutunlar,
            (-func.sum(StockMovement.qty)).label("net_cikis"),
            func.count().label("hareket"),
            tutar.label("tutar"),
            eksik.label("maliyet_eksik"),
        )
        .group_by(*[text(str(i + 1)) for i in range(len(sutunlar))])
    )
    if kirilim == "ekipman":
        stmt = stmt.where(ServiceOrder.equipment_id.is_not(None))
    satirlar = (await db.execute(stmt)).mappings().all()
    urun_idler = {r["product_id"] for r in satirlar if r.get("product_id")}
    urunler = {
        u.id: u
        for u in (
            await db.scalars(select(Product).where(Product.id.in_(list(urun_idler) or [0])))
        ).all()
    }
    musteri_idler = {r["musteri_id"] for r in satirlar if r.get("musteri_id")}
    musteriler = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(Account.id.in_(list(musteri_idler) or [0]))
            )
        ).all()
    )
    so_idler = {r["so_id"] for r in satirlar if r.get("so_id")}
    isler = dict(
        (
            await db.execute(
                select(ServiceOrder.id, ServiceOrder.so_no).where(
                    ServiceOrder.id.in_(list(so_idler) or [0])
                )
            )
        ).all()
    )
    ekipman_idler = {r["ekipman_id"] for r in satirlar if r.get("ekipman_id")}
    ekipmanlar = {
        e.id: e
        for e in (
            await db.scalars(
                select(ServiceEquipment).where(ServiceEquipment.id.in_(list(ekipman_idler) or [0]))
            )
        ).all()
    }
    sonuc = []
    toplam_net = 0
    toplam_tutar = Decimal("0.00")
    toplam_eksik = 0
    for r in satirlar:
        satir: dict[str, Any] = {k: r[k] for k in r.keys() if k not in ("tutar", "maliyet_eksik")}
        satir["is_grubu_adi"] = IS_GRUBU_ADLARI.get(r["is_grubu"], r["is_grubu"])
        if r.get("product_id"):
            u = urunler.get(r["product_id"])
            satir["urun_kodu"] = u.code if u else None
            satir["urun_adi"] = u.name if u else None
        if "musteri_id" in r:
            satir["musteri"] = musteriler.get(r["musteri_id"])
        if r.get("so_id"):
            satir["so_no"] = isler.get(r["so_id"])
        if r.get("ekipman_id"):
            e = ekipmanlar.get(r["ekipman_id"])
            satir["ekipman"] = (
                {"id": e.id, "tip": e.equipment_type, "seri": e.serial_no} if e else None
            )
        satir["net_cikis"] = int(r["net_cikis"] or 0)
        toplam_net += satir["net_cikis"]
        eksik_mi = bool(r["maliyet_eksik"])
        toplam_eksik += int(r["maliyet_eksik"] or 0)
        if maliyet_gorur:
            satir["maliyet_eksik"] = eksik_mi
            satir["tutar"] = (
                None
                if eksik_mi
                else Decimal(str(r["tutar"] or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)
            )
            if satir["tutar"] is not None:
                toplam_tutar += satir["tutar"]
        sonuc.append(satir)
    sonuc.sort(
        key=lambda x: (
            str(x.get("ay") or ""),
            str(x.get("birim") or ""),
            str(x.get("musteri") or ""),
            str(x.get("is_turu") or ""),
            str(x.get("so_no") or ""),
            str(x.get("urun_kodu") or ""),
            x["is_grubu"],
        )
    )
    toplam: dict[str, Any] = {"net_cikis": toplam_net}
    if maliyet_gorur:
        toplam["tutar"] = toplam_tutar
        toplam["maliyet_eksik_hareket"] = toplam_eksik
    return {
        "donem": {"bas": bas, "bit": bit},
        "kirilim": kirilim,
        "satirlar": sonuc,
        "toplam": toplam,
    }


# --- Kayıtlar (dosyanın EN ALTINDA; plan §1.8, §1.11) ------------------------------------

kancalar.kaydet("durum_degisti", talepleri_kapat)
ts_uyarilar.kaydet("parca", "parca.yonet", az_stok_uyarisi)
ts_uyarilar.kaydet("parca", "parca.kullan", parca_geldi_uyarisi)
