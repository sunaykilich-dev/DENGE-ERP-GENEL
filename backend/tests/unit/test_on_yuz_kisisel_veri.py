"""Ön yüz paketinde kişi adı yok (TS-216, E02-18).

**Neden:** eski sistemde teknisyen listesi ön yüz koduna gömülüydü; oturum
açmadan indirilebilen statik JS dosyasında personelin adı soyadı
yayımlanıyordu (M02-14). Yeni ön yüzde kişi listesi yalnız API'den gelir
(`/api/personel/atanabilir`). Bu test, birinin "geçici" bir ad listesini ya
da deneme kullanıcısının adını koda gömmesini yakalar: `frontend/src`
altındaki her `.ts/.tsx` dosyasının metin sabitleri taranır.

İki ölçüt:
1. `seeds/dev.py`'nin ürettiği deneme kullanıcı adları (`Deneme <rol adı>`)
   koda girmemiş olmalı.
2. Türkçe ad + soyad kalıbı (yaygın ilk adla başlayan, iki ya da üç büyük
   harfli sözcük) metin sabiti olarak geçmemeli. Yer tutucu/örnek metin
   gerekiyorsa `IZINLI` kümesine gerekçesiyle eklenir.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.permissions import ROLES

ON_YUZ = Path(__file__).resolve().parents[3] / "frontend" / "src"

# Yaygın Türkçe ilk adlar (kadın/erkek). Liste kalıbın "ad" yarısıdır; soyad
# herhangi bir büyük harfli sözcük olabilir. Amaç sözlük değil, gömülü bir
# personel/müşteri listesini yakalamak.
ILK_ADLAR = frozenset(
    """
    Ahmet Mehmet Mustafa Ali Hasan Hüseyin İbrahim İsmail Murat Ömer Osman Yusuf
    Emre Burak Serkan Volkan Kemal Kadir Halil Recep Ramazan Erkan Erdem
    Fatih Cem Can Onur Okan Orhan Selim Sinan Tolga Tuncay Uğur Yasin Yunus Zafer
    Abdullah Bayram Cengiz Engin Gökhan Hakan Levent Mert Metin Oğuz Özgür Serdar
    Ayşe Fatma Emine Hatice Zeynep Elif Merve Esra Özlem Derya Ebru Gül Sevgi
    Hülya Aylin Büşra Gamze Seda Tuğba Yasemin Zehra Kübra Melek Şerife Nur Dilek
    """.split()
)
_SOZCUK = r"[A-ZÇĞİÖŞÜ][a-zçğıöşü]+"
_AD_SOYAD = re.compile(rf"\b({_SOZCUK})\s+({_SOZCUK})(?:\s+{_SOZCUK})?\b")
_METIN_SABITI = re.compile(r"""(["'`])((?:\\.|(?!\1).){3,200})\1""")

# Bilerek koda yazılmış, kişi olmayan ifadeler (gerekçesiyle).
IZINLI: frozenset[str] = frozenset()


def deneme_adlari() -> set[str]:
    return {f"Deneme {ad}" for ad, _izinler, _kapsam in ROLES.values()}


def kisi_adlari(metin: str) -> list[str]:
    """Metin sabitlerindeki ad-soyad adayları."""
    bulunan: list[str] = []
    for sabit in _METIN_SABITI.finditer(metin):
        for m in _AD_SOYAD.finditer(sabit.group(2)):
            if m.group(1) in ILK_ADLAR and m.group(0) not in IZINLI:
                bulunan.append(m.group(0))
    return bulunan


def _dosyalar() -> list[Path]:
    return sorted(p for p in ON_YUZ.rglob("*") if p.suffix in (".ts", ".tsx"))


@pytest.mark.skipif(not ON_YUZ.is_dir(), reason="frontend/src yok (yalnız backend kopyası)")
def test_on_yuzde_deneme_kullanici_adi_yok() -> None:
    adlar = deneme_adlari()
    hatalar = [
        f"{p.relative_to(ON_YUZ)}: {ad}"
        for p in _dosyalar()
        for ad in adlar
        if ad in p.read_text(encoding="utf-8")
    ]
    assert not hatalar, "Deneme kullanıcı adı ön yüz koduna gömülmüş:\n" + "\n".join(hatalar)


@pytest.mark.skipif(not ON_YUZ.is_dir(), reason="frontend/src yok (yalnız backend kopyası)")
def test_on_yuzde_kisi_adi_listesi_yok() -> None:
    dosyalar = _dosyalar()
    assert len(dosyalar) > 20, "ön yüz dosyası bulunamadı; tarama boşa geçerdi"
    hatalar = [
        f"{p.relative_to(ON_YUZ)}: {ad}"
        for p in dosyalar
        for ad in kisi_adlari(p.read_text(encoding="utf-8"))
    ]
    assert not hatalar, (
        "Ön yüz kodunda kişi adı (personel/müşteri listesi API'den gelmeli):\n" + "\n".join(hatalar)
    )


def test_tarayici_kendini_kanitlar() -> None:
    """Gömülü liste yakalanır; arayüz metni ve rol adı yakalanmaz."""
    gomulu = 'const ekip = ["Ahmet Yılmaz", "Ayşe Kara Demir", "Servis Teknisyeni"];'
    assert kisi_adlari(gomulu) == ["Ahmet Yılmaz", "Ayşe Kara Demir"]
    assert kisi_adlari('<Button>Kaydet</Button> title="Servis Planlama"') == []
    assert "Deneme Servis Teknisyeni" in deneme_adlari()
