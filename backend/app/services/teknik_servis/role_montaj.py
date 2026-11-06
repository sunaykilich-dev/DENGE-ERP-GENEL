"""Haberleşme saha işi: röle (repeater) montaj bilgileri (KARARLAR 2026-10-28 §10).

Kullanıcı isteği (2026-11-06): "Repeater Montaj Bilgileri" kütüğünün sütunları
Haberleşme KURULUM/MONTAJ işlerinde zorunlu; eksikse iş KAPATILAMAZ. Haberleşme
saha işi açılırken işin niteliği çoktan seçmeli seçilir (`nitelikler`); kural
türü KURULUM olan ya da niteliklerinde KURULUM/MONTAJ bulunan işe uygulanır.

- Alan listesi ve zorunluluk kuralı yalnız burada (`ALANLAR`, `eksik_alanlar`).
- Kayıt kısmi olabilir (teknisyen sahada bir kısmını, ofis BTK bilgisini sonra
  girer); engel yalnız kapanışta (`kapanis_dogrula`, tek durum kapısından).
- Moda bağlı alanlar: analog ton yalnız ANALOG/MIX'te, dijital CC/slot/grup
  yalnız DIJITAL/MIX'te; simpleks alanları yalnız simpleks VAR ise zorunlu.
  Kütükteki "X" (uygulanmaz) böylece uydurma değer yazılmadan karşılanır.
- Toplam telsiz sayısı girilmez, el + araç + sabitten hesaplanır.
- Sorumlu kişi ve telefonu kişisel veridir: olay/denetim özetine yazılmaz.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import Account, Address, ServiceOrder, ServiceRoleMontaj, User
from app.models.teknik_servis import HABERLESME_NITELIKLERI
from app.services.teknik_servis import atama, gecmis
from app.services.teknik_servis.kancalar import ServisGirdiHatasi, ServisHatasi

BIRIM = "HABERLESME"
# Atölye işi saha işi değildir: niteliği sorulmaz, montaj bilgisi aranmaz.
SAHA_DISI_TURLER = ("ATOLYE",)
NITELIK_ADLARI = {
    "KURULUM": "Kurulum",
    "MONTAJ": "Montaj",
    "DEMONTAJ": "Demontaj",
    "ARIZA": "Arıza",
    "BAKIM": "Bakım",
    "PROGRAMLAMA": "Programlama / frekans ayarı",
    "KESIF": "Keşif",
    "DIGER": "Diğer",
}
MONTAJ_NITELIKLERI = ("KURULUM", "MONTAJ")
# Sistem açılışlarında (PB, teklif, aktarım) ve göçte türden varsayılan nitelik.
TUR_NITELIGI = {
    "KURULUM": "KURULUM",
    "DEMONTAJ": "DEMONTAJ",
    "ARIZA": "ARIZA",
    "PB": "BAKIM",
    "PLANSIZ_BAKIM": "BAKIM",
    "KESIF": "KESIF",
}

MODLAR = ("ANALOG", "DIJITAL", "MIX")
_ANALOG = ("ANALOG", "MIX")
_DIJITAL = ("DIJITAL", "MIX")


def _a(kod, ad, grup, tip="metin", *, secenekler=None, kosul=None, zorunlu=True, ipucu=None):
    return {
        "kod": kod,
        "ad": ad,
        "grup": grup,
        "tip": tip,
        "secenekler": list(secenekler) if secenekler else None,
        "kosul": kosul,
        "zorunlu": zorunlu,
        "ipucu": ipucu,
    }


# kosul: {"alan": kod, "degerler": [...]} → alan yalnız o değerlerde görünür/zorunlu.
_ANALOG_K = {"alan": "calisma_modu", "degerler": list(_ANALOG)}
_DIJITAL_K = {"alan": "calisma_modu", "degerler": list(_DIJITAL)}
_SIMP = {"alan": "simpleks", "degerler": ["VAR"]}

ALANLAR: list[dict[str, Any]] = [
    # Bildirim ve yetki (ofis tamamlar)
    _a(
        "alt_yapi_bildirim_durumu",
        "Alt yapı bildirim durumu",
        "Bildirim ve yetki",
        "secim",
        secenekler=(
            "BİLDİRİM YAPILDI",
            "BİLDİRİM YAPILMADI",
            "SORULACAK",
            "DEMONTE YAZISI GÖNDERİLECEK",
            "ABONELİK İPTAL EDİLDİ",
            "KURUMA AİT FREKANSLAR",
        ),
    ),
    _a("kurulum_tarihi", "Kurulum tarihi", "Bildirim ve yetki", "tarih"),
    _a(
        "yetki_belgesi",
        "Sayısı sınırlandırılmayan kullanım hakkı yetki belgesi",
        "Bildirim ve yetki",
    ),
    _a("btk_bildirim", "BTK bildirim tarih / sayı", "Bildirim ve yetki"),
    # Müşteri ve yer
    _a("firma_adi", "Firma adı", "Müşteri ve yer"),
    _a("proje_adi", "Proje adı", "Müşteri ve yer"),
    _a("role_sahiplik", "Röle sahiplik durumu", "Müşteri ve yer"),
    _a("adres", "Sistem kurulumu yapılan adres", "Müşteri ve yer"),
    _a("koordinat", "Sistem kurulumu yapılan koordinat", "Müşteri ve yer"),
    _a("yerel_bolgesel", "Yerel / bölgesel", "Müşteri ve yer", ipucu="Örn. MARMARA BÖLGESEL"),
    _a("sorumlu_ad", "Sorumlu kişi", "Müşteri ve yer"),
    _a("sorumlu_telefon", "Sorumlu kişi irtibat (telefon)", "Müşteri ve yer"),
    _a("sorumlu_eposta", "Sorumlu kişi e-posta", "Müşteri ve yer", zorunlu=False),
    # Montaj
    _a("role_kurulum_yeri", "Röle kurulumunun yapıldığı yer", "Montaj"),
    _a("anten_sayisi", "Anten sayısı", "Montaj", "sayi"),
    _a("anten_tipi", "Anten tipi", "Montaj"),
    _a("anten_yerleri", "Anten yerleri", "Montaj"),
    _a("kablo_tipi", "Kablo tipi", "Montaj"),
    _a("kablo_metraji", "Kablo metrajı (m)", "Montaj", "sayi"),
    _a(
        "diger_malzemeler",
        "Diğer montaj malzemeleri",
        "Montaj",
        ipucu="Yoksa 'Yok' yazın",
    ),
    _a("alt_yapi_durumu", "Alt yapı durumu", "Montaj", ipucu="Örn. RÖLE, SİMPLEKS"),
    _a("role_marka_model", "Röle marka model", "Montaj"),
    _a("role_seri_no", "Röle seri no", "Montaj"),
    _a("yazilim_versiyon", "Yazılım versiyon", "Montaj"),
    _a("montaj_yapan", "Montajı yapan teknik personel", "Montaj"),
    # Frekans ve mod
    _a("role_tx", "Röle TX frekansı (MHz)", "Frekans ve mod", "frekans"),
    _a("role_rx", "Röle RX frekansı (MHz)", "Frekans ve mod", "frekans"),
    _a(
        "calisma_modu",
        "Röle cihazı çalışma modu",
        "Frekans ve mod",
        "secim",
        secenekler=MODLAR,
    ),
    _a("role_analog_ton", "Röle analog mod RX / TX ton", "Frekans ve mod", kosul=_ANALOG_K),
    _a("role_dijital_cc", "Röle dijital mod CC", "Frekans ve mod", kosul=_DIJITAL_K),
    _a("role_dijital_slot", "Röle dijital mod slot no", "Frekans ve mod", kosul=_DIJITAL_K),
    _a("role_dijital_grup", "Röle dijital mod grup no", "Frekans ve mod", kosul=_DIJITAL_K),
    _a("telsiz_cc", "Telsiz CC", "Frekans ve mod", kosul=_DIJITAL_K),
    _a("telsiz_slot", "Telsiz slot no", "Frekans ve mod", kosul=_DIJITAL_K),
    _a("telsiz_grup", "Telsiz grup no", "Frekans ve mod", kosul=_DIJITAL_K),
    # Simpleks
    _a("simpleks", "Simpleks kullanımı", "Simpleks", "secim", secenekler=("VAR", "YOK")),
    _a("simpleks_frekans", "Simpleks frekans (MHz)", "Simpleks", "frekans", kosul=_SIMP),
    _a(
        "simpleks_analog_ton",
        "Simpleks analog RX / TX ton",
        "Simpleks",
        kosul={**_SIMP, "mod": list(_ANALOG)},
    ),
    _a(
        "simpleks_dijital_cc",
        "Simpleks dijital CC",
        "Simpleks",
        kosul={**_SIMP, "mod": list(_DIJITAL)},
    ),
    _a(
        "simpleks_dijital_slot",
        "Simpleks dijital slot no",
        "Simpleks",
        kosul={**_SIMP, "mod": list(_DIJITAL)},
    ),
    _a(
        "simpleks_dijital_grup",
        "Simpleks dijital grup no",
        "Simpleks",
        kosul={**_SIMP, "mod": list(_DIJITAL)},
    ),
    # Telsizler
    _a("el_telsizi", "El telsizi sayısı", "Telsizler", "sayi"),
    _a("arac_telsizi", "Araç telsizi sayısı", "Telsizler", "sayi"),
    _a("sabit_telsiz", "Sabit telsiz sayısı", "Telsizler", "sayi"),
]
_TANIM = {a["kod"]: a for a in ALANLAR}
KISISEL_ALANLAR = ("sorumlu_ad", "sorumlu_telefon", "sorumlu_eposta")
_FREKANS = re.compile(r"^\d{1,4}([.,]\d{1,5})?$")
_AZAMI = 500


class RoleMontajEksikHatasi(ServisHatasi):
    """Eksik montaj bilgisiyle kapanış (409)."""


def nitelik_sorulur_mu(birim: str, tur: str) -> bool:
    return birim == BIRIM and tur not in SAHA_DISI_TURLER


def nitelik_dogrula(
    birim: str, tur: str, nitelikler: list[str] | None, *, zorunlu: bool
) -> list[str] | None:
    """Saklanacak nitelik listesi. Haberleşme saha işi değilse None (gönderilen
    nitelik 400). `zorunlu` (ekran açılışı/düzeltme) değilse boş liste türden
    varsayılana döner."""
    if not nitelik_sorulur_mu(birim, tur):
        if nitelikler:
            raise ServisGirdiHatasi("İşin niteliği yalnız Haberleşme saha işinde seçilir")
        return None
    secili: list[str] = []
    for n in nitelikler or []:
        if n not in NITELIK_ADLARI:
            raise ServisGirdiHatasi(f"Bilinmeyen iş niteliği: {n}")
        if n not in secili:
            secili.append(n)
    if not secili:
        if zorunlu:
            raise ServisGirdiHatasi("Haberleşme saha işinde işin niteliği seçilmeli")
        secili = [TUR_NITELIGI.get(tur, "DIGER")]
    return [n for n in HABERLESME_NITELIKLERI if n in secili]


def uygulanir_mi(so: ServiceOrder) -> bool:
    """Haberleşme kurulum/montaj işi mi (tür KURULUM ya da nitelikte KURULUM/MONTAJ)."""
    if not nitelik_sorulur_mu(so.birim, so.tur):
        return False
    return so.tur == "KURULUM" or bool(set(so.nitelikler or ()) & set(MONTAJ_NITELIKLERI))


def _dolu(v: Any) -> bool:
    return v is not None and str(v).strip() != ""


def gorunur_mu(tanim: dict[str, Any], degerler: dict[str, Any]) -> bool:
    kosul = tanim.get("kosul")
    if not kosul:
        return True
    if degerler.get(kosul["alan"]) not in kosul["degerler"]:
        return False
    mod = kosul.get("mod")
    return mod is None or degerler.get("calisma_modu") in mod


def eksik_alanlar(degerler: dict[str, Any]) -> list[str]:
    """Doldurulmamış zorunlu alanların adları (ekran sırasıyla)."""
    return [
        a["ad"]
        for a in ALANLAR
        if a["zorunlu"] and gorunur_mu(a, degerler) and not _dolu(degerler.get(a["kod"]))
    ]


def toplam_telsiz(degerler: dict[str, Any]) -> int | None:
    parcalar = [degerler.get(k) for k in ("el_telsizi", "arac_telsizi", "sabit_telsiz")]
    if not all(isinstance(p, int) for p in parcalar):
        return None
    return sum(parcalar)


def temizle(girdi: dict[str, Any]) -> dict[str, Any]:
    """Girdiyi tanımlara göre doğrular; bilinmeyen alan/biçim → ServisGirdiHatasi.

    Boş değer silinir (kısmi kayıt serbest; zorunluluk kapanışta aranır).
    """
    temiz: dict[str, Any] = {}
    for kod, deger in girdi.items():
        tanim = _TANIM.get(kod)
        if tanim is None:
            raise ServisGirdiHatasi(f"Bilinmeyen alan: {kod}")
        if not _dolu(deger):
            continue
        ad, tip = tanim["ad"], tanim["tip"]
        if tip == "sayi":
            try:
                sayi = int(str(deger).strip())
            except ValueError:
                raise ServisGirdiHatasi(f"{ad}: tam sayı olmalı") from None
            if sayi < 0 or sayi > 100000:
                raise ServisGirdiHatasi(f"{ad}: 0 ile 100000 arasında olmalı")
            temiz[kod] = sayi
            continue
        metin = str(deger).strip()
        if len(metin) > _AZAMI:
            raise ServisGirdiHatasi(f"{ad}: en çok {_AZAMI} karakter")
        if tip == "tarih":
            try:
                metin = date.fromisoformat(metin[:10]).isoformat()
            except ValueError:
                raise ServisGirdiHatasi(f"{ad}: tarih YYYY-AA-GG biçiminde olmalı") from None
        elif tip == "frekans":
            if not _FREKANS.match(metin):
                raise ServisGirdiHatasi(f"{ad}: frekans MHz olarak yazılmalı (örn. 427.1125)")
            metin = metin.replace(",", ".")
        elif tip == "secim" and metin not in tanim["secenekler"]:
            raise ServisGirdiHatasi(f"{ad}: geçersiz seçim")
        temiz[kod] = metin
    return temiz


async def _kayit(db: AsyncSession, so: ServiceOrder) -> ServiceRoleMontaj | None:
    return await db.scalar(
        select(ServiceRoleMontaj).where(ServiceRoleMontaj.service_order_id == so.id)
    )


async def oneriler(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    """Kayıt yokken işten doldurulan başlangıç değerleri (kaydedilmez)."""
    oneri: dict[str, Any] = {}
    if so.customer_id is not None:
        hesap = await db.get(Account, so.customer_id)
        if hesap is not None:
            oneri["firma_adi"] = hesap.title
    if so.address_id is not None:
        adres = await db.get(Address, so.address_id)
        if adres is not None:
            if adres.site_name:
                oneri["proje_adi"] = adres.site_name
            parca = [adres.line, adres.district, adres.city]
            metin = ", ".join(p for p in parca if p)
            if metin:
                oneri["adres"] = metin
    ekip = [a for a in await atama.aktif_ekip(db, so) if a.rol != "SEF"]
    if ekip:
        adlar = (
            await db.scalars(select(User.full_name).where(User.id.in_({a.user_id for a in ekip})))
        ).all()
        if adlar:
            oneri["montaj_yapan"] = ", ".join(sorted(adlar))
    from app.services.teknik_servis import is_emirleri

    seriler = await is_emirleri.aktif_seriler(db, so)
    if len(seriler) == 1:
        oneri["role_seri_no"] = seriler[0].seri_no
    return oneri


async def durum(db: AsyncSession, so: ServiceOrder) -> dict[str, Any]:
    """Ekran için: uygulanır mı, tanımlar, değerler, eksikler, version."""
    kayit = await _kayit(db, so)
    uygulanir = uygulanir_mi(so)
    if kayit is not None:
        degerler = dict(kayit.alanlar)
    elif so.birim == BIRIM:
        degerler = await oneriler(db, so)
    else:
        degerler = {}
    return {
        "uygulanir": uygulanir,
        "kayitli": kayit is not None,
        "version": kayit.version if kayit is not None else None,
        "alanlar": ALANLAR,
        "degerler": degerler,
        "toplam_telsiz": toplam_telsiz(degerler),
        "eksikler": eksik_alanlar(degerler if kayit is not None else {}) if uygulanir else [],
    }


async def eksikler(db: AsyncSession, so: ServiceOrder) -> list[str] | None:
    """Uygulanmıyorsa None; uygulanıyorsa eksik alan adları (boş = tamam)."""
    if not uygulanir_mi(so):
        return None
    kayit = await _kayit(db, so)
    return eksik_alanlar(dict(kayit.alanlar) if kayit is not None else {})


async def kapanis_dogrula(db: AsyncSession, so: ServiceOrder) -> None:
    """Tek durum kapısından (KAPATILDI) çağrılır; eksik varsa 409."""
    eksik = await eksikler(db, so)
    if eksik:
        ilk = ", ".join(eksik[:5]) + (f" ve {len(eksik) - 5} alan daha" if len(eksik) > 5 else "")
        raise RoleMontajEksikHatasi(
            f"Haberleşme kurulum/montaj işi röle montaj bilgileri tamamlanmadan kapatılamaz. "
            f"Eksik: {ilk}"
        )


async def kaydet(
    db: AsyncSession,
    so: ServiceOrder,
    girdi: dict[str, Any],
    *,
    version: int | None,
    user: User,
    clock: Clock,
) -> ServiceRoleMontaj:
    """Tümünü yazar (gönderilmeyen alan silinir). İlk kayıtta version None;
    sonrakilerde eski version → ServisHatasi (409)."""
    if so.birim != BIRIM:
        raise ServisGirdiHatasi("Röle montaj bilgileri yalnız Haberleşme işlerinde tutulur")
    if so.is_deleted or so.status in ("KAPATILDI", "IPTAL"):
        raise ServisHatasi("Kapanmış ya da iptal edilmiş işin montaj bilgileri değiştirilemez")
    temiz = temizle(girdi)
    kayit = await _kayit(db, so)
    if kayit is None:
        if version is not None:
            raise ServisHatasi("Kayıt bulunamadı; sayfayı yenileyin")
        kayit = ServiceRoleMontaj(
            service_order_id=so.id, alanlar=temiz, created_by=user.id, updated_by=user.id
        )
        db.add(kayit)
    else:
        if version != kayit.version:
            raise ServisHatasi("Montaj bilgileri başka biri tarafından değişmiş; sayfayı yenileyin")
        kayit.alanlar = temiz
        kayit.updated_by = user.id
    await db.flush()
    eksik = eksik_alanlar(temiz)
    await gecmis.olay_yaz(
        db,
        so,
        "NOT",
        "Röle montaj bilgileri güncellendi"
        + (f" ({len(eksik)} zorunlu alan eksik)" if eksik else " (tamam)"),
        user=user,
        clock=clock,
        veri={"role_montaj_eksik": len(eksik)},
    )
    return kayit


def denetim_degeri(alanlar: dict[str, Any]) -> dict[str, Any]:
    """Denetim izine kişisel alanlar yazılmaz."""
    return {k: v for k, v in alanlar.items() if k not in KISISEL_ALANLAR}
