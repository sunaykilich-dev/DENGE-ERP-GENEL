"""Araç profili.

Plaka `normalize_plate` ile anahtarlanır; doğrulanamayan plaka REDDEDİLMEZ,
`is_plate_verified=false` ile girer ve arayüzde rozetle görünür. Gerçek
veride 194 kayıtta plaka da şase de boştu; aracı hiç açmamak, iş emrinin
hangi araca yapıldığını büsbütün kaybettirirdi.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Vehicle
from app.models.vehicle import plaka_anahtari
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.normalize import clean_cell, normalize_plate, tr_normkey

SUTUNLAR = (
    Sutun("plaka", ("Plaka", "Mevcut Plaka"), zorunlu=True, aciklama="Ör. 34ABC123."),
    Sutun("musteri", ("Firma", "Müşteri", "Firma Adı"), aciklama="Hesaplardaki müşteri unvanı."),
    Sutun("sase", ("Şase No", "Sase No", "VIN"), aciklama="17 haneli şase / VIN."),
    Sutun("ruhsat", ("Ruhsat No", "Ruhsat"), aciklama="Ruhsat belge numarası."),
    Sutun("marka", ("Marka",), aciklama="Ör. Ford."),
    Sutun("model", ("Model", "Araç Modeli"), aciklama="Ör. Transit."),
    Sutun("yil", ("Yıl", "Model Yılı", "Ü.Yılı"), aciklama="4 haneli yıl."),
    Sutun("tip", ("Araç Tipi", "Tip"), aciklama="Ör. KAMYONET, OTOBUS, BINEK."),
    Sutun("notlar", ("Not", "Notlar"), aciklama="Serbest not."),
)


class AracProfili(Profil):
    kod = "arac"
    ad = "Araçlar"
    aciklama = "Müşteri araç listesi. Plaka doğrulanamazsa kayıt yine açılır, rozetlenir."
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        hesaplar = {
            h.title_key: h.id
            for h in (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
        }

        sonuclar: list[SatirSonucu] = []
        gorulen: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            plaka_ham = clean_cell(ham.get("plaka"))
            try:
                plaka = normalize_plate(plaka_ham)
            except ValueError:
                plaka = ""
            if not plaka_ham:
                r.hatalar.append("Plaka boş")
            elif not plaka:
                # Okunabilir ama biçime uymayan plaka: kayıt açılır, rozetlenir.
                r.veri["plate"] = plaka_ham
                r.veri["plate_key"] = plaka_anahtari(plaka_ham)
                r.veri["is_plate_verified"] = False
                r.uyarilar.append("Plaka biçimi tanınmadı; 'doğrulanmadı' rozetiyle girecek")
            else:
                r.veri["plate"] = plaka
                r.veri["plate_key"] = plaka_anahtari(plaka)
                r.veri["is_plate_verified"] = True

            musteri = clean_cell(ham.get("musteri"))
            if musteri:
                hesap_id = hesaplar.get(tr_normkey(musteri))
                if hesap_id is None:
                    r.hatalar.append(f"Hesaplarda bulunamadı: {musteri}")
                else:
                    r.veri["customer_id"] = hesap_id

            for alan, kaynak in (
                ("chassis_no", "sase"),
                ("registration_no", "ruhsat"),
                ("brand", "marka"),
                ("model", "model"),
                ("vehicle_type", "tip"),
                ("notes", "notlar"),
            ):
                deger = clean_cell(ham.get(kaynak))
                if deger:
                    r.veri[alan] = deger.upper() if alan == "vehicle_type" else deger

            yil = clean_cell(ham.get("yil"))
            if yil:
                rakamlar = "".join(c for c in yil if c.isdigit())[:4]
                if len(rakamlar) == 4 and 1950 <= int(rakamlar) <= 2100:
                    r.veri["model_year"] = int(rakamlar)
                else:
                    r.uyarilar.append(f"Model yılı okunamadı, boş bırakıldı: {yil}")

            anahtar = r.veri.get("plate_key")
            if anahtar:
                if anahtar in gorulen:
                    r.hatalar.append(f"Dosya içinde mükerrer plaka (ilk satır: {gorulen[anahtar]})")
                else:
                    gorulen[anahtar] = sira

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        anahtarlar = [
            r.veri["plate_key"] for r in sonuclar if r.gecerli and r.veri.get("plate_key")
        ]
        if not anahtarlar:
            return
        mevcutlar = {
            a.plate_key: a
            for a in (
                await db.scalars(
                    select(Vehicle).where(
                        Vehicle.plate_key.in_(anahtarlar), Vehicle.is_deleted.is_(False)
                    )
                )
            ).all()
        }
        for r in sonuclar:
            mevcut = mevcutlar.get(r.veri.get("plate_key"))
            if mevcut is None:
                continue
            r.cakisma = {
                "tip": "mevcut",
                "kayit_id": mevcut.id,
                "aciklama": (
                    f"{mevcut.plate} zaten kayıtlı. Güncellenirse dosyada DOLU olan alanlar "
                    "yazılır; boş bırakılan alanlar mevcut değerini korur."
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
            alanlar = _alanlara_cevir(veri)
            cakisma = satir.get("cakisma")

            if cakisma:
                mevcut = await db.get(Vehicle, cakisma["kayit_id"])
                if mevcut is None:
                    continue
                for alan, deger in alanlar.items():
                    # Boş hücre "sil" demek değildir; yalnız dolu alanlar yazılır.
                    if deger is None or alan == "plate_key":
                        continue
                    setattr(mevcut, alan, deger)
                mevcut.updated_by = user_id
                sayac["guncellendi"] += 1
                continue

            db.add(Vehicle(**alanlar, created_by=user_id))
            sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


def _alanlara_cevir(veri: dict[str, Any]) -> dict[str, Any]:
    alanlar: dict[str, Any] = {}
    for alan in (
        "plate",
        "plate_key",
        "chassis_no",
        "registration_no",
        "brand",
        "model",
        "vehicle_type",
        "notes",
    ):
        if veri.get(alan):
            alanlar[alan] = veri[alan]
    if veri.get("customer_id"):
        alanlar["customer_id"] = int(veri["customer_id"])
    if veri.get("model_year"):
        alanlar["model_year"] = int(veri["model_year"])
    if veri.get("is_plate_verified") is not None:
        alanlar["is_plate_verified"] = str(veri["is_plate_verified"]).lower() in ("true", "1")
    return alanlar
