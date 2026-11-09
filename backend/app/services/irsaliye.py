"""İrsaliye iş kuralları (KARARLAR 2026-11-09 S4.3, S4.4).

* **Ne zaman:** depodan (merkez/bölge) şirket DIŞINA giden her stok transferi
  irsaliye üretir — satış siparişi sevki ve Stok ekranındaki dış transfer
  (`irsaliye_gerekir_mi`). Teknisyene, başka depoya, hurdaya giden iç
  hareketler irsaliye üretmez. Kiralama sevki ve servis parça çıkışı kendi
  tutanak/fişleriyle yürür; bu modülün kapsamında değildir.
* **Numara:** `IRS<yıl>-<6 hane>`, yıl başına boşluksuz (`numara_al`).
* **Fiyat:** satır fiyatı yalnız siparişten gelir; yalnız `fiyat_gorur_mu`
  olan kullanıcıya basılır/aktarılır. Maliyet (alış) irsaliyede HİÇ yoktur.
* **Kapsam:** `KENDI_MUSTERILERI` kapsamlı kullanıcı yalnız kendi siparişinin
  irsaliyesini görür (sipariş uçlarıyla aynı kural).
* **Muhasebe devri:** toplu işaret bütündür (biri uygun değilse hiçbiri);
  geri alma gerekçe ister. Logo API'si YOK — yalnız Excel/CSV şablonu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    Account,
    Address,
    BelgeSayaci,
    Device,
    Irsaliye,
    IrsaliyeKalemi,
    Order,
    Product,
    StockMovement,
    Transfer,
    User,
    Warehouse,
)
from app.services import audit
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

SERI = "IRS"
# Şirket dışı varış noktaları: mal başka bir kişiye/firmaya geçer.
DIS_HEDEFLER = ("MUSTERI", "BAYI", "MONTAJ_NOKTASI", "SERVIS")
DEPO_KAYNAKLARI = ("MERKEZ_DEPO", "BOLGE_DEPO")
HEDEF_ADLARI = {
    "MUSTERI": "Müşteri",
    "BAYI": "Bayi",
    "MONTAJ_NOKTASI": "Montaj noktası",
    "SERVIS": "Dış servis",
}
BIRIM_ADLARI = {
    "ADET": "Adet",
    "METRE": "Metre",
    "TAKIM": "Takım",
    "LITRE": "Litre",
    "PAKET": "Paket",
    "KUTU": "Kutu",
}
DEVIR_DURUMLARI = ("bekleyen", "devredildi")
AZAMI_TOPLU = 200
NOT_UZUNLUGU = 300


class IrsaliyeHatasi(ValueError):
    """İrsaliye kurallarına aykırı işlem (409)."""

    def __init__(self, mesaj: str, *, sorunlu: list[int] | None = None) -> None:
        super().__init__(mesaj)
        self.sorunlu = sorunlu or []


class IrsaliyeGirdiHatasi(ValueError):
    """Eksik/biçimsiz girdi (400)."""


@dataclass
class KalemGirdisi:
    aciklama: str
    miktar: Decimal
    product_id: int | None = None
    order_line_id: int | None = None
    stock_movement_id: int | None = None
    urun_kodu: str | None = None
    birim: str = "ADET"
    seri_nolar: list[str] = field(default_factory=list)
    birim_fiyat: Decimal | None = None
    iskonto_yuzde: Decimal | None = None
    kdv_orani: Decimal | None = None


def irsaliye_gerekir_mi(from_location_type: str, to_location_type: str) -> bool:
    """Depodan şirket dışına çıkış mı?"""
    return from_location_type in DEPO_KAYNAKLARI and to_location_type in DIS_HEDEFLER


def fiyat_gorur_mu(user: User) -> bool:
    """Satış fiyatını görme hakkı (sipariş/teklif fiyatlarını zaten görenler)."""
    return user.has("siparis.gor") or user.has("teklif.gor")


async def numara_al(db: AsyncSession, clock: Clock) -> tuple[int, int, str]:
    """(yıl, sıra, numara). Sayaç satırı işlem sonuna kadar kilitli kalır;
    geri alınan işlem numara yakmaz (boşluksuz)."""
    yil = yerel_bugun(clock).year
    stmt = (
        pg_insert(BelgeSayaci)
        .values(seri=SERI, yil=yil, son_no=1)
        .on_conflict_do_update(
            index_elements=[BelgeSayaci.seri, BelgeSayaci.yil],
            set_={"son_no": BelgeSayaci.son_no + 1},
        )
        .returning(BelgeSayaci.son_no)
    )
    sira = int((await db.execute(stmt)).scalar_one())
    return yil, sira, f"{SERI}{yil}-{sira:06d}"


async def _alici_adresi(db: AsyncSession, account_id: int) -> str | None:
    adres = await db.scalar(
        select(Address)
        .where(Address.account_id == account_id, Address.kind != "TESIS")
        .order_by(Address.is_primary.desc(), Address.id)
        .limit(1)
    )
    if adres is None:
        return None
    metin = " ".join(filter(None, [adres.line, adres.district, adres.city]))
    return metin[:400] or None


async def cihaz_kalemleri(
    db: AsyncSession,
    device_ids: list[int],
    *,
    kalem_esleme: dict[int, int] | None = None,
) -> list[KalemGirdisi]:
    """Cihazları (ürün, sipariş kalemi) bazında gruplar; seri no listesi metin.

    `kalem_esleme`: cihaz → sipariş kalemi (fiyat siparişten gelir)."""
    from app.models import OrderLine

    if not device_ids:
        return []
    cihazlar = (await db.scalars(select(Device).where(Device.id.in_(device_ids)))).all()
    gruplar: dict[tuple[int | None, int | None], list[Device]] = {}
    for c in sorted(cihazlar, key=lambda x: x.id):
        anahtar = (c.product_id, (kalem_esleme or {}).get(c.id))
        gruplar.setdefault(anahtar, []).append(c)
    sonuc: list[KalemGirdisi] = []
    for (urun_id, kalem_id), liste in gruplar.items():
        urun = await db.get(Product, urun_id) if urun_id else None
        kalem = await db.get(OrderLine, kalem_id) if kalem_id else None
        sonuc.append(
            KalemGirdisi(
                aciklama=(kalem.description if kalem else None) or (urun.name if urun else "Cihaz"),
                miktar=Decimal(len(liste)),
                product_id=urun_id,
                order_line_id=kalem_id,
                urun_kodu=urun.code if urun else None,
                birim=(urun.birim if urun and urun.birim else "ADET"),
                seri_nolar=[c.imei or c.serial_no or f"#{c.id}" for c in liste],
                birim_fiyat=kalem.unit_price if kalem else None,
                iskonto_yuzde=kalem.discount_pct if kalem else None,
                kdv_orani=kalem.vat_rate if kalem else None,
            )
        )
    return sonuc


async def serisiz_bakiye(db: AsyncSession, product_id: int, warehouse_id: int | None) -> int:
    """Serisiz ürünün eldeki adedi. Depo verilmişse o depo; verilmemişse
    servis/kiralama depoları DIŞINDAKİ (mobilite) toplam."""
    stmt = select(func.coalesce(func.sum(StockMovement.qty), 0)).where(
        StockMovement.product_id == product_id
    )
    if warehouse_id is not None:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    else:
        mobilite = select(Warehouse.id).where(
            Warehouse.servis_deposu.is_(False), Warehouse.kiralama_deposu.is_(False)
        )
        stmt = stmt.where(
            or_(StockMovement.warehouse_id.is_(None), StockMovement.warehouse_id.in_(mobilite))
        )
    return int(await db.scalar(stmt) or 0)


async def olustur(
    db: AsyncSession,
    transfer: Transfer,
    kalemler: list[KalemGirdisi],
    *,
    clock: Clock,
    user_id: int | None,
    numara: tuple[int, int, str] | None = None,
    notlar: str | None = None,
    ip: str | None = None,
) -> Irsaliye:
    """Transfer için irsaliye yazar (aynı işlemde). Alıcı zorunludur."""
    if not kalemler:
        raise IrsaliyeHatasi("İrsaliyede kalem yok.")
    if transfer.to_account_id is None:
        raise IrsaliyeGirdiHatasi(
            "Şirket dışına sevk için alıcı hesap seçilmeli; irsaliye alıcısız düzenlenemez."
        )
    alici = await db.get(Account, transfer.to_account_id)
    if alici is None:
        raise IrsaliyeGirdiHatasi("Alıcı hesap bulunamadı.")
    depo = (
        await db.get(Warehouse, transfer.from_warehouse_id) if transfer.from_warehouse_id else None
    )
    yil, sira, no = numara or await numara_al(db, clock)
    bugun = yerel_bugun(clock)
    irs = Irsaliye(
        irsaliye_no=no,
        yil=yil,
        sira=sira,
        durum="DUZENLENDI",
        transfer_id=transfer.id,
        order_id=transfer.order_id,
        alici_account_id=alici.id,
        alici_unvan=alici.title,
        alici_vkn=alici.tax_no,
        alici_vergi_dairesi=alici.tax_office,
        alici_adres=await _alici_adresi(db, alici.id),
        hedef_konum=transfer.to_location_type,
        cikis_depo_id=depo.id if depo else None,
        cikis_depo_adi=depo.name if depo else None,
        duzenleme_tarihi=bugun,
        sevk_tarihi=transfer.shipped_at or bugun,
        teslim_eden=transfer.delivered_by,
        notlar=notlar if notlar is not None else transfer.notes,
        created_by=user_id,
        updated_by=user_id,
        kalemler=[
            IrsaliyeKalemi(
                sira=i,
                product_id=k.product_id,
                order_line_id=k.order_line_id,
                stock_movement_id=k.stock_movement_id,
                urun_kodu=k.urun_kodu,
                aciklama=k.aciklama[:300],
                miktar=k.miktar,
                birim=k.birim or "ADET",
                seri_nolar=", ".join(k.seri_nolar) or None,
                birim_fiyat=k.birim_fiyat,
                iskonto_yuzde=k.iskonto_yuzde,
                kdv_orani=k.kdv_orani,
            )
            for i, k in enumerate(kalemler, start=1)
        ],
    )
    db.add(irs)
    # Elle yazılan belge no yoksa transferin belge no'su irsaliye no olur.
    if not transfer.document_no:
        transfer.document_no = no
    await db.flush()
    await audit.log(
        db,
        "irsaliyeler",
        "olustur",
        entity_id=irs.id,
        new_value={
            "no": no,
            "transfer": transfer.transfer_no,
            "siparis": transfer.order_id,
            "kalem": len(kalemler),
        },
        user_id=user_id,
        ip=ip,
    )
    return irs


# --- Kapsam ve liste --------------------------------------------------------------


def kapsam_kosulu(stmt: Select, user: User) -> Select:
    """`KENDI_MUSTERILERI` kapsamı: yalnız kendi siparişinin irsaliyesi."""
    if user.role.scope == "KENDI_MUSTERILERI":
        kendi = select(Order.id).where(Order.owner_id == user.id)
        stmt = stmt.where(Irsaliye.order_id.in_(kendi))
    return stmt


@dataclass
class IrsaliyeSuzgeci:
    order_id: int | None = None
    transfer_id: int | None = None
    devir: str | None = None  # bekleyen | devredildi
    durum: str | None = None
    donem: str | None = None  # YYYY-AA (düzenleme tarihi)
    ara: str | None = None


def liste_sorgusu(user: User, s: IrsaliyeSuzgeci) -> Select:
    stmt = select(Irsaliye)
    if s.order_id is not None:
        stmt = stmt.where(Irsaliye.order_id == s.order_id)
    if s.transfer_id is not None:
        stmt = stmt.where(Irsaliye.transfer_id == s.transfer_id)
    if s.durum:
        stmt = stmt.where(Irsaliye.durum == s.durum)
    if s.devir:
        if s.devir not in DEVIR_DURUMLARI:
            raise IrsaliyeGirdiHatasi(f"Bilinmeyen devir durumu: {s.devir}")
        if s.devir == "bekleyen":
            stmt = stmt.where(Irsaliye.muhasebe_devri_at.is_(None), Irsaliye.durum == "DUZENLENDI")
        else:
            stmt = stmt.where(Irsaliye.muhasebe_devri_at.is_not(None))
    if s.donem:
        bas, bit = donem_araligi(s.donem)
        stmt = stmt.where(Irsaliye.duzenleme_tarihi >= bas, Irsaliye.duzenleme_tarihi < bit)
    if s.ara:
        desen = f"%{s.ara.strip()}%"
        stmt = stmt.where(or_(Irsaliye.irsaliye_no.ilike(desen), Irsaliye.alici_unvan.ilike(desen)))
    return kapsam_kosulu(stmt, user).order_by(Irsaliye.id.desc())


def donem_araligi(donem: str):
    from datetime import date, timedelta

    try:
        yil, ay = (int(p) for p in donem.split("-"))
        bas = date(yil, ay, 1)
    except (ValueError, TypeError) as exc:
        raise IrsaliyeGirdiHatasi("Dönem YYYY-AA biçiminde olmalı") from exc
    return bas, (bas + timedelta(days=32)).replace(day=1)


async def kapsamli_getir(db: AsyncSession, irsaliye_id: int, user: User) -> Irsaliye | None:
    return await db.scalar(kapsam_kosulu(select(Irsaliye).where(Irsaliye.id == irsaliye_id), user))


async def kullanici_adlari(db: AsyncSession, idler: set[int | None]) -> dict[int, str]:
    temiz = [i for i in idler if i is not None]
    if not temiz:
        return {}
    return dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(temiz)))).all())


def cikti(irs: Irsaliye, user: User, adlar: dict[int, str] | None = None) -> dict[str, Any]:
    """API çıktısı. Fiyat anahtarları yalnız `fiyat_gorur_mu` ile döner."""
    fiyat = fiyat_gorur_mu(user)
    adlar = adlar or {}
    kalemler = []
    for k in irs.kalemler:
        d: dict[str, Any] = {
            "id": k.id,
            "sira": k.sira,
            "product_id": k.product_id,
            "order_line_id": k.order_line_id,
            "urun_kodu": k.urun_kodu,
            "aciklama": k.aciklama,
            "miktar": k.miktar,
            "birim": k.birim,
            "seri_nolar": k.seri_nolar,
        }
        if fiyat:
            d.update(
                birim_fiyat=k.birim_fiyat, iskonto_yuzde=k.iskonto_yuzde, kdv_orani=k.kdv_orani
            )
        kalemler.append(d)
    return {
        "id": irs.id,
        "irsaliye_no": irs.irsaliye_no,
        "durum": irs.durum,
        "transfer_id": irs.transfer_id,
        "order_id": irs.order_id,
        "alici_account_id": irs.alici_account_id,
        "alici_unvan": irs.alici_unvan,
        "alici_vkn": irs.alici_vkn,
        "alici_adres": irs.alici_adres,
        "hedef_konum": irs.hedef_konum,
        "cikis_depo_adi": irs.cikis_depo_adi,
        "duzenleme_tarihi": irs.duzenleme_tarihi,
        "sevk_tarihi": irs.sevk_tarihi,
        "teslim_eden": irs.teslim_eden,
        "notlar": irs.notlar,
        "iptal_at": irs.iptal_at,
        "iptal_nedeni": irs.iptal_nedeni,
        "muhasebe_devri_at": irs.muhasebe_devri_at,
        "muhasebe_devreden": adlar.get(irs.muhasebe_devri_by or 0),
        "muhasebe_notu": irs.muhasebe_notu,
        "toplam_miktar": sum((Decimal(str(k.miktar)) for k in irs.kalemler), Decimal("0")),
        "fiyatli": fiyat and any(k.birim_fiyat is not None for k in irs.kalemler),
        "version": irs.version,
        "kalemler": kalemler,
    }


# --- İptal --------------------------------------------------------------------------


def _not(deger: str | None) -> str | None:
    metin = (deger or "").strip() or None
    if metin is not None and len(metin) > NOT_UZUNLUGU:
        raise IrsaliyeGirdiHatasi(f"Not en çok {NOT_UZUNLUGU} karakter olabilir")
    return metin


async def iptal_et(
    db: AsyncSession,
    irs: Irsaliye,
    *,
    neden: str,
    version: int,
    clock: Clock,
    user_id: int,
    ip: str | None = None,
) -> Irsaliye:
    """Belgeyi iptal eder; numara iptal olarak görünür kalır (boşluksuz).

    Stoğu GERİ ALMAZ: sevk edilen mal fiziken çıkmıştır; geri gelişi iade
    transferiyle kaydedilir. Muhasebeye devredilmiş irsaliye iptal edilemez
    (önce devir geri alınır)."""
    metin = _not(neden)
    if metin is None:
        raise IrsaliyeGirdiHatasi("İptal nedeni zorunlu")
    if version != irs.version:
        raise IrsaliyeHatasi("Bu kaydı siz görüntülerken başka biri değiştirdi. Sayfayı yenileyin.")
    if irs.durum == "IPTAL":
        raise IrsaliyeHatasi("İrsaliye zaten iptal edilmiş.")
    if irs.muhasebe_devri_at is not None:
        raise IrsaliyeHatasi(
            "Muhasebeye devredilmiş irsaliye iptal edilemez; önce devri geri alın."
        )
    irs.durum = "IPTAL"
    irs.iptal_at = clock.now()
    irs.iptal_by = user_id
    irs.iptal_nedeni = metin
    irs.updated_by = user_id
    await db.flush()
    await audit.log(
        db,
        "irsaliyeler",
        "iptal",
        entity_id=irs.id,
        new_value={"no": irs.irsaliye_no, "neden": metin},
        user_id=user_id,
        ip=ip,
    )
    return irs


# --- Muhasebe devri (S4.4; fatura devri kalıbı) --------------------------------------


async def devret(
    db: AsyncSession,
    user: User,
    idler: list[int],
    *,
    not_: str | None,
    clock: Clock,
    ip: str | None = None,
) -> list[int]:
    """Toplu "muhasebeye devredildi". Biri uygun değilse TAMAMI 409."""
    temiz = sorted({int(i) for i in idler})
    if not temiz:
        raise IrsaliyeGirdiHatasi("En az bir irsaliye seçilmeli")
    if len(temiz) > AZAMI_TOPLU:
        raise IrsaliyeGirdiHatasi(f"Tek seferde en çok {AZAMI_TOPLU} kayıt işaretlenebilir")
    metin = _not(not_)
    kayitlar = (
        await db.scalars(
            kapsam_kosulu(select(Irsaliye).where(Irsaliye.id.in_(temiz)), user).with_for_update()
        )
    ).all()
    uygun = {i.id: i for i in kayitlar if i.durum == "DUZENLENDI" and i.muhasebe_devri_at is None}
    sorunlu = [i for i in temiz if i not in uygun]
    if sorunlu:
        raise IrsaliyeHatasi(
            "Seçilen irsaliyelerin bazıları devre uygun değil (iptal, zaten devredilmiş ya "
            "da bulunamadı); hiçbiri işaretlenmedi",
            sorunlu=sorunlu,
        )
    simdi = clock.now()
    for i in temiz:
        irs = uygun[i]
        irs.muhasebe_devri_at = simdi
        irs.muhasebe_devri_by = user.id
        irs.muhasebe_notu = metin
        irs.updated_by = user.id
        await audit.log(
            db,
            "irsaliyeler",
            "muhasebe.devredildi",
            entity_id=irs.id,
            new_value={"no": irs.irsaliye_no, "not": metin},
            user_id=user.id,
            ip=ip,
        )
    await db.flush()
    return temiz


async def devri_geri_al(
    db: AsyncSession, user: User, irs: Irsaliye, *, gerekce: str, ip: str | None = None
) -> Irsaliye:
    metin = _not(gerekce)
    if metin is None:
        raise IrsaliyeGirdiHatasi("Geri alma gerekçesi zorunlu")
    if irs.muhasebe_devri_at is None:
        raise IrsaliyeHatasi("İrsaliye muhasebeye devredilmemiş", sorunlu=[irs.id])
    eski = {
        "muhasebe_devri_at": irs.muhasebe_devri_at.isoformat(),
        "muhasebe_devri_by": irs.muhasebe_devri_by,
        "muhasebe_notu": irs.muhasebe_notu,
    }
    irs.muhasebe_devri_at = None
    irs.muhasebe_devri_by = None
    irs.muhasebe_notu = None
    irs.updated_by = user.id
    await db.flush()
    await audit.log(
        db,
        "irsaliyeler",
        "muhasebe.geri_al",
        entity_id=irs.id,
        old_value=eski,
        new_value={"no": irs.irsaliye_no, "gerekce": metin},
        user_id=user.id,
        ip=ip,
    )
    return irs


def cari_kodu(account_id: int | None, dis_referans: str | None) -> str:
    """Logo cari kodu: hesabın dış referansı (Logo kodu girilmişse), yoksa
    ERP kimliğinden türetilen sabit kod. Logo'da eşleme bu kodla yapılır."""
    if dis_referans:
        return dis_referans
    return f"CR{account_id:06d}" if account_id else ""


def tarih_metni(an: datetime | None) -> str | None:
    from app.services.teknik_servis.yerel_zaman import yerel_an

    return yerel_an(an).strftime("%d.%m.%Y %H:%M") if an else None


# --- PDF ----------------------------------------------------------------------------


async def pdf_baglami(db: AsyncSession, irs: Irsaliye, *, fiyatli: bool) -> dict[str, Any]:
    """`templates/irsaliye.html` bağlamı. `fiyatli` çağıranda yetkiyle süzülür."""
    from app.services.belgeler import _sade, ayar_haritasi, firma_bilgisi
    from app.services.pdf import tl

    siparis = await db.get(Order, irs.order_id) if irs.order_id else None
    transfer = await db.get(Transfer, irs.transfer_id)
    fiyat_var = fiyatli and any(k.birim_fiyat is not None for k in irs.kalemler)
    kalemler = []
    for k in irs.kalemler:
        d: dict[str, Any] = {
            "sira": k.sira,
            "kod": k.urun_kodu or "",
            "aciklama": k.aciklama,
            "miktar": _sade(k.miktar),
            "birim": BIRIM_ADLARI.get(k.birim, k.birim),
            "seri_nolar": k.seri_nolar,
        }
        if fiyat_var and k.birim_fiyat is not None:
            d["birim_fiyat"] = tl(k.birim_fiyat)
            d["iskonto"] = _sade(k.iskonto_yuzde or 0)
            d["kdv"] = _sade(Decimal(str(k.kdv_orani or 0)) * 100)
        kalemler.append(d)
    return {
        "irs": irs,
        "baslik": "SEVK İRSALİYESİ",
        "duzenleme_tarihi": irs.duzenleme_tarihi.strftime("%d.%m.%Y"),
        "sevk_tarihi": irs.sevk_tarihi.strftime("%d.%m.%Y"),
        "hedef": HEDEF_ADLARI.get(irs.hedef_konum, irs.hedef_konum),
        "siparis_no": siparis.order_no if siparis else None,
        "transfer_no": transfer.transfer_no if transfer else None,
        "kalemler": kalemler,
        "fiyatli": fiyat_var,
        "toplam_miktar": _sade(sum((Decimal(str(k.miktar)) for k in irs.kalemler), Decimal("0"))),
        "iptal": irs.durum == "IPTAL",
        "firma": firma_bilgisi(await ayar_haritasi(db)),
    }


async def pdf_uret(db: AsyncSession, irs: Irsaliye, *, fiyatli: bool) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async("irsaliye.html", **await pdf_baglami(db, irs, fiyatli=fiyatli))
