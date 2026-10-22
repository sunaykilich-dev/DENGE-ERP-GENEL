"""Hesap ve lokasyon birleştirme (E14-12, E14-07).

Maddeler: TS-192. Doldurur: D3-C (iskelet D3-S).

Mantık `migration/hesap_birlestir.py` betiğinden servise taşındı (betik
tarihî `BIRLESMELER` listesiyle kalır; servisi çağıracak biçime dönüşümü göç
paketinin — `mg/*` Dalga 3'te D3-G — işidir). Betikten farkları:

- **Clock ve kullanıcı** parametresi; `datetime.now` yok.
- **Lokasyon** (`tur='LOKASYON'`) birleştirmesi: aynı hesabın iki tesisi.
- **Hak ediş zinciri koruması:** kaynak hesabın `work_orders`,
  `work_order_items`, `partner_settlements`, `settlement_lines` ya da
  `installation_partners` referansı varsa 409 — mobilite hak ediş kaydı olan
  hesap bu ekrandan birleştirilemez (yalnız `sistem.goc` betiği).
- **Önizleme hiçbir şey yazmaz**, taşınacak satır sayılarını ve engelleri
  (hedefte aynı adlı aktif tesis — `uq_addresses_tesis_aktif`) gösterir.
  Uygulama, istemcinin gördüğü sayıları (`beklenen`) güncel önizlemeyle
  karşılaştırır; arada veri değiştiyse 409 "yeniden önizleyin".
- **Tek transaction + satır kilidi** (`with_for_update`, kimlik sırasıyla):
  ikinci UPDATE'te hata olursa hiçbir satır taşınmaz (çağıran commit etmez).
- Kaynak unvan/tesis adı `account_aliases`'e `BIRLESTIRME` takma adı olur
  (eski yazımla arayan hedefi bulur); `account_merges` satırı açılır.

Referans kolonları ŞEMADAN okunur (elle liste yok): yeni bir tablo `accounts`
ya da `addresses`'e FK eklediğinde birleştirme onu kendiliğinden taşır.
Canlı hesap kartı (`/kart`) değişmez; servis işi kapsam anlık görüntüsü
(`service_orders.coverage_snapshot`) ve hak ediş tabloları YAZILMAZ.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text

from app.models import Account, AccountMerge, Address
from app.models.account import BIRLESTIRME_TURLERI
from app.services.teknik_servis import ana_veri

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

# Mobilite hak ediş zinciri: bu tablolarda kaynak hesaba referans varsa 409.
HAKEDIS_TABLOLARI = frozenset(
    {
        "work_orders",
        "work_order_items",
        "partner_settlements",
        "settlement_lines",
        "settlement_disputes",
        "partner_tariffs",
        "installation_partners",
    }
)

# FK'si olmayan, elle taşınan bağlar (betikteki `EK_BAGLAR` ile aynı).
EK_BAGLAR = {
    "HESAP": (
        ("attachments", "entity_id", "entity = 'accounts'"),
        ("devices", "current_customer_id", None),
    ),
    "LOKASYON": (),
}

# Kaynaktan hedefe YALNIZ hedefte boşsa kopyalanan alanlar (betikle aynı).
TASINAN_ALANLAR = (
    "tax_no",
    "tax_office",
    "iban",
    "email",
    "phone",
    "region",
    "segment",
    "parent_dealer_id",
    "sales_rep_id",
)
ROL_BAYRAKLARI = ("is_musteri", "is_bayi", "is_montaj_noktasi", "is_tedarikci")
GEREKCE_ASGARI = 5

_HEDEF_TABLO = {"HESAP": "accounts", "LOKASYON": "addresses"}


class BirlestirmeHatasi(ValueError):
    """`kod` HTTP durumu (400 girdi, 404 kapsam, 409 kural); `veri` 409 gövdesine."""

    def __init__(self, mesaj: str, *, kod: int = 400, veri: dict[str, Any] | None = None):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.kod = kod
        self.veri = veri or {}


async def referans_kolonlari(db: AsyncSession, tablo: str) -> list[tuple[str, str]]:
    """`tablo.id`'ye bakan (tablo, kolon) çiftleri — şemadan okunur."""
    sonuc = await db.execute(
        text(
            """
            select c.conrelid::regclass::text as tablo, a.attname as kolon
            from pg_constraint c
            join unnest(c.conkey) with ordinality k(attnum, ord) on true
            join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.attnum
            where c.contype = 'f' and c.confrelid = cast(:t as regclass)
              and array_length(c.conkey, 1) = 1
            order by 1, 2
            """
        ),
        {"t": tablo},
    )
    return [(r.tablo, r.kolon) for r in sonuc]


async def _sayim(db: AsyncSession, tablo: str, kolon: str, kimlik: int, kosul: str | None) -> int:
    ek = f" and {kosul}" if kosul else ""
    return int(
        await db.scalar(
            text(f"select count(*) from {tablo} where {kolon} = :id{ek}"),  # noqa: S608
            {"id": kimlik},
        )
        or 0
    )


def _tur_dogrula(tur: str) -> str:
    if tur not in BIRLESTIRME_TURLERI:
        raise BirlestirmeHatasi(f"Birleştirme türü {BIRLESTIRME_TURLERI} içinden olmalı")
    return tur


async def _kayitlar(
    db: AsyncSession, tur: str, kaynak_id: int, hedef_id: int, user: User, *, kilitle: bool
) -> tuple[Any, Any]:
    """Kaynak ve hedefi kapsamla getirir (kapsam dışı 404), gerekirse kilitler."""
    if kaynak_id == hedef_id:
        raise BirlestirmeHatasi("Kaynak ile hedef aynı kayıt olamaz")
    model = Account if tur == "HESAP" else Address
    if kilitle:
        # Kimlik sırasıyla kilit: iki ters yönlü birleştirme kilitlenmesin.
        await db.execute(
            select(model.id)
            .where(model.id.in_(sorted((kaynak_id, hedef_id))))
            .order_by(model.id)
            .with_for_update()
        )
    try:
        if tur == "HESAP":
            kaynak = await ana_veri.kapsamli_hesap(db, user, kaynak_id)
            hedef = await ana_veri.kapsamli_hesap(db, user, hedef_id)
        else:
            kaynak = await ana_veri.kapsamli_lokasyon(db, user, kaynak_id)
            hedef = await ana_veri.kapsamli_lokasyon(db, user, hedef_id)
    except ana_veri.AnaVeriHatasi as exc:
        raise BirlestirmeHatasi(exc.mesaj, kod=exc.kod) from exc
    if kilitle:
        await db.refresh(kaynak)
        await db.refresh(hedef)
    if tur == "HESAP":
        if not hedef.is_active:
            raise BirlestirmeHatasi("Hedef hesap pasif; pasif hesaba birleştirilemez")
    else:
        if hedef.account_id != kaynak.account_id:
            raise BirlestirmeHatasi("Lokasyonlar aynı hesaba ait olmalı")
        if not hedef.is_active:
            raise BirlestirmeHatasi("Hedef lokasyon pasif; pasif lokasyona birleştirilemez")
    return kaynak, hedef


def _ad(tur: str, kayit: Any) -> str | None:
    return kayit.title if tur == "HESAP" else (kayit.site_name or kayit.label)


async def onizle(
    db: AsyncSession, tur: str, kaynak_id: int, hedef_id: int, *, user: User, _kilitle: bool = False
) -> dict[str, Any]:
    """Birleştirmenin önizlemesi — hiçbir şey YAZMAZ.

    Döner: taşınacak satırlar (`tablo.kolon → adet`), engeller (varsa uygula
    409 verir), uyarılar, hedefte doldurulacak alanlar ve eklenecek roller.
    """
    tur = _tur_dogrula(tur)
    kaynak, hedef = await _kayitlar(db, tur, kaynak_id, hedef_id, user, kilitle=_kilitle)
    tasinacak: dict[str, int] = {}
    hakedis: dict[str, int] = {}
    for tablo, kolon in await referans_kolonlari(db, _HEDEF_TABLO[tur]):
        adet = await _sayim(db, tablo, kolon, kaynak.id, None)
        if not adet:
            continue
        if tur == "HESAP" and tablo in HAKEDIS_TABLOLARI:
            hakedis[f"{tablo}.{kolon}"] = adet
        tasinacak[f"{tablo}.{kolon}"] = adet
    for tablo, kolon, kosul in EK_BAGLAR[tur]:
        adet = await _sayim(db, tablo, kolon, kaynak.id, kosul)
        if adet:
            tasinacak[f"{tablo}.{kolon}"] = adet

    engeller: list[str] = []
    uyarilar: list[str] = []
    if hakedis:
        engeller.append(
            "Mobilite hak ediş kaydı olan hesap bu ekrandan birleştirilemez "
            "(yalnız sistem göç betiğiyle)."
        )
    cakisan_tesisler: list[dict[str, Any]] = []
    if tur == "HESAP":
        kaynak_tesisleri = (
            await db.scalars(
                select(Address).where(
                    Address.account_id == kaynak.id,
                    Address.kind == "TESIS",
                    Address.is_active.is_(True),
                )
            )
        ).all()
        hedef_anahtarlari = set(
            (
                await db.scalars(
                    select(Address.site_key).where(
                        Address.account_id == hedef.id,
                        Address.kind == "TESIS",
                        Address.is_active.is_(True),
                    )
                )
            ).all()
        )
        cakisan_tesisler = [
            {"id": a.id, "tesis_adi": a.site_name}
            for a in kaynak_tesisleri
            if a.site_key and a.site_key in hedef_anahtarlari
        ]
        if cakisan_tesisler:
            engeller.append(
                "Hedefte aynı adlı aktif tesis var; önce tesisleri birleştirin "
                "(tesis birleştirmesi önerilir, otomatik yapılmaz)."
            )
        if not kaynak.is_active:
            uyarilar.append("Kaynak hesap pasif.")
        doldurulacak = {
            a: _json(getattr(kaynak, a))
            for a in TASINAN_ALANLAR
            if getattr(kaynak, a) and not getattr(hedef, a)
        }
        roller = [r for r in ROL_BAYRAKLARI if getattr(kaynak, r) and not getattr(hedef, r)]
    else:
        doldurulacak, roller = {}, []
        if not kaynak.is_active:
            uyarilar.append("Kaynak lokasyon zaten pasif.")
    return {
        "tur": tur,
        "kaynak": {"id": kaynak.id, "ad": _ad(tur, kaynak)},
        "hedef": {"id": hedef.id, "ad": _ad(tur, hedef)},
        "tasinacak": tasinacak,
        "hakedis_referanslari": hakedis,
        "cakisan_tesisler": cakisan_tesisler,
        "engeller": engeller,
        "uyarilar": uyarilar,
        "doldurulacak": doldurulacak,
        "eklenen_roller": roller,
    }


def _json(deger: Any) -> Any:
    if deger is None or isinstance(deger, str | int | float | bool):
        return deger
    return str(deger)


async def uygula(
    db: AsyncSession,
    tur: str,
    kaynak_id: int,
    hedef_id: int,
    *,
    gerekce: str,
    beklenen: dict[str, int] | None,
    user: User,
    clock: Clock,
) -> AccountMerge:
    """Birleştirmeyi tek transaction'da uygular; commit ÇAĞIRANIN işidir.

    Sıra: kilit → güncel önizleme → engel (409) → beklenen sayı kontrolü (409)
    → referans UPDATE'leri → kaynak yumuşak silme/pasifleme → takma ad →
    `account_merges`. Herhangi bir adımda hata = çağıran geri alır, hiçbir
    satır taşınmaz.
    """
    metin = (gerekce or "").strip()
    if len(metin) < GEREKCE_ASGARI:
        raise BirlestirmeHatasi(f"Gerekçe zorunlu (en az {GEREKCE_ASGARI} karakter)")
    plan = await onizle(db, tur, kaynak_id, hedef_id, user=user, _kilitle=True)
    if plan["engeller"]:
        raise BirlestirmeHatasi(
            plan["engeller"][0],
            kod=409,
            veri={
                "engeller": plan["engeller"],
                "hakedis_referanslari": plan["hakedis_referanslari"],
                "cakisan_tesisler": plan["cakisan_tesisler"],
            },
        )
    if beklenen is not None and dict(beklenen) != plan["tasinacak"]:
        raise BirlestirmeHatasi(
            "Veri değişti, yeniden önizleyin.",
            kod=409,
            veri={"guncel": plan["tasinacak"]},
        )

    model = Account if tur == "HESAP" else Address
    kaynak = await db.get(model, kaynak_id)
    hedef = await db.get(model, hedef_id)
    sayac: dict[str, int] = {}
    for tablo, kolon in await referans_kolonlari(db, _HEDEF_TABLO[tur]):
        sonuc = await db.execute(
            text(f"update {tablo} set {kolon} = :hedef where {kolon} = :kaynak"),  # noqa: S608
            {"hedef": hedef_id, "kaynak": kaynak_id},
        )
        if sonuc.rowcount:
            sayac[f"{tablo}.{kolon}"] = sonuc.rowcount
    for tablo, kolon, kosul in EK_BAGLAR[tur]:
        ek = f" and {kosul}" if kosul else ""
        sonuc = await db.execute(
            text(f"update {tablo} set {kolon} = :hedef where {kolon} = :kaynak{ek}"),  # noqa: S608
            {"hedef": hedef_id, "kaynak": kaynak_id},
        )
        if sonuc.rowcount:
            sayac[f"{tablo}.{kolon}"] = sonuc.rowcount
    if tur == "HESAP":
        # Kaynak hedefin bayisi görünüyorsa kendine işaret eden kayıt doğar.
        await db.execute(
            text(
                "update accounts set parent_dealer_id = null"
                " where id = :hedef and parent_dealer_id = :hedef"
            ),
            {"hedef": hedef_id},
        )
    # Ham SQL güncellemesi oturumdaki nesneleri bayatlatır: iki kaydı açıkça
    # yeniden yükle (`expire_all` kullanıcı nesnesini de bayatlatır; async
    # oturumda bayat özniteliğe dokunmak örtük IO'dur).
    await db.refresh(kaynak)
    await db.refresh(hedef)

    an = clock.now()
    if tur == "HESAP":
        for rol in plan["eklenen_roller"]:
            setattr(hedef, rol, True)
        for alan in plan["doldurulacak"]:
            setattr(hedef, alan, getattr(kaynak, alan))
        hedef.updated_by = user.id
        kaynak.is_deleted = True
        kaynak.deleted_at = an
        kaynak.is_active = False
        kaynak.merged_into_id = hedef.id
        not_metni = f"#{hedef.id} {hedef.title} ile birleştirildi ({an.date().isoformat()})."
        kaynak.notes = f"{kaynak.notes}\n{not_metni}" if kaynak.notes else not_metni
        kaynak.updated_by = user.id
        takma_hesap, takma_adres, takma_metin = hedef.id, None, kaynak.title
        tablo_adi = "accounts"
    else:
        kaynak.is_active = False
        kaynak.updated_by = user.id
        takma_hesap, takma_adres = hedef.account_id, hedef.id
        takma_metin = kaynak.site_name or kaynak.label
        tablo_adi = "addresses"
    await db.flush()

    if ana_veri.unvan_anahtari(takma_metin) and ana_veri.unvan_anahtari(
        takma_metin
    ) != ana_veri.unvan_anahtari(_ad(tur, hedef)):
        try:
            await ana_veri.takma_ad_ekle(
                db,
                account_id=takma_hesap,
                alias_text=takma_metin,
                kaynak="BIRLESTIRME",
                address_id=takma_adres,
                kaynak_tablo=tablo_adi,
                user_id=user.id,
            )
        except ana_veri.AnaVeriHatasi:
            pass  # yazım zaten bir hedefe bağlı: takma ad global tekildir

    kayit = AccountMerge(
        tur=tur,
        kaynak_id=kaynak_id,
        hedef_id=hedef_id,
        gerekce=metin,
        onizleme=dict(beklenen) if beklenen is not None else plan["tasinacak"],
        tasinan=sayac,
        doldurulan_alanlar=plan["doldurulacak"] or None,
        eklenen_roller=plan["eklenen_roller"] or None,
        created_by=user.id,
    )
    db.add(kayit)
    await db.flush()
    return kayit


def kayit_satiri(k: AccountMerge) -> dict[str, Any]:
    return {
        "id": k.id,
        "tur": k.tur,
        "kaynak_id": k.kaynak_id,
        "hedef_id": k.hedef_id,
        "gerekce": k.gerekce,
        "onizleme": k.onizleme,
        "tasinan": k.tasinan,
        "doldurulan_alanlar": k.doldurulan_alanlar,
        "eklenen_roller": k.eklenen_roller,
        "created_by": k.created_by,
        "created_at": k.created_at,
    }
