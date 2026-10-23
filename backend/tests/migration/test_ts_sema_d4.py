"""Teknik servis Dalga 4 şemasının taşıyıcı kısıtları gerçekten veritabanında mı (TS-210).

`trg_audit_degistirilemez` denetim izinin değiştirilemezliğini uygulama
kodundan ve kurulumdaki hak kısıtından bağımsız kılar: DELETE her zaman,
UPDATE ise KVKK maskesi ve FK `SET NULL` dışında reddedilir.
`ck_user_permissions_vekalet` vekâletin 30 günü aşmasını ve süreli "geri
alma" satırını şemada engeller.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import kvkk

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
MASKE = '{"kvkk": "değer imha edildi"}'


async def test_tetikleyici_kisit_ve_indeks_var(db) -> None:
    tetikleyiciler = set(
        (
            await db.execute(
                text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'audit_logs'::regclass")
            )
        ).scalars()
    )
    assert "trg_audit_degistirilemez" in tetikleyiciler
    kisitlar = set((await db.execute(text("SELECT conname FROM pg_constraint"))).scalars())
    assert {"ck_user_permissions_vekalet", "fk_user_permissions_veren"} <= kisitlar
    indeksler = set(
        (
            await db.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        ).scalars()
    )
    assert "ix_user_permissions_bitis" in indeksler
    surum = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert surum >= "d4a000000002"


async def _kullanici(db, ad: str) -> int:
    rol = (await db.execute(text("SELECT id FROM roles ORDER BY id LIMIT 1"))).scalar()
    if rol is None:
        rol = (
            await db.execute(
                text("INSERT INTO roles (code, name) VALUES ('T_D4', 'Test') RETURNING id")
            )
        ).scalar_one()
    return (
        await db.execute(
            text(
                "INSERT INTO users (username, full_name, password_hash, role_id) "
                "VALUES (:u, :u, 'x', :r) RETURNING id"
            ),
            {"u": ad, "r": rol},
        )
    ).scalar_one()


async def _denetim(db, *, kisisel: bool, user_id: int | None = None) -> int:
    kimlik = (
        await db.execute(
            text(
                "INSERT INTO audit_logs (user_id, entity, entity_id, action, old_value, "
                "new_value, is_personal_data, ip) VALUES (:k, 'accounts', '7', 'guncelle', "
                """'{"telefon": "05551112233"}', '{"telefon": "05559998877"}', :p, """
                "'10.0.0.1') RETURNING id"
            ),
            {"k": user_id, "p": kisisel},
        )
    ).scalar_one()
    await db.commit()
    return kimlik


async def _reddedilir(db, sql: str, params: dict) -> None:
    with pytest.raises(DBAPIError, match="Denetim kaydı|Kişisel veri"):
        await db.execute(text(sql), params)
    await db.rollback()


async def test_denetim_kaydi_silinemez(db) -> None:
    kimlik = await _denetim(db, kisisel=True)
    await _reddedilir(db, "DELETE FROM audit_logs WHERE id = :i", {"i": kimlik})
    assert (
        await db.execute(text("SELECT count(*) FROM audit_logs WHERE id = :i"), {"i": kimlik})
    ).scalar_one() == 1


async def test_denetim_kaydi_degistirilemez(db) -> None:
    kimlik = await _denetim(db, kisisel=True)
    for sql in (
        "UPDATE audit_logs SET action = 'sil' WHERE id = :i",
        "UPDATE audit_logs SET entity_id = '8' WHERE id = :i",
        "UPDATE audit_logs SET is_personal_data = false WHERE id = :i",
        "UPDATE audit_logs SET ip = NULL WHERE id = :i",
        "UPDATE audit_logs SET created_at = created_at - interval '1 day' WHERE id = :i",
        # Maske dışında bir değere "düzeltmek" de yasak.
        """UPDATE audit_logs SET new_value = '{"telefon": "0"}' WHERE id = :i""",
        """UPDATE audit_logs SET old_value = '{"kvkk": "x", "telefon": "0"}' WHERE id = :i""",
    ):
        await _reddedilir(db, sql, {"i": kimlik})


async def test_kvkk_maskesi_yalniz_kisisel_satirda_gecer(db) -> None:
    kisisel = await _denetim(db, kisisel=True)
    await db.execute(
        text("UPDATE audit_logs SET old_value = :m, new_value = :m WHERE id = :i"),
        {"m": MASKE, "i": kisisel},
    )
    await db.commit()
    satir = (
        await db.execute(
            text("SELECT old_value, new_value, action FROM audit_logs WHERE id = :i"),
            {"i": kisisel},
        )
    ).one()
    assert satir.old_value == kvkk.DEGER_SILINDI and satir.new_value == kvkk.DEGER_SILINDI
    assert satir.action == "guncelle", "olay korunur"

    kisisel_degil = await _denetim(db, kisisel=False)
    await _reddedilir(
        db,
        "UPDATE audit_logs SET old_value = :m, new_value = :m WHERE id = :i",
        {"m": MASKE, "i": kisisel_degil},
    )


async def test_kullanici_silinince_satir_kalir_kim_bosalir(db) -> None:
    kisi = await _kullanici(db, "d4_gidecek")
    kimlik = await _denetim(db, kisisel=False, user_id=kisi)
    baska = await _kullanici(db, "d4_baska")
    await db.commit()
    await _reddedilir(
        db, "UPDATE audit_logs SET user_id = :b WHERE id = :i", {"b": baska, "i": kimlik}
    )
    await db.execute(text("DELETE FROM users WHERE id = :k"), {"k": kisi})
    await db.commit()
    assert (
        await db.execute(text("SELECT user_id FROM audit_logs WHERE id = :i"), {"i": kimlik})
    ).scalar_one() is None


async def _izin(db) -> str:
    kod = (await db.execute(text("SELECT code FROM permissions LIMIT 1"))).scalar()
    if kod is None:
        kod = "t_d4.izin"
        await db.execute(
            text("INSERT INTO permissions (code, module, description) VALUES (:c, 'T', 'T')"),
            {"c": kod},
        )
    return kod


async def test_vekalet_kisiti(db) -> None:
    kisi = await _kullanici(db, "d4_vekil")
    kod = await _izin(db)
    await db.commit()
    ekle = (
        "INSERT INTO user_permissions (user_id, permission_code, allow, baslangic_at, bitis_at) "
        "VALUES (:u, :c, :a, :b, :s)"
    )
    for allow, bas, bit in (
        (True, T0, T0 + timedelta(days=30, seconds=1)),  # 31 gün
        (True, T0, T0),  # sıfır süre
        (True, T0, None),  # yalnız bir uç
        (False, T0, T0 + timedelta(days=3)),  # süreli geri alma
    ):
        with pytest.raises(DBAPIError, match="ck_user_permissions_vekalet"):
            await db.execute(text(ekle), {"u": kisi, "c": kod, "a": allow, "b": bas, "s": bit})
        await db.rollback()

    # Tam 30 gün ve kalıcı istisna geçer.
    await db.execute(
        text(ekle),
        {
            "u": kisi,
            "c": kod,
            "a": True,
            "b": T0,
            "s": T0 + timedelta(days=30),
        },
    )
    await db.execute(text("DELETE FROM user_permissions WHERE user_id = :u"), {"u": kisi})
    await db.execute(
        text(
            "INSERT INTO user_permissions (user_id, permission_code, allow) VALUES (:u, :c, false)"
        ),
        {"u": kisi, "c": kod},
    )
    await db.commit()
