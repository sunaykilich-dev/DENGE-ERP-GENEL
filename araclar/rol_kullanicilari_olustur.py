"""Yerel deneme veritabanında her rol için bir test kullanıcısı açar (yalnız geliştirme).

Çalışan API üzerinden (http://127.0.0.1:8000) yönetici hesabıyla gider; kullanıcı
açma, geçici parola ve ilk girişte parola değişimi gerçek akıştan geçer.
Parolalar yalnız .yerel_gizli/rol_test_kullanicilari.txt dosyasına yazılır.

Kullanım (denge-erp-deneme/backend içinde):  uv run python ..\\..\\araclar\\rol_kullanicilari_olustur.py
Tekrar çalıştırılabilir: dosyada parolası olan kullanıcı atlanır.
"""

import secrets
import sys
from pathlib import Path

import httpx

KOK = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000/api"
DOSYA = KOK / ".yerel_gizli" / "rol_test_kullanicilari.txt"

TEL, ELK, MOB = "TELEKOM", "ELEKTRONIK", "MOBILITE"

# (kullanıcı adı, ad soyad, rol, birimler, şirketler) — adlar kurgusal (kişisel veri yok).
KULLANICILAR = [
    ("t_yonetim", "Test Üst Yönetim", "YONETIM", [], [TEL, ELK, MOB]),
    ("t_yon_guv", "Test TS Yöneticisi Güvenlik", "SERVIS_YONETICI", ["GUVENLIK"], [ELK]),
    ("t_yon_hab", "Test TS Yöneticisi Haberleşme", "SERVIS_YONETICI", ["HABERLESME"], [TEL]),
    ("t_sef_guv", "Test Şef Güvenlik", "SERVIS_SEF", ["GUVENLIK"], [ELK]),
    ("t_sef_hab", "Test Şef Haberleşme", "SERVIS_SEF", ["HABERLESME"], [TEL]),
    ("t_sef_bar", "Test Şef Set Bariyer", "SERVIS_SEF", ["BARIYER"], [ELK]),
    ("t_tek_guv1", "Test Teknisyen Güvenlik 1", "SERVIS_TEKNISYEN", ["GUVENLIK"], [ELK]),
    ("t_tek_guv2", "Test Teknisyen Güvenlik 2", "SERVIS_TEKNISYEN", ["GUVENLIK"], [ELK]),
    ("t_tek_hab", "Test Teknisyen Haberleşme", "SERVIS_TEKNISYEN", ["HABERLESME"], [TEL]),
    ("t_saha_guv", "Test Saha Sorumlusu Güvenlik", "SAHA_SORUMLUSU", ["GUVENLIK"], [ELK]),
    ("t_ops_guv", "Test Operasyon Güvenlik", "SERVIS_OPERASYON", ["GUVENLIK"], [ELK]),
    ("t_ops_hab", "Test Operasyon Haberleşme", "SERVIS_OPERASYON", ["HABERLESME"], [TEL]),
    ("t_atolye_guv", "Test Atölye Güvenlik", "ATOLYE", ["GUVENLIK"], [ELK]),
    ("t_satis_guv", "Test Satış Güvenlik", "SATIS", ["GUVENLIK"], [ELK]),
    ("t_sdestek_guv", "Test Satış Destek Güvenlik", "SATIS_DESTEK", ["GUVENLIK"], [ELK]),
    ("t_sdestek_hab", "Test Satış Destek Haberleşme", "SATIS_DESTEK", ["HABERLESME"], [TEL]),
    ("t_finans_yon", "Test Finans Yöneticisi", "FINANS_YONETICI", [], [TEL, ELK, MOB]),
    ("t_finans_uzm", "Test Finans Uzmanı", "MUHASEBE_DESTEK", [], [ELK]),
    ("t_depo_guv", "Test Depo Güvenlik", "SERVIS_DEPO", ["GUVENLIK"], [ELK]),
    ("t_mob_depo", "Test Mobilite Depo", "DEPO", [], [MOB]),
]


def admin_parolasi() -> str:
    for satir in (KOK / ".yerel_gizli" / "deneme_admin.txt").read_text(encoding="utf-8").splitlines():
        if satir.startswith("sifre="):
            return satir.split("=", 1)[1].strip()
    raise SystemExit("deneme_admin.txt içinde parola yok")


def kayitli() -> dict[str, str]:
    if not DOSYA.exists():
        return {}
    sonuc = {}
    for satir in DOSYA.read_text(encoding="utf-8").splitlines():
        if satir.startswith("#") or "\t" not in satir:
            continue
        ad, _rol, parola = satir.split("\t")[:3]
        sonuc[ad] = parola
    return sonuc


def yeni_parola() -> str:
    return "Dn-" + secrets.token_urlsafe(12) + "7a"


def main() -> None:
    a = httpx.Client(headers={"X-Requested-With": "fetch"}, timeout=60)
    r = a.post(f"{API}/auth/login", json={"username": "admin", "password": admin_parolasi()})
    if r.status_code >= 400:
        sys.exit(f"Yönetici girişi başarısız: {r.status_code}")
    mevcut = kayitli()
    satirlar = [
        "# Rol test kullanıcıları — YALNIZ yerel deneme veritabanı. Paylaşma.",
        "# kullanici\trol\tparola\tbirimler\tsirketler",
    ]
    for ad, tam_ad, rol, birimler, sirketler in KULLANICILAR:
        if ad in mevcut:
            satirlar.append("\t".join([ad, rol, mevcut[ad], ",".join(birimler), ",".join(sirketler)]))
            print("var:", ad)
            continue
        gecici = yeni_parola()
        r = a.post(
            f"{API}/kullanicilar",
            json={
                "full_name": tam_ad,
                "username": ad,
                "email": f"{ad}@deneme.local",
                "role_code": rol,
                "password": gecici,
                "birimler": birimler,
                "birincil_birim": birimler[0] if birimler else None,
                "sirketler": sirketler,
            },
        )
        if r.status_code >= 400:
            print(f"HATA {ad}: {r.status_code} {r.text[:300]}")
            continue
        k = httpx.Client(headers={"X-Requested-With": "fetch"}, timeout=60)
        r = k.post(f"{API}/auth/login", json={"username": ad, "password": gecici})
        kalici = yeni_parola()
        r2 = k.post(f"{API}/auth/parola", json={"mevcut": gecici, "yeni": kalici})
        if r.status_code >= 400 or r2.status_code >= 400:
            print(f"HATA parola {ad}: {r.status_code}/{r2.status_code} {r2.text[:200]}")
            continue
        satirlar.append("\t".join([ad, rol, kalici, ",".join(birimler), ",".join(sirketler)]))
        print("açıldı:", ad, rol)
    DOSYA.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    print("Parolalar:", DOSYA)


if __name__ == "__main__":
    main()
