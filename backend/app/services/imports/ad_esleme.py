"""Ad eşleme kararı profili (TS-170, E13-08) — İK onayı İçe Aktarma'dan.

Girdi, `python -m app.migration.servis_ad_esleme oner` çıktısı olan öneri
Excel'idir: her satır eski sistemdeki bir ad yazımı (kaynak alan + ad) ve
sistemin önerisi. İK `Karar` sütununu doldurup dosyayı geri yükler:

- `E` / `ONAY` → ONAYLANDI. Hedef kişi sırasıyla `Hedef Kullanıcı Id`,
  `Hedef Sicil`, yoksa `Önerilen Kullanıcı Id`'dir; kişi yoksa satır HATA.
- `H` / `RED` → REDDEDILDI (öneri yanlış, kişi bilinmiyor).
- `ESLESMEDI` → ESLESMEDI (kişi sistemde yok; kayıtlar adla kalır).
- Boş karar → satır atlanır (uyarı). Tahmin yazılmaz.

Daha önce farklı karar verilmiş satır ÇAKIŞMA'dır (varsayılan atla): onaylı
eşlemeyi sessizce değiştirmek, göçte işlenmiş kişi-saatleri başka kişiye
taşımak demekti. Aynı karar ikinci kez yüklenirse 0 satır yazılır.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import PersonnelNameMap, User
from app.services import audit
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.normalize import clean_cell, tr_normkey
from app.services.teknik_servis import ad_esleme as svc

SUTUNLAR = (
    Sutun(
        "kaynak_alan",
        ("Kaynak Alan",),
        zorunlu=True,
        aciklama="Eski sistemdeki alan: " + ", ".join(svc.KAYNAK_ALANLARI),
    ),
    Sutun("kaynak_ad", ("Kaynak Ad", "Eski Ad"), zorunlu=True, aciklama="Eski sistemdeki ad."),
    Sutun("normal_ad", ("Normal Ad",), aciklama="Bilgi amaçlı; sistem yeniden hesaplar."),
    Sutun("kayit_sayisi", ("Kayıt Sayısı",), aciklama="Bilgi amaçlı."),
    Sutun("onerilen_id", ("Önerilen Kullanıcı Id",), aciklama="Sistem önerisi."),
    Sutun("onerilen_ad", ("Önerilen Kullanıcı",), aciklama="Bilgi amaçlı."),
    Sutun(
        "karar",
        ("Karar", "Onay (E/H)"),
        ham=True,
        aciklama="E/ONAY = onayla, H/RED = reddet, ESLESMEDI = kişi sistemde yok. Boş = atla.",
    ),
    Sutun("hedef_id", ("Hedef Kullanıcı Id",), aciklama="Öneriden farklı kişi seçilecekse."),
    Sutun("hedef_sicil", ("Hedef Sicil",), aciklama="Kullanıcı Id yerine sicil no."),
)

_KARARLAR = {
    "e": "ONAYLANDI",
    "evet": "ONAYLANDI",
    "onay": "ONAYLANDI",
    "onaylandi": "ONAYLANDI",
    "h": "REDDEDILDI",
    "hayir": "REDDEDILDI",
    "red": "REDDEDILDI",
    "reddedildi": "REDDEDILDI",
    "eslesmedi": "ESLESMEDI",
}


def _tamsayi(ham: Any) -> int | None:
    metin = clean_cell(ham)
    if not metin:
        return None
    try:
        return int(float(metin))
    except ValueError as exc:
        raise ValueError(f"sayı bekleniyor: {metin}") from exc


class AdEslemeProfili(Profil):
    kod = "ad_esleme"
    ad = "Personel Ad Eşleme (göç)"
    aciklama = (
        "Eski sistemdeki ad yazımlarının personele bağlanması. Öneri Excel'i "
        "göç betiğinden alınır; yalnız Karar sütunu dolu satırlar yazılır."
    )
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        gorulen: dict[tuple[str, str], int] = {}
        siciller: dict[str, int] = {
            s: uid
            for uid, s in (
                await db.execute(select(User.id, User.sicil_no).where(User.sicil_no.is_not(None)))
            ).all()
        }
        kullanicilar = set((await db.scalars(select(User.id))).all())
        mevcut = {
            (m.kaynak_alan, m.normal_ad): m
            for m in (
                await db.scalars(
                    select(PersonnelNameMap).where(
                        PersonnelNameMap.kaynak_sistem == svc.KAYNAK_SISTEM
                    )
                )
            ).all()
        }

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            alan = clean_cell(ham.get("kaynak_alan"))
            ad = clean_cell(ham.get("kaynak_ad"))
            if alan not in svc.KAYNAK_ALANLARI:
                r.hatalar.append(f"Kaynak alan tanınmıyor: {alan}")
            if not ad:
                r.hatalar.append("Kaynak ad boş")
            norm = svc.normal_ad(ad)
            r.veri.update({"kaynak_alan": alan, "kaynak_ad": ad[:150], "normal_ad": norm})

            karar_ham = tr_normkey((ham.get("karar") or "").strip())
            if not karar_ham:
                r.uyarilar.append("Karar boş — satır atlanacak")
                r.veri["karar"] = ""
                sonuclar.append(r)
                continue
            karar = _KARARLAR.get(karar_ham.replace(" ", ""))
            if karar is None:
                r.hatalar.append(f"Karar tanınmıyor: {ham.get('karar')} (E, H veya ESLESMEDI)")
                sonuclar.append(r)
                continue
            r.veri["karar"] = karar

            if karar == "ONAYLANDI":
                try:
                    hedef = _tamsayi(ham.get("hedef_id"))
                    if hedef is None and clean_cell(ham.get("hedef_sicil")):
                        sicil = clean_cell(ham.get("hedef_sicil"))
                        hedef = siciller.get(sicil)
                        if hedef is None:
                            r.hatalar.append(f"Sicil bulunamadı: {sicil}")
                    if hedef is None and not r.hatalar:
                        hedef = _tamsayi(ham.get("onerilen_id"))
                except ValueError as exc:
                    r.hatalar.append(str(exc))
                    hedef = None
                if hedef is None and not r.hatalar:
                    r.hatalar.append("Onaylanan satırda hedef kullanıcı yok")
                elif hedef is not None and hedef not in kullanicilar:
                    r.hatalar.append(f"Kullanıcı bulunamadı: {hedef}")
                r.veri["hedef_id"] = hedef

            anahtar = (alan, norm)
            if r.gecerli:
                if anahtar in gorulen:
                    r.hatalar.append(
                        f"Dosya içinde aynı ad iki kez (ilk satır: {gorulen[anahtar]})"
                    )
                else:
                    gorulen[anahtar] = sira

            onceki = mevcut.get(anahtar)
            if r.gecerli and onceki is not None and onceki.durum != "ONERI":
                ayni = onceki.durum == karar and (
                    karar != "ONAYLANDI" or onceki.onaylanan_user_id == r.veri.get("hedef_id")
                )
                if ayni:
                    r.uyarilar.append("Aynı karar zaten kayıtlı — değişiklik yok")
                    r.veri["degisiklik_yok"] = "1"
                else:
                    r.cakisma = {
                        "tip": "karar_degisiyor",
                        "kayit_id": onceki.id,
                        "aciklama": (
                            f"Bu ad için önceki karar {onceki.durum}. Güncellenirse karar "
                            "değişir; göç tablolarına işlenmiş satırlar kendiliğinden geri "
                            "alınmaz."
                        ),
                    }
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
        mevcut = {
            (m.kaynak_alan, m.normal_ad): m
            for m in (
                await db.scalars(
                    select(PersonnelNameMap).where(
                        PersonnelNameMap.kaynak_sistem == svc.KAYNAK_SISTEM
                    )
                )
            ).all()
        }
        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            veri: dict[str, Any] = satir["veri"]
            karar = veri.get("karar")
            if not karar or veri.get("degisiklik_yok"):
                continue
            hedef = veri.get("hedef_id")
            hedef_id = int(hedef) if hedef not in (None, "", "None") else None
            anahtar = (veri["kaynak_alan"], veri["normal_ad"])
            kayit = mevcut.get(anahtar)
            yeni = kayit is None
            if yeni:
                kayit = PersonnelNameMap(
                    kaynak_sistem=svc.KAYNAK_SISTEM,
                    kaynak_alan=veri["kaynak_alan"],
                    kaynak_ad=veri["kaynak_ad"],
                    normal_ad=veri["normal_ad"],
                    kayit_sayisi=0,
                    created_by=user_id,
                )
                db.add(kayit)
                mevcut[anahtar] = kayit
            eski = {"durum": kayit.durum, "onaylanan_user_id": kayit.onaylanan_user_id}
            kayit.durum = karar
            kayit.onaylanan_user_id = hedef_id if karar == "ONAYLANDI" else None
            kayit.onaylayan_id = user_id
            kayit.onay_at = clock.now()
            kayit.updated_by = user_id
            await db.flush()
            await audit.log(
                db,
                "personnel_name_maps",
                "ad_esleme.karar",
                entity_id=kayit.id,
                old_value=None if yeni else eski,
                new_value={
                    "kaynak_alan": kayit.kaynak_alan,
                    "kaynak_ad": kayit.kaynak_ad,
                    "durum": karar,
                    "onaylanan_user_id": kayit.onaylanan_user_id,
                },
                user_id=user_id,
                is_personal_data=True,
            )
            sayac["eklendi" if yeni else "guncellendi"] += 1
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"] - sayac["guncellendi"]
        return sayac


PROFIL = AdEslemeProfili()
PROFIL_IZNI = "personel.yaz"
