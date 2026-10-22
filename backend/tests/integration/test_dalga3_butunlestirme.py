"""Dalga 3 bütünleştirme doğrulaması (TS-180…TS-208 kesişen kabuller).

- Rapor sayıları KAPSAMLIDIR: aynı altın veri setinde başka birim kullanıcısı
  farklı toplam görür (JSON ve Excel), yetkisiz birim süzgeci 403.
- Maliyet/tutar sütunu yetkisiz kullanıcıda Excel'de de YOKTUR (fatura devri).
- TS-198: atama/plan yanıtı yetkinlik uyarılarını taşır, atama ENGELLENMEZ ve
  ATAMA olayına "yetkinlik uyarısıyla atandı" notu düşer (kişi adı olay
  verisine yazılmaz).
- Kayıt noktaları: kiralık envanter göç profili İçe Aktarma'da; `Personnel.
  FullName` ad eşleme alanlarında; bakım rapor KPI'ları servis paketi
  yüklenince (API'siz) motor kaydında.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from urllib.parse import unquote

import pytest
from openpyxl import load_workbook
from servis_rapor_ortam import DONEM, R, altin_kur, giris
from sqlalchemy import select

from app.models import (
    Competency,
    ServiceCompetencyRequirement,
    ServiceOrderAssignment,
    ServiceOrderEvent,
)
from app.models.servis_maliyet import ServiceOrderFinancial

pytestmark = pytest.mark.integration

TS = "/api/teknik-servis"


# --- Rapor kapsamı -----------------------------------------------------------------------


@pytest.fixture
async def altin(client, db, kullanici_ac, birimli_kullanici_ac):
    return await altin_kur(db, kullanici_ac, birimli_kullanici_ac)


async def _gelen(client, kullanici: str, **ek) -> int:
    await giris(client, kullanici)
    r = await client.get(f"{R}/ozet", params={**DONEM, **ek})
    assert r.status_code == 200, r.text
    return {k["kod"]: k["deger"] for k in r.json()["kpiler"]}["rapor_gelen"]


async def _veri_satiri(client, kullanici: str) -> tuple[int, set[str]]:
    await giris(client, kullanici)
    r = await client.get(f"{R}/kitap.xlsx", params=DONEM)
    assert r.status_code == 200, r.text
    ws = load_workbook(BytesIO(r.content))["Veri_IsEmirleri"]
    basliklar = [h.value for h in ws[1]]
    satirlar = list(ws.iter_rows(min_row=2, values_only=True))
    birimler: set[str] = set()
    if "Birim" in basliklar:
        i = basliklar.index("Birim")
        birimler = {str(s[i]) for s in satirlar if s[i]}
    return len(satirlar), birimler


async def test_rapor_sayilari_kapsamli_baska_birim_farkli_toplam(client, altin):
    mudur = await _gelen(client, "mudur")
    sef_g = await _gelen(client, "sef_g")
    sef_h = await _gelen(client, "sef_h")
    # Altın tablo: tümü 27, GÜVENLİK 26, HABERLEŞME 1 (kapsam toplamı birebir).
    assert (mudur, sef_g, sef_h) == (27, 26, 1)
    assert sef_g + sef_h == mudur
    # Kapsam dışı birim süzgeci genişletmez: 403.
    await giris(client, "sef_h")
    r = await client.get(f"{R}/ozet", params={**DONEM, "birim": "GUVENLIK"})
    assert r.status_code == 403
    # KPI listesi de aynı kapsamla sayar.
    r = await client.get(f"{R}/kpi-liste", params={**DONEM, "kpi": "rapor_gelen", "limit": 1})
    assert int(r.headers["X-Toplam-Kayit"]) == 1


async def test_rapor_excel_kapsamli(client, altin):
    n_g, birim_g = await _veri_satiri(client, "sef_g")
    n_h, birim_h = await _veri_satiri(client, "sef_h")
    n_m, _ = await _veri_satiri(client, "mudur")
    assert n_g + n_h == n_m
    assert n_h < n_g
    if birim_g or birim_h:  # birim sütunu varsa yabancı birim satırı yok
        assert all("HABER" not in b.upper() for b in birim_g)
        assert all("GÜVEN" not in b.upper() and "GUVEN" not in b.upper() for b in birim_h)


# --- Tutar sütunu yetkisizde Excel'de yok --------------------------------------------------


async def test_fatura_devri_excel_tutar_yalniz_yetkilide(
    client, db, kullanici_ac, birimli_kullanici_ac, rol_ac, servis_isi_ac
):
    await rol_ac("T_DEVIR_X", ["tahsilat.gor", "servis_rapor.disaaktar"], "KENDI_BIRIMI")
    await birimli_kullanici_ac("devir_x", "T_DEVIR_X", ["GUVENLIK"])
    await kullanici_ac("adm_x", "ADMIN")
    so = await servis_isi_ac(
        birim="GUVENLIK", durum="TAMAMLANDI", completed_at=datetime(2026, 1, 1, 8, tzinfo=UTC)
    )
    db.add(
        ServiceOrderFinancial(
            service_order_id=so.id, gelir=Decimal("1234"), gelir_kaynagi="ELLE", gelir_notu="x"
        )
    )
    await db.commit()

    async def _baslik(kullanici: str) -> list:
        await giris(client, kullanici)
        r = await client.get(f"{TS}/maliyet/fatura-devri.xlsx")
        assert r.status_code == 200, r.text
        ws = load_workbook(BytesIO(r.content)).active
        assert ws.max_row == 2  # bir satır, iki kullanıcıda da aynı
        return [h.value for h in ws[1]]

    yetkisiz = await _baslik("devir_x")
    assert not any("Tutar" in str(b) or "Gelir" == str(b) for b in yetkisiz)
    yetkili = await _baslik("adm_x")
    assert "Tutar (KDV hariç)" in yetkili
    # JSON'da da anahtar yok.
    await giris(client, "devir_x")
    r = await client.get(f"{TS}/maliyet/fatura-devri")
    assert r.status_code == 200 and all("tutar" not in x for x in r.json())


# --- TS-198: atamada yetkinlik uyarısı --------------------------------------------------------


@pytest.fixture
async def yetkinlik_ortami(db, birimli_kullanici_ac):
    sef = await birimli_kullanici_ac("sef_y", "SERVIS_SEF", ["GUVENLIK"], saha_rolu="SEF")
    t1 = await birimli_kullanici_ac(
        "tek_y1", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    t2 = await birimli_kullanici_ac(
        "tek_y2", "SERVIS_TEKNISYEN", ["GUVENLIK"], saha_rolu="TEKNISYEN"
    )
    y = Competency(kod="XRY", ad="X-Ray Bakımı", birim="GUVENLIK")
    db.add(y)
    await db.flush()
    db.add(
        ServiceCompetencyRequirement(
            birim="GUVENLIK", tur="ARIZA", competency_id=y.id, min_seviye=2
        )
    )
    await db.commit()
    return sef, t1, t2


async def _olaylar(db, so_id: int) -> list[ServiceOrderEvent]:
    return list(
        (
            await db.scalars(
                select(ServiceOrderEvent)
                .where(
                    ServiceOrderEvent.service_order_id == so_id,
                    ServiceOrderEvent.olay_turu == "ATAMA",
                )
                .order_by(ServiceOrderEvent.id)
            )
        ).all()
    )


async def test_tekli_atama_uyari_basligi_engellemez_ve_olay_notu(
    client, db, yetkinlik_ortami, servis_isi_ac
):
    _, t1, _ = yetkinlik_ortami
    so = await servis_isi_ac(birim="GUVENLIK", tur="ARIZA")
    await giris(client, "sef_y")
    r = await client.put(
        f"{TS}/isler/{so.id}/atama",
        json={"atamalar": [{"user_id": t1.id, "rol": "TEKNISYEN", "is_lead": True}]},
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)  # canlı sözleşme: gövde ekip listesi
    uyarilar = json.loads(unquote(r.headers["X-Atama-Uyarilari"]))
    assert uyarilar and any("değerlendirilmemiş" in u for u in uyarilar)
    # Atama yapıldı (uyarı engellemez).
    aktif = await db.scalar(
        select(ServiceOrderAssignment.user_id).where(
            ServiceOrderAssignment.service_order_id == so.id,
            ServiceOrderAssignment.removed_at.is_(None),
        )
    )
    assert aktif == t1.id
    [olay] = await _olaylar(db, so.id)
    assert "yetkinlik uyarısıyla atandı" in olay.ozet
    assert olay.veri["yetkinlik_uyarisi"] is True
    assert t1.full_name not in json.dumps(olay.veri, ensure_ascii=False)


async def test_toplu_atama_uyarilar_alani_ve_esleme_yoksa_bos(
    client, db, yetkinlik_ortami, servis_isi_ac
):
    _, t1, t2 = yetkinlik_ortami
    a = await servis_isi_ac(birim="GUVENLIK", tur="ARIZA")
    b = await servis_isi_ac(birim="GUVENLIK", tur="ARIZA")
    await giris(client, "sef_y")
    r = await client.put(
        f"{TS}/isler/toplu-atama",
        json={
            "is_idler": [a.id, b.id],
            "atamalar": [{"user_id": t2.id, "rol": "TEKNISYEN", "is_lead": True}],
            "mod": "DEGISTIR",
        },
    )
    assert r.status_code == 200, r.text
    govde = r.json()
    assert govde["guncellenen"] == 2
    # Aynı kişi iki işte: uyarı metni tekrarlanmaz.
    assert len(govde["uyarilar"]) == len(set(govde["uyarilar"])) >= 1
    # Eşlemesi olmayan tür: uyarı yok, başlık yok.
    c = await servis_isi_ac(birim="GUVENLIK", tur="DESTEK")
    r = await client.put(
        f"{TS}/isler/{c.id}/atama",
        json={"atamalar": [{"user_id": t1.id, "rol": "TEKNISYEN", "is_lead": True}]},
    )
    assert r.status_code == 200, r.text
    assert "X-Atama-Uyarilari" not in r.headers
    [olay] = await _olaylar(db, c.id)
    assert "yetkinlik" not in olay.ozet


# --- Kayıt noktaları ------------------------------------------------------------------------


def test_kayit_noktalari_baglandi():
    import app.services.teknik_servis  # noqa: F401  (paket: modül kayıtları)
    from app.services import imports
    from app.services.imports import kiralama_goc
    from app.services.teknik_servis import ad_esleme, panel

    assert "Personnel.FullName" in ad_esleme.KAYNAK_ALANLARI
    assert kiralama_goc.PROFIL.kod in imports.PROFILLER
    assert imports.PROFIL_IZINLERI[kiralama_goc.PROFIL.kod] == "sistem.goc"
    # Bakım rapor KPI'ları servis paketiyle (API yüklenmeden de) kayıtlı.
    assert any(k.startswith("rapor_bakim_") for k in panel.KPI_TANIMLARI)
