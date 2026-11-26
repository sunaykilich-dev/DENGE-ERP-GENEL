"""Hesap profili: müşteri, bayi, montaj noktası, tedarikçi.

Hesap tipi tekil bir enum DEĞİL, BAYRAK SETİ (plan §2/6): AUTOLAND hem
müşteri hem montaj noktası — kendi aracına kendi montajını yapan bir
rent-a-car. Tek alanlı bir "tip" sütunu bu gerçeği taşıyamazdı, bu yüzden
dört ayrı evet/hayır sütunu var.

**E-posta ve IBAN burada toplanır.** Canlı veride montaj noktalarının
e-posta kolonu hiç yoktu ve IBAN 1.235 kaydın sıfırında doluydu; hak ediş
dökümünün e-postayla gönderilmesi ve ödeme listesi bu iki alan girilmeden
çalışmıyor (plan §8/2).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import evet_hayir
from app.services.normalize import (
    clean_cell,
    normalize_iban,
    normalize_msisdn,
    normalize_tax_no,
    tr_normkey,
)

SUTUNLAR = (
    Sutun(
        "unvan", ("Unvan", "Ünvan", "Firma", "Firma Adı"), zorunlu=True, aciklama="Ticari unvan."
    ),
    Sutun("musteri_mi", ("Müşteri mi", "Musteri mi"), aciklama="Evet / Hayır.", ham=True),
    Sutun("bayi_mi", ("Bayi mi",), aciklama="Evet / Hayır.", ham=True),
    Sutun(
        "montaj_noktasi_mi",
        ("Montaj Noktası mı", "Montaj Noktasi mi"),
        aciklama="Evet / Hayır. Aynı hesap hem müşteri hem montaj noktası olabilir.",
        ham=True,
    ),
    Sutun("tedarikci_mi", ("Tedarikçi mi", "Tedarikci mi"), aciklama="Evet / Hayır.", ham=True),
    Sutun("vkn", ("VKN", "VKN/TCKN", "Vergi No"), aciklama="10 haneli VKN ya da 11 haneli TCKN."),
    Sutun("vergi_dairesi", ("Vergi Dairesi",), aciklama="Vergi dairesi adı."),
    Sutun(
        "eposta",
        ("E-posta", "Eposta", "Email", "Mail"),
        aciklama="Hak ediş dökümü ve teklif bu adrese gider.",
    ),
    Sutun("telefon", ("Telefon", "Cep", "GSM"), aciklama="E.164'e çevrilir."),
    Sutun("iban", ("IBAN",), aciklama="TR ile başlayan 26 karakter; mod-97 doğrulanır."),
    Sutun("bolge", ("Bölge", "Bolge", "Şehir", "İl"), aciklama="Ör. İstanbul."),
    Sutun("segment", ("Segment",), aciklama="Ör. HYTERA_BAYI."),
    Sutun("notlar", ("Not", "Notlar"), aciklama="Serbest not."),
    # Muhasebe cari kodu (E14-01): yalnız METİN, entegrasyon değil. İsteğe bağlı
    # sütun; olmayan dosyanın davranışı değişmez.
    Sutun(
        "cari_kodu",
        ("Cari Kodu", "Cari Kod", "Muhasebe Kodu"),
        aciklama="Muhasebedeki cari kodu (en çok 40 karakter).",
    ),
)

# `accounts.dis_referans` kolon boyu.
CARI_KODU_UZUNLUK = 40
# Serbest metin alanlarının kolon boyları — modelden okunur (tek kaynak).
METIN_SINIRLARI = {
    alan: Account.__table__.c[alan].type.length for alan in ("tax_office", "region", "segment")
}

BAYRAKLAR = (
    ("musteri_mi", "is_musteri"),
    ("bayi_mi", "is_bayi"),
    ("montaj_noktasi_mi", "is_montaj_noktasi"),
    ("tedarikci_mi", "is_tedarikci"),
)


class HesapProfili(Profil):
    kod = "hesap"
    ad = "Hesaplar"
    aciklama = (
        "Müşteri / bayi / montaj noktası / tedarikçi. Bir hesap birden fazla rol taşıyabilir."
    )
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[str, int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})

            unvan = clean_cell(ham.get("unvan"))
            if not unvan:
                r.hatalar.append("Unvan boş")
            else:
                r.veri["title"] = unvan
                r.veri["title_key"] = tr_normkey(unvan)

            rol_var = False
            for kaynak, alan in BAYRAKLAR:
                try:
                    deger = evet_hayir(ham.get(kaynak), varsayilan=False)
                except ValueError as exc:
                    r.hatalar.append(f"{kaynak}: {exc}")
                    continue
                r.veri[alan] = deger
                rol_var = rol_var or deger
            if not r.hatalar and not rol_var:
                # Rolsüz hesap hiçbir listede görünmez; sessizce kaybolur.
                r.veri["is_musteri"] = True
                r.uyarilar.append("Hiçbir rol işaretlenmemiş; müşteri kabul edildi")

            vkn = clean_cell(ham.get("vkn"))
            if vkn:
                try:
                    r.veri["tax_no"] = normalize_tax_no(vkn)
                except ValueError as exc:
                    r.hatalar.append(f"VKN: {exc}")

            iban = clean_cell(ham.get("iban"))
            if iban:
                try:
                    r.veri["iban"] = normalize_iban(iban)
                except ValueError as exc:
                    r.hatalar.append(f"IBAN: {exc}")

            telefon = clean_cell(ham.get("telefon"))
            if telefon:
                try:
                    r.veri["phone"] = normalize_msisdn(telefon)
                except ValueError as exc:
                    r.uyarilar.append(f"Telefon okunamadı, boş bırakıldı: {exc}")

            eposta = clean_cell(ham.get("eposta"))
            if eposta:
                if "@" not in eposta or " " in eposta:
                    r.hatalar.append(f"E-posta geçersiz: {eposta}")
                else:
                    r.veri["email"] = eposta.lower()

            for alan, kaynak in (
                ("tax_office", "vergi_dairesi"),
                ("region", "bolge"),
                ("segment", "segment"),
                ("notes", "notlar"),
            ):
                deger = clean_cell(ham.get(kaynak))
                if not deger:
                    continue
                # Kolon boyunu aşan değer önizlemede yakalanmalı; yoksa "Uygula"
                # bütün partiyi tek bir veritabanı hatasıyla düşürüyordu.
                sinir = METIN_SINIRLARI.get(alan)
                if sinir and len(deger) > sinir:
                    r.hatalar.append(f"{kaynak}: {sinir} karakteri aşıyor ({len(deger)}): {deger}")
                else:
                    r.veri[alan] = deger

            cari_kodu = clean_cell(ham.get("cari_kodu"))
            if cari_kodu:
                if len(cari_kodu) > CARI_KODU_UZUNLUK:
                    r.hatalar.append(f"Cari kodu {CARI_KODU_UZUNLUK} karakteri aşıyor: {cari_kodu}")
                else:
                    r.veri["dis_referans"] = cari_kodu

            if r.veri.get("is_montaj_noktasi") and not r.veri.get("iban"):
                r.uyarilar.append("Montaj noktasının IBAN'ı yok — ödeme listesine giremez")
            if r.veri.get("is_montaj_noktasi") and not r.veri.get("email"):
                r.uyarilar.append("Montaj noktasının e-postası yok — döküm gönderilemez")

            anahtar = r.veri.get("title_key")
            if anahtar:
                if anahtar in gorulen:
                    r.hatalar.append(f"Dosya içinde mükerrer unvan (ilk satır: {gorulen[anahtar]})")
                else:
                    gorulen[anahtar] = sira

            sonuclar.append(r)

        await self._mevcutlari_isaretle(db, sonuclar)
        return sonuclar

    async def _mevcutlari_isaretle(self, db: AsyncSession, sonuclar: list[SatirSonucu]) -> None:
        anahtarlar = [
            r.veri["title_key"] for r in sonuclar if r.gecerli and r.veri.get("title_key")
        ]
        if not anahtarlar:
            return
        mevcutlar = {
            h.title_key: h
            for h in (
                await db.scalars(
                    select(Account).where(
                        Account.title_key.in_(anahtarlar), Account.is_deleted.is_(False)
                    )
                )
            ).all()
        }
        for r in sonuclar:
            mevcut = mevcutlar.get(r.veri.get("title_key"))
            if mevcut is None:
                continue
            r.cakisma = {
                "tip": "mevcut",
                "kayit_id": mevcut.id,
                "aciklama": (
                    f"{mevcut.title} zaten kayıtlı. Güncellenirse dosyada dolu olan alanlar "
                    "yazılır; roller BİRLEŞTİRİLİR (var olan rol kaldırılmaz)."
                ),
            }

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
            veri: dict[str, Any] = satir["veri"]
            alanlar = _alanlara_cevir(veri)
            cakisma = satir.get("cakisma")

            if cakisma:
                mevcut = await db.get(Account, cakisma["kayit_id"])
                if mevcut is None:
                    continue
                for alan, deger in alanlar.items():
                    if deger is None or alan == "title_key":
                        continue
                    # Roller BİRLEŞTİRİLİR: dosyada "Hayır" yazması, hesabın
                    # sistemdeki rolünü kaldırmak anlamına gelmez.
                    if alan.startswith("is_"):
                        if deger:
                            setattr(mevcut, alan, True)
                        continue
                    setattr(mevcut, alan, deger)
                mevcut.updated_by = user_id
                sayac["guncellendi"] += 1
                continue

            db.add(Account(**alanlar, created_by=user_id))
            sayac["eklendi"] += 1

        await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


def _alanlara_cevir(veri: dict[str, Any]) -> dict[str, Any]:
    alanlar: dict[str, Any] = {}
    for alan in (
        "title",
        "title_key",
        "tax_no",
        "tax_office",
        "email",
        "phone",
        "iban",
        "region",
        "segment",
        "notes",
        "dis_referans",
    ):
        if veri.get(alan):
            alanlar[alan] = veri[alan]
    for _, alan in BAYRAKLAR:
        if veri.get(alan) is not None:
            alanlar[alan] = str(veri[alan]).lower() in ("true", "1")
    return alanlar
