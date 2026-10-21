"""Göç öncesi güvenlik cihaz kütüğü profili — SALT OKUNUR (TS-017 / E03-05).

    uv run python -m app.migration.kutuk_profil --seed-sql <DengeERP_V15_Seed.sql>
    uv run python -m app.migration.kutuk_profil --kutuk SecurityDevices.xlsx \\
        --kalemler MaintenanceDeviceItems.xlsx --sozlesmeler MaintenanceContracts.xlsx \\
        --db --cikti analiz/kutuk_profil_<tarih>.xlsx

**Neden var:** kütük göçünün (TS-172) kabul rakamları — seri no'suz satır,
mükerrer seri grubu, lokasyonsuz satır, okunamayan teslim tarihi — tasarımda
V1.5 seed dosyasından çıkarıldı (1.324 / 96 / 38-96 / 299 / 1.137). Canlı
SQL Server'da sonradan değişmiş olabilir. Bu betik aynı sayıları kaynağın
güncel dökümünden **ölçer** ve tasarım tablosuyla yan yana koyar; sayı
uydurulmaz, ölçülemeyen değer "ÖLÇÜLMEDİ" yazılır.

**Kaynaklar** (SQL Server'a canlı bağlanılmaz — E03 karar 19):

- `--seed-sql`: V1.5 seed dosyası (`MERGE ... USING (VALUES ...)` blokları).
- `--kutuk` / `--kalemler` / `--sozlesmeler`: SSMS'te `SELECT *` ile alınmış
  `dbo.SecurityDevices`, `dbo.MaintenanceDeviceItems`,
  `dbo.MaintenanceContracts` dökümü (xlsx ya da UTF-8 csv; başlık satırı
  kaynak kolon adları). Dosya verilirse seed'deki aynı tablonun yerine geçer.
- `--db`: canlı PG — `accounts` ile otomatik müşteri eşleşme oranı ve
  `service_equipment` (göç sonrası) mükerrer/serisiz sayıları. Bağlantı
  `SET TRANSACTION READ ONLY` ile açılır (`ana_veri_olcum.salt_okunur`).

**Seri anahtarı:** TS-011 kuralı (strip, iç boşluk teke, ASCII büyük harf
i/ı/İ→I; baştaki sıfır ve `/-.` korunur). `normalize.normalize_seri`
yayımlandığında o kullanılır; rapor hangisinin kullanıldığını yazar.
Kişi adı (`ContactName`) rapora girmez.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.clock import Clock, RealClock
from app.migration.ana_veri_olcum import OLCULMEDI, Sayfa, cok_sayfali_xlsx, salt_okunur
from app.models.servis_ekipman import model_anahtari
from app.services import normalize as _normalize
from app.services.normalize import tr_normkey

# Tasarım tablosu (`analiz/02_moduller/03_cihaz_kutugu_tasarim.md`): V1.5 seed
# dosyasından çıkarılan sayılar. Ölçüm bunlarla KARŞILAŞTIRILIR, yerine geçmez.
TASARIM_SAYILARI: dict[str, int] = {
    "toplam_satir": 1324,
    "serisiz": 96,
    "mukerrer_seri_grup": 38,
    "mukerrer_seri_satir": 96,
    "lokasyonsuz": 299,
    "teslim_excel_gun": 1137,
}

TABLOLAR = ("SecurityDevices", "MaintenanceContracts", "MaintenanceDeviceItems")

# Excel gün sayısının üst sınırı: 2958465 = 9999-12-31.
_EXCEL_UST = 2958465
_GG_AA_YYYY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


# --- Saf yardımcılar -------------------------------------------------------------


def _bos_mu(deger: Any) -> bool:
    return deger is None or not str(deger).strip()


def _yerel_seri_anahtari(ham: Any) -> str | None:
    """TS-011 `normalize_seri` kuralı (yayımlanana kadar profil için)."""
    if _bos_mu(ham):
        return None
    metin = re.sub(r"\s+", " ", str(ham).strip())
    metin = metin.replace("i", "I").replace("ı", "I").replace("İ", "I")
    return metin.upper()


def seri_anahtari_fonksiyonu() -> tuple[Callable[[Any], str | None], str]:
    """(fonksiyon, ad) — `normalize.normalize_seri` varsa onu döndürür."""
    resmi = getattr(_normalize, "normalize_seri", None)
    if resmi is not None:

        def _sar(ham: Any) -> str | None:
            return None if _bos_mu(ham) else (resmi(str(ham)) or None)

        return _sar, "normalize.normalize_seri"
    return _yerel_seri_anahtari, "yerel (TS-011 kuralı; normalize_seri henüz yok)"


def teslim_deseni(ham: Any) -> str:
    """`DeliveryDateText` deseni: tarih UYDURULMAZ, yalnız sınıflandırılır."""
    if _bos_mu(ham):
        return "BOS"
    metin = str(ham).strip()
    if metin.isdigit():
        sayi = int(metin)
        if len(metin) == 4 and 1950 <= sayi <= 2100:
            return "YIL"
        if 1 <= sayi <= _EXCEL_UST:
            return "EXCEL_GUN"
        return "GECERSIZ"
    eslesme = _GG_AA_YYYY.match(metin)
    if eslesme:
        gun, ay, yil = (int(x) for x in eslesme.groups())
        try:
            date(yil, ay, gun)
        except ValueError:
            return "GG.AA.YYYY_GECERSIZ"
        return "GG.AA.YYYY"
    return "DIGER"


# --- Kaynak okuma ------------------------------------------------------------------


class KaynakHatasi(ValueError):
    pass


def _tsql_degerleri(metin: str) -> list[list[Any]]:
    """`(N'a',1,NULL),(…)` gövdesini satırlara ayırır. `''` kaçışını çözer."""
    satirlar: list[list[Any]] = []
    i, n = 0, len(metin)
    satir: list[Any] | None = None
    while i < n:
        c = metin[i]
        if satir is None:
            if c == "(":
                satir = []
            i += 1
            continue
        if c in " \t\r\n,":
            i += 1
            continue
        if c == ")":
            satirlar.append(satir)
            satir = None
            i += 1
            continue
        if c in "Nn" and i + 1 < n and metin[i + 1] == "'":
            i += 1
            c = "'"
        if c == "'":
            i += 1
            parca: list[str] = []
            while i < n:
                if metin[i] == "'":
                    if i + 1 < n and metin[i + 1] == "'":
                        parca.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                parca.append(metin[i])
                i += 1
            satir.append("".join(parca))
            continue
        bitis = i
        while bitis < n and metin[bitis] not in ",)":
            bitis += 1
        belirtec = metin[i:bitis].strip()
        if belirtec.upper() == "NULL":
            satir.append(None)
        else:
            try:
                satir.append(int(belirtec))
            except ValueError:
                try:
                    satir.append(float(belirtec))
                except ValueError as exc:
                    raise KaynakHatasi(f"Çözülemeyen değer: {belirtec!r}") from exc
        i = bitis
    if satir is not None:
        raise KaynakHatasi("Kapanmamış satır parantezi")
    return satirlar


_MERGE = re.compile(
    r"MERGE\s+dbo\.(\w+)\s+AS\s+t\s+USING\s*\(\s*VALUES(?P<govde>.*?)\)\s*AS\s+s\s*\((?P<kolonlar>[^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


def seed_sql_oku(metin: str) -> dict[str, list[dict[str, Any]]]:
    """V1.5 seed dosyasındaki `MERGE … USING (VALUES …) AS s(kolonlar)` blokları.

    Aynı tablonun birden çok bloğu birleştirilir. Kolon sayısı tutmayan satır
    sessizce atlanmaz, hata verir (profil eksik veriyle sayı üretmesin).
    """
    tablolar: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in _MERGE.finditer(metin):
        tablo = m.group(1)
        kolonlar = [k.strip() for k in m.group("kolonlar").split(",")]
        for satir in _tsql_degerleri(m.group("govde")):
            if len(satir) != len(kolonlar):
                raise KaynakHatasi(
                    f"{tablo}: {len(kolonlar)} kolon beklenirken {len(satir)} değer: {satir[:3]}"
                )
            tablolar[tablo].append(dict(zip(kolonlar, satir, strict=True)))
    return dict(tablolar)


def tablo_dosyasi_oku(yol: Path) -> list[dict[str, Any]]:
    """SSMS dökümü: xlsx (ilk sayfa) ya da UTF-8 csv; ilk satır kolon adları."""
    if yol.suffix.lower() == ".csv":
        with yol.open(encoding="utf-8-sig", newline="") as f:
            return [dict(s) for s in csv.DictReader(f)]
    from openpyxl import load_workbook

    wb = load_workbook(yol, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        satirlar = ws.iter_rows(values_only=True)
        basliklar = [str(b).strip() if b is not None else "" for b in next(satirlar, ())]
        return [
            dict(zip(basliklar, s, strict=False))
            for s in satirlar
            if s and any(h is not None for h in s)
        ]
    finally:
        wb.close()


# --- Profil ---------------------------------------------------------------------


@dataclass
class Profil:
    ozet: list[tuple[str, Any, str]] = field(default_factory=list)
    sayfalar: dict[str, Sayfa] = field(default_factory=dict)
    sayilar: dict[str, int] = field(default_factory=dict)

    def ekle(self, anahtar: str, ad: str, deger: Any, aciklama: str = "") -> None:
        if isinstance(deger, int):
            self.sayilar[anahtar] = deger
        self.ozet.append((ad, deger, aciklama))


def _aktif_mi(satir: dict[str, Any]) -> bool:
    deger = satir.get("IsActive")
    if deger is None or (isinstance(deger, str) and not deger.strip()):
        return True  # seed dosyasında kolon yok: hepsi aktif yüklenir
    return str(deger).strip().lower() not in ("0", "false", "hayır")


def _dagilim_sayfasi(sayac: Counter, baslik: str) -> list[list[Any]]:
    return [
        [baslik, deger if deger is not None else "(boş)", adet]
        for deger, adet in sayac.most_common()
    ]


def profil_cikar(
    cihazlar: list[dict[str, Any]],
    *,
    sozlesmeler: list[dict[str, Any]] | None = None,
    kalemler: list[dict[str, Any]] | None = None,
    hesap_anahtarlari: dict[str, int] | None = None,
) -> Profil:
    """Kaynak satırlardan profil üretir. Hiçbir yere yazmaz.

    `hesap_anahtarlari`: `title_key → aynı anahtarlı aktif hesap sayısı`
    (yalnız `--db` ile); verilmezse eşleşme oranı "ÖLÇÜLMEDİ".
    """
    p = Profil()
    seri_fn, seri_adi = seri_anahtari_fonksiyonu()
    aktifler = [c for c in cihazlar if _aktif_mi(c)]

    p.ekle("toplam_satir", "kütük satırı", len(cihazlar), "kaynaktaki tüm satırlar")
    p.ekle("aktif_satir", "aktif kütük satırı", len(aktifler), "IsActive=1 (seed: hepsi)")

    dagilim = Sayfa(["Boyut", "Değer", "Adet"])
    dagilim.satirlar += _dagilim_sayfasi(Counter(c.get("DeviceType") for c in cihazlar), "tip")
    dagilim.satirlar += _dagilim_sayfasi(Counter(c.get("Brand") for c in cihazlar), "marka")
    p.sayfalar["Tip_Marka"] = dagilim
    p.ekle(
        "farkli_model_metni",
        "farklı model metni",
        len({str(c.get("Model")).strip() for c in cihazlar if not _bos_mu(c.get("Model"))}),
        "ham",
    )
    p.ekle(
        "farkli_model_anahtari",
        "farklı model anahtarı",
        len({k for c in cihazlar if (k := model_anahtari(c.get("Model")))}),
        "model_anahtari (boşluk/- atılmış)",
    )

    # Seri no ---------------------------------------------------------------
    serisiz = [c for c in cihazlar if _bos_mu(c.get("SerialNo"))]
    p.ekle("serisiz", "seri no'suz satır", len(serisiz), "SerialNo boş; seri uydurulmaz")

    gruplar: dict[str, list[dict]] = defaultdict(list)
    tip_marka_gruplari: dict[tuple, list[dict]] = defaultdict(list)
    for c in aktifler:
        anahtar = seri_fn(c.get("SerialNo"))
        if anahtar:
            gruplar[anahtar].append(c)
            tip_marka_gruplari[
                (tr_normkey(c.get("DeviceType")), tr_normkey(c.get("Brand")), anahtar)
            ].append(c)
    mukerrer = {k: v for k, v in gruplar.items() if len(v) > 1}
    p.ekle(
        "mukerrer_seri_grup", "mükerrer seri grubu", len(mukerrer), f"aktif; anahtar: {seri_adi}"
    )
    p.ekle(
        "mukerrer_seri_satir",
        "mükerrer gruplardaki satır",
        sum(len(v) for v in mukerrer.values()),
        "aktif",
    )
    p.ekle(
        "mukerrer_tip_marka_seri_grup",
        "mükerrer tip+marka+seri grubu",
        sum(1 for v in tip_marka_gruplari.values() if len(v) > 1),
        "E03-02 409 kuralının göçte karşılaşacağı grup",
    )
    mukerrer_sayfa = Sayfa(["Seri Anahtarı", "Satır", "SourceKey'ler", "Tipler", "Müşteriler"])
    for anahtar in sorted(mukerrer):
        grup = mukerrer[anahtar]
        mukerrer_sayfa.satirlar.append(
            [
                anahtar,
                len(grup),
                ", ".join(str(c.get("SourceKey") or c.get("SecurityDeviceId") or "") for c in grup),
                " | ".join(sorted({str(c.get("DeviceType") or "") for c in grup})),
                " | ".join(sorted({str(c.get("CustomerName") or "") for c in grup})),
            ]
        )
    p.sayfalar["Mukerrer_Seri"] = mukerrer_sayfa

    # Lokasyon / müşteri -------------------------------------------------------
    p.ekle(
        "lokasyonsuz",
        "lokasyonsuz satır",
        sum(1 for c in cihazlar if _bos_mu(c.get("Location"))),
        "Location boş",
    )
    p.ekle(
        "musterisiz",
        "müşterisiz satır",
        sum(1 for c in cihazlar if _bos_mu(c.get("CustomerName"))),
        "CustomerName boş",
    )

    # Teslim tarihi deseni ------------------------------------------------------
    desenler = Counter(teslim_deseni(c.get("DeliveryDateText")) for c in cihazlar)
    desen_sayfa = Sayfa(["Desen", "Adet", "Örnek Değerler"])
    for desen, adet in desenler.most_common():
        ornekler = sorted(
            {
                str(c.get("DeliveryDateText")).strip()
                for c in cihazlar
                if teslim_deseni(c.get("DeliveryDateText")) == desen and desen != "BOS"
            }
        )[:10]
        desen_sayfa.satirlar.append([desen, adet, ", ".join(ornekler)])
    p.sayfalar["Teslim_Tarihi_Deseni"] = desen_sayfa
    p.ekle("teslim_excel_gun", "teslim tarihi Excel gün sayısı", desenler["EXCEL_GUN"], "")
    p.ekle("teslim_gg_aa_yyyy", "teslim tarihi GG.AA.YYYY (geçerli)", desenler["GG.AA.YYYY"], "")
    p.ekle(
        "teslim_okunamaz",
        "teslim tarihi okunamaz",
        desenler["GG.AA.YYYY_GECERSIZ"] + desenler["GECERSIZ"] + desenler["DIGER"],
        "geçersiz gün/ay veya serbest metin",
    )
    p.ekle("teslim_bos", "teslim tarihi boş", desenler["BOS"], "")

    # PB kalemleri ---------------------------------------------------------------
    if kalemler is None:
        p.ekle("pb_kalem", "PB kalemi", OLCULMEDI, "MaintenanceDeviceItems verilmedi")
        p.ekle("pb_kalem_cihazsiz", "cihaz kimliği boş PB kalemi", OLCULMEDI, "")
    else:
        p.ekle("pb_kalem", "PB kalemi", len(kalemler), "MaintenanceDeviceItems")
        p.ekle(
            "pb_kalem_cihazsiz",
            "cihaz kimliği boş PB kalemi",
            sum(1 for k in kalemler if _bos_mu(k.get("SecurityDeviceId"))),
            "SecurityDeviceId NULL (E03-05 kabul 3)",
        )

    # Sözleşme – kütük müşteri adı eşleşmesi ------------------------------------
    kutuk_adlari = {
        str(c.get("CustomerName")) for c in aktifler if not _bos_mu(c.get("CustomerName"))
    }
    kutuk_anahtarlari = {tr_normkey(a) for a in kutuk_adlari}
    if sozlesmeler is None:
        p.ekle("sozlesme", "aktif sözleşme", OLCULMEDI, "MaintenanceContracts verilmedi")
    else:
        aktif_sozlesmeler = [s for s in sozlesmeler if _aktif_mi(s)]
        birebir = sum(1 for s in aktif_sozlesmeler if str(s.get("CustomerName")) in kutuk_adlari)
        katlanmis = sum(
            1 for s in aktif_sozlesmeler if tr_normkey(s.get("CustomerName")) in kutuk_anahtarlari
        )
        p.ekle("sozlesme", "aktif sözleşme", len(aktif_sozlesmeler), "")
        p.ekle(
            "sozlesme_kutuk_birebir",
            "kütükte birebir müşteri adı olan sözleşme",
            birebir,
            f"V1 eşleştirme kuralı; oran {_oran(birebir, len(aktif_sozlesmeler))}",
        )
        p.ekle(
            "sozlesme_kutuk_katlanmis",
            "kütükte tr_normkey müşteri adı olan sözleşme",
            katlanmis,
            f"oran {_oran(katlanmis, len(aktif_sozlesmeler))}",
        )

    # Hesaplarla otomatik eşleşme ------------------------------------------------
    if hesap_anahtarlari is None:
        p.ekle("hesap_tekil", "accounts ile tekil eşleşen müşteri adı", OLCULMEDI, "--db verilmedi")
    else:
        tekil = belirsiz = yok = 0
        for anahtar in kutuk_anahtarlari:
            adet = hesap_anahtarlari.get(anahtar, 0)
            if adet == 1:
                tekil += 1
            elif adet > 1:
                belirsiz += 1
            else:
                yok += 1
        toplam = len(kutuk_anahtarlari)
        p.ekle("kutuk_musteri_adi", "kütükte farklı müşteri adı (tr_normkey)", toplam, "")
        p.ekle(
            "hesap_tekil",
            "accounts ile tekil eşleşen müşteri adı",
            tekil,
            f"title_key eşit, tek aktif hesap; oran {_oran(tekil, toplam)}",
        )
        p.ekle("hesap_belirsiz", "birden çok hesapla eşleşen müşteri adı", belirsiz, "insana döner")
        p.ekle("hesap_yok", "hesabı olmayan müşteri adı", yok, "")

    # Tasarım karşılaştırması ----------------------------------------------------
    karsilastirma = Sayfa(["Ölçüm", "Ölçülen", "Tasarım (seed)", "Fark"])
    for anahtar, tasarim in TASARIM_SAYILARI.items():
        olculen = p.sayilar.get(anahtar)
        karsilastirma.satirlar.append(
            [
                anahtar,
                olculen if olculen is not None else OLCULMEDI,
                tasarim,
                olculen - tasarim if olculen is not None else "",
            ]
        )
    p.sayfalar["Tasarim_Karsilastirma"] = karsilastirma
    return p


def _oran(pay: int, payda: int) -> str:
    return f"%{100 * pay / payda:.1f}" if payda else "-"


# --- Canlı PG (salt okunur) ------------------------------------------------------


async def hesap_anahtarlari_oku(conn: AsyncConnection) -> dict[str, int]:
    satirlar = await conn.execute(
        text(
            "SELECT title_key, count(*) FROM accounts "
            "WHERE is_active AND NOT is_deleted GROUP BY title_key"
        )
    )
    return {s[0]: s[1] for s in satirlar.all()}


async def canli_kutuk_olc(conn: AsyncConnection, p: Profil) -> None:
    """`service_equipment` (göç sonrası canlı kütük) mükerrer/serisiz sayıları."""
    satirlar = (
        await conn.execute(
            text(
                """
                SELECT birim,
                       count(*) AS toplam,
                       count(*) FILTER (
                           WHERE is_active AND NOT is_deleted AND merged_into_id IS NULL
                       ) AS aktif,
                       count(*) FILTER (
                           WHERE is_active AND NOT is_deleted AND merged_into_id IS NULL
                             AND (serial_no IS NULL OR btrim(serial_no) = '')
                       ) AS serisiz
                FROM service_equipment GROUP BY birim ORDER BY birim
                """
            )
        )
    ).all()
    mukerrer = (
        await conn.execute(
            text(
                """
                SELECT birim, count(*) AS grup, sum(n) AS satir FROM (
                    SELECT birim, serial_key, count(*) AS n FROM service_equipment
                    WHERE is_active AND NOT is_deleted AND merged_into_id IS NULL
                      AND serial_key IS NOT NULL AND serial_key <> ''
                    GROUP BY birim, serial_key HAVING count(*) > 1
                ) x GROUP BY birim
                """
            )
        )
    ).all()
    muk = {m.birim: (m.grup, int(m.satir)) for m in mukerrer}
    sayfa = Sayfa(
        ["Birim", "Toplam", "Aktif", "Serisiz (aktif)", "Mükerrer Grup", "Mükerrer Satır"]
    )
    for s in satirlar:
        grup, satir = muk.get(s.birim, (0, 0))
        sayfa.satirlar.append([s.birim, s.toplam, s.aktif, s.serisiz, grup, satir])
    p.sayfalar["Canli_Kutuk"] = sayfa
    p.ekle(
        "canli_toplam", "canlı kütük (service_equipment) satırı", sum(s.toplam for s in satirlar)
    )
    p.ekle("canli_serisiz", "canlı kütük serisiz aktif satır", sum(s.serisiz for s in satirlar))
    p.ekle(
        "canli_mukerrer_grup", "canlı kütük mükerrer seri grubu", sum(g for g, _ in muk.values())
    )
    p.ekle("canli_mukerrer_satir", "canlı kütük mükerrer satır", sum(s for _, s in muk.values()))


# --- Çalıştırma ------------------------------------------------------------------


def kaynaklari_topla(
    *,
    seed_sql: Path | None = None,
    kutuk: Path | None = None,
    kalemler: Path | None = None,
    sozlesmeler: Path | None = None,
) -> dict[str, list[dict[str, Any]] | None]:
    """Dosya verilen tablo seed'dekinin yerine geçer; hiç kaynağı olmayan None."""
    tablolar: dict[str, list[dict[str, Any]] | None] = dict.fromkeys(TABLOLAR)
    if seed_sql is not None:
        tablolar.update(seed_sql_oku(seed_sql.read_text(encoding="utf-8-sig")))
    for ad, yol in (
        ("SecurityDevices", kutuk),
        ("MaintenanceDeviceItems", kalemler),
        ("MaintenanceContracts", sozlesmeler),
    ):
        if yol is not None:
            tablolar[ad] = tablo_dosyasi_oku(yol)
    return tablolar


async def calistir(
    tablolar: dict[str, list[dict[str, Any]] | None],
    *,
    engine: AsyncEngine | None,
    cikti: Path | None,
    clock: Clock,
) -> Profil:
    cihazlar = tablolar.get("SecurityDevices")
    if not cihazlar:
        raise KaynakHatasi("Kütük (SecurityDevices) satırı yok: --seed-sql ya da --kutuk verin")
    hesaplar: dict[str, int] | None = None
    if engine is not None:
        async with salt_okunur(engine) as conn:
            hesaplar = await hesap_anahtarlari_oku(conn)
            profil = profil_cikar(
                cihazlar,
                sozlesmeler=tablolar.get("MaintenanceContracts"),
                kalemler=tablolar.get("MaintenanceDeviceItems"),
                hesap_anahtarlari=hesaplar,
            )
            await canli_kutuk_olc(conn, profil)
    else:
        profil = profil_cikar(
            cihazlar,
            sozlesmeler=tablolar.get("MaintenanceContracts"),
            kalemler=tablolar.get("MaintenanceDeviceItems"),
        )
    if cikti is not None:
        ozet = Sayfa(["Ölçüm", "Değer", "Açıklama"])
        ozet.satirlar.append(["ölçüm zamanı (UTC)", clock.now().isoformat(timespec="seconds"), ""])
        ozet.satirlar.extend([list(s) for s in profil.ozet])
        cikti.write_bytes(cok_sayfali_xlsx({"Ozet": ozet, **profil.sayfalar}))
    return profil


def _yaz(satirlar: Iterable[tuple[str, Any, str]]) -> None:
    for ad, deger, aciklama in satirlar:
        print(f"  {ad:48s} {deger!s:>10}  {aciklama}")


async def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Göç öncesi kütük profili (salt okunur)")
    ayristirici.add_argument("--seed-sql", type=Path, help="V1.5 seed SQL dosyası")
    ayristirici.add_argument("--kutuk", type=Path, help="SecurityDevices dökümü (xlsx/csv)")
    ayristirici.add_argument("--kalemler", type=Path, help="MaintenanceDeviceItems dökümü")
    ayristirici.add_argument("--sozlesmeler", type=Path, help="MaintenanceContracts dökümü")
    ayristirici.add_argument("--db", action="store_true", help="Canlı PG'yi de salt okunur ölç")
    ayristirici.add_argument("--cikti", type=Path, help="xlsx rapor dosyası")
    args = ayristirici.parse_args(argv)

    for yol in (args.seed_sql, args.kutuk, args.kalemler, args.sozlesmeler):
        if yol is not None and not yol.is_file():
            print(f"Dosya yok: {yol}", file=sys.stderr)
            return 1
    try:
        tablolar = kaynaklari_topla(
            seed_sql=args.seed_sql,
            kutuk=args.kutuk,
            kalemler=args.kalemler,
            sozlesmeler=args.sozlesmeler,
        )
        engine = None
        if args.db:
            from app.db import get_engine

            engine = get_engine()
        try:
            profil = await calistir(tablolar, engine=engine, cikti=args.cikti, clock=RealClock())
        finally:
            if engine is not None:
                await engine.dispose()
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1

    print("=" * 70)
    print("KÜTÜK PROFİLİ — salt okunur, hiçbir şey yazılmadı")
    print("=" * 70)
    _yaz(profil.ozet)
    print("\nTASARIM KARŞILAŞTIRMASI (ölçülen / tasarım):")
    for anahtar, olculen, tasarim, fark in profil.sayfalar["Tasarim_Karsilastirma"].satirlar:
        print(f"  {anahtar:30s} {olculen!s:>10} / {tasarim:<6} {fark!s}")
    if args.cikti:
        print(f"\nRapor: {args.cikti}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
