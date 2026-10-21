"""`test-verisi-temizle` gerçek ticari kayıtlara DOKUNMAMALI.

Komut KURULUM.md kontrol listesinde ve sunucuda çalıştırılıyor. İlk sürümde
`delete from quotes` / `orders` / `subscriptions` / `rma_cases` / `payments`
KOŞULSUZDU — "nasıl olsa gerçek kayıt yok" varsayımıyla. Varsayım canlıya
çıkışla birlikte çöküyor: go-live'dan sonra komutu çalıştıran biri bütün
teklif, sipariş, abonelik, RMA ve tahsilatı silerdi.
"""

import pytest
from sqlalchemy import select

from app.models import Account, Quote, QuoteVersion
from app.yonetim import _test_verisi_temizle

pytestmark = pytest.mark.integration


class _Sarmal:
    """`db` fixture'ı context manager değil; komut `async with` bekliyor."""

    def __init__(self, oturum):
        self.oturum = oturum

    async def __aenter__(self):
        return self.oturum

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def komutu_bagla(db, monkeypatch):
    """Komutu testin oturumuna bağlar; kendi fabrikası GELİŞTİRME veritabanına
    bağlanırdı ve test canlı veriyi silerdi."""
    from app import yonetim

    monkeypatch.setattr(yonetim, "get_session_factory", lambda: lambda: _Sarmal(db))


async def _hesap(db, unvan: str) -> Account:
    h = Account(title=unvan, is_musteri=True)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


async def _teklif(db, musteri_id: int, no: str) -> Quote:
    t = Quote(quote_no=no, customer_id=musteri_id, status="TASLAK", title="Deneme")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def test_gercek_musterinin_teklifi_silinmez(db, seeded, komutu_bagla):
    """Asıl koruma bu: gerçek müşteriye bağlı teklif temizlikte kalmalı."""
    gercek = await _hesap(db, "AKÇADAĞ İNŞAAT A.Ş.")
    await _teklif(db, gercek.id, "TKF2026-00001")

    assert await _test_verisi_temizle(yaz=True) == 0
    assert len((await db.scalars(select(Quote))).all()) == 1


async def test_test_hesabinin_teklifi_silinir(db, seeded, komutu_bagla):
    test_hesap = await _hesap(db, "AJANTEST MUSTERI")
    await _teklif(db, test_hesap.id, "TKF2026-00002")

    assert await _test_verisi_temizle(yaz=True) == 0
    assert (await db.scalars(select(Quote))).all() == []


async def test_teklif_versiyonu_da_temizlenir(db, seeded, komutu_bagla):
    """Teklif silinirken versiyonu ortada kalmamalı."""
    test_hesap = await _hesap(db, "AJANTEST MUSTERI")
    t = await _teklif(db, test_hesap.id, "TKF2026-00003")
    db.add(QuoteVersion(quote_id=t.id, version_no=1, currency="TRY"))
    await db.commit()

    await _test_verisi_temizle(yaz=True)
    assert (await db.scalars(select(QuoteVersion))).all() == []
    assert (await db.scalars(select(Quote))).all() == []


async def test_karisik_durumda_yalniz_test_kaydi_gider(db, seeded, komutu_bagla):
    """Gerçek ve test kayıtları bir aradayken ayrım doğru yapılmalı."""
    gercek = await _hesap(db, "ZSR PATLAYICI SANAYİ A.Ş.")
    test_hesap = await _hesap(db, "AJANTEST MUSTERI")
    await _teklif(db, gercek.id, "TKF2026-00004")
    await _teklif(db, test_hesap.id, "TKF2026-00005")

    await _test_verisi_temizle(yaz=True)
    kalan = (await db.scalars(select(Quote))).all()
    assert [t.quote_no for t in kalan] == ["TKF2026-00004"]
