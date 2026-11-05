"""Teklif iş kuralları: versiyonlama, hesaplama, onay ve karar.

**Dalga 2 (TS-140…148): birimli (teknik servis) teklif.** Satış teklifi
(`birim IS NULL`) canlı akışıyla AYNEN sürer; birim dolu teklifte şunlar
devreye girer:

- **Kapsam (TS-140):** `teklif_kapsami` okuma süzgecidir (KENDI_MUSTERILERI =
  kendi teklifleri, KENDI_BIRIMI/KENDI_ISLERI = `birim ∈ user_units`,
  bilinmeyen kapsam = RED). Yazma ayrıca `teklif_yazilabilir_mi` ister:
  birimli teklife yalnız servis rolü ya da birim üyesi, birimsiz (satış)
  teklife yalnız servis DIŞI rol yazar (E07 kontrol B4). Aksi 404 — kayıt
  yokmuş gibi; kapsam dışı yazma hiçbir şey değiştirmez.
- **Makine (TS-141):** birimli teklifte her durum değişikliği `TEKLIF`
  makinesinden geçer (`gecis`). Satış uçları makineye bağlanmadı: canlı
  `karar` ucu TASLAK→KABUL'e izin veriyor ve bunu kısıtlamak kabul edilmiş
  satış akışını değiştirmek olurdu (kontrol: "satış uçlarına doğrulamasız
  durum_degistir eklenmez"). Durum geçmişi `audit_logs`'tan okunur (K16).
- **İç onay:** TASLAK → ONAY_BEKLIYOR → ONAYLANDI; öz-onay yasağı ayardan
  (`teklif_oz_onay_yasak`). İç onay iskonto eşiği onayını da kapsar (K4);
  satış iskonto onayı ucu birimli teklifte 409'dur (yan kapı, kontrol B2).
- **Karar yalnız güncel ve karar verilebilir sürümde (E07-D01):** eski
  sürümün linki görüntülenir ama karar almaz.
- **"Süresi doldu" HESAPLANIR, yazılmaz** (`etkin_durum`, K7): worker'a
  bağlamak satış tekliflerinin verisini sessizce değiştirirdi.

Fiyat ve adet 2 haneye yuvarlanır (E07-03, K8): DB zaten 2 hane saklıyor;
yuvarlama hesabı DB ile hizalar. Bu kural `kalem_alanlari` üzerinden sipariş
kalemlerini de etkiler (aynı kuruş farkı kapanır; sürüm notu).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    exists,
    false,
    func,
    or_,
    select,
)
from sqlalchemy.orm.attributes import flag_modified

from app.clock import Clock
from app.models import (
    Account,
    Address,
    AuditLog,
    Contact,
    Product,
    Quote,
    QuoteLine,
    QuoteSend,
    QuoteVersion,
    ServiceOrder,
    User,
)
from app.models.quote import BIRIMLI_KALEM_ACIKLAMA_UZUNLUGU, KALEM_TIPLERI, TEKLIF_IS_TURLERI
from app.models.rbac import BIRIM_KODLARI
from app.permissions import (
    SCOPE_ALL,
    SCOPE_OWN_CUSTOMERS,
    SCOPE_OWN_JOBS,
    SCOPE_OWN_UNITS,
    SERVIS_ROLLERI,
)
from app.services import audit, sirketler
from app.services import settings as ayar_svc
from app.services.statemachine import TEKLIF, IzinsizGecis

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

KURUS = Decimal("0.01")


def yuvarla(d: Decimal) -> Decimal:
    return d.quantize(KURUS, rounding=ROUND_HALF_UP)


class TeklifKilitli(Exception):
    """Gönderilmiş versiyon değiştirilemez; revizyon yeni versiyon açar."""


# --- Dalga 2: hata sınıfları (API eşlemesi a/quotes.py) ----------------------------


class TeklifGirdiHatasi(ValueError):
    """Girdi hatası → 400 (KDV listesi, geçmiş geçerlilik, eksik kur, neden ...)."""


class TeklifKuralHatasi(ValueError):
    """İş kuralı / durum ihlali → 409."""


class TeklifYetkiHatasi(PermissionError):
    """Gövdedeki ikinci, daha dar izin yok ya da öz-onay → 403."""


class TeklifKapsamDisi(LookupError):
    """Kayıt (ya da gövdedeki referans) kullanıcının kapsamı dışında → 404."""


# --- Dalga 2: sabitler ------------------------------------------------------------

# Birimli teklifte KDV beyaz listesi (E07-03; ayar değil kod sabiti — plan §1.9
# DEFAULTS'a girmedi). Satış teklifinin girdi kuralı DEĞİŞMEZ (K8).
BIRIMLI_KDV_ORANLARI = (Decimal("0"), Decimal("0.01"), Decimal("0.10"), Decimal("0.20"))
# E-posta alıcı sınırı (E07-06; `ck_qsend_alici_sayisi` ile aynı).
AZAMI_ALICI = 3
SATIS_KALEM_ACIKLAMA_UZUNLUGU = 300
NEDEN_ASGARI = 5
# Müşteri kararı bekleyen durumlar: "süresi doldu" bunlarda hesaplanır, public
# link yalnız bunlarda karar alır.
KARAR_BEKLEYEN = ("GONDERILDI", "GORUNTULENDI", "REVIZE_EDILDI")
# Birimli teklifte yeniden gönderim serbest durumlar (durum değişmez).
YENIDEN_GONDERILEBILIR = ("GONDERILDI", "GORUNTULENDI")
KABUL_DURUMLARI = ("KABUL", "SIPARISE_DONUSTU")

KPI_KODLARI = (
    "onay_bekleyen",
    "onayli_gonderilmedi",
    "musteri_yaniti_bekleyen",
    "suresi_yaklasan",
    "suresi_dolan",
    "bu_ay_kabul",
)
KPI_ADLARI = {
    "onay_bekleyen": "Onay Bekliyor",
    "onayli_gonderilmedi": "Onaylı, Gönderilmedi",
    "musteri_yaniti_bekleyen": "Müşteri Yanıtı Bekleniyor",
    "suresi_yaklasan": "Süresi Yaklaşan",
    "suresi_dolan": "Süresi Dolan",
    "bu_ay_kabul": "Bu Ay Kabul",
}

DURUM_ADLARI = {
    "TASLAK": "Taslak",
    "ONAY_BEKLIYOR": "Onay Bekliyor",
    "ONAYLANDI": "Onaylandı",
    "GONDERILDI": "Gönderildi",
    "GORUNTULENDI": "Görüntülendi",
    "REVIZE_EDILDI": "Revize Edildi",
    "KABUL": "Kabul",
    "RED": "Ret",
    "SURESI_DOLDU": "Süresi Doldu",
    "SIPARISE_DONUSTU": "Siparişe Dönüştü",
    "IPTAL": "İptal",
}


def kalem_topla(qty: Decimal, unit_price: Decimal, discount_pct: Decimal) -> Decimal:
    """İskonto kalem bazında uygulanır."""
    brut = Decimal(str(qty)) * Decimal(str(unit_price))
    return yuvarla(brut * (Decimal("1") - Decimal(str(discount_pct)) / Decimal("100")))


async def versiyon_hesapla(db: AsyncSession, versiyon: QuoteVersion) -> QuoteVersion:
    """Kalemlerden versiyon toplamlarını yeniden hesaplar.

    KDV kalem bazında hesaplanır (oranlar kalemde dondurulmuştur); tek bir
    genel oran uygulamak farklı KDV'li kalemleri olan teklifleri bozardı.
    """
    kalemler = (
        await db.scalars(select(QuoteLine).where(QuoteLine.version_id == versiyon.id))
    ).all()

    ara = Decimal("0")
    iskonto = Decimal("0")
    kdv = Decimal("0")
    en_yuksek_iskonto = Decimal("0")

    for k in kalemler:
        brut = Decimal(str(k.qty)) * Decimal(str(k.unit_price))
        net = kalem_topla(k.qty, k.unit_price, k.discount_pct)
        k.line_total = net
        ara += brut
        iskonto += brut - net
        kdv += yuvarla(net * Decimal(str(k.vat_rate)))
        en_yuksek_iskonto = max(en_yuksek_iskonto, Decimal(str(k.discount_pct)))

    versiyon.subtotal = yuvarla(ara)
    versiyon.discount_total = yuvarla(iskonto)
    versiyon.vat_total = yuvarla(kdv)
    versiyon.grand_total = yuvarla(ara - iskonto + kdv)
    versiyon.max_discount_pct = en_yuksek_iskonto
    await db.flush()
    return versiyon


async def onay_gerekiyor_mu(db: AsyncSession, versiyon: QuoteVersion) -> bool:
    """Eşik üstü iskonto satış müdürü onayına düşer (brief §4.9)."""
    esik = Decimal(str(await ayar_svc.get(db, "iskonto_onay_esigi_yuzde")))
    return Decimal(str(versiyon.max_discount_pct)) > esik


async def yeni_versiyon(
    db: AsyncSession, teklif: Quote, *, clock: Clock, kaynak: QuoteVersion | None = None
) -> QuoteVersion:
    """Yeni versiyon açar; öncekini KİLİTLER ve kalemleri kopyalar.

    Kopyalama fiyatları da taşır — revizyon yaparken ürün kartındaki güncel
    fiyat değil, müşteriye gösterilen fiyat esastır. Kalemin servis işi bağı
    da kopyalanır (bulgu teklifinin revizyonu aynı işlere bağlı kalır).
    """
    son_no = (
        await db.scalar(
            select(func.coalesce(func.max(QuoteVersion.version_no), 0)).where(
                QuoteVersion.quote_id == teklif.id
            )
        )
        or 0
    )
    if kaynak is not None:
        kaynak.is_locked = True

    gecerlilik_gun = int(await ayar_svc.get(db, "teklif_varsayilan_gecerlilik_gun"))
    yeni = QuoteVersion(
        quote_id=teklif.id,
        version_no=son_no + 1,
        currency=kaynak.currency if kaynak else "TRY",
        fx_rate=kaynak.fx_rate if kaynak else None,
        fx_date=kaynak.fx_date if kaynak else None,
        fx_source=kaynak.fx_source if kaynak else None,
        valid_until=(clock.now().date() + timedelta(days=gecerlilik_gun)),
        public_token=secrets.token_urlsafe(24),
    )
    db.add(yeni)
    await db.flush()

    if kaynak is not None:
        for k in (
            await db.scalars(select(QuoteLine).where(QuoteLine.version_id == kaynak.id))
        ).all():
            db.add(
                QuoteLine(
                    version_id=yeni.id,
                    item_type=k.item_type,
                    product_id=k.product_id,
                    description=k.description,
                    qty=k.qty,
                    unit_price=k.unit_price,
                    discount_pct=k.discount_pct,
                    vat_rate=k.vat_rate,
                    sort_order=k.sort_order,
                    service_order_id=k.service_order_id,
                )
            )
        await db.flush()
        await versiyon_hesapla(db, yeni)

    teklif.current_version_id = yeni.id
    await db.flush()
    return yeni


async def urun_kaleminden(
    db: AsyncSession, product_id: int, qty: Decimal, *, iskonto: Decimal = Decimal("0")
) -> dict:
    """Ürün kartından kalem verisi üretir; fiyat ve KDV DONDURULUR."""
    urun = await db.get(Product, product_id)
    if urun is None:
        raise ValueError(f"Ürün bulunamadı: {product_id}")
    varsayilan_kdv = Decimal(str(await ayar_svc.get(db, "kdv_oran_varsayilan")))
    return {
        "item_type": "URUN",
        "product_id": urun.id,
        "description": urun.name,
        "qty": qty,
        "unit_price": Decimal(str(urun.list_price or 0)),
        "discount_pct": iskonto,
        "vat_rate": Decimal(str(urun.vat_rate)) if urun.vat_rate else varsayilan_kdv,
    }


def _iki_hane(veri: dict) -> dict:
    """Fiyat ve adedi DB'nin sakladığı 2 haneye indirir (E07-03).

    `Numeric(14,2)` 33,333'ü 33,33 saklıyordu ama hesap kimlik haritasındaki
    33,333 ile yapılıyordu: iskontosuz teklifte 1 kuruşluk "iskonto" doğuyordu.
    """
    veri["qty"] = yuvarla(Decimal(str(veri["qty"])))
    veri["unit_price"] = yuvarla(Decimal(str(veri["unit_price"])))
    return veri


async def kalem_alanlari(
    db: AsyncSession,
    *,
    item_type: str,
    product_id: int | None,
    description: str | None,
    qty: Decimal,
    unit_price: Decimal | None,
    discount_pct: Decimal,
    vat_rate: Decimal | None,
) -> dict:
    """Bir belge kaleminin DONDURULACAK alanlarını üretir.

    Teklif ve sipariş kalemleri aynı kurallara tabi (plan §3.3/2), bu yüzden
    tek yerde durur: ürün kartı varsayılanları taban alınır, elle verilen
    değerler onu geçersiz kılar, ürünsüz kalemde açıklama ve fiyat zorunludur.
    """
    if item_type not in KALEM_TIPLERI:
        raise ValueError(f"Kalem tipi {KALEM_TIPLERI} içinden olmalı")

    if product_id:
        veri = await urun_kaleminden(db, product_id, qty, iskonto=discount_pct)
        veri["item_type"] = item_type
        if unit_price is not None:
            veri["unit_price"] = unit_price
        if description:
            veri["description"] = description
        if vat_rate is not None:
            veri["vat_rate"] = vat_rate
        return _iki_hane(veri)

    if unit_price is None or not description:
        raise ValueError("Ürünsüz kalemde açıklama ve birim fiyat zorunludur")
    varsayilan_kdv = Decimal(str(await ayar_svc.get(db, "kdv_oran_varsayilan")))
    return _iki_hane(
        {
            "item_type": item_type,
            "product_id": None,
            "description": description,
            "qty": qty,
            "unit_price": unit_price,
            "discount_pct": discount_pct,
            "vat_rate": vat_rate if vat_rate is not None else varsayilan_kdv,
        }
    )


async def suresi_dolanlari_isaretle(db: AsyncSession, clock: Clock) -> int:
    """Geçerlilik tarihi geçen teklifleri SURESI_DOLDU yapar.

    Kabul edilmiş veya siparişe dönmüş teklifler etkilenmez — geçmişe dönük
    bir süre dolması, tamamlanmış işi geçersiz göstermek olurdu. Birimli
    teklif işaretlenmez: onlarda "süresi doldu" yalnız hesaplanır (K7) ve
    `TEKLIF` makinesinde SURESI_DOLDU durumu yoktur.
    """
    bugun = clock.now().date()
    teklifler = (
        await db.execute(
            select(Quote, QuoteVersion)
            .join(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
            .where(
                Quote.is_deleted.is_(False),
                Quote.birim.is_(None),
                Quote.status.in_(("GONDERILDI", "GORUNTULENDI", "REVIZE_EDILDI")),
                QuoteVersion.valid_until.is_not(None),
                QuoteVersion.valid_until < bugun,
            )
        )
    ).all()
    for teklif, _ in teklifler:
        teklif.status = "SURESI_DOLDU"
    await db.flush()
    return len(teklifler)


async def karar_ver(
    db: AsyncSession,
    versiyon: QuoteVersion,
    *,
    kabul: bool,
    clock: Clock,
    kanal: str,
    red_nedeni: str | None = None,
) -> Quote:
    """Kabul veya red kaydeder.

    `kanal` LİNK ise müşteri kendi tıkladı, ELLE ise ekip işaretledi — ikisi
    aynı kanıt değeri taşımaz, bu yüzden ayrı tutulur.
    """
    simdi = clock.now()
    teklif = await db.get(Quote, versiyon.quote_id)
    if kabul:
        versiyon.accepted_at = simdi
        teklif.status = "KABUL"
    else:
        versiyon.rejected_at = simdi
        versiyon.reject_reason = red_nedeni
        teklif.status = "RED"
        teklif.lost_reason = red_nedeni
    versiyon.decision_channel = kanal
    versiyon.is_locked = True
    await db.flush()
    return teklif


def public_url(taban: str, token: str) -> str:
    return f"{taban.rstrip('/')}/teklif/{token}"


# =====================================================================================
# Dalga 2 — birimli (teknik servis) teklif
# =====================================================================================


def birimli_mi(t: Quote) -> bool:
    return t.birim is not None


def _rol_kodu(user: User) -> str | None:
    return user.role.code if user.role is not None else None


def _kapsam(user: User) -> str | None:
    return user.role.scope if user.role is not None else None


def servis_rolu_mu(user: User) -> bool:
    return _rol_kodu(user) in SERVIS_ROLLERI


def _admin_mu(user: User) -> bool:
    return _rol_kodu(user) == "ADMIN"


def kullanici_birimleri(user: User) -> frozenset[str]:
    """Üyesi olduğu birimler ∩ etkin şirketin birimleri (tek kaynak kapsam.py)."""
    from app.services.teknik_servis import kapsam

    return kapsam.kullanici_birimleri(user)


def _sirket_kosulu(user: User) -> ColumnElement[bool] | None:
    """Şirket ayrımı (KARARLAR 2026-11-04 §1); None = süzgeç yok.

    Birimli (servis) teklif etkin şirketin birimlerinde olmalı; birimsiz
    (satış/mobilite) teklif yalnız DENGE MOBİLİTE etkinken görünür — teklif
    ekranı iki modülün ortak ucu olduğu için kapı yönlendiricide değil burada.
    """
    birimler = sirketler.etkin_birimler(user)
    if birimler is None:
        return None
    birimli = Quote.birim.in_(sorted(birimler)) if birimler else false()
    if sirketler.mobilite_acik_mi(user):
        return or_(Quote.birim.is_(None), birimli)
    return birimli


def _sirket_disinda_mi(user: User, t: Quote) -> bool:
    birimler = sirketler.etkin_birimler(user)
    if birimler is None:
        return False
    if t.birim is None:
        return not sirketler.mobilite_acik_mi(user)
    return t.birim not in birimler


def bugun_yerel(clock: Clock) -> date:
    from app.services.teknik_servis.yerel_zaman import yerel_bugun

    return yerel_bugun(clock)


# --- Kapsam (TS-140) -----------------------------------------------------------------


def _kapsam_kosulu(user: User) -> ColumnElement[bool] | None:
    """`quotes` satırına okuma koşulu; None = süzgeç yok (TUMU)."""
    kapsam = _kapsam(user)
    if kapsam == SCOPE_ALL:
        return None
    if kapsam == SCOPE_OWN_CUSTOMERS:
        # Satış temsilcisi kendi tekliflerini VE kendi müşterilerinin tekliflerini
        # (ör. satış destek'in hazırladığı servis teklifi) görür — rol testi tur 2
        # O12 (KARARLAR 2026-11-04 §7.8). Yazma yalnız kendi teklifinde kalır
        # (`teklif_yazilabilir_mi`); şirket süzgeci ayrıca uygulanır.
        from app.services.accounts import kendi_hesaplari

        return or_(Quote.owner_id == user.id, Quote.customer_id.in_(kendi_hesaplari(user)))
    if kapsam in (SCOPE_OWN_UNITS, SCOPE_OWN_JOBS):
        # Birimsiz satış teklifleri birimli kullanıcıya GÖRÜNMEZ (E07-02).
        birimler = kullanici_birimleri(user)
        if not birimler:
            return false()
        return Quote.birim.in_(sorted(birimler))
    # Bilinmeyen kapsam dizesi = red (E07-D05).
    return false()


def teklif_kapsami(stmt: Select, user: User) -> Select:
    """Liste, KPI, Excel ve uyarı aynı süzgeci kullanır (sayı = sızıntı)."""
    for kosul in (_kapsam_kosulu(user), _sirket_kosulu(user)):
        if kosul is not None:
            stmt = stmt.where(kosul)
    return stmt


def teklif_kapsam_disinda_mi(user: User, t: Quote) -> bool:
    """`teklif_kapsami`'nın tek kayıt karşılığı (aynı kural)."""
    if _sirket_disinda_mi(user, t):
        return True
    kapsam = _kapsam(user)
    if kapsam == SCOPE_ALL:
        return False
    if kapsam == SCOPE_OWN_CUSTOMERS:
        return t.owner_id != user.id
    if kapsam in (SCOPE_OWN_UNITS, SCOPE_OWN_JOBS):
        return t.birim is None or t.birim not in kullanici_birimleri(user)
    return True


def birimli_yazabilir_mi(user: User, birim: str) -> bool:
    """Birimli teklife yazma: ADMIN, servis rolü ya da o birimin üyesi (B4)."""
    return _admin_mu(user) or servis_rolu_mu(user) or birim in kullanici_birimleri(user)


def satis_yazabilir_mi(user: User) -> bool:
    """Birimsiz (satış) teklife yazma: servis rolü YETMEZ (B4)."""
    return _admin_mu(user) or not servis_rolu_mu(user)


def teklif_yazilabilir_mi(user: User, t: Quote) -> bool:
    if teklif_kapsam_disinda_mi(user, t):
        return False
    return birimli_yazabilir_mi(user, t.birim) if t.birim else satis_yazabilir_mi(user)


async def teklif_al(db: AsyncSession, teklif_id: int, user: User, *, yazma: bool = False) -> Quote:
    """`db.get` → `is_deleted` → kapsam (→ yazma) sırası; aksi `TeklifKapsamDisi`.

    Canlıda `revize/iskonto-onayla/pdf/gonder/karar` uçları kapsamı hiç
    sormuyordu (G1) ve bazıları silinmiş teklifi de işliyordu. Kontrol
    YAZMADAN önce yapılır.
    """
    t = await db.get(Quote, teklif_id)
    if t is None or t.is_deleted:
        raise TeklifKapsamDisi("Teklif bulunamadı")
    if await teklif_erisimi_yok_mu(db, user, t):
        raise TeklifKapsamDisi("Teklif bulunamadı")
    if yazma and not teklif_yazilabilir_mi(user, t):
        raise TeklifKapsamDisi("Teklif bulunamadı")
    return t


async def teklif_erisimi_yok_mu(db: AsyncSession, user: User, t: Quote) -> bool:
    """OKUMA için tek kayıt kapsamı (`teklif_kapsami` ile aynı kural).

    `teklif_kapsam_disinda_mi` senkron ve dardır (KENDI_MUSTERILERI'de yalnız
    kendi teklifi — yazma kuralı); okumada satış temsilcisi kendi müşterisinin
    teklifini de görür (rol testi tur 2 O12)."""
    if not teklif_kapsam_disinda_mi(user, t):
        return False
    if _sirket_disinda_mi(user, t) or _kapsam(user) != SCOPE_OWN_CUSTOMERS:
        return True
    from app.services import accounts

    return await accounts.kapsam_disinda_mi(db, user, t.customer_id)


# --- Etkin durum ve KPI süzgeçleri (TS-148) ---------------------------------------------


def etkin_durum(t: Quote, v: QuoteVersion | None, bugun: date) -> str:
    """Hesaplanan durum: karar bekleyen ve geçerliliği geçmiş teklif SURESI_DOLDU."""
    if (
        t.status in KARAR_BEKLEYEN
        and v is not None
        and v.valid_until is not None
        and v.valid_until < bugun
    ):
        return "SURESI_DOLDU"
    return t.status


def etkin_durum_ifadesi(bugun: date) -> ColumnElement[str]:
    """`etkin_durum`'un SQL karşılığı (sorgu `QuoteVersion` güncel sürümle birleşik)."""
    return case(
        (
            and_(
                Quote.status.in_(KARAR_BEKLEYEN),
                QuoteVersion.valid_until.is_not(None),
                QuoteVersion.valid_until < bugun,
            ),
            "SURESI_DOLDU",
        ),
        else_=Quote.status,
    )


def sonraki_durumlar(t: Quote, v: QuoteVersion | None, bugun: date) -> list[str]:
    """Birimli teklifte makinenin izin verdiği hedefler (eylem düğmeleri buradan).

    Süresi dolmuş teklifte KABUL/RED sunulmaz (karar 409 olurdu); satış
    teklifinde makine zorlanmadığı için boş döner.
    """
    if not birimli_mi(t):
        return []
    hedefler = set(TEKLIF.sonraki(t.status))
    if etkin_durum(t, v, bugun) == "SURESI_DOLDU":
        hedefler -= {"KABUL", "RED"}
    return sorted(hedefler)


def _ay_araligi(bugun: date) -> tuple[datetime, datetime]:
    from app.services.teknik_servis.yerel_zaman import yerel_gun_araligi

    ilk = bugun.replace(day=1)
    sonraki = (ilk + timedelta(days=32)).replace(day=1)
    return yerel_gun_araligi(ilk)[0], yerel_gun_araligi(sonraki)[0]


def filtre_ifadesi(kod: str, bugun: date, takip_gun: int) -> ColumnElement[bool]:
    """KPI kutusu = liste süzgeci (TEK kaynak; E07-18). Sorgu güncel sürümle birleşik."""
    gecerli = or_(QuoteVersion.valid_until.is_(None), QuoteVersion.valid_until >= bugun)
    if kod == "onay_bekleyen":
        return Quote.status == "ONAY_BEKLIYOR"
    if kod == "onayli_gonderilmedi":
        return Quote.status == "ONAYLANDI"
    if kod == "musteri_yaniti_bekleyen":
        return and_(Quote.status.in_(KARAR_BEKLEYEN), gecerli)
    if kod == "suresi_yaklasan":
        return and_(
            Quote.status.in_(KARAR_BEKLEYEN),
            QuoteVersion.valid_until >= bugun,
            QuoteVersion.valid_until <= bugun + timedelta(days=takip_gun),
        )
    if kod == "suresi_dolan":
        return etkin_durum_ifadesi(bugun) == "SURESI_DOLDU"
    if kod == "bu_ay_kabul":
        bas, bit = _ay_araligi(bugun)
        return and_(
            Quote.status.in_(KABUL_DURUMLARI),
            QuoteVersion.accepted_at >= bas,
            QuoteVersion.accepted_at < bit,
        )
    raise TeklifGirdiHatasi(f"Bilinmeyen KPI: {kod}")


@dataclass
class TeklifFiltresi:
    """Liste, özet ve Excel'in ortak süzgeci (aynı ifade → aynı sayı)."""

    durum: str | None = None
    musteri_id: int | None = None
    tur: str | None = None  # SATIS | SERVIS
    birim: str | None = None
    kpi: str | None = None
    tarih_bas: date | None = None
    tarih_bit: date | None = None
    tarih_alani: str = "olusturma"  # olusturma | gonderim
    servis_isi_id: int | None = None
    hazirlayan_id: int | None = None
    q: str | None = None
    idler: list[int] = field(default_factory=list)


def _filtre_dogrula(f: TeklifFiltresi) -> None:
    if f.tur is not None and f.tur not in ("SATIS", "SERVIS"):
        raise TeklifGirdiHatasi("Tür SATIS ya da SERVIS olmalı")
    if f.birim is not None and f.birim not in BIRIM_KODLARI:
        raise TeklifGirdiHatasi(f"Bilinmeyen birim: {f.birim}")
    if f.kpi is not None and f.kpi not in KPI_KODLARI:
        raise TeklifGirdiHatasi(f"Bilinmeyen KPI: {f.kpi}")
    if f.durum is not None and f.durum not in DURUM_ADLARI:
        raise TeklifGirdiHatasi(f"Bilinmeyen durum: {f.durum}")
    if f.tarih_alani not in ("olusturma", "gonderim"):
        raise TeklifGirdiHatasi("Tarih alanı olusturma ya da gonderim olmalı")
    if f.tarih_bas and f.tarih_bit and f.tarih_bas > f.tarih_bit:
        raise TeklifGirdiHatasi("Başlangıç tarihi bitişten sonra olamaz")


def liste_sorgusu(
    user: User, f: TeklifFiltresi, bugun: date, takip_gun: int, *, kpi_haric: bool = False
) -> Select:
    """`select(Quote)` + güncel sürüm birleşimi + kapsam + süzgeçler."""
    from app.services.teknik_servis.yerel_zaman import yerel_gun_araligi

    _filtre_dogrula(f)
    stmt = (
        select(Quote)
        .outerjoin(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
        .where(Quote.is_deleted.is_(False))
    )
    stmt = teklif_kapsami(stmt, user)
    if f.tur == "SATIS":
        stmt = stmt.where(Quote.birim.is_(None))
    elif f.tur == "SERVIS":
        stmt = stmt.where(Quote.birim.is_not(None))
    if f.birim:
        stmt = stmt.where(Quote.birim == f.birim)
    if f.durum:
        stmt = stmt.where(etkin_durum_ifadesi(bugun) == f.durum)
    if f.musteri_id:
        stmt = stmt.where(Quote.customer_id == f.musteri_id)
    if f.hazirlayan_id:
        stmt = stmt.where(Quote.owner_id == f.hazirlayan_id)
    if f.servis_isi_id:
        stmt = stmt.where(
            or_(
                Quote.service_order_id == f.servis_isi_id,
                exists().where(
                    QuoteLine.version_id == Quote.current_version_id,
                    QuoteLine.service_order_id == f.servis_isi_id,
                ),
            )
        )
    if f.q:
        desen = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(
                Quote.quote_no.ilike(desen),
                Quote.title.ilike(desen),
                exists().where(Account.id == Quote.customer_id, Account.title.ilike(desen)),
            )
        )
    alan = Quote.created_at if f.tarih_alani == "olusturma" else QuoteVersion.sent_at
    if f.tarih_bas:
        stmt = stmt.where(alan >= yerel_gun_araligi(f.tarih_bas)[0])
    if f.tarih_bit:
        stmt = stmt.where(alan < yerel_gun_araligi(f.tarih_bit)[1])
    if f.idler:
        stmt = stmt.where(Quote.id.in_(f.idler))
    if f.kpi and not kpi_haric:
        stmt = stmt.where(filtre_ifadesi(f.kpi, bugun, takip_gun))
    return stmt.order_by(Quote.id.desc())


async def ozet(db: AsyncSession, user: User, f: TeklifFiltresi, clock: Clock) -> dict[str, int]:
    """KPI kutuları: her sayı listenin `kpi=<kod>` süzgeciyle AYNI ifade."""
    bugun = bugun_yerel(clock)
    takip = int(await ayar_svc.get(db, "teklif_takip_uyari_gun"))
    taban = liste_sorgusu(user, f, bugun, takip, kpi_haric=True).order_by(None)
    sonuc: dict[str, int] = {}
    for kod in KPI_KODLARI:
        alt = taban.where(filtre_ifadesi(kod, bugun, takip)).subquery()
        sonuc[kod] = int(await db.scalar(select(func.count()).select_from(alt)) or 0)
    return sonuc


# --- Durum geçişi (TS-141) ---------------------------------------------------------


async def gecis(
    db: AsyncSession,
    t: Quote,
    hedef: str,
    *,
    user_id: int | None,
    neden: str | None = None,
    kanal: str | None = None,
    ip: str | None = None,
) -> None:
    """Birimli teklifin TEK durum kapısı: makine + denetim (`quotes/durum`)."""
    eski = t.status
    try:
        TEKLIF.dogrula(eski, hedef)
    except IzinsizGecis as exc:
        raise TeklifKuralHatasi(
            f"Teklif '{DURUM_ADLARI.get(eski, eski)}' durumundan "
            f"'{DURUM_ADLARI.get(hedef, hedef)}' durumuna geçemez"
        ) from exc
    t.status = hedef
    if user_id is not None:
        t.updated_by = user_id
    await audit.log(
        db,
        "quotes",
        "durum",
        entity_id=t.id,
        old_value={"durum": eski},
        new_value={"durum": hedef, "neden": neden, "kanal": kanal},
        user_id=user_id,
        ip=ip,
    )


def _birimli_sart(t: Quote) -> None:
    if not birimli_mi(t):
        raise TeklifKuralHatasi("Bu işlem yalnız teknik servis (birimli) teklifte vardır")


def _neden(neden: str | None, ad: str = "Neden") -> str:
    metin = (neden or "").strip()
    if len(metin) < NEDEN_ASGARI:
        raise TeklifGirdiHatasi(f"{ad} en az {NEDEN_ASGARI} karakter olmalı")
    if len(metin) > 300:
        raise TeklifGirdiHatasi(f"{ad} en çok 300 karakter olabilir")
    return metin


async def guncel_versiyon(db: AsyncSession, t: Quote) -> QuoteVersion:
    v = await db.get(QuoteVersion, t.current_version_id) if t.current_version_id else None
    if v is None:
        raise TeklifKuralHatasi("Teklifin güncel versiyonu yok")
    return v


async def _kalem_sayisi(db: AsyncSession, v: QuoteVersion) -> int:
    return int(await db.scalar(select(func.count()).where(QuoteLine.version_id == v.id)) or 0)


async def onaya_gonder(
    db: AsyncSession,
    t: Quote,
    *,
    user: User,
    clock: Clock,
    beklet: bool = False,
    ip: str | None = None,
) -> list[str]:
    """TASLAK → ONAY_BEKLIYOR (en az 1 kalem). `beklet` işi TEKLIF beklemesine alır."""
    _birimli_sart(t)
    v = await guncel_versiyon(db, t)
    if await _kalem_sayisi(db, v) == 0:
        raise TeklifGirdiHatasi("Kalemsiz teklif onaya gönderilemez")
    await _gecerlilik_dogrula(v, clock)
    await gecis(db, t, "ONAY_BEKLIYOR", user_id=user.id, ip=ip)
    t.submitted_by = user.id
    t.submitted_at = clock.now()
    await db.flush()
    return await bekleme_bagla(db, t, user=user, clock=clock, beklet=beklet)


async def onayla(
    db: AsyncSession, t: Quote, *, user: User, clock: Clock, ip: str | None = None
) -> None:
    """ONAY_BEKLIYOR → ONAYLANDI. Öz-onay yasağı (ayar) → 403. İskonto onayı dahil."""
    _birimli_sart(t)
    if t.status != "ONAY_BEKLIYOR":
        raise TeklifKuralHatasi("Yalnız onay bekleyen teklif onaylanabilir")
    if bool(await ayar_svc.get(db, "teklif_oz_onay_yasak")) and user.id in (
        t.owner_id,
        t.submitted_by,
    ):
        raise TeklifYetkiHatasi("Hazırladığınız ya da onaya gönderdiğiniz teklifi onaylayamazsınız")
    v = await guncel_versiyon(db, t)
    await gecis(db, t, "ONAYLANDI", user_id=user.id, ip=ip)
    simdi = clock.now()
    v.approved_by = user.id
    v.approved_at = simdi
    # Tek kademeli onay (K4): eşik üstü iskonto da bu onayla kapanır.
    if await onay_gerekiyor_mu(db, v):
        v.discount_approved_by = user.id
        v.discount_approved_at = simdi
    await db.flush()


async def geri_cevir(
    db: AsyncSession, t: Quote, *, user: User, neden: str | None, ip: str | None = None
) -> None:
    """ONAY_BEKLIYOR/ONAYLANDI → TASLAK; sürümün onayı silinir (yeniden onay gerekir)."""
    _birimli_sart(t)
    metin = _neden(neden, "Geri çevirme nedeni")
    if t.status not in ("ONAY_BEKLIYOR", "ONAYLANDI"):
        raise TeklifKuralHatasi("Yalnız onay bekleyen ya da onaylı teklif geri çevrilebilir")
    v = await guncel_versiyon(db, t)
    await gecis(db, t, "TASLAK", user_id=user.id, neden=metin, ip=ip)
    v.approved_by = None
    v.approved_at = None
    v.discount_approved_by = None
    v.discount_approved_at = None
    await db.flush()


async def iptal(
    db: AsyncSession,
    t: Quote,
    *,
    user: User,
    clock: Clock,
    neden: str | None,
    ip: str | None = None,
) -> list[str]:
    """Birimli teklif iptali. KABUL'den iptal yalnız `teklif.onayla` ile; iş
    faturaya iletildiyse 409 (E07-D04); TEKLIF kaynaklı gelir geri alınır."""
    from app.services.teknik_servis import maliyet

    _birimli_sart(t)
    metin = _neden(neden, "İptal nedeni")
    kabulden = t.status == "KABUL"
    if kabulden and not user.has("teklif.onayla"):
        raise TeklifYetkiHatasi("Kabul edilmiş teklifi yalnız teklif onaylayıcı iptal edebilir")
    if kabulden:
        await maliyet.fatura_kilidi_dogrula(db, t)
    # İptal alanları geçişten ÖNCE: `gecis` flush ederse ck_quote_iptal_neden
    # (status=IPTAL ⇒ cancel_reason dolu) ara durumda kırılmasın.
    t.cancelled_by = user.id
    t.cancelled_at = clock.now()
    t.cancel_reason = metin
    await gecis(db, t, "IPTAL", user_id=user.id, neden=metin, ip=ip)
    await db.flush()
    uyarilar: list[str] = []
    if kabulden:
        uyarilar += await maliyet.gelir_aktar(db, t, user=user, clock=clock)
    uyarilar += await bekleme_kapat(db, t, user=user, clock=clock, sonuc="IPTAL")
    return uyarilar


async def _gecerlilik_dogrula(v: QuoteVersion, clock: Clock) -> None:
    if v.valid_until is not None and v.valid_until < bugun_yerel(clock):
        raise TeklifGirdiHatasi("Geçerlilik tarihi geçmiş; tarihi güncelleyin")


def karar_dogrula(t: Quote, v: QuoteVersion, bugun: date, *, kabul: bool) -> None:
    """Birimli teklifte elle/link kararı: makine + süresi dolmamış (TS-141)."""
    hedef = "KABUL" if kabul else "RED"
    if not TEKLIF.izinli_mi(t.status, hedef):
        raise TeklifKuralHatasi(
            f"'{DURUM_ADLARI.get(t.status, t.status)}' durumundaki teklife karar verilemez"
        )
    if etkin_durum(t, v, bugun) == "SURESI_DOLDU":
        raise TeklifKuralHatasi("Teklifin geçerlilik süresi dolmuş; revizyon açın")


def karar_verilebilir_mi(t: Quote, v: QuoteVersion, bugun: date) -> bool:
    """Public link kuralı (E07-D01): YALNIZ güncel sürüm, karar bekleyen durum,
    gönderilmiş ve süresi dolmamış. Satış teklifinde de uygulanır: eski
    sürümün kabulü canlıda bir veri tutarsızlığıydı (sürüm notu)."""
    if v.accepted_at or v.rejected_at:
        return False
    if v.id != t.current_version_id:
        return False
    if t.status not in KARAR_BEKLEYEN:
        return False
    if v.valid_until and v.valid_until < bugun:
        return False
    if birimli_mi(t) and not TEKLIF.izinli_mi(t.status, "KABUL"):
        return False
    return v.sent_at is not None


async def kabul_sonrasi(
    db: AsyncSession, t: Quote, *, user: User | None, clock: Clock
) -> list[str]:
    """Birimli teklif kabulünün yan etkileri (aynı transaction):
    PB bulgusu → düzeltici iş, gelir aktarımı, eşleşen beklemenin kapanması."""
    from app.services.teknik_servis import maliyet

    if not birimli_mi(t):
        return []
    uyarilar = await kabulde_is_ac(db, t, user=user, clock=clock)
    uyarilar += await maliyet.duzeltici_isleri_ac(db, t, user=user, clock=clock)
    uyarilar += await maliyet.gelir_aktar(db, t, user=user, clock=clock)
    uyarilar += await bekleme_kapat(db, t, user=user, clock=clock, sonuc="KABUL")
    return uyarilar


async def kabulde_is_ac(
    db: AsyncSession, t: Quote, *, user: User | None, clock: Clock
) -> list[str]:
    """Kabul edilen servis teklifi teknik servise düşer (KARARLAR 2026-11-05 §9.4).

    Yalnız işe bağlı olmayan ve `servis_turu` seçilmiş birimli teklifte:
    PLANLAMADA durumunda tek servis işi açılır ve teklife bağlanır (gelir
    aktarımı bu bağdan sonra çalışır). Sonrası diğer işlerle aynı: müdür
    ekip liderine verir, lider planlar, teknisyen yapar, lider ve müdür onaylar.
    Müşteri linkinden kabulde `user` None'dır (sistem açılışı).
    """
    from app.services.teknik_servis import is_emirleri

    if t.service_order_id is not None or not t.servis_turu or not t.birim:
        return []
    so = await is_emirleri.olustur(
        db,
        is_emirleri.ServisIsiGirdisi(
            birim=t.birim,
            tur=t.servis_turu,
            konu=(t.title or f"Teklif {t.quote_no}")[:200],
            customer_id=t.customer_id,
            address_id=t.address_id,
            contact_id=t.contact_id,
            talep_kanali="DIGER",
            aciklama=f"Kabul edilen teklif: {t.quote_no}",
        ),
        user=user,
        clock=clock,
        baslangic_durumu="PLANLAMADA",
    )
    t.service_order_id = so.id
    await db.flush()
    await audit.log(
        db,
        "quotes",
        "kabulde_is_acildi",
        entity_id=t.id,
        new_value={"so_id": so.id, "so_no": so.so_no, "tur": so.tur},
        user_id=user.id if user is not None else None,
    )
    return [f"Teklif kabul edildi; servis işi açıldı: {so.so_no}"]


async def ret_sonrasi(db: AsyncSession, t: Quote, *, user: User | None, clock: Clock) -> list[str]:
    if not birimli_mi(t):
        return []
    return await bekleme_kapat(db, t, user=user, clock=clock, sonuc="RED")


# --- Servis işi köprüsü (TS-147) -------------------------------------------------------


async def servis_isi_dogrula(
    db: AsyncSession, user: User, so_id: int, *, customer_id: int, birim: str | None
) -> ServiceOrder:
    """Gövdedeki servis işi: yok/silinmiş/kapsam dışı → 404 (plan §1.2);
    başka müşterinin ya da başka birimin işi → 400 (bağlanamaz)."""
    from app.services.teknik_servis import kapsam

    so = await db.get(ServiceOrder, so_id)
    if so is None or so.is_deleted or await kapsam.is_erisimi_yok_mu(db, user, so):
        raise TeklifKapsamDisi("Servis işi bulunamadı")
    if so.customer_id != customer_id or (birim is not None and so.birim != birim):
        raise TeklifGirdiHatasi("Servis işi bulunamadı veya bu teklife bağlanamaz")
    return so


async def _irtibat_adres_dogrula(
    db: AsyncSession, customer_id: int, contact_id: int | None, address_id: int | None
) -> None:
    if contact_id is not None:
        k = await db.get(Contact, contact_id)
        if k is None or k.account_id != customer_id:
            raise TeklifGirdiHatasi("İrtibat kişisi bu müşteriye ait değil")
    if address_id is not None:
        a = await db.get(Address, address_id)
        if a is None or a.account_id != customer_id:
            raise TeklifGirdiHatasi("Adres bu müşteriye ait değil")


@dataclass
class BaslikGirdisi:
    """Teklif başlığı (oluşturma ve taslak düzenleme ortak)."""

    customer_id: int
    birim: str | None = None
    service_order_id: int | None = None
    contact_id: int | None = None
    address_id: int | None = None
    currency: str = "TRY"
    fx_rate: Decimal | None = None
    valid_until: date | None = None
    servis_turu: str | None = None


async def baslik_dogrula(
    db: AsyncSession, user: User, g: BaslikGirdisi, clock: Clock
) -> ServiceOrder | None:
    """Başlık kuralları. Servis işinden açılan teklifte birim, adres ve
    (boşsa) irtibat İŞTEN alınır — istemcinin gönderdiği değer esas değildir."""
    musteri = await db.get(Account, g.customer_id)
    if musteri is None or musteri.is_deleted:
        raise TeklifGirdiHatasi("Müşteri bulunamadı")
    # Rol testi tur 2 (6_satis 1.1, KARARLAR 2026-11-04 §7.8): satış temsilcisi
    # BAŞKA temsilcinin müşterisine teklif açamaz; yanıt "yok" ile aynı (varlık
    # sızmasın). Sahipsiz (temsilcisi atanmamış) müşteri canlı satış akışındaki
    # gibi açık kalır — yeni müşteriye ilk teklif engellenmesin.
    if (
        _kapsam(user) == SCOPE_OWN_CUSTOMERS
        and musteri.sales_rep_id is not None
        and musteri.sales_rep_id != user.id
    ):
        raise TeklifGirdiHatasi("Müşteri bulunamadı")
    so: ServiceOrder | None = None
    if g.service_order_id is not None:
        so = await servis_isi_dogrula(
            db, user, g.service_order_id, customer_id=g.customer_id, birim=g.birim
        )
        g.birim = so.birim
        g.address_id = so.address_id
        if g.contact_id is None:
            g.contact_id = so.contact_id
    if g.birim is not None:
        if g.birim not in BIRIM_KODLARI:
            raise TeklifGirdiHatasi(f"Bilinmeyen birim: {g.birim}")
        # Şirket ayrımı (KARARLAR 2026-11-04 §1): birim etkin şirketin olmalı.
        if not sirketler.birim_etkin_sirkette_mi(user, g.birim):
            raise TeklifYetkiHatasi(sirketler.sirket_disi_mesaji(user))
        if not birimli_yazabilir_mi(user, g.birim):
            raise TeklifYetkiHatasi("Birimli (servis) teklifi yalnız teknik servis rolleri açar")
        if _kapsam(user) != SCOPE_ALL and g.birim not in kullanici_birimleri(user):
            raise TeklifKapsamDisi("Birim bulunamadı")
        if g.currency != "TRY" and g.fx_rate is None:
            raise TeklifGirdiHatasi("Dövizli teklifte kur zorunlu")
        if g.valid_until is not None and g.valid_until < bugun_yerel(clock):
            raise TeklifGirdiHatasi("Geçerlilik tarihi geçmiş bir gün olamaz")
    elif not satis_yazabilir_mi(user):
        raise TeklifYetkiHatasi("Teknik servis rolleri yalnız birimli (servis) teklif açabilir")
    elif sirketler.etkin_birimler(user) is not None and not sirketler.mobilite_acik_mi(user):
        # Birimsiz teklif canlı mobilite satış teklifidir (karar §1).
        raise TeklifYetkiHatasi(
            "Birimsiz (satış) teklifi yalnız DENGE MOBİLİTE seçiliyken açılır; "
            "servis teklifi için birim seçin."
        )
    if g.servis_turu is not None:
        if g.birim is None:
            raise TeklifGirdiHatasi("Açılacak iş türü yalnız servis teklifinde seçilir")
        if g.service_order_id is not None:
            raise TeklifGirdiHatasi(
                "Servis işine bağlı teklifte ayrıca iş açılmaz; iş türü seçilemez"
            )
        if g.servis_turu not in TEKLIF_IS_TURLERI:
            raise TeklifGirdiHatasi(f"Bilinmeyen iş türü: {g.servis_turu}")
    await _irtibat_adres_dogrula(db, g.customer_id, g.contact_id, g.address_id)
    return so


async def kalemleri_yaz(
    db: AsyncSession,
    user: User,
    versiyon: QuoteVersion,
    kalemler: list[dict[str, Any]],
    *,
    teklif: Quote,
) -> None:
    """Kalemleri doğrular ve yazar. Birimli teklifte KDV beyaz listesi, 500
    karakter açıklama ve kalem servis işi doğrulaması; satışta açıklama 300."""
    birimli = birimli_mi(teklif)
    sinir = BIRIMLI_KALEM_ACIKLAMA_UZUNLUGU if birimli else SATIS_KALEM_ACIKLAMA_UZUNLUGU
    dogrulanan: dict[int, ServiceOrder] = {}
    for sira, ham in enumerate(kalemler):
        k = dict(ham)
        so_id = k.pop("service_order_id", None)
        if k.get("description") and len(k["description"]) > sinir:
            raise TeklifGirdiHatasi(f"Kalem açıklaması en çok {sinir} karakter olabilir")
        try:
            veri = await kalem_alanlari(db, **k)
        except ValueError as exc:
            raise TeklifGirdiHatasi(str(exc)) from exc
        if len(veri["description"] or "") > sinir:
            raise TeklifGirdiHatasi(f"Kalem açıklaması en çok {sinir} karakter olabilir")
        if so_id is not None:
            if not birimli:
                raise TeklifGirdiHatasi("Satış teklifi kalemi servis işine bağlanamaz")
            if so_id not in dogrulanan:
                dogrulanan[so_id] = await servis_isi_dogrula(
                    db, user, so_id, customer_id=teklif.customer_id, birim=teklif.birim
                )
        if birimli and Decimal(str(veri["vat_rate"])) not in BIRIMLI_KDV_ORANLARI:
            izinli = ", ".join(f"%{int(o * 100)}" for o in BIRIMLI_KDV_ORANLARI)
            raise TeklifGirdiHatasi(f"KDV oranı {izinli} değerlerinden biri olmalı")
        db.add(QuoteLine(version_id=versiyon.id, sort_order=sira, service_order_id=so_id, **veri))
    await db.flush()


async def taslak_guncelle(
    db: AsyncSession,
    t: Quote,
    user: User,
    *,
    baslik: BaslikGirdisi,
    title: str | None,
    fx_date: date | None,
    kalemler: list[dict[str, Any]],
    version: int,
    clock: Clock,
) -> tuple[Decimal, Decimal]:
    """TASLAK teklifi YERİNDE düzenler (TS-148; sürüm sayısı artmaz).

    Başlık satırı da yazılır (`flag_modified`) ki `version` artsın ve iyimser
    kilit işlesin (kontrol: kalem değişikliği tek başına `quotes` satırını
    güncellemiyordu). Dönüş: (eski tutar, yeni tutar).
    """
    if version != t.version:
        raise TeklifKuralHatasi("Teklif başka biri tarafından değiştirildi; sayfayı yenileyin")
    if t.status != "TASLAK":
        raise TeklifKuralHatasi(
            "Yalnız taslak teklif düzenlenebilir; gönderilmiş teklif için revizyon açın"
        )
    v = await guncel_versiyon(db, t)
    if v.is_locked:
        raise TeklifKuralHatasi("Güncel sürüm kilitli; revizyon açın")
    if t.service_order_id is not None:
        if baslik.service_order_id not in (None, t.service_order_id):
            raise TeklifGirdiHatasi("Teklifin bağlı olduğu servis işi değiştirilemez")
        baslik.service_order_id = t.service_order_id
        baslik.birim = t.birim
    if (baslik.birim is None) != (t.birim is None) and baslik.service_order_id is None:
        raise TeklifGirdiHatasi("Teklif türü (satış/servis) değiştirilemez")
    if t.birim is not None and baslik.birim is not None and baslik.birim != t.birim:
        from app.services.teknik_servis import kapsam

        # Kaydı başka birime taşıyıp kapsamı genişletmek yasak (plan §1.2) → 404.
        if kapsam.birim_degisimi_yasak_mi(user, t.birim, baslik.birim):
            raise TeklifKapsamDisi("Birim bulunamadı")
    so = await baslik_dogrula(db, user, baslik, clock)
    if (baslik.birim is None) != (t.birim is None):
        raise TeklifGirdiHatasi("Teklif türü (satış/servis) değiştirilemez")
    eski_tutar = v.grand_total

    t.customer_id = baslik.customer_id
    t.birim = baslik.birim
    t.service_order_id = so.id if so is not None else None
    t.servis_turu = baslik.servis_turu if so is None else None
    t.contact_id = baslik.contact_id
    t.address_id = baslik.address_id
    t.title = title
    t.updated_by = user.id
    flag_modified(t, "updated_by")
    v.currency = baslik.currency
    v.fx_rate = baslik.fx_rate
    v.fx_date = fx_date
    v.fx_source = "MANUEL" if baslik.fx_rate else None
    if baslik.valid_until:
        v.valid_until = baslik.valid_until
    for k in (await db.scalars(select(QuoteLine).where(QuoteLine.version_id == v.id))).all():
        await db.delete(k)
    await db.flush()
    await kalemleri_yaz(db, user, v, kalemler, teklif=t)
    await versiyon_hesapla(db, v)
    return eski_tutar, v.grand_total


async def revize_kurali(t: Quote, v: QuoteVersion, bugun: date) -> str:
    """Revizyon sonrası durum. Satışta canlı davranış (REVIZE_EDILDI); birimli
    teklifte yalnız gönderilmiş/ret/süresi dolmuş iken ve durum TASLAK olur
    (yeniden iç onay gerekir; kontrol B2)."""
    if t.status in ("KABUL", "SIPARISE_DONUSTU"):
        raise TeklifKuralHatasi("Kabul edilmiş teklif revize edilemez; yeni teklif açın.")
    if not birimli_mi(t):
        return "REVIZE_EDILDI"
    if t.status in ("ONAY_BEKLIYOR", "ONAYLANDI"):
        raise TeklifKuralHatasi("Onay sürecindeki teklif revize edilemez; önce geri çevirin")
    if t.status == "TASLAK":
        raise TeklifKuralHatasi("Taslak teklif revize edilmez; yerinde düzenleyin")
    if t.status not in ("GONDERILDI", "GORUNTULENDI", "RED"):
        raise TeklifKuralHatasi(
            f"'{DURUM_ADLARI.get(t.status, t.status)}' durumundaki teklif revize edilemez"
        )
    return "TASLAK"


# --- TEKLIF beklemesi (E07-14, kontrol B6) -------------------------------------------


async def bekleme_bagla(
    db: AsyncSession, t: Quote, *, user: User | None, clock: Clock, beklet: bool
) -> list[str]:
    """İşin aktif TEKLIF beklemesine `quote_id` yazar; yoksa ve `beklet` ise E01
    `beklet()` ile açar. Başka nedenli aktif bekleme varken ikinci bekleme
    AÇILMAZ (tek aktif bekleme) ve uyarı döner."""
    from app.services.teknik_servis import bekletme, gecmis
    from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

    if not birimli_mi(t) or t.service_order_id is None:
        return []
    so = await db.get(ServiceOrder, t.service_order_id)
    if so is None or so.is_deleted:
        return []
    aktif = await bekletme.aktif_bekleme(db, so)
    if aktif is not None:
        if aktif.neden != "TEKLIF":
            return (
                ["İşte başka nedenli aktif bekleme var; teklif beklemesi açılmadı"]
                if beklet
                else []
            )
        if aktif.quote_id is None:
            aktif.quote_id = t.id
            await db.flush()
            await gecmis.olay_yaz(
                db,
                so,
                "TEKLIF",
                f"Teklif beklemesine bağlandı: {t.quote_no}",
                user=user,
                clock=clock,
                veri={"teklif_id": t.id, "quote_no": t.quote_no},
            )
        return []
    if not beklet:
        return []
    try:
        yeni = await bekletme.beklet(
            db, so, "TEKLIF", user=user, clock=clock, aciklama=f"Teklif {t.quote_no}"
        )
    except (ServisHatasi, ServisGirdiHatasi) as exc:
        return [f"Teklif beklemesi açılamadı: {exc}"]
    yeni.quote_id = t.id
    await db.flush()
    return []


async def bekleme_kapat(
    db: AsyncSession, t: Quote, *, user: User | None, clock: Clock, sonuc: str
) -> list[str]:
    """YALNIZ bu teklife bağlı (`quote_id = t.id`) aktif bekleme kapanır;
    başka nedenli bekleme (ör. MALZEME) dokunulmadan kalır (E07-14 kabul 3)."""
    from app.models import ServiceHold
    from app.services.teknik_servis import bekletme, gecmis
    from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

    if not birimli_mi(t):
        return []
    beklemeler = (
        await db.scalars(
            select(ServiceHold).where(
                ServiceHold.quote_id == t.id, ServiceHold.released_at.is_(None)
            )
        )
    ).all()
    uyarilar: list[str] = []
    for bekleme in beklemeler:
        so = await db.get(ServiceOrder, bekleme.service_order_id)
        if so is None:
            continue
        try:
            await bekletme.beklemeyi_bitir(
                db,
                so,
                user=user,
                clock=clock,
                not_=f"Teklif {t.quote_no}: {DURUM_ADLARI.get(sonuc, sonuc)}",
            )
        except (ServisHatasi, ServisGirdiHatasi) as exc:
            uyarilar.append(f"{so.so_no} beklemesi kapatılamadı: {exc}")
            continue
        await gecmis.olay_yaz(
            db,
            so,
            "TEKLIF",
            f"Teklif {t.quote_no}: {DURUM_ADLARI.get(sonuc, sonuc)}",
            user=user,
            clock=clock,
            veri={"teklif_id": t.id, "quote_no": t.quote_no, "sonuc": sonuc},
        )
    return uyarilar


# --- Gönderim günlüğü ve PDF (TS-142/143) ---------------------------------------------


def pdf_ozeti(pdf: bytes | None) -> str | None:
    return hashlib.sha256(pdf).hexdigest() if pdf is not None else None


async def gonderim_kaydet(
    db: AsyncSession,
    t: Quote,
    v: QuoteVersion,
    *,
    kanal: str,
    sonuc: str,
    user_id: int | None,
    alicilar: list[str] | None = None,
    cc: str | None = None,
    hata_ozeti: str | None = None,
    pdf: bytes | None = None,
    notlar: str | None = None,
) -> QuoteSend:
    kayit = QuoteSend(
        quote_id=t.id,
        version_id=v.id,
        kanal=kanal,
        alicilar=alicilar or None,
        cc=cc,
        sonuc=sonuc,
        hata_ozeti=hata_ozeti,
        pdf_sha256=pdf_ozeti(pdf),
        notlar=notlar,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(kayit)
    await db.flush()
    return kayit


def kdv_dokumu(kalemler: list[QuoteLine]) -> list[dict[str, Decimal]]:
    """Oran bazında matrah ve KDV; kalem başına yuvarlama `versiyon_hesapla`
    ile AYNI olduğu için toplam `vat_total`'a eşittir (E07-08 kabul 1)."""
    gruplar: dict[Decimal, list[Decimal]] = {}
    for k in kalemler:
        oran = Decimal(str(k.vat_rate))
        net = Decimal(str(k.line_total))
        matrah, kdv = gruplar.get(oran, [Decimal("0"), Decimal("0")])
        gruplar[oran] = [matrah + net, kdv + yuvarla(net * oran)]
    return [
        {"oran": oran, "matrah": yuvarla(m), "kdv": yuvarla(k)}
        for oran, (m, k) in sorted(gruplar.items(), reverse=True)
    ]


def teklif_no_gosterim(t: Quote, v: QuoteVersion) -> str:
    """`TKF2026-00012-R1` — R = sürüm no − 1 (yalnız gösterim, K19)."""
    return f"{t.quote_no}-R{v.version_no - 1}" if v.version_no > 1 else t.quote_no


async def teklif_pdf_baglami(db: AsyncSession, t: Quote, v: QuoteVersion) -> dict:
    """Canlı `belgeler.teklif_baglami` + kurumsal alanlar (yalnız EKLEME, E07-08).

    `belgeler.py` bu dalgada donmuş olduğu için ek alanlar burada eklenir;
    satış PDF'i de aynı ekleri alır (onaylayan yalnız doluysa basılır).
    """
    from app.services import belgeler
    from app.services.belgeler import tl

    baglam = await belgeler.teklif_baglami(db, t, v)
    kalemler = list(
        (
            await db.scalars(
                select(QuoteLine)
                .where(QuoteLine.version_id == v.id)
                .order_by(QuoteLine.sort_order, QuoteLine.id)
            )
        ).all()
    )
    baglam["teklif_no_gosterim"] = teklif_no_gosterim(t, v)
    baglam["kdv_dokumu"] = [
        {
            "oran": f"%{(d['oran'] * 100).normalize():f}",
            "matrah": tl(d["matrah"]),
            "kdv": tl(d["kdv"]),
        }
        for d in kdv_dokumu(kalemler)
    ]
    if v.approved_by:
        onaylayan = await db.get(User, v.approved_by)
        if onaylayan is not None:
            baglam["onaylayan"] = onaylayan.full_name
    if t.contact_id:
        irtibat = await db.get(Contact, t.contact_id)
        if irtibat is not None:
            baglam["irtibat"] = {
                "ad": irtibat.full_name,
                "telefon": irtibat.phone,
                "eposta": irtibat.email,
            }
    return baglam


async def teklif_pdf(db: AsyncSession, t: Quote, v: QuoteVersion) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async("teklif.html", **await teklif_pdf_baglami(db, t, v))


# --- Geçmiş (audit_logs; K16) --------------------------------------------------------

_EYLEM_ADLARI = {
    "olustur": "Oluşturuldu",
    "guncelle": "Taslak düzenlendi",
    "revize": "Revize edildi",
    "gonder": "Gönderildi",
    "elle_gonderildi": "Elle gönderildi",
    "karar": "Karar",
    "iskonto.onayla": "İskonto onaylandı",
    "goruntulendi": "Müşteri görüntüledi",
    "durum": "Durum değişti",
}


async def gecmis(db: AsyncSession, t: Quote) -> list[dict[str, Any]]:
    satirlar = (
        await db.execute(
            select(AuditLog, User.full_name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(AuditLog.entity == "quotes", AuditLog.entity_id == str(t.id))
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    ).all()
    sonuc = []
    for kayit, ad in satirlar:
        eski = kayit.old_value or {}
        yeni = kayit.new_value or {}
        sonuc.append(
            {
                "zaman": kayit.created_at,
                "eylem": kayit.action,
                "eylem_adi": _EYLEM_ADLARI.get(kayit.action, kayit.action),
                "kullanici": ad if kayit.user_id else None,
                "eski_durum": eski.get("durum"),
                "yeni_durum": yeni.get("durum")
                or ("KABUL" if yeni.get("kabul") is True else None)
                or ("RED" if yeni.get("kabul") is False else None),
                "neden": yeni.get("neden"),
                "kanal": yeni.get("kanal"),
                "versiyon": yeni.get("versiyon"),
            }
        )
    return sonuc


async def kullanici_adlari(db: AsyncSession, idler: set[int | None]) -> dict[int, str]:
    gercek = {i for i in idler if i}
    if not gercek:
        return {}
    return dict(
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(gercek)))).all()
    )
