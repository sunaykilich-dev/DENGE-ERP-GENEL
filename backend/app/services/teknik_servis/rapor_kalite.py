"""Veri Kalitesi sayfasının servis + ana veri kontrolleri (E12-16, E14-18).

Maddeler: TS-188. Doldurur: D3-C (iskelet D3-S).

**Salt okuma.** Sayfa hiçbir veriyi düzeltmez; satırdaki iş no, hesap ya da
sözleşme kendi ekranına bağlanır. Düzeltme (eşleştirme, birleştirme,
doğrulama) kendi yetkili akışındadır.

**Sayı = liste.** Her kontrolün sayısı, tıklanınca açılan listenin toplamıdır:
ikisi de `listele()`'den geçer (SQL kontrolünde aynı `Select`, Python
kontrolünde aynı liste). Kapsam her kontrolde AYNI yardımcılarla (servis işi
`kapsam_isler`, hesap `kapsam_uygula`, tesis `kapsam_musteri`, sözleşme
`bakim.sozlesme_kapsami`) uygulanır: sayı da bir okuma yoludur.

**Tanımlar** (kontrol B7–B9 düzeltmeleriyle):
- `tanimsiz_durum` göç KARANTİNASINDAN gelir: `servis_isleri` profiliyle
  yüklenmiş ama hatası olduğu için aktarılamayan satırlar (birim/tür/durum
  eşlenemedi). Servis işi tablosunda tanımsız durum yoktur (CHECK).
- `sure_kaydi_eksik` E09 tanımıdır (`zaman.sure_eksik_ifadesi`, EKSIK ∪
  KISMI); telefon/uzaktan çözülen iş eksik sayılmaz, tahmini süre kullanılmaz.
- `seri_eksik`: `TUR_KURALLARI.seri_zorunlu` türleri (PB, ATOLYE) + ekipmansız
  tek cihazlı ARIZA/PLANSIZ_BAKIM ("seri bekleniyor", rol testi B6).
- Müşteri varyantı `unvan_anahtari` ile KAPSAM İÇİ hesaplarda gruplanır
  (canlı `mukerrer_adaylari` tek hesap içindir ve kapsamsızdır — B9).
- Ekipman kontrolleri `ekipman.kalite_ozeti`'ndedir (E03-13); bu sayfa onları
  gösterir ve listeyi Ekipman Kütüğü'nde açar (`?kalite=`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, exists, func, not_, or_, select
from sqlalchemy.orm import aliased

from app.models import (
    Account,
    Address,
    ImportBatch,
    MaintenanceContract,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderSerial,
)
from app.models.teknik_servis import DURUM_GRUPLARI
from app.services import accounts as hesap_svc
from app.services.teknik_servis import ana_veri, kapsam

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

KARANTINA_PROFILI = "servis_isleri"

GRUPLAR = {
    "servis": "Servis işleri",
    "ana_veri": "Müşteri ve tesis",
    "sozlesme": "Bakım sözleşmeleri",
    "ekipman": "Ekipman kütüğü",
}


@dataclass(frozen=True)
class KaliteKontrolu:
    kod: str
    baslik: str
    tanim: str
    grup: str
    izinler: tuple[str, ...]
    # Excel/ekran sütunları: (başlık, satır anahtarı, export tipi).
    sutunlar: tuple[tuple[str, str, str], ...]
    sorgu: Callable[[User], Select] | None = None
    satirlar: Callable[[AsyncSession, User], Awaitable[list[dict[str, Any]]]] | None = None
    donustur: Callable[[AsyncSession, list], Awaitable[list[dict[str, Any]]]] | None = None


# --- Servis işi kontrolleri ----------------------------------------------------------

_IS_SUTUNLARI = (
    ("İş No", "so_no", "metin"),
    ("Birim", "birim", "metin"),
    ("Tür", "tur", "metin"),
    ("Durum", "durum", "metin"),
    ("Müşteri", "musteri", "metin"),
    ("Lokasyon", "lokasyon", "metin"),
    ("Açılış", "acilis", "zaman"),
)


def _is_taban(user: User) -> Select:
    stmt = select(ServiceOrder).where(ServiceOrder.is_deleted.is_(False))
    return kapsam.kapsam_isler(stmt, user, ServiceOrder.id)


def _cozulmus() -> Any:
    return ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["COZULDU"]))


def _s_cozum_zamani_eksik(user: User) -> Select:
    return _is_taban(user).where(
        _cozulmus(),
        or_(ServiceOrder.completed_at.is_(None), ServiceOrder.first_completed_at.is_(None)),
    )


def _s_sure_kaydi_eksik(user: User) -> Select:
    from app.services.teknik_servis import zaman

    return _is_taban(user).where(_cozulmus(), zaman.sure_eksik_ifadesi())


def _seri_zorunlu_turler() -> list[str]:
    from app.services.teknik_servis.is_emirleri import TUR_KURALLARI

    return sorted(t for t, k in TUR_KURALLARI.items() if k.seri_zorunlu)


# Tek cihazlı bakım/arıza işleri (1 cihaz = 1 iş): seri açılışta zorunlu değil
# ("seri bekleniyor", §7.5) ama kalite listesinde görünmeli (rol testi B6).
TEK_CIHAZLI_SERI_TURLERI = ("ARIZA", "PLANSIZ_BAKIM")


def _s_seri_eksik(user: User) -> Select:
    seri_yok = not_(
        exists().where(
            ServiceOrderSerial.service_order_id == ServiceOrder.id,
            ServiceOrderSerial.is_active.is_(True),
        )
    )
    return _is_taban(user).where(
        ServiceOrder.status != "IPTAL",
        seri_yok,
        or_(
            ServiceOrder.tur.in_(_seri_zorunlu_turler()),
            # Ekipmana bağlı iş cihazını kütükten bilir; yalnız ekipmansız olan eksik.
            and_(
                ServiceOrder.tur.in_(TEK_CIHAZLI_SERI_TURLERI),
                ServiceOrder.equipment_id.is_(None),
            ),
        ),
    )


def _s_lokasyonsuz_is(user: User) -> Select:
    return _is_taban(user).where(ServiceOrder.address_id.is_(None), ServiceOrder.status != "IPTAL")


def _s_musterisiz_is(user: User) -> Select:
    return _is_taban(user).where(ServiceOrder.customer_id.is_(None), ServiceOrder.status != "IPTAL")


def _s_sef_atanmamis(user: User) -> Select:
    return _is_taban(user).where(
        ServiceOrder.status.in_(sorted(DURUM_GRUPLARI["ACIK"])),
        not_(
            exists().where(
                ServiceOrderAssignment.service_order_id == ServiceOrder.id,
                ServiceOrderAssignment.rol == "SEF",
                ServiceOrderAssignment.removed_at.is_(None),
            )
        ),
    )


def _s_sla_olculemedi(user: User) -> Select:
    return _is_taban(user).where(ServiceOrder.sla_sonuc == "OLCULEMEDI")


def _s_kutukte_olmayan_seri(user: User) -> Select:
    from app.services.teknik_servis import is_emirleri

    return _is_taban(user).where(is_emirleri.kutukte_olmayan_seri_kosulu())


async def _is_satirlari(db: AsyncSession, kayitlar: list) -> list[dict[str, Any]]:
    from app.services.teknik_servis import is_emirleri

    isler = [r[0] if isinstance(r, tuple) or hasattr(r, "_mapping") else r for r in kayitlar]
    musteriler = await is_emirleri.musteri_ozetleri(
        db, {s.customer_id for s in isler if s.customer_id}
    )
    lokasyonlar = await is_emirleri.lokasyon_ozetleri(
        db, {s.address_id for s in isler if s.address_id}
    )
    return [
        {
            "id": s.id,
            "so_no": s.so_no,
            "birim": s.birim,
            "tur": s.tur,
            "durum": s.status,
            "musteri": (musteriler.get(s.customer_id) or {}).get("title") or s.customer_name_raw,
            "lokasyon": (lokasyonlar.get(s.address_id) or {}).get("ad") or s.location_raw,
            "acilis": s.created_at,
            "yol": f"/servis-isleri/{s.id}",
        }
        for s in isler
    ]


async def _karantina_satirlari(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Göç karantinası: `servis_isleri` profilinde bekleyen (HAZIR) partilerin
    HATALI satırları. Satırın birimi kapsam dışındaysa (ya da tanınmıyorsa ve
    kullanıcı TUMU değilse) görünmez — fail-closed."""
    partiler = (
        await db.scalars(
            select(ImportBatch)
            .where(ImportBatch.profile == KARANTINA_PROFILI, ImportBatch.status == "HAZIR")
            .order_by(ImportBatch.id)
        )
    ).all()
    sonuc: list[dict[str, Any]] = []
    for p in partiler:
        for s in p.staged_rows or []:
            if not s.get("hatalar"):
                continue
            ham = s.get("ham") or {}
            birim = (str(ham.get("birim") or "")).strip().upper() or None
            if kapsam.birim_disinda_mi(user, birim, birimsiz_gorunur=False):
                continue
            sonuc.append(
                {
                    "id": f"{p.id}-{s.get('satir_no')}",
                    "parti_id": p.id,
                    "dosya": p.filename,
                    "satir_no": s.get("satir_no"),
                    "ref": ham.get("ref"),
                    "birim": birim,
                    "durum": ham.get("durum"),
                    "hatalar": "; ".join(str(h) for h in s["hatalar"]),
                    "yol": "/ice-aktarma",
                }
            )
    return sonuc


# --- Ana veri kontrolleri ------------------------------------------------------------


def _s_dogrulanmamis_musteri(user: User) -> Select:
    stmt = select(Account).where(
        Account.is_deleted.is_(False),
        Account.is_musteri.is_(True),
        Account.is_verified.is_(False),
    )
    return hesap_svc.kapsam_uygula(stmt, user)


async def _hesap_satirlari(db: AsyncSession, kayitlar: list) -> list[dict[str, Any]]:
    hesaplar = [r[0] if hasattr(r, "_mapping") else r for r in kayitlar]
    return [
        {
            "id": h.id,
            "unvan": h.title,
            "il": h.region,
            "acilis": h.created_at,
            "yol": f"/hesaplar/{h.id}",
        }
        for h in hesaplar
    ]


def _s_dogrulanmamis_tesis(user: User) -> Select:
    stmt = (
        select(Address, Account.title)
        .join(Account, Account.id == Address.account_id)
        .where(
            Account.is_deleted.is_(False),
            Address.kind == "TESIS",
            Address.is_active.is_(True),
            Address.is_verified.is_(False),
        )
    )
    return hesap_svc.kapsam_musteri(stmt, user, Address.account_id)


async def _tesis_satirlari(db: AsyncSession, kayitlar: list) -> list[dict[str, Any]]:
    return [
        {
            "id": a.id,
            "unvan": unvan,
            "tesis": a.site_name,
            "il": a.city,
            "acilis": a.created_at,
            "yol": f"/hesaplar/{a.account_id}",
        }
        for a, unvan in kayitlar
    ]


async def _kapsamli_hesaplar(db: AsyncSession, user: User) -> list[Account]:
    stmt = select(Account).where(Account.is_deleted.is_(False), Account.is_musteri.is_(True))
    return list((await db.scalars(hesap_svc.kapsam_uygula(stmt, user).order_by(Account.id))).all())


def _grup_satirlari(gruplar: dict[str, list[Account]], etiket: str) -> list[dict[str, Any]]:
    sonuc = []
    for anahtar in sorted(gruplar):
        uyeler = gruplar[anahtar]
        if len(uyeler) < 2:
            continue
        sonuc.append(
            {
                "id": anahtar,
                etiket: anahtar,
                "adet": len(uyeler),
                "hesaplar": ", ".join(f"#{h.id} {h.title}" for h in uyeler),
                "hesap_idleri": [h.id for h in uyeler],
                "yol": f"/hesaplar/{uyeler[0].id}",
            }
        )
    return sonuc


async def _mukerrer_unvan(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    gruplar: dict[str, list[Account]] = defaultdict(list)
    for h in await _kapsamli_hesaplar(db, user):
        anahtar = ana_veri.unvan_anahtari(h.title)
        if anahtar:
            gruplar[anahtar].append(h)
    return _grup_satirlari(gruplar, "anahtar")


async def _mukerrer_vkn(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    gruplar: dict[str, list[Account]] = defaultdict(list)
    for h in await _kapsamli_hesaplar(db, user):
        if h.tax_no and h.is_active:
            gruplar[h.tax_no].append(h)
    # VKN değeri satırda yalnız `hesap.gor` sahibine gider (kontrolün izni).
    return _grup_satirlari(gruplar, "vkn")


# --- Sözleşme kontrolleri --------------------------------------------------------------


def _sozlesme_taban(user: User) -> Select:
    from app.services.teknik_servis import bakim

    stmt = select(MaintenanceContract).where(MaintenanceContract.is_deleted.is_(False))
    return bakim.sozlesme_kapsami(stmt, user)


def _s_eslesmemis_sozlesme(user: User) -> Select:
    return _sozlesme_taban(user).where(
        MaintenanceContract.status != "PASIF",
        or_(MaintenanceContract.account_id.is_(None), MaintenanceContract.address_id.is_(None)),
    )


def _s_cakisan_sozlesme(user: User) -> Select:
    """Aynı tesiste (ve birimde) dönemi kesişen AKTİF sözleşmeler; dönemi
    bilinmeyen (tarihsiz/teyit bekleyen) sözleşmede aynı tesiste ikinci aktif
    ya da teyit bekleyen sözleşme (E14-11 mükerrer listesi). Otomatik
    pasifleme yok — liste düzeltme içindir."""
    diger = aliased(MaintenanceContract)
    tarihli = and_(
        MaintenanceContract.status == "AKTIF",
        MaintenanceContract.valid_from.is_not(None),
        MaintenanceContract.valid_to.is_not(None),
        exists().where(
            diger.id != MaintenanceContract.id,
            diger.address_id == MaintenanceContract.address_id,
            diger.birim == MaintenanceContract.birim,
            diger.status == "AKTIF",
            diger.is_deleted.is_(False),
            diger.valid_from < MaintenanceContract.valid_to,
            diger.valid_to > MaintenanceContract.valid_from,
        ),
    )
    tarihsiz = and_(
        MaintenanceContract.status.in_(("AKTIF", "TEYIT_BEKLIYOR")),
        or_(MaintenanceContract.valid_from.is_(None), MaintenanceContract.valid_to.is_(None)),
        exists().where(
            diger.id != MaintenanceContract.id,
            diger.address_id == MaintenanceContract.address_id,
            diger.birim == MaintenanceContract.birim,
            diger.status.in_(("AKTIF", "TEYIT_BEKLIYOR")),
            diger.is_deleted.is_(False),
        ),
    )
    return _sozlesme_taban(user).where(
        MaintenanceContract.address_id.is_not(None), or_(tarihli, tarihsiz)
    )


async def _sozlesme_satirlari(db: AsyncSession, kayitlar: list) -> list[dict[str, Any]]:
    sozlesmeler = [r[0] if hasattr(r, "_mapping") else r for r in kayitlar]
    hesaplar = {}
    adresler = {}
    hesap_idleri = {s.account_id for s in sozlesmeler if s.account_id}
    adres_idleri = {s.address_id for s in sozlesmeler if s.address_id}
    if hesap_idleri:
        hesaplar = dict(
            (
                await db.execute(
                    select(Account.id, Account.title).where(Account.id.in_(hesap_idleri))
                )
            )
            .tuples()
            .all()
        )
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
    return [
        {
            "id": s.id,
            "sozlesme_no": s.contract_no,
            "birim": s.birim,
            "durum": s.status,
            "cari": hesaplar.get(s.account_id) or s.customer_name_raw,
            "tesis": adresler.get(s.address_id) or s.site_name_raw,
            "donem": ana_veri.donem_metni(s.valid_from, s.valid_to),
            "yol": f"/bakim?sozlesme={s.id}",
        }
        for s in sozlesmeler
    ]


_SERVIS = ("servis.gor", "servis_rapor.gor")
_ANA = ("hesap.gor", "servis_rapor.gor")
_SOZ = ("bakim.gor", "servis_rapor.gor")
_HESAP_SUTUNLARI = (
    ("Hesap Id", "id", "tamsayi"),
    ("Unvan", "unvan", "metin"),
    ("İl", "il", "metin"),
    ("Açılış", "acilis", "zaman"),
)
_SOZ_SUTUNLARI = (
    ("Sözleşme No", "sozlesme_no", "metin"),
    ("Birim", "birim", "metin"),
    ("Durum", "durum", "metin"),
    ("Cari", "cari", "metin"),
    ("Tesis", "tesis", "metin"),
    ("Dönem", "donem", "metin"),
)

KONTROLLER: dict[str, KaliteKontrolu] = {
    k.kod: k
    for k in (
        KaliteKontrolu("tanimsiz_durum", "Tanımsız (göç karantinası)", "Göçte birimi/türü/durumu eşlenemediği için aktarılamayan, İçe Aktarma'da bekleyen servis işi satırları.", "servis", _SERVIS, (("Parti", "parti_id", "tamsayi"), ("Dosya", "dosya", "metin"), ("Satır", "satir_no", "tamsayi"), ("Kaynak Ref", "ref", "metin"), ("Birim", "birim", "metin"), ("Durum", "durum", "metin"), ("Hatalar", "hatalar", "metin")), satirlar=_karantina_satirlari),  # noqa: E501
        KaliteKontrolu("cozum_zamani_eksik", "Çözüm zamanı eksik", "Çözüldü grubunda (Tamamlandı/Kapatıldı) ama tamamlanma ya da ilk çözüm anı boş işler.", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_cozum_zamani_eksik, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("sure_kaydi_eksik", "Süre kaydı eksik", "Çözülmüş ve süre kaydı hiç olmayan ya da bir teknisyeninin kaydı eksik işler (telefon/uzaktan çözülen hariç; tahmini süre kullanılmaz).", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_sure_kaydi_eksik, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("seri_eksik", "Seri no eksik", "Seri zorunlu türde (PB, atölye) ya da ekipmansız tek cihazlı bakım/arıza işinde aktif seri kaydı olmayan, iptal edilmemiş işler.", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_seri_eksik, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("lokasyonsuz_is", "Lokasyonsuz iş", "Tesise (lokasyona) bağlanmamış, iptal edilmemiş işler.", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_lokasyonsuz_is, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("musterisiz_is", "Müşterisi eşleşmemiş iş", "Müşteri hesabı boş (göçten ham metinle gelmiş), iptal edilmemiş işler.", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_musterisiz_is, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("sef_atanmamis", "Şef tayin edilmemiş", "Açık olup aktif şef tayini olmayan işler.", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_sef_atanmamis, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("sla_olculemedi", "SLA ölçülemedi", "SLA sonucu ÖLÇÜLEMEDİ olan işler (uyum paydasında yok).", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_sla_olculemedi, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("kutukte_olmayan_seri", "Cihaz kütüğünde olmayan seri", "Mobilite/Araç Takip işinde IMEI/seri no cihaz kütüğünde bulunamayan işler (kayıt engellenmez).", "servis", _SERVIS, _IS_SUTUNLARI, sorgu=_s_kutukte_olmayan_seri, donustur=_is_satirlari),  # noqa: E501
        KaliteKontrolu("dogrulanmamis_musteri", "Doğrulanmamış müşteri", "Servis ekranından hızlı açılmış, henüz doğrulanmamış müşteri hesapları.", "ana_veri", _ANA, _HESAP_SUTUNLARI, sorgu=_s_dogrulanmamis_musteri, donustur=_hesap_satirlari),  # noqa: E501
        KaliteKontrolu("dogrulanmamis_tesis", "Doğrulanmamış tesis", "Hızlı eklenmiş, henüz doğrulanmamış aktif tesisler.", "ana_veri", _ANA, (("Tesis Id", "id", "tamsayi"), ("Müşteri", "unvan", "metin"), ("Tesis", "tesis", "metin"), ("İl", "il", "metin"), ("Açılış", "acilis", "zaman")), sorgu=_s_dogrulanmamis_tesis, donustur=_tesis_satirlari),  # noqa: E501
        KaliteKontrolu("mukerrer_unvan", "Mükerrer unvan grubu", "Ek/noktalama farkı dışında aynı unvanı taşıyan müşteri grupları (aday; karar insanın).", "ana_veri", _ANA, (("Unvan Anahtarı", "anahtar", "metin"), ("Adet", "adet", "tamsayi"), ("Hesaplar", "hesaplar", "metin")), satirlar=_mukerrer_unvan),  # noqa: E501
        KaliteKontrolu("mukerrer_vkn", "Aynı VKN'li hesap grubu", "Aynı vergi numarasını taşıyan aktif müşteri grupları (şube/bayi meşru olabilir).", "ana_veri", _ANA, (("VKN", "vkn", "metin"), ("Adet", "adet", "tamsayi"), ("Hesaplar", "hesaplar", "metin")), satirlar=_mukerrer_vkn),  # noqa: E501
        KaliteKontrolu("eslesmemis_sozlesme", "Eşleşmemiş sözleşme", "Cari hesabı ya da tesisi boş, pasif olmayan bakım sözleşmeleri.", "sozlesme", _SOZ, _SOZ_SUTUNLARI, sorgu=_s_eslesmemis_sozlesme, donustur=_sozlesme_satirlari),  # noqa: E501
        KaliteKontrolu("cakisan_sozlesme", "Aynı tesiste çakışan sözleşme", "Aynı tesis ve birimde dönemi kesişen aktif sözleşmeler; dönemi bilinmiyorsa aynı tesiste ikinci aktif/teyit bekleyen sözleşme.", "sozlesme", _SOZ, _SOZ_SUTUNLARI, sorgu=_s_cakisan_sozlesme, donustur=_sozlesme_satirlari),  # noqa: E501
    )
}  # fmt: skip


class KaliteHatasi(LookupError):
    """Bilinmeyen kontrol kodu (400)."""


def gorebilir_mi(user: User, kontrol: KaliteKontrolu) -> bool:
    return all(user.has(i) for i in kontrol.izinler)


def kontrol_getir(kod: str) -> KaliteKontrolu:
    try:
        return KONTROLLER[kod]
    except KeyError as exc:
        raise KaliteHatasi(f"Bilinmeyen kontrol: {kod}") from exc


async def _say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


async def listele(
    db: AsyncSession,
    user: User,
    kod: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """(toplam, satırlar). Toplam = ekrandaki kutu sayısı (aynı sorgu/liste)."""
    k = kontrol_getir(kod)
    if k.sorgu is not None:
        stmt = k.sorgu(user)
        toplam = await _say(db, stmt)
        ana = stmt.column_descriptions[0]["entity"]
        sayfa = stmt.order_by(ana.id.desc())
        if limit is not None:
            sayfa = sayfa.limit(limit).offset(offset)
        kayitlar = list((await db.execute(sayfa)).all())
        if k.donustur is not None and kayitlar and len(kayitlar[0]) == 1:
            kayitlar = [r[0] for r in kayitlar]
        return toplam, await k.donustur(db, kayitlar) if k.donustur else []
    tum = await k.satirlar(db, user)  # type: ignore[misc]
    son = len(tum) if limit is None else offset + limit
    return len(tum), tum[offset:son]


async def ozet(db: AsyncSession, user: User, clock: Clock) -> list[dict[str, Any]]:
    """Kullanıcının görebildiği kontrollerin sayıları + ekipman kontrolleri.

    Servis grubunda `oran` (eşleşmiş iş oranı) için payda = kapsamdaki iptal
    edilmemiş iş sayısı verilir; oran ekranda hesaplanır.
    """
    sonuc: list[dict[str, Any]] = []
    for k in KONTROLLER.values():
        if not gorebilir_mi(user, k):
            continue
        toplam, _ = await listele(db, user, k.kod, limit=0)
        sonuc.append(
            {
                "kod": k.kod,
                "baslik": k.baslik,
                "tanim": k.tanim,
                "grup": k.grup,
                "deger": toplam,
                "hedef": None,
            }
        )
    if user.has("ekipman.gor"):
        from app.services.teknik_servis import ekipman

        for e in await ekipman.kalite_ozeti(db, user, clock):
            hedef = {
                "liste": f"/servis-ekipman?kalite={e['kod']}",
                "mukerrer": "/servis-ekipman?sekme=kalite&liste=mukerrer",
                "saha": "/servis-ekipman?sekme=kalite&liste=saha",
            }[e["liste"]]
            sonuc.append(
                {
                    "kod": f"ekipman_{e['kod']}",
                    "baslik": e["baslik"],
                    "tanim": e["tanim"],
                    "grup": "ekipman",
                    "deger": e["deger"],
                    "hedef": hedef,
                }
            )
    return sonuc


async def is_paydasi(db: AsyncSession, user: User) -> int:
    """Eşleşme oranının paydası: kapsamdaki iptal edilmemiş iş sayısı."""
    return await _say(db, _is_taban(user).where(ServiceOrder.status != "IPTAL"))


async def eksik_veri_is_sayisi(db: AsyncSession, user: User) -> int:
    """Rapor "Yönetim Özeti" notu için: servis kontrollerinden en az birine
    düşen FARKLI iş sayısı (D3-A çağırabilir; karantina satırı iş değildir)."""
    kosullar = [
        k.sorgu(user).with_only_columns(ServiceOrder.id)
        for k in KONTROLLER.values()
        if k.grup == "servis" and k.sorgu is not None
    ]
    if not kosullar:
        return 0
    birlesim = kosullar[0].union(*kosullar[1:]).subquery()
    return int(await db.scalar(select(func.count()).select_from(birlesim)) or 0)
