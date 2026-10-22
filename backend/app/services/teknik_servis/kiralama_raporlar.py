"""Kiralama uyarıları (E06-17). Raporlar (E06-21) Dalga 3'te (D3-D, TS-195).

Maddeler: TS-119. D2-C.

Uyarılar SAKLANMAZ, hesaplanır (K10, canlı desen) ve izne tabidir
(`kiralama.gor`). Sayı bir sızıntıdır: her uyarı liste ucunun AYNI
sorgusundan (`kiralama.liste_sorgusu`, `kiralik_envanter.envanter_sorgusu`)
ve AYNI kapsamla sayılır; uyarıya tıklayınca açılan listenin toplamı uyarının
adedine eşittir. Başka birimin kaydı sayıya girmez.

- `kiralama.geciken_iade` (kritik): iade günü geçmiş, cihazı müşteride;
  `/kiralamalar?kpi=geciken`.
- `kiralama.eksik_tahsis`: 3 gün içinde başlayacak, tahsisi eksik;
  `/kiralamalar?kpi=eksik_tahsis`.
- `kiralama.uzun_kontrol`: `kiralama_kontrol_uyari_gun`'den uzun KONTROLDE (seri);
  `/kiralik-envanter?durum=KONTROLDE&uzun=1`.
- `kiralama.musaitlik_acigi`: PLANLANDI kiralamada müsaitlik negatif;
  `/kiralamalar?durum=PLANLANDI`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models import RentalItem
from app.services import settings as ayar_svc
from app.services.teknik_servis import kiralama as kiralama_svc
from app.services.teknik_servis import kiralik_envanter as envanter_svc
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis.kiralama_tahsis import musaitlik
from app.services.teknik_servis.yerel_zaman import yerel_bugun
from app.services.uyarilar import Uyari

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.clock import Clock
    from app.models import User

KONTROL_AYARI = "kiralama_kontrol_uyari_gun"
MUSAITLIK_TARAMA_UST_SINIR = 200


async def kontrol_esigi(db: AsyncSession) -> int:
    try:
        return int(await ayar_svc.get(db, KONTROL_AYARI))
    except (KeyError, TypeError, ValueError):
        return 7


async def musaitlik_acigi_olanlar(db: AsyncSession, user: User, clock: Clock) -> list[int]:
    """PLANLANDI kiralamalardan, kendisi hariç müsaitliği kalem adedini
    karşılamayanlar (kapsamlı)."""
    bugun = yerel_bugun(clock)
    stmt = kiralama_svc.liste_sorgusu(
        user, kiralama_svc.KiralamaSuzgeci(durum="PLANLANDI"), bugun=bugun
    ).limit(MUSAITLIK_TARAMA_UST_SINIR)
    acik: list[int] = []
    for kiralama, _ in (await db.execute(stmt)).all():
        kalemler = (
            await db.scalars(select(RentalItem).where(RentalItem.rental_id == kiralama.id))
        ).all()
        for k in kalemler:
            m = await musaitlik(
                db, k.product_id, kiralama.baslangic, kiralama.bitis, haric_rental_id=kiralama.id
            )
            if m["musait"] < k.qty:
                acik.append(kiralama.id)
                break
    return acik


async def uyarilar(db: AsyncSession, user: User, clock: Clock) -> list[Uyari]:
    """Geciken iade, eksik tahsis, uzun kontrol, müsaitlik açığı (birim kapsamlı)."""
    bugun = yerel_bugun(clock)
    geciken = await kiralama_svc.say(
        db,
        kiralama_svc.liste_sorgusu(user, kiralama_svc.KiralamaSuzgeci(kpi="geciken"), bugun=bugun),
    )
    eksik = await kiralama_svc.say(
        db,
        kiralama_svc.liste_sorgusu(
            user, kiralama_svc.KiralamaSuzgeci(kpi="eksik_tahsis"), bugun=bugun
        ),
    )
    esik = await kontrol_esigi(db)
    uzun = await kiralama_svc.say(
        db,
        envanter_svc.envanter_sorgusu(
            user,
            envanter_svc.EnvanterSuzgeci(durum="KONTROLDE", uzun=True),
            an=clock.now(),
            uzun_gun=esik,
        ),
    )
    acik = len(await musaitlik_acigi_olanlar(db, user, clock))
    return [
        Uyari(
            kod="kiralama.geciken_iade",
            baslik="Geciken kiralama iadesi",
            adet=geciken,
            yol="/kiralamalar?kpi=geciken",
            onem="kritik",
            aciklama="İade günü geçmiş ve cihazı hâlâ müşteride olan kiralamalar",
        ),
        Uyari(
            kod="kiralama.eksik_tahsis",
            baslik="Tahsisi eksik kiralama",
            adet=eksik,
            yol="/kiralamalar?kpi=eksik_tahsis",
            onem="uyari",
            aciklama=(
                f"{kiralama_svc.EKSIK_TAHSIS_GUN} gün içinde başlayacak, tahsisi tamamlanmamış"
            ),
        ),
        Uyari(
            kod="kiralama.uzun_kontrol",
            baslik="Uzun süredir kontrolde bekleyen kiralık cihaz",
            adet=uzun,
            yol="/kiralik-envanter?durum=KONTROLDE&uzun=1",
            onem="uyari",
            aciklama=f"{esik} günden uzun süredir dönüş kontrolü bekleyen cihazlar",
        ),
        Uyari(
            kod="kiralama.musaitlik_acigi",
            baslik="Müsaitlik açığı olan planlı kiralama",
            adet=acik,
            yol="/kiralamalar?durum=PLANLANDI",
            onem="uyari",
            aciklama="Planlı kiralamanın tarihlerinde yeterli kiralık envanter görünmüyor",
        ),
    ]


ts_uyarilar.kaydet("kiralama", "kiralama.gor", uyarilar)
