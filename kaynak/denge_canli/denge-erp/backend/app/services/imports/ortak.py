"""Profillerin paylaştığı hücre çözümleyicileri.

Excel'den gelen değer hiçbir zaman beklenen tipte değil: tarih bazen
`datetime`, bazen Excel seri numarası, bazen `"15.03.2026"`; tutar bazen
`1250.5`, bazen `"1.250,50"`, bazen `"1,250.50"`. Bu dönüşümleri her
profilde tekrar yazmak, her birinde ayrı bir kenar durumu kaçırmak demekti.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.services.normalize import clean_cell

# Excel tarih serisi 1900-01-00'dan sayar ve 1900'ü artık yıl sanar.
_EXCEL_BASLANGIC = date(1899, 12, 30)

_TARIH_BICIMLERI = (
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d.%m.%y",
    "%d-%m-%Y",
)


def tarih_coz(deger: object) -> date:
    """Excel hücresinden tarih çıkarır."""
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger

    metin = clean_cell(deger)
    if not metin:
        raise ValueError("tarih boş")

    # Excel seri numarası (ör. 46082) — hücre biçimi metne çevrilmişse gelir.
    if metin.isdigit() and 10_000 <= int(metin) <= 60_000:
        return _EXCEL_BASLANGIC + timedelta(days=int(metin))

    metin = metin.split(" ")[0]
    for bicim in _TARIH_BICIMLERI:
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"tarih okunamadı: {metin} (GG.AA.YYYY bekleniyor)")


def tutar_coz(deger: object) -> Decimal:
    """Türkçe ve İngilizce ondalık yazımını çözer.

    `"1.250,50"` → 1250.50, `"1,250.50"` → 1250.50. Belirsiz kalan tek
    durum tek ayraçlı `"1.250"`: binlik ayracı varsayılır, çünkü tarife ve
    ücret listelerinde tam TL çok daha sık.
    """
    if isinstance(deger, int | float | Decimal):
        return Decimal(str(deger))

    metin = clean_cell(deger).replace(" ", "").replace("₺", "").replace("TL", "")
    if not metin:
        raise ValueError("tutar boş")

    nokta, virgul = metin.rfind("."), metin.rfind(",")
    if nokta >= 0 and virgul >= 0:
        # Sonda olan ondalık ayracıdır.
        if virgul > nokta:
            metin = metin.replace(".", "").replace(",", ".")
        else:
            metin = metin.replace(",", "")
    elif virgul >= 0:
        metin = metin.replace(",", ".")
    elif nokta >= 0 and len(metin) - nokta - 1 == 3:
        metin = metin.replace(".", "")

    try:
        return Decimal(metin)
    except InvalidOperation as exc:
        raise ValueError(f"tutar okunamadı: {clean_cell(deger)}") from exc


_EVET = {"evet", "e", "var", "yes", "true", "1", "x"}
_HAYIR = {"hayir", "hayır", "h", "yok", "no", "false", "0", ""}


def evet_hayir(deger: object, *, varsayilan: bool = False) -> bool:
    """Evet/hayır sütununu çözer.

    `clean_cell` "x" ve "yok" gibi işaretleri DOLGU sayıp boşaltır — veri
    sütunlarında doğru, ama evet/hayır sütununda değil: ekip kutuyu çarpıyla
    işaretlediğinde bu "hayır" olarak okunur ve hata sessizce geçerdi.
    Bu yüzden temizlenmiş değer boşalırsa ham metne bakılır.
    """
    temiz = clean_cell(deger)
    metin = (temiz or ("" if deger is None else str(deger))).strip().lower()
    if metin in _EVET:
        return True
    if metin in _HAYIR:
        return varsayilan if metin == "" else False
    raise ValueError(f"'evet' veya 'hayır' bekleniyor: {metin}")
