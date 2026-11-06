"""İzin kataloğunun kendi içinde tutarlılığı — DB gerektirmez."""

from app.permissions import PERMISSIONS, ROLES, SCOPES, permissions_of


def test_roller_yalnizca_tanimli_izinlere_referans_verir():
    for role_code, (_, perms, _) in ROLES.items():
        for code in perms:
            assert code in PERMISSIONS, f"{role_code} tanımsız izne referans veriyor: {code}"


def test_her_rolun_kapsami_gecerli():
    for role_code, (_, _, scope) in ROLES.items():
        assert scope in SCOPES, f"{role_code} geçersiz kapsam: {scope}"


def test_admin_tum_izinlere_sahip():
    assert set(permissions_of("ADMIN")) == set(PERMISSIONS)


def test_maliyet_gorunurlugu_varsayilan_kapali():
    """Brief §3: maliyet yalnız yetkili rollerde. 'Varsayılan açık, bazılarında
    gizle' tasarımı güvenlik açısından yanlış olurdu — bu testi kıran bir
    değişiklik o yanlışa dönüş demektir."""
    gorenler = {r for r in ROLES if "maliyet.gor" in permissions_of(r)}
    assert gorenler == {"ADMIN", "SATIS_MUDURU", "MUHASEBE_DESTEK", "YONETIM"}


def test_satis_temsilcisi_kendi_musterileriyle_sinirli():
    _, perms, scope = ROLES["SATIS"]
    assert scope == "KENDI_MUSTERILERI"
    assert "maliyet.gor" not in perms


def test_yonetim_salt_okunur():
    """Yönetim rolü hiçbir yazma iznine sahip olmamalı."""
    yazanlar = [
        p for p in permissions_of("YONETIM") if p.endswith((".yaz", ".onayla", ".ode", ".transfer"))
    ]
    assert yazanlar == []


def test_her_izin_bir_role_atanmis():
    """Hiçbir role verilmemiş izin = ya unutulmuş ya ölü tanım."""
    atanmis = {c for r in ROLES for c in permissions_of(r)}
    assert set(PERMISSIONS) - atanmis == set()
