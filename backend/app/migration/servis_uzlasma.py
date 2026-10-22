"""Servis göçü (Göç-1) yürütücüsü ve uzlaşma raporu (TS-177, plan §5.3).

    make goc-servis-onizleme KAYNAK=<döküm>   # HİÇBİR ŞEY YAZMAZ
    make goc-servis-uygula   KAYNAK=<döküm>   # tek transaction
    make goc-servis-rapor    KAYNAK=<döküm>   # uzlaşma xlsx (salt okunur)

    uv run python -m app.migration.servis_uzlasma onizleme|uygula|rapor \\
        --kaynak <döküm> [--adim kutuk,servis,plan,zaman] [--birim GUVENLIK] [--cikti x.xlsx]

Adım sırası zorunludur: kütük → servis işleri → plan → zaman (plan ve zaman
göç edilmiş işe bağlanır). Bakım sözleşmesi ve müşteri/ad eşleştirmesi insan
kararı ister ve İçe Aktarma profilleriyle yapılır (`deploy/KURULUM.md`).

**Uzlaşma sözleşmesi (tablo bazında):**
`kaynak = aktarılan + karantina + reddedilen (+ ertelenen)`.

- aktarılan: hedef tabloda `source_ref`'i bulunan kaynak satırı (karantinadan
  profil ile sonradan aktarılan dahil),
- karantina: insan kararı bekleyen (profil Excel'i yazılır),
- reddedilen: kimliksiz/bozuk, hiç yüklenemez,
- ertelenen: `--birim` ile bu koşunun dışında bırakılan birimler (birim bazlı
  geçiş: GUVENLIK → HABERLESME/POC → MOBILITE/ARAC_TAKIP).

Uygulamadan sonra "bekleyen" (aktarılacak ama hedefte olmayan) 0 olmalıdır;
ikinci `uygula` 0 yeni satır üretir. Rapor, kaynak ekranla karşılaştırılacak
5 örnek işi de listeler.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration import servis_goc, servis_plan, servis_zaman, yukle_kutuk
from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.migration.servis_kaynak import (
    GOC_SISTEMI,
    AdimSonucu,
    KaynakDizini,
    KaynakHatasi,
    mevcut_refler,
)
from app.models import ServiceOrder

ADIMLAR = ("kutuk", "servis", "plan", "zaman")


@dataclass
class Kosu:
    """Bir göç koşusunun adım sonuçları ve ertelenenleri."""

    sonuclar: list[AdimSonucu] = field(default_factory=list)
    ertelenen: dict[str, int] = field(default_factory=dict)


def _ref(x: Any) -> str:
    return x["source_ref"] if isinstance(x, dict) else x.ref


async def kos(
    db: AsyncSession,
    dizin: KaynakDizini,
    *,
    adimlar: tuple[str, ...] = ADIMLAR,
    uygula: bool = False,
    birimler: frozenset[str] | None = None,
    user_id: int | None = None,
) -> Kosu:
    """Adımları sırayla hazırlar; `uygula=True` ise yazar (commit ÇAĞIRANDA).

    Önizlemede sonraki adımlar o ana kadar DB'de olan işleri görür: henüz
    yazılmamış işlerin planları önizlemede karantinada görünür (uyarı
    yazdırılır), uygulamada değil.
    """
    kosu = Kosu()
    if "kutuk" in adimlar:
        s = await yukle_kutuk.hazirla(db, dizin)
        if uygula:
            await yukle_kutuk.yukle(db, s, user_id=user_id)
        kosu.sonuclar.append(s)
    if "servis" in adimlar:
        s = await servis_goc.hazirla_db(db, dizin)
        if birimler is not None:
            kalan = [t for t in s.aktarilacak if t.birim in birimler]
            kosu.ertelenen[s.kaynak_tablo] = len(s.aktarilacak) - len(kalan)
            s.aktarilacak = kalan
            var = await mevcut_refler(db, s.hedef_tablo, s.kaynak_tablo)
            s.mevcut = sum(1 for t in kalan if t.ref in var)
            s.yeni = len(kalan) - s.mevcut
        if uygula:
            await servis_goc.yukle(db, s, user_id=user_id)
        kosu.sonuclar.append(s)
    if "plan" in adimlar:
        s = await servis_plan.hazirla_db(db, dizin)
        if uygula:
            await servis_plan.yukle(db, s, user_id=user_id)
        kosu.sonuclar.append(s)
    if "zaman" in adimlar:
        ss = await servis_zaman.hazirla_db(db, dizin)
        if uygula:
            await servis_zaman.yukle(db, ss, user_id=user_id)
        kosu.sonuclar.extend(ss)
    return kosu


async def uzlasma(db: AsyncSession, kosu: Kosu) -> list[dict[str, Any]]:
    """Tablo bazında `kaynak = aktarılan + karantina + reddedilen (+ ertelenen)`."""
    satirlar: list[dict[str, Any]] = []
    for s in kosu.sonuclar:
        var = await mevcut_refler(db, s.hedef_tablo, s.kaynak_tablo)
        aktarilacak = {_ref(x) for x in s.aktarilacak}
        karantina = {r for r, _ in s.karantina}
        ertelenen = kosu.ertelenen.get(s.kaynak_tablo, 0)
        aktarilan = len((aktarilacak | karantina) & var)
        karantina_kalan = len(karantina - var)
        bekleyen = len(aktarilacak - var)
        toplam = aktarilan + karantina_kalan + len(s.reddedilen) + ertelenen + bekleyen
        satirlar.append(
            {
                "kaynak_tablo": s.kaynak_tablo,
                "hedef_tablo": s.hedef_tablo,
                "kaynak": s.kaynak,
                "aktarilan": aktarilan,
                "karantina": karantina_kalan,
                "reddedilen": len(s.reddedilen),
                "ertelenen": ertelenen,
                "bekleyen": bekleyen,
                "tutarli": s.kaynak == toplam and bekleyen == 0,
                "uyarilar": s.uyari_sayilari(),
            }
        )
    return satirlar


async def ornek_isler(db: AsyncSession, adet: int = 5) -> list[list[Any]]:
    """Kaynak ekranla elle karşılaştırılacak örnek işler: baş, son ve aradan eşit aralıklı."""
    isler = (
        await db.execute(
            select(
                ServiceOrder.source_ref,
                ServiceOrder.so_no,
                ServiceOrder.birim,
                ServiceOrder.tur,
                ServiceOrder.status,
                ServiceOrder.customer_id,
                ServiceOrder.customer_name_raw,
                ServiceOrder.created_at,
            )
            .where(ServiceOrder.source_system == GOC_SISTEMI)
            .order_by(ServiceOrder.id)
        )
    ).all()
    if not isler:
        return []
    if len(isler) <= adet:
        secilen = list(isler)
    else:
        adim = (len(isler) - 1) / (adet - 1)
        secilen = [isler[round(i * adim)] for i in range(adet)]
    return [
        [
            r.source_ref,
            r.so_no,
            r.birim,
            r.tur,
            r.status,
            r.customer_id,
            r.customer_name_raw,
            r.created_at.isoformat() if r.created_at else None,
        ]
        for r in secilen
    ]


def rapor_xlsx(
    kosu: Kosu, uzlasma_satirlari: list[dict[str, Any]], ornekler: list[list[Any]]
) -> bytes:
    ozet = Sayfa(
        [
            "Kaynak Tablo",
            "Hedef Tablo",
            "Kaynak",
            "Aktarılan",
            "Karantina",
            "Reddedilen",
            "Ertelenen",
            "Bekleyen",
            "Tutarlı",
        ]
    )
    for u in uzlasma_satirlari:
        ozet.satirlar.append(
            [
                u["kaynak_tablo"],
                u["hedef_tablo"],
                u["kaynak"],
                u["aktarilan"],
                u["karantina"],
                u["reddedilen"],
                u["ertelenen"],
                u["bekleyen"],
                "EVET" if u["tutarli"] else "HAYIR",
            ]
        )
    karantina = Sayfa(["Kaynak Tablo", "Kaynak Ref", "Neden"])
    reddedilen = Sayfa(["Kaynak Tablo", "Kaynak", "Neden"])
    uyarilar = Sayfa(["Kaynak Tablo", "Kaynak Ref", "Uyarı", "Ayrıntı"])
    for s in kosu.sonuclar:
        karantina.satirlar += [[s.kaynak_tablo, r, n] for r, n in s.karantina]
        reddedilen.satirlar += [[s.kaynak_tablo, r, n] for r, n in s.reddedilen]
        uyarilar.satirlar += [[s.kaynak_tablo, r, k, a] for r, k, a in s.uyarilar]
    sayfalar = {
        "Uzlasma": ozet,
        "Karantina": karantina,
        "Reddedilen": reddedilen,
        "Uyarilar": uyarilar,
        "Ornek_5_Is": Sayfa(
            [
                "Kaynak Ref",
                "Yeni No",
                "Birim",
                "Tür",
                "Durum",
                "Hesap Id",
                "Ham Müşteri",
                "Açılış (UTC)",
            ],
            ornekler,
        ),
    }
    return cok_sayfali_xlsx(sayfalar)


def servis_karantina_xlsx(kosu: Kosu) -> bytes | None:
    """Servis işi karantinası `servis_isleri` profil şablonunda (insan kararı için)."""
    for s in kosu.sonuclar:
        if s.kaynak_tablo == servis_goc.KAYNAK_TABLO and s.karantina:
            return cok_sayfali_xlsx(
                {
                    "Servis Isleri": Sayfa(
                        servis_goc.KARANTINA_BASLIKLARI, servis_goc.karantina_excel_satirlari(s)
                    )
                }
            )
    return None


def _yazdir(kosu: Kosu, uzlasma_satirlari: list[dict[str, Any]], mod: str) -> None:
    print("=" * 96)
    print(f"SERVİS GÖÇÜ — {mod.upper()}" + (" (HİÇBİR ŞEY YAZILMADI)" if mod != "uygula" else ""))
    print("=" * 96)
    print(
        f"{'Kaynak tablo':24s}{'kaynak':>8}{'aktarılan':>11}{'karantina':>11}"
        f"{'reddedilen':>12}{'ertelenen':>11}{'bekleyen':>10}{'yeni':>7}  durum"
    )
    for s, u in zip(kosu.sonuclar, uzlasma_satirlari, strict=True):
        print(
            f"{u['kaynak_tablo']:24s}{u['kaynak']:>8}{u['aktarilan']:>11}{u['karantina']:>11}"
            f"{u['reddedilen']:>12}{u['ertelenen']:>11}{u['bekleyen']:>10}{s.yeni:>7}  "
            + ("TUTARLI" if u["tutarli"] else ("UYGULANMADI" if mod == "onizleme" else "FARK"))
        )
        if u["uyarilar"]:
            print(
                "    uyarılar: " + ", ".join(f"{k}={v}" for k, v in sorted(u["uyarilar"].items()))
            )


async def _calistir(args: argparse.Namespace) -> int:
    from app.db import get_engine, get_session_factory

    adimlar = tuple(a for a in ADIMLAR if a in set(args.adim.split(",")))
    birimler = frozenset(b.strip().upper() for b in args.birim.split(",")) if args.birim else None
    dizin = KaynakDizini(args.kaynak)
    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            kosu = await kos(
                db, dizin, adimlar=adimlar, uygula=args.mod == "uygula", birimler=birimler
            )
            if args.mod == "uygula":
                await db.commit()
            satirlar = await uzlasma(db, kosu)
            ornekler = await ornek_isler(db)
            if args.mod != "uygula":
                await db.rollback()
    finally:
        await engine.dispose()
    _yazdir(kosu, satirlar, args.mod)
    if args.cikti:
        args.cikti.write_bytes(rapor_xlsx(kosu, satirlar, ornekler))
        print(f"\nUzlaşma raporu: {args.cikti}")
        karantina = servis_karantina_xlsx(kosu)
        if karantina is not None:
            yol = args.cikti.with_name(args.cikti.stem + "_servis_isleri_karantina.xlsx")
            yol.write_bytes(karantina)
            print(f"Servis işi karantinası (servis_isleri profili): {yol}")
    if args.mod == "rapor" and not all(u["tutarli"] for u in satirlar):
        return 2
    return 0


def komut_satiri(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Servis göçü (Göç-1) ve uzlaşma")
    ayr.add_argument("mod", choices=("onizleme", "uygula", "rapor"), nargs="?", default="onizleme")
    ayr.add_argument("--kaynak", type=Path, required=True, help="CSV döküm dizini")
    ayr.add_argument("--adim", default=",".join(ADIMLAR), help="kutuk,servis,plan,zaman")
    ayr.add_argument("--birim", help="Yalnız bu birim(ler)in servis işleri (virgülle)")
    ayr.add_argument("--cikti", type=Path, help="Uzlaşma raporu xlsx")
    ayr.add_argument("--uygula", action="store_true", help="'uygula' moduyla aynı")
    args = ayr.parse_args(argv)
    if args.uygula:
        args.mod = "uygula"
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(_calistir(args))
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(komut_satiri())
