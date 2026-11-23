"""Servis talep listesi profili: birimlerin Excel'de tuttuğu müşteri talepleri.

Güvenlik birimi talepleri yıllarca "Güvenlik Talep Takip" Excel'inde izledi
(müşteri, lokasyon, araç, personel, talep detayı, durum). Bu profil o listeyi
servis işine çevirir; yazma, eski sistem göçüyle AYNI fonksiyondur
(`servis_goc.is_yaz`): numara, olay kaydı, bekleme ve sonuç kuralları tek yerde.

Kurallar (2026-11-23):
- Müşteri, unvanı birebir ya da tek bir hesabın unvanında geçiyorsa o hesaba
  bağlanır; bulunamazsa ham müşteri metniyle gelir (uyarı) — iş kaybolmaz.
- TAMAMLANDI → KAPATILDI (geçmiş kaydı; İş Emri Onayı kuyruğunu doldurmaz).
  BEKLEMEDE / PLANLANDI / boş → PLANLAMADA (tayin bekler; personel adı ekibe
  otomatik atanmaz, açıklamada durur). DEVAM EDİYOR → ISLEMDE.
  ERTELENDİ → BEKLEMEDE.
- Personel, araç, yetkili, planlanan tarih ve not açıklamaya yazılır.
- Aynı satır ikinci kez yüklenirse yeni iş açılmaz (müşteri + detay + tarih
  + lokasyon özetinden kaynak anahtarı; `uq_so_kaynak`).
"""

import hashlib
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.migration import servis_goc
from app.models import Account, ServiceOrder
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import SERVIS_TURLERI
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz
from app.services.normalize import clean_cell, tr_normkey

KAYNAK_ONEKI = "ExcelTalep:"
DURUM_ESLEME = {
    "tamamlandi": "KAPATILDI",
    "kapatildi": "KAPATILDI",
    "beklemede": "PLANLAMADA",
    "planlandi": "PLANLAMADA",
    "devam ediyor": "ISLEMDE",
    "ertelendi": "BEKLEMEDE",
    "iptal": "IPTAL",
    "iptal edildi": "IPTAL",
    "": "PLANLAMADA",
}
YASAK_TURLER = {"PB", "ATOLYE"}
KONU_SINIRI = ServiceOrder.__table__.c.konu.type.length
MUSTERI_SINIRI = ServiceOrder.__table__.c.customer_name_raw.type.length

SUTUNLAR = (
    Sutun("birim", ("Birim",), zorunlu=True, aciklama=", ".join(BIRIM_KODLARI)),
    Sutun("tur", ("Tür", "Tur"), aciklama="Servis türü kodu (boşsa ARIZA)."),
    Sutun("tarih", ("Talep Tarihi", "Tarih"), aciklama="GG.AA.YYYY"),
    Sutun("musteri", ("Müşteri / Firma", "Müşteri", "Firma"), zorunlu=True),
    Sutun("lokasyon", ("Lokasyon", "Adres")),
    Sutun("detay", ("Talep Detayı", "Talep", "Konu"), zorunlu=True),
    Sutun("durum", ("Durum",), aciklama="Tamamlandı / Beklemede / Planlandı / Devam ediyor."),
    Sutun("plan", ("Planlanan Tarih",), aciklama="Açıklamaya yazılır."),
    Sutun("personel", ("Personel",), aciklama="Açıklamaya yazılır."),
    Sutun("arac", ("Araç", "Arac"), aciklama="Açıklamaya yazılır."),
    Sutun("yetkili", ("Yetkili Kişi", "Yetkili")),
    Sutun("yetkili_iletisim", ("Yetkili İletişim", "Yetkili Iletisim")),
    Sutun("notlar", ("Not / Açıklama", "Not", "Açıklama")),
)


def _gun(deger: str | None) -> date | None:
    if not deger:
        return None
    try:
        return tarih_coz(deger)
    except ValueError:
        return None


def _an(gun: date | None) -> datetime | None:
    return datetime.combine(gun, time(9, 0), tzinfo=UTC) if gun else None


class ServisTalepProfili(Profil):
    kod = "servis_talep"
    ad = "Servis Talepleri"
    aciklama = "Birimin Excel'de tuttuğu müşteri talep listesi → servis işleri."
    sutunlar = SUTUNLAR
    guncelleme_destekli = False

    async def _hesaplar(self, db: AsyncSession) -> list[tuple[int, str]]:
        return list(
            (
                await db.execute(
                    select(Account.id, Account.title_key).where(
                        Account.is_deleted.is_(False), Account.merged_into_id.is_(None)
                    )
                )
            ).all()
        )

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        hesaplar = await self._hesaplar(db)
        birebir = {anahtar: hid for hid, anahtar in hesaplar}
        sonuclar: list[SatirSonucu] = []
        gorulen: set[str] = set()
        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            h = {k: (clean_cell(v) or "") for k, v in ham.items()}

            birim = h.get("birim", "").upper()
            if birim not in BIRIM_KODLARI:
                r.hatalar.append(f"birim tanınmadı: {h.get('birim')}")
            tur = (h.get("tur") or "ARIZA").upper()
            if tur not in SERVIS_TURLERI or tur in YASAK_TURLER:
                r.hatalar.append(f"tür seçilemez: {h.get('tur')}")
            durum_ham = tr_normkey(h.get("durum", ""))
            durum = DURUM_ESLEME.get(durum_ham)
            if durum is None:
                r.hatalar.append(f"durum tanınmadı: {h.get('durum')}")
            musteri, detay = h.get("musteri", ""), h.get("detay", "")
            if not musteri:
                r.hatalar.append("müşteri boş")
            if not detay:
                r.hatalar.append("talep detayı boş")
            talep_gunu = _gun(h.get("tarih"))
            plan_gunu = _gun(h.get("plan"))
            if h.get("tarih") and talep_gunu is None:
                r.uyarilar.append(f"Talep tarihi okunamadı: {h['tarih']}")

            anahtar = tr_normkey(musteri)
            hesap_id = birebir.get(anahtar)
            if hesap_id is None and len(anahtar) >= 4:
                adaylar = [hid for hid, k in hesaplar if anahtar in k]
                hesap_id = adaylar[0] if len(adaylar) == 1 else None
            if hesap_id is None and musteri:
                r.uyarilar.append("Müşteri hesabı bulunamadı; ham adla açılacak")

            ozet = "|".join(
                (anahtar, tr_normkey(detay), tr_normkey(h.get("lokasyon", "")), h.get("tarih", ""))
            )
            ref = KAYNAK_ONEKI + hashlib.sha1(ozet.encode()).hexdigest()[:24]  # noqa: S324
            if ref in gorulen:
                r.hatalar.append("Dosya içinde aynı talep iki kez")
            gorulen.add(ref)

            r.veri.update(
                {
                    "ref": ref,
                    "birim": birim,
                    "tur": tur,
                    "durum": durum,
                    "hesap_id": hesap_id,
                    "talep_gunu": talep_gunu.isoformat() if talep_gunu else None,
                    "plan_gunu": plan_gunu.isoformat() if plan_gunu else None,
                    "eski_durum": h.get("durum") or None,
                    **{k: h.get(k) or None for k in ("musteri", "lokasyon", "detay")},
                    **{
                        k: h.get(k) or None
                        for k in (
                            "plan",
                            "personel",
                            "arac",
                            "yetkili",
                            "yetkili_iletisim",
                            "notlar",
                        )
                    },
                }
            )
            sonuclar.append(r)

        refler = [r.veri["ref"] for r in sonuclar if r.gecerli]
        if refler:
            var = set(
                (
                    await db.scalars(
                        select(ServiceOrder.source_ref).where(
                            ServiceOrder.source_system == servis_goc.GOC_SISTEMI,
                            ServiceOrder.source_ref.in_(refler),
                        )
                    )
                ).all()
            )
            for r in sonuclar:
                if r.veri.get("ref") in var:
                    r.hatalar.append("Bu talep daha önce aktarılmış")
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
        for satir, _ in self.uygulanacaklar(satirlar, kararlar):
            v: dict[str, Any] = satir["veri"]
            ekler: list[str] = []
            for etiket, alan in (
                ("Personel", "personel"),
                ("Araç", "arac"),
                ("Planlanan tarih", "plan"),
                ("Yetkili", "yetkili"),
                ("Yetkili iletişim", "yetkili_iletisim"),
                ("Not", "notlar"),
                ("Excel'deki durum", "eski_durum"),
            ):
                if v.get(alan):
                    ekler.append(f"{etiket}: {v[alan]}")
            konu = servis_goc.sigdir(v["detay"], KONU_SINIRI, "Talep", ekler)
            musteri = servis_goc.sigdir(v["musteri"], MUSTERI_SINIRI, "Müşteri", ekler)
            talep = _an(date.fromisoformat(v["talep_gunu"])) if v.get("talep_gunu") else None
            plan = _an(date.fromisoformat(v["plan_gunu"])) if v.get("plan_gunu") else None
            bitis = plan or talep or clock.now()
            t = servis_goc.IsTaslagi(
                ref=v["ref"],
                eski_no=None,
                birim=v["birim"],
                tur=v["tur"],
                durum=v["durum"],
                kanal="YERINDE" if v["durum"] == "KAPATILDI" else None,
                hesap_id=int(v["hesap_id"]) if v.get("hesap_id") else None,
                musteri_ham=musteri,
                lokasyon_ham=v.get("lokasyon"),
                konu=konu or "",
                aciklama="\n".join(["Excel talep listesinden aktarıldı.", *ekler]),
                acilis=talep or clock.now(),
                tamamlanma=bitis if v["durum"] == "KAPATILDI" else None,
                kapanis=bitis if v["durum"] == "KAPATILDI" else None,
                bekleme_baslangic=talep,
                onceki_durum="PLANLAMADA",
            )
            if await servis_goc.is_yaz(db, t, bag) is not None:
                sayac["eklendi"] += 1
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        return sayac


PROFIL = ServisTalepProfili()
PROFIL_IZNI = "servis.yaz"
