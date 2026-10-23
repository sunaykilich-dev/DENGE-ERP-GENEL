"""Teknik servis Dalga 4 şema iskeletinin tek-kaynak sözleşmeleri (TS-210).

Zincir sırası (`d4a…01` → `d3a…04`, `d4a…02` → `d4a…01`); vekâlet azami
süresi model, CHECK ve migration'da aynı; denetim tetikleyicisinin maske
anahtarı `kvkk.DEGER_SILINDI` ile uyumlu; süreli istisna `Clock` anı
bilinmeden sayılmaz (fail-closed) ve kalıcı istisnaların davranışı değişmez.
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models import Role, RolePermission, User, UserPermission
from app.models.rbac import VEKALET_AZAMI_GUN
from app.services import kvkk

SURUMLER = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _rev(dosya_on_eki: str):
    yol = next(SURUMLER.glob(f"{dosya_on_eki}_*.py"))
    spec = importlib.util.spec_from_file_location(yol.stem, yol)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_zincir_sirasi() -> None:
    assert _rev("d4a000000001").down_revision == "d3a000000004"
    assert _rev("d4a000000002").down_revision == "d4a000000001"


def test_vekalet_azami_gun_tek_kaynak() -> None:
    assert VEKALET_AZAMI_GUN == 30
    assert _rev("d4a000000002").VEKALET_AZAMI_GUN == VEKALET_AZAMI_GUN
    kisit = {
        c.name: str(c.sqltext)
        for c in UserPermission.__table__.constraints
        if c.name and hasattr(c, "sqltext")
    }["ck_user_permissions_vekalet"]
    assert f"interval '{VEKALET_AZAMI_GUN} days'" in kisit


def test_denetim_maskesi_tetikleyici_anahtariyla_uyumlu() -> None:
    """Tetikleyici yalnız `{"kvkk": ...}` biçimli maskeye izin verir; KVKK
    servisinin maskesi başka biçime geçerse bütün imhalar DB'de reddedilir."""
    anahtar = _rev("d4a000000001").MASKE_ANAHTARI
    assert set(kvkk.DEGER_SILINDI) == {anahtar}


def _kisi(*istisnalar: UserPermission, rol_izinleri: tuple[str, ...] = ()) -> User:
    rol = Role(
        code="X", name="X", permissions=[RolePermission(permission_code=k) for k in rol_izinleri]
    )
    return User(username="u", role=rol, izin_istisnalari=list(istisnalar))


T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _vekalet(kod: str) -> UserPermission:
    return UserPermission(
        permission_code=kod,
        allow=True,
        baslangic_at=T0,
        bitis_at=T0 + timedelta(days=3),
    )


def test_sureli_istisna_an_bilinmeden_sayilmaz() -> None:
    kisi = _kisi(_vekalet("servis.ata"))
    assert not kisi.has("servis.ata")
    assert "servis.ata" not in kisi.etkin_izinler()


def test_sureli_istisna_yalniz_araliginda_gecerli() -> None:
    kisi = _kisi(_vekalet("servis.ata"))
    for an, beklenen in (
        (T0 - timedelta(seconds=1), False),
        (T0, True),
        (T0 + timedelta(days=2), True),
        (T0 + timedelta(days=3), False),  # bitiş dahil değil
    ):
        kisi.izin_anini_ata(an)
        assert kisi.has("servis.ata") is beklenen, an
        assert ("servis.ata" in kisi.etkin_izinler()) is beklenen, an


def test_kalici_istisna_davranisi_degismez() -> None:
    kisi = _kisi(
        UserPermission(permission_code="a", allow=True),
        UserPermission(permission_code="b", allow=False),
        rol_izinleri=("b", "c"),
    )
    for an in (None, T0):
        kisi.izin_anini_ata(an)
        assert kisi.has("a") and not kisi.has("b") and kisi.has("c")
        assert kisi.etkin_izinler() == ["a", "c"]
