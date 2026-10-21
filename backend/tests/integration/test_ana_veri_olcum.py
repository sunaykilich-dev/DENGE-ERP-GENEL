"""TS-017: ana veri ölçümü ve kütük profili salt okunurdur ve sayı uydurmaz.

Çivilenen şeyler:
- ölçüm bağlantısı `SET TRANSACTION READ ONLY`: yazma denemesi DB hatası verir,
- koşu öncesi/sonrası satır sayıları aynı,
- VKN grubu yalnız AKTİF ve silinmemiş hesapları sayar; TCKN maskelenir,
- çok adresli hesap ve il yazım çeşitleri doğru sayılır,
- kütük profili seri no'suz / mükerrer / lokasyonsuz / tarih desenini ve
  cihaz kimliği boş PB kalemini doğru sayar; ölçülemeyeni "ÖLÇÜLMEDİ" yazar,
- çıktı tablo bazında ayrı sayfalardır.
"""

import re
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.clock import FakeClock
from app.migration import ana_veri_olcum, kutuk_profil
from app.migration.ana_veri_olcum import OLCULMEDI, salt_okunur, vergi_no_goster
from app.migration.kutuk_profil import (
    KaynakHatasi,
    profil_cikar,
    seed_sql_oku,
    teslim_deseni,
)
from app.models import Account, Address

pytestmark = pytest.mark.integration

_SAYILAN = (
    "accounts",
    "addresses",
    "contacts",
    "service_equipment",
    "audit_logs",
    "settings",
)


async def _satir_sayilari(engine) -> dict[str, int]:
    async with engine.connect() as conn:
        return {
            t: await conn.scalar(text(f"SELECT count(*) FROM {t}"))  # noqa: S608 — sabit liste
            for t in _SAYILAN
        }


async def _hesap(db, unvan: str, **kw) -> Account:
    hesap = Account(title=unvan, is_musteri=True, **kw)
    db.add(hesap)
    await db.flush()
    return hesap


async def _adres(db, hesap: Account, **kw) -> Address:
    adres = Address(account_id=hesap.id, line=kw.pop("line", "Cadde 1"), **kw)
    db.add(adres)
    await db.flush()
    return adres


async def _ekipman(db, *, seri: str | None, birim: str = "GUVENLIK", aktif: bool = True) -> None:
    # Ham SQL: ölçümün ORM olaylarından bağımsız, kayıttaki `serial_key`'i
    # okuduğunu gösterir.
    await db.execute(
        text(
            "INSERT INTO service_equipment"
            " (birim, equipment_type, serial_no, serial_key, is_active)"
            " VALUES (:b, 'XRAY', :s, :k, :a)"
        ),
        {"b": birim, "s": seri, "k": seri.strip().upper() if seri else None, "a": aktif},
    )


# --- Salt okunurluk ---------------------------------------------------------------


async def test_salt_okunur_baglanti_yazmayi_reddeder(engine):
    async with salt_okunur(engine) as conn:
        with pytest.raises(DBAPIError, match="read-only"):
            await conn.execute(
                text("INSERT INTO settings (key, value) VALUES ('olcum.deneme', '1'::jsonb)")
            )
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM settings")) == 0


async def test_salt_okunur_baglanti_transaction_salt_okunur(engine):
    async with salt_okunur(engine) as conn:
        assert await conn.scalar(text("SHOW transaction_read_only")) == "on"


# --- Ana veri ölçümü --------------------------------------------------------------


async def test_ana_veri_olcumu_sayilari_ve_salt_okunurluk(engine, db, tmp_path):
    a1 = await _hesap(db, "Alfa Güvenlik A.Ş.", tax_no="1234567890", region="İstanbul")
    a2 = await _hesap(db, "ALFA GÜVENLİK A.Ş.", tax_no="1234567890", region="ISTANBUL")
    # Aynı VKN'li ama pasif ve silinmiş hesaplar gruba girmez.
    await _hesap(db, "Alfa Eski", tax_no="1234567890", is_active=False)
    await _hesap(db, "Alfa Silinen", tax_no="1234567890", is_deleted=True)
    # Şahıs: 11 hane TCKN, raporda maskelenir.
    await _hesap(db, "Ali Veli", tax_no="12345678901", region="istanbul ")
    await _hesap(db, "Ali Veli Ltd", tax_no="12345678901")
    await _hesap(db, "Beta", tax_no="9999999999", region="Ankara")
    await _adres(db, a1, city="İzmir", is_primary=True)
    await _adres(db, a1, city="IZMIR", is_primary=True)
    await _adres(db, a2, city="İzmir")
    await db.commit()

    once = await _satir_sayilari(engine)
    cikti = tmp_path / "olcum.xlsx"
    sonuc = await ana_veri_olcum.calistir(engine, cikti, clock=FakeClock())
    assert await _satir_sayilari(engine) == once, "ölçüm hiçbir tabloya yazmamalı"

    assert sonuc.deger("aktif hesap") == 5
    assert sonuc.deger("aynı VKN'li aktif hesap grubu") == 2
    assert sonuc.deger("aynı VKN'li gruplardaki aktif hesap") == 4
    vkn_satirlari = sonuc.sayfalar["VKN_Gruplari"].satirlar
    assert {s[0] for s in vkn_satirlari} == {"1234567890", "12*******01"}
    assert all("12345678901" not in str(h) for s in vkn_satirlari for h in s), "TCKN açık yazılmaz"

    assert sonuc.deger("title_key çakışan aktif hesap grubu") == 1
    assert sonuc.deger("birden çok adresli aktif hesap") == 1
    assert sonuc.deger("birden çok birincil adresli aktif hesap") == 1
    assert sonuc.deger("toplam adres") == 3

    # İstanbul: 3 yazım tek anahtar; İzmir: 2 yazım tek anahtar; Ankara tek.
    assert sonuc.deger("farklı il yazımı (ham)") == 6
    assert sonuc.deger("farklı il anahtarı (tr_normkey)") == 3
    assert sonuc.deger("birden çok yazımı olan il anahtarı") == 2

    wb = load_workbook(cikti, read_only=True)
    assert wb.sheetnames == [
        "Ozet",
        "VKN_Gruplari",
        "Unvan_Gruplari",
        "Adres_Dagilimi",
        "Il_Yazimlari",
    ]


async def test_bos_veritabaninda_sifir_doner_uydurmaz(engine):
    sonuc = await ana_veri_olcum.calistir(engine, None, clock=FakeClock())
    assert sonuc.deger("aktif hesap") == 0
    assert sonuc.deger("aynı VKN'li aktif hesap grubu") == 0
    assert sonuc.deger("birden çok adresli aktif hesap") == 0
    assert sonuc.sayfalar["VKN_Gruplari"].satirlar == []


def test_vergi_no_maskesi():
    assert vergi_no_goster("1234567890") == "1234567890"
    assert vergi_no_goster("12345678901") == "12*******01"


async def test_formul_gibi_unvan_metin_olarak_yazilir(engine, db, tmp_path):
    await _hesap(db, "=HYPERLINK(1)", tax_no="1111111111")
    await _hesap(db, "=hyperlink(1)", tax_no="1111111111")
    await db.commit()
    cikti = tmp_path / "olcum.xlsx"
    await ana_veri_olcum.calistir(engine, cikti, clock=FakeClock())
    ws = load_workbook(cikti)["VKN_Gruplari"]
    assert ws["D2"].data_type == "s"


# --- Kütük profili: saf fonksiyonlar ------------------------------------------------

_CIHAZ_KOLONLARI = (
    "SourceKey,SourceRowNo,DeviceType,Brand,Model,ProductRaw,SerialNo,"
    "CustomerName,Location,ContactName,DeliveryDateText,InstallStatus,Notes"
)
_SOZLESME_KOLONLARI = (
    "SourceKey,CustomerName,CurrentAddress,ProductsText,FrequencyText,AnnualFrequency,"
    "MaintenanceFeeText,PeriodText,CompletedCount,ContractTotal,Total2026"
)
_SEED = "\n".join(
    [
        "-- deneme",
        "MERGE dbo.SecurityDevices AS t",
        "USING (VALUES",
        "(N'XRAY-1',1,N'X-Ray',N'SC',N'SC-5030 A',N'p',N' abc-i01 ',N'MÜŞTERİ A',"
        "N'Kapı',N'KİŞİ',N'42721',N'KURULDU',NULL),",
        "(N'XRAY-2',2,N'X-Ray',N'SC',N'SC 5030 A',N'p',N'ABC-I01',N'MÜŞTERİ A',"
        "NULL,N'KİŞİ',N'00.00.2015',NULL,NULL),",
        "(N'XRAY-3',3,N'X-Ray',N'SC',N'SC-5030A',N'p',N'00123',N'CITY''S AVM',"
        "N'',NULL,N'15.03.2020',NULL,NULL),",
        "(N'XRAY-4',4,N'Kapı Dedektörü',N'CEIA',N'HI-PE',N'p',N'123',N'müşteri a',"
        "N'Giriş',NULL,NULL,NULL,NULL),",
        "(N'XRAY-5',5,N'Kapı Dedektörü',N'CEIA',N'HI-PE',N'p',NULL,NULL,"
        "N'Giriş',NULL,N'2015',NULL,NULL)",
        f") AS s({_CIHAZ_KOLONLARI})",
        "ON t.SourceKey=s.SourceKey",
        "WHEN NOT MATCHED THEN INSERT(SourceKey) VALUES(s.SourceKey);",
        "GO",
        "MERGE dbo.MaintenanceContracts AS t",
        "USING (VALUES",
        "(N'BAKIM-1',N'MÜŞTERİ A',N'adres',N'1 X-RAY',N'YILDA 1',1,N'1 TL',"
        "N'01.01.2026-31.12.2026',0,1.5,NULL),",
        "(N'BAKIM-2',N'Müşteri A',NULL,N'1 X-RAY',N'YILDA 1',1,NULL,NULL,0,NULL,NULL),",
        "(N'BAKIM-3',N'MEGA AVM',NULL,N'1 X-RAY',N'YILDA 1',1,NULL,NULL,0,NULL,NULL)",
        f") AS s({_SOZLESME_KOLONLARI})",
        "ON t.SourceKey=s.SourceKey;",
    ]
)


def test_seed_sql_ayristirilir_kacis_ve_null_korunur():
    tablolar = seed_sql_oku(_SEED)
    cihazlar = tablolar["SecurityDevices"]
    assert len(cihazlar) == 5
    assert cihazlar[0]["SerialNo"] == " abc-i01 ", "ham değer değiştirilmez"
    assert cihazlar[2]["CustomerName"] == "CITY'S AVM"
    assert cihazlar[2]["SerialNo"] == "00123", "baştaki sıfır korunur"
    assert cihazlar[4]["SerialNo"] is None
    assert cihazlar[0]["SourceRowNo"] == 1
    assert len(tablolar["MaintenanceContracts"]) == 3
    assert tablolar["MaintenanceContracts"][0]["ContractTotal"] == 1.5


def test_seed_sql_kolon_sayisi_tutmazsa_hata():
    bozuk = "MERGE dbo.SecurityDevices AS t USING (VALUES (N'a',1)) AS s(SourceKey) ON 1=1;"
    with pytest.raises(KaynakHatasi):
        seed_sql_oku(bozuk)


@pytest.mark.parametrize(
    ("ham", "desen"),
    [
        (None, "BOS"),
        ("  ", "BOS"),
        ("42721", "EXCEL_GUN"),
        ("15.03.2020", "GG.AA.YYYY"),
        ("00.00.2015", "GG.AA.YYYY_GECERSIZ"),
        ("2015", "YIL"),
        ("MART 2020", "DIGER"),
        ("99999999", "GECERSIZ"),
    ],
)
def test_teslim_deseni(ham, desen):
    assert teslim_deseni(ham) == desen


def test_kutuk_profili_sayilari():
    tablolar = seed_sql_oku(_SEED)
    kalemler = [{"SecurityDeviceId": 1}, {"SecurityDeviceId": None}, {"SecurityDeviceId": ""}]
    p = profil_cikar(
        tablolar["SecurityDevices"],
        sozlesmeler=tablolar["MaintenanceContracts"],
        kalemler=kalemler,
    )
    s = p.sayilar
    assert s["toplam_satir"] == 5
    assert s["serisiz"] == 1
    # ' abc-i01 ' ve 'ABC-I01' aynı anahtar; '00123' ile '123' FARKLI.
    assert s["mukerrer_seri_grup"] == 1
    assert s["mukerrer_seri_satir"] == 2
    assert s["lokasyonsuz"] == 2, "NULL ve boş metin lokasyonsuz"
    assert s["musterisiz"] == 1
    assert s["teslim_excel_gun"] == 1
    assert s["teslim_gg_aa_yyyy"] == 1
    assert s["teslim_okunamaz"] == 1
    assert s["teslim_bos"] == 1
    assert s["farkli_model_metni"] == 4
    assert s["farkli_model_anahtari"] == 2, "SC-5030 A / SC 5030 A / SC-5030A tek model"
    assert s["pb_kalem"] == 3
    assert s["pb_kalem_cihazsiz"] == 2
    assert s["sozlesme"] == 3
    assert s["sozlesme_kutuk_birebir"] == 1
    assert s["sozlesme_kutuk_katlanmis"] == 2

    ozet = {ad: deger for ad, deger, _ in p.ozet}
    assert ozet["accounts ile tekil eşleşen müşteri adı"] == OLCULMEDI, "DB yoksa uydurulmaz"

    karsilastirma = {r[0]: r for r in p.sayfalar["Tasarim_Karsilastirma"].satirlar}
    assert karsilastirma["serisiz"][1:] == [1, 96, -95]


def test_kaynak_yoksa_olculmedi_yazar():
    p = profil_cikar(seed_sql_oku(_SEED)["SecurityDevices"])
    ozet = {ad: deger for ad, deger, _ in p.ozet}
    assert ozet["PB kalemi"] == OLCULMEDI
    assert ozet["aktif sözleşme"] == OLCULMEDI
    assert "pb_kalem" not in p.sayilar


def test_pasif_satir_mukerrere_girmez():
    cihazlar = [
        {"SerialNo": "A1", "IsActive": 1},
        {"SerialNo": "a1", "IsActive": 0},
        {"SerialNo": "A1", "IsActive": "True"},
    ]
    p = profil_cikar(cihazlar)
    assert p.sayilar["aktif_satir"] == 2
    assert p.sayilar["mukerrer_seri_satir"] == 2


def test_xlsx_ve_csv_dokumu_okunur(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["SecurityDeviceId", "SerialNo", "Location", "IsActive"])
    ws.append([1, "00123", "Kapı", 1])
    ws.append([2, None, None, 1])
    ws.append([None, None, None, None])
    xlsx = tmp_path / "kutuk.xlsx"
    wb.save(xlsx)
    csv_yol = tmp_path / "kalemler.csv"
    csv_yol.write_text("MaintenanceDeviceItemId,SecurityDeviceId\n1,5\n2,\n", encoding="utf-8")

    tablolar = kutuk_profil.kaynaklari_topla(kutuk=xlsx, kalemler=csv_yol)
    assert len(tablolar["SecurityDevices"]) == 2, "tamamen boş satır atlanır"
    assert tablolar["SecurityDevices"][0]["SerialNo"] == "00123"
    assert tablolar["MaintenanceContracts"] is None
    p = profil_cikar(tablolar["SecurityDevices"], kalemler=tablolar["MaintenanceDeviceItems"])
    assert p.sayilar["serisiz"] == 1
    assert p.sayilar["pb_kalem_cihazsiz"] == 1


# --- Kütük profili: canlı PG ------------------------------------------------------


async def test_kutuk_profili_db_ile_salt_okunur(engine, db, tmp_path):
    await _hesap(db, "MÜŞTERİ A")
    await _hesap(db, "City's AVM")
    await _hesap(db, "CITY'S AVM")  # aynı title_key → belirsiz
    await _ekipman(db, seri="X1")
    await _ekipman(db, seri="x1 ")
    await _ekipman(db, seri="X1", aktif=False)
    await _ekipman(db, seri=None)
    await _ekipman(db, seri="  ")
    await _ekipman(db, seri="X1", birim="HABERLESME")
    await db.commit()

    once = await _satir_sayilari(engine)
    seed = tmp_path / "seed.sql"
    seed.write_text(_SEED, encoding="utf-8")
    cikti = tmp_path / "profil.xlsx"
    p = await kutuk_profil.calistir(
        kutuk_profil.kaynaklari_topla(seed_sql=seed), engine=engine, cikti=cikti, clock=FakeClock()
    )
    assert await _satir_sayilari(engine) == once, "profil hiçbir tabloya yazmamalı"

    s = p.sayilar
    # Kütükte farklı müşteri adı: 'müşteri a' (MÜŞTERİ A ile aynı) ve "city's avm".
    assert s["kutuk_musteri_adi"] == 2
    assert s["hesap_tekil"] == 1
    assert s["hesap_belirsiz"] == 1
    assert s["hesap_yok"] == 0

    assert s["canli_toplam"] == 6
    assert s["canli_serisiz"] == 2
    assert s["canli_mukerrer_grup"] == 1, "pasif satır ve başka birim gruba girmez"
    assert s["canli_mukerrer_satir"] == 2

    wb = load_workbook(cikti, read_only=True)
    assert "Ozet" in wb.sheetnames
    assert "Canli_Kutuk" in wb.sheetnames
    assert "Tasarim_Karsilastirma" in wb.sheetnames


async def test_kutuk_yoksa_hata(engine):
    with pytest.raises(KaynakHatasi):
        await kutuk_profil.calistir(
            dict.fromkeys(kutuk_profil.TABLOLAR), engine=None, cikti=None, clock=FakeClock()
        )


async def test_komut_satiri_dosya_yoksa_1_doner(tmp_path):
    assert await kutuk_profil.main(["--seed-sql", str(tmp_path / "yok.sql")]) == 1


# --- Kaynak T-SQL betiği ----------------------------------------------------------

_M14_SQL = Path(kutuk_profil.__file__).parent / "teknik_servis" / "sql" / "m14_olcum.sql"


def test_m14_kaynak_olcumu_yalniz_select():
    """Kaynak ölçüm betiği SQL Server test kopyasında koşar; hiçbir şey yazmamalı."""
    metin = _M14_SQL.read_text(encoding="utf-8")
    kod = re.sub(r"/\*.*?\*/", " ", metin, flags=re.DOTALL)
    kod = re.sub(r"--[^\n]*", " ", kod)
    yasak = re.findall(
        r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|EXEC|EXECUTE|GRANT|INTO)\b",
        kod,
        flags=re.IGNORECASE,
    )
    assert yasak == []
    # Kabulde istenen sonuç kümeleri yerinde.
    for parca in ("WorkOrders", "SecurityDevices", "MaintenanceDeviceItems", "Zone", "IsActive"):
        assert parca in kod
