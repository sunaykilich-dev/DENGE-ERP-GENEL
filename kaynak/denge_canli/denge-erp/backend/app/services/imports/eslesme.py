"""Eşleştirme profilleri: cihaz–hat, cihaz–araç, cihaz–zimmet.

Varlık profillerinden (cihaz, hat, araç) farkları: bunlar **tarihli ilişki**
yazar. İlişki kayıtlarının hepsinde `[)` yarı açık aralık ve EXCLUDE kısıtı
var; açık dönemi kapatmadan yeni dönem açmak veritabanı hatası verirdi. Bu
yüzden hiçbiri doğrudan INSERT etmez, mevcut servisleri çağırır
(`devices.hat_tak`, `assignments.tak`, `stock.konum_ata`) — kural tek yerde
kalsın diye.

**Montaj içe aktarımı HAK EDİŞ SATIRI ÜRETMEZ.** Sahada yıllardır takılı
cihazları sisteme tanıtmak, o montajlar için montaj noktasına para borcu
doğurmaz; göçte Esenyurt dosyası da aynı kararla aktarılmıştı. Hak ediş
yalnız ERP'de açılan iş emrinden doğar.
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Device, SimCard, SimDeviceHistory, Vehicle, Warehouse
from app.models.stock import KONUM_TIPLERI, SAHIPLIK_DURUMLARI
from app.models.vehicle import plaka_anahtari
from app.services import assignments as atama_svc
from app.services import stock as stok_svc
from app.services.devices import durum_degistir, hat_tak
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz
from app.services.normalize import (
    clean_cell,
    normalize_iccid,
    normalize_msisdn,
    tr_normkey,
)
from app.services.statemachine import CIHAZ, IzinsizGecis

KIMLIK_SUTUNU = Sutun(
    "kimlik",
    ("IMEI", "Cihaz IMEI No", "IMEI / Seri No", "Seri No"),
    zorunlu=True,
    aciklama="Cihazın IMEI'si ya da seri numarası.",
)


def _an(deger: Any) -> datetime:
    """Tarih hücresini günün başına (UTC) sabitler."""
    if isinstance(deger, datetime):
        return deger if deger.tzinfo else deger.replace(tzinfo=UTC)
    gun = deger if isinstance(deger, date) else date.fromisoformat(str(deger))
    return datetime.combine(gun, datetime.min.time(), tzinfo=UTC)


async def _cihaz_dizini(db: AsyncSession) -> dict[str, Device]:
    """IMEI ve seri no, ikisi de aynı sözlükte — dosyada hangisi varsa."""
    dizin: dict[str, Device] = {}
    for c in (await db.scalars(select(Device).where(Device.is_deleted.is_(False)))).all():
        if c.imei:
            dizin[c.imei] = c
        if c.serial_no:
            dizin.setdefault(tr_normkey(c.serial_no), c)
    return dizin


def _cihaz_bul(dizin: dict[str, Device], ham: str) -> Device | None:
    return dizin.get(ham) or dizin.get(tr_normkey(ham))


# --- Cihaz ↔ Hat --------------------------------------------------------------


class CihazHatProfili(Profil):
    kod = "cihaz_hat"
    ad = "IMEI–SIM eşleştirme"
    aciklama = "Hangi hattın hangi cihazda olduğu. Tarihli — önceki eşleşme kapatılır."
    sutunlar = (
        KIMLIK_SUTUNU,
        Sutun(
            "hat",
            ("ICCID", "Hat No", "Numara", "MSISDN", "M2M Hat No"),
            zorunlu=True,
            aciklama="ICCID ya da hat numarası; ikisi de kabul edilir.",
        ),
        Sutun(
            "tarih",
            ("Takılma Tarihi", "Tarih", "Başlangıç"),
            aciklama="GG.AA.YYYY. Boşsa bugün. Geçmişe dönük eşleştirme yazılabilir.",
        ),
    )

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        cihazlar = await _cihaz_dizini(db)
        hatlar: dict[str, SimCard] = {}
        for h in (await db.scalars(select(SimCard).where(SimCard.is_deleted.is_(False)))).all():
            hatlar[h.iccid] = h
            if h.msisdn:
                hatlar.setdefault(h.msisdn, h)

        sonuclar: list[SatirSonucu] = []
        gorulen_cihaz: dict[int, int] = {}
        gorulen_hat: dict[int, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            kimlik = clean_cell(ham.get("kimlik"))
            cihaz = _cihaz_bul(cihazlar, kimlik)
            if cihaz is None:
                r.hatalar.append(f"Cihaz bulunamadı: {kimlik} (önce Cihazlar profilini yükleyin)")
            else:
                r.veri["device_id"] = cihaz.id

            hat = _hat_bul(hatlar, clean_cell(ham.get("hat")))
            if hat is None:
                r.hatalar.append(
                    f"Hat bulunamadı: {clean_cell(ham.get('hat'))} (önce Hatlar profilini yükleyin)"
                )
            else:
                r.veri["sim_id"] = hat.id

            tarih = clean_cell(ham.get("tarih"))
            if tarih:
                try:
                    r.veri["tarih"] = tarih_coz(tarih)
                except ValueError as exc:
                    r.hatalar.append(f"Tarih: {exc}")

            # Dosya içi çift kullanım: bir cihaza iki hat ya da bir hat iki
            # cihaza takılamaz; ikisi de EXCLUDE kısıtına çarpardı.
            for alan, gorulen, ad in (
                ("device_id", gorulen_cihaz, "cihaz"),
                ("sim_id", gorulen_hat, "hat"),
            ):
                kid = r.veri.get(alan)
                if kid is None:
                    continue
                if kid in gorulen:
                    r.hatalar.append(f"Dosyada aynı {ad} ikinci kez (ilk satır: {gorulen[kid]})")
                else:
                    gorulen[kid] = sira

            sonuclar.append(r)

        await self._acik_donemleri_isaretle(db, sonuclar)
        return sonuclar

    async def _acik_donemleri_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        for r in sonuclar:
            if not r.gecerli:
                continue
            acik = (
                await db.scalars(
                    select(SimDeviceHistory).where(
                        (SimDeviceHistory.device_id == r.veri["device_id"])
                        | (SimDeviceHistory.sim_id == r.veri["sim_id"]),
                        SimDeviceHistory.valid_to.is_(None),
                    )
                )
            ).all()
            if not acik:
                continue
            aynisi = [
                a
                for a in acik
                if a.device_id == r.veri["device_id"] and a.sim_id == r.veri["sim_id"]
            ]
            if aynisi:
                r.cakisma = {
                    "tip": "mevcut",
                    "kayit_id": aynisi[0].id,
                    "aciklama": "Bu eşleşme zaten açık; değişiklik yok.",
                }
            elif any(a.valid_from >= _an(r.veri["tarih"]) for a in acik if r.veri.get("tarih")):
                # Yeni eşleşme açık dönemin başlangıcından önce/aynı anda
                # olamaz: sıfır uzunlukta dönem aralık kısıtına çarpar.
                en_erken = min(a.valid_from for a in acik)
                r.hatalar.append(
                    f"Açık eşleşme {en_erken:%d.%m.%Y} tarihinde başlıyor; "
                    "takılma tarihi bundan sonra olmalı."
                )
            else:
                r.cakisma = {
                    "tip": "acik_donem",
                    "kayit_id": acik[0].id,
                    "aciklama": (
                        f"Cihazın ya da hattın açık bir eşleşmesi var "
                        f"({acik[0].valid_from:%d.%m.%Y}'den beri). Onaylanırsa o dönem "
                        "kapatılır, yenisi açılır."
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
            if (satir.get("cakisma") or {}).get("tip") == "mevcut":
                continue
            try:
                await hat_tak(
                    db,
                    device_id=int(veri["device_id"]),
                    sim_id=int(veri["sim_id"]),
                    clock=clock,
                    an=_an(veri["tarih"]) if veri.get("tarih") else None,
                )
            except ValueError as exc:
                raise ValueError(f"Satır {satir['satir_no']}: {exc}") from exc
            if satir.get("cakisma"):
                sayac["guncellendi"] += 1
            else:
                sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


def _hat_bul(hatlar: dict[str, SimCard], ham: str) -> SimCard | None:
    if not ham:
        return None
    for cozucu in (normalize_iccid, normalize_msisdn):
        try:
            bulunan = hatlar.get(cozucu(ham))
        except ValueError:
            continue
        if bulunan is not None:
            return bulunan
    return hatlar.get(ham)


# --- Cihaz ↔ Araç -------------------------------------------------------------


class CihazAracProfili(Profil):
    kod = "cihaz_arac"
    ad = "IMEI–araç montajı"
    aciklama = (
        "Sahada takılı cihazların araç eşleşmesi. Hak ediş satırı ÜRETMEZ — "
        "hak ediş yalnız ERP'de açılan iş emrinden doğar."
    )
    sutunlar = (
        KIMLIK_SUTUNU,
        Sutun("plaka", ("Plaka",), zorunlu=True, aciklama="Araçlar listesinde kayıtlı plaka."),
        Sutun(
            "tarih",
            ("Montaj Tarihi", "Tarih", "Başlangıç"),
            aciklama="GG.AA.YYYY. Boşsa bugün.",
        ),
        Sutun(
            "montaj_noktasi",
            ("Montaj Noktası", "Montaj Noktasi"),
            aciklama="Montajı yapan nokta (bilgi amaçlı; ödeme doğurmaz).",
        ),
        Sutun(
            "rol",
            ("Cihaz Rolü", "Rol"),
            aciklama="BIRINCIL_TAKIP, KAMERA, YARDIMCI_KAMERA, AKSESUAR.",
        ),
    )

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        cihazlar = await _cihaz_dizini(db)
        araclar = {
            a.plate_key: a
            for a in (await db.scalars(select(Vehicle).where(Vehicle.is_deleted.is_(False)))).all()
        }
        noktalar = {
            h.title_key: h.id
            for h in (
                await db.scalars(
                    select(Account).where(
                        Account.is_montaj_noktasi.is_(True), Account.is_deleted.is_(False)
                    )
                )
            ).all()
        }

        sonuclar: list[SatirSonucu] = []
        gorulen: dict[int, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            kimlik = clean_cell(ham.get("kimlik"))
            cihaz = _cihaz_bul(cihazlar, kimlik)
            if cihaz is None:
                r.hatalar.append(f"Cihaz bulunamadı: {kimlik}")
            elif cihaz.status in ("HURDA", "KAYIP_CALINTI"):
                r.hatalar.append(f"{kimlik} cihazı '{cihaz.status}' durumunda; araca takılamaz.")
            else:
                r.veri["device_id"] = cihaz.id
                r.veri["mevcut_durum"] = cihaz.status

            plaka_ham = clean_cell(ham.get("plaka"))
            arac = araclar.get(plaka_anahtari(plaka_ham))
            if arac is None:
                r.hatalar.append(f"Araç bulunamadı: {plaka_ham} (önce Araçlar profilini yükleyin)")
            else:
                r.veri["vehicle_id"] = arac.id
                if arac.customer_id:
                    r.veri["customer_id"] = arac.customer_id

            nokta = clean_cell(ham.get("montaj_noktasi"))
            if nokta:
                nokta_id = noktalar.get(tr_normkey(nokta))
                if nokta_id is None:
                    r.uyarilar.append(f"Montaj noktası bulunamadı, boş bırakıldı: {nokta}")
                else:
                    r.veri["installed_by_id"] = nokta_id

            rol = tr_normkey(ham.get("rol", "")).upper().replace(" ", "_")
            if rol:
                if rol not in ("BIRINCIL_TAKIP", "KAMERA", "YARDIMCI_KAMERA", "AKSESUAR"):
                    r.hatalar.append(f"Cihaz rolü tanınmadı: {rol}")
                else:
                    r.veri["device_role"] = rol

            tarih = clean_cell(ham.get("tarih"))
            if tarih:
                try:
                    r.veri["tarih"] = tarih_coz(tarih)
                except ValueError as exc:
                    r.hatalar.append(f"Tarih: {exc}")

            cid = r.veri.get("device_id")
            if cid is not None:
                if cid in gorulen:
                    r.hatalar.append(f"Dosyada aynı cihaz ikinci kez (ilk satır: {gorulen[cid]})")
                else:
                    gorulen[cid] = sira

            sonuclar.append(r)

        await self._acik_donemleri_isaretle(db, sonuclar)
        return sonuclar

    async def _acik_donemleri_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        for r in sonuclar:
            if not r.gecerli:
                continue
            acik = await atama_svc.acik_donem(db, r.veri["device_id"])
            if acik is None:
                continue
            if acik.vehicle_id == r.veri["vehicle_id"]:
                r.cakisma = {
                    "tip": "mevcut",
                    "kayit_id": acik.id,
                    "aciklama": "Cihaz zaten bu araçta; değişiklik yok.",
                }
            elif r.veri.get("tarih") and acik.valid_from >= _an(r.veri["tarih"]):
                r.hatalar.append(
                    f"Cihazın açık montajı {acik.valid_from:%d.%m.%Y} tarihinde başlıyor; "
                    "yeni montaj tarihi bundan sonra olmalı."
                )
            else:
                arac = await db.get(Vehicle, acik.vehicle_id)
                r.cakisma = {
                    "tip": "baska_arac",
                    "kayit_id": acik.id,
                    "aciklama": (
                        f"Cihaz şu an {arac.plate if arac else acik.vehicle_id} aracında "
                        f"({acik.valid_from:%d.%m.%Y}'den beri). Onaylanırsa o dönem "
                        "kapatılır, yeni araca taşınır."
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
            if (satir.get("cakisma") or {}).get("tip") == "mevcut":
                continue
            an = _an(veri["tarih"]) if veri.get("tarih") else clock.now()

            try:
                await atama_svc.tak(
                    db,
                    device_id=int(veri["device_id"]),
                    vehicle_id=int(veri["vehicle_id"]),
                    clock=clock,
                    customer_id=int(veri["customer_id"]) if veri.get("customer_id") else None,
                    installed_by_type="MONTAJ_NOKTASI" if veri.get("installed_by_id") else None,
                    installed_by_id=(
                        int(veri["installed_by_id"]) if veri.get("installed_by_id") else None
                    ),
                    an=an,
                    # Tarihi dosyadan gelen montaj çıkarım değil, beyandır.
                    is_inferred=not veri.get("tarih"),
                )
            except ValueError as exc:
                raise ValueError(f"Satır {satir['satir_no']}: {exc}") from exc

            cihaz = await db.get(Device, int(veri["device_id"]))
            if cihaz is not None:
                if veri.get("device_role"):
                    cihaz.device_role = veri["device_role"]
                # Araca takılı cihaz STOKTA görünemez; durum zincirini
                # makinenin verdiği en kısa yoldan yürü (doğrudan atama
                # geçmişi uydururdu).
                await self._aktife_al(db, cihaz, clock=clock, user_id=user_id)

            if satir.get("cakisma"):
                sayac["guncellendi"] += 1
            else:
                sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac

    async def _aktife_al(
        self, db: AsyncSession, cihaz: Device, *, clock: Clock, user_id: int | None
    ) -> None:
        for adim in CIHAZ.yol(cihaz.status, "AKTIF"):
            try:
                await durum_degistir(
                    db,
                    cihaz,
                    adim,
                    clock=clock,
                    user_id=user_id,
                    neden="İçe aktarma: sahada takılı cihaz",
                )
            except IzinsizGecis:
                break


# --- Cihaz ↔ Zimmet (konum / sahiplik) ----------------------------------------


class CihazZimmetProfili(Profil):
    kod = "cihaz_zimmet"
    ad = "Cihaz zimmet / konum"
    aciklama = "Cihazların nerede ve kimin malı olduğu. Konum ve sahiplik ayrı iki boyut."
    sutunlar = (
        KIMLIK_SUTUNU,
        Sutun(
            "konum_tipi",
            ("Konum Tipi", "Konum"),
            zorunlu=True,
            aciklama="MERKEZ_DEPO, BOLGE_DEPO, TEKNISYEN, MONTAJ_NOKTASI, BAYI, MUSTERI, "
            "YOLDA, SERVIS, HURDA.",
        ),
        Sutun(
            "hesap",
            ("Hesap", "Bayi", "Montaj Noktası", "Müşteri"),
            aciklama="Bayi / montaj noktası / müşteri konumlarında hesap unvanı.",
        ),
        Sutun("depo", ("Depo", "Depo Kodu"), aciklama="Depo konumlarında depo kodu."),
        Sutun(
            "sahiplik",
            ("Sahiplik",),
            aciklama="DENGE, BAYI_SATILDI, MUSTERI_SATILDI, MUSTERI_KIRALIK. "
            "Boşsa önceki sahiplik korunur.",
        ),
        Sutun("tarih", ("Tarih", "Başlangıç"), aciklama="GG.AA.YYYY. Boşsa bugün."),
    )

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        cihazlar = await _cihaz_dizini(db)
        hesaplar = {
            h.title_key: h.id
            for h in (await db.scalars(select(Account).where(Account.is_deleted.is_(False)))).all()
        }
        depolar = {tr_normkey(d.code): d.id for d in (await db.scalars(select(Warehouse))).all()}

        sonuclar: list[SatirSonucu] = []
        gorulen: dict[int, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            kimlik = clean_cell(ham.get("kimlik"))
            cihaz = _cihaz_bul(cihazlar, kimlik)
            if cihaz is None:
                r.hatalar.append(f"Cihaz bulunamadı: {kimlik}")
            else:
                r.veri["device_id"] = cihaz.id

            konum = tr_normkey(ham.get("konum_tipi", "")).upper().replace(" ", "_")
            if konum not in KONUM_TIPLERI:
                r.hatalar.append(f"Konum tipi {KONUM_TIPLERI} içinden olmalı: {konum}")
            else:
                r.veri["location_type"] = konum

            hesap = clean_cell(ham.get("hesap"))
            if hesap:
                hesap_id = hesaplar.get(tr_normkey(hesap))
                if hesap_id is None:
                    r.hatalar.append(f"Hesap bulunamadı: {hesap}")
                else:
                    r.veri["account_id"] = hesap_id
            elif konum in ("BAYI", "MUSTERI", "MONTAJ_NOKTASI"):
                r.uyarilar.append(f"{konum} konumunda hesap girilmedi — kimde olduğu belirsiz")

            depo = clean_cell(ham.get("depo"))
            if depo:
                depo_id = depolar.get(tr_normkey(depo))
                if depo_id is None:
                    r.hatalar.append(f"Depo bulunamadı: {depo}")
                else:
                    r.veri["warehouse_id"] = depo_id

            sahiplik = tr_normkey(ham.get("sahiplik", "")).upper().replace(" ", "_")
            if sahiplik:
                if sahiplik not in SAHIPLIK_DURUMLARI:
                    r.hatalar.append(f"Sahiplik {SAHIPLIK_DURUMLARI} içinden olmalı: {sahiplik}")
                else:
                    r.veri["ownership"] = sahiplik

            tarih = clean_cell(ham.get("tarih"))
            if tarih:
                try:
                    r.veri["tarih"] = tarih_coz(tarih)
                except ValueError as exc:
                    r.hatalar.append(f"Tarih: {exc}")

            cid = r.veri.get("device_id")
            if cid is not None:
                if cid in gorulen:
                    r.hatalar.append(f"Dosyada aynı cihaz ikinci kez (ilk satır: {gorulen[cid]})")
                else:
                    gorulen[cid] = sira

            sonuclar.append(r)

        await self._acik_konumlari_isaretle(db, sonuclar)
        return sonuclar

    async def _acik_konumlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        for r in sonuclar:
            if not r.gecerli:
                continue
            acik = await stok_svc.acik_konum(db, r.veri["device_id"])
            if acik is None:
                continue
            aynisi = acik.location_type == r.veri[
                "location_type"
            ] and acik.account_id == r.veri.get("account_id")
            r.cakisma = {
                "tip": "mevcut" if aynisi else "acik_konum",
                "kayit_id": acik.id,
                "aciklama": (
                    "Cihaz zaten bu konumda; değişiklik yok."
                    if aynisi
                    else (
                        f"Cihaz şu an '{acik.location_type}' konumunda "
                        f"({acik.valid_from:%d.%m.%Y}'den beri). Onaylanırsa o dönem "
                        "kapatılır, yenisi açılır."
                    )
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
            if (satir.get("cakisma") or {}).get("tip") == "mevcut":
                continue
            try:
                await stok_svc.konum_ata(
                    db,
                    device_id=int(veri["device_id"]),
                    location_type=veri["location_type"],
                    clock=clock,
                    warehouse_id=int(veri["warehouse_id"]) if veri.get("warehouse_id") else None,
                    account_id=int(veri["account_id"]) if veri.get("account_id") else None,
                    ownership=veri.get("ownership"),
                    an=_an(veri["tarih"]) if veri.get("tarih") else None,
                    notes="İçe aktarma",
                )
            except stok_svc.TransferHatasi as exc:
                raise ValueError(f"Satır {satir['satir_no']}: {exc}") from exc

            if satir.get("cakisma"):
                sayac["guncellendi"] += 1
            else:
                sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac
