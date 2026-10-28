"""MESAI takvimli SLA (Faz A-1, TS-200; M5.1, M5.4, M12.2).

Karar: SLA müşteri sözleşmesine göre 7/24 ya da MESAI (hafta içi 08:30–18:00,
Europe/Istanbul, tatiller fark etmez). Öncelik: lokasyon → müşteri → politika
→ 7/24; sonuç iş açılışında DONDURULUR. Burada kilitlenenler:

- öncelik zinciri (API ile girilen hesap/lokasyon değeriyle),
- dondurma (müşteri sonradan değişse de, öncelik düzeltmesinde de takvim aynı),
- iş beklemesinin MESAI kayması,
- SQL `servis_mesai_dk` = Python `takvim_dakika`; `sla_ifadeleri` = `sla_durumu`
  (MESAI işinde "riskte" çalışılan dakikayla),
- uçlar: politika MESAI kabul (eski 400 kalktı), müşteri/lokasyon alanı iyimser
  kilit + denetim, mesai penceresi ayarı (ters pencere 400), rapor çözüm süresi.

FakeClock başlangıcı 2026-01-01 00:00 UTC = Perşembe 03:00 yerel (1 Ocak resmî
tatil — FARK ETMEZ).
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from servis_yardimci import acilis, giris, musteri
from sqlalchemy import func, select

from app.models import (
    Account,
    AuditLog,
    ServiceHold,
    ServiceOrder,
    ServiceOrderEvent,
    ServiceSlaPolicy,
)
from app.models.teknik_servis import VARSAYILAN_SLA_POLITIKALARI
from app.services import settings as ayarlar
from app.services.teknik_servis import sla, sla_takvim
from app.services.teknik_servis.yerel_zaman import YEREL

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)
TS = "/api/teknik-servis"
ANA = f"{TS}/ana-veri"


def y(ay: int, gun: int, saat: int, dakika: int = 0) -> datetime:
    return datetime(2026, ay, gun, saat, dakika, tzinfo=YEREL)


@pytest.fixture(autouse=True)
async def _tohum_politikalari(db):
    """Politika tohumu `_TRUNCATE` dışıdır: her testten önce tohum değerleri (7/24)."""
    varsayilan = dict(VARSAYILAN_SLA_POLITIKALARI)
    for p in (await db.scalars(select(ServiceSlaPolicy))).all():
        if p.birim is None and p.oncelik in varsayilan:
            p.cozum_saat = Decimal(varsayilan[p.oncelik])
            p.mudahale_saat = None
            p.takvim_turu = "7_24"
            p.is_active = True
        else:
            p.is_active = False
    await db.commit()
    yield
    for p in (await db.scalars(select(ServiceSlaPolicy))).all():
        p.takvim_turu = "7_24"
    await db.commit()


@pytest.fixture
async def mudur(client, db, kullanici_ac):
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await giris(client, "mudur")
    await ayarlar.set_many(
        db, {"servis_sla_yururluk_at": (AN - timedelta(days=1)).isoformat()}, None
    )
    await db.commit()
    return (await musteri(db)).id


async def is_ac(client, hesap_id: int, **kw) -> int:
    r = await client.post(f"{TS}/isler", json=acilis(hesap_id, **kw))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def kayit(db, so_id: int) -> ServiceOrder:
    db.expire_all()
    return await db.get(ServiceOrder, so_id)


async def hesap_takvimi(client, db, hesap_id: int, tur: str | None) -> dict:
    hesap = await db.get(Account, hesap_id)
    await db.refresh(hesap)
    r = await client.patch(
        f"{ANA}/musteriler/{hesap_id}", json={"sla_takvim_turu": tur, "version": hesap.version}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def lokasyon(client, hesap_id: int, ad: str, tur: str | None) -> dict:
    r = await client.post(
        "/api/lokasyonlar",
        json={
            "hesap_id": hesap_id,
            "kind": "TESIS",
            "site_name": ad,
            "city": "İzmir",
            "sla_takvim_turu": tur,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- Öncelik zinciri ------------------------------------------------------------------


async def test_musteri_mesai_ise_hedef_mesaiyle_damgalanir(client, db, mudur) -> None:
    """Perşembe 03:00 açılan KRITIK (12 sa = 720 çalışma dk): Perşembe 08:30'dan
    570 dk + Cuma 150 dk → Cuma 11:00 (yerel). Olay metni kaynağı söyler."""
    yanit = await hesap_takvimi(client, db, mudur, "MESAI")
    assert yanit["sla_takvim_turu"] == "MESAI"
    so_id = await is_ac(client, mudur, oncelik="KRITIK")
    k = await kayit(db, so_id)
    assert k.sla_takvim_turu == "MESAI" and k.cozum_hedef_dk == 720
    assert k.cozum_hedef_at == y(1, 2, 11)
    assert k.cozum_hedef_ilk_at == k.cozum_hedef_at
    ozet = await db.scalar(
        select(ServiceOrderEvent.ozet).where(
            ServiceOrderEvent.service_order_id == so_id, ServiceOrderEvent.olay_turu == "SLA"
        )
    )
    assert "Mesai" in ozet and "müşteri sözleşmesi" in ozet
    kart = (await client.get(f"{TS}/operasyon/isler/{so_id}/sla")).json()["sla"]
    assert kart["takvim_turu"] == "MESAI"
    assert kart["takvim_adi"] == "Mesai (hafta içi 08:30–18:00)"


async def test_lokasyon_musteriyi_ezer(client, db, mudur) -> None:
    """M12.2: müşteri MESAI ama lokasyon 7/24 → 7/24; müşteri boş, lokasyon MESAI → MESAI."""
    await hesap_takvimi(client, db, mudur, "MESAI")
    lok_7_24 = await lokasyon(client, mudur, "Hastane Acil", "7_24")
    assert lok_7_24["sla_takvim_turu"] == "7_24"
    k = await kayit(db, await is_ac(client, mudur, oncelik="KRITIK", address_id=lok_7_24["id"]))
    assert k.sla_takvim_turu == "7_24"
    assert k.cozum_hedef_at == k.sla_baslangic_at + timedelta(hours=12)

    diger = (await musteri(db, "Yedek Müşteri A.Ş.")).id
    lok_mesai = await lokasyon(client, diger, "Merkez Ofis", "MESAI")
    k2 = await kayit(db, await is_ac(client, diger, oncelik="KRITIK", address_id=lok_mesai["id"]))
    assert k2.sla_takvim_turu == "MESAI" and k2.cozum_hedef_at == y(1, 2, 11)

    # Lokasyon boş → müşteri (MESAI) geçerli.
    lok_bos = await lokasyon(client, mudur, "Depo", None)
    k3 = await kayit(db, await is_ac(client, mudur, oncelik="KRITIK", address_id=lok_bos["id"]))
    assert k3.sla_takvim_turu == "MESAI"


async def test_politika_mesai_kabul_edilir_ve_varsayilan_olur(client, db, mudur) -> None:
    """Eski 400 kalktı; müşteri/lokasyon boşsa politikanın takvimi uygulanır."""
    p = await db.scalar(
        select(ServiceSlaPolicy).where(
            ServiceSlaPolicy.oncelik == "KRITIK", ServiceSlaPolicy.birim.is_(None)
        )
    )
    r = await client.put(
        f"{TS}/sla-tanimlari/politikalar",
        json={
            "id": p.id,
            "version": p.version,
            "oncelik": "KRITIK",
            "cozum_saat": "12",
            "takvim_turu": "MESAI",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["takvim_turu"] == "MESAI"
    k = await kayit(db, await is_ac(client, mudur, oncelik="KRITIK"))
    assert k.sla_takvim_turu == "MESAI" and k.cozum_hedef_at == y(1, 2, 11)
    # Müşteri 7/24 ise politikayı ezer.
    await hesap_takvimi(client, db, mudur, "7_24")
    k2 = await kayit(db, await is_ac(client, mudur, oncelik="KRITIK"))
    assert k2.sla_takvim_turu == "7_24"


async def test_hicbiri_yoksa_7_24(client, db, mudur) -> None:
    k = await kayit(db, await is_ac(client, mudur, oncelik="KRITIK"))
    assert k.sla_takvim_turu == "7_24"
    assert k.cozum_hedef_at == k.sla_baslangic_at + timedelta(hours=12)


# --- Dondurma -------------------------------------------------------------------------


async def test_takvim_acilista_donar(client, db, mudur) -> None:
    """Müşteri sonradan 7/24'e geçse de açık iş MESAI kalır; öncelik düzeltmesi hedefi
    yeni politikayla ama DONMUŞ takvimle yeniden hesaplar."""
    await hesap_takvimi(client, db, mudur, "MESAI")
    so_id = await is_ac(client, mudur, oncelik="KRITIK")
    await hesap_takvimi(client, db, mudur, "7_24")
    k = await kayit(db, so_id)
    assert k.sla_takvim_turu == "MESAI" and k.cozum_hedef_at == y(1, 2, 11)
    r = await client.patch(f"{TS}/isler/{so_id}", json={"version": k.version, "oncelik": "YUKSEK"})
    assert r.status_code == 200, r.text
    k = await kayit(db, so_id)
    # YUKSEK 24 sa = 1440 dk: Per 570 + Cum 570 + Pzt 300 → Pazartesi 13:30.
    assert k.sla_takvim_turu == "MESAI" and k.cozum_hedef_at == y(1, 5, 13, 30)
    assert k.cozum_hedef_ilk_at == y(1, 2, 11)


# --- İş beklemesi ---------------------------------------------------------------------


async def test_bekleme_kaymasi_mesai_dakikasidir(client, db, mudur) -> None:
    """Cuma 10:00 → Pazartesi 09:00 müşteri onayı beklemesi: 480 + 30 = 510 mesai dk
    (hafta sonu sayılmaz). Hedef Cuma 11:00 + 510 dk → Pazartesi 10:00."""
    await hesap_takvimi(client, db, mudur, "MESAI")
    so_id = await is_ac(client, mudur, oncelik="KRITIK")
    client.clock.set(y(1, 2, 10).astimezone(UTC))
    await giris(client, "mudur")
    r = await client.post(f"{TS}/isler/{so_id}/bekleme", json={"neden": "MUSTERI_ONAYI"})
    assert r.status_code == 200, r.text
    client.clock.set(y(1, 5, 9).astimezone(UTC))
    await giris(client, "mudur")
    r = await client.post(f"{TS}/isler/{so_id}/bekleme/bitir", json={})
    assert r.status_code == 200, r.text
    kayma = await db.scalar(
        select(ServiceHold.sla_kayma_dk).where(ServiceHold.service_order_id == so_id)
    )
    assert kayma == 510
    k = await kayit(db, so_id)
    assert k.cozum_hedef_at == y(1, 5, 10)
    assert k.cozum_hedef_ilk_at == y(1, 2, 11)


# --- SQL = Python ---------------------------------------------------------------------


async def test_sql_mesai_fonksiyonu_python_ile_ayni(db) -> None:
    rnd = random.Random(20261028)
    bas0 = y(1, 1, 0)
    ciftler = []
    for _ in range(150):
        a = bas0 + timedelta(minutes=rnd.randint(0, 30 * 24 * 60), seconds=rnd.randint(0, 59))
        b = a + timedelta(minutes=rnd.randint(-600, 10 * 24 * 60), seconds=rnd.randint(0, 59))
        ciftler.append((a, b))
    ciftler += [(y(1, 2, 17), y(1, 5, 9, 30)), (y(1, 3, 9), y(1, 4, 20))]
    for a, b in ciftler:
        sql_dk = await db.scalar(select(func.servis_mesai_dk(a, b, 510, 1080)))
        assert sql_dk == sla_takvim.takvim_dakika(a, b, "MESAI"), (a, b)
    assert await db.scalar(select(func.servis_mesai_dk(None, AN, 510, 1080))) is None
    # Özel pencere.
    m = sla_takvim.MesaiTakvimi.metinden("09:00", "17:00")
    for a, b in ciftler[:40]:
        sql_dk = await db.scalar(select(func.servis_mesai_dk(a, b, 540, 1020)))
        assert sql_dk == sla_takvim.takvim_dakika(a, b, "MESAI", mesai=m)


async def test_sla_ifadeleri_mesai_riskini_python_ile_ayni_hesaplar(db, servis_isi_ac) -> None:
    """Liste/sayaç (SQL) ile kart (Python) MESAI işinde aynı durumu ve kalanı verir;
    ayar değişince ikisi de yeni pencereyi kullanır."""
    rnd = random.Random(7)
    simdi = y(1, 12, 15)  # Pazartesi 15:00
    isler = []
    for i in range(30):
        tur = "MESAI" if i % 3 else "7_24"
        bas = simdi - timedelta(minutes=rnd.randint(0, 6 * 24 * 60))
        dk = rnd.choice((720, 1440, 4320))
        hedef = sla_takvim.is_saati_ekle(bas, dk, tur)
        isler.append(
            await servis_isi_ac(
                durum="ISLEMDE",
                sla_baslangic_at=bas,
                cozum_hedef_at=hedef,
                cozum_hedef_ilk_at=hedef,
                sla_takvim_turu=tur,
                sla_kaynak="CANLI",
            )
        )
    await db.commit()

    async def karsilastir() -> set[str]:
        mesai = await sla.mesai_takvimi(db)
        ifade = sla.sla_ifadeleri(simdi, 80)
        sql_sonuc = {
            i: (d, k)
            for i, d, k in (
                await db.execute(select(ServiceOrder.id, ifade["durum"], ifade["kalan_dk"]))
            ).all()
        }
        gorulen = set()
        for so in isler:
            await db.refresh(so)
            py = sla.sla_durumu(so, None, simdi, 80, mesai=mesai)
            assert sql_sonuc[so.id] == (py.durum, py.kalan_dk), (so.id, so.sla_takvim_turu)
            gorulen.add(py.durum)
        return gorulen

    assert {"ZAMANINDA", "RISKTE"} <= await karsilastir()
    await ayarlar.set_many(
        db, {"servis_mesai_baslangic": "10:00", "servis_mesai_bitis": "16:00"}, None
    )
    await db.commit()
    await karsilastir()


# --- Uçlar ----------------------------------------------------------------------------


async def test_musteri_takvimi_ucu_kilit_denetim_ve_mobilite(client, db, mudur) -> None:
    hesap = await db.get(Account, mudur)
    eski_surum = hesap.version
    yanit = await hesap_takvimi(client, db, mudur, "MESAI")
    assert yanit["version"] == eski_surum + 1
    # Eski sürüm → 409.
    r = await client.patch(
        f"{ANA}/musteriler/{mudur}", json={"sla_takvim_turu": "7_24", "version": eski_surum}
    )
    assert r.status_code == 409
    # Sözlük dışı → 422.
    r = await client.patch(
        f"{ANA}/musteriler/{mudur}", json={"sla_takvim_turu": "5_8", "version": yanit["version"]}
    )
    assert r.status_code == 422
    denetim = await db.scalar(select(AuditLog).where(AuditLog.action == "servis.musteri.guncelle"))
    assert denetim is not None and denetim.new_value.get("sla_takvim_turu") == "MESAI"
    kart = (await client.get(f"{ANA}/musteriler/{mudur}/servis-karti")).json()
    assert kart["sla_takvim_turu"] == "MESAI" and kart["version"] == yanit["version"]
    # null → politikaya döner.
    assert (await hesap_takvimi(client, db, mudur, None))["sla_takvim_turu"] is None

    # Mobilite rolü taşıyan müşteri: yalnız SLA takvimi yazılabilir, künye 409.
    filo = await musteri(db, "Kendi Montajını Yapan Filo", is_montaj_noktasi=True)
    r = await client.patch(
        f"{ANA}/musteriler/{filo.id}", json={"sla_takvim_turu": "MESAI", "version": filo.version}
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{ANA}/musteriler/{filo.id}",
        json={"title": "Yeni Unvan", "version": r.json()["version"]},
    )
    assert r.status_code == 409


async def test_lokasyon_takvimi_ucu(client, db, mudur) -> None:
    lok = await lokasyon(client, mudur, "Fabrika", None)
    assert lok["sla_takvim_turu"] is None
    r = await client.patch(
        f"/api/lokasyonlar/{lok['id']}",
        json={"sla_takvim_turu": "MESAI", "version": lok["version"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sla_takvim_turu"] == "MESAI"
    r2 = await client.patch(
        f"/api/lokasyonlar/{lok['id']}", json={"sla_takvim_turu": "7_24", "version": lok["version"]}
    )
    assert r2.status_code == 409  # iyimser kilit
    r3 = await client.patch(
        f"/api/lokasyonlar/{lok['id']}",
        json={"sla_takvim_turu": "GECE", "version": r.json()["version"]},
    )
    assert r3.status_code == 422
    denetim = await db.scalar(select(AuditLog).where(AuditLog.action == "lokasyon.guncelle"))
    assert denetim is not None and denetim.new_value.get("sla_takvim_turu") == "MESAI"


async def test_mesai_penceresi_ayari(client, db, mudur) -> None:
    s = (await client.get(f"{TS}/sla-tanimlari/sozluk")).json()
    assert s["mesai"] == {"baslangic": "08:30", "bitis": "18:00", "metin": "hafta içi 08:30–18:00"}
    assert {t["kod"] for t in s["takvim_turleri"]} == {"7_24", "MESAI"}
    r = await client.put(f"{TS}/sla-tanimlari/mesai", json={"baslangic": "09:00"})
    assert r.status_code == 200, r.text
    assert r.json()["metin"] == "hafta içi 09:00–18:00"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "sla.mesai.degistir"))
    # Ters pencere (tek anahtar gönderilse de mevcut değerle karşılaştırılır) → 400.
    r = await client.put(f"{TS}/sla-tanimlari/mesai", json={"bitis": "08:00"})
    assert r.status_code == 400
    r = await client.put(f"{TS}/sla-tanimlari/mesai", json={"bitis": "25:00"})
    assert r.status_code == 400
    # Yeni pencere yeni işe uygulanır: Per 03:00 + 720 dk (09:00–18:00 = 540/gün)
    # → Per 540 + Cum 180 → Cuma 12:00.
    await hesap_takvimi(client, db, mudur, "MESAI")
    k = await kayit(db, await is_ac(client, mudur, oncelik="KRITIK"))
    assert k.cozum_hedef_at == y(1, 2, 12)


async def test_mesai_ayari_yetkisiz_403(client, db, kullanici_ac) -> None:
    await kullanici_ac("tekno", "SERVIS_TEKNISYEN")
    await giris(client, "tekno")
    r = await client.put(f"{TS}/sla-tanimlari/mesai", json={"baslangic": "09:00"})
    assert r.status_code == 403


async def test_rapor_cozum_suresi_mesai_saatidir(client, db, mudur) -> None:
    """Perşembe 03:00 açılan MESAI işi Cuma 10:00'da çözülür: 570 + 90 = 660 dk = 11 sa
    (duvar saatiyle 31 sa olurdu)."""
    await hesap_takvimi(client, db, mudur, "MESAI")
    so_id = await is_ac(client, mudur, oncelik="KRITIK")
    client.clock.set(y(1, 2, 10).astimezone(UTC))
    await giris(client, "mudur")
    r = await client.post(
        f"{TS}/isler/{so_id}/sonuc",
        json={"sonuc": "COZULDU", "cozum_kanali": "TELEFON", "yapilan_islem": "Çözüldü"},
    )
    assert r.status_code == 200, r.text
    k = await kayit(db, so_id)
    assert k.sla_sonuc == "ZAMANINDA"
    r = await client.get(
        f"{TS}/raporlar/sla", params={"baslangic": "2026-01-01", "bitis": "2026-01-31"}
    )
    assert r.status_code == 200, r.text
    cozum = r.json()["cozum_suresi"]
    assert cozum["olculen"] == 1 and cozum["ortalama_saat"] == 11.0
