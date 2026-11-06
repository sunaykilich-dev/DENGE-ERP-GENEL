"""Montaj noktası tarifesi profili.

Bu profil planın §8/1 blokajını açar: canlı veritabanındaki 44 montaj
noktasının tarifelerinin HEPSİ 0,00. Geçmiş göçü bundan etkilenmiyor
(tutarlar satırlarda yazılı) ama YENİ iş girişi tarife olmadan fiyat
öneremiyor.

Tarife TARİHLİ ve `[)` yarı açık aralıkla saklanır; aynı nokta + iş tipi +
ürün grubu için çakışan dönem EXCLUDE kısıtıyla engellenir. Yeni dönem
yüklemek, açık dönemi kapatıp yenisini açmak demektir — geçmiş işlerin
hesabı değişmez.

**Tarife bağlayıcı değil (plan §2/7):** aynı noktada aynı iş için canlı
veride 250/350/400, bir kayıtta 2.750 TL görüldü. Buradaki değer ÖNERİDİR;
hak ediş satırında elle geçersiz kılınabilir.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, PartnerTariff
from app.models.settlement import HAK_EDIS_IS_TIPLERI
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz, tutar_coz
from app.services.normalize import clean_cell, tr_normkey

SUTUNLAR = (
    Sutun(
        "montaj_noktasi",
        ("Montaj Noktası", "Montaj Noktasi", "Firma", "Unvan"),
        aciklama="Boş bırakılırsa GENEL (varsayılan) tarife olur, tüm noktalara uygulanır.",
    ),
    Sutun(
        "is_tipi",
        ("İş Tipi", "Is Tipi", "İşlem"),
        zorunlu=True,
        aciklama="ATS_MONTAJ, OBD_ATS_MONTAJ, DASHCAM_MONTAJ, HARICI_KAMERA_MONTAJ, "
        "SOKUM, SOK_TAK, DEGISIM, ARIZA, KESIF, YOL_KM.",
    ),
    Sutun(
        "urun_grubu",
        ("Ürün Grubu", "Urun Grubu"),
        aciklama="Boş bırakılırsa * (tüm ürünler).",
    ),
    Sutun(
        "birim_fiyat",
        ("Birim Fiyat", "Tutar", "Fiyat"),
        zorunlu=True,
        aciklama="TL. YOL_KM satırında km başına ücret.",
    ),
    Sutun(
        "gecerli_baslangic",
        ("Geçerlilik Başlangıcı", "Baslangic", "Başlangıç"),
        zorunlu=True,
        aciklama="GG.AA.YYYY. Bu tarihten önceki işler eski tarifeden hesaplanır.",
    ),
    Sutun("notlar", ("Not", "Notlar"), aciklama="Serbest not."),
)


class TarifeProfili(Profil):
    kod = "tarife"
    ad = "Montaj noktası tarifeleri"
    aciklama = "Tarihli hak ediş tarifeleri. Yeni dönem, açık dönemi kapatarak girer."
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        noktalar = {
            h.title_key: h
            for h in (
                await db.scalars(
                    select(Account).where(
                        Account.is_montaj_noktasi.is_(True), Account.is_deleted.is_(False)
                    )
                )
            ).all()
        }

        sonuclar: list[SatirSonucu] = []
        gorulen: dict[tuple, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            nokta_ham = clean_cell(ham.get("montaj_noktasi"))
            if nokta_ham:
                nokta = noktalar.get(tr_normkey(nokta_ham))
                if nokta is None:
                    r.hatalar.append(
                        f"Montaj noktası bulunamadı: {nokta_ham} "
                        "(hesap açık mı ve 'montaj noktası' işaretli mi?)"
                    )
                else:
                    r.veri["partner_id"] = nokta.id
            else:
                r.veri["partner_id"] = None
                r.uyarilar.append("Genel tarife — noktası olmayan tüm işlere uygulanır")

            is_tipi = tr_normkey(ham.get("is_tipi", "")).upper().replace(" ", "_")
            if is_tipi not in HAK_EDIS_IS_TIPLERI:
                r.hatalar.append(f"İş tipi {HAK_EDIS_IS_TIPLERI} içinden olmalı: {is_tipi}")
            else:
                r.veri["work_type"] = is_tipi

            r.veri["product_group"] = clean_cell(ham.get("urun_grubu")) or "*"

            fiyat_ham = clean_cell(ham.get("birim_fiyat"))
            try:
                fiyat = tutar_coz(fiyat_ham)
                if fiyat < 0:
                    r.hatalar.append("Birim fiyat negatif olamaz")
                else:
                    r.veri["unit_price"] = fiyat
                    if fiyat == 0:
                        r.uyarilar.append("Birim fiyat 0 — yeni iş girişinde fiyat önerilmez")
            except ValueError as exc:
                r.hatalar.append(f"Birim fiyat: {exc}")

            try:
                r.veri["valid_from"] = tarih_coz(ham.get("gecerli_baslangic"))
            except ValueError as exc:
                r.hatalar.append(f"Geçerlilik başlangıcı: {exc}")

            notlar = clean_cell(ham.get("notlar"))
            if notlar:
                r.veri["notes"] = notlar

            anahtar = (
                r.veri.get("partner_id"),
                r.veri.get("work_type"),
                r.veri.get("product_group"),
                str(r.veri.get("valid_from")),
            )
            if r.gecerli:
                if anahtar in gorulen:
                    r.hatalar.append(
                        f"Dosya içinde aynı nokta/iş tipi/tarih ikinci kez "
                        f"(ilk satır: {gorulen[anahtar]})"
                    )
                else:
                    gorulen[anahtar] = sira

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        for r in sonuclar:
            if not r.gecerli:
                continue
            acik = await db.scalar(
                select(PartnerTariff).where(
                    PartnerTariff.partner_id.is_(None)
                    if r.veri.get("partner_id") is None
                    else PartnerTariff.partner_id == r.veri["partner_id"],
                    PartnerTariff.work_type == r.veri["work_type"],
                    PartnerTariff.product_group == r.veri["product_group"],
                    PartnerTariff.valid_to.is_(None),
                )
            )
            if acik is None:
                continue

            yeni_baslangic = r.veri["valid_from"]
            if acik.valid_from.date() >= yeni_baslangic:
                r.hatalar.append(
                    f"Açık tarife {acik.valid_from:%d.%m.%Y} tarihinde başlıyor; "
                    "yeni dönem bundan sonra başlamalı."
                )
                continue
            r.cakisma = {
                "tip": "acik_donem",
                "kayit_id": acik.id,
                "aciklama": (
                    f"Yürürlükteki tarife {acik.unit_price} TL "
                    f"({acik.valid_from:%d.%m.%Y}'den beri). Onaylanırsa o dönem "
                    f"{yeni_baslangic:%d.%m.%Y} tarihinde kapatılır, yenisi açılır."
                ),
            }

    async def yaz(
        self,
        db: AsyncSession,
        satirlar: list[dict],
        *,
        clock: Clock,
        user_id: int | None,
        kararlar: dict[int, str],
    ) -> dict[str, int]:
        sayac = self.bos_sayac()

        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            veri: dict[str, Any] = satir["veri"]
            baslangic = _gun(veri["valid_from"])
            cakisma = satir.get("cakisma")

            if cakisma:
                acik = await db.get(PartnerTariff, cakisma["kayit_id"])
                if acik is not None:
                    acik.valid_to = baslangic
                    await db.flush()
                sayac["guncellendi"] += 1

            db.add(
                PartnerTariff(
                    partner_id=int(veri["partner_id"]) if veri.get("partner_id") else None,
                    work_type=veri["work_type"],
                    product_group=veri["product_group"],
                    unit_price=Decimal(str(veri["unit_price"])),
                    valid_from=baslangic,
                    notes=veri.get("notes"),
                    created_by=user_id,
                )
            )
            sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        return sayac


def _gun(deger: Any) -> datetime:
    """Tarih hücresini dönem başlangıcı anına çevirir (günün başı, UTC)."""
    if isinstance(deger, datetime):
        return deger if deger.tzinfo else deger.replace(tzinfo=UTC)
    gun = deger if isinstance(deger, date) else date.fromisoformat(str(deger))
    return datetime.combine(gun, datetime.min.time(), tzinfo=UTC)
