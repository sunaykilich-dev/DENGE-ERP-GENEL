"""Ana Panel ucu (KARARLAR 2026-11-04 §4): `GET /api/teknik-servis/ana-panel`.

İzin `servis.gor` + `takip.gor` (teknisyende yok). İş kuralı ve "sayı = liste" sözleşmesi
`services/teknik_servis/ana_panel.py`'dedir; bu dosya yalnız sorgu
parametrelerini doğrular ve yanıt şemasını (Türkçe alan adları) tanımlar.
Yanıtta para/maliyet alanı YOKTUR (şema bunu da sabitler: yeni alan ancak
buraya yazılarak eklenebilir).

Hata kodları: bilinmeyen birim/durum grubu, ters ya da 24 aydan uzun dönem →
400; kapsam dışı birim → 403 (Servis Paneli kuralı).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import ClockDep, DbDep, require_permission
from app.models import User
from app.services.teknik_servis import ana_panel as ana_panel_svc
from app.services.teknik_servis.kancalar import ServisGirdiHatasi

router = APIRouter(prefix="/api/teknik-servis", tags=["ana-panel"])

# Ekip yönetimi ekranı (2026-11-09): saha teknisyeninde `takip.gor` yok.
Okuyucu = Annotated[User, Depends(require_permission("servis.gor", "takip.gor"))]


# --- Yanıt şeması ----------------------------------------------------------------------------


class KpiKarti(BaseModel):
    kod: str
    ad: str
    tanim: str | None = None
    deger: int
    # Yalnız "sahadaki ekip": aktif / toplam.
    toplam: int | None = None
    onceki_deger: int | None = None
    degisim_yuzde: float | None = None
    # "dönem başına göre" | "hedefe göre" | None (karşılaştırma yok).
    karsilastirma: str | None = None
    vurgu: str = "normal"
    # Tıklanınca açılan süzülmüş liste; sayı bu listenin toplamıdır. None = tıklanamaz.
    liste_yolu: str | None = None


class BirimYollari(BaseModel):
    acik: str
    sahada: str
    atolyede: str
    tamamlanan: str
    donem_is_emri: str


class BirimOzeti(BaseModel):
    birim: str
    ad: str
    acik: int
    sahada: int
    atolyede: int
    tamamlanan: int
    donem_is_emri: int
    tamamlanma_yuzde: int | None = None
    yollar: BirimYollari


class KisiAdi(BaseModel):
    id: int
    ad: str | None = None
    sorumlu: bool = False


class SlaOzeti(BaseModel):
    durum: str | None = None
    ad: str | None = None
    kalan_dk: int | None = None
    olculur: bool = False


class AktifIs(BaseModel):
    id: int
    no: str
    tur: str
    tur_adi: str
    birim: str
    birim_adi: str
    ekipman: str | None = None
    alt_sistem: str | None = None
    musteri: str | None = None
    lokasyon: str | None = None
    tayin_edilen_sef: list[KisiAdi]
    tayin_edilen_personel: list[KisiAdi]
    arac: str | None = None
    durum: str
    durum_adi: str
    oncelik: str
    son_guncelleme: datetime
    sla: SlaOzeti
    yol: str


class AktifIsler(BaseModel):
    satirlar: list[AktifIs]
    liste_yolu: str


class EkipIsi(BaseModel):
    id: int | None = None
    no: str
    lokasyon: str | None = None


class EkipSatiri(BaseModel):
    user_id: int
    ad: str | None = None
    saha_rolu: str | None = None
    birimler: list[str]
    # SAHADA | UZAKTAN | ATOLYEDE | MUSAIT | IZINLI
    durum: str
    durum_adi: str
    is_: EkipIsi | None = None
    aciklama: str | None = None
    sure_dk: int | None = None


class DurumAdedi(BaseModel):
    durum: str
    ad: str
    adet: int


class EkipDurumu(BaseModel):
    # False: `operasyon.gor` yok → satır dönmez (yalnız KPI sayısı).
    gorunur: bool
    satirlar: list[EkipSatiri]
    ozet: list[DurumAdedi]
    liste_yolu: str | None = None


class BekleyenAksiyon(BaseModel):
    kayit_id: int
    kayit_no: str
    aciklama: str | None = None
    kaynak_birim: str
    hedef_birim: str
    bekleme_baslangic: datetime | None = None
    bekleme_dk: int | None = None
    yol: str


class HedefAdedi(BaseModel):
    hedef_birim: str
    adet: int


class BekleyenAksiyonlar(BaseModel):
    satirlar: list[BekleyenAksiyon]
    ozet: list[HedefAdedi]
    toplam: int


class GrafikDilimi(BaseModel):
    kod: str
    ad: str
    deger: int
    liste_yolu: str | None = None


class BirimYuku(BaseModel):
    birim: str
    ad: str
    deger: int
    liste_yolu: str


class PlanliBakim(BaseModel):
    toplam: int
    tamamlanan: int
    yuzde: int | None = None
    parcalar: list[GrafikDilimi]
    liste_yolu: str


class PlanGunu(BaseModel):
    tarih: date
    gun_adi: str
    adet: int
    bugun: bool
    liste_yolu: str


class YaklasanBakim(BaseModel):
    tarih: date
    id: int
    no: str
    musteri: str | None = None
    aciklama: str | None = None
    yol: str


class AylikBakim(BaseModel):
    ay: date
    planlanan: int
    tamamlanan: int
    kalan: int
    yuzde: int | None = None
    yaklasan: list[YaklasanBakim]


class Grafikler(BaseModel):
    durum_dagilimi: list[GrafikDilimi]
    acik_toplam: int
    bolum_is_yuku: list[BirimYuku]
    planli_bakim: PlanliBakim
    haftalik_plan: list[PlanGunu]
    aylik_bakim: AylikBakim


class KodAd(BaseModel):
    kod: str
    ad: str


class KimlikAd(BaseModel):
    id: int
    ad: str | None = None


class Secenekler(BaseModel):
    birimler: list[KodAd]
    durum_gruplari: list[KodAd]
    sefler: list[KimlikAd]
    personel: list[KimlikAd]
    lokasyonlar: list[KimlikAd]


class Donem(BaseModel):
    bas: date
    bit: date
    aralik: str


class Suzgec(BaseModel):
    birim: str | None = None
    durum_grubu: str | None = None
    sef_id: int | None = None
    personel_id: int | None = None
    lokasyon_id: int | None = None


class AnaPanelYaniti(BaseModel):
    guncelleme_zamani: datetime
    donem: Donem
    suzgec: Suzgec
    kpiler: list[KpiKarti]
    birim_ozeti: list[BirimOzeti]
    aktif_isler: AktifIsler
    ekip_durumu: EkipDurumu
    bekleyen_aksiyonlar: BekleyenAksiyonlar
    grafikler: Grafikler
    secenekler: Secenekler


# --- Uç ---------------------------------------------------------------------------------------


@router.get("/ana-panel", response_model=AnaPanelYaniti)
async def ana_panel(
    db: DbDep,
    clock: ClockDep,
    user: Okuyucu,
    birim: str | None = Query(default=None, max_length=20),
    durum_grubu: str | None = Query(default=None, max_length=20),
    sef_id: int | None = None,
    personel_id: int | None = None,
    lokasyon_id: int | None = None,
    bas: date | None = None,
    bit: date | None = None,
) -> dict:
    """Ana panel: KPI kartları, birim özeti, aktif işler, ekip, bekleyen
    aksiyonlar, grafikler. Her tıklanabilir sayı = `liste_yolu` listesinin toplamı."""
    try:
        s = ana_panel_svc.suzgec_hazirla(
            user,
            clock,
            birim=birim,
            durum_grubu=durum_grubu,
            sef_id=sef_id,
            personel_id=personel_id,
            lokasyon_id=lokasyon_id,
            bas=bas,
            bit=bit,
        )
        return await ana_panel_svc.ana_panel(db, user, clock, s)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ServisGirdiHatasi as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
