"""Kütük göçünün hazırlama adımı — SAF fonksiyonlar, hiçbir şey yazmaz (TS-172).

E03-04 / E03-10 kuralları:

- **Tip tekleştirme:** kaynak `X-Ray`/`XRAY Cihazı` → `XRAY`, `Kapı Dedektörü`/
  `Kapı Tipi Metal Dedektörü` → `KAPI_DEDEKTORU` ... Tanınmayan tip
  `DIGER_GUVENLIK` olur ve uyarıya düşer (satır atılmaz).
- **Teslim tarihi metinden DATE:** Excel gün sayısı (`44083` → 2020-09-09) ve
  `GG.AA.YYYY` çözülür; yalnız yıl, geçersiz gün ve serbest metin TARİH
  UYDURMAZ (`delivery_date` NULL, ham metin `delivery_date_raw`'da korunur).
- **Seri no METİN:** girildiği gibi; anahtar `normalize_seri` ile. Seri no'suz
  ve mükerrer seri satırları AKTİF yüklenir, veri kalitesi uyarısına düşer.
- **Müşteri/tesis:** yalnız `HesapEsleyici`'nin kesin yöntemleri; belirsiz ve
  eşleşmeyen satır ham metinle gelir (`customer_name_raw`, `location_raw`),
  bağ sonradan eşleştirme profiliyle kurulur (TS-171).
- `is_active` kaynaktan; `lifecycle_status` kaynakta yoksa `BILINMIYOR`.

Kolon taşması (ör. 60 karakterden uzun marka) satırı KARANTİNAYA alır:
kesmek ham metni değiştirmek olurdu.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from app.migration.kutuk_profil import teslim_deseni
from app.migration.servis_kaynak import GOC_SISTEMI, AdimSonucu, bit, kaynak_ref, metin, tamsayi
from app.models.servis_ekipman import model_anahtari
from app.services.normalize import normalize_seri, tr_normkey
from app.services.teknik_servis.veri_kalitesi import HesapEsleyici

KAYNAK_TABLO = "SecurityDevices"
HEDEF_TABLO = "service_equipment"
BIRIM = "GUVENLIK"

_EXCEL_TABANI = date(1899, 12, 30)
_GG_AA_YYYY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")

YASAM_ESLEME = {
    "kurulu": "KURULU",
    "kuruldu": "KURULU",
    "aktif": "KURULU",
    "kurulum bekliyor": "KURULUM_BEKLIYOR",
    "kurulacak": "KURULUM_BEKLIYOR",
    "devre disi": "DEVRE_DISI",
    "pasif": "DEVRE_DISI",
    "hurda": "HURDA",
}


def ekipman_tipi(ham: str | None) -> str | None:
    """Kaynak tip metni → `EKIPMAN_TIPLERI`; tanınmazsa None."""
    k = tr_normkey(ham).replace("-", " ")
    if not k:
        return None
    if "x ray" in k or "xray" in k or "x isini" in k:
        return "XRAY"
    if "kapi" in k:
        return "KAPI_DEDEKTORU"
    if re.search(r"\bel\b", k) and "dedekt" in k:
        return "EL_DEDEKTORU"
    if "role" in k or "tekrarlay" in k or "repeater" in k:
        return "ROLE_TEKRARLAYICI"
    if "telsiz" in k:
        return "TELSIZ"
    return None


def excel_gun_tarihi(ham: Any) -> date | None:
    """`'44083'` → 2020-09-09; `GG.AA.YYYY` → tarih; diğer her şey None (uydurma yok)."""
    desen = teslim_deseni(ham)
    if desen == "EXCEL_GUN":
        return _EXCEL_TABANI + timedelta(days=int(str(ham).strip()))
    if desen == "GG.AA.YYYY":
        g, a, y = (int(x) for x in _GG_AA_YYYY.match(str(ham).strip()).groups())
        return date(y, a, g)
    return None


def _uzunluk_kontrol(alanlar: dict[str, Any], sinirlar: dict[str, int]) -> str | None:
    for alan, sinir in sinirlar.items():
        deger = alanlar.get(alan)
        if deger is not None and len(deger) > sinir:
            return f"{alan} {sinir} karakteri aşıyor"
    return None


_SINIRLAR = {
    "brand": 60,
    "model": 80,
    "serial_no": 200,
    "customer_name_raw": 200,
    "contact_name_raw": 120,
    "delivery_date_raw": 100,
}


def hazirla(satirlar: list[dict[str, Any]], esleyici: HesapEsleyici) -> AdimSonucu:
    """Kaynak satırları → `service_equipment` INSERT değerleri + karantina + uyarılar."""
    sonuc = AdimSonucu(KAYNAK_TABLO, HEDEF_TABLO, kaynak=len(satirlar))
    seri_gruplari: dict[str, list[str]] = defaultdict(list)
    gorulen: set[str] = set()

    for sira, s in enumerate(satirlar, start=1):
        try:
            kimlik = tamsayi(s.get("SecurityDeviceId"))
        except ValueError:
            kimlik = None
        if kimlik is None:
            sonuc.reddet(f"satır {sira}", "SecurityDeviceId yok — idempotent yüklenemez")
            continue
        ref = kaynak_ref(KAYNAK_TABLO, kimlik)
        if ref in gorulen:
            sonuc.reddet(ref, "dökümde aynı kimlik iki kez")
            continue
        gorulen.add(ref)

        alanlar = {
            "brand": metin(s.get("Brand")),
            "model": metin(s.get("Model")),
            "serial_no": metin(s.get("SerialNo")),
            "customer_name_raw": metin(s.get("CustomerName")),
            "contact_name_raw": metin(s.get("ContactName")),
            "delivery_date_raw": metin(s.get("DeliveryDateText")),
        }
        tasma = _uzunluk_kontrol(alanlar, _SINIRLAR)
        if tasma:
            sonuc.karantinaya(ref, tasma)
            continue

        tip = ekipman_tipi(s.get("DeviceType"))
        if tip is None:
            tip = "DIGER_GUVENLIK"
            sonuc.uyar(ref, "TIP_TANIMSIZ", str(s.get("DeviceType") or ""))

        teslim = excel_gun_tarihi(s.get("DeliveryDateText"))
        desen = teslim_deseni(s.get("DeliveryDateText"))
        if desen not in ("BOS", "EXCEL_GUN", "GG.AA.YYYY"):
            sonuc.uyar(ref, "TESLIM_TARIHI_OKUNAMADI", alanlar["delivery_date_raw"] or "")

        yasam = YASAM_ESLEME.get(tr_normkey(s.get("InstallStatus")), "BILINMIYOR")
        aktif = bit(s.get("IsActive"), varsayilan=True)

        es = esleyici.esle(alanlar["customer_name_raw"], metin(s.get("Location")))
        if not alanlar["customer_name_raw"] and not metin(s.get("Location")):
            sonuc.uyar(ref, "MUSTERISIZ")
        elif es.belirsiz:
            sonuc.uyar(ref, "MUSTERI_BELIRSIZ", ",".join(map(str, es.adaylar)))
        elif es.account_id is None:
            sonuc.uyar(ref, "MUSTERI_ESLESMEDI", alanlar["customer_name_raw"] or "")
        if aktif and es.account_id is not None and es.address_id is None:
            sonuc.uyar(ref, "TESIS_ESLESMEDI", metin(s.get("Location")) or "")

        seri_anahtari = (
            normalize_seri(alanlar["serial_no"]) or None if alanlar["serial_no"] else None
        )
        if seri_anahtari is None:
            sonuc.uyar(ref, "SERISIZ")
        elif aktif:
            seri_gruplari[seri_anahtari].append(ref)

        sonuc.aktarilacak.append(
            {
                "source_system": GOC_SISTEMI,
                "source_ref": ref,
                "birim": BIRIM,
                "equipment_type": tip,
                "brand": alanlar["brand"],
                "brand_key": tr_normkey(alanlar["brand"]) or None,
                "model": alanlar["model"],
                "model_key": model_anahtari(alanlar["model"]),
                "product_raw": metin(s.get("ProductRaw")),
                "serial_no": alanlar["serial_no"],
                "serial_key": seri_anahtari,
                "account_id": es.account_id,
                "customer_name_raw": alanlar["customer_name_raw"],
                "address_id": es.address_id,
                "location_raw": metin(s.get("Location")),
                "contact_name_raw": alanlar["contact_name_raw"],
                "delivery_date": teslim,
                "delivery_date_raw": alanlar["delivery_date_raw"],
                "lifecycle_status": yasam,
                "is_active": aktif,
                "notes": metin(s.get("Notes")),
            }
        )

    for anahtar, refler in seri_gruplari.items():
        if len(refler) > 1:
            for ref in refler:
                sonuc.uyar(ref, "MUKERRER_SERI", anahtar)
    return sonuc
