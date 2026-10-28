"""SLA çekirdeği (TS-081, TS-085; E10-01/03/10/12/13/17).

Gerçek hikâye: eski sistemde "geciken iş" her ekranda başka sayılıyordu ve
hedef, işin elle girilen bildirim saatine bağlıydı (geriye tarih → açılır
açılmaz aşılmış). Burada hedef açılışta Clock'tan DAMGALANIR, politika
değişse de açık işin hedefi değişmez, SLA'yı durduran iş beklemesi hedefi
ileri alır, sonuç ilk TAMAMLANDI'da donar ve aşılmış iş gecikme nedenisiz
kapatılamaz.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from servis_yardimci import acilis, giris, musteri, teknisyen
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, ServiceHold, ServiceOrder, ServiceOrderEvent, ServiceSlaPolicy
from app.models.teknik_servis import VARSAYILAN_SLA_POLITIKALARI
from app.services import settings as ayarlar

pytestmark = pytest.mark.integration

AN = datetime(2026, 1, 1, tzinfo=UTC)  # FakeClock başlangıcı
TS = "/api/teknik-servis"


async def sla_yururlukte(db, an: datetime = AN - timedelta(days=1)) -> None:
    await ayarlar.set_many(db, {"servis_sla_yururluk_at": an.isoformat()}, None)
    await db.commit()


async def is_ac(client, hesap_id: int, **kw) -> dict:
    r = await client.post(f"{TS}/isler", json=acilis(hesap_id, **kw))
    assert r.status_code == 201, r.text
    return r.json()


async def kayit(db, so_id: int) -> ServiceOrder:
    db.expire_all()
    return await db.get(ServiceOrder, so_id)


async def sla_karti(client, so_id: int) -> dict:
    r = await client.get(f"{TS}/operasyon/isler/{so_id}/sla")
    assert r.status_code == 200, r.text
    return r.json()


async def ileri(client, **kw) -> None:
    """Saati ilerletir ve oturumu tazeler (boşta kalma süresi FakeClock'la da dolar)."""
    client.clock.advance(**kw)
    await giris(client, getattr(client, "ts_kullanici", "mudur"))


async def tamamla(client, so_id: int) -> None:
    r = await client.post(
        f"{TS}/isler/{so_id}/sonuc",
        json={"sonuc": "COZULDU", "cozum_kanali": "TELEFON", "yapilan_islem": "Çözüldü"},
    )
    assert r.status_code == 200, r.text


@pytest.fixture(autouse=True)
async def _tohum_politikalari(db):
    """SLA tohumu `_TRUNCATE` dışıdır: yarıda kesilmiş bir koşudan kalan değişiklik
    sonraki testleri bozmasın diye her testten önce tohum değerlerine döndürülür
    (genel politika = VARSAYILAN, aktif, müdahale hedefi yok; birime özel pasif)."""
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


@pytest.fixture
async def mudur(client, db, kullanici_ac):
    await kullanici_ac("mudur", "SERVIS_YONETICI")
    await giris(client, "mudur")
    return await musteri(db)


async def test_yururluk_bosken_damga_yok(client, db, mudur) -> None:
    """KD-22: `servis_sla_yururluk_at` boşken iş damgalanmaz (göç fırtınası önlemi)."""
    so = await is_ac(client, mudur, oncelik="KRITIK")
    kayitli = await kayit(db, so["id"])
    assert kayitli.sla_policy_id is None and kayitli.cozum_hedef_at is None
    assert (await sla_karti(client, so["id"]))["sla"]["durum"] == "OLCULEMEDI"
    # Yürürlük ileri bir an → yine damga yok.
    await sla_yururlukte(db, AN + timedelta(days=1))
    so2 = await is_ac(client, mudur)
    assert (await kayit(db, so2["id"])).cozum_hedef_at is None


async def test_kritik_is_12_saat_damgalanir(client, db, mudur) -> None:
    """Kabul (1): KRITIK → hedef = başlangıç + 12 sa; başlangıç Clock'tan (DB saati değil)."""
    await sla_yururlukte(db)
    client.clock.set(AN + timedelta(hours=5, minutes=17))
    await giris(client, "mudur")
    so = await is_ac(
        client, mudur, oncelik="KRITIK", reported_at=(AN - timedelta(days=3)).isoformat()
    )
    k = await kayit(db, so["id"])
    assert k.sla_baslangic_at == AN + timedelta(hours=5, minutes=17)
    assert k.cozum_hedef_at == k.sla_baslangic_at + timedelta(hours=12)
    assert k.cozum_hedef_ilk_at == k.cozum_hedef_at
    assert k.cozum_hedef_dk == 720 and k.sla_takvim_turu == "7_24"
    assert k.sla_kaynak == "CANLI" and k.mudahale_hedef_at is None
    kart = await sla_karti(client, so["id"])
    assert kart["sla"]["durum"] == "ZAMANINDA" and kart["sla"]["kalan_dk"] == 720
    # Tohum: YUKSEK 24, NORMAL 72.
    for oncelik, saat in (("YUKSEK", 24), ("NORMAL", 72)):
        diger = await kayit(db, (await is_ac(client, mudur, oncelik=oncelik))["id"])
        assert diger.cozum_hedef_at - diger.sla_baslangic_at == timedelta(hours=saat)


async def test_politika_degisimi_eski_isi_etkilemez_ve_denetlenir(client, db, mudur) -> None:
    """Kabul (2)+(6): politika 12→8; eski iş 12 sa kalır, yeni iş 8 sa; denetimde eski/yeni."""
    await sla_yururlukte(db)
    eski_is = await is_ac(client, mudur, oncelik="KRITIK")
    politika = await db.scalar(
        select(ServiceSlaPolicy).where(
            ServiceSlaPolicy.oncelik == "KRITIK", ServiceSlaPolicy.birim.is_(None)
        )
    )
    pid, pver = politika.id, politika.version
    try:
        r = await client.put(
            f"{TS}/sla-tanimlari/politikalar",
            json={
                "id": pid,
                "version": pver,
                "oncelik": "KRITIK",
                "cozum_saat": "8",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["cozum_saat"] == 8.0
        k = await kayit(db, eski_is["id"])
        assert k.cozum_hedef_at - k.sla_baslangic_at == timedelta(hours=12)
        yeni = await kayit(db, (await is_ac(client, mudur, oncelik="KRITIK"))["id"])
        assert yeni.cozum_hedef_at - yeni.sla_baslangic_at == timedelta(hours=8)
        denetim = await db.scalar(
            select(AuditLog).where(AuditLog.action == "sla.politika.degistir")
        )
        assert denetim is not None and denetim.user_id is not None
        assert denetim.old_value["cozum_saat"] == "12.00"
        assert denetim.new_value["cozum_saat"] == "8.00"
    finally:
        # Tohum testler arasında temizlenmez (`_TRUNCATE` dışı): geri al.
        db.expire_all()
        p = await db.get(ServiceSlaPolicy, pid)
        p.cozum_saat = Decimal("12")
        await db.commit()


async def test_politika_tanim_kurallari(client, db, mudur, kullanici_ac) -> None:
    await kullanici_ac("sef_okur", "SERVIS_SEF")
    politika = await db.scalar(
        select(ServiceSlaPolicy).where(
            ServiceSlaPolicy.oncelik == "NORMAL", ServiceSlaPolicy.birim.is_(None)
        )
    )
    # MESAI artık geçerli (Faz A, TS-200): 400 değil, çakışma kuralına takılır (409);
    # ikinci aktif genel politika → 409; genel politikayı pasifleştirmek → 409;
    # eski sürüm → 409.
    r = await client.put(
        f"{TS}/sla-tanimlari/politikalar",
        json={"oncelik": "NORMAL", "cozum_saat": "5", "takvim_turu": "MESAI"},
    )
    assert r.status_code == 409
    r = await client.put(
        f"{TS}/sla-tanimlari/politikalar", json={"oncelik": "NORMAL", "cozum_saat": "5"}
    )
    assert r.status_code == 409
    temel = {
        "id": politika.id,
        "version": politika.version,
        "oncelik": "NORMAL",
        "cozum_saat": "72",
    }
    r = await client.put(f"{TS}/sla-tanimlari/politikalar", json={**temel, "is_active": False})
    assert r.status_code == 409
    r = await client.put(
        f"{TS}/sla-tanimlari/politikalar", json={**temel, "version": politika.version + 5}
    )
    assert r.status_code == 409
    # Birime özel politika eklenebilir ve o birimde önce seçilir; sonra pasiflenir.
    r = await client.put(
        f"{TS}/sla-tanimlari/politikalar",
        json={"oncelik": "NORMAL", "birim": "HABERLESME", "cozum_saat": "10"},
    )
    assert r.status_code == 200, r.text
    ozel = r.json()
    try:
        await sla_yururlukte(db)
        so = await is_ac(client, mudur, birim="HABERLESME")
        k = await kayit(db, so["id"])
        assert k.sla_policy_id == ozel["id"]
        assert k.cozum_hedef_at - k.sla_baslangic_at == timedelta(hours=10)
        # RBAC: şefte `operasyon.yonet` yok → 403; okuma `servis.gor` → 200.
        await giris(client, "sef_okur")
        r = await client.put(
            f"{TS}/sla-tanimlari/politikalar",
            json={"oncelik": "NORMAL", "birim": "POC", "cozum_saat": "3"},
        )
        assert r.status_code == 403
        r = await client.get(f"{TS}/sla-tanimlari/politikalar")
        assert r.status_code == 200 and len(r.json()) >= 4
    finally:
        db.expire_all()
        satir = await db.get(ServiceSlaPolicy, ozel["id"])
        satir.is_active = False
        await db.commit()


async def test_politika_tanimsiz_acilis_409(client, db, mudur) -> None:
    """Kabul (9): aktif politika yokken açılış 409 'SLA politikası tanımsız'."""
    await sla_yururlukte(db)
    hepsi = (
        await db.scalars(select(ServiceSlaPolicy).where(ServiceSlaPolicy.oncelik == "YUKSEK"))
    ).all()
    durumlar = {p.id: p.is_active for p in hepsi}
    try:
        for p in hepsi:
            p.is_active = False
        await db.commit()
        r = await client.post(f"{TS}/isler", json=acilis(mudur, oncelik="YUKSEK"))
        assert r.status_code == 409 and "SLA politikası tanımsız" in r.json()["detail"]
        assert await db.scalar(select(func.count()).select_from(ServiceOrder)) == 0
    finally:
        for p in hepsi:
            p.is_active = durumlar[p.id]
        await db.commit()


async def test_oncelik_duzeltmesi_yeniden_damgalar(client, db, mudur) -> None:
    """Kabul (5): NORMAL→KRITIK hedefi başlangıçtan yeniden hesaplar; ilk hedef değişmez;
    geçmişte eski/yeni hedef, denetimde kayıt."""
    await sla_yururlukte(db)
    so = await is_ac(client, mudur, oncelik="NORMAL")
    ilk = await kayit(db, so["id"])
    ilk_hedef = ilk.cozum_hedef_at
    await ileri(client, hours=2)
    r = await client.patch(
        f"{TS}/isler/{so['id']}", json={"version": ilk.version, "oncelik": "kritik".upper()}
    )
    assert r.status_code == 200, r.text
    k = await kayit(db, so["id"])
    assert k.cozum_hedef_at == k.sla_baslangic_at + timedelta(hours=12)
    assert k.cozum_hedef_ilk_at == ilk_hedef
    olay = await db.scalar(
        select(ServiceOrderEvent)
        .where(ServiceOrderEvent.service_order_id == so["id"], ServiceOrderEvent.olay_turu == "SLA")
        .order_by(ServiceOrderEvent.id.desc())
    )
    assert "yeniden hesaplandı" in olay.ozet
    assert olay.veri["eski"]["cozum_hedef_at"] != olay.veri["yeni"]["cozum_hedef_at"]
    assert await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "sla.yeniden_damga")
    )


async def test_tur_proje_olunca_damga_kalkar(client, db, mudur) -> None:
    """Tür düzeltmesi işi SLA dışına çıkarırsa (KURULUM, PROJE) damga temizlenir."""
    await sla_yururlukte(db)
    so = await is_ac(client, mudur)
    k = await kayit(db, so["id"])
    r = await client.patch(f"{TS}/isler/{so['id']}", json={"version": k.version, "tur": "KURULUM"})
    assert r.status_code == 200, r.text
    k = await kayit(db, so["id"])
    assert k.kategori == "PROJE" and k.sla_policy_id is None and k.cozum_hedef_at is None


async def test_durduran_bekleme_hedefi_ileri_alir(client, db, mudur) -> None:
    """E10-03 (2): MUSTERI_ONAYI ile 3 sa bekleyen işin hedefi 3 sa kayar; MALZEME ile kaymaz.
    Beklemedeyken durum DURDURULDU ve kalan süre donar."""
    await sla_yururlukte(db)
    a = await is_ac(client, mudur, oncelik="KRITIK")
    b = await is_ac(client, mudur, oncelik="KRITIK")
    hedef_a = (await kayit(db, a["id"])).cozum_hedef_at
    hedef_b = (await kayit(db, b["id"])).cozum_hedef_at
    await ileri(client, hours=1)
    assert (
        await client.post(f"{TS}/isler/{a['id']}/bekleme", json={"neden": "MUSTERI_ONAYI"})
    ).status_code == 200  # noqa: E501
    assert (
        await client.post(f"{TS}/isler/{b['id']}/bekleme", json={"neden": "MALZEME"})
    ).status_code == 200  # noqa: E501
    await ileri(client, hours=3)
    kart = (await sla_karti(client, a["id"]))["sla"]
    assert kart["durum"] == "DURDURULDU" and kart["kalan_dk"] == 11 * 60
    assert (await sla_karti(client, b["id"]))["sla"]["durum"] == "ZAMANINDA"
    for so in (a, b):
        r = await client.post(f"{TS}/isler/{so['id']}/bekleme/bitir", json={})
        assert r.status_code == 200, r.text
    ka = await kayit(db, a["id"])
    assert ka.cozum_hedef_at == hedef_a + timedelta(hours=3)
    assert ka.cozum_hedef_ilk_at == hedef_a
    assert (await kayit(db, b["id"])).cozum_hedef_at == hedef_b
    kaymalar = dict(
        (await db.execute(select(ServiceHold.service_order_id, ServiceHold.sla_kayma_dk))).all()
    )
    assert kaymalar == {a["id"]: 180, b["id"]: 0}


async def test_sonuc_ilk_tamamlandida_donar_bagli_is_silmez(client, db, mudur) -> None:
    """Kabul (7) + B3: TAMAMLANDI'da sonuç donar. M1.7 (Faz A): yeniden açma
    yok (409); bağlı yeni iş açılınca öncekinin SLA sonucu ve ilk hedefi
    DEĞİŞMEZ, yeni iş kendi SLA'sıyla doğar."""
    await sla_yururlukte(db)
    so = await is_ac(client, mudur, oncelik="KRITIK")
    await ileri(client, hours=2)
    await tamamla(client, so["id"])
    k = await kayit(db, so["id"])
    assert k.sla_sonuc == "ZAMANINDA" and k.sla_durdurulan_dk == 0
    assert k.ilk_mudahale_at == k.completed_at  # telefonla çözüm = ilk müdahale
    ilk_hedef = k.cozum_hedef_ilk_at
    r = await client.post(f"{TS}/isler/{so['id']}/yeniden-ac", json={"gerekce": "Arıza sürüyor"})
    assert r.status_code == 409, r.text
    await ileri(client, hours=20)  # hedef çoktan geçti
    r = await client.post(f"{TS}/isler/{so['id']}/bagli-yeni-is", json={"konu": "Arıza sürüyor"})
    assert r.status_code == 201, r.text
    yeni = await kayit(db, r.json()["id"])
    assert yeni.sla_policy_id is not None and yeni.cozum_hedef_ilk_at > ilk_hedef
    k = await kayit(db, so["id"])
    assert k.sla_sonuc == "ZAMANINDA" and k.cozum_hedef_ilk_at == ilk_hedef
    assert (await sla_karti(client, so["id"]))["sla"]["durum"] == "KARSILANDI"


async def test_asilmis_is_gecikme_nedenisiz_kapanmaz(client, db, mudur) -> None:
    """Kabul (4): hedef geçmiş işte TAMAMLANDI 200, gecikme nedenisiz KAPATILDI 409."""
    await sla_yururlukte(db)
    so = await is_ac(client, mudur, oncelik="KRITIK")
    await ileri(client, hours=13)
    assert (await sla_karti(client, so["id"]))["sla"]["durum"] == "ASILDI"
    await tamamla(client, so["id"])
    k = await kayit(db, so["id"])
    assert k.sla_sonuc == "ASILDI"
    kart = await sla_karti(client, so["id"])
    assert kart["sla"]["durum"] == "KARSILANMADI"
    assert kart["kapanis_icin_gerekenler"] == ["GECIKME_NEDENI"]
    r = await client.post(f"{TS}/isler/{so['id']}/kapat", json={})
    assert r.status_code == 409 and "gecikme nedeni" in r.json()["detail"]
    assert (await kayit(db, so["id"])).status == "TAMAMLANDI"
    # DIGER açıklamasız 400; geçerli neden ile kapanır.
    yol = f"{TS}/operasyon/isler/{so['id']}/kapanis-bilgisi"
    assert (await client.put(yol, json={"gecikme_nedeni": "DIGER"})).status_code == 400
    assert (await client.put(yol, json={"gecikme_nedeni": "XYZ"})).status_code == 422
    r = await client.put(yol, json={"gecikme_nedeni": "MALZEME_TEDARIK"})
    assert r.status_code == 200, r.text
    assert r.json()["kapanis_icin_gerekenler"] == []
    r = await client.post(f"{TS}/isler/{so['id']}/kapat", json={})
    assert r.status_code == 200, r.text
    assert await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "sla.kapanis_bilgisi")
    )


async def test_asilmamis_iste_gecikme_nedeni_409(client, db, mudur) -> None:
    await sla_yururlukte(db)
    so = await is_ac(client, mudur)
    r = await client.put(
        f"{TS}/operasyon/isler/{so['id']}/kapanis-bilgisi", json={"gecikme_nedeni": "ULASIM"}
    )
    assert r.status_code == 409
    r = await client.put(
        f"{TS}/operasyon/isler/{so['id']}/kapanis-bilgisi",
        json={"tekrar_ariza_teyit": "AYNI_ARIZA"},
    )
    assert r.status_code == 409  # aday olmayan işte teyit yok


async def test_ilk_mudahale_durum_ve_sayac(client, db, mudur, birimli_kullanici_ac) -> None:
    """Kabul (3) / E10-17: SAHA sayacı ilk müdahaleyi yazar; YOL ve BEKLEME yazmaz ve BEKLEME
    faaliyeti işi BEKLEMEDE yapmaz; ikinci sayaç değiştirmez."""
    await sla_yururlukte(db)
    tek = await teknisyen(birimli_kullanici_ac, "tek1")
    so = await is_ac(client, mudur)
    r = await client.put(
        f"{TS}/isler/{so['id']}/atama",
        json={"atamalar": [{"user_id": tek.id, "rol": "TEKNISYEN", "is_lead": True}]},
    )
    assert r.status_code == 200, r.text
    await giris(client, "tek1")
    client.ts_kullanici = "tek1"
    r = await client.post(
        f"{TS}/zaman/baslat",
        json={
            "is_id": so["id"],
            "eylem": "DIGER",
            "faaliyet": "BEKLEME",
            "bekleme_nedeni": "MALZEME",
        },
    )
    assert r.status_code == 201, r.text
    bolum = r.json()["bolum"]
    k = await kayit(db, so["id"])
    assert k.ilk_mudahale_at is None and k.status == "MUSTERI_TALEBI"

    async def gecis(bolum: dict, faaliyet: str) -> dict:
        r = await client.post(
            f"{TS}/isler/{so['id']}/zaman/bolumler/{bolum['id']}/gecis",
            json={"version": bolum["version"], "faaliyet": faaliyet},
        )
        assert r.status_code == 200, r.text
        return r.json()["yeni_bolum"]

    await ileri(client, minutes=10)
    bolum = await gecis(bolum, "YOL")
    assert (await kayit(db, so["id"])).ilk_mudahale_at is None
    await ileri(client, minutes=30)
    bolum = await gecis(bolum, "SAHA")
    ilk = (await kayit(db, so["id"])).ilk_mudahale_at
    assert ilk == AN + timedelta(minutes=40)
    await ileri(client, minutes=30)
    await gecis(bolum, "TEST")
    assert (await kayit(db, so["id"])).ilk_mudahale_at == ilk


async def test_pb_isine_sla_damgalanamaz(db, servis_isi_ac, sozlesme_ac) -> None:
    """Kabul (8): `ck_so_pb_sla` — PB işine politika/hedef yazılamaz (şema)."""
    from app.models import MaintenanceContractItem, MaintenancePeriod

    sozlesme = await sozlesme_ac()
    kalem = MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=1)
    donem = MaintenancePeriod(
        contract_id=sozlesme.id, cycle_start=AN, sequence_no=1, target_date=AN.date()
    )
    db.add_all([kalem, donem])
    await db.commit()
    so = await servis_isi_ac(tur="PB", contract_item_id=kalem.id, maintenance_period_id=donem.id)
    so.cozum_hedef_at = AN
    with pytest.raises(DBAPIError, match="ck_so_pb_sla"):
        await db.commit()
    await db.rollback()


async def test_rbac_sla_uclari(client, db, mudur, kullanici_ac) -> None:
    """Yeni uçların 403/2xx'i (matris dışında maddeye özgü)."""
    await kullanici_ac("satis1", "SATIS")
    so = await is_ac(client, mudur)
    await giris(client, "satis1")
    assert (await client.get(f"{TS}/operasyon/isler/{so['id']}/sla")).status_code == 403
    assert (await client.get(f"{TS}/sla-tanimlari/sozluk")).status_code == 403
    r = await client.put(
        f"{TS}/operasyon/isler/{so['id']}/kapanis-bilgisi", json={"gecikme_nedeni": "ULASIM"}
    )
    assert r.status_code == 403
    await giris(client, "mudur")
    r = await client.get(f"{TS}/sla-tanimlari/sozluk")
    assert r.status_code == 200 and r.json()["sla_yururlukte"] is False
    assert r.json()["terimler"]["IS_BEKLEMESI"] == "İş Beklemesi"
