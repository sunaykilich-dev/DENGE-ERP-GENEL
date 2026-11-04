"""Şirket ayrımı — etkin şirket, üyelik ve birim kümesi (KARARLAR 2026-11-04 §1).

**Ayrım anahtarı birimdir.** Her birim tek bir şirkete aittir
(`birim_sirketleri`). Kullanıcının görebileceği birimler =
(kapsamına göre birimleri) ∩ (etkin şirketin birimleri). Kesişim TEK yerde,
`services/teknik_servis/kapsam.py`'de uygulanır; bu modül yalnız "etkin şirket
hangisi, birimleri neler" sorusunu cevaplar.

**Etkin şirket OTURUMDA tutulur** (`sessions.aktif_sirket`). Her istekte
`api/deps.current_user` → `auth.resolve_session` → `oturuma_bagla` çağrılır ve
sonuç kullanıcı nesnesine GEÇİCİ öznitelik olarak bağlanır:

- `_aktif_sirket`: etkin şirket kodu (None = üyelik yok);
- `_sirket_birimleri`: etkin şirketin birimleri (frozenset);
- `_uye_sirketler`: seçilebilir şirketler (sıralı).

**Fail-closed:** bağlanmamış kullanıcı (istek dışı çağrı, unutulmuş yol) için
`etkin_birimler` BOŞ küme döner → şirkete bağlı hiçbir kayıt görünmez,
mobilite kapısı kapalıdır. "Bağlı değil = süzgeç yok" yorumu, yeni bir arka
plan yolunda bütün şirketlerin kayıtlarını açardı. Bilinçli olarak süzgeçsiz
çalışması gereken sahte kullanıcı `_sirket_birimleri=None` taşır
(ör. `api/egitim._gecerlilik_kisi`: kart zaten kapsamdan geçmiş).

**Varsayılan etkin şirket** (girişte ve üyelik değişince): (1) birincil
biriminin şirketi, (2) DENGE MOBİLİTE — canlı sistem mobilite şirketidir; birimi
olmayan canlı kullanıcılar (DEPO, SATIS, MUHASEBE ...) geçişten sonra ekranlarını
kaybetmesin, (3) `SIRKETLER` sırasındaki ilk üyelik.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BirimSirketi, Sirket, User
from app.permissions import MOBILITE_SIRKETI, SIRKETLER

# Seçici sırası: önce `SIRKETLER` sözlüğünün sırası, sonra (varsa) kod sırası.
_SIRA = {kod: i for i, kod in enumerate(SIRKETLER)}

SIRKET_DISI_KODU = "SIRKET_DISI"


@dataclass(frozen=True)
class SirketKaydi:
    kod: str
    ad: str
    birimler: tuple[str, ...] = field(default_factory=tuple)


async def katalog(db: AsyncSession) -> list[SirketKaydi]:
    """AKTİF şirketler ve birimleri, seçici sırasıyla (tek sorgu)."""
    satirlar = (
        await db.execute(
            select(Sirket.kod, Sirket.ad, BirimSirketi.birim)
            .outerjoin(BirimSirketi, BirimSirketi.sirket_kod == Sirket.kod)
            .where(Sirket.aktif.is_(True))
        )
    ).all()
    ad: dict[str, str] = {}
    birimler: dict[str, list[str]] = {}
    for kod, sirket_adi, birim in satirlar:
        ad[kod] = sirket_adi
        birimler.setdefault(kod, [])
        if birim is not None:
            birimler[kod].append(birim)
    sirali = sorted(ad, key=lambda k: (_SIRA.get(k, len(_SIRA)), k))
    return [SirketKaydi(k, ad[k], tuple(sorted(birimler[k]))) for k in sirali]


def _admin_mi(user: User) -> bool:
    return user.role is not None and user.role.code == "ADMIN"


def uye_sirketler(user: User, kat: list[SirketKaydi]) -> list[str]:
    """Kullanıcının seçebileceği aktif şirketler (seçici sırası).

    ADMIN bütün aktif şirketleri seçer (karar §1); diğerleri yalnız üyesi
    olduklarını. Pasif şirket listede yoktur.
    """
    aktifler = [s.kod for s in kat]
    if _admin_mi(user):
        return aktifler
    uyelik = set(user.sirket_kodlari)
    return [k for k in aktifler if k in uyelik]


def varsayilan_sirket(user: User, kat: list[SirketKaydi]) -> str | None:
    """Girişte etkin şirket: birincil birimin şirketi → MOBİLİTE → ilk üyelik."""
    uyeler = uye_sirketler(user, kat)
    if not uyeler:
        return None
    birincil = user.birincil_birim
    if birincil is not None:
        for s in kat:
            if birincil in s.birimler and s.kod in uyeler:
                return s.kod
    if MOBILITE_SIRKETI in uyeler:
        return MOBILITE_SIRKETI
    return uyeler[0]


def _bagla(user: User, kod: str | None, kat: list[SirketKaydi]) -> None:
    birimler = next((s.birimler for s in kat if s.kod == kod), ())
    user._aktif_sirket = kod  # type: ignore[attr-defined]
    user._sirket_birimleri = frozenset(birimler)  # type: ignore[attr-defined]
    user._uye_sirketler = uye_sirketler(user, kat)  # type: ignore[attr-defined]


async def oturuma_bagla(db: AsyncSession, user: User, istenen: str | None) -> str | None:
    """Oturumdaki şirketi doğrular ve kullanıcıya bağlar; ETKİN kodu döner.

    İstenen şirket artık seçilemiyorsa (üyelik kaldırıldı, şirket pasif)
    varsayılana düşer; çağıran oturum satırını bu değerle günceller.
    """
    kat = await katalog(db)
    uyeler = uye_sirketler(user, kat)
    kod = istenen if istenen in uyeler else varsayilan_sirket(user, kat)
    _bagla(user, kod, kat)
    return kod


async def varsayilan_uyelik(db: AsyncSession, rol, birimler: list[str]) -> list[str]:
    """Kullanıcı açılışında şirket verilmezse üyelik — migration göçüyle AYNI kural.

    Birimlerinin şirketleri; birimi yoksa ADMIN ve TUMU kapsamı bütün
    şirketler; hiçbiri değilse DENGE MOBİLİTE (canlı sistem mobilite şirketi).
    """
    from app.permissions import SCOPE_ALL

    kat = await katalog(db)
    if birimler:
        return [s.kod for s in kat if set(s.birimler) & set(birimler)]
    if rol is not None and (rol.code == "ADMIN" or rol.scope == SCOPE_ALL):
        return [s.kod for s in kat]
    return [MOBILITE_SIRKETI]


# --- Kapsam yardımcılarının girdisi (kapsam.py bunları modül özniteliği olarak
# çağırır; testler `conftest` üzerinden bunları süzgeçsiz sürüme çevirebilir) ---


def etkin_birimler(user) -> frozenset[str] | None:
    """Etkin şirketin birimleri; None = şirket süzgeci yok (yalnız bilinçli
    işaretlenmiş sahte kullanıcı). Bağlanmamış kullanıcı → boş küme."""
    if not hasattr(user, "_sirket_birimleri"):
        return frozenset()
    return user._sirket_birimleri


def aktif_sirket(user) -> str | None:
    return getattr(user, "_aktif_sirket", None)


def secilebilir_sirketler(user) -> list[str]:
    deger = getattr(user, "_uye_sirketler", None)
    return list(deger) if deger is not None else []


def mobilite_acik_mi(user) -> bool:
    """Canlı mobilite modülü (cihaz, hat, araç, iş emri, hak ediş, teklif ...)
    yalnız etkin şirket DENGE MOBİLİTE iken açıktır."""
    return aktif_sirket(user) == MOBILITE_SIRKETI


def birim_etkin_sirkette_mi(user, birim: str | None) -> bool:
    """Yeni kayıt açılışında seçilen birim etkin şirkete ait mi?"""
    birimler = etkin_birimler(user)
    if birimler is None:
        return True
    return birim is not None and birim in birimler


def sirket_disi_mesaji(user) -> str:
    ad = SIRKETLER.get(aktif_sirket(user) or "", "seçili şirket")
    return (
        f"Seçilen birim etkin şirkete ({ad}) ait değil. "
        "Üst çubuktaki şirket seçiciden ilgili şirkete geçin."
    )
