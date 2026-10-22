"""Kütük göçünün yükleme adımı (TS-172).

    uv run python -m app.migration.yukle_kutuk --kaynak <döküm dizini>            # önizleme
    uv run python -m app.migration.yukle_kutuk --kaynak <döküm dizini> --uygula   # yazar

`INSERT ... ON CONFLICT ON CONSTRAINT uq_svceq_kaynak DO NOTHING`: ikinci
koşu satır sayısını değiştirmez ve ekrandan yapılmış düzeltmeyi (seri no,
pasif, durum, müşteri bağı) EZMEZ — mevcut satıra hiç dokunulmaz. Core
INSERT ORM olayını tetiklemediği için anahtar kolonları (`brand_key`,
`model_key`, `serial_key`) hazırlama adımında aynı fonksiyonlarla doldurulur.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.migration import hazirla_kutuk
from app.migration.kaynak_kutuk import kutuk_satirlari
from app.migration.servis_kaynak import AdimSonucu, KaynakDizini, mevcut_refler
from app.models import ServiceEquipment
from app.services import audit
from app.services.teknik_servis.veri_kalitesi import hesap_esleyici

PARCA = 500


async def hazirla(db: AsyncSession, dizin: KaynakDizini) -> AdimSonucu:
    """Kaynağı okur, hazırlar ve kaçının zaten yüklü olduğunu sayar (yazmaz)."""
    sonuc = hazirla_kutuk.hazirla(kutuk_satirlari(dizin), await hesap_esleyici(db))
    var = await mevcut_refler(db, hazirla_kutuk.HEDEF_TABLO, hazirla_kutuk.KAYNAK_TABLO)
    sonuc.mevcut = sum(1 for r in sonuc.aktarilacak if r["source_ref"] in var)
    sonuc.yeni = len(sonuc.aktarilacak) - sonuc.mevcut
    return sonuc


async def yukle(db: AsyncSession, sonuc: AdimSonucu, *, user_id: int | None = None) -> AdimSonucu:
    """Hazırlanmış satırları yazar; `yeni` = gerçekten eklenen satır sayısı."""
    eklenen = 0
    for i in range(0, len(sonuc.aktarilacak), PARCA):
        parca = [
            {**r, "created_by": user_id, "updated_by": user_id}
            for r in sonuc.aktarilacak[i : i + PARCA]
        ]
        if not parca:
            continue
        stmt = (
            insert(ServiceEquipment.__table__)
            .values(parca)
            .on_conflict_do_nothing(constraint="uq_svceq_kaynak")
            .returning(ServiceEquipment.__table__.c.id)
        )
        eklenen += len((await db.execute(stmt)).all())
    sonuc.yeni = eklenen
    sonuc.mevcut = len(sonuc.aktarilacak) - eklenen
    await audit.log(
        db,
        "service_equipment",
        "goc.kutuk",
        new_value=sonuc.ozet(),
        user_id=user_id,
    )
    return sonuc


if __name__ == "__main__":
    import sys

    from app.migration.servis_uzlasma import komut_satiri

    sys.exit(komut_satiri(["--adim", "kutuk", *sys.argv[1:]]))
