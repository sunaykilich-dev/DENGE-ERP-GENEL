"""Personel izin talebi ve onay zinciri (KARARLAR 2026-11-20 §7).

- Personel kendi talebini girer; İK (`izin.yonet`) başkası adına girer.
- Zorunlu: tür, tarih aralığı, vekil (izinde yerine bakacak personel), izinde
  bulunacağı il, iletişim numarası.
- Onay zinciri org şemasından (`users.yonetici_id`): personelin yöneticisi
  (birim şefi) → onun yöneticisi (teknik müdür) → onunki (GMY). En çok üç
  basamak; zincir kısaysa olan kadarıyla. Yöneticisi yoksa talep alınmaz.
- Sırası gelen onaycıya ERP'de uyarı, e-posta yapılandırılmışsa düğmeli
  e-posta gider. Düğme tek kullanımlık bağlantıyla karar SAYFASINI açar;
  karar sayfadaki düğmeyle verilir (e-posta tarayıcısı bağlantıyı açarsa
  onay sayılmaz).
- Red herhangi bir basamakta talebi bitirir (gerekçe zorunlu).
- Son onaydan sonra talep ONAYLANDI; İK e-postasına (`ik_eposta`) ve talep
  sahibine bilgi; planlamada personelin müsaitliğine İZİN bloğu düşer.
- 24 saat (`izin_onay_sure_saat`) içinde karar verilmezse basamak SURE_ASIMI
  olur, talep sıradaki yöneticiye geçer; son basamaksa onaycının
  yöneticisine yeni basamak eklenir; o da yoksa İK'ya bildirilir ve beklenir.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import Clock
from app.config import get_config
from app.models import IzinOnayi, IzinTalebi, User
from app.models.izin import IZIN_TUR_ADLARI, IZIN_TURLERI
from app.services import audit
from app.services import settings as ayar_svc

logger = logging.getLogger(__name__)

AZAMI_BASAMAK = 3
YONETIM_IZNI = "izin.yonet"
DURUM_ADLARI = {
    "BEKLIYOR": "Onay bekliyor",
    "ONAYLANDI": "Onaylandı",
    "REDDEDILDI": "Reddedildi",
    "IPTAL": "İptal edildi",
}


class IzinHatasi(ValueError):
    """İş kuralı (409)."""


class IzinGirdiHatasi(ValueError):
    """Eksik/yanlış girdi (400)."""


class IzinYetkiHatasi(ValueError):
    """Yetki (403)."""


class IzinBulunamadi(ValueError):
    """404."""


@dataclass
class TalepGirdisi:
    tur: str
    baslangic: date
    bitis: date
    vekil_id: int | None
    izin_ili: str | None
    iletisim_tel: str | None
    aciklama: str | None = None
    personel_id: int | None = None


def _bos(x: str | None) -> str | None:
    return (x or "").strip() or None


def _telefon(deger: str | None) -> str:
    deger = _bos(deger)
    if not deger or len(re.sub(r"\D", "", deger)) < 10:
        raise IzinGirdiHatasi("İzindeyken ulaşılacak telefon numarası zorunlu (en az 10 hane)")
    return deger[:30]


async def zincir(db: AsyncSession, personel: User) -> list[User]:
    """Org şemasından onaycılar: yönetici → onun yöneticisi → … (en çok 3)."""
    sonuc: list[User] = []
    gorulen = {personel.id}
    kimlik = personel.yonetici_id
    while kimlik is not None and len(sonuc) < AZAMI_BASAMAK:
        if kimlik in gorulen:
            break
        u = await db.get(User, kimlik)
        if u is None:
            break
        gorulen.add(u.id)
        if u.is_active:
            sonuc.append(u)
        kimlik = u.yonetici_id
    return sonuc


def _yeni_token() -> str:
    return secrets.token_urlsafe(32)


def karar_adresi(token: str) -> str:
    return get_config().public_base_url.rstrip("/") + f"/izin-karar/{token}"


async def _gonder(
    db: AsyncSession, alici: str | None, konu: str, govde: str, html: str | None = None
) -> bool:
    """E-posta yapılandırılmamışsa ya da gönderilemezse sessizce geçer (ERP'de uyarı var)."""
    from app.services import mail

    if not alici:
        return False
    try:
        await mail.gonder(db, alici=alici, konu=konu, govde=govde, html=html)
        return True
    except mail.MailKapali:
        return False
    except Exception:  # noqa: BLE001 - bildirim hatası talebi bozmasın
        logger.warning("İzin e-postası gönderilemedi", exc_info=False)
        return False


def _ozet(t: IzinTalebi, personel: User, vekil: User | None) -> str:
    return (
        f"Personel: {personel.full_name}\n"
        f"Tür: {IZIN_TUR_ADLARI.get(t.tur, t.tur)}\n"
        f"Tarih: {t.baslangic:%d.%m.%Y} – {t.bitis:%d.%m.%Y} ({t.gun_sayisi} gün)\n"
        f"Vekil: {vekil.full_name if vekil else '-'}\n"
        f"İzinde bulunacağı il: {t.izin_ili}\n"
    )


async def _onayciya_bildir(db: AsyncSession, t: IzinTalebi, o: IzinOnayi) -> None:
    onayci = await db.get(User, o.onaylayici_id)
    personel = await db.get(User, t.personel_id)
    vekil = await db.get(User, t.vekil_id)
    if onayci is None or personel is None or not o.token:
        return
    adres = karar_adresi(o.token)
    ozet = _ozet(t, personel, vekil)
    govde = (
        f"Onayınızı bekleyen bir izin talebi var.\n\n{ozet}\n"
        f"Onaylamak ya da reddetmek için: {adres}\n"
        "ERP'de İnsan Kaynakları › İzin Talepleri › Onayımda ekranından da karar verebilirsiniz.\n"
    )
    e = html_lib.escape
    parcalar = (s.partition(": ") for s in ozet.strip().splitlines())
    satirlar = "".join(
        f"<tr><td style='padding:2px 8px;color:#555'>{e(a)}</td><td>{e(b)}</td></tr>"
        for a, _, b in parcalar
    )
    dugme = (
        "display:inline-block;padding:10px 18px;margin-right:8px;border-radius:6px;"
        "text-decoration:none;color:#fff;font-weight:600;"
    )
    html = (
        "<div style='font-family:sans-serif'>"
        "<p>Onayınızı bekleyen bir izin talebi var.</p>"
        f"<table>{satirlar}</table><p>"
        f"<a href='{e(adres)}?karar=ONAY' style='{dugme}background:#2e7d32'>Onayla</a>"
        f"<a href='{e(adres)}?karar=RED' style='{dugme}background:#c62828'>Reddet</a>"
        "</p><p style='color:#777;font-size:12px'>Düğme karar sayfasını açar; karar orada "
        "verilir. Bağlantı tek kullanımlıktır.</p></div>"
    )
    await _gonder(db, onayci.email, f"İzin onayı: {personel.full_name}", govde, html)


async def _sonuc_bildir(db: AsyncSession, t: IzinTalebi) -> None:
    personel = await db.get(User, t.personel_id)
    vekil = await db.get(User, t.vekil_id)
    if personel is None:
        return
    ozet = _ozet(t, personel, vekil)
    durum = DURUM_ADLARI.get(t.durum, t.durum)
    await _gonder(
        db, personel.email, f"İzin talebiniz: {durum}", f"İzin talebiniz {durum.lower()}.\n\n{ozet}"
    )
    if t.durum == "ONAYLANDI":
        ik = _bos(str(await ayar_svc.get(db, "ik_eposta") or ""))
        await _gonder(
            db,
            ik,
            f"Onaylanan izin: {personel.full_name}",
            f"Aşağıdaki izin talebi bütün onaylardan geçti.\n\n{ozet}İletişim: {t.iletisim_tel}\n",
        )


def _aktiflestir(o: IzinOnayi, simdi: datetime) -> None:
    o.durum = "BEKLIYOR"
    o.aktif_at = simdi
    o.token = _yeni_token()


async def olustur(
    db: AsyncSession, g: TalepGirdisi, *, aktor: User, clock: Clock, ip: str | None = None
) -> IzinTalebi:
    personel_id = g.personel_id or aktor.id
    if personel_id != aktor.id and not aktor.has(YONETIM_IZNI):
        raise IzinYetkiHatasi("Başkası adına izin talebi yalnız İK girer")
    personel = await db.get(User, personel_id)
    if personel is None or not personel.is_active:
        raise IzinGirdiHatasi("Personel bulunamadı")
    if g.tur not in IZIN_TURLERI:
        raise IzinGirdiHatasi(f"Bilinmeyen izin türü: {g.tur}")
    if g.bitis < g.baslangic:
        raise IzinGirdiHatasi("Bitiş tarihi başlangıçtan önce olamaz")
    if (g.bitis - g.baslangic).days > 120:
        raise IzinGirdiHatasi("Tek talep en çok 120 gün olabilir")
    if g.vekil_id is None:
        raise IzinGirdiHatasi("Yerinize bakacak vekil seçilmeli")
    if g.vekil_id == personel.id:
        raise IzinGirdiHatasi("Vekil talep sahibinin kendisi olamaz")
    vekil = await db.get(User, g.vekil_id)
    if vekil is None or not vekil.is_active:
        raise IzinGirdiHatasi("Vekil aktif bir personel olmalı")
    il = _bos(g.izin_ili)
    if not il:
        raise IzinGirdiHatasi("İzinde bulunacağınız il zorunlu")
    tel = _telefon(g.iletisim_tel)
    cakisan = await db.scalar(
        select(IzinTalebi.id).where(
            IzinTalebi.personel_id == personel.id,
            IzinTalebi.durum.in_(("BEKLIYOR", "ONAYLANDI")),
            IzinTalebi.baslangic <= g.bitis,
            IzinTalebi.bitis >= g.baslangic,
        )
    )
    if cakisan is not None:
        raise IzinHatasi("Bu tarihlerle çakışan bekleyen ya da onaylı bir izin talebi var")
    onaycilar = await zincir(db, personel)
    if not onaycilar:
        raise IzinHatasi(
            "Personelin yöneticisi tanımlı değil; onay zinciri kurulamıyor. "
            "İK'dan yönetici tanımını isteyin."
        )
    simdi = clock.now()
    t = IzinTalebi(
        personel_id=personel.id,
        tur=g.tur,
        baslangic=g.baslangic,
        bitis=g.bitis,
        gun_sayisi=(g.bitis - g.baslangic).days + 1,
        vekil_id=vekil.id,
        izin_ili=il[:60],
        iletisim_tel=tel,
        aciklama=_bos(g.aciklama),
        created_by=aktor.id,
    )
    for sira, u in enumerate(onaycilar, start=1):
        o = IzinOnayi(sira=sira, onaylayici_id=u.id)
        if sira == 1:
            _aktiflestir(o, simdi)
        t.onaylar.append(o)
    db.add(t)
    await db.flush()
    await audit.log(
        db,
        "izin_talepleri",
        "izin.talep",
        entity_id=t.id,
        new_value={"personel_id": personel.id, "gun": t.gun_sayisi, "basamak": len(onaycilar)},
        user_id=aktor.id,
        ip=ip,
    )
    await _onayciya_bildir(db, t, t.onaylar[0])
    return t


def bekleyen_basamak(t: IzinTalebi) -> IzinOnayi | None:
    return next((o for o in t.onaylar if o.durum == "BEKLIYOR"), None)


async def karar_ver(
    db: AsyncSession,
    o: IzinOnayi,
    onay: bool,
    *,
    aciklama: str | None,
    user: User | None,
    clock: Clock,
    ip: str | None = None,
) -> IzinTalebi:
    """`user` None = e-posta bağlantısı (token zaten onaycıya aittir)."""
    t = await db.get(IzinTalebi, o.talep_id, with_for_update=True)
    if t is None:
        raise IzinBulunamadi("İzin talebi bulunamadı")
    await db.refresh(o)
    if t.durum != "BEKLIYOR" or o.durum != "BEKLIYOR":
        raise IzinHatasi("Bu basamak için karar zaten verilmiş ya da talep kapanmış")
    if user is not None and user.id != o.onaylayici_id:
        raise IzinYetkiHatasi("Bu izin talebinin sıradaki onaycısı siz değilsiniz")
    aciklama = _bos(aciklama)
    if not onay and not aciklama:
        raise IzinGirdiHatasi("Red gerekçesi zorunlu")
    simdi = clock.now()
    o.durum = "ONAYLANDI" if onay else "REDDEDILDI"
    o.karar_at = simdi
    o.aciklama = aciklama[:500] if aciklama else None
    o.token = None
    sonraki: IzinOnayi | None = None
    if not onay:
        t.durum = "REDDEDILDI"
        t.sonuc_at = simdi
        for x in t.onaylar:
            if x.durum == "SIRADA":
                x.durum = "IPTAL"
    else:
        sonraki = next((x for x in t.onaylar if x.durum == "SIRADA"), None)
        if sonraki is not None:
            _aktiflestir(sonraki, simdi)
        else:
            t.durum = "ONAYLANDI"
            t.sonuc_at = simdi
    await db.flush()
    await audit.log(
        db,
        "izin_talepleri",
        "izin.onay" if onay else "izin.red",
        entity_id=t.id,
        new_value={"basamak": o.sira, "eposta": user is None},
        user_id=user.id if user is not None else o.onaylayici_id,
        ip=ip,
    )
    if sonraki is not None:
        await _onayciya_bildir(db, t, sonraki)
    if t.durum in ("ONAYLANDI", "REDDEDILDI"):
        if t.durum == "ONAYLANDI":
            await _musaitlige_yaz(db, t)
        await _sonuc_bildir(db, t)
    return t


async def _musaitlige_yaz(db: AsyncSession, t: IzinTalebi) -> None:
    """Planlamada personelin müsaitliğine İZİN bloğu; çakışan blok varsa atlanır."""
    from zoneinfo import ZoneInfo

    from app.models.servis_planlama import ServiceUnavailability

    tz = ZoneInfo("Europe/Istanbul")
    blok = ServiceUnavailability(
        user_id=t.personel_id,
        starts_at=datetime.combine(t.baslangic, time.min, tz),
        ends_at=datetime.combine(t.bitis + timedelta(days=1), time.min, tz),
        tur="IZIN",
        note=f"İzin talebi #{t.id}",
    )
    try:
        async with db.begin_nested():
            db.add(blok)
            await db.flush()
    except Exception:  # noqa: BLE001 - çakışan blok: planlamadaki kayıt korunur
        logger.info("İzin bloğu planlamaya yazılamadı (çakışma), talep %s", t.id)


async def iptal(
    db: AsyncSession, t: IzinTalebi, *, user: User, clock: Clock, ip: str | None = None
) -> IzinTalebi:
    if t.personel_id != user.id and not user.has(YONETIM_IZNI):
        raise IzinYetkiHatasi("Talebi yalnız sahibi ya da İK iptal eder")
    if t.durum != "BEKLIYOR":
        raise IzinHatasi("Yalnız onay bekleyen talep iptal edilir")
    t.durum = "IPTAL"
    t.sonuc_at = clock.now()
    for x in t.onaylar:
        if x.durum in ("SIRADA", "BEKLIYOR"):
            x.durum = "IPTAL"
            x.token = None
    t.updated_by = user.id
    await db.flush()
    await audit.log(db, "izin_talepleri", "izin.iptal", entity_id=t.id, user_id=user.id, ip=ip)
    return t


async def yukselt(db: AsyncSession, clock: Clock) -> str:
    """Worker: süresi dolan basamağı bir sonraki yöneticiye geçirir."""
    sure = int(await ayar_svc.get(db, "izin_onay_sure_saat"))
    simdi = clock.now()
    esik = simdi - timedelta(hours=sure)
    gecikmis = (
        await db.scalars(
            select(IzinOnayi)
            .join(IzinTalebi, IzinTalebi.id == IzinOnayi.talep_id)
            .where(
                IzinOnayi.durum == "BEKLIYOR",
                IzinOnayi.aktif_at <= esik,
                IzinTalebi.durum == "BEKLIYOR",
            )
            .with_for_update(of=IzinOnayi)
        )
    ).all()
    gecen = bekleyen = 0
    for o in gecikmis:
        t = await db.get(IzinTalebi, o.talep_id)
        if t is None:
            continue
        sonraki = next((x for x in t.onaylar if x.durum == "SIRADA"), None)
        if sonraki is None:
            onayci = await db.get(User, o.onaylayici_id)
            ust_id = onayci.yonetici_id if onayci is not None else None
            zincirde = {x.onaylayici_id for x in t.onaylar} | {t.personel_id}
            ust = await db.get(User, ust_id) if ust_id else None
            if ust is not None and ust.is_active and ust.id not in zincirde:
                sonraki = IzinOnayi(sira=max(x.sira for x in t.onaylar) + 1, onaylayici_id=ust.id)
                t.onaylar.append(sonraki)
        if sonraki is None:
            # Üst yönetici yok: basamak bekler, İK'ya bildirilir, süre yeniden başlar.
            o.aktif_at = simdi
            bekleyen += 1
            ik = _bos(str(await ayar_svc.get(db, "ik_eposta") or ""))
            await _gonder(
                db,
                ik,
                f"İzin talebi #{t.id} {sure} saattir onay bekliyor",
                f"İzin talebi #{t.id} için onaycı {sure} saat içinde karar vermedi ve "
                "üstünde yönetici tanımlı değil. Lütfen takip edin.\n",
            )
            continue
        o.durum = "SURE_ASIMI"
        o.karar_at = simdi
        o.token = None
        _aktiflestir(sonraki, simdi)
        await db.flush()
        await audit.log(
            db,
            "izin_talepleri",
            "izin.sure_asimi",
            entity_id=t.id,
            new_value={"basamak": o.sira, "sonraki": sonraki.sira},
        )
        await _onayciya_bildir(db, t, sonraki)
        gecen += 1
    await db.commit()
    return (
        f"izin yükseltme: {gecen} talep sonraki yöneticiye geçti, {bekleyen} talep İK'ya bildirildi"
    )


# --- Okuma ------------------------------------------------------------------------------


async def cikti(db: AsyncSession, t: IzinTalebi, *, tam: bool = True) -> dict[str, Any]:
    kimlikler = {t.personel_id, t.vekil_id} | {o.onaylayici_id for o in t.onaylar}
    adlar = dict(
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(kimlikler)))).all()
    )
    return {
        "id": t.id,
        "version": t.version,
        "personel_id": t.personel_id,
        "personel": adlar.get(t.personel_id),
        "tur": t.tur,
        "tur_adi": IZIN_TUR_ADLARI.get(t.tur, t.tur),
        "baslangic": t.baslangic,
        "bitis": t.bitis,
        "gun_sayisi": t.gun_sayisi,
        "vekil_id": t.vekil_id,
        "vekil": adlar.get(t.vekil_id),
        "izin_ili": t.izin_ili,
        "iletisim_tel": t.iletisim_tel if tam else None,
        "aciklama": t.aciklama,
        "durum": t.durum,
        "durum_adi": DURUM_ADLARI.get(t.durum, t.durum),
        "created_at": t.created_at,
        "sonuc_at": t.sonuc_at,
        "onaylar": [
            {
                "id": o.id,
                "sira": o.sira,
                "onaylayici_id": o.onaylayici_id,
                "onaylayici": adlar.get(o.onaylayici_id),
                "durum": o.durum,
                "aktif_at": o.aktif_at,
                "karar_at": o.karar_at,
                "aciklama": o.aciklama,
            }
            for o in t.onaylar
        ],
    }


async def benim(db: AsyncSession, user: User) -> list[IzinTalebi]:
    return list(
        (
            await db.scalars(
                select(IzinTalebi)
                .where(IzinTalebi.personel_id == user.id)
                .order_by(IzinTalebi.id.desc())
                .limit(200)
            )
        ).all()
    )


async def onayimda(db: AsyncSession, user: User, *, hepsi: bool = False) -> list[IzinTalebi]:
    """Sırası bende olanlar (`hepsi`: karar verdiklerim de)."""
    kosul = IzinOnayi.onaylayici_id == user.id
    if not hepsi:
        kosul = kosul & (IzinOnayi.durum == "BEKLIYOR")
    return list(
        (
            await db.scalars(
                select(IzinTalebi)
                .where(IzinTalebi.id.in_(select(IzinOnayi.talep_id).where(kosul)))
                .order_by(IzinTalebi.id.desc())
                .limit(300)
            )
        ).all()
    )


async def tumu(db: AsyncSession, *, durum: str | None = None) -> list[IzinTalebi]:
    stmt = select(IzinTalebi).order_by(IzinTalebi.id.desc()).limit(500)
    if durum:
        stmt = stmt.where(IzinTalebi.durum == durum)
    return list((await db.scalars(stmt)).all())


async def bekleyen_sayisi(db: AsyncSession, user: User) -> int:
    from sqlalchemy import func

    return int(
        await db.scalar(
            select(func.count())
            .select_from(IzinOnayi)
            .join(IzinTalebi, IzinTalebi.id == IzinOnayi.talep_id)
            .where(
                IzinOnayi.onaylayici_id == user.id,
                IzinOnayi.durum == "BEKLIYOR",
                IzinTalebi.durum == "BEKLIYOR",
            )
        )
        or 0
    )


async def token_ile(db: AsyncSession, token: str) -> IzinOnayi:
    o = await db.scalar(select(IzinOnayi).where(IzinOnayi.token == token)) if token else None
    if o is None:
        raise IzinBulunamadi("Bağlantı geçersiz ya da kullanılmış")
    return o


async def vekil_adaylari(db: AsyncSession) -> list[dict[str, Any]]:
    satirlar = await db.execute(
        select(User.id, User.full_name, User.unvan)
        .where(User.is_active.is_(True), or_(User.ayrilis_tarihi.is_(None)))
        .order_by(User.full_name)
    )
    return [{"id": i, "ad": a, "unvan": u} for i, a, u in satirlar.all()]
