"""Yetki yükseltme kuralları (TS-006) ve birim kapsamı (TS-003) — DB'siz.

Kurallar saf fonksiyon; burada kalıcı olmayan (transient) `User`/`Role`
nesneleriyle her kapsam × durum birleşimi sınanır. Sorgu süzgeçleri
(`kapsam_isler`, `kapsam_personel`) gerçek veritabanında
`tests/integration/test_birim_kapsami.py`'de.
"""

import pytest

from app.models import Role, RolePermission, User, UserPermission, UserUnit
from app.permissions import PERMISSIONS, YUKSEK_YETKILI_IZINLER, permissions_of
from app.services import yetki
from app.services.teknik_servis import kapsam


def _rol(code: str, scope: str = "TUMU", izinler=None) -> Role:
    if izinler is None:
        izinler = permissions_of(code) if code in ("ADMIN", "DEPO", "SERVIS_SEF", "IK") else ()
    return Role(
        code=code,
        name=code,
        scope=scope,
        permissions=[RolePermission(permission_code=k) for k in izinler],
    )


def _kisi(rol: Role, birimler=(), istisna=()) -> User:
    return User(
        full_name="X",
        username="x",
        password_hash="-",
        role=rol,
        is_active=True,
        giris_acik=True,
        birimler=[UserUnit(birim=b, is_primary=i == 0) for i, b in enumerate(birimler)],
        izin_istisnalari=[UserPermission(permission_code=k, allow=a) for k, a in istisna],
    )


# --- Yetki yükseltme ---------------------------------------------------------


def test_admin_rolu_ust_yetkilidir_istisnayla_yuksek_izni_olan_da():
    assert yetki.ust_yetkili_mi(_kisi(_rol("ADMIN")))
    depocu = _kisi(_rol("DEPO"), istisna=[("sistem.denetim", True)])
    assert yetki.ust_yetkili_mi(depocu)
    assert not yetki.ust_yetkili_mi(_kisi(_rol("DEPO")))


def test_yuksek_yetkili_izin_admin_aktor_icin_bile_verilemez():
    admin = _kisi(_rol("ADMIN"))
    assert yetki.verilemeyen_izinler(admin, ["sistem.denetim", "cihaz.gor"]) == ["sistem.denetim"]
    # ADMIN hedefte zaten var: "verilebilir" sayılır.
    assert yetki.verilemeyen_izinler(admin, ["sistem.denetim"], hedef_admin=True) == []


def test_admin_olmayan_aktor_yalniz_kendi_izin_alt_kumesini_verir():
    aktor = _kisi(_rol("OZEL", izinler=("sistem.kullanici", "cihaz.gor")))
    assert yetki.verilemeyen_izinler(aktor, ["cihaz.gor"]) == []
    assert yetki.verilemeyen_izinler(aktor, ["cihaz.gor", "hakedis.gor"]) == ["hakedis.gor"]


def test_admin_rolunu_yalniz_admin_atar():
    admin_rol = _rol("ADMIN")
    assert yetki.rol_atanabilir_mi(_kisi(_rol("ADMIN")), admin_rol)
    ozel = _kisi(_rol("OZEL", izinler=tuple(PERMISSIONS)))  # ADMIN değil, tüm izinli
    assert not yetki.rol_atanabilir_mi(ozel, admin_rol)


def test_yuksek_izinli_ozel_rolu_admin_olmayan_atayamaz():
    aktor = _kisi(_rol("OZEL", izinler=("sistem.kullanici", "cihaz.gor")))
    assert not yetki.rol_atanabilir_mi(aktor, _rol("ESKI", izinler=("sistem.denetim",)))
    assert yetki.rol_atanabilir_mi(aktor, _rol("DAR", izinler=("cihaz.gor",)))
    assert not yetki.rol_atanabilir_mi(aktor, _rol("DEPO"))  # alt küme değil


def test_hedef_kontrol_ust_yetkiliye_yalniz_admin_dokunur():
    ik = _kisi(_rol("IK"))
    with pytest.raises(yetki.YetkiHatasi):
        yetki.hedef_kontrol(ik, _kisi(_rol("ADMIN")))
    yetki.hedef_kontrol(ik, _kisi(_rol("DEPO")))  # sıradan hedef serbest
    yetki.hedef_kontrol(_kisi(_rol("ADMIN")), _kisi(_rol("ADMIN")))


def test_yuksek_yetkili_kume_katalogda():
    assert YUKSEK_YETKILI_IZINLER <= set(PERMISSIONS)


# --- Birim kapsamı: tek kayıt ve katalog kuralları ----------------------------

_KAPSAMLAR = ("TUMU", "KENDI_MUSTERILERI", "KENDI_BIRIMI", "KENDI_ISLERI")


@pytest.mark.parametrize("scope", _KAPSAMLAR)
def test_birimsiz_kullanici_tumu_disinda_hicbir_birimi_goremez(scope):
    """Fail-closed (KD-04): birim üyeliği yoksa tek kayıt 404."""
    kisi = _kisi(_rol("R", scope=scope, izinler=()))
    beklenen = scope != "TUMU"
    assert kapsam.birim_disinda_mi(kisi, "GUVENLIK") is beklenen
    assert kapsam.birim_disinda_mi(kisi, None) is beklenen


@pytest.mark.parametrize("scope", ("KENDI_MUSTERILERI", "KENDI_BIRIMI", "KENDI_ISLERI"))
def test_birimli_kullanici_yalniz_kendi_birimini_ve_ortak_kaydi_gorur(scope):
    kisi = _kisi(_rol("R", scope=scope, izinler=()), birimler=("POC", "MOBILITE"))
    assert not kapsam.birim_disinda_mi(kisi, "POC")
    assert not kapsam.birim_disinda_mi(kisi, "MOBILITE")
    assert kapsam.birim_disinda_mi(kisi, "GUVENLIK")
    assert not kapsam.birim_disinda_mi(kisi, None)  # birimsiz ortak kayıt (ör. depo)
    assert kapsam.birim_disinda_mi(kisi, None, birimsiz_gorunur=False)


def test_bilinmeyen_kapsam_varsayilan_red():
    kisi = _kisi(_rol("R", scope="UYDURMA", izinler=()), birimler=("POC",))
    assert kapsam.birim_disinda_mi(kisi, "POC")
    assert kapsam.katalog_birim_yasak_mi(kisi, "POC")


def test_birim_degisimi_hedef_birim_de_kapsamda_olmali():
    sef = _kisi(_rol("R", scope="KENDI_BIRIMI", izinler=()), birimler=("POC",))
    assert not kapsam.birim_degisimi_yasak_mi(sef, "POC", "POC")
    assert kapsam.birim_degisimi_yasak_mi(sef, "POC", "GUVENLIK"), "kaydı dışarı taşıyamaz"
    assert kapsam.birim_degisimi_yasak_mi(sef, "GUVENLIK", "POC"), "başka birimin kaydını çekemez"
    assert kapsam.birim_degisimi_yasak_mi(sef, "POC", None), "kaydı birimsiz yapıp yayamaz"
    yonetici = _kisi(_rol("R", scope="TUMU", izinler=()))
    assert not kapsam.birim_degisimi_yasak_mi(yonetici, "POC", "GUVENLIK")


def test_katalog_ogesi_baska_birimin_ise_yasak():
    sef = _kisi(_rol("R", scope="KENDI_BIRIMI", izinler=()), birimler=("POC",))
    assert not kapsam.katalog_birim_yasak_mi(sef, "POC")
    assert kapsam.katalog_birim_yasak_mi(sef, "GUVENLIK")
    assert not kapsam.katalog_birim_yasak_mi(sef, None), "ortak katalog herkese açık"
    assert not kapsam.katalog_birim_yasak_mi(_kisi(_rol("R", izinler=())), "GUVENLIK")


def test_kullanici_birimleri():
    kisi = _kisi(_rol("R", izinler=()), birimler=("POC", "MOBILITE"))
    assert kapsam.kullanici_birimleri(kisi) == frozenset({"POC", "MOBILITE"})
