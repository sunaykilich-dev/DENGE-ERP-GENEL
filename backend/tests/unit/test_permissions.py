"""İzin kataloğunun kendi içinde tutarlılığı — DB gerektirmez."""

from app.permissions import (
    ATANABILIR_SAHA_ROLLERI,
    AYRILIS_NEDENLERI,
    BIRIM_KAPSAMLARI,
    BIRIMLER,
    PERMISSIONS,
    ROLES,
    SAHA_ROLLERI,
    SCOPE_ALL,
    SCOPE_OWN_JOBS,
    SCOPE_OWN_UNITS,
    SCOPES,
    SERVIS_ROLLERI,
    VEKALETE_KAPALI,
    YUKSEK_YETKILI_IZINLER,
    permissions_of,
)


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


# --------------------------------------------------------------------------
# Teknik servis (TS-001, plan §1.2–1.4)
# --------------------------------------------------------------------------

_MOBILITE_ROLLERI = (
    "ADMIN",
    "SATIS",
    "SATIS_MUDURU",
    "DEPO",
    "TEKNIK_SERVIS",
    "MONTAJ_KOORD",
    "HAT_SORUMLUSU",
    "MUHASEBE_DESTEK",
    "YONETIM",
)


def test_mevcut_roller_aynen_kalir_ve_servis_rolleri_eklenir():
    assert set(ROLES) == set(_MOBILITE_ROLLERI) | set(SERVIS_ROLLERI)
    assert len(SERVIS_ROLLERI) == 8


def test_teknik_servis_mobilite_rolu_anlik_goruntuyle_ayni():
    """`TEKNIK_SERVIS` mobilite montaj/onay rolüdür (isemri.onayla → hak ediş);
    teknik servis izinleri ona İNMEZ, yeniden anlamlandırılmaz."""
    assert set(permissions_of("TEKNIK_SERVIS")) == {
        "gorev.gor",
        "gorev.yaz",
        "hesap.gor",
        "urun.gor",
        "cihaz.gor",
        "cihaz.yaz",
        "hat.gor",
        "hat.yaz",
        "arac.gor",
        "arac.yaz",
        "isemri.gor",
        "isemri.yaz",
        "isemri.onayla",
        "rma.gor",
        "rma.yaz",
        "rapor.gor",
    }
    assert ROLES["TEKNIK_SERVIS"][2] == "TUMU"


def test_servis_rollerinde_mobilite_finans_ve_yazma_izni_yok():
    """KD-06/07/11: servis personeli hak edişe, tahsilata, mobilite iş emrine,
    mobilite rapor Excel'ine ve maliyete erişmez; IBAN/VKN düzenlemez."""
    for rol in SERVIS_ROLLERI:
        izinler = set(permissions_of(rol))
        yasak = {
            p
            for p in izinler
            if p.split(".")[0] in {"isemri", "hakedis", "tahsilat", "maliyet"}
            or p in {"rapor.gor", "rapor.disaaktar", "hesap.yaz"}
        }
        assert yasak == set(), f"{rol}: {sorted(yasak)}"


def test_servis_teknisyeni_kendi_isleriyle_sinirli_ve_hesap_goremez():
    _, perms, scope = ROLES["SERVIS_TEKNISYEN"]
    assert scope == SCOPE_OWN_JOBS
    assert "hesap.gor" not in perms


def test_servis_rollerinin_kapsamlari():
    beklenen = {
        "SERVIS_YONETICI": SCOPE_ALL,
        "SERVIS_SEF": SCOPE_OWN_UNITS,
        "SERVIS_OPERASYON": SCOPE_OWN_UNITS,
        "SERVIS_TEKNISYEN": SCOPE_OWN_JOBS,
        "ATOLYE": SCOPE_OWN_UNITS,
        "SERVIS_DEPO": SCOPE_OWN_UNITS,
        "KIRALAMA_DEPO": SCOPE_OWN_UNITS,
        "IK": SCOPE_ALL,
    }
    assert {r: ROLES[r][2] for r in SERVIS_ROLLERI} == beklenen


def test_kapsam_sabitleri():
    assert SCOPES == ("TUMU", "KENDI_MUSTERILERI", "KENDI_BIRIMI", "KENDI_ISLERI")
    assert set(BIRIM_KAPSAMLARI) == {"KENDI_BIRIMI", "KENDI_ISLERI"}
    assert set(BIRIM_KAPSAMLARI) <= set(SCOPES)


def test_yonetim_bilincli_olarak_kisisel_ayrinti_izinlerini_almaz():
    """KVKK en az erişim: adları `.gor` ile bitmediği için otomatik kümeye
    girmezler; biri yanlışlıkla `.gor` yaparsa bu test kırılır."""
    yonetim = set(permissions_of("YONETIM"))
    assert {"servis.irtibat_gor", "egitim.detay", "servis_rapor.personel"} & yonetim == set()
    # `.gor` ile bitenleri kendiliğinden alır (personel listesi dahil).
    assert {"servis.gor", "personel.gor", "egitim.gor", "servis_rapor.gor"} <= yonetim


def test_yonetim_yalniz_okuma_izni_tasir():
    """Yeni eylem adları (`.planla`, `.kapat`, `.kullan` ...) ad sonekiyle
    yakalanamaz; YONETIM izinleri okuma kümesiyle sınırlı olmalı."""
    yonetim = set(permissions_of("YONETIM"))
    fazla = {p for p in yonetim if not p.endswith(".gor")} - {"rapor.disaaktar"}
    assert fazla == set()


def test_maliyet_yazma_yalniz_admin():
    """KD-11: ihtiyaç sahibine kişi bazlı gerekçeli istisna verilir."""
    assert {r for r in ROLES if "maliyet.yaz" in permissions_of(r)} == {"ADMIN"}


def test_yuksek_yetkili_izinler_yalniz_admin_rolunde():
    """E13-01 (1): kullanıcı yönetimi, denetim, ayar, göç, KVKK yalnız ADMIN."""
    assert YUKSEK_YETKILI_IZINLER <= set(PERMISSIONS)
    for rol in ROLES:
        if rol == "ADMIN":
            continue
        assert YUKSEK_YETKILI_IZINLER & set(permissions_of(rol)) == set(), rol


def test_vekalete_kapali_liste_katalogda():
    """`vekalet.ver` kataloğa Dalga 4'te (TS-213) girer; diğerleri şimdiden var."""
    assert YUKSEK_YETKILI_IZINLER <= VEKALETE_KAPALI
    assert VEKALETE_KAPALI - {"vekalet.ver"} <= set(PERMISSIONS)


def test_birim_ve_personel_sozlukleri_modellerle_ayni():
    """Ad sözlüğü burada, CHECK kısıtlarının kaynağı modellerde; ayrışırsa
    arayüzden seçilen birim veritabanında CHECK ihlaline düşer."""
    from app.models import user as user_model
    from app.models.rbac import BIRIM_KODLARI

    assert tuple(BIRIMLER) == BIRIM_KODLARI
    assert SAHA_ROLLERI == user_model.SAHA_ROLLERI
    assert AYRILIS_NEDENLERI == user_model.AYRILIS_NEDENLERI
    assert set(ATANABILIR_SAHA_ROLLERI) <= set(SAHA_ROLLERI)


def test_rol_onizleme_sayfalari_katalogdaki_izinlere_bagli():
    """`_SAYFA_IZINLERI` menüyle aynı listeyi taşır (plan §1.10); tanımsız
    izne bağlı sayfa rol önizlemesinde hiç görünmezdi."""
    from app.api.users import _KAPSAM_ACIKLAMA, _SAYFA_IZINLERI

    for ad, izin in _SAYFA_IZINLERI:
        kodlar = izin if isinstance(izin, tuple) else (izin,)
        assert set(kodlar) <= set(PERMISSIONS), ad
    adlar = {ad for ad, _ in _SAYFA_IZINLERI}
    assert {"Servis Paneli", "Servis İşleri", "Benim İşlerim", "Personel"} <= adlar
    assert set(_KAPSAM_ACIKLAMA) == set(SCOPES)
