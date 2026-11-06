"""Araç, cihaz ve hat kayıtlarının hazırlanması (saf fonksiyonlar).

Kimlik çözümü satır satır şöyle işler:

1. 15 haneli geçerli IMEI  → IMEI'li cihaz.
2. IMEI sütununda kamera seri numarası (harf+rakam) → SERİ NO'lu cihaz.
   Kaynakta 155 satır böyle: seri no yanlış sütuna girilmiş.
3. IMEI boş ama M2M hattı başka bir satırda TEK bir IMEI ile görülmüş
   → o IMEI kullanılır, türetim karantinaya "bilgi" olarak yazılır.
4. Ürün IMEI'li ama IMEI hiçbir şekilde bulunamıyor → CİHAZ OLUŞTURULMAZ,
   karantinaya "engel" olarak düşer. Sahte IMEI ÜRETİLMEZ: bugünkü
   `…...........` dolgusunun yerine geçecek sahte bir numara zamanla gerçek
   sanılır ve daha kötüsüdür.
"""

# Ürün kodu → kimlik tipi (URUN_KARTLARI ile tutarlı).
from app.migration.esleme import URUN_ESLEME, URUN_KARTLARI
from app.migration.kaynak_esenyurt import (
    EsenyurtKaynagi,
    EsenyurtSatiri,
    ImeiKurtarma,
    gecerli_imei,
    gecerli_msisdn,
    gecerli_seri_no,
)
from app.migration.kaynak_hakedis import HazirlikSonucu, KarantinaSatiri
from app.services.normalize import normalize_msisdn, normalize_plate

_KIMLIK = {k["code"]: k["identity_kind"] for k in URUN_KARTLARI}


def _plaka(ham: str) -> tuple[str | None, bool]:
    """(plaka, doğrulandı_mı).

    Standart TR plakasına uymayan değerler REDDEDİLMEZ: filoda iş makineleri
    ve demirbaş numarasıyla anılan araçlar var. Ham değer korunur, araç
    `is_plate_verified=False` ile açılır ve düzeltme listesinde görünür.
    """
    if not ham:
        return None, False
    try:
        return normalize_plate(ham), True
    except ValueError:
        temiz = ham.strip().upper()
        return (temiz, False) if temiz else (None, False)


def _sase(ham: str) -> str | None:
    """Şase no 17 karakterse tekil kabul edilir; kısa değerler dolgudur."""
    metin = (ham or "").strip().upper()
    return metin if len(metin) == 17 else None


def esenyurt_envanteri(kaynak: EsenyurtKaynagi, sonuc: HazirlikSonucu) -> None:
    satirlar = kaynak.satirlar()
    kurtarma = ImeiKurtarma.olustur(satirlar)

    araclar: dict[str, dict] = {}
    cihazlar: dict[str, dict] = {}
    hatlar: dict[str, dict] = {}

    for s in satirlar:
        _arac_ekle(s, araclar, sonuc)
        _hat_ekle(s, hatlar, sonuc)
        _cihaz_ekle(s, cihazlar, kurtarma, sonuc)

    _sase_birlestir(araclar, sonuc)
    _eksik_urun_kartlari(cihazlar, sonuc)
    sonuc.araclar = sorted(araclar.values(), key=lambda a: a["plate"])
    sonuc.cihazlar = sorted(cihazlar.values(), key=lambda c: c["kimlik"])
    sonuc.hatlar = sorted(hatlar.values(), key=lambda h: h["iccid_veya_msisdn"])


def _eksik_urun_kartlari(cihazlar: dict, sonuc: HazirlikSonucu) -> None:
    """Envanterde geçen ama ürün listesinde olmayan kartları ekler.

    Ürün listesi hak ediş veritabanından geliyordu; Esenyurt dosyasında ise
    orada hiç geçmeyen iki Dahua dış kamera modeli var. Kart açılmazsa o
    cihazlar sessizce yazılmadan kalırdı — nitekim ilk koşuda 65 seri no'lu
    kamera böyle kaybolmuştu.
    """
    mevcut = {u["code"] for u in sonuc.urunler}
    kart_indeks = {k["code"]: k for k in URUN_KARTLARI}
    for kayit in cihazlar.values():
        kod = kayit["urun_kodu"]
        if kod in mevcut or kod not in kart_indeks:
            continue
        kart = dict(kart_indeks[kod])
        kart["kaynak_adlar"] = ["(Esenyurt montaj geçmişi)"]
        sonuc.urunler.append(kart)
        mevcut.add(kod)
    sonuc.urunler.sort(key=lambda k: (k.get("family") or "", k["code"]))


def _sase_birlestir(araclar: dict, sonuc: HazirlikSonucu) -> None:
    """Aynı şase numarasını taşıyan araç kayıtlarını birleştirir.

    Şase (VIN) aracın en güçlü kimliğidir; aynı VIN iki kayıtta görünüyorsa
    ya plaka değişmiştir ya da aynı araç iki farklı şekilde yazılmıştır.
    Gerçek veride üçü de var: iki iş makinesi hem demirbaş numarasıyla hem
    adıyla ("KAZICI YÜKLEYİCİ-1") girilmiş, bir araçta da plaka değişmiş.

    Kanonik plaka seçimi: doğrulanmış standart plaka > daha çok satırda
    geçen > alfabetik. Diğer yazım notlara yazılır ve karantinaya düşer —
    birleştirme kararı görünür olsun.
    """
    gruplar: dict[str, list[dict]] = {}
    for kayit in araclar.values():
        if kayit["chassis_no"]:
            gruplar.setdefault(kayit["chassis_no"], []).append(kayit)

    for sase, uyeler in gruplar.items():
        if len(uyeler) < 2:
            continue
        kanonik = max(uyeler, key=lambda a: (a["is_plate_verified"], a["satir_adedi"], a["plate"]))
        digerleri = [a for a in uyeler if a is not kanonik]
        kanonik["diger_plakalar"] = sorted(a["plate"] for a in digerleri)
        kanonik["satir_adedi"] += sum(a["satir_adedi"] for a in digerleri)
        for a in digerleri:
            araclar.pop(a["plate"], None)
        sonuc.karantina.append(
            KarantinaSatiri(
                kaynak="esenyurt",
                ham_deger=f"{sase}: {kanonik['plate']} ← {', '.join(kanonik['diger_plakalar'])}",
                neden="Aynı şase birden fazla plakada — tek araçta birleştirildi (plaka değişimi?)",
                hedef="vehicles.chassis_no",
                seviye="uyari",
            )
        )


def _arac_ekle(s: EsenyurtSatiri, araclar: dict, sonuc: HazirlikSonucu) -> None:
    plaka, dogrulandi = _plaka(s.plaka)
    if plaka is None:
        return
    if not dogrulandi:
        sonuc.karantina.append(
            KarantinaSatiri(
                kaynak=f"esenyurt:{s.satir_no}",
                ham_deger=s.plaka,
                neden="Standart plaka değil (iş makinesi/demirbaş?) — araç açıldı, doğrulanmadı",
                hedef="vehicles.is_plate_verified",
                seviye="uyari",
            )
        )

    kayit = araclar.setdefault(
        plaka,
        {
            "plate": plaka,
            "is_plate_verified": dogrulandi,
            "chassis_no": None,
            "registration_no": None,
            "brand": None,
            "model_year": None,
            "musteri_adi": s.firma,
            "diger_plakalar": [],
            "satir_adedi": 0,
        },
    )
    kayit["satir_adedi"] += 1
    kayit["chassis_no"] = kayit["chassis_no"] or _sase(s.sase)
    kayit["registration_no"] = kayit["registration_no"] or (s.ruhsat or None)
    kayit["brand"] = kayit["brand"] or (s.marka_model or None)
    if kayit["model_year"] is None and s.yil.isdigit() and 1950 < int(s.yil) < 2100:
        kayit["model_year"] = int(s.yil)


def _hat_ekle(s: EsenyurtSatiri, hatlar: dict, sonuc: HazirlikSonucu) -> None:
    ham = gecerli_msisdn(s.m2m)
    if not ham:
        if s.m2m:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"esenyurt:{s.satir_no}",
                    ham_deger=s.m2m,
                    neden="M2M alanı telefon numarasına benzemiyor",
                    hedef="sim_cards.msisdn",
                    seviye="engel",
                )
            )
        return
    try:
        msisdn = normalize_msisdn(ham)
    except ValueError as exc:
        sonuc.karantina.append(
            KarantinaSatiri(
                kaynak=f"esenyurt:{s.satir_no}",
                ham_deger=s.m2m,
                neden=f"Numara çözümlenemedi ({exc})",
                hedef="sim_cards.msisdn",
                seviye="engel",
            )
        )
        return

    hatlar.setdefault(
        msisdn,
        {
            # ICCID kaynakta YOK — hat kartı MSISDN ile açılır, ICCID sonra
            # operatörden veya elle tamamlanır.
            "iccid_veya_msisdn": msisdn,
            "msisdn": msisdn,
            "operator": _operator(msisdn),
            "iccid_var": False,
        },
    )


def _operator(msisdn: str) -> str:
    """MSISDN ön ekinden operatör. Kaynakta %98,4 Türk Telekom."""
    yerel = msisdn.removeprefix("+90")
    if yerel.startswith(("501", "505", "506", "507", "551", "552", "553", "554", "555", "559")):
        return "TURK_TELEKOM" if yerel.startswith(("501", "50", "55")) else "DIGER"
    return "DIGER"


def _cihaz_ekle(
    s: EsenyurtSatiri, cihazlar: dict, kurtarma: ImeiKurtarma, sonuc: HazirlikSonucu
) -> None:
    eslesme = URUN_ESLEME.get(s.cihaz_modeli)
    if eslesme is None:
        if s.cihaz_modeli:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"esenyurt:{s.satir_no}",
                    ham_deger=s.cihaz_modeli,
                    neden="Ürün eşlemesi tanımlı değil — esleme.py'ye eklenmeli",
                    hedef="devices.product_id",
                    seviye="engel",
                )
            )
        return
    urun_kodu = eslesme[0]
    kimlik_tipi = _KIMLIK.get(urun_kodu, "IMEI")

    imei = gecerli_imei(s.imei)
    seri = None if imei else gecerli_seri_no(s.imei)

    if kimlik_tipi == "SERI_NO":
        if not seri:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"esenyurt:{s.satir_no}",
                    ham_deger=f"{urun_kodu} / plaka {s.plaka}",
                    neden="Ek kameranın seri numarası kaynakta yok — sahadan toplanmalı",
                    hedef="devices.serial_no",
                    seviye="engel",
                )
            )
            return
        anahtar = f"seri:{seri}"
        cihazlar.setdefault(
            anahtar,
            {
                "kimlik": seri,
                "imei": None,
                "serial_no": seri,
                "identity_kind": "SERI_NO",
                "urun_kodu": urun_kodu,
                "is_identity_provisional": False,
            },
        )
        return

    # IMEI'li ürün
    if not imei:
        kurtarilan = kurtarma.kurtar(s.m2m)
        if kurtarilan:
            imei = kurtarilan
            sonuc.kurtarilan_imei += 1
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"esenyurt:{s.satir_no}",
                    ham_deger=f"{urun_kodu} / hat {s.m2m}",
                    neden=f"IMEI kaynakta boştu, aynı hattın geçtiği satırdan alındı: {imei}",
                    hedef="devices.imei",
                    seviye="bilgi",
                )
            )
        else:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"esenyurt:{s.satir_no}",
                    ham_deger=f"{urun_kodu} / plaka {s.plaka} / hat {s.m2m or '—'}",
                    neden="IMEI yok ve türetilemedi — cihaz kaydı AÇILMADI (sahte IMEI üretilmez)",
                    hedef="devices.imei",
                    seviye="engel",
                )
            )
            return

    anahtar = f"imei:{imei}"
    cihazlar.setdefault(
        anahtar,
        {
            "kimlik": imei,
            "imei": imei,
            "serial_no": None,
            "identity_kind": "IMEI",
            "urun_kodu": urun_kodu,
            "is_identity_provisional": False,
        },
    )


def envanter_raporu(sonuc: HazirlikSonucu) -> str:
    seviyeler: dict[str, int] = {}
    for k in sonuc.karantina:
        seviyeler[k.seviye] = seviyeler.get(k.seviye, 0) + 1

    imeili = sum(1 for c in sonuc.cihazlar if c["identity_kind"] == "IMEI")
    serili = len(sonuc.cihazlar) - imeili
    return "\n".join(
        [
            "",
            "ENVANTER (Esenyurt montaj geçmişi)",
            "-" * 64,
            f"  Araç            : {len(sonuc.araclar)}",
            f"  Cihaz           : {len(sonuc.cihazlar)}  ({imeili} IMEI'li, {serili} seri no'lu)",
            f"  Hat             : {len(sonuc.hatlar)}",
            f"  Kurtarılan IMEI : {sonuc.kurtarilan_imei}  (aynı hattın geçtiği satırdan)",
            "  Karantina       : "
            + ", ".join(f"{adet} {sev}" for sev, adet in sorted(seviyeler.items())),
            "",
        ]
    )


def hakedis_envanteri(isler: list[dict], sonuc: HazirlikSonucu) -> None:
    """Hak ediş kaynağındaki araç, cihaz ve hatları envantere ekler.

    Esenyurt dosyası tek müşterinin montaj geçmişi; hak ediş veritabanı ise
    tüm müşterileri kapsıyor (979 IMEI, 1.006 plaka). İkisi birleşmeden
    cihaz–araç ömür boyu geçmişi eksik kalır — 124 IMEI'nin birden çok
    araçta görüldüğü zincirler yalnız bu kaynakta var.
    """
    araclar = {a["plate"]: a for a in sonuc.araclar}
    cihazlar = {(c["imei"] or c["serial_no"]): c for c in sonuc.cihazlar}
    hatlar = {h["msisdn"]: h for h in sonuc.hatlar}

    for j in isler:
        plaka, dogrulandi = _plaka(j.get("plaka") or "")
        if plaka and plaka not in araclar:
            sase = (j.get("saseNo") or "").strip().upper()
            araclar[plaka] = {
                "plate": plaka,
                "is_plate_verified": dogrulandi,
                "chassis_no": sase if len(sase) == 17 else None,
                "registration_no": (j.get("ruhsat") or "").strip() or None,
                "brand": (j.get("aracModel") or "").strip() or None,
                "model_year": None,
                "musteri_adi": (j.get("firma") or "").strip(),
                "diger_plakalar": [],
                "satir_adedi": 0,
            }
            if not dogrulandi:
                sonuc.karantina.append(
                    KarantinaSatiri(
                        kaynak=f"hakedis:{j['id'][:8]}",
                        ham_deger=j.get("plaka") or "",
                        neden="Standart plaka değil — araç açıldı, doğrulanmadı",
                        hedef="vehicles.is_plate_verified",
                        seviye="uyari",
                    )
                )
        if plaka:
            araclar[plaka]["satir_adedi"] += 1

        imei = gecerli_imei(j.get("imei") or "")
        eslesme = URUN_ESLEME.get(j.get("cihazModel") or "")
        if imei and eslesme and imei not in cihazlar:
            cihazlar[imei] = {
                "kimlik": imei,
                "imei": imei,
                "serial_no": None,
                "identity_kind": "IMEI",
                "urun_kodu": eslesme[0],
                "is_identity_provisional": False,
            }
        elif not imei and eslesme and (j.get("imei") or "").strip():
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak=f"hakedis:{j['id'][:8]}",
                    ham_deger=(j.get("imei") or "")[:40],
                    neden="IMEI 15 haneli sayı değil — cihaz kaydı açılmadı",
                    hedef="devices.imei",
                    seviye="engel",
                )
            )

        ham_hat = gecerli_msisdn(j.get("m2mHat") or "")
        if ham_hat:
            try:
                msisdn = normalize_msisdn(ham_hat)
            except ValueError:
                msisdn = None
            if msisdn and msisdn not in hatlar:
                hatlar[msisdn] = {
                    "iccid_veya_msisdn": msisdn,
                    "msisdn": msisdn,
                    "operator": _operator(msisdn),
                    "iccid_var": False,
                }

    _sase_birlestir(araclar, sonuc)
    _eksik_urun_kartlari(cihazlar, sonuc)
    sonuc.araclar = sorted(araclar.values(), key=lambda a: a["plate"])
    sonuc.cihazlar = sorted(cihazlar.values(), key=lambda c: c["kimlik"])
    sonuc.hatlar = sorted(hatlar.values(), key=lambda h: h["iccid_veya_msisdn"])
