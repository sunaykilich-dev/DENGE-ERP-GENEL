"""SPA yedek yolu, static dizinin dışına çıkamaz.

Gerçek bir açıktan doğdu: `GET /..%2f..%2f..%2fetc%2fpasswd` dosyayı
döndürüyordu. Yönlendirici `..%2f` dizilerini yol ayracı saymadığı için
normalleştirmiyor, `pathlib` ise sonradan çözüyordu.

Sonuç **kimlik doğrulaması gerektirmeyen keyfi dosya okuma**ydı: sistem
dosyaları, uygulama kaynak kodu ve — en ağırı — `var/files` altındaki
müşteri belgeleri (vergi levhaları, montaj fotoğrafları, sözleşmeler).
Ek indirme ucundaki yetki kontrolü tamamen atlanıyordu.
"""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# Her biri farklı bir kaçış denemesi; hiçbiri static dizinin dışını görmemeli.
KACIS_DENEMELERI = [
    "..%2f..%2f..%2fetc%2fpasswd",
    "..%2f..%2fapp%2fconfig.py",
    "..%2f..%2fvar%2ffiles%2ffoo.pdf",
    "..%2F..%2F..%2Fetc%2Fpasswd",  # büyük harf kodlama
    "..%252f..%252fetc%252fpasswd",  # çift kodlama
    "....%2f....%2fetc%2fpasswd",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "../../../etc/passwd",
]


@pytest.fixture
def static_istemci(tmp_path, monkeypatch):
    """Static dizini olan bir uygulama — SPA yedek yolu yalnız o zaman açılır."""
    import app.main as ana

    kok = tmp_path / "static"
    (kok / "assets").mkdir(parents=True)
    (kok / "index.html").write_text("<!doctype html><title>SPA</title>")
    (kok / "assets" / "app.js").write_text("console.log(1)")
    # Dışarıda kalması gereken, okunabilir bir dosya.
    (tmp_path / "gizli.txt").write_text("BU DOSYA ASLA SERVIS EDILMEMELI")

    monkeypatch.setattr(ana, "STATIC_DIR", kok)
    ana.get_config.cache_clear()
    with TestClient(ana.create_app()) as istemci:
        yield istemci


@pytest.mark.parametrize("yol", KACIS_DENEMELERI)
def test_dizin_disina_cikilamaz(static_istemci, yol):
    cevap = static_istemci.get(f"/{yol}", follow_redirects=False)
    # SPA olduğu için 404 değil index.html dönmesi normaldir; ÖNEMLİ olan
    # dışarıdaki dosyanın İÇERİĞİNİN dönmemesi.
    assert "root:x:0:0" not in cevap.text, f"/etc/passwd sızdı: {yol}"
    assert "BU DOSYA ASLA SERVIS EDILMEMELI" not in cevap.text, f"dışarı sızdı: {yol}"
    assert "pydantic_settings" not in cevap.text, f"kaynak kod sızdı: {yol}"


def test_gizli_dosya_ust_dizinden_okunamaz(static_istemci):
    cevap = static_istemci.get("/..%2fgizli.txt")
    assert "ASLA SERVIS EDILMEMELI" not in cevap.text


def test_mesru_varliklar_calisiyor(static_istemci):
    """Kısıt gerçek dosyaları engellememeli; yoksa arayüz açılmaz."""
    assert "console.log(1)" in static_istemci.get("/assets/app.js").text
    assert "<title>SPA</title>" in static_istemci.get("/index.html").text
    # Bilinmeyen yol SPA'ya düşer (istemci tarafı yönlendirme).
    assert "<title>SPA</title>" in static_istemci.get("/hesaplar/123").text
