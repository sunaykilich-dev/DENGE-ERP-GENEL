"""Servis işinde seri okutma zorunluluğu (2026-11-23 sahip kararı).

Cihazlı işte (`CIHAZLI_TURLER`) seri numarası iki anda okutulur:

- **Açılış** (ekrandan iş açma, telefonla çözüldü kaydı, bağlı yeni iş, tekil
  atölye kabulü): en az bir seri olmalı ve her serinin nasıl girildiği
  (`okuma_kaynagi`) bilinmeli — OKUTMA (kamera ya da el okuyucu) ya da ELLE +
  sabit listeden gerekçe (`ELLE_GEREKCELERI`; DIGER'de açıklama zorunlu).
- **Kapanış** (teknisyenin sonuç girip işi TAMAMLANDI yapması, `kaynak='sonuc'`):
  tamamlayan sonuçta cihaz serisi okutulmuş (ya da gerekçeyle elle girilmiş)
  olmalı. Açılış serisinden farklıysa ENGELLENMEZ: geçmişe not düşülür, yanıt
  ve iş ayrıntısı uyarı gösterir. Telefon/uzaktan çözümde cihaz teknisyenin
  yanında olmadığı için kapanış okutması istenmez.

Sunucu gerçek okutmayı yazmadan ayıramaz; kaynağı istemci işaretler (el
okuyucu tuş zamanlamasından, kamera okuyucudan). Sunucu varlığı ve gerekçeyi
zorlar. Kural dışı: içe aktarma profilleri, göç, sistem açılışları (bakım
üretimi, satıştan teslimat, kiralama), toplu açılışlar ve geçiş kaydı
(`sla_kaynak=GECIS`). Ayar `servis_seri_okutma_zorunlu` kapalıysa kural yok.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.models.teknik_servis import SERI_ELLE_GEREKCELERI, SERI_OKUMA_KAYNAKLARI
from app.services import settings as ayar_svc
from app.services.normalize import normalize_seri
from app.services.teknik_servis import kancalar
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import ServiceOrder, ServiceOrderSerial, ServiceResult

AYAR = "servis_seri_okutma_zorunlu"
# Cihazlı türler. Cihazsız: DESTEK, KESIF, TOPLAMA, TASIMA, DEMONTAJ, TESLIMAT
# (sahip kararı; teslimat satıştan sistemce açılır).
CIHAZLI_TURLER = frozenset({"ARIZA", "PLANSIZ_BAKIM", "KURULUM", "ATOLYE", "PB"})
OKUTMA, ELLE = SERI_OKUMA_KAYNAKLARI
ELLE_GEREKCE_ADLARI: dict[str, str] = {
    "ETIKET_YOK": "Etiket yok / okunmuyor",
    "CIHAZ_YANINDA_DEGIL": "Cihaz yanımda değil (telefonla açılan iş)",
    "DIGER": "Diğer",
}
# Cihaz teknisyenin yanında olmayan çözüm kanalları: kapanış okutması istenmez.
UZAKTAN_KANALLAR = frozenset({"TELEFON", "UZAKTAN"})


@dataclass(frozen=True)
class SeriOkuma:
    seri_no: str
    okuma_kaynagi: str
    elle_gerekce: str | None = None
    elle_aciklama: str | None = None

    @property
    def norm(self) -> str:
        return normalize_seri(self.seri_no)


def okuma(
    seri_no: str | None,
    okuma_kaynagi: str | None,
    elle_gerekce: str | None = None,
    elle_aciklama: str | None = None,
) -> SeriOkuma:
    """Girdiyi doğrular ve temizler (400). OKUTMA'da gerekçe yok sayılır."""
    seri = (seri_no or "").strip()
    if not seri:
        raise ServisGirdiHatasi("Seri numarası boş olamaz")
    if len(seri) > 200:
        raise ServisGirdiHatasi("Seri numarası en çok 200 karakter olabilir")
    if okuma_kaynagi not in SERI_OKUMA_KAYNAKLARI:
        raise ServisGirdiHatasi(
            "Seri numarasının nasıl girildiği bilinmeli (okutuldu ya da elle girildi)"
        )
    if okuma_kaynagi == OKUTMA:
        return SeriOkuma(seri, OKUTMA)
    if elle_gerekce not in SERI_ELLE_GEREKCELERI:
        raise ServisGirdiHatasi(
            "Elle girilen seri için neden seçin: " + ", ".join(ELLE_GEREKCE_ADLARI.values())
        )
    aciklama = (elle_aciklama or "").strip() or None
    if aciklama is not None and len(aciklama) > 200:
        raise ServisGirdiHatasi("Elle giriş açıklaması en çok 200 karakter olabilir")
    if elle_gerekce == "DIGER" and aciklama is None:
        raise ServisGirdiHatasi("Elle giriş nedeni 'Diğer' ise açıklama yazın")
    return SeriOkuma(seri, ELLE, elle_gerekce, aciklama)


def okuma_haritasi(okumalar: Iterable[SeriOkuma] | None) -> dict[str, SeriOkuma]:
    return {o.norm: o for o in okumalar or ()}


def satira_yaz(satir: ServiceOrderSerial, o: SeriOkuma | None) -> None:
    if o is None:
        return
    satir.okuma_kaynagi = o.okuma_kaynagi
    satir.elle_gerekce = o.elle_gerekce
    satir.elle_aciklama = o.elle_aciklama


def etiket(kaynak: str | None, gerekce: str | None, aciklama: str | None) -> str | None:
    """Rapor/ayrıntı metni: "Okutuldu" / "Elle: <neden>" / None (eski kayıt)."""
    if kaynak == OKUTMA:
        return "Okutuldu"
    if kaynak == ELLE:
        neden = ELLE_GEREKCE_ADLARI.get(gerekce or "", gerekce or "?")
        if gerekce == "DIGER" and aciklama:
            neden = aciklama
        return f"Elle: {neden}"
    return None


async def acik_mi(db: AsyncSession) -> bool:
    return bool(await ayar_svc.get(db, AYAR))


def kapsamda(tur: str, *, gecis: bool = False) -> bool:
    return tur in CIHAZLI_TURLER and not gecis


async def acilis_dogrula(
    db: AsyncSession,
    tur: str,
    seriler: list[str],
    okumalar: dict[str, SeriOkuma],
    *,
    gecis: bool = False,
    devralinan: frozenset[str] = frozenset(),
) -> None:
    """Açılış kuralı (400). `devralinan`: önceki işten kopyalanan seriler
    (bağlı yeni iş) — onların kaynağı önceki işteki kayıttır."""
    if not kapsamda(tur, gecis=gecis) or not await acik_mi(db):
        return
    if not seriler:
        raise ServisGirdiHatasi(
            "Cihazlı işte seri numarası zorunlu: cihazın barkodunu okutun ya da "
            "elle girip nedenini seçin"
        )
    bilinen = set(okumalar) | devralinan
    eksik = [s for s in seriler if normalize_seri(s) not in bilinen]
    if eksik:
        raise ServisGirdiHatasi(
            "Seri numarası okutulmalı ya da elle giriş nedeni seçilmeli: " + ", ".join(eksik)
        )


async def kapanis_isteniyor(db: AsyncSession, so: ServiceOrder) -> bool:
    """Bu işte kapanışta (sonuç ucunda) cihaz serisi okutulur mu?"""
    return kapsamda(so.tur, gecis=so.sla_kaynak == "GECIS") and await acik_mi(db)


def kapanis_okumasi(sonuc: ServiceResult | None) -> SeriOkuma | None:
    if sonuc is None or not sonuc.kapanis_seri_no or not sonuc.kapanis_okuma_kaynagi:
        return None
    return SeriOkuma(
        sonuc.kapanis_seri_no,
        sonuc.kapanis_okuma_kaynagi,
        sonuc.kapanis_elle_gerekce,
        sonuc.kapanis_elle_aciklama,
    )


def kapanis_farkli(sonuc: ServiceResult | None, acilis_normlari: Iterable[str]) -> bool:
    """Kapanış serisi açılış serilerinden hiçbirine uymuyor (açılışta seri varken)."""
    o = kapanis_okumasi(sonuc)
    normlar = set(acilis_normlari)
    return o is not None and bool(normlar) and o.norm not in normlar


def kapanis_ozeti(sonuc: ServiceResult | None, acilis_normlari: Iterable[str]) -> dict[str, Any]:
    o = kapanis_okumasi(sonuc)
    if o is None:
        return {"kapanis_seri_no": None, "kapanis_okuma": None, "kapanis_seri_farkli": False}
    return {
        "kapanis_seri_no": o.seri_no,
        "kapanis_okuma": {
            "okuma_kaynagi": o.okuma_kaynagi,
            "elle_gerekce": o.elle_gerekce,
            "elle_aciklama": o.elle_aciklama,
            "etiket": etiket(o.okuma_kaynagi, o.elle_gerekce, o.elle_aciklama),
        },
        "kapanis_seri_farkli": kapanis_farkli(sonuc, acilis_normlari),
    }


# --- Kanca ----------------------------------------------------------------------------


async def kapanis_okumasi_dogrula(
    db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str
) -> None:
    """`durum_dogrula`: teknisyen sonuçla tamamlarken cihaz serisi okutulmuş olmalı.

    Yalnız `kaynak='sonuc'` (atölye teslimi kendi seri okutmasını yapar, PB
    bakım formu kendi seri alanını tutar, uzaktan çözümde cihaz yok).
    """
    if hedef != "TAMAMLANDI" or kaynak != "sonuc":
        return
    if not await kapanis_isteniyor(db, so):
        return
    from app.services.teknik_servis import sonuc as sonuc_svc

    gecerli = await sonuc_svc.gecerli_sonuc(db, so)
    if gecerli is None or gecerli.cozum_kanali in UZAKTAN_KANALLAR:
        return
    if kapanis_okumasi(gecerli) is None:
        raise ServisGirdiHatasi(
            "İşi tamamlamak için cihazın seri numarasını okutun (ya da elle girip nedenini seçin)"
        )


kancalar.kaydet("durum_dogrula", kapanis_okumasi_dogrula)
