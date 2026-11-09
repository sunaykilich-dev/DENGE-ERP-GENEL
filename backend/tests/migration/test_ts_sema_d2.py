"""Teknik servis Dalga 2 şemasının taşıyıcı kısıtları gerçekten veritabanında mı (TS-080).

Bu kısıtlar iş kurallarının SON savunmasıdır: aynı cihaza ikinci açık atölye
kaydı (`uq_atolye_acik_ekipman`), aynı kiralık cihazın çakışan tahsisi
(`ex_rtahsis_cihaz_cakisma` — M10.1 ile kaldırıldı, uyarıya döndü), çakışan işçilik tarifesi
(`ex_iscilik_tarife_cakisma`), servis stok defterinin değiştirilemezliği
(`trg_stok_hareket_degismez`), PB/atölye işine SLA damgası (`ck_so_pb_sla`).
Biri bir migration düzenlemesinde sessizce düşerse servis katmanındaki kontrol
yarış durumunda tek başına kalırdı; bu test onu yakalar. Canlı tablolara
dokunan değişikliklerin (plan §1.12) mevcut satır davranışını değiştirmediği
de burada sınanır.
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
        "uq_slap_aktif",
        "uq_salert_acik",
        "uq_atolye_acik_ekipman",
        "uq_rasset_urun_seri",
        "uq_rhareket_ters",
        "uq_stok_hareket_acilis",
        "uq_stok_hareket_ters",
        "uq_stok_sayim_acik",
        "uq_parca_talep_acik",
        "uq_iscilik_tarife_acik",
        "uq_tp_kisi_kurs_yil",
        "uq_so_kiralama_tur_acik",
        "ix_so_sla_hedef",
        "ix_quote_birim_durum_tarih",
        # M10.1: EXCLUDE yerine aynı ifadeli GiST indeksi (e1a000000003).
        "ix_rtahsis_cihaz_aralik",
    ):
        assert ad in indeksler, f"{ad} indeksi yok"

    kisitlar = set((await db.execute(text("SELECT conname FROM pg_constraint"))).scalars())
    for ad in (
        "ck_so_pb_sla",
        "fk_so_sla_politikasi",
        "uq_so_id_ekipman",
        "fk_atolye_servis_ekipman",
        "uq_atolye_servis_isi",
        "fk_rasset_urun_kimlik",
        "ck_rasset_seri_takipli",
        "ck_warehouse_tur_tekil",
        "ck_stok_hareket_tur_yon",
        "ck_products_yedek_parca_serisiz",
        "ex_iscilik_tarife_cakisma",
        "uq_sof_is",
        "ck_quote_durum",
        "ck_quote_birim",
        "fk_hold_teklif",
        "uq_tca_gozlem",
        "fk_so_kiralama",
        "fk_atolye_kiralik_cihaz",
    ):
        assert ad in kisitlar, f"{ad} kısıtı yok"

    tetikler = set(
        (await db.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))).scalars()
    )
    assert {"trg_stok_hareket_degismez", "trg_rhareket_degismez"} <= tetikler


async def test_numara_sequencelari_tabloya_bagli(db) -> None:
    """OWNED BY: test temizliğindeki RESTART IDENTITY onları da sıfırlar."""
    satirlar = (
        await db.execute(
            text(
                "SELECT s.relname, t.relname FROM pg_class s "
                "JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a' "
                "JOIN pg_class t ON t.oid = d.refobjid "
                "WHERE s.relkind = 'S' AND s.relname IN "
                "('atolye_no_seq', 'atolye_kabul_grubu_seq', 'rental_no_seq', "
                "'stock_count_no_seq')"
            )
        )
    ).all()
    assert dict(satirlar) == {
        "atolye_no_seq": "workshop_records",
        "atolye_kabul_grubu_seq": "workshop_records",
        "rental_no_seq": "rentals",
        "stock_count_no_seq": "stock_counts",
    }


async def test_sla_tohumu_test_temizliginden_sag_cikar(db) -> None:
    """Politika tohumu `users`'a FK taşımaz; TRUNCATE ... CASCADE onu silmez."""
    satirlar = dict(
        (
            await db.execute(
                text(
                    "SELECT oncelik, cozum_saat FROM service_sla_policies "
                    "WHERE is_active AND birim IS NULL"
                )
            )
        ).all()
    )
    assert {k: int(v) for k, v in satirlar.items()} == {"KRITIK": 12, "YUKSEK": 24, "NORMAL": 72}


async def test_teklif_durum_kumesi_genisledi_eskiler_korundu(db) -> None:
    tanim = (
        await db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_quote_durum'"
            )
        )
    ).scalar_one()
    for durum in (
        "TASLAK",
        "ONAY_BEKLIYOR",
        "ONAYLANDI",
        "GONDERILDI",
        "GORUNTULENDI",
        "REVIZE_EDILDI",
        "KABUL",
        "RED",
        "SURESI_DOLDU",
        "SIPARISE_DONUSTU",
        "IPTAL",
    ):
        assert f"'{durum}'" in tanim, durum


async def _urun_depo(db, *, servis_deposu: bool = True) -> tuple[int, int]:
    urun = (
        await db.execute(
            text(
                "INSERT INTO products (code, name, name_key, identity_kind, yedek_parca) "
                "VALUES ('YP-1', 'Sigorta', 'SIGORTA', 'YOK', true) RETURNING id"
            )
        )
    ).scalar_one()
    depo = (
        await db.execute(
            text(
                "INSERT INTO warehouses (code, name, servis_deposu, birim) "
                "VALUES ('SRV-T1', 'Servis deposu', :s, 'GUVENLIK') RETURNING id"
            ),
            {"s": servis_deposu},
        )
    ).scalar_one()
    return urun, depo


async def test_servis_stok_hareketi_degistirilemez_mobilite_satiri_degisir(db) -> None:
    urun, depo = await _urun_depo(db)
    servis = (
        await db.execute(
            text(
                "INSERT INTO stock_movements (product_id, warehouse_id, qty, reason, hareket_turu) "
                "VALUES (:u, :d, 5, 'GIRIS', 'GIRIS') RETURNING id"
            ),
            {"u": urun, "d": depo},
        )
    ).scalar_one()
    mobilite = (
        await db.execute(
            text(
                "INSERT INTO stock_movements (product_id, warehouse_id, qty, reason) "
                "VALUES (:u, :d, 3, 'GIRIS') RETURNING id"
            ),
            {"u": urun, "d": depo},
        )
    ).scalar_one()
    await db.commit()

    # Mobilite satırının bugünkü davranışı değişmez (tetikleyici WHEN koşulu).
    await db.execute(
        text("UPDATE stock_movements SET notes = 'düzeltme' WHERE id = :i"), {"i": mobilite}
    )
    await db.commit()

    with pytest.raises(DBAPIError, match="değiştirilemez"):
        await db.execute(text("UPDATE stock_movements SET qty = 7 WHERE id = :i"), {"i": servis})
    await db.rollback()
    with pytest.raises(DBAPIError, match="silinemez"):
        await db.execute(text("DELETE FROM stock_movements WHERE id = :i"), {"i": servis})
    await db.rollback()


async def test_hareket_turu_yon_eslemesi_semada_kilitli(db) -> None:
    urun, depo = await _urun_depo(db)
    await db.commit()
    with pytest.raises(DBAPIError, match="ck_stok_hareket_tur_yon"):
        await db.execute(
            text(
                "INSERT INTO stock_movements (product_id, warehouse_id, qty, reason, hareket_turu) "
                "VALUES (:u, :d, 2, 'CIKIS', 'ZAYI')"
            ),
            {"u": urun, "d": depo},
        )
    await db.rollback()


async def test_depo_hem_servis_hem_kiralama_olamaz(db) -> None:
    with pytest.raises(DBAPIError, match="ck_warehouse_tur_tekil"):
        await db.execute(
            text(
                "INSERT INTO warehouses (code, name, servis_deposu, kiralama_deposu, birim) "
                "VALUES ('X1', 'Karışık', true, true, 'GUVENLIK')"
            )
        )
    await db.rollback()


async def test_atolye_isine_sla_damgalanamaz(db) -> None:
    """`ck_so_pb_sla`: PB ve atölye işi SLA dışıdır (TS-081)."""
    with pytest.raises(DBAPIError, match="ck_so_pb_sla"):
        await db.execute(
            text(
                "INSERT INTO service_orders "
                "(so_no, birim, tur, kategori, konu, source_system, cozum_hedef_at) "
                "VALUES ('SRV-202610-000009', 'HABERLESME', 'ATOLYE', 'ATOLYE', 'deneme', "
                "'TEST', now())"
            )
        )
    await db.rollback()


async def test_iscilik_tarifesi_cakisamaz(db) -> None:
    await db.execute(
        text(
            "INSERT INTO service_labor_rates (birim, valid_from, valid_to, hourly_cost) "
            "VALUES ('GUVENLIK', '2026-01-01', '2026-07-01', 500)"
        )
    )
    await db.commit()
    with pytest.raises(DBAPIError, match="ex_iscilik_tarife_cakisma"):
        await db.execute(
            text(
                "INSERT INTO service_labor_rates (birim, valid_from, hourly_cost) "
                "VALUES ('GUVENLIK', '2026-06-01', 600)"
            )
        )
    await db.rollback()
    # Yarı açık aralık: bitişle aynı gün başlayan tarife çakışmaz.
    await db.execute(
        text(
            "INSERT INTO service_labor_rates (birim, valid_from, hourly_cost) "
            "VALUES ('GUVENLIK', '2026-07-01', 600)"
        )
    )
    await db.commit()
