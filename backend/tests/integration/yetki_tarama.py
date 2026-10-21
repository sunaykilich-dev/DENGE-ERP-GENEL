"""Uç taraması yardımcıları — yetki matrisi ve kapsam taraması ortak kullanır (TS-013).

Testler uçları ELLE listelemez: liste `app.routes`'tan üretilir, böylece yeni
bir uç eklendiğinde matris onu kendiliğinden kapsar. Bir ucun hangi izni
istediği `require_permission` / `require_any_permission` kapısının
`izinler` / `izinler_herhangi` özniteliğinden okunur (`api/deps.py`).

Örnek gövde: uç gövdesinin Pydantic modelinde `json_schema_extra={"examples":
[...]}` varsa ilk örnek kullanılır; yoksa zorunlu alanlar şemadan türetilen
yer tutucularla doldurulur. Kapsam taraması 422 görürse ucun modeline örnek
eklenmesi istenir (tarama "doğrulanamadı"yı geçti saymaz).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fastapi.routing import APIRoute

# Yolu bu öneklerle başlayan uçlar "teknik servis ucu" sayılır.
TS_ONEKLERI = (
    "/api/teknik-servis",
    "/api/personel",
    "/api/lokasyonlar",
    "/api/hesaplar/{hesap_id}/lokasyonlar",
    "/api/kiralama",
    "/api/egitim",
    "/api/vekalet",
    "/api/erisim-gozden",
)

YOK_KIMLIK = 987_654_321  # hiçbir testte üretilmeyecek kadar büyük


@dataclass(frozen=True)
class Uc:
    yontem: str
    yol: str
    rota: APIRoute
    izinler: tuple[str, ...]  # hepsi gerekli
    herhangi: tuple[str, ...]  # en az biri gerekli (boşsa yok)

    @property
    def korumali(self) -> bool:
        return bool(self.izinler or self.herhangi)

    def izinli_mi(self, kodlar: set[str]) -> bool:
        if not set(self.izinler) <= kodlar:
            return False
        return not self.herhangi or bool(set(self.herhangi) & kodlar)

    @property
    def ad(self) -> str:
        return f"{self.yontem} {self.yol}"


def _kapilar(dependant) -> tuple[list[str], list[str]]:
    hepsi: list[str] = []
    herhangi: list[str] = []
    for alt in dependant.dependencies:
        cagri = alt.call
        hepsi.extend(getattr(cagri, "izinler", ()) or ())
        herhangi.extend(tuple(getattr(cagri, "izinler_herhangi", ()) or ()))
        a, h = _kapilar(alt)
        hepsi.extend(a)
        herhangi.extend(h)
    return hepsi, herhangi


def _rotalar(rotalar, onek: str = "", kapilar=()):
    """`APIRoute`'ları düzleştirir.

    FastAPI 0.14x `include_router`'ı `_IncludedRouter` sarmalayıcısıyla
    tembel bağlar: `app.routes` artık uçları doğrudan listelemiyor. Tarama
    özgün router'a iner; `include_router(prefix=..., dependencies=...)` ile
    verilen önek ve bağımlılıklar da hesaba katılır.
    """
    for rota in rotalar:
        if isinstance(rota, APIRoute):
            yield onek + rota.path, rota, kapilar
        elif hasattr(rota, "original_router"):
            baglam = getattr(rota, "include_context", None)
            ek_onek = getattr(baglam, "prefix", "") or ""
            ek_kapilar = tuple(getattr(baglam, "dependencies", ()) or ())
            yield from _rotalar(rota.original_router.routes, onek + ek_onek, kapilar + ek_kapilar)


def uclar(app) -> list[Uc]:
    sonuc: list[Uc] = []
    for yol, rota, ek_kapilar in _rotalar(app.routes):
        hepsi, herhangi = _kapilar(rota.dependant)
        for bagimlilik in ek_kapilar:
            cagri = getattr(bagimlilik, "dependency", None)
            hepsi.extend(getattr(cagri, "izinler", ()) or ())
            herhangi.extend(tuple(getattr(cagri, "izinler_herhangi", ()) or ()))
        for yontem in sorted(rota.methods - {"HEAD", "OPTIONS"}):
            sonuc.append(
                Uc(
                    yontem=yontem,
                    yol=yol,
                    rota=rota,
                    izinler=tuple(dict.fromkeys(hepsi)),
                    herhangi=tuple(dict.fromkeys(herhangi)),
                )
            )
    return sonuc


def ts_ucu_mu(yol: str) -> bool:
    return yol.startswith(TS_ONEKLERI)


_PARAM = re.compile(r"\{([^}:]+)(:[^}]+)?\}")


def yol_doldur(yol: str, degerler: dict[str, Any] | None = None) -> str:
    degerler = degerler or {}
    return _PARAM.sub(lambda m: str(degerler.get(m.group(1), YOK_KIMLIK)), yol)


def yol_parametreleri(yol: str) -> list[str]:
    return [m.group(1) for m in _PARAM.finditer(yol)]


# --- Örnek istek ---------------------------------------------------------------


def _deger(sema: dict, tanimlar: dict) -> Any:
    if "$ref" in sema:
        return _deger(tanimlar[sema["$ref"].rsplit("/", 1)[-1]], tanimlar)
    for anahtar in ("anyOf", "oneOf"):
        if anahtar in sema:
            secenekler = [s for s in sema[anahtar] if s.get("type") != "null"]
            return _deger(secenekler[0] if secenekler else {"type": "null"}, tanimlar)
    if "allOf" in sema:
        return _deger(sema["allOf"][0], tanimlar)
    if "examples" in sema and sema["examples"]:
        return sema["examples"][0]
    if "default" in sema:
        return sema["default"]
    if "enum" in sema:
        return sema["enum"][0]
    if "const" in sema:
        return sema["const"]
    tur = sema.get("type")
    if tur == "string":
        bicim = sema.get("format")
        if bicim == "date":
            return "2026-01-15"
        if bicim == "date-time":
            return "2026-01-15T09:00:00+03:00"
        if bicim == "email":
            return "ornek@example.com"
        return "x" * max(int(sema.get("minLength", 1)), 1)
    if tur == "integer":
        return max(int(sema.get("minimum", 1)), 1)
    if tur == "number":
        return max(float(sema.get("minimum", 1)), 1.0)
    if tur == "boolean":
        return False
    if tur == "array":
        adet = int(sema.get("minItems", 0))
        return [_deger(sema.get("items", {}), tanimlar) for _ in range(adet)]
    if tur == "object":
        return _nesne(sema, tanimlar)
    return None


def _nesne(sema: dict, tanimlar: dict) -> dict:
    zorunlu = set(sema.get("required", ()))
    ozellikler = sema.get("properties", {})
    # İyimser kilit alanı zorunlu olmasa da gönderilir: kapsam kontrolü
    # sürümden ÖNCE gelmeli, sürüm uyuşmazlığı (409) onu gizlememeli.
    alanlar = zorunlu | ({"version"} & set(ozellikler))
    return {ad: _deger(ozellikler[ad], tanimlar) for ad in ozellikler if ad in alanlar}


def ornek_govde(rota: APIRoute) -> tuple[str, Any] | None:
    """('json', gövde) | ('form', None) | None (gövdesiz uç)."""
    alan = rota.body_field
    if alan is None:
        return None
    if any(type(p.field_info).__name__ in ("Form", "File") for p in rota.dependant.body_params):
        return ("form", None)
    model = getattr(alan.field_info, "annotation", None) or getattr(alan, "type_", None)
    sema_kaynagi = getattr(model, "model_json_schema", None)
    if sema_kaynagi is None:
        return ("json", {})
    ayar = getattr(model, "model_config", {}) or {}
    ekstra = ayar.get("json_schema_extra") or {}
    if isinstance(ekstra, dict) and ekstra.get("examples"):
        return ("json", ekstra["examples"][0])
    sema = sema_kaynagi()
    return ("json", _nesne(sema, sema.get("$defs", {})))


def ornek_sorgu(rota: APIRoute) -> dict[str, str]:
    """Zorunlu sorgu parametrelerini yer tutucuyla doldurur."""
    sorgu: dict[str, str] = {}
    for p in rota.dependant.query_params:
        if not p.field_info.is_required():
            continue
        tur = getattr(p.field_info, "annotation", None)
        ad = getattr(tur, "__name__", str(tur))
        if "int" in ad:
            sorgu[p.alias] = "1"
        elif "date" in ad:
            sorgu[p.alias] = "2026-01-15"
        elif "bool" in ad:
            sorgu[p.alias] = "false"
        else:
            sorgu[p.alias] = "xx"
    return sorgu


async def cagir(istemci, uc: Uc, yol: str):
    govde = ornek_govde(uc.rota)
    kw: dict[str, Any] = {"params": ornek_sorgu(uc.rota)}
    if govde is not None and govde[0] == "json":
        kw["json"] = govde[1]
    return await istemci.request(uc.yontem, yol, **kw)
