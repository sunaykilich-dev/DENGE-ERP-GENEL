"""Ana Panel bileşen kaydı ve kişisel/rol düzeni (KARARLAR 2026-11-09 S8; G7.2/G7.3/G8.1).

**Bileşen kaydı (`BILESENLER`) tek kaynaktır.** Her bileşenin kodu, adı, gereken
izinleri (HEPSİ gerekli; kodlar `app/permissions.py`'den), varsayılan boyutu ve
verisinin geldiği uç burada yazılır. Ön yüz (`frontend/src/pages/anaPanel/
bilesenler.tsx`) yalnız ÇİZER: hangi bileşenin kime görüneceğine sunucu karar
verir ve katalogu kullanıcının izinleriyle süzülmüş olarak döndürür. Kişi
göremeyeceği veriyi panele EKLEYEMEZ (kayıtta 403) ve rol varsayılanında ya da
eski bir düzende kalmış izinsiz bileşen okumada DÜŞER (S8.2). Veri uçlarının
kendi izin kapıları ayrıca geçerlidir (servis verisi `servis.gor`, ekip satırları
`operasyon.gor`, teklif sayıları `teklif.gor` + teklif kapsamı); bu kayıt veri
açmaz, yalnız ekranda yer ayırır.

**Etkin düzen:** kullanıcının kendi düzeni → rolünün varsayılanı (yönetici,
`panel.yonet`, G7.3/S8.3) → sistem varsayılanı (`SISTEM_VARSAYILANI` = bugünkü
Ana Panel). Sistem varsayılanındaki bileşenlerin hiçbirini göremeyen kullanıcıya
(ör. yalnız `teklif.gor`'u olan satış) izinli bütün bileşenler varsayılan
boyutlarıyla gösterilir: boş panel açılmasın.

**Yeni bileşen eklemek:** buraya bir `Bilesen` + ön yüzde aynı kodla çizim.
Kişisel düzeni olan kullanıcıya yeni bileşen kendiliğinden EKLENMEZ (düzen
onun seçimidir); katalogdan ekler. Migration gerekmez (kodlar şemada sabit
değil).

**Satış bileşenleri (S8.2):** "Tekliflerim" mevcut `GET /api/teklifler/ozet?
hazirlayan_id=` ucunu kullanır. "Kazanma oranı" ve "Satışlarımın durumu" için
henüz uç YOK (satış raporları ayrı oturumda yapılıyor); kayıt yerleri
`PLANLANAN_BILESENLER`'de belgelidir ve uç gelince buraya taşınır.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnaPanelDuzeni, Role, User
from app.services import audit

DAR = "DAR"
GENIS = "GENIS"
BOYUTLAR = (DAR, GENIS)

# Kaynaklar: etkin düzenin nereden geldiği (ön yüz "rol varsayılanı" rozetini çizer).
KAYNAK_KULLANICI = "KULLANICI"
KAYNAK_ROL = "ROL"
KAYNAK_SISTEM = "SISTEM"

# Rol varsayılanını düzenleme izni (G7.3: düzenleme yalnız yöneticilere).
ROL_DUZENI_IZNI = "panel.yonet"


class DuzenHatasi(ValueError):
    """Girdi hatası (bilinmeyen/tekrarlı bileşen) → 400."""


class DuzenYetkiHatasi(PermissionError):
    """İzinsiz bileşen → 403."""


class DuzenCakismasi(Exception):
    """İyimser kilit: düzen siz düzenlerken değişti → 409."""


@dataclass(frozen=True)
class Bilesen:
    kod: str
    ad: str
    aciklama: str
    grup: str
    # "gosterge" (tek sayı kartı) | "kart" (liste/grafik). Izgara boyutunu belirler.
    tur: str
    # HEPSİ gerekli.
    izinler: tuple[str, ...]
    varsayilan_boyut: str = DAR
    # Verinin geldiği uç (belge; ön yüz aynı ucu çağırır).
    veri: str = "servis"


_SERVIS = ("servis.gor",)
_TS = "Teknik Servis"

BILESENLER: tuple[Bilesen, ...] = (
    # --- Teknik servis göstergeleri (`GET /api/teknik-servis/ana-panel` → `kpiler`) ---
    Bilesen("kpi_acik_is", "Açık İş Emirleri", "Kapsamınızdaki açık servis işleri; dönem başına göre değişim.", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_planli_bakim", "Planlı Bakım Bu Ay", "Bu ay planlı bakım işleri; hedefe göre.", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_acil_ariza", "Acil / Kritik Arıza", "Açık kritik öncelikli arızalar.", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_poc_acik", "POC Açık Talep", "POC biriminin açık talepleri (POC kapsamınızdaysa).", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_sla_riski", "SLA Riski Olan İşler", "Çözüm hedefi riskte ya da aşılmış açık işler.", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_sahadaki_ekip", "Sahadaki Ekip", "Açık zaman kaydı olan saha personeli / toplam.", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_askida", "Askıdaki Kayıtlar", "Beklemedeki (askıdaki) servis işleri.", _TS, "gosterge", _SERVIS),  # noqa: E501
    Bilesen("kpi_bekleyen_onay", "Bekleyen Onaylar", "Şef kapanışı ya da kalite onayı bekleyen işler.", _TS, "gosterge", _SERVIS),  # noqa: E501
    # --- Teknik servis kartları ---
    Bilesen("birim_ozeti", "Canlı Operasyon Özeti", "Birim bazında açık, sahada, atölyede ve tamamlanan işler.", _TS, "kart", _SERVIS, GENIS),  # noqa: E501
    Bilesen("ekip_durumu", "Canlı Ekip Durumu", "Kim sahada, kim müsait; Operasyon Merkezi yetkisi gerekir.", _TS, "kart", ("servis.gor", "operasyon.gor")),  # noqa: E501
    Bilesen("aktif_isler", "Aktif İşler / Kim Ne Yapıyor", "Son güncellenen açık işler, tayinli ekip ve SLA.", _TS, "kart", _SERVIS, GENIS),  # noqa: E501
    Bilesen("bekleyen_aksiyonlar", "Birimler Arası Bekleyen Aksiyonlar", "Başka birimin aksiyonunu bekleyen işler.", _TS, "kart", _SERVIS),  # noqa: E501
    Bilesen("grafik_durum", "Duruma Göre İşler", "Açık işlerin durum dağılımı.", _TS, "kart", _SERVIS),  # noqa: E501
    Bilesen("grafik_bolum", "Bölüme Göre İş Yükü", "Birim bazında açık iş yükü.", _TS, "kart", _SERVIS),  # noqa: E501
    Bilesen("grafik_pb", "Planlı Bakım Tamamlanma", "Bu ayın planlı bakım işlerinin tamamlanma oranı.", _TS, "kart", _SERVIS),  # noqa: E501
    Bilesen("grafik_haftalik", "Haftalık Plan", "Bu haftanın günlük planlı iş sayıları.", _TS, "kart", _SERVIS),  # noqa: E501
    Bilesen("grafik_aylik", "Aylık Plan / Bakım Takvimi", "Ayın bakım hedefi ve yaklaşan bakımlar.", _TS, "kart", _SERVIS),  # noqa: E501
    # --- Satış (S8.2) — mevcut teklif özeti ucu, `hazirlayan_id` = kendisi ---
    Bilesen("tekliflerim", "Tekliflerim", "Hazırladığınız tekliflerin durum sayıları (onay bekleyen, yanıt bekleyen, süresi yaklaşan...).", "Satış", "kart", ("teklif.gor",), veri="teklif"),  # noqa: E501
)  # fmt: skip

BILESEN_HARITASI: dict[str, Bilesen] = {b.kod: b for b in BILESENLER}

# S8.2'nin henüz veri ucu olmayan satış bileşenleri. Uç gelince `BILESENLER`'e
# taşınır (kod sabittir; ön yüz aynı kodla çizer):
# - "kazanma_orani"      — Kazanma oranı (kabul / karara bağlanan teklif), `teklif.gor`.
# - "satislarim_durumu"  — Satışlarımın durumu (sipariş/sevk), `siparis.gor`.
PLANLANAN_BILESENLER: dict[str, str] = {
    "kazanma_orani": "Kazanma Oranı",
    "satislarim_durumu": "Satışlarımın Durumu",
}

# Bugünkü Ana Panel (geri dönüş). Sıra = ekrandaki sıra.
SISTEM_VARSAYILANI: tuple[tuple[str, str], ...] = (
    ("kpi_acik_is", DAR),
    ("kpi_planli_bakim", DAR),
    ("kpi_acil_ariza", DAR),
    ("kpi_poc_acik", DAR),
    ("kpi_sla_riski", DAR),
    ("kpi_sahadaki_ekip", DAR),
    ("kpi_askida", DAR),
    ("kpi_bekleyen_onay", DAR),
    ("birim_ozeti", GENIS),
    ("ekip_durumu", DAR),
    ("aktif_isler", GENIS),
    ("bekleyen_aksiyonlar", DAR),
    ("grafik_durum", DAR),
    ("grafik_bolum", DAR),
    ("grafik_pb", DAR),
    ("grafik_haftalik", DAR),
    ("grafik_aylik", DAR),
)

IzinVar = Callable[[str], bool]


# --- Saf yardımcılar -------------------------------------------------------------------------


def izinli_mi(b: Bilesen, izin_var: IzinVar) -> bool:
    return all(izin_var(i) for i in b.izinler)


def katalog(izin_var: IzinVar) -> list[dict[str, Any]]:
    """İzinle süzülmüş bileşen kataloğu (ekleme çekmecesi)."""
    return [
        {
            "kod": b.kod,
            "ad": b.ad,
            "aciklama": b.aciklama,
            "grup": b.grup,
            "tur": b.tur,
            "varsayilan_boyut": b.varsayilan_boyut,
            "veri": b.veri,
        }
        for b in BILESENLER
        if izinli_mi(b, izin_var)
    ]


def _oge(kod: str, boyut: str, gorunur: bool = True) -> dict[str, Any]:
    return {"kod": kod, "boyut": boyut, "gorunur": gorunur}


def suz(bilesenler: Iterable[dict[str, Any]], izin_var: IzinVar) -> list[dict[str, Any]]:
    """Kayıtlı listeyi okunur hale getirir: bilinmeyen/izinsiz/tekrarlı kod ve
    geçersiz boyut DÜŞER (eski düzen ya da izni geri alınmış kullanıcı)."""
    sonuc: list[dict[str, Any]] = []
    gorulen: set[str] = set()
    for o in bilesenler or []:
        if not isinstance(o, dict):
            continue
        kod = o.get("kod")
        b = BILESEN_HARITASI.get(kod) if isinstance(kod, str) else None
        if b is None or kod in gorulen or not izinli_mi(b, izin_var):
            continue
        boyut = o.get("boyut") if o.get("boyut") in BOYUTLAR else b.varsayilan_boyut
        gorulen.add(b.kod)
        sonuc.append(_oge(b.kod, boyut, bool(o.get("gorunur", True))))
    return sonuc


def sistem_varsayilani(izin_var: IzinVar) -> list[dict[str, Any]]:
    """Bugünkü panel; hiçbir bileşenini göremeyene izinli bütün bileşenler."""
    duzen = suz((_oge(k, s) for k, s in SISTEM_VARSAYILANI), izin_var)
    if duzen:
        return duzen
    return [_oge(b.kod, b.varsayilan_boyut) for b in BILESENLER if izinli_mi(b, izin_var)]


def dogrula(bilesenler: list[dict[str, Any]], izin_var: IzinVar, *, kime: str) -> list[dict]:
    """Kayıt girdisi: bilinmeyen/tekrarlı kod → `DuzenHatasi` (400); izinsiz
    bileşen → `DuzenYetkiHatasi` (403). `kime` hata metnindeki sahip adıdır."""
    gorulen: set[str] = set()
    temiz: list[dict[str, Any]] = []
    for o in bilesenler:
        kod = o["kod"]
        b = BILESEN_HARITASI.get(kod)
        if b is None:
            raise DuzenHatasi(f"Bilinmeyen bileşen: {kod}")
        if kod in gorulen:
            raise DuzenHatasi(f"Bileşen iki kez eklenmiş: {b.ad}")
        if o["boyut"] not in BOYUTLAR:
            raise DuzenHatasi(f"Geçersiz boyut: {o['boyut']}")
        if not izinli_mi(b, izin_var):
            raise DuzenYetkiHatasi(
                f"'{b.ad}' bileşeni için {kime} yetkisi yok ({', '.join(b.izinler)})"
            )
        gorulen.add(kod)
        temiz.append(_oge(kod, o["boyut"], bool(o.get("gorunur", True))))
    return temiz


def rol_izin_kumesi(rol: Role) -> set[str]:
    return {rp.permission_code for rp in rol.permissions}


def _surum_kontrol(kayit: AnaPanelDuzeni | None, version: int | None) -> None:
    """Kayıt varsa istemci aynı sürümü göndermeli; yoksa sürüm göndermemeli
    (başka cihazda açılmış/sıfırlanmış düzenin üstüne sessizce yazılmasın)."""
    mevcut = kayit.version if kayit is not None else None
    if mevcut != version:
        raise DuzenCakismasi(
            "Panel düzeni siz düzenlerken başka bir yerden değişti. Sayfayı yenileyin."
        )


# --- Kullanıcı düzeni ------------------------------------------------------------------------


async def _kullanici_kaydi(db: AsyncSession, user_id: int) -> AnaPanelDuzeni | None:
    return await db.scalar(select(AnaPanelDuzeni).where(AnaPanelDuzeni.user_id == user_id))


async def _rol_kaydi(db: AsyncSession, role_id: int) -> AnaPanelDuzeni | None:
    return await db.scalar(select(AnaPanelDuzeni).where(AnaPanelDuzeni.role_id == role_id))


async def varsayilan_duzen(db: AsyncSession, user: User) -> tuple[str, list[dict[str, Any]]]:
    """Kullanıcının "varsayılana dön" hedefi: rol varsayılanı, yoksa sistem."""
    rol = await _rol_kaydi(db, user.role_id)
    if rol is not None:
        return KAYNAK_ROL, suz(rol.bilesenler, user.has)
    return KAYNAK_SISTEM, sistem_varsayilani(user.has)


async def etkin_duzen(db: AsyncSession, user: User) -> dict[str, Any]:
    kaynak, varsayilan = await varsayilan_duzen(db, user)
    kayit = await _kullanici_kaydi(db, user.id)
    return {
        "kaynak": KAYNAK_KULLANICI if kayit is not None else kaynak,
        "version": kayit.version if kayit is not None else None,
        "bilesenler": suz(kayit.bilesenler, user.has) if kayit is not None else varsayilan,
        "varsayilan": {"kaynak": kaynak, "bilesenler": varsayilan},
        "katalog": katalog(user.has),
        "rol_duzenleyebilir": user.has(ROL_DUZENI_IZNI),
    }


async def kaydet(
    db: AsyncSession,
    user: User,
    bilesenler: list[dict[str, Any]],
    version: int | None,
    *,
    ip: str | None = None,
) -> dict[str, Any]:
    temiz = dogrula(bilesenler, user.has, kime="yetkiniz")
    kayit = await _kullanici_kaydi(db, user.id)
    _surum_kontrol(kayit, version)
    if kayit is None:
        kayit = AnaPanelDuzeni(user_id=user.id, bilesenler=temiz, created_by=user.id)
        db.add(kayit)
        eylem = "olustur"
    else:
        kayit.bilesenler = temiz
        kayit.updated_by = user.id
        eylem = "guncelle"
    await db.flush()
    await audit.log(
        db,
        "ana_panel_duzeni",
        eylem,
        entity_id=kayit.id,
        new_value={"sahip": f"kullanici:{user.id}", "bilesenler": temiz},
        user_id=user.id,
        ip=ip,
    )
    return await etkin_duzen(db, user)


async def sifirla(
    db: AsyncSession, user: User, version: int | None, *, ip: str | None = None
) -> dict[str, Any]:
    """ "Varsayılana dön": kişisel düzen silinir; rol/sistem varsayılanı geçer.
    Kayıt yoksa işlem zaten yapılmıştır (idempotent)."""
    kayit = await _kullanici_kaydi(db, user.id)
    if kayit is not None:
        if version is not None:
            _surum_kontrol(kayit, version)
        await audit.log(
            db,
            "ana_panel_duzeni",
            "sifirla",
            entity_id=kayit.id,
            old_value={"sahip": f"kullanici:{user.id}", "bilesenler": kayit.bilesenler},
            user_id=user.id,
            ip=ip,
        )
        await db.delete(kayit)
        await db.flush()
    return await etkin_duzen(db, user)


# --- Rol varsayılanı (G7.3, S8.3) --------------------------------------------------------------


async def rol_getir(db: AsyncSession, rol_kodu: str) -> Role | None:
    return await db.scalar(select(Role).where(Role.code == rol_kodu))


def _rol_izni(rol: Role, duzenleyen: User) -> IzinVar:
    """Rol varsayılanına konabilecek bileşen: rolün izni VAR ve düzenleyen de
    o veriyi görebiliyor (yönetici göremediği bileşeni başkasına dayatmasın)."""
    rol_izinleri = rol_izin_kumesi(rol)
    return lambda kod: kod in rol_izinleri and duzenleyen.has(kod)


async def rol_listesi(db: AsyncSession) -> list[dict[str, Any]]:
    roller = (await db.scalars(select(Role).order_by(Role.name, Role.id))).all()
    kayitlar = {
        k.role_id: k
        for k in (
            await db.scalars(select(AnaPanelDuzeni).where(AnaPanelDuzeni.role_id.is_not(None)))
        ).all()
    }
    return [
        {
            "rol_kodu": r.code,
            "rol_adi": r.name,
            "ozel": r.id in kayitlar,
            "version": kayitlar[r.id].version if r.id in kayitlar else None,
        }
        for r in roller
    ]


async def rol_duzeni(db: AsyncSession, rol: Role, duzenleyen: User) -> dict[str, Any]:
    rol_izinleri = rol_izin_kumesi(rol)
    kayit = await _rol_kaydi(db, rol.id)

    def rol_var(kod: str) -> bool:
        return kod in rol_izinleri

    return {
        "rol_kodu": rol.code,
        "rol_adi": rol.name,
        "kaynak": KAYNAK_ROL if kayit is not None else KAYNAK_SISTEM,
        "version": kayit.version if kayit is not None else None,
        # Okumada rolün izniyle süzülür (rolden izin düşmüşse bileşen de düşer).
        "bilesenler": suz(kayit.bilesenler, rol_var)
        if kayit is not None
        else sistem_varsayilani(rol_var),
        "sistem_varsayilani": sistem_varsayilani(rol_var),
        "katalog": katalog(_rol_izni(rol, duzenleyen)),
    }


async def rol_kaydet(
    db: AsyncSession,
    rol: Role,
    duzenleyen: User,
    bilesenler: list[dict[str, Any]],
    version: int | None,
    *,
    ip: str | None = None,
) -> dict[str, Any]:
    kime = f"'{rol.name}' rolünün ya da sizin"
    temiz = dogrula(bilesenler, _rol_izni(rol, duzenleyen), kime=kime)
    kayit = await _rol_kaydi(db, rol.id)
    _surum_kontrol(kayit, version)
    eski: list | None = None
    if kayit is None:
        kayit = AnaPanelDuzeni(role_id=rol.id, bilesenler=temiz, created_by=duzenleyen.id)
        db.add(kayit)
        eylem = "rol_olustur"
    else:
        eski = kayit.bilesenler
        kayit.bilesenler = temiz
        kayit.updated_by = duzenleyen.id
        eylem = "rol_guncelle"
    await db.flush()
    await audit.log(
        db,
        "ana_panel_duzeni",
        eylem,
        entity_id=kayit.id,
        old_value={"bilesenler": eski} if eski is not None else None,
        new_value={"sahip": f"rol:{rol.code}", "bilesenler": temiz},
        user_id=duzenleyen.id,
        ip=ip,
    )
    return await rol_duzeni(db, rol, duzenleyen)


async def rol_sifirla(
    db: AsyncSession, rol: Role, duzenleyen: User, version: int | None, *, ip: str | None = None
) -> dict[str, Any]:
    kayit = await _rol_kaydi(db, rol.id)
    if kayit is not None:
        if version is not None:
            _surum_kontrol(kayit, version)
        await audit.log(
            db,
            "ana_panel_duzeni",
            "rol_sifirla",
            entity_id=kayit.id,
            old_value={"sahip": f"rol:{rol.code}", "bilesenler": kayit.bilesenler},
            user_id=duzenleyen.id,
            ip=ip,
        )
        await db.delete(kayit)
        await db.flush()
    return await rol_duzeni(db, rol, duzenleyen)
