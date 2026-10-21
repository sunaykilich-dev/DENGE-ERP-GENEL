"""Hak ediş verisinin iş emri + hak ediş dökümüne açılması.

Kaynağın düz `jobs` tablosunun tek satırı ERP'de BEŞ tabloya dağılır:
hesap, araç, cihaz, iş emri (+kalem) ve hak ediş satırı.

Gruplama: aynı araca aynı gün aynı montaj noktasınca yapılan işler TEK
ziyarettir. Hak ediş verisinde bu pratikte 1:1 (990 ziyaretin 990'ı tek
satır, 9'u iki satır) ama model ziyaret bazlı olduğu için gruplanır. Yol
ücreti ziyaret başına toplanır — tüm birim fiyatlar 10 TL/km olduğu için
toplama kayıpsızdır.

Plakası veya tarihi olmayan 227 kayıt gruplanamaz; her biri kendi iş emrini
alır ve karantinaya yazılır.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from app.migration.esleme import (
    URUN_ESLEME,
    firma_ayristir,
    montaj_noktasi_kanonik,
)
from app.migration.kaynak_hakedis import KarantinaSatiri

# odemeDurumu → (ödenebilirlik, neden)
ODEME_ESLEME: dict[str, tuple[str, str | None]] = {
    "Ödenecek": ("ODENECEK", None),
    # Küçük harfli yazım: canlı uygulama tam eşleşme yaptığı için bu 3 kaydı
    # hak edişe HİÇ almamıştı (3.000 TL). Kullanıcı kararı: bu bir hataydı,
    # ödenecek. ERP'nin Nisan 2026 raporu bu yüzden 3.000 TL fazla çıkar.
    "ödenecek": ("ODENECEK", None),
    "Ödenmeyecek": ("ODENMEYECEK", "DIGER"),
    "ödenmeyecek": ("ODENMEYECEK", "DIGER"),
    "Ödenmeyecek (Kendi Satışları)": ("ODENMEYECEK", "KENDI_SATISI"),
    "Ödenmeyecek (Kendi Satışı)": ("ODENMEYECEK", "KENDI_SATISI"),
    "Ödenmeyecek (Müşteriden Alındı)": ("ODENMEYECEK", "MUSTERIDEN_TAHSIL"),
    "": ("KARAR_BEKLIYOR", None),
}

# islemTipi → (iş emri tipi, form_data ekleri)
ISLEM_ESLEME: dict[str, tuple[str, dict]] = {
    "Yeni Cihaz Montajı": ("MONTAJ", {}),
    "Demonte Cihaz Montajı": ("MONTAJ", {"cihaz_kaynagi": "DEMONTE"}),
    "Blokajlı Yeni Montaj": ("MONTAJ", {"blokajli": True}),
    "Blokajlı Geri Montaj": ("MONTAJ", {"blokajli": True, "geri_montaj": True}),
    "Demontaj": ("SOKUM", {}),
    "Demontaj + Montaj": ("SOK_TAK", {}),
    "": ("MONTAJ", {}),
}

# montajTuru → cihaz rolü (hak ediş iş tipini belirler)
MONTAJ_TURU_ROL = {
    "ATS Montajı": "BIRINCIL_TAKIP",
    "Dashcam Montajı": "KAMERA",
    "Harici Kamera Montajı": "YARDIMCI_KAMERA",
    "OBD'li ATS Montajı": "BIRINCIL_TAKIP",  # kaynakta hiç kullanılmamış
}


@dataclass
class IsEmriTaslagi:
    anahtar: str
    wo_no: str
    tip: str
    form_data: dict
    donem: str
    tarih: date | None
    firma: str
    plaka: str
    sase: str
    ruhsat: str
    km: int | None
    montaj_noktasi: str
    travel_km: float
    travel_unit_price: float | None
    kalemler: list[dict] = field(default_factory=list)


def _tarih(ham: str) -> date | None:
    ham = (ham or "").strip()
    if not ham:
        return None
    try:
        return datetime.strptime(ham[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def tl(deger: float) -> str:
    """Türkçe para biçimi: binlik nokta, ondalık virgül (507.950,00)."""
    return f"{deger:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _sayi(ham) -> float:
    try:
        return float(ham or 0)
    except (TypeError, ValueError):
        return 0.0


def isemirlerini_hazirla(satirlar: list[dict], sonuc) -> list[IsEmriTaslagi]:
    """`jobs` satırlarından iş emri taslakları üretir."""
    gruplar: dict[str, IsEmriTaslagi] = {}

    for j in satirlar:
        tarih = _tarih(j["tarih"])
        plaka = (j["plaka"] or "").strip().upper().replace(" ", "")
        nokta = montaj_noktasi_kanonik(j["montajNoktasi"] or "")

        if tarih is None:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"hakedis:{j['id'][:8]}",
                    ham_deger=f"{j['firma']} / {plaka or '—'}",
                    neden="İş tarihi boş — dönemin son günü varsayıldı",
                    hedef="work_orders.completed_at",
                    seviye="uyari",
                )
            )
        if not plaka:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"hakedis:{j['id'][:8]}",
                    ham_deger=j["firma"] or "—",
                    neden="Plaka boş — araç kaydı oluşmaz, iş emri araçsız kalır",
                    hedef="work_orders.vehicle_id",
                    seviye="uyari",
                )
            )

        # Gruplanabilir mi? Değilse kendi iş emrini alır.
        anahtar = f"{plaka}|{tarih.isoformat()}|{nokta}" if plaka and tarih else f"tek:{j['id']}"

        tip, form_ek = ISLEM_ESLEME.get(j["islemTipi"] or "", ("MONTAJ", {}))
        taslak = gruplar.get(anahtar)
        if taslak is None:
            taslak = IsEmriTaslagi(
                anahtar=anahtar,
                wo_no="",  # yükleme sırasında atanır
                tip=tip,
                form_data=dict(form_ek),
                donem=j["ay"],
                tarih=tarih,
                firma=firma_ayristir(j["firma"] or "")[0],
                plaka=plaka,
                sase=(j["saseNo"] or "").strip().upper(),
                ruhsat=(j["ruhsat"] or "").strip(),
                km=int(_sayi(j["km"])) or None,
                montaj_noktasi=nokta,
                travel_km=0.0,
                travel_unit_price=None,
            )
            gruplar[anahtar] = taslak
        else:
            taslak.form_data.update(form_ek)
            # Ziyarette farklı işlem tipleri varsa en kapsayıcısı seçilir.
            if tip == "SOK_TAK" or (tip == "SOKUM" and taslak.tip == "MONTAJ"):
                taslak.tip = "SOK_TAK" if tip == "SOK_TAK" else taslak.tip

        km = _sayi(j["mobilKm"])
        if km > 0:
            taslak.travel_km += km
            taslak.travel_unit_price = _sayi(j["mobilBirim"]) or 10.0

        odeme = j["odemeDurumu"] or ""
        odenebilirlik, neden = ODEME_ESLEME.get(odeme, ("KARAR_BEKLIYOR", None))
        if odeme not in ODEME_ESLEME:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"hakedis:{j['id'][:8]}",
                    ham_deger=odeme,
                    neden="Ödeme durumu tanınmadı — karar bekliyor olarak girildi",
                    hedef="work_order_items.payability",
                    seviye="engel",
                )
            )
        if odenebilirlik == "KARAR_BEKLIYOR" and odeme == "":
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"hakedis:{j['id'][:8]}",
                    ham_deger=f"{j['firma']} / {_sayi(j['servisBedeli']):.0f} TL",
                    neden="Ödeme durumu boş — dönem kapanışında karar verilmeli",
                    hedef="work_order_items.payability",
                    seviye="uyari",
                )
            )

        urun_kodu = None
        if j["cihazModel"] and j["cihazModel"] in URUN_ESLEME:
            urun_kodu, blokajli = URUN_ESLEME[j["cihazModel"]]
            if blokajli:
                taslak.form_data["blokajli"] = True

        taslak.kalemler.append(
            {
                "kaynak_id": j["id"],
                "imei": (j["imei"] or "").strip(),
                "m2m": (j["m2mHat"] or "").strip(),
                "urun_kodu": urun_kodu,
                "device_role": MONTAJ_TURU_ROL.get(j["montajTuru"] or "", "BIRINCIL_TAKIP"),
                "action": "SOKULDU" if tip == "SOKUM" else "TAKILDI",
                "payability": odenebilirlik,
                "non_payable_reason": neden,
                "unit_price": _sayi(j["servisBedeli"]),
                "notes": (j["aciklama"] or "").strip() or None,
                "fatura_no": (j["ftNo"] or "").strip() or None,
                "fatura_kesildi": (j["faturaKesildi"] or "").strip() or None,
            }
        )

    return sorted(gruplar.values(), key=lambda t: (t.donem, t.tarih or date.min, t.anahtar))


def isemri_raporu(taslaklar: list[IsEmriTaslagi]) -> str:
    odenecek = sum(1 for t in taslaklar for k in t.kalemler if k["payability"] == "ODENECEK")
    odenmeyecek = sum(1 for t in taslaklar for k in t.kalemler if k["payability"] == "ODENMEYECEK")
    bekleyen = sum(1 for t in taslaklar for k in t.kalemler if k["payability"] == "KARAR_BEKLIYOR")
    hizmet = sum(
        k["unit_price"] for t in taslaklar for k in t.kalemler if k["payability"] == "ODENECEK"
    )
    yol = sum(
        t.travel_km * (t.travel_unit_price or 0)
        for t in taslaklar
        if any(k["payability"] == "ODENECEK" for k in t.kalemler)
    )
    donemler = {t.donem for t in taslaklar}
    dokumler = {
        (t.donem, t.montaj_noktasi)
        for t in taslaklar
        if any(k["payability"] == "ODENECEK" for k in t.kalemler)
    }
    return "\n".join(
        [
            "",
            "İŞ EMRİ VE HAK EDİŞ (hak ediş uygulaması)",
            "-" * 64,
            f"  İş emri (ziyaret)  : {len(taslaklar)}",
            f"  Kalem              : {odenecek} ödenecek, {odenmeyecek} ödenmeyecek, "
            f"{bekleyen} karar bekliyor",
            f"  Dönem              : {len(donemler)}",
            f"  Hak ediş dökümü    : {len(dokumler)}",
            f"  Hizmet bedeli      : {tl(hizmet)} TL",
            f"  Yol ücreti         : {tl(yol)} TL",
            f"  GENEL TOPLAM       : {tl(hizmet + yol)} TL",
            "",
        ]
    )
