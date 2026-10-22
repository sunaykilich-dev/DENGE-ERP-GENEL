"""Müşteri/lokasyon eşleştirme kararı profili (TS-171, E14-09 Faz 1).

Girdi, Ana Veri Kalitesi ekranından indirilen aday Excel'idir
(`GET /api/teknik-servis/ana-veri/eslestirme/adaylar.xlsx?kaynak=`). Her satır
hesabı ya da tesisi boş bir kayıttır (bakım sözleşmesi ya da Güvenlik
ekipmanı) ve sistemin önerisini taşır. Kullanıcı `Onay (E/H)` sütununu
doldurur, gerekirse hedefi değiştirir ya da yeni tesis adı yazar.

Kurallar (kabul 1-7):

- YALNIZ `Onay=E` satırlar yazılır; onaysız ve boş satır hiçbir tabloya
  dokunmaz (uyarıyla atlanır).
- Hedef hesap müşteri değilse ya da tesis başka hesaba aitse satır HATA →
  karantina. Kayıt zaten BAŞKA bir hesaba bağlıysa satır ÇAKIŞMA'dır
  (varsayılan atla; "belirsiz 409 insana döner").
- Yazılan: kaynak kaydın `account_id/address_id`'si; `Yeni Tesis Adı`
  doluysa `kind='TESIS'` adres (aynı adlı aktif tesis varsa o kullanılır);
  ham müşteri metni ve (tesis bağlandıysa) ham lokasyon metni
  `account_aliases`'e `kaynak='ESLESTIRME'` ile. **Ham metin kolonları
  (`customer_name_raw`, `site_name_raw`, `location_raw`) DEĞİŞMEZ.**
- İdempotent: aynı dosya ikinci kez uygulanırsa 0 satır yazılır.
- Sonuç tablo bazında `{tablo: {yazilan, atlanan, karantina}}` döner.

**Faz 2 (TS-208, E14-09 Faz 2):** kapsam diğer birimlere açılır — her
birimin ekipmanı ve müşterisi ham metinle göç etmiş servis işleri
(`service_orders.customer_name_raw/location_raw`). Faz 2 aday listesi
`faz2_adaylari()` ile (Faz 1 ile aynı `HesapEsleyici` kuralları, aynı Excel
şablonu) üretilir; yükleme yine bu profille ve aynı kurallarla yapılır.
Ekran uçları Faz 1'dedir; Faz 2 adayları `make goc-ana-veri-faz2` ile alınır.
Teklif, kiralama ve atölye kaydı ham müşteri metni taşımaz (müşteri FK
zorunlu açılır), bu yüzden Faz 2'de eşleştirilecek satırları yoktur.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import (
    Account,
    AccountAlias,
    Address,
    MaintenanceContract,
    ServiceEquipment,
    ServiceOrder,
)
from app.services import audit
from app.services.imports.cekirdek import Profil, SatirSonucu, Sutun
from app.services.normalize import clean_cell, tr_normkey
from app.services.teknik_servis import ana_veri

_MODELLER: dict[str, Any] = {
    "maintenance_contracts": MaintenanceContract,
    "service_equipment": ServiceEquipment,
    # Faz 2 (TS-208): göç edilmiş servis işleri (her birim).
    "service_orders": ServiceOrder,
}
# Kayıttaki ham metin alanları (tablo → (müşteri, lokasyon)).
_HAM_ALANLAR = {
    "maintenance_contracts": ("customer_name_raw", "site_name_raw"),
    "service_equipment": ("customer_name_raw", "location_raw"),
    "service_orders": ("customer_name_raw", "location_raw"),
}


def _hesap_alani(tablo: str) -> str:
    """Kaydın hesap FK kolonu (servis işinde `customer_id`)."""
    return "customer_id" if tablo == "service_orders" else "account_id"


# Faz 2 aday kaynakları (Faz 1 kaynakları `veri_kalitesi.ESLESTIRME_KAYNAKLARI`).
FAZ2_KAYNAKLARI: dict[str, str] = {
    "servis_isi": "service_orders",
    "ekipman_diger": "service_equipment",
}

SUTUNLAR = (
    Sutun("tablo", ("Kaynak Tablo",), zorunlu=True, aciklama=", ".join(_MODELLER)),
    Sutun("kayit_id", ("Kaynak Id",), zorunlu=True, aciklama="Kaynak kaydın kimliği."),
    Sutun("ham_musteri", ("Ham Müşteri",), aciklama="Bilgi amaçlı; kayıttan okunur."),
    Sutun("ham_lokasyon", ("Ham Lokasyon",), aciklama="Bilgi amaçlı; kayıttan okunur."),
    Sutun("onerilen_hesap", ("Önerilen Hesap Id",), aciklama="Sistem önerisi."),
    Sutun("onerilen_hesap_ad", ("Önerilen Hesap",), aciklama="Bilgi amaçlı."),
    Sutun("yontem", ("Yöntem",), aciklama="Önerinin yöntemi (TRGM_ONERI yalnız öneridir)."),
    Sutun("onerilen_lokasyon", ("Önerilen Lokasyon Id",), aciklama="Sistem önerisi."),
    Sutun("onerilen_lokasyon_ad", ("Önerilen Lokasyon",), aciklama="Bilgi amaçlı."),
    Sutun("onay", ("Onay (E/H)", "Onay"), ham=True, aciklama="E = onayla. Boş/H = yazma."),
    Sutun("hedef_hesap", ("Hedef Hesap Id",), aciklama="Öneri yerine başka hesap."),
    Sutun("hedef_lokasyon", ("Hedef Lokasyon Id",), aciklama="Öneri yerine başka tesis."),
    Sutun(
        "yeni_tesis", ("Yeni Tesis Adı",), aciklama="Doluysa hedef hesapta bu adla tesis açılır."
    ),
)


def _tamsayi(ham: Any) -> int | None:
    metin = clean_cell(ham)
    if not metin:
        return None
    try:
        return int(float(metin))
    except ValueError as exc:
        raise ValueError(f"sayı bekleniyor: {metin}") from exc


def _onayli(ham: Any) -> bool:
    return tr_normkey((ham or "").strip()) in ("e", "evet", "onay", "x")


class MusteriEslestirmeProfili(Profil):
    kod = "musteri_eslestirme"
    ad = "Müşteri/Lokasyon Eşleştirme (göç)"
    aciklama = (
        "Serbest metin müşteri/tesis kayıtlarının hesaba ve tesise bağlanması. "
        "Aday listesi Ana Veri Kalitesi ekranından indirilir; yalnız Onay=E satırlar yazılır."
    )
    sutunlar = SUTUNLAR

    async def dogrula(self, db: AsyncSession, satirlar: list[dict]) -> list[SatirSonucu]:
        sonuclar: list[SatirSonucu] = []
        takma_hedef: dict[str, tuple[int, int | None]] = {
            t.alias_key: (t.account_id, t.address_id)
            for t in (await db.scalars(select(AccountAlias))).all()
        }
        dosyadaki: dict[str, tuple[int, int]] = {}
        gorulen: dict[tuple[str, int], int] = {}

        for sira, ham in enumerate(satirlar, start=1):
            r = SatirSonucu(satir_no=sira, ham={k: clean_cell(v) for k, v in ham.items()})
            tablo = clean_cell(ham.get("tablo"))
            r.veri["tablo"] = tablo
            if not _onayli(ham.get("onay")):
                r.uyarilar.append("Onaylanmadı — satır atlanacak, hiçbir şey yazılmaz")
                r.veri["onay"] = ""
                sonuclar.append(r)
                continue
            r.veri["onay"] = "E"
            if tablo not in _MODELLER:
                r.hatalar.append(f"Kaynak tablo tanınmıyor: {tablo}")
                sonuclar.append(r)
                continue
            try:
                kayit_id = _tamsayi(ham.get("kayit_id"))
                hedef_hesap = _tamsayi(ham.get("hedef_hesap")) or _tamsayi(
                    ham.get("onerilen_hesap")
                )
                hedef_lok = _tamsayi(ham.get("hedef_lokasyon"))
                if hedef_lok is None and not _tamsayi(ham.get("hedef_hesap")):
                    hedef_lok = _tamsayi(ham.get("onerilen_lokasyon"))
            except ValueError as exc:
                r.hatalar.append(str(exc))
                sonuclar.append(r)
                continue
            yeni_tesis = clean_cell(ham.get("yeni_tesis"))[:200]
            r.veri.update(
                {
                    "kayit_id": kayit_id,
                    "hesap_id": hedef_hesap,
                    "adres_id": hedef_lok,
                    "yeni_tesis": yeni_tesis,
                }
            )

            kayit = await db.get(_MODELLER[tablo], kayit_id) if kayit_id else None
            if kayit is None or kayit.is_deleted:
                r.hatalar.append("Kaynak kayıt bulunamadı")
                sonuclar.append(r)
                continue
            if tablo == "service_orders" and kayit.source_system is None:
                # Ekrandan açılan işin müşterisi zaten FK'dir; eşleştirme yalnız göç izidir.
                r.hatalar.append("Yalnız göçle gelmiş servis işi eşleştirilir")
            if (tablo, kayit_id) in gorulen:
                r.hatalar.append(
                    f"Aynı kayıt dosyada iki kez (ilk satır: {gorulen[(tablo, kayit_id)]})"
                )
            gorulen.setdefault((tablo, kayit_id), sira)

            hesap = await db.get(Account, hedef_hesap) if hedef_hesap else None
            if hesap is None or hesap.is_deleted:
                r.hatalar.append("Hedef hesap yok ya da silinmiş")
            elif not hesap.is_musteri:
                r.hatalar.append(f"Hedef hesap müşteri değil: {hesap.title}")
            if hedef_lok is not None and yeni_tesis:
                r.hatalar.append("Hem hedef lokasyon hem yeni tesis adı yazılmış")
            if hedef_lok is not None and hesap is not None:
                adres = await db.get(Address, hedef_lok)
                if adres is None or adres.kind != "TESIS":
                    r.hatalar.append("Hedef lokasyon bir tesis değil")
                elif adres.account_id != hesap.id:
                    r.hatalar.append("Tesis başka hesaba ait")
            if not r.gecerli:
                sonuclar.append(r)
                continue

            musteri_alani, lokasyon_alani = _HAM_ALANLAR[tablo]
            ham_musteri = getattr(kayit, musteri_alani)
            ham_lokasyon = getattr(kayit, lokasyon_alani)
            for metin, adresli in ((ham_musteri, False), (ham_lokasyon, True)):
                anahtar = ana_veri.unvan_anahtari(metin)
                if not anahtar or (adresli and hedef_lok is None and not yeni_tesis):
                    continue
                var = takma_hedef.get(anahtar)
                if var is not None and var[0] != hesap.id:
                    r.hatalar.append(
                        f"'{metin}' yazımı başka bir hesaba bağlı (hesap {var[0]}); "
                        "önce o takma ad incelenmeli"
                    )
                onceki = dosyadaki.get(anahtar)
                if onceki is not None and onceki[0] != hesap.id:
                    r.hatalar.append(
                        f"'{metin}' dosyada başka hesaba da bağlanmış (satır {onceki[1]})"
                    )
                dosyadaki.setdefault(anahtar, (hesap.id, sira))

            mevcut_hesap = getattr(kayit, _hesap_alani(tablo))
            if r.gecerli and mevcut_hesap is not None and mevcut_hesap != hesap.id:
                r.cakisma = {
                    "tip": "farkli_hesap",
                    "kayit_id": kayit.id,
                    "aciklama": (
                        f"Kayıt zaten {mevcut_hesap} numaralı hesaba bağlı. Güncellenirse "
                        "hesap değişir; ham metin korunur."
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
    ) -> dict[str, Any]:
        sayac: dict[str, Any] = self.bos_sayac()
        tablolar: dict[str, dict[str, int]] = {
            t: {"yazilan": 0, "atlanan": 0, "karantina": 0} for t in _MODELLER
        }
        takma_ad_sayisi = 0
        for s in satirlar:
            tablo = (s.get("veri") or {}).get("tablo")
            if tablo in tablolar and s.get("hatalar"):
                tablolar[tablo]["karantina"] += 1

        for satir, _karar in self.uygulanacaklar(satirlar, kararlar):
            veri: dict[str, Any] = satir["veri"]
            tablo = veri.get("tablo")
            if veri.get("onay") != "E" or tablo not in _MODELLER:
                if tablo in tablolar:
                    tablolar[tablo]["atlanan"] += 1
                continue
            kayit = await db.get(_MODELLER[tablo], int(veri["kayit_id"]))
            hesap_id = int(veri["hesap_id"])
            adres_id = (
                int(veri["adres_id"]) if veri.get("adres_id") not in (None, "", "None") else None
            )
            if veri.get("yeni_tesis"):
                adres_id = await _tesis_bul_ya_da_ac(db, hesap_id, veri["yeni_tesis"], user_id)

            musteri_alani, lokasyon_alani = _HAM_ALANLAR[tablo]
            degisti = False
            hesap_alani = _hesap_alani(tablo)
            if getattr(kayit, hesap_alani) != hesap_id:
                setattr(kayit, hesap_alani, hesap_id)
                degisti = True
            if adres_id is not None and kayit.address_id != adres_id:
                kayit.address_id = adres_id
                degisti = True
            if degisti:
                kayit.updated_by = user_id
                await audit.log_change(db, kayit, "eslestirme.uygula", user_id=user_id)

            yeni_takma = await _takma_ad(
                db, hesap_id, None, getattr(kayit, musteri_alani), tablo, user_id
            )
            if adres_id is not None:
                yeni_takma += await _takma_ad(
                    db, hesap_id, adres_id, getattr(kayit, lokasyon_alani), tablo, user_id
                )
            takma_ad_sayisi += yeni_takma
            await db.flush()
            if degisti or yeni_takma:
                tablolar[tablo]["yazilan"] += 1
                sayac["guncellendi"] += 1
            else:
                tablolar[tablo]["atlanan"] += 1

        sayac["atlandi"] = len(satirlar) - sayac["guncellendi"]
        sayac["takma_ad"] = takma_ad_sayisi
        sayac["tablolar"] = tablolar
        return sayac


async def _tesis_bul_ya_da_ac(db: AsyncSession, hesap_id: int, ad: str, user_id: int | None) -> int:
    """Hesapta aynı anahtarlı aktif tesis varsa onu döner, yoksa açar."""
    anahtar = ana_veri.unvan_anahtari(ad)
    mevcut = await db.scalar(
        select(Address.id).where(
            Address.account_id == hesap_id,
            Address.kind == "TESIS",
            Address.is_active.is_(True),
            Address.site_key == anahtar,
        )
    )
    if mevcut is not None:
        return mevcut
    adres = Address(
        account_id=hesap_id,
        kind="TESIS",
        label="Tesis",
        site_name=ad,
        is_verified=False,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(adres)
    await db.flush()
    await audit.log(
        db,
        "addresses",
        "eslestirme.tesis_ac",
        entity_id=adres.id,
        new_value={"hesap_id": hesap_id, "tesis": ad},
        user_id=user_id,
    )
    return adres.id


async def _takma_ad(
    db: AsyncSession,
    hesap_id: int,
    adres_id: int | None,
    metin: str | None,
    tablo: str,
    user_id: int | None,
) -> int:
    """Ham metni takma ad olarak ekler; zaten varsa ya da unvanın kendisiyse 0."""
    anahtar = ana_veri.unvan_anahtari(metin)
    if not anahtar:
        return 0
    hesap = await db.get(Account, hesap_id)
    if hesap is not None and adres_id is None and ana_veri.unvan_anahtari(hesap.title) == anahtar:
        return 0
    if await db.scalar(select(AccountAlias.id).where(AccountAlias.alias_key == anahtar)):
        return 0
    try:
        takma = await ana_veri.takma_ad_ekle(
            db,
            account_id=hesap_id,
            alias_text=metin,
            kaynak="ESLESTIRME",
            address_id=adres_id,
            kaynak_tablo=tablo,
            user_id=user_id,
        )
    except ana_veri.AnaVeriHatasi:
        return 0
    await audit.log(
        db,
        "account_aliases",
        "eslestirme.takma_ad",
        entity_id=takma.id,
        new_value=ana_veri.takma_ad_satiri(takma) | {"created_at": None},
        user_id=user_id,
    )
    return 1


async def faz2_adaylari(db: AsyncSession, kaynak: str) -> list[dict[str, Any]]:
    """Faz 2 aday listesi (TS-208): hesabı/tesisi boş göç servis işleri ya da Güvenlik
    dışı ekipman. Faz 1 ile aynı öneri sırası (`HesapEsleyici`, belirsizde öneri yok,
    trigram yalnız öneri). Satır sözlüğü `veri_kalitesi.aday_satiri` biçimindedir.
    HİÇBİR ŞEY YAZMAZ. Komut satırı aracıdır (sistem göç sorumlusu; kapsam yok).
    """
    from app.services.teknik_servis import veri_kalitesi as vk

    if kaynak == "servis_isi":
        kayitlar = (
            await db.scalars(
                select(ServiceOrder)
                .where(
                    ServiceOrder.is_deleted.is_(False),
                    ServiceOrder.source_system.is_not(None),
                    (ServiceOrder.customer_id.is_(None)) | (ServiceOrder.address_id.is_(None)),
                )
                .order_by(ServiceOrder.id)
            )
        ).all()
    elif kaynak == "ekipman_diger":
        kayitlar = (
            await db.scalars(
                select(ServiceEquipment)
                .where(
                    ServiceEquipment.is_deleted.is_(False),
                    ServiceEquipment.merged_into_id.is_(None),
                    ServiceEquipment.birim != vk.FAZ1_EKIPMAN_BIRIMI,
                    (ServiceEquipment.account_id.is_(None))
                    | (ServiceEquipment.address_id.is_(None)),
                )
                .order_by(ServiceEquipment.id)
            )
        ).all()
    else:
        raise ValueError(f"Bilinmeyen Faz 2 kaynağı: {kaynak}")
    tablo = FAZ2_KAYNAKLARI[kaynak]
    musteri_alani, lokasyon_alani = _HAM_ALANLAR[tablo]
    hesap_alani = _hesap_alani(tablo)
    esleyici = await vk.hesap_esleyici(db)
    sonuc: list[dict[str, Any]] = []
    trgm: dict[str, int | None] = {}
    for k in kayitlar:
        musteri, lokasyon = getattr(k, musteri_alani), getattr(k, lokasyon_alani)
        hesap_id, adres_id = getattr(k, hesap_alani), k.address_id
        satir: dict[str, Any] = {
            "tablo": tablo,
            "id": k.id,
            "musteri": musteri,
            "lokasyon": lokasyon,
            "hesap_id": hesap_id,
            "adres_id": adres_id,
            "onerilen_hesap_id": hesap_id,
            "onerilen_adres_id": adres_id,
            "yontem": "MEVCUT" if hesap_id else vk.YONTEM_YOK,
            "musterisiz": not (musteri or "").strip() and not (lokasyon or "").strip(),
        }
        if not satir["musterisiz"]:
            es = esleyici.esle(musteri, lokasyon)
            if es.belirsiz:
                satir["yontem"] = f"{vk.YONTEM_BELIRSIZ}: " + ", ".join(map(str, es.adaylar))
            elif es.account_id is not None and hesap_id in (None, es.account_id):
                satir["onerilen_hesap_id"] = es.account_id
                satir["onerilen_adres_id"] = adres_id or es.address_id
                if hesap_id is None:
                    satir["yontem"] = es.yontem
            elif hesap_id is None and (musteri or "").strip():
                anahtar = musteri.strip()
                if anahtar not in trgm:
                    adaylar = await ana_veri.benzer_musteriler(db, anahtar)
                    trgm[anahtar] = adaylar[0]["id"] if adaylar else None
                if trgm[anahtar] is not None:
                    satir["onerilen_hesap_id"] = trgm[anahtar]
                    satir["yontem"] = vk.YONTEM_TRGM
        sonuc.append(satir)
    hesaplar = {r["onerilen_hesap_id"] for r in sonuc if r["onerilen_hesap_id"]}
    adresler = {r["onerilen_adres_id"] for r in sonuc if r["onerilen_adres_id"]}
    hesap_adlari = (
        dict(
            (await db.execute(select(Account.id, Account.title).where(Account.id.in_(hesaplar))))
            .tuples()
            .all()
        )
        if hesaplar
        else {}
    )
    adres_adlari = (
        dict(
            (
                await db.execute(
                    select(Address.id, Address.site_name).where(Address.id.in_(adresler))
                )
            )
            .tuples()
            .all()
        )
        if adresler
        else {}
    )
    for r in sonuc:
        r["onerilen_hesap"] = hesap_adlari.get(r["onerilen_hesap_id"])
        r["onerilen_adres"] = adres_adlari.get(r["onerilen_adres_id"])
    return sonuc


PROFIL = MusteriEslestirmeProfili()
PROFIL_IZNI = "hesap.birlestir"
