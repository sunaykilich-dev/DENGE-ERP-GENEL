"""Canlı PG ana veri kalitesi ölçümü — SALT OKUNUR (TS-017 / E14-08).

    uv run python -m app.migration.ana_veri_olcum
    uv run python -m app.migration.ana_veri_olcum --cikti ana_veri_olcum.xlsx

**Neden var:** Teknik servis ana veri kararları (VKN çakışmasında 409 + onay,
teklif adresinin `is_primary DESC, id` sırası, il adının 81 il listesine
bağlanması) mevcut canlı veriyi etkiler. Etkinin büyüklüğü tahminle değil
ölçümle yayın notuna yazılır; **sayı uydurulmaz**. Bu betik o sayıları üretir:

- aynı VKN'li AKTİF hesap grupları (E14-01 VKN uyarısının yayın kapısı, B1),
- `title_key` (ve varsa `unvan_anahtari`) çakışan aktif hesap grupları,
- `addresses` dağılımı ve birden çok adresli hesap sayısı (K24/B8),
- `accounts.region` ve `addresses.city` il yazım çeşitleri (E14-D02).

**Neden salt okunur transaction:** betik canlının kopyasında ve gerekirse
canlıda koşar. Bağlantı `SET TRANSACTION READ ONLY` ile açılır; yanlışlıkla
eklenen bir yazma sorgusu PostgreSQL tarafından reddedilir (testte
doğrulanır) ve transaction her durumda geri alınır.

**KVKK:** 11 haneli vergi numarası TCKN'dir (şahıs). Raporda maskelenir
(`12*******90`); 10 haneli VKN tüzel kişi numarasıdır ve açık yazılır.
Kişi adı, telefon, e-posta bu rapora girmez.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clock import Clock, RealClock
from app.services import normalize as _normalize
from app.services.normalize import tr_normkey

OLCULMEDI = "ÖLÇÜLMEDİ"

_BASLIK_DOLGU = PatternFill("solid", fgColor="E8E4DB")
_BASLIK_YAZI = Font(bold=True, color="3C4657")


# --- Ortak: salt okunur bağlantı ve çok sayfalı xlsx ---------------------------


@asynccontextmanager
async def salt_okunur(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """`SET TRANSACTION READ ONLY` ile açılmış bağlantı verir; çıkışta geri alır.

    `SET TRANSACTION` transaction'ın İLK komutu olmalıdır; SQLAlchemy ilk
    `execute` ile transaction'ı başlattığı için sıra burada garanti edilir.
    Commit hiç çağrılmaz: ölçüm hiçbir iz bırakmaz.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield conn
        finally:
            await conn.rollback()


@dataclass
class Sayfa:
    basliklar: list[str]
    satirlar: list[list[Any]] = field(default_factory=list)


def cok_sayfali_xlsx(sayfalar: dict[str, Sayfa]) -> bytes:
    """Her ölçüm ayrı sayfa (kabul 2). `=` ile başlayan metin formül olmaz.

    `services/export.satirlari_xlsx` tek sayfa üretiyor; ölçüm raporu tablo
    bazında ayrı sayfa istediği için aynı biçim kuralları burada tekrarlanır.
    """
    wb = Workbook()
    wb.remove(wb.active)
    for ad, sayfa in sayfalar.items():
        ws = wb.create_sheet(ad[:31])
        ws.append(sayfa.basliklar)
        for h in ws[1]:
            h.fill, h.font = _BASLIK_DOLGU, _BASLIK_YAZI
            h.alignment = Alignment(vertical="center")
        for satir in sayfa.satirlar:
            ws.append(list(satir))
            for h in ws[ws.max_row]:
                if h.data_type == "f":
                    h.data_type = "s"
        for i, baslik in enumerate(sayfa.basliklar, start=1):
            en = max([len(str(baslik))] + [len(str(s[i - 1])) for s in sayfa.satirlar])
            ws.column_dimensions[get_column_letter(i)].width = min(max(en + 2, 10), 60)
        ws.freeze_panes = "A2"
    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def vergi_no_goster(vergi_no: str) -> str:
    """11 hane (TCKN) maskelenir; 10 hane VKN aynen gösterilir."""
    temiz = (vergi_no or "").strip()
    if len(temiz) == 11 and temiz.isdigit():
        return f"{temiz[:2]}{'*' * 7}{temiz[-2:]}"
    return temiz


# --- Ölçüm --------------------------------------------------------------------


@dataclass
class Olcum:
    """`ozet`: (ölçüm, değer, açıklama). `sayfalar`: ayrıntı sayfaları."""

    ozet: list[tuple[str, Any, str]] = field(default_factory=list)
    sayfalar: dict[str, Sayfa] = field(default_factory=dict)

    def deger(self, olcum: str) -> Any:
        for ad, deger, _ in self.ozet:
            if ad == olcum:
                return deger
        raise KeyError(olcum)


async def _vkn_gruplari(conn: AsyncConnection, sonuc: Olcum) -> None:
    satirlar = (
        await conn.execute(
            text(
                """
                SELECT btrim(a.tax_no) AS vkn, count(*) AS adet,
                       array_agg(a.id ORDER BY a.id) AS idler,
                       array_agg(a.title ORDER BY a.id) AS unvanlar
                FROM accounts a
                WHERE a.is_active AND NOT a.is_deleted
                  AND a.tax_no IS NOT NULL AND btrim(a.tax_no) <> ''
                GROUP BY btrim(a.tax_no)
                HAVING count(*) > 1
                ORDER BY count(*) DESC, btrim(a.tax_no)
                """
            )
        )
    ).all()
    sayfa = Sayfa(["Vergi No", "Hesap Sayısı", "Hesap ID'leri", "Unvanlar"])
    for s in satirlar:
        sayfa.satirlar.append(
            [
                vergi_no_goster(s.vkn),
                s.adet,
                ", ".join(map(str, s.idler)),
                " | ".join(s.unvanlar),
            ]
        )
    sonuc.sayfalar["VKN_Gruplari"] = sayfa
    sonuc.ozet.append(
        ("aynı VKN'li aktif hesap grubu", len(satirlar), "VKN çakışması 409 yayın kapısı (B1)")
    )
    sonuc.ozet.append(
        (
            "aynı VKN'li gruplardaki aktif hesap",
            sum(s.adet for s in satirlar),
            "silinmemiş ve aktif hesaplar",
        )
    )


async def _unvan_gruplari(conn: AsyncConnection, sonuc: Olcum) -> None:
    hesaplar = (
        await conn.execute(
            text(
                "SELECT a.id, a.title, a.title_key FROM accounts a "
                "WHERE a.is_active AND NOT a.is_deleted ORDER BY a.id"
            )
        )
    ).all()

    def _grupla(anahtar_fn) -> dict[str, list]:
        gruplar: dict[str, list] = defaultdict(list)
        for h in hesaplar:
            anahtar = anahtar_fn(h)
            if anahtar:
                gruplar[anahtar].append(h)
        return {k: v for k, v in gruplar.items() if len(v) > 1}

    sayfa = Sayfa(["Anahtar Türü", "Anahtar", "Hesap Sayısı", "Hesap ID'leri", "Unvanlar"])
    title_gruplari = _grupla(lambda h: h.title_key)
    for anahtar, grup in sorted(title_gruplari.items()):
        sayfa.satirlar.append(
            [
                "title_key",
                anahtar,
                len(grup),
                ", ".join(str(h.id) for h in grup),
                " | ".join(h.title for h in grup),
            ]
        )
    sonuc.ozet.append(
        ("title_key çakışan aktif hesap grubu", len(title_gruplari), "tr_normkey(unvan) eşit")
    )

    # `unvan_anahtari` D0-B (TS-011) ile gelir; yoksa sayı UYDURULMAZ.
    unvan_anahtari = getattr(_normalize, "unvan_anahtari", None)
    if unvan_anahtari is None:
        sonuc.ozet.append(
            (
                "unvan_anahtari çakışan aktif hesap grubu",
                OLCULMEDI,
                "normalize.unvan_anahtari henüz yok (TS-011)",
            )
        )
    else:
        unvan_gruplari = _grupla(lambda h: unvan_anahtari(h.title))
        for anahtar, grup in sorted(unvan_gruplari.items()):
            sayfa.satirlar.append(
                [
                    "unvan_anahtari",
                    anahtar,
                    len(grup),
                    ", ".join(str(h.id) for h in grup),
                    " | ".join(h.title for h in grup),
                ]
            )
        sonuc.ozet.append(
            (
                "unvan_anahtari çakışan aktif hesap grubu",
                len(unvan_gruplari),
                "A.Ş./LTD. ekleri ve noktalama atılmış anahtar",
            )
        )
    sonuc.sayfalar["Unvan_Gruplari"] = sayfa


async def _adres_dagilimi(conn: AsyncConnection, sonuc: Olcum) -> None:
    turler = (
        await conn.execute(
            text(
                """
                SELECT kind, is_active, count(*) AS adet
                FROM addresses GROUP BY kind, is_active ORDER BY kind, is_active DESC
                """
            )
        )
    ).all()
    sayfa = Sayfa(["Ölçüm", "Tür", "Aktif mi", "Adet"])
    for t in turler:
        sayfa.satirlar.append(["adres türü", t.kind, "evet" if t.is_active else "hayır", t.adet])

    dagilim = (
        await conn.execute(
            text(
                """
                SELECT CASE WHEN n >= 3 THEN '3+' ELSE n::text END AS kova, count(*) AS adet
                FROM (
                    SELECT a.id, count(ad.id) AS n
                    FROM accounts a LEFT JOIN addresses ad ON ad.account_id = a.id
                    WHERE a.is_active AND NOT a.is_deleted
                    GROUP BY a.id
                ) x
                GROUP BY 1 ORDER BY 1
                """
            )
        )
    ).all()
    for d in dagilim:
        sayfa.satirlar.append(["hesap başına adres", d.kova, "", d.adet])

    cok_adresli = await conn.scalar(
        text(
            """
            SELECT count(*) FROM (
                SELECT a.id FROM accounts a JOIN addresses ad ON ad.account_id = a.id
                WHERE a.is_active AND NOT a.is_deleted GROUP BY a.id HAVING count(*) > 1
            ) x
            """
        )
    )
    cok_birincil = await conn.scalar(
        text(
            """
            SELECT count(*) FROM (
                SELECT a.id FROM accounts a JOIN addresses ad ON ad.account_id = a.id
                WHERE a.is_active AND NOT a.is_deleted AND ad.is_primary
                GROUP BY a.id HAVING count(*) > 1
            ) x
            """
        )
    )
    toplam_adres = await conn.scalar(text("SELECT count(*) FROM addresses"))
    sonuc.sayfalar["Adres_Dagilimi"] = sayfa
    sonuc.ozet.append(("toplam adres", toplam_adres, "tüm türler, aktif + pasif"))
    sonuc.ozet.append(
        (
            "birden çok adresli aktif hesap",
            cok_adresli,
            "0 değilse teklif PDF adres sırası (K24) yayın notuna yazılır (B8)",
        )
    )
    sonuc.ozet.append(
        ("birden çok birincil adresli aktif hesap", cok_birincil, "is_primary birden fazla")
    )


async def _il_yazimlari(conn: AsyncConnection, sonuc: Olcum) -> None:
    satirlar = (
        await conn.execute(
            text(
                """
                SELECT 'accounts.region' AS kaynak, a.region AS deger, count(*) AS adet
                FROM accounts a
                WHERE a.is_active AND NOT a.is_deleted
                  AND a.region IS NOT NULL AND btrim(a.region) <> ''
                GROUP BY a.region
                UNION ALL
                SELECT 'addresses.city', ad.city, count(*)
                FROM addresses ad
                WHERE ad.city IS NOT NULL AND btrim(ad.city) <> ''
                GROUP BY ad.city
                """
            )
        )
    ).all()
    # Türkçe katlama SQL'de güvenilir değil (test DB'leri `C` collation):
    # anahtar Python'da `tr_normkey` ile üretilir.
    gruplar: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in satirlar:
        gruplar[tr_normkey(s.deger)][s.deger] += s.adet

    il_normalize = getattr(_normalize, "il_normalize", None)
    sayfa = Sayfa(["Anahtar", "Yazım", "Kayıt Sayısı", "Yazım Çeşidi", "81 İl Karşılığı"])
    taninmayan = 0
    for anahtar in sorted(gruplar):
        yazimlar = gruplar[anahtar]
        karsilik: Any = OLCULMEDI
        if il_normalize is not None:
            karsilik = il_normalize(next(iter(yazimlar))) or "TANINMADI"
            if karsilik == "TANINMADI":
                taninmayan += 1
        for yazim, adet in sorted(yazimlar.items()):
            sayfa.satirlar.append([anahtar, yazim, adet, len(yazimlar), karsilik])
    sonuc.sayfalar["Il_Yazimlari"] = sayfa

    sonuc.ozet.append(
        (
            "farklı il yazımı (ham)",
            len({s.deger for s in satirlar}),
            "accounts.region + addresses.city",
        )
    )
    sonuc.ozet.append(
        ("farklı il anahtarı (tr_normkey)", len(gruplar), "büyük/küçük harf katlanmış")
    )
    sonuc.ozet.append(
        (
            "birden çok yazımı olan il anahtarı",
            sum(1 for y in gruplar.values() if len(y) > 1),
            "aynı il farklı yazılmış",
        )
    )
    sonuc.ozet.append(
        (
            "81 il listesinde tanınmayan anahtar",
            taninmayan if il_normalize is not None else OLCULMEDI,
            "normalize.il_normalize (TS-011)"
            if il_normalize is not None
            else "normalize.il_normalize henüz yok (TS-011)",
        )
    )


async def olc(conn: AsyncConnection) -> Olcum:
    """Tüm ölçümleri verilen (salt okunur) bağlantıda koşar."""
    sonuc = Olcum()
    sonuc.ozet.append(
        (
            "aktif hesap",
            await conn.scalar(
                text("SELECT count(*) FROM accounts a WHERE a.is_active AND NOT a.is_deleted")
            ),
            "",
        )
    )
    await _vkn_gruplari(conn, sonuc)
    await _unvan_gruplari(conn, sonuc)
    await _adres_dagilimi(conn, sonuc)
    await _il_yazimlari(conn, sonuc)
    return sonuc


def rapor_xlsx(sonuc: Olcum, *, clock: Clock) -> bytes:
    ozet = Sayfa(["Ölçüm", "Değer", "Açıklama"])
    ozet.satirlar.append(["ölçüm zamanı (UTC)", clock.now().isoformat(timespec="seconds"), ""])
    ozet.satirlar.extend([list(s) for s in sonuc.ozet])
    return cok_sayfali_xlsx({"Ozet": ozet, **sonuc.sayfalar})


async def calistir(engine: AsyncEngine, cikti: Path | None, *, clock: Clock) -> Olcum:
    async with salt_okunur(engine) as conn:
        sonuc = await olc(conn)
    if cikti is not None:
        cikti.write_bytes(rapor_xlsx(sonuc, clock=clock))
    return sonuc


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(
        description="Canlı ana veri kalitesi ölçümü (salt okunur)"
    )
    ayristirici.add_argument("--cikti", type=Path, help="xlsx dosyası; verilmezse yalnız konsol")
    args = ayristirici.parse_args(argv)

    from app.db import get_engine

    clock = RealClock()
    engine = get_engine()
    try:
        sonuc = await calistir(engine, args.cikti, clock=clock)
    finally:
        await engine.dispose()

    print("=" * 70)
    print("ANA VERİ ÖLÇÜMÜ — salt okunur, hiçbir şey yazılmadı")
    print("=" * 70)
    for ad, deger, aciklama in sonuc.ozet:
        print(f"  {ad:45s} {deger!s:>12}  {aciklama}")
    if args.cikti:
        print(f"\nRapor: {args.cikti}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
