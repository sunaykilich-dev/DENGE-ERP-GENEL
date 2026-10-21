"""Migration zinciri iki yönde de yürümeli.

Plan §7 bunu öngörmüştü ama test yazılmamıştı ve zincir gerçekten kırıktı:
`uq_products_id_kimlik`, ona bağlı `fk_devices_urun_kimlik` yüzünden
düşürülemiyordu çünkü autogenerate onu `devices` tablosundan ÖNCE silmeye
çalışıyordu.

Bu hatanın görüneceği tek an, **üretimde bir sürümü geri almak zorunda
kaldığın an**dır — ve o anda şema yarı düşmüş halde kalır. Yükseltme testi
bunu yakalamaz; yalnız downgrade yakalar.
"""

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
def bos_veritabani(test_db_url: str):
    """Zincir testi için AYRI ve boş bir veritabanı.

    Asıl test veritabanına dokunulmaz: downgrade base her şeyi silerdi ve
    aynı anda koşan diğer testler yarısında kalırdı.
    """
    parcalar = urlsplit(test_db_url)
    ad = parcalar.path.lstrip("/") + "_zincir"
    yonetim = urlunsplit(parcalar._replace(path="/postgres"))
    motor = sa.create_engine(yonetim, isolation_level="AUTOCOMMIT")
    with motor.connect() as baglanti:
        baglanti.execute(sa.text(f'DROP DATABASE IF EXISTS "{ad}"'))
        baglanti.execute(sa.text(f'CREATE DATABASE "{ad}"'))
    motor.dispose()

    yield urlunsplit(parcalar._replace(path=f"/{ad}"))

    motor = sa.create_engine(yonetim, isolation_level="AUTOCOMMIT")
    with motor.connect() as baglanti:
        baglanti.execute(sa.text(f'DROP DATABASE IF EXISTS "{ad}"'))
    motor.dispose()


def test_upgrade_downgrade_upgrade(bos_veritabani: str) -> None:
    """head → base → head. Her adım hatasız bitmeli ve şema aynı kalmalı."""
    ilk = _alembic(["upgrade", "head"], bos_veritabani)
    assert ilk.returncode == 0, f"upgrade head başarısız:\n{ilk.stderr[-2000:]}"

    senkron = sa.create_engine(bos_veritabani)
    with senkron.connect() as b:
        tablo_once = b.execute(
            sa.text("select count(*) from information_schema.tables where table_schema='public'")
        ).scalar_one()
        kisit_once = b.execute(
            sa.text("select count(*) from pg_constraint where contype='x'")
        ).scalar_one()

    geri = _alembic(["downgrade", "base"], bos_veritabani)
    assert geri.returncode == 0, (
        f"downgrade base başarısız — üretimde sürüm geri alınamaz demektir:\n{geri.stderr[-2000:]}"
    )

    with senkron.connect() as b:
        kalan = b.execute(
            sa.text(
                "select count(*) from information_schema.tables "
                "where table_schema='public' and table_name <> 'alembic_version'"
            )
        ).scalar_one()
    assert kalan == 0, f"downgrade sonrası {kalan} tablo kaldı"

    tekrar = _alembic(["upgrade", "head"], bos_veritabani)
    assert tekrar.returncode == 0, f"ikinci upgrade başarısız:\n{tekrar.stderr[-2000:]}"

    with senkron.connect() as b:
        tablo_sonra = b.execute(
            sa.text("select count(*) from information_schema.tables where table_schema='public'")
        ).scalar_one()
        kisit_sonra = b.execute(
            sa.text("select count(*) from pg_constraint where contype='x'")
        ).scalar_one()
    senkron.dispose()

    assert tablo_sonra == tablo_once, "gidiş-dönüş sonrası tablo sayısı değişti"
    assert kisit_sonra == kisit_once, "EXCLUDE kısıtları gidiş-dönüşte kayboldu"


def test_tek_head_var() -> None:
    """İki head, yükseltmede çatallaşma demektir: `alembic upgrade head` patlar."""
    sonuc = _alembic(["heads"], os.environ.get("DATABASE_URL", ""))
    assert sonuc.returncode == 0, sonuc.stderr[-1000:]
    basliklar = [s for s in sonuc.stdout.splitlines() if s.strip()]
    assert len(basliklar) == 1, f"birden çok head var:\n{sonuc.stdout}"
