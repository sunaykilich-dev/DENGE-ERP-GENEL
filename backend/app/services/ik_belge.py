"""İK "Bordro ve Belgeler" iş kuralları (KARARLAR_2026-10-28 §11).

Akış: İK gönderir (GONDERILDI) → personel belgeyi açar (GORULDU) → parolasını
(ya da iki adımlı doğrulama kodunu) tekrar girip onaylar (ONAYLANDI) veya
gerekçe yazıp itiraz eder (ITIRAZ). Yanıt verilmiş belge bir daha değişmez;
yanlış gönderilen ve yanıtlanmamış belgeyi İK geri alır (GERI_ALINDI).

İmza kanıtı `ik_belge_olaylari` zinciridir: her olay belgenin sha256 özetini,
zamanı, IP'yi, tarayıcıyı, doğrulama yolunu ve ÖNCEKİ olayın özetini taşır;
satırın kendi özeti bunların hepsinden hesaplanır. Bir satır sonradan
değiştirilirse (tetikleyici de aşılırsa) `zincir_dogrula` bunu yakalar.

Kişisel veri: denetim izine yalnız kimlikler ve sayılar yazılır; itiraz metni,
tutar ve dosya adı yazılmaz. E-posta bildirimi belge EKLEMEZ, yalnız haber
verir (bordro e-postayla dolaşmasın).
"""

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.models import IkBelge, IkBelgeOlayi, IkGonderim, User
from app.models.ik_belge import BELGE_TURLERI, SON_DURUMLAR
from app.services import audit, mail, mfa
from app.services import auth as auth_service
from app.services.normalize import tr_normkey
from app.services.storage import Kayit

log = logging.getLogger(__name__)

TUR_ADLARI = {
    "BORDRO": "Bordro",
    "FORM": "Form",
    "TALIMAT": "Talimat",
    "TAAHHUTNAME": "Taahhütname",
    "KVKK": "KVKK metni",
    "DIGER": "Belge",
}
BEKLEYEN_DURUMLAR = ("GONDERILDI", "GORULDU")
IZIN_BORDRO = "bordro.yonet"
IZIN_BELGE = "ik_belge.yonet"


class IkBelgeHatasi(ValueError):
    """İş kuralı ihlali; API `durum` koduyla döner."""

    def __init__(self, mesaj: str, durum: int = 400) -> None:
        super().__init__(mesaj)
        self.durum = durum


class DogrulamaHatasi(IkBelgeHatasi):
    """Parola/kod yanlış. Sayaç işlendiği için API önce commit eder."""


def tur_izni(tur: str) -> str:
    return IZIN_BORDRO if tur == "BORDRO" else IZIN_BELGE


def yonetebilir_mi(user: User, tur: str) -> bool:
    return user.has(tur_izni(tur))


# --- Olay zinciri ----------------------------------------------------------------


def _kayit_ozeti(alanlar: dict[str, Any]) -> str:
    metin = json.dumps(alanlar, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()


def _olay_alanlari(o: IkBelgeOlayi) -> dict[str, Any]:
    return {
        "belge_id": o.belge_id,
        "olay": o.olay,
        "user_id": o.user_id,
        # Saat dilimi DB dönüşünde değişebilir; özet UTC'ye göre.
        "at": o.at.astimezone(UTC).isoformat(),
        "ip": o.ip,
        "user_agent": o.user_agent,
        "dogrulama": o.dogrulama,
        "belge_ozeti": o.belge_ozeti,
        "aciklama": o.aciklama,
        "onceki_ozet": o.onceki_ozet,
    }


@dataclass(frozen=True)
class Istek:
    """İsteğin kanıta girecek bilgileri."""

    an: datetime
    ip: str | None = None
    user_agent: str | None = None


async def olay_ekle(
    db: AsyncSession,
    belge: IkBelge,
    olay: str,
    *,
    user_id: int | None,
    istek: Istek,
    dogrulama: str | None = None,
    aciklama: str | None = None,
) -> IkBelgeOlayi:
    onceki = await db.scalar(
        select(IkBelgeOlayi.kayit_ozeti)
        .where(IkBelgeOlayi.belge_id == belge.id)
        .order_by(IkBelgeOlayi.id.desc())
        .limit(1)
    )
    o = IkBelgeOlayi(
        belge_id=belge.id,
        olay=olay,
        user_id=user_id,
        at=istek.an,
        ip=(istek.ip or None) and istek.ip[:64],
        user_agent=(istek.user_agent or None) and istek.user_agent[:300],
        dogrulama=dogrulama,
        belge_ozeti=belge.sha256,
        aciklama=aciklama,
        onceki_ozet=onceki,
    )
    o.kayit_ozeti = _kayit_ozeti(_olay_alanlari(o))
    db.add(o)
    await db.flush()
    return o


def zincir_dogrula(olaylar: Sequence[IkBelgeOlayi], belge_ozeti: str) -> bool:
    """Olaylar id sırasıyla: her özet yeniden hesaplanır ve bir öncekine bağlanır."""
    onceki: str | None = None
    for o in olaylar:
        if o.onceki_ozet != onceki or o.belge_ozeti != belge_ozeti:
            return False
        if _kayit_ozeti(_olay_alanlari(o)) != o.kayit_ozeti:
            return False
        onceki = o.kayit_ozeti
    return True


# --- Dosya adından kişi eşleştirme --------------------------------------------------

_ASCII = str.maketrans({"ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "ı": "i"})


def _sade(metin: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", tr_normkey(metin).translate(_ASCII))


def _parcalar(dosya_adi: str) -> set[str]:
    govde = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", dosya_adi or "")
    return {_sade(p) for p in re.split(r"[\s_\-.()\[\]]+", govde) if _sade(p)}


async def alici_adaylari(db: AsyncSession) -> list[User]:
    """Belge gönderilebilecek kişiler: etkin ve ERP'ye girişi açık."""
    return list(
        (
            await db.scalars(
                select(User)
                .where(User.is_active.is_(True), User.giris_acik.is_(True))
                .order_by(User.full_name)
            )
        ).all()
    )


def eslestir(dosya_adlari: Sequence[str], kisiler: Sequence[User]) -> list[dict[str, Any]]:
    """Dosya adından kişi önerisi. Öncelik sicil no, sonra ad soyad.

    Uydurma yok: birden çok kişi tutarsa öneri verilmez (`BELIRSIZ`), İK seçer.
    TCKN sistemde tutulmadığı için TCKN'li dosya adları eşleşmez (§11.6).
    """
    siciller: dict[str, list[User]] = {}
    adlar: list[tuple[str, User]] = []
    for k in kisiler:
        if k.sicil_no and _sade(k.sicil_no):
            siciller.setdefault(_sade(k.sicil_no), []).append(k)
        ad = _sade(k.full_name)
        if len(ad) >= 5:
            adlar.append((ad, k))
    sonuc = []
    for dosya_adi in dosya_adlari:
        parca = _parcalar(dosya_adi)
        govde = _sade(re.sub(r"\.[A-Za-z0-9]{1,5}$", "", dosya_adi or ""))
        # Sicil ya bir parçaya tam eşit ya da (en az 4 karakterse) adın içinde
        # geçer: "2026-10_S-1001.pdf" → "s1001". Kısa sicil içerikte aranmaz.
        adaylar = {
            k.id: k
            for s, kisiler_ in siciller.items()
            if s in parca or (len(s) >= 4 and s in govde)
            for k in kisiler_
        }
        yontem = "SICIL"
        if not adaylar:
            adaylar = {k.id: k for ad, k in adlar if ad in govde}
            yontem = "AD"
        if len(adaylar) == 1:
            kisi = next(iter(adaylar.values()))
            sonuc.append(
                {"dosya_adi": dosya_adi, "user_id": kisi.id, "ad": kisi.full_name, "yontem": yontem}
            )
        else:
            sonuc.append(
                {
                    "dosya_adi": dosya_adi,
                    "user_id": None,
                    "ad": None,
                    "yontem": "BELIRSIZ" if adaylar else "YOK",
                }
            )
    return sonuc


# --- Gönderim -----------------------------------------------------------------------


@dataclass(frozen=True)
class Alici:
    user_id: int
    dosya: Kayit
    dosya_adi: str


async def gonder(
    db: AsyncSession,
    *,
    tur: str,
    baslik: str,
    donem: str | None,
    aciklama: str | None,
    son_tarih: date | None,
    sablon_id: int | None,
    alicilar: Sequence[Alici],
    gonderen: User,
    istek: Istek,
) -> IkGonderim:
    if tur not in BELGE_TURLERI:
        raise IkBelgeHatasi(f"Geçersiz belge türü: {tur}")
    if not yonetebilir_mi(gonderen, tur):
        raise IkBelgeHatasi(f"Bu işlem için yetkiniz yok ({tur_izni(tur)})", 403)
    if tur == "BORDRO" and not donem:
        raise IkBelgeHatasi("Bordro için dönem (YYYY-AA) zorunlu")
    if not alicilar:
        raise IkBelgeHatasi("En az bir alıcı seçin")
    idler = [a.user_id for a in alicilar]
    if len(set(idler)) != len(idler):
        raise IkBelgeHatasi("Aynı kişi bir gönderimde iki kez seçilemez")
    if son_tarih is not None and son_tarih < istek.an.date():
        raise IkBelgeHatasi("Son tarih geçmişte olamaz")

    kisiler = {k.id: k for k in (await db.scalars(select(User).where(User.id.in_(idler)))).all()}
    uygunsuz = [i for i in idler if i not in kisiler]
    if uygunsuz:
        raise IkBelgeHatasi("Seçilen kişi bulunamadı", 404)
    girissiz = [k.full_name for k in kisiler.values() if not (k.is_active and k.giris_acik)]
    if girissiz:
        raise IkBelgeHatasi(
            "ERP girişi kapalı kişiye belge gönderilemez (göremez): " + ", ".join(sorted(girissiz))
        )
    if tur == "BORDRO":
        # Aynı ayın bordrosu kişiye iki kez gitmez; düzeltme için eskisi geri alınır.
        var_olan = (
            await db.scalars(
                select(IkBelge.user_id)
                .join(IkGonderim, IkGonderim.id == IkBelge.gonderim_id)
                .where(
                    IkGonderim.tur == "BORDRO",
                    IkGonderim.donem == donem,
                    IkBelge.user_id.in_(idler),
                    IkBelge.durum != "GERI_ALINDI",
                )
            )
        ).all()
        if var_olan:
            adlar = ", ".join(sorted(kisiler[i].full_name for i in set(var_olan)))
            raise IkBelgeHatasi(
                f"{donem} bordrosu bu kişilere zaten gönderilmiş: {adlar}. "
                "Düzeltilmiş bordro için önce eskisini geri alın.",
                409,
            )

    g = IkGonderim(
        tur=tur,
        baslik=baslik.strip(),
        donem=donem,
        aciklama=(aciklama or "").strip() or None,
        son_tarih=son_tarih,
        sablon_id=sablon_id,
        created_by=gonderen.id,
        updated_by=gonderen.id,
    )
    db.add(g)
    await db.flush()
    for a in alicilar:
        b = IkBelge(
            gonderim_id=g.id,
            user_id=a.user_id,
            durum="GONDERILDI",
            gonderildi_at=istek.an,
            dosya_adi=a.dosya_adi,
            storage_path=a.dosya.storage_path,
            mime_type=a.dosya.mime_type,
            size_bytes=a.dosya.size_bytes,
            sha256=a.dosya.sha256,
        )
        db.add(b)
        await db.flush()
        await olay_ekle(db, b, "GONDERILDI", user_id=gonderen.id, istek=istek)
    await audit.log(
        db,
        "ik_gonderim",
        "gonder",
        entity_id=g.id,
        new_value={"tur": tur, "donem": donem, "kisi_sayisi": len(alicilar)},
        user_id=gonderen.id,
        ip=istek.ip,
    )
    return g


async def bildir(
    db: AsyncSession, kisiler: Sequence[User], *, g: IkGonderim, hatirlatma: bool
) -> int:
    """E-posta ile haber verir (belge eklenmez). Kaç kişiye gittiğini döner.

    Başarısız gönderim işi durdurmaz: belge ERP'de "Belgelerim"de zaten durur.
    SMTP tanımlı değilse hiç denemez.
    """
    gonderilen = 0
    tur = TUR_ADLARI.get(g.tur, "Belge")
    konu = ("Hatırlatma: " if hatirlatma else "") + f"{tur} onayınızı bekliyor: {g.baslik}"
    for k in kisiler:
        if not k.email:
            continue
        govde = (
            f"Merhaba {k.full_name},\n\n"
            f'Size "{g.baslik}" başlıklı {tur.lower()} gönderildi.'
            + (f" Son tarih: {g.son_tarih:%d.%m.%Y}." if g.son_tarih else "")
            + "\n\nBelgeyi ERP'de Belgelerim ekranından açıp onaylayabilir ya da "
            "gerekçe yazarak itiraz edebilirsiniz.\n\nBu e-posta bilgilendirme amaçlıdır; "
            "belge e-postaya eklenmez.\n"
        )
        try:
            await mail.gonder(db, alici=k.email, konu=konu, govde=govde)
        except mail.MailKapali:
            return gonderilen  # SMTP yok: diğerlerini denemenin anlamı yok
        except Exception as exc:  # noqa: BLE001 — bildirim belgeyi durdurmaz
            log.warning("İK belge bildirimi gönderilemedi: %s", type(exc).__name__)
            continue
        gonderilen += 1
    return gonderilen


async def hatirlat(
    db: AsyncSession,
    g: IkGonderim,
    *,
    belge_idleri: Sequence[int] | None,
    yapan: User,
    istek: Istek,
) -> list[IkBelge]:
    q = select(IkBelge).where(IkBelge.gonderim_id == g.id, IkBelge.durum.in_(BEKLEYEN_DURUMLAR))
    if belge_idleri:
        q = q.where(IkBelge.id.in_(belge_idleri))
    belgeler = list((await db.scalars(q.order_by(IkBelge.id))).all())
    for b in belgeler:
        b.hatirlatma_sayisi += 1
        b.son_hatirlatma_at = istek.an
        await olay_ekle(db, b, "HATIRLATMA", user_id=yapan.id, istek=istek)
    await audit.log(
        db,
        "ik_gonderim",
        "hatirlat",
        entity_id=g.id,
        new_value={"kisi_sayisi": len(belgeler)},
        user_id=yapan.id,
        ip=istek.ip,
    )
    return belgeler


async def geri_al(db: AsyncSession, b: IkBelge, *, gerekce: str, yapan: User, istek: Istek) -> None:
    if b.durum in SON_DURUMLAR:
        raise IkBelgeHatasi(
            "Yanıtlanmış ya da geri alınmış belge geri alınamaz; kanıt olarak kalır.", 409
        )
    b.durum = "GERI_ALINDI"
    b.yanit_at = istek.an
    await olay_ekle(db, b, "GERI_ALINDI", user_id=yapan.id, istek=istek, aciklama=gerekce.strip())
    await audit.log(db, "ik_belge", "geri_al", entity_id=b.id, user_id=yapan.id, ip=istek.ip)


# --- Personel tarafı ---------------------------------------------------------------


async def goruldu(db: AsyncSession, b: IkBelge, kisi: User, istek: Istek) -> None:
    """İlk açılışta GORULDU; sonrakiler olay üretmez (gürültü olmasın)."""
    if b.durum != "GONDERILDI":
        return
    b.durum = "GORULDU"
    b.goruldu_at = istek.an
    await olay_ekle(db, b, "GORULDU", user_id=kisi.id, istek=istek)


async def kimlik_dogrula(
    db: AsyncSession, kisi: User, *, parola: str | None, kod: str | None, clock: Clock
) -> str:
    """Parola tekrarı ya da (iki adımlı doğrulaması açıksa) tek kullanımlık kod.

    Yanlış deneme giriş sayacına işlenir: imza adımı parola denemek için
    kilitsiz bir kapı olmasın. Kilitli hesap imza atamaz.
    """
    if await auth_service.kilit_zamani(db, kisi.username) is not None:
        raise IkBelgeHatasi(
            "Hesabınız çok sayıda hatalı deneme nedeniyle kilitli. Sistem yöneticisine başvurun.",
            423,
        )
    if kod and kisi.mfa_enabled:
        if mfa.check_login_code(kisi, kod):
            return "TOTP"
    elif parola:
        if auth_service.verify_password(parola, kisi.password_hash):
            return "PAROLA"
    else:
        raise IkBelgeHatasi("Onay için parolanızı (ya da doğrulama kodunuzu) girin")
    kilitlendi = await auth_service.record_failed_login(db, kisi.username, clock)
    raise DogrulamaHatasi(
        "Hesabınız kilitlendi; sistem yöneticisine başvurun."
        if kilitlendi
        else "Parola ya da doğrulama kodu hatalı.",
        423 if kilitlendi else 400,
    )


def yanit_kontrol(b: IkBelge) -> None:
    """Parola denetiminden ÖNCE koşar: yanıtlanmış belgede sayaç işlemesin."""
    if b.durum in SON_DURUMLAR:
        raise IkBelgeHatasi("Bu belge zaten yanıtlanmış; yanıt değiştirilemez.", 409)
    if b.durum == "GONDERILDI":
        # "Okudum" beyanının anlamı olsun: belge açılmadan onay/itiraz yok.
        raise IkBelgeHatasi("Onaylamadan ya da itiraz etmeden önce belgeyi açıp okuyun.", 409)


async def yanitla(
    db: AsyncSession,
    b: IkBelge,
    kisi: User,
    *,
    onay: bool,
    gerekce: str | None,
    dogrulama: str,
    istek: Istek,
) -> None:
    yanit_kontrol(b)
    gerekce = (gerekce or "").strip()
    if not onay and len(gerekce) < 5:
        raise IkBelgeHatasi("İtiraz gerekçesi en az 5 karakter olmalı")
    b.durum = "ONAYLANDI" if onay else "ITIRAZ"
    b.yanit_at = istek.an
    b.itiraz_gerekcesi = None if onay else gerekce
    await olay_ekle(
        db,
        b,
        b.durum,
        user_id=kisi.id,
        istek=istek,
        dogrulama=dogrulama,
        aciklama=None if onay else gerekce,
    )
    # İtiraz metni denetim izine yazılmaz (kişisel veri olabilir); olay zincirinde durur.
    await audit.log(
        db,
        "ik_belge",
        "onayla" if onay else "itiraz",
        entity_id=b.id,
        new_value={"gonderim_id": b.gonderim_id, "dogrulama": dogrulama},
        user_id=kisi.id,
        ip=istek.ip,
    )


async def durum_sayilari(
    db: AsyncSession, gonderim_idleri: Sequence[int]
) -> dict[int, dict[str, int]]:
    sonuc: dict[int, dict[str, int]] = {i: {} for i in gonderim_idleri}
    if not gonderim_idleri:
        return sonuc
    satirlar = await db.execute(
        select(IkBelge.gonderim_id, IkBelge.durum, func.count())
        .where(IkBelge.gonderim_id.in_(gonderim_idleri))
        .group_by(IkBelge.gonderim_id, IkBelge.durum)
    )
    for gid, durum, adet in satirlar:
        sonuc[gid][durum] = adet
    return sonuc
