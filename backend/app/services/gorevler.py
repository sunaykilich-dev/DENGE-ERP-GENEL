"""Görev kartının ERP kaydına bağlantısı.

Bağlantı polimorfik (`entity` + `entity_id`). Bu dosya tek kayıt noktası:
hangi kayıt tiplerine bağlanılabilir, kartta nasıl yazılır, arayüzde hangi
adrese gider. Üçü ayrı yerlerde dursaydı yeni bir tip eklemek üç dosyayı
birden doğru değiştirmeyi gerektirirdi — biri unutulunca kart tıklanamaz ya
da etiketsiz görünürdü.

**Kaynak kayıt silinmiş olabilir.** Polimorfik bağlantıda veritabanı
bütünlüğü zorlamaz; bu yüzden etiket çözülürken kaydın varlığı kontrol edilir
ve yoksa kart bunu açıkça söyler. Sessizce boş bir etiket göstermek,
"bağlantı yok" ile "bağlantı kırık"ı aynı şeye çevirirdi.

**Şirket ayrımı ve kayıt kapsamı (rol testi S1, KARARLAR 2026-11-04 §6.1).**
Pano etkin şirkete aittir (`boards.sirket_kod`); bağlı kaydın etiketi (iş no,
plaka, MSISDN, IMEI ...) yalnız o kaydı GÖREBİLENE döner. Görmeyen kişi kartı
"erişim yok" etiketiyle, tıklanamaz görür. Karta kayıt bağlamak da aynı
kurala tabidir: göremediğin kaydı karta bağlayamazsın (404) — aksi halde id
sayarak başka şirketin ya da mobilitenin kayıt numarası okunabiliyordu.
"""

from dataclasses import dataclass

from sqlalchemy import ColumnElement, false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    Board,
    Device,
    MaintenanceContract,
    Order,
    PartnerSettlement,
    Quote,
    Rental,
    RmaCase,
    ServiceEquipment,
    ServiceOrder,
    SimCard,
    TrainingCorrectiveAction,
    User,
    Vehicle,
    WorkOrder,
    WorkshopRecord,
)
from app.permissions import SCOPE_OWN_CUSTOMERS
from app.services import sirketler


@dataclass(frozen=True)
class KayitTipi:
    kod: str
    ad: str
    model: type
    # Kartta görünen kısa etiket; ilk dolu alan kullanılır.
    alanlar: tuple[str, ...]
    # Arayüz adresi; `{id}` kaydın kimliğiyle değişir.
    yol: str
    # Kaydı görmek için gereken izin (kayıt ekranının okuma izni).
    izin: str


# `yol` arayüzün GERÇEK rotasıdır (bkz. `frontend/src/main.tsx`). Kimliğe
# göre derin bağlantısı olmayan ekranlar liste sayfasına gider — yanlış bir
# adres üretip 404'e düşürmektense listeye götürmek yeğdir.
KAYIT_TIPLERI: tuple[KayitTipi, ...] = (
    KayitTipi("isemri", "İş Emri", WorkOrder, ("wo_no",), "/is-emirleri", "isemri.gor"),
    KayitTipi("teklif", "Teklif", Quote, ("quote_no",), "/teklifler", "teklif.gor"),
    KayitTipi("siparis", "Sipariş", Order, ("order_no",), "/siparisler", "siparis.gor"),
    KayitTipi("rma", "RMA", RmaCase, ("rma_no",), "/rma", "rma.gor"),
    KayitTipi("hesap", "Hesap", Account, ("title",), "/hesaplar/{id}", "hesap.gor"),
    KayitTipi("cihaz", "Cihaz", Device, ("imei", "serial_no"), "/cihazlar/{etiket}", "cihaz.gor"),
    KayitTipi("arac", "Araç", Vehicle, ("plate",), "/araclar/{id}", "arac.gor"),
    KayitTipi("hat", "Hat (SIM)", SimCard, ("msisdn", "iccid"), "/hatlar/{id}", "hat.gor"),
    KayitTipi(
        "hakedis", "Hak Ediş Dökümü", PartnerSettlement, ("period",), "/hakedis", "hakedis.gor"
    ),
    # --- Teknik servis (plan §1.11) -------------------------------------------
    # Etiket yalnız kaydı görebilene döner (`kayda_erisebilir_mi`); yine de
    # etiket alanı KİŞİSEL VERİ ya da müşteri adı taşımaz: yalnız belge
    # numarası. Ekipmanın seri numarası bile yazılmaz (müşteri malı kütüğü):
    # alan listesi boş, kart "Ekipman #id" görünür.
    KayitTipi(
        "servis_isi", "Servis İşi", ServiceOrder, ("so_no",), "/servis-isleri/{id}", "servis.gor"
    ),
    KayitTipi("ekipman", "Ekipman", ServiceEquipment, (), "/servis-ekipman/{id}", "ekipman.gor"),
    KayitTipi(
        "bakim_sozlesme",
        "Bakım Sözleşmesi",
        MaintenanceContract,
        ("contract_no",),
        "/bakim?sozlesme={id}",
        "bakim.gor",
    ),
    # --- Dalga 2 (TS-091, TS-110, TS-155, TS-165) ------------------------------
    KayitTipi(
        "atolye", "Atölye Kaydı", WorkshopRecord, ("atolye_no",), "/atolye/{id}", "atolye.gor"
    ),
    KayitTipi("kiralama", "Kiralama", Rental, ("rental_no",), "/kiralamalar/{id}", "kiralama.gor"),
    # Düzeltici faaliyet kişisel performans kaydıdır: etiket kişi adı ya da
    # gözlem notu taşımaz, kart "#id" görünür; adres eğitim ekranının listesi.
    KayitTipi(
        "egitim_faaliyet",
        "Düzeltici Faaliyet",
        TrainingCorrectiveAction,
        (),
        "/egitim",
        "egitim.gor",
    ),
    # Personel kartı adı da taşımaz; "#id" + kart adresi.
    KayitTipi("personel", "Personel", User, (), "/personel/{id}", "personel.gor"),
)

_TIPE_GORE = {t.kod: t for t in KAYIT_TIPLERI}

# Canlı mobilite modülünün kayıtları: yalnız etkin şirket DENGE MOBİLİTE iken
# görünür (KARARLAR 2026-11-04 §1; `api/deps.mobilite_sirketi_gerekli` ile aynı).
MOBILITE_TIPLERI = frozenset({"isemri", "siparis", "rma", "cihaz", "arac", "hat", "hakedis"})


def tip(kod: str) -> KayitTipi | None:
    return _TIPE_GORE.get(kod)


# --- Pano şirket kapısı ----------------------------------------------------------


def pano_sirket_kosulu(user: User) -> ColumnElement[bool] | None:
    """Panonun etkin şirkete ait olma koşulu; None = süzgeç yok.

    Süzgeçsiz sahte kullanıcı (`sirketler.etkin_birimler` None) dışında pano
    yalnız `boards.sirket_kod == etkin şirket` iken görünür. Etkin şirketi
    olmayan kullanıcı hiçbir pano görmez (fail-closed).
    """
    if sirketler.etkin_birimler(user) is None:
        return None
    aktif = sirketler.aktif_sirket(user)
    if aktif is None:
        return false()
    return Board.sirket_kod == aktif


def pano_gorunur_mu(user: User, pano: Board) -> bool:
    """`pano_sirket_kosulu`'nun tek kayıt karşılığı (aynı kural)."""
    if sirketler.etkin_birimler(user) is None:
        return True
    aktif = sirketler.aktif_sirket(user)
    return aktif is not None and pano.sirket_kod == aktif


# --- Bağlı kaydın kapsamı ----------------------------------------------------------


async def kayda_erisebilir_mi(db: AsyncSession, user: User, kod: str, kayit) -> bool:
    """Kullanıcı bu kaydı kendi ekranında görebilir mi? (etiket ve bağlama kapısı)

    Kayıt uçlarının tek kayıt kuralının AYNISI: okuma izni + şirket/birim
    kapsamı (teknik servis `kapsam.py`), mobilite tiplerinde şirket kapısı ve
    müşteri kapsamı (`accounts.kapsam_disinda_mi`), teklifte teklif kapsamı.
    """
    from app.services import accounts, quotes
    from app.services.teknik_servis import kapsam

    kt = _TIPE_GORE.get(kod)
    if kt is None or not user.has(kt.izin):
        return False
    if kod in MOBILITE_TIPLERI:
        if not sirketler.mobilite_acik_mi(user):
            return False
        if user.role is not None and user.role.scope == SCOPE_OWN_CUSTOMERS:
            musteri = getattr(kayit, "customer_id", None) or getattr(kayit, "account_id", None)
            return not await accounts.kapsam_disinda_mi(db, user, musteri)
        return True
    if kod == "teklif":
        return not await quotes.teklif_erisimi_yok_mu(db, user, kayit)
    if kod == "hesap":
        return not await accounts.kapsam_disinda_mi(db, user, kayit.id)
    if kod == "servis_isi":
        return not kayit.is_deleted and not await kapsam.is_erisimi_yok_mu(db, user, kayit)
    if kod == "atolye":
        so = await db.get(ServiceOrder, kayit.service_order_id)
        return (
            so is not None
            and not so.is_deleted
            and not await kapsam.is_erisimi_yok_mu(db, user, so)
        )
    if kod in ("ekipman", "bakim_sozlesme", "kiralama"):
        return not kapsam.birim_disinda_mi(user, kayit.birim)
    if kod == "egitim_faaliyet":
        return not await kapsam.personel_disinda_mi(db, user, kayit.user_id)
    if kod == "personel":
        return not await kapsam.personel_disinda_mi(db, user, kayit.id)
    return False  # pragma: no cover - katalogdaki her tip yukarıda ele alındı


async def baglanti_erisimi_var_mi(db: AsyncSession, user: User, kod: str, kimlik: int) -> bool:
    """Karta bağlanacak kayıt var VE kullanıcı onu görebiliyor mu? (değilse 404)"""
    kt = _TIPE_GORE.get(kod)
    if kt is None:
        return False
    kayit = await db.get(kt.model, kimlik)
    return kayit is not None and await kayda_erisebilir_mi(db, user, kod, kayit)


async def baglanti_cozumle(
    db: AsyncSession, ciftler: set[tuple[str, int]], user: User
) -> dict[tuple[str, int], dict[str, str | bool]]:
    """(entity, entity_id) çiftlerini etiket + adrese çevirir.

    Kart listesi başına TEK sorgu düşsün diye tip bazında toplu okur; kart
    başına sorgu, elli kartlık bir panoda elli gidiş geliş demekti.

    Etiket ve adres yalnız kaydı görebilene döner; göremeyen "erişim yok"
    görür (kayıt numarası, plaka, MSISDN sızmaz).
    """
    sonuc: dict[tuple[str, int], dict[str, str | bool]] = {}
    tipe_gore: dict[str, set[int]] = {}
    for kod, kimlik in ciftler:
        tipe_gore.setdefault(kod, set()).add(kimlik)

    for kod, kimlikler in tipe_gore.items():
        kt = _TIPE_GORE.get(kod)
        if kt is None:
            # Katalogdan çıkarılmış tip: kartı kaybetme, durumu söyle.
            for kimlik in kimlikler:
                sonuc[(kod, kimlik)] = {"ad": kod, "etiket": "—", "yol": "", "var": False}
            continue
        kayitlar = (await db.scalars(select(kt.model).where(kt.model.id.in_(kimlikler)))).all()
        bulunan = {k.id: k for k in kayitlar}
        for kimlik in kimlikler:
            kayit = bulunan.get(kimlik)
            if kayit is None:
                sonuc[(kod, kimlik)] = {
                    "ad": kt.ad,
                    "etiket": "kaynak kayıt silinmiş",
                    "yol": "",
                    "var": False,
                }
                continue
            if not await kayda_erisebilir_mi(db, user, kod, kayit):
                sonuc[(kod, kimlik)] = {
                    "ad": kt.ad,
                    "etiket": "erişim yok",
                    "yol": "",
                    "var": False,
                }
                continue
            etiket = next(
                (str(d) for a in kt.alanlar if (d := getattr(kayit, a, None))), f"#{kimlik}"
            )
            sonuc[(kod, kimlik)] = {
                "ad": kt.ad,
                "etiket": etiket,
                "yol": kt.yol.format(id=kimlik, etiket=etiket),
                "var": True,
            }
    return sonuc
