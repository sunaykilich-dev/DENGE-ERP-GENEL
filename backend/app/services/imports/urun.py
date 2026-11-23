"""Ürün kataloğu profili: muhasebe/eski ERP ürün listesinden toplu ürün açılışı.

Her ürün bir şirkete ait olabilir (2026-11-23 kararı: Telekom telsizlerini,
Elektronik güvenlik cihazlarını, Mobilite kendi ürünlerini görür) ya da ORTAK
olur (her şirket görür). Görünürlük kuralı `services/sirket_kapsami.py`'de.

Kimlik politikası türden gelir: seri numaralı cihaz (`CIHAZ_SERILI`) → SERI_NO;
aksesuar, sarf ve hizmet → kimliksiz (YOK, adetle izlenir). IMEI'li takip
cihazı bu profilden açılmaz — onun kaydı cihaz profiliyle ve ürün ekranından.

Anahtar ürün kodudur (`uq_products_code`): sistemde olan kod çakışma verir,
varsayılan ATLA; "güncelle" kararıyla dosyada dolu alanlar yazılır.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Product
from app.models.catalog import OLCU_BIRIMLERI
from app.permissions import SIRKETLER
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.normalize import clean_cell, tr_normkey

# Dosyadaki yazım → (tip, kimlik). Anahtarlar tr_normkey'den geçmiş hâliyle.
TUR_ESLEME: dict[str, tuple[str, str]] = {
    "cihaz": ("CIHAZ_SERILI", "SERI_NO"),
    "cihaz serili": ("CIHAZ_SERILI", "SERI_NO"),
    "cihaz_serili": ("CIHAZ_SERILI", "SERI_NO"),
    "seri nolu cihaz": ("CIHAZ_SERILI", "SERI_NO"),
    "aksesuar": ("AKSESUAR", "YOK"),
    "sarf": ("AKSESUAR", "YOK"),
    "malzeme": ("AKSESUAR", "YOK"),
    "hizmet": ("HIZMET", "YOK"),
}
ORTAK_YAZIMLARI = {"", "ortak", "hepsi", "tum sirketler", "tumu"}

KOLON = Product.__table__.c
SINIRLAR = {alan: KOLON[alan].type.length for alan in ("code", "name", "brand", "supplier_code")}

SUTUNLAR = (
    Sutun("kod", ("Ürün Kodu", "Kod", "Urun Kodu"), zorunlu=True, aciklama="Tekil ürün kodu."),
    Sutun("ad", ("Ürün Adı", "Tanım", "Ad", "Urun Adi"), zorunlu=True, aciklama="Ürün adı."),
    Sutun(
        "tur",
        ("Tür", "Tur"),
        aciklama="Cihaz (seri no'lu) / Aksesuar / Hizmet. Boşsa Aksesuar.",
        ham=True,
    ),
    Sutun(
        "sirket",
        ("Şirket", "Sirket"),
        aciklama="TELEKOM / ELEKTRONIK / MOBILITE ya da Ortak (boş = Ortak).",
        ham=True,
    ),
    Sutun("birim", ("Ölçü Birimi", "Birim"), aciklama=", ".join(OLCU_BIRIMLERI) + "."),
    Sutun("marka", ("Marka",), aciklama="Ör. HYTERA."),
    Sutun(
        "tedarikci_kodu",
        ("ERP Kodu", "Tedarikçi Kodu", "Tedarikci Kodu"),
        aciklama="Eski ERP / tedarikçi kodu (ürün kodundan farklıysa).",
    ),
    Sutun("notlar", ("Not", "Notlar", "Açıklama"), aciklama="Serbest not."),
)


def _sirket_coz(deger: str) -> str | None:
    """'DENGE TELEKOM', 'telekom', 'TELEKOM' → TELEKOM; boş/ortak → None."""
    anahtar = tr_normkey(deger)
    if anahtar in ORTAK_YAZIMLARI:
        return None
    for kod, ad in SIRKETLER.items():
        if anahtar in (tr_normkey(kod), tr_normkey(ad), tr_normkey(ad.replace("DENGE ", ""))):
            return kod
    raise ValueError(f"tanınmayan şirket: {deger} (TELEKOM / ELEKTRONIK / MOBILITE / Ortak)")


class UrunProfili(Profil):
    kod = "urun"
    ad = "Ürünler"
    aciklama = "Ürün kataloğu: cihaz, aksesuar, hizmet; şirkete ait ya da ortak."
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            for alan, kaynak in (("code", "kod"), ("name", "ad")):
                deger = clean_cell(ham.get(kaynak))
                if not deger:
                    r.hatalar.append(f"{kaynak}: boş")
                elif len(deger) > SINIRLAR[alan]:
                    r.hatalar.append(f"{kaynak}: {SINIRLAR[alan]} karakteri aşıyor")
                else:
                    r.veri[alan] = deger
            if r.veri.get("name"):
                r.veri["name_key"] = tr_normkey(r.veri["name"])

            tur = tr_normkey(clean_cell(ham.get("tur")) or "aksesuar")
            if tur in TUR_ESLEME:
                r.veri["type"], r.veri["identity_kind"] = TUR_ESLEME[tur]
            else:
                r.hatalar.append(f"tür tanınmadı: {ham.get('tur')} (Cihaz / Aksesuar / Hizmet)")

            try:
                r.veri["sirket"] = _sirket_coz(clean_cell(ham.get("sirket")) or "")
            except ValueError as exc:
                r.hatalar.append(f"şirket: {exc}")

            birim = (clean_cell(ham.get("birim")) or "").upper()
            if birim in OLCU_BIRIMLERI:
                r.veri["birim"] = birim
            elif birim:
                r.uyarilar.append(f"Ölçü birimi tanınmadı ({birim}); ADET kabul edildi")

            for alan, kaynak in (("brand", "marka"), ("supplier_code", "tedarikci_kodu")):
                deger = clean_cell(ham.get(kaynak))
                if not deger or deger == r.veri.get("code"):
                    continue
                if len(deger) > SINIRLAR[alan]:
                    r.hatalar.append(f"{kaynak}: {SINIRLAR[alan]} karakteri aşıyor")
                else:
                    r.veri[alan] = deger
            notlar = clean_cell(ham.get("notlar"))
            if notlar:
                r.veri["notes"] = notlar

            kod = r.veri.get("code")
            if kod:
                if kod in gorulen:
                    r.hatalar.append(f"Dosya içinde mükerrer ürün kodu (ilk satır: {gorulen[kod]})")
                else:
                    gorulen[kod] = sira
            sonuclar.append(r)

        kodlar = [r.veri["code"] for r in sonuclar if r.gecerli and r.veri.get("code")]
        if kodlar:
            mevcutlar = {
                u.code: u
                for u in (
                    await db.scalars(
                        select(Product).where(
                            Product.code.in_(kodlar), Product.is_deleted.is_(False)
                        )
                    )
                ).all()
            }
            for r in sonuclar:
                mevcut = mevcutlar.get(r.veri.get("code"))
                if mevcut is not None:
                    r.cakisma = {
                        "tip": "mevcut",
                        "kayit_id": mevcut.id,
                        "aciklama": (
                            f"{mevcut.code} — {mevcut.name} zaten kayıtlı. Güncellenirse ad, "
                            "şirket, birim, marka ve not yazılır; tür ve kimlik değişmez."
                        ),
                    }
        return sonuclar

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
            veri: dict[str, Any] = {k: v for k, v in satir["veri"].items() if v is not None}
            if satir.get("cakisma"):
                mevcut = await db.get(Product, satir["cakisma"]["kayit_id"])
                if mevcut is None:
                    continue
                # Tür/kimlik değişmez: cihazların kimlik tipi ürününkine bağlı
                # (uq_products_id_kimlik); değiştirmek mevcut cihazları bozar.
                for alan in ("name", "name_key", "birim", "brand", "supplier_code", "notes"):
                    if alan in veri:
                        setattr(mevcut, alan, veri[alan])
                mevcut.sirket = satir["veri"].get("sirket")
                mevcut.updated_by = user_id
                sayac["guncellendi"] += 1
                continue
            db.add(Product(**veri, created_by=user_id))
            sayac["eklendi"] += 1
        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


PROFIL = UrunProfili()
PROFIL_IZNI = "urun.yaz"
