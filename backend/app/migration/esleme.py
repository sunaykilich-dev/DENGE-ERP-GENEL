"""Küratörlü eşleme tabloları — veri göçünün insan kararları.

Buradaki her satır GERÇEK VERİYE BAKILARAK yazıldı ve doğrulandı. Otomatik
benzerlik araması yalnız ADAY üretir; hangi kayıtların gerçekten aynı olduğuna
insan karar verir. Bunun neden şart olduğunun kanıtı bu dosyanın içinde:
`BALIKESİR KOÇ OTO` ile `BURSA 3D MOBİL` aynı telefon numarasını taşıyor ama
farklı şehirlerde farklı firmalar — telefon tek başına birleştirme ölçütü
olamaz.
"""

# --- Montaj noktası birleştirmeleri: 44 → 39 --------------------------------
# Hepsi normalize edilmiş telefon numarası eşleşmesiyle bulundu ve tek tek
# gözle doğrulandı. Sol taraf silinecek ad, sağ taraf korunacak kanonik ad.
MONTAJ_NOKTASI_BIRLESTIRME: dict[str, str] = {
    "ANTALYA RAMAZAN ÇULLU": "ANTALYA RAMAZAN CULLU",
    "GÜREK OTO ŞENOL GÜREK": "GÜREK OTO- ŞENOL GÜREK",
    "ENS ELEKTRONİK ÖMER GÜL": "İKİTELLİ ENS ELEKTRONİK- ÖMER GÜL",
    "VAN YILMAZ OTO": "VAN YILMAZ OTO ELEKTRİK- ABDÜLAZİZ YILMAZ",
    "İZMİR OTOFOM OTOMOTİV": "İZMİR OTOFOM OTOMOTİV- MUSA BEY",
}

# Aynı telefonu taşıdığı için aday çıkan ama BİRLEŞTİRİLMEYECEK çiftler.
# Betik bunları tekrar tekrar önermesin diye açıkça kayıt altına alınır.
BIRLESTIRILMEYECEK: set[frozenset[str]] = {
    frozenset({"BALIKESİR KOÇ OTO-SELÇUK KOÇ", "BURSA 3D MOBİL"}),
}

# --- Müşteri adına gömülü bayi ----------------------------------------------
# Kaynak veride müşteri adı `BZL OTOMOTİV (GAZİANTEP EVA)` biçiminde; parantez
# içi çoğu zaman satışın yapıldığı bayi. AMA HEPSİ DEĞİL: `ALTINORDU (ORDU
# BELEDİYESİ)` bir açıklama, bayi değil. Bu yüzden liste küratörlü.
BAYI_ISARETI: dict[str, str] = {
    "GAZİANTEP EVA": "GAZİANTEP EVA",
    "GAZİANTP EVA": "GAZİANTEP EVA",  # yazım hatası, aynı bayi
    "GAZİANTEP BAYİ": "GAZİANTEP EVA",
    "DİYARBAKIR BAYİ": "DİYARBAKIR BAYİ",
    "DİYARBAKIR BAYİİ": "DİYARBAKIR BAYİ",
    "İZMİR KARDEŞLER": "İZMİR KARDEŞLER ELEKTRONİK- AYHAN KARABULUT",
    "EVA ARAC TAKİP": "EVA ARAÇ TAKİP SİSTEMLERİ",
    "DELTAPARK- ATLASPARK": "DELTAPARK/ATLASPARK- BURAK POLAT",
    "HOPA ELEKTRONİK": "HOPA ELEKTRONİK- GENCAY GENÇ",
    "VAN BAYİİ": "VAN YILMAZ OTO ELEKTRİK- ABDÜLAZİZ YILMAZ",
    "AYZ VAN": "AYZ VAN",
    "BİZİM FİLO": "BİZİM FİLO",
}

# Parantez içi bayi DEĞİL — müşterinin kendi açıklaması. Ad olduğu gibi kalır,
# karantina üretilmez.
BAYI_DEGIL: set[str] = {
    "ORDU BELEDİYESİ",
    "EDİRNE İL SAĞLIK MÜD.",
    "MURAT ÇÖKELEK",
    "OSMAN ALİ DAĞ",
}

# Belirsiz: ad olduğu gibi kalır AMA karantinaya da düşer — insan baksın.
BAYI_BELIRSIZ: dict[str, str] = {
    "CKR LOJİSTİK SATIŞI": "Satışı yapan taraf belirsiz — bayi mi, müşterinin kendi satışı mı?",
}

# --- Cihaz modeli → ürün ------------------------------------------------------
# 25 serbest metin değeri ~12 ürüne iner. "BLOKAJLI/BLK" bir ÜRÜN DEĞİL,
# montaj özelliğidir (röle ile marş kesme) — iş emrine bayrak olarak yazılır,
# ayrı ürün kartı açılmaz. İşlerin %21,1'i blokajlı.
URUN_ESLEME: dict[str, tuple[str, bool]] = {
    # kaynak metin: (kanonik ürün kodu, blokajli_mi)
    "L300": ("L300", False),
    "L300 BLK.": ("L300", True),
    "L300BLK": ("L300", True),
    "L300BLK.": ("L300", True),
    "L300 GO": ("L300-GO", False),
    "L300 GO BLK.": ("L300-GO", True),
    "GS900": ("GS900", False),
    "GS900 STD": ("GS900", False),
    "GS900STD": ("GS900", False),
    "GS900 BLOKAJLI": ("GS900", True),
    "GS900BLOKAJLI": ("GS900", True),
    "GM900": ("GM900", False),
    "GM900 STD": ("GM900", False),
    "GS12": ("GS12", False),
    "DM20": ("DM20", False),
    "DM900": ("DM900", False),
    "H20P": ("H20P", False),
    "H20P AI": ("H20P-AI", False),
    "TELTONİKA": ("FMB920", False),
    "TELTONİKA FMB920": ("FMB920", False),
    "FMB920": ("FMB920", False),
    "DAHUA CDR8213 KAMERA": ("DAHUA-CDR8213", False),
    "DAHUA HMW3200LP İÇ KAMERA (2 MP)": ("DAHUA-HMW3200LP", False),
    "DAHUA HMW3200LP DIŞ KAMERA (2 MP)": ("DAHUA-HMW3200LP", False),
    "DAHUA HAC-HDW3200GP DIŞ KAMERA (2 MP)": ("DAHUA-HDW3200GP", False),
    "DAHUA HAC-HMW3200P DIŞ KAMERA (2 MP)": ("DAHUA-HMW3200P", False),
}

# Ürün OLMAYAN değerler — cihaz modeli sütununa yanlış girilmiş.
URUN_DEGIL: dict[str, str] = {
    "ARIZA ONARIM": "is_tipi",  # ürün değil, iş emri tipi → ARIZA
    "VF1RJK00670151708": "sase_no",  # şase numarası, yanlış sütuna girilmiş
}

# --- Ürün kartları -------------------------------------------------------------
# Kimlik tipi KRİTİK: DAHUA-HMW3200LP analog (HDCVI) bir ek kamera — modemi
# yok, IMEI'si fiziksel olarak yok, ana cihazın kanalına bağlanır.
URUN_KARTLARI: list[dict] = [
    {
        "code": "L300",
        "name": "Armoli L300",
        "family": "L300",
        "identity_kind": "IMEI",
        "supported_network_tech": ["2G", "4G"],
    },
    {
        "code": "L300-GO",
        "name": "Armoli L300 GO",
        "family": "L300",
        "identity_kind": "IMEI",
        "supported_network_tech": ["4G"],
    },
    {
        "code": "GS900",
        "name": "GS900 / DM900 Araç Takip",
        "family": "GS900",
        "identity_kind": "IMEI",
        "supported_network_tech": ["2G", "4G"],
    },
    {
        "code": "GM900",
        "name": "GM900 Araç Takip",
        "family": "GS900",
        "identity_kind": "IMEI",
        "supported_network_tech": ["2G", "4G"],
    },
    {
        "code": "GS12",
        "name": "GS12 / DM12 Araç Takip",
        "family": "GS12",
        "identity_kind": "IMEI",
        "supported_network_tech": ["2G"],
    },
    {
        "code": "DM20",
        "name": "DM20 Araç Takip",
        "family": "DM20",
        "identity_kind": "IMEI",
        "supported_network_tech": ["4G"],
    },
    {
        "code": "DM900",
        "name": "DM900 Araç Takip",
        "family": "GS900",
        "identity_kind": "IMEI",
        "supported_network_tech": ["2G", "4G"],
    },
    {
        "code": "H20P",
        "name": "H20P / DM20P ADAS+DMS Kamera",
        "family": "H20P",
        "identity_kind": "IMEI",
        "supported_network_tech": ["4G"],
    },
    {
        "code": "H20P-AI",
        "name": "H20P AI ADAS+DMS Kamera",
        "family": "H20P",
        "identity_kind": "IMEI",
        "supported_network_tech": ["4G"],
    },
    {
        "code": "FMB920",
        "name": "Teltonika FMB920",
        "family": "TELTONIKA",
        "identity_kind": "IMEI",
        "supported_network_tech": ["2G", "4G"],
    },
    {
        "code": "DAHUA-CDR8213",
        "name": "Dahua CDR8213 Araç Kamerası",
        "family": "DAHUA",
        "identity_kind": "IMEI",
        "supported_network_tech": ["4G"],
        "channel_count": 2,
    },
    # IMEI'si fiziksel olarak yok — 898 montaj satırının 898'inde boş.
    {
        "code": "DAHUA-HMW3200LP",
        "name": "Dahua HMW3200LP Kamera (2 MP)",
        "family": "DAHUA",
        "identity_kind": "SERI_NO",
        "requires_parent": True,
    },
    # "HAC" = Dahua'nın HDCVI analog serisi. Bu iki modelin de modemi yok;
    # 219 montaj satırının hiçbirinde IMEI geçmiyor.
    {
        "code": "DAHUA-HDW3200GP",
        "name": "Dahua HAC-HDW3200GP Dış Kamera (2 MP)",
        "family": "DAHUA",
        "identity_kind": "SERI_NO",
        "requires_parent": True,
    },
    {
        "code": "DAHUA-HMW3200P",
        "name": "Dahua HAC-HMW3200P Dış Kamera (2 MP)",
        "family": "DAHUA",
        "identity_kind": "SERI_NO",
        "requires_parent": True,
    },
]


def firma_ayristir(ad: str) -> tuple[str, str | None, str | None]:
    """`BZL OTOMOTİV (GAZİANTEP EVA)` → (firma, bayi, karantina_nedeni).

    Parantez içi küratörlü listede yoksa ad OLDUĞU GİBİ kalır ve karantina
    nedeni döner — tahminle bayi uydurmak, bayi bazında ciro raporunu sessizce
    bozardı.
    """
    if "(" not in ad or ")" not in ad:
        return ad.strip(), None, None
    govde, _, kalan = ad.partition("(")
    icerik = kalan.rstrip().rstrip(")").strip()
    govde = govde.strip()
    if icerik in BAYI_ISARETI:
        return govde, BAYI_ISARETI[icerik], None
    if icerik in BAYI_DEGIL:
        return ad.strip(), None, None
    if icerik in BAYI_BELIRSIZ:
        return ad.strip(), None, BAYI_BELIRSIZ[icerik]
    return ad.strip(), None, f"Parantez içi tanınmadı: {icerik!r}"


def montaj_noktasi_kanonik(ad: str) -> str:
    return MONTAJ_NOKTASI_BIRLESTIRME.get(ad.strip(), ad.strip())


def kaynak_ref(tur: str, ad: str) -> str:
    """Göç kimliği: `tur:<16 hane özet>`.

    Ham adı doğrudan kullanmak iki nedenle kırılgandı: uzun unvanlar
    `source_ref` sütununu (64 karakter) taşırıyor ve kaynakta ad düzeltilince
    kayıt kimliğini kaybedip ikinci kez açılıyordu. Özet, `tr_normkey`
    üzerinden alınır; böylece büyük/küçük harf ve Türkçe karakter varyantları
    aynı kimliğe düşer — kaynağın kendisi bu varyantlarla dolu.
    """
    import hashlib

    from app.services.normalize import tr_normkey

    # Kimlik anahtari; imza degil. usedforsecurity=False bunu hem okuyucuya
    # hem denetim araclarina soyluyor.
    ozet = hashlib.sha1(tr_normkey(ad).encode(), usedforsecurity=False).hexdigest()[:16]
    return f"{tur}:{ozet}"
