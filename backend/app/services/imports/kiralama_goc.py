"""Kiralama pilot verisinin uzlaştırması ve kiralık envanter göç profili (TS-205, E06-09).

Eski .NET V1.20.1 kiralama modülü pilot olarak kullanıldı. Geçişten önce iki
iş yapılır:

1. **Uzlaştırma raporu (salt okunur)** — `uzlastirma(dizin)` döküm
   dosyalarını okur, hiçbir şey yazmaz ve dört uyumsuzluk türünü sayıyla ve
   satır listesiyle verir (E06-09):

   - `TAHSISSIZ_KIRADA` — durumu "Kirada" olan ama hiçbir kiralama kalemine
     tahsis edilmemiş envanter satırı;
   - `KAPALI_KIRALAMAYA_BAGLI` — Kapandı/İptal kiralamanın kalemine hâlâ
     bağlı (tahsisli) envanter satırı;
   - `ENVANTERSIZ_SERI` — kiralama kalemine elle yazılmış ama kiralık
     envanterde karşılığı olmayan seri;
   - `DURUM_ASAMA_UYUMSUZ` — kiralamanın durumu ile aşama geçmişi çelişiyor
     (ör. "Kapandı" ama son aşama "Sevk Edildi"; "Talep" ama aşaması var).

   Rapor ayrıca her kiralamanın yeni sistemdeki HESAPLANAN durumunu verir:
   aşama geçmişi varsa son aşama (Sevk Edildi → SEVK_EDILDI ...), yoksa eski
   durumun ön-sevk karşılığı; eski "Teklif" → `TALEP` (E06-09). Uydurma tarih
   yazılmaz: aşama zamanı yoksa olay da yoktur.

2. **Kiralık envanter göç profili** (`kiralik_envanter_goc`, izin `sistem.goc`)
   — `envanter_karar_satirlari(dizin)` profil şablonunda Excel satırları
   üretir; uyumsuz satırların "Uyumsuzluk" sütunu DOLU gelir. İçe Aktarma'da
   uyumsuz satır **çakışma** olarak işaretlenir ve çerçeve kuralı gereği
   varsayılan ATLANIR: satır ancak kullanıcı o satır için açıkça "Güncelle"
   (= uyumsuzluğu onayla) kararı verirse yazılır. **Kararsız uyumsuz satır
   aktarılmaz.** (E06-09'daki parti düzeyi `uyumsuzluk_onayi`, ortak
   `api/imports.py`'ye dokunmadan satır düzeyi kararla sağlanır.)

Yazma kuralları: seri takipli üründe her satır bir `rental_assets` satırı
(`source_ref='RentalInventory:<Id>'`, `uq_rasset_kaynak`) + `GIRIS` hareketi;
toplu üründe yalnız `GIRIS` hareketi (notunda kaynak ref; ikinci koşu aynı
ref'i bulur ve atlar). Hareketler TEK yazıcı `kiralik_envanter.hareket_yaz`
üzerinden. "Kirada" durumu girişte kullanılamaz (kiradaki cihaz kiralamasıyla
birlikte ya da fiziksel sayımla gelir): kullanıcı `Durum` sütununu seçer.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.migration.servis_kaynak import GOC_SISTEMI, KaynakDizini, metin, tamsayi
from app.models import Product, RentalAsset, RentalInventoryMovement, User
from app.services import audit
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.normalize import clean_cell, normalize_seri, tr_normkey
from app.services.teknik_servis import kiralik_envanter as env

# --- Uzlaştırma ------------------------------------------------------------------

UYUMSUZLUK_TURLERI = (
    ("TAHSISSIZ_KIRADA", "Tahsissiz 'Kirada' cihaz"),
    ("KAPALI_KIRALAMAYA_BAGLI", "Kapanmış/iptal kiralamaya bağlı cihaz"),
    ("ENVANTERSIZ_SERI", "Envanterle eşleşmeyen elle yazılmış seri"),
    ("DURUM_ASAMA_UYUMSUZ", "Durum - aşama geçmişi uyumsuzluğu"),
)
_KAPALI_KIRALAMA = {"kapandi", "iptal"}
# Eski aşama → yeni kiralama durumu (aşama adları yeni makinede durumdur).
ASAMA_ESLEME = {
    "sevk edildi": "SEVK_EDILDI",
    "kurulum yapildi": "KURULUM_YAPILDI",
    "devreye alindi": "DEVREYE_ALINDI",
    "toplandi": "TOPLANDI",
    "depoya alindi": "DEPOYA_ALINDI",
}
# Aşamasız kiralamada eski durum → yeni durum (yalnız sevk öncesi + son durumlar).
ON_SEVK_ESLEME = {
    "talep": "TALEP",
    "teklif": "TALEP",
    "planlama": "PLANLANDI",
    "hazirlaniyor": "HAZIRLANIYOR",
    "teslimata hazir": "HAZIRLANIYOR",
    "kapandi": "KAPANDI",
    "iptal": "IPTAL",
}
# Eski durum hangi aşama ailesiyle tutarlıdır.
_SEVK_SONRASI = {"teslim edildi", "kirada", "iade bekliyor"}
_DONUS_SONRASI = {"iade alindi", "test / kontrol", "kapandi"}
_SAHADA_ASAMALAR = {"sevk edildi", "kurulum yapildi", "devreye alindi"}
_DONUS_ASAMALARI = {"toplandi", "depoya alindi"}

# Eski envanter durumu → giriş durumu. Kirada bilinçli olarak YOK (girişte seçilmez).
ENVANTER_DURUM_ESLEME = {
    "hazir": "HAZIR",
    "kontrolde": "KONTROLDE",
    "test / kontrol": "KONTROLDE",
    "hazir degil": "HAZIR_DEGIL",
    "arizali": "HAZIR_DEGIL",
    "eksik": "HAZIR_DEGIL",
}
_SERI_AYRAC = re.compile(r"[,;\n\r|]+")


def _seriler(ham: str | None) -> list[str]:
    return [p.strip() for p in _SERI_AYRAC.split(ham or "") if p.strip()]


@dataclass
class KiralamaUzlastirma:
    """Dört tür uyumsuzluk + kiralama bazında hesaplanan durum. Hiçbir şey yazılmaz."""

    satirlar: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {kod: [] for kod, _ in UYUMSUZLUK_TURLERI}
    )
    kiralamalar: list[dict[str, Any]] = field(default_factory=list)
    envanter_uyumsuz: dict[str, list[str]] = field(default_factory=dict)  # ref → türler
    kaynak_sayilari: dict[str, int] = field(default_factory=dict)

    @property
    def sayilar(self) -> dict[str, int]:
        return {kod: len(s) for kod, s in self.satirlar.items()}


def yeni_kiralama_durumu(eski_durum: str | None, asamalar: list[str]) -> str | None:
    """Son aşama varsa onun karşılığı; yoksa eski durumun ön-sevk karşılığı (yoksa None).

    Kapandı/İptal her zaman kendi karşılığıdır (aşama geçmişi kapanışı geri almaz).
    """
    k = tr_normkey(eski_durum)
    if k in ("kapandi", "iptal"):
        return ON_SEVK_ESLEME[k]
    if asamalar:
        return ASAMA_ESLEME.get(tr_normkey(asamalar[-1]))
    return ON_SEVK_ESLEME.get(k)


def _durum_asama_celiskisi(eski_durum: str | None, asamalar: list[str]) -> str | None:
    k = tr_normkey(eski_durum)
    son = tr_normkey(asamalar[-1]) if asamalar else None
    if k == "iptal":
        return None
    if son is None:
        if k in _SEVK_SONRASI or k in ("iade alindi", "test / kontrol"):
            return "Sevk sonrası durum ama aşama geçmişi yok"
        return None
    if son in _SAHADA_ASAMALAR and k in _DONUS_SONRASI:
        return f"Durum '{eski_durum}' ama son aşama '{asamalar[-1]}' (dönüş aşaması yok)"
    if son in _DONUS_ASAMALARI and k in _SEVK_SONRASI:
        return f"Durum '{eski_durum}' ama son aşama '{asamalar[-1]}' (cihazlar dönmüş)"
    if k in ON_SEVK_ESLEME and k not in ("kapandi",):
        return f"Sevk öncesi durum '{eski_durum}' ama aşama geçmişi var ('{asamalar[-1]}')"
    if son not in ASAMA_ESLEME:
        return f"Tanınmayan aşama: {asamalar[-1]}"
    return None


def uzlastirma(dizin: KaynakDizini) -> KiralamaUzlastirma:
    """V1 kiralama dökümünden dört uyumsuzluk türünü çıkarır (saf, salt okunur)."""
    sonuc = KiralamaUzlastirma()
    siparisler = {
        k: s
        for s in dizin.tablo("RentalOrders", zorunlu=False)
        if (k := tamsayi(s.get("RentalOrderId"))) is not None
    }
    kalemler = {
        k: s
        for s in dizin.tablo("RentalOrderItems", zorunlu=False)
        if (k := tamsayi(s.get("RentalOrderItemId"))) is not None
    }
    envanter = dizin.tablo("RentalInventory", zorunlu=False)
    asama_satirlari = dizin.tablo("RentalStageHistory", zorunlu=False)
    sonuc.kaynak_sayilari = {
        "RentalOrders": len(siparisler),
        "RentalOrderItems": len(kalemler),
        "RentalInventory": len(envanter),
        "RentalStageHistory": len(asama_satirlari),
    }
    asamalar: dict[int, list[tuple[str, int, str]]] = defaultdict(list)
    for a in asama_satirlari:
        k = tamsayi(a.get("RentalOrderId"))
        ad = metin(a.get("StageName"))
        if k is not None and ad:
            asamalar[k].append(
                (str(a.get("EventAt") or ""), tamsayi(a.get("RentalStageHistoryId")) or 0, ad)
            )
    envanter_serileri: dict[int | None, set[str]] = defaultdict(set)
    tum_seriler: set[str] = set()
    b = sonuc.satirlar

    for e in envanter:
        ref = f"RentalInventory:{e.get('RentalInventoryId')}"
        anahtar = normalize_seri(metin(e.get("SerialNo")) or "")
        if anahtar:
            envanter_serileri[tamsayi(e.get("RentalProductId"))].add(anahtar)
            tum_seriler.add(anahtar)
        durum = tr_normkey(e.get("ConditionStatus"))
        kalem_id = tamsayi(e.get("RentalOrderItemId"))
        turler: list[str] = []
        if durum == "kirada" and kalem_id is None:
            turler.append("TAHSISSIZ_KIRADA")
            b["TAHSISSIZ_KIRADA"].append(
                {"ref": ref, "seri": e.get("SerialNo"), "durum": e.get("ConditionStatus")}
            )
        if kalem_id is not None:
            kalem = kalemler.get(kalem_id)
            siparis = siparisler.get(tamsayi(kalem.get("RentalOrderId"))) if kalem else None
            if siparis is not None and tr_normkey(siparis.get("Status")) in _KAPALI_KIRALAMA:
                turler.append("KAPALI_KIRALAMAYA_BAGLI")
                b["KAPALI_KIRALAMAYA_BAGLI"].append(
                    {
                        "ref": ref,
                        "seri": e.get("SerialNo"),
                        "kiralama": siparis.get("RentalNo"),
                        "kiralama_durumu": siparis.get("Status"),
                    }
                )
        if turler:
            sonuc.envanter_uyumsuz[ref] = turler

    for kalem_id, kalem in sorted(kalemler.items()):
        siparis = siparisler.get(tamsayi(kalem.get("RentalOrderId")))
        urun = tamsayi(kalem.get("RentalProductId"))
        for seri in _seriler(kalem.get("SerialNumbers")):
            anahtar = normalize_seri(seri)
            if anahtar and anahtar not in envanter_serileri.get(urun, set()):
                b["ENVANTERSIZ_SERI"].append(
                    {
                        "ref": f"RentalOrderItems:{kalem_id}",
                        "seri": seri,
                        "kiralama": siparis.get("RentalNo") if siparis else None,
                        "baska_urunde": anahtar in tum_seriler,
                    }
                )

    for sid, s in sorted(siparisler.items()):
        sirali = [ad for _, _, ad in sorted(asamalar.get(sid, []))]
        yeni = yeni_kiralama_durumu(s.get("Status"), sirali)
        neden = _durum_asama_celiskisi(s.get("Status"), sirali)
        if neden:
            b["DURUM_ASAMA_UYUMSUZ"].append(
                {
                    "ref": f"RentalOrders:{sid}",
                    "kiralama": s.get("RentalNo"),
                    "durum": s.get("Status"),
                    "son_asama": sirali[-1] if sirali else None,
                    "neden": neden,
                }
            )
        sonuc.kiralamalar.append(
            {
                "ref": f"RentalOrders:{sid}",
                "kiralama": s.get("RentalNo"),
                "eski_durum": s.get("Status"),
                "asama_sayisi": len(sirali),
                "yeni_durum": yeni or "EŞLENEMEDİ",
                "uyumsuz": bool(neden),
            }
        )
    return sonuc


def uzlastirma_sayfalari(u: KiralamaUzlastirma) -> dict[str, Any]:
    """Rapor sayfaları (`ana_veri_olcum.cok_sayfali_xlsx` girdisi)."""
    from app.migration.ana_veri_olcum import Sayfa

    ozet = Sayfa(["Kalem", "Adet"])
    ozet.satirlar += [[f"Kaynak: {t}", n] for t, n in u.kaynak_sayilari.items()]
    ozet.satirlar += [[ad, u.sayilar[kod]] for kod, ad in UYUMSUZLUK_TURLERI]
    sayfalar: dict[str, Any] = {"Ozet": ozet}
    for kod, _ad in UYUMSUZLUK_TURLERI:
        satirlar = u.satirlar[kod]
        anahtarlar = list(satirlar[0]) if satirlar else ["ref"]
        sayfalar[kod[:31]] = Sayfa(anahtarlar, [[s.get(a) for a in anahtarlar] for s in satirlar])
    sayfalar["Kiralamalar"] = Sayfa(
        ["Kaynak Ref", "Kiralama No", "Eski Durum", "Aşama Sayısı", "Yeni Durum", "Uyumsuz"],
        [
            [
                k["ref"],
                k["kiralama"],
                k["eski_durum"],
                k["asama_sayisi"],
                k["yeni_durum"],
                "EVET" if k["uyumsuz"] else "HAYIR",
            ]
            for k in u.kiralamalar
        ],
    )
    return sayfalar


def uzlastirma_xlsx(u: KiralamaUzlastirma) -> bytes:
    from app.migration.ana_veri_olcum import cok_sayfali_xlsx

    return cok_sayfali_xlsx(uzlastirma_sayfalari(u))


# --- Kiralık envanter göç profili ------------------------------------------------

_REF = re.compile(r"^RentalInventory:\d+$")
_GOC_NOTU = "Göç {ref}"
# Toplu girişin kimliği hareket notundadır ("Göç RentalInventory:12" ya da "...; not").
_GOC_NOTU_DESENI = re.compile(r"^Göç (RentalInventory:\d+)(?:;|$)")

SUTUNLAR = (
    Sutun("ref", ("Kaynak Ref",), zorunlu=True, aciklama="RentalInventory:<Id> — değiştirmeyin."),
    Sutun("urun_kodu", ("Ürün Kodu",), zorunlu=True, aciklama="Kiralama kataloğundaki ürün kodu."),
    Sutun("depo_id", ("Depo Id",), zorunlu=True, aciklama="Aktif kiralama deposu kimliği."),
    Sutun("seri", ("Seri No",), aciklama="Seri takipli üründe zorunlu, toplu üründe boş."),
    Sutun("adet", ("Adet",), aciklama="Toplu üründe adet (seri üründe 1)."),
    Sutun("eski_depo", ("Eski Depo",), aciklama="Bilgi amaçlı."),
    Sutun("eski_durum", ("Eski Durum",), aciklama="Bilgi amaçlı."),
    Sutun(
        "durum",
        ("Durum",),
        aciklama="Giriş durumu: HAZIR, KONTROLDE, HAZIR_DEGIL (Kirada girişte seçilemez).",
    ),
    Sutun(
        "uyumsuzluk",
        ("Uyumsuzluk",),
        aciklama="Uzlaştırmanın bulduğu tür(ler). Doluysa satır yalnız açık kararla yazılır.",
    ),
    Sutun("not_", ("Not",), aciklama="Hareket notuna eklenir (300 karakter)."),
)
KARAR_BASLIKLARI = [s.baslik for s in SUTUNLAR]


def envanter_karar_satirlari(dizin: KaynakDizini, u: KiralamaUzlastirma) -> list[list[Any]]:
    """Profil şablonunda satırlar: ürün kodu ve eski durum dökümden, uyumsuzluk dolu."""
    urunler = {
        tamsayi(p.get("RentalProductId")): p for p in dizin.tablo("RentalProducts", zorunlu=False)
    }
    depolar = {
        tamsayi(d.get("RentalWarehouseId")): d
        for d in dizin.tablo("RentalWarehouses", zorunlu=False)
    }
    satirlar: list[list[Any]] = []
    for e in dizin.tablo("RentalInventory", zorunlu=False):
        ref = f"RentalInventory:{e.get('RentalInventoryId')}"
        urun = urunler.get(tamsayi(e.get("RentalProductId"))) or {}
        depo = depolar.get(tamsayi(e.get("RentalWarehouseId"))) or {}
        seri = metin(e.get("SerialNo"))
        satirlar.append(
            [
                ref,
                urun.get("ProductCode"),
                None,
                seri,
                None if seri else tamsayi(e.get("Quantity")),
                " - ".join(x for x in (depo.get("Code"), depo.get("Name")) if x) or None,
                e.get("ConditionStatus"),
                ENVANTER_DURUM_ESLEME.get(tr_normkey(e.get("ConditionStatus"))),
                ", ".join(u.envanter_uyumsuz.get(ref, [])) or None,
                metin(e.get("Notes")),
            ]
        )
    return satirlar


def _tamsayi(ham: Any) -> int | None:
    m = clean_cell(ham)
    if not m:
        return None
    try:
        return int(float(m))
    except ValueError as exc:
        raise ValueError(f"sayı bekleniyor: {m}") from exc


async def _aktarilmis_refler(db: AsyncSession, refler: list[str]) -> set[str]:
    if not refler:
        return set()
    seri = set(
        (
            await db.scalars(
                select(RentalAsset.source_ref).where(
                    RentalAsset.source_system == GOC_SISTEMI, RentalAsset.source_ref.in_(refler)
                )
            )
        ).all()
    )
    istenen = set(refler)
    toplu: set[str] = set()
    for n in (
        await db.scalars(
            select(RentalInventoryMovement.note).where(
                RentalInventoryMovement.kind == "GIRIS",
                RentalInventoryMovement.asset_id.is_(None),
                RentalInventoryMovement.note.like("Göç RentalInventory:%"),
            )
        )
    ).all():
        m = _GOC_NOTU_DESENI.match(n or "")
        if m and m.group(1) in istenen:
            toplu.add(m.group(1))
    return seri | toplu


class KiralikEnvanterGocProfili(Profil):
    kod = "kiralik_envanter_goc"
    ad = "Kiralık Envanter (pilot göçü)"
    aciklama = (
        "Eski sistem kiralık envanterinin aktarılması. Satırlar uzlaştırma raporuyla "
        "üretilir; uyumsuz satır yalnız açık 'Güncelle' kararıyla yazılır."
    )
    sutunlar = SUTUNLAR
    # Çakışma = uyumsuzluk; karar "guncelle" = uyumsuzluğu onaylayıp aktar.
    guncelleme_destekli = True

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        refler = [clean_cell(s.get("ref")) for s in satirlar]
        aktarilmis = await _aktarilmis_refler(db, [r for r in refler if _REF.match(r)])
        sonuclar: list[SatirSonucu] = []
        gorulen_ref: set[str] = set()
        gorulen_seri: set[tuple[int, str]] = set()
        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            v = r.veri
            ref = clean_cell(ham.get("ref"))
            v["ref"] = ref
            if not _REF.match(ref):
                r.hatalar.append("Kaynak ref 'RentalInventory:<Id>' biçiminde olmalı")
            elif ref in gorulen_ref:
                r.hatalar.append("Aynı kaynak ref dosyada iki kez")
            gorulen_ref.add(ref)
            try:
                depo_id = _tamsayi(ham.get("depo_id"))
                adet = _tamsayi(ham.get("adet"))
            except ValueError as exc:
                r.hatalar.append(str(exc))
                sonuclar.append(r)
                continue
            kod = clean_cell(ham.get("urun_kodu"))
            urun = await db.scalar(select(Product).where(Product.code == kod)) if kod else None
            profil = None
            try:
                urun = env.urun_dogrula(urun)
                profil = await env.aktif_katalog(db, urun.id)
                await env.kiralama_deposu(db, depo_id, profil.birim)
            except env.KiralamaHatasi as exc:
                r.hatalar.append(str(exc) if kod else "Ürün kodu boş")
            eski = clean_cell(ham.get("eski_durum"))
            durum = clean_cell(ham.get("durum")).upper() or ENVANTER_DURUM_ESLEME.get(
                tr_normkey(eski)
            )
            if durum not in env.GIRIS_DURUMLARI:
                r.hatalar.append(
                    "Durum seçilmeli (HAZIR, KONTROLDE, HAZIR_DEGIL); "
                    f"eski durum '{eski or '-'}' girişte kullanılamaz"
                )
            seri = clean_cell(ham.get("seri"))
            if urun is not None and profil is not None:
                if env.seri_takipli_mi(urun):
                    anahtar = normalize_seri(seri)
                    if not anahtar:
                        r.hatalar.append(f"'{urun.code}' seri takipli; seri zorunlu")
                    elif len(seri) > 200:
                        r.hatalar.append("Seri 200 karakteri aşıyor")
                    elif adet not in (None, 1):
                        r.hatalar.append("Seri takipli üründe adet 1'dir")
                    elif (urun.id, anahtar) in gorulen_seri:
                        r.hatalar.append(f"'{seri}' dosyada iki kez")
                    else:
                        gorulen_seri.add((urun.id, anahtar))
                        var = await env._seri_var_mi(db, urun.id, anahtar)
                        if var is not None and var.source_ref != ref:
                            r.hatalar.append(f"'{seri}' bu ürün için zaten kiralık envanterde")
                    adet = 1
                else:
                    if seri:
                        r.hatalar.append(f"'{urun.code}' toplu ürün; seri yazılmaz, adet yazılır")
                    if adet is None or adet <= 0:
                        r.hatalar.append("Toplu üründe adet sıfırdan büyük olmalı")
            uyumsuzluk = clean_cell(ham.get("uyumsuzluk"))
            v.update(
                {
                    "product_id": urun.id if urun is not None else None,
                    "depo_id": depo_id,
                    "seri": seri or None,
                    "adet": adet,
                    "durum": durum,
                    "not": clean_cell(ham.get("not_"))[:200] or None,
                }
            )
            if r.gecerli and ref in aktarilmis:
                r.uyarilar.append("Bu satır zaten aktarılmış — atlanacak")
                v["aktarilmis"] = "1"
            elif r.gecerli and uyumsuzluk:
                r.cakisma = {
                    "tip": "uyumsuzluk",
                    "kayit_id": None,
                    "aciklama": (
                        f"Uzlaştırma uyumsuzluğu: {uyumsuzluk}. Aktarmak için bu satıra "
                        "açıkça 'Güncelle' kararı verin; kararsız satır aktarılmaz."
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
        kullanici = await db.get(User, user_id) if user_id is not None else None
        aktarilmis = await _aktarilmis_refler(
            db, [s["veri"]["ref"] for s in satirlar if _REF.match(s["veri"].get("ref") or "")]
        )
        onaylanan_uyumsuz = 0
        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            v: dict[str, Any] = satir["veri"]
            if v.get("aktarilmis") or v["ref"] in aktarilmis:
                continue
            product_id = int(v["product_id"])
            urun = await db.get(Product, product_id)
            profil = await env.aktif_katalog(db, product_id)
            depo = await env.kiralama_deposu(db, int(v["depo_id"]), profil.birim)
            notu = _GOC_NOTU.format(ref=v["ref"])
            if v.get("not"):
                notu = f"{notu}; {v['not']}"
            cihaz = None
            if env.seri_takipli_mi(urun):
                cihaz = RentalAsset(
                    product_id=product_id,
                    identity_kind=env.KIMLIK_SERI,
                    serial_no=v["seri"],
                    serial_key=normalize_seri(v["seri"]),
                    birim=profil.birim,
                    warehouse_id=depo.id,
                    durum=v["durum"],
                    source_system=GOC_SISTEMI,
                    source_ref=v["ref"],
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(cihaz)
                await db.flush()
            await env.hareket_yaz(
                db,
                tur="GIRIS",
                product_id=product_id,
                qty=1 if cihaz is not None else int(v["adet"]),
                clock=clock,
                user=kullanici,
                asset=cihaz,
                to_warehouse_id=depo.id,
                to_durum=v["durum"],
                note=notu,
            )
            aktarilmis.add(v["ref"])
            sayac["eklendi"] += 1
            if satir.get("cakisma"):
                onaylanan_uyumsuz += 1
        sayac["atlandi"] = len(satirlar) - sayac["eklendi"]
        await audit.log(
            db,
            env.ENTITY_KIRALIK,
            "goc.kiralik_envanter",
            new_value={**sayac, "onaylanan_uyumsuz": onaylanan_uyumsuz},
            user_id=user_id,
        )
        sayac["onaylanan_uyumsuz"] = onaylanan_uyumsuz
        return sayac


PROFIL = KiralikEnvanterGocProfili()
PROFIL_IZNI = "sistem.goc"
