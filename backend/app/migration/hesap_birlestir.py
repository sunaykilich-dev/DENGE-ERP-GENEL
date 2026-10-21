"""Mükerrer hesapları birleştirir.

    uv run python -m app.migration.hesap_birlestir            # ÖNİZLEME
    uv run python -m app.migration.hesap_birlestir --uygula   # yazar

Neden gerekiyor: göç iki kaynaktan (hak ediş + takip platformu) beslendi ve
aynı firma bazen iki kayda düştü. İki ayrı sebep var, ikisi de bu betikle
çözülüyor:

1. **Aynı firma, iki rol.** ÇAMKIRAN kendi aracına kendi montajını yapıyor;
   kaynakta biri "müşteri" biri "montaj noktası" olarak iki satır. ERP'nin
   hesap modeli tam bunun için bayrak seti ile kuruldu (`is_musteri`,
   `is_montaj_noktasi`) — tek kayıt her iki rolü birden taşıyabilir.
2. **Gerçek bölünme.** AKÇADAĞ'ın 34 iş emri iki kayda ayrılmış.

Kurallar:

* **Karar insanın.** Otomatik benzerlik burada aday bile üretmez; eşleşmeler
  aşağıdaki listede elle yazılı, her biri gerekçesiyle.
* **Hiçbir satır silinmez.** Kaynak hesap yumuşak silinir ve notuna hedefin
  numarası yazılır; denetim izi ve `source_ref` yerinde kalır, göç tekrar
  koşarsa eski kayda bir daha düşmez.
* **Hedefin dolu alanı ezilmez.** Boş alanlar kaynaktan tamamlanır.
* Tek transaction; bir çakışma çıkarsa hiçbir birleşme yazılmaz.

Referans kolonları **veritabanından okunur**, elle listelenmez: `accounts`'a
bakan 25 kolon var ve yeni tablo eklendiğinde bu betiğin sessizce eksik
kalması kabul edilemez.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import Account


@dataclass(frozen=True)
class Birlesme:
    kaynak: int
    hedef: int
    gerekce: str


# Kullanıcı kararı (23 Eyl 2026). Hedef = KALACAK kayıt.
BIRLESMELER = (
    Birlesme(
        339,
        408,
        "Aynı firma iki rolde: 1224-1226 no'lu iş emirlerinin müşterisi #408, "
        "montajcısı #339 — Çamkıran kendi aracına kendi montajını yapıyor. "
        "Hedef #408, adı gerçek unvana daha yakın (vergi levhası: ÇAMKIRAN "
        "OTOMOTİV SAN. VE TİC. LTD. ŞTİ.).",
    ),
    Birlesme(
        446,
        319,
        "Aynı firma iki rolde: #319 bayi/montaj noktası (20 iş, hepsi "
        "ödenmeyecek), #446 bir kez müşteri. Hedef #319; 4 alt hesap onu "
        "bayi olarak gösteriyor.",
    ),
    Birlesme(
        363,
        364,
        "Gerçek bölünme: 34 iş emri iki kayda ayrılmış (18 + 16). Hedef #364, "
        "vergi levhasındaki unvanla örtüşüyor (AKÇADAĞ İNŞAAT ENERJİ "
        "MADENCİLİK A.Ş.).",
    ),
    Birlesme(
        452,
        453,
        "Gerçek bölünme. Hedef #453; cihazlar onda ve vergi levhası "
        "'MEVLANA OTOPARK İŞLETMECİLİĞİ OTO KİRALAMA' ikisini de kapsıyor. "
        "#402 MEVLANA FİLO'ya DOKUNULMUYOR — ayrı şirket olabilir, teyit yok.",
    ),
    Birlesme(
        425,
        400,
        "Gerçek bölünme: cihazlar #425'te, işlerin çoğu #400'de. Hedef #400, "
        "vergi levhasındaki unvanla örtüşüyor (SONKAR GIDA OTOMOTİV İNŞAAT "
        "HAYVANCILIK TAŞIMACILIK).",
    ),
)

# Yabancı anahtarı olmayan, elle taşınması gereken bağlar.
# attachments çok biçimli (entity/entity_id), devices.current_customer_id türetilmiş alan.
EK_BAGLAR = (
    ("attachments", "entity_id", "entity = 'accounts'"),
    ("devices", "current_customer_id", None),
)

# Kaynaktan hedefe YALNIZ hedefte boşsa kopyalanacak alanlar.
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


async def referans_kolonlari(db: AsyncSession) -> list[tuple[str, str]]:
    """`accounts.id`'ye bakan (tablo, kolon) çiftleri — şemadan okunur."""
    sonuc = await db.execute(
        text("""
        select c.conrelid::regclass::text as tablo, a.attname as kolon
        from pg_constraint c
        join unnest(c.conkey) with ordinality k(attnum, ord) on true
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.attnum
        where c.contype = 'f' and c.confrelid = 'accounts'::regclass
        order by 1, 2
        """)
    )
    return [(r.tablo, r.kolon) for r in sonuc]


async def _sayim(db: AsyncSession, tablo: str, kolon: str, hesap_id: int, kosul: str | None) -> int:
    ek = f" and {kosul}" if kosul else ""
    return int(
        await db.scalar(
            text(f"select count(*) from {tablo} where {kolon} = :id{ek}"), {"id": hesap_id}
        )  # noqa: S608
        or 0
    )


async def onizle(db: AsyncSession, birlesme: Birlesme) -> dict:
    kaynak = await db.get(Account, birlesme.kaynak)
    hedef = await db.get(Account, birlesme.hedef)
    if kaynak is None or hedef is None:
        return {"hata": "hesap bulunamadı"}

    baglar = await referans_kolonlari(db)
    tasinan: dict[str, int] = {}
    for tablo, kolon in baglar:
        adet = await _sayim(db, tablo, kolon, birlesme.kaynak, None)
        if adet:
            tasinan[f"{tablo}.{kolon}"] = adet
    for tablo, kolon, kosul in EK_BAGLAR:
        adet = await _sayim(db, tablo, kolon, birlesme.kaynak, kosul)
        if adet:
            tasinan[f"{tablo}.{kolon}"] = adet

    # installation_partners birincil anahtarı account_id: iki tarafta da varsa taşınamaz.
    cakisma = None
    kaynakta_nokta = await _sayim(db, "installation_partners", "account_id", birlesme.kaynak, None)
    hedefte_nokta = await _sayim(db, "installation_partners", "account_id", birlesme.hedef, None)
    if kaynakta_nokta and hedefte_nokta:
        cakisma = "iki hesapta da montaj noktası kaydı var; hedefinki korunur"

    return {
        "kaynak": kaynak,
        "hedef": hedef,
        "tasinan": tasinan,
        "cakisma": cakisma,
        "doldurulacak": {
            a: getattr(kaynak, a)
            for a in TASINAN_ALANLAR
            if getattr(kaynak, a) and not getattr(hedef, a)
        },
        "eklenen_rol": [r for r in ROL_BAYRAKLARI if getattr(kaynak, r) and not getattr(hedef, r)],
    }


async def uygula(db: AsyncSession, birlesme: Birlesme, plan: dict) -> dict[str, int]:
    kaynak: Account = plan["kaynak"]
    hedef: Account = plan["hedef"]
    sayac: dict[str, int] = {}

    baglar = await referans_kolonlari(db)
    for tablo, kolon in baglar:
        if tablo == "installation_partners" and kolon == "account_id" and plan["cakisma"]:
            continue  # hedefte zaten var; kaynağınki yerinde kalır, hesapla birlikte kapanır
        sonuc = await db.execute(
            text(f"update {tablo} set {kolon} = :hedef where {kolon} = :kaynak"),  # noqa: S608
            {"hedef": birlesme.hedef, "kaynak": birlesme.kaynak},
        )
        if sonuc.rowcount:
            sayac[f"{tablo}.{kolon}"] = sonuc.rowcount

    for tablo, kolon, kosul in EK_BAGLAR:
        ek = f" and {kosul}" if kosul else ""
        sonuc = await db.execute(
            text(f"update {tablo} set {kolon} = :hedef where {kolon} = :kaynak{ek}"),  # noqa: S608
            {"hedef": birlesme.hedef, "kaynak": birlesme.kaynak},
        )
        if sonuc.rowcount:
            sayac[f"{tablo}.{kolon}"] = sonuc.rowcount

    # Kaynak hedefin bayisi görünüyorsa kendine işaret eden bir kayıt doğar.
    await db.execute(
        text(
            "update accounts set parent_dealer_id = null"
            " where id = :hedef and parent_dealer_id = :hedef"
        ),
        {"hedef": birlesme.hedef},
    )

    for rol in plan["eklenen_rol"]:
        setattr(hedef, rol, True)
    for alan, deger in plan["doldurulacak"].items():
        setattr(hedef, alan, deger)

    kaynak.is_deleted = True
    kaynak.deleted_at = datetime.now(UTC)
    kaynak.is_active = False
    not_metni = f"#{birlesme.hedef} {hedef.title} ile birleştirildi (23.09.2026)."
    kaynak.notes = f"{kaynak.notes}\n{not_metni}" if kaynak.notes else not_metni
    return sayac


def _yazdir(birlesme: Birlesme, plan: dict, sayac: dict[str, int] | None) -> None:
    if "hata" in plan:
        print(f"#{birlesme.kaynak} → #{birlesme.hedef}: {plan['hata']}")
        return
    kaynak, hedef = plan["kaynak"], plan["hedef"]
    print(f"\n#{birlesme.kaynak} {kaynak.title}")
    print(f"   ↳ #{birlesme.hedef} {hedef.title}")
    print(f"   {birlesme.gerekce}")
    tasinan = sayac if sayac is not None else plan["tasinan"]
    for anahtar, adet in sorted(tasinan.items()):
        print(f"     {anahtar:42s} {adet:5d}")
    if plan["eklenen_rol"]:
        print(f"     hedefe eklenen rol: {', '.join(plan['eklenen_rol'])}")
    if plan["doldurulacak"]:
        print(f"     hedefte doldurulan: {', '.join(plan['doldurulacak'])}")
    if plan["cakisma"]:
        print(f"     ! {plan['cakisma']}")


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Mükerrer hesapları birleştirir.")
    ayristirici.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    async with get_session_factory()() as db:
        print("=" * 72)
        print(f"HESAP BİRLEŞTİRME — {len(BIRLESMELER)} çift")
        print("=" * 72)
        for birlesme in BIRLESMELER:
            plan = await onizle(db, birlesme)
            sayac = None
            if args.uygula and "hata" not in plan:
                sayac = await uygula(db, birlesme, plan)
                await db.flush()
            _yazdir(birlesme, plan, sayac)

        if args.uygula:
            await db.commit()
            kalan = await db.scalar(
                select(Account.id).where(Account.is_deleted.is_(False)).limit(1)
            )
            print(f"\nUYGULANDI. (örnek açık hesap #{kalan})")
        else:
            print("\nÖNİZLEME — hiçbir şey yazılmadı. Yazmak için --uygula ekleyin.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
