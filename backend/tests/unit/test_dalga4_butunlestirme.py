"""Dalga 4 son bütünleştirme: devreden açıkların kapanış sözleşmeleri.

- `kancalar.atama_uyarilari` imzası `clock` taşır ve kayıtlı fonksiyona geçirir
  (saat verilmezse geçirmez: geri uyumlu).
- Rapor Excel satır sınırı ve erişim gözden geçirme eşiği ayardan okunur.
- Zorunlu parola değişimi ekranı uygulama kapısına bağlıdır (TS-212).
- `canliya-hazirla` yönetici parolasını geçici sayar (ilk girişte değişim).
"""

from pathlib import Path

from app.clock import FakeClock
from app.services import settings as ayar
from app.services.teknik_servis import kancalar
from app.services.teknik_servis import rapor_tanimlari as rt

KOK = Path(__file__).resolve().parents[3]


async def test_atama_uyarilari_clock_kayitli_fonksiyona_gecer() -> None:
    gorulen: list[object] = []

    async def kanca(_db, _so, _kimlikler, *, clock=None):
        gorulen.append(clock)
        return []

    saat = FakeClock()
    kancalar.kaydet("atama_uyarilari", kanca)
    try:
        await kancalar.atama_uyarilari(None, None, [1], saat)
        await kancalar.atama_uyarilari(None, None, [1])
    finally:
        kancalar._KAYIT["atama_uyarilari"].remove(kanca)
    assert gorulen == [saat, None]


def test_rapor_ve_erisim_ayarlari_tanimli() -> None:
    assert ayar.DEFAULTS["servis_rapor_excel_azami_satir"] == rt.EXCEL_AZAMI_SATIR
    assert ayar.DEFAULTS["erisim_girissiz_gun"] == 60
    ayar.ayar_dogrula("servis_rapor_excel_azami_satir", 10_000)
    ayar.ayar_dogrula("erisim_girissiz_gun", 90)


async def test_excel_azami_satir_okunamazsa_varsayilan(monkeypatch) -> None:
    async def patla(_db, _anahtar):
        raise KeyError(_anahtar)

    monkeypatch.setattr(ayar, "get", patla)
    assert await rt.excel_azami_satir(None) == rt.EXCEL_AZAMI_SATIR

    async def deger(_db, _anahtar):
        return 1234

    monkeypatch.setattr(ayar, "get", deger)
    assert await rt.excel_azami_satir(None) == 1234


def test_parola_degistir_ekrani_uygulama_kapisinda() -> None:
    main = (KOK / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert 'import ParolaDegistirPage from "./pages/ParolaDegistirPage";' in main
    assert "if (kullanici.parola_degismeli) return <ParolaDegistirPage />;" in main
    # MFA kapısından SONRA: MFA kurulum uçları parola kapısından muaf.
    assert main.index("mfa_kurulumu_gerekli") < main.index("parola_degismeli")


def test_canliya_hazirla_yonetici_parolasi_gecici() -> None:
    kaynak = (KOK / "backend" / "app" / "yonetim.py").read_text(encoding="utf-8")
    assert "admin.parola_degismeli = True" in kaynak


def test_env_ornegi_forwarded_allow_ips() -> None:
    ornek = (KOK / ".env.example").read_text(encoding="utf-8")
    assert "FORWARDED_ALLOW_IPS=" in ornek
