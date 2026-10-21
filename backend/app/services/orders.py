"""Sipariş iş kuralları: tekliften dönüşüm, IMEI rezervasyonu, sevkiyat."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Device,
    Order,
    OrderLine,
    OrderReservation,
    Product,
    Quote,
    QuoteLine,
    QuoteVersion,
    Transfer,
    TransferItem,
)
from app.services import stock as stok_svc
from app.services.devices import durum_degistir
from app.services.quotes import kalem_topla, yuvarla

# Rezervasyona uygun cihaz durumları — sevk edilmiş ya da arızalı cihaz
# müşteriye söz verilemez.
REZERVE_EDILEBILIR = ("STOKTA", "TEST_EDILDI", "YENIDEN_STOKTA")


class SiparisHatasi(ValueError):
    """Sipariş kurallarına aykırı işlem."""


async def hesapla(db: AsyncSession, siparis: Order) -> Order:
    """Kalemlerden sipariş toplamlarını yeniden hesaplar.

    KDV kalem bazında; oranlar kalemde dondurulmuştur (plan §3.3/2).
    """
    kalemler = (await db.scalars(select(OrderLine).where(OrderLine.order_id == siparis.id))).all()

    ara = iskonto = kdv = Decimal("0")
    for k in kalemler:
        brut = Decimal(str(k.qty)) * Decimal(str(k.unit_price))
        net = kalem_topla(k.qty, k.unit_price, k.discount_pct)
        k.line_total = net
        ara += brut
        iskonto += brut - net
        kdv += yuvarla(net * Decimal(str(k.vat_rate)))

    siparis.subtotal = yuvarla(ara)
    siparis.discount_total = yuvarla(iskonto)
    siparis.vat_total = yuvarla(kdv)
    siparis.grand_total = yuvarla(ara - iskonto + kdv)
    await db.flush()
    return siparis


async def numara_uret(db: AsyncSession, clock: Clock) -> str:
    sira = (await db.scalar(select(Order.id).order_by(Order.id.desc()).limit(1)) or 0) + 1
    return f"SIP{clock.now():%Y}-{sira:05d}"


async def tekliften_olustur(
    db: AsyncSession,
    teklif: Quote,
    versiyon: QuoteVersion,
    *,
    clock: Clock,
    user_id: int | None = None,
    istenen_tarih: date | None = None,
) -> Order:
    """Kabul edilmiş teklif versiyonundan sipariş açar.

    Kalemler KOPYALANIR, referansla bağlanmaz: teklif sonradan revize edilse
    de siparişin içeriği değişmez. Aynı teklif ikinci kez siparişe
    dönüştürülemez — mükerrer sevkiyatın en kolay yolu budur.
    """
    if versiyon.accepted_at is None:
        raise SiparisHatasi("Yalnız kabul edilmiş teklif versiyonu siparişe dönüştürülebilir.")
    mevcut = await db.scalar(
        select(Order).where(Order.quote_id == teklif.id, Order.is_deleted.is_(False))
    )
    if mevcut is not None:
        raise SiparisHatasi(f"Bu teklif zaten {mevcut.order_no} siparişine dönüştürülmüş.")

    siparis = Order(
        order_no=await numara_uret(db, clock),
        customer_id=teklif.customer_id,
        quote_id=teklif.id,
        quote_version_id=versiyon.id,
        owner_id=teklif.owner_id,
        status="TASLAK",
        order_date=clock.now().date(),
        requested_date=istenen_tarih,
        currency=versiyon.currency,
        fx_rate=versiyon.fx_rate,
        fx_date=versiyon.fx_date,
        created_by=user_id,
    )
    db.add(siparis)
    await db.flush()

    for k in (
        await db.scalars(
            select(QuoteLine)
            .where(QuoteLine.version_id == versiyon.id)
            .order_by(QuoteLine.sort_order, QuoteLine.id)
        )
    ).all():
        db.add(
            OrderLine(
                order_id=siparis.id,
                item_type=k.item_type,
                product_id=k.product_id,
                description=k.description,
                qty=k.qty,
                unit_price=k.unit_price,
                discount_pct=k.discount_pct,
                vat_rate=k.vat_rate,
                sort_order=k.sort_order,
            )
        )
    await db.flush()
    await hesapla(db, siparis)

    teklif.status = "SIPARISE_DONUSTU"
    await db.flush()
    return siparis


async def acik_rezervasyonlar(db: AsyncSession, order_id: int) -> list[OrderReservation]:
    return list(
        (
            await db.scalars(
                select(OrderReservation).where(
                    OrderReservation.order_id == order_id,
                    OrderReservation.released_at.is_(None),
                )
            )
        ).all()
    )


async def _kalem_rezerve_sayisi(db: AsyncSession, order_line_id: int) -> Decimal:
    return Decimal(
        str(
            await db.scalar(
                select(func.count())
                .select_from(OrderReservation)
                .where(
                    OrderReservation.order_line_id == order_line_id,
                    OrderReservation.released_at.is_(None),
                )
            )
            or 0
        )
    )


async def rezerve_et(
    db: AsyncSession,
    siparis: Order,
    kalem: OrderLine,
    device_ids: list[int],
    *,
    clock: Clock,
    user_id: int | None = None,
    ip: str | None = None,
) -> list[OrderReservation]:
    """Kalem için IMEI ayırır.

    Rezervasyon cihaz bazındadır: hangi IMEI'nin kime söz verildiği baştan
    bellidir. Cihaz `REZERVE` durumuna geçer; bir cihazın aynı anda tek açık
    rezervasyonu olabilir (kısmi tekil indeks).
    """
    if siparis.status in ("TASLAK", "IPTAL", "TAMAMLANDI"):
        raise SiparisHatasi(
            f"{siparis.status} durumundaki siparişte rezervasyon yapılamaz; önce onaylayın."
        )

    # KİMLİK İSTEMEYEN kaleme cihaz bağlanamaz. Hizmet/abonelik satırına cihaz
    # rezerve edilebiliyordu: API kendi çıktısında o kalemin kimlik
    # gerektirmediğini söylüyor, ama engellemiyordu. Sonuç, sevk edilemeyecek
    # bir cihazın stoktan düşmüş görünmesi.
    if kalem.item_type not in SEVK_EDILEBILIR_KALEM:
        raise SiparisHatasi(
            f"'{kalem.item_type}' kalemine cihaz rezerve edilemez; bu satır sevk edilmez."
        )
    if kalem.product_id:
        urun = await db.get(Product, kalem.product_id)
        if urun is not None and urun.identity_kind == "YOK":
            raise SiparisHatasi(f"{urun.name} ürünü kimlik taşımıyor; cihaz rezerve edilemez.")

    zaten = await _kalem_rezerve_sayisi(db, kalem.id)
    sevk = Decimal(str(kalem.qty_shipped or 0))
    kalan = Decimal(str(kalem.qty)) - zaten - sevk
    if Decimal(len(device_ids)) > kalan:
        raise SiparisHatasi(
            f"Kalem için kalan adet {kalan:g}; {len(device_ids)} cihaz rezerve edilemez."
        )

    simdi = clock.now()
    sonuc: list[OrderReservation] = []
    for device_id in device_ids:
        cihaz = await db.get(Device, device_id)
        if cihaz is None or cihaz.is_deleted:
            raise SiparisHatasi(f"Cihaz bulunamadı: {device_id}")
        if kalem.product_id and cihaz.product_id != kalem.product_id:
            raise SiparisHatasi(
                f"{cihaz.imei or cihaz.serial_no or cihaz.id} cihazı kalemdeki ürüne ait değil."
            )
        if cihaz.status not in REZERVE_EDILEBILIR:
            raise SiparisHatasi(
                f"{cihaz.imei or cihaz.serial_no or cihaz.id} cihazı '{cihaz.status}' "
                "durumunda; rezerve edilemez."
            )
        acik = await db.scalar(
            select(OrderReservation).where(
                OrderReservation.device_id == device_id,
                OrderReservation.released_at.is_(None),
            )
        )
        if acik is not None:
            raise SiparisHatasi(
                f"{cihaz.imei or cihaz.serial_no or cihaz.id} cihazı başka bir siparişte "
                "rezerve edilmiş."
            )

        rezervasyon = OrderReservation(
            order_id=siparis.id,
            order_line_id=kalem.id,
            device_id=device_id,
            reserved_at=simdi,
            created_by=user_id,
        )
        db.add(rezervasyon)
        await durum_degistir(
            db,
            cihaz,
            "REZERVE",
            clock=clock,
            user_id=user_id,
            neden=f"{siparis.order_no} siparişi için rezerve edildi",
            ip=ip,
        )
        sonuc.append(rezervasyon)

    await db.flush()
    if siparis.status == "ONAYLANDI":
        siparis.status = "REZERVE"
        await db.flush()
    return sonuc


async def rezervasyon_birak(
    db: AsyncSession,
    rezervasyon: OrderReservation,
    *,
    clock: Clock,
    neden: str | None = None,
    user_id: int | None = None,
    ip: str | None = None,
) -> None:
    """Rezervasyonu serbest bırakır ve cihazı stoğa döndürür."""
    if rezervasyon.released_at is not None:
        raise SiparisHatasi("Bu rezervasyon zaten serbest bırakılmış.")
    if rezervasyon.shipped_at is not None:
        raise SiparisHatasi("Sevk edilmiş cihazın rezervasyonu geri alınamaz; iade kaydı açın.")

    rezervasyon.released_at = clock.now()
    rezervasyon.release_reason = neden
    cihaz = await db.get(Device, rezervasyon.device_id)
    if cihaz is not None and cihaz.status == "REZERVE":
        await durum_degistir(db, cihaz, "STOKTA", clock=clock, user_id=user_id, neden=neden, ip=ip)
    await db.flush()

    siparis = await db.get(Order, rezervasyon.order_id)
    if siparis is not None and siparis.status == "REZERVE":
        if not await acik_rezervasyonlar(db, siparis.id):
            siparis.status = "ONAYLANDI"
            await db.flush()


async def sevk_et(
    db: AsyncSession,
    siparis: Order,
    rezervasyonlar: list[OrderReservation],
    *,
    clock: Clock,
    from_warehouse_id: int | None = None,
    belge_no: str | None = None,
    teslim_eden: str | None = None,
    user_id: int | None = None,
    ip: str | None = None,
) -> Transfer:
    """Rezerve cihazları müşteriye sevk eder.

    Sevkiyat, stok modülünün `transfers` belgesiyle yapılır — ikinci bir sevk
    mekanizması konum geçmişini iki yoldan yazmak olurdu. Belge `YOLDA`
    açılır; teslim ve konum güncellemesi mevcut stok akışından yürür.
    """
    if not rezervasyonlar:
        raise SiparisHatasi("Sevk edilecek rezervasyon seçilmedi.")
    if siparis.status not in ("REZERVE", "ONAYLANDI", "KISMI_SEVK"):
        raise SiparisHatasi(f"{siparis.status} durumundaki sipariş sevk edilemez.")

    simdi = clock.now()
    sira = (await db.scalar(select(Transfer.id).order_by(Transfer.id.desc()).limit(1)) or 0) + 1
    transfer = Transfer(
        transfer_no=f"TR{simdi:%Y%m}-{sira:05d}",
        type="SATIS",
        status="YOLDA",
        order_id=siparis.id,
        from_location_type="MERKEZ_DEPO",
        from_warehouse_id=from_warehouse_id,
        to_location_type="MUSTERI",
        to_account_id=siparis.customer_id,
        new_ownership="MUSTERI_SATILDI",
        document_no=belge_no,
        shipped_at=simdi.date(),
        delivered_by=teslim_eden,
        created_by=user_id,
    )
    db.add(transfer)
    await db.flush()

    kalem_artis: dict[int, Decimal] = {}
    for rez in rezervasyonlar:
        if rez.order_id != siparis.id:
            raise SiparisHatasi("Rezervasyon bu siparişe ait değil.")
        if rez.released_at is not None or rez.shipped_at is not None:
            raise SiparisHatasi("Serbest bırakılmış veya zaten sevk edilmiş rezervasyon seçildi.")

        db.add(TransferItem(transfer_id=transfer.id, device_id=rez.device_id))
        rez.shipped_at = simdi
        # Sevkiyat rezervasyonu TÜKETİR: cihaz artık "rezerve" değil, yolda.
        rez.released_at = simdi
        rez.release_reason = "Sevk edildi"
        rez.transfer_id = transfer.id
        kalem_artis[rez.order_line_id] = kalem_artis.get(rez.order_line_id, Decimal("0")) + 1

        cihaz = await db.get(Device, rez.device_id)
        if cihaz is not None:
            await durum_degistir(
                db,
                cihaz,
                "SEVK_EDILDI",
                clock=clock,
                user_id=user_id,
                neden=f"{siparis.order_no} · {transfer.transfer_no}",
                ip=ip,
            )

    for kalem_id, adet in kalem_artis.items():
        kalem = await db.get(OrderLine, kalem_id)
        kalem.qty_shipped = Decimal(str(kalem.qty_shipped or 0)) + adet
    await db.flush()

    await durum_yenile(db, siparis)
    return transfer


# Sevk edilebilen kalem tipleri. HİZMET ve ABONELİK satırı için "sevkiyat"
# diye bir şey yok; `qty_shipped` alanlarını artıran hiçbir uç da yok.
# Toplama dahil edildiklerinde sipariş SEVK_EDİLDİ'ye ULAŞAMIYOR: 3 cihaz +
# 3 hizmet kalemli sipariş, cihazların hepsi sevk edildikten sonra bile
# KISMI_SEVK'te kilitli kalıyordu.
SEVK_EDILEBILIR_KALEM = ("URUN", "PAKET", "SIM_PAKETI", "SERBEST")


async def durum_yenile(db: AsyncSession, siparis: Order) -> str:
    """Sevk edilen adede göre sipariş durumunu günceller."""
    toplam, sevk = (
        await db.execute(
            select(
                func.coalesce(func.sum(OrderLine.qty), 0),
                func.coalesce(func.sum(OrderLine.qty_shipped), 0),
            ).where(
                OrderLine.order_id == siparis.id,
                OrderLine.item_type.in_(SEVK_EDILEBILIR_KALEM),
            )
        )
    ).one()
    toplam, sevk = Decimal(str(toplam)), Decimal(str(sevk))

    if toplam <= 0:
        # Yalnız hizmet/abonelik içeren sipariş: sevk kavramı yok.
        return siparis.status
    if sevk <= 0:
        yeni = "REZERVE" if await acik_rezervasyonlar(db, siparis.id) else "ONAYLANDI"
    elif sevk < toplam:
        yeni = "KISMI_SEVK"
    else:
        yeni = "SEVK_EDILDI"

    if siparis.status != yeni and siparis.status not in ("IPTAL", "TAMAMLANDI"):
        siparis.status = yeni
        await db.flush()
    return siparis.status


async def iptal_et(
    db: AsyncSession,
    siparis: Order,
    *,
    clock: Clock,
    neden: str,
    user_id: int | None = None,
    ip: str | None = None,
) -> Order:
    """Siparişi iptal eder ve açık rezervasyonları serbest bırakır.

    Sevk edilmiş cihaz geri gelmez — iade ayrı bir transfer belgesidir.
    """
    if siparis.status in ("IPTAL", "TAMAMLANDI"):
        raise SiparisHatasi(f"{siparis.status} durumundaki sipariş iptal edilemez.")
    for rez in await acik_rezervasyonlar(db, siparis.id):
        await rezervasyon_birak(
            db, rez, clock=clock, neden=f"Sipariş iptali: {neden}", user_id=user_id, ip=ip
        )
    siparis.status = "IPTAL"
    siparis.cancelled_at = clock.now()
    siparis.cancel_reason = neden
    await db.flush()
    return siparis


async def bekleyen_sevkiyat(db: AsyncSession) -> list[dict]:
    """Onaylanmış ama tamamen sevk edilmemiş siparişler — depo iş listesi."""
    satirlar = (
        await db.execute(
            select(
                Order,
                func.coalesce(func.sum(OrderLine.qty), 0).label("toplam"),
                func.coalesce(func.sum(OrderLine.qty_shipped), 0).label("sevk"),
            )
            .join(OrderLine, OrderLine.order_id == Order.id)
            .where(
                Order.is_deleted.is_(False),
                Order.status.in_(("ONAYLANDI", "REZERVE", "KISMI_SEVK")),
            )
            .group_by(Order.id)
            .order_by(Order.order_date)
        )
    ).all()
    return [
        {
            "order_id": s.id,
            "order_no": s.order_no,
            "customer_id": s.customer_id,
            "status": s.status,
            "order_date": s.order_date,
            "requested_date": s.requested_date,
            "toplam_adet": Decimal(str(toplam)),
            "sevk_adet": Decimal(str(sevk)),
            "kalan_adet": Decimal(str(toplam)) - Decimal(str(sevk)),
        }
        for s, toplam, sevk in satirlar
    ]


async def teslim_et(
    db: AsyncSession, transfer: Transfer, *, clock: Clock, teslim_alan: str | None = None
) -> int:
    """Sevkiyatı teslim alındı işaretler; konum/sahiplik stok akışından yürür."""
    adet = await stok_svc.transferi_teslim_et(db, transfer, clock=clock, teslim_alan=teslim_alan)
    if transfer.order_id:
        siparis = await db.get(Order, transfer.order_id)
        if siparis is not None and siparis.status == "SEVK_EDILDI":
            siparis.status = "TAMAMLANDI"
            await db.flush()
    return adet
