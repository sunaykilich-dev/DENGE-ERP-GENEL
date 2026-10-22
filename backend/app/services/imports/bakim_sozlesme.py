"""Bakım sözleşmesi göç/teyit profili (TS-173; E04-03, E04-04, E04-D03).

Girdi, `python -m app.migration.bakim_sozlesme` çıktısı olan ayrıştırılmış
teyit Excel'idir (eski `MaintenanceContracts` dökümünden). `SERVIS_YONETICI`
listeyi kontrol eder, eksik dönemi/adedi/müşteriyi doldurur, `Durum`'u AKTIF
yapar ve dosyayı geri yükler. Kurallar:

- **Ekrandan yönetilen kayıt EZİLMEZ.** Kaynak anahtarıyla eşleşen sözleşme
  `TEYIT_BEKLIYOR` dışındaysa satır "korundu" ÇAKIŞMASIDIR ve kullanıcı
  "güncelle" dese bile yazılmaz. `TEYIT_BEKLIYOR` kayıt yalnız açık
  "güncelle" kararıyla güncellenir (çerçevenin varsayılanı atlamak).
- **Kapsam azaltma serbest** (E04-04): teyitte 11 → 8 X-Ray düzeltmesi
  satır SİLMEZ, en büyük sıralı 3 kaleme `valid_to` yazar (hiç yürürlüğe
  girmemiş kalem yumuşak silinir) — `bakim.kapsam_guncelle` kuralının aynısı.
- **Müşteri:** `Hesap Id` yoksa `HesapEsleyici` kesin yöntemleri; BİRDEN ÇOK
  ADAY satırı karantinaya alır (uydurma bağ yok). Eşleşmeyen sözleşme
  hesapsız `TEYIT_BEKLIYOR` kalır.
- **Ücret kolonları yalnız `maliyet.gor` (`sees_cost`)** sahibi yüklediğinde
  yazılır; diğerlerinde YOK SAYILIR ve sonuçta sayılır. Ücret denetim
  kaydına da yazılmaz.
- **Birim kapsamı:** uygulayanın birimi dışındaki satır yazılmaz.
- `source_system='DENGEERP_V1'`, `source_ref='MaintenanceContracts:<Id>'`;
  aynı dosya ikinci kez yüklenirse 0 yeni sözleşme.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Address, MaintenanceContract, User
from app.models.rbac import BIRIM_KODLARI
from app.models.servis_bakim import BAKIM_SOZLESME_DURUMLARI
from app.services import audit
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz, tutar_coz
from app.services.normalize import clean_cell
from app.services.statemachine import BAKIM_SOZLESMESI
from app.services.teknik_servis import bakim, kapsam, numara
from app.services.teknik_servis.veri_kalitesi import hesap_esleyici
from app.services.teknik_servis.yerel_zaman import YEREL

GOC_SISTEMI = "DENGEERP_V1"
KAYNAK_TABLO = "MaintenanceContracts"
_KAYNAK_DESENI = re.compile(rf"^{KAYNAK_TABLO}:\d+$")
_NO_DESENI = re.compile(numara.BAKIM_SOZLESME_DESENI)

UCRET_SUTUNLARI = ("ucret_ziyaret", "ucret_toplam", "ucret_metin")

SUTUNLAR = (
    Sutun(
        "kaynak",
        ("Kaynak Anahtar",),
        zorunlu=True,
        aciklama="MaintenanceContracts:<Id> — göç kimliği, değiştirmeyin.",
    ),
    Sutun("sozlesme_no", ("Sözleşme No",), aciklama="BAKIM-NNNN; eski numara korunur."),
    Sutun("birim", ("Birim",), aciklama="Boşsa GUVENLIK."),
    Sutun("musteri", ("Müşteri",), aciklama="Eski müşteri metni (ham, değişmez)."),
    Sutun("tesis", ("Tesis",), aciklama="Eski tesis metni (ham, değişmez)."),
    Sutun("hesap_id", ("Hesap Id",), aciklama="Sözleşme tarafı cari. Boşsa metinden eşlenir."),
    Sutun("lokasyon_id", ("Lokasyon Id",), aciklama="Tesis (addresses.kind=TESIS)."),
    Sutun("baslangic", ("Başlangıç",), aciklama="GG.AA.YYYY (dahil)."),
    Sutun("bitis", ("Bitiş",), aciklama="GG.AA.YYYY (dahil; sistem ertesi gün 00:00 saklar)."),
    Sutun("frekans", ("Yıllık Frekans",), aciklama="Yılda kaç bakım (1-12)."),
    Sutun("xray", ("X-Ray Adedi",), aciklama="Kapsamdaki X-Ray sayısı."),
    Sutun("kapi", ("Kapı Dedektörü Adedi",), aciklama="Kapsamdaki kapı dedektörü sayısı."),
    Sutun(
        "durum",
        ("Durum",),
        aciklama="TEYIT_BEKLIYOR, AKTIF veya PASIF. AKTIF için hesap, dönem ve frekans şart.",
    ),
    Sutun("teyit_gerekcesi", ("Teyit Gerekçesi",), aciklama="TEYIT_BEKLIYOR iken neden."),
    Sutun("eski_urun", ("Eski Ürün Metni",), aciklama="Bilgi; legacy_products_text."),
    Sutun("eski_donem", ("Eski Dönem Metni",), aciklama="Bilgi; legacy_period_text."),
    Sutun("eski_frekans", ("Eski Frekans Metni",), aciklama="Bilgi; legacy_frequency_text."),
    Sutun("eski_tamamlanan", ("Eski Tamamlanan",), aciklama="Bilgi; legacy_completed_count."),
    Sutun("notlar", ("Notlar",), aciklama="Serbest not."),
    Sutun("ucret_ziyaret", ("Ziyaret Ücreti",), aciklama="Yalnız maliyet yetkisiyle yazılır."),
    Sutun("ucret_toplam", ("Sözleşme Toplamı",), aciklama="Yalnız maliyet yetkisiyle yazılır."),
    Sutun("ucret_metin", ("Eski Ücret Metni",), aciklama="Yalnız maliyet yetkisiyle yazılır."),
)


def _tamsayi(ham: Any) -> int | None:
    metin = clean_cell(ham)
    if not metin:
        return None
    try:
        return int(float(metin.replace(",", ".")))
    except ValueError as exc:
        raise ValueError(f"sayı bekleniyor: {metin}") from exc


def yerel_gece(gun: date) -> datetime:
    """Yerel gün başı (00:00 Europe/Istanbul) → UTC an."""
    return datetime.combine(gun, time(0), tzinfo=YEREL).astimezone(UTC)


class BakimSozlesmeProfili(Profil):
    kod = "bakim_sozlesme"
    ad = "Bakım Sözleşmesi (göç/teyit)"
    aciklama = (
        "Eski sistemden ayrıştırılmış bakım sözleşmeleri. Ekrandan yönetilen sözleşme "
        "korunur; yalnız TEYIT_BEKLIYOR kayıt 'güncelle' kararıyla değişir."
    )
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        esleyici = await hesap_esleyici(db)
        refler = [clean_cell(s.get("kaynak")) for s in satirlar]
        mevcutlar = {
            s.source_ref: s
            for s in (
                await db.scalars(
                    select(MaintenanceContract).where(
                        MaintenanceContract.source_system == GOC_SISTEMI,
                        MaintenanceContract.source_ref.in_([r for r in refler if r]),
                    )
                )
            ).all()
        }
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            v = r.veri
            ref = clean_cell(ham.get("kaynak"))
            if not _KAYNAK_DESENI.match(ref):
                r.hatalar.append(f"Kaynak anahtar '{KAYNAK_TABLO}:<Id>' biçiminde olmalı")
            elif ref in gorulen:
                r.hatalar.append(f"Aynı kaynak anahtar dosyada iki kez (ilk satır: {gorulen[ref]})")
            gorulen.setdefault(ref, sira)
            v["kaynak"] = ref

            no = clean_cell(ham.get("sozlesme_no")).upper()
            if no and not _NO_DESENI.match(no):
                r.hatalar.append(f"Sözleşme no BAKIM-NNNN biçiminde olmalı: {no}")
            v["sozlesme_no"] = no
            birim = clean_cell(ham.get("birim")).upper() or "GUVENLIK"
            if birim not in BIRIM_KODLARI:
                r.hatalar.append(f"Birim tanınmıyor: {birim}")
            v["birim"] = birim
            v["musteri"] = clean_cell(ham.get("musteri"))[:250]
            v["tesis"] = clean_cell(ham.get("tesis"))[:250]

            try:
                bas = tarih_coz(ham["baslangic"]) if clean_cell(ham.get("baslangic")) else None
                bit = tarih_coz(ham["bitis"]) if clean_cell(ham.get("bitis")) else None
                frekans = _tamsayi(ham.get("frekans"))
                xray = _tamsayi(ham.get("xray")) or 0
                kapi = _tamsayi(ham.get("kapi")) or 0
                hesap_id = _tamsayi(ham.get("hesap_id"))
                lokasyon_id = _tamsayi(ham.get("lokasyon_id"))
                tamamlanan = _tamsayi(ham.get("eski_tamamlanan"))
                ucretler = {
                    "ucret_ziyaret": (
                        str(tutar_coz(ham["ucret_ziyaret"]))
                        if clean_cell(ham.get("ucret_ziyaret"))
                        else None
                    ),
                    "ucret_toplam": (
                        str(tutar_coz(ham["ucret_toplam"]))
                        if clean_cell(ham.get("ucret_toplam"))
                        else None
                    ),
                    "ucret_metin": clean_cell(ham.get("ucret_metin")) or None,
                }
            except ValueError as exc:
                r.hatalar.append(str(exc))
                sonuclar.append(r)
                continue
            if bas and bit and bit < bas:
                r.hatalar.append("Bitiş başlangıçtan önce")
            if frekans is not None and not 1 <= frekans <= 12:
                r.hatalar.append("Yıllık frekans 1-12 arasında olmalı")
            for ad, adet in (("X-Ray", xray), ("Kapı dedektörü", kapi)):
                if not 0 <= adet <= bakim.AZAMI_ADET:
                    r.hatalar.append(f"{ad} adedi 0-{bakim.AZAMI_ADET} arasında olmalı")
            v.update(
                {
                    "baslangic": bas.isoformat() if bas else None,
                    "bitis": bit.isoformat() if bit else None,
                    "frekans": frekans,
                    "xray": xray,
                    "kapi": kapi,
                    "eski_tamamlanan": tamamlanan,
                    "eski_urun": clean_cell(ham.get("eski_urun")) or None,
                    "eski_donem": clean_cell(ham.get("eski_donem")) or None,
                    "eski_frekans": clean_cell(ham.get("eski_frekans")) or None,
                    "notlar": clean_cell(ham.get("notlar")) or None,
                    **ucretler,
                }
            )

            # Müşteri: açık kimlik → doğrula; yoksa kesin eşleşme; belirsiz → karantina.
            if hesap_id is not None:
                hesap = await db.get(Account, hesap_id)
                if hesap is None or hesap.is_deleted or not hesap.is_musteri:
                    r.hatalar.append(f"Hesap {hesap_id} yok ya da müşteri değil")
            else:
                es = esleyici.esle(v["musteri"], v["tesis"])
                if es.belirsiz:
                    r.hatalar.append(
                        "Birden çok müşteri adayı (hesap "
                        + ", ".join(map(str, es.adaylar))
                        + ") — Hesap Id yazılarak karar verilmeli"
                    )
                hesap_id = es.account_id
                if lokasyon_id is None:
                    lokasyon_id = es.address_id
                if hesap_id is None and not es.belirsiz:
                    r.uyarilar.append("Müşteri eşleşmedi — sözleşme hesapsız teyit bekleyecek")
            if lokasyon_id is not None and hesap_id is not None:
                adres = await db.get(Address, lokasyon_id)
                if adres is None or adres.kind != "TESIS" or adres.account_id != hesap_id:
                    r.hatalar.append("Lokasyon bu hesabın tesisi değil")
            v["hesap_id"] = hesap_id
            v["lokasyon_id"] = lokasyon_id

            durum = clean_cell(ham.get("durum")).upper() or "TEYIT_BEKLIYOR"
            if durum not in BAKIM_SOZLESME_DURUMLARI or durum == "TASLAK":
                r.hatalar.append("Durum TEYIT_BEKLIYOR, AKTIF ya da PASIF olmalı")
            gerekce = clean_cell(ham.get("teyit_gerekcesi"))
            eksik = [
                ad
                for ad, deger in (
                    ("müşteri", hesap_id),
                    ("başlangıç", bas),
                    ("bitiş", bit),
                    ("frekans", frekans),
                )
                if deger is None
            ]
            if durum == "PASIF" and hesap_id is None:
                # Hesapsız sözleşme yalnız TEYIT_BEKLIYOR olabilir (`ck_mc_musteri_teyit`).
                r.uyarilar.append("Müşterisiz pasif sözleşme teyit bekleyen olarak yazılacak")
                durum = "TEYIT_BEKLIYOR"
                gerekce = (gerekce + "; " if gerekce else "") + "eski sistemde PASIF, müşteri yok"
            if durum == "AKTIF" and eksik:
                r.uyarilar.append(
                    "AKTIF için eksik: " + ", ".join(eksik) + " — teyit bekleyen olarak yazılacak"
                )
                durum = "TEYIT_BEKLIYOR"
                gerekce = gerekce or "Eksik: " + ", ".join(eksik)
            if durum == "TEYIT_BEKLIYOR" and not gerekce:
                gerekce = "Göç: teyit bekliyor" + (
                    " (eksik: " + ", ".join(eksik) + ")" if eksik else ""
                )
            v["durum"] = durum
            v["teyit_gerekcesi"] = gerekce or None

            mevcut = mevcutlar.get(ref)
            if r.gecerli and mevcut is not None:
                if mevcut.status != "TEYIT_BEKLIYOR":
                    r.cakisma = {
                        "tip": "korundu",
                        "kayit_id": mevcut.id,
                        "aciklama": (
                            f"{mevcut.contract_no} ekrandan yönetiliyor ({mevcut.status}); "
                            "korundu, bu satır yazılmaz."
                        ),
                    }
                else:
                    r.cakisma = {
                        "tip": "mevcut",
                        "kayit_id": mevcut.id,
                        "aciklama": (
                            f"{mevcut.contract_no} teyit bekliyor. Güncellenirse dosyadaki "
                            "dönem, frekans, müşteri ve adetler yazılır (adet azalırsa fazla "
                            "kalemler kapanır)."
                        ),
                    }
            elif r.gecerli and no:
                baska = await db.scalar(
                    select(MaintenanceContract.id).where(MaintenanceContract.contract_no == no)
                )
                if baska is not None:
                    r.hatalar.append(f"{no} numarası başka bir sözleşmede kullanılıyor")
            sonuclar.append(r)
        return sonuclar

    async def yaz(
        self,
        db: AsyncSession,
        satirlar: list[dict],
        *,
        clock: Clock,
        user_id: int | None,
        kararlar: dict[int, str],
    ) -> dict[str, Any]:
        sayac: dict[str, Any] = {**self.bos_sayac(), "korundu": 0, "ucret_yok_sayildi": 0}
        kullanici = await db.get(User, user_id) if user_id is not None else None
        maliyet = bool(kullanici is not None and kullanici.has("maliyet.gor"))
        aktor = kullanici if kullanici is not None else SimpleNamespace(id=None)

        for satir in satirlar:
            if (satir.get("cakisma") or {}).get("tip") == "korundu":
                sayac["korundu"] += 1

        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            cakisma = satir.get("cakisma") or {}
            if cakisma.get("tip") == "korundu":
                continue  # ekrandan yönetilen kayıt: karar ne olursa olsun yazılmaz
            v: dict[str, Any] = satir["veri"]
            if kullanici is not None and kapsam.birim_disinda_mi(kullanici, v["birim"]):
                continue

            if cakisma:
                sozlesme = await db.get(
                    MaintenanceContract, cakisma["kayit_id"], with_for_update=True
                )
                if sozlesme is None or sozlesme.status != "TEYIT_BEKLIYOR":
                    sayac["korundu"] += 1
                    continue
                yeni = False
            else:
                no = v.get("sozlesme_no") or await _yeni_no(db)
                sozlesme = MaintenanceContract(
                    contract_no=no,
                    birim=v["birim"],
                    status="TEYIT_BEKLIYOR",
                    teyit_gerekcesi=v.get("teyit_gerekcesi") or "Göç: teyit bekliyor",
                    source_system=GOC_SISTEMI,
                    source_ref=v["kaynak"],
                    created_by=user_id,
                )
                db.add(sozlesme)
                yeni = True

            bas = (
                date.fromisoformat(v["baslangic"])
                if v.get("baslangic") not in (None, "None")
                else None
            )
            bit = date.fromisoformat(v["bitis"]) if v.get("bitis") not in (None, "None") else None
            sozlesme.customer_name_raw = v.get("musteri") or None
            sozlesme.site_name_raw = v.get("tesis") or None
            sozlesme.account_id = _int(v.get("hesap_id"))
            sozlesme.address_id = _int(v.get("lokasyon_id"))
            sozlesme.valid_from = yerel_gece(bas) if bas else None
            sozlesme.valid_to = yerel_gece(bit + timedelta(days=1)) if bit else None
            sozlesme.annual_frequency = _int(v.get("frekans"))
            sozlesme.legacy_products_text = _bos_none(v.get("eski_urun"))
            sozlesme.legacy_period_text = _bos_none(v.get("eski_donem"))
            sozlesme.legacy_frequency_text = _bos_none(v.get("eski_frekans"))
            sozlesme.legacy_completed_count = _int(v.get("eski_tamamlanan"))
            sozlesme.notes = _bos_none(v.get("notlar"))
            sozlesme.updated_by = user_id

            ucret_var = any(_bos_none(v.get(k)) for k in UCRET_SUTUNLARI)
            if ucret_var and not maliyet:
                sayac["ucret_yok_sayildi"] += 1
            elif ucret_var:
                if _bos_none(v.get("ucret_ziyaret")):
                    sozlesme.fee_per_visit = Decimal(v["ucret_ziyaret"])
                if _bos_none(v.get("ucret_toplam")):
                    sozlesme.contract_total = Decimal(v["ucret_toplam"])
                if _bos_none(v.get("ucret_metin")):
                    sozlesme.legacy_fee_text = v["ucret_metin"]

            hedef_durum = v["durum"]
            sozlesme.teyit_gerekcesi = (
                (_bos_none(v.get("teyit_gerekcesi")) or "Göç: teyit bekliyor")
                if hedef_durum == "TEYIT_BEKLIYOR"
                else sozlesme.teyit_gerekcesi
            )
            await db.flush()

            # Kalemler önce: AKTIF'e geçmeden kapsam tarihle yazılsın.
            for k in await bakim.acik_kalemler(db, sozlesme.id):
                if k.valid_from is None and sozlesme.valid_from is not None:
                    k.valid_from = sozlesme.valid_from
            await bakim.kapsam_guncelle(
                db,
                sozlesme,
                {"XRAY": int(v.get("xray") or 0), "KAPI_DEDEKTORU": int(v.get("kapi") or 0)},
                user=aktor,
                clock=clock,
            )
            if hedef_durum != sozlesme.status:
                BAKIM_SOZLESMESI.dogrula(sozlesme.status, hedef_durum)
                sozlesme.status = hedef_durum
                await db.flush()

            await audit.log(
                db,
                "maintenance_contracts",
                "bakim.goc." + ("ekle" if yeni else "teyit"),
                entity_id=sozlesme.id,
                new_value={
                    "no": sozlesme.contract_no,
                    "kaynak": sozlesme.source_ref,
                    "durum": sozlesme.status,
                    "hesap_id": sozlesme.account_id,
                    "kapsam": {"XRAY": v.get("xray"), "KAPI_DEDEKTORU": v.get("kapi")},
                },
                user_id=user_id,
            )
            sayac["eklendi" if yeni else "guncellendi"] += 1

        await db.flush()
        await _sekansi_ilerlet(db)
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


def _int(deger: Any) -> int | None:
    if deger in (None, "", "None"):
        return None
    return int(float(deger))


def _bos_none(deger: Any) -> str | None:
    if deger in (None, "", "None"):
        return None
    return str(deger)


async def _yeni_no(db: AsyncSession) -> str:
    """Eski numarası olmayan sözleşmeye numara: önce sequence korunan en büyük
    göç numarasının ötesine alınır (aynı partide BAKIM-0011 yazılmışken
    sequence 10'daysa çakışmasın), sonra boş numara alınır."""
    await db.flush()
    await _sekansi_ilerlet(db)
    while True:
        no = await numara.bakim_sozlesme_no(db)
        if not await db.scalar(
            select(MaintenanceContract.id).where(MaintenanceContract.contract_no == no)
        ):
            return no


async def _sekansi_ilerlet(db: AsyncSession) -> None:
    """Göçte korunan en büyük `BAKIM-NNNN`'den sonra sequence devam etsin.

    `setval` yalnız İLERİ alır (GREATEST): sequence zaten öndeyse dokunulmaz,
    yeni ekrandan açılan sözleşme göç numarasıyla çakışmaz.
    """
    en_buyuk = await db.scalar(
        text(
            "SELECT max(substring(contract_no FROM '^BAKIM-([0-9]+)$')::bigint) "
            "FROM maintenance_contracts"
        )
    )
    if en_buyuk:
        await db.execute(
            text(
                "SELECT setval('seq_bakim_sozlesme_no', GREATEST(:n, "
                "(SELECT last_value FROM seq_bakim_sozlesme_no)))"
            ),
            {"n": int(en_buyuk)},
        )


PROFIL = BakimSozlesmeProfili()
PROFIL_IZNI = "bakim.yaz"
