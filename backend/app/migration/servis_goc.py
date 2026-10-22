"""Servis işi göçü: V1 `WorkOrders` → `service_orders` (+ olay, sonuç, seri, atama) (TS-174).

Kaynak tablolar: `WorkOrders`, `WorkOrderStatusLogs` (olay geçmişi),
`WorkOrderDevices` (seri), `WorkOrderAssignments` (ad metniyle atama).
Kurallar (E01-06 göç eşlemesi, E01 K2, E01 K16):

- **Eski numara korunur:** `so_no` = `WorkOrderNo` (V1 biçimi `SRV-YYYYAA-NNNN`
  yeni 6 haneli seriyle çakışmaz). 24 karakteri aşan ya da başka kayıtta
  kullanılan numara yeni seriden alınır, eski no açıklamaya yazılır.
- **Müşteri uydurulmaz:** `HesapEsleyici`'nin kesin eşleşmesi yoksa
  `customer_id` NULL + `customer_name_raw`/`location_raw` (`ck_so_musteri`
  göç kaydına izin verir); bağ sonradan eşleştirme profiliyle kurulur.
- **POC durumları çözüm kanalına:** `Telefonla Destek / Uzaktan Müdahale /
  Yerinde Müdahale` (durum ya da iş türü) → TELEFON / UZAKTAN / YERINDE. Açık
  işte durum `ISLEMDE` olur; kapalı işte kanal sonuç satırına yazılır. Kanalı
  bilinmeyen kapalı iş sonuçsuz kalır ve raporlanır (`SONUCSUZ_KAPALI`) —
  kanal uydurulmaz. Eşlenemeyen durum ya da tür satırı KARANTİNAYA alır.
- **KD-13:** `Kargoda` → `ATOLYEDE`, `Test / Kontrol` → `ISLEMDE`.
- **Kapsam dışı türler karantinada:** `Planlı Bakım` (bakım dönemi göçü yok;
  `ck_so_pb_bag`), atölye ve kiralık telsiz işleri (atölye/kiralama göçü
  Dalga 3, TS-205). Karantina satırları `servis_isleri` profil Excel'ine
  dökülür; insan türü/durumu belirleyip İçe Aktarma'dan yükler.
- **Olay geçmişi kaynak log'dan:** `WorkOrderStatusLogs` → `DURUM` olayları
  (kişisel veri ve not metni YAZILMAZ: olay tablosu değiştirilemez).
- **İdempotent:** `ON CONFLICT ON CONSTRAINT uq_so_kaynak DO NOTHING`; alt
  kayıtlar yalnız iş İLK kez yazıldığında eklenir. Tekrar koşu 0 yeni iş
  üretir; yalnız sonradan onaylanmış ad eşlemelerinin EKSİK atamaları eklenir.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration.servis_kaynak import (
    GOC_SISTEMI,
    AdimSonucu,
    KaynakDizini,
    bit,
    kaynak_ref,
    metin,
    mevcut_refler,
    tamsayi,
    yerel_an,
)
from app.models import (
    ServiceEquipment,
    ServiceHold,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderEvent,
    ServiceOrderSerial,
    ServiceResult,
)
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import COZUM_KANALLARI, ONCELIKLER, SERVIS_DURUMLARI, SERVIS_TURLERI
from app.services import audit
from app.services.normalize import normalize_seri, tr_normkey
from app.services.teknik_servis import ad_esleme, numara
from app.services.teknik_servis.is_emirleri import tur_kategorisi
from app.services.teknik_servis.veri_kalitesi import HesapEsleyici, hesap_esleyici

KAYNAK_TABLO = "WorkOrders"
HEDEF_TABLO = "service_orders"

BIRIM_ESLEME = {
    "guvenlik sistemleri": "GUVENLIK",
    "guvenlik": "GUVENLIK",
    "haberlesme": "HABERLESME",
    "mobilite": "MOBILITE",
    "arac takip": "ARAC_TAKIP",
    "poc": "POC",
}

# Tür: None = bilinçli KARANTİNA (neden ikinci elemanda).
TUR_ESLEME: dict[str, tuple[str | None, str]] = {
    "saha arizasi": ("ARIZA", ""),
    "ariza": ("ARIZA", ""),
    "saha kurulumu / devreye alma": ("KURULUM", ""),
    "saha kurulumu": ("KURULUM", ""),
    "kurulum": ("KURULUM", ""),
    "kontrol / test": ("PLANSIZ_BAKIM", ""),
    "bakim": ("PLANSIZ_BAKIM", ""),
    "telefonla destek": ("DESTEK", ""),
    "uzaktan mudahale": ("DESTEK", ""),
    "yerinde mudahale": ("DESTEK", ""),
    "planli bakim": (None, "Planlı bakım işi: bakım dönemi göçü yok (PB bağı kurulamaz)"),
    "atolye tamir": (None, "Atölye işi: atölye göçü Dalga 3 (TS-205)"),
    "atolye teknik servis": (None, "Atölye işi: atölye göçü Dalga 3 (TS-205)"),
    "kiralik el telsizi hazirligi": (None, "Kiralama işi: kiralama göçü Dalga 3"),
    "kiradan donen el telsizi testi": (None, "Kiralama işi: kiralama göçü Dalga 3"),
}

DURUM_ESLEME = {
    "musteri talebi": "MUSTERI_TALEBI",
    "planlamada": "PLANLAMADA",
    "planlandi": "PLANLANDI",
    "yola cikildi": "YOLA_CIKILDI",
    "sahada": "SAHADA",
    "islemde": "ISLEMDE",
    "inceleniyor": "ISLEMDE",
    "test / kontrol": "ISLEMDE",
    "atolyede": "ATOLYEDE",
    "kargoda": "ATOLYEDE",
    "beklemede": "BEKLEMEDE",
    "tamamlandi": "TAMAMLANDI",
    "kapatildi": "KAPATILDI",
    "cozuldu": "KAPATILDI",
    "tekrar acildi": "TEKRAR_ACILDI",
    "iptal": "IPTAL",
    # POC: durum aslında çözüm kanalıydı (E01 K2) — iş açıkken İŞLEMDE.
    "telefonla destek": "ISLEMDE",
    "uzaktan mudahale": "ISLEMDE",
    "yerinde mudahale": "ISLEMDE",
}

KANAL_ESLEME = {
    "telefonla destek": "TELEFON",
    "uzaktan mudahale": "UZAKTAN",
    "yerinde mudahale": "YERINDE",
}

ONCELIK_ESLEME = {"kritik": "KRITIK", "yuksek": "YUKSEK", "acil": "YUKSEK", "normal": "NORMAL"}

_KAPANIS_HAM = {"tamamlandi", "kapatildi", "cozuldu"}
_SERI_AYRAC = re.compile(r"[,;\n\r|]+")
GOC_IPTAL_GEREKCESI = "Göç: eski sistemde iptal edilmiş iş"
GOC_SONUC_METNI = "Göç: eski sistemden aktarıldı (ayrıntılı sonuç kaydı yok)"


def birim_esle(ham: str | None) -> str | None:
    k = tr_normkey(ham)
    if k.upper().replace(" ", "_") in BIRIM_KODLARI:
        return k.upper().replace(" ", "_")
    return BIRIM_ESLEME.get(k)


def tur_esle(ham: str | None) -> tuple[str | None, str]:
    """(tür, karantina nedeni). Tanınmayan tür karantinadır."""
    k = tr_normkey(ham)
    if k.upper() in SERVIS_TURLERI:
        return k.upper(), ""
    if k in TUR_ESLEME:
        return TUR_ESLEME[k]
    return None, f"Eşlenemeyen iş türü: {ham}"


def durum_esle(ham: str | None) -> str | None:
    k = tr_normkey(ham)
    if k.upper() in SERVIS_DURUMLARI:
        return k.upper()
    return DURUM_ESLEME.get(k)


def kanal_esle(ham: str | None) -> str | None:
    return KANAL_ESLEME.get(tr_normkey(ham))


def oncelik_esle(ham: str | None) -> str:
    k = tr_normkey(ham)
    return k.upper() if k.upper() in ONCELIKLER else ONCELIK_ESLEME.get(k, "NORMAL")


@dataclass
class IsTaslagi:
    """Yazılmaya hazır bir servis işi. `servis_isleri` profili de bunu üretir."""

    ref: str
    eski_no: str | None
    birim: str
    tur: str
    durum: str
    oncelik: str = "NORMAL"
    kanal: str | None = None
    hesap_id: int | None = None
    adres_id: int | None = None
    musteri_ham: str | None = None
    lokasyon_ham: str | None = None
    konu: str = ""
    aciklama: str | None = None
    proje: str | None = None
    sistem: str | None = None
    acilis: datetime | None = None
    guncelleme: datetime | None = None
    tamamlanma: datetime | None = None
    kapanis: datetime | None = None
    iptal: datetime | None = None
    bekleme_baslangic: datetime | None = None
    onceki_durum: str | None = None
    seriler: list[str] = field(default_factory=list)
    olaylar: list[dict[str, Any]] = field(default_factory=list)
    atamalar: list[tuple[str, str, datetime | None]] = field(default_factory=list)


def sigdir(deger: str | None, sinir: int, ad: str, ekler: list[str]) -> str | None:
    """Kolona sığmayan metin kısaltılır; TAM hâli açıklamaya eklenir (kayıp yok)."""
    if deger is None or len(deger) <= sinir:
        return deger
    ekler.append(f"{ad} (tam): {deger}")
    return deger[: sinir - 1] + "…"


def _seriler(ham: str | None) -> list[str]:
    return [p.strip() for p in _SERI_AYRAC.split(ham or "") if p.strip()]


@dataclass
class _KarantinaYazici:
    """Karantina satırını hem uzlaşma sayısına hem profil Excel'ine yazar."""

    sonuc: AdimSonucu
    satirlar: list[dict[str, Any]]
    ref: str
    w: dict[str, Any]
    cihaz_serileri: list[str]

    def __call__(
        self,
        neden: str,
        *,
        tur: str | None = None,
        durum: str | None = None,
        kanal: str | None = None,
    ) -> None:
        w = self.w
        self.sonuc.karantinaya(self.ref, neden)
        self.satirlar.append(
            {
                "ref": self.ref,
                "eski_no": metin(w.get("WorkOrderNo")),
                "birim": birim_esle(w.get("UnitCode")) or w.get("UnitCode"),
                "tur": tur or "",
                "durum": durum or "",
                "kanal": kanal or "",
                "musteri": metin(w.get("CustomerName")),
                "lokasyon": metin(w.get("Location")),
                "konu": metin(w.get("Subject")),
                "aciklama": metin(w.get("Description")),
                "oncelik": oncelik_esle(w.get("Priority")),
                "acilis": metin(w.get("CreatedAt")),
                "kapanis": metin(w.get("ClosedAt")),
                "seri": ", ".join(_seriler(w.get("SerialNo")) + self.cihaz_serileri),
                "neden": neden,
                "eski_tur": w.get("WorkType"),
                "eski_durum": w.get("Status"),
            }
        )


def hazirla(dizin: KaynakDizini, esleyici: HesapEsleyici) -> AdimSonucu:
    """Kaynak → `IsTaslagi` listesi + karantina (profil Excel satırlarıyla) + uyarılar."""
    isler = dizin.tablo("WorkOrders")
    sonuc = AdimSonucu(KAYNAK_TABLO, HEDEF_TABLO, kaynak=len(isler))
    loglar: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for log in dizin.tablo("WorkOrderStatusLogs", zorunlu=False):
        kimlik = tamsayi(log.get("WorkOrderId"))
        if kimlik is not None:
            loglar[kimlik].append(log)
    cihazlar: dict[int, list[str]] = defaultdict(list)
    for c in dizin.tablo("WorkOrderDevices", zorunlu=False):
        kimlik = tamsayi(c.get("WorkOrderId"))
        if kimlik is not None and bit(c.get("IsActive"), varsayilan=True):
            cihazlar[kimlik].extend(_seriler(c.get("SerialNo")))
    atamalar: dict[int, list[tuple[str, str, datetime | None]]] = defaultdict(list)
    for a in dizin.tablo("WorkOrderAssignments", zorunlu=False):
        kimlik = tamsayi(a.get("WorkOrderId"))
        ad = metin(a.get("AssignedName"))
        if kimlik is None or not ad or not bit(a.get("IsActive"), varsayilan=True):
            continue
        rol = "SEF" if "sef" in tr_normkey(a.get("AssignmentRole")) else "TEKNISYEN"
        atamalar[kimlik].append((ad, rol, yerel_an(a.get("AssignedAt"))))
    karantina_satirlari: list[dict[str, Any]] = []
    gorulen: set[str] = set()

    for sira, w in enumerate(isler, start=1):
        kimlik = tamsayi(w.get("WorkOrderId"))
        if kimlik is None:
            sonuc.reddet(f"satır {sira}", "WorkOrderId yok — idempotent yüklenemez")
            continue
        ref = kaynak_ref(KAYNAK_TABLO, kimlik)
        if ref in gorulen:
            sonuc.reddet(ref, "dökümde aynı kimlik iki kez")
            continue
        gorulen.add(ref)
        ham_durum, ham_tur, ham_birim = w.get("Status"), w.get("WorkType"), w.get("UnitCode")
        karantinaya = _KarantinaYazici(sonuc, karantina_satirlari, ref, w, cihazlar.get(kimlik, []))

        birim = birim_esle(ham_birim)
        tur, tur_neden = tur_esle(ham_tur)
        durum = durum_esle(ham_durum)
        kanal_ipucu = kanal_esle(ham_durum) or kanal_esle(ham_tur)
        if birim is None:
            karantinaya(f"Eşlenemeyen birim: {ham_birim}", tur=tur, durum=durum)
            continue
        if tur is None:
            karantinaya(tur_neden, durum=durum, kanal=kanal_ipucu)
            continue
        if durum is None:
            karantinaya(f"Eşlenemeyen durum: {ham_durum}", tur=tur, kanal=kanal_ipucu)
            continue
        try:
            acilis = yerel_an(w.get("CreatedAt"))
            guncelleme = yerel_an(w.get("UpdatedAt")) or acilis
            kapanis_ham = yerel_an(w.get("ClosedAt"))
            log_satirlari = sorted(
                (
                    (an, tamsayi(x.get("StatusLogId")) or 0, x)
                    for x in loglar.get(kimlik, [])
                    if (an := yerel_an(x.get("ChangedAt"))) is not None
                ),
                key=lambda x: (x[0], x[1]),
            )
        except ValueError as exc:
            karantinaya(f"Tarih okunamadı: {exc}", tur=tur, durum=durum, kanal=kanal_ipucu)
            continue
        if acilis is None:
            karantinaya("Açılış tarihi (CreatedAt) yok", tur=tur, durum=durum, kanal=kanal_ipucu)
            continue

        ekler: list[str] = []
        konu = sigdir(metin(w.get("Subject")) or "(konu yok)", 200, "Konu", ekler)
        proje = sigdir(metin(w.get("ProjectName")), 120, "Proje", ekler)
        sistem = sigdir(metin(w.get("SystemName")), 120, "Sistem", ekler)
        aciklama_parca = [*ekler, metin(w.get("Description")) or ""]

        t = IsTaslagi(
            ref=ref,
            eski_no=metin(w.get("WorkOrderNo")),
            birim=birim,
            tur=tur,
            durum=durum,
            oncelik=oncelik_esle(w.get("Priority")),
            musteri_ham=metin(w.get("CustomerName")),
            lokasyon_ham=metin(w.get("Location")),
            konu=konu,
            proje=proje,
            sistem=sistem,
            acilis=acilis,
            guncelleme=guncelleme,
        )
        es = esleyici.esle(t.musteri_ham, t.lokasyon_ham)
        t.hesap_id, t.adres_id = es.account_id, es.address_id
        if es.belirsiz:
            sonuc.uyar(ref, "MUSTERI_BELIRSIZ", ",".join(map(str, es.adaylar)))
        elif es.account_id is None:
            sonuc.uyar(ref, "MUSTERI_ESLESMEDI", t.musteri_ham or "")

        # Olaylar ve kapanış anları kaynak log'dan.
        son_kanal: str | None = None
        onceki_ham: str | None = None
        for an, _log_id, log in log_satirlari:
            yeni_ham = metin(log.get("NewStatus"))
            k = kanal_esle(yeni_ham)
            if k:
                son_kanal = k
            yeni_k = tr_normkey(yeni_ham)
            if yeni_k in _KAPANIS_HAM and t.tamamlanma is None:
                t.tamamlanma = an
            if yeni_k in ("kapatildi", "cozuldu"):
                t.kapanis = an
            if yeni_k == "iptal":
                t.iptal = an
            if yeni_k == "beklemede":
                t.bekleme_baslangic = an
                t.onceki_durum = durum_esle(onceki_ham)
            t.olaylar.append(
                {
                    "olay_turu": "DURUM",
                    "eski_durum": durum_esle(metin(log.get("OldStatus"))),
                    "yeni_durum": durum_esle(yeni_ham),
                    "ozet": (
                        f"Durum: {metin(log.get('OldStatus')) or '-'} → {yeni_ham or '-'} "
                        "(eski sistem)"
                    )[:500],
                    "veri": {
                        "kaynak": kaynak_ref("WorkOrderStatusLogs", log.get("StatusLogId")),
                        "eski_ham": metin(log.get("OldStatus")),
                        "yeni_ham": yeni_ham,
                    },
                    "olusma_zamani": an,
                }
            )
            onceki_ham = yeni_ham

        if durum in ("TAMAMLANDI", "KAPATILDI"):
            t.tamamlanma = t.tamamlanma or kapanis_ham or guncelleme
            if durum == "KAPATILDI":
                t.kapanis = t.kapanis or kapanis_ham or t.tamamlanma
            if t.kapanis and t.tamamlanma and t.kapanis < t.tamamlanma:
                t.kapanis = t.tamamlanma
            t.kanal = son_kanal or kanal_ipucu
            if t.kanal is None:
                sonuc.uyar(ref, "SONUCSUZ_KAPALI", "çözüm kanalı bilinmiyor; sonuç yazılmadı")
        elif durum == "IPTAL":
            t.iptal = t.iptal or kapanis_ham or guncelleme
        elif durum == "BEKLEMEDE":
            t.bekleme_baslangic = t.bekleme_baslangic or guncelleme
            t.onceki_durum = t.onceki_durum or "ISLEMDE"
            if t.onceki_durum in ("BEKLEMEDE", "TAMAMLANDI", "KAPATILDI", "IPTAL"):
                t.onceki_durum = "ISLEMDE"
        if kanal_ipucu and durum not in ("TAMAMLANDI", "KAPATILDI"):
            sonuc.uyar(ref, "POC_DURUM_KANALA_TASINDI", ham_durum or ham_tur or "")
        if tr_normkey(ham_durum) == "kargoda":
            sonuc.uyar(ref, "KARGODA_ATOLYEDE", "")

        eski_no = t.eski_no or ""
        if eski_no and len(eski_no) > 24:
            aciklama_parca.insert(0, f"Eski no: {eski_no}")
            sonuc.uyar(ref, "ESKI_NO_UZUN", eski_no)
        t.aciklama = "\n\n".join(p for p in aciklama_parca if p) or None

        seriler: list[str] = []
        anahtarlar: set[str] = set()
        for s in _seriler(w.get("SerialNo")) + cihazlar.get(kimlik, []):
            anahtar = normalize_seri(s)
            if anahtar and anahtar not in anahtarlar and len(s) <= 200:
                anahtarlar.add(anahtar)
                seriler.append(s)
        t.seriler = seriler
        t.atamalar = atamalar.get(kimlik, [])
        sonuc.aktarilacak.append(t)

    sonuc.ek["karantina_satirlari"] = karantina_satirlari
    return sonuc


# --- Yazma ----------------------------------------------------------------------------


@dataclass
class YazmaBaglami:
    """Bir göç koşusunda bir kez yüklenen eşlemeler."""

    ekipmanlar: dict[tuple[str, str], list[int]]
    atama_adlari: dict[str, int | None]
    kullanilan_nolar: set[str]
    user_id: int | None = None
    sayac: dict[str, int] = field(default_factory=lambda: defaultdict(int))


async def yazma_baglami(db: AsyncSession, *, user_id: int | None = None) -> YazmaBaglami:
    ekipmanlar: dict[tuple[str, str], list[int]] = defaultdict(list)
    for eid, birim, anahtar in (
        await db.execute(
            select(ServiceEquipment.id, ServiceEquipment.birim, ServiceEquipment.serial_key).where(
                ServiceEquipment.is_deleted.is_(False),
                ServiceEquipment.is_active.is_(True),
                ServiceEquipment.merged_into_id.is_(None),
                ServiceEquipment.serial_key.is_not(None),
            )
        )
    ).all():
        ekipmanlar[(birim, anahtar)].append(eid)
    harita = await ad_esleme.onayli_harita(db, [ad_esleme.ALAN_ATAMA])
    return YazmaBaglami(
        ekipmanlar=dict(ekipmanlar),
        atama_adlari=ad_esleme.ada_gore(harita, [ad_esleme.ALAN_ATAMA]),
        kullanilan_nolar=set((await db.scalars(select(ServiceOrder.so_no))).all()),
        user_id=user_id,
    )


async def _numara(db: AsyncSession, t: IsTaslagi, bag: YazmaBaglami) -> str:
    no = t.eski_no or ""
    if no and len(no) <= 24 and no not in bag.kullanilan_nolar:
        return no
    yeni = await numara.belge_no(db, "service_order_no_seq", "SRV", t.acilis or date(2000, 1, 1))
    if no and len(no) <= 24:
        bag.sayac["eski_no_cakisti"] += 1
        t.aciklama = f"Eski no: {no}\n\n{t.aciklama or ''}".strip()
    return yeni


async def atamalari_tamamla(db: AsyncSession, so_id: int, t: IsTaslagi, bag: YazmaBaglami) -> int:
    """Onaylı adla eşleşen ama işte henüz olmayan atamaları ekler (idempotent)."""
    if not t.atamalar:
        return 0
    mevcut = (
        await db.execute(
            select(ServiceOrderAssignment.user_id, ServiceOrderAssignment.is_lead).where(
                ServiceOrderAssignment.service_order_id == so_id,
                ServiceOrderAssignment.removed_at.is_(None),
            )
        )
    ).all()
    var = {u for u, _ in mevcut}
    lider_var = any(lead for _, lead in mevcut)
    eklenen = 0
    for ad, rol, an in sorted(t.atamalar, key=lambda a: (a[2] is None, a[2] or datetime.min)):
        uid = bag.atama_adlari.get(ad_esleme.normal_ad(ad))
        if uid is None:
            bag.sayac["atama_eslesmedi"] += 1
            continue
        if uid in var:
            continue
        lider = rol == "TEKNISYEN" and not lider_var
        db.add(
            ServiceOrderAssignment(
                service_order_id=so_id,
                user_id=uid,
                rol=rol,
                is_lead=lider,
                assigned_at=an or t.acilis,
                assigned_by=bag.user_id,
            )
        )
        lider_var = lider_var or lider
        var.add(uid)
        eklenen += 1
    if eklenen:
        await db.flush()
        bag.sayac["atama_eklendi"] += eklenen
    return eklenen


async def is_yaz(db: AsyncSession, t: IsTaslagi, bag: YazmaBaglami) -> int | None:
    """Tek işi yazar. Yeni yazıldıysa kimliği, zaten varsa None döner."""
    ekipman = None
    for s in t.seriler:
        adaylar = bag.ekipmanlar.get((t.birim, normalize_seri(s)), [])
        if len(adaylar) == 1:
            ekipman = adaylar[0]
            break
    so_no = await _numara(db, t, bag)
    degerler: dict[str, Any] = {
        "so_no": so_no,
        "birim": t.birim,
        "tur": t.tur,
        "kategori": tur_kategorisi(t.tur),
        "oncelik": t.oncelik,
        "status": t.durum,
        "customer_id": t.hesap_id,
        "address_id": t.adres_id,
        "customer_name_raw": t.musteri_ham,
        "location_raw": t.lokasyon_ham,
        "reported_at": t.acilis,
        "proje": t.proje,
        "sistem": t.sistem,
        "konu": t.konu,
        "aciklama": t.aciklama,
        "equipment_id": ekipman,
        "source_system": GOC_SISTEMI,
        "source_ref": t.ref,
        "created_by": bag.user_id,
        "updated_by": bag.user_id,
    }
    if t.acilis is not None:
        degerler["created_at"] = t.acilis
        degerler["updated_at"] = max(t.guncelleme or t.acilis, t.acilis)
    if t.durum in ("TAMAMLANDI", "KAPATILDI"):
        degerler["completed_at"] = t.tamamlanma
        degerler["first_completed_at"] = t.tamamlanma
    if t.durum == "KAPATILDI":
        degerler["closed_at"] = t.kapanis
    if t.durum == "IPTAL":
        degerler["cancelled_at"] = t.iptal
        degerler["cancel_reason"] = GOC_IPTAL_GEREKCESI
    stmt = (
        insert(ServiceOrder.__table__)
        .values(**degerler)
        .on_conflict_do_nothing(constraint="uq_so_kaynak")
        .returning(ServiceOrder.__table__.c.id)
    )
    so_id = (await db.execute(stmt)).scalar()
    if so_id is None:
        mevcut = await db.scalar(
            select(ServiceOrder.id).where(
                ServiceOrder.source_system == GOC_SISTEMI, ServiceOrder.source_ref == t.ref
            )
        )
        if mevcut is not None:
            await atamalari_tamamla(db, mevcut, t, bag)
        return None
    bag.kullanilan_nolar.add(so_no)

    olaylar = [
        {
            "service_order_id": so_id,
            "olay_turu": "OLUSTUR",
            "ozet": f"Eski sistemden aktarıldı ({t.eski_no or so_no})"[:500],
            "veri": {"kaynak": t.ref, "eski_no": t.eski_no},
            "olusma_zamani": t.acilis,
        },
        *({"service_order_id": so_id, **o} for o in t.olaylar if o.get("olusma_zamani")),
    ]
    await db.execute(insert(ServiceOrderEvent.__table__), olaylar)

    for s in t.seriler:
        db.add(
            ServiceOrderSerial(
                service_order_id=so_id,
                seri_no=s,
                seri_norm=normalize_seri(s),
                created_by=bag.user_id,
            )
        )
    if t.durum in ("TAMAMLANDI", "KAPATILDI") and t.kanal in COZUM_KANALLARI:
        db.add(
            ServiceResult(
                service_order_id=so_id,
                sonuc="COZULDU",
                cozum_kanali=t.kanal,
                yapilan_islem=GOC_SONUC_METNI,
                created_by=bag.user_id,
            )
        )
        bag.sayac["sonuc"] += 1
    if t.durum == "BEKLEMEDE":
        db.add(
            ServiceHold(
                service_order_id=so_id,
                neden="DIGER",
                aciklama="Göç: eski sistemde beklemede (neden kaydı yok)",
                onceki_durum=t.onceki_durum or "ISLEMDE",
                started_at=t.bekleme_baslangic or t.acilis,
                started_by=bag.user_id,
                sla_durdurur=False,
            )
        )
    await db.flush()
    await atamalari_tamamla(db, so_id, t, bag)
    return so_id


async def hazirla_db(db: AsyncSession, dizin: KaynakDizini) -> AdimSonucu:
    sonuc = hazirla(dizin, await hesap_esleyici(db))
    var = await mevcut_refler(db, HEDEF_TABLO, KAYNAK_TABLO)
    sonuc.mevcut = sum(1 for t in sonuc.aktarilacak if t.ref in var)
    sonuc.yeni = len(sonuc.aktarilacak) - sonuc.mevcut
    return sonuc


async def yukle(db: AsyncSession, sonuc: AdimSonucu, *, user_id: int | None = None) -> AdimSonucu:
    bag = await yazma_baglami(db, user_id=user_id)
    yeni = 0
    for t in sonuc.aktarilacak:
        if await is_yaz(db, t, bag) is not None:
            yeni += 1
    sonuc.yeni = yeni
    sonuc.mevcut = len(sonuc.aktarilacak) - yeni
    sonuc.ek["sayac"] = dict(bag.sayac)
    await audit.log(
        db,
        "service_orders",
        "goc.servis_isleri",
        new_value={**sonuc.ozet(), **dict(bag.sayac)},
        user_id=user_id,
    )
    return sonuc


# Profil Excel'inin (karantina → insan kararı → İçe Aktarma) başlıkları.
KARANTINA_BASLIKLARI = [
    "Kaynak Ref",
    "Eski No",
    "Birim",
    "Tür",
    "Durum",
    "Çözüm Kanalı",
    "Hesap Id",
    "Lokasyon Id",
    "Müşteri",
    "Lokasyon",
    "Konu",
    "Açıklama",
    "Öncelik",
    "Açılış",
    "Kapanış",
    "Seri No",
    "Karantina Nedeni",
    "Eski Tür",
    "Eski Durum",
]


def karantina_excel_satirlari(sonuc: AdimSonucu) -> list[list[Any]]:
    return [
        [
            k["ref"],
            k["eski_no"],
            k["birim"],
            k["tur"],
            k["durum"],
            k["kanal"],
            None,
            None,
            k["musteri"],
            k["lokasyon"],
            k["konu"],
            k["aciklama"],
            k["oncelik"],
            k["acilis"],
            k["kapanis"],
            k["seri"],
            k["neden"],
            k["eski_tur"],
            k["eski_durum"],
        ]
        for k in sonuc.ek.get("karantina_satirlari", [])
    ]
