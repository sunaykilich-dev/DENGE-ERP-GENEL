"""Serbest metin girdilerin kanonik biçime çevrilmesi.

Bu modül ERP'nin en çok kullanılan yardımcısıdır: Excel içe aktarma, veri göçü,
form doğrulama ve arama hepsi buradan geçer. Kural: bir alan sisteme
GİRERKEN normalize edilir; sorgu tarafında tekrar normalize etmeye gerek
kalmasın diye.

Türkçe tuzağı — `"I".lower()` Python'da `"i"` verir ama Türkçe'de `"ı"`dır;
`"İ".lower()` ise `"i̇"` (birleşik) verir. Mevcut hak ediş uygulamasında bu
hata `"Cihaz Imei No"` başlığının hiç eşleşmemesine ve IMEI sütununun
okunmamasına yol açmıştı. `tr_normkey` bunu açıkça ele alır.
"""

import re
import unicodedata

import phonenumbers

_CLEAN_RE = re.compile(r"[\s\-().]")


def normalize_msisdn(raw: str | int | float, default_region: str = "TR") -> str:
    """Farklı biçimlerdeki numarayı E.164'e çevirir: +905xx…, 905xx…, 05xx…, 5xx…

    Geçersizse Türkçe mesajlı ValueError yükseltir.
    """
    text = _stringify(raw)
    if not text:
        raise ValueError("Numara boş")
    text = _CLEAN_RE.sub("", text)

    if text.startswith("00"):
        text = "+" + text[2:]

    candidates = []
    if text.startswith("+"):
        candidates.append(text)
    else:
        if not text.isdigit():
            raise ValueError(f"Numara sayısal değil: {raw!r}")
        # 905321234567 → +905321234567 ; 05321234567 / 5321234567 → ulusal TR
        if text.startswith("90") and len(text) == 12:
            candidates.append("+" + text)
        candidates.append(text)  # phonenumbers ulusal biçimi default_region ile çözer

    for candidate in candidates:
        try:
            parsed = phonenumbers.parse(candidate, default_region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    raise ValueError(f"Geçersiz telefon numarası: {raw!r}")


def validate_imei(raw: str | int | float) -> str:
    """IMEI: tam 15 hane, sayısal.

    Excel'in sayısal hücreleri (int/tam-değerli float) güvenle çevrilir — 15
    hane 2^53 altında olduğundan hassasiyet kaybolmaz. Ancak CSV'ye zaten
    bilimsel gösterimle yazılmış metin ('8.63071E+14') gerçek veri kaybıdır:
    düzeltilmeye çalışılmaz, net hata verilir (kaynak sütun metin yapılmalı).
    """
    text = _stringify(raw).replace(" ", "")
    if not text:
        raise ValueError("IMEI boş")
    lowered = text.lower()
    if "e+" in lowered or "e-" in lowered or "." in text:
        raise ValueError(f"IMEI sayı biçiminde bozulmuş ({text}) — Excel sütununu metin yapın")
    if not text.isdigit():
        raise ValueError(f"IMEI sayısal değil: {text}")
    if len(text) != 15:
        raise ValueError(f"IMEI 15 hane olmalı ({len(text)} hane): {text}")
    return text


def _stringify(raw: str | int | float) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        # openpyxl sayısal hücreyi float verir; tam sayıysa hanesiz yaz
        return str(int(raw)) if raw.is_integer() else repr(raw)
    return str(raw or "").strip()


# --- Türkçe metin ------------------------------------------------------------

# Türkçe'ye özgü harfler ASCII karşılığına indirgenir; böylece "İZMİR",
# "izmir", "IZMIR" ve "ızmir" aynı anahtara düşer.
_TR_FOLD = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "ı": "i",
        "i": "i",
        "Ş": "s",
        "ş": "s",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
        "Â": "a",
        "â": "a",
        "Î": "i",
        "î": "i",
        "Û": "u",
        "û": "u",
    }
)


def tr_normkey(raw: str | None) -> str:
    """Türkçe-duyarlı karşılaştırma anahtarı.

    Sütun başlığı eşleme, mükerrer tespiti ve arama bunu kullanır.
    `str.lower()` KULLANMAYIN — I/ı/İ/i dönüşümü yanlış olur.

    >>> tr_normkey("Cihaz Imei No")
    'cihaz imei no'
    >>> tr_normkey("İZMİR OTOFOM") == tr_normkey("izmir otofom")
    True
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", str(raw)).translate(_TR_FOLD).lower()
    return re.sub(r"\s+", " ", text).strip()


# Excel'de "veri yok" anlamına gelen dolgu işaretleri. Gerçek dosyalarda
# 752 satırı etkiliyor; boşa çevrilmezse IMEI/şase alanlarına çöp girer.
_DOLGU = {"", "-", "?", "??", "???", "—", "–", "x", "xx", "xxx", "yok", "istenmedi", "bilinmiyor"}


def clean_cell(raw: object) -> str:
    """Hücreyi metne çevirir ve dolgu işaretlerini boşa indirger."""
    if raw is None:
        return ""
    text = _stringify(raw)
    # "…...........", "*****", "......" gibi tek karakterden oluşan dolgular
    if text and set(text) <= set(".…*_-–— "):
        return ""
    return "" if tr_normkey(text) in _DOLGU else text


# --- Kimlik ve mali alanlar ---------------------------------------------------


def normalize_tax_no(raw: object) -> str:
    """VKN (10 hane) veya TCKN (11 hane). Geçersizse ValueError."""
    text = re.sub(r"\D", "", clean_cell(raw))
    if not text:
        raise ValueError("Vergi/TC numarası boş")
    if len(text) not in (10, 11):
        raise ValueError(f"VKN 10, TCKN 11 hane olmalı ({len(text)} hane): {text}")
    return text


_IBAN_RE = re.compile(r"^TR\d{24}$")


def normalize_iban(raw: object) -> str:
    """TR IBAN'ı boşluksuz büyük harfe çevirir ve mod-97 ile doğrular.

    Hak ediş ödeme listesi bu alandan üretilecek; yanlış IBAN parayı yanlış
    hesaba gönderir, bu yüzden biçim kontrolü yetmez, sağlama da yapılır.
    """
    text = re.sub(r"\s", "", clean_cell(raw)).upper()
    if not text:
        raise ValueError("IBAN boş")
    if not _IBAN_RE.match(text):
        raise ValueError(f"IBAN 'TR' + 24 hane olmalı: {text}")
    # mod-97: ilk 4 karakter sona alınır, harfler sayıya çevrilir, %97 == 1
    yeniden = text[4:] + text[:4]
    sayisal = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in yeniden)
    if int(sayisal) % 97 != 1:
        raise ValueError(f"IBAN sağlaması tutmuyor: {text}")
    return text


_PLAKA_RE = re.compile(r"^(0[1-9]|[1-7][0-9]|8[01])[A-Z]{1,3}\d{2,5}$")


def normalize_plate(raw: object) -> str:
    """Plakayı boşluksuz büyük harfe çevirir. Biçim tutmazsa ValueError.

    Türkçe büyük harf dönüşümü kullanılır (i→İ değil, plakada i yok ama
    kullanıcı küçük harf yazabilir).
    """
    text = (
        re.sub(r"[\s\-.]", "", clean_cell(raw))
        .translate(
            str.maketrans(
                {"ı": "I", "i": "I", "İ": "I", "ş": "S", "ğ": "G", "ö": "O", "ç": "C", "ü": "U"}
            )
        )
        .upper()
    )
    if not text:
        raise ValueError("Plaka boş")
    if not _PLAKA_RE.match(text):
        raise ValueError(f"Plaka biçimi tanınmadı: {text}")
    return text


def normalize_iccid(raw: object) -> str:
    """ICCID: yalnız hane sayısı zorlanır (19 veya 20).

    Luhn sağlaması BİLİNÇLİ OLARAK burada zorlanmaz. ITU-T E.118'e göre 20
    haneli ICCID'nin son hanesi sağlama hanesidir, ama operatörler sahada 19
    haneli (sağlamasız) biçimi de basıyor. Katı davranmak gerçek hattı sisteme
    sokmamak demek olurdu — içe aktarma katmanı `iccid_luhn_ok()` ile UYARI
    üretir, kaydı reddetmez.
    """
    text = re.sub(r"\D", "", clean_cell(raw))
    if not text:
        raise ValueError("ICCID boş")
    if len(text) not in (19, 20):
        raise ValueError(f"ICCID 19 veya 20 hane olmalı ({len(text)} hane): {text}")
    return text


def iccid_luhn_ok(iccid: str) -> bool:
    """20 haneli ICCID'nin sağlama hanesi tutuyor mu. 19 hanelide anlamsız →
    True döner (kontrol edilemez, şüphe üretilmez).

    Rakam olmayan değerde HATA ATMAZ, False döner. Göçten gelen kayıtlarda
    ICCID bilinmediğinde yer tutucu yazılıyor (`MSISDN:+90…`); atan bir
    sağlama fonksiyonu yüzünden tek bir böyle satır BÜTÜN hat listesini
    500 yapıyordu. Sağlama sorusu "bu geçerli mi" — geçersiz girdinin
    cevabı "hayır"dır, istisna değil.
    """
    return _luhn_ok(iccid) if len(iccid) == 20 else True


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit():
        return False
    toplam = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        toplam += d
    return toplam % 10 == 0


# --- Sayı ve tarih ------------------------------------------------------------


def parse_decimal(raw: object) -> float:
    """TR ('1.250,50') ve EN ('1,250.50') biçimlerini birlikte çözer."""
    text = clean_cell(raw).replace(" ", "")
    if not text:
        raise ValueError("Sayı boş")
    if isinstance(raw, int | float):
        return float(raw)
    if "," in text and "." in text:
        # Son görülen ayraç ondalıktır
        text = (
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else text.replace(",", "")
        )
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Sayıya çevrilemedi: {raw!r}") from exc
