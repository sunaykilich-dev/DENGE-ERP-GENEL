"""KVKK: kişisel veriye erişim logu, veri bulma, saklama ve imha.

Brief §8 dört şey istiyor: rol bazlı erişim (zaten `require_permission`),
**kişisel veriye erişim logu**, **saklama süresi parametreleri ve süre
dolunca imha/anonimleştirme**, **silme/erişim talebi için veri bulma**.

**İmha yerine ANONİMLEŞTİRME.** Kaydı silmek iş geçmişini de siler: bir
aracın hangi cihazı taşıdığı, hangi montaj yapıldığı ticari kayıttır ve
kişisel veri değildir. Bu yüzden kişiyi tanımlayan alanlar (ad, telefon,
e-posta, plaka, şase) maskelenir, kaydın kendisi ve ilişkileri durur.
Böylece hak ediş geçmişi ve cihaz zaman çizelgesi bozulmaz.

**Anonimleştirme geri alınamaz** ve bunu yapan kişi denetim izine yazılır.

**Kayıt defterleri (teknik servis, plan §1.11):** yeni modüller kişisel veri
alanlarını bu dosyayı düzenlemeden, kendi dosyalarının sonunda kaydeder —
`ANONIMLESTIRME_KANCALARI` (hesap anonimleştirilirken çalışan temizleyiciler),
`VERI_BUL_KANCALARI` (ilgili kişi başvurusunda ek arama), ve
`DENETIM_MASKE_VARLIKLARI` (geçmiş denetim satırlarının maskelenmesi). Bu
dosya Dalga 1'den sonra dondurulur; bir modülün kişisel alanı ancak buraya
kaydolursa imhaya girer.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, AccountAlias, Address, AuditLog, Contact, Device, Vehicle
from app.models.vehicle import plaka_anahtari
from app.services import audit
from app.services.normalize import normalize_msisdn, normalize_plate, tr_normkey

# Kişisel veri taşıyan varlıklar — erişim logu ve veri bulma bunlara bakar.
# `addresses`: bireysel müşterinin tesisi evidir; `account_aliases`: eski
# yazımlar kişinin adını taşıyabilir (E14-03).
KISISEL_VARLIKLAR = ("accounts", "contacts", "vehicles", "addresses", "account_aliases")


class KvkkHatasi(ValueError):
    """KVKK işlemi kurallara aykırı."""


# --- Kayıt defterleri ------------------------------------------------------------


@dataclass
class VeriBulAramasi:
    """Veri bulma kancalarına verilen, bir kez çözülmüş arama."""

    arama: str
    anahtar: str  # tr_normkey(arama)
    telefon: str | None
    plaka: str | None
    hesap_idleri: list[int] = field(default_factory=list)


# (db, account_id, clock) → {"etiket": maskelenen_satir_sayisi}
AnonimlestirmeKancasi = Callable[[AsyncSession, int, Clock], Awaitable[dict[str, int]]]
# (db, arama) → bulunan kayıt satırları (sonuç sözlüğünde kendi anahtarı altında)
VeriBulKancasi = Callable[[AsyncSession, VeriBulAramasi], Awaitable[list[dict]]]
# (db, account_id) → bu hesaba ait denetim satırlarını seçen SQL koşulları
DenetimMaskeKancasi = Callable[[AsyncSession, int], Awaitable[list[ColumnElement[bool]]]]

ANONIMLESTIRME_KANCALARI: list[AnonimlestirmeKancasi] = []
VERI_BUL_KANCALARI: dict[str, VeriBulKancasi] = {}
DENETIM_MASKE_VARLIKLARI: dict[str, DenetimMaskeKancasi] = {}


def anonimlestirme_kaydet(fn: AnonimlestirmeKancasi) -> AnonimlestirmeKancasi:
    """Hesap anonimleştirilirken çalışacak temizleyiciyi kaydeder (idempotent)."""
    if fn not in ANONIMLESTIRME_KANCALARI:
        ANONIMLESTIRME_KANCALARI.append(fn)
    return fn


def veri_bul_kaydet(anahtar: str, fn: VeriBulKancasi) -> None:
    """`veri_bul` sonucuna `anahtar` altında ek kayıt listesi ekler."""
    if anahtar in ("arama", "hesaplar", "kisiler", "araclar", "cihazlar", "ozet"):
        raise ValueError(f"Veri bulma anahtarı çekirdek alanla çakışıyor: {anahtar}")
    VERI_BUL_KANCALARI[anahtar] = fn


def denetim_maske_kaydet(entity: str, fn: DenetimMaskeKancasi) -> None:
    """`entity` denetim satırlarını anonimleştirmede maskelenecek varlıklara ekler."""
    DENETIM_MASKE_VARLIKLARI[entity] = fn


def denetim_hesap_kosulu(entity: str, account_id: int, idler: list[int]) -> ColumnElement[bool]:
    """`entity` için hesaba ait denetim satırlarının koşulu.

    Satır kimliğiyle (`entity_id`) YA DA değer içindeki `hesap` anahtarıyla
    eşleşir: silinmiş satırın (ör. silinen takma ad) kimliği artık hesaptan
    bulunamaz ama denetim satırı onun metnini taşır.
    """
    hesap = str(account_id)
    kosul = or_(
        AuditLog.new_value.op("->>")("hesap") == hesap,
        AuditLog.old_value.op("->>")("hesap") == hesap,
    )
    if idler:
        kosul = or_(kosul, AuditLog.entity_id.in_([str(i) for i in idler]))
    return and_(AuditLog.entity == entity, kosul)


# --- Erişim logu --------------------------------------------------------------


async def erisim_kaydet(
    db: AsyncSession,
    *,
    entity: str,
    entity_id: int | str | None,
    amac: str,
    user_id: int | None,
    ip: str | None = None,
) -> None:
    """Kişisel veriye OKUMA erişimini loglar.

    Yazma zaten denetim izinde; KVKK'nın ayrıca istediği, kimin ne zaman
    hangi kişisel veriyi GÖRDÜĞÜ. Liste ekranlarında değil, tek bir kişinin
    kartı açıldığında kaydedilir — aksi halde log, gürültüden okunamaz hale
    gelirdi.
    """
    await audit.log(
        db,
        entity,
        "kisisel.eris",
        entity_id=entity_id,
        new_value={"amac": amac},
        user_id=user_id,
        ip=ip,
        is_personal_data=True,
    )


async def erisim_gecmisi(
    db: AsyncSession,
    *,
    entity: str | None = None,
    entity_id: str | None = None,
    user_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Kişisel veri erişim kayıtları."""
    stmt = (
        select(AuditLog)
        .where(AuditLog.is_personal_data.is_(True))
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == str(entity_id))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)

    return [
        {
            "id": k.id,
            "user_id": k.user_id,
            "entity": k.entity,
            "entity_id": k.entity_id,
            "action": k.action,
            "amac": (k.new_value or {}).get("amac"),
            "ip": str(k.ip) if k.ip else None,
            "created_at": k.created_at,
        }
        for k in (await db.scalars(stmt)).all()
    ]


# --- Veri bulma (erişim / silme talebi) --------------------------------------


async def veri_bul(db: AsyncSession, arama: str) -> dict:
    """Bir kişiyle ilgili TÜM kayıtları bulur (silme/erişim talebi için).

    Arama: unvan, kişi adı, telefon ya da plaka. Kişinin hangi ad altında
    kayıtlı olduğunu bilmeyen bir talepte tek alandan aramak yetersizdi.
    """
    arama = (arama or "").strip()
    if len(arama) < 3:
        raise KvkkHatasi("Arama en az 3 karakter olmalı.")

    anahtar = tr_normkey(arama)
    try:
        telefon = normalize_msisdn(arama)
    except ValueError:
        telefon = None
    try:
        plaka = normalize_plate(arama)
    except ValueError:
        plaka = None

    # Koşullar listeden kurulur: eşleşmeyen bir "nöbetçi değer" koymak
    # (ör. "\\x00") PostgreSQL metin alanında hataya yol açıyordu.
    hesap_kosullari = [Account.title_key.contains(anahtar), Account.email == arama.lower()]
    if telefon:
        hesap_kosullari.append(Account.phone == telefon)
    hesaplar = (
        await db.scalars(
            select(Account).where(Account.is_deleted.is_(False), or_(*hesap_kosullari)).limit(50)
        )
    ).all()

    # Ad araması Türkçe katlanmış anahtar üzerinden: `lower()` veritabanı
    # collation'ına bağlı ('C' collation'da `lower('Ö')` = 'Ö'), "ÖZKAN" araması
    # "Ali Özkan"ı bulamıyordu. Katlama SQL'de `translate` ile, aramanınki
    # `tr_normkey` ile — iki taraf aynı kurala iner.
    kisi_kosullari = [
        _sql_katla(Contact.full_name).contains(anahtar),
        Contact.email == arama.lower(),
    ]
    if telefon:
        kisi_kosullari.append(Contact.phone == telefon)
    kisiler = (await db.scalars(select(Contact).where(or_(*kisi_kosullari)).limit(50))).all()

    hesap_idleri = [h.id for h in hesaplar] or [0]
    arac_kosullari = [Vehicle.customer_id.in_(hesap_idleri)]
    if plaka:
        arac_kosullari.append(Vehicle.plate_key == plaka_anahtari(plaka))
    araclar = (
        await db.scalars(
            select(Vehicle).where(Vehicle.is_deleted.is_(False), or_(*arac_kosullari)).limit(200)
        )
    ).all()

    cihazlar = (
        await db.scalars(
            select(Device)
            .where(
                Device.is_deleted.is_(False),
                Device.current_customer_id.in_(hesap_idleri),
            )
            .limit(500)
        )
    ).all()

    sonuc: dict[str, Any] = {
        "arama": arama,
        "hesaplar": [
            {
                "id": h.id,
                "unvan": h.title,
                "telefon": h.phone,
                "eposta": h.email,
                "vkn": h.tax_no,
                "anonim": _anonim_mi(h.title),
            }
            for h in hesaplar
        ],
        "kisiler": [
            {
                "id": k.id,
                "account_id": k.account_id,
                "ad": k.full_name,
                "telefon": k.phone,
                "eposta": k.email,
                "anonim": _anonim_mi(k.full_name),
            }
            for k in kisiler
        ],
        "araclar": [
            {"id": a.id, "plaka": a.plate, "sase": a.chassis_no, "musteri_id": a.customer_id}
            for a in araclar
        ],
        "cihazlar": [
            {"device_id": c.id, "kimlik": c.imei or c.serial_no, "status": c.status}
            for c in cihazlar
        ],
    }
    baglam = VeriBulAramasi(
        arama=arama,
        anahtar=anahtar,
        telefon=telefon,
        plaka=plaka,
        hesap_idleri=[h.id for h in hesaplar],
    )
    for ad, kanca in VERI_BUL_KANCALARI.items():
        sonuc[ad] = await kanca(db, baglam)
    return sonuc


# 'C' collation'dan bağımsız Türkçe katlama: `tr_normkey`'in harf tablosunun
# SQL karşılığı (uzunluklar eşit olmalı — translate harf harf eşler).
_TR_KAYNAK = "İIıŞşĞğÜüÖöÇçÂâÎîÛû"
_TR_HEDEF = "iiissgguuooccaaiiuu"


def _sql_katla(sutun):
    return func.lower(func.translate(sutun, _TR_KAYNAK, _TR_HEDEF))


ANONIM_ISARETI = "[ANONİMLEŞTİRİLDİ]"

# Denetim izinde kişisel veri DEĞERİNİN yerine yazılan işaret. Olay durur,
# değer gider.
DEGER_SILINDI = {"kvkk": "değer imha edildi"}


def _anonim_mi(deger: str | None) -> bool:
    return bool(deger) and ANONIM_ISARETI in deger


# --- Anonimleştirme -----------------------------------------------------------


async def hesabi_anonimlestir(
    db: AsyncSession,
    account_id: int,
    *,
    clock: Clock,
    gerekce: str,
    user_id: int | None = None,
    ip: str | None = None,
) -> dict:
    """Hesabı ve bağlı kişileri anonimleştirir. GERİ ALINAMAZ.

    Ticari kayıt (cihaz geçmişi, iş emri, hak ediş) KORUNUR; yalnız kişiyi
    tanımlayan alanlar maskelenir.
    """
    if not gerekce or len(gerekce.strip()) < 5:
        raise KvkkHatasi("Anonimleştirme gerekçesi zorunlu (silme talebi referansı).")

    hesap = await db.get(Account, account_id)
    if hesap is None or hesap.is_deleted:
        raise KvkkHatasi(f"Hesap bulunamadı: {account_id}")
    if _anonim_mi(hesap.title):
        raise KvkkHatasi("Bu hesap zaten anonimleştirilmiş.")

    # Denetim iznine HANGİ ALANLARIN temizlendiği yazılır, DEĞERLERİ değil.
    # Eski sürüm unvan/telefon/e-postayı `old_value` içine düz metin
    # yazıyordu; Denetim İzi ekranında aynen okunabiliyordu, yani
    # "geri alınamaz" denen anonimleştirme bilgi düzeyinde geri alınabiliyordu.
    temizlenen = sorted(
        a
        for a in ("title", "phone", "email", "tax_no", "tax_office", "iban", "notes")
        if getattr(hesap, a, None)
    )
    etiket = f"{ANONIM_ISARETI} #{hesap.id}"
    hesap.title = etiket
    hesap.title_key = tr_normkey(etiket)
    hesap.phone = None
    hesap.email = None
    hesap.tax_no = None
    hesap.tax_office = None
    hesap.iban = None
    hesap.notes = None
    hesap.updated_by = user_id

    kisiler = (await db.scalars(select(Contact).where(Contact.account_id == account_id))).all()
    for k in kisiler:
        k.full_name = f"{ANONIM_ISARETI} #{k.id}"
        k.phone = None
        k.email = None

    # Plaka kişisel veridir; şase araca aittir ve ticari kayıt sayılır ama
    # plakayla birlikte kişiyi işaret ettiği için o da maskelenir.
    araclar = (
        await db.scalars(
            select(Vehicle).where(Vehicle.customer_id == account_id, Vehicle.is_deleted.is_(False))
        )
    ).all()
    for a in araclar:
        a.plate = f"{ANONIM_ISARETI[:12]}-{a.id}"
        a.chassis_no = None
        a.registration_no = None
        a.is_plate_verified = False

    await db.flush()
    # Modül temizleyicileri (tesis, takma ad; Dalga 1+ servis kayıtlarının ham
    # irtibat metinleri). Denetim maskesinden ÖNCE: onların ürettiği yazımlar
    # da maskelenecek satırlar arasında olmalı.
    kanca_sayilari: dict[str, int] = {}
    for kanca in ANONIMLESTIRME_KANCALARI:
        for etiket, adet in (await kanca(db, account_id, clock)).items():
            kanca_sayilari[etiket] = kanca_sayilari.get(etiket, 0) + adet
    await db.flush()

    maskelenen = await _denetim_izini_maskele(db, account_id, [k.id for k in kisiler])
    await audit.log(
        db,
        "accounts",
        "kvkk.anonimlestir",
        entity_id=account_id,
        old_value={"temizlenen_alanlar": temizlenen},
        new_value={
            "gerekce": gerekce,
            "kisi": len(kisiler),
            "arac": len(araclar),
            **kanca_sayilari,
            "denetim_satiri": maskelenen,
        },
        user_id=user_id,
        ip=ip,
        is_personal_data=True,
    )
    return {
        "account_id": account_id,
        "kisi": len(kisiler),
        "arac": len(araclar),
        **kanca_sayilari,
        "denetim_satiri": maskelenen,
    }


async def _denetim_izini_maskele(db: AsyncSession, account_id: int, kisi_ids: list[int]) -> int:
    """Hesabın GEÇMİŞ denetim kayıtlarındaki kişisel veri değerlerini maskeler.

    İmha yalnız ana kaydı temizlemekle bitmiyor: `audit_logs.old_value` /
    `new_value` alanları o hesabın eski unvanını, telefonunu ve e-postasını
    düz metin tutuyor ve Denetim İzi ekranında okunabiliyordu.

    Olayın kendisi (kim, ne zaman, hangi işlem) KORUNUR — denetim izinin
    anlamı budur; silinen yalnız kişisel veri DEĞERLERİDİR. Satır sayısı
    geri döner ve anonimleştirme kaydına yazılır.
    """
    # `audit_logs.entity_id` METİN (varchar): tablo tüm modülleri taşıdığı için
    # kimlik tipi sabit değil. Karşılaştırmada dönüştürmek ŞART — sayıyla
    # karşılaştırmak Postgres'te doğrudan hata verir.
    kosul = [and_(AuditLog.entity == "accounts", AuditLog.entity_id == str(account_id))]
    if kisi_ids:
        kosul.append(
            and_(AuditLog.entity == "contacts", AuditLog.entity_id.in_([str(k) for k in kisi_ids]))
        )
    for kanca in DENETIM_MASKE_VARLIKLARI.values():
        kosul.extend(await kanca(db, account_id))
    sonuc = await db.execute(
        sa_update(AuditLog)
        .where(or_(*kosul), AuditLog.is_personal_data.is_(True))
        .values(old_value=DEGER_SILINDI, new_value=DEGER_SILINDI)
    )
    return sonuc.rowcount or 0


# --- Saklama süresi -----------------------------------------------------------


async def saklama_suresi_dolanlar(
    db: AsyncSession, clock: Clock, *, yil: int | None = None
) -> list[dict]:
    """Saklama süresi dolmuş, hareketsiz müşteri hesapları.

    Ölçüt: aktif aboneliği, açık cihazı ve son N yılda iş emri olmayan
    hesaplar. Otomatik anonimleştirme YAPILMAZ — liste çıkarılır, karar
    insana bırakılır; yanlış bir ölçütün müşteri kaydını sessizce silmesi
    geri alınamaz bir hata olurdu.
    """
    from app.services import settings as ayar_svc

    sure = yil if yil is not None else int(await ayar_svc.get(db, "kvkk_saklama_yili"))
    sinir: date = clock.now().date() - timedelta(days=365 * sure)

    from app.models import Subscription, WorkOrder

    # DİKKAT — `NOT IN (NULL içeren alt sorgu)` HER SATIR İÇİN UNKNOWN döner,
    # yani sonuç DAİMA BOŞTUR. `work_orders.customer_id` alanında 7 NULL satır
    # vardı ve bu yüzden saklama süresi listesi hiç dolmuyordu: KVKK §8'in
    # "süresi dolanı imha et" ayağı sessizce hiç çalışmadı (ölçüldü: NULL
    # ayıklanınca 0 yerine 319 hesap). Her alt sorguda NULL ayıklaması ŞART.
    aktif_abonelik = select(Subscription.customer_id).where(
        Subscription.is_deleted.is_(False),
        Subscription.customer_id.is_not(None),
        Subscription.status.in_(("TASLAK", "AKTIF", "ASKIDA")),
    )
    acik_cihaz = select(Device.current_customer_id).where(
        Device.current_customer_id.is_not(None), Device.is_deleted.is_(False)
    )
    son_isler = select(WorkOrder.customer_id).where(
        WorkOrder.is_deleted.is_(False),
        WorkOrder.customer_id.is_not(None),
        WorkOrder.completed_at.is_not(None),
        func.date(WorkOrder.completed_at) >= sinir,
    )

    hesaplar = (
        await db.scalars(
            select(Account).where(
                Account.is_deleted.is_(False),
                Account.is_musteri.is_(True),
                Account.id.not_in(aktif_abonelik),
                Account.id.not_in(acik_cihaz),
                Account.id.not_in(son_isler),
            )
        )
    ).all()

    return [
        {
            "account_id": h.id,
            "unvan": h.title,
            "telefon": h.phone,
            "eposta": h.email,
            "anonim": _anonim_mi(h.title),
            "esik_yil": sure,
        }
        for h in hesaplar
        if not _anonim_mi(h.title)
    ]


def maskele(deger: str | None, *, gosterilecek: int = 3) -> str | None:
    """Rapor ve ekran için kısmi maskeleme (ör. telefon son 3 hane)."""
    if not deger:
        return deger
    if len(deger) <= gosterilecek:
        return "*" * len(deger)
    return "*" * (len(deger) - gosterilecek) + deger[-gosterilecek:]


def ozet(veri: dict[str, Any]) -> dict[str, int]:
    return {anahtar: len(deger) for anahtar, deger in veri.items() if isinstance(deger, list)}


# --- Ana veri: tesis ve takma ad (TS-016, E14-03) ---------------------------------
#
# Çekirdek kayıtlar: `addresses` ve `account_aliases` canlı hesap tablolarının
# parçası olduğu için temizleyicileri burada, diğer modüller kendi dosyalarında.


async def _tesisleri_anonimlestir(db: AsyncSession, account_id: int, _clock: Clock) -> dict:
    """Hesabın adres satırları ve takma adları maskelenir; satırlar DURUR.

    Servis işi, ekipman ve sözleşme bu satırlara FK ile bağlı — ticari kayıt
    korunur, yalnız kişiyi işaret eden metin gider. Türetilmiş anahtarlar
    (`site_key`, `alias_key`) ORM olayıyla MASKELİ metinden yeniden üretilir:
    eski anahtar kalsaydı ad geri okunurdu ve global tekil `alias_key` aynı
    yazımla yeni kaydı 409'a düşürürdü (E14 B5).
    """
    adresler = (await db.scalars(select(Address).where(Address.account_id == account_id))).all()
    for a in adresler:
        etiket = f"{ANONIM_ISARETI} #{a.id}"
        if a.line is not None or a.kind != "TESIS":
            a.line = etiket  # ck_addresses_satir: TESIS dışında satır boş olamaz
        if a.site_name is not None or a.kind == "TESIS":
            a.site_name = etiket  # site_key olayla yeniden üretilir
        a.access_note = None
        a.district = None

    takma_adlar = (
        await db.scalars(select(AccountAlias).where(AccountAlias.account_id == account_id))
    ).all()
    for t in takma_adlar:
        # Anahtar kimlik taşır ki global tekillik bozulmasın (iki maskeli ad
        # aynı anahtara düşerse ikinci UPDATE 409 verirdi).
        t.alias_text = f"{ANONIM_ISARETI} TAKMA {t.id}"
    return {"lokasyon": len(adresler), "takma_ad": len(takma_adlar)}


async def _adres_denetim_kosulu(db: AsyncSession, account_id: int) -> list[ColumnElement[bool]]:
    idler = list(await db.scalars(select(Address.id).where(Address.account_id == account_id)))
    return [denetim_hesap_kosulu("addresses", account_id, idler)]


async def _takma_ad_denetim_kosulu(db: AsyncSession, account_id: int) -> list[ColumnElement[bool]]:
    idler = list(
        await db.scalars(select(AccountAlias.id).where(AccountAlias.account_id == account_id))
    )
    return [denetim_hesap_kosulu("account_aliases", account_id, idler)]


async def _tesis_bul(db: AsyncSession, arama: VeriBulAramasi) -> list[dict]:
    """İlgili kişi başvurusu: adres metni, erişim notu ve tesis adında arar;
    bulunan hesapların bütün adresleri de listelenir."""
    kosullar = [
        _sql_katla(Address.line).contains(arama.anahtar),
        _sql_katla(Address.access_note).contains(arama.anahtar),
        _sql_katla(Address.site_name).contains(arama.anahtar),
    ]
    if arama.hesap_idleri:
        kosullar.append(Address.account_id.in_(arama.hesap_idleri))
    adresler = (await db.scalars(select(Address).where(or_(*kosullar)).limit(200))).all()
    return [
        {
            "id": a.id,
            "account_id": a.account_id,
            "tur": a.kind,
            "tesis_adi": a.site_name,
            "adres": a.line,
            "il": a.city,
            "anonim": _anonim_mi(a.line) or _anonim_mi(a.site_name),
        }
        for a in adresler
    ]


async def _takma_ad_bul(db: AsyncSession, arama: VeriBulAramasi) -> list[dict]:
    kosullar = [_sql_katla(AccountAlias.alias_text).contains(arama.anahtar)]
    if arama.hesap_idleri:
        kosullar.append(AccountAlias.account_id.in_(arama.hesap_idleri))
    takmalar = (await db.scalars(select(AccountAlias).where(or_(*kosullar)).limit(200))).all()
    return [
        {
            "id": t.id,
            "account_id": t.account_id,
            "metin": t.alias_text,
            "kaynak": t.kaynak,
            "anonim": _anonim_mi(t.alias_text),
        }
        for t in takmalar
    ]


anonimlestirme_kaydet(_tesisleri_anonimlestir)
denetim_maske_kaydet("addresses", _adres_denetim_kosulu)
denetim_maske_kaydet("account_aliases", _takma_ad_denetim_kosulu)
veri_bul_kaydet("lokasyonlar", _tesis_bul)
veri_bul_kaydet("takma_adlar", _takma_ad_bul)
