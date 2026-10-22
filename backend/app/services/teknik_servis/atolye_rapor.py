"""Atölye listesi, özet/KPI ve Excel satırları — TEK süzgeç kaynağı (E05-08/09/18, TS-092/098).

**Sayı = liste (plan §4.5):** liste ucu, KPI kutuları (`ozet`) ve Excel AYNI
`filtreli_sorgu`'yu kullanır; kutudaki sayı, tıklanınca açılan listenin
`X-Toplam-Kayit` başlığıyla aynıdır. Kapsam SQL'de uygulanır
(`kapsam.kapsam_isler` — atölye kaydı servis işinin bağlısıdır, plan §1.2):
kapsam dışı birimin kaydı ne listede ne sayıda ne Excel'de görünür.

**Yaşlandırma** kabul anından (sunucu Clock'u) Türkiye günüyle hesaplanır;
yaş kovaları ve "tahmini bitişi geçen" yalnız AÇIK kayıtlara uygulanır.

**Tamir bedeli (TS-092):** `repair_amount` satıra yalnız `maliyet_gorur`
true iken ANAHTAR olarak girer (None değil, anahtar yok). Excel sütunu da
aynı kuralla eklenir; kural çağıranın hatırlamasına bırakılmaz.

**KPI raporu (TS-194, E05-09/24):** çevrim süresi = `completed_at −
received_at` (ilk TESLIME_HAZIR/ONARILMADAN_IADE anı; tahmini bitiş hiçbir
koşulda yerine konmaz). Dış servis süresi (`external_returned_at −
external_sent_at`) çevrim ortalamasından AYRI raporlanır ve "dış servis
hariç çevrim" ayrıca verilir. İşçilik kişi-saati zaman modülünün tek
tanımından (`zaman.sure_eksik_ifadesi`, MOLA hariç kapalı bölümler) gelir;
süre kaydı eksik iş ortalamaya GİRMEZ, "süre kaydı eksik" sayısında görünür.
Bütün toplama SQL'dedir; her sayılabilir gösterge, tıklanınca açılan listenin
süzgecini (`sorgu`) taşır (sayı = liste).

**Uyarılar (E05-28):** `atolye.teslim_alinmadi` (TESLIME_HAZIR /
ONARILMADAN_IADE ve tamamlanmasının üzerinden `atolye_teslim_alinmayan_uyari_gun`
geçmiş), `atolye.geciken` (tahmini bitişi geçen açık kayıt). Sayılar liste
süzgecinin AYNI sorgusundan ve aynı kapsamla gelir.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, and_, exists, func, or_, select

from app.models import (
    Account,
    ServiceEquipment,
    ServiceFaultReason,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceTimeEntry,
    User,
    WorkshopRecord,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.servis_atolye import (
    ATOLYE_ACIK_OLMAYAN,
    ATOLYE_DURUMLARI,
    ATOLYE_SERVIS_TURLERI,
)
from app.models.teknik_servis import KISI_SAATE_DAHIL
from app.services import settings as ayar_svc
from app.services.normalize import normalize_seri, tr_normkey
from app.services.teknik_servis import kapsam, zaman
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi
from app.services.teknik_servis.yerel_zaman import yerel_bugun, yerel_gun, yerel_gun_araligi
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

ACIK_DURUMLAR = tuple(d for d in ATOLYE_DURUMLARI if d not in ATOLYE_ACIK_OLMAYAN)
# İşi bitmiş, müşterinin almasını bekleyen durumlar (E05-28).
TESLIM_BEKLEYEN = ("TESLIME_HAZIR", "ONARILMADAN_IADE")
TESLIM_AYARI = "atolye_teslim_alinmayan_uyari_gun"
VARSAYILAN_TESLIM_ESIGI = 30
# Rapor dönemi: varsayılan son 31 gün, en çok 24 ay (D3-A motoruyla aynı sınır).
VARSAYILAN_DONEM_GUN = 30
AZAMI_DONEM_GUN = 731

# Yaş kovası → (en az gün, en çok gün; None = üst sınır yok). Kabul günü 0. gündür.
YAS_KOVALARI: dict[str, tuple[int, int | None]] = {
    "0-3": (0, 3),
    "4-7": (4, 7),
    "8-14": (8, 14),
    "15+": (15, None),
}
DURUM_GRUPLARI = ("ACIK", "KAPALI")

DURUM_ADLARI: dict[str, str] = {
    "KABUL_EDILDI": "Kabul edildi",
    "TESHISTE": "Teşhiste",
    "ONAY_BEKLIYOR": "Onay bekliyor",
    "ONARIMDA": "Onarımda",
    "PARCA_BEKLIYOR": "Parça bekliyor",
    "DIS_SERVISTE": "Dış serviste",
    "TEST_KONTROL": "Test / kontrol",
    "TESLIME_HAZIR": "Teslime hazır",
    "ONARILMADAN_IADE": "Onarılmadan iade",
    "KARGOYA_VERILDI": "Kargoya verildi",
    "TESLIM_EDILDI": "Teslim edildi",
    "IPTAL": "İptal",
}
SERVIS_TURU_ADLARI: dict[str, str] = {
    "ARIZA_ONARIMI": "Arıza onarımı",
    "GARANTI_ONARIMI": "Garanti onarımı",
    "DIS_SERVIS": "Dış servis",
    "YAZILIM_FREKANS": "Yazılım / frekans",
    "KIRALAMA_TAKIP": "Kiralama takip",
}
GARANTI_ADLARI: dict[str, str] = {
    "GARANTI_ICI": "Garanti içi",
    "GARANTI_DISI": "Garanti dışı",
    "ONARIM_GARANTISI": "Onarım garantisi",
    "BELIRSIZ": "Belirsiz",
}

# Liste/Excel/özet süzgecinin kabul ettiği anahtarlar (tek tanım).
FILTRE_ANAHTARLARI = (
    "durum",
    "durum_grubu",
    "birim",
    "teknisyen_id",
    "marka",
    "servis_turu",
    "q",
    "yas",
    "geciken",
    "kabul_grubu",
    "musteri_id",
    # TS-194: uyarı / KPI raporu listeleri
    "teslim_alinmayan",
    "dis_servis",
    "tedarikci_id",
    "sure_eksik",
    "tamamlanma_bas",
    "tamamlanma_bit",
)


def _bos(deger: Any) -> Any:
    if isinstance(deger, str):
        return deger.strip() or None
    return deger


def _tarih(deger: Any, alan: str) -> date | None:
    """Süzgeç tarihi: `date` ya da ISO metin (KPI `sorgu`'su JSON'dan gelir)."""
    if deger is None or isinstance(deger, date):
        return deger
    try:
        return date.fromisoformat(str(deger))
    except ValueError as exc:
        raise ServisGirdiHatasi(f"{alan} geçerli bir tarih değil: {deger}") from exc


def _bool(deger: Any) -> bool:
    if isinstance(deger, str):
        return deger.strip().lower() in ("1", "true", "evet", "on")
    return bool(deger)


async def teslim_esigi(db: AsyncSession) -> int:
    """Teslim alınmayan cihaz eşiği (gün); ayar okunamazsa 30."""
    try:
        return int(await ayar_svc.get(db, TESLIM_AYARI))
    except (KeyError, TypeError, ValueError):
        return VARSAYILAN_TESLIM_ESIGI


def filtre_dogrula(filtre: dict[str, Any]) -> dict[str, Any]:
    """Süzgeç sözlüğünü doğrular ve temizler (bilinmeyen değer → 400)."""
    f = {k: _bos(filtre.get(k)) for k in FILTRE_ANAHTARLARI}
    durumlar = [d for d in (f.get("durum") or []) if d]
    bilinmeyen = [d for d in durumlar if d not in ATOLYE_DURUMLARI]
    if bilinmeyen:
        raise ServisGirdiHatasi(f"Bilinmeyen atölye durumu: {', '.join(bilinmeyen)}")
    f["durum"] = durumlar
    if f["durum_grubu"] is not None and f["durum_grubu"] not in DURUM_GRUPLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen durum grubu: {f['durum_grubu']}")
    if f["birim"] is not None and f["birim"] not in BIRIM_KODLARI:
        raise ServisGirdiHatasi(f"Bilinmeyen birim: {f['birim']}")
    if f["servis_turu"] is not None and f["servis_turu"] not in ATOLYE_SERVIS_TURLERI:
        raise ServisGirdiHatasi(f"Bilinmeyen servis türü: {f['servis_turu']}")
    if f["yas"] is not None and f["yas"] not in YAS_KOVALARI:
        raise ServisGirdiHatasi(f"Bilinmeyen yaş kovası: {f['yas']}")
    f["geciken"] = _bool(f.get("geciken"))
    for anahtar in ("teslim_alinmayan", "dis_servis", "sure_eksik"):
        f[anahtar] = _bool(f.get(anahtar))
    f["tamamlanma_bas"] = _tarih(f.get("tamamlanma_bas"), "Tamamlanma başlangıcı")
    f["tamamlanma_bit"] = _tarih(f.get("tamamlanma_bit"), "Tamamlanma bitişi")
    if f["tamamlanma_bas"] and f["tamamlanma_bit"] and f["tamamlanma_bit"] < f["tamamlanma_bas"]:
        raise ServisGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    return f


def _gun_baslangici(gun: date):
    return yerel_gun_araligi(gun)[0]


def filtreli_sorgu(
    user: User,
    filtre: dict[str, Any],
    clock: Clock,
    *,
    teslim_esik_gun: int = VARSAYILAN_TESLIM_ESIGI,
) -> Select:
    """Liste, özet, KPI raporu, uyarı ve Excel AYNI sorguyu kullanır (sayı = liste).

    Dönen sorgu `WorkshopRecord` seçer (sayfalama kırılması birincil anahtara
    eklenir); servis işi ve ekipman süzgeç için JOIN'lidir. Kapsam her
    zaman uygulanır. `teslim_esik_gun` yalnız `teslim_alinmayan` süzgecinde
    kullanılır (çağıran ayarı `teslim_esigi` ile okur).
    """
    f = filtre_dogrula(filtre)
    stmt = (
        select(WorkshopRecord)
        .join(ServiceOrder, ServiceOrder.id == WorkshopRecord.service_order_id)
        .join(ServiceEquipment, ServiceEquipment.id == WorkshopRecord.equipment_id)
        .where(WorkshopRecord.is_deleted.is_(False), ServiceOrder.is_deleted.is_(False))
    )
    stmt = kapsam.kapsam_isler(stmt, user, WorkshopRecord.service_order_id)
    acik = WorkshopRecord.status.in_(ACIK_DURUMLAR)
    if f["durum"]:
        stmt = stmt.where(WorkshopRecord.status.in_(f["durum"]))
    if f["durum_grubu"] == "ACIK":
        stmt = stmt.where(acik)
    elif f["durum_grubu"] == "KAPALI":
        stmt = stmt.where(WorkshopRecord.status.in_(ATOLYE_ACIK_OLMAYAN))
    if f["birim"]:
        stmt = stmt.where(ServiceOrder.birim == f["birim"])
    if f["musteri_id"] is not None:
        stmt = stmt.where(ServiceOrder.customer_id == int(f["musteri_id"]))
    if f["servis_turu"]:
        stmt = stmt.where(WorkshopRecord.service_type == f["servis_turu"])
    if f["kabul_grubu"] is not None:
        stmt = stmt.where(WorkshopRecord.intake_group_no == int(f["kabul_grubu"]))
    if f["teknisyen_id"] is not None:
        stmt = stmt.where(
            exists().where(
                ServiceOrderAssignment.service_order_id == WorkshopRecord.service_order_id,
                ServiceOrderAssignment.user_id == int(f["teknisyen_id"]),
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    if f["marka"]:
        # Marka serbest metindir; karşılaştırma Türkçe katlamalı ve harf duyarsız (E05-20).
        stmt = stmt.where(ServiceEquipment.brand_key == tr_normkey(f["marka"]))
    if f["q"]:
        desen = f"%{f['q']}%"
        seri = normalize_seri(f["q"])
        anahtar = tr_normkey(f["q"])
        kosullar = [
            WorkshopRecord.atolye_no.ilike(desen),
            ServiceOrder.so_no.ilike(desen),
            exists().where(
                Account.id == ServiceOrder.customer_id,
                or_(Account.title.ilike(desen), Account.title_key.contains(anahtar))
                if anahtar
                else Account.title.ilike(desen),
            ),
        ]
        if seri:
            kosullar.append(ServiceEquipment.serial_key.like(f"%{seri}%"))
        stmt = stmt.where(or_(*kosullar))
    bugun = yerel_bugun(clock)
    if f["yas"]:
        alt, ust = YAS_KOVALARI[f["yas"]]
        # yaş = bugün − kabul günü; kabul günü ≤ bugün − alt  ve  > bugün − ust − 1
        kosul = [
            acik,
            WorkshopRecord.received_at < yerel_gun_araligi(bugun - timedelta(days=alt))[1],
        ]
        if ust is not None:
            kosul.append(WorkshopRecord.received_at >= _gun_baslangici(bugun - timedelta(days=ust)))
        stmt = stmt.where(and_(*kosul))
    if f["geciken"]:
        stmt = stmt.where(acik, WorkshopRecord.estimated_finish_date < bugun)
    if f["teslim_alinmayan"]:
        stmt = stmt.where(
            WorkshopRecord.status.in_(TESLIM_BEKLEYEN),
            WorkshopRecord.completed_at < clock.now() - timedelta(days=teslim_esik_gun),
        )
    if f["dis_servis"]:
        stmt = stmt.where(WorkshopRecord.external_sent_at.is_not(None))
    if f["tedarikci_id"] is not None:
        stmt = stmt.where(WorkshopRecord.external_vendor_id == int(f["tedarikci_id"]))
    if f["sure_eksik"]:
        # Zaman modülünün TEK tanımı (EKSIK | KISMI); ikinci hesap yazılmaz.
        stmt = stmt.where(zaman.sure_eksik_ifadesi())
    if f["tamamlanma_bas"] is not None:
        stmt = stmt.where(WorkshopRecord.completed_at >= _gun_baslangici(f["tamamlanma_bas"]))
    if f["tamamlanma_bit"] is not None:
        stmt = stmt.where(WorkshopRecord.completed_at < yerel_gun_araligi(f["tamamlanma_bit"])[1])
    return stmt.order_by(WorkshopRecord.received_at.desc())


async def say(db: AsyncSession, stmt: Select) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )


def kpi_tanimlari(teslim_esik_gun: int = VARSAYILAN_TESLIM_ESIGI) -> list[dict[str, Any]]:
    """KPI kutuları: kod, başlık, tanım ve kutunun açtığı liste süzgeci."""
    kutular: list[dict[str, Any]] = [
        {
            "kod": "ACIK",
            "baslik": "Atölyede",
            "tanim": "Teslim edilmemiş ve iptal edilmemiş bütün atölye kayıtları",
            "sorgu": {"durum_grubu": "ACIK"},
        }
    ]
    for d in ACIK_DURUMLAR:
        kutular.append(
            {
                "kod": d,
                "baslik": DURUM_ADLARI[d],
                "tanim": f"Atölye durumu '{DURUM_ADLARI[d]}' olan kayıtlar",
                "sorgu": {"durum": [d]},
            }
        )
    for kova, (alt, ust) in YAS_KOVALARI.items():
        aralik = f"{alt}+ gün" if ust is None else f"{alt}-{ust} gün"
        kutular.append(
            {
                "kod": f"YAS_{kova}",
                "baslik": f"Bekleyen {aralik}",
                "tanim": f"Kabulünden bu yana {aralik} geçmiş AÇIK kayıtlar (Türkiye günü)",
                "sorgu": {"yas": kova},
            }
        )
    kutular.append(
        {
            "kod": "GECIKEN",
            "baslik": "Tahmini bitişi geçen",
            "tanim": "Tahmini bitiş tarihi bugünden önce olan AÇIK kayıtlar",
            "sorgu": {"geciken": True},
        }
    )
    kutular.append(
        {
            "kod": "TESLIM_ALINMADI",
            "baslik": "Teslim alınmayan",
            "tanim": (
                f"Teslime hazır / onarılmadan iade durumunda {teslim_esik_gun} günden uzun "
                "süredir müşterinin almadığı cihazlar"
            ),
            "sorgu": {"teslim_alinmayan": True},
        }
    )
    kutular.append(
        {
            "kod": "SURE_EKSIK",
            "baslik": "Süre kaydı eksik (açık)",
            "tanim": (
                "Açık atölye kayıtlarından çalışılmış ama zaman kaydı olmayan ya da "
                "atanan teknisyenlerden birinin kaydı eksik olanlar"
            ),
            "sorgu": {"durum_grubu": "ACIK", "sure_eksik": True},
        }
    )
    return kutular


_KPI_EZEN = (
    "durum",
    "durum_grubu",
    "yas",
    "geciken",
    "teslim_alinmayan",
    "sure_eksik",
    "dis_servis",
    "tamamlanma_bas",
    "tamamlanma_bit",
)


async def ozet(
    db: AsyncSession, user: User, filtre: dict[str, Any], clock: Clock
) -> list[dict[str, Any]]:
    """KPI kutuları: her kutu = taban süzgeç + kutunun süzgeci ile `filtreli_sorgu` sayısı."""
    taban = {k: v for k, v in filtre.items() if k not in _KPI_EZEN}
    esik = await teslim_esigi(db)
    sonuc = []
    for kutu in kpi_tanimlari(esik):
        stmt = filtreli_sorgu(user, {**taban, **kutu["sorgu"]}, clock, teslim_esik_gun=esik)
        sonuc.append({**kutu, "deger": await say(db, stmt)})
    return sonuc


# --- KPI raporu (TS-194, E05-09/24) -------------------------------------------------


def donem_dogrula(bas: date | None, bit: date | None, clock: Clock) -> tuple[date, date]:
    """Rapor dönemi (Türkiye günü, kapalı aralık): varsayılan son 31 gün.

    Bitiş başlangıçtan önceyse ya da aralık 24 ayı aşıyorsa 400 (sınırsız
    tarama tek istekte bütün arşivi toplardı).
    """
    bit = bit or yerel_bugun(clock)
    bas = bas or bit - timedelta(days=VARSAYILAN_DONEM_GUN)
    if bit < bas:
        raise ServisGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if (bit - bas).days > AZAMI_DONEM_GUN:
        raise ServisGirdiHatasi("Rapor dönemi en çok 24 ay olabilir")
    return bas, bit


def _yuvarla(deger: Any, basamak: str = "0.1") -> Decimal | None:
    if deger is None:
        return None
    return Decimal(str(deger)).quantize(Decimal(basamak), ROUND_HALF_UP)


def _kpi(
    kod: str,
    baslik: str,
    tanim: str,
    deger: Any,
    *,
    birim: str = "adet",
    sorgu: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kod": kod,
        "baslik": baslik,
        "tanim": tanim,
        "deger": deger,
        "birim": birim,
        "sorgu": sorgu,
    }


async def _donem_ozeti(db: AsyncSession, stmt: Select) -> dict[str, Any]:
    """Süzgeçli küme üzerinde tek SQL toplaması (ham süre istemciye taşınmaz)."""
    alt = (
        stmt.order_by(None)
        .with_only_columns(
            WorkshopRecord.id.label("kayit_id"),
            WorkshopRecord.service_order_id.label("so_id"),
            WorkshopRecord.received_at.label("received_at"),
            WorkshopRecord.completed_at.label("completed_at"),
            WorkshopRecord.external_sent_at.label("dis_gonderim"),
            WorkshopRecord.external_returned_at.label("dis_donus"),
            zaman.sure_eksik_ifadesi().label("sure_eksik"),
        )
        .subquery()
    )
    gun = func.extract("epoch", alt.c.completed_at - alt.c.received_at) / 86400.0
    dis_yok = alt.c.dis_gonderim.is_(None)
    dis_var = alt.c.dis_gonderim.is_not(None)
    donen = and_(dis_var, alt.c.dis_donus.is_not(None))
    satir = (
        await db.execute(
            select(
                func.count(),
                func.avg(gun),
                func.percentile_cont(0.5).within_group(gun),
                func.avg(gun).filter(dis_yok),
                func.count().filter(dis_var),
                func.avg(alt.c.dis_donus - alt.c.dis_gonderim).filter(donen),
                func.count().filter(and_(dis_var, alt.c.dis_donus.is_(None))),
                func.count().filter(alt.c.sure_eksik),
            ).select_from(alt)
        )
    ).one()
    # İşçilik: MOLA hariç, iptal edilmemiş KAPALI bölümler; süre eksik iş dışarıda.
    bolum = (
        select(
            ServiceTimeEntry.service_order_id.label("so_id"),
            func.sum(
                func.extract("epoch", ServiceTimeEntry.ended_at - ServiceTimeEntry.started_at)
            ).label("saniye"),
        )
        .where(
            ServiceTimeEntry.service_order_id.in_(select(alt.c.so_id)),
            zaman.gecerli_bolum(),
            ServiceTimeEntry.faaliyet.in_(sorted(KISI_SAATE_DAHIL)),
            ServiceTimeEntry.ended_at.is_not(None),
        )
        .group_by(ServiceTimeEntry.service_order_id)
        .subquery()
    )
    iscilik_ort, iscilik_adet = (
        await db.execute(
            select(func.avg(bolum.c.saniye) / 60.0, func.count())
            .select_from(alt.join(bolum, bolum.c.so_id == alt.c.so_id))
            .where(alt.c.sure_eksik.is_(False))
        )
    ).one()
    return {
        "adet": int(satir[0] or 0),
        "cevrim_ort_gun": _yuvarla(satir[1]),
        "cevrim_medyan_gun": _yuvarla(satir[2]),
        "cevrim_dis_haric_ort_gun": _yuvarla(satir[3]),
        "dis_servis_adet": int(satir[4] or 0),
        "dis_servis_ort_gun": _yuvarla(satir[5]),
        "dis_serviste_donmeyen": int(satir[6] or 0),
        "sure_eksik": int(satir[7] or 0),
        "iscilik_ort_dk": _yuvarla(iscilik_ort, "1"),
        "iscilik_olculen": int(iscilik_adet or 0),
    }


async def kpi_raporu(
    db: AsyncSession,
    user: User,
    filtre: dict[str, Any],
    clock: Clock,
    *,
    bas: date | None = None,
    bit: date | None = None,
) -> dict[str, Any]:
    """Atölye KPI raporu: dönemde TAMAMLANAN (ilk teslime hazır anı dönemde)
    kayıtlar üzerinden çevrim, dış servis ve işçilik göstergeleri + servis
    türü kırılımı. Sayılabilir her göstergenin `sorgu`'su liste süzgecidir."""
    bas, bit = donem_dogrula(bas, bit, clock)
    taban = {k: v for k, v in filtre.items() if k not in _KPI_EZEN}
    donem = {**taban, "tamamlanma_bas": bas.isoformat(), "tamamlanma_bit": bit.isoformat()}
    esik = await teslim_esigi(db)
    ozet_ = await _donem_ozeti(db, filtreli_sorgu(user, donem, clock, teslim_esik_gun=esik))
    acik_dis = await say(
        db,
        filtreli_sorgu(user, {**taban, "durum": ["DIS_SERVISTE"]}, clock, teslim_esik_gun=esik),
    )
    teslim_bekleyen = await say(
        db,
        filtreli_sorgu(user, {**taban, "teslim_alinmayan": True}, clock, teslim_esik_gun=esik),
    )
    kutular = [
        _kpi(
            "TAMAMLANAN",
            "Tamamlanan",
            "Dönem içinde ilk kez teslime hazır / onarılmadan iade olan kayıtlar",
            ozet_["adet"],
            sorgu=donem,
        ),
        _kpi(
            "CEVRIM_ORT",
            "Ortalama çevrim",
            "Kabulden ilk teslime hazır anına geçen süre (gün); tahmini bitiş kullanılmaz",
            ozet_["cevrim_ort_gun"],
            birim="gün",
        ),
        _kpi(
            "CEVRIM_MEDYAN",
            "Medyan çevrim",
            "Çevrim süresinin ortancası (gün)",
            ozet_["cevrim_medyan_gun"],
            birim="gün",
        ),
        _kpi(
            "CEVRIM_DIS_HARIC",
            "Ortalama çevrim (dış servis hariç)",
            "Dış servise gönderilmemiş kayıtların ortalama çevrimi (gün)",
            ozet_["cevrim_dis_haric_ort_gun"],
            birim="gün",
        ),
        _kpi(
            "DIS_SERVIS",
            "Dış servise giden",
            "Dönemde tamamlanan ve üretici/distribütöre gönderilmiş kayıtlar",
            ozet_["dis_servis_adet"],
            sorgu={**donem, "dis_servis": True},
        ),
        _kpi(
            "DIS_SERVIS_SURE",
            "Ortalama dış servis süresi",
            "Dış servise gönderimden dönüşe geçen gün (dönmeyen kayıt girmez)",
            ozet_["dis_servis_ort_gun"],
            birim="gün",
        ),
        _kpi(
            "DIS_SERVISTE",
            "Şu an dış serviste",
            "Durumu 'Dış serviste' olan açık kayıtlar (dönemden bağımsız)",
            acik_dis,
            sorgu={**taban, "durum": ["DIS_SERVISTE"]},
        ),
        _kpi(
            "SURE_EKSIK",
            "Süre kaydı eksik",
            "Dönemde tamamlanan ve zaman kaydı olmayan ya da eksik olan kayıtlar; "
            "işçilik ortalamasına girmez",
            ozet_["sure_eksik"],
            sorgu={**donem, "sure_eksik": True},
        ),
        _kpi(
            "ISCILIK_ORT",
            "Ortalama işçilik",
            "Süre kaydı tam olan kayıtlarda kişi-dakika ortalaması (mola hariç)",
            ozet_["iscilik_ort_dk"],
            birim="dk",
        ),
        _kpi(
            "TESLIM_ALINMADI",
            "Teslim alınmayan",
            f"{esik} günden uzun süredir teslim alınmayı bekleyen cihazlar (dönemden bağımsız)",
            teslim_bekleyen,
            sorgu={**taban, "teslim_alinmayan": True},
        ),
    ]
    kirilim = []
    for tur in ATOLYE_SERVIS_TURLERI:
        if taban.get("servis_turu") and taban["servis_turu"] != tur:
            continue
        sorgu = {**donem, "servis_turu": tur}
        o = await _donem_ozeti(db, filtreli_sorgu(user, sorgu, clock, teslim_esik_gun=esik))
        if not o["adet"]:
            continue
        kirilim.append(
            {
                "servis_turu": tur,
                "ad": SERVIS_TURU_ADLARI.get(tur, tur),
                **o,
                "sorgu": sorgu,
            }
        )
    return {
        "donem": {"bas": bas, "bit": bit},
        "kutular": kutular,
        "servis_turu_kirilimi": kirilim,
    }


async def donem_satirlari(
    db: AsyncSession,
    user: User,
    filtre: dict[str, Any],
    clock: Clock,
    *,
    bas: date,
    bit: date,
) -> list[dict[str, Any]]:
    """Excel "Kayıtlar" sayfası: dönemde tamamlanan kayıtlar + kayıt başı süreler."""
    taban = {k: v for k, v in filtre.items() if k not in _KPI_EZEN}
    donem = {**taban, "tamamlanma_bas": bas.isoformat(), "tamamlanma_bit": bit.isoformat()}
    kayitlar = list((await db.scalars(filtreli_sorgu(user, donem, clock))).all())
    ozetler = await zaman.sure_ozeti_toplu(db, [k.service_order_id for k in kayitlar])
    isler = dict(
        (
            await db.execute(
                select(ServiceOrder.id, ServiceOrder.so_no).where(
                    ServiceOrder.id.in_([k.service_order_id for k in kayitlar] or [0])
                )
            )
        ).all()
    )
    sonuc = []
    for k in kayitlar:
        o = ozetler.get(k.service_order_id)
        cevrim = (
            _yuvarla((k.completed_at - k.received_at).total_seconds() / 86400.0)
            if k.completed_at
            else None
        )
        dis = (
            (k.external_returned_at - k.external_sent_at).days
            if k.external_sent_at and k.external_returned_at
            else None
        )
        eksik = o is None or o.sure_eksik
        sonuc.append(
            {
                "atolye_no": k.atolye_no,
                "so_no": isler.get(k.service_order_id),
                "service_type": k.service_type,
                "status": k.status,
                "received_at": k.received_at,
                "completed_at": k.completed_at,
                "cevrim_gun": cevrim,
                "dis_servis_gun": dis,
                "sure_durumu": o.sure_durumu if o else "EKSIK",
                "iscilik_dk": None if eksik or o is None else o.kisi_saat_dk,
            }
        )
    return sonuc


# --- Satır üretimi (liste ve Excel ortak) -------------------------------------------


def bekleme_gunu(kayit: WorkshopRecord, clock: Clock) -> int:
    """Kabul gününden bugüne (açık kayıt) ya da teslim/iptal gününe gün sayısı."""
    bitis = yerel_bugun(clock)
    if kayit.status in ATOLYE_ACIK_OLMAYAN:
        son = kayit.delivered_at or kayit.updated_at
        if son is not None:
            bitis = yerel_gun(son)
    return max(0, (bitis - yerel_gun(kayit.received_at)).days)


async def satirlar(
    db: AsyncSession,
    kayitlar: list[WorkshopRecord],
    clock: Clock,
    *,
    maliyet_gorur: bool,
) -> list[dict[str, Any]]:
    """Liste satırları (toplu sorgularla). `repair_amount` yalnız `maliyet_gorur`."""
    if not kayitlar:
        return []
    so_idler = [k.service_order_id for k in kayitlar]
    isler = {
        s.id: s
        for s in (await db.scalars(select(ServiceOrder).where(ServiceOrder.id.in_(so_idler)))).all()
    }
    ekipmanlar = {
        e.id: e
        for e in (
            await db.scalars(
                select(ServiceEquipment).where(
                    ServiceEquipment.id.in_({k.equipment_id for k in kayitlar})
                )
            )
        ).all()
    }
    hesap_idler = {s.customer_id for s in isler.values() if s.customer_id}
    hesaplar = dict(
        (
            await db.execute(
                select(Account.id, Account.title).where(Account.id.in_(hesap_idler or {0}))
            )
        ).all()
    )
    atamalar: dict[int, list[ServiceOrderAssignment]] = {i: [] for i in so_idler}
    for a in (
        await db.scalars(
            select(ServiceOrderAssignment)
            .where(
                ServiceOrderAssignment.service_order_id.in_(so_idler),
                ServiceOrderAssignment.removed_at.is_(None),
            )
            .order_by(ServiceOrderAssignment.is_lead.desc(), ServiceOrderAssignment.id)
        )
    ).all():
        atamalar[a.service_order_id].append(a)
    kisi_idler = {a.user_id for e in atamalar.values() for a in e}
    adlar = dict(
        (
            await db.execute(select(User.id, User.full_name).where(User.id.in_(kisi_idler or {0})))
        ).all()
    )
    neden_idler = {k.fault_reason_id for k in kayitlar if k.fault_reason_id}
    nedenler = dict(
        (
            await db.execute(
                select(ServiceFaultReason.id, ServiceFaultReason.ad).where(
                    ServiceFaultReason.id.in_(neden_idler or {0})
                )
            )
        ).all()
    )
    bugun = yerel_bugun(clock)
    sonuc = []
    for k in kayitlar:
        so = isler[k.service_order_id]
        e = ekipmanlar.get(k.equipment_id)
        ekip = atamalar.get(so.id, [])
        sorumlu = next((a for a in ekip if a.is_lead), ekip[0] if ekip else None)
        acik = k.status not in ATOLYE_ACIK_OLMAYAN
        satir: dict[str, Any] = {
            "id": so.id,
            "so_id": so.id,
            "kayit_id": k.id,
            "atolye_no": k.atolye_no,
            "so_no": so.so_no,
            "birim": so.birim,
            "servis_durumu": so.status,
            "musteri": (
                {"id": so.customer_id, "title": hesaplar.get(so.customer_id)}
                if so.customer_id
                else None
            ),
            "service_type": k.service_type,
            "status": k.status,
            "acik": acik,
            "ekipman": (
                {
                    "id": e.id,
                    "tip": e.equipment_type,
                    "marka": e.brand,
                    "model": e.model,
                    "seri": e.serial_no,
                }
                if e
                else None
            ),
            "sorumlu": (
                {"id": sorumlu.user_id, "ad": adlar.get(sorumlu.user_id)} if sorumlu else None
            ),
            "ekip": [{"id": a.user_id, "ad": adlar.get(a.user_id)} for a in ekip],
            "received_at": k.received_at,
            "estimated_finish_date": k.estimated_finish_date,
            "bekleme_gunu": bekleme_gunu(k, clock),
            "geciken": bool(
                acik and k.estimated_finish_date is not None and k.estimated_finish_date < bugun
            ),
            "warranty_status": k.warranty_status,
            "intake_group_no": k.intake_group_no,
            "ariza_nedeni": nedenler.get(k.fault_reason_id) if k.fault_reason_id else None,
            "repair_category": k.repair_category,
            "test_result": k.test_result,
            "completed_at": k.completed_at,
            "delivered_at": k.delivered_at,
            "version": k.version,
        }
        if maliyet_gorur:
            satir["repair_amount"] = k.repair_amount
        sonuc.append(satir)
    return sonuc


def excel_sutunlari(maliyet_gorur: bool) -> list[Any]:
    from app.services.export import Sutun

    sutunlar = [
        Sutun("Atölye No"),
        Sutun("Servis İşi No"),
        Sutun("Birim"),
        Sutun("Müşteri"),
        Sutun("Servis Türü"),
        Sutun("Durum"),
        Sutun("Ekipman Tipi"),
        Sutun("Marka"),
        Sutun("Model"),
        Sutun("Seri No"),
        Sutun("Sorumlu"),
        Sutun("Kabul", "zaman"),
        Sutun("Tahmini Bitiş", "tarih"),
        Sutun("Bekleme (gün)", "tamsayi"),
        Sutun("Gecikmiş"),
        Sutun("Garanti"),
        Sutun("Arıza Nedeni"),
        Sutun("Onarım Kategorisi"),
        Sutun("Test"),
        Sutun("Tamamlanma", "zaman"),
        Sutun("Teslim", "zaman"),
        Sutun("Kabul Grubu"),
    ]
    if maliyet_gorur:
        sutunlar.append(Sutun("Tamir Bedeli", "ondalik"))
    return sutunlar


def excel_satiri(s: dict[str, Any], *, maliyet_gorur: bool) -> list[Any]:
    from app.permissions import BIRIMLER

    e = s["ekipman"] or {}
    satir = [
        s["atolye_no"],
        s["so_no"],
        BIRIMLER.get(s["birim"], s["birim"]),
        (s["musteri"] or {}).get("title"),
        SERVIS_TURU_ADLARI.get(s["service_type"], s["service_type"]),
        DURUM_ADLARI.get(s["status"], s["status"]),
        e.get("tip"),
        e.get("marka"),
        e.get("model"),
        e.get("seri"),
        (s["sorumlu"] or {}).get("ad"),
        s["received_at"],
        s["estimated_finish_date"],
        s["bekleme_gunu"],
        "Evet" if s["geciken"] else "Hayır",
        GARANTI_ADLARI.get(s["warranty_status"], s["warranty_status"]),
        s["ariza_nedeni"],
        s["repair_category"],
        s["test_result"],
        s["completed_at"],
        s["delivered_at"],
        s["intake_group_no"],
    ]
    if maliyet_gorur:
        satir.append(s.get("repair_amount"))
    return satir


SURE_DURUMU_ADLARI = {
    "TAM": "Tam",
    "KISMI": "Kısmi (eksik)",
    "EKSIK": "Eksik",
    "BEKLENMIYOR": "Beklenmiyor",
}


def kpi_excel_sayfalari(rapor: dict[str, Any], kayitlar: list[dict[str, Any]]) -> list[Any]:
    """KPI raporu Excel'i: göstergeler, servis türü kırılımı, dönem kayıtları.

    Fiyat/maliyet sütunu YOK (yalnız süre ve adet). Ölçülemeyen değer boş
    hücre olarak kalır, 0 yazılmaz.
    """
    from app.services.export import Sayfa, Sutun

    kpi = Sayfa(
        "KPI",
        [Sutun("Gösterge"), Sutun("Değer", "ondalik"), Sutun("Birim"), Sutun("Tanım")],
        [[k["baslik"], k["deger"], k["birim"], k["tanim"]] for k in rapor["kutular"]],
    )
    kirilim = Sayfa(
        "Servis Türü",
        [
            Sutun("Servis Türü"),
            Sutun("Tamamlanan", "tamsayi"),
            Sutun("Ort. Çevrim (gün)", "ondalik"),
            Sutun("Medyan Çevrim (gün)", "ondalik"),
            Sutun("Dış Servis Hariç Çevrim (gün)", "ondalik"),
            Sutun("Dış Servise Giden", "tamsayi"),
            Sutun("Ort. Dış Servis (gün)", "ondalik"),
            Sutun("Süre Kaydı Eksik", "tamsayi"),
            Sutun("Ort. İşçilik (dk)", "ondalik"),
        ],
        [
            [
                r["ad"],
                r["adet"],
                r["cevrim_ort_gun"],
                r["cevrim_medyan_gun"],
                r["cevrim_dis_haric_ort_gun"],
                r["dis_servis_adet"],
                r["dis_servis_ort_gun"],
                r["sure_eksik"],
                r["iscilik_ort_dk"],
            ]
            for r in rapor["servis_turu_kirilimi"]
        ],
    )
    satirlar = Sayfa(
        "Kayıtlar",
        [
            Sutun("Atölye No"),
            Sutun("Servis İşi No"),
            Sutun("Servis Türü"),
            Sutun("Durum"),
            Sutun("Kabul", "zaman"),
            Sutun("Tamamlanma", "zaman"),
            Sutun("Çevrim (gün)", "ondalik"),
            Sutun("Dış Servis (gün)", "tamsayi"),
            Sutun("Süre Kaydı"),
            Sutun("İşçilik (dk)", "tamsayi"),
        ],
        [
            [
                s["atolye_no"],
                s["so_no"],
                SERVIS_TURU_ADLARI.get(s["service_type"], s["service_type"]),
                DURUM_ADLARI.get(s["status"], s["status"]),
                s["received_at"],
                s["completed_at"],
                s["cevrim_gun"],
                s["dis_servis_gun"],
                SURE_DURUMU_ADLARI.get(s["sure_durumu"], s["sure_durumu"]),
                s["iscilik_dk"],
            ]
            for s in kayitlar
        ],
    )
    return [kpi, kirilim, satirlar]


# --- Uyarılar (E05-28) -------------------------------------------------------------------


async def atolye_uyarilari(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Teslim alınmayan cihaz ve tahmini bitişi geçen kayıt (birim/iş kapsamlı).

    Sayı, uyarının açtığı listenin AYNI sorgusudur (`filtreli_sorgu`).
    """
    esik = await teslim_esigi(db)
    teslim = await say(
        db, filtreli_sorgu(user, {"teslim_alinmayan": True}, clock, teslim_esik_gun=esik)
    )
    geciken = await say(db, filtreli_sorgu(user, {"geciken": True}, clock))
    return [
        Uyari(
            kod="atolye.teslim_alinmadi",
            baslik="Teslim alınmayan atölye cihazı",
            adet=teslim,
            yol="/atolye?teslim_alinmayan=1",
            onem="uyari",
            aciklama=f"Teslime hazır olup {esik} günden uzun süredir müşterinin almadığı cihazlar",
        ),
        Uyari(
            kod="atolye.geciken",
            baslik="Tahmini bitişi geçen atölye kaydı",
            adet=geciken,
            yol="/atolye?geciken=1",
            onem="uyari",
            aciklama="Tahmini bitiş tarihi geçmiş ve henüz teslim edilmemiş kayıtlar",
        ),
    ]


ts_uyarilar.kaydet("atolye", "atolye.gor", atolye_uyarilari)
