"""Servis işinde cihaz başına bilgi (2026-11-24 sahip kararı, migration fcp000000001).

Bir işe birden fazla cihaz (seri) eklenir; her cihazın kendi bilgisi:

- **Yalnız personel:** `notlar`, `musteri_sikayeti`. Müşteri belgesine
  (onarım fişi, servis formu) ve müşteri bağlantısına BASILMAZ.
- **Müşteriye giden:** `cihaz_durumu` (sabit liste) + `cihaz_durumu_aciklama`,
  `onarim_bilgisi`, `aksesuarlar` (2026-11-25) — onarım fişindeki cihaz tablosu.

Dört alan açılışta girilir, iş kapanana kadar düzenlenir (kapalı/iptal işte
değişmez). Her düzenleme olay geçmişine yazılır (metin değil, yalnız hangi
alanların değiştiği — olay geçmişi kişisel veri taşımaz).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.teknik_servis import CIHAZ_DURUMLARI, ServiceOrderSerial
from app.services.normalize import normalize_seri
from app.services.teknik_servis import gecmis
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import ServiceOrder, User

ALANLAR = (
    "notlar",
    "musteri_sikayeti",
    "cihaz_durumu",
    "cihaz_durumu_aciklama",
    "onarim_bilgisi",
    # 2026-11-25: cihazla gelen aksesuarlar (atölye kabulüyle aynı türler).
    "aksesuarlar",
)
DURUM_ADLARI = {
    "CALISIYOR": "Çalışıyor",
    "ARIZALI": "Arızalı",
    "HASARLI": "Fiziksel hasarlı",
    "PARCA_EKSIK": "Parçası eksik",
}


def _temiz(deger: Any) -> Any:
    if isinstance(deger, str):
        deger = deger.strip()
        return deger or None
    return deger


def _aksesuar_temiz(liste: Any) -> list[dict[str, Any]] | None:
    """Aksesuar listesini doğrular ve sadeleştirir; boş liste → None."""
    if not liste:
        return None
    from app.models.servis_atolye import AKSESUAR_TURLERI

    temiz: list[dict[str, Any]] = []
    for a in liste:
        tur = a.get("kind")
        if tur not in AKSESUAR_TURLERI:
            raise ServisGirdiHatasi(f"Bilinmeyen aksesuar türü: {tur}")
        aciklama = _temiz(a.get("description"))
        if tur == "DIGER" and not aciklama:
            raise ServisGirdiHatasi("'Diğer' aksesuarda açıklama zorunlu")
        temiz.append({"kind": tur, "qty": int(a.get("qty") or 1), "description": aciklama})
    return temiz


def aksesuar_metni(liste: list[dict[str, Any]] | None) -> str | None:
    """Fiş için: "Batarya × 1, Şarj yuvası × 1, Bel çantası × 1"."""
    if not liste:
        return None
    from app.services.teknik_servis.atolye import AKSESUAR_ADLARI

    parcalar = []
    for a in liste:
        ad = a.get("description") if a["kind"] == "DIGER" else AKSESUAR_ADLARI.get(a["kind"])
        parcalar.append(f"{ad or a['kind']} × {a.get('qty', 1)}")
    return ", ".join(parcalar)


def uygula(satir: ServiceOrderSerial, degerler: dict[str, Any]) -> list[str]:
    """Verilen alanları satıra yazar; değişen alan adlarını döner."""
    degisen: list[str] = []
    for alan in ALANLAR:
        if alan not in degerler:
            continue
        yeni = _aksesuar_temiz(degerler[alan]) if alan == "aksesuarlar" else _temiz(degerler[alan])
        if alan == "cihaz_durumu" and yeni is not None and yeni not in CIHAZ_DURUMLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen cihaz durumu: {yeni}")
        if getattr(satir, alan) != yeni:
            setattr(satir, alan, yeni)
            degisen.append(alan)
    return degisen


def acilista_yaz(satirlar: list[ServiceOrderSerial], bilgiler: list[dict[str, Any]]) -> None:
    """Açılış gövdesindeki cihaz bilgilerini seriye göre eşleyip yazar.
    İşte olmayan seriye bilgi gönderilirse 400 (sessizce kaybolmasın)."""
    if not bilgiler:
        return
    norm = {s.seri_norm: s for s in satirlar}
    for b in bilgiler:
        satir = norm.get(normalize_seri(b["seri_no"]))
        if satir is None:
            raise ServisGirdiHatasi(f"Cihaz bilgisi işte olmayan seri için: {b['seri_no']}")
        uygula(satir, b)


async def duzenle(
    db: AsyncSession,
    so: ServiceOrder,
    satir: ServiceOrderSerial,
    degerler: dict[str, Any],
    *,
    user: User,
    clock: Clock,
) -> list[str]:
    degisen = uygula(satir, degerler)
    if degisen:
        satir.updated_by = user.id
        await gecmis.olay_yaz(
            db,
            so,
            "NOT",
            f"Cihaz bilgisi güncellendi: {satir.seri_no}",
            user=user,
            clock=clock,
            veri={"seri_id": satir.id, "alanlar": degisen},
        )
        await db.flush()
    return degisen


def cikti(satir: ServiceOrderSerial) -> dict[str, Any]:
    """Personel ekranı için cihaz bilgisi (iş detayı)."""
    return {
        **{alan: getattr(satir, alan) for alan in ALANLAR},
        "cihaz_durumu_adi": DURUM_ADLARI.get(satir.cihaz_durumu or ""),
    }


def musteri_ciktisi(satir: ServiceOrderSerial) -> dict[str, Any]:
    """Müşteri belgesi için: yalnız durum ve onarım (not/şikâyet YOK)."""
    return {
        "seri_no": satir.seri_no,
        "cihaz_durumu": DURUM_ADLARI.get(satir.cihaz_durumu or ""),
        "cihaz_durumu_aciklama": satir.cihaz_durumu_aciklama,
        "onarim_bilgisi": satir.onarim_bilgisi,
        "aksesuarlar": aksesuar_metni(satir.aksesuarlar),
    }
