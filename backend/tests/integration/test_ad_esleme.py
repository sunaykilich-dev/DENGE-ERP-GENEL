"""Eski ad bazlı kayıtların onaylı personel eşlemesi (TS-170, E13-08).

Kabul:
- öneri çıktısında her ayrı ad için kayıt sayısı ve öneri var; trgm yalnız öneri;
- verilmiş karar, öneri yeniden üretilince EZİLMEZ;
- İK kararı `ad_esleme` profiliyle; aynı dosya ikinci kez 0 satır;
- onay sonrası göç satırlarında `user_id` dolar, kaynak metin değişmez;
  onaysız ad "eşleşmedi" sayılır; komut iki kez çalışınca ikincisi hiçbir
  satırı değiştirmez.
"""

import io

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.clock import FakeClock
from app.migration import servis_ad_esleme, servis_uzlasma
from app.migration.servis_kaynak import KaynakDizini
from app.models import PersonnelNameMap, ServiceOrderAssignment, ServiceTimeEntry
from app.services import imports as ice
from app.services.imports.ad_esleme import SUTUNLAR, AdEslemeProfili
from app.services.teknik_servis import ad_esleme
from tests.migration.goc_ortami import FIXTURE, goc_ortami, kisi_ac

pytestmark = pytest.mark.integration


def _xlsx(satirlar: list[list]) -> bytes:
    wb = Workbook()
    wb.active.append([s.baslik for s in SUTUNLAR])
    for s in satirlar:
        wb.active.append(s)
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


async def _profil(db, icerik: bytes, kararlar=None, user_id=None):
    profil = AdEslemeProfili()
    okuma = ice.oku("ad.xlsx", icerik, profil)
    staged = [s.sozluk() for s in await profil.dogrula(db, okuma.satirlar)]
    sayac = await profil.yaz(
        db, staged, clock=FakeClock(), user_id=user_id, kararlar=kararlar or {}
    )
    await db.commit()
    return staged, sayac


async def test_oneri_uretimi_sayilar_ve_karar_korunur(seeded, tmp_path):
    db = seeded
    ort = await goc_ortami(db, ad_onayla=False)
    cikti = tmp_path / "oneriler.xlsx"
    sayac = await servis_ad_esleme.oner(db, KaynakDizini(FIXTURE), cikti)
    await db.commit()
    # atama: Ali, Bilinmeyen, Eski Atama; zaman: Ali, Bilinmeyen; oturum: Ali
    assert sayac["yeni"] == 6
    satirlar = {
        (m.kaynak_alan, m.normal_ad): m for m in (await db.scalars(select(PersonnelNameMap))).all()
    }
    zaman_ali = satirlar[(ad_esleme.ALAN_ZAMAN, ad_esleme.normal_ad("Ali Veli"))]
    assert zaman_ali.kayit_sayisi == 4 and zaman_ali.durum == "ONERI"  # 3 yazım tek satır
    assert zaman_ali.onerilen_user_id == ort.ali.id
    assert (
        satirlar[(ad_esleme.ALAN_ZAMAN, ad_esleme.normal_ad("Bilinmeyen Kişi"))].onerilen_user_id
        is None
    )

    ws = load_workbook(cikti).active
    basliklar = [h.value for h in ws[1]]
    assert basliklar == [s.baslik for s in SUTUNLAR]
    assert ws.max_row == 1 + len(satirlar)

    # İK kararı: Ali onay, Bilinmeyen eşleşmedi; boş karar atlanır.
    icerik = _xlsx(
        [
            [ad_esleme.ALAN_ZAMAN, "Ali Veli", None, None, ort.ali.id, None, "E", None, None],
            [
                ad_esleme.ALAN_ZAMAN,
                "Bilinmeyen Kişi",
                None,
                None,
                None,
                None,
                "ESLESMEDI",
                None,
                None,
            ],
            [ad_esleme.ALAN_ATAMA, "Eski Atama", None, None, None, None, "", None, None],
        ]
    )
    staged, sayac = await _profil(db, icerik)
    assert sayac["guncellendi"] == 2 and sayac["eklendi"] == 0
    await db.refresh(zaman_ali)
    assert zaman_ali.durum == "ONAYLANDI" and zaman_ali.onaylanan_user_id == ort.ali.id

    # Aynı dosya ikinci kez: değişiklik yok.
    _, sayac = await _profil(db, icerik)
    assert sayac["guncellendi"] == 0 and sayac["eklendi"] == 0
    # Öneri yeniden üretilince karar ezilmez.
    sayac = await servis_ad_esleme.oner(db, KaynakDizini(FIXTURE), None)
    await db.commit()
    assert sayac["karari_korunan"] == 2
    await db.refresh(zaman_ali)
    assert zaman_ali.durum == "ONAYLANDI"


async def test_karar_degisimi_cakisma_ve_hatali_hedef(seeded):
    db = seeded
    ort = await goc_ortami(db)  # Ali üç alanda onaylı
    baska = await kisi_ac(db, "Veli Ali", "veli.ali")
    await db.commit()
    icerik = _xlsx(
        [
            [ad_esleme.ALAN_ZAMAN, "Ali Veli", None, None, None, None, "E", baska.id, None],
            [ad_esleme.ALAN_ZAMAN, "Yeni Ad", None, None, None, None, "E", 999999, None],
            ["Uydurma.Alan", "X", None, None, None, None, "E", ort.ali.id, None],
        ]
    )
    staged, sayac = await _profil(db, icerik)
    assert staged[0]["cakisma"]["tip"] == "karar_degisiyor"
    assert "bulunamadı" in staged[1]["hatalar"][0]
    assert "tanınmıyor" in staged[2]["hatalar"][0]
    assert sayac["guncellendi"] == 0 and sayac["eklendi"] == 0


async def test_uygula_bos_kisileri_baglar_ve_idempotent(seeded):
    db = seeded
    ort = await goc_ortami(db)
    await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), uygula=True)
    await db.commit()
    bilinmeyen = await db.scalar(
        select(ServiceTimeEntry).where(ServiceTimeEntry.source_ref == "WorkOrderTimeLogs:803")
    )
    assert bilinmeyen.user_id is None

    # İK sonradan "Bilinmeyen Kişi"yi gerçek bir personele bağlar.
    kisi = await kisi_ac(db, "Bilge Yılmaz", "bilge")
    await db.commit()
    icerik = _xlsx(
        [
            [ad_esleme.ALAN_ZAMAN, "Bilinmeyen Kişi", None, None, None, None, "E", kisi.id, None],
            [ad_esleme.ALAN_ATAMA, "Bilinmeyen Kişi", None, None, None, None, "E", kisi.id, None],
        ]
    )
    await _profil(db, icerik)
    sayac = await ad_esleme.uygula(db, clock=FakeClock())
    await db.commit()
    assert sayac["baglanan"] == 1
    await db.refresh(bilinmeyen)
    assert bilinmeyen.user_id == kisi.id
    assert bilinmeyen.kaynak_personel_adi == "Bilinmeyen Kişi"  # ham metin korunur

    ikinci = await ad_esleme.uygula(db, clock=FakeClock())
    await db.commit()
    assert ikinci["baglanan"] == 0

    # Göç yeniden koşunca yeni onaylı adın eksik ataması eklenir (iş tekrar yazılmaz).
    await servis_uzlasma.kos(db, KaynakDizini(FIXTURE), adimlar=("servis",), uygula=True)
    await db.commit()
    atananlar = set(
        (
            await db.scalars(
                select(ServiceOrderAssignment.user_id).where(
                    ServiceOrderAssignment.removed_at.is_(None)
                )
            )
        ).all()
    )
    assert atananlar == {ort.ali.id, kisi.id}
