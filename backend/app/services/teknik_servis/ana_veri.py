"""Müşteri / lokasyon / irtibat ana verisinin teknik servis yüzü (TS-014, TS-015).

**Ayrı müşteri tablosu YOK** (plan §1.5): müşteri = `accounts(is_musteri)`,
gidilen yer = `addresses(kind='TESIS')`, irtibat = `contacts` (+ `address_id`).
Bu modül o üç canlı tablonun üzerine servisin ihtiyaç duyduğu kuralları
TEK YERDE toplar; servis işi, ekipman, sözleşme, kiralama ve atölye kendi
doğrulayıcısını yazmaz, buradakini çağırır:

- `lokasyon_dogrula` — "adres ve irtibat aynı hesaba ait, hesap müşteri ve
  silinmemiş/aktif" değişmezi. Eskiden her modül bunu ayrı yazacaktı; birinin
  unutması, yabancı bir hesabın tesisine servis işi bağlamak demekti.
- `lokasyon_anahtari` — havuz, toplu plan, ziyaret ve rapor boyutunun tek
  gruplama anahtarı. E02 `tr_normkey`, E12 `unvan_anahtari`, E09 başka bir
  bileşim kullanıyordu; aynı iş üç ekranda üç ayrı gruba düşüyordu (E14 B11).
- `saha_onerisi_kaynak` — plan formunun ön dolumu YALNIZ tesis satırından
  gelir; carinin unvanı adres diye, kütükteki ham irtibat adı irtibat diye
  önerilmez (E14-16, K3).

Hızlı ekleme (`hizli_musteri`) servis personelinin müşteri bulamadığı için
işi açamaması sorununu çözer, ama kaydı DAİMA `is_verified=False` açar:
VKN/IBAN gibi mali alanlara servis rolü dokunmaz (KD-07); doğrulamayı
`hesap.birlestir` sahibi yapar.

Servis fonksiyonları yalnız `flush` yapar; commit ve denetim izi API'dedir
(denetimin eylem adı ve IP'si uçta bilinir).
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, AccountAlias, Address, Contact, User
from app.models.account import TAKMA_AD_KAYNAKLARI
from app.services import accounts as hesap_svc
from app.services import normalize
from app.services.normalize import tr_normkey

# Hızlı eklemede "bunu mu demek istediniz?" eşiği (pg_trgm benzerliği).
# Plan §1.9 ayar listesine girmedi; ayar yapılırsa yalnız bu sabit okunur.
BENZERLIK_ESIGI = 0.6

# Hafif arama uçlarının dönebileceği en çok satır. Arama kutusu bir seçicidir,
# liste ekranı değil: 20'den fazlası kullanıcıya daha uzun yazmasını söyler.
HAFIF_ARAMA_UST_SINIR = 20

# Mobilite hesabı rolleri. Servis tarafındaki müşteri düzenleme ucu bu
# rollerden birini taşıyan hesaba dokunmaz: montaj noktasının unvanı/telefonu
# hak ediş dökümünün künyesidir (E14-D01).
MOBILITE_ROLLERI = ("is_bayi", "is_montaj_noktasi", "is_tedarikci")


class AnaVeriHatasi(ValueError):
    """Ana veri kuralı ihlali.

    `kod` uçta HTTP durumuna çevrilir (400 girdi hatası, 409 kural/çakışma);
    `veri` 409 gövdesine konur (aday listesi, mevcut kayıt).
    """

    def __init__(self, mesaj: str, *, kod: int = 400, veri: dict[str, Any] | None = None):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.kod = kod
        self.veri = veri or {}


# --- Normalleştirme ------------------------------------------------------------


def unvan_anahtari(ham: str | None) -> str:
    """`normalize.unvan_anahtari` için boşa dayanıklı ince sarmalayıcı."""
    return normalize.unvan_anahtari(ham) if ham else ""


def il_dogrula(ham: str | None) -> str | None:
    """İl adını 81 il listesine göre tek yazıma çevirir; bilinmeyen il 400.

    "istanbul", "İSTANBUL" ve "Istanbul" aynı değeri üretmeli: hafif arama
    "ad + il" döndürüyor ve lokasyon anahtarı il bilgisini taşıyor; serbest
    metin il, aynı şehri üç gruba bölüyordu (E14-D02). Boş girdi `None`.
    """
    if ham is None or not str(ham).strip():
        return None
    try:
        il = normalize.il_normalize(ham)
    except ValueError:
        il = None
    if not il:
        raise AnaVeriHatasi(f"Bilinmeyen il: {ham}")
    return il


# --- Kapsam yardımcıları -------------------------------------------------------


async def kapsamli_hesap(db: AsyncSession, user: User, hesap_id: int) -> Account:
    """Hesabı kapsam filtresiyle getirir; silinmiş ya da kapsam dışıysa 404.

    `api/accounts._kapsamli_hesap` ile aynı kural: `db.get` kapsamı atlar ve
    kontrol yazmadan ÖNCE yapılmazsa kapsam dışı kayıt sessizce değişir.
    """
    stmt = select(Account).where(Account.id == hesap_id, Account.is_deleted.is_(False))
    hesap = await db.scalar(hesap_svc.kapsam_uygula(stmt, user))
    if hesap is None:
        raise AnaVeriHatasi("Hesap bulunamadı", kod=404)
    return hesap


async def kapsamli_lokasyon(db: AsyncSession, user: User, lokasyon_id: int) -> Address:
    """Lokasyonu hesabının kapsamıyla getirir; kapsam dışı ya da yoksa 404.

    Silinmiş hesabın adresi de bulunamaz sayılır: birleştirilen kaynak
    hesabın tesisleri hedefte yaşar, kaynakta değil.
    """
    adres = await db.get(Address, lokasyon_id)
    if adres is None:
        raise AnaVeriHatasi("Lokasyon bulunamadı", kod=404)
    await kapsamli_hesap(db, user, adres.account_id)
    return adres


# --- VKN ve ad tekrarı ---------------------------------------------------------


async def vkn_cakismasi(
    db: AsyncSession, tax_no: str | None, *, haric_id: int | None = None
) -> list[Account]:
    """Aynı VKN'yi taşıyan silinmemiş ve AKTİF hesaplar.

    VKN için tekil indeks bilerek AÇILMADI (E14 K6): canlıda aynı VKN'li şube
    ve bayi çiftleri var ve hepsi meşru. Kontrol bu yüzden servis katmanında,
    onay + gerekçe ile geçilebilir bir 409'dur.
    """
    if not tax_no:
        return []
    stmt = select(Account).where(
        Account.tax_no == tax_no,
        Account.is_deleted.is_(False),
        Account.is_active.is_(True),
    )
    if haric_id is not None:
        stmt = stmt.where(Account.id != haric_id)
    return list((await db.scalars(stmt.order_by(Account.id))).all())


def musteri_satiri(hesap: Account, eslesen: str) -> dict[str, Any]:
    """Hafif müşteri satırı: ad + il + doğrulama rozeti.

    **VKN, IBAN, telefon, e-posta ve irtibat YOK.** Bu satır `servis.gor` ile
    teknisyene de gider; `hesap.gor` olmayan rol mali kimliği görmez (KD-09).
    """
    return {
        "id": hesap.id,
        "unvan": hesap.title,
        "il": hesap.region,
        "dogrulandi": hesap.is_verified,
        "eslesen": eslesen,
    }


async def benzer_musteriler(
    db: AsyncSession, unvan: str, *, esik: float = BENZERLIK_ESIGI
) -> list[dict[str, Any]]:
    """Hızlı eklemeden önce "bunu mu demek istediniz?" adayları.

    Üç kaynak taranır:
    1. Hesap unvanı: `unvan_anahtari` tam eşleşmesi (A.Ş. / Anonim Şirketi
       farkı) veya `title_key` trigram benzerliği ≥ eşik.
    2. Takma adlar — birleştirilmiş (silinmiş) hesabın takma adı HEDEF
       hesabı gösterir; eski yazımla gelen kullanıcı yeni kopya açmasın.
    3. Aktif tesis adı: "Akyaka AVM" tesisi olan cariye "AKYAKA AVM" diye
       ikinci müşteri açılması, ad tekrarının en sık biçimi.
    """
    anahtar = unvan_anahtari(unvan)
    norm = tr_normkey(unvan)
    if not anahtar and not norm:
        return []

    adaylar: dict[int, dict[str, Any]] = {}

    def ekle(hesap: Account | None, eslesen: str) -> None:
        if hesap is None or hesap.is_deleted or hesap.id in adaylar:
            return
        adaylar[hesap.id] = musteri_satiri(hesap, eslesen)

    benzerlik = func.similarity(Account.title_key, norm)
    kosullar = [benzerlik >= esik]
    ilk = anahtar.split()[0] if anahtar else ""
    if len(ilk) >= 3:
        # Trigram, ek farkını ("anonim şirketi" ↔ "a.ş.") cezalandırır; ilk
        # anlamlı kelime ön elemedir, kesin karar aşağıda anahtarla verilir.
        kosullar.append(Account.title_key.contains(ilk))
    satirlar = (
        await db.execute(
            select(Account, benzerlik)
            .where(Account.is_deleted.is_(False), or_(*kosullar))
            .order_by(benzerlik.desc(), Account.id)
            .limit(200)
        )
    ).all()
    for hesap, puan in satirlar:
        if anahtar and unvan_anahtari(hesap.title) == anahtar:
            ekle(hesap, "unvan")
        elif float(puan or 0) >= esik:
            ekle(hesap, "unvan")

    if anahtar:
        takma_benzerlik = func.similarity(AccountAlias.alias_key, anahtar)
        for _takma, hesap in (
            await db.execute(
                select(AccountAlias, Account)
                .join(Account, Account.id == AccountAlias.account_id)
                .where(or_(AccountAlias.alias_key == anahtar, takma_benzerlik >= esik))
                .limit(50)
            )
        ).all():
            hedef = hesap
            if hesap.is_deleted and hesap.merged_into_id:
                hedef = await db.get(Account, hesap.merged_into_id)
            ekle(hedef, "takma_ad")

        for (hesap,) in (
            await db.execute(
                select(Account)
                .join(Address, Address.account_id == Account.id)
                .where(
                    Address.kind == "TESIS",
                    Address.is_active.is_(True),
                    Address.site_key == anahtar,
                    Account.is_deleted.is_(False),
                )
                .limit(20)
            )
        ).all():
            ekle(hesap, "tesis")

    return list(adaylar.values())


# --- Hafif arama ---------------------------------------------------------------


async def musteri_ara(
    db: AsyncSession, user: User, q: str, *, limit: int = HAFIF_ARAMA_UST_SINIR
) -> list[dict[str, Any]]:
    """Servis formundaki müşteri seçicisinin araması (`servis.gor`).

    Unvan, takma ad, tesis adı ve (en az 3 hane yazılmışsa) VKN başlangıcıyla
    eşleşir; yanıtta yalnız ad, il ve doğrulama rozeti vardır. VKN ile
    bulunan satırda bile VKN DEĞERİ dönmez — `eslesen='vkn'` yeterli.
    Satış temsilcisi kapsamı (`kapsam_uygula`) aynen uygulanır.
    """
    q = (q or "").strip()
    norm = tr_normkey(q)
    anahtar = unvan_anahtari(q)
    rakam = "".join(ch for ch in q if ch.isdigit())

    takma_alt = (
        select(AccountAlias.account_id).where(AccountAlias.alias_key.contains(anahtar))
        if anahtar
        else None
    )
    tesis_alt = (
        select(Address.account_id).where(
            Address.kind == "TESIS",
            Address.is_active.is_(True),
            Address.site_key.contains(anahtar),
        )
        if anahtar
        else None
    )
    kosullar = []
    if norm:
        kosullar.append(Account.title_key.contains(norm))
    if takma_alt is not None:
        kosullar.append(Account.id.in_(takma_alt))
    if tesis_alt is not None:
        kosullar.append(Account.id.in_(tesis_alt))
    if len(rakam) >= 3:
        kosullar.append(Account.tax_no.startswith(rakam))
    if not kosullar:
        return []

    stmt: Select = (
        select(Account)
        .where(
            Account.is_deleted.is_(False),
            Account.is_active.is_(True),
            Account.is_musteri.is_(True),
            or_(*kosullar),
        )
        .order_by(Account.title, Account.id)
        .limit(limit)
    )
    hesaplar = list((await db.scalars(hesap_svc.kapsam_uygula(stmt, user))).all())
    if not hesaplar:
        return []

    idler = [h.id for h in hesaplar]
    takma_idleri: set[int] = set()
    tesis_idleri: set[int] = set()
    if takma_alt is not None:
        takma_idleri = set(
            (await db.scalars(takma_alt.where(AccountAlias.account_id.in_(idler)))).all()
        )
    if tesis_alt is not None:
        tesis_idleri = set((await db.scalars(tesis_alt.where(Address.account_id.in_(idler)))).all())

    sonuc = []
    for h in hesaplar:
        if norm and norm in h.title_key:
            eslesen = "unvan"
        elif h.id in takma_idleri:
            eslesen = "takma_ad"
        elif h.id in tesis_idleri:
            eslesen = "tesis"
        else:
            eslesen = "vkn"
        sonuc.append(musteri_satiri(h, eslesen))
    return sonuc


def lokasyon_satiri(adres: Address) -> dict[str, Any]:
    """Hafif lokasyon satırı (`lokasyon-ara`): tesis adı + ilçe + il."""
    return {
        "id": adres.id,
        "hesap_id": adres.account_id,
        "tesis_adi": adres.site_name or adres.label,
        "ilce": adres.district,
        "il": adres.city,
        "aktif": adres.is_active,
        "dogrulandi": adres.is_verified,
    }


async def lokasyon_ara(
    db: AsyncSession,
    hesap_id: int,
    q: str | None,
    *,
    pasif_dahil: bool = False,
    limit: int = HAFIF_ARAMA_UST_SINIR,
) -> list[dict[str, Any]]:
    """Bir carinin tesisleri (seçicinin ikinci adımı). Kapsamı çağıran uygular."""
    stmt = select(Address).where(Address.account_id == hesap_id, Address.kind == "TESIS")
    if not pasif_dahil:
        stmt = stmt.where(Address.is_active.is_(True))
    anahtar = unvan_anahtari(q) if q else ""
    if anahtar:
        stmt = stmt.where(Address.site_key.contains(anahtar))
    stmt = stmt.order_by(Address.site_name, Address.id).limit(limit)
    return [lokasyon_satiri(a) for a in (await db.scalars(stmt)).all()]


# --- Hızlı ekleme --------------------------------------------------------------


@dataclass
class HizliMusteriGirdisi:
    unvan: str
    il: str
    tesis_adi: str | None = None
    onay_benzer: bool = False


async def hizli_musteri(
    db: AsyncSession, girdi: HizliMusteriGirdisi, *, user: User, clock: Clock
) -> tuple[Account, Address | None]:
    """Servis ekranından yalnız ad + il (+ tesis adı) ile müşteri açar.

    - Hesap `is_musteri=True`, **`is_verified=False`** doğar; gövdede ne
      gelirse gelsin doğrulama bu yoldan açılmaz.
    - Benzer kayıt varsa ve `onay_benzer` verilmemişse 409 + aday listesi:
      kullanıcı "bunu mu demek istediniz?" sorusunu cevaplamadan kopya açılmaz.
    - Tesis adı verilirse aynı transaction'da `TESIS` satırı açılır; adres
      metni uydurulmaz (`line` NULL — onaylı istisna, plan §1.12).
    - Kapsamı temsilciye bağlı rol (KENDI_MUSTERILERI) açtığı hesabı kendine
      bağlar; aksi halde kaydettiği müşteriyi bir daha göremezdi.
    """
    # `clock` modül kalıbı için imzada: açılış anı DB'nin `created_at`'idir.
    unvan = girdi.unvan.strip()
    il = il_dogrula(girdi.il)
    if il is None:
        raise AnaVeriHatasi("İl zorunlu")
    tesis_adi = (girdi.tesis_adi or "").strip() or None

    if not girdi.onay_benzer:
        adaylar = await benzer_musteriler(db, unvan)
        if adaylar:
            gorunen = await _kapsamdakiler(db, user, adaylar)
            raise AnaVeriHatasi(
                "Benzer adlı kayıt var. Listeden seçin ya da yine de eklemek için onaylayın.",
                kod=409,
                veri={"adaylar": gorunen, "kapsam_disi": len(adaylar) - len(gorunen)},
            )

    hesap = Account(
        title=unvan,
        is_musteri=True,
        is_verified=False,
        region=il,
        created_by=user.id,
        sales_rep_id=user.id if _temsilci_mi(user) else None,
    )
    db.add(hesap)
    await db.flush()

    tesis: Address | None = None
    if tesis_adi:
        tesis = Address(
            account_id=hesap.id,
            kind="TESIS",
            label="Tesis",
            site_name=tesis_adi,
            city=il,
            is_verified=False,
            created_by=user.id,
        )
        db.add(tesis)
        await db.flush()
    return hesap, tesis


def _temsilci_mi(user: User) -> bool:
    from app.permissions import SCOPE_OWN_CUSTOMERS

    return user.role.scope == SCOPE_OWN_CUSTOMERS


async def _kapsamdakiler(
    db: AsyncSession, user: User, satirlar: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Aday listesinden kullanıcının kapsamında olanları bırakır.

    409 gövdesi de bir okuma yoludur: kapsam dışı hesabın unvanı burada
    görünseydi, hızlı ekleme portföy taraması için kullanılabilirdi.
    """
    if not _temsilci_mi(user):
        return satirlar
    return [s for s in satirlar if not await hesap_svc.kapsam_disinda_mi(db, user, s["id"])]


# --- Ortak doğrulayıcı ---------------------------------------------------------


async def lokasyon_dogrula(
    db: AsyncSession,
    account_id: int | None,
    address_id: int | None = None,
    contact_id: int | None = None,
) -> tuple[Account, Address | None, Contact | None]:
    """Servis kayıtlarının TEK müşteri-lokasyon-irtibat doğrulayıcısı.

    Servis işi, ekipman, bakım sözleşmesi, kiralama, atölye ve teklif köprüsü
    YENİ kayıt yazarken bunu çağırır; ihlal 400 (`AnaVeriHatasi(kod=400)`):

    - hesap yok, silinmiş, pasif ya da müşteri değil;
    - adres başka hesaba ait ya da pasif (pasiflenen lokasyona bağlı ESKİ
      kayıtlar açılmaya devam eder — bu fonksiyon yalnız yeni bağda çağrılır);
    - irtibat başka hesaba ait.

    Kapsam kontrolü (404) çağıranın işidir; bu fonksiyon veri tutarlılığını
    sınar, yetkiyi değil.
    """
    if account_id is None:
        raise AnaVeriHatasi("Müşteri seçilmedi")
    hesap = await db.get(Account, account_id)
    if hesap is None or hesap.is_deleted:
        raise AnaVeriHatasi("Müşteri bulunamadı")
    if not hesap.is_musteri:
        raise AnaVeriHatasi(f"'{hesap.title}' müşteri olarak işaretli değil")
    if not hesap.is_active:
        raise AnaVeriHatasi(f"'{hesap.title}' pasif; yeni kayıt açılamaz")

    adres: Address | None = None
    if address_id is not None:
        adres = await db.get(Address, address_id)
        if adres is None or adres.account_id != hesap.id:
            raise AnaVeriHatasi("Seçilen lokasyon bu müşteriye ait değil")
        if not adres.is_active:
            raise AnaVeriHatasi(
                f"'{adres.site_name or adres.label}' lokasyonu pasif; yeni kayıtta seçilemez"
            )

    kisi: Contact | None = None
    if contact_id is not None:
        kisi = await db.get(Contact, contact_id)
        if kisi is None or kisi.account_id != hesap.id:
            raise AnaVeriHatasi("Seçilen irtibat bu müşteriye ait değil")
    return hesap, adres, kisi


# --- Lokasyon anahtarı ---------------------------------------------------------


def _al(kayit: Any, *adlar: str) -> Any:
    """Nesne ya da sözlükten ilk dolu alanı okur (servis işi, plan, satır…)."""
    for ad in adlar:
        deger = kayit.get(ad) if isinstance(kayit, dict) else getattr(kayit, ad, None)
        if deger not in (None, ""):
            return deger
    return None


def lokasyon_anahtari(kayit: Any) -> tuple | None:
    """Havuz, toplu plan, ziyaret, rapor boyutu ve veri kalitesinin TEK
    gruplama anahtarı (plan §1.5; E14 B11).

    - `(birim, "L", address_id)` — lokasyonu bağlı kayıt;
    - `(birim, "M", musteri_id, unvan_anahtari(ham_lokasyon))` — müşterisi
      bilinen ama tesisi eşleşmemiş (göç) kayıt; "Akyaka  AVM" ile
      "AKYAKA AVM" aynı gruba düşer;
    - `(birim, "E", unvan_anahtari(ham_musteri + ham_lokasyon))` — müşterisi
      de eşleşmemiş kayıt;
    - `None` — ne adresi ne ham metni olan kayıt **gruplanmaz** (her biri
      kendi başınadır; boş anahtar altında yüzlerce işi birleştirmek havuzu
      anlamsızlaştırırdı).

    Birim ön eki bilinçli: aynı tesise giden güvenlik ve haberleşme ekipleri
    ayrı planlanır.
    """
    birim = _al(kayit, "birim")
    address_id = _al(kayit, "address_id")
    if address_id:
        return (birim, "L", address_id)

    ham_lokasyon = _al(kayit, "location_raw", "site_name_raw", "lokasyon_metni")
    musteri_id = _al(kayit, "customer_id", "account_id")
    if musteri_id:
        anahtar = unvan_anahtari(ham_lokasyon)
        return (birim, "M", musteri_id, anahtar) if anahtar else None

    ham_musteri = _al(kayit, "customer_name_raw", "firma_metni")
    anahtar = unvan_anahtari(" ".join(str(x) for x in (ham_musteri, ham_lokasyon) if x))
    return (birim, "E", anahtar) if anahtar else None


# --- Saha önerisi --------------------------------------------------------------


async def saha_onerisi_kaynak(db: AsyncSession, address_id: int | None) -> dict[str, Any] | None:
    """Plan/servis formunun saha ön dolumu — YALNIZ tesis satırından (E14-16).

    Döner: `adres` (= `line`, asla carinin unvanı değil), `ilce`, `il`,
    `erisim_notu` ve birincil irtibat (`addresses.primary_contact_id` →
    `contacts`). Lokasyon yoksa `None`, birincil irtibatı yoksa `irtibat: None`.
    Kütükteki `contact_name_raw` irtibat olarak ÖNERİLMEZ (K3): teyitsiz ham
    ad, sahada yanlış kişiyi aratırdı. Maskeleme (telefon) çağıranın işidir.
    """
    if address_id is None:
        return None
    adres = await db.get(Address, address_id)
    if adres is None:
        return None
    irtibat = None
    if adres.primary_contact_id:
        kisi = await db.get(Contact, adres.primary_contact_id)
        if kisi is not None and kisi.account_id == adres.account_id:
            irtibat = {"id": kisi.id, "ad": kisi.full_name, "telefon": kisi.phone}
    return {
        "lokasyon_id": adres.id,
        "tesis_adi": adres.site_name or adres.label,
        "adres": adres.line,
        "ilce": adres.district,
        "il": adres.city,
        "erisim_notu": adres.access_note,
        "irtibat": irtibat,
    }


# --- Tesis ve takma ad ---------------------------------------------------------


async def tesis_cakismasi(
    db: AsyncSession, account_id: int, site_name: str | None, *, haric_id: int | None = None
) -> Address | None:
    """Aynı carinin aynı anahtarlı AKTİF tesisi (varsa).

    `uq_addresses_tesis_aktif` yarışta da korur; bu ön kontrol 409 gövdesine
    mevcut kaydı koyabilmek içindir ("zaten var, şunu seçin").
    """
    anahtar = unvan_anahtari(site_name)
    if not anahtar:
        return None
    stmt = select(Address).where(
        Address.account_id == account_id,
        Address.kind == "TESIS",
        Address.is_active.is_(True),
        Address.site_key == anahtar,
    )
    if haric_id is not None:
        stmt = stmt.where(Address.id != haric_id)
    return await db.scalar(stmt.limit(1))


async def takma_ad_ekle(
    db: AsyncSession,
    *,
    account_id: int,
    alias_text: str,
    kaynak: str = "ELLE",
    address_id: int | None = None,
    kaynak_tablo: str | None = None,
    user_id: int | None = None,
) -> AccountAlias:
    """Takma ad ekler. `alias_key` GLOBAL tekildir: bir yazım tek hedefe gider.

    Aynı anahtar başka hedefteyse 409 + mevcut hedef döner (eşleştirme
    deterministik kalsın); aynı hedefteyse yine 409 (kopya satır anlamsız).
    """
    if kaynak not in TAKMA_AD_KAYNAKLARI:
        raise AnaVeriHatasi(f"Takma ad kaynağı {TAKMA_AD_KAYNAKLARI} içinden olmalı")
    metin = (alias_text or "").strip()
    anahtar = unvan_anahtari(metin)
    if not anahtar:
        raise AnaVeriHatasi("Takma ad boş olamaz")

    hesap = await db.get(Account, account_id)
    if hesap is None or hesap.is_deleted:
        raise AnaVeriHatasi("Hesap bulunamadı", kod=404)
    if address_id is not None:
        adres = await db.get(Address, address_id)
        if adres is None or adres.account_id != account_id:
            raise AnaVeriHatasi("Lokasyon bu hesaba ait değil")

    mevcut = await db.scalar(select(AccountAlias).where(AccountAlias.alias_key == anahtar))
    if mevcut is not None:
        hedef = await db.get(Account, mevcut.account_id)
        raise AnaVeriHatasi(
            "Bu yazım zaten bir kayda bağlı.",
            kod=409,
            veri={
                "mevcut": {
                    "takma_ad_id": mevcut.id,
                    "hesap_id": mevcut.account_id,
                    "hesap_unvan": hedef.title if hedef else None,
                    "lokasyon_id": mevcut.address_id,
                }
            },
        )

    takma = AccountAlias(
        account_id=account_id,
        address_id=address_id,
        alias_text=metin[:250],
        kaynak=kaynak,
        kaynak_tablo=kaynak_tablo,
        created_by=user_id,
    )
    db.add(takma)
    await db.flush()
    return takma


def takma_ad_satiri(takma: AccountAlias) -> dict[str, Any]:
    return {
        "id": takma.id,
        "hesap_id": takma.account_id,
        "lokasyon_id": takma.address_id,
        "metin": takma.alias_text,
        "anahtar": takma.alias_key,
        "kaynak": takma.kaynak,
        "kaynak_tablo": takma.kaynak_tablo,
        "created_at": takma.created_at,
    }


# --- Kapsam bilgisi ve anlık görüntü (TS-192, E14-17) ---------------------------


def donem_metni(bas: Any, bit: Any) -> str:
    """Sözleşme dönemi `01.01.2026–31.12.2026`; tarih eksikse "Dönem bilgisi yok"."""
    if bas is None or bit is None:
        return "Dönem bilgisi yok"
    from datetime import datetime

    from app.services.teknik_servis.yerel_zaman import yerel_gun

    def _t(deger: Any) -> str:
        gun = yerel_gun(deger) if isinstance(deger, datetime) else deger
        return gun.strftime("%d.%m.%Y")

    return f"{_t(bas)}–{_t(bit)}"


async def kapsam_bilgisi(
    db: AsyncSession,
    *,
    customer_id: int | None,
    address_id: int | None,
    equipment_id: int | None,
    clock: Clock,
    user: User | None = None,
) -> dict[str, Any]:
    """Servis işi açılışında sözleşme/garanti kapsam bilgisi (E14-17).

    **Tutar alanı YOK** (sözleşme ücreti dahil; `maliyet.gor` olsa bile).
    Durum kuralı: yalnız TARİHİ BİLİNEN ve şu anı kapsayan AKTİF sözleşme
    SOZLESMELI, yalnız kütükte bitişi bugünden ileri garanti GARANTILI
    yapar; teyit bekleyen ya da tarihsiz sözleşme BILINMIYOR'dur ("Sözleşmeli"
    denmez), hiçbiri yoksa KAPSAM_DISI. `user` verilirse sözleşmeler ve son
    işler kapsamından süzülür (uç); verilmezse (açılış damgası) süzülmez.
    """
    from app.models import (
        MaintenanceContract,
        MaintenanceContractItem,
        ServiceEquipment,
        ServiceOrder,
    )
    from app.services import settings as ayar_svc
    from app.services.teknik_servis import kapsam
    from app.services.teknik_servis.yerel_zaman import yerel_bugun

    an = clock.now()
    bugun = yerel_bugun(clock)
    ekipman = await db.get(ServiceEquipment, equipment_id) if equipment_id else None

    kosullar = []
    if address_id is not None:
        kosullar.append(MaintenanceContract.address_id == address_id)
    if ekipman is not None:
        kosullar.append(
            MaintenanceContract.id.in_(
                select(MaintenanceContractItem.contract_id).where(
                    MaintenanceContractItem.equipment_id == ekipman.id,
                    MaintenanceContractItem.is_deleted.is_(False),
                )
            )
        )
    if not kosullar and customer_id is not None:
        kosullar.append(MaintenanceContract.account_id == customer_id)
    sozlesmeler: list = []
    if kosullar:
        stmt = select(MaintenanceContract).where(
            MaintenanceContract.is_deleted.is_(False),
            MaintenanceContract.status.in_(("AKTIF", "TEYIT_BEKLIYOR")),
            or_(*kosullar),
        )
        if user is not None:
            from app.services.teknik_servis import bakim

            stmt = bakim.sozlesme_kapsami(stmt, user)
        sozlesmeler = list((await db.scalars(stmt.order_by(MaintenanceContract.id))).all())

    adresler: dict[int, str | None] = {}
    adres_idleri = {s.address_id for s in sozlesmeler if s.address_id}
    if adres_idleri:
        adresler = dict(
            (
                await db.execute(
                    select(Address.id, Address.site_name).where(Address.id.in_(adres_idleri))
                )
            )
            .tuples()
            .all()
        )

    def tarihli_gecerli(s) -> bool:
        return (
            s.status == "AKTIF"
            and s.valid_from is not None
            and s.valid_to is not None
            and s.valid_from <= an < s.valid_to
        )

    aktif = [
        {
            "id": s.id,
            "no": s.contract_no,
            "tesis": adresler.get(s.address_id) or s.site_name_raw,
            "donem": donem_metni(s.valid_from, s.valid_to),
            "durum": s.status,
            "yururlukte": tarihli_gecerli(s),
        }
        for s in sozlesmeler
    ]
    garanti = None
    if ekipman is not None and ekipman.warranty_end is not None and ekipman.warranty_end >= bugun:
        garanti = {
            "bitis": ekipman.warranty_end.isoformat(),
            "kaynak": ekipman.warranty_source,
        }

    if any(s["yururlukte"] for s in aktif):
        durum = "SOZLESMELI"
    elif garanti is not None:
        durum = "GARANTILI"
    elif aktif:
        durum = "BILINMIYOR"  # teyit bekleyen / tarihsiz / dönem dışı aktif
    elif customer_id is None and address_id is None and ekipman is None:
        durum = "BILINMIYOR"
    else:
        durum = "KAPSAM_DISI"

    son_isler: list[dict[str, Any]] = []
    if user is not None and (address_id is not None or ekipman is not None):
        gun = int(await ayar_svc.get(db, "servis_kapsam_son_is_gun"))
        is_kosulu = []
        if address_id is not None:
            is_kosulu.append(ServiceOrder.address_id == address_id)
        if ekipman is not None:
            is_kosulu.append(ServiceOrder.equipment_id == ekipman.id)
        stmt = select(ServiceOrder).where(
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.created_at >= an - timedelta(days=gun),
            or_(*is_kosulu),
        )
        stmt = kapsam.kapsam_isler(stmt, user, ServiceOrder.id)
        son_isler = [
            {"id": s.id, "so_no": s.so_no, "durum": s.status, "konu": s.konu, "tarih": s.created_at}
            for s in (
                await db.scalars(stmt.order_by(ServiceOrder.created_at.desc()).limit(20))
            ).all()
        ]
    return {
        "kapsam_durumu": durum,
        "aktif_sozlesmeler": aktif,
        "garanti": garanti,
        "son_isler": son_isler,
    }


async def _kapsam_damgasi(db: AsyncSession, so: Any, clock: Clock) -> None:
    """`is_olusturuldu` kancası: kapsam anlık görüntüsü açılışta BİR KEZ yazılır.

    Sonradan sözleşme pasiflense de değişmez (güncelleme uçları bu alanları
    kabul etmez). Göç işi (`source_system` dolu) ve kapsamı zaten verilmiş iş
    (PB üretimi SOZLESMELI yazar) atlanır: göç anı açılış anı değildir.
    """
    if so.coverage_status is not None or getattr(so, "source_system", None):
        return
    bilgi = await kapsam_bilgisi(
        db,
        customer_id=so.customer_id,
        address_id=so.address_id,
        equipment_id=so.equipment_id,
        clock=clock,
    )
    so.coverage_status = bilgi["kapsam_durumu"]
    so.coverage_snapshot = {
        "zaman": clock.now().isoformat(),
        "kapsam_durumu": bilgi["kapsam_durumu"],
        "sozlesmeler": [
            {k: s[k] for k in ("id", "no", "tesis", "donem", "durum")}
            for s in bilgi["aktif_sozlesmeler"]
        ],
        "garanti": bilgi["garanti"],
    }
    await db.flush()


# --- Müşteri kartının servis sekmesi (TS-192, E14-07) -------------------------------


async def servis_karti(
    db: AsyncSession, user: User, hesap: Account, clock: Clock
) -> dict[str, Any]:
    """Canlı `/kart` DEĞİŞMEZ; servis sekmesi bu ayrı özetten beslenir.

    - Açık iş sayısı servis işi LİSTE sorgusundan sayılır (`/isler?musteri_id=
      &durum_grubu=ACIK` `X-Toplam-Kayit`'ı ile aynı); kartta ayrı sayım yok.
    - Her blok kendi modül izniyle ve birim kapsamıyla gelir; izni olmayan
      blok yanıtta HİÇ yoktur.
    - Tutar (sözleşme ücreti) yalnız `maliyet.gor` sahibinde anahtar olarak var.
    """
    from app.models import MaintenanceContract, Quote, Rental
    from app.services.teknik_servis import is_emirleri, kapsam
    from app.services.teknik_servis.yerel_zaman import yerel_bugun

    sonuc: dict[str, Any] = {
        "hesap_id": hesap.id,
        "unvan": hesap.title,
        # Faz A (TS-200): müşteri sözleşmesinin SLA takvimi + iyimser kilit sürümü
        # (`PATCH /musteriler/{id}` ile yazılır; null = SLA politikasının takvimi).
        "sla_takvim_turu": hesap.sla_takvim_turu,
        "version": hesap.version,
    }

    acik_f = is_emirleri.ListeFiltresi(musteri_id=hesap.id, durum_grubu="ACIK")
    acik_stmt = is_emirleri.liste_sorgusu(user, acik_f, clock).order_by(None)
    alt = acik_stmt.subquery()
    sonuc["acik_is_sayisi"] = int(await db.scalar(select(func.count()).select_from(alt)) or 0)
    lokasyon_acik = dict(
        (await db.execute(select(alt.c.address_id, func.count()).group_by(alt.c.address_id)))
        .tuples()
        .all()
    )

    tesisler = (
        await db.scalars(
            select(Address)
            .where(Address.account_id == hesap.id, Address.kind == "TESIS")
            .order_by(Address.is_active.desc(), Address.site_name, Address.id)
        )
    ).all()
    sonuc["lokasyonlar"] = [
        {
            "id": a.id,
            "tesis_adi": a.site_name or a.label,
            "il": a.city,
            "aktif": a.is_active,
            "acik_is": int(lokasyon_acik.get(a.id, 0)),
            "sla_takvim_turu": a.sla_takvim_turu,
        }
        for a in tesisler
    ]
    sonuc["lokasyonsuz_acik_is"] = int(lokasyon_acik.get(None, 0))

    son_f = is_emirleri.ListeFiltresi(musteri_id=hesap.id, kapali_dahil=True)
    son = (await db.scalars(is_emirleri.liste_sorgusu(user, son_f, clock).limit(20))).all()
    sonuc["servis_isleri"] = [
        {
            "id": s.id,
            "so_no": s.so_no,
            "birim": s.birim,
            "tur": s.tur,
            "durum": s.status,
            "konu": s.konu,
            "lokasyon_id": s.address_id,
            "tarih": s.created_at,
        }
        for s in son
    ]

    maliyet = user.has("maliyet.gor")
    if user.has("bakim.gor"):
        from app.services.teknik_servis import bakim

        stmt = bakim.sozlesme_kapsami(
            select(MaintenanceContract).where(
                MaintenanceContract.account_id == hesap.id,
                MaintenanceContract.is_deleted.is_(False),
            ),
            user,
        )
        satirlar = []
        for s in (await db.scalars(stmt.order_by(MaintenanceContract.id.desc()).limit(50))).all():
            satir = {
                "id": s.id,
                "no": s.contract_no,
                "birim": s.birim,
                "tesis_id": s.address_id,
                "tesis": s.site_name_raw,
                "donem": donem_metni(s.valid_from, s.valid_to),
                "durum": s.status,
            }
            if maliyet:
                satir["ucret"] = float(s.fee_per_visit) if s.fee_per_visit is not None else None
            satirlar.append(satir)
        sonuc["sozlesmeler"] = satirlar

    if user.has("ekipman.gor"):
        from app.services.teknik_servis import ekipman as ekipman_svc

        e_stmt = ekipman_svc.liste_sorgusu(
            user,
            ekipman_svc.EkipmanSuzgeci(hesap_id=hesap.id),
            bugun=yerel_bugun(clock),
            an=clock.now(),
        ).order_by(None)
        e_alt = e_stmt.with_only_columns(ekipman_svc.ServiceEquipment.equipment_type).subquery()
        kirilim = dict(
            (
                await db.execute(
                    select(e_alt.c.equipment_type, func.count()).group_by(e_alt.c.equipment_type)
                )
            )
            .tuples()
            .all()
        )
        sonuc["ekipman_sayisi"] = int(sum(kirilim.values()))
        sonuc["ekipman_turleri"] = [{"tip": t, "adet": int(n)} for t, n in sorted(kirilim.items())]

    if user.has("kiralama.gor"):
        stmt = kapsam.kapsam_birim(
            select(Rental).where(
                Rental.customer_id == hesap.id,
                Rental.is_deleted.is_(False),
                Rental.status.not_in(("KAPANDI", "IPTAL")),
            ),
            user,
            Rental.birim,
            birimsiz_gorunur=False,
        )
        sonuc["kiralamalar"] = [
            {
                "id": r.id,
                "no": r.rental_no,
                "birim": r.birim,
                "durum": r.status,
                "baslangic": r.baslangic,
                "bitis": r.bitis,
            }
            for r in (await db.scalars(stmt.order_by(Rental.id.desc()).limit(50))).all()
        ]

    if user.has("teklif.gor"):
        # Yalnız birimli (servis) teklifler; satış teklifi canlı Hesaplar kartında.
        stmt = kapsam.kapsam_birim(
            select(Quote).where(
                Quote.customer_id == hesap.id,
                Quote.birim.is_not(None),
                Quote.is_deleted.is_(False),
            ),
            user,
            Quote.birim,
            birimsiz_gorunur=False,
        )
        sonuc["teklifler"] = [
            {
                "id": q.id,
                "no": q.quote_no,
                "birim": q.birim,
                "durum": q.status,
                "tarih": q.created_at,
            }
            for q in (await db.scalars(stmt.order_by(Quote.id.desc()).limit(20))).all()
        ]

    bos = (
        not sonuc["servis_isleri"]
        and not sonuc.get("sozlesmeler")
        and not sonuc.get("ekipman_sayisi")
    )
    sonuc["aciklama"] = (
        "Bu müşteriye bağlanmamış eski kayıtlar olabilir — Servis Ana Verisi > Eşleştirme"
        if bos
        else None
    )
    return sonuc


# --- Uyarı ---------------------------------------------------------------------


async def dogrulanmamis_sayilari(db: AsyncSession, user: User, clock: Clock) -> dict[str, int]:
    """`hesap_dogrulanmamis_uyari_gun`'den eski doğrulanmamış müşteri/tesis sayısı.

    Uyarı modülü (`s/uyarilar.py`) bunu `hesap.birlestir` sahibine gösterir;
    hızlı eklenen kayıt doğrulanmadan aylarca kalırsa VKN'siz cariye fatura
    kesilmeye başlanır. Sayılar hesap kapsamından geçer (sayı = sızıntı).
    """
    from app.services import settings as ayar_svc

    gun = int(await ayar_svc.get(db, "hesap_dogrulanmamis_uyari_gun"))
    sinir = clock.now() - timedelta(days=gun)
    hesap_stmt = select(func.count()).select_from(
        hesap_svc.kapsam_uygula(
            select(Account.id).where(
                Account.is_deleted.is_(False),
                Account.is_verified.is_(False),
                Account.created_at < sinir,
            ),
            user,
        ).subquery()
    )
    tesis_stmt = select(func.count()).select_from(
        hesap_svc.kapsam_musteri(
            select(Address.id)
            .join(Account, Account.id == Address.account_id)
            .where(
                Account.is_deleted.is_(False),
                Address.kind == "TESIS",
                Address.is_active.is_(True),
                Address.is_verified.is_(False),
                Address.created_at < sinir,
            ),
            user,
            Address.account_id,
        ).subquery()
    )
    return {
        "hesap": int(await db.scalar(hesap_stmt) or 0),
        "lokasyon": int(await db.scalar(tesis_stmt) or 0),
    }


async def dogrulanmamis_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list:
    """Uyarı zili: eski doğrulanmamış müşteri ve tesis sayıları (`hesap.birlestir`)."""
    from app.services.uyarilar import Uyari

    sayilar = await dogrulanmamis_sayilari(db, user, clock)
    return [
        Uyari(
            kod="hesap_dogrulanmamis",
            baslik="Doğrulanmamış müşteri",
            adet=sayilar["hesap"],
            yol="/hesaplar",
            onem="uyari",
            aciklama="Servis ekranından hızlı açılmış, süresi geçmiş ve henüz doğrulanmamış.",
        ),
        Uyari(
            kod="lokasyon_dogrulanmamis",
            baslik="Doğrulanmamış tesis",
            adet=sayilar["lokasyon"],
            yol="/hesaplar",
            onem="bilgi",
            aciklama="Hızlı eklenmiş, süresi geçmiş ve henüz doğrulanmamış tesis.",
        ),
    ]


# Uyarı kaydı modülün sonunda (plan §1.11): toplayıcı bu modülü kendisi yükler.
from app.services.teknik_servis import uyarilar as _ts_uyarilar  # noqa: E402

_ts_uyarilar.kaydet("ana_veri", "hesap.birlestir", dogrulanmamis_uyarilari)

# Kapsam anlık görüntüsü açılışta bir kez (TS-192, E14-17; plan KD-15 kanca kalıbı).
from app.services.teknik_servis import kancalar as _kancalar  # noqa: E402

_kancalar.kaydet("is_olusturuldu", _kapsam_damgasi)
