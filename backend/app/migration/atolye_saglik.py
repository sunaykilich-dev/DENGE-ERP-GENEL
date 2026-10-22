"""Atölye pilot verisi sağlık raporu — SALT OKUNUR (TS-205, E05-23).

    uv run python -m app.migration.atolye_saglik --kaynak <döküm> [--cikti atolye_saglik.xlsx]
    make goc-atolye-saglik KAYNAK=<döküm>

Eski .NET V1.20.1 atölye modülü yalnız pilot olarak kullanıldı. Göç KOŞULLUDUR
(plan §5.3 adım 4.5): pilot gerçek veri üretmediyse göç yoktur, bu rapor tek
çıktıdır. Göç kararı bu raporun kullanıcı onaylı çıktısıyla verilir (E05-23
kabul 3); karar verilmeden hiçbir atölye kaydı yazılmaz.

**Hiçbir tabloya yazmaz.** Döküm dosyaları okunur; kişi eşlemesi için DB
`SET TRANSACTION READ ONLY` bağlantıyla okunur (`ana_veri_olcum.salt_okunur`)
ve transaction her durumda geri alınır.

Yedi bölüm (E05-23):

1. **Durum uyuşmazlığı** — atölye kaydı kapalı (Teslim Edildi/İptal) iken bağlı
   iş emri açık, ya da tersi.
2. **İptal-açık iş** — atölye kaydı İptal, bağlı iş emri hâlâ açık.
3. **Seri farkı** — atölye kaydının serisi bağlı iş emrinin hiçbir serisiyle
   (`WorkOrders.SerialNo` + `WorkOrderDevices`) eşleşmiyor (normalize_seri).
4. **Eşleşmeyen AssignedTo** — ad, ne onaylı ad eşlemesinde ne tek bir
   kullanıcının adında bulunuyor (eşleme UYDURULMAZ; birden çok aynı adlı
   kullanıcı da eşleşmez sayılır).
5. **Yetim iş emri** — atölye türlü iş emrinin atölye kaydı yok; ya da atölye
   kaydının iş emri dökümde yok.
6. **Mükerrer açık seri** — aynı seri birden çok AÇIK atölye kaydında.
7. **Eski durum dağılımı** — eski durum → yeni atölye durumu eşlemesi ve
   adetleri; eşlenemeyen durum ayrıca işaretlenir.

`received_at` kaynak `EntryDate`'tir (yerel saat; eski sistemin kayması
düzeltilmez, rapora not düşülür). "Garanti Değil" dönüştürülmez.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx, salt_okunur
from app.migration.servis_kaynak import KaynakDizini, KaynakHatasi, bit, metin, tamsayi
from app.models import PersonnelNameMap, User
from app.services.normalize import normalize_seri, tr_normkey
from app.services.teknik_servis import ad_esleme

KAYNAK_TABLO = "WorkshopTickets"

# Eski atölye durumu → yeni atölye durumu (E05-23). Tanınmayan durum raporlanır.
DURUM_ESLEME = {
    "yeni kayit": "KABUL_EDILDI",
    "onarimda": "ONARIMDA",
    "beklemede": "PARCA_BEKLIYOR",
    "test / kontrol": "TEST_KONTROL",
    "tamamlandi": "TESLIME_HAZIR",
    "teslim edildi": "TESLIM_EDILDI",
    "iptal": "IPTAL",
}
_ATOLYE_KAPALI = {"teslim edildi", "iptal"}
_IS_KAPALI = {"tamamlandi", "kapatildi", "cozuldu", "iptal"}
# Atölye kaydı beklenen eski iş türleri (servis göçünde de karantinaya alınanlar).
ATOLYE_IS_TURLERI = {"atolye tamir", "atolye teknik servis"}

BOLUMLER = (
    ("DURUM_UYUSMAZLIGI", "Durum uyuşmazlığı"),
    ("IPTAL_ACIK_IS", "İptal kayıt - açık iş emri"),
    ("SERI_FARKI", "Seri farkı"),
    ("ESLESMEYEN_ATANAN", "Eşleşmeyen AssignedTo"),
    ("YETIM_IS", "Yetim iş emri / kayıt"),
    ("MUKERRER_ACIK_SERI", "Mükerrer açık seri"),
    ("DURUM_DAGILIMI", "Eski durum dağılımı"),
)


@dataclass
class SaglikRaporu:
    """Yedi bölümün satırları. `DURUM_DAGILIMI` satırı (eski, yeni, adet)."""

    kayit_sayisi: int = 0
    bolumler: dict[str, list[list[Any]]] = field(
        default_factory=lambda: {kod: [] for kod, _ in BOLUMLER}
    )
    notlar: list[str] = field(default_factory=list)

    @property
    def sayilar(self) -> dict[str, int]:
        return {kod: len(satirlar) for kod, satirlar in self.bolumler.items()}

    @property
    def goc_gerekli(self) -> bool:
        """Pilot gerçek veri üretmediyse göç yok (plan §5.3)."""
        return self.kayit_sayisi > 0


def _seriler(*hamlar: str | None) -> set[str]:
    kume: set[str] = set()
    for ham in hamlar:
        for parca in (ham or "").replace(";", ",").replace("\n", ",").split(","):
            anahtar = normalize_seri(parca.strip())
            if anahtar:
                kume.add(anahtar)
    return kume


def saglik_raporu(dizin: KaynakDizini, kisiler: dict[str, int | None]) -> SaglikRaporu:
    """Saf hesap (DB'siz). `kisiler`: normal ad → kullanıcı (None = belirsiz).

    Kaynak dosya yoksa rapor boştur ve `goc_gerekli=False` olur (eksik döküm
    "kayıt yok" ile karışmasın diye bu durum notlara yazılır).
    """
    rapor = SaglikRaporu()
    if not dizin.var_mi(KAYNAK_TABLO):
        rapor.notlar.append(
            f"{KAYNAK_TABLO}.csv dökümde yok — pilot atölye verisi alınmamış; göç yok."
        )
        return rapor
    kayitlar = dizin.tablo(KAYNAK_TABLO)
    rapor.kayit_sayisi = len(kayitlar)
    rapor.notlar.append(
        "received_at = EntryDate (eski sistem yerel saati); eski kayma düzeltilmez."
    )
    isler = {
        k: w
        for w in dizin.tablo("WorkOrders", zorunlu=False)
        if (k := tamsayi(w.get("WorkOrderId"))) is not None
    }
    cihazlar: dict[int, list[str]] = defaultdict(list)
    for c in dizin.tablo("WorkOrderDevices", zorunlu=False):
        k = tamsayi(c.get("WorkOrderId"))
        if k is not None and bit(c.get("IsActive"), varsayilan=True):
            cihazlar[k].append(c.get("SerialNo") or "")
    b = rapor.bolumler
    durumlar: Counter[str] = Counter()
    acik_seriler: dict[str, list[str]] = defaultdict(list)
    atolyeli_isler: set[int] = set()

    for t in kayitlar:
        no = metin(t.get("WorkshopNo")) or f"#{t.get('WorkshopTicketId')}"
        durum_ham = metin(t.get("Status")) or "Yeni Kayıt"
        durum_k = tr_normkey(durum_ham)
        durumlar[durum_ham] += 1
        atolye_kapali = durum_k in _ATOLYE_KAPALI
        seri = metin(t.get("SerialNo"))
        anahtar = normalize_seri(seri or "")
        if anahtar and not atolye_kapali:
            acik_seriler[anahtar].append(no)

        atanan = metin(t.get("AssignedTo"))
        if atanan and kisiler.get(ad_esleme.normal_ad(atanan)) is None:
            neden = (
                "aynı adlı birden çok kullanıcı"
                if ad_esleme.normal_ad(atanan) in kisiler
                else "kullanıcı/onaylı eşleme yok"
            )
            b["ESLESMEYEN_ATANAN"].append([no, atanan, neden])

        is_id = tamsayi(t.get("WorkOrderId"))
        if is_id is None:
            continue
        atolyeli_isler.add(is_id)
        w = isler.get(is_id)
        if w is None:
            b["YETIM_IS"].append([no, f"WorkOrders:{is_id}", "Atölye kaydının iş emri dökümde yok"])
            continue
        is_durum = metin(w.get("Status")) or ""
        is_kapali = tr_normkey(is_durum) in _IS_KAPALI
        if atolye_kapali != is_kapali:
            b["DURUM_UYUSMAZLIGI"].append([no, durum_ham, w.get("WorkOrderNo"), is_durum])
        if durum_k == "iptal" and not is_kapali:
            b["IPTAL_ACIK_IS"].append([no, w.get("WorkOrderNo"), is_durum])
        is_serileri = _seriler(w.get("SerialNo"), *cihazlar.get(is_id, []))
        if anahtar and is_serileri and anahtar not in is_serileri:
            b["SERI_FARKI"].append([no, seri, w.get("WorkOrderNo"), ", ".join(sorted(is_serileri))])

    for is_id, w in sorted(isler.items()):
        if tr_normkey(w.get("WorkType")) in ATOLYE_IS_TURLERI and is_id not in atolyeli_isler:
            b["YETIM_IS"].append(
                [w.get("WorkOrderNo"), f"WorkOrders:{is_id}", "Atölye işinin atölye kaydı yok"]
            )
    for anahtar, nolar in sorted(acik_seriler.items()):
        if len(nolar) > 1:
            b["MUKERRER_ACIK_SERI"].append([anahtar, len(nolar), ", ".join(nolar)])
    for ham, adet in sorted(durumlar.items()):
        yeni = DURUM_ESLEME.get(tr_normkey(ham))
        b["DURUM_DAGILIMI"].append([ham, yeni or "EŞLENEMEDİ", adet])
    return rapor


async def kisi_haritasi(conn: AsyncConnection) -> dict[str, int | None]:
    """Normal ad → kullanıcı: önce ONAYLI ad eşlemesi, sonra tek kullanıcı adı.

    Aynı ad birden çok kişiye çıkarsa değer None'dır (belirsiz, eşleşmez sayılır).
    """
    harita: dict[str, int | None] = {}
    for uid, ad in (await conn.execute(select(User.id, User.full_name))).all():
        n = ad_esleme.normal_ad(ad)
        if n:
            harita[n] = None if n in harita and harita[n] != uid else uid
    onayli: dict[str, int | None] = {}
    for norm, uid in (
        await conn.execute(
            select(PersonnelNameMap.normal_ad, PersonnelNameMap.onaylanan_user_id).where(
                PersonnelNameMap.durum == "ONAYLANDI",
                PersonnelNameMap.onaylanan_user_id.is_not(None),
            )
        )
    ).all():
        # Aynı ad farklı alanlarda farklı kişiye onaylandıysa belirsiz (ada_gore kuralı).
        onayli[norm] = None if norm in onayli and onayli[norm] != uid else uid
    harita.update(onayli)
    return harita


def rapor_xlsx(rapor: SaglikRaporu) -> bytes:
    basliklar = {
        "DURUM_UYUSMAZLIGI": ["Atölye No", "Atölye Durumu", "İş Emri No", "İş Emri Durumu"],
        "IPTAL_ACIK_IS": ["Atölye No", "İş Emri No", "İş Emri Durumu"],
        "SERI_FARKI": ["Atölye No", "Atölye Serisi", "İş Emri No", "İş Emri Serileri"],
        "ESLESMEYEN_ATANAN": ["Atölye No", "AssignedTo", "Neden"],
        "YETIM_IS": ["No", "Kaynak", "Neden"],
        "MUKERRER_ACIK_SERI": ["Seri (normalize)", "Açık Kayıt", "Atölye Nolar"],
        "DURUM_DAGILIMI": ["Eski Durum", "Yeni Durum", "Adet"],
    }
    ozet = Sayfa(["Bölüm", "Adet"], [["Atölye kaydı (kaynak)", rapor.kayit_sayisi]])
    ozet.satirlar += [[ad, rapor.sayilar[kod]] for kod, ad in BOLUMLER]
    ozet.satirlar += [["Göç gerekli mi", "EVET" if rapor.goc_gerekli else "HAYIR"]]
    ozet.satirlar += [["Not", n] for n in rapor.notlar]
    sayfalar = {"Ozet": ozet}
    for i, (kod, _ad) in enumerate(BOLUMLER, start=1):
        sayfalar[f"{i}_{kod}"[:31]] = Sayfa(basliklar[kod], rapor.bolumler[kod])
    return cok_sayfali_xlsx(sayfalar)


def _yazdir(rapor: SaglikRaporu) -> None:
    print("=" * 72)
    print("ATÖLYE PİLOT VERİSİ SAĞLIK RAPORU (SALT OKUNUR — HİÇBİR ŞEY YAZILMADI)")
    print("=" * 72)
    print(f"Atölye kaydı: {rapor.kayit_sayisi}")
    for kod, ad in BOLUMLER:
        print(f"  {ad:34s}{rapor.sayilar[kod]:>6}")
    for n in rapor.notlar:
        print(f"Not: {n}")
    print("Göç: " + ("karar gerekli (rapor onayıyla)" if rapor.goc_gerekli else "gerekmez"))


async def _calistir(args: argparse.Namespace) -> int:
    from app.db import get_engine

    dizin = KaynakDizini(args.kaynak)
    engine = get_engine()
    try:
        async with salt_okunur(engine) as conn:
            kisiler = await kisi_haritasi(conn)
    finally:
        await engine.dispose()
    rapor = saglik_raporu(dizin, kisiler)
    _yazdir(rapor)
    if args.cikti:
        args.cikti.write_bytes(rapor_xlsx(rapor))
        print(f"\nRapor: {args.cikti}")
    return 0


def komut_satiri(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Atölye pilot verisi sağlık raporu (salt okunur)")
    ayr.add_argument("--kaynak", type=Path, required=True, help="CSV döküm dizini")
    ayr.add_argument("--cikti", type=Path, help="Rapor xlsx")
    args = ayr.parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(_calistir(args))
    except KaynakHatasi as exc:
        print(f"Kaynak okunamadı: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(komut_satiri())
