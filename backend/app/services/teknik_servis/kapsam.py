"""Teknik servis kayıt kapsamı: birim, kendi işleri, personel, katalog (TS-003).

Canlı `services/accounts.py: kapsam_musteri / kapsam_disinda_mi` kalıbının
teknik servis karşılığı. Canlı yardımcılar DEĞİŞMEZ; yeni kapsamlar
(`KENDI_BIRIMI`, `KENDI_ISLERI`) yalnız burada anlam kazanır, canlı ekranlarda
TUMU gibi davranır (plan §1.2).

**Tek tablo (plan §1.2) — bütün modüller buna uyar:**

- TUMU: servis işleri hepsi; diğer varlıklar ve personel hepsi.
- KENDI_BIRIMI: işler `birim ∈ user_units`; diğer varlıklar `birim ∈ user_units`
  (birimsiz kayıt, ör. ortak depo, görünür; birimsiz personel görünmez).
- KENDI_ISLERI: işler = aktif ataması veya aktif plan üyeliği olanlar; diğer
  varlıklar `birim ∈ user_units`.
- KENDI_MUSTERILERI: işler = `kapsam_musteri(customer_id)` ∧ birim kesişimi;
  diğer varlıklar `user_units` kesişimi (genelde boş → hiçbiri).

**Fail-closed (KD-04):** kapsamı TUMU olmayan kullanıcının birim üyeliği
yoksa liste boş, tek kayıt 404. Bilinmeyen kapsam dizesi = red. "Boş = hepsi"
yorumu, birimi girilmemiş yeni bir şefe bütün birimlerin işlerini açardı.

**KENDI_MUSTERILERI kararı:** satış temsilcisine istisnayla servis izni
verilirse yalnız kendi müşterilerinin VE kendi birimlerinin işlerini görür;
birimi olmadığı için pratikte hiçbirini (TS-003 kabulü). Müşteri süzgeci
tek başına bırakılsaydı servis kaydı birim sınırı olmadan açılırdı.

**Sayı = sızıntı:** liste, KPI sayısı, uyarı sayısı, Excel ve arama AYNI
fonksiyonları kullanır. Tek kayıt yardımcıları liste süzgecinden türetilir ki
ikisi ayrışmasın (`is_erisimi_yok_mu` aynı sorguyu tek satıra uygular).

Yanıt kodları: URL'deki kayıt kapsam dışı → 404 ve yazma yok; gövdedeki
referans (iş, kişi) kapsam dışı → 404; gövdedeki katalog öğesi başka birimin
→ 403 (`katalog_birim_yasak_mi`).

**Şirket ayrımı (KARARLAR 2026-11-04 §1):** bütün kurallar etkin şirketin
birimleriyle KESİŞTİRİLİR (`_sirket_birimleri`). KENDI_BIRIMI/KENDI_ISLERI'de
`kullanici_birimleri` zaten kesişimdir; TUMU kapsamı da yalnız etkin şirketin
birimlerini görür (birimsiz ortak kayıt, ör. ortak depo, eskisi gibi görünür).
Kesişim boşsa fail-closed: liste boş, tek kayıt 404. Şirket kümesi
`services/sirketler.etkin_birimler`'den, MODÜL ÖZNİTELİĞİ olarak okunur (tek
nokta; test altyapısı varsayılan kullanıcılar için oradan süzgeçsiz çalıştırır).
"""

from sqlalchemy import ColumnElement, Select, and_, exists, false, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KullaniciSirketi,
    ServiceOrder,
    ServiceOrderAssignment,
    ServicePlan,
    ServicePlanMember,
    User,
    UserUnit,
)
from app.models.rbac import BIRIM_KODLARI
from app.permissions import (
    SCOPE_ALL,
    SCOPE_OWN_CUSTOMERS,
    SCOPE_OWN_JOBS,
    SCOPE_OWN_UNITS,
    SCOPES,
)
from app.services import sirketler
from app.services.accounts import kendi_hesaplari


def _sirket_birimleri(user: User) -> frozenset[str] | None:
    """Etkin şirketin birimleri; None = şirket süzgeci yok."""
    return sirketler.etkin_birimler(user)


def kullanici_birimleri(user: User) -> frozenset[str]:
    """Kullanıcının üyesi olduğu birimler (`user_units`) ∩ etkin şirketin birimleri."""
    birimler = frozenset(u.birim for u in user.birimler)
    sirket = _sirket_birimleri(user)
    return birimler if sirket is None else birimler & sirket


def gorunur_birimler(user: User) -> list[str]:
    """Kullanıcının seçebileceği/görebileceği birim kodları (katalog sırası).

    TUMU: etkin şirketin bütün birimleri; diğer kapsamlar: kendi birimleri
    (kesişim). Form süzgeçleri ve "hangi birimler" listeleri bunu kullanır.
    """
    if _kapsam(user) == SCOPE_ALL:
        sirket = _sirket_birimleri(user)
        return [b for b in BIRIM_KODLARI if sirket is None or b in sirket]
    if _kapsam(user) is None:
        return []
    birimler = kullanici_birimleri(user)
    return [b for b in BIRIM_KODLARI if b in birimler]


def tum_kayitlar_mi(user: User) -> bool:
    """Kullanıcı HİÇBİR süzgeç olmadan bütün kayıtları mı görüyor?

    TUMU kapsamı artık şirketle sınırlıdır; bu yalnız şirket süzgeci olmayan
    (sahte/sistem) kullanıcıda True'dur. "TUMU ise genel sayıyı göster" türü
    kısayollar buna bakmalı, rol kapsamına değil.
    """
    return _kapsam(user) == SCOPE_ALL and _sirket_birimleri(user) is None


def _kapsam(user: User) -> str | None:
    """Rol kapsamı; katalog dışı dize None döner (→ red)."""
    kapsam = user.role.scope if user.role is not None else None
    return kapsam if kapsam in SCOPES else None


def _birim_kosulu(user: User, sutun, *, birimsiz_gorunur: bool) -> ColumnElement[bool]:
    """TUMU dışı kapsamlar için birim koşulu; birimsiz kullanıcıda daima yanlış."""
    birimler = kullanici_birimleri(user)
    if not birimler:
        return false()
    kosul = sutun.in_(sorted(birimler))
    return or_(sutun.is_(None), kosul) if birimsiz_gorunur else kosul


def _sirket_kosulu(user: User, sutun) -> ColumnElement[bool] | None:
    """TUMU kapsamı için şirket koşulu; None = süzgeç yok.

    Birimsiz kayıt (ortak) TUMU'ya her şirkette görünür — eski TUMU kuralı.
    """
    sirket = _sirket_birimleri(user)
    if sirket is None:
        return None
    if not sirket:
        return sutun.is_(None)
    return or_(sutun.is_(None), sutun.in_(sorted(sirket)))


# --- Birimli varlıklar (ekipman, sözleşme, kiralama, depo, teklif, eğitim) ------


def kapsam_birim(stmt: Select, user: User, sutun, *, birimsiz_gorunur: bool = True) -> Select:
    """Birim kolonu taşıyan servis varlıklarına liste süzgeci.

    `birimsiz_gorunur`: birimi NULL kayıt (ör. ortak depo) birimli kullanıcıya
    görünür mü. Birim kolonu NOT NULL ise etkisizdir. Birimsiz KULLANICI her
    durumda hiçbir şey görmez (fail-closed). TUMU: etkin şirketin birimleri.
    """
    kapsam = _kapsam(user)
    if kapsam == SCOPE_ALL:
        kosul = _sirket_kosulu(user, sutun)
        return stmt if kosul is None else stmt.where(kosul)
    if kapsam is None:
        return stmt.where(false())
    return stmt.where(_birim_kosulu(user, sutun, birimsiz_gorunur=birimsiz_gorunur))


def _sirket_disinda_mi(user: User, birim: str | None) -> bool:
    """TUMU için tek kayıt: birimli kayıt etkin şirketin dışında mı?"""
    sirket = _sirket_birimleri(user)
    if sirket is None or birim is None:
        return False
    return birim not in sirket


def birim_disinda_mi(user: User, birim: str | None, *, birimsiz_gorunur: bool = True) -> bool:
    """Tek kayıt için: bu birim kullanıcının kapsamı dışında mı? (→ 404)

    `kapsam_birim`'in tek kayıt karşılığı; aynı kuralı taşır.
    """
    kapsam = _kapsam(user)
    if kapsam == SCOPE_ALL:
        return _sirket_disinda_mi(user, birim)
    if kapsam is None:
        return True
    birimler = kullanici_birimleri(user)
    if not birimler:
        return True
    if birim is None:
        return not birimsiz_gorunur
    return birim not in birimler


def birim_degisimi_yasak_mi(user: User, eski: str | None, yeni: str | None) -> bool:
    """Kaydın birimi değiştiriliyorsa hedef birim de kullanıcının kapsamında mı?

    Kaydı başka birime taşıyıp kapsamı genişletmek (ya da başka birimin
    kaydını kendine çekmek) engellenir (`api/accounts.py` sahip değişimi
    emsali). True → çağıran 404 döner, hiçbir şey yazmaz.
    """
    if eski == yeni:
        return birim_disinda_mi(user, eski)
    return birim_disinda_mi(user, eski) or birim_disinda_mi(user, yeni, birimsiz_gorunur=False)


def katalog_birim_yasak_mi(user: User, birim: str | None) -> bool:
    """Gövdedeki katalog öğesi (kurs, yetkinlik, arıza nedeni) başka birimin mi?

    True → 403 (kayıt bilinen bir katalog öğesidir; varlığını gizlemenin
    anlamı yok). Birimsiz (ortak) katalog öğesi herkese açıktır.
    """
    kapsam = _kapsam(user)
    if kapsam == SCOPE_ALL:
        return _sirket_disinda_mi(user, birim)
    if kapsam is None:
        return True
    if birim is None:
        return False
    return birim not in kullanici_birimleri(user)


# --- Servis işleri ve bağlıları (plan, zaman, onay, ek, atölye, teklif köprüsü) --


def _kendi_isleri(user: User):
    """Aktif ataması VEYA aktif plan üyeliği olan iş kimlikleri (alt sorgu)."""
    atanan = select(ServiceOrderAssignment.service_order_id).where(
        ServiceOrderAssignment.user_id == user.id,
        ServiceOrderAssignment.removed_at.is_(None),
    )
    planli = (
        select(ServicePlan.service_order_id)
        .join(ServicePlanMember, ServicePlanMember.plan_id == ServicePlan.id)
        .where(
            ServicePlanMember.user_id == user.id,
            ServicePlan.is_active.is_(True),
            ServicePlan.is_deleted.is_(False),
        )
    )
    return atanan.union(planli)


def _is_kosulu(user: User) -> ColumnElement[bool] | None:
    """`service_orders` satırına uygulanacak kapsam koşulu; None = süzgeç yok."""
    kapsam = _kapsam(user)
    sirket = _sirket_birimleri(user)
    if kapsam == SCOPE_ALL:
        if sirket is None:
            return None
        return ServiceOrder.birim.in_(sorted(sirket)) if sirket else false()
    if kapsam is None or not kullanici_birimleri(user):
        return false()
    if kapsam == SCOPE_OWN_UNITS:
        return _birim_kosulu(user, ServiceOrder.birim, birimsiz_gorunur=False)
    if kapsam == SCOPE_OWN_JOBS:
        # Atandığı iş başka birimde olsa da görünür (birimler arası destek) —
        # ama yalnız etkin şirketin birimlerinde (başka şirketin işi o şirket
        # seçiliyken görünür).
        kendi = ServiceOrder.id.in_(_kendi_isleri(user))
        return kendi if sirket is None else and_(kendi, ServiceOrder.birim.in_(sorted(sirket)))
    if kapsam == SCOPE_OWN_CUSTOMERS:
        return and_(
            _birim_kosulu(user, ServiceOrder.birim, birimsiz_gorunur=False),
            or_(
                ServiceOrder.customer_id.is_(None),
                ServiceOrder.customer_id.in_(kendi_hesaplari(user)),
            ),
        )
    return false()  # pragma: no cover - SCOPES dışı değer _kapsam'da elendi


def kapsam_isler(stmt: Select, user: User, so_id_sutunu) -> Select:
    """Servis işine bağlı listelere (iş, plan, zaman, onay ...) kapsam süzgeci.

    `so_id_sutunu`: listedeki iş kimliği kolonu — `ServiceOrder.id` ya da bağlı
    tablonun `service_order_id`'si. Süzgeç alt sorgu ile uygulanır; böylece
    çağıranın JOIN yapısına dokunmaz ve sayım (`sayfala`) bozulmaz.
    """
    kosul = _is_kosulu(user)
    if kosul is None:
        return stmt
    izinli = select(ServiceOrder.id).where(kosul)
    return stmt.where(so_id_sutunu.in_(izinli))


async def is_erisimi_yok_mu(db: AsyncSession, user: User, so: ServiceOrder) -> bool:
    """Tek iş için: kapsam dışı mı? (→ 404, yazma yok)

    Liste koşulunun AYNISI tek satıra uygulanır; iki ayrı kural yazılsaydı
    listede görünmeyen iş kimliğiyle açılabilirdi.
    """
    kosul = _is_kosulu(user)
    if kosul is None:
        return False
    bulunan = await db.scalar(select(ServiceOrder.id).where(ServiceOrder.id == so.id, kosul))
    return bulunan is None


# --- Personel --------------------------------------------------------------------


def sirket_personel_kosulu(user: User, user_id_sutunu) -> ColumnElement[bool] | None:
    """Personelin etkin şirkete göre koşulu; None = süzgeç yok.

    Etkin şirketin bir biriminde üyeliği olan kişi VEYA hiç birimi olmayan ve
    etkin şirketin ÜYESİ olan kişi (`kullanici_sirketleri`). Birimsiz kişi
    eskisi gibi yalnız TUMU'ya görünür; ama artık yalnız üyesi olduğu şirkette
    (rol testi S3/B19): yalnız MOBİLİTE üyesi depo kullanıcısı TELEKOM'un
    personel listesinde görünmez. ADMIN üyelik satırı taşıdığı şirketlerde
    görünür (seed/göç bütün şirketleri yazar).
    """
    sirket = _sirket_birimleri(user)
    if sirket is None:
        return None
    aktif = sirketler.aktif_sirket(user)
    birimsiz = not_(exists().where(UserUnit.user_id == user_id_sutunu))
    if aktif is None:
        return false()
    birimsiz_uye = and_(
        birimsiz,
        exists().where(
            KullaniciSirketi.user_id == user_id_sutunu, KullaniciSirketi.sirket_kod == aktif
        ),
    )
    if not sirket:
        return birimsiz_uye
    return or_(
        exists().where(UserUnit.user_id == user_id_sutunu, UserUnit.birim.in_(sorted(sirket))),
        birimsiz_uye,
    )


def _personel_kosulu(user: User, user_id_sutunu) -> ColumnElement[bool] | None:
    kapsam = _kapsam(user)
    if kapsam == SCOPE_ALL:
        return sirket_personel_kosulu(user, user_id_sutunu)
    birimler = kullanici_birimleri(user)
    if kapsam is None or not birimler:
        return false()
    return exists().where(
        UserUnit.user_id == user_id_sutunu,
        UserUnit.birim.in_(sorted(birimler)),
    )


def kapsam_personel(stmt: Select, user: User, user_id_sutunu) -> Select:
    """Personel listesine kapsam süzgeci: ortak birimi olan kişiler.

    Birimsiz personel yalnız TUMU kapsamına görünür (tablo). Ek birimler
    dikkate alınır: Mobilite + Araç Takip üyesi kişi iki birimin şefine de
    görünür.
    """
    kosul = _personel_kosulu(user, user_id_sutunu)
    return stmt if kosul is None else stmt.where(kosul)


async def personel_disinda_mi(db: AsyncSession, user: User, user_id: int) -> bool:
    """Tek kişi için: kapsam dışı mı? (→ 404). Liste koşulunun aynısı."""
    kosul = _personel_kosulu(user, User.id)
    if kosul is None:
        return False
    bulunan = await db.scalar(select(User.id).where(User.id == user_id, kosul))
    return bulunan is None
