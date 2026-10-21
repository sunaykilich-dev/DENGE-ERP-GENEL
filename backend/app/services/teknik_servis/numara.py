"""Teknik servis belge numaraları (plan §1.6, KD-12).

Tek biçim: `ÖNEK-YYYYAA-NNNNNN` (ör. `SRV-202610-000123`). Sayı PostgreSQL
SEQUENCE'ten gelir ve yıl/ay başında SIFIRLANMAZ: eşzamanlı iki açılış
çakışmaz, göç numaralarıyla da karışmaz (tekillik ayrıca `uq_` ile korunur).
Canlıdaki `count()+1` / `max(id)+1` üreticilerine dokunulmaz.

Sequence'ler migration'da `OWNED BY <tablo>.id` ile bağlıdır: testlerdeki
`TRUNCATE ... RESTART IDENTITY` onları da sıfırlar. Testler numara DEĞERİNE
değil biçimine (`NUMARA_DESENI`) bağlanır.

`nextval` transaction geri alınsa bile geri dönmez: numara serisinde boşluk
olabilir. Bu bilinçli bedeldir — boşluksuz seri ancak tabloyu kilitleyerek
(eşzamanlı açılışları sıraya sokarak) elde edilirdi.
"""

import re
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.teknik_servis.yerel_zaman import yerel_gun

# Sequence adı → kullanan belge(ler). `belge_no` yalnız bu adları kabul eder
# (SQL'e dışarıdan ad girmesin).
SEKANSLAR: dict[str, str] = {
    "service_order_no_seq": "Servis işi (SRV-) ve planlı bakım işi (PB-) — ortak",
    "service_visit_no_seq": "Ziyaret (ZYR-)",
    "seq_bakim_sozlesme_no": "Bakım sözleşmesi (BAKIM-NNNN, aylık değil)",
}

# Önek → sequence. Dalga 2'nin önekleri (AT-, KIR-, SAY-) kendi
# migration'larıyla birlikte eklenir.
ONEKLER: dict[str, str] = {
    "SRV": "service_order_no_seq",
    "PB": "service_order_no_seq",
    "ZYR": "service_visit_no_seq",
}

NUMARA_DESENI = r"^[A-Z]{2,5}-\d{6}-\d{6,}$"
BAKIM_SOZLESME_DESENI = r"^BAKIM-\d{4,}$"

_ONEK_BICIMI = re.compile(r"^[A-Z]{2,5}$")


async def _sonraki(db: AsyncSession, sekans: str) -> int:
    if sekans not in SEKANSLAR:
        raise ValueError(f"Bilinmeyen numara serisi: {sekans}")
    # Ad beyaz listeden geldiği için bağlama parametresi yeterli; regclass
    # dönüşümü olmayan sequence'te açık hata verir.
    deger = await db.scalar(text("SELECT nextval(CAST(:ad AS regclass))"), {"ad": sekans})
    return int(deger)


async def belge_no(db: AsyncSession, sekans: str, onek: str, tarih: date | datetime) -> str:
    """`f"{onek}-{tarih:%Y%m}-{nextval:06d}"`.

    `tarih` yerel (Europe/Istanbul) tarih olmalıdır — çağıran
    `yerel_zaman.yerel_bugun(clock)` ya da dönemin hedef tarihini verir.
    Saat dilimli bir `datetime` verilirse Türkiye gününe çevrilir (31 Ekim
    22:30 UTC'de açılan iş KASIM numarası alır). `sekans` `SEKANSLAR`
    dışında, önek tanımsız ya da başka bir seriye bağlıysa ValueError.
    """
    if not _ONEK_BICIMI.match(onek or ""):
        raise ValueError(f"Geçersiz belge öneki: {onek!r}")
    if ONEKLER.get(onek) != sekans:
        raise ValueError(f"'{onek}' öneki '{sekans}' serisine bağlı değil")
    gun = yerel_gun(tarih) if isinstance(tarih, datetime) else tarih
    sira = await _sonraki(db, sekans)
    return f"{onek}-{gun:%Y%m}-{sira:06d}"


async def bakim_sozlesme_no(db: AsyncSession) -> str:
    """`BAKIM-NNNN` (`seq_bakim_sozlesme_no`); göçteki `BAKIM-00NN` korunur.

    Ay bilgisi taşımaz: sözleşme yıllara yayılır, numarası müşteriye yazılı
    olarak verilmiş eski biçimle aynı kalmalı.
    """
    sira = await _sonraki(db, "seq_bakim_sozlesme_no")
    return f"BAKIM-{sira:04d}"
