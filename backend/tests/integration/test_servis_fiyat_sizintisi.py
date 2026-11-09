"""Fiyat/maliyet sızıntısı taraması — teknik servisin TÜM GET uçları (TS-216, E07-23).

**Neden:** fiyatın "varsayılan gizli" olması (KD-11) tek tek uçlarda
`sees_cost` kontrolüyle sağlanıyor. Her yeni uç bu kontrolü yeniden yazmak
zorunda; biri unutulduğunda maliyet bir liste ya da kart yanıtında sessizce
görünür (canlıda atölye `repairAmount` tam olarak böyle sızıyordu, A1-02).
Elle yazılmış uç listesi yeni uçları kaçırırdı; bu tarama uçları
`app.routes`'tan bulur, her teknik servis rolüyle çağırır ve JSON yanıtı
özyinelemeli tarar: yasak bir ANAHTAR (değeri `null` olsa bile) bulunursa
test kırmızıdır.

Kurallar:
- `MALIYET_ANAHTARLARI` `maliyet.gor` olmayan hiçbir teknik servis rolünde
  görünmez. Servis rollerinde `maliyet.gor` tek istisna TS Yöneticisidir
  (G4.4, KARARLAR 2026-11-04 §7.7); başka servis rolü alırsa test kırmızı.
- `FIYAT_ANAHTARLARI` (teklif tutarları) yalnız `teklif.gor` sahibine görünür.
- Taranamayan GET ucu (hiçbir rolde 200 alınamayan) `TARANMAYAN` beyaz
  listesinde gerekçesiyle durmak zorunda; yeni uç kendiliğinden taramaya girer.
- Tarama kendini kanıtlar: bir uca `monkeypatch` ile maliyet alanı eklenince
  kırmızıya döner ("ekle → kırmızı").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from yetki_tarama import TS_ONEKLERI, Uc, ornek_sorgu, uclar, yol_doldur

from app.permissions import ROLES, SERVIS_ROLLERI

pytestmark = [pytest.mark.integration, pytest.mark.kapsam_taramasi]

# E07-23 anahtar listesi + gerçek kolon adları (sözleşme ücreti, atölye
# bedeli, stok hareket maliyeti, işçilik tarifesi, iş finansı).
MALIYET_ANAHTARLARI = frozenset(
    {
        "iscilik",
        "malzeme",
        "diger",
        "fark",
        "gelir",
        "hourly_cost",
        "unit_cost_try",
        "unit_cost",
        "landed_cost_try",
        "maliyet",
        "diger_maliyet",
        "fee_per_visit",
        "contract_total",
        "repair_amount",
    }
)
# Teklif tutarları: `teklif.gor` olmayan rolde anahtar olarak YOK.
FIYAT_ANAHTARLARI = frozenset(
    {"grand_total", "subtotal", "unit_price", "line_total", "vat_total", "discount_total"}
)

# Hiçbir servis rolünde 200 alınamayan GET uçları ve gerekçesi. Liste
# BÜYÜMEMELİ: yeni uç buraya değil, taramanın kurduğu veriye göre eklenir.
_AYRI_KURULUM = "kayıt kurulumu modülün kendi testinde; yanıt para alanı taşımaz"
TARANMAYAN: dict[str, str] = {
    "/api/kiralama/sayim": f"kiralama sayımı ({_AYRI_KURULUM}: seri/adet)",
    "/api/kiralama/sayim/fark": f"kiralama sayım farkı ({_AYRI_KURULUM}: seri/adet)",
    "/api/teknik-servis/parca/sayim": (
        "parça sayımı (test_yedek_parca*): sayım yanıtı adet taşır; maliyet anahtarları "
        "stok listesinde taranıyor"
    ),
    "/api/egitim/kurs-yetkinlikleri": f"eğitim kursu ({_AYRI_KURULUM})",
    "/api/egitim/oturumlar/katilimcilar": f"eğitim oturumu ({_AYRI_KURULUM})",
    "/api/egitim/kisiler/{personel_id}/gozlemler/{gozlem_id}": (
        f"eğitim gözlemi ({_AYRI_KURULUM}; kişisel performans, test_egitim_*)"
    ),
    "/api/teknik-servis/bakim/formlar/{so_id}": (
        "PB işi sözleşme kalemi + dönem ister (ck_so_pb_bag; test_bakim_*); form yanıtı "
        "kontrol listesi, ücret yok"
    ),
    "/api/teknik-servis/bakim/sozlesmeler/{sozlesme_id}/donemler/{donem_id}/cihazlar": (
        "bakım dönemi üretimi (test_bakim_*); yanıt cihaz/ekipman listesi, ücret yok"
    ),
    "/api/teknik-servis/isler/{so_id}/bakim-fisi.pdf": (
        "bakım işi ister (taramanın işi arıza → 409); PDF, JSON değil; fiyat yalnız "
        "fiyatli + maliyet.gor ile basılır (test_irsaliye)"
    ),
    "/api/teknik-servis/parca/fis.pdf": (
        "sahada parça hareketi ister (test_sahada_parca); PDF, fiyat/maliyet basılmaz"
    ),
}

# Zorunlu sorgu parametresi yer tutucuyla (ornek_sorgu) geçersiz kalan uçlar:
# uç → ortamdan sorgu listesi (birden çok değer = her KPI/kontrol ayrı taranır).
SORGU: dict[str, Any] = {
    "/api/personel/atanabilir": lambda o: [{"birim": "GUVENLIK"}],
    # Dönem zorunlu; §7.7 ile TS Yöneticisi (maliyet.gor) bu uçları tarar.
    "/api/teknik-servis/maliyet/analiz": lambda o: [
        {"baslangic": "2026-01-01", "bitis": "2026-12-31"}
    ],
    "/api/teknik-servis/maliyet/analiz.xlsx": lambda o: [
        {"baslangic": "2026-01-01", "bitis": "2026-12-31"}
    ],
    "/api/teknik-servis/maliyet/teklif-donusumu": lambda o: [{"birim": "GUVENLIK"}],
    "/api/teknik-servis/maliyet/teklif-donusumu.xlsx": lambda o: [{"birim": "GUVENLIK"}],
    "/api/teknik-servis/zaman/isler": lambda o: [{"kpi": "sure_eksik"}, {"kpi": "farkli_is"}],
    "/api/teknik-servis/isler/ziyaret-formu.pdf": lambda o: [{"is_id": o.so_id}],
    "/api/teknik-servis/cihaz-servis-isleri": lambda o: [{"cihaz_id": o.kimlikler["cihaz"]}],
    "/api/teknik-servis/atolye/kabul-grubu-fisi.pdf": lambda o: [{"grup_no": 1}],
    "/api/egitim/atama-uyarilari": lambda o: [
        {"so_id": o.so_id, "user_ids": o.kimlikler["personel_id"]}
    ],
    "/api/kiralama/musaitlik": lambda o: [
        {
            "product_id": o.kimlikler["kiralik_urun"],
            "baslangic": "2026-11-01",
            "bitis": "2026-11-05",
        }
    ],
    "/api/teknik-servis/planlama/kpi-liste": lambda o: [{"kod": k} for k in _planlama_kpileri()],
    "/api/teknik-servis/raporlar/kpi-liste": lambda o: [{"kpi": k} for k in _rapor_kpileri()],
    "/api/teknik-servis/ana-veri/veri-kalitesi/liste": lambda o: [
        {"kontrol": k} for k in _kalite_kontrolleri()
    ],
    "/api/teknik-servis/ana-veri/veri-kalitesi/liste.xlsx": lambda o: [
        {"kontrol": k} for k in _kalite_kontrolleri()
    ],
}

# Yol parametresi varsayılan hedef yerine başka kayıt isteyen uçlar.
YOL_HEDEFI: dict[str, dict[str, str]] = {
    "/api/teknik-servis/atolye/{so_id}": {"so_id": "atolye_so"},
    "/api/teknik-servis/atolye/{so_id}/kabul-fisi.pdf": {"so_id": "atolye_so"},
    "/api/teknik-servis/atolye/{so_id}/teslim-tutanagi.pdf": {"so_id": "atolye_so"},
}


def _planlama_kpileri() -> list[str]:
    from app.services.teknik_servis import takvim

    return list(takvim.KPI_TANIMLARI)


def _rapor_kpileri() -> list[str]:
    from app.services.teknik_servis import panel

    return list(panel.KPI_TANIMLARI)


def _kalite_kontrolleri() -> list[str]:
    from app.services.teknik_servis import rapor_kalite

    return list(rapor_kalite.KONTROLLER)


# Aynı adı taşıyan ama para OLMAYAN alanlar: (uç, JSON yolu kalıbı) → gerekçe.
# Yol kalıbında liste indeksleri `[]` olarak yazılır. Yalnız yaprak alan adı
# değil TAM yol eşleşir: aynı uçta başka bir yere `fark` eklenirse yine kırmızı.
ANLAM_FARKLI: dict[tuple[str, str], str] = {
    ("/api/teknik-servis/raporlar/ozet", "$.kpiler[].fark"): (
        "KPI'nin önceki döneme göre farkı (adet/oran), para değil"
    ),
    ("/api/teknik-servis/raporlar/ozet", "$.olcumler[].fark"): (
        "ölçümün önceki döneme göre farkı (adet/oran), para değil"
    ),
}


def _kalip(yol: str) -> str:
    import re

    return re.sub(r"\[\d+\]", "[]", yol)


def yasak_anahtarlar(veri: Any, yasak: frozenset[str], yol: str = "$") -> list[str]:
    """Yanıtta (iç içe) yasak anahtarların JSON yolu."""
    bulunan: list[str] = []
    if isinstance(veri, dict):
        for anahtar, deger in veri.items():
            alt = f"{yol}.{anahtar}"
            if anahtar in yasak:
                bulunan.append(alt)
            bulunan += yasak_anahtarlar(deger, yasak, alt)
    elif isinstance(veri, list):
        for i, deger in enumerate(veri[:50]):
            bulunan += yasak_anahtarlar(deger, yasak, f"{yol}[{i}]")
    return bulunan


# Servis rollerinde `maliyet.gor` tek istisnası (G4.4, §7.7).
MALIYET_GOREN_SERVIS_ROLLERI = frozenset({"SERVIS_YONETICI"})


def rol_yasaklari(rol: str) -> frozenset[str]:
    izinler = set(ROLES[rol][1])
    fiyat = frozenset() if "teklif.gor" in izinler else FIYAT_ANAHTARLARI
    if "maliyet.gor" in izinler:
        assert rol in MALIYET_GOREN_SERVIS_ROLLERI, f"{rol} maliyet.gor almış (KD-11, §7.7)"
        return fiyat
    return MALIYET_ANAHTARLARI | fiyat


@dataclass
class Ortam:
    istemciler: dict[str, httpx.AsyncClient] = field(default_factory=dict)
    kimlikler: dict[str, int] = field(default_factory=dict)
    so_id: int = 0


async def _oturum(username: str) -> httpx.AsyncClient:
    from app.main import app

    ist = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
    r = await ist.post("/api/auth/login", json={"username": username, "password": "parola1234"})
    assert r.status_code == 200, r.text
    return ist


async def _kiralama(db, musteri) -> dict[str, int]:
    from app.models import Product, Rental, RentalAsset, RentalCatalogItem, Warehouse

    depo = Warehouse(code="FS-KIR", name="Sızıntı Kiralık Deposu", kiralama_deposu=True)
    urun = Product(code="FS-KIR-SERI", name="Sızıntı Kiralık Telsiz", identity_kind="SERI_NO")
    db.add_all([depo, urun])
    await db.flush()
    db.add(RentalCatalogItem(product_id=urun.id, birim="GUVENLIK", kategori="Sızıntı"))
    kiralik = RentalAsset(
        product_id=urun.id,
        serial_no="FS-0001",
        serial_key="FS0001",
        birim="GUVENLIK",
        warehouse_id=depo.id,
    )
    kiralama = Rental(
        rental_no="KIR-202611-888801",
        birim="GUVENLIK",
        customer_id=musteri.id,
        baslangic=date(2026, 11, 1),
        bitis=date(2026, 11, 5),
        status="PLANLANDI",
    )
    db.add_all([kiralik, kiralama])
    await db.commit()
    return {"kiralama": kiralama.id, "kiralik": kiralik.id, "kiralik_urun": urun.id}


async def _atolye(db, servis_isi_ac, ekipman, musteri, tesis) -> int:
    """Atölye işi + kaydı (tamir bedeli dolu: TS-092 alanı taramaya girsin)."""
    from datetime import UTC, datetime

    from app.models import WorkshopRecord

    so = await servis_isi_ac(
        birim="GUVENLIK",
        musteri=musteri,
        lokasyon=tesis,
        tur="ATOLYE",
        durum="ATOLYEDE",
        equipment_id=ekipman.id,
    )
    db.add(
        WorkshopRecord(
            atolye_no="AT-202611-999901",
            service_order_id=so.id,
            equipment_id=ekipman.id,
            intake_group_no=1,
            service_type="ARIZA_ONARIMI",
            received_at=datetime(2026, 1, 5, 9, tzinfo=UTC),
            receive_type="ELDEN",
            customer_complaint="Açılmıyor",
            repair_amount=Decimal("750.00"),
        )
    )
    await db.commit()
    return so.id


@pytest.fixture
async def ortam(
    client,
    db,
    birimli_kullanici_ac,
    servis_isi_ac,
    ekipman_ac,
    sozlesme_ac,
    lokasyon_ac,
    cihaz_ac,
):
    """Her servis rolünden bir GUVENLIK kullanıcısı; maliyet ve fiyat taşıyan
    GUVENLIK kayıtları (iş finansı, sözleşme ücreti, teklif)."""
    from app.models import Account, ServiceOrderFinancial

    kullanicilar = {}
    for rol in SERVIS_ROLLERI:
        saha = {"SERVIS_SEF": "SEF", "SERVIS_TEKNISYEN": "TEKNISYEN"}.get(rol)
        kullanicilar[rol] = await birimli_kullanici_ac(
            f"fs_{rol.lower()}", rol, ["GUVENLIK"], saha_rolu=saha
        )
    musteri = Account(title="Sızıntı Müşterisi A.Ş.", is_musteri=True, email="m@example.com")
    db.add(musteri)
    await db.commit()
    tesis = await lokasyon_ac(musteri, ad="Sızıntı Tesisi")
    so = await servis_isi_ac(
        birim="GUVENLIK",
        musteri=musteri,
        lokasyon=tesis,
        atananlar=[kullanicilar["SERVIS_TEKNISYEN"]],
    )
    db.add(
        ServiceOrderFinancial(
            service_order_id=so.id,
            gelir=Decimal("1500.00"),
            gelir_kaynagi="ELLE",
            gelir_notu="sızıntı testi",
            diger_maliyet=Decimal("250.00"),
            diger_maliyet_notu="sızıntı testi",
        )
    )
    await db.commit()
    ekipman = await ekipman_ac(birim="GUVENLIK", musteri=musteri, lokasyon=tesis)
    sozlesme = await sozlesme_ac(
        birim="GUVENLIK",
        musteri=musteri,
        lokasyon=tesis,
        fee_per_visit=Decimal("900.00"),
        contract_total=Decimal("3600.00"),
    )
    kiralama = await _kiralama(db, musteri)
    atolye_so = await _atolye(db, servis_isi_ac, ekipman, musteri, tesis)
    cihaz = await cihaz_ac(imei="861111111111119", current_customer_id=musteri.id)

    o = Ortam()
    for rol, k in kullanicilar.items():
        o.istemciler[rol] = await _oturum(k.username)
    # Teklif (fiyatlı) işe bağlı — müdür açar.
    r = await o.istemciler["SERVIS_YONETICI"].post(
        "/api/teklifler",
        json={
            "customer_id": musteri.id,
            "birim": "GUVENLIK",
            "service_order_id": so.id,
            "kalemler": [
                {
                    "item_type": "HIZMET",
                    "description": "Onarım işçiliği",
                    "qty": 1,
                    "unit_price": 1000,
                    "vat_rate": 0.20,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    o.so_id = so.id
    o.kimlikler = {
        "so_id": so.id,
        "is_id": so.id,
        "servis_isi_id": so.id,
        "ekipman_id": ekipman.id,
        "sozlesme_id": sozlesme.id,
        "personel_id": kullanicilar["SERVIS_TEKNISYEN"].id,
        "hesap_id": musteri.id,
        "musteri_id": musteri.id,
        "lokasyon_id": tesis.id,
        "kiralama_id": kiralama["kiralama"],
        "kiralik_id": kiralama["kiralik"],
        "kiralik_urun": kiralama["kiralik_urun"],
        "atolye_so": atolye_so,
        "cihaz": cihaz.id,
    }
    yield o
    for ist in o.istemciler.values():
        await ist.aclose()


def _get_uclari() -> list[Uc]:
    from app.main import app

    return [u for u in uclar(app) if u.yontem == "GET" and u.yol.startswith(TS_ONEKLERI)]


def _degerler(o: Ortam, uc: Uc) -> dict[str, int]:
    degerler = dict(o.kimlikler)
    if "{id}" in uc.yol and uc.yol.startswith("/api/teknik-servis/bakim/sozlesmeler/"):
        degerler["id"] = o.kimlikler["sozlesme_id"]
    for param, hedef in YOL_HEDEFI.get(uc.yol, {}).items():
        degerler[param] = o.kimlikler[hedef]
    return degerler


def _sorgular(o: Ortam, uc: Uc) -> list[dict[str, Any]]:
    uretici = SORGU.get(uc.yol)
    if uretici is None:
        return [ornek_sorgu(uc.rota)]
    return uretici(o)


async def _tara(o: Ortam, ucler: list[Uc]) -> tuple[list[str], set[str], list[str]]:
    """(sızıntılar, 200 alınan uçlar, 5xx hataları)."""
    sizintilar: list[str] = []
    taranan: set[str] = set()
    hatalar: list[str] = []
    for uc in ucler:
        yol = yol_doldur(uc.yol, _degerler(o, uc))
        cagrilar = [
            (rol, sorgu)
            for rol in SERVIS_ROLLERI
            if uc.izinli_mi(set(ROLES[rol][1]))
            for sorgu in _sorgular(o, uc)
        ]
        for rol, sorgu in cagrilar:
            r = await o.istemciler[rol].get(yol, params=sorgu)
            if r.status_code == 503 and uc.yol.endswith(".pdf"):
                # PDF motoru (WeasyPrint) bu makinede yok; içerik zaten JSON
                # değil — uç erişilebilir sayılır (yetki/kapsam geçti).
                taranan.add(uc.yol)
                continue
            if r.status_code >= 500:
                hatalar.append(f"{rol} {uc.ad}: {r.status_code}")
                continue
            if r.status_code != 200:
                continue
            taranan.add(uc.yol)
            if "json" not in r.headers.get("content-type", ""):
                continue
            kaliplar = {_kalip(b) for b in yasak_anahtarlar(r.json(), rol_yasaklari(rol))}
            for kalip in sorted(kaliplar):
                if (uc.yol, kalip) not in ANLAM_FARKLI:
                    sizintilar.append(f"{rol} {uc.ad}: {kalip}")
    return sizintilar, taranan, hatalar


async def test_teknik_servis_get_uclarinda_maliyet_anahtari_yok(ortam) -> None:
    ucler = _get_uclari()
    assert len(ucler) > 100, "tarama uç bulamadı"
    sizintilar, taranan, hatalar = await _tara(ortam, ucler)
    assert not hatalar, "\n".join(hatalar)
    assert not sizintilar, "Yetkisiz rolde maliyet/fiyat anahtarı:\n" + "\n".join(sizintilar)

    # Hiçbir servis rolünün izinli olmadığı uç (ör. maliyet.gor) taranamaz ama
    # açık da değildir; geri kalan her uç en az bir rolde 200 dönmeli.
    izinsiz = {
        u.yol for u in ucler if not any(u.izinli_mi(set(ROLES[r][1])) for r in SERVIS_ROLLERI)
    }
    taranmayan = sorted({u.yol for u in ucler} - taranan - izinsiz - set(TARANMAYAN))
    assert not taranmayan, (
        "Bu GET uçları hiçbir rolde 200 dönmedi, içerikleri taranamadı (veri "
        "kurun ya da TARANMAYAN'a gerekçesiyle ekleyin):\n" + "\n".join(taranmayan)
    )
    gereksiz = sorted(set(TARANMAYAN) & taranan)
    assert not gereksiz, f"TARANMAYAN listesinde artık taranan uç var: {gereksiz}"


async def test_maliyet_uclari_servis_rollerine_kapali(ortam) -> None:
    """`/maliyet/analiz`, iş finansı ve gelir yazımı maliyet.gor ister → 403
    (maliyet.gor sahibi TS Yöneticisi hariç, §7.7)."""
    so = ortam.so_id
    for rol in SERVIS_ROLLERI:
        if rol in MALIYET_GOREN_SERVIS_ROLLERI:
            continue
        ist = ortam.istemciler[rol]
        for yol in (
            "/api/teknik-servis/maliyet/analiz",
            f"/api/teknik-servis/maliyet/isler/{so}",
            "/api/teknik-servis/maliyet/tarifeler",
        ):
            assert (await ist.get(yol)).status_code == 403, f"{rol} {yol}"
        r = await ist.put(
            f"/api/teknik-servis/maliyet/isler/{so}/gelir",
            json={"gelir": 10, "kaynak": "ELLE", "not": "sızıntı", "version": 1},
        )
        assert r.status_code == 403, f"{rol} gelir yazımı {r.status_code}"


async def test_teknisyen_is_detayinda_teklif_tutari_yok(ortam) -> None:
    """Teknisyen işi görür ama bağlı teklifin tutarını göremez; teklif.gor
    sahibi müdür aynı işte teklifi görür (test boşa geçmesin)."""
    tek = ortam.istemciler["SERVIS_TEKNISYEN"]
    r = await tek.get(f"/api/teknik-servis/isler/{ortam.so_id}")
    assert r.status_code == 200, r.text
    assert not yasak_anahtarlar(r.json(), FIYAT_ANAHTARLARI | MALIYET_ANAHTARLARI)
    assert (await tek.get("/api/teklifler")).status_code == 403

    mudur = ortam.istemciler["SERVIS_YONETICI"]
    teklifler = (await mudur.get("/api/teklifler", params={"servis_isi_id": ortam.so_id})).json()
    assert teklifler and teklifler[0]["service_order_id"] == ortam.so_id


async def test_sozlesme_ucreti_alan_olarak_yok(ortam) -> None:
    """Şef sözleşmeyi görür ama ücreti göremez; maliyet.gor sahibi TS
    Yöneticisi aynı sözleşmede ücreti görür (§7.7, test boşa geçmesin)."""
    yol = f"/api/teknik-servis/bakim/sozlesmeler/{ortam.kimlikler['sozlesme_id']}"
    r = await ortam.istemciler["SERVIS_SEF"].get(yol)
    assert r.status_code == 200, r.text
    veri = r.json()
    assert "fee_per_visit" not in str(veri) and "contract_total" not in str(veri)
    r = await ortam.istemciler["SERVIS_YONETICI"].get(yol)
    assert r.status_code == 200 and "fee_per_visit" in r.json(), r.text


async def test_tarama_kendini_kanitlar(ortam, monkeypatch) -> None:
    """Ekle → kırmızı: arıza nedeni çıktısına maliyet alanı eklenince tarama yakalar."""
    from app.api import teknik_servis as ts_api

    ozgun = ts_api._ariza_cikti
    monkeypatch.setattr(ts_api, "_ariza_cikti", lambda n: {**ozgun(n), "maliyet": None})
    hedef = [u for u in _get_uclari() if u.yol == "/api/teknik-servis/tanimlar/ariza-nedenleri"]
    assert hedef
    sizintilar, taranan, _ = await _tara(ortam, hedef)
    assert taranan == {hedef[0].yol}
    assert any(".maliyet" in s for s in sizintilar), sizintilar


def test_anahtar_tarayici_ic_ice_bulur() -> None:
    veri = {"a": [{"b": {"grand_total": None}}], "iscilik": 0}
    assert yasak_anahtarlar(veri, FIYAT_ANAHTARLARI | MALIYET_ANAHTARLARI) == [
        "$.a[0].b.grand_total",
        "$.iscilik",
    ]
    assert yasak_anahtarlar({"ad": "x"}, MALIYET_ANAHTARLARI) == []


def test_servis_rolleri_maliyet_gormez() -> None:
    for rol in SERVIS_ROLLERI:
        rol_yasaklari(rol)
    goren = {r for r in SERVIS_ROLLERI if "maliyet.gor" in ROLES[r][1]}
    assert goren == MALIYET_GOREN_SERVIS_ROLLERI
