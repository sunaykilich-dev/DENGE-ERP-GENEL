"""Teknik servis Dalga 3 şemasının taşıyıcı kısıtları gerçekten veritabanında mı (TS-180).

Kısıtlar iş kurallarının SON savunmasıdır: aynı depoya ikinci açık sayım
(`uq_rsayim_acik`) iki kişinin aynı depoyu sayıp çift KAYIP hareketi yazmasını,
giden kutusu tekilliği (`uq_smo_anlik`, `uq_smo_ozet`) worker'ın her turunda
yeni e-posta üretmesini engeller. Biri bir migration düzenlemesinde sessizce
düşerse servis katmanındaki kontrol yarış durumunda tek başına kalırdı.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import RentalCountLine

pytestmark = pytest.mark.integration


async def test_kritik_indeks_ve_kisitlar_var(db) -> None:
    indeksler = set(
        (
            await db.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        ).scalars()
    )
    for ad in (
        "uq_rsayim_acik",
        "uq_rsayim_satir_cihaz",
        "uq_rsayim_satir_seri",
        "uq_rsayim_satir_toplu",
        "uq_smo_anlik",
        "uq_smo_ozet",
        "ix_smo_bekleyen",
        "ix_ccmp_yetkinlik",
    ):
        assert ad in indeksler, f"{ad} indeksi yok"

    kisitlar = set((await db.execute(text("SELECT conname FROM pg_constraint"))).scalars())
    for ad in (
        "ck_rsayim_durum",
        "ck_rsayim_onay",
        "ck_rsayim_iptal",
        "ck_rsayim_satir_tek_kimlik",
        "ck_rsayim_satir_seri_adet",
        "ck_smo_tur",
        "ck_smo_durum",
        "ck_smo_deneme",
        "ck_smo_ozet_gunu",
        "ck_smo_gonderildi",
        "pk_course_competencies",
        "uq_scr_birim_tur_yetkinlik",
        "ck_scr_seviye",
        "ck_scr_birim",
        "ck_scr_tur",
    ):
        assert ad in kisitlar, f"{ad} kısıtı yok"


async def test_mesai_takvimi_tablolari_yok(db) -> None:
    """TS-200 MESAI kararı verilmedi (KD-23): `d3a000000003` atlandı."""
    tablolar = set(
        (
            await db.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            )
        ).scalars()
    )
    assert not {"service_work_calendar", "service_holidays"} & tablolar
    surum = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert surum >= "d3a000000004"


async def _depo_urun(db) -> tuple[int, int]:
    depo = (
        await db.execute(
            text(
                "INSERT INTO warehouses (code, name, kiralama_deposu, birim) "
                "VALUES ('KRD-S1', 'Kiralama deposu', true, 'HABERLESME') RETURNING id"
            )
        )
    ).scalar_one()
    urun = (
        await db.execute(
            text(
                "INSERT INTO products (code, name, name_key, identity_kind) "
                "VALUES ('KR-1', 'Telsiz', 'TELSIZ', 'SERI_NO') RETURNING id"
            )
        )
    ).scalar_one()
    return depo, urun


async def test_depo_basina_tek_acik_sayim(db) -> None:
    depo, _ = await _depo_urun(db)
    await db.execute(
        text("INSERT INTO rental_counts (warehouse_id, baslangic_at) VALUES (:d, now())"),
        {"d": depo},
    )
    await db.commit()
    with pytest.raises(DBAPIError, match="uq_rsayim_acik"):
        await db.execute(
            text("INSERT INTO rental_counts (warehouse_id, baslangic_at) VALUES (:d, now())"),
            {"d": depo},
        )
    await db.rollback()
    # Kapanmış sayım yenisini engellemez.
    await db.execute(
        text(
            "UPDATE rental_counts SET durum = 'IPTAL', iptal_gerekcesi = 'yanlış depo' "
            "WHERE warehouse_id = :d"
        ),
        {"d": depo},
    )
    await db.execute(
        text("INSERT INTO rental_counts (warehouse_id, baslangic_at) VALUES (:d, now())"),
        {"d": depo},
    )
    await db.commit()


async def test_sayim_onay_ve_iptal_kosullari(db) -> None:
    depo, _ = await _depo_urun(db)
    await db.commit()
    with pytest.raises(DBAPIError, match="ck_rsayim_onay"):
        await db.execute(
            text(
                "INSERT INTO rental_counts (warehouse_id, baslangic_at, durum) "
                "VALUES (:d, now(), 'ONAYLANDI')"
            ),
            {"d": depo},
        )
    await db.rollback()
    with pytest.raises(DBAPIError, match="ck_rsayim_iptal"):
        await db.execute(
            text(
                "INSERT INTO rental_counts (warehouse_id, baslangic_at, durum, iptal_gerekcesi) "
                "VALUES (:d, now(), 'IPTAL', '  ')"
            ),
            {"d": depo},
        )
    await db.rollback()


async def test_sayim_satiri_seri_anahtari_ve_tekillik(db) -> None:
    depo, urun = await _depo_urun(db)
    sayim = (
        await db.execute(
            text(
                "INSERT INTO rental_counts (warehouse_id, baslangic_at) "
                "VALUES (:d, now()) RETURNING id"
            ),
            {"d": depo},
        )
    ).scalar_one()
    await db.commit()

    satir = RentalCountLine(rental_count_id=sayim, product_id=urun, serial_text="  ab-12 34 ")
    db.add(satir)
    await db.commit()
    await db.refresh(satir)
    assert satir.serial_text == "ab-12 34"
    assert satir.serial_key == "AB-12 34"  # tek normalizasyon fonksiyonu (normalize_seri)

    db.add(RentalCountLine(rental_count_id=sayim, product_id=urun, serial_text="AB-12   34"))
    with pytest.raises(DBAPIError, match="uq_rsayim_satir_seri"):
        await db.commit()
    await db.rollback()

    # Seri satırında adet yalnız 0/1; toplu satır serbest ama ürün başına tek.
    with pytest.raises(DBAPIError, match="ck_rsayim_satir_seri_adet"):
        await db.execute(
            text(
                "INSERT INTO rental_count_lines (rental_count_id, product_id, serial_text, "
                "serial_key, sayilan_adet) VALUES (:s, :u, 'X9', 'X9', 3)"
            ),
            {"s": sayim, "u": urun},
        )
    await db.rollback()
    await db.execute(
        text(
            "INSERT INTO rental_count_lines (rental_count_id, product_id, sayilan_adet) "
            "VALUES (:s, :u, 12)"
        ),
        {"s": sayim, "u": urun},
    )
    await db.commit()
    with pytest.raises(DBAPIError, match="uq_rsayim_satir_toplu"):
        await db.execute(
            text(
                "INSERT INTO rental_count_lines (rental_count_id, product_id, sayilan_adet) "
                "VALUES (:s, :u, 4)"
            ),
            {"s": sayim, "u": urun},
        )
    await db.rollback()


async def _kullanici(db) -> int:
    rol = (await db.execute(text("SELECT id FROM roles ORDER BY id LIMIT 1"))).scalar_one_or_none()
    if rol is None:
        rol = (
            await db.execute(
                text("INSERT INTO roles (code, name) VALUES ('T_D3S', 'Test') RETURNING id")
            )
        ).scalar_one()
    return (
        await db.execute(
            text(
                "INSERT INTO users (full_name, username, password_hash, role_id) "
                "VALUES ('Eposta Test', 'eposta_d3s', 'x', :r) RETURNING id"
            ),
            {"r": rol},
        )
    ).scalar_one()


async def test_gunluk_ozet_kisi_basina_gunde_tek(db) -> None:
    kisi = await _kullanici(db)
    ekle = text(
        "INSERT INTO service_mail_outbox (tur, user_id, ozet_gunu, alici, konu, govde) "
        "VALUES ('GUNLUK_OZET', :k, DATE '2026-10-22', 'a@b.c', 'Özet', 'gövde')"
    )
    await db.execute(ekle, {"k": kisi})
    await db.commit()
    with pytest.raises(DBAPIError, match="uq_smo_ozet"):
        await db.execute(ekle, {"k": kisi})
    await db.rollback()


async def test_giden_kutusu_durum_kurallari(db) -> None:
    kisi = await _kullanici(db)
    await db.commit()
    with pytest.raises(DBAPIError, match="ck_smo_gonderildi"):
        await db.execute(
            text(
                "INSERT INTO service_mail_outbox (tur, user_id, ozet_gunu, alici, konu, govde, "
                "durum) VALUES ('GUNLUK_OZET', :k, DATE '2026-10-22', 'a@b.c', 'k', 'g', "
                "'GONDERILDI')"
            ),
            {"k": kisi},
        )
    await db.rollback()
    with pytest.raises(DBAPIError, match="ck_smo_deneme"):
        await db.execute(
            text(
                "INSERT INTO service_mail_outbox (tur, user_id, ozet_gunu, alici, konu, govde, "
                "deneme) VALUES ('GUNLUK_OZET', :k, DATE '2026-10-23', 'a@b.c', 'k', 'g', 11)"
            ),
            {"k": kisi},
        )
    await db.rollback()
    with pytest.raises(DBAPIError, match="ck_smo_ozet_gunu"):
        await db.execute(
            text(
                "INSERT INTO service_mail_outbox (tur, user_id, alici, konu, govde) "
                "VALUES ('GUNLUK_OZET', :k, 'a@b.c', 'k', 'g')"
            ),
            {"k": kisi},
        )
    await db.rollback()


async def test_yetkinlik_eslemesi_tekil_ve_tur_kumesi(db) -> None:
    yetkinlik = (
        await db.execute(
            text("INSERT INTO competencies (kod, ad) VALUES ('XR', 'X-Ray') RETURNING id")
        )
    ).scalar_one()
    ekle = text(
        "INSERT INTO service_competency_requirements (birim, tur, competency_id, min_seviye) "
        "VALUES ('GUVENLIK', 'PB', :y, 3)"
    )
    await db.execute(ekle, {"y": yetkinlik})
    await db.commit()
    with pytest.raises(DBAPIError, match="uq_scr_birim_tur_yetkinlik"):
        await db.execute(ekle, {"y": yetkinlik})
    await db.rollback()
    with pytest.raises(DBAPIError, match="ck_scr_tur"):
        await db.execute(
            text(
                "INSERT INTO service_competency_requirements "
                "(birim, tur, competency_id, min_seviye) VALUES ('GUVENLIK', 'BAKIM', :y, 2)"
            ),
            {"y": yetkinlik},
        )
    await db.rollback()
    with pytest.raises(DBAPIError, match="ck_scr_seviye"):
        await db.execute(
            text(
                "INSERT INTO service_competency_requirements "
                "(birim, tur, competency_id, min_seviye) VALUES ('GUVENLIK', 'ARIZA', :y, 5)"
            ),
            {"y": yetkinlik},
        )
    await db.rollback()
