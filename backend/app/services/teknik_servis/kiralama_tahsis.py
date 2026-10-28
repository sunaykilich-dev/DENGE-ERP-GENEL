"""Kiralama tahsis, sevk, iade, müsaitlik (E06-04/06/07/12).

Maddeler: TS-112, TS-113, TS-116. D2-C.

**Kalem ≠ tahsis:** kalem "kaç adet istendi", tahsis "hangi depodan hangi
cihaz / kaç adet". Tahsis cihazı bağlar ama depodan ÇIKARMAZ (durum HAZIR
kalır); sevk cihazı KIRADA yapar. Bir kalemin AKTİF tahsis toplamı kalem
adedini aşamaz. Seri cihazın tarihleri çakışan İKİNCİ AKTİF tahsisi (çifte
rezervasyon) M10.1 (KARARLAR 2026-10-28 §7 Faz A/4) ile ENGEL DEĞİL UYARIDIR:
servis çakışan kiralamaları `CakismaUyarisi` (409 + liste) ile bildirir;
çağıran `CakismaOnayi(gerekce)` verirse kayıt yapılır, geçilen çakışmalar
onay nesnesine yazılır ve API denetim izine gerekçeyle düşer. Eski
`ex_rtahsis_cihaz_cakisma` kısıtı `e1a000000003` ile kaldırıldı (yerine aynı
ifadeli GiST indeksi `ix_rtahsis_cihaz_aralik`). Aynı kiralamada aynı cihaz
iki kez tahsis EDİLEMEZ (bu bir uyarı değil, veri hatası). Toplu üründe serbest adet:
`bakiye(depo, HAZIR) − Σ(qty − sevk)[AKTİF, aynı depo, tarih çakışan]`.

**Rezervasyon (K3):** PLANLANDI…TOPLANDI durumundaki kiralamanın kalemleri
tarih aralığında (`daterange '[)'`, bitiş = iade günü) ürün/adet bazında
rezervdir; TALEP hiçbir şeyi bloke etmez. Bitişi geçmiş ama cihazı hâlâ
müşteride olan kiralama, müşterideki adet kadar rezerv sayılır.

**Tamamlanma:** her AKTİF tahsiste `iade_adet + kayip_adet = sevk_adet`
olunca kiralama DEPOYA_ALINDI olur; kurulum yapılmış (KURULUM_YAPILDI /
DEVREYE_ALINDI) kiralamada son iade önce TOPLANDI ister (makinede kenar yok,
409). Tamamen iade edilen tahsis KAPANDI olur (cihaz başka kiralamaya
çakışmadan tahsis edilebilsin).

Her sevk/iade çağrısı TEK bir olay yazar; olay yazdığı hareketlerin ve
sayaç değişikliklerinin kimliklerini taşır ki aşama geri alma
(`kiralama.asama_geri_al`) yalnız o olayı tersine çevirebilsin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import (
    Product,
    Rental,
    RentalAllocation,
    RentalAsset,
    RentalEvent,
    RentalItem,
)
from app.services.statemachine import KIRALAMA, IzinsizGecis
from app.services.teknik_servis.kiralik_envanter import (
    DURUM_ETIKETLERI,
    KiralamaHatasi,
    bakiye,
    bulunamadi,
    cihazlari_kilitle,
    durum_sayilari,
    girdi,
    hareket_yaz,
    katalog_kilitle,
    katalog_profili,
    kiralama_deposu,
    rezerve_toplu,
    seri_takipli_mi,
)
from app.services.teknik_servis.yerel_zaman import yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

# Ürün/adet rezervi tutan durumlar (K3).
REZERV_DURUMLARI = (
    "PLANLANDI",
    "HAZIRLANIYOR",
    "SEVK_EDILDI",
    "KURULUM_YAPILDI",
    "DEVREYE_ALINDI",
    "TOPLANDI",
)
SEVK_SONRASI = ("SEVK_EDILDI", "KURULUM_YAPILDI", "DEVREYE_ALINDI", "TOPLANDI")
# Tahsis bu durumlarda yapılır; sevk sonrası yalnız ek/değişim tahsisi.
TAHSIS_DURUMLARI_IZINLI = REZERV_DURUMLARI
# Ek sevk bu durumlarda (TOPLANDI'da cihaz sahadan toplanmıştır).
EK_SEVK_DURUMLARI = ("SEVK_EDILDI", "KURULUM_YAPILDI", "DEVREYE_ALINDI")
IADE_SONUCLARI = ("IADE_ALINDI", "MUSTERIDE", "KAYIP")
DURUM_ADLARI = {
    "TALEP": "Talep",
    "PLANLANDI": "Planlandı",
    "HAZIRLANIYOR": "Hazırlanıyor",
    "SEVK_EDILDI": "Sevk edildi",
    "KURULUM_YAPILDI": "Kurulum yapıldı",
    "DEVREYE_ALINDI": "Devreye alındı",
    "TOPLANDI": "Toplandı",
    "DEPOYA_ALINDI": "Depoya alındı",
    "KAPANDI": "Kapandı",
    "IPTAL": "İptal",
}
# Aşama zamanı en çok bu kadar ileri / geri girilebilir.
ILERI_TOLERANS = timedelta(days=1)
GERI_SINIR_YIL = 10


# --- Olay ve durum ------------------------------------------------------------------


async def olay_yaz(
    db: AsyncSession,
    kiralama: Rental,
    tur: str,
    *,
    user: User | None,
    clock: Clock,
    at: datetime | None = None,
    onceki_durum: str | None = None,
    yeni_durum: str | None = None,
    alan: str | None = None,
    eski: dict | None = None,
    yeni: dict | None = None,
    service_order_id: int | None = None,
    ekip_user_ids: list[int] | None = None,
    gerekce: str | None = None,
    geri_alinan_event_id: int | None = None,
) -> RentalEvent:
    """Ekleme-yalnız olay (kişisel veri YAZILMAZ: yalnız durum/tarih/kimlik)."""
    olay = RentalEvent(
        rental_id=kiralama.id,
        at=at or clock.now(),
        tur=tur,
        onceki_durum=onceki_durum,
        yeni_durum=yeni_durum,
        alan=alan,
        eski=eski,
        yeni=yeni,
        service_order_id=service_order_id,
        ekip_user_ids=ekip_user_ids,
        gerekce=(gerekce or None) and gerekce[:500],
        geri_alinan_event_id=geri_alinan_event_id,
        created_by=user.id if user is not None else None,
    )
    db.add(olay)
    await db.flush()
    return olay


def gecis_dogrula(mevcut: str, hedef: str) -> None:
    """KIRALAMA makinesi; yasak geçiş Türkçe mesajla 409."""
    try:
        KIRALAMA.dogrula(mevcut, hedef)
    except IzinsizGecis:
        izinli = ", ".join(DURUM_ADLARI[d] for d in sorted(KIRALAMA.sonraki(mevcut)))
        if mevcut == hedef:
            raise KiralamaHatasi(f"Kiralama zaten '{DURUM_ADLARI[hedef]}' durumunda") from None
        raise KiralamaHatasi(
            f"'{DURUM_ADLARI.get(mevcut, mevcut)}' durumundan '{DURUM_ADLARI.get(hedef, hedef)}' "
            f"durumuna geçilemez. İzin verilenler: {izinli or 'yok (kapalı kayıt)'}"
        ) from None


def durum_ata(kiralama: Rental, hedef: str, user: User | None) -> str:
    """Makineyle doğrulanmış geçiş; önceki durumu döner (olay çağıranda)."""
    onceki = kiralama.status
    gecis_dogrula(onceki, hedef)
    kiralama.status = hedef
    if user is not None:
        kiralama.updated_by = user.id
    return onceki


def asama_zamani(at: datetime | None, kiralama: Rental, clock: Clock) -> datetime:
    """Aşama anı: en çok 1 gün ileri, başlangıçtan en çok 10 yıl geri (400)."""
    simdi = clock.now()
    if at is None:
        return simdi
    if at.tzinfo is None:
        raise girdi("Aşama zamanı saat dilimi bilgisiyle girilmeli")
    if at > simdi + ILERI_TOLERANS:
        raise girdi("Aşama zamanı bir günden fazla ileri olamaz")
    alt = date(kiralama.baslangic.year - GERI_SINIR_YIL, 1, 1)
    if at.date() < alt:
        raise girdi("Aşama zamanı kiralama başlangıcından 10 yıldan fazla geri olamaz")
    return at


# --- Okuma yardımcıları --------------------------------------------------------------


async def kalemler(db: AsyncSession, kiralama_id: int) -> list[RentalItem]:
    return list(
        (
            await db.scalars(
                select(RentalItem)
                .where(RentalItem.rental_id == kiralama_id)
                .order_by(RentalItem.id)
            )
        ).all()
    )


async def tahsisler(
    db: AsyncSession, kiralama_id: int, *, kilit: bool = False
) -> list[RentalAllocation]:
    stmt = (
        select(RentalAllocation)
        .where(RentalAllocation.rental_id == kiralama_id)
        .order_by(RentalAllocation.id)
    )
    if kilit:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list((await db.scalars(stmt)).all())


def disarida(t: RentalAllocation) -> int:
    """Tahsisin müşteride kalan adedi."""
    return t.sevk_adet - t.iade_adet - t.kayip_adet


def iade_gosterimi(tahsis_listesi: list[RentalAllocation]) -> str:
    """`YOK / KISMI / TAM` — kısmi iade ayrı bir durum değildir."""
    gecerli = [t for t in tahsis_listesi if t.durum != "COZULDU"]
    sevk = sum(t.sevk_adet for t in gecerli)
    donen = sum(t.iade_adet + t.kayip_adet for t in gecerli)
    if sevk == 0 or donen == 0:
        return "YOK"
    return "TAM" if donen >= sevk else "KISMI"


# --- Müsaitlik (TS-116) ---------------------------------------------------------------


async def musaitlik(
    db: AsyncSession,
    product_id: int,
    baslangic: date,
    bitis: date,
    *,
    user: User | None = None,
    haric_rental_id: int | None = None,
) -> dict[str, Any]:
    """Tarih bazlı müsait adet (yarı açık aralık `[baslangic, bitis)`).

    `toplam = HAZIR + KONTROLDE + KIRADA`; KAYIP, HAZIR_DEGIL, ATOLYEDE ve
    HURDA düşülür. `rezerve` = çakışan rezerv durumlu kiralamaların kalem
    adetleri + bitişi geçmiş ama müşteride kalan adet. `musait = toplam −
    rezerve`. KONTROLDE müsaite dahildir ama ayrı alanda gösterilir.
    """
    if bitis <= baslangic:
        raise girdi("Bitiş tarihi başlangıçtan sonra olmalı")
    sayilar = await durum_sayilari(db, product_id)
    toplam = sayilar["HAZIR"] + sayilar["KONTROLDE"] + sayilar["KIRADA"]
    cakisan = (
        select(func.coalesce(func.sum(RentalItem.qty), 0))
        .join(Rental, Rental.id == RentalItem.rental_id)
        .where(
            RentalItem.product_id == product_id,
            Rental.is_deleted.is_(False),
            Rental.status.in_(REZERV_DURUMLARI),
            Rental.baslangic < bitis,
            Rental.bitis > baslangic,
        )
    )
    if haric_rental_id is not None:
        cakisan = cakisan.where(Rental.id != haric_rental_id)
    rezerve = int(await db.scalar(cakisan) or 0)
    geciken = (
        select(
            func.coalesce(
                func.sum(
                    RentalAllocation.sevk_adet
                    - RentalAllocation.iade_adet
                    - RentalAllocation.kayip_adet
                ),
                0,
            )
        )
        .join(Rental, Rental.id == RentalAllocation.rental_id)
        .where(
            RentalAllocation.product_id == product_id,
            RentalAllocation.durum == "AKTIF",
            Rental.is_deleted.is_(False),
            Rental.status.in_(SEVK_SONRASI),
            Rental.bitis <= baslangic,
        )
    )
    if haric_rental_id is not None:
        geciken = geciken.where(Rental.id != haric_rental_id)
    gecikme = int(await db.scalar(geciken) or 0)
    rezerve_toplam = rezerve + gecikme
    return {
        "product_id": product_id,
        "baslangic": baslangic,
        "bitis": bitis,
        "toplam": toplam,
        "hazir": sayilar["HAZIR"],
        "kirada": sayilar["KIRADA"],
        "kontrolde": sayilar["KONTROLDE"],
        "hazir_degil": sayilar["HAZIR_DEGIL"],
        "kayip": sayilar["KAYIP"],
        "atolyede": sayilar["ATOLYEDE"],
        "rezerve": rezerve_toplam,
        "geciken": gecikme,
        "musait": toplam - rezerve_toplam,
    }


async def yeterlilik_dogrula(
    db: AsyncSession,
    kiralama: Rental,
    istenen: dict[int, int],
    *,
    baslangic: date | None = None,
    bitis: date | None = None,
) -> None:
    """Ürün → istenen adet, kiralamanın (ya da verilen) tarihlerinde müsait mi?

    Katalog satırları `product_id` sırasıyla kilitlenir: iki kiralama aynı
    ürünleri aynı anda planlarsa biri bekler, deadlock olmaz (E06-12).
    Eksik varsa 409 + "PG-5030: 1 adet eksik" listesi.
    """
    if not istenen:
        return
    await katalog_kilitle(db, list(istenen))
    eksikler: list[str] = []
    for product_id in sorted(istenen):
        m = await musaitlik(
            db,
            product_id,
            baslangic or kiralama.baslangic,
            bitis or kiralama.bitis,
            haric_rental_id=kiralama.id,
        )
        eksik = istenen[product_id] - m["musait"]
        if eksik > 0:
            urun = await db.get(Product, product_id)
            eksikler.append(f"{urun.code if urun else product_id}: {eksik} adet eksik")
    if eksikler:
        raise KiralamaHatasi(
            "Seçilen tarihlerde yeterli müsait envanter yok — " + "; ".join(eksikler),
            veri={"eksikler": eksikler},
        )


# --- Tahsis (TS-112) -------------------------------------------------------------------


@dataclass
class TahsisSatiri:
    kalem_id: int
    kiralik_idler: list[int] | None = None
    depo_id: int | None = None
    adet: int | None = None


@dataclass
class CakismaOnayi:
    """M10.1: tarih çakışmasını bilerek geçme beyanı (gerekçe zorunlu, API'de
    boş olamaz). Servis geçilen çakışmaları `gecilenler`e yazar; API bunları
    gerekçeyle birlikte denetim izine düşer."""

    gerekce: str
    gecilenler: list[dict[str, Any]] = field(default_factory=list)


class CakismaUyarisi(KiralamaHatasi):
    """Seri cihaz başka kiralamada aynı tarihlere tahsisli (M10.1) — 409 +
    `kod=KIRALAMA_CAKISMA` + çakışan kiralama listesi. Onay + gerekçeyle
    tekrar gönderilirse kayıt yapılır."""

    def __init__(self, cakismalar: list[dict[str, Any]]):
        ozet = ", ".join(
            f"{c['seri_no']} → {c['kiralama_no']} ({c['baslangic']} – {c['bitis']})"
            for c in cakismalar[:5]
        )
        if len(cakismalar) > 5:
            ozet += f" ve {len(cakismalar) - 5} çakışma daha"
        super().__init__(
            f"Tarih çakışması: {ozet}. Yine de kaydetmek için gerekçe girin.",
            veri={"kod": "KIRALAMA_CAKISMA", "cakismalar": cakismalar},
        )


async def _seri_cakismalari(
    db: AsyncSession,
    cihaz: RentalAsset,
    baslangic: date,
    bitis: date,
    *,
    haric_tahsis_id: int | None = None,
) -> list[RentalAllocation]:
    """Cihazın tarihleri kesişen (yarı açık `[)`) AKTİF tahsisleri."""
    stmt = select(RentalAllocation).where(
        RentalAllocation.asset_id == cihaz.id,
        RentalAllocation.durum == "AKTIF",
        RentalAllocation.baslangic < bitis,
        RentalAllocation.bitis > baslangic,
    )
    if haric_tahsis_id is not None:
        stmt = stmt.where(RentalAllocation.id != haric_tahsis_id)
    return list((await db.scalars(stmt.order_by(RentalAllocation.id))).all())


async def _cakisma_satirlari(
    db: AsyncSession, cihaz: RentalAsset, tahsisler_: list[RentalAllocation]
) -> list[dict[str, Any]]:
    """Uyarı satırı: yalnız kiralama no/tarih/durum (müşteri adı yok — çakışan
    kiralama kullanıcının kapsamı dışında olabilir)."""
    satirlar = []
    for t in tahsisler_:
        baska = await db.get(Rental, t.rental_id)
        satirlar.append(
            {
                "seri_no": cihaz.serial_no,
                "kiralik_id": cihaz.id,
                "tahsis_id": t.id,
                "kiralama_id": t.rental_id,
                "kiralama_no": baska.rental_no if baska else None,
                "kiralama_durumu": baska.status if baska else None,
                "baslangic": t.baslangic.isoformat(),
                "bitis": t.bitis.isoformat(),
            }
        )
    return satirlar


async def cakisma_denetle(
    db: AsyncSession,
    kiralama: Rental,
    istekler: list[tuple[RentalAsset, date, date, int | None]],
    onay: CakismaOnayi | None,
) -> None:
    """Seri cihaz çakışmalarını TOPLU denetler (yazmadan ÖNCE çağrılır).

    `istekler` = (cihaz, başlangıç, bitiş, hariç tutulacak tahsis). Aynı
    kiralamadaki AKTİF tahsisle çakışma her zaman hatadır; başka kiralamayla
    çakışma onaysızsa `CakismaUyarisi`, onaylıysa `onay.gecilenler`e eklenir.
    """
    bulunan: list[dict[str, Any]] = []
    for cihaz, bas, bit, haric in istekler:
        cakisan = await _seri_cakismalari(db, cihaz, bas, bit, haric_tahsis_id=haric)
        if any(t.rental_id == kiralama.id for t in cakisan):
            raise KiralamaHatasi(f"'{cihaz.serial_no}' bu kiralamada zaten tahsisli")
        bulunan.extend(await _cakisma_satirlari(db, cihaz, cakisan))
    if not bulunan:
        return
    if onay is None:
        raise CakismaUyarisi(bulunan)
    onay.gecilenler.extend(bulunan)


async def tahsis_et(
    db: AsyncSession,
    kiralama: Rental,
    satirlar: list[TahsisSatiri],
    *,
    user: User,
    clock: Clock,
    replaced_allocation_id: int | None = None,
    cakisma_onayi: CakismaOnayi | None = None,
) -> list[RentalAllocation]:
    """Kalemleri depodaki cihaz/adetle karşılar (`kind=TAHSIS`, durum değişmez).

    Katalog satırları `product_id` sıralı FOR UPDATE; seri cihaz satırları da
    kilitlenir. İlk tahsiste PLANLANDI → HAZIRLANIYOR. Kalem toplamını aşan,
    müsait olmayan istek 409. Başka kiralamaya tarih çakışan seri cihaz
    `CakismaUyarisi` (409) — `cakisma_onayi` verilirse kaydedilir (M10.1).
    """
    if kiralama.status not in TAHSIS_DURUMLARI_IZINLI:
        if kiralama.status == "TALEP":
            raise KiralamaHatasi("Talep aşamasındaki kiralamaya tahsis yapılamaz; önce planlayın")
        raise KiralamaHatasi(f"'{DURUM_ADLARI[kiralama.status]}' kiralamaya tahsis yapılamaz")
    if not satirlar:
        raise girdi("Tahsis satırı yok")
    kalem_haritasi = {k.id: k for k in await kalemler(db, kiralama.id)}
    for s in satirlar:
        if s.kalem_id not in kalem_haritasi:
            raise girdi("Kalem bu kiralamaya ait değil")
    await katalog_kilitle(db, {kalem_haritasi[s.kalem_id].product_id for s in satirlar})
    seri_idler = [i for s in satirlar for i in (s.kiralik_idler or [])]
    if len(seri_idler) != len(set(seri_idler)):
        raise girdi("Aynı cihaz iki kez seçildi")
    cihazlar = await cihazlari_kilitle(db, seri_idler)
    # Çakışma uyarısı yazmadan ÖNCE ve TOPLU: kullanıcı bütün çakışmaları tek
    # pencerede görür, onayladığında hepsi birlikte geçilir (M10.1).
    await cakisma_denetle(
        db,
        kiralama,
        [(c, kiralama.baslangic, kiralama.bitis, None) for c in cihazlar.values()],
        cakisma_onayi,
    )
    mevcut = await tahsisler(db, kiralama.id)
    eklenen_kalem: dict[int, int] = {}
    eklenen_depo: dict[tuple[int, int], int] = {}
    yeni: list[RentalAllocation] = []
    hareket_idler: list[int] = []
    for s in satirlar:
        kalem = kalem_haritasi[s.kalem_id]
        urun = await db.get(Product, kalem.product_id)
        aktif = sum(t.qty for t in mevcut if t.rental_item_id == kalem.id and t.durum == "AKTIF")
        aktif += eklenen_kalem.get(kalem.id, 0)
        if seri_takipli_mi(urun):
            if not s.kiralik_idler:
                raise girdi(f"'{urun.code}' seri takipli; cihaz seçilerek tahsis edilir")
            if s.adet not in (None, len(s.kiralik_idler)):
                raise girdi("Seri takipli üründe adet seçilen cihaz sayısıdır")
            istenen = len(s.kiralik_idler)
        else:
            if s.kiralik_idler:
                raise girdi(f"'{urun.code}' seri takipli değil; depo ve adet girilir")
            if not s.adet or s.adet <= 0:
                raise girdi("Tahsis adedi sıfırdan büyük olmalı")
            istenen = s.adet
        if aktif + istenen > kalem.qty:
            raise KiralamaHatasi(
                f"{urun.code}: kalem {kalem.qty} adet; {aktif} adet zaten tahsisli, "
                f"{istenen} adet daha tahsis edilemez"
            )
        if seri_takipli_mi(urun):
            for cid in s.kiralik_idler:
                cihaz = cihazlar.get(cid)
                if cihaz is None:
                    raise girdi("Seçilen kiralık cihaz bulunamadı")
                if cihaz.product_id != kalem.product_id:
                    raise girdi(f"'{cihaz.serial_no}' bu kalemin ürünü değil")
                if cihaz.birim != kiralama.birim:
                    raise girdi(f"'{cihaz.serial_no}' başka birimin envanterinde")
                if cihaz.durum != "HAZIR":
                    raise KiralamaHatasi(
                        f"'{cihaz.serial_no}' {DURUM_ETIKETLERI[cihaz.durum]}; yalnız hazır cihaz "
                        "tahsis edilir"
                    )
                await kiralama_deposu(db, cihaz.warehouse_id, kiralama.birim)
                tahsis = RentalAllocation(
                    rental_id=kiralama.id,
                    rental_item_id=kalem.id,
                    product_id=kalem.product_id,
                    asset_id=cihaz.id,
                    from_warehouse_id=cihaz.warehouse_id,
                    qty=1,
                    baslangic=kiralama.baslangic,
                    bitis=kiralama.bitis,
                    durum="AKTIF",
                    replaced_allocation_id=replaced_allocation_id,
                    created_by=user.id,
                    updated_by=user.id,
                )
                db.add(tahsis)
                await db.flush()
                yeni.append(tahsis)
                hareket = await hareket_yaz(
                    db,
                    tur="TAHSIS",
                    product_id=cihaz.product_id,
                    qty=1,
                    clock=clock,
                    user=user,
                    asset=cihaz,
                    from_warehouse_id=cihaz.warehouse_id,
                    to_warehouse_id=cihaz.warehouse_id,
                    from_durum="HAZIR",
                    to_durum="HAZIR",
                    rental_id=kiralama.id,
                    allocation_id=tahsis.id,
                    note=kiralama.rental_no,
                )
                hareket_idler.append(hareket.id)
        else:
            depo = await kiralama_deposu(db, s.depo_id, kiralama.birim)
            anahtar = (kalem.product_id, depo.id)
            serbest = await bakiye(db, kalem.product_id, depo.id, "HAZIR")
            serbest -= await rezerve_toplu(
                db, kalem.product_id, depo.id, baslangic=kiralama.baslangic, bitis=kiralama.bitis
            )
            serbest -= eklenen_depo.get(anahtar, 0)
            if serbest < istenen:
                raise KiralamaHatasi(
                    f"{urun.code}: {depo.name} deposunda bu tarihler için serbest "
                    f"{max(serbest, 0)} adet var; {istenen - max(serbest, 0)} adet eksik"
                )
            tahsis = RentalAllocation(
                rental_id=kiralama.id,
                rental_item_id=kalem.id,
                product_id=kalem.product_id,
                from_warehouse_id=depo.id,
                qty=istenen,
                baslangic=kiralama.baslangic,
                bitis=kiralama.bitis,
                durum="AKTIF",
                replaced_allocation_id=replaced_allocation_id,
                created_by=user.id,
                updated_by=user.id,
            )
            db.add(tahsis)
            await db.flush()
            yeni.append(tahsis)
            hareket = await hareket_yaz(
                db,
                tur="TAHSIS",
                product_id=kalem.product_id,
                qty=istenen,
                clock=clock,
                user=user,
                from_warehouse_id=depo.id,
                to_warehouse_id=depo.id,
                from_durum="HAZIR",
                to_durum="HAZIR",
                rental_id=kiralama.id,
                allocation_id=tahsis.id,
                note=kiralama.rental_no,
                bakiye_dogrula=False,
            )
            hareket_idler.append(hareket.id)
            eklenen_depo[anahtar] = eklenen_depo.get(anahtar, 0) + istenen
        eklenen_kalem[kalem.id] = eklenen_kalem.get(kalem.id, 0) + istenen
    onceki = kiralama.status
    if kiralama.status == "PLANLANDI":
        durum_ata(kiralama, "HAZIRLANIYOR", user)
    await olay_yaz(
        db,
        kiralama,
        "TAHSIS",
        user=user,
        clock=clock,
        onceki_durum=onceki,
        yeni_durum=kiralama.status,
        yeni={"tahsisler": [t.id for t in yeni], "hareketler": hareket_idler},
    )
    return yeni


async def kapsamli_tahsis(db: AsyncSession, kiralama: Rental, tahsis_id: int) -> RentalAllocation:
    tahsis = await db.scalar(
        select(RentalAllocation)
        .where(RentalAllocation.id == tahsis_id, RentalAllocation.rental_id == kiralama.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tahsis is None:
        raise bulunamadi("Tahsis bulunamadı")
    return tahsis


async def _tahsisi_coz(
    db: AsyncSession,
    kiralama: Rental,
    tahsis: RentalAllocation,
    *,
    user: User,
    clock: Clock,
    hedef: str = "COZULDU",
    note: str | None = None,
) -> int | None:
    """Tahsisin sevk edilmemiş kısmını serbest bırakır (`kind=TAHSIS_COZ`)."""
    kalan = tahsis.qty - tahsis.sevk_adet
    hareket_id = None
    if kalan > 0:
        cihaz = None
        if tahsis.asset_id is not None:
            cihaz = (await cihazlari_kilitle(db, [tahsis.asset_id])).get(tahsis.asset_id)
        hareket = await hareket_yaz(
            db,
            tur="TAHSIS_COZ",
            product_id=tahsis.product_id,
            qty=kalan,
            clock=clock,
            user=user,
            asset=cihaz,
            from_warehouse_id=tahsis.from_warehouse_id,
            to_warehouse_id=tahsis.from_warehouse_id,
            from_durum=cihaz.durum if cihaz is not None else "HAZIR",
            to_durum=cihaz.durum if cihaz is not None else "HAZIR",
            rental_id=kiralama.id,
            allocation_id=tahsis.id,
            note=note or kiralama.rental_no,
            bakiye_dogrula=False,
        )
        hareket_id = hareket.id
    tahsis.durum = hedef
    tahsis.closed_at = clock.now()
    tahsis.updated_by = user.id
    await db.flush()
    return hareket_id


async def tahsis_coz(
    db: AsyncSession, kiralama: Rental, tahsis: RentalAllocation, *, user: User, clock: Clock
) -> RentalAllocation:
    """Yalnız sevk edilmemiş AKTİF tahsis çözülür (409)."""
    if kiralama.status in ("KAPANDI", "IPTAL"):
        raise KiralamaHatasi("Kapalı kiralamada tahsis değiştirilemez")
    if tahsis.durum != "AKTIF":
        raise KiralamaHatasi("Tahsis aktif değil")
    if tahsis.sevk_adet > 0:
        raise KiralamaHatasi("Sevk edilmiş tahsis çözülemez; önce iade alın")
    hareket_id = await _tahsisi_coz(db, kiralama, tahsis, user=user, clock=clock)
    await olay_yaz(
        db,
        kiralama,
        "TAHSIS",
        user=user,
        clock=clock,
        alan="tahsis_coz",
        yeni={"tahsis_id": tahsis.id, "hareketler": [hareket_id] if hareket_id else []},
    )
    return tahsis


async def tahsisleri_coz(
    db: AsyncSession, kiralama: Rental, *, user: User, clock: Clock, note: str | None = None
) -> list[int]:
    """İptal/kapanışta kalan AKTİF tahsislerin sevk edilmemiş kısımlarını çözer."""
    hareketler = []
    for t in await tahsisler(db, kiralama.id, kilit=True):
        if t.durum != "AKTIF":
            continue
        hedef = "COZULDU" if t.sevk_adet == 0 else "KAPANDI"
        hid = await _tahsisi_coz(db, kiralama, t, user=user, clock=clock, hedef=hedef, note=note)
        if hid:
            hareketler.append(hid)
    return hareketler


# --- Sevk (TS-113, E06-06/07) -----------------------------------------------------------


@dataclass
class SevkSatiri:
    tahsis_id: int
    adet: int | None = None


async def sevk_et(
    db: AsyncSession,
    kiralama: Rental,
    satirlar: list[SevkSatiri] | None,
    *,
    at: datetime | None,
    user: User,
    clock: Clock,
    note: str | None = None,
) -> RentalEvent:
    """Sevk: HAZIRLANIYOR → SEVK_EDILDI (her kalemde Σ AKTİF tahsis = kalem adedi,
    eksikse 400 ve eksik listesi); sevk sonrası yalnız seçilen tahsisler (ek sevk).

    İlk sevk bütün tahsisleri göndermek zorunda değildir (satır seçilebilir).
    Seri cihaz HAZIR → KIRADA (HAZIR değilse 409); toplu `(depo, HAZIR) →
    (KIRADA)`.
    """
    an = asama_zamani(at, kiralama, clock)
    tahsis_listesi = await tahsisler(db, kiralama.id, kilit=True)
    aktifler = {t.id: t for t in tahsis_listesi if t.durum == "AKTIF"}
    if kiralama.status == "HAZIRLANIYOR":
        eksikler = []
        for kalem in await kalemler(db, kiralama.id):
            tahsisli = sum(t.qty for t in aktifler.values() if t.rental_item_id == kalem.id)
            if tahsisli != kalem.qty:
                urun = await db.get(Product, kalem.product_id)
                eksikler.append(
                    f"{urun.code if urun else kalem.product_id}: {kalem.qty - tahsisli} adet "
                    "eksik tahsis"
                )
        if eksikler:
            raise KiralamaHatasi(
                "Sevk için her kalem tamamen tahsis edilmeli — " + "; ".join(eksikler),
                "GIRDI",
                veri={"eksikler": eksikler},
            )
        hedef_durum: str | None = "SEVK_EDILDI"
        gecis_dogrula(kiralama.status, "SEVK_EDILDI")
    elif kiralama.status in EK_SEVK_DURUMLARI:
        if not satirlar:
            raise girdi("Ek sevk için gönderilecek tahsisleri seçin")
        hedef_durum = None
    else:
        raise KiralamaHatasi(
            f"'{DURUM_ADLARI[kiralama.status]}' kiralamada sevk yapılamaz"
            + (" (önce tahsis yapın)" if kiralama.status in ("TALEP", "PLANLANDI") else "")
        )
    if satirlar is None:
        secim = [(t, t.qty - t.sevk_adet) for t in aktifler.values() if t.qty > t.sevk_adet]
    else:
        secim = []
        gorulen: set[int] = set()
        for s in satirlar:
            if s.tahsis_id in gorulen:
                raise girdi("Aynı tahsis iki kez seçildi")
            gorulen.add(s.tahsis_id)
            t = aktifler.get(s.tahsis_id)
            if t is None:
                raise girdi("Seçilen tahsis bu kiralamada aktif değil")
            kalan = t.qty - t.sevk_adet
            adet = kalan if s.adet is None else s.adet
            if adet <= 0 or adet > kalan:
                raise girdi(f"Tahsis #{t.id} için sevk edilebilecek adet {kalan}")
            secim.append((t, adet))
    if not secim:
        raise girdi("Sevk edilecek tahsis yok")
    await katalog_kilitle(db, {t.product_id for t, _ in secim})
    cihazlar = await cihazlari_kilitle(db, [t.asset_id for t, _ in secim if t.asset_id])
    hareket_idler: list[int] = []
    sayaclar: list[dict[str, Any]] = []
    for t, adet in sorted(secim, key=lambda x: x[0].id):
        cihaz = cihazlar.get(t.asset_id) if t.asset_id else None
        hareket = await hareket_yaz(
            db,
            tur="SEVK",
            product_id=t.product_id,
            qty=adet,
            clock=clock,
            user=user,
            asset=cihaz,
            from_warehouse_id=cihaz.warehouse_id if cihaz is not None else t.from_warehouse_id,
            from_durum="HAZIR",
            to_durum="KIRADA",
            rental_id=kiralama.id,
            allocation_id=t.id,
            note=note or kiralama.rental_no,
        )
        hareket_idler.append(hareket.id)
        sayaclar.append({"tahsis_id": t.id, "sevk": adet, "shipped_at_bostu": t.shipped_at is None})
        t.sevk_adet += adet
        if t.shipped_at is None:
            t.shipped_at = an
        t.updated_by = user.id
    onceki = kiralama.status
    if hedef_durum is not None:
        durum_ata(kiralama, hedef_durum, user)
    await db.flush()
    return await olay_yaz(
        db,
        kiralama,
        "SEVK",
        user=user,
        clock=clock,
        at=an,
        onceki_durum=onceki,
        yeni_durum=kiralama.status,
        yeni={"hareketler": hareket_idler, "sayaclar": sayaclar},
        gerekce=note,
    )


# --- İade (TS-113, E06-07) ----------------------------------------------------------------


@dataclass
class IadeSatiri:
    tahsis_id: int
    sonuc: str
    adet: int | None = None
    depo_id: int | None = None
    note: str | None = None


async def iade_al(
    db: AsyncSession,
    kiralama: Rental,
    satirlar: list[IadeSatiri],
    *,
    at: datetime | None,
    user: User,
    clock: Clock,
) -> RentalEvent:
    """İade: IADE_ALINDI → (depo, KONTROLDE), KAYIP → KAYIP, MUSTERIDE yalnız not.

    Sevk edilmemiş tahsis reddedilir (400). Bütün AKTİF tahsislerde müşteride
    adet kalmayınca DEPOYA_ALINDI; kurulum yapılmış kiralamada önce TOPLANDI
    girilmeli (409). Hasar/eksik tespiti kontrolde yapılır, iadede değil.
    """
    if kiralama.status not in SEVK_SONRASI:
        raise KiralamaHatasi(f"'{DURUM_ADLARI[kiralama.status]}' kiralamada iade alınamaz")
    if not satirlar:
        raise girdi("İade satırı yok")
    an = asama_zamani(at, kiralama, clock)
    tahsis_listesi = await tahsisler(db, kiralama.id, kilit=True)
    aktifler = {t.id: t for t in tahsis_listesi if t.durum == "AKTIF"}
    plan: list[tuple[RentalAllocation, IadeSatiri, int]] = []
    kalan_sayac: dict[int, int] = {}
    for s in satirlar:
        if s.sonuc not in IADE_SONUCLARI:
            raise girdi(f"Bilinmeyen iade sonucu: {s.sonuc}")
        t = aktifler.get(s.tahsis_id)
        if t is None:
            raise girdi("Seçilen tahsis bu kiralamada aktif değil")
        if t.sevk_adet == 0:
            raise girdi(f"Tahsis #{t.id} sevk edilmemiş; iade alınamaz")
        kalan = kalan_sayac.get(t.id, disarida(t))
        adet = s.adet if s.adet is not None else (1 if t.asset_id else kalan)
        if adet <= 0 or adet > kalan:
            raise girdi(f"Tahsis #{t.id} için müşteride {kalan} adet var")
        if s.sonuc != "MUSTERIDE":
            kalan_sayac[t.id] = kalan - adet
        if s.sonuc == "IADE_ALINDI" and s.depo_id is None:
            raise girdi("İade alınan cihaz için depo seçilmeli")
        plan.append((t, s, adet))
    # Son iadede kenar kuralı yazmadan ÖNCE sınanır.
    disarida_kalan = sum(kalan_sayac.get(t.id, disarida(t)) for t in aktifler.values())
    tamamlaniyor = disarida_kalan == 0 and any(s.sonuc != "MUSTERIDE" for s in satirlar)
    if tamamlaniyor and kiralama.status in ("KURULUM_YAPILDI", "DEVREYE_ALINDI"):
        raise KiralamaHatasi(
            "Kurulum yapılmış kiralamada son iade için önce 'Toplandı' aşaması girilmeli"
        )
    await katalog_kilitle(db, {t.product_id for t, _, _ in plan})
    cihazlar = await cihazlari_kilitle(db, [t.asset_id for t, _, _ in plan if t.asset_id])
    hareket_idler: list[int] = []
    sayaclar: list[dict[str, Any]] = []
    notlar: list[dict[str, Any]] = []
    for t, s, adet in plan:
        cihaz = cihazlar.get(t.asset_id) if t.asset_id else None
        if s.sonuc == "MUSTERIDE":
            notlar.append({"tahsis_id": t.id, "adet": adet, "not": (s.note or "")[:200]})
            continue
        if s.sonuc == "IADE_ALINDI":
            depo = await kiralama_deposu(db, s.depo_id, kiralama.birim)
            hareket = await hareket_yaz(
                db,
                tur="IADE",
                product_id=t.product_id,
                qty=adet,
                clock=clock,
                user=user,
                asset=cihaz,
                from_durum="KIRADA",
                to_warehouse_id=depo.id,
                to_durum="KONTROLDE",
                rental_id=kiralama.id,
                allocation_id=t.id,
                note=s.note or kiralama.rental_no,
            )
            t.iade_adet += adet
            sayaclar.append({"tahsis_id": t.id, "iade": adet})
        else:
            hareket = await hareket_yaz(
                db,
                tur="KAYIP",
                product_id=t.product_id,
                qty=adet,
                clock=clock,
                user=user,
                asset=cihaz,
                from_durum="KIRADA",
                to_durum="KAYIP",
                rental_id=kiralama.id,
                allocation_id=t.id,
                note=s.note or kiralama.rental_no,
            )
            t.kayip_adet += adet
            sayaclar.append({"tahsis_id": t.id, "kayip": adet})
        hareket_idler.append(hareket.id)
        t.updated_by = user.id
    kapanan: list[int] = []
    for t in aktifler.values():
        if t.sevk_adet == t.qty and disarida(t) == 0 and t.id in {x[0].id for x in plan}:
            t.durum = "KAPANDI"
            t.closed_at = an
            kapanan.append(t.id)
    onceki = kiralama.status
    if tamamlaniyor:
        durum_ata(kiralama, "DEPOYA_ALINDI", user)
    await db.flush()
    return await olay_yaz(
        db,
        kiralama,
        "IADE",
        user=user,
        clock=clock,
        at=an,
        onceki_durum=onceki,
        yeni_durum=kiralama.status,
        yeni={
            "hareketler": hareket_idler,
            "sayaclar": sayaclar,
            "kapanan_tahsisler": kapanan,
            "musteride": notlar,
        },
    )


# --- Sahada cihaz değişimi (TS-195, E06-20) ----------------------------------------------


DEGISIM_DURUMLARI = EK_SEVK_DURUMLARI


async def degisim(
    db: AsyncSession,
    kiralama: Rental,
    *,
    eski_tahsis_id: int,
    yeni_kiralik_id: int,
    iade_depo_id: int,
    user: User,
    clock: Clock,
    note: str | None = None,
    cakisma_onayi: CakismaOnayi | None = None,
) -> RentalEvent:
    """Sahadaki seri cihazı başka bir cihazla TEK transaction'da değiştirir.

    Sıra: (1) yeni cihaza tahsis (`replaced_allocation_id` = eski tahsis),
    (2) yeni cihazın sevki HAZIR → KIRADA, (3) eski cihazın iadesi KIRADA →
    (iade deposu, KONTROLDE). Her iki cihaz hareketi `kind=DEGISIM`; eski
    tahsis KAPANDI olur. Ayrı veri modeli yoktur (E06-20).

    Kiralama durumu DEĞİŞMEZ (müşterideki adet aynı kalır). Yeni cihaz HAZIR
    değilse ya da başka birimdeyse 409; tarihleri çakışan başka bir AKTİF
    tahsisi varsa `CakismaUyarisi` (onay + gerekçeyle geçilir, M10.1). Yalnız
    seri takipli cihaz değiştirilir; toplu üründe iade + ek tahsis kullanılır
    (400).
    """
    if kiralama.status not in DEGISIM_DURUMLARI:
        raise KiralamaHatasi(
            f"'{DURUM_ADLARI[kiralama.status]}' kiralamada sahada değişim yapılamaz; "
            "yalnız sevk edilmiş, sahadaki kiralamada"
        )
    tahsis_listesi = await tahsisler(db, kiralama.id, kilit=True)
    eski = next((t for t in tahsis_listesi if t.id == eski_tahsis_id), None)
    if eski is None or eski.durum != "AKTIF":
        raise girdi("Değiştirilecek tahsis bu kiralamada aktif değil")
    if eski.asset_id is None:
        raise girdi("Toplu üründe sahada değişim yapılmaz; iade alıp ek tahsis ve sevk kullanın")
    if disarida(eski) != 1:
        raise KiralamaHatasi(
            "Değiştirilecek cihaz müşteride görünmüyor (sevk edilmemiş ya da iade)"
        )
    if yeni_kiralik_id == eski.asset_id:
        raise girdi("Yeni cihaz eskisiyle aynı olamaz")
    await katalog_kilitle(db, [eski.product_id])
    cihazlar = await cihazlari_kilitle(db, [eski.asset_id, yeni_kiralik_id])
    eski_cihaz = cihazlar.get(eski.asset_id)
    yeni_cihaz = cihazlar.get(yeni_kiralik_id)
    if yeni_cihaz is None:
        raise girdi("Yeni kiralık cihaz bulunamadı")
    if yeni_cihaz.product_id != eski.product_id:
        raise girdi(f"'{yeni_cihaz.serial_no}' değiştirilen cihazla aynı ürün değil")
    if yeni_cihaz.birim != kiralama.birim:
        raise girdi(f"'{yeni_cihaz.serial_no}' başka birimin envanterinde")
    if yeni_cihaz.durum != "HAZIR":
        raise KiralamaHatasi(
            f"'{yeni_cihaz.serial_no}' {DURUM_ETIKETLERI[yeni_cihaz.durum]}; yalnız hazır cihaz "
            "sahaya gönderilir"
        )
    iade_deposu = await kiralama_deposu(db, iade_depo_id, kiralama.birim, alan="İade deposu")
    kaynak_depo = await kiralama_deposu(db, yeni_cihaz.warehouse_id, kiralama.birim)
    bugun_ = yerel_bugun(clock)
    # Yeni tahsis bugünden başlar (geçmiş tarihlere sahte rezerv yazılmaz);
    # gecikmiş kiralamada en az bir günlük aralık korunur (`bitis > baslangic`).
    baslangic = max(kiralama.baslangic, min(bugun_, kiralama.bitis - timedelta(days=1)))
    bitis = max(kiralama.bitis, baslangic + timedelta(days=1))
    await cakisma_denetle(db, kiralama, [(yeni_cihaz, baslangic, bitis, None)], cakisma_onayi)
    metin = (note or "").strip()
    an = clock.now()
    yeni = RentalAllocation(
        rental_id=kiralama.id,
        rental_item_id=eski.rental_item_id,
        product_id=eski.product_id,
        asset_id=yeni_cihaz.id,
        from_warehouse_id=kaynak_depo.id,
        qty=1,
        sevk_adet=1,
        baslangic=baslangic,
        bitis=bitis,
        durum="AKTIF",
        shipped_at=an,
        replaced_allocation_id=eski.id,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(yeni)
    await db.flush()
    etiket = f"{kiralama.rental_no} değişim: {eski_cihaz.serial_no} → {yeni_cihaz.serial_no}"
    if metin:
        etiket = f"{etiket} — {metin}"
    giden = await hareket_yaz(
        db,
        tur="DEGISIM",
        product_id=yeni_cihaz.product_id,
        qty=1,
        clock=clock,
        user=user,
        asset=yeni_cihaz,
        from_warehouse_id=kaynak_depo.id,
        from_durum="HAZIR",
        to_durum="KIRADA",
        rental_id=kiralama.id,
        allocation_id=yeni.id,
        note=etiket,
    )
    donen = await hareket_yaz(
        db,
        tur="DEGISIM",
        product_id=eski_cihaz.product_id,
        qty=1,
        clock=clock,
        user=user,
        asset=eski_cihaz,
        from_durum="KIRADA",
        to_warehouse_id=iade_deposu.id,
        to_durum="KONTROLDE",
        rental_id=kiralama.id,
        allocation_id=eski.id,
        note=etiket,
    )
    eski.iade_adet += 1
    eski.durum = "KAPANDI"
    eski.closed_at = an
    eski.updated_by = user.id
    await db.flush()
    return await olay_yaz(
        db,
        kiralama,
        "TAHSIS",
        user=user,
        clock=clock,
        alan="degisim",
        eski={"tahsis_id": eski.id, "seri": eski_cihaz.serial_no},
        yeni={
            "tahsis_id": yeni.id,
            "seri": yeni_cihaz.serial_no,
            "hareketler": [giden.id, donen.id],
        },
        gerekce=metin or None,
    )


async def ozet_seriler(db: AsyncSession, tahsis_listesi: list[RentalAllocation]) -> dict[int, str]:
    """Tahsis → seri metni (yalnız seri cihazlı tahsisler)."""
    idler = [t.asset_id for t in tahsis_listesi if t.asset_id]
    if not idler:
        return {}
    cihazlar = {
        c.id: c
        for c in (await db.scalars(select(RentalAsset).where(RentalAsset.id.in_(idler)))).all()
    }
    return {t.id: cihazlar[t.asset_id].serial_no for t in tahsis_listesi if t.asset_id in cihazlar}


async def tarihleri_uygula(
    db: AsyncSession,
    kiralama: Rental,
    baslangic: date,
    bitis: date,
    *,
    user: User,
    cakisma_onayi: CakismaOnayi | None = None,
) -> None:
    """AKTİF tahsislerin tarihlerini kiralamayla eşitler (uzatma, K15).

    Seri cihaz yeni tarihlerde başka kiralamaya çakışırsa `CakismaUyarisi`
    (409 + liste); `cakisma_onayi` verilirse uygulanır (M10.1).
    """
    aktifler = [t for t in await tahsisler(db, kiralama.id, kilit=True) if t.durum == "AKTIF"]
    seri = [t for t in aktifler if t.asset_id is not None]
    if seri:
        cihazlar = {
            c.id: c
            for c in (
                await db.scalars(
                    select(RentalAsset).where(RentalAsset.id.in_([t.asset_id for t in seri]))
                )
            ).all()
        }
        await cakisma_denetle(
            db,
            kiralama,
            [(cihazlar[t.asset_id], baslangic, bitis, t.id) for t in seri],
            cakisma_onayi,
        )
    for t in aktifler:
        t.baslangic = baslangic
        t.bitis = bitis
        t.updated_by = user.id
    await db.flush()


def bugun(clock: Clock) -> date:
    return yerel_bugun(clock)


async def katalog_birimi(db: AsyncSession, product_id: int) -> str | None:
    profil = await katalog_profili(db, product_id)
    return profil.birim if profil is not None else None
