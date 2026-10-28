"""Kiralama başlığı, kalem, irtibat, durum, iptal, kapanış, geri alma (E06).

Maddeler: TS-110, TS-113, TS-114, TS-117, TS-120. D2-C.

**Müşteri = hesap, lokasyon = adres** (plan §1.5): tek doğrulayıcı
`ana_veri.lokasyon_dogrula` (müşteri değil/pasif/yok → 400). Kiralama birimi
katalog profilinin birimiyle aynı olmalı; mobilite ve araç takip birimlerinde
kiralama açılmaz (E06-D04/D05). Başlıkta ürün/seri kopyası YOK: kalem
`rental_items`'ta, seri tahsiste.

**Durum yalnız `KIRALAMA` makinesiyle** ve yalnız aşama uçlarından ilerler
(planla, tahsis, sevk, aşama, iade, iptal, kapat); PUT durum kabul etmez
(400). Aynı aşamanın tekrarı yasak geçiştir (409).

**Aşama geri alma (E06-08) — bilinçli sapma:** makineye ters kenar
EKLENMEZ; `asama_geri_al` yalnız SON aşama olayını (sevk, iade, kurulum/
devreye alma/toplama) ters hareketlerle çevirir, sayaçları geri sarar ve
durumu olayın `onceki_durum`'una DOĞRUDAN atar. Atamadan önce ileri geçişin
makinede gerçekten var olduğu (`KIRALAMA.dogrula(onceki, yeni)`) ve kaydın
hâlâ o olayın ürettiği durumda olduğu doğrulanır. Normal uçlardan geriye
gidiş bu yüzden mümkün değildir; KAPANDI ve IPTAL geri alınamaz.

**Kurulum/toplama servis işi (TS-120):** servis işi çekirdeğinin
`is_emirleri.olustur()` fonksiyonuyla `PLANLAMADA` açılır,
`service_orders.rental_id` bağlanır (`uq_so_kiralama_tur_acik`: kiralama +
tür başına tek açık iş). İş TAMAMLANDI olunca `durum_degisti` kancası
(`asama_oner`) kiralama geçmişine öneri yazar; aşama OTOMATİK YAZILMAZ,
onayı `kiralama.asama` sahibi verir. `work_orders`'a hiçbir şey yazılmaz.

**Kanca kayıtları** (dosyanın EN ALTINDA): `durum_degisti → asama_oner`,
ek kapsamı `rentals` ve `rental_assets`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, exists, func, or_, select

from app.models import (
    Account,
    Address,
    Contact,
    Product,
    Quote,
    Rental,
    RentalAllocation,
    RentalContact,
    RentalEvent,
    RentalItem,
    ServiceOrder,
    User,
)
from app.models.servis_kiralama import (
    IRTIBAT_ROLLERI,
    KIRALAMA_DURUMLARI,
    KIRALAMA_SERVIS_TURLERI,
)
from app.permissions import BIRIMLER
from app.services import audit
from app.services.accounts import kapsam_disinda_mi, kapsam_musteri
from app.services.statemachine import KIRALAMA, SERVIS_IS_EMRI
from app.services.teknik_servis import ek_kapsam, kancalar
from app.services.teknik_servis import kiralama_tahsis as tahsis_svc
from app.services.teknik_servis.kapsam import birim_disinda_mi, kapsam_birim
from app.services.teknik_servis.kiralama_tahsis import (
    DURUM_ADLARI,
    REZERV_DURUMLARI,
    SEVK_SONRASI,
    asama_zamani,
    durum_ata,
    gecis_dogrula,
    olay_yaz,
)
from app.services.teknik_servis.kiralik_envanter import (
    KiralamaHatasi,
    aktif_katalog,
    birim_dogrula,
    bulunamadi,
    girdi,
    kiralik_kosulu,
    ters_hareket_yaz,
    urun_dogrula,
)
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

ENTITY = "rentals"
ASAMA_HEDEFLERI = ("KURULUM_YAPILDI", "DEVREYE_ALINDI", "TOPLANDI")
GERI_ALINABILIR_OLAYLAR = ("SEVK", "IADE", "ASAMA")
KAPALI_DURUMLAR = ("KAPANDI", "IPTAL")
EKSIK_TAHSIS_GUN = 3
IRTIBAT_ROL_ADLARI = {
    "SATIN_ALMA": "Satın alma",
    "SAHA_OPERASYON": "Saha operasyon",
    "TEKNIK_SORUMLU": "Teknik sorumlu",
    "DIGER": "Diğer",
}

__all__ = [
    "KIRALAMA_DURUMLARI",
    "KiralamaHatasi",
    "asama_geri_al",
    "asama_ilerlet",
    "asama_oner",
    "iptal",
    "kapat",
    "kapsamli_kiralama",
    "olustur",
    "planla",
    "servis_isi_ac",
    "tutanak_baglami",
]


# --- Kapsam ------------------------------------------------------------------------


def kiralama_kosulu(stmt: Select, user: User) -> Select:
    """Kiralama listelerine kapsam: birim (`user_units`) + müşteri portföyü."""
    stmt = kapsam_birim(stmt, user, Rental.birim, birimsiz_gorunur=False)
    return kapsam_musteri(stmt, user, Rental.customer_id)


async def kapsamli_kiralama(
    db: AsyncSession, user: User, kiralama_id: int, *, kilit: bool = False
) -> Rental:
    """Kiralamayı kapsamıyla getirir; yoksa ya da kapsam dışıysa 404 (yazma yok)."""
    stmt = select(Rental).where(Rental.id == kiralama_id, Rental.is_deleted.is_(False))
    stmt = kiralama_kosulu(stmt, user)
    if kilit:
        stmt = stmt.with_for_update(of=Rental).execution_options(populate_existing=True)
    kiralama = await db.scalar(stmt)
    if kiralama is None:
        raise bulunamadi("Kiralama bulunamadı")
    return kiralama


# --- Girdi -------------------------------------------------------------------------


@dataclass
class KalemGirdisi:
    product_id: int
    qty: int
    note: str | None = None
    id: int | None = None


@dataclass
class IrtibatGirdisi:
    contact_id: int
    rol: str
    id: int | None = None


@dataclass
class KiralamaGirdisi:
    birim: str
    customer_id: int | None
    baslangic: date
    bitis: date
    address_id: int | None = None
    lokasyon_metni: str | None = None
    proje_adi: str | None = None
    sorumlu_user_id: int | None = None
    quote_id: int | None = None
    notes: str | None = None
    kalemler: list[KalemGirdisi] = field(default_factory=list)
    irtibatlar: list[IrtibatGirdisi] = field(default_factory=list)


def _bos(deger: str | None) -> str | None:
    if deger is None:
        return None
    temiz = deger.strip()
    return temiz or None


async def _musteri_dogrula(
    db: AsyncSession, user: User, customer_id: int | None, address_id: int | None
) -> None:
    from app.services.teknik_servis import ana_veri

    if customer_id is None:
        raise girdi("Müşteri seçilmedi")
    try:
        await ana_veri.lokasyon_dogrula(db, customer_id, address_id, None)
    except ana_veri.AnaVeriHatasi as exc:
        raise girdi(exc.mesaj) from exc
    if await kapsam_disinda_mi(db, user, customer_id):
        raise bulunamadi("Müşteri bulunamadı")


def _tarih_dogrula(baslangic: date | None, bitis: date | None) -> None:
    if baslangic is None or bitis is None:
        raise girdi("Başlangıç ve bitiş tarihi zorunlu")
    if bitis <= baslangic:
        raise girdi("Bitiş (iade günü) başlangıçtan sonra olmalı")


async def _urun_kalemi_dogrula(db: AsyncSession, birim: str, k: KalemGirdisi) -> Product:
    if k.qty is None or k.qty <= 0:
        raise girdi("Kalem adedi sıfırdan büyük olmalı")
    urun = urun_dogrula(await db.get(Product, k.product_id))
    profil = await aktif_katalog(db, urun.id)
    if profil.birim != birim:
        raise girdi(
            f"'{urun.code}' {BIRIMLER.get(profil.birim, profil.birim)} biriminin kiralama "
            f"kataloğunda; {BIRIMLER.get(birim, birim)} kiralamasına eklenemez"
        )
    return urun


async def _sorumlu_dogrula(db: AsyncSession, user_id: int | None) -> None:
    if user_id is None:
        return
    kisi = await db.get(User, user_id)
    if kisi is None or not kisi.is_active:
        raise girdi("Sorumlu kullanıcı bulunamadı")


async def _teklif_dogrula(db: AsyncSession, quote_id: int | None) -> None:
    if quote_id is not None and await db.get(Quote, quote_id) is None:
        raise girdi("Kaynak teklif bulunamadı")


async def _irtibat_dogrula(
    db: AsyncSession, customer_id: int, irtibatlar: list[IrtibatGirdisi]
) -> None:
    gorulen: set[tuple[int, str]] = set()
    for i in irtibatlar:
        if i.rol not in IRTIBAT_ROLLERI:
            raise girdi(f"Bilinmeyen irtibat rolü: {i.rol}")
        kisi = await db.get(Contact, i.contact_id)
        if kisi is None or kisi.account_id != customer_id:
            raise girdi("Seçilen irtibat bu müşteriye ait değil")
        if (i.contact_id, i.rol) in gorulen:
            raise girdi("Aynı irtibat aynı rolle iki kez eklenemez")
        gorulen.add((i.contact_id, i.rol))


async def _kiralama_no(db: AsyncSession, clock: Clock) -> str:
    """`KIR-YYYYAA-NNNNNN` (`rental_no_seq`, OWNED BY rentals.id).

    `numara.belge_no` KIR önekini tanıdığında (D2-S talebi) ona devreder;
    tanımıyorsa aynı biçimi aynı sequence'ten üretir.
    """
    from sqlalchemy import text

    from app.services.teknik_servis import numara

    if numara.ONEKLER.get("KIR") == "rental_no_seq":
        return await numara.belge_no(db, "rental_no_seq", "KIR", clock.now())
    sira = await db.scalar(text("SELECT nextval('rental_no_seq')"))
    return f"KIR-{yerel_gun(clock.now()):%Y%m}-{int(sira):06d}"


# --- Oluşturma (TS-110) ---------------------------------------------------------------


async def olustur(
    db: AsyncSession,
    veri: KiralamaGirdisi,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> Rental:
    """Başlık + kalem + irtibat tek transaction; numara `rental_no_seq` (KIR-YYYYAA-NNNNNN)."""
    birim_dogrula(veri.birim)
    if birim_disinda_mi(user, veri.birim, birimsiz_gorunur=False):
        raise bulunamadi("Bu birimde kiralama açamazsınız")
    await _musteri_dogrula(db, user, veri.customer_id, veri.address_id)
    _tarih_dogrula(veri.baslangic, veri.bitis)
    if not veri.kalemler:
        raise girdi("En az bir kalem girilmeli")
    urunler: set[int] = set()
    for k in veri.kalemler:
        await _urun_kalemi_dogrula(db, veri.birim, k)
        if k.product_id in urunler:
            raise girdi("Aynı ürün iki kalemde olamaz; adedi artırın")
        urunler.add(k.product_id)
    await _irtibat_dogrula(db, veri.customer_id, veri.irtibatlar)
    await _sorumlu_dogrula(db, veri.sorumlu_user_id)
    await _teklif_dogrula(db, veri.quote_id)

    kiralama = Rental(
        rental_no=await _kiralama_no(db, clock),
        birim=veri.birim,
        customer_id=veri.customer_id,
        address_id=veri.address_id,
        lokasyon_metni=_bos(veri.lokasyon_metni),
        proje_adi=_bos(veri.proje_adi),
        baslangic=veri.baslangic,
        bitis=veri.bitis,
        status="TALEP",
        sorumlu_user_id=veri.sorumlu_user_id,
        quote_id=veri.quote_id,
        notes=_bos(veri.notes),
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(kiralama)
    await db.flush()
    for k in veri.kalemler:
        db.add(
            RentalItem(
                rental_id=kiralama.id,
                product_id=k.product_id,
                qty=k.qty,
                note=_bos(k.note),
                created_by=user.id,
            )
        )
    for i in veri.irtibatlar:
        db.add(
            RentalContact(
                rental_id=kiralama.id, contact_id=i.contact_id, rol=i.rol, created_by=user.id
            )
        )
    await db.flush()
    await olay_yaz(db, kiralama, "OLUSTUR", user=user, clock=clock, yeni_durum="TALEP")
    await audit.log(
        db,
        ENTITY,
        "olustur",
        entity_id=kiralama.id,
        new_value={
            "rental_no": kiralama.rental_no,
            "birim": kiralama.birim,
            "customer_id": kiralama.customer_id,
            "baslangic": str(kiralama.baslangic),
            "bitis": str(kiralama.bitis),
            "kalem_sayisi": len(veri.kalemler),
        },
        user_id=user.id,
        ip=ip,
    )
    return kiralama


# --- Güncelleme (E06-15) ----------------------------------------------------------------


async def _aktif_tahsis_toplamlari(db: AsyncSession, kiralama_id: int) -> dict[int, int]:
    satirlar = (
        await db.execute(
            select(RentalAllocation.rental_item_id, func.sum(RentalAllocation.qty))
            .where(RentalAllocation.rental_id == kiralama_id, RentalAllocation.durum == "AKTIF")
            .group_by(RentalAllocation.rental_item_id)
        )
    ).all()
    return {k: int(a) for k, a in satirlar}


async def guncelle(
    db: AsyncSession,
    kiralama: Rental,
    alanlar: dict[str, Any],
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
    cakisma_onayi: tahsis_svc.CakismaOnayi | None = None,
) -> Rental:
    """Başlık + kalem + irtibat TEK transaction (PUT). Durum ve birim kabul edilmez.

    Kalem: kimlikli satır güncellenir, kimliksiz eklenir, listede olmayan
    silinir. Tahsisli kalemin ürünü değişmez, adedi AKTİF tahsisin altına
    inmez, silinmez (409). AKTİF tahsis varken müşteri değişmez (409).
    Rezervli kiralamada adet artışı / tarih değişikliği müsaitlikten geçer.
    """
    if alanlar.get("status") is not None or alanlar.get("durum") is not None:
        raise girdi("Durum bu işlemle değiştirilemez; aşama işlemlerini kullanın")
    if alanlar.get("birim") is not None and alanlar["birim"] != kiralama.birim:
        raise girdi("Kiralamanın birimi değiştirilemez")
    if kiralama.status in KAPALI_DURUMLAR:
        raise KiralamaHatasi(f"'{DURUM_ADLARI[kiralama.status]}' kiralama düzenlenemez")
    aktif_toplam = await _aktif_tahsis_toplamlari(db, kiralama.id)

    # Müşteri / lokasyon
    yeni_musteri = alanlar.get("customer_id", kiralama.customer_id)
    if "customer_id" in alanlar and yeni_musteri is None:
        raise girdi("Müşteri seçilmedi")
    yeni_adres = alanlar.get("address_id", kiralama.address_id)
    musteri_degisti = yeni_musteri != kiralama.customer_id
    if musteri_degisti and sum(aktif_toplam.values()) > 0:
        raise KiralamaHatasi("Aktif tahsisi olan kiralamanın müşterisi değiştirilemez")
    if musteri_degisti or yeni_adres != kiralama.address_id:
        await _musteri_dogrula(db, user, yeni_musteri, yeni_adres)

    # Tarihler
    eski_bas, eski_bit = kiralama.baslangic, kiralama.bitis
    yeni_bas = alanlar.get("baslangic") or eski_bas
    yeni_bit = alanlar.get("bitis") or eski_bit
    _tarih_dogrula(yeni_bas, yeni_bit)
    tarih_degisti = (yeni_bas, yeni_bit) != (eski_bas, eski_bit)
    if yeni_bas != eski_bas and kiralama.status in SEVK_SONRASI:
        raise KiralamaHatasi("Sevk edilmiş kiralamanın başlangıç tarihi değiştirilemez")

    # Kalemler
    mevcut_kalemler = {k.id: k for k in await tahsis_svc.kalemler(db, kiralama.id)}
    istenen: dict[int, int] = {k.product_id: k.qty for k in mevcut_kalemler.values()}
    kalem_ozeti: dict[str, Any] | None = None
    if alanlar.get("kalemler") is not None:
        gelen: list[KalemGirdisi] = alanlar["kalemler"]
        if not gelen:
            raise girdi("En az bir kalem girilmeli")
        urunler: set[int] = set()
        istenen = {}
        for k in gelen:
            if k.id is not None and k.id not in mevcut_kalemler:
                raise girdi("Kalem bu kiralamaya ait değil")
            await _urun_kalemi_dogrula(db, kiralama.birim, k)
            if k.product_id in urunler:
                raise girdi("Aynı ürün iki kalemde olamaz; adedi artırın")
            urunler.add(k.product_id)
            istenen[k.product_id] = k.qty
            if k.id is not None:
                eski = mevcut_kalemler[k.id]
                tahsisli = aktif_toplam.get(eski.id, 0)
                if eski.product_id != k.product_id and tahsisli:
                    raise KiralamaHatasi("Tahsisli kalemin ürünü değiştirilemez")
                if k.qty < tahsisli:
                    raise KiralamaHatasi(
                        f"Kalem adedi aktif tahsisin ({tahsisli}) altına indirilemez"
                    )
        silinen = [k for kid, k in mevcut_kalemler.items() if kid not in {g.id for g in gelen}]
        for k in silinen:
            gecmis = await db.scalar(
                select(RentalAllocation.id).where(RentalAllocation.rental_item_id == k.id).limit(1)
            )
            if gecmis is not None:
                raise KiralamaHatasi("Tahsis geçmişi olan kalem silinemez")
        kalem_ozeti = {
            "eski": {str(k.product_id): k.qty for k in mevcut_kalemler.values()},
            "yeni": {str(p): q for p, q in istenen.items()},
        }

    # Rezervli kiralamada müsaitlik (artan adet ya da değişen tarih)
    if kiralama.status in REZERV_DURUMLARI:
        eski_istenen = {k.product_id: k.qty for k in mevcut_kalemler.values()}
        kontrol = (
            istenen
            if tarih_degisti
            else {p: q for p, q in istenen.items() if q > eski_istenen.get(p, 0)}
        )
        await tahsis_svc.yeterlilik_dogrula(
            db, kiralama, kontrol, baslangic=yeni_bas, bitis=yeni_bit
        )

    # İrtibatlar
    irtibat_ozeti: dict[str, Any] | None = None
    if alanlar.get("irtibatlar") is not None:
        gelen_irtibat: list[IrtibatGirdisi] = alanlar["irtibatlar"]
        await _irtibat_dogrula(db, yeni_musteri, gelen_irtibat)
        mevcut_irtibat = {
            r.id: r
            for r in (
                await db.scalars(
                    select(RentalContact).where(RentalContact.rental_id == kiralama.id)
                )
            ).all()
        }
        for i in gelen_irtibat:
            if i.id is not None and i.id not in mevcut_irtibat:
                raise girdi("İrtibat satırı bu kiralamaya ait değil")
        irtibat_ozeti = {
            "eski": sorted(r.contact_id for r in mevcut_irtibat.values()),
            "yeni": sorted(i.contact_id for i in gelen_irtibat),
        }
    elif musteri_degisti:
        # Eski müşterinin kişileri yeni müşteriye bağlı kalamaz.
        await db.execute(
            RentalContact.__table__.delete().where(RentalContact.rental_id == kiralama.id)
        )

    # --- Yazım (hepsi doğrulandıktan sonra) ---------------------------------------
    eski_sorumlu = kiralama.sorumlu_user_id
    for alan in ("lokasyon_metni", "proje_adi", "notes"):
        if alan in alanlar:
            setattr(kiralama, alan, _bos(alanlar[alan]))
    if "quote_id" in alanlar:
        await _teklif_dogrula(db, alanlar["quote_id"])
        kiralama.quote_id = alanlar["quote_id"]
    if "sorumlu_user_id" in alanlar:
        await _sorumlu_dogrula(db, alanlar["sorumlu_user_id"])
        kiralama.sorumlu_user_id = alanlar["sorumlu_user_id"]
    kiralama.customer_id = yeni_musteri
    kiralama.address_id = yeni_adres
    kiralama.baslangic = yeni_bas
    kiralama.bitis = yeni_bit
    kiralama.updated_by = user.id
    await audit.log_change(db, kiralama, "guncelle", user_id=user.id, ip=ip)

    if alanlar.get("kalemler") is not None:
        gelen = alanlar["kalemler"]
        gelen_idler = {g.id for g in gelen if g.id is not None}
        for kid, k in mevcut_kalemler.items():
            if kid not in gelen_idler:
                await db.delete(k)
        await db.flush()
        for g in gelen:
            if g.id is not None:
                k = mevcut_kalemler[g.id]
                k.product_id = g.product_id
                k.qty = g.qty
                k.note = _bos(g.note)
            else:
                db.add(
                    RentalItem(
                        rental_id=kiralama.id,
                        product_id=g.product_id,
                        qty=g.qty,
                        note=_bos(g.note),
                        created_by=user.id,
                    )
                )
        await db.flush()
        if kalem_ozeti and kalem_ozeti["eski"] != kalem_ozeti["yeni"]:
            await olay_yaz(
                db, kiralama, "KALEM", user=user, clock=clock, alan="kalemler", **kalem_ozeti
            )
    if alanlar.get("irtibatlar") is not None:
        gelen_irtibat = alanlar["irtibatlar"]
        mevcut_irtibat = {
            r.id: r
            for r in (
                await db.scalars(
                    select(RentalContact).where(RentalContact.rental_id == kiralama.id)
                )
            ).all()
        }
        gelen_idler = {i.id for i in gelen_irtibat if i.id is not None}
        for rid, r in mevcut_irtibat.items():
            if rid not in gelen_idler:
                await db.delete(r)
        await db.flush()
        for i in gelen_irtibat:
            if i.id is not None:
                r = mevcut_irtibat[i.id]
                r.contact_id = i.contact_id
                r.rol = i.rol
            else:
                db.add(
                    RentalContact(
                        rental_id=kiralama.id,
                        contact_id=i.contact_id,
                        rol=i.rol,
                        created_by=user.id,
                    )
                )
        await db.flush()
        if irtibat_ozeti and irtibat_ozeti["eski"] != irtibat_ozeti["yeni"]:
            await olay_yaz(db, kiralama, "IRTIBAT", user=user, clock=clock, alan="irtibatlar")
            await audit.log(
                db,
                ENTITY,
                "irtibat",
                entity_id=kiralama.id,
                old_value={"contact_ids": irtibat_ozeti["eski"]},
                new_value={"contact_ids": irtibat_ozeti["yeni"]},
                user_id=user.id,
                ip=ip,
                is_personal_data=True,
            )
    if tarih_degisti:
        if kiralama.status in REZERV_DURUMLARI:
            await tahsis_svc.tarihleri_uygula(
                db, kiralama, yeni_bas, yeni_bit, user=user, cakisma_onayi=cakisma_onayi
            )
        await olay_yaz(
            db,
            kiralama,
            "TARIH",
            user=user,
            clock=clock,
            alan="tarih",
            eski={"baslangic": str(eski_bas), "bitis": str(eski_bit)},
            yeni={"baslangic": str(yeni_bas), "bitis": str(yeni_bit)},
        )
    if kiralama.sorumlu_user_id != eski_sorumlu:
        await olay_yaz(
            db,
            kiralama,
            "SORUMLU",
            user=user,
            clock=clock,
            alan="sorumlu_user_id",
            eski={"user_id": eski_sorumlu},
            yeni={"user_id": kiralama.sorumlu_user_id},
        )
    await db.flush()
    return kiralama


# --- Aşamalar (TS-113) ----------------------------------------------------------------


async def planla(db: AsyncSession, kiralama: Rental, *, user: User, clock: Clock) -> Rental:
    """TALEP → PLANLANDI: ürün/adet rezervi tarih bazlı müsaitlikten geçer (409)."""
    gecis_dogrula(kiralama.status, "PLANLANDI")
    kalem_listesi = await tahsis_svc.kalemler(db, kiralama.id)
    if not kalem_listesi:
        raise girdi("Kalemi olmayan kiralama planlanamaz")
    istenen: dict[int, int] = {}
    for k in kalem_listesi:
        istenen[k.product_id] = istenen.get(k.product_id, 0) + k.qty
    await tahsis_svc.yeterlilik_dogrula(db, kiralama, istenen)
    onceki = durum_ata(kiralama, "PLANLANDI", user)
    await db.flush()
    await olay_yaz(
        db, kiralama, "DURUM", user=user, clock=clock, onceki_durum=onceki, yeni_durum="PLANLANDI"
    )
    return kiralama


async def _ekip(db: AsyncSession, so: ServiceOrder) -> list[int]:
    """İşin ekibi: aktif plan üyeleri, plan yoksa aktif atamalar (serbest metin yok)."""
    from app.services.teknik_servis import atama, planlama

    plan = await planlama.aktif_plan(db, so.id)
    if plan is not None:
        uyeler = (await planlama.plan_uyeleri(db, [plan.id])).get(plan.id, [])
        if uyeler:
            return sorted({u.user_id for u in uyeler})
    return sorted({a.user_id for a in await atama.aktif_ekip(db, so)})


async def _bagli_is(db: AsyncSession, kiralama: Rental, so_id: int) -> ServiceOrder:
    so = await db.get(ServiceOrder, so_id)
    if so is None or so.rental_id != kiralama.id or so.is_deleted:
        raise girdi("Seçilen servis işi bu kiralamaya bağlı değil")
    return so


async def asama_ilerlet(
    db: AsyncSession,
    kiralama: Rental,
    hedef: str,
    *,
    user: User,
    clock: Clock,
    at: datetime | None = None,
    service_order_id: int | None = None,
    note: str | None = None,
) -> RentalEvent:
    """Kurulum yapıldı / devreye alındı / toplandı. Ekip bağlı işin planından,
    süre zaman kaydından (`sure_ozeti`; kayıt yoksa EKSIK — 0 yazılmaz)."""
    if hedef not in ASAMA_HEDEFLERI:
        raise girdi(
            "Bu uçla yalnız Kurulum yapıldı, Devreye alındı ve Toplandı girilir "
            "(sevk, iade, iptal ve kapanışın kendi işlemleri var)"
        )
    an = asama_zamani(at, kiralama, clock)
    ekip: list[int] | None = None
    sure: dict[str, Any] | None = None
    if service_order_id is not None:
        so = await _bagli_is(db, kiralama, service_order_id)
        ekip = await _ekip(db, so)
        from app.services.teknik_servis import zaman

        ozet = await zaman.sure_ozeti(db, so.id)
        sure = {"kisi_saat_dk": ozet.kisi_saat_dk, "sure_durumu": ozet.sure_durumu}
    onceki = durum_ata(kiralama, hedef, user)
    await db.flush()
    return await olay_yaz(
        db,
        kiralama,
        "ASAMA",
        user=user,
        clock=clock,
        at=an,
        onceki_durum=onceki,
        yeni_durum=hedef,
        service_order_id=service_order_id,
        ekip_user_ids=ekip,
        yeni=sure,
        gerekce=note,
    )


async def iptal(
    db: AsyncSession,
    kiralama: Rental,
    gerekce: str | None,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> Rental:
    """İptal (E06-14): gerekçe zorunlu (400); sevk edilmiş tahsis varsa 409.

    Tahsisler çözülür (cihazlar başka kiralamaya tahsis edilebilir); bağlı
    açık kurulum/toplama işleri `kaynak='kiralama'` ile iptal edilir — iş
    sahadaysa (iptal edilemiyorsa) kiralama da iptal edilemez (409).
    """
    gerekce = _bos(gerekce)
    if gerekce is None:
        raise girdi("İptal gerekçesi zorunlu")
    gecis_dogrula(kiralama.status, "IPTAL")
    tahsis_listesi = await tahsis_svc.tahsisler(db, kiralama.id, kilit=True)
    if any(t.sevk_adet > 0 for t in tahsis_listesi):
        raise KiralamaHatasi("Sevk edilmiş kiralama iptal edilemez; önce iade alın")
    from app.services.teknik_servis import is_emirleri

    acik_isler = (
        await db.scalars(
            select(ServiceOrder).where(
                ServiceOrder.rental_id == kiralama.id,
                ServiceOrder.is_deleted.is_(False),
                ServiceOrder.status.not_in(("TAMAMLANDI", "KAPATILDI", "IPTAL")),
            )
        )
    ).all()
    for so in acik_isler:
        if not SERVIS_IS_EMRI.izinli_mi(so.status, "IPTAL"):
            raise KiralamaHatasi(
                f"Bağlı servis işi {so.so_no} iptal edilebilecek durumda değil; "
                "önce o işi sonuçlandırın"
            )
    await tahsis_svc.tahsisleri_coz(db, kiralama, user=user, clock=clock, note="Kiralama iptali")
    for so in acik_isler:
        await is_emirleri.durum_degistir(
            db,
            so,
            "IPTAL",
            kaynak="kiralama",
            user=user,
            clock=clock,
            gerekce=f"Kiralama {kiralama.rental_no} iptal edildi: {gerekce}"[:500],
        )
    onceki = durum_ata(kiralama, "IPTAL", user)
    kiralama.iptal_gerekcesi = gerekce[:500]
    await db.flush()
    await olay_yaz(
        db,
        kiralama,
        "IPTAL",
        user=user,
        clock=clock,
        onceki_durum=onceki,
        yeni_durum="IPTAL",
        gerekce=gerekce,
    )
    await audit.log(
        db,
        ENTITY,
        "kiralama.iptal",
        entity_id=kiralama.id,
        old_value={"status": onceki},
        new_value={"status": "IPTAL", "gerekce": gerekce},
        user_id=user.id,
        ip=ip,
    )
    return kiralama


async def kapat(
    db: AsyncSession, kiralama: Rental, *, user: User, clock: Clock, ip: str | None = None
) -> Rental:
    """DEPOYA_ALINDI → KAPANDI. Müşteride cihaz varsa 409; sevk edilmemiş kalan
    tahsisler otomatik çözülür (olay kaydıyla)."""
    tahsis_listesi = await tahsis_svc.tahsisler(db, kiralama.id, kilit=True)
    disarida = sum(tahsis_svc.disarida(t) for t in tahsis_listesi if t.durum == "AKTIF")
    if disarida > 0:
        raise KiralamaHatasi(f"Müşteride {disarida} adet cihaz var; kiralama kapatılamaz")
    gecis_dogrula(kiralama.status, "KAPANDI")
    hareketler = await tahsis_svc.tahsisleri_coz(
        db, kiralama, user=user, clock=clock, note="Kapanışta sevk edilmeyen kalan çözüldü"
    )
    onceki = durum_ata(kiralama, "KAPANDI", user)
    kiralama.kapanis_at = clock.now()
    await db.flush()
    await olay_yaz(
        db,
        kiralama,
        "DURUM",
        user=user,
        clock=clock,
        onceki_durum=onceki,
        yeni_durum="KAPANDI",
        yeni={"hareketler": hareketler} if hareketler else None,
    )
    await audit.log(
        db,
        ENTITY,
        "kiralama.kapat",
        entity_id=kiralama.id,
        new_value={"status": "KAPANDI"},
        user_id=user.id,
        ip=ip,
    )
    return kiralama


async def _geri_alinmis_idler(db: AsyncSession, kiralama_id: int) -> set[int]:
    return set(
        (
            await db.scalars(
                select(RentalEvent.geri_alinan_event_id).where(
                    RentalEvent.rental_id == kiralama_id,
                    RentalEvent.geri_alinan_event_id.is_not(None),
                )
            )
        ).all()
    )


async def son_geri_alinabilir_olay(db: AsyncSession, kiralama_id: int) -> RentalEvent | None:
    geri_alinmis = await _geri_alinmis_idler(db, kiralama_id)
    olaylar = (
        await db.scalars(
            select(RentalEvent)
            .where(
                RentalEvent.rental_id == kiralama_id,
                RentalEvent.tur.in_(GERI_ALINABILIR_OLAYLAR),
            )
            .order_by(RentalEvent.id.desc())
        )
    ).all()
    for o in olaylar:
        if o.id not in geri_alinmis:
            return o
    return None


async def asama_geri_al(
    db: AsyncSession,
    kiralama: Rental,
    gerekce: str | None,
    *,
    user: User,
    clock: Clock,
    olay_id: int | None = None,
    ip: str | None = None,
) -> RentalEvent:
    """Son aşamayı gerekçeyle geri alır (E06-08) — bkz. modül docstring'i.

    Ters hareketler yazılır (hiçbir kayıt silinmez), tahsis sayaçları geri
    sarılır, durum olayın önceki durumuna döner. Cihaz o arada başka harekete
    konu olduysa 409 ("önce sonraki işlemi geri alın").
    """
    gerekce = _bos(gerekce)
    if gerekce is None:
        raise girdi("Geri alma gerekçesi zorunlu")
    if kiralama.status in KAPALI_DURUMLAR:
        raise KiralamaHatasi(f"'{DURUM_ADLARI[kiralama.status]}' kiralamada geri alma yapılamaz")
    hedef = await son_geri_alinabilir_olay(db, kiralama.id)
    if olay_id is not None:
        if olay_id in await _geri_alinmis_idler(db, kiralama.id):
            raise KiralamaHatasi("Bu işlem zaten geri alınmış")
        if hedef is None or hedef.id != olay_id:
            raise KiralamaHatasi("Yalnız son aşama işlemi geri alınabilir")
    if hedef is None:
        raise KiralamaHatasi("Geri alınacak aşama işlemi yok")
    if hedef.onceki_durum != hedef.yeni_durum:
        if kiralama.status != hedef.yeni_durum:
            raise KiralamaHatasi("Kiralama bu işlemden sonra başka bir aşamaya geçmiş")
        # İleri geçiş makinede gerçekten var mı (ters kenar eklenmez).
        KIRALAMA.dogrula(hedef.onceki_durum, hedef.yeni_durum)
    veri = hedef.yeni or {}
    from app.models import RentalInventoryMovement

    hareket_idler = sorted(veri.get("hareketler") or [], reverse=True)
    for hid in hareket_idler:
        hareket = await db.get(RentalInventoryMovement, hid)
        if hareket is None:
            raise KiralamaHatasi("Olayın hareket kaydı bulunamadı")
        await ters_hareket_yaz(
            db, hareket, user=user, clock=clock, note=f"Geri alma: {gerekce}"[:300]
        )
    tahsis_haritasi = {t.id: t for t in await tahsis_svc.tahsisler(db, kiralama.id, kilit=True)}
    for s in veri.get("sayaclar") or []:
        t = tahsis_haritasi.get(s["tahsis_id"])
        if t is None:
            continue
        t.sevk_adet -= int(s.get("sevk", 0))
        t.iade_adet -= int(s.get("iade", 0))
        t.kayip_adet -= int(s.get("kayip", 0))
        if s.get("shipped_at_bostu"):
            t.shipped_at = None
        t.updated_by = user.id
    for tid in veri.get("kapanan_tahsisler") or []:
        t = tahsis_haritasi.get(tid)
        if t is not None:
            t.durum = "AKTIF"
            t.closed_at = None
    onceki = kiralama.status
    if hedef.onceki_durum is not None and hedef.onceki_durum != hedef.yeni_durum:
        # Belgeli tek doğrudan atama (modül docstring'i, E06 kontrol §2.2/16).
        kiralama.status = hedef.onceki_durum
        kiralama.updated_by = user.id
    await db.flush()
    olay = await olay_yaz(
        db,
        kiralama,
        "DUZELTME",
        user=user,
        clock=clock,
        onceki_durum=onceki,
        yeni_durum=kiralama.status,
        gerekce=gerekce,
        geri_alinan_event_id=hedef.id,
        yeni={"geri_alinan_tur": hedef.tur},
    )
    await audit.log(
        db,
        ENTITY,
        "kiralama.asama.geri_al",
        entity_id=kiralama.id,
        old_value={"status": onceki, "olay_id": hedef.id},
        new_value={"status": kiralama.status, "gerekce": gerekce},
        user_id=user.id,
        ip=ip,
    )
    return olay


# --- Servis işi bağı (TS-120) ----------------------------------------------------------


TUR_ADLARI = {"KURULUM": "Kurulum", "TOPLAMA": "Toplama"}


async def servis_isi_ac(
    db: AsyncSession,
    kiralama: Rental,
    tur: str,
    *,
    user: User,
    clock: Clock,
    ip: str | None = None,
) -> ServiceOrder:
    """Kurulum/toplama işini servis işi çekirdeğiyle açar ve kiralamaya bağlar.

    Taşınan: birim, müşteri, lokasyon; açıklamada kiralama no ve tahsisli
    seri listesi. Aynı türde ikinci açık iş 409 (`uq_so_kiralama_tur_acik`).
    """
    from app.services.teknik_servis import is_emirleri
    from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

    if tur not in KIRALAMA_SERVIS_TURLERI:
        raise girdi("Kiralamaya yalnız Kurulum ya da Toplama işi bağlanır")
    if kiralama.status in KAPALI_DURUMLAR:
        raise KiralamaHatasi(f"'{DURUM_ADLARI[kiralama.status]}' kiralamaya iş açılamaz")
    acik = await db.scalar(
        select(ServiceOrder).where(
            ServiceOrder.rental_id == kiralama.id,
            ServiceOrder.tur == tur,
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.status.not_in(("KAPATILDI", "IPTAL")),
        )
    )
    if acik is not None:
        raise KiralamaHatasi(f"Bu kiralama için açık bir {TUR_ADLARI[tur]} işi var: {acik.so_no}")
    tahsis_listesi = await tahsis_svc.tahsisler(db, kiralama.id)
    seriler = list(
        (
            await tahsis_svc.ozet_seriler(db, [t for t in tahsis_listesi if t.durum != "COZULDU"])
        ).values()
    )
    aciklama = f"Kiralama {kiralama.rental_no} — {TUR_ADLARI[tur]}"
    if kiralama.proje_adi:
        aciklama += f"\nProje: {kiralama.proje_adi}"
    if kiralama.lokasyon_metni:
        aciklama += f"\nYer: {kiralama.lokasyon_metni}"
    if seriler:
        aciklama += "\nSeriler: " + ", ".join(seriler)
    girdi_ = is_emirleri.ServisIsiGirdisi(
        birim=kiralama.birim,
        tur=tur,
        konu=f"Kiralama {kiralama.rental_no} — {TUR_ADLARI[tur]}",
        customer_id=kiralama.customer_id,
        address_id=kiralama.address_id,
        aciklama=aciklama[:4000],
        seriler=seriler[: is_emirleri.SERI_UST_SINIR],
        proje=kiralama.proje_adi,
    )
    try:
        so = await is_emirleri.olustur(
            db, girdi_, user=user, clock=clock, baslangic_durumu="PLANLAMADA"
        )
    except ServisGirdiHatasi as exc:
        raise girdi(str(exc)) from exc
    except ServisHatasi as exc:
        raise KiralamaHatasi(str(exc)) from exc
    so.rental_id = kiralama.id
    await db.flush()
    await olay_yaz(
        db,
        kiralama,
        "NOT",
        user=user,
        clock=clock,
        alan="servis_isi",
        service_order_id=so.id,
        yeni={"tur": tur, "so_no": so.so_no},
    )
    await audit.log(
        db,
        ENTITY,
        "kiralama.servis_isi",
        entity_id=kiralama.id,
        new_value={"service_order_id": so.id, "tur": tur},
        user_id=user.id,
        ip=ip,
    )
    return so


async def bagli_isler(db: AsyncSession, kiralama_id: int) -> list[ServiceOrder]:
    return list(
        (
            await db.scalars(
                select(ServiceOrder)
                .where(ServiceOrder.rental_id == kiralama_id, ServiceOrder.is_deleted.is_(False))
                .order_by(ServiceOrder.id)
            )
        ).all()
    )


def onerilen_asama(kiralama: Rental, isler: list[ServiceOrder]) -> str | None:
    """Tamamlanan kurulum/toplama işine göre önerilen aşama (yazılmaz, önerilir)."""
    biten = {so.tur for so in isler if so.status in ("TAMAMLANDI", "KAPATILDI")}
    if "TOPLAMA" in biten and kiralama.status in (
        "SEVK_EDILDI",
        "KURULUM_YAPILDI",
        "DEVREYE_ALINDI",
    ):
        return "TOPLANDI"
    if "KURULUM" in biten and kiralama.status == "SEVK_EDILDI":
        return "KURULUM_YAPILDI"
    return None


async def asama_oner(
    db: AsyncSession, so: Any, onceki: str, hedef: str, kaynak: str, clock: Clock
) -> None:
    """`durum_degisti` kancası: kurulum/toplama işi TAMAMLANDI → aşama önerisi.

    Yalnız kiralama geçmişine öneri NOTU yazar; aşamayı `kiralama.asama`
    sahibi onaylar (otomatik ilerleme yok).
    """
    rental_id = getattr(so, "rental_id", None)
    if rental_id is None or hedef != "TAMAMLANDI" or so.tur not in KIRALAMA_SERVIS_TURLERI:
        return
    kiralama = await db.get(Rental, rental_id)
    if kiralama is None or kiralama.status in KAPALI_DURUMLAR:
        return
    oneri = onerilen_asama(kiralama, await bagli_isler(db, rental_id))
    await olay_yaz(
        db,
        kiralama,
        "NOT",
        user=None,
        clock=clock,
        alan="asama_onerisi",
        service_order_id=so.id,
        yeni={"oneri": oneri, "so_no": so.so_no, "tur": so.tur},
    )


# --- Liste, KPI (TS-122) -----------------------------------------------------------------


KPI_TANIMLARI: tuple[tuple[str, str, str], ...] = (
    ("talep", "Talep", "Talep aşamasındaki kiralamalar (rezerv yok)"),
    ("planli", "Planlı", "Planlanmış, tahsisi başlamamış kiralamalar"),
    ("hazirlaniyor", "Hazırlanıyor", "Tahsisi süren kiralamalar"),
    ("kirada", "Kirada", "Sevk edilmiş, depoya dönmemiş kiralamalar"),
    ("geciken", "Geciken iade", "İade günü geçmiş ve cihazı müşteride olan kiralamalar"),
    (
        "eksik_tahsis",
        "Eksik tahsis",
        f"{EKSIK_TAHSIS_GUN} gün içinde başlayacak ve tahsisi tamamlanmamış kiralamalar",
    ),
)


@dataclass
class KiralamaSuzgeci:
    q: str | None = None
    durum: str | None = None
    birim: str | None = None
    musteri_id: int | None = None
    kpi: str | None = None
    idler: list[int] | None = None


def _disarida_var():
    a = RentalAllocation
    return exists().where(
        a.rental_id == Rental.id,
        a.durum == "AKTIF",
        a.sevk_adet - a.iade_adet - a.kayip_adet > 0,
    )


def _eksik_tahsis_kosulu():
    kalem_toplam = (
        select(func.coalesce(func.sum(RentalItem.qty), 0))
        .where(RentalItem.rental_id == Rental.id)
        .correlate(Rental)
        .scalar_subquery()
    )
    tahsis_toplam = (
        select(func.coalesce(func.sum(RentalAllocation.qty), 0))
        .where(RentalAllocation.rental_id == Rental.id, RentalAllocation.durum == "AKTIF")
        .correlate(Rental)
        .scalar_subquery()
    )
    return kalem_toplam > tahsis_toplam


def kpi_kosulu(kod: str, bugun: date):
    if kod == "talep":
        return Rental.status == "TALEP"
    if kod == "planli":
        return Rental.status == "PLANLANDI"
    if kod == "hazirlaniyor":
        return Rental.status == "HAZIRLANIYOR"
    if kod == "kirada":
        return Rental.status.in_(SEVK_SONRASI)
    if kod == "geciken":
        return Rental.status.in_(SEVK_SONRASI) & (Rental.bitis < bugun) & _disarida_var()
    if kod == "eksik_tahsis":
        return (
            Rental.status.in_(("PLANLANDI", "HAZIRLANIYOR"))
            & (Rental.baslangic <= bugun + timedelta(days=EKSIK_TAHSIS_GUN))
            & _eksik_tahsis_kosulu()
        )
    raise girdi(f"Bilinmeyen KPI: {kod}")


def liste_sorgusu(user: User, s: KiralamaSuzgeci, *, bugun: date) -> Select:
    """Liste, KPI sayısı, Excel ve uyarı AYNI sorgudan (sayı = liste)."""
    stmt = (
        select(Rental, Account.title)
        .join(Account, Account.id == Rental.customer_id)
        .where(Rental.is_deleted.is_(False))
    )
    if s.durum:
        if s.durum not in KIRALAMA_DURUMLARI:
            raise girdi(f"Bilinmeyen durum: {s.durum}")
        stmt = stmt.where(Rental.status == s.durum)
    if s.birim:
        stmt = stmt.where(Rental.birim == s.birim)
    if s.musteri_id:
        stmt = stmt.where(Rental.customer_id == s.musteri_id)
    if s.idler:
        stmt = stmt.where(Rental.id.in_(s.idler))
    if s.q and s.q.strip():
        q = f"%{s.q.strip()}%"
        stmt = stmt.where(
            or_(Rental.rental_no.ilike(q), Account.title.ilike(q), Rental.proje_adi.ilike(q))
        )
    if s.kpi:
        stmt = stmt.where(kpi_kosulu(s.kpi, bugun))
    return kiralama_kosulu(stmt, user).order_by(Rental.id.desc())


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def ozet(db: AsyncSession, user: User, clock: Clock) -> list[dict[str, Any]]:
    bugun = yerel_bugun(clock)
    return [
        {
            "kod": kod,
            "baslik": baslik,
            "tanim": tanim,
            "deger": await say(db, liste_sorgusu(user, KiralamaSuzgeci(kpi=kod), bugun=bugun)),
        }
        for kod, baslik, tanim in KPI_TANIMLARI
    ]


async def satir_ekleri(db: AsyncSession, idler: list[int]) -> dict[int, dict[str, Any]]:
    """Liste satırı için kalem özeti, tahsis/sevk/iade toplamları (toplu sorgu)."""
    if not idler:
        return {}
    ekler: dict[int, dict[str, Any]] = {
        i: {"kalem_ozeti": [], "kalem_adet": 0, "tahsis_adet": 0, "sevk": 0, "donen": 0}
        for i in idler
    }
    kalem_satirlari = (
        await db.execute(
            select(RentalItem.rental_id, Product.code, RentalItem.qty)
            .join(Product, Product.id == RentalItem.product_id)
            .where(RentalItem.rental_id.in_(idler))
            .order_by(RentalItem.id)
        )
    ).all()
    for rid, kod, qty in kalem_satirlari:
        ekler[rid]["kalem_ozeti"].append(f"{kod} ×{qty}")
        ekler[rid]["kalem_adet"] += qty
    tahsis_satirlari = (
        await db.execute(
            select(
                RentalAllocation.rental_id,
                RentalAllocation.durum,
                func.sum(RentalAllocation.qty),
                func.sum(RentalAllocation.sevk_adet),
                func.sum(RentalAllocation.iade_adet + RentalAllocation.kayip_adet),
            )
            .where(RentalAllocation.rental_id.in_(idler), RentalAllocation.durum != "COZULDU")
            .group_by(RentalAllocation.rental_id, RentalAllocation.durum)
        )
    ).all()
    for rid, durum, qty, sevk, donen in tahsis_satirlari:
        if durum == "AKTIF":
            ekler[rid]["tahsis_adet"] += int(qty or 0)
        ekler[rid]["sevk"] += int(sevk or 0)
        ekler[rid]["donen"] += int(donen or 0)
    for e in ekler.values():
        if e["sevk"] == 0 or e["donen"] == 0:
            e["iade_gosterimi"] = "YOK"
        else:
            e["iade_gosterimi"] = "TAM" if e["donen"] >= e["sevk"] else "KISMI"
    return ekler


# --- Tutanak (TS-117) ---------------------------------------------------------------------


TUTANAK_TURLERI = ("TESLIM", "IADE")


async def tutanak_baglami(
    db: AsyncSession, kiralama: Rental, *, tur: str, clock: Clock | None = None
) -> dict[str, Any]:
    """Teslim/iade tutanağı PDF bağlamı — FİYATSIZ (K13).

    Yalnız tahsisli seriler/adetler listelenir. Sevk yapılmadan alınan teslim
    tutanağına TASLAK filigranı basılır. Bağlamda fiyat, tutar ya da maliyet
    anahtarı YOKTUR (test).
    """
    from app.services import belgeler

    if tur not in TUTANAK_TURLERI:
        raise girdi("Tutanak türü TESLIM ya da IADE olmalı")
    hesap = await db.get(Account, kiralama.customer_id)
    adres = await db.get(Address, kiralama.address_id) if kiralama.address_id else None
    irtibatlar = (
        await db.execute(
            select(Contact.full_name, Contact.phone, RentalContact.rol)
            .join(RentalContact, RentalContact.contact_id == Contact.id)
            .where(RentalContact.rental_id == kiralama.id)
            .order_by(RentalContact.id)
        )
    ).all()
    kalem_listesi = await tahsis_svc.kalemler(db, kiralama.id)
    tahsis_listesi = [
        t for t in await tahsis_svc.tahsisler(db, kiralama.id) if t.durum != "COZULDU"
    ]
    seriler = await tahsis_svc.ozet_seriler(db, tahsis_listesi)
    urunler = {
        u.id: u
        for u in (
            await db.scalars(
                select(Product).where(Product.id.in_([k.product_id for k in kalem_listesi] or [0]))
            )
        ).all()
    }
    kalemler_ = []
    for k in kalem_listesi:
        urun = urunler.get(k.product_id)
        ilgili = [t for t in tahsis_listesi if t.rental_item_id == k.id]
        kalemler_.append(
            {
                "urun_kodu": urun.code if urun else "",
                "urun_adi": urun.name if urun else "",
                "istenen": k.qty,
                "tahsisli": sum(t.qty for t in ilgili),
                "sevk": sum(t.sevk_adet for t in ilgili),
                "iade": sum(t.iade_adet for t in ilgili),
                "kayip": sum(t.kayip_adet for t in ilgili),
                "satirlar": [
                    {
                        "seri": seriler.get(t.id),
                        "adet": t.qty,
                        "sevk": t.sevk_adet,
                        "iade": t.iade_adet,
                        "kayip": t.kayip_adet,
                        "musteride": tahsis_svc.disarida(t),
                    }
                    for t in ilgili
                ],
            }
        )
    iade_notlari = []
    if tur == "IADE":
        olaylar = (
            await db.scalars(
                select(RentalEvent)
                .where(RentalEvent.rental_id == kiralama.id, RentalEvent.tur == "IADE")
                .order_by(RentalEvent.id)
            )
        ).all()
        for o in olaylar:
            for n in (o.yeni or {}).get("musteride") or []:
                iade_notlari.append(n.get("not") or "Müşteride kaldı")
    toplam_sevk = sum(t.sevk_adet for t in tahsis_listesi)
    sehir = adres.city if adres else None
    return {
        "firma": belgeler.firma_bilgisi(await belgeler.ayar_haritasi(db)),
        "baslik": "TESLİM TUTANAĞI" if tur == "TESLIM" else "İADE TUTANAĞI",
        "tur": tur,
        "taslak": tur == "TESLIM" and toplam_sevk == 0,
        "rental_no": kiralama.rental_no,
        "birim": BIRIMLER.get(kiralama.birim, kiralama.birim),
        "durum": DURUM_ADLARI[kiralama.status],
        "musteri": hesap.title if hesap else "",
        "lokasyon": " · ".join(
            filter(
                None,
                [
                    (adres.site_name or adres.label) if adres else None,
                    adres.line if adres else None,
                    sehir,
                    kiralama.lokasyon_metni,
                ],
            )
        ),
        "proje_adi": kiralama.proje_adi,
        "baslangic": kiralama.baslangic.strftime("%d.%m.%Y"),
        "bitis": kiralama.bitis.strftime("%d.%m.%Y"),
        "irtibatlar": [
            {"ad": ad, "telefon": tel, "rol": IRTIBAT_ROL_ADLARI.get(rol, rol)}
            for ad, tel, rol in irtibatlar
        ],
        "kalemler": kalemler_,
        "iade_notlari": iade_notlari,
        "belge_tarihi": yerel_bugun(clock).strftime("%d.%m.%Y") if clock else None,
    }


async def tutanak_pdf(db: AsyncSession, kiralama: Rental, *, tur: str, clock: Clock) -> bytes:
    from app.services.pdf import pdf_uret_async

    return await pdf_uret_async(
        "kiralama_tutanak.html", **await tutanak_baglami(db, kiralama, tur=tur, clock=clock)
    )


# --- Ek kapsamı (plan §1.11) ---------------------------------------------------------------


async def _kiralama_ek_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    """`rentals` ekleri: kiralama kapsamı (birim + müşteri). Kayıt yoksa True
    (varlık kontrolü API'nin)."""
    var = await db.scalar(select(Rental.id).where(Rental.id == entity_id))
    if var is None:
        return True
    stmt = kiralama_kosulu(
        select(Rental.id).where(Rental.id == entity_id, Rental.is_deleted.is_(False)), user
    )
    return await db.scalar(stmt) is not None


async def _kiralik_ek_kapsami(db: AsyncSession, user: User, entity_id: int, yazma: bool) -> bool:
    """`rental_assets` ekleri: cihazın birimi kullanıcının kapsamında mı."""
    from app.models import RentalAsset

    var = await db.scalar(select(RentalAsset.id).where(RentalAsset.id == entity_id))
    if var is None:
        return True
    stmt = kiralik_kosulu(
        select(RentalAsset.id).where(
            RentalAsset.id == entity_id, RentalAsset.is_deleted.is_(False)
        ),
        user,
    )
    return await db.scalar(stmt) is not None


kancalar.kaydet("durum_degisti", asama_oner)
ek_kapsam.kaydet("rentals", _kiralama_ek_kapsami)
ek_kapsam.kaydet("rental_assets", _kiralik_ek_kapsami)
