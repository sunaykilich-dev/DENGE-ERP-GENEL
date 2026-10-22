"""Kiralama uyarıları (E06-17) ve kiralama raporları (E06-21).

Maddeler: TS-119 (D2-C), TS-195 (D3-D).

**Raporlar (TS-195)** kiralama router'ında, `servis_rapor.gor + kiralama.gor`
ile (mobilite `api/reports.py`'ye DOKUNULMAZ); Excel ek olarak
`servis_rapor.disaaktar`. Fiyat kolonu YOKTUR (K13).

- `depo_durumu`: depo × ürün × (HAZIR, REZERVE, SERBEST, KIRADA, KONTROLDE,
  HAZIR_DEGIL, KAYIP, ATOLYEDE). REZERVE = AKTİF tahsisin sevk edilmemiş
  kısmı (tahsis cihazı depodan çıkarmaz, HAZIR içinde kalır); SERBEST =
  HAZIR − REZERVE; KIRADA tahsisin kaynak deposuna yazılır (müşterideki adet).
  KAYIP/ATOLYEDE depo dışıdır ("Depo dışı" satırı).
- `geciken_iade`: liste ucunun `kpi=geciken` sorgusunun AYNISI (sayı =
  liste); müşterideki adet ve seri, kurulum/toplama aşama süresi zaman
  kaydından — kayıt yoksa "EKSIK" (tahmini süre yerine konmaz).
- `kontrolde_bekleme`: seri cihazlar envanter listesinin `durum=KONTROLDE`
  sorgusunun AYNISI; toplu ürünler depo bakiyesi + son KONTROLDE girişi.

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

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models import (
    Product,
    Rental,
    RentalAllocation,
    RentalAsset,
    RentalCatalogItem,
    RentalInventoryMovement,
    RentalItem,
    ServiceOrder,
    Warehouse,
)
from app.services import settings as ayar_svc
from app.services.teknik_servis import kiralama as kiralama_svc
from app.services.teknik_servis import kiralik_envanter as envanter_svc
from app.services.teknik_servis import uyarilar as ts_uyarilar
from app.services.teknik_servis import zaman as zaman_svc
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


# --- Raporlar (TS-195, E06-21) -----------------------------------------------------------

DEPO_SUTUNLARI = (
    "hazir",
    "rezerve",
    "serbest",
    "kirada",
    "kontrolde",
    "hazir_degil",
    "kayip",
    "atolyede",
)
_DURUM_SUTUNU = {
    "HAZIR": "hazir",
    "KONTROLDE": "kontrolde",
    "HAZIR_DEGIL": "hazir_degil",
    "KAYIP": "kayip",
    "ATOLYEDE": "atolyede",
}
ASAMA_TURLERI = ("KURULUM", "TOPLAMA")


async def depo_durumu(db: AsyncSession, user: User) -> dict[str, Any]:
    """Depo × ürün × durum adetleri (seri + toplu), kapsamlı (katalog birimi)."""
    hucre: dict[tuple[int | None, int], dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(DEPO_SUTUNLARI, 0)
    )
    for s in await envanter_svc.bakiye_tablosu(db, user):
        sutun = _DURUM_SUTUNU.get(s["durum"])
        if sutun is None:  # KIRADA tahsisten, HURDA envanter dışı
            continue
        depo = s["depo_id"] if s["durum"] in envanter_svc.DEPO_DURUMLARI else None
        hucre[(depo, s["product_id"])][sutun] += s["adet"]
    a = RentalAllocation
    tahsis = (
        select(
            a.from_warehouse_id,
            a.product_id,
            func.sum(a.qty - a.sevk_adet),
            func.sum(a.sevk_adet - a.iade_adet - a.kayip_adet),
        )
        .join(RentalCatalogItem, RentalCatalogItem.product_id == a.product_id)
        .join(Rental, Rental.id == a.rental_id)
        .where(a.durum == "AKTIF", Rental.is_deleted.is_(False))
        .group_by(a.from_warehouse_id, a.product_id)
    )
    tahsis = envanter_svc.katalog_kosulu(tahsis, user)
    for depo_id, product_id, rezerve, kirada in (await db.execute(tahsis)).all():
        h = hucre[(depo_id, product_id)]
        h["rezerve"] += int(rezerve or 0)
        h["kirada"] += int(kirada or 0)
    urun_idler = {p for _, p in hucre}
    depo_idler = {d for d, _ in hucre if d is not None}
    urunler = {
        u.id: u
        for u in (await db.scalars(select(Product).where(Product.id.in_(urun_idler or {0})))).all()
    }
    depolar = {
        d.id: d
        for d in (
            await db.scalars(select(Warehouse).where(Warehouse.id.in_(depo_idler or {0})))
        ).all()
    }
    satirlar: list[dict[str, Any]] = []
    toplamlar: dict[int | None, dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(DEPO_SUTUNLARI, 0)
    )
    for (depo_id, product_id), h in hucre.items():
        h["serbest"] = h["hazir"] - h["rezerve"]
        if not any(h[s] for s in DEPO_SUTUNLARI if s != "serbest"):
            continue
        urun = urunler.get(product_id)
        depo = depolar.get(depo_id) if depo_id is not None else None
        satirlar.append(
            {
                "depo_id": depo_id,
                "depo_adi": depo.name if depo else "Depo dışı",
                "product_id": product_id,
                "urun_kodu": urun.code if urun else None,
                "urun_adi": urun.name if urun else None,
                "seri_takipli": bool(urun and urun.identity_kind == "SERI_NO"),
                **h,
            }
        )
        for s in DEPO_SUTUNLARI:
            toplamlar[depo_id][s] += h[s]
    satirlar.sort(key=lambda r: (r["depo_id"] is None, r["depo_adi"] or "", r["urun_kodu"] or ""))
    return {
        "satirlar": satirlar,
        "depolar": [
            {
                "depo_id": d,
                "depo_adi": depolar[d].name if d is not None and d in depolar else "Depo dışı",
                **t,
            }
            for d, t in sorted(toplamlar.items(), key=lambda x: (x[0] is None, x[0] or 0))
        ],
    }


async def _asama_sureleri(db: AsyncSession, kiralama_idler: list[int]) -> dict[int, dict]:
    """Kiralama → {KURULUM|TOPLAMA: {so_no, dk, durum}} (zaman kaydının TEK özeti).

    İş yoksa `durum="IS_YOK"`; iş var ama süre kaydı eksikse `dk=None`,
    `durum="EKSIK"` — tahmini süre yerine konmaz.
    """
    if not kiralama_idler:
        return {}
    isler = (
        await db.execute(
            select(ServiceOrder.id, ServiceOrder.rental_id, ServiceOrder.tur, ServiceOrder.so_no)
            .where(
                ServiceOrder.rental_id.in_(kiralama_idler),
                ServiceOrder.tur.in_(ASAMA_TURLERI),
                ServiceOrder.is_deleted.is_(False),
                ServiceOrder.status != "IPTAL",
            )
            .order_by(ServiceOrder.id)
        )
    ).all()
    ozetler = await zaman_svc.sure_ozeti_toplu(db, [i[0] for i in isler])
    sonuc: dict[int, dict] = {
        k: {t: {"so_no": None, "dk": None, "durum": "IS_YOK"} for t in ASAMA_TURLERI}
        for k in kiralama_idler
    }
    for so_id, kiralama_id, tur, so_no in isler:
        o = ozetler.get(so_id)
        eksik = o is None or o.kisi_saat_dk is None or o.sure_eksik
        sonuc[kiralama_id][tur] = {
            "so_no": so_no,
            "dk": None if eksik else o.kisi_saat_dk,
            "durum": "EKSIK" if eksik else o.sure_durumu,
        }
    return sonuc


async def geciken_iade(db: AsyncSession, user: User, clock: Clock) -> list[dict[str, Any]]:
    """Geciken iadeler: kiralama listesinin `kpi=geciken` sorgusu (sayı = liste)."""
    bugun = yerel_bugun(clock)
    stmt = kiralama_svc.liste_sorgusu(
        user, kiralama_svc.KiralamaSuzgeci(kpi="geciken"), bugun=bugun
    )
    kayitlar = (await db.execute(stmt)).all()
    idler = [k.id for k, _ in kayitlar]
    disarida: dict[int, int] = defaultdict(int)
    seriler: dict[int, list[str]] = defaultdict(list)
    if idler:
        a = RentalAllocation
        for rental_id, adet, seri in (
            await db.execute(
                select(a.rental_id, a.sevk_adet - a.iade_adet - a.kayip_adet, RentalAsset.serial_no)
                .outerjoin(RentalAsset, RentalAsset.id == a.asset_id)
                .where(a.rental_id.in_(idler), a.durum == "AKTIF")
                .order_by(a.id)
            )
        ).all():
            if adet and adet > 0:
                disarida[rental_id] += int(adet)
                if seri:
                    seriler[rental_id].append(seri)
    sureler = await _asama_sureleri(db, idler)
    return [
        {
            "id": k.id,
            "rental_no": k.rental_no,
            "birim": k.birim,
            "musteri": unvan,
            "proje_adi": k.proje_adi,
            "bitis": k.bitis,
            "gecikme_gun": (bugun - k.bitis).days,
            "status": k.status,
            "musteride_adet": disarida.get(k.id, 0),
            "seriler": seriler.get(k.id, []),
            "asama_sureleri": sureler.get(k.id, {}),
        }
        for k, unvan in kayitlar
    ]


async def kontrolde_bekleme(db: AsyncSession, user: User, clock: Clock) -> dict[str, Any]:
    """KONTROLDE bekleyenler: seri cihaz satırları (envanter listesiyle aynı sorgu)
    ve toplu ürün bakiyeleri (son KONTROLDE girişinden gün)."""
    an = clock.now()
    esik = await kontrol_esigi(db)
    seri_stmt = envanter_svc.envanter_sorgusu(
        user, envanter_svc.EnvanterSuzgeci(durum="KONTROLDE"), an=an, uzun_gun=esik
    )
    seri_kayitlar = (await db.execute(seri_stmt)).all()
    gunler = await envanter_svc.kontrolde_gun(db, [c.id for c, *_ in seri_kayitlar], an)
    girisler = dict(
        (
            await db.execute(
                select(RentalInventoryMovement.asset_id, func.max(RentalInventoryMovement.at))
                .where(
                    RentalInventoryMovement.asset_id.in_([c.id for c, *_ in seri_kayitlar] or [0]),
                    RentalInventoryMovement.to_durum == "KONTROLDE",
                )
                .group_by(RentalInventoryMovement.asset_id)
            )
        ).all()
    )
    seri = [
        {
            "kiralik_id": c.id,
            "urun_kodu": kod,
            "urun_adi": ad,
            "serial_no": c.serial_no,
            "birim": c.birim,
            "depo_id": c.warehouse_id,
            "depo_adi": depo,
            "giris_at": girisler.get(c.id),
            "bekleme_gun": gunler.get(c.id),
            "uzun": (gunler.get(c.id) or 0) > esik,
        }
        for c, kod, ad, depo in seri_kayitlar
    ]
    toplu = []
    m = RentalInventoryMovement
    for s in await envanter_svc.bakiye_tablosu(db, user):
        if s["seri_takipli"] or s["durum"] != "KONTROLDE" or s["adet"] <= 0:
            continue
        son = await db.scalar(
            select(func.max(m.at)).where(
                m.asset_id.is_(None),
                m.product_id == s["product_id"],
                m.to_warehouse_id == s["depo_id"],
                m.to_durum == "KONTROLDE",
            )
        )
        gun = max((an - son).days, 0) if son is not None else None
        toplu.append(
            {
                "product_id": s["product_id"],
                "urun_kodu": s["urun_kodu"],
                "urun_adi": s["urun_adi"],
                "depo_id": s["depo_id"],
                "depo_adi": s["depo_adi"],
                "adet": s["adet"],
                "son_giris_at": son,
                "bekleme_gun": gun,
                "uzun": (gun or 0) > esik,
            }
        )
    return {"esik_gun": esik, "seri": seri, "toplu": toplu}


ts_uyarilar.kaydet("kiralama", "kiralama.gor", uyarilar)
