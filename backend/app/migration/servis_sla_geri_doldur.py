"""Göç işlerinde SLA alanlarının geri doldurulması — rapor modu + idempotent uygula (TS-207).

    uv run python -m app.migration.servis_sla_geri_doldur rapor  [--kaynak <döküm>] [--cikti x.xlsx]
    uv run python -m app.migration.servis_sla_geri_doldur uygula [--kaynak <döküm>] [--cikti x.xlsx]
    make goc-servis-sla-rapor / make goc-servis-sla-uygula

E10-15 ve E10 kontrol kararı (KD-22, E10-D02): **kapalı tarihsel işe bugünkü
politikayla hedef YAZILMAZ** — bu, "uydurma veri yazılmaz" ilkesine aykırı
olurdu. Bu yüzden:

- **Kapalı göç işi** (TAMAMLANDI/KAPATILDI) → `sla_sonuc='OLCULEMEDI'`
  (uyum paydasına girmez). `GERIYE_DONUK` hesap (açılış + bugünkü politika
  saati, tamamlanma anıyla karşılaştırma) **yalnız raporda** gösterilir,
  hiçbir kolona yazılmaz.
- **Açık göç işi** → hedef SLA yürürlük anından (`servis_sla_yururluk_at`)
  damgalanır, `sla_kaynak='GECIS'` (kapanışta gecikme nedeni zorunlu
  DEĞİLDİR, `sla.kapanis_dogrula`). Yürürlük anı tanımsızsa açık iş
  damgalanmaz ve raporda "yürürlük yok" sayılır (canlıya geçişte göç
  işleri uyarı fırtınası üretmesin).
- `ilk_mudahale_at`, yalnız eski durum logunda saha/işlem/atölye geçişi
  varsa (göçün yazdığı DURUM olayları) doldurulur; uydurulmaz.
- PB hariçtir; atölye işi ölçülmez ve AYRI satırda sayılır; GUNLUK_SERVIS
  dışı (proje) ve iptal işler dokunulmadan sayılır. Aktif politikası
  olmayan öncelik "katalog dışı öncelik" olarak raporlanır ve yazılmaz.
- Kaynak döküm verilirse eski `OpsHolds` nedenleri anahtar kelimeyle
  sözlüğe eşlenir ve eşlenemeyenler (DIGER) ile eski `Priority`
  değerlerinin eşlemesi raporlanır (göç `Acil→YUKSEK` gibi eşlemeleri
  uygulamıştır; burada onaya sunulur). Bekleme satırı YAZILMAZ.

Yalnız `source_system='DENGEERP_V1' AND sla_kaynak IS NULL AND sla_sonuc IS
NULL` işler adaydır: ikinci `uygula` 0 satır değiştirir. Rapor modu hiçbir
şey yazmaz (transaction geri alınır). Uygula tek transaction'dır ve denetime
`sla.geri_doldur` yazar.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock, RealClock
from app.migration.ana_veri_olcum import Sayfa, cok_sayfali_xlsx
from app.migration.servis_goc import ONCELIK_ESLEME, durum_esle
from app.migration.servis_kaynak import GOC_SISTEMI, KaynakDizini, KaynakHatasi, metin
from app.models import ServiceOrder, ServiceOrderEvent, ServiceSlaPolicy
from app.models.teknik_servis import ONCELIKLER
from app.services import audit
from app.services.normalize import tr_normkey
from app.services.teknik_servis import sla, sla_takvim

# Sınıflar (rapor satırları). Yalnız GECIS ve OLCULEMEDI yazılır.
GECIS = "GECIS"
OLCULEMEDI = "OLCULEMEDI"
ATOLYE_OLCULEMEDI = "ATOLYE_OLCULEMEDI"
PB_HARIC = "PB_HARIC"
SLA_DISI = "SLA_DISI"
IPTAL = "IPTAL"
KATALOG_DISI = "KATALOG_DISI_ONCELIK"
YURURLUK_YOK = "YURURLUK_YOK"
SINIFLAR = (
    (GECIS, "Güncellenecek: açık iş (yürürlük anından damga)"),
    (OLCULEMEDI, "Ölçülemedi: kapalı göç işi"),
    (ATOLYE_OLCULEMEDI, "Atölye ölçülemedi (yazılmaz)"),
    (PB_HARIC, "PB hariç"),
    (SLA_DISI, "SLA dışı tür/kategori (yazılmaz)"),
    (IPTAL, "İptal iş (yazılmaz)"),
    (KATALOG_DISI, "Katalog dışı öncelik (politika yok, yazılmaz)"),
    (YURURLUK_YOK, "Açık iş, yürürlük anı tanımsız (yazılmaz)"),
)
YAZILAN_SINIFLAR = frozenset({GECIS, OLCULEMEDI})

# Eski serbest metin bekleme nedeni → sözlük (sıra önemli: ilk eşleşen).
BEKLEME_ANAHTARLARI = (
    ("malzeme", "MALZEME"),
    ("parca", "MALZEME"),
    ("teklif", "TEKLIF"),
    ("onay", "MUSTERI_ONAYI"),
    ("erisim", "MUSTERI_ERISIMI"),
    ("ulasilam", "MUSTERI_ERISIMI"),
    ("personel", "PERSONEL"),
    ("dis servis", "DIS_SERVIS"),
    ("uretici", "DIS_SERVIS"),
)


def bekleme_nedeni_esle(ham: str | None) -> str:
    k = tr_normkey(ham)
    for anahtar, kod in BEKLEME_ANAHTARLARI:
        if anahtar in k:
            return kod
    return "DIGER"


@dataclass
class Plan:
    """Bir işin geri doldurma kararı."""

    so_id: int
    so_no: str
    sinif: str
    ilk_mudahale_at: datetime | None = None
    hedef_at: datetime | None = None
    politika: ServiceSlaPolicy | None = None
    geriye_donuk: str | None = None  # yalnız rapor: ZAMANINDA / ASILDI / OLCULEMEDI
    geriye_donuk_hedef: datetime | None = None
    # Faz A: lokasyon → müşteri → politika → 7/24 (canlı damgayla aynı zincir).
    takvim_turu: str = "7_24"


@dataclass
class GeriDoldurma:
    planlar: list[Plan] = field(default_factory=list)
    yururluk: datetime | None = None
    bekleme_nedenleri: list[list[Any]] = field(default_factory=list)
    oncelik_eslemesi: list[list[Any]] = field(default_factory=list)
    degisen: int = 0

    @property
    def sayilar(self) -> dict[str, int]:
        c = Counter(p.sinif for p in self.planlar)
        return {kod: c.get(kod, 0) for kod, _ in SINIFLAR}

    @property
    def geriye_donuk_sayilari(self) -> dict[str, int]:
        return dict(Counter(p.geriye_donuk for p in self.planlar if p.geriye_donuk))


def _adaylar_sorgusu():
    return (
        select(ServiceOrder)
        .where(
            ServiceOrder.source_system == GOC_SISTEMI,
            ServiceOrder.sla_kaynak.is_(None),
            ServiceOrder.sla_sonuc.is_(None),
            ServiceOrder.is_deleted.is_(False),
        )
        .order_by(ServiceOrder.id)
    )


async def _ilk_mudahaleler(db: AsyncSession, so_idler: list[int]) -> dict[int, datetime]:
    """İşin eski durum logundan gelen İLK saha/işlem/atölye geçişi.

    Göç-1'in ilk sürümü DURUM olayının `yeni_durum` kolonunu boş yazmıştı
    (executemany anahtar hatası, `servis_goc.is_yaz`'da düzeltildi); o
    satırlarda durum `veri.yeni_ham`'dan aynı eşlemeyle (`durum_esle`) okunur.
    """
    if not so_idler:
        return {}
    sonuc: dict[int, datetime] = {}
    for so_id, yeni, veri, an in (
        await db.execute(
            select(
                ServiceOrderEvent.service_order_id,
                ServiceOrderEvent.yeni_durum,
                ServiceOrderEvent.veri,
                ServiceOrderEvent.olusma_zamani,
            ).where(
                ServiceOrderEvent.service_order_id.in_(so_idler),
                ServiceOrderEvent.olay_turu == "DURUM",
            )
        )
    ).all():
        durum = yeni or durum_esle((veri or {}).get("yeni_ham"))
        if durum in sla.MUDAHALE_DURUMLARI and (so_id not in sonuc or an < sonuc[so_id]):
            sonuc[so_id] = an
    return sonuc


async def _politika(
    db: AsyncSession, onbellek: dict[tuple[str, str], Any], oncelik: str, birim: str
) -> ServiceSlaPolicy | None:
    anahtar = (oncelik, birim)
    if anahtar not in onbellek:
        try:
            onbellek[anahtar] = await sla.politika_bul(db, oncelik, birim)
        except sla.SlaHatasi:
            onbellek[anahtar] = None
    return onbellek[anahtar]


def _hedef(
    bas: datetime, politika: ServiceSlaPolicy, tur: str, mesai: sla_takvim.MesaiTakvimi
) -> datetime:
    dk = int(round(float(politika.cozum_saat) * 60))
    return sla_takvim.is_saati_ekle(bas, dk, tur, mesai=mesai)


async def hazirla(db: AsyncSession) -> GeriDoldurma:
    """Hiçbir şey yazmadan her aday işin sınıfını ve (rapor) GERIYE_DONUK sonucunu çıkarır."""
    sonuc = GeriDoldurma(yururluk=await sla.yururluk_ani(db))
    isler = (await db.scalars(_adaylar_sorgusu())).all()
    mudahaleler = await _ilk_mudahaleler(db, [s.id for s in isler])
    politikalar: dict[tuple[str, str], Any] = {}
    mesai = await sla.mesai_takvimi(db)
    for so in isler:
        p = Plan(so.id, so.so_no, SLA_DISI, ilk_mudahale_at=mudahaleler.get(so.id))
        sonuc.planlar.append(p)
        if so.tur == "PB":
            p.sinif = PB_HARIC
            continue
        if so.tur == "ATOLYE":
            p.sinif = ATOLYE_OLCULEMEDI
            continue
        if not sla.sla_olculur_mu(so):
            continue
        if so.status == "IPTAL":
            p.sinif = IPTAL
            continue
        politika = await _politika(db, politikalar, so.oncelik, so.birim)
        p.takvim_turu = (await sla.takvim_turu_bul(db, so, politika))[0]
        kapali = so.status in ("TAMAMLANDI", "KAPATILDI") or so.first_completed_at is not None
        if kapali:
            p.sinif = OLCULEMEDI
            bitis = so.first_completed_at or so.completed_at or so.closed_at
            if politika is not None and so.created_at is not None and bitis is not None:
                p.geriye_donuk_hedef = _hedef(so.created_at, politika, p.takvim_turu, mesai)
                p.geriye_donuk = "ASILDI" if bitis > p.geriye_donuk_hedef else "ZAMANINDA"
            else:
                p.geriye_donuk = "OLCULEMEDI"
            continue
        if politika is None:
            p.sinif = KATALOG_DISI
            continue
        if sonuc.yururluk is None:
            p.sinif = YURURLUK_YOK
            continue
        p.sinif = GECIS
        p.politika = politika
        p.hedef_at = _hedef(sonuc.yururluk, politika, p.takvim_turu, mesai)
    return sonuc


def kaynak_raporu(sonuc: GeriDoldurma, dizin: KaynakDizini) -> None:
    """Eski `OpsHolds` nedenleri ve `Priority` değerlerinin eşlemesi (salt okunur)."""
    nedenler: Counter[tuple[str, str]] = Counter()
    for h in dizin.tablo("OpsHolds", zorunlu=False):
        ham = metin(h.get("Reason")) or ""
        nedenler[(ham, bekleme_nedeni_esle(ham))] += 1
    sonuc.bekleme_nedenleri = [
        [ham, kod, adet, "EŞLENEMEDİ" if kod == "DIGER" else ""]
        for (ham, kod), adet in sorted(nedenler.items())
    ]
    oncelikler: Counter[str] = Counter(
        metin(w.get("Priority")) or "" for w in dizin.tablo("WorkOrders", zorunlu=False)
    )
    for ham, adet in sorted(oncelikler.items()):
        k = tr_normkey(ham)
        if k.upper() in ONCELIKLER:
            yeni, not_ = k.upper(), ""
        elif k in ONCELIK_ESLEME:
            yeni, not_ = ONCELIK_ESLEME[k], "eşleme uygulandı (onaya sunulur)"
        else:
            yeni, not_ = "NORMAL", "KATALOG DIŞI — göçte NORMAL yazıldı"
        sonuc.oncelik_eslemesi.append([ham, yeni, adet, not_])


async def uygula(
    db: AsyncSession, sonuc: GeriDoldurma, *, clock: Clock, user_id: int | None = None
) -> int:
    """Yalnız GECIS ve OLCULEMEDI sınıflarını yazar; commit ÇAĞIRANDA."""
    degisen = 0
    for p in sonuc.planlar:
        if p.sinif not in YAZILAN_SINIFLAR:
            continue
        so = await db.get(ServiceOrder, p.so_id)
        if so is None or so.sla_kaynak is not None or so.sla_sonuc is not None:
            continue
        if so.ilk_mudahale_at is None and p.ilk_mudahale_at is not None:
            so.ilk_mudahale_at = p.ilk_mudahale_at
        if p.sinif == OLCULEMEDI:
            so.sla_sonuc = "OLCULEMEDI"
        else:
            politika = p.politika
            mudahale_dk = (
                int(round(float(politika.mudahale_saat) * 60))
                if politika.mudahale_saat is not None
                else None
            )
            tur = p.takvim_turu
            so.sla_policy_id = politika.id
            so.sla_baslangic_at = sonuc.yururluk
            so.sla_takvim_turu = tur
            so.cozum_hedef_dk = int(round(float(politika.cozum_saat) * 60))
            so.mudahale_hedef_dk = mudahale_dk
            so.cozum_hedef_ilk_at = so.cozum_hedef_at = p.hedef_at
            so.mudahale_hedef_at = (
                sla_takvim.is_saati_ekle(
                    sonuc.yururluk, mudahale_dk, tur, mesai=await sla.mesai_takvimi(db)
                )
                if mudahale_dk is not None and so.ilk_mudahale_at is None
                else None
            )
            so.sla_kaynak = "GECIS"
            db.add(
                ServiceOrderEvent(
                    service_order_id=so.id,
                    olay_turu="SLA",
                    ozet=(
                        f"SLA hedefi geçiş damgası (yürürlük anından): "
                        f"{p.hedef_at.isoformat()} ({so.oncelik})"
                    )[:500],
                    veri={
                        "sla_kaynak": "GECIS",
                        "sla_policy_id": politika.id,
                        "cozum_hedef_at": p.hedef_at.isoformat(),
                    },
                    user_id=user_id,
                    olusma_zamani=clock.now(),
                )
            )
        so.updated_by = user_id
        degisen += 1
    await db.flush()
    sonuc.degisen = degisen
    await audit.log(
        db,
        "service_orders",
        "sla.geri_doldur",
        new_value={"adet": degisen, **sonuc.sayilar},
        user_id=user_id,
    )
    return degisen


def rapor_xlsx(sonuc: GeriDoldurma) -> bytes:
    ozet = Sayfa(["Sınıf", "Açıklama", "Adet"])
    ozet.satirlar += [[kod, ad, sonuc.sayilar[kod]] for kod, ad in SINIFLAR]
    ozet.satirlar.append(
        [
            "YURURLUK",
            "servis_sla_yururluk_at",
            sonuc.yururluk.isoformat() if sonuc.yururluk else "-",
        ]
    )
    for kod, adet in sorted(sonuc.geriye_donuk_sayilari.items()):
        ozet.satirlar.append([f"GERIYE_DONUK_{kod}", "Yalnız rapor — yazılmaz", adet])
    isler = Sayfa(
        ["İş No", "Sınıf", "Hedef (GECIS)", "İlk Müdahale", "GERİYE DÖNÜK (rapor)", "GD Hedef"],
        [
            [
                p.so_no,
                p.sinif,
                p.hedef_at.isoformat() if p.hedef_at else None,
                p.ilk_mudahale_at.isoformat() if p.ilk_mudahale_at else None,
                p.geriye_donuk,
                p.geriye_donuk_hedef.isoformat() if p.geriye_donuk_hedef else None,
            ]
            for p in sonuc.planlar
        ],
    )
    return cok_sayfali_xlsx(
        {
            "Ozet": ozet,
            "Isler": isler,
            "Bekleme Nedenleri": Sayfa(
                ["Eski Neden", "Yeni Neden", "Adet", "Not"], sonuc.bekleme_nedenleri
            ),
            "Oncelik Eslemesi": Sayfa(
                ["Eski Öncelik", "Yeni Öncelik", "Adet", "Not"], sonuc.oncelik_eslemesi
            ),
        }
    )


async def _calistir(args: argparse.Namespace) -> int:
    from app.db import get_engine, get_session_factory

    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            sonuc = await hazirla(db)
            if args.kaynak:
                kaynak_raporu(sonuc, KaynakDizini(args.kaynak))
            if args.mod == "uygula":
                await uygula(db, sonuc, clock=RealClock())
                await db.commit()
            else:
                await db.rollback()
    finally:
        await engine.dispose()
    print("=" * 72)
    print(
        "SLA GERİ DOLDURMA — "
        + ("UYGULANDI" if args.mod == "uygula" else "RAPOR (HİÇBİR ŞEY YAZILMADI)")
    )
    print("=" * 72)
    for kod, ad in SINIFLAR:
        print(f"  {ad:54s}{sonuc.sayilar[kod]:>6}")
    for kod, adet in sorted(sonuc.geriye_donuk_sayilari.items()):
        print(f"  GERİYE DÖNÜK (yalnız rapor) {kod:26s}{adet:>6}")
    if args.mod == "uygula":
        print(f"Değişen iş: {sonuc.degisen}")
    if args.cikti:
        args.cikti.write_bytes(rapor_xlsx(sonuc))
        print(f"\nRapor: {args.cikti}")
    return 0


def komut_satiri(argv: list[str] | None = None) -> int:
    ayr = argparse.ArgumentParser(description="Göç işlerinde SLA geri doldurma")
    ayr.add_argument("mod", choices=("rapor", "uygula"), nargs="?", default="rapor")
    ayr.add_argument("--kaynak", type=Path, help="CSV döküm dizini (OpsHolds/öncelik raporu)")
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
