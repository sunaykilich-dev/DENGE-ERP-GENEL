"""Worker döngüsünün hata sonrası davranışı.

Sunucu yeniden başladığında veritabanı worker'dan birkaç saniye SONRA hazır
oluyor ve ilk tur "connection refused" ile düşüyor. Eskiden bir sonraki deneme
PERİYOT kadar sonraydı (6–24 saat): o günün uzlaştırması hiç koşmuyordu ve
kimse fark etmiyordu. 30 Eyl 2026'da gerçekten böyle oldu, log'dan görüldü.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app import worker


class _SabitSaat:
    def now(self) -> datetime:
        return datetime(2026, 9, 30, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_hata_sonrasi_periyot_kadar_beklenmez(monkeypatch):
    bekleme_sureleri: list[float] = []
    turlar = {"n": 0}

    async def sahte_bir_tur(gorev, clock):
        turlar["n"] += 1
        # İlk iki tur düşer, üçüncü tutar.
        return turlar["n"] > 2

    async def sahte_bekle(awaitable, timeout):
        awaitable.close()  # beklenmeyen coroutine uyarısı çıkmasın
        bekleme_sureleri.append(timeout)
        if len(bekleme_sureleri) >= 3:
            raise asyncio.CancelledError
        raise TimeoutError

    monkeypatch.setattr(worker, "_bir_tur", sahte_bir_tur)
    monkeypatch.setattr(asyncio, "wait_for", sahte_bekle)

    gorev = worker.Gorev("deneme", timedelta(hours=24), lambda db, c: None)
    with pytest.raises(asyncio.CancelledError):
        await worker._dongu(gorev, clock=_SabitSaat(), dur=asyncio.Event())

    gun = timedelta(hours=24).total_seconds()
    assert bekleme_sureleri[0] < gun, "ilk hata sonrası bir gün beklenmemeli"
    assert bekleme_sureleri[1] < gun, "ikinci hata sonrası da beklenmemeli"
    assert bekleme_sureleri[0] < bekleme_sureleri[1], "aralık artmalı"
    # Görev tutunca normal periyoda dönülür.
    assert bekleme_sureleri[2] == gun


@pytest.mark.asyncio
async def test_yeniden_deneme_periyodu_asmaz(monkeypatch):
    """Sık koşan bir görevi hata yüzünden daha SEYREK denemek anlamsız."""
    bekleme_sureleri: list[float] = []

    async def hep_dus(gorev, clock):
        return False

    async def sahte_bekle(awaitable, timeout):
        awaitable.close()
        bekleme_sureleri.append(timeout)
        if len(bekleme_sureleri) >= 4:
            raise asyncio.CancelledError
        raise TimeoutError

    monkeypatch.setattr(worker, "_bir_tur", hep_dus)
    monkeypatch.setattr(asyncio, "wait_for", sahte_bekle)

    gorev = worker.Gorev("sik", timedelta(seconds=5), lambda db, c: None)
    with pytest.raises(asyncio.CancelledError):
        await worker._dongu(gorev, clock=_SabitSaat(), dur=asyncio.Event())

    assert all(s <= 5 for s in bekleme_sureleri), bekleme_sureleri


@pytest.mark.asyncio
async def test_bir_tur_hatayi_yaymaz(monkeypatch):
    """Tek bir görevin patlaması worker'ı düşürmemeli."""

    async def patlayan(db, clock):
        raise RuntimeError("veritabanı yok")

    def sahte_fabrika():
        raise RuntimeError("bağlantı reddedildi")

    monkeypatch.setattr(worker, "get_session_factory", sahte_fabrika)
    gorev = worker.Gorev("patlayan", timedelta(hours=1), patlayan)
    assert await worker._bir_tur(gorev, clock=_SabitSaat()) is False
