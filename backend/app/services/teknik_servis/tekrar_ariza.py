"""Tekrar arıza işareti ve kök neden teyidi (E10-04, TS-084).

Doldurdu: D2-G.

**Kural:** yeni işin aktif serilerinden (`seri_norm`, tek normalizasyon
fonksiyonu — tire ve baştaki sıfır korunur) HERHANGİ BİRİ, son
`servis_tekrar_ariza_gun` (30) gün içinde KAPATILMIŞ başka bir işte geçiyorsa
yeni iş `tekrar_ariza_aday=true` olur. Planlı bakım (PB) ne tetikler ne
tetiklenir: 17 cihazlık bakım turu arıza tekrarı değildir.

**Bağ:** iş henüz bağlı değilse en son kapanan eşleşen işe `TEKRAR_ARIZA`
olarak otomatik bağlanır. Kullanıcının elle kurduğu bağın (MUKERRER, DEVAM …)
ÜZERİNE YAZILMAZ; o durumda yalnız işaret konur. Eşleşen iş kullanıcının
kapsamı dışında olabilir (başka birim): bağ yine kurulur ama olay geçmişine
iş numarası YAZILMAZ ve detayda bağ maskelidir ("Kapsam dışı iş",
`is_emirleri.bagli_isler`). Numara sızdırmamak için olay metni geneldir.

**Teyit KAPATILDI'da** (K10): işaretli iş, kök neden teyidi
(`tekrar_ariza_teyit`) ve geçerli sonuçta arıza nedeni olmadan KAPATILAMAZ
(409). TAMAMLANDI'da teyit istenmez — teknisyen bloke edilmez.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import exists, select

from app.models import ServiceOrder, ServiceOrderSerial
from app.services import settings as ayarlar
from app.services.teknik_servis import gecmis, kancalar
from app.services.teknik_servis.kancalar import ServisHatasi

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock


class TekrarArizaHatasi(ServisHatasi):
    """Teyit / kök neden eksik → 409."""


async def adaylar(db: AsyncSession, so: ServiceOrder, clock: Clock) -> list[ServiceOrder]:
    """Son N günde kapanmış, aynı `seri_norm`'lu, PB olmayan işler (en yeni önce)."""
    if so.tur == "PB":
        return []
    normlar = sorted(
        {
            s
            for s in (
                await db.scalars(
                    select(ServiceOrderSerial.seri_norm).where(
                        ServiceOrderSerial.service_order_id == so.id,
                        ServiceOrderSerial.is_active.is_(True),
                    )
                )
            ).all()
            if s
        }
    )
    if not normlar:
        return []
    gun = int(await ayarlar.get(db, "servis_tekrar_ariza_gun") or 30)
    simdi = clock.now()
    return list(
        (
            await db.scalars(
                select(ServiceOrder)
                .where(
                    ServiceOrder.id != so.id,
                    ServiceOrder.is_deleted.is_(False),
                    ServiceOrder.tur != "PB",
                    ServiceOrder.status == "KAPATILDI",
                    ServiceOrder.closed_at.is_not(None),
                    ServiceOrder.closed_at >= simdi - timedelta(days=gun),
                    ServiceOrder.closed_at <= simdi,
                    exists().where(
                        ServiceOrderSerial.service_order_id == ServiceOrder.id,
                        ServiceOrderSerial.is_active.is_(True),
                        ServiceOrderSerial.seri_norm.in_(normlar),
                    ),
                )
                .order_by(ServiceOrder.closed_at.desc(), ServiceOrder.id.desc())
            )
        ).all()
    )


async def isaretle(db: AsyncSession, so: ServiceOrder, clock: Clock) -> None:
    """`is_olusturuldu` kancası: 30 gün içinde aynı `seri_norm` → `tekrar_ariza_aday`; PB
    hariç. Elle kurulmuş bağın üzerine yazmaz."""
    bulunan = await adaylar(db, so, clock)
    if not bulunan:
        return
    so.tekrar_ariza_aday = True
    bagla = so.iliskili_is_id is None
    hedef = bulunan[0]
    if bagla:
        so.iliskili_is_id = hedef.id
        so.iliski_turu = "TEKRAR_ARIZA"
    await db.flush()
    gun = int(await ayarlar.get(db, "servis_tekrar_ariza_gun") or 30)
    await gecmis.olay_yaz(
        db,
        so,
        "ILISKI",
        (
            f"Tekrar arıza adayı: son {gun} günde aynı seriyle kapanmış iş bulundu"
            + ("; otomatik bağlandı" if bagla else "; mevcut bağ korundu")
        ),
        user=None,
        clock=clock,
        # Kimlik/numara yazılmaz: eşleşen iş okuyucunun kapsamı dışında olabilir.
        veri={"tekrar_ariza_aday": True, "eslesen_sayisi": len(bulunan), "otomatik_bag": bagla},
    )
    if bagla:
        await gecmis.olay_yaz(
            db,
            hedef,
            "ILISKI",
            "Aynı seriyle yeni servis işi açıldı (tekrar arıza, otomatik bağ)",
            user=None,
            clock=clock,
            veri={"yon": "alt", "iliski_turu": "TEKRAR_ARIZA", "otomatik_bag": True},
        )


async def kapanis_dogrula(db: AsyncSession, so: ServiceOrder, hedef: str, kaynak: str) -> None:
    """`durum_dogrula` kancası: tekrar arıza adayı iş teyit + kök neden olmadan KAPATILAMAZ."""
    if hedef != "KAPATILDI" or not so.tekrar_ariza_aday:
        return
    if so.tekrar_ariza_teyit is None:
        raise TekrarArizaHatasi(
            "Tekrar arıza adayı işte kapatmadan önce kök neden teyidi girilmeli "
            "(aynı arıza / farklı arıza / kullanıcı hatası)"
        )
    from app.services.teknik_servis import sonuc

    gecerli = await sonuc.gecerli_sonuc(db, so)
    if gecerli is None or gecerli.ariza_nedeni_id is None:
        raise TekrarArizaHatasi(
            "Tekrar arıza adayı işte kapatmadan önce kök neden (arıza nedeni) seçin"
        )


# --- Kanca kayıtları (sla.damgala'dan SONRA; import sırası) ------------------------------
kancalar.kaydet("is_olusturuldu", isaretle)
kancalar.kaydet("durum_dogrula", kapanis_dogrula)
