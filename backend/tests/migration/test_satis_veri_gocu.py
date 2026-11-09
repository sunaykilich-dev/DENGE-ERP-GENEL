"""fcsatis00001 veri göçü (KARARLAR 2026-11-09 S1.1, S2.1).

- Tek genel iskonto eşiği rol tablosuna emilir: eski eşik "DIGER" olur,
  satış rolleri karar değerlerini alır; eski ayar satırı silinir; downgrade
  eşiği geri yazar.
- Eski serbest metin kaybedilme nedeni "DIGER" + açıklama olur; boş metin
  NULL'a çekilir.

Asıl test veritabanına dokunulmaz: ayrı, boş bir veritabanında `fba000000001`
şemasına kadar çıkılır, eski biçimde veri yazılır, sonra yükseltilir.
"""

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


def _alembic(komut: list[str], db_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["uv", "run", "alembic", *komut],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def gocu_veritabani(test_db_url: str):
    parcalar = urlsplit(test_db_url)
    ad = parcalar.path.lstrip("/") + "_satis_gocu"
    yonetim = urlunsplit(parcalar._replace(path="/postgres"))
    motor = sa.create_engine(yonetim, isolation_level="AUTOCOMMIT")
    with motor.connect() as baglanti:
        baglanti.execute(sa.text(f'DROP DATABASE IF EXISTS "{ad}"'))
        baglanti.execute(sa.text(f'CREATE DATABASE "{ad}"'))
    motor.dispose()
    yield urlunsplit(parcalar._replace(path=f"/{ad}"))
    motor = sa.create_engine(yonetim, isolation_level="AUTOCOMMIT")
    with motor.connect() as baglanti:
        baglanti.execute(sa.text(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)'))
    motor.dispose()


def test_esik_ve_kayip_nedeni_gocu(gocu_veritabani: str) -> None:
    r = _alembic(["upgrade", "fba000000001"], gocu_veritabani)
    assert r.returncode == 0, r.stderr[-2000:]
    motor = sa.create_engine(gocu_veritabani)
    with motor.begin() as b:
        b.execute(
            sa.text(
                "INSERT INTO settings (key, value) VALUES "
                "('iskonto_onay_esigi_yuzde', CAST('15.0' AS jsonb))"
            )
        )
        hesap = b.execute(
            sa.text(
                "INSERT INTO accounts (title, title_key, is_musteri) "
                "VALUES ('A', 'a', true) RETURNING id"
            )
        ).scalar_one()
        for no, durum, neden in (
            ("T1", "RED", "Fiyat pahalı"),
            ("T2", "RED", "   "),
            ("T3", "KABUL", None),
        ):
            b.execute(
                sa.text(
                    "INSERT INTO quotes (quote_no, customer_id, status, lost_reason) "
                    "VALUES (:n, :c, :s, :l)"
                ),
                {"n": no, "c": hesap, "s": durum, "l": neden},
            )

    r = _alembic(["upgrade", "fcsatis00001"], gocu_veritabani)
    assert r.returncode == 0, r.stderr[-2000:]
    with motor.connect() as b:
        ayarlar = dict(b.execute(sa.text("SELECT key, value FROM settings")).all())
        assert "iskonto_onay_esigi_yuzde" not in ayarlar
        tablo = ayarlar["iskonto_rol_limitleri"]
        tablo = json.loads(tablo) if isinstance(tablo, str) else tablo
        assert tablo == {"SATIS": 10, "SATIS_DESTEK": 5, "SATIS_MUDURU": 25, "DIGER": 15.0}
        satirlar = dict(
            (no, (kod, neden))
            for no, kod, neden in b.execute(
                sa.text("SELECT quote_no, lost_reason_kod, lost_reason FROM quotes")
            ).all()
        )
        assert satirlar == {
            "T1": ("DIGER", "Fiyat pahalı"),
            "T2": (None, None),
            "T3": (None, None),
        }

    r = _alembic(["downgrade", "fba000000001"], gocu_veritabani)
    assert r.returncode == 0, r.stderr[-2000:]
    with motor.connect() as b:
        ayarlar = dict(b.execute(sa.text("SELECT key, value FROM settings")).all())
    motor.dispose()
    assert "iskonto_rol_limitleri" not in ayarlar
    assert float(ayarlar["iskonto_onay_esigi_yuzde"]) == 15.0
