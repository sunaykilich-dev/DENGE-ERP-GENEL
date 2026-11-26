"""Servis e-posta bildirimi: kuyruğa alma, gönderim ve saklama (E10-06, TS-200).

Doldurdu: D3-F (iskelet D3-S). Tablolar: `service_notification_prefs`,
`service_mail_outbox` (`d3a000000002`).

**Neden giden kutusu (outbox) ve neden worker:** SLA aşımı 5 dakikalık
üretim görevinde (`uyari_uretimi`) bulunur; e-postayı aynı anda göndermek SMTP
yavaşken/çökükken bildirim üretimini de durdururdu. Satır önce kutuya yazılır
(tekillik şemada: `uq_smo_anlik`, `uq_smo_ozet`), gönderim ayrı adımdır. Worker
kaç tur koşarsa koşsun aynı bildirim aynı kişiye BİR kez gider (kabul 2).

**Alıcı listesi saklanmaz** (E10 K4): alıcı gönderim anında hesaplanır —
`servis.gor` izni, giriş açık, tercihi açık, e-postası dolu ve bildirimin işi
kullanıcının KAPSAMINDA (`kapsam.kapsam_isler`; liste ve sayılarla aynı
fonksiyon, "sayı = sızıntı"). Böylece birim değişikliği hemen etkili olur.

**Kurallar (E10-06 kabulü):**
- `servis_eposta_acik=false` → hiçbir satır üretilmez (R1'de kapalı açılır).
- SMTP tanımsızken (`mail.yapilandirildi_mi`) kutudaki HİÇBİR satıra
  dokunulmaz: `deneme` artmaz, durum BEKLIYOR kalır, worker hata değil BİLGİ
  satırı yazar (kabul 1).
- Hata: `deneme+1`, `son_hata` yalnız sınıflandırma + istisna sınıf adı +
  sunucu:port — SMTP parolası/kullanıcı adı/istisna metni ASLA (kabul 4).
  `servis_eposta_deneme`'ye ulaşınca BASARISIZ (kabul 3).
- Gövdede iş no, birim, müşteri unvanı, öncelik, hedef, durum ve ERP
  bağlantısı var; fiyat/tutar/maliyet ve iletişim telefonu YOK (kabul 5).
- `anlik_eposta=false` kullanıcıya satır oluşmaz; e-postası boş kullanıcı
  kuyruğa alınmaz, görev özetinde "e-postası olmayan alıcı" olarak sayılır
  (kabul 6).
- GERIYE_DONUK (göç geri doldurması) SLA damgalı işe e-posta YOK.
- Gönderilmeden önce bildirimi kapanan ANLIK satır gönderilmez, silinir
  (artık doğru değil); pasifleşen kullanıcının bekleyen satırı silinir.

**KVKK / saklama:** `alici` kişisel veridir. GONDERILDI/BASARISIZ satırlar
`servis_uyari_saklama_gun` (varsayılan 90) günden eskiyse silinir; pasif
(ayrılmış) kullanıcıların kutusu her turda temizlenir (anonimleştirilen
personelin adresi kutuda kalmasın).

Saat yalnız `Clock`/`yerel_zaman`. `kuyruga_al` ve `temizle` flush yapar,
commit YAPMAZ; `gonder_bekleyenler` her gönderimden sonra COMMIT eder —
gönderim geri alınamaz bir yan etkidir, sonraki satırda çöken bir tur
gönderilmiş satırı BEKLIYOR'a geri çevirip ikinci kez göndermemeli.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_config
from app.models import (
    ServiceAlert,
    ServiceMailOutbox,
    ServiceNotificationPref,
    ServiceOrder,
    User,
)
from app.models.teknik_servis import EPOSTA_ANLIK_KODLAR
from app.permissions import BIRIMLER
from app.services import mail
from app.services import settings as ayar_svc
from app.services.teknik_servis import is_emirleri, kapsam, panel
from app.services.teknik_servis.yerel_zaman import yerel_an, yerel_bugun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock

logger = logging.getLogger("denge.worker")

KOD_ADLARI: dict[str, str] = {
    "SLA_ASILDI": "SLA çözüm hedefi aşıldı",
    "MUDAHALE_ASILDI": "Müdahale hedefi aşıldı",
    "TAYIN_GECIKTI": "Tayin süresi aşıldı",
}
# Günlük özetteki sayaçlar (panel KPI kaydı; sayı = liste, kapsamlı).
OZET_SAYACLARI: tuple[tuple[str, str], ...] = (
    ("sla_asildi", "SLA aşıldı"),
    ("sla_riskte", "SLA riskte"),
    ("mudahale_asildi", "Müdahale gecikti"),
    ("bekleme_bitis_gecti", "Beklenen bitişi geçmiş bekleme"),
    ("vadesi_gecen_bakim", "Vadesi geçen bakım"),
)
OZET_LISTE_SINIRI = 20
TUR_BASINA_GONDERIM = 200


# --- Yardımcılar ------------------------------------------------------------------------


def _zaman(an: datetime | None) -> str:
    return yerel_an(an).strftime("%d.%m.%Y %H:%M") if an is not None else "—"


def _baglanti(yol: str) -> str:
    return get_config().public_base_url.rstrip("/") + yol


def _ozet_saati(deger: Any) -> time:
    try:
        saat, dakika = str(deger or "07:30").split(":", 1)
        return time(int(saat), int(dakika))
    except (ValueError, TypeError):
        return time(7, 30)


def _alici_mi(user: User) -> bool:
    """E-posta alabilecek kullanıcı: girişi açık ve `servis.gor` sahibi."""
    return user.giris_yapabilir_mi() and user.has("servis.gor")


def _eposta(user: User) -> str | None:
    deger = (user.email or "").strip()
    return deger or None


def is_satiri(so: ServiceOrder, musteri: str | None, *, hedef: datetime | None) -> list[str]:
    """Gövdedeki iş bilgisi. Fiyat/maliyet ve iletişim telefonu bilinçli olarak YOK."""
    return [
        f"İş no: {so.so_no}",
        f"Birim: {BIRIMLER.get(so.birim, so.birim)}",
        f"Müşteri: {musteri or so.customer_name_raw or '—'}",
        f"Öncelik: {so.oncelik}",
        f"Hedef: {_zaman(hedef)}",
        f"Durum: {so.status}",
        f"Bağlantı: {_baglanti(f'/servis-isleri/{so.id}')}",
    ]


_ALT_BILGI = (
    "\n--\nBu e-postayı Denge ERP servis bildirim tercihleriniz nedeniyle aldınız. "
    "Kullanıcı menüsü → Bildirim tercihleri'nden kapatabilirsiniz."
)


def anlik_icerik(kod: str, so: ServiceOrder, musteri: str | None) -> tuple[str, str]:
    """ANLIK e-postanın konu ve gövdesi (kişiye özel bilgi içermez)."""
    hedef = so.mudahale_hedef_at if kod == "MUDAHALE_ASILDI" else so.cozum_hedef_at
    konu = f"[Denge ERP] {KOD_ADLARI.get(kod, kod)}: {so.so_no}"[:200]
    govde = "\n".join(
        [f"SLA bildirimi: {KOD_ADLARI.get(kod, kod)}", "", *is_satiri(so, musteri, hedef=hedef)]
    )
    return konu, govde + _ALT_BILGI


async def _musteriler(db: AsyncSession, sos: list[ServiceOrder]) -> dict[int, str]:
    ozet = await is_emirleri.musteri_ozetleri(db, {s.customer_id for s in sos if s.customer_id})
    return {i: o["title"] for i, o in ozet.items()}


async def ozet_icerik(db: AsyncSession, user: User, clock: Clock, gun: date) -> tuple[str, str]:
    """Günlük özetin konu ve gövdesi — kullanıcının KAPSAMIYLA hesaplanır."""
    satirlar = [f"Servis günlük özeti — {gun.strftime('%d.%m.%Y')}", ""]
    for kod, ad in OZET_SAYACLARI:
        satirlar.append(f"{ad}: {await panel.kpi_sayisi(db, kod, user, clock)}")
    stmt = (
        select(ServiceOrder)
        .where(
            ServiceOrder.id.in_(panel.kapsamli_sorgu(panel.kpi_suzgeci("sla_asildi"), user, clock))
        )
        .order_by(ServiceOrder.cozum_hedef_at, ServiceOrder.id)
        .limit(OZET_LISTE_SINIRI)
    )
    sos = list((await db.scalars(stmt)).all())
    if sos:
        musteriler = await _musteriler(db, sos)
        satirlar += ["", f"SLA'sı aşılmış işler (ilk {OZET_LISTE_SINIRI}):"]
        for so in sos:
            satirlar += [
                "",
                *is_satiri(so, musteriler.get(so.customer_id), hedef=so.cozum_hedef_at),
            ]
    yol = (
        "/operasyon?kpi=sla_asildi"
        if user.has("operasyon.gor")
        else "/servis-isleri?kpi=sla_asildi"
    )
    satirlar += ["", f"Tüm liste: {_baglanti(yol)}"]
    konu = f"[Denge ERP] Servis günlük özeti {gun.strftime('%d.%m.%Y')}"
    return konu, "\n".join(satirlar) + _ALT_BILGI


# --- Kuyruğa alma -----------------------------------------------------------------------


async def _tercihli_kullanicilar(db: AsyncSession) -> list[tuple[User, ServiceNotificationPref]]:
    return [
        (u, p)
        for u, p in (
            await db.execute(
                select(User, ServiceNotificationPref)
                .join(ServiceNotificationPref, ServiceNotificationPref.user_id == User.id)
                .where(
                    or_(
                        ServiceNotificationPref.anlik_eposta.is_(True),
                        ServiceNotificationPref.gunluk_ozet.is_(True),
                    ),
                    User.is_active.is_(True),
                )
                .order_by(User.id)
            )
        ).all()
    ]


def _anlik_bildirim_sorgusu():
    """Açık, e-posta üreten kodlu bildirimler (silinmemiş, GERIYE_DONUK olmayan iş)."""
    return (
        select(ServiceAlert.id, ServiceAlert.kod, ServiceAlert.service_order_id)
        .join(ServiceOrder, ServiceOrder.id == ServiceAlert.service_order_id)
        .where(
            ServiceAlert.kod.in_(EPOSTA_ANLIK_KODLAR),
            ServiceAlert.kapanis_at.is_(None),
            ServiceOrder.is_deleted.is_(False),
            ServiceOrder.sla_kaynak.is_distinct_from("GERIYE_DONUK"),
        )
    )


async def kuyruga_al(db: AsyncSession, clock: Clock) -> dict[str, Any]:
    """ANLIK ve GUNLUK_OZET satırlarını üretir (idempotent; ON CONFLICT DO NOTHING)."""
    if not await ayar_svc.get(db, "servis_eposta_acik"):
        return {"kapali": True}
    simdi = clock.now()
    bugun = yerel_bugun(clock)
    ozet_vakti = yerel_an(simdi).time() >= _ozet_saati(
        await ayar_svc.get(db, "servis_gunluk_ozet_saati")
    )
    sonuc = {"anlik": 0, "ozet": 0, "eposta_yok": 0}
    icerikler: dict[int, tuple[str, str]] = {}

    for user, tercih in await _tercihli_kullanicilar(db):
        if not _alici_mi(user):
            continue
        adres = _eposta(user)
        if adres is None:
            sonuc["eposta_yok"] += 1
            continue
        if tercih.anlik_eposta:
            gorunen = (
                await db.execute(
                    kapsam.kapsam_isler(
                        _anlik_bildirim_sorgusu(), user, ServiceAlert.service_order_id
                    )
                )
            ).all()
            eksik = [(a, k, s) for a, k, s in gorunen if a not in icerikler]
            if eksik:
                sos = {
                    so.id: so
                    for so in (
                        await db.scalars(
                            select(ServiceOrder).where(
                                ServiceOrder.id.in_({s for _, _, s in eksik})
                            )
                        )
                    ).all()
                }
                musteriler = await _musteriler(db, list(sos.values()))
                for alert_id, kod, so_id in eksik:
                    so = sos[so_id]
                    icerikler[alert_id] = anlik_icerik(kod, so, musteriler.get(so.customer_id))
            if gorunen:
                eklenen = await db.execute(
                    insert(ServiceMailOutbox)
                    .values(
                        [
                            {
                                "tur": "ANLIK",
                                "alert_id": alert_id,
                                "user_id": user.id,
                                "alici": adres,
                                "konu": icerikler[alert_id][0],
                                "govde": icerikler[alert_id][1],
                                "durum": "BEKLIYOR",
                                "deneme": 0,
                                "created_at": simdi,
                                "updated_at": simdi,
                            }
                            for alert_id, _, _ in gorunen
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=["alert_id", "user_id"],
                        index_where=ServiceMailOutbox.tur == "ANLIK",
                    )
                    .returning(ServiceMailOutbox.id)
                )
                sonuc["anlik"] += len(eklenen.all())
        if tercih.gunluk_ozet and ozet_vakti:
            var = await db.scalar(
                select(ServiceMailOutbox.id).where(
                    ServiceMailOutbox.tur == "GUNLUK_OZET",
                    ServiceMailOutbox.user_id == user.id,
                    ServiceMailOutbox.ozet_gunu == bugun,
                )
            )
            if var is None:
                konu, govde = await ozet_icerik(db, user, clock, bugun)
                eklenen = await db.execute(
                    insert(ServiceMailOutbox)
                    .values(
                        tur="GUNLUK_OZET",
                        user_id=user.id,
                        ozet_gunu=bugun,
                        alici=adres,
                        konu=konu[:200],
                        govde=govde,
                        durum="BEKLIYOR",
                        deneme=0,
                        created_at=simdi,
                        updated_at=simdi,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["user_id", "ozet_gunu"],
                        index_where=ServiceMailOutbox.tur == "GUNLUK_OZET",
                    )
                    .returning(ServiceMailOutbox.id)
                )
                sonuc["ozet"] += len(eklenen.all())
    await db.flush()
    return sonuc


# --- Gönderim ---------------------------------------------------------------------------


def hata_metni(exc: mail.MailKapali, ayarlar: dict) -> str:
    """`son_hata`: sınıflandırma + istisna sınıf adı + sunucu:port. Parola, kullanıcı
    adı ve istisna METNİ yazılmaz (kabul 4)."""
    neden = type(exc.__cause__).__name__ if exc.__cause__ is not None else "-"
    return f"{exc.sinif} {neden} {mail.sunucu_etiketi(ayarlar)}"[:300]


async def _gecersiz_mi(db: AsyncSession, satir: ServiceMailOutbox) -> bool:
    """Gönderim anında artık doğru olmayan satır: bildirim kapanmış/silinmiş ya da
    kullanıcı pasif/girişsiz/izinsiz."""
    user = await db.get(User, satir.user_id)
    if user is None or not _alici_mi(user):
        return True
    if satir.tur == "ANLIK":
        if satir.alert_id is None:
            return True
        acik = await db.scalar(
            select(ServiceAlert.id).where(
                ServiceAlert.id == satir.alert_id, ServiceAlert.kapanis_at.is_(None)
            )
        )
        return acik is None
    return False


async def gonder_bekleyenler(db: AsyncSession, clock: Clock) -> dict[str, Any]:
    """BEKLIYOR satırları gönderir. SMTP tanımsızsa hiçbir satıra DOKUNMAZ."""
    ayarlar = await ayar_svc.get_all(db)
    if not mail.yapilandirildi_mi(ayarlar):
        bekleyen = await db.scalar(
            select(func.count())
            .select_from(ServiceMailOutbox)
            .where(ServiceMailOutbox.durum == "BEKLIYOR")
        )
        return {"smtp_yok": True, "bekleyen": int(bekleyen or 0)}
    azami = int(ayarlar.get("servis_eposta_deneme") or 3)
    satirlar = list(
        (
            await db.scalars(
                select(ServiceMailOutbox)
                .where(ServiceMailOutbox.durum == "BEKLIYOR")
                .order_by(ServiceMailOutbox.created_at, ServiceMailOutbox.id)
                .limit(TUR_BASINA_GONDERIM)
            )
        ).all()
    )
    sonuc = {"gonderilen": 0, "hatali": 0, "basarisiz": 0, "dusurulen": 0}
    for satir in satirlar:
        if await _gecersiz_mi(db, satir):
            await db.delete(satir)
            await db.commit()
            sonuc["dusurulen"] += 1
            continue
        try:
            await asyncio.to_thread(
                mail.duz_metin_gonder,
                ayarlar,
                alici=satir.alici,
                konu=satir.konu,
                govde=satir.govde,
            )
        except mail.MailKapali as exc:
            satir.deneme = min(int(satir.deneme or 0) + 1, azami)
            satir.son_hata = hata_metni(exc, ayarlar)
            satir.updated_at = clock.now()
            if satir.deneme >= azami:
                satir.durum = "BASARISIZ"
                sonuc["basarisiz"] += 1
            else:
                sonuc["hatali"] += 1
        else:
            satir.durum = "GONDERILDI"
            satir.gonderildi_at = clock.now()
            satir.updated_at = satir.gonderildi_at
            sonuc["gonderilen"] += 1
        await db.commit()
    return sonuc


# --- Saklama (KVKK) ---------------------------------------------------------------------


async def temizle(db: AsyncSession, clock: Clock) -> int:
    """Eski sonuçlanmış satırları ve pasif kullanıcıların kutusunu siler."""
    gun = int(await ayar_svc.get(db, "servis_uyari_saklama_gun") or 90)
    sinir = clock.now() - timedelta(days=gun)
    eski = await db.execute(
        delete(ServiceMailOutbox)
        .where(
            ServiceMailOutbox.durum.in_(("GONDERILDI", "BASARISIZ")),
            ServiceMailOutbox.created_at < sinir,
        )
        .returning(ServiceMailOutbox.id)
    )
    pasif = await db.execute(
        delete(ServiceMailOutbox)
        .where(ServiceMailOutbox.user_id.in_(select(User.id).where(User.is_active.is_(False))))
        .returning(ServiceMailOutbox.id)
    )
    await db.flush()
    return len(eski.all()) + len(pasif.all())


# --- Worker görevi ----------------------------------------------------------------------


async def gorev(db: AsyncSession, clock: Clock) -> str:
    """Worker `servis-eposta` (5 dk): kuyruğa al → gönder → saklama. Log satırı döner.

    SMTP tanımsızken BİLGİ satırı döner (hata değil; kabul 1).
    """
    kuyruk = await kuyruga_al(db, clock)
    await db.commit()
    silinen = await temizle(db, clock)
    await db.commit()
    if kuyruk.get("kapali"):
        return f"servis e-postası kapalı (servis_eposta_acik=false); saklama silinen={silinen}"
    gonderim = await gonder_bekleyenler(db, clock)
    kuyruk_metni = (
        f"kuyruğa alınan anlık={kuyruk['anlik']} özet={kuyruk['ozet']} "
        f"e-postası olmayan alıcı={kuyruk['eposta_yok']}"
    )
    if gonderim.get("smtp_yok"):
        return (
            f"BİLGİ: SMTP tanımlı değil, gönderim bekliyor (bekleyen={gonderim['bekleyen']}); "
            f"{kuyruk_metni}; saklama silinen={silinen}"
        )
    return (
        f"{kuyruk_metni}; gönderilen={gonderim['gonderilen']} hatalı={gonderim['hatali']} "
        f"başarısız={gonderim['basarisiz']} düşürülen={gonderim['dusurulen']}; "
        f"saklama silinen={silinen}"
    )
