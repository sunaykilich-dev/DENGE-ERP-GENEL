"""Hesap iş kuralları."""

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, User
from app.permissions import SCOPE_OWN_CUSTOMERS
from app.services.normalize import tr_normkey


def kapsam_uygula(stmt: Select, user: User) -> Select:
    """Kayıt bazlı filtre (brief §3).

    Satış temsilcisi yalnız kendi müşterilerini görür. Filtreyi her liste
    ucunda elle yazmak unutulmaya açık olduğu için tek yardımcıya toplandı —
    yeni bir liste ucu yazan buraya uğramak zorunda.
    """
    if user.role.scope == SCOPE_OWN_CUSTOMERS:
        # Kendi müşterileri + temsilcisi atanmamış olanlar değil, YALNIZ kendisi.
        return stmt.where(Account.sales_rep_id == user.id)
    return stmt


def kendi_hesaplari(user: User):
    """Kullanıcının kapsamındaki hesap id'lerini veren alt sorgu."""
    return select(Account.id).where(Account.sales_rep_id == user.id)


def kapsam_musteri(stmt: Select, user: User, sutun) -> Select:
    """Müşteriye bağlı kayıtlara kapsam filtresi uygular.

    `kapsam_uygula` yalnız `accounts` tablosunu süzüyordu; araç, cihaz ve iş
    emri listeleri kapsamsızdı. Ölçüldü: SATIS rolündeki kullanıcı 7.366
    aracın ve 17.356 cihazın tamamını, müşteri unvanlarıyla birlikte, ADMIN
    ile birebir aynı görüyordu — ve `arac.yaz` izni olduğu için hepsini
    düzenleyebiliyordu.

    **Sahipsiz kayıt GİZLENMEZ.** `customer_id IS NULL` olan bir cihaz
    Denge'nin kendi stoğudur, başka bir temsilcinin portföyü değil; satış
    temsilcisinin satabileceği stoğu görememesi işi durdururdu.
    """
    if user.role.scope != SCOPE_OWN_CUSTOMERS:
        return stmt
    return stmt.where(or_(sutun.is_(None), sutun.in_(kendi_hesaplari(user))))


async def kapsam_disinda_mi(db: AsyncSession, user: User, musteri_id: int | None) -> bool:
    """Tek kayıt için: bu müşteri kullanıcının kapsamı dışında mı?

    Liste filtresinin tek kayıt karşılığı. Yazma uçlarında şart: `db.get()`
    kapsamı atlar ve kontrol açıkça yapılmazsa kapsam dışı kayıt sessizce
    değişir (hesaplarda tam bu yaşandı: cevap 404, yazma geçmiş).

    Sahipsiz kayıt (müşterisi olmayan stok cihazı) kapsam dışı SAYILMAZ.
    """
    if user.role.scope != SCOPE_OWN_CUSTOMERS or musteri_id is None:
        return False
    sahip = await db.scalar(
        select(Account.id).where(Account.id == musteri_id, Account.sales_rep_id == user.id)
    )
    return sahip is None


def eksik_alanlar(hesap: Account) -> list[str]:
    """Teslimatı bloke edecek eksikler (plan §8).

    Montaj noktasının e-postası ve IBAN'ı yoksa hak ediş dökümü gönderilemez
    ve ödeme listesi çıkarılamaz. Kayıt açılırken zorunlu tutmak göçü
    kilitlerdi (kaynak veride ikisi de yok); bunun yerine görünür kılınır.
    """
    eksik: list[str] = []
    if hesap.is_montaj_noktasi:
        if not hesap.email:
            eksik.append("e-posta")
        if not hesap.iban:
            eksik.append("IBAN")
        if not hesap.tax_no:
            eksik.append("VKN/TCKN")
    if hesap.is_musteri and not hesap.tax_no:
        eksik.append("VKN/TCKN")
    return eksik


async def mukerrer_adaylari(
    db: AsyncSession, hesap: Account, *, esik: float = 0.45, limit: int = 5
) -> list[tuple[Account, float]]:
    """Unvan benzerliğine göre olası mükerrer kayıtlar.

    Göçte 44 montaj noktasından 5 çift birleştirilecek
    (`ANTALYA RAMAZAN CULLU` / `ANTALYA RAMAZAN ÇULLU` gibi). Ama benzerlik
    TEK BAŞINA karar ölçütü değildir: kaynak veride `BURSA 3D MOBİL` ile
    `BALIKESİR KOÇ OTO` aynı telefonu taşıyor, farklı firmalar. Bu yüzden
    fonksiyon ADAY üretir; birleştirme kararını insan verir.
    """
    benzerlik = func.similarity(Account.title_key, tr_normkey(hesap.title))
    stmt = (
        select(Account, benzerlik.label("benzerlik"))
        .where(
            Account.id != hesap.id,
            Account.is_deleted.is_(False),
            benzerlik > esik,
        )
        .order_by(benzerlik.desc())
        .limit(limit)
    )
    return [(row[0], float(row[1])) for row in (await db.execute(stmt)).all()]


def arama_filtresi(stmt: Select, terim: str) -> Select:
    """Serbest metin araması — unvan, vergi no, telefon, e-posta, bölge."""
    anahtar = tr_normkey(terim)
    rakam = "".join(ch for ch in terim if ch.isdigit())
    kosullar = [Account.title_key.contains(anahtar)]
    if rakam:
        kosullar.append(Account.tax_no.startswith(rakam))
        kosullar.append(Account.phone.contains(rakam))
    if "@" in terim:
        kosullar.append(Account.email.ilike(f"%{terim}%"))
    return stmt.where(or_(*kosullar))
