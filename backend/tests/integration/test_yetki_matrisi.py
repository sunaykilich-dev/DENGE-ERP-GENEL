"""Otomatik yetki matrisi: her rol × her korumalı uç (TS-013, E13-14).

**Neden elle değil:** canlıda her yeni uç için "yetkisiz 403, yetkili 200"
testi elle yazılıyordu; teknik servis yüzü aşkın uç getiriyor ve tek bir
unutulan `require_permission` bütün müşteri arşivini açar. Matris uç listesini
`app.routes`'tan, izinleri kapının kendisinden (`_guard.izinler`), rolleri
`permissions.ROLES`'tan okur: yeni uç ya da yeni rol eklendiğinde test
kendiliğinden genişler.

Beklenen:
- rolde izin YOK → tam olarak 403 (gövde/parametre hatası değil: izin
  kontrolü doğrulamadan ÖNCE koşar, aksi halde 422 yanıtı ucun varlığını ve
  şemasını yetkisiz kişiye anlatır);
- rolde izin VAR → kapının kendi 403'ü DEĞİL (kimliği olmayan kayıt 404,
  eksik gövde 422 olabilir; gövdedeki ikinci, daha dar izin kontrolü 403
  verebilir — matrisin konusu yalnız yetki kapısı);
- hiçbir çağrı 5xx değil (yer tutucu girdi uygulamayı düşürmemeli).
Ayrıca teknik servis önekli her uç bir izin kapısıyla korunmalıdır.
"""

import os
import re

import httpx
import pytest
from sqlalchemy import select
from yetki_tarama import YOK_KIMLIK, cagir, ts_ucu_mu, uclar, yol_doldur

from app.models import Role, User
from app.permissions import ROLES

pytestmark = [pytest.mark.integration, pytest.mark.yetki_matrisi]


async def _rol_istemcileri(db) -> dict[str, tuple[set[str], httpx.AsyncClient]]:
    """Her rol için oturum açmış ayrı istemci (çerezler karışmasın).

    Parola özeti BİR kez hesaplanır: argon2 bilerek yavaştır ve rol başına
    ayrı özet matrisi dakikalarca uzatırdı.
    """
    from app.main import app
    from app.services import auth as auth_service

    ozet = auth_service.hash_password("parola1234")
    roller = {r.code: r for r in (await db.scalars(select(Role))).all()}
    istemciler: dict[str, tuple[set[str], httpx.AsyncClient]] = {}
    for kod in ROLES:
        kullanici = User(
            full_name=f"Matris {kod}",
            username=f"matris_{kod.lower()}",
            password_hash=ozet,
            role_id=roller[kod].id,
        )
        db.add(kullanici)
        await db.commit()
        await db.refresh(kullanici)
        izinler = set(kullanici.etkin_izinler())
        ist = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"X-Requested-With": "fetch"},
        )
        r = await ist.post(
            "/api/auth/login", json={"username": kullanici.username, "password": "parola1234"}
        )
        assert r.status_code == 200, (kod, r.text)
        istemciler[kod] = (izinler, ist)
    return istemciler


async def test_teknik_servis_uclari_izin_kapisiyla_korunur() -> None:
    from app.main import app

    korumasiz = [u.ad for u in uclar(app) if ts_ucu_mu(u.yol) and not u.korumali]
    assert not korumasiz, "require_permission'sız teknik servis ucu:\n" + "\n".join(korumasiz)


async def test_rol_kodlari_seed_ile_ayni(seeded) -> None:
    """Matris `ROLES`'tan üretilir; DB'deki roller aynı küme olmalı."""
    kodlar = set((await seeded.scalars(select(Role.code))).all())
    assert set(ROLES) <= kodlar


_KAPI_MESAJI = re.compile(r"^Bu işlem için yetkiniz yok \((.+)\)$")


def _kapi_reddi_mi(r, uc) -> bool:
    """403 yanıtı ucun KENDİ kapısından mı geldi?

    Bazı uçlar kapıdan sonra gövdede ikinci, daha dar bir izin ister (canlı
    kalıp `_izin(user, kod)`; ör. montaj noktası raporu `hakedis.gor` +
    `maliyet.gor`, saha önerisi `hesap.gor`/`lokasyon.yaz`). O 403 bilinçli
    katmanlı yetkidir; matrisin yakaladığı hata yalnız kapının, rolde VAR olan
    izinlerle reddetmesidir.
    """
    try:
        detay = r.json().get("detail")
    except ValueError:
        return False
    eslesme = _KAPI_MESAJI.match(detay) if isinstance(detay, str) else None
    if eslesme is None:
        return False
    kodlar = set(re.split(r", | veya ", eslesme.group(1)))
    return kodlar <= set(uc.izinler) | set(uc.herhangi)


def _ornekler(uc, istemciler: dict, sira: int) -> list[tuple[str, bool]]:
    """Bu uçta HTTP ile sınanacak (rol, izinli_mi) çiftleri.

    Beklenti BÜTÜN rol × uç çiftleri için hesaplanır (bellek içi, ucuz); HTTP
    ile her uçta izinli rollerden biri ve izinsiz rollerden ikisi sınanır,
    seçim uçtan uca kayar ki her rol yüzlerce uçta sınansın. Tam matris
    (her çift HTTP ile, ~4 dk) `TAM_MATRIS=1` ile koşar.
    """
    izinli = [k for k, (iz, _) in istemciler.items() if uc.izinli_mi(iz)]
    izinsiz = [k for k in istemciler if k not in izinli]
    if os.getenv("TAM_MATRIS") == "1":
        return [(k, True) for k in izinli] + [(k, False) for k in izinsiz]
    secim: list[tuple[str, bool]] = []
    if izinli:
        secim.append((izinli[sira % len(izinli)], True))
    for adim in range(min(2, len(izinsiz))):
        secim.append((izinsiz[(sira + adim) % len(izinsiz)], False))
    return secim


async def test_rol_x_uc_matrisi(client, db) -> None:
    from app.main import app

    hedefler = [u for u in uclar(app) if u.korumali]
    assert hedefler, "korumalı uç bulunamadı — kapı özniteliği okunamıyor"
    istemciler = await _rol_istemcileri(db)
    hatalar: list[str] = []
    sinanan_roller: set[str] = set()
    try:
        for sira, uc in enumerate(hedefler):
            yol = yol_doldur(uc.yol)
            for rol, beklenen_izinli in _ornekler(uc, istemciler, sira):
                sinanan_roller.add(rol)
                r = await cagir(istemciler[rol][1], uc, yol)
                if beklenen_izinli and r.status_code == 403 and _kapi_reddi_mi(r, uc):
                    hatalar.append(f"{rol}: {uc.ad} izinli ama 403 → {r.text[:120]}")
                elif not beklenen_izinli and r.status_code != 403:
                    hatalar.append(f"{rol}: {uc.ad} izinsiz ama {r.status_code}")
                if r.status_code >= 500:
                    hatalar.append(f"{rol}: {uc.ad} sunucu hatası {r.status_code}")
    finally:
        for _, ist in istemciler.values():
            await ist.aclose()
    assert not hatalar, f"{len(hatalar)} matris ihlali:\n" + "\n".join(hatalar[:60])
    assert sinanan_roller == set(istemciler), "bazı roller hiç sınanmadı"


async def test_matris_kendini_dogrular() -> None:
    """Kapı okuyucusu gerçekten izin buluyor mu: bilinen bir uç örneği."""
    from app.main import app

    ayarlar = {u.ad: u for u in uclar(app)}
    assert ayarlar["GET /api/ayarlar"].izinler == ("sistem.ayar",)
    assert "GET /api/arama" in ayarlar and ayarlar["GET /api/arama"].herhangi
    assert yol_doldur("/api/x/{id}/y/{kod}") == f"/api/x/{YOK_KIMLIK}/y/{YOK_KIMLIK}"
