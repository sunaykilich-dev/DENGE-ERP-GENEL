"""Serbest metin müşteri/lokasyon → hesap/tesis eşleştirmesi (TS-171, E14-09 Faz 1).

**Neden var:** eski sistem müşteriyi ve tesisi serbest metinle tutuyordu
(`MaintenanceContracts.CustomerName`, `SecurityDevices.CustomerName/Location`);
aynı müşteri onlarca yazımla geçiyor. Göç bu metni bir hesaba bağlamadan
kapsam, PB üretimi ve müşteri bazlı rapor doğru çıkmaz.

İki parça:

- `HesapEsleyici` — DETERMİNİSTİK ve tahminsiz eşleştirici. Yalnız kesin
  yöntemler bağ kurar: onaylı takma ad (`account_aliases`), tek hesaba düşen
  `unvan_anahtari`, tek hesaba ait tesis adı (`site_key`). İki hesaba düşen
  ad BELİRSİZ'dir ve insana döner; trigram benzerliği ASLA bağ kurmaz.
  Göç betikleri (kütük, servis işi, bakım sözleşmesi) ve aday listesi aynı
  sınıfı kullanır — üç ayrı eşleştirme kuralı aynı metni üç farklı hesaba
  bağlardı.
- `eslestirme_adaylari` — eşleşmemiş kayıtların aday listesi (Excel'e
  dökülür). Önerinin yöntemi yazılır; `trgm` yalnız ÖNERİDİR. Karar insanın:
  dosya `Onay=E` ile `musteri_eslestirme` içe aktarma profiline yüklenir.

Bu modül YAZMAZ (kabul 1: aday üretimi veriyi değiştirmez).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import Account, AccountAlias, Address, MaintenanceContract, ServiceEquipment
from app.services.teknik_servis import ana_veri, kapsam

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import User

# Eşleştirme yöntemleri (aday Excel'inde ve göç raporunda yazılır).
YONTEM_TAKMA_AD = "TAKMA_AD"
YONTEM_UNVAN = "UNVAN_ANAHTARI"
YONTEM_TESIS = "TESIS_ADI"
YONTEM_TRGM = "TRGM_ONERI"
YONTEM_BELIRSIZ = "BELIRSIZ"
YONTEM_YOK = "YOK"

# Faz 1 kaynakları (E14-09). Faz 2 (servis işi, plan, teklif, kiralama,
# atölye) TS-208'de bu sözlüğe eklenir.
ESLESTIRME_KAYNAKLARI: dict[str, str] = {
    "sozlesme": "maintenance_contracts",
    "ekipman": "service_equipment",
}
# Faz 1 ekipman kapsamı yalnız Güvenlik birimidir.
FAZ1_EKIPMAN_BIRIMI = "GUVENLIK"


@dataclass(frozen=True)
class Eslesme:
    """Bir ham metin çiftinin eşleşme sonucu."""

    account_id: int | None
    address_id: int | None
    yontem: str
    adaylar: tuple[int, ...] = ()

    @property
    def belirsiz(self) -> bool:
        return self.yontem == YONTEM_BELIRSIZ


@dataclass
class HesapEsleyici:
    """Bellekte kurulmuş eşleştirme tabloları; `hesap_esleyici(db)` ile yüklenir.

    Saf sınıftır (DB çağrısı yapmaz): göç hazırlama adımı binlerce satırı
    tek sorgu turuyla eşleyebilsin ve birim testlerinde DB'siz sınansın.
    """

    unvan: dict[str, list[int]]
    takma: dict[str, tuple[int, int | None]]
    tesis: dict[str, list[tuple[int, int]]]

    def esle(self, musteri: str | None, lokasyon: str | None = None) -> Eslesme:
        mk = ana_veri.unvan_anahtari(musteri)
        lk = ana_veri.unvan_anahtari(lokasyon)
        hesap: int | None = None
        adres: int | None = None
        yontem = YONTEM_YOK

        if mk and mk in self.takma:
            hesap, adres = self.takma[mk]
            yontem = YONTEM_TAKMA_AD
        elif mk and mk in self.unvan:
            idler = sorted(set(self.unvan[mk]))
            if len(idler) > 1:
                return Eslesme(None, None, YONTEM_BELIRSIZ, tuple(idler))
            hesap, yontem = idler[0], YONTEM_UNVAN
        elif mk and mk in self.tesis:
            ciftler = sorted(set(self.tesis[mk]))
            hesaplar = sorted({h for h, _ in ciftler})
            if len(hesaplar) > 1:
                return Eslesme(None, None, YONTEM_BELIRSIZ, tuple(hesaplar))
            hesap = hesaplar[0]
            adres = ciftler[0][1] if len(ciftler) == 1 else None
            yontem = YONTEM_TESIS

        # Lokasyon metni tesisi belirler; hesap henüz yoksa tek hesaba ait
        # tesis hesabı da belirler (kütükte Location çoğu kez tesis adıdır).
        if adres is None and lk:
            if lk in self.takma:
                t_hesap, t_adres = self.takma[lk]
                if t_adres is not None and (hesap is None or t_hesap == hesap):
                    if hesap is None:
                        yontem = YONTEM_TAKMA_AD
                    hesap, adres = t_hesap, t_adres
            if adres is None and lk in self.tesis:
                uygun = sorted({(h, a) for h, a in self.tesis[lk] if hesap is None or h == hesap})
                if len(uygun) == 1:
                    if hesap is None:
                        yontem = YONTEM_TESIS
                    hesap, adres = uygun[0]
                elif hesap is None and len({h for h, _ in uygun}) > 1:
                    return Eslesme(
                        None, None, YONTEM_BELIRSIZ, tuple(sorted({h for h, _ in uygun}))
                    )
        return Eslesme(hesap, adres, yontem)


async def hesap_esleyici(db: AsyncSession) -> HesapEsleyici:
    """Aktif müşteri hesapları, takma adlar ve aktif tesislerden eşleyici kurar.

    Birleştirilmiş (silinmiş) hesabın takma adı HEDEF hesabı gösterir; hedefi
    de silinmişse takma ad yok sayılır (uydurma bağ yok).
    """
    unvan: dict[str, list[int]] = defaultdict(list)
    for hesap_id, baslik in (
        await db.execute(
            select(Account.id, Account.title).where(
                Account.is_musteri.is_(True),
                Account.is_deleted.is_(False),
                Account.is_active.is_(True),
            )
        )
    ).all():
        anahtar = ana_veri.unvan_anahtari(baslik)
        if anahtar:
            unvan[anahtar].append(hesap_id)

    hesap_durumu = {
        h.id: h
        for h in (
            await db.scalars(select(Account).where(Account.id.in_(select(AccountAlias.account_id))))
        ).all()
    }
    takma: dict[str, tuple[int, int | None]] = {}
    for t in (await db.scalars(select(AccountAlias))).all():
        hesap = hesap_durumu.get(t.account_id)
        hedef = t.account_id
        adres = t.address_id
        if hesap is not None and hesap.is_deleted:
            if not hesap.merged_into_id:
                continue
            hedef, adres = hesap.merged_into_id, None
        takma[t.alias_key] = (hedef, adres)

    tesis: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for adres_id, hesap_id, site_key in (
        await db.execute(
            select(Address.id, Address.account_id, Address.site_key)
            .join(Account, Account.id == Address.account_id)
            .where(
                Address.kind == "TESIS",
                Address.is_active.is_(True),
                Address.site_key.is_not(None),
                Account.is_deleted.is_(False),
            )
        )
    ).all():
        tesis[site_key].append((hesap_id, adres_id))
    return HesapEsleyici(unvan=dict(unvan), takma=takma, tesis=dict(tesis))


# --- Aday listesi ------------------------------------------------------------------

ADAY_BASLIKLARI = [
    "Kaynak Tablo",
    "Kaynak Id",
    "Ham Müşteri",
    "Ham Lokasyon",
    "Önerilen Hesap Id",
    "Önerilen Hesap",
    "Yöntem",
    "Önerilen Lokasyon Id",
    "Önerilen Lokasyon",
    "Onay (E/H)",
    "Hedef Hesap Id",
    "Hedef Lokasyon Id",
    "Yeni Tesis Adı",
]


async def _kaynak_satirlari(db: AsyncSession, user: User, kaynak: str) -> list[dict[str, Any]]:
    if kaynak == "sozlesme":
        stmt = select(MaintenanceContract).where(
            MaintenanceContract.is_deleted.is_(False),
            (MaintenanceContract.account_id.is_(None)) | (MaintenanceContract.address_id.is_(None)),
        )
        stmt = kapsam.kapsam_birim(stmt, user, MaintenanceContract.birim)
        return [
            {
                "tablo": "maintenance_contracts",
                "id": s.id,
                "musteri": s.customer_name_raw,
                "lokasyon": s.site_name_raw,
                "hesap_id": s.account_id,
                "adres_id": s.address_id,
            }
            for s in (await db.scalars(stmt.order_by(MaintenanceContract.id))).all()
        ]
    if kaynak == "ekipman":
        stmt = select(ServiceEquipment).where(
            ServiceEquipment.is_deleted.is_(False),
            ServiceEquipment.merged_into_id.is_(None),
            ServiceEquipment.birim == FAZ1_EKIPMAN_BIRIMI,
            (ServiceEquipment.account_id.is_(None)) | (ServiceEquipment.address_id.is_(None)),
        )
        stmt = kapsam.kapsam_birim(stmt, user, ServiceEquipment.birim)
        return [
            {
                "tablo": "service_equipment",
                "id": e.id,
                "musteri": e.customer_name_raw,
                "lokasyon": e.location_raw,
                "hesap_id": e.account_id,
                "adres_id": e.address_id,
            }
            for e in (await db.scalars(stmt.order_by(ServiceEquipment.id))).all()
        ]
    raise ValueError(f"Bilinmeyen eşleştirme kaynağı: {kaynak}")


async def eslestirme_adaylari(
    db: AsyncSession, user: User, kaynak: str = "sozlesme"
) -> list[dict[str, Any]]:
    """Serbest metin müşteri/lokasyon → hesap/tesis aday listesi (`hesap.birlestir`).

    Hesabı ya da tesisi boş her kayıt bir satırdır. Öneri sırası: kayıtta
    zaten bağlı hesap → `HesapEsleyici` (takma ad / unvan / tesis) → trigram
    (yalnız öneri, `TRGM_ONERI`). Belirsiz satırda öneri BOŞ bırakılır,
    aday hesap kimlikleri yöntem sütununda listelenir (insana döner).
    Müşteri ve lokasyon metni boş satırlar `musterisiz=True` ile işaretlenir
    (Excel'de ayrı sayfa, kabul 4). Hiçbir şey yazmaz.
    """
    satirlar = await _kaynak_satirlari(db, user, kaynak)
    esleyici = await hesap_esleyici(db)
    hesap_adlari: dict[int, str] = {}
    adres_adlari: dict[int, str] = {}
    trgm_onbellek: dict[str, dict[str, Any] | None] = {}
    sonuc: list[dict[str, Any]] = []

    for s in satirlar:
        musteri, lokasyon = s["musteri"], s["lokasyon"]
        satir = {
            **s,
            "onerilen_hesap_id": s["hesap_id"],
            "yontem": "MEVCUT" if s["hesap_id"] else YONTEM_YOK,
            "onerilen_adres_id": s["adres_id"],
            "musterisiz": not (musteri or "").strip() and not (lokasyon or "").strip(),
        }
        if satir["musterisiz"]:
            sonuc.append(satir)
            continue
        if s["hesap_id"] is None or s["adres_id"] is None:
            es = esleyici.esle(musteri, lokasyon)
            if es.belirsiz:
                satir["yontem"] = f"{YONTEM_BELIRSIZ}: " + ", ".join(str(a) for a in es.adaylar)
            elif es.account_id is not None and (
                s["hesap_id"] is None or es.account_id == s["hesap_id"]
            ):
                satir["onerilen_hesap_id"] = es.account_id
                satir["onerilen_adres_id"] = s["adres_id"] or es.address_id
                if s["hesap_id"] is None:
                    satir["yontem"] = es.yontem
            elif s["hesap_id"] is None and (musteri or "").strip():
                anahtar = musteri.strip()
                if anahtar not in trgm_onbellek:
                    adaylar = await ana_veri.benzer_musteriler(db, anahtar)
                    trgm_onbellek[anahtar] = adaylar[0] if adaylar else None
                aday = trgm_onbellek[anahtar]
                if aday is not None:
                    satir["onerilen_hesap_id"] = aday["id"]
                    satir["yontem"] = YONTEM_TRGM
        sonuc.append(satir)

    hesap_idler = {r["onerilen_hesap_id"] for r in sonuc if r["onerilen_hesap_id"]}
    adres_idler = {r["onerilen_adres_id"] for r in sonuc if r["onerilen_adres_id"]}
    if hesap_idler:
        hesap_adlari = dict(
            (await db.execute(select(Account.id, Account.title).where(Account.id.in_(hesap_idler))))
            .tuples()
            .all()
        )
    if adres_idler:
        adres_adlari = dict(
            (
                await db.execute(
                    select(Address.id, Address.site_name).where(Address.id.in_(adres_idler))
                )
            )
            .tuples()
            .all()
        )
    for r in sonuc:
        r["onerilen_hesap"] = hesap_adlari.get(r["onerilen_hesap_id"])
        r["onerilen_adres"] = adres_adlari.get(r["onerilen_adres_id"])
    return sonuc


def aday_satiri(r: dict[str, Any]) -> list[Any]:
    """Aday sözlüğü → Excel satırı (`ADAY_BASLIKLARI` sırası; onay sütunları boş)."""
    return [
        r["tablo"],
        r["id"],
        r["musteri"],
        r["lokasyon"],
        r["onerilen_hesap_id"],
        r.get("onerilen_hesap"),
        r["yontem"],
        r["onerilen_adres_id"],
        r.get("onerilen_adres"),
        None,
        None,
        None,
        None,
    ]


async def eslestirme_ozeti(db: AsyncSession, user: User) -> dict[str, dict[str, int]]:
    """Ekran özeti: kaynak başına eşleşmemiş / müşterisiz / belirsiz sayıları.

    Sayılar `eslestirme_adaylari` ile AYNI listeden sayılır (sayı = liste).
    """
    ozet: dict[str, dict[str, int]] = {}
    for kaynak in ESLESTIRME_KAYNAKLARI:
        satirlar = await eslestirme_adaylari(db, user, kaynak)
        ozet[kaynak] = {
            "eslesmemis": len(satirlar),
            "hesapsiz": sum(1 for r in satirlar if r["hesap_id"] is None),
            "musterisiz": sum(1 for r in satirlar if r["musterisiz"]),
            "belirsiz": sum(1 for r in satirlar if str(r["yontem"]).startswith(YONTEM_BELIRSIZ)),
            "kesin_oneri": sum(
                1 for r in satirlar if r["yontem"] in (YONTEM_TAKMA_AD, YONTEM_UNVAN, YONTEM_TESIS)
            ),
        }
    return ozet
