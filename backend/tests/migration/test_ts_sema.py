"""Teknik servis Dalga 0+1 şemasının taşıyıcı kısıtları gerçekten veritabanında mı (TS-018).

Bu kısıtlar iş kurallarının SON savunmasıdır: "1 cihaz = 1 PB iş emri"
(`uq_so_pb_cihaz_donem`), tek aktif plan (`uq_svcplan_aktif`), aynı ekipman
iki sözleşmede olamaz (`ex_mci_ekipman_cakisma`), kişi aynı anda iki yerde
olamaz (`ex_ste_kisi_cakisma`, `ex_svcmusait_cakisma`), olay geçmişi
silinemez (`trg_soe_salt_ekleme`). Biri bir migration düzenlemesinde
sessizce düşerse servis katmanındaki kontrol yarış durumunda tek başına
kalırdı; bu test onu yakalar.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


async def test_kritik_indeks_ve_kisitlar_var(db) -> None:
    indeksler = set(
        (
            await db.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        ).scalars()
    )
    for ad in (
        "uq_so_pb_cihaz_donem",
        "uq_svcplan_aktif",
        "uq_hold_aktif",
        "uq_soa_tek_sorumlu",
        "uq_ste_acik_kisi",
        "uq_user_units_birincil",
        "uq_addresses_tesis_aktif",
        "uq_svceq_cihaz",
    ):
        assert ad in indeksler, f"{ad} indeksi yok"

    kisitlar = set((await db.execute(text("SELECT conname FROM pg_constraint"))).scalars())
    for ad in (
        "ex_mci_ekipman_cakisma",
        "ex_svcmusait_cakisma",
        "ex_ste_kisi_cakisma",
        "fk_so_ekipman",
        "fk_so_sozlesme_kalemi",
        "fk_so_bakim_donemi",
        "ck_so_pb_bag",
        "ck_addresses_satir",
    ):
        assert ad in kisitlar, f"{ad} kısıtı yok"

    tetikler = set(
        (await db.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))).scalars()
    )
    assert "trg_soe_salt_ekleme" in tetikler


async def test_numara_sequencelari_tabloya_bagli(db) -> None:
    """OWNED BY: test temizliğindeki RESTART IDENTITY onları da sıfırlar."""
    satirlar = (
        await db.execute(
            text(
                "SELECT s.relname, t.relname FROM pg_class s "
                "JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a' "
                "JOIN pg_class t ON t.oid = d.refobjid "
                "WHERE s.relkind = 'S' AND s.relname IN "
                "('service_order_no_seq', 'service_visit_no_seq', 'seq_bakim_sozlesme_no')"
            )
        )
    ).all()
    assert dict(satirlar) == {
        "service_order_no_seq": "service_orders",
        "service_visit_no_seq": "service_visits",
        "seq_bakim_sozlesme_no": "maintenance_contracts",
    }


async def test_katalog_tohumlari_test_temizliginden_sag_cikar(db) -> None:
    """Bekleme/arıza nedeni tohumu TRUNCATE ... CASCADE'e takılmamalı: servis
    işi testleri bu kataloğa dayanır."""
    nedenler = set((await db.execute(text("SELECT kod FROM service_hold_reasons"))).scalars())
    assert {"MALZEME", "MUSTERI_ONAYI", "BAKIM_UYGUNSUZLUK", "DIGER"} <= nedenler
    durduranlar = set(
        (
            await db.execute(text("SELECT kod FROM service_hold_reasons WHERE sla_durdurur"))
        ).scalars()
    )
    assert durduranlar == {"MUSTERI_ONAYI", "TEKLIF", "MUSTERI_ERISIMI"}
    birimler = (
        await db.execute(text("SELECT count(DISTINCT birim) FROM service_fault_reasons"))
    ).scalar_one()
    assert birimler == 5


async def test_olay_gecmisi_guncellenemez_ve_silinemez(db) -> None:
    so_id = (
        await db.execute(
            text(
                "INSERT INTO service_orders (so_no, birim, tur, kategori, konu, source_system) "
                "VALUES ('SRV-202610-000001', 'GUVENLIK', 'ARIZA', 'GUNLUK_SERVIS', 'deneme', "
                "'TEST') RETURNING id"
            )
        )
    ).scalar_one()
    olay_id = (
        await db.execute(
            text(
                "INSERT INTO service_order_events "
                "(service_order_id, olay_turu, ozet, olusma_zamani) "
                "VALUES (:so, 'OLUSTUR', 'açıldı', now()) RETURNING id"
            ),
            {"so": so_id},
        )
    ).scalar_one()
    await db.commit()

    with pytest.raises(DBAPIError, match="yalnız eklenebilir"):
        await db.execute(
            text("UPDATE service_order_events SET ozet = 'x' WHERE id = :i"), {"i": olay_id}
        )
    await db.rollback()
    with pytest.raises(DBAPIError, match="yalnız eklenebilir"):
        await db.execute(text("DELETE FROM service_order_events WHERE id = :i"), {"i": olay_id})
    await db.rollback()


async def test_api_ile_acilan_is_musterisiz_olamaz(db) -> None:
    """`ck_so_musteri`: müşterisiz kayıt yalnız göçte (source_system dolu)."""
    with pytest.raises(DBAPIError, match="ck_so_musteri"):
        await db.execute(
            text(
                "INSERT INTO service_orders (so_no, birim, tur, kategori, konu) "
                "VALUES ('SRV-202610-000002', 'GUVENLIK', 'ARIZA', 'GUNLUK_SERVIS', 'deneme')"
            )
        )
    await db.rollback()
