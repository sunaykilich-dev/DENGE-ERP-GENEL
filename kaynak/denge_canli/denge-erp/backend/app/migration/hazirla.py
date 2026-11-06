"""Kaynak veriyi ERP kayıtlarına dönüştürür — HİÇBİR ŞEY YAZMADAN.

Bu modülün tamamı saf fonksiyonlardır: veritabanı bağlantısı almaz, ORM
kullanmaz. Böylece önizleme, altın kayıt testi ve asıl yükleme aynı dönüşüm
kodunu paylaşır ve "önizlemede şunu gösterdi, yüklerken başka şey yaptı"
sınıfı hatalar imkânsız hale gelir.
"""

from app.migration.esleme import (
    URUN_DEGIL,
    URUN_ESLEME,
    URUN_KARTLARI,
    firma_ayristir,
    montaj_noktasi_kanonik,
)
from app.migration.kaynak_hakedis import (
    HakedisKaynagi,
    HazirlikSonucu,
    KarantinaSatiri,
)
from app.services.normalize import normalize_msisdn, tr_normkey

# Türkçe'ye özgü harfler — doğru yazımın işareti.
_TR_HARFLER = set("çğıöşüÇĞİÖŞÜ")


def _yazim_puani(ad: str) -> tuple[int, int]:
    """Aynı firmanın farklı yazımları arasından hangisi tercih edilsin.

    Türkçe karakter içeren yazım daha doğrudur (`KARDEŞLER` > `KARDESLER`);
    eşitlikte daha uzun olan seçilir (kısaltılmış yazımlar bilgi kaybediyor).
    """
    return (sum(ch in _TR_HARFLER for ch in ad), len(ad))


def _telefon(ham: str | None) -> str | None:
    try:
        return normalize_msisdn(ham) if ham else None
    except ValueError:
        return None


def hazirla(kaynak: HakedisKaynagi) -> HazirlikSonucu:
    sonuc = HazirlikSonucu()
    is_sayilari = kaynak.is_sayilari()
    firma_isleri = kaynak.firma_is_sayilari()

    # --- Montaj noktaları: 44 → 39 -------------------------------------------
    ham_noktalar = {r["ad"]: r for r in kaynak.montaj_noktalari()}
    kanonik: dict[str, dict] = {}
    for ad, satir in ham_noktalar.items():
        hedef = montaj_noktasi_kanonik(ad)
        if hedef != ad:
            sonuc.birlestirmeler.append((ad, hedef, is_sayilari.get(ad, 0)))
        kayit = kanonik.setdefault(
            hedef,
            {
                "title": hedef,
                "is_montaj_noktasi": True,
                "phone": None,
                "yetkili": None,
                "km_unit_price": None,
                "is_sayisi": 0,
                "kaynak_adlar": [],
            },
        )
        kayit["kaynak_adlar"].append(ad)
        kayit["is_sayisi"] += is_sayilari.get(ad, 0)
        # Ana kaydın (kanonik adın) bilgileri tercih edilir; yoksa diğerinden alınır.
        if ad == hedef or kayit["phone"] is None:
            kayit["phone"] = _telefon(satir["telefon"]) or kayit["phone"]
            kayit["yetkili"] = (satir["yetkili"] or "").strip() or kayit["yetkili"]
            kayit["km_unit_price"] = satir["kmBirim"] or kayit["km_unit_price"]

        if satir["telefon"] and _telefon(satir["telefon"]) is None:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak="montaj_noktalari",
                    ham_deger=f"{ad} / {satir['telefon']}",
                    neden="Telefon numarası çözümlenemedi",
                    hedef="accounts.phone",
                )
            )
        # Tarifelerin tamamı kaynakta 0.0 — yeni iş girişini bloklar (plan §8).
        if not any((satir["ats"], satir["obdAts"], satir["dashcam"], satir["harici"])):
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak="montaj_noktalari",
                    ham_deger=ad,
                    neden="Tarife tanımsız (hepsi 0) — tarife Excel'i gerekli",
                    hedef="partner_tariffs",
                )
            )
    sonuc.montaj_noktalari = sorted(kanonik.values(), key=lambda k: -k["is_sayisi"])

    # --- Müşteriler ve bayiler ------------------------------------------------
    bayi_adlari: dict[str, int] = {}
    musteriler: dict[str, dict] = {}
    for ad in kaynak.firmalar():
        firma, bayi, karantina_nedeni = firma_ayristir(ad)
        if karantina_nedeni:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak="firmalar",
                    ham_deger=ad,
                    neden=karantina_nedeni,
                    hedef="accounts.parent_dealer_id",
                )
            )
        # Gruplama Türkçe-duyarlı anahtar üzerinden: kaynakta aynı firma hem
        # `KARDEŞLER REFTEKE` hem `KARDESLER REFTEKE` olarak geçiyor. Birleşme
        # doğru ama SESSİZ olmamalı — raporda varyant listesi gösterilir.
        anahtar = tr_normkey(firma)
        kayit = musteriler.setdefault(
            anahtar,
            {"title": firma, "is_musteri": True, "bayi": bayi, "is_sayisi": 0, "kaynak_adlar": []},
        )
        kayit["kaynak_adlar"].append(ad)
        kayit["is_sayisi"] += firma_isleri.get(ad, 0)
        if bayi and not kayit["bayi"]:
            kayit["bayi"] = bayi
        if bayi:
            bayi_adlari[bayi] = bayi_adlari.get(bayi, 0) + 1

    for kayit in musteriler.values():
        # Aynı anahtara düşen FARKLI yazımlar varsa görünür kıl ve DOĞRU
        # yazımı kanonik yap: firma adı teklif ve hak ediş belgelerinde
        # basılacak, "KARDESLER" yerine "KARDEŞLER" görünmeli.
        yazimlar = {firma_ayristir(a)[0] for a in kayit["kaynak_adlar"]}
        if len(yazimlar) > 1:
            kayit["title"] = max(yazimlar, key=_yazim_puani)
            sonuc.varyant_birlesmeleri.append((kayit["title"], sorted(yazimlar)))
    sonuc.musteriler = sorted(musteriler.values(), key=lambda k: -k["is_sayisi"])

    # Bayiler: müşteri adlarından çıkan bayi işaretleri. Bir kısmı zaten montaj
    # noktası olarak var (HOPA ELEKTRONİK gibi) — o zaman AYNI hesaba bayrak
    # eklenir, ikinci kayıt açılmaz. Bayrak setinin varlık sebebi tam olarak bu.
    nokta_adlari = set(kanonik)
    for bayi, musteri_sayisi in sorted(bayi_adlari.items(), key=lambda x: -x[1]):
        sonuc.bayiler.append(
            {
                "title": bayi,
                "is_bayi": True,
                "musteri_sayisi": musteri_sayisi,
                "mevcut_montaj_noktasi": bayi in nokta_adlari,
            }
        )

    # --- Ürünler: 25 → 12 -----------------------------------------------------
    kart_indeks = {k["code"]: k for k in URUN_KARTLARI}
    kullanilan: dict[str, list[str]] = {}
    for ham in kaynak.cihaz_modelleri():
        if ham in URUN_DEGIL:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak="cihazlar",
                    ham_deger=ham,
                    neden=f"Ürün değil ({URUN_DEGIL[ham]}) — cihaz modeli sütununa yanlış girilmiş",
                    hedef="products",
                )
            )
            continue
        eslesme = URUN_ESLEME.get(ham)
        if eslesme is None:
            sonuc.karantina.append(
                KarantinaSatiri(
                    kaynak="cihazlar",
                    ham_deger=ham,
                    neden="Ürün eşlemesi tanımlı değil — esleme.py'ye eklenmeli",
                    hedef="products",
                )
            )
            continue
        kod, _blokajli = eslesme
        kullanilan.setdefault(kod, []).append(ham)

    for kod, ham_adlar in kullanilan.items():
        kart = dict(kart_indeks[kod])
        kart["kaynak_adlar"] = sorted(ham_adlar)
        sonuc.urunler.append(kart)
    sonuc.urunler.sort(key=lambda k: (k.get("family") or "", k["code"]))

    return sonuc


def rapor_metni(sonuc: HazirlikSonucu, ozet: dict[str, int]) -> str:
    satirlar = [
        "VERİ GÖÇÜ ÖNİZLEMESİ — hiçbir şey yazılmadı",
        "=" * 64,
        "",
        f"Kaynak: {ozet['is_sayisi']} iş, {ozet['nokta']} montaj noktası, "
        f"{ozet['firma']} firma, {ozet['cihaz_modeli']} cihaz modeli",
        "",
        f"→ Montaj noktası : {ozet['nokta']} → {len(sonuc.montaj_noktalari)} "
        f"({len(sonuc.birlestirmeler)} birleştirme)",
        f"→ Müşteri        : {len(sonuc.musteriler)}",
        f"→ Bayi           : {len(sonuc.bayiler)}",
        f"→ Ürün           : {ozet['cihaz_modeli']} → {len(sonuc.urunler)}",
        f"→ Karantina      : {len(sonuc.karantina)} satır",
        "",
    ]

    if sonuc.birlestirmeler:
        satirlar += ["BİRLEŞTİRİLECEK MONTAJ NOKTALARI", "-" * 64]
        for eski, yeni, is_sayisi in sonuc.birlestirmeler:
            satirlar.append(f"  {eski}  ({is_sayisi} iş)\n    → {yeni}")
        satirlar.append("")

    if sonuc.varyant_birlesmeleri:
        satirlar += [
            "YAZIM VARYANTI OLARAK BİRLEŞENLER (Türkçe karakter farkı)",
            "-" * 64,
        ]
        for kanonik, yazimlar in sonuc.varyant_birlesmeleri:
            satirlar.append(f"  {kanonik}")
            for y in yazimlar:
                satirlar.append(f"      ← {y}")
        satirlar.append("")

    if sonuc.bayiler:
        satirlar += ["BAYİLER (müşteri adlarından çıkarıldı)", "-" * 64]
        for b in sonuc.bayiler:
            not_ = (
                "  [zaten montaj noktası — aynı hesaba bayrak eklenir]"
                if b["mevcut_montaj_noktasi"]
                else ""
            )
            satirlar.append(f"  {b['title']}  ({b['musteri_sayisi']} müşteri){not_}")
        satirlar.append("")

    satirlar += ["ÜRÜN KARTLARI", "-" * 64]
    for u in sonuc.urunler:
        kimlik = u["identity_kind"]
        isaret = "  ← IMEI'si YOK, seri no ile" if kimlik == "SERI_NO" else ""
        satirlar.append(f"  {u['code']:<18} {u['name']}{isaret}")
        satirlar.append(f"      kaynak: {', '.join(u['kaynak_adlar'])}")
    satirlar.append("")

    if sonuc.karantina:
        satirlar += ["KARANTİNA — elle karar gerektiren satırlar", "-" * 64]
        gruplu: dict[str, list] = {}
        for k in sonuc.karantina:
            gruplu.setdefault(k.neden, []).append(k.ham_deger)
        for neden, degerler in sorted(gruplu.items(), key=lambda x: -len(x[1])):
            satirlar.append(f"  [{len(degerler)}] {neden}")
            for d in degerler[:4]:
                satirlar.append(f"        {d}")
            if len(degerler) > 4:
                satirlar.append(f"        … ve {len(degerler) - 4} tane daha")
        satirlar.append("")

    satirlar.append("Uygulamak için: make goc-uygula")
    return "\n".join(satirlar)
