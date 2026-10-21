"""Abonelik profili.

Aboneliği TASLAK açar, **aktifleştirmez**. Aktivasyon MRR olayı yazar ve
geliri kayda geçirir; yüzlerce satırı tek tıkla MRR'a sokmak, yanlış bir
dosyanın gelir raporunu sessizce bozması demekti. Ekip önizlemede gördüğünü
onaylar, sonra abonelikleri listeden aktifleştirir.

Ücret tarihlidir; içe aktarma sözleşme başlangıcından geçerli ilk ücret
dönemini açar.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Subscription, Vehicle
from app.models.subscription import FATURA_PERIYOTLARI, YENILEME_TIPLERI
from app.models.vehicle import plaka_anahtari
from app.services import subscriptions as abonelik_svc
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz, tutar_coz
from app.services.normalize import clean_cell, tr_normkey

SUTUNLAR = (
    Sutun("musteri", ("Müşteri", "Musteri", "Firma"), zorunlu=True, aciklama="Hesap unvanı."),
    Sutun("konu", ("Konu", "Başlık", "Açıklama"), aciklama="Ör. Platform aboneliği."),
    Sutun("plaka", ("Plaka",), aciklama="Araç başına abonelikse plaka."),
    Sutun(
        "periyot",
        ("Periyot", "Fatura Periyodu"),
        aciklama="AYLIK (varsayılan), UC_AYLIK, ALTI_AYLIK, YILLIK.",
    ),
    Sutun("ucret", ("Ücret", "Ucret", "Tutar"), zorunlu=True, aciklama="DÖNEM ücreti (TL)."),
    Sutun("kdv", ("KDV Oranı", "KDV"), aciklama="0.20 ya da %20. Boşsa ayarlardaki varsayılan."),
    Sutun("baslangic", ("Başlangıç", "Baslangic"), zorunlu=True, aciklama="GG.AA.YYYY."),
    Sutun("bitis", ("Bitiş", "Bitis"), aciklama="GG.AA.YYYY. Boşsa süresiz."),
    Sutun(
        "taahhut_bitisi",
        ("Taahhüt Bitişi", "Taahhut Bitisi"),
        aciklama="GG.AA.YYYY. Taahhüt süren sözleşme toplu zamdan otomatik muaf tutulur.",
    ),
    # ham=True: "YOK" bu sütunda GEÇERLİ BİR DEĞER, dolgu işareti değil.
    # Dolgu filtresi onu boşaltınca alan hiç gelmemiş sayılıyor ve varsayılan
    # OTOMATIK uygulanıyordu: yenilenmemesi gereken sözleşme, hatasız ve
    # uyarısız biçimde otomatik yenilemeli giriyordu.
    Sutun("yenileme", ("Yenileme",), aciklama="OTOMATIK (varsayılan), MANUEL, YOK.", ham=True),
    Sutun("notlar", ("Not", "Notlar"), aciklama="Serbest not."),
)


class AbonelikProfili(Profil):
    kod = "abonelik"
    ad = "Abonelikler"
    aciklama = "Sözleşme listesi. TASLAK olarak girer; MRR'a ancak aktifleştirilince dahil olur."
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        hesaplar = {
            h.title_key: h.id
            for h in (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
        }
        araclar = {
            a.plate_key: a
            for a in (await db.scalars(select(Vehicle).where(Vehicle.is_deleted.is_(False)))).all()
        }

        sonuclar: list[SatirSonucu] = []
        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            musteri = clean_cell(ham.get("musteri"))
            hesap_id = hesaplar.get(tr_normkey(musteri))
            if hesap_id is None:
                r.hatalar.append(f"Hesaplarda bulunamadı: {musteri}")
            else:
                r.veri["customer_id"] = hesap_id

            plaka_ham = clean_cell(ham.get("plaka"))
            if plaka_ham:
                arac = araclar.get(plaka_anahtari(plaka_ham))
                if arac is None:
                    r.uyarilar.append(f"Araç bulunamadı, abonelik araçsız açılacak: {plaka_ham}")
                else:
                    r.veri["vehicle_id"] = arac.id
                    if hesap_id and arac.customer_id and arac.customer_id != hesap_id:
                        r.uyarilar.append("Araç bu müşteriye kayıtlı değil — kontrol edin")

            periyot = tr_normkey(ham.get("periyot", "")).upper().replace(" ", "_") or "AYLIK"
            if periyot not in FATURA_PERIYOTLARI:
                r.hatalar.append(f"Periyot {FATURA_PERIYOTLARI} içinden olmalı: {periyot}")
            else:
                r.veri["billing_period"] = periyot

            yenileme = tr_normkey(ham.get("yenileme", "")).upper().replace(" ", "_") or "OTOMATIK"
            if yenileme not in YENILEME_TIPLERI:
                r.hatalar.append(f"Yenileme {YENILEME_TIPLERI} içinden olmalı: {yenileme}")
            else:
                r.veri["renewal_type"] = yenileme

            try:
                ucret = tutar_coz(ham.get("ucret"))
                if ucret < 0:
                    r.hatalar.append("Ücret negatif olamaz")
                else:
                    r.veri["unit_price"] = ucret
            except ValueError as exc:
                r.hatalar.append(f"Ücret: {exc}")

            kdv_ham = clean_cell(ham.get("kdv"))
            if kdv_ham:
                try:
                    kdv = tutar_coz(kdv_ham.replace("%", ""))
                    # "20" ile "0.20" aynı şeyi kasteder; yüzde işareti çoğu
                    # dosyada unutuluyor.
                    r.veri["vat_rate"] = kdv / Decimal("100") if kdv > 1 else kdv
                except ValueError as exc:
                    r.hatalar.append(f"KDV: {exc}")

            for alan, kaynak in (
                ("start_date", "baslangic"),
                ("end_date", "bitis"),
                ("commitment_end_date", "taahhut_bitisi"),
            ):
                deger = clean_cell(ham.get(kaynak))
                if not deger:
                    if alan == "start_date":
                        r.hatalar.append("Başlangıç tarihi zorunlu")
                    continue
                try:
                    r.veri[alan] = tarih_coz(deger)
                except ValueError as exc:
                    r.hatalar.append(f"{kaynak}: {exc}")

            bas, bit = r.veri.get("start_date"), r.veri.get("end_date")
            if bas and bit and bit < bas:
                r.hatalar.append("Bitiş tarihi başlangıçtan önce olamaz")

            for alan, kaynak in (("title", "konu"), ("notes", "notlar")):
                deger = clean_cell(ham.get(kaynak))
                if deger:
                    r.veri[alan] = deger

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        """Aynı müşteri + araç (ya da araçsızsa müşteri + başlık) için yürüyen
        abonelik varsa uyarır.

        Araçsız satırlar hiç kontrol edilmiyordu: platform/genel abonelikler
        aynı dosya ikinci kez yüklendiğinde YENİDEN AÇILIYORDU. Plakalı
        satırlar doğru şekilde çakışma veriyordu, araçsız olanlar MRR'a
        mükerrer sözleşme olarak giriyordu.
        """
        for r in sonuclar:
            if not r.gecerli:
                continue
            kosullar = [
                Subscription.is_deleted.is_(False),
                Subscription.status.in_(("TASLAK", "AKTIF", "ASKIDA")),
            ]
            if r.veri.get("vehicle_id"):
                kosullar.append(Subscription.vehicle_id == r.veri["vehicle_id"])
            elif r.veri.get("customer_id"):
                kosullar += [
                    Subscription.customer_id == r.veri["customer_id"],
                    Subscription.vehicle_id.is_(None),
                    Subscription.title == r.veri.get("title"),
                ]
            else:
                continue
            mevcut = await db.scalar(select(Subscription).where(*kosullar))
            if mevcut is None:
                continue
            nesne = "Bu aracın" if r.veri.get("vehicle_id") else "Bu müşterinin aynı başlıkta"
            r.cakisma = {
                "tip": "arac_zaten_abone" if r.veri.get("vehicle_id") else "musteri_zaten_abone",
                "kayit_id": mevcut.id,
                "aciklama": (
                    f"{nesne} {mevcut.subscription_no} aboneliği zaten var "
                    f"({mevcut.status}). Onaylanırsa İKİNCİ bir abonelik açılır."
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
        from app.services import settings as ayar_svc

        sayac = self.bos_sayac()
        varsayilan_kdv = Decimal(str(await ayar_svc.get(db, "kdv_oran_varsayilan")))

        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            veri: dict[str, Any] = satir["veri"]
            baslangic = _gun(veri["start_date"])

            abonelik = Subscription(
                subscription_no=await abonelik_svc.numara_uret(db, clock),
                customer_id=int(veri["customer_id"]),
                vehicle_id=int(veri["vehicle_id"]) if veri.get("vehicle_id") else None,
                title=veri.get("title"),
                billing_period=veri["billing_period"],
                vat_rate=Decimal(str(veri.get("vat_rate") or varsayilan_kdv)),
                start_date=baslangic,
                end_date=_gun(veri["end_date"]) if veri.get("end_date") else None,
                commitment_end_date=(
                    _gun(veri["commitment_end_date"]) if veri.get("commitment_end_date") else None
                ),
                renewal_type=veri["renewal_type"],
                notes=veri.get("notes"),
                created_by=user_id,
            )
            db.add(abonelik)
            await db.flush()
            await abonelik_svc.fiyat_yaz(
                db,
                abonelik,
                unit_price=Decimal(str(veri["unit_price"])),
                valid_from=baslangic,
                neden="İçe aktarma",
                user_id=user_id,
            )
            sayac["eklendi"] += 1

        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        return sayac


def _gun(deger: Any) -> date:
    return deger if isinstance(deger, date) else date.fromisoformat(str(deger))
