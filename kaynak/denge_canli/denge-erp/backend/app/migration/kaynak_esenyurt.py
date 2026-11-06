"""Esenyurt montaj geçmişi Excel'ini okur.

2.312 satır, 2024-06 … 2026-08, tek müşteri (Esenyurt Belediyesi). Hak ediş
kapsamı DIŞINDA bir iş: dosyada ücret sütunu yok ve tarife betiğinde bu nokta
`ATLA` kümesinde. Dolayısıyla ERP'ye iş emri ve cihaz–araç geçmişi olarak
girer, hak ediş satırı ÜRETMEZ.

Dosyanın tipik üçlüsü aynı plaka + aynı gün:
  L300 (takip, IMEI'li) + CDR8213 (dashcam, IMEI'li, M2M hatlı) +
  HMW3200LP (analog ek kamera, ne IMEI ne hat)
Bu "set montaj"ın ta kendisi ve araç başına çoklu cihazın kanıtı.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.services.normalize import clean_cell

VARSAYILAN_YOL = Path.home() / "Downloads" / "ESENYURT_SON_MONTAJ_.xlsx"
SAYFA = "Genel_Veri"

# Sütun sırası sabit değil; başlık adından eşlenir (dosya yeniden
# düzenlenirse sessizce yanlış sütun okunmasın).
BASLIK_ESLEME = {
    "sira": "sıra",
    "tarih": "montaj tarihi",
    "firma": "firma adı",
    "plaka": "mevcut plaka",
    "marka_model": "araç marka & modeli",
    "yil": "ü.yılı",
    "sase": "şase no",
    "ruhsat": "ruhsat",
    "km": "km",
    "cihaz_modeli": "c.modeli",
    "imei": "cihaz imei no",
    "m2m": "m2m hat no",
    "montaj_noktasi": "montaj noktası",
    "yetkili": "yetkili adı",
    "yapilan_islem": "yapılan işlem",
    "cihaz_tipi": "cihaz tipi (genel)",
    "montaj_turu": "montaj türü (standart)",
}


@dataclass
class EsenyurtSatiri:
    satir_no: int
    tarih: date | None
    firma: str
    plaka: str
    marka_model: str
    yil: str
    sase: str
    ruhsat: str
    km: str
    cihaz_modeli: str
    imei: str
    m2m: str
    montaj_noktasi: str
    yapilan_islem: str
    montaj_turu: str

    @property
    def ziyaret_anahtari(self) -> tuple[str, str]:
        """Aynı araca aynı gün yapılan montajlar TEK ziyarettir (D3'te iş
        emri bu anahtarla gruplanacak)."""
        return (self.plaka, self.tarih.isoformat() if self.tarih else "")


@dataclass
class EsenyurtKaynagi:
    yol: Path = VARSAYILAN_YOL

    def satirlar(self) -> list[EsenyurtSatiri]:
        import openpyxl

        if not self.yol.exists():
            raise FileNotFoundError(f"Esenyurt dosyası bulunamadı: {self.yol}")

        wb = openpyxl.load_workbook(self.yol, read_only=True, data_only=True)
        ws = wb[SAYFA]
        satir_iter = ws.iter_rows(values_only=True)
        basliklar = [_norm(b) for b in next(satir_iter)]
        # Beklenen başlıklar da AYNI normalizasyondan geçer — tek taraflı
        # katlama "Firma Adı" ile "firma adı"yı eşleştiremezdi.
        indeks = {
            alan: basliklar.index(_norm(baslik))
            for alan, baslik in BASLIK_ESLEME.items()
            if _norm(baslik) in basliklar
        }
        eksik = set(BASLIK_ESLEME) - set(indeks)
        if eksik:
            raise ValueError(f"Beklenen sütunlar bulunamadı: {sorted(eksik)}")

        def al(satir, alan: str) -> str:
            return clean_cell(satir[indeks[alan]])

        sonuc: list[EsenyurtSatiri] = []
        for no, satir in enumerate(satir_iter, start=2):
            if not any(satir):
                continue
            sonuc.append(
                EsenyurtSatiri(
                    satir_no=no,
                    tarih=_tarih(satir[indeks["tarih"]]),
                    firma=al(satir, "firma"),
                    plaka=al(satir, "plaka"),
                    marka_model=al(satir, "marka_model"),
                    yil=al(satir, "yil"),
                    sase=al(satir, "sase"),
                    ruhsat=al(satir, "ruhsat"),
                    km=al(satir, "km"),
                    cihaz_modeli=al(satir, "cihaz_modeli"),
                    imei=al(satir, "imei"),
                    m2m=al(satir, "m2m"),
                    montaj_noktasi=al(satir, "montaj_noktasi"),
                    yapilan_islem=al(satir, "yapilan_islem"),
                    montaj_turu=al(satir, "montaj_turu"),
                )
            )
        wb.close()
        return sonuc


def _norm(deger: object) -> str:
    from app.services.normalize import tr_normkey

    return tr_normkey(deger if deger is not None else "")


def _tarih(deger: object) -> date | None:
    if deger is None:
        return None
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    metin = clean_cell(deger)
    for bicim in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin[:10], bicim).date()
        except ValueError:
            continue
    return None


@dataclass
class ImeiKurtarma:
    """M2M hat numarası üzerinden IMEI tamamlama.

    Kaynakta 75 satırda IMEI boş ama M2M hattı dolu. Aynı hat başka bir
    satırda TEK bir IMEI ile görülmüşse eşleştirme güvenlidir. Hat zaman
    içinde iki cihaza takılmışsa (veride böyle hatlar var) tarih bilgisi
    olmadan karar verilemez — o satırlar karantinaya gider.
    """

    hat_imei: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def olustur(cls, satirlar: list[EsenyurtSatiri]) -> "ImeiKurtarma":
        harita: dict[str, set[str]] = {}
        for s in satirlar:
            imei, hat = gecerli_imei(s.imei), gecerli_msisdn(s.m2m)
            if imei and hat:
                harita.setdefault(hat, set()).add(imei)
        return cls(hat_imei=harita)

    def kurtar(self, m2m: str) -> str | None:
        hat = gecerli_msisdn(m2m)
        if not hat:
            return None
        adaylar = self.hat_imei.get(hat, set())
        return next(iter(adaylar)) if len(adaylar) == 1 else None


def gecerli_imei(ham: str) -> str | None:
    metin = re.sub(r"\D", "", ham or "")
    return metin if len(metin) == 15 else None


def gecerli_msisdn(ham: str) -> str | None:
    metin = re.sub(r"\D", "", ham or "")
    return metin if 10 <= len(metin) <= 12 else None


def gecerli_seri_no(ham: str) -> str | None:
    """Kamera seri numarası: harf+rakam karışık, 12-18 karakter."""
    metin = (ham or "").strip().upper()
    if 12 <= len(metin) <= 18 and re.fullmatch(r"[A-Z0-9]+", metin) and not metin.isdigit():
        return metin
    return None
