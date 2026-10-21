"""Hak ediş dökümü belgesi (PDF) ve muhasebe dışa aktarımı."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    Address,
    InstallationPartner,
    PartnerSettlement,
    Quote,
    QuoteLine,
    QuoteVersion,
    SettlementLine,
    User,
    WorkOrder,
)
from app.services import settings as ayar_svc
from app.services.pdf import pdf_uret_async, tl

BELGE_TIPI_ADI = {
    "FATURA": "Fatura",
    "SERBEST_MESLEK_MAKBUZU": "Serbest Meslek Makbuzu",
    "GIDER_PUSULASI": "Gider Pusulası",
    "BELIRSIZ": "BELİRSİZ",
}


async def dokum_baglami(db: AsyncSession, dokum: PartnerSettlement) -> dict:
    nokta = await db.get(Account, dokum.partner_id)
    ortak = await db.get(InstallationPartner, dokum.partner_id)
    fatura_eden = None
    if dokum.billing_account_id and dokum.billing_account_id != dokum.partner_id:
        b = await db.get(Account, dokum.billing_account_id)
        fatura_eden = b.title if b else None

    satirlar = (
        await db.scalars(
            select(SettlementLine)
            .where(SettlementLine.settlement_id == dokum.id)
            .order_by(SettlementLine.is_deduction, SettlementLine.id)
        )
    ).all()

    is_nolari: dict[int, str] = {}
    wo_idleri = {s.work_order_id for s in satirlar if s.work_order_id}
    if wo_idleri:
        for wo in (await db.scalars(select(WorkOrder).where(WorkOrder.id.in_(wo_idleri)))).all():
            is_nolari[wo.id] = wo.wo_no

    gorunum = [
        {
            "is_no": is_nolari.get(s.work_order_id or 0),
            "work_type": s.work_type,
            "description": s.description,
            "unit_price": tl(s.unit_price),
            "quantity": (f"{Decimal(str(s.quantity)):g}" if s.quantity is not None else "1"),
            "amount": tl(s.amount),
            "is_deduction": s.is_deduction,
        }
        for s in satirlar
    ]

    matrah = Decimal(str(dokum.gross_amount)) - Decimal(str(dokum.deduction_amount))
    ayarlar = await ayar_svc.get_all(db)
    return {
        "dokum": dokum,
        "nokta": nokta,
        "fatura_eden": fatura_eden,
        "belge_tipi": BELGE_TIPI_ADI.get(
            (ortak.document_type if ortak else "BELIRSIZ"), "BELİRSİZ"
        ),
        "belge_no": f"HD-{dokum.period.replace('-', '')}-{dokum.id:05d}",
        "satirlar": gorunum,
        "toplam": {
            "brut": tl(dokum.gross_amount),
            "kesinti": tl(dokum.deduction_amount),
            "kesinti_var": Decimal(str(dokum.deduction_amount)) > 0,
            "matrah": tl(matrah),
            "kdv": tl(dokum.vat_amount),
            "kdv_var": Decimal(str(dokum.vat_amount)) > 0,
            "stopaj": tl(dokum.withholding_amount),
            "stopaj_var": Decimal(str(dokum.withholding_amount)) > 0,
            "damga": tl(dokum.stamp_tax_amount),
            "damga_var": Decimal(str(dokum.stamp_tax_amount)) > 0,
            "net": tl(dokum.net_payable),
        },
        "firma": firma_bilgisi(ayarlar),
    }


async def dokum_pdf(db: AsyncSession, dokum: PartnerSettlement) -> bytes:
    return await pdf_uret_async("hakedis_dokumu.html", **await dokum_baglami(db, dokum))


# --- Teklif -------------------------------------------------------------------


async def ayar_haritasi(db: AsyncSession) -> dict:
    """Belge üretiminin okuduğu ayarlar. Arayüzdeki canlı önizleme de bunu
    kullanır; iki yerden okunsaydı ekran ile PDF ayrışırdı."""
    return await ayar_svc.get_all(db)


def _sade(deger) -> str:
    """Sondaki anlamsız sıfırları atar: 20.0000 → 20, 1.00 → 1, 2.50 → 2.5.

    `:g` biçimi Decimal'in HASSASİYETİNİ koruyor; `Decimal("0.2000") * 100`
    ile gelen değer belgeye `%20.0000` olarak basılıyordu. Teklif müşteriye
    gidiyor: KDV oranının dört ondalıkla yazılması ciddiyetsiz görünür.
    """
    d = Decimal(str(deger)).normalize()
    # `normalize()` büyük sayıları üstel biçime çevirebilir (1E+2); geri al.
    return f"{d:f}" if d == d.to_integral_value() else format(d, "f").rstrip("0").rstrip(".")


def firma_bilgisi(ayarlar: dict) -> dict:
    """Belge başlığındaki şirket künyesi.

    Resmî bilgiler henüz toplanmadı (plan §8 madde 5). Eksikse belge yine
    üretilir ve BİLİNEN adres/telefon basılır — sessizce yanlış bilgi
    basmaktansa doğru bildiğimizi basmak doğrudur. Parametreler ekranından
    girilince bu varsayılanların yerini alır.
    """
    return {
        "unvan": ayarlar.get("firma_unvan") or "Denge Mobilite",
        "adres": ayarlar.get("firma_adres")
        or "Küçükbakkalköy Mah. Derebey Sok. No:6 Denge Plaza, Ataşehir / İstanbul",
        "telefon": ayarlar.get("firma_telefon") or "+90 216 573 40 40",
        "eposta": ayarlar.get("firma_eposta") or "bilgi@dengemobil.com.tr",
        "vkn": ayarlar.get("firma_vkn") or "",
        "vergi_dairesi": ayarlar.get("firma_vergi_dairesi") or "",
        "mersis": ayarlar.get("firma_mersis") or "",
        "kep": ayarlar.get("firma_kep") or "",
    }


VARSAYILAN_SARTLAR = (
    "Fiyatlarımıza KDV dahil değildir; tabloda ayrıca gösterilmiştir. "
    "Ödeme ve teslim şartları taraflar arasında ayrıca mutabık kalınacaktır. "
    "Teklif, yukarıda belirtilen geçerlilik tarihine kadar bağlayıcıdır."
)


async def _teklif_adresi(db: AsyncSession, teklif: Quote) -> Address | None:
    """Teklif PDF'ine basılan müşteri adresi (K24, E14-02/E14-15).

    1. Teklif bir tesise bağlıysa (`quotes.address_id`, servis işinden açılan
       teklif) ve tesis aynı müşteriye aitse o basılır.
    2. Değilse carinin TESİS DIŞI ilk adresi. `addresses` artık servis
       tesislerini de taşıyor; sırasız `limit(1)` bir AVM tesisini teklifin
       muhatap adresi diye basabilirdi.

    Sıralama `id`: bugünkü sırasız sorgu pratikte ekleme sırasını veriyordu
    ve canlıdaki satırların hepsi MERKEZ olduğundan basılan adres DEĞİŞMEZ.
    `is_primary DESC` bilerek eklenmedi — çok adresli hesapta bugünkü çıktıyı
    değiştirirdi (E14 kontrol B8).
    """
    if teklif.address_id is not None:
        bagli = await db.get(Address, teklif.address_id)
        if bagli is not None and bagli.account_id == teklif.customer_id:
            return bagli
    return await db.scalar(
        select(Address)
        .where(Address.account_id == teklif.customer_id, Address.kind != "TESIS")
        .order_by(Address.id)
        .limit(1)
    )


async def teklif_baglami(db: AsyncSession, teklif: Quote, versiyon: QuoteVersion) -> dict:
    musteri = await db.get(Account, teklif.customer_id)
    hazirlayan = await db.get(User, teklif.owner_id) if teklif.owner_id else None
    adres = await _teklif_adresi(db, teklif)
    kalemler = (
        await db.scalars(
            select(QuoteLine)
            .where(QuoteLine.version_id == versiyon.id)
            .order_by(QuoteLine.sort_order, QuoteLine.id)
        )
    ).all()

    ayarlar = await ayar_svc.get_all(db)
    return {
        "teklif": teklif,
        "versiyon": versiyon,
        "musteri": musteri,
        "adres": " ".join(filter(None, [adres.line, adres.district, adres.city]))
        if adres
        else None,
        "hazirlayan": hazirlayan.full_name if hazirlayan else "—",
        "gecerlilik": versiyon.valid_until.strftime("%d.%m.%Y") if versiyon.valid_until else "—",
        "kur": tl(versiyon.fx_rate) if versiyon.fx_rate else None,
        "kur_tarihi": versiyon.fx_date.strftime("%d.%m.%Y") if versiyon.fx_date else "",
        "kalemler": [
            {
                "description": k.description,
                "qty": _sade(k.qty),
                "unit_price": tl(k.unit_price),
                "discount_pct": _sade(k.discount_pct),
                "iskonto_var": Decimal(str(k.discount_pct)) > 0,
                "vat_pct": _sade(Decimal(str(k.vat_rate)) * 100),
                "line_total": tl(k.line_total),
            }
            for k in kalemler
        ],
        "toplam": {
            "ara": tl(versiyon.subtotal),
            "iskonto": tl(versiyon.discount_total),
            "iskonto_var": Decimal(str(versiyon.discount_total)) > 0,
            "kdv": tl(versiyon.vat_total),
            "genel": tl(versiyon.grand_total),
        },
        # Standart ticari şartlar metni henüz hazır değil (plan §8 madde 6);
        # ayarlardan doldurulabilir, boşsa makul bir varsayılan basılır.
        "sartlar": ayarlar.get("teklif_ticari_sartlar") or VARSAYILAN_SARTLAR,
        "firma": firma_bilgisi(ayarlar),
    }


async def teklif_pdf(db: AsyncSession, teklif: Quote, versiyon: QuoteVersion) -> bytes:
    return await pdf_uret_async("teklif.html", **await teklif_baglami(db, teklif, versiyon))
