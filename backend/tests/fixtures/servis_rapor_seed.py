# ruff: noqa: E501  (senaryo tablosu ve tek satırlık kayıt kurulumları okunur kalsın)
"""Servis raporları altın KPI veri seti (TS-183, E12-07).

**Yalnız test veritabanında çalışır** (kontrol B15): veritabanı adı `_test`
(ya da paket veritabanı `_test_<ek>`) ile bitmiyorsa ya da geliştirme
`DATABASE_URL`'iyle aynıysa `RuntimeError`. `seeds/dev.py`'ye EKLENMEZ.

**Senaryo** (Mart 2026, Türkiye saati; beklenen değerler elle hesaplandı,
`servis_rapor_beklenen.json`):

| İş | Birim | Durum | Not |
|---|---|---|---|
| J1 | GUVENLIK | TAMAMLANDI | KRİTİK, seri `0012345`, AKYAKA; Ali Veli YOL 0,5 + SAHA 2 + SAHA 1 (iki gün → tekrar ziyaret), MOLA 0,5 (sayılmaz); SLA zamanında |
| J2 | GUVENLIK | KAPATILDI | 19 haneli seri; süre kaydı YOK (süre eksik, ziyaret kaydı eksik); SLA aşıldı (malzeme) |
| J3 | GUVENLIK | TAMAMLANDI | TELEFON ile çözüldü — süre beklenmez; SLA zamanında |
| J4 | GUVENLIK | TAMAMLANDI | servis fonksiyonlarıyla: çöz → YENİDEN AÇ → çöz (olay geçmişi gerçek); SAHA 1 + 1,5; SLA yürürlükte değil → kanca ÖLÇÜLEMEDİ yazar |
| J5 | GUVENLIK | MÜŞTERİ TALEBİ | J2'nin tekrar arızası, teyit AYNI_ARIZA (onaylı) |
| J6 | GUVENLIK | PLANLANDI | KRİTİK, plan 26.03 |
| J7 | GUVENLIK | İPTAL | |
| J8 | GUVENLIK | İPTAL | atölye işi iptali (açık/geciken sayılmaz) |
| J9 | HABERLESME | TAMAMLANDI | Hasan Yıldız SAHA 2; il "34"; SLA zamanında |
| J10 | GUVENLIK | MÜŞTERİ TALEBİ | göç (V1), müşteri eşleşmemiş "Gama Ltd"; göç süre kaydı "Eski Teknisyen" SAHA 1 |
| J11 | GUVENLIK | TAMAMLANDI | Şubat (önceki dönem) |
| J13 | GUVENLIK | MÜŞTERİ TALEBİ | J1'e tekrar arıza bağı, teyit YOK (aday) |
| PB×17 | GUVENLIK | 15 TAMAMLANDI + 2 PLANLAMADA | AKYAKA sözleşmesi, cihaz başına PB işi |

Seed idempotenttir: işaret hesabı (`Account.title == AKYAKA`) varsa yeniden
kurmaz. Kayıtların çoğu ORM ile kurulur (zaman damgaları belirlenebilir
olsun); yeniden açılma senaryosu servis fonksiyonlarıyla (`is_emirleri.
olustur/durum_degistir`, `sonuc.sonuc_kaydet`) yürür ki olay tablosu gerçek olsun.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from app.clock import FakeClock
from app.config import get_config
from app.models import (
    Account,
    Address,
    MaintenanceContract,
    MaintenanceContractItem,
    MaintenancePeriod,
    ServiceOrder,
    ServiceOrderAssignment,
    ServiceOrderSerial,
    ServicePlan,
    ServiceResult,
    ServiceTimeEntry,
)
from app.services.normalize import normalize_seri
from app.services.teknik_servis import is_emirleri, numara, sonuc

AKYAKA = "AKYAKA AVM Yönetimi"
_DB_KALIBI = re.compile(r"_test(_[a-z0-9]+)?$")


def z(gun: int, saat: int, dakika: int = 0, ay: int = 3) -> datetime:
    """2026 yılı UTC anı (Türkiye = UTC+3)."""
    return datetime(2026, ay, gun, saat, dakika, tzinfo=UTC)


@dataclass
class Seed:
    isler: dict[str, ServiceOrder] = field(default_factory=dict)
    pb: list[ServiceOrder] = field(default_factory=list)
    kisiler: dict[str, Any] = field(default_factory=dict)
    akyaka: Account | None = None


async def _veritabani_dogrula(db) -> None:
    baglanti = await db.connection()
    url = baglanti.engine.url
    if not _DB_KALIBI.search(url.database or ""):
        raise RuntimeError(f"Seed yalnız test veritabanında çalışır (veritabanı: {url.database})")
    if url.render_as_string(hide_password=False) == get_config().database_url:
        raise RuntimeError("Seed geliştirme veritabanına yazmaz")


async def _so(db, *, birim="GUVENLIK", tur="ARIZA", durum, musteri, adres=None, created, **kw):
    so = ServiceOrder(
        so_no=await numara.belge_no(
            db, "service_order_no_seq", "PB" if tur == "PB" else "SRV", created
        ),
        birim=birim,
        tur=tur,
        kategori=is_emirleri.tur_kategorisi(tur),
        status=durum,
        customer_id=musteri.id if musteri is not None else None,
        address_id=adres.id if adres is not None else None,
        konu=kw.pop("konu", "Altın set arızası"),
        created_at=created,
        **kw,
    )
    db.add(so)
    await db.flush()
    return so


def _seri(so, seri: str) -> ServiceOrderSerial:
    return ServiceOrderSerial(service_order_id=so.id, seri_no=seri, seri_norm=normalize_seri(seri))


def _atama(so, kisi, rol="TEKNISYEN", lead=True) -> ServiceOrderAssignment:
    return ServiceOrderAssignment(
        service_order_id=so.id, user_id=kisi.id, rol=rol, is_lead=lead, assigned_at=so.created_at
    )


def _bolum(so, kisi, faaliyet, bas, bit, **kw) -> ServiceTimeEntry:
    return ServiceTimeEntry(
        service_order_id=so.id,
        user_id=kisi.id if kisi is not None else None,
        faaliyet=faaliyet,
        started_at=bas,
        ended_at=bit,
        kaynak="MANUEL",
        girildi_at=bit,
        **kw,
    )


def _sonuc(so, kanal="YERINDE") -> ServiceResult:
    return ServiceResult(
        service_order_id=so.id, sonuc="COZULDU", cozum_kanali=kanal, yapilan_islem="Giderildi"
    )


async def kur(db, kisiler: dict[str, Any]) -> Seed:
    """Altın seti kurar. `kisiler`: tek1 (Ali Veli), tek2 (Aliye Kaya), tek3
    (Hasan Yıldız, HABERLESME), sef_g (GUVENLIK şefi) — çağıran açar (rol ve
    birim üyelikleri `conftest` yardımcılarıyla)."""
    await _veritabani_dogrula(db)
    mevcut = await db.scalar(select(Account).where(Account.title == AKYAKA))
    if mevcut is not None:
        # İdempotent: ikinci kurulum hiçbir satır eklemez (E12-07 kabulü).
        return Seed(kisiler=kisiler, akyaka=mevcut)
    s = Seed(kisiler=kisiler)
    akyaka = Account(title=AKYAKA, is_musteri=True)
    beta = Account(title="Beta Lojistik A.Ş.", is_musteri=True)
    db.add_all([akyaka, beta])
    await db.flush()
    s.akyaka = akyaka
    a_akyaka = Address(
        account_id=akyaka.id,
        kind="TESIS",
        label="Tesis",
        site_name="Akyaka AVM",
        city="MUĞLA",
        district="Ula",
    )  # noqa: E501
    a_beta = Address(
        account_id=beta.id, kind="TESIS", label="Tesis", site_name="Beta Depo", city="istanbul"
    )  # noqa: E501
    a_beta2 = Address(
        account_id=beta.id, kind="TESIS", label="Tesis", site_name="Beta Telsiz Odası", city="34"
    )  # noqa: E501
    db.add_all([a_akyaka, a_beta, a_beta2])
    await db.flush()
    tek1, tek2, tek3, sef = kisiler["tek1"], kisiler["tek2"], kisiler["tek3"], kisiler["sef_g"]

    # J1 — kritik, çözüldü, iki gün saha (tekrar ziyaret), mola sayılmaz.
    j1 = await _so(db, durum="TAMAMLANDI", musteri=akyaka, adres=a_akyaka, created=z(2, 6),
                   oncelik="KRITIK", completed_at=z(4, 9), first_completed_at=z(4, 9),
                   sla_sonuc="ZAMANINDA", iletisim_ad="Saha Yetkilisi", iletisim_telefon="+905321112233")  # fmt: skip
    db.add_all([
        _seri(j1, "0012345"), _atama(j1, tek1), _atama(j1, sef, "SEF", lead=False), _sonuc(j1),
        _bolum(j1, tek1, "YOL", z(2, 7), z(2, 7, 30)),
        _bolum(j1, tek1, "SAHA", z(2, 7, 30), z(2, 9, 30), konum_notu="Kat 2"),
        _bolum(j1, tek1, "MOLA", z(2, 9, 30), z(2, 10)),
        _bolum(j1, tek1, "SAHA", z(4, 7), z(4, 8), aciklama="Kart değişti"),
    ])  # fmt: skip

    # J2 — kapatıldı, süre kaydı yok, SLA aşıldı.
    j2 = await _so(db, durum="KAPATILDI", musteri=beta, adres=a_beta, created=z(5, 8),
                   completed_at=z(6, 10), first_completed_at=z(6, 10), closed_at=z(7, 8),
                   sla_sonuc="ASILDI", gecikme_nedeni="MALZEME_TEDARIK")  # fmt: skip
    db.add_all([_seri(j2, "1234567890123456789"), _atama(j2, tek2), _sonuc(j2)])

    # J3 — telefonla çözüldü (süre beklenmez).
    j3 = await _so(db, tur="DESTEK", durum="TAMAMLANDI", musteri=beta, adres=a_beta,
                   created=z(10, 8), completed_at=z(10, 8, 30), first_completed_at=z(10, 8, 30),
                   sla_sonuc="ZAMANINDA")  # fmt: skip
    db.add(_sonuc(j3, "TELEFON"))

    # J5 — J2'nin onaylı tekrar arızası (açık).
    j5 = await _so(db, durum="MUSTERI_TALEBI", musteri=beta, adres=a_beta, created=z(20, 8),
                   iliskili_is_id=j2.id, iliski_turu="TEKRAR_ARIZA", tekrar_ariza_aday=True,
                   tekrar_ariza_teyit="AYNI_ARIZA")  # fmt: skip
    db.add(_seri(j5, "1234567890123456789"))

    # J6 — kritik, planlandı (dönem sonunda açık).
    j6 = await _so(db, durum="PLANLANDI", musteri=beta, adres=a_beta, created=z(25, 8),
                   oncelik="KRITIK")  # fmt: skip
    db.add(ServicePlan(service_order_id=j6.id, plan_date=date(2026, 3, 26), duration_min=60,
                       change_type="ILK_PLAN"))  # fmt: skip

    # J7 — iptal; J8 — atölye işi iptali.
    j7 = await _so(db, durum="IPTAL", musteri=beta, adres=a_beta, created=z(15, 8),
                   cancelled_at=z(16, 8), cancel_reason="Müşteri vazgeçti")  # fmt: skip
    j8 = await _so(db, tur="ATOLYE", durum="IPTAL", musteri=beta, adres=a_beta, created=z(3, 8),
                   cancelled_at=z(5, 8), cancel_reason="Atölye kaydı iptal edildi")  # fmt: skip
    db.add(_seri(j8, "AT-SERI-01"))

    # J9 — HABERLEŞME, il "34".
    j9 = await _so(db, birim="HABERLESME", durum="TAMAMLANDI", musteri=beta, adres=a_beta2,
                   created=z(8, 8), completed_at=z(8, 11), first_completed_at=z(8, 11),
                   sla_sonuc="ZAMANINDA")  # fmt: skip
    db.add_all([_atama(j9, tek3), _sonuc(j9), _bolum(j9, tek3, "SAHA", z(8, 8), z(8, 10))])

    # J10 — göç işi, müşteri eşleşmemiş, göç süre kaydı (kişi eşleşmemiş).
    j10 = await _so(db, durum="MUSTERI_TALEBI", musteri=None, created=z(20, 8, ay=2),
                    source_system="V1", source_ref="G-1", customer_name_raw="Gama Ltd",
                    location_raw="Gama Depo")  # fmt: skip
    db.add(_bolum(j10, None, "SAHA", z(9, 8), z(9, 9), source_system="V1", source_ref="S-1",
                  kaynak_personel_adi="Eski Teknisyen"))  # fmt: skip

    # J11 — önceki dönem (Şubat).
    j11 = await _so(db, durum="TAMAMLANDI", musteri=beta, adres=a_beta, created=z(10, 8, ay=2),
                    completed_at=z(11, 8, ay=2), first_completed_at=z(11, 8, ay=2),
                    sla_sonuc="ZAMANINDA")  # fmt: skip
    db.add(_sonuc(j11))

    # J13 — J1'e bağlı, teyitsiz tekrar arıza adayı.
    j13 = await _so(db, durum="MUSTERI_TALEBI", musteri=akyaka, adres=a_akyaka, created=z(25, 9),
                    iliskili_is_id=j1.id, iliski_turu="TEKRAR_ARIZA", tekrar_ariza_aday=True)  # fmt: skip
    db.add(_seri(j13, "0012345"))

    # AKYAKA PB dönemi: 17 cihaz, 15 tamamlandı.
    sozlesme = MaintenanceContract(
        contract_no=await numara.bakim_sozlesme_no(db), birim="GUVENLIK",
        account_id=akyaka.id, address_id=a_akyaka.id,
    )  # fmt: skip
    db.add(sozlesme)
    await db.flush()
    # Cihaz başına bir sözleşme kalemi (`uq_so_pb_cihaz_donem`: kalem × dönem tek iş).
    kalemler = [
        MaintenanceContractItem(contract_id=sozlesme.id, equipment_type="XRAY", sira=i + 1)
        for i in range(17)
    ]
    donem = MaintenancePeriod(contract_id=sozlesme.id, cycle_start=z(1, 0), sequence_no=1,
                              target_date=date(2026, 3, 15))  # fmt: skip
    db.add_all([*kalemler, donem])
    await db.flush()
    for i, kalem in enumerate(kalemler):
        tamam = i < 15
        pb = await _so(db, tur="PB", durum="TAMAMLANDI" if tamam else "PLANLAMADA",
                       musteri=akyaka, adres=a_akyaka, created=z(1, 6),
                       completed_at=z(10, 8, i) if tamam else None,
                       first_completed_at=z(10, 8, i) if tamam else None,
                       contract_item_id=kalem.id, maintenance_period_id=donem.id,
                       konu=f"Periyodik bakım cihaz {i + 1}")  # fmt: skip
        db.add(_seri(pb, f"AKY-XR-{i + 1:02d}"))
        s.pb.append(pb)
    await db.commit()

    # J4 — servis fonksiyonlarıyla: çöz → yeniden aç → çöz (gerçek olay geçmişi).
    saat = FakeClock(z(11, 6))
    j4 = await is_emirleri.olustur(
        db,
        is_emirleri.ServisIsiGirdisi(
            birim="GUVENLIK", tur="ARIZA", konu="Kapı dedektörü alarm vermiyor",
            customer_id=akyaka.id, address_id=a_akyaka.id, seriler=["KD-77"],
        ),
        user=None,
        clock=saat,
    )  # fmt: skip
    j4.created_at = z(11, 6)
    db.add(_atama(j4, tek1))
    db.add(_bolum(j4, tek1, "SAHA", z(11, 7), z(11, 8)))
    await db.flush()
    saat.set(z(11, 9))
    await sonuc.sonuc_kaydet(
        db, j4, sonuc.SonucGirdisi("COZULDU", "YERINDE", "Sensör ayarlandı"), user=None, clock=saat
    )
    await is_emirleri.durum_degistir(db, j4, "TAMAMLANDI", kaynak="sonuc", user=None, clock=saat)
    saat.set(z(12, 6))
    await is_emirleri.durum_degistir(
        db, j4, "TEKRAR_ACILDI", kaynak="yeniden_ac", user=None, clock=saat,
        gerekce="Arıza devam ediyor",
    )  # fmt: skip
    db.add(_bolum(j4, tek1, "SAHA", z(12, 7), z(12, 8, 30)))
    await db.flush()
    saat.set(z(12, 9))
    await sonuc.sonuc_kaydet(
        db, j4, sonuc.SonucGirdisi("COZULDU", "YERINDE", "Sensör değişti"), user=None, clock=saat
    )
    await is_emirleri.durum_degistir(db, j4, "TAMAMLANDI", kaynak="sonuc", user=None, clock=saat)
    await db.commit()

    s.isler = {
        "J1": j1, "J2": j2, "J3": j3, "J4": j4, "J5": j5, "J6": j6, "J7": j7, "J8": j8,
        "J9": j9, "J10": j10, "J11": j11, "J13": j13,
    }  # fmt: skip
    return s
