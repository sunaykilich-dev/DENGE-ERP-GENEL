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
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, AuditLog, Contact, Device, Vehicle
from app.models.vehicle import plaka_anahtari
from app.services import audit
from app.services.normalize import normalize_msisdn, normalize_plate, tr_normkey

# Kişisel veri taşıyan varlıklar — erişim logu ve veri bulma bunlara bakar.
KISISEL_VARLIKLAR = ("accounts", "contacts", "vehicles")


class KvkkHatasi(ValueError):
    """KVKK işlemi kurallara aykırı."""


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

    kisi_kosullari = [
        func.lower(Contact.full_name).contains(arama.lower()),
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

    return {
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
