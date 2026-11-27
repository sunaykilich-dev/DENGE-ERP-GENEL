"""Servis talep listesi profili: birimlerin Excel'de tuttuğu müşteri talepleri.

Güvenlik birimi talepleri yıllarca "Güvenlik Talep Takip" Excel'inde izledi
(müşteri, lokasyon, araç, personel, talep detayı, durum). Bu profil o listeyi
servis işine çevirir; yazma, eski sistem göçüyle AYNI fonksiyondur
(`servis_goc.is_yaz`): numara, olay kaydı ve sonuç kuralları tek yerde.

Kurallar (KARARLAR 2026-11-27; 2026-11-23 sürümünün yerine):
- Birim sütunu yoksa/boşsa GUVENLIK (liste Güvenlik Talep Takip dosyasıdır;
  başka birim kendi kodunu yazar).
- TAMAMLANDI → TAMAMLANDI: iş İş Emri Onayı'na düşer. "Not / Açıklama"
  sütunu işin SONUCU olarak yazılır (yerinde çözüldü); not yoksa göç metni.
- Tamamlanmayan her durum (Beklemede, Planlandı, Devam ediyor, Ertelendi,
  boş) → PLANLAMADA (planlamada bekler). İptal edildi → IPTAL.
- Personel sütunundaki adlar kayıtlı kullanıcılarla eşlenip işe TAYİN edilir
  (ilk teknisyen sorumlu). Ayraçsız yazılmış adlar ("ONUR DEMİR SERVET
  YAMAN") ve küçük yazım hataları da eşlenir; eşleşmeyen ad uyarı olur ve
  açıklamada kalır.
- Talep tarihi boşsa planlanan tarih kullanılır (Yetkili sütununa tarih
  yazılmışsa o da talep tarihi sayılır). Tamamlanma anı planlanan tarihtir.
- Araç plaka biçimindeyse işin plakasına, değilse açıklamaya yazılır.
- Tür sütunu boşsa talep detayından çıkarılır: kurulum/devreye alma →
  KURULUM, keşif → KESIF, bakım → PLANSIZ_BAKIM, diğerleri ARIZA.
- Aynı satır ikinci kez yüklenirse yeni iş açılmaz (sıra no + müşteri + detay
  + tarih + lokasyon özetinden kaynak anahtarı; `uq_so_kaynak`).
"""

import hashlib
import re
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.migration import servis_goc
from app.models import Account, Role, ServiceOrder, ServiceOrderAssignment, User
from app.models.rbac import BIRIM_KODLARI
from app.models.teknik_servis import SERVIS_TURLERI
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.imports.ortak import tarih_coz
from app.services.normalize import clean_cell, tr_normkey

KAYNAK_ONEKI = "ExcelTalep:"
VARSAYILAN_BIRIM = "GUVENLIK"
DURUM_ESLEME = {
    "tamamlandi": "TAMAMLANDI",
    "kapatildi": "TAMAMLANDI",
    "beklemede": "PLANLAMADA",
    "planlandi": "PLANLAMADA",
    "devam ediyor": "PLANLAMADA",
    "ertelendi": "PLANLAMADA",
    "iptal": "IPTAL",
    "iptal edildi": "IPTAL",
    "": "PLANLAMADA",
}
YASAK_TURLER = {"PB", "ATOLYE"}
KONU_SINIRI = ServiceOrder.__table__.c.konu.type.length
MUSTERI_SINIRI = ServiceOrder.__table__.c.customer_name_raw.type.length
PLAKA_SINIRI = ServiceOrder.__table__.c.arac_plaka.type.length
MUSTERI_YOK = "(Müşteri yazılmamış)"
DETAY_YOK = "(Talep detayı yazılmamış)"
TAMAMLANMIS_SONUC_YOK = "Excel talep listesinden aktarıldı (sonuç notu yok)"
_PLAKA = re.compile(r"\b(\d{2})\s*([A-ZÇĞİÖŞÜ]{1,3})\s*(\d{2,4})\b")

SUTUNLAR = (
    Sutun("no", ("No", "Sıra", "Sıra No")),
    Sutun("birim", ("Birim",), aciklama=", ".join(BIRIM_KODLARI) + " (boşsa GUVENLIK)"),
    Sutun("tur", ("Tür", "Tur"), aciklama="Servis türü kodu (boşsa detaydan çıkarılır)."),
    Sutun("tarih", ("Talep Tarihi", "Tarih"), aciklama="GG.AA.YYYY (boşsa planlanan tarih)"),
    Sutun("musteri", ("Müşteri / Firma", "Müşteri", "Firma"), zorunlu=True),
    Sutun("lokasyon", ("Lokasyon", "Adres")),
    Sutun("detay", ("Talep Detayı", "Talep", "Konu"), zorunlu=True),
    Sutun("durum", ("Durum",), aciklama="Tamamlandı / Beklemede / Planlandı / Devam ediyor."),
    Sutun("plan", ("Planlanan Tarih",), aciklama="Tamamlanma anı; talep tarihi yoksa o."),
    Sutun("personel", ("Personel",), aciklama="Kayıtlı kullanıcılara tayin edilir."),
    Sutun("arac", ("Araç", "Arac"), aciklama="Plaka işin plakasına yazılır."),
    Sutun("yetkili", ("Yetkili Kişi", "Yetkili")),
    Sutun("yetkili_iletisim", ("Yetkili İletişim", "Yetkili Iletisim")),
    Sutun("notlar", ("Not / Açıklama", "Not", "Açıklama"), aciklama="Tamamlanan işin sonucu."),
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


def tur_cikar(detay: str) -> str:
    k = tr_normkey(detay)
    if "kurulum" in k or "devreye al" in k:
        return "KURULUM"
    if "kesif" in k:
        return "KESIF"
    if "bakim" in k:
        return "PLANSIZ_BAKIM"
    return "ARIZA"


def plaka_coz(ham: str | None) -> str | None:
    """İlk plaka biçimli parça ("34 GES 273"); yoksa None (metin açıklamada kalır)."""
    m = _PLAKA.search((ham or "").upper())
    if not m:
        return None
    return " ".join(m.groups())[:PLAKA_SINIRI]


def _belirtecler(metin: str) -> list[str]:
    return re.findall(r"[0-9a-z]+", tr_normkey(metin))


def _mesafe(a: str, b: str) -> int:
    """Levenshtein uzaklığı (kısa adlar için)."""
    onceki = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        simdi = [i]
        for j, cb in enumerate(b, 1):
            simdi.append(min(onceki[j] + 1, simdi[j - 1] + 1, onceki[j - 1] + (ca != cb)))
        onceki = simdi
    return onceki[-1]


class AdEsleyici:
    """Serbest yazılmış personel metnini kayıtlı kullanıcılara eşler.

    Takma adlar: tam ad, her ad + soyad ("Burak Şahinbaş", "Mehmet Şahinbaş").
    Metin sözcüklere bölünür; soldan sağa 3/2/1 sözcüklük pencere bir takma
    adla eşlenir: birebir, ya da sözcüklerden biri birebir ve diğerlerinde
    küçük yazım hatası (kısa sözcükte 1, uzunda 2 harf). Tek sözcük yalnız bitişik
    yazılmış ad içindir ("BURAKŞAHİNBAŞ"); tek başına ad ("SERDAR") eşlenmez.
    Aynı takma ad, sözcük kümesi aynı iki hesaba çıkarsa (mükerrer hesap) en
    eski hesap seçilir; farklı kişilere çıkarsa eşlenmez (uydurma yok).
    """

    def __init__(self, kisiler: list[tuple[int, str, str]]):
        self.kisiler = {uid: (ad, rol) for uid, ad, rol in kisiler}
        adaylar: dict[tuple[str, ...], set[int]] = {}
        kume: dict[int, frozenset[str]] = {}
        for uid, ad, _ in kisiler:
            b = _belirtecler(ad)
            if len(b) < 2:
                continue
            kume[uid] = frozenset(b)
            for t in {tuple(b)} | {(on, b[-1]) for on in b[:-1]}:
                adaylar.setdefault(t, set()).add(uid)
        self.takma: dict[tuple[str, ...], int] = {}
        for t, uidler in adaylar.items():
            if len({kume[u] for u in uidler}) == 1:
                self.takma[t] = min(uidler)
        self.bitisik = {"".join(t): uid for t, uid in self.takma.items()}

    def _bul(self, pencere: list[str]) -> tuple[int, int | None]:
        """(puan, kişi): 2 = birebir, 1 = küçük yazım hatası, 0 = yok."""
        tup = tuple(pencere)
        if tup in self.takma:
            return 2, self.takma[tup]
        if "".join(pencere) in self.bitisik:
            return 2, self.bitisik["".join(pencere)]
        adaylar = {
            uid
            for t, uid in self.takma.items()
            if len(t) == len(tup)
            and any(a == b for a, b in zip(t, tup, strict=True))
            and all(_mesafe(a, b) <= (1 if len(a) < 6 else 2) for a, b in zip(t, tup, strict=True))
        }
        return (1, adaylar.pop()) if len(adaylar) == 1 else (0, None)

    def esle(self, metin: str | None) -> tuple[list[int], list[str]]:
        b = _belirtecler(metin or "")
        bulunan: list[int] = []
        kalan: list[list[str]] = []
        son_eslesmeyen = -2
        i = 0
        while i < len(b):
            secim = None
            for w in (3, 2, 1):
                if i + w > len(b):
                    continue
                puan, uid = self._bul(b[i : i + w])
                if uid is not None and (secim is None or puan > secim[0]):
                    secim = (puan, uid, w)
            if secim:
                if secim[1] not in bulunan:
                    bulunan.append(secim[1])
                i += secim[2]
                continue
            if kalan and son_eslesmeyen == i - 1:
                kalan[-1].append(b[i])
            else:
                kalan.append([b[i]])
            son_eslesmeyen = i
            i += 1
        return bulunan, [" ".join(p).upper() for p in kalan if p != ["ve"]]


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

    async def _esleyici(self, db: AsyncSession) -> AdEsleyici:
        satirlar = (
            await db.execute(
                select(User.id, User.full_name, User.saha_rolu, Role.code)
                .join(Role, Role.id == User.role_id)
                .where(User.is_active.is_(True), User.ayrilis_tarihi.is_(None))
            )
        ).all()
        return AdEsleyici(
            [
                (uid, ad, "SEF" if (saha == "SEF" or kod == "SERVIS_SEF") else "TEKNISYEN")
                for uid, ad, saha, kod in satirlar
            ]
        )

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        hesaplar = await self._hesaplar(db)
        birebir = {anahtar: hid for hid, anahtar in hesaplar}
        esleyici = await self._esleyici(db)
        sonuclar: list[SatirSonucu] = []
        gorulen: set[str] = set()
        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            h = {k: (clean_cell(v) or "") for k, v in ham.items()}

            birim = (h.get("birim") or VARSAYILAN_BIRIM).upper()
            if birim not in BIRIM_KODLARI:
                r.hatalar.append(f"birim tanınmadı: {h.get('birim')}")
            musteri, detay = h.get("musteri", ""), h.get("detay", "")
            tur = (h.get("tur") or tur_cikar(detay)).upper()
            if tur not in SERVIS_TURLERI or tur in YASAK_TURLER:
                r.hatalar.append(f"tür seçilemez: {h.get('tur')}")
            durum_ham = tr_normkey(h.get("durum", ""))
            durum = DURUM_ESLEME.get(durum_ham)
            if durum is None:
                r.hatalar.append(f"durum tanınmadı: {h.get('durum')}")
            # Geçmiş iş kaybolmasın: yalnız biri boşsa yer tutucuyla açılır.
            if not musteri and not detay:
                r.hatalar.append("müşteri ve talep detayı boş")
            elif not musteri:
                musteri = MUSTERI_YOK
                r.uyarilar.append("Müşteri yazılmamış; iş müşterisiz açılacak")
            elif not detay:
                detay = h.get("notlar") or DETAY_YOK
                r.uyarilar.append("Talep detayı yazılmamış; not/yer tutucu konu olacak")

            yetkili = h.get("yetkili", "")
            yetkili_gunu = _gun(yetkili) if re.match(r"^\d", yetkili) else None
            if yetkili_gunu is not None:
                yetkili = ""
            talep_gunu = _gun(h.get("tarih")) or yetkili_gunu
            plan_gunu = _gun(h.get("plan"))
            if h.get("tarih") and _gun(h.get("tarih")) is None:
                r.uyarilar.append(f"Talep tarihi okunamadı: {h['tarih']}")
            if h.get("plan") and plan_gunu is None:
                r.uyarilar.append(f"Planlanan tarih okunamadı: {h['plan']}")
            if talep_gunu is None and plan_gunu is not None:
                talep_gunu = plan_gunu

            anahtar = tr_normkey(musteri)
            hesap_id = birebir.get(anahtar)
            if hesap_id is None and len(anahtar) >= 4:
                adaylar = [hid for hid, k in hesaplar if anahtar in k]
                hesap_id = adaylar[0] if len(adaylar) == 1 else None
            if hesap_id is None and musteri:
                r.uyarilar.append("Müşteri hesabı bulunamadı; ham adla açılacak")

            kisiler, eslesmeyen = esleyici.esle(h.get("personel"))
            if eslesmeyen:
                r.uyarilar.append("Personel bulunamadı: " + ", ".join(eslesmeyen))

            ozet = "|".join(
                (
                    h.get("no", ""),
                    anahtar,
                    tr_normkey(detay),
                    tr_normkey(h.get("lokasyon", "")),
                    h.get("tarih", ""),
                    h.get("plan", ""),
                )
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
                    "plaka": plaka_coz(h.get("arac")),
                    # Parti verisi metin olarak saklanır: "kişi_id:ROL,..."
                    "atamalar": ",".join(f"{uid}:{esleyici.kisiler[uid][1]}" for uid in kisiler)
                    or None,
                    "yetkili": yetkili or None,
                    "musteri": musteri,
                    "detay": detay,
                    "lokasyon": h.get("lokasyon") or None,
                    **{
                        k: h.get(k) or None
                        for k in ("plan", "personel", "arac", "yetkili_iletisim", "notlar")
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
            tamam = v["durum"] == "TAMAMLANDI"
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
            acilis = talep or clock.now()
            bitis = max(plan or acilis, acilis)
            t = servis_goc.IsTaslagi(
                ref=v["ref"],
                eski_no=None,
                birim=v["birim"],
                tur=v["tur"],
                durum=v["durum"],
                kanal="YERINDE" if tamam else None,
                hesap_id=int(v["hesap_id"]) if v.get("hesap_id") else None,
                musteri_ham=musteri,
                lokasyon_ham=v.get("lokasyon"),
                konu=konu or "",
                aciklama="\n".join(["Excel talep listesinden aktarıldı.", *ekler]),
                acilis=acilis,
                tamamlanma=bitis if tamam else None,
                iptal=bitis if v["durum"] == "IPTAL" else None,
                onceki_durum="PLANLAMADA",
                sonuc_metni=(v.get("notlar") or TAMAMLANMIS_SONUC_YOK) if tamam else None,
                arac_plaka=v.get("plaka"),
            )
            so_id = await servis_goc.is_yaz(db, t, bag)
            if so_id is None:
                continue
            sayac["eklendi"] += 1
            atamalar = [
                (int(p.split(":")[0]), p.split(":")[1])
                for p in (v.get("atamalar") or "").split(",")
                if ":" in p
            ]
            # Sorumlu: ilk teknisyen; ekipte teknisyen yoksa ilk şef (B1).
            sorumlu = next((u for u, r in atamalar if r == "TEKNISYEN"), None)
            if sorumlu is None and atamalar:
                sorumlu = atamalar[0][0]
            for uid, rol in atamalar:
                db.add(
                    ServiceOrderAssignment(
                        service_order_id=so_id,
                        user_id=uid,
                        rol=rol,
                        is_lead=uid == sorumlu,
                        assigned_at=acilis,
                        assigned_by=user_id,
                    )
                )
            await db.flush()
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        return sayac


PROFIL = ServisTalepProfili()
PROFIL_IZNI = "servis.yaz"
