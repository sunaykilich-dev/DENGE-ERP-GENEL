"""Uç taraması: `{id}` yollu her teknik servis ucunda kapsam dışı kayıt → 404 ve
veri DEĞİŞMEZ (TS-013, plan §4.5).

**Neden:** canlıdaki kapsam açığı tam olarak buydu (`test_kapsam_guvenligi`):
liste uçları süzülüyordu ama tek kayıt uçları `db.get()` ile kaydı alıp
kapsamı hiç sormuyordu — yanıt 404 bile olsa yazma GEÇMİŞTİ. Teknik servis
yüzlerce `{id}` ucu getiriyor; her biri için bu testi elle yazmak unutulmaya
mahkûmdu. Tarama uçları `app.routes`'tan bulur, yoldaki parametre ADINDAN
hedef kaydı kurar, kapsam dışı kullanıcıyla çağırır ve kaydın hiçbir
kolonunun, ilişkili tabloların ve denetim izinin değişmediğini doğrular.

**Parametre adı sözleşmesi** (yeni uç bu adları kullanır; yoksa tarama
"hedef tanımsız" der ve kırmızı olur — sessizce atlamaz):

| Parametre | Hedef | Kapsam türü |
|---|---|---|
| `so_id`, `is_id`, `servis_isi_id` | servis işi (başka birim) | birim |
| `ekipman_id` | servis ekipmanı (başka birim) | birim |
| `sozlesme_id` | bakım sözleşmesi (başka birim) | birim |
| `personel_id` | personel (başka birim) | birim |
| `hesap_id`, `musteri_id` | hesap (başka temsilcinin) | müşteri |
| `lokasyon_id`, `adres_id` | tesis (başka temsilcinin hesabı) | müşteri |
| `kisi_id` | irtibat (başka temsilcinin hesabı) | müşteri |
| `takma_ad_id` | takma ad (başka temsilcinin hesabı) | müşteri |
| `arac_id` | servis aracı (başka birim) | birim |
| `kiralama_id` | kiralama (başka birim) | birim |
| `kiralik_id` | kiralık seri cihaz (başka birim) | birim |
| `katalog_id` | kiralık katalog profili (başka birim) | birim |
| `tahsis_id` | kiralama tahsisi (başka birimin kiralaması) | birim |

Yalın `{id}` yolun önekinden çözülür (`_ONEK_HEDEFLERI`). Gövdeli uçlarda
gövde modelin `json_schema_extra` örneğinden ya da şemadan üretilir; 422
alınırsa modele örnek eklenmesi istenir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import func, inspect, select
from yetki_tarama import cagir, ts_ucu_mu, uclar, yol_doldur, yol_parametreleri

from app.models import (
    Account,
    AccountAlias,
    Address,
    AuditLog,
    Contact,
    ServiceOrderEvent,
    ServiceVehicle,
    UserUnit,
)
from app.permissions import PERMISSIONS

pytestmark = [pytest.mark.integration, pytest.mark.kapsam_taramasi]

_PARAM_HEDEFLERI = {
    "so_id": "servis_isi",
    "is_id": "servis_isi",
    "servis_isi_id": "servis_isi",
    "ekipman_id": "ekipman",
    "sozlesme_id": "sozlesme",
    "personel_id": "personel",
    "hesap_id": "hesap",
    "musteri_id": "hesap",
    "lokasyon_id": "lokasyon",
    "adres_id": "lokasyon",
    "kisi_id": "irtibat",
    "takma_ad_id": "takma_ad",
    "arac_id": "arac",
    "kiralama_id": "kiralama",
    "kiralik_id": "kiralik",
    "katalog_id": "katalog",
    "tahsis_id": "tahsis",
    "yonlendirme_id": "yonlendirme",
    "kod": "kiralik",  # kiralık cihaz karekodu
}
# Kimlik yerine başka alanla adreslenen parametreler.
_PARAM_ALANI = {"kod": "etiket_kodu"}

# Yalın `{id}` için önek → hedef (uzun önek önce).
_ONEK_HEDEFLERI = (
    ("/api/teknik-servis/bakim/sozlesmeler/", "sozlesme"),
    ("/api/teknik-servis/ekipman/", "ekipman"),
    ("/api/teknik-servis/isler/", "servis_isi"),
    ("/api/personel/", "personel"),
    ("/api/lokasyonlar/", "lokasyon"),
)

_BIRIM_HEDEFLERI = {
    "servis_isi",
    "ekipman",
    "sozlesme",
    "personel",
    "arac",
    "kiralama",
    "kiralik",
    "katalog",
    "tahsis",
    "yonlendirme",
}

# Yazma sızıntısını yakalamak için sayılan tablolar: kaydın kendisi dışında
# kapsam dışı bir uç bunlara satır ekleyebilir/silebilir.
_SAYILAN = (AuditLog, Address, Contact, AccountAlias, UserUnit, ServiceOrderEvent)


@dataclass
class Ortam:
    birim_istemci: Any = None
    musteri_istemci: Any = None
    hedefler: dict[str, Any] = field(default_factory=dict)


def _hedef_turu(yol: str, param: str) -> str | None:
    if param in _PARAM_HEDEFLERI:
        return _PARAM_HEDEFLERI[param]
    if param == "id":
        for onek, tur in _ONEK_HEDEFLERI:
            if yol.startswith(onek):
                return tur
    return None


async def _anlik(db, kayit) -> dict[str, Any]:
    db.expire(kayit)
    await db.refresh(kayit)
    kolonlar = {a.key: getattr(kayit, a.key) for a in inspect(kayit).mapper.column_attrs}
    for model in _SAYILAN:
        kolonlar[f"#{model.__tablename__}"] = await db.scalar(
            select(func.count()).select_from(model)
        )
    return kolonlar


async def _giris(client, username: str):
    import httpx

    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return ist


async def _kiralama_hedefleri(db, musteri) -> dict[str, Any]:
    """HABERLESME birimli kiralık katalog profili, seri cihaz, kiralama ve
    tahsis (ORM ile; akış kuralları kiralama testlerinde sınanır)."""
    from datetime import date

    from app.models import (
        Product,
        Rental,
        RentalAllocation,
        RentalAsset,
        RentalCatalogItem,
        RentalItem,
        Warehouse,
    )

    depo = Warehouse(code="TRZ-KIR", name="Tarama Kiralık Deposu", kiralama_deposu=True)
    urun = Product(code="TRZ-KIR-SERI", name="Tarama Kiralık Telsiz", identity_kind="SERI_NO")
    db.add_all([depo, urun])
    await db.flush()
    katalog = RentalCatalogItem(product_id=urun.id, birim="HABERLESME", kategori="Tarama")
    kiralik = RentalAsset(
        product_id=urun.id,
        serial_no="TRZ-0001",
        serial_key="TRZ0001",
        birim="HABERLESME",
        etiket_kodu="TRZ-ETIKET-1",
        warehouse_id=depo.id,
    )
    kiralama = Rental(
        rental_no="KIR-202611-999901",
        birim="HABERLESME",
        customer_id=musteri.id,
        baslangic=date(2026, 11, 1),
        bitis=date(2026, 11, 5),
        status="PLANLANDI",
    )
    db.add_all([katalog, kiralik, kiralama])
    await db.flush()
    kalem = RentalItem(rental_id=kiralama.id, product_id=urun.id, qty=1)
    db.add(kalem)
    await db.flush()
    tahsis = RentalAllocation(
        rental_id=kiralama.id,
        rental_item_id=kalem.id,
        product_id=urun.id,
        asset_id=kiralik.id,
        from_warehouse_id=depo.id,
        qty=1,
        baslangic=kiralama.baslangic,
        bitis=kiralama.bitis,
    )
    db.add(tahsis)
    from app.models import ServisYonlendirme

    yonlendirme = ServisYonlendirme(kaynak="KIRALAMA", rental_id=kiralama.id, birim="HABERLESME")
    db.add(yonlendirme)
    await db.commit()
    return {
        "kiralama": kiralama,
        "kiralik": kiralik,
        "katalog": katalog,
        "tahsis": tahsis,
        "yonlendirme": yonlendirme,
    }


@pytest.fixture
async def ortam(
    client,
    db,
    rol_ac,
    kullanici_ac,
    birimli_kullanici_ac,
    servis_isi_ac,
    ekipman_ac,
    sozlesme_ac,
    lokasyon_ac,
):
    """İki aktör: GUVENLIK birimli şef (bütün izinler, KENDI_BIRIMI) ve
    satış temsilcisi (bütün izinler, KENDI_MUSTERILERI). Hedefler HABERLESME
    biriminde ve başka bir temsilcinin portföyünde. Aktörlere BÜTÜN izinler
    verilir ki 404'ün nedeni izin değil yalnız kapsam olsun."""
    tum = list(PERMISSIONS)
    await rol_ac("T_TARAMA_BIRIM", tum, "KENDI_BIRIMI")
    await rol_ac("T_TARAMA_MUSTERI", tum, "KENDI_MUSTERILERI")
    await rol_ac("T_HEDEF", ["servis.gor"], "KENDI_BIRIMI")

    await birimli_kullanici_ac("tarayici_birim", "T_TARAMA_BIRIM", ["GUVENLIK"])
    await kullanici_ac("tarayici_musteri", "T_TARAMA_MUSTERI")
    diger_temsilci = await kullanici_ac("diger_temsilci", "T_HEDEF")

    yabanci = Account(title="Yabancı Portföy A.Ş.", is_musteri=True, sales_rep_id=diger_temsilci.id)
    db.add(yabanci)
    await db.commit()
    tesis = await lokasyon_ac(yabanci, ad="Yabancı Tesis")
    irtibat = Contact(account_id=yabanci.id, full_name="Yabancı Kişi", address_id=tesis.id)
    takma = AccountAlias(account_id=yabanci.id, alias_text="YABANCI PORTFOY", kaynak="ELLE")
    arac = ServiceVehicle(plate="34 HAB 001", birim="HABERLESME")
    db.add_all([irtibat, takma, arac])
    await db.commit()
    kiralama_hedefleri = await _kiralama_hedefleri(db, yabanci)

    o = Ortam()
    o.hedefler = {
        "servis_isi": await servis_isi_ac(birim="HABERLESME"),
        "ekipman": await ekipman_ac(birim="HABERLESME"),
        "sozlesme": await sozlesme_ac(birim="HABERLESME"),
        "personel": await birimli_kullanici_ac("hedef_personel", "T_HEDEF", ["HABERLESME"]),
        "hesap": yabanci,
        "lokasyon": tesis,
        "irtibat": irtibat,
        "takma_ad": takma,
        "arac": arac,
        **kiralama_hedefleri,
    }
    o.birim_istemci = await _giris(client, "tarayici_birim")
    o.musteri_istemci = await _giris(client, "tarayici_musteri")
    yield o
    await o.birim_istemci.aclose()
    await o.musteri_istemci.aclose()


def _taranacaklar(app) -> tuple[list[tuple[Any, dict[str, str]]], list[str]]:
    taranacak, tanimsiz = [], []
    for uc in uclar(app):
        if not ts_ucu_mu(uc.yol):
            continue
        parametreler = yol_parametreleri(uc.yol)
        if not parametreler:
            continue
        eslesme = {p: t for p in parametreler if (t := _hedef_turu(uc.yol, p))}
        if not eslesme:
            tanimsiz.append(f"{uc.ad} ({', '.join(parametreler)})")
            continue
        taranacak.append((uc, eslesme))
    return taranacak, tanimsiz


async def test_kimlikli_ts_uclarinin_hedefi_tanimli() -> None:
    from app.main import app

    _, tanimsiz = _taranacaklar(app)
    assert not tanimsiz, (
        "Kapsam taraması bu uçların yol parametresini tanımıyor; sözleşmedeki "
        "adlardan birini kullanın:\n" + "\n".join(tanimsiz)
    )


async def test_kapsam_disi_kimlik_404_ve_veri_degismez(ortam, db) -> None:
    from app.main import app

    taranacak, _ = _taranacaklar(app)
    assert taranacak, "taranacak {id} yollu teknik servis ucu bulunamadı"
    hatalar: list[str] = []
    for uc, eslesme in taranacak:
        degerler = {
            p: getattr(ortam.hedefler[t], _PARAM_ALANI.get(p, "id")) for p, t in eslesme.items()
        }
        birim_mi = any(t in _BIRIM_HEDEFLERI for t in eslesme.values())
        istemci = ortam.birim_istemci if birim_mi else ortam.musteri_istemci
        izlenen = [ortam.hedefler[t] for t in dict.fromkeys(eslesme.values())]
        once = [await _anlik(db, k) for k in izlenen]
        r = await cagir(istemci, uc, yol_doldur(uc.yol, degerler))
        sonra = [await _anlik(db, k) for k in izlenen]
        if r.status_code == 422:
            hatalar.append(f"{uc.ad}: 422 — gövde modeline json_schema_extra örneği ekleyin")
        elif r.status_code != 404:
            hatalar.append(f"{uc.ad}: kapsam dışı kayıtta {r.status_code} (404 bekleniyordu)")
        if once != sonra:
            farklar = {
                k: (a.get(k), b.get(k))
                for a, b in zip(once, sonra, strict=True)
                for k in a
                if a.get(k) != b.get(k)
            }
            hatalar.append(f"{uc.ad}: kapsam dışı kayıt DEĞİŞTİ {farklar}")
    assert not hatalar, "\n".join(hatalar)


async def test_tarama_kendini_dogrular(ortam, db) -> None:
    """Kurulan hedefler gerçekten kapsam dışı mı? Kapsam İÇİ kullanıcı için
    aynı hedef görünür olmalı; yoksa tarama boşa 404 sayıyor olurdu."""
    from app.models import User
    from app.services.accounts import kapsam_disinda_mi
    from app.services.teknik_servis import kapsam

    birim_kullanici = await db.scalar(select(User).where(User.username == "tarayici_birim"))
    assert birim_kullanici.birim_kodlari == ["GUVENLIK"]
    assert kapsam.birim_disinda_mi(birim_kullanici, ortam.hedefler["servis_isi"].birim)
    assert not kapsam.birim_disinda_mi(birim_kullanici, "GUVENLIK")
    musteri_kullanici = await db.scalar(select(User).where(User.username == "tarayici_musteri"))
    assert await kapsam_disinda_mi(db, musteri_kullanici, ortam.hedefler["hesap"].id)
