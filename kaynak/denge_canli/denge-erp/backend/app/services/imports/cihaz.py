"""Cihaz profili: IMEI/seri no partisi yükleme.

Kimlik politikası ÜRÜN KARTINDAN gelir (plan §2/1): `identity_kind = IMEI`
olan üründe IMEI, `SERI_NO` olanda seri no zorunludur. Dosyada hangisinin
dolu olduğuna bakıp karar vermek, 898 satırlık analog kamera partisini
"IMEI'si eksik" diye reddetmek olurdu.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Device, Product
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.normalize import clean_cell, tr_normkey, validate_imei

SUTUNLAR = (
    Sutun(
        "urun",
        ("Ürün Kodu", "Urun Kodu", "Model", "Cihaz Modeli"),
        zorunlu=True,
        aciklama="Ürün kataloğundaki kod ya da ad (ör. L300, DAHUA-HMW3200LP).",
    ),
    Sutun(
        "imei",
        ("IMEI", "Cihaz IMEI No", "IMEI No"),
        aciklama="15 haneli IMEI. Ürünün kimlik tipi IMEI ise zorunludur.",
    ),
    Sutun(
        "seri_no",
        ("Seri No", "Serial No", "SN"),
        aciklama="Ürünün kimlik tipi SERİ NO ise zorunludur (ek kameralar).",
    ),
    Sutun(
        "durum",
        ("Durum",),
        aciklama="Boş bırakılırsa STOKTA. Geçerli: STOKTA, TEST_EDILDI, ITHALATTA.",
    ),
    Sutun("notlar", ("Not", "Notlar", "Açıklama"), aciklama="Serbest not."),
)

# Yeni parti yalnız stok tarafındaki durumlarla girebilir; "AKTIF" bir cihazı
# Excel'den açmak, montaj ve cihaz-araç dönemi olmadan aktif cihaz demekti.
GIRIS_DURUMLARI = ("STOKTA", "TEST_EDILDI", "ITHALATTA")


class CihazProfili(Profil):
    kod = "cihaz"
    ad = "Cihazlar"
    aciklama = "Yeni IMEI / seri no partisi. Kimlik zorunluluğu ürün kartından gelir."
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        urunler = (await db.scalars(select(Product))).all()
        urun_indeks: dict[str, Product] = {}
        for u in urunler:
            urun_indeks[tr_normkey(u.code)] = u
            urun_indeks.setdefault(tr_normkey(u.name), u)

        sonuclar: list[SatirSonucu] = []
        gorulen_imei: dict[str, int] = {}
        gorulen_seri: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            urun = urun_indeks.get(tr_normkey(ham.get("urun", "")))
            if urun is None:
                r.hatalar.append(f"Ürün kataloğunda yok: {clean_cell(ham.get('urun'))}")
            else:
                r.veri["product_id"] = urun.id
                r.veri["identity_kind"] = urun.identity_kind

            imei_ham = clean_cell(ham.get("imei"))
            if imei_ham:
                try:
                    r.veri["imei"] = validate_imei(imei_ham)
                except ValueError as exc:
                    r.hatalar.append(str(exc))
            seri = clean_cell(ham.get("seri_no"))
            if seri:
                r.veri["serial_no"] = seri

            if urun is not None:
                if urun.identity_kind == "IMEI" and not r.veri.get("imei"):
                    r.hatalar.append(f"{urun.code} ürünü IMEI ister; IMEI sütunu boş.")
                elif urun.identity_kind == "SERI_NO" and not r.veri.get("serial_no"):
                    r.hatalar.append(f"{urun.code} ürünü seri no ister; Seri No sütunu boş.")

            durum = tr_normkey(ham.get("durum", "")).upper().replace(" ", "_") or "STOKTA"
            if durum not in GIRIS_DURUMLARI:
                r.hatalar.append(f"Durum {GIRIS_DURUMLARI} içinden olmalı: {durum}")
            else:
                r.veri["status"] = durum

            notlar = clean_cell(ham.get("notlar"))
            if notlar:
                r.veri["notes"] = notlar

            # Dosya içi mükerrer: ilk satır geçerli kalır.
            for alan, gorulen in (("imei", gorulen_imei), ("serial_no", gorulen_seri)):
                deger = r.veri.get(alan)
                if not deger:
                    continue
                if deger in gorulen:
                    r.hatalar.append(
                        f"Dosya içinde mükerrer {alan} (ilk görüldüğü satır: {gorulen[deger]})"
                    )
                else:
                    gorulen[deger] = sira

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        imeiler = [r.veri["imei"] for r in sonuclar if r.gecerli and r.veri.get("imei")]
        seriler = [r.veri["serial_no"] for r in sonuclar if r.gecerli and r.veri.get("serial_no")]
        if not imeiler and not seriler:
            return

        mevcutlar = (
            await db.scalars(
                select(Device).where(
                    (Device.imei.in_(imeiler or [""])) | (Device.serial_no.in_(seriler or [""]))
                )
            )
        ).all()
        imei_ile = {d.imei: d for d in mevcutlar if d.imei}
        seri_ile = {d.serial_no: d for d in mevcutlar if d.serial_no}

        for r in sonuclar:
            if not r.gecerli:
                continue
            mevcut = imei_ile.get(r.veri.get("imei")) or seri_ile.get(r.veri.get("serial_no"))
            if mevcut is None:
                continue
            kimlik = mevcut.imei or mevcut.serial_no
            if mevcut.is_deleted:
                r.cakisma = {
                    "tip": "silinmis",
                    "kayit_id": mevcut.id,
                    "aciklama": f"{kimlik} silinmiş bir kayıt — geri açılsın mı?",
                }
            elif mevcut.status == r.veri.get("status"):
                r.cakisma = {
                    "tip": "mevcut",
                    "kayit_id": mevcut.id,
                    "aciklama": f"{kimlik} zaten kayıtlı ve aynı durumda; değişiklik yok.",
                }
            else:
                r.cakisma = {
                    "tip": "durum_farkli",
                    "kayit_id": mevcut.id,
                    "aciklama": (
                        f"{kimlik} sistemde '{mevcut.status}' durumunda. "
                        "Durum güncellenmemeli — cihaz durumu yalnız iş akışıyla değişir."
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
            cakisma = satir.get("cakisma")

            if cakisma:
                # Var olan cihazın DURUMUNA dokunulmaz; yalnız not ve
                # kimlik tamamlanır. Durum geçişi iş akışının işidir.
                mevcut = await db.get(Device, cakisma["kayit_id"])
                if mevcut is None:
                    sayac["atlandi"] += 1
                    continue
                if mevcut.is_deleted:
                    mevcut.is_deleted = False
                    mevcut.deleted_at = None
                    mevcut.deleted_by = None
                if veri.get("notes"):
                    mevcut.notes = veri["notes"]
                if veri.get("imei") and not mevcut.imei:
                    mevcut.imei = veri["imei"]
                    mevcut.is_identity_provisional = False
                if veri.get("serial_no") and not mevcut.serial_no:
                    mevcut.serial_no = veri["serial_no"]
                mevcut.updated_by = user_id
                sayac["guncellendi"] += 1
                continue

            db.add(
                Device(
                    imei=veri.get("imei"),
                    serial_no=veri.get("serial_no"),
                    identity_kind=veri["identity_kind"],
                    product_id=int(veri["product_id"]),
                    status=veri["status"],
                    notes=veri.get("notes"),
                    created_by=user_id,
                )
            )
            sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac
