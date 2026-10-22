"""Zaman kaydı göçü: V1 zaman kayıtları + mola oturumları → `service_time_entries` (TS-176).

Kurallar:

- **Kişi:** eski kayıt kişiyi AD METNİYLE tutar. Yalnız İK'nın onayladığı ad
  eşlemesi (`personnel_name_maps`, TS-170) `user_id` doldurur; eşleşmeyen ad
  `user_id NULL + kaynak_personel_adi` ile gelir (`ck_ste_kisi` yalnız göç
  satırına izin verir). Onay sonradan gelirse `servis_ad_esleme uygula`
  satırı bağlar; ham ad korunur.
- **Satır atılmaz:** aynı kişinin başka kaydıyla çakışan satır `GOC_CAKISMA`
  iptal türüyle (yumuşak silinmiş) saklanır — EXCLUDE kısıtı çakışmayı
  reddederdi, satırı düşürmek veri kaybı olurdu. Eski sistemde iptal edilmiş
  satır `GOC_IPTAL` olarak gelir.
- Faaliyet tek sözlüğe çevrilir (E09-D02; ISCILIK yok): `Saha Çalışması` →
  SAHA, `Yol / Ulaşım` → YOL, `Bekleme` → BEKLEME (neden `DIGER`), `Mola /
  Ara` → MOLA ...
- Yalnız göç edilmiş işe bağlanır; işi aktarılmamış satır KARANTİNADA kalır.
- İdempotent: `uq_ste_kaynak`; tekrar koşu 0 yeni satır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration.servis_kaynak import (
    GOC_SISTEMI,
    AdimSonucu,
    KaynakDizini,
    bit,
    kaynak_ref,
    metin,
    mevcut_refler,
    tamsayi,
    yerel_an,
)
from app.migration.servis_plan import goc_isleri
from app.models import ServiceTimeEntry
from app.services import audit
from app.services.normalize import tr_normkey
from app.services.teknik_servis import ad_esleme

KAYNAK_TABLO = "WorkOrderTimeLogs"
KAYNAK_OTURUM = "WorkOrderLiveSessions"
HEDEF_TABLO = "service_time_entries"

FAALIYET_ESLEME = {
    "saha calismasi": "SAHA",
    "yol / ulasim": "YOL",
    "bekleme": "BEKLEME",
    "uzaktan destek": "UZAKTAN",
    "atolye": "ATOLYE",
    "test / kontrol": "TEST",
    "diger": "DIGER",
    "mola / ara": "MOLA",
}
ESKI_IPTAL_GEREKCESI = "Eski sistemde iptal edilmiş kayıt"
CAKISMA_GEREKCESI = "Göç: kişinin başka kaydıyla çakışıyor"


@dataclass
class ZamanTaslagi:
    ref: str
    alan: str
    is_ref: str
    ad: str
    faaliyet: str
    baslangic: datetime
    bitis: datetime
    girildi: datetime
    konum_notu: str | None
    aciklama: str | None
    iptal: bool
    iptal_at: datetime | None


def faaliyet_esle(ham: str | None) -> str | None:
    return FAALIYET_ESLEME.get(tr_normkey(ham))


def _taslak(
    sonuc: AdimSonucu,
    satir: dict[str, Any],
    *,
    tablo: str,
    kimlik_kolonu: str,
    alan: str,
    isler: dict[str, dict[str, Any]],
    sira: int,
) -> ZamanTaslagi | None:
    kimlik = tamsayi(satir.get(kimlik_kolonu))
    if kimlik is None:
        sonuc.reddet(f"{tablo} satır {sira}", f"{kimlik_kolonu} yok")
        return None
    ref = kaynak_ref(tablo, kimlik)
    is_ref = kaynak_ref("WorkOrders", satir.get("WorkOrderId"))
    if is_ref not in isler:
        sonuc.karantinaya(ref, f"İşi aktarılmamış ({is_ref})")
        return None
    ad = metin(satir.get("TechnicianName"))
    if not ad:
        sonuc.karantinaya(ref, "Personel adı yok")
        return None
    if len(ad) > 100:
        sonuc.karantinaya(ref, "Personel adı 100 karakteri aşıyor")
        return None
    faaliyet = faaliyet_esle(satir.get("ActivityType"))
    if faaliyet is None:
        sonuc.karantinaya(ref, f"Eşlenemeyen faaliyet: {satir.get('ActivityType')}")
        return None
    try:
        bas = yerel_an(satir.get("StartedAt"))
        bit_ = yerel_an(satir.get("EndedAt"))
        girildi = yerel_an(satir.get("CreatedAt")) or bas
        iptal_at = yerel_an(satir.get("VoidedAt"))
    except ValueError as exc:
        sonuc.karantinaya(ref, f"Tarih okunamadı: {exc}")
        return None
    if bas is None or bit_ is None:
        sonuc.karantinaya(ref, "Başlangıç/bitiş yok (açık oturum göç edilmez)")
        return None
    if bit_ <= bas:
        sonuc.karantinaya(ref, "Bitiş başlangıçtan sonra değil")
        return None
    if (bit_ - bas).total_seconds() > 18 * 3600:
        sonuc.karantinaya(ref, "18 saati aşan bölüm")
        return None
    return ZamanTaslagi(
        ref=ref,
        alan=alan,
        is_ref=is_ref,
        ad=ad,
        faaliyet=faaliyet,
        baslangic=bas,
        bitis=bit_,
        girildi=girildi,
        konum_notu=(metin(satir.get("LocationNote")) or "")[:200] or None,
        aciklama=metin(satir.get("WorkNote")),
        iptal=bit(satir.get("IsVoided")),
        iptal_at=iptal_at,
    )


def hazirla(dizin: KaynakDizini, isler: dict[str, dict[str, Any]]) -> list[AdimSonucu]:
    """İki kaynak tablo → iki adım sonucu (uzlaşma tablo bazında)."""
    sonuclar: list[AdimSonucu] = []
    for tablo, kimlik_kolonu, alan, zorunlu in (
        (KAYNAK_TABLO, "TimeLogId", ad_esleme.ALAN_ZAMAN, True),
        (KAYNAK_OTURUM, "SessionId", ad_esleme.ALAN_CANLI_OTURUM, False),
    ):
        satirlar = dizin.tablo(tablo, zorunlu=zorunlu)
        sonuc = AdimSonucu(tablo, HEDEF_TABLO, kaynak=len(satirlar))
        gorulen: set[str] = set()
        for sira, s in enumerate(satirlar, start=1):
            t = _taslak(
                sonuc,
                s,
                tablo=tablo,
                kimlik_kolonu=kimlik_kolonu,
                alan=alan,
                isler=isler,
                sira=sira,
            )
            if t is None:
                continue
            if t.ref in gorulen:
                sonuc.reddet(t.ref, "dökümde aynı kimlik iki kez")
                continue
            gorulen.add(t.ref)
            sonuc.aktarilacak.append(t)
        sonuc.aktarilacak.sort(key=lambda x: (x.baslangic, x.ref))
        sonuclar.append(sonuc)
    return sonuclar


async def hazirla_db(db: AsyncSession, dizin: KaynakDizini) -> list[AdimSonucu]:
    sonuclar = hazirla(dizin, await goc_isleri(db))
    for sonuc in sonuclar:
        var = await mevcut_refler(db, HEDEF_TABLO, sonuc.kaynak_tablo)
        sonuc.mevcut = sum(1 for t in sonuc.aktarilacak if t.ref in var)
        sonuc.yeni = len(sonuc.aktarilacak) - sonuc.mevcut
    return sonuclar


async def yukle(
    db: AsyncSession, sonuclar: list[AdimSonucu], *, user_id: int | None = None
) -> list[AdimSonucu]:
    isler = await goc_isleri(db)
    harita = ad_esleme.ada_gore(
        await ad_esleme.onayli_harita(db, ad_esleme.ZAMAN_ALANLARI), ad_esleme.ZAMAN_ALANLARI
    )
    for sonuc in sonuclar:
        sayac = {"kisiye_bagli": 0, "eslesmeyen_ad": 0, "goc_cakisma": 0, "eski_iptal": 0}
        eklenen = 0
        for t in sonuc.aktarilacak:
            uid = harita.get(ad_esleme.normal_ad(t.ad))
            iptal_turu = iptal_gerekcesi = None
            silindi_at = None
            if t.iptal:
                iptal_turu, iptal_gerekcesi = "GOC_IPTAL", ESKI_IPTAL_GEREKCESI
                silindi_at = t.iptal_at or t.girildi
            elif uid is not None and await ad_esleme.cakisan_var_mi(db, uid, t.baslangic, t.bitis):
                iptal_turu, iptal_gerekcesi = "GOC_CAKISMA", CAKISMA_GEREKCESI
                silindi_at = t.girildi
            stmt = (
                insert(ServiceTimeEntry.__table__)
                .values(
                    service_order_id=isler[t.is_ref]["id"],
                    user_id=uid,
                    kaynak_personel_adi=t.ad,
                    faaliyet=t.faaliyet,
                    bekleme_nedeni="DIGER" if t.faaliyet == "BEKLEME" else None,
                    started_at=t.baslangic,
                    ended_at=t.bitis,
                    kaynak="MANUEL",
                    kapanis_turu="BITIR",
                    girildi_at=t.girildi,
                    konum_notu=t.konum_notu,
                    aciklama=t.aciklama,
                    is_deleted=iptal_turu is not None,
                    deleted_at=silindi_at,
                    iptal_turu=iptal_turu,
                    iptal_gerekcesi=iptal_gerekcesi,
                    source_system=GOC_SISTEMI,
                    source_ref=t.ref,
                    created_by=user_id,
                    updated_by=user_id,
                )
                .on_conflict_do_nothing(constraint="uq_ste_kaynak")
                .returning(ServiceTimeEntry.__table__.c.id)
            )
            if (await db.execute(stmt)).scalar() is None:
                continue
            eklenen += 1
            sayac["kisiye_bagli" if uid is not None else "eslesmeyen_ad"] += 1
            if iptal_turu == "GOC_CAKISMA":
                sayac["goc_cakisma"] += 1
            elif iptal_turu == "GOC_IPTAL":
                sayac["eski_iptal"] += 1
        sonuc.yeni = eklenen
        sonuc.mevcut = len(sonuc.aktarilacak) - eklenen
        sonuc.ek["sayac"] = sayac
        await audit.log(
            db,
            HEDEF_TABLO,
            "goc.servis_zaman",
            new_value={**sonuc.ozet(), **sayac},
            user_id=user_id,
        )
    return sonuclar
