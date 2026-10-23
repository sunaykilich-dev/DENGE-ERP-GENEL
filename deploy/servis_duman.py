"""Teknik servis duman testi — canlıya çıkış provasının servis adımı (TS-220).

Prova sunucusunda, api konteynerinin İÇİNDE koşar (cikis-provasi.sh çağırır):

    DENGE_PROVA=1 docker compose exec -T -e DENGE_PROVA=1 api python - < deploy/servis_duman.py

NEDEN: `dogrula.sh` tabloların okunabildiğini söyler ama yazma yolunu
denemez. Yükseltmeden sonra ilk servis işini gerçek kullanıcı açtığında
patlayan bir kanca (SLA damgası, numara serisi, olay kaydı) canlıda
öğrenilmemeli. Bu betik aynı yolu (`is_emirleri.olustur`) uygulamanın
kendi koduyla bir kez yürür.

KALICI DEĞİL ama CANLIDA ÇALIŞTIRILMAZ: her şey tek transaction'da yapılır
ve sonunda geri alınır; yalnız numara sequence'i bir ilerler (PostgreSQL
sequence'leri rollback olmaz) ve canlıda bir servis işi numarası boşa gider.
Bu yüzden `DENGE_PROVA=1` olmadan çalışmaz.

Çıktı: her denetim için bir `TAMAM`/`HATA` satırı; hata varsa çıkış kodu 1.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Uygulamanın kayıt noktaları (kancalar, router'lar) `app.main` içe
# aktarılınca kurulur; servis işi açılışı bu kancalara dayanır.
from app.main import app

BEKLENEN_ONEKLER = (
    "/api/teknik-servis",
    "/api/teknik-servis/planlama",
    "/api/teknik-servis/bakim",
    "/api/teknik-servis/atolye",
    "/api/teknik-servis/ekipman",
    "/api/teknik-servis/parca",
    "/api/teknik-servis/maliyet",
    "/api/teknik-servis/raporlar",
    "/api/teknik-servis/ana-veri",
    "/api/kiralama",
    "/api/egitim",
    "/api/personel",
)


def rota_denetimi() -> list[tuple[bool, str]]:
    """Her teknik servis modülünün router'ı uygulamaya bağlı mı.

    `app.routes` yerine OpenAPI şeması: FastAPI'nin yeni sürümlerinde
    `include_router` yolları düz listeye açmıyor; şema her sürümde tam yolu
    verir (üretimde /api/docs kapalı olsa da şema bellekte üretilebilir)."""
    yollar = list(app.openapi().get("paths", {}))
    sonuc = []
    for onek in BEKLENEN_ONEKLER:
        adet = sum(1 for y in yollar if y == onek or y.startswith(onek + "/"))
        sonuc.append((adet > 0, f"rota {onek}: {adet} uç"))
    return sonuc


async def yazma_denetimi(db) -> list[tuple[bool, str]]:
    """Bir arıza işi açar ve okur. Geri almak ÇAĞIRANIN işidir."""
    from sqlalchemy import func, select

    from app.clock import RealClock
    from app.models.account import Account
    from app.models.teknik_servis import ServiceOrder, ServiceOrderEvent
    from app.services.teknik_servis import is_emirleri

    sonuc: list[tuple[bool, str]] = []
    hesap_id = await db.scalar(
        select(Account.id).where(Account.is_musteri.is_(True)).order_by(Account.id).limit(1)
    )
    if hesap_id is None:
        # Boş prova veritabanı: geçici müşteri de aynı transaction'la geri alınır.
        hesap = Account(title="Duman Testi Geçici Müşteri", is_musteri=True)
        db.add(hesap)
        await db.flush()
        hesap_id = hesap.id
    girdi = is_emirleri.ServisIsiGirdisi(
        birim="GUVENLIK",
        tur="ARIZA",
        konu="Çıkış provası duman testi (geri alınır)",
        customer_id=hesap_id,
    )
    is_ = await is_emirleri.olustur(db, girdi, user=None, clock=RealClock())
    await db.flush()
    sonuc.append((bool(is_.so_no), f"servis işi açıldı: {is_.so_no} ({is_.status})"))
    okunan = await db.get(ServiceOrder, is_.id)
    sonuc.append((okunan is not None and okunan.birim == "GUVENLIK", "servis işi geri okundu"))
    olay = await db.scalar(
        select(func.count())
        .select_from(ServiceOrderEvent)
        .where(ServiceOrderEvent.service_order_id == is_.id)
    )
    sonuc.append((bool(olay), f"olay geçmişi yazıldı ({olay} olay)"))
    return sonuc


async def kos() -> int:
    from app.db import get_session_factory

    sonuc = rota_denetimi()
    async with get_session_factory()() as db:
        try:
            sonuc += await yazma_denetimi(db)
        except Exception as hata:  # noqa: BLE001 — her hata provada raporlanır
            sonuc.append((False, f"servis işi açılamadı: {type(hata).__name__}: {hata}"))
        finally:
            await db.rollback()
    sonuc.append((True, "transaction geri alındı (kalıcı kayıt yok)"))
    for tamam, metin in sonuc:
        print(f"  {'TAMAM' if tamam else 'HATA '}  {metin}")
    return 0 if all(t for t, _ in sonuc) else 1


def main() -> int:
    if os.environ.get("DENGE_PROVA") != "1":
        print("HATA: yalnız prova sunucusunda çalışır (DENGE_PROVA=1). Canlıda çalıştırmayın.")
        return 2
    return asyncio.run(kos())


if __name__ == "__main__":
    sys.exit(main())
