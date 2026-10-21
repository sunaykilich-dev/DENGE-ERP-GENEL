"""Hat (SIM) profili.

Maliyet TEK SAYI DEĞİL (plan §2/15): tarife + veri paketi + APN kalemleri
ayrı yüklenir. Taahhüt bitiş tarihi de burada girer — %89 indirim taahhüde
bağlı ve bitişi bilinmezse hat maliyeti dokuz katına çıktığında haber
alınmıyor.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import SimCard
from app.models.sim import OPERATORLER
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz, tutar_coz
from app.services.normalize import (
    clean_cell,
    iccid_luhn_ok,
    normalize_iccid,
    normalize_msisdn,
    tr_normkey,
)

SUTUNLAR = (
    Sutun(
        "iccid",
        ("ICCID", "Iccid", "Sim Seri No"),
        zorunlu=True,
        aciklama="19-20 haneli ICCID.",
    ),
    Sutun(
        "msisdn",
        ("Numara", "MSISDN", "Hat No", "M2M Hat No", "Telefon"),
        aciklama="Hat numarası; E.164'e çevrilir (5xx… ya da +90…).",
    ),
    Sutun(
        "operator",
        ("Operatör", "Operator"),
        aciklama="TURK_TELEKOM (varsayılan), TURKCELL, VODAFONE, DIGER.",
    ),
    Sutun("apn", ("APN",), aciklama="APN adı."),
    Sutun("plan_name", ("Paket", "Tarife Adı", "Plan"), aciklama="Veri paketi adı."),
    Sutun(
        "data_allowance_mb",
        ("Kota MB", "Kota (MB)", "Data MB"),
        aciklama="Aylık veri kotası, MB cinsinden.",
    ),
    Sutun("tariff_cost", ("Tarife Ücreti",), aciklama="Aylık tarife bedeli (TL)."),
    Sutun("package_cost", ("Paket Ücreti",), aciklama="Veri paketi bedeli (TL)."),
    Sutun("apn_cost", ("APN Ücreti",), aciklama="APN bedeli (TL)."),
    Sutun(
        "monthly_charge",
        ("Müşteriye Yansıyan", "Satış Fiyatı"),
        aciklama="Müşteriden alınan aylık tutar (TL).",
    ),
    Sutun(
        "commitment_end_date",
        ("Taahhüt Bitişi", "Taahhut Bitisi"),
        aciklama="GG.AA.YYYY. Boşsa taahhüt yok kabul edilir.",
    ),
    Sutun("activated_at", ("Aktivasyon Tarihi",), aciklama="GG.AA.YYYY."),
    Sutun("notes", ("Not", "Notlar"), aciklama="Serbest not."),
)


class HatProfili(Profil):
    kod = "hat"
    ad = "Hatlar (SIM)"
    aciklama = "Operatörden gelen hat listesi; maliyet kalem kalem, taahhüt bitişiyle."
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            try:
                iccid = normalize_iccid(ham.get("iccid"))
                r.veri["iccid"] = iccid
                # Luhn UYARI seviyesinde: operatörler kontrol hanesiz
                # 19 haneli ICCID basıyor, hata saymak gerçek hatları elerdi.
                if not iccid_luhn_ok(iccid):
                    r.uyarilar.append("ICCID kontrol hanesi tutmuyor (operatör baskısı olabilir)")
            except ValueError as exc:
                r.hatalar.append(str(exc))

            msisdn_ham = clean_cell(ham.get("msisdn"))
            if msisdn_ham:
                try:
                    r.veri["msisdn"] = normalize_msisdn(msisdn_ham)
                except ValueError as exc:
                    r.hatalar.append(f"Numara: {exc}")

            operator = tr_normkey(ham.get("operator", "")).upper().replace(" ", "_")
            operator = {"TT": "TURK_TELEKOM", "TURKTELEKOM": "TURK_TELEKOM"}.get(operator, operator)
            if operator and operator not in OPERATORLER:
                r.hatalar.append(f"Operatör {OPERATORLER} içinden olmalı: {operator}")
            else:
                r.veri["operator"] = operator or "TURK_TELEKOM"

            for alan in ("apn", "plan_name", "notes"):
                deger = clean_cell(ham.get(alan))
                if deger:
                    r.veri[alan] = deger

            kota = clean_cell(ham.get("data_allowance_mb"))
            if kota:
                try:
                    r.veri["data_allowance_mb"] = int(Decimal(str(tutar_coz(kota))))
                except (ValueError, ArithmeticError):
                    r.hatalar.append(f"Kota sayı olmalı: {kota}")

            for alan in ("tariff_cost", "package_cost", "apn_cost", "monthly_charge"):
                deger = clean_cell(ham.get(alan))
                if not deger:
                    continue
                try:
                    r.veri[alan] = tutar_coz(deger)
                except ValueError as exc:
                    r.hatalar.append(f"{alan}: {exc}")

            for alan in ("commitment_end_date", "activated_at"):
                deger = clean_cell(ham.get(alan))
                if not deger:
                    continue
                try:
                    r.veri[alan] = tarih_coz(deger)
                except ValueError as exc:
                    r.hatalar.append(f"{alan}: {exc}")

            if not r.veri.get("commitment_end_date"):
                r.uyarilar.append("Taahhüt bitişi yok — indirim bittiğinde uyarı çıkmaz")

            iccid = r.veri.get("iccid")
            if iccid:
                if iccid in gorulen:
                    r.hatalar.append(f"Dosya içinde mükerrer ICCID (ilk satır: {gorulen[iccid]})")
                else:
                    gorulen[iccid] = sira

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        iccidler = [r.veri["iccid"] for r in sonuclar if r.gecerli and r.veri.get("iccid")]
        if not iccidler:
            return
        mevcutlar = {
            s.iccid: s
            for s in (await db.scalars(select(SimCard).where(SimCard.iccid.in_(iccidler)))).all()
        }
        for r in sonuclar:
            mevcut = mevcutlar.get(r.veri.get("iccid"))
            if mevcut is None:
                continue
            r.cakisma = {
                "tip": "mevcut",
                "kayit_id": mevcut.id,
                "aciklama": (
                    f"{mevcut.iccid} zaten kayıtlı ({mevcut.status}). "
                    "Güncellenirse paket, maliyet ve taahhüt alanları dosyadaki değerlerle "
                    "değiştirilir; cihaz eşleşmesi ve durum korunur."
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
        # Maliyet alanları dosyadan geldiğinde kaynağı işaretlenir; gece
        # koşan operatör senkronu elle girilen değeri ezmesin diye.
        kaynak = {"tariff_cost": "ICE_AKTARIM", "package_cost": "ICE_AKTARIM"}

        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            veri: dict[str, Any] = satir["veri"]
            alanlar = _alanlara_cevir(veri)
            cakisma = satir.get("cakisma")

            if cakisma:
                mevcut = await db.get(SimCard, cakisma["kayit_id"])
                if mevcut is None:
                    continue
                for alan, deger in alanlar.items():
                    if alan == "iccid" or deger is None:
                        continue
                    setattr(mevcut, alan, deger)
                mevcut.field_sources = {**(mevcut.field_sources or {}), **kaynak}
                mevcut.updated_by = user_id
                sayac["guncellendi"] += 1
                continue

            db.add(SimCard(**alanlar, field_sources=kaynak, created_by=user_id))
            sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


def _alanlara_cevir(veri: dict[str, Any]) -> dict[str, Any]:
    """Aşamalanmış JSON metinlerini ORM tiplerine çevirir."""
    alanlar: dict[str, Any] = {}
    for alan in ("iccid", "msisdn", "operator", "apn", "plan_name", "notes"):
        if veri.get(alan):
            alanlar[alan] = veri[alan]
    if veri.get("data_allowance_mb"):
        alanlar["data_allowance_mb"] = int(veri["data_allowance_mb"])
    for alan in ("tariff_cost", "package_cost", "apn_cost", "monthly_charge"):
        if veri.get(alan) is not None:
            alanlar[alan] = Decimal(str(veri[alan]))
    for alan in ("commitment_end_date", "activated_at"):
        if veri.get(alan):
            deger = veri[alan]
            alanlar[alan] = deger if isinstance(deger, date) else date.fromisoformat(str(deger))
    return alanlar
