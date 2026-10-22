"""Stok, transfer ve konum/sahiplik iş kuralları."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Account,
    Device,
    DeviceCustodyHistory,
    Transfer,
    TransferItem,
    Warehouse,
)
from app.services import settings as ayar_svc


class TransferHatasi(ValueError):
    """Transfer kurallarına aykırı işlem."""


def _an(deger: datetime) -> datetime:
    return deger if deger.tzinfo else deger.replace(tzinfo=UTC)


async def acik_konum(db: AsyncSession, device_id: int) -> DeviceCustodyHistory | None:
    return await db.scalar(
        select(DeviceCustodyHistory).where(
            DeviceCustodyHistory.device_id == device_id,
            DeviceCustodyHistory.valid_to.is_(None),
        )
    )


async def konum_tarihinde(
    db: AsyncSession, device_id: int, an: datetime
) -> DeviceCustodyHistory | None:
    """'Bu cihaz o gün neredeydi' — brief §4.3."""
    an = _an(an)
    return await db.scalar(
        select(DeviceCustodyHistory).where(
            DeviceCustodyHistory.device_id == device_id,
            DeviceCustodyHistory.valid_from <= an,
            (DeviceCustodyHistory.valid_to.is_(None)) | (DeviceCustodyHistory.valid_to > an),
        )
    )


async def konum_ata(
    db: AsyncSession,
    *,
    device_id: int,
    location_type: str,
    clock: Clock,
    warehouse_id: int | None = None,
    account_id: int | None = None,
    ownership: str | None = None,
    transfer_id: int | None = None,
    an: datetime | None = None,
    notes: str | None = None,
) -> DeviceCustodyHistory:
    """Cihazı yeni konuma alır; açık dönemi kapatır.

    Sahiplik verilmezse ÖNCEKİ sahiplik korunur — konum değişikliği tek
    başına mülkiyeti değiştirmez (depo→bayi sevkinde cihaz hâlâ Denge'nin
    malı olabilir).
    """
    zaman = _an(an or clock.now())
    onceki = await acik_konum(db, device_id)
    if onceki is not None:
        if onceki.valid_from >= zaman:
            raise TransferHatasi(
                "Yeni konum kaydı, mevcut kaydın başlangıcından eski olamaz "
                f"({onceki.valid_from:%d.%m.%Y} ≥ {zaman:%d.%m.%Y})."
            )
        onceki.valid_to = zaman
    kayit = DeviceCustodyHistory(
        device_id=device_id,
        location_type=location_type,
        warehouse_id=warehouse_id,
        account_id=account_id,
        ownership=ownership or (onceki.ownership if onceki else "DENGE"),
        transfer_id=transfer_id,
        valid_from=zaman,
        notes=notes,
    )
    db.add(kayit)
    await db.flush()
    return kayit


async def transferi_teslim_et(
    db: AsyncSession, transfer: Transfer, *, clock: Clock, teslim_alan: str | None = None
) -> int:
    """Transferi teslim edilmiş sayar ve tüm cihazların konumunu günceller.

    Konum kayıtları TRANSFERLE BİRLİKTE yazılır; ayrı bir adım bırakılsaydı
    "sevk edildi ama konumu güncellenmedi" durumu oluşurdu.
    """
    if transfer.status == "TESLIM_EDILDI":
        raise TransferHatasi("Bu transfer zaten teslim edilmiş.")
    if transfer.status == "IPTAL":
        raise TransferHatasi("İptal edilmiş transfer teslim edilemez.")

    kalemler = (
        await db.scalars(select(TransferItem).where(TransferItem.transfer_id == transfer.id))
    ).all()
    if not kalemler:
        raise TransferHatasi("Transferde hiç cihaz yok.")

    simdi = clock.now()
    for kalem in kalemler:
        await konum_ata(
            db,
            device_id=kalem.device_id,
            location_type=transfer.to_location_type,
            warehouse_id=transfer.to_warehouse_id,
            account_id=transfer.to_account_id,
            ownership=transfer.new_ownership,
            transfer_id=transfer.id,
            clock=clock,
            an=simdi,
        )
    transfer.status = "TESLIM_EDILDI"
    transfer.delivered_at = simdi.date()
    if teslim_alan:
        transfer.received_by = teslim_alan
    await db.flush()
    return len(kalemler)


async def bayi_stogu(db: AsyncSession, *, account_id: int | None = None) -> list[dict]:
    """Bayi/montaj noktası bazında elde duran cihaz sayısı ve bekleme günü."""
    # Unvan sorguya katılır: çağıranların tek tek hesap çekmesi (N+1) iki
    # ayrı uçta tekrarlanıyordu ve biri unvanı hiç doldurmuyordu.
    stmt = (
        select(
            DeviceCustodyHistory.account_id,
            Account.title,
            DeviceCustodyHistory.ownership,
            func.count().label("adet"),
            func.min(DeviceCustodyHistory.valid_from).label("en_eski"),
        )
        .outerjoin(Account, Account.id == DeviceCustodyHistory.account_id)
        .where(
            DeviceCustodyHistory.valid_to.is_(None),
            DeviceCustodyHistory.location_type.in_(("BAYI", "MONTAJ_NOKTASI")),
        )
        .group_by(DeviceCustodyHistory.account_id, Account.title, DeviceCustodyHistory.ownership)
    )
    if account_id:
        stmt = stmt.where(DeviceCustodyHistory.account_id == account_id)
    return [
        {
            "account_id": r.account_id,
            "account_title": r.title,
            "ownership": r.ownership,
            "adet": r.adet,
            "en_eski": r.en_eski,
        }
        for r in (await db.execute(stmt)).all()
    ]


async def yaslanan_stok(db: AsyncSession, clock: Clock) -> list[dict]:
    """Bayide eşik günden uzun süredir bekleyen cihazlar.

    Konsinye kapsam dışı olduğu için bu rapor "satılmış ama hâlâ bayide
    duran" stoğu izler — satış sonrası hareketsizlik de bir sinyaldir.
    """
    esik_gun = int(await ayar_svc.get(db, "bayi_stok_yaslanma_gun"))
    sinir = clock.now() - timedelta(days=esik_gun)
    satirlar = (
        await db.execute(
            select(DeviceCustodyHistory, Device)
            .join(Device, Device.id == DeviceCustodyHistory.device_id)
            .where(
                DeviceCustodyHistory.valid_to.is_(None),
                DeviceCustodyHistory.location_type.in_(("BAYI", "MONTAJ_NOKTASI")),
                DeviceCustodyHistory.valid_from < sinir,
            )
            .order_by(DeviceCustodyHistory.valid_from)
        )
    ).all()
    return [
        {
            "device_id": c.id,
            "kimlik": c.kimlik,
            "account_id": k.account_id,
            "ownership": k.ownership,
            "bekleme_gunu": (clock.now() - k.valid_from).days,
        }
        for k, c in satirlar
    ]


# --- Denge'nin kendi stoğu (model bazında) -----------------------------------

# "Elimde var" sayılan cihaz durumları. REZERVE ve SEVK_EDILDI ayrı gösterilir:
# fiziksel olarak depoda durabilirler ama söz verilmiş ya da yola çıkmıştır,
# yeni bir siparişe sayılamazlar.
ELDEKI = ("STOKTA", "TEST_EDILDI", "YENIDEN_STOKTA")
YOLDAKI = ("ITHALATTA", "SEVK_EDILDI")
AYRILMIS = ("REZERVE",)


async def denge_stogu(db: AsyncSession, *, urun_tipi: str | None = None) -> list[dict]:
    """Model bazında Denge stoğu: hangi üründen kaç adet var.

    İki farklı ürün türü tek listede birleşir:

    * **Serili ürünler** (cihaz) — her adedin kendi kaydı var, sayım
      `devices` üzerinden yapılır ve durum kırılımı verilir.
    * **Serisiz ürünler** (aksesuar, kablo) — tekil kayıt yok, eldeki adet
      `stock_movements` toplamıdır.

    Sayım `devices.status` üzerinden yapılır, konum geçmişi üzerinden değil:
    durum durum makinesiyle korunuyor ve göçten gelen cihazların bir kısmında
    konum kaydı hiç yok. Konum kırılımı ayrıca verilir ("nerede duruyor").
    """
    from app.models import Product, StockMovement

    urunler = (
        await db.scalars(
            select(Product).where(Product.is_deleted.is_(False)).order_by(Product.name)
        )
    ).all()
    if urun_tipi:
        urunler = [u for u in urunler if u.type == urun_tipi]

    # --- serili: durum kırılımı ---
    durumlar: dict[tuple[int, str], int] = {
        (pid, durum): adet
        for pid, durum, adet in (
            await db.execute(
                select(Device.product_id, Device.status, func.count())
                .where(Device.is_deleted.is_(False))
                .group_by(Device.product_id, Device.status)
            )
        ).all()
    }
    # --- serili: eldekilerin nerede durduğu ---
    konumlar: dict[tuple[int, str], int] = {
        (pid, konum): adet
        for pid, konum, adet in (
            await db.execute(
                select(Device.product_id, DeviceCustodyHistory.location_type, func.count())
                .join(DeviceCustodyHistory, DeviceCustodyHistory.device_id == Device.id)
                .where(
                    Device.is_deleted.is_(False),
                    Device.status.in_(ELDEKI),
                    DeviceCustodyHistory.valid_to.is_(None),
                    DeviceCustodyHistory.ownership == "DENGE",
                )
                .group_by(Device.product_id, DeviceCustodyHistory.location_type)
            )
        ).all()
    }
    # --- serisiz: hareket toplamı ---
    serisiz: dict[int, int] = dict(
        (
            await db.execute(
                select(
                    StockMovement.product_id, func.coalesce(func.sum(StockMovement.qty), 0)
                ).group_by(StockMovement.product_id)
            )
        ).all()
    )
    # "Elde" TEK toplamdır (servis deposu dahil, E11-D01 K1); servis
    # depolarındaki kısım ayrıca gösterilir ki mobilite ekranı farkı görsün.
    servis_deposunda: dict[int, int] = dict(
        (
            await db.execute(
                select(StockMovement.product_id, func.coalesce(func.sum(StockMovement.qty), 0))
                .join(Warehouse, Warehouse.id == StockMovement.warehouse_id)
                .where(Warehouse.servis_deposu.is_(True))
                .group_by(StockMovement.product_id)
            )
        ).all()
    )

    sonuc = []
    for u in urunler:
        serili = u.identity_kind in ("IMEI", "SERI_NO")
        if serili:
            elde = sum(durumlar.get((u.id, d), 0) for d in ELDEKI)
            yolda = sum(durumlar.get((u.id, d), 0) for d in YOLDAKI)
            ayrilmis = sum(durumlar.get((u.id, d), 0) for d in AYRILMIS)
            sahada = sum(durumlar.get((u.id, d), 0) for d in ("AKTIF", "MONTAJ_BEKLIYOR"))
            serviste = sum(durumlar.get((u.id, d), 0) for d in ("ARIZALI", "RMA", "TAMIRDE"))
        else:
            elde = serisiz.get(u.id, 0)
            yolda = ayrilmis = sahada = serviste = 0

        sonuc.append(
            {
                "product_id": u.id,
                "kod": u.code,
                "ad": u.name,
                "marka": u.brand,
                "model": u.model,
                "tip": u.type,
                "serili": serili,
                "elde": elde,
                "ayrilmis": ayrilmis,
                "yolda": yolda,
                "sahada": sahada,
                "serviste": serviste,
                "konumlar": {
                    konum: adet for (pid, konum), adet in konumlar.items() if pid == u.id and adet
                },
                "servis_deposunda": 0 if serili else servis_deposunda.get(u.id, 0),
            }
        )
    return sonuc


async def stok_hareketi(
    db: AsyncSession,
    *,
    product_id: int,
    qty: int,
    reason: str,
    warehouse_id: int | None = None,
    document_no: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
):
    """Serisiz ürüne stok hareketi yazar.

    Serili üründe kullanılmaz: orada adet, cihaz kayıtlarının kendisidir ve
    ikinci bir sayaç tutmak iki rakamın ayrışması demekti.
    """
    from app.models import Product, StockMovement

    urun = await db.get(Product, product_id)
    if urun is None or urun.is_deleted:
        raise TransferHatasi(f"Ürün bulunamadı: {product_id}")
    if urun.identity_kind in ("IMEI", "SERI_NO"):
        raise TransferHatasi(
            f"{urun.code} seri numarasıyla takip ediliyor; adet stok hareketi girilemez. "
            "Cihazları tek tek kaydedin ya da toplu içe aktarın."
        )
    if qty == 0:
        raise TransferHatasi("Adet sıfır olamaz")
    if warehouse_id is not None:
        # Tek yazıcı ilkesi (E11-01/D01, E06-D01): servis deposu yalnız Yedek
        # Parça uçlarından (`teknik_servis/parca.py`), kiralama deposu kendi
        # defterinden yazılır. Mobilite depoları ve depo seçilmeyen hareket
        # bugünkü gibi çalışır.
        depo = await db.get(Warehouse, warehouse_id)
        if depo is not None and (depo.servis_deposu or depo.kiralama_deposu):
            raise TransferHatasi(
                "Servis ve kiralama depolarına hareket bu ekrandan girilmez; Yedek Parça "
                "ya da Kiralık Envanter ekranını kullanın."
            )

    hareket = StockMovement(
        product_id=product_id,
        warehouse_id=warehouse_id,
        qty=qty,
        reason=reason,
        document_no=document_no,
        notes=notes,
        created_by=user_id,
    )
    db.add(hareket)
    await db.flush()
    return hareket
