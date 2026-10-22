"""Servis işi göç karantinası profili (TS-174) — insan kararıyla yeniden yükleme.

`goc-servis-onizleme/uygula` eşlenemeyen eski işleri (tanınmayan durum/tür,
planlı bakım, atölye/kiralama işi, okunamayan tarih) karantinaya alır ve bu
profilin şablonunda bir Excel yazar (`servis_isleri_karantina.xlsx`). Göç
sorumlusu `Tür`, `Durum`, gerekirse `Çözüm Kanalı` ve `Hesap Id`'yi doldurup
dosyayı İçe Aktarma'dan yükler. Yazma, toplu göçle AYNI fonksiyondur
(`servis_goc.is_yaz`): numara, ham müşteri metni, kanal → sonuç ve
idempotentlik kuralları tek yerde.

Kurallar: `PB` ve `ATOLYE` türü seçilemez (bakım dönemi/atölye kaydı göçü
yok; `ck_so_pb_bag`). Zaten aktarılmış kaynak satırı atlanır (0 yeni).
İzin: `sistem.goc` (plan §5.3 adım 5).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.migration import servis_goc
from app.migration.servis_kaynak import GOC_SISTEMI, yerel_an
from app.models import Account, Address, ServiceOrder
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import COZUM_KANALLARI, ONCELIKLER, SERVIS_DURUMLARI, SERVIS_TURLERI
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz
from app.services.normalize import clean_cell
from app.services.teknik_servis.yerel_zaman import YEREL

_REF = re.compile(r"^WorkOrders:\d+$")
_YASAK_TURLER = {"PB": "bakım dönemi bağı kurulamaz", "ATOLYE": "atölye kaydı göçü yok"}

SUTUNLAR = (
    Sutun("ref", ("Kaynak Ref",), zorunlu=True, aciklama="WorkOrders:<Id> — değiştirmeyin."),
    Sutun("eski_no", ("Eski No",), aciklama="Korunur (24 karakteri aşarsa yeni numara)."),
    Sutun("birim", ("Birim",), zorunlu=True, aciklama=", ".join(BIRIM_KODLARI)),
    Sutun("tur", ("Tür",), aciklama="Servis türü kodu (PB/ATOLYE hariç)."),
    Sutun("durum", ("Durum",), aciklama="Servis durumu kodu."),
    Sutun(
        "kanal",
        ("Çözüm Kanalı",),
        aciklama="Kapalı işte sonuç kanalı: " + ", ".join(COZUM_KANALLARI),
    ),
    Sutun("hesap_id", ("Hesap Id",), aciklama="Boşsa ham müşteri metniyle gelir."),
    Sutun("lokasyon_id", ("Lokasyon Id",), aciklama="Hesabın tesisi."),
    Sutun("musteri", ("Müşteri",), aciklama="Ham müşteri metni."),
    Sutun("lokasyon", ("Lokasyon",), aciklama="Ham lokasyon metni."),
    Sutun("konu", ("Konu",), aciklama="Zorunlu (boşsa '(konu yok)')."),
    Sutun("aciklama", ("Açıklama",)),
    Sutun("oncelik", ("Öncelik",), aciklama=", ".join(ONCELIKLER)),
    Sutun(
        "acilis",
        ("Açılış",),
        zorunlu=True,
        aciklama="Eski sistem yerel saati (ISO ya da GG.AA.YYYY).",
    ),
    Sutun("kapanis", ("Kapanış",), aciklama="Kapalı işte kapanış anı."),
    Sutun("seri", ("Seri No",), aciklama="Virgülle ayrılmış seri numaraları."),
    Sutun("neden", ("Karantina Nedeni",), aciklama="Bilgi amaçlı."),
    Sutun("eski_tur", ("Eski Tür",), aciklama="Bilgi amaçlı."),
    Sutun("eski_durum", ("Eski Durum",), aciklama="Bilgi amaçlı."),
)


def an_coz(ham: Any) -> datetime | None:
    """Eski yerel saat (ISO) ya da GG.AA.YYYY (yerel gün başı) → UTC."""
    metin = clean_cell(ham)
    if not metin:
        return None
    try:
        return yerel_an(metin)
    except ValueError:
        gun = tarih_coz(metin)
        return datetime(gun.year, gun.month, gun.day, tzinfo=YEREL).astimezone(UTC)


def _tamsayi(ham: Any) -> int | None:
    metin = clean_cell(ham)
    if not metin:
        return None
    try:
        return int(float(metin))
    except ValueError as exc:
        raise ValueError(f"sayı bekleniyor: {metin}") from exc


class ServisIsleriProfili(Profil):
    kod = "servis_isleri"
    ad = "Servis İşleri (göç karantinası)"
    aciklama = (
        "Eski sistemden eşlenemeyen servis işlerinin insan kararıyla aktarılması. "
        "Karantina Excel'i göç betiğinden alınır; aktarılmış satır yeniden yazılmaz."
    )
    sutunlar = SUTUNLAR
    guncelleme_destekli = False

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        refler = [clean_cell(s.get("ref")) for s in satirlar]
        aktarilmis = set(
            (
                await db.scalars(
                    select(ServiceOrder.source_ref).where(
                        ServiceOrder.source_system == GOC_SISTEMI,
                        ServiceOrder.source_ref.in_([r for r in refler if r]),
                    )
                )
            ).all()
        )
        sonuclar: list[SatirSonucu] = []
        gorulen: set[str] = set()
        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            v = r.veri
            ref = clean_cell(ham.get("ref"))
            if not _REF.match(ref):
                r.hatalar.append("Kaynak ref 'WorkOrders:<Id>' biçiminde olmalı")
            elif ref in gorulen:
                r.hatalar.append("Aynı kaynak ref dosyada iki kez")
            gorulen.add(ref)
            v["ref"] = ref
            birim = clean_cell(ham.get("birim")).upper()
            tur = clean_cell(ham.get("tur")).upper()
            durum = clean_cell(ham.get("durum")).upper()
            kanal = clean_cell(ham.get("kanal")).upper() or None
            oncelik = clean_cell(ham.get("oncelik")).upper() or "NORMAL"
            if birim not in BIRIM_KODLARI:
                r.hatalar.append(f"Birim tanınmıyor: {birim}")
            if tur not in SERVIS_TURLERI:
                r.hatalar.append(f"Tür seçilmeli ({', '.join(SERVIS_TURLERI)})")
            elif tur in _YASAK_TURLER:
                r.hatalar.append(f"{tur} türü göçle açılamaz: {_YASAK_TURLER[tur]}")
            if durum not in SERVIS_DURUMLARI:
                r.hatalar.append("Durum seçilmeli")
            if kanal is not None and kanal not in COZUM_KANALLARI:
                r.hatalar.append(f"Çözüm kanalı tanınmıyor: {kanal}")
            if oncelik not in ONCELIKLER:
                r.hatalar.append(f"Öncelik tanınmıyor: {oncelik}")
            try:
                acilis = an_coz(ham.get("acilis"))
                kapanis = an_coz(ham.get("kapanis"))
                hesap_id = _tamsayi(ham.get("hesap_id"))
                lokasyon_id = _tamsayi(ham.get("lokasyon_id"))
            except ValueError as exc:
                r.hatalar.append(str(exc))
                sonuclar.append(r)
                continue
            if acilis is None:
                r.hatalar.append("Açılış tarihi zorunlu")
            if hesap_id is not None:
                hesap = await db.get(Account, hesap_id)
                if hesap is None or hesap.is_deleted or not hesap.is_musteri:
                    r.hatalar.append(f"Hesap {hesap_id} yok ya da müşteri değil")
            if lokasyon_id is not None:
                adres = await db.get(Address, lokasyon_id)
                if adres is None or adres.kind != "TESIS" or adres.account_id != hesap_id:
                    r.hatalar.append("Lokasyon bu hesabın tesisi değil")
            v.update(
                {
                    "eski_no": clean_cell(ham.get("eski_no")) or None,
                    "birim": birim,
                    "tur": tur,
                    "durum": durum,
                    "kanal": kanal,
                    "oncelik": oncelik,
                    "hesap_id": hesap_id,
                    "lokasyon_id": lokasyon_id,
                    "musteri": clean_cell(ham.get("musteri"))[:250] or None,
                    "lokasyon": clean_cell(ham.get("lokasyon")) or None,
                    "konu": clean_cell(ham.get("konu")) or "(konu yok)",
                    "aciklama": clean_cell(ham.get("aciklama")) or None,
                    "acilis": acilis.isoformat() if acilis else None,
                    "kapanis": kapanis.isoformat() if kapanis else None,
                    "seri": clean_cell(ham.get("seri")) or None,
                }
            )
            if r.gecerli and ref in aktarilmis:
                r.uyarilar.append("Bu iş zaten aktarılmış — atlanacak")
                v["aktarilmis"] = "1"
            if r.gecerli and durum in ("TAMAMLANDI", "KAPATILDI") and kanal is None:
                r.uyarilar.append("Çözüm kanalı yok — sonuç kaydı yazılmayacak")
            sonuclar.append(r)
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
        bag = await servis_goc.yazma_baglami(db, user_id=user_id)
        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            v: dict[str, Any] = satir["veri"]
            if v.get("aktarilmis"):
                continue
            acilis = datetime.fromisoformat(v["acilis"])
            kapanis = datetime.fromisoformat(v["kapanis"]) if v.get("kapanis") else None
            konu = v["konu"]
            ekler: list[str] = []
            konu = servis_goc.sigdir(konu, 200, "Konu", ekler)
            t = servis_goc.IsTaslagi(
                ref=v["ref"],
                eski_no=v.get("eski_no"),
                birim=v["birim"],
                tur=v["tur"],
                durum=v["durum"],
                oncelik=v.get("oncelik") or "NORMAL",
                kanal=v.get("kanal"),
                hesap_id=int(v["hesap_id"]) if v.get("hesap_id") else None,
                adres_id=int(v["lokasyon_id"]) if v.get("lokasyon_id") else None,
                musteri_ham=v.get("musteri"),
                lokasyon_ham=v.get("lokasyon"),
                konu=konu,
                aciklama="\n\n".join([*ekler, v.get("aciklama") or ""]).strip() or None,
                acilis=acilis,
                guncelleme=kapanis or acilis,
                tamamlanma=kapanis or acilis,
                kapanis=kapanis or acilis,
                iptal=kapanis or acilis,
                bekleme_baslangic=acilis,
                onceki_durum="ISLEMDE",
                seriler=[s.strip() for s in (v.get("seri") or "").split(",") if s.strip()],
            )
            if await servis_goc.is_yaz(db, t, bag) is not None:
                sayac["eklendi"] += 1
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        return sayac


PROFIL = ServisIsleriProfili()
PROFIL_IZNI = "sistem.goc"
