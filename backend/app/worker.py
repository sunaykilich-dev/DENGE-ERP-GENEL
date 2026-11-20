"""Arka plan görev koşucusu.

    python -m app.worker            # sürekli koşar (Compose'daki `worker` servisi)
    python -m app.worker --bir-kez  # her görevi bir kez koşar ve çıkar

Bu bir **periyodik görev koşucusu**, iş kuyruğu değil. Kuyruk (`jobs` tablosu,
`FOR UPDATE SKIP LOCKED`, outbox) D10 ile birlikte ertelendi; o geldiğinde bu
dosyaya bir şerit daha eklenir. Bugün gereken şey farklı: gecede bir kez koşup
türetilmiş alanları doğrulayan ve biriken satırları temizleyen bir süreç.

Tasarım kuralları (plan §3.5):

* **Tek kopya.** `docker-compose.yml` `replicas: 1` diyor. İki kopya aynı
  uzlaştırmayı aynı anda koşarsa aynı cihaza iki kez yazar.
* **Her döngü kendi `try/except`i içinde.** Bir görevin patlaması diğerlerini
  durdurmaz; aksi halde tek bir hata gece boyunca her şeyi susturur.
* **`asyncio.TaskGroup` + durdurma olayı.** SIGTERM gelince koşan görev bitene
  kadar beklenir; yarım kalan transaction bırakılmaz.
* **Nabız.** Her tur log'a yazılır. Susan bir worker, hiç çalışmayan bir
  worker'dan daha tehlikelidir: kimse fark etmez.
* **CPU bağlı iş olay döngüsünden çıkarılmalı.** Bugünkü görevlerin hepsi G/Ç
  bağlı. İleride Excel/PDF üreten bir görev eklenirse (openpyxl, WeasyPrint)
  o görev kendi içinde `asyncio.to_thread` çağırmalı; yoksa üretim sürerken
  diğer görevler de durur. Bu, deseni kopyalarken yapılabilecek tek gerçek hata.

Saat `Clock` üzerinden okunur — uygulama kodunda `datetime.now()` yok.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock, RealClock
from app.db import get_session_factory

logger = logging.getLogger("denge.worker")

Calisan = Callable[[AsyncSession, Clock], Awaitable[str]]


@dataclass(frozen=True)
class Gorev:
    ad: str
    periyot: timedelta
    calistir: Calisan


# --- görevler ---------------------------------------------------------------


async def cihaz_uzlastirma(db: AsyncSession, clock: Clock) -> str:
    """`devices.current_*` alanlarını tarihli tablolardan yeniden türetir.

    Doğruluk kaynağı daima tarihli tablo; bu alanlar yalnız sorguyu ucuzlatmak
    için var ve sapabilir (göç, toplu içe aktarma, elle düzeltme). Sapma sessiz
    kalırsa garanti başlangıcı ve "bu cihaz kimde" cevabı yanlış çıkar.
    """
    from app.services import devices as cihaz_svc

    sonuc = await cihaz_svc.uzlastir(db, yaz=True)
    # `farklar` on binlerce satır olabilir; log'a sayıları yaz, listeyi değil.
    # Tek satırda 10.000 kayıt basan bir log okunmaz ve diski doldurur.
    sayilar = {a: d for a, d in sonuc.items() if isinstance(d, int)}
    ornek = (sonuc.get("farklar") or [])[:3]
    ozet = ", ".join(f"{a}={d}" for a, d in sorted(sayilar.items()))
    return f"{ozet} örnek={[o['kimlik'] for o in ornek]}" if ornek else ozet or "sapma yok"


async def oturum_temizligi(db: AsyncSession, clock: Clock) -> str:
    from app.services import auth as auth_svc

    silinen = await auth_svc.suresi_dolan_oturumlari_sil(db, clock)
    return f"{silinen} süresi dolmuş oturum silindi"


async def is_uyarilari(db: AsyncSession, clock: Clock) -> str:
    """Zamana bağlı uyarıları sayar ve log'a yazar.

    Bu uyarılar ekranlarda zaten hesaplanıyor; buradaki değer ekranı kimse
    açmasa da kaydın oluşması. Hat taahhüdü bitince maliyet dokuz katına
    çıkıyor (plan §2 #15) — bunu ayın sonunda faturadan öğrenmek pahalı.
    """
    from app.services import sims as hat_svc
    from app.services import subscriptions as abonelik_svc

    taahhut = await hat_svc.taahhudu_bitenler(db, clock)
    kota = await hat_svc.kota_uyarilari(db)
    yenilenecek = await abonelik_svc.yenilenecekler(db, clock)
    return (
        f"taahhüdü bitecek hat={len(taahhut)}, "
        f"kota uyarısı={len(kota)}, yenilenecek abonelik={len(yenilenecek)}"
    )


async def ek_dosya_temizligi(db: AsyncSession, clock: Clock) -> str:
    """Hiçbir ek kaydının işaret etmediği dosyaları kaldırır.

    Ek silinince dosya ANINDA silinmiyor (eşzamanlı bir yükleme aynı içeriği
    paylaşıyorsa silme onu da götürürdü). Artan dosyalar burada toplanır.
    En az 24 saat beklenir: yüklemesi süren dosya da yetim görünür.
    """
    from app.db import Base
    from app.services import storage as depo

    # Depoya dosya yazan HER tablo sayılır (ekler, İK şablon ve belgeleri,
    # özlük belgeleri...). Eskiden yalnız `attachments` sayılıyordu; İK'nın
    # bordro/imzalı belge dosyaları 24 saat sonra "yetim" diye silinebiliyordu
    # (2026-11-20). Yeni tablo `storage_path` sütunuyla kendiliğinden katılır.
    kullanilan: set[str] = set()
    for tablo in Base.metadata.sorted_tables:
        if "storage_path" in tablo.c:
            kullanilan |= {y for y in (await db.scalars(select(tablo.c.storage_path))).all() if y}
    silinen = depo.yetimleri_temizle(kullanilan, en_az_yas_saat=24)
    return f"{silinen} yetim dosya silindi ({len(kullanilan)} dosya kullanımda)"


async def pb_uretimi(db: AsyncSession, clock: Clock) -> str:
    """Vadesi gelen bakım dönemlerinin PB işlerini üretir (TS-062).

    `bakim_otomatik_uretim=False` iken hiçbir şey yazmaz (R1 yayını, KD-21).
    İdempotent: `uq_so_pb_cihaz_donem` + `ON CONFLICT DO NOTHING`; yeniden
    deneme aynı turu tekrar koşsa da çift PB açılmaz.
    """
    from app.services.teknik_servis import bakim_uretim

    return await bakim_uretim.pb_uretimi_gorevi(db, clock)


async def bakim_donem_uzlastirma(db: AsyncSession, clock: Clock) -> str:
    """Bakım dönem kapanışlarını PB durumlarından yeniden türetir (TS-065).

    Kapanış durum kancasıyla anında güncellenir; bu görev kancayı atlayan bir
    yolun bıraktığı farkı düzeltir ve log'a yazar.
    """
    from app.services.teknik_servis import bakim_formu

    return await bakim_formu.donem_uzlastirma_gorevi(db, clock)


async def servis_sla_uyarilari(db: AsyncSession, clock: Clock) -> str:
    """Kalıcı SLA bildirimlerini açar/kapatır (TS-083) ve tutarsız bekleme sayar (E10-11).

    Zil sayısı bu göreve BAĞLI DEĞİL (anlık hesaplanır); tablo yalnız "görüldü"
    ve e-posta tekilliği içindir. `servis_uyari_uretimi_acik=false` iken yazmaz.
    İdempotent: `uq_salert_acik` + ON CONFLICT DO NOTHING. Tek kopya worker.
    """
    from app.services.teknik_servis import uyari_uretimi

    return await uyari_uretimi.uretim_gorevi(db, clock)


async def servis_uyari_temizligi(db: AsyncSession, clock: Clock) -> str:
    """`servis_uyari_saklama_gun`'den eski KAPALI SLA bildirimlerini siler (TS-083)."""
    from app.services.teknik_servis import uyari_uretimi

    return await uyari_uretimi.temizlik_gorevi(db, clock)


async def servis_eposta(db: AsyncSession, clock: Clock) -> str:
    """Servis SLA e-postaları: kuyruğa al → gönder → saklama (TS-200, E10-06).

    `servis_eposta_acik=false` iken hiçbir satır üretmez. SMTP tanımsızken
    kutuya DOKUNMAZ ve hata değil bilgi satırı yazar. SMTP G/Ç'si
    `asyncio.to_thread` içinde (olay döngüsü bloklanmaz). Tekillik şemada
    (`uq_smo_anlik`, `uq_smo_ozet`): tekrar koşan tur ikinci e-posta üretmez.
    """
    from app.services.teknik_servis import eposta

    return await eposta.gorev(db, clock)


async def vekalet_sona_erme(db: AsyncSession, clock: Clock) -> str:
    """Süresi dolan vekâletleri denetim izine BİR KEZ yazar (TS-213).

    Yetki bu göreve BAĞLI DEĞİL: süre her istekte `Clock` ile denetlenir,
    görev koşmasa da süresi dolan izin 403 verir. Görev yalnız "vekâlet sona
    erdi" olayını denetimde görünür kılar. İdempotent (aynı kişi+izin+bitiş
    için ikinci satır yazılmaz).
    """
    from app.services import yetki

    return await yetki.suresi_dolan_vekaletleri_kaydet(db, clock)


GOREVLER: tuple[Gorev, ...] = (
    Gorev("cihaz-uzlastirma", timedelta(hours=24), cihaz_uzlastirma),
    Gorev("oturum-temizligi", timedelta(hours=6), oturum_temizligi),
    Gorev("is-uyarilari", timedelta(hours=24), is_uyarilari),
    Gorev("ek-dosya-temizligi", timedelta(hours=24), ek_dosya_temizligi),
    Gorev("pb-uretimi", timedelta(hours=24), pb_uretimi),
    Gorev("bakim-donem-uzlastirma", timedelta(hours=24), bakim_donem_uzlastirma),
    Gorev("servis-sla-uyarilari", timedelta(minutes=5), servis_sla_uyarilari),
    Gorev("servis-uyari-temizligi", timedelta(hours=24), servis_uyari_temizligi),
    Gorev("servis-eposta", timedelta(minutes=5), servis_eposta),
    Gorev("vekalet-sona-erme", timedelta(hours=24), vekalet_sona_erme),
)


# --- koşucu -----------------------------------------------------------------


async def _bir_tur(gorev: Gorev, clock: Clock) -> bool:
    """Görevi kendi oturumunda koşar. Başarılıysa True.

    Hata yakalanır ve loglanır — asla yayılmaz; tek bir görevin patlaması
    worker'ı düşürmemeli.
    """
    baslangic = clock.now()
    try:
        async with get_session_factory()() as db:
            ozet = await gorev.calistir(db, clock)
            await db.commit()
        sure = (clock.now() - baslangic).total_seconds()
        logger.info("görev bitti ad=%s süre=%.1fs %s", gorev.ad, sure, ozet)
        return True
    except Exception:
        # Hata izi olmadan "neden çalışmadı" cevaplanamaz.
        logger.exception("görev HATA ad=%s", gorev.ad)
        return False


# Hata sonrası yeniden deneme aralıkları. Sunucu yeniden başladığında
# veritabanı worker'dan birkaç saniye SONRA hazır oluyor ve ilk tur
# "connection refused" ile düşüyor. Periyot kadar (6-24 saat) beklenirse o
# günün uzlaştırması hiç koşmaz — sessizce, kimse fark etmeden. Artan
# aralıklarla yeniden denemek bunu saniyeler içinde kapatır; kalıcı bir arıza
# varsa da log'u dakikada bir değil, seyrekleşerek doldurur.
_YENIDEN_DENEME = (timedelta(seconds=10), timedelta(seconds=30), timedelta(minutes=2))


async def _dongu(gorev: Gorev, clock: Clock, dur: asyncio.Event) -> None:
    hata_sayisi = 0
    while not dur.is_set():
        if await _bir_tur(gorev, clock):
            hata_sayisi = 0
            bekleme = gorev.periyot
        else:
            bekleme = _YENIDEN_DENEME[min(hata_sayisi, len(_YENIDEN_DENEME) - 1)]
            hata_sayisi += 1
            # Yeniden deneme periyodu AŞMAMALI: 6 saatte bir koşan bir görevi
            # hata yüzünden daha sık denemek anlamlı, daha seyrek denemek değil.
            bekleme = min(bekleme, gorev.periyot)
            logger.warning(
                "görev yeniden denenecek ad=%s saniye=%.0f deneme=%d",
                gorev.ad,
                bekleme.total_seconds(),
                hata_sayisi,
            )
        try:
            await asyncio.wait_for(dur.wait(), timeout=bekleme.total_seconds())
        except TimeoutError:
            continue


async def _nabiz(clock: Clock, dur: asyncio.Event, aralik: timedelta) -> None:
    while not dur.is_set():
        logger.info("nabız görev_sayısı=%d", len(GOREVLER))
        try:
            await asyncio.wait_for(dur.wait(), timeout=aralik.total_seconds())
        except TimeoutError:
            continue


async def kos(clock: Clock | None = None) -> None:
    clock = clock or RealClock()
    dur = asyncio.Event()

    dongu = asyncio.get_running_loop()
    for isaret in (signal.SIGTERM, signal.SIGINT):
        try:
            dongu.add_signal_handler(isaret, dur.set)
        except NotImplementedError:  # Windows
            pass

    logger.info("worker başladı görev_sayısı=%d", len(GOREVLER))
    async with asyncio.TaskGroup() as tg:
        for gorev in GOREVLER:
            tg.create_task(_dongu(gorev, clock, dur))
        tg.create_task(_nabiz(clock, dur, timedelta(minutes=5)))
    logger.info("worker durdu")


async def bir_kez(clock: Clock | None = None) -> None:
    clock = clock or RealClock()
    for gorev in GOREVLER:
        await _bir_tur(gorev, clock)


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Denge ERP arka plan görevleri")
    ayristirici.add_argument("--bir-kez", action="store_true", help="Her görevi bir kez koş ve çık")
    args = ayristirici.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )
    asyncio.run(bir_kez() if args.bir_kez else kos())
    return 0


if __name__ == "__main__":
    sys.exit(main())
