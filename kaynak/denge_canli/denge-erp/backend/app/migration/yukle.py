"""Veri göçü orkestratörü.

    python -m app.migration.yukle              # ÖNİZLEME — hiçbir şey yazmaz
    python -m app.migration.yukle --uygula     # tek transaction

Tasarım kuralları (mevcut hak ediş uygulamasının göç betiklerinden devralındı):
- `--uygula` verilmedikçe HİÇBİR ŞEY yazılmaz.
- Yazma TEK transaction'da olur; ortada bir hata çıkarsa hiçbir satır kalmaz.
- Tekrar çalıştırılabilir: her kayıt `source_system`/`source_ref` taşır,
  ikinci koşu aynı kayıtları günceller, kopya üretmez.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.migration.esleme import kaynak_ref
from app.migration.hazirla import hazirla, rapor_metni
from app.migration.hazirla_envanter import (
    envanter_raporu,
    esenyurt_envanteri,
    hakedis_envanteri,
)
from app.migration.hazirla_isemri import isemirlerini_hazirla, isemri_raporu
from app.migration.kaynak_esenyurt import EsenyurtKaynagi
from app.migration.kaynak_hakedis import HakedisKaynagi, HazirlikSonucu
from app.migration.yukle_isemri import isemirlerini_yaz
from app.models import Account, Device, InstallationPartner, Product, SimCard, Vehicle
from app.services.normalize import tr_normkey

KAYNAK = "hakedis"


async def _hesap_upsert(db: AsyncSession, ref: str, alanlar: dict) -> Account:
    """source_ref üzerinden bul-veya-oluştur. İkinci koşuda kopya üretmez."""
    hesap = await db.scalar(
        select(Account).where(Account.source_system == KAYNAK, Account.source_ref == ref)
    )
    if hesap is None:
        hesap = Account(source_system=KAYNAK, source_ref=ref, **alanlar)
        db.add(hesap)
    else:
        for alan, deger in alanlar.items():
            # Bayrakları GERİ ALMA: elle eklenmiş bir rol göçte silinmesin.
            if alan.startswith("is_") and getattr(hesap, alan) and not deger:
                continue
            setattr(hesap, alan, deger)
    await db.flush()
    return hesap


async def uygula(db: AsyncSession, sonuc: HazirlikSonucu) -> dict[str, int]:
    sayac = {"montaj_noktasi": 0, "musteri": 0, "bayi": 0, "urun": 0}

    # 1) Montaj noktaları — hak edişin ön koşulu, önce açılır.
    nokta_idleri: dict[str, int] = {}
    for kayit in sonuc.montaj_noktalari:
        hesap = await _hesap_upsert(
            db,
            kaynak_ref("nokta", kayit["title"]),
            {
                "title": kayit["title"],
                "is_montaj_noktasi": True,
                "phone": kayit["phone"],
                "is_active": True,
            },
        )
        nokta_idleri[kayit["title"]] = hesap.id
        ortak = await db.get(InstallationPartner, hesap.id)
        if ortak is None:
            db.add(InstallationPartner(account_id=hesap.id, km_unit_price=kayit["km_unit_price"]))
        else:
            ortak.km_unit_price = kayit["km_unit_price"]
        sayac["montaj_noktasi"] += 1
    await db.flush()

    # 2) Bayiler — bir kısmı zaten montaj noktası; o zaman AYNI hesaba bayrak
    #    eklenir, ikinci kayıt açılmaz.
    bayi_idleri: dict[str, int] = {}
    for kayit in sonuc.bayiler:
        ad = kayit["title"]
        if ad in nokta_idleri:
            hesap = await db.get(Account, nokta_idleri[ad])
            hesap.is_bayi = True
        else:
            hesap = await _hesap_upsert(
                db, kaynak_ref("bayi", ad), {"title": ad, "is_bayi": True, "is_active": True}
            )
        bayi_idleri[ad] = hesap.id
        sayac["bayi"] += 1
    await db.flush()

    # 3) Müşteriler — bayi bağı varsa parent_dealer_id'ye yazılır.
    for kayit in sonuc.musteriler:
        ad = kayit["title"]
        alanlar = {"title": ad, "is_musteri": True, "is_active": True}
        if kayit["bayi"] and kayit["bayi"] in bayi_idleri:
            alanlar["parent_dealer_id"] = bayi_idleri[kayit["bayi"]]
        mevcut_nokta = nokta_idleri.get(ad)
        if mevcut_nokta:
            # Hem müşteri hem montaj noktası (ör. kendi aracına kendi montajını
            # yapan firma) — tek hesap, iki bayrak.
            hesap = await db.get(Account, mevcut_nokta)
            hesap.is_musteri = True
            if alanlar.get("parent_dealer_id"):
                hesap.parent_dealer_id = alanlar["parent_dealer_id"]
        else:
            await _hesap_upsert(db, kaynak_ref("musteri", ad), alanlar)
        sayac["musteri"] += 1
    await db.flush()

    # 4) Ürün kartları — cihazlardan ÖNCE (cihaz ürüne bağlı)
    for kart in sonuc.urunler:
        veri = {k: v for k, v in kart.items() if k != "kaynak_adlar"}
        urun = await db.scalar(select(Product).where(Product.code == veri["code"]))
        if urun is None:
            db.add(
                Product(source_system=KAYNAK, source_ref=kaynak_ref("urun", veri["code"]), **veri)
            )
        else:
            for alan, deger in veri.items():
                setattr(urun, alan, deger)
        sayac["urun"] += 1
    await db.flush()

    # 5) Araçlar
    sayac.update({"arac": 0, "cihaz": 0, "hat": 0})
    musteri_idleri: dict[str, int] = {}
    for kayit in sonuc.araclar:
        unvan = kayit.get("musteri_adi") or ""
        if unvan and unvan not in musteri_idleri:
            hesap = await db.scalar(select(Account).where(Account.title_key == tr_normkey(unvan)))
            if hesap is None:
                hesap = await _hesap_upsert(
                    db, kaynak_ref("musteri", unvan), {"title": unvan, "is_musteri": True}
                )
            musteri_idleri[unvan] = hesap.id

        ref = kaynak_ref("arac", kayit["plate"])
        arac = await db.scalar(
            select(Vehicle).where(Vehicle.source_system == KAYNAK, Vehicle.source_ref == ref)
        )
        alanlar = {
            "plate": kayit["plate"],
            "is_plate_verified": kayit["is_plate_verified"],
            "chassis_no": kayit["chassis_no"],
            "registration_no": kayit["registration_no"],
            "brand": kayit["brand"],
            "model_year": kayit["model_year"],
            "customer_id": musteri_idleri.get(unvan),
        }
        if kayit.get("diger_plakalar"):
            alanlar["notes"] = "Aynı şaseyle kayıtlı diğer plakalar: " + ", ".join(
                kayit["diger_plakalar"]
            )
        if arac is None:
            db.add(Vehicle(source_system=KAYNAK, source_ref=ref, **alanlar))
        else:
            for alan, deger in alanlar.items():
                # Elle doldurulmuş bir alanı göç BOŞLA EZMEZ.
                if deger is not None or getattr(arac, alan) is None:
                    setattr(arac, alan, deger)
        sayac["arac"] += 1
    await db.flush()

    # 6) Hatlar — ICCID kaynakta yok, kart MSISDN ile açılır.
    for kayit in sonuc.hatlar:
        ref = kaynak_ref("hat", kayit["msisdn"])
        hat = await db.scalar(
            select(SimCard).where(SimCard.source_system == KAYNAK, SimCard.source_ref == ref)
        )
        if hat is None:
            db.add(
                SimCard(
                    source_system=KAYNAK,
                    source_ref=ref,
                    # ICCID zorunlu ve tekil; kaynakta olmadığı için geçici
                    # yer tutucu MSISDN'den türetilir ve operatörden gelince
                    # düzeltilir. Sahte IMEI'den farkı: ICCID bir kimlik değil,
                    # hattın seri numarasıdır ve MSISDN zaten hattı tanımlar.
                    iccid=f"MSISDN:{kayit['msisdn']}",
                    msisdn=kayit["msisdn"],
                    operator=kayit["operator"],
                    status="AKTIF",
                    field_sources={"iccid": "EKSIK"},
                )
            )
        sayac["hat"] += 1
    await db.flush()

    # 7) Cihazlar
    urun_idleri = {
        u.code: (u.id, u.identity_kind) for u in (await db.scalars(select(Product))).all()
    }
    for kayit in sonuc.cihazlar:
        urun = urun_idleri.get(kayit["urun_kodu"])
        if urun is None:
            continue
        urun_id, kimlik_tipi = urun
        ref = kaynak_ref("cihaz", kayit["kimlik"])
        cihaz = await db.scalar(
            select(Device).where(Device.source_system == KAYNAK, Device.source_ref == ref)
        )
        if cihaz is None:
            db.add(
                Device(
                    source_system=KAYNAK,
                    source_ref=ref,
                    imei=kayit["imei"],
                    serial_no=kayit["serial_no"],
                    identity_kind=kimlik_tipi,
                    product_id=urun_id,
                    is_identity_provisional=kayit["is_identity_provisional"],
                    status="AKTIF",
                )
            )
        sayac["cihaz"] += 1
    await db.flush()

    return sayac


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Denge ERP veri göçü")
    parser.add_argument(
        "--uygula", action="store_true", help="Değişiklikleri YAZ (yoksa yalnız önizleme)"
    )
    parser.add_argument("--hakedis-yolu", type=Path, help="hakedis.db yolu")
    parser.add_argument("--esenyurt-yolu", type=Path, help="Esenyurt xlsx yolu")
    args = parser.parse_args(argv)

    kaynak = HakedisKaynagi(**({"yol": args.hakedis_yolu} if args.hakedis_yolu else {}))
    try:
        sonuc = hazirla(kaynak)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    esenyurt = EsenyurtKaynagi(**({"yol": args.esenyurt_yolu} if args.esenyurt_yolu else {}))
    try:
        esenyurt_envanteri(esenyurt, sonuc)
    except FileNotFoundError as exc:
        print(f"UYARI: {exc}\n(Envanter aktarımı atlandı.)")

    isler = kaynak.isler()
    # Hak ediş kaynağındaki araç/cihaz/hatlar da envantere katılır;
    # sök-tak zincirlerinin çoğu yalnız bu kaynakta var.
    hakedis_envanteri(isler, sonuc)
    taslaklar = isemirlerini_hazirla(isler, sonuc)

    print(rapor_metni(sonuc, kaynak.ozet()))
    print(envanter_raporu(sonuc))
    print(isemri_raporu(taslaklar))

    if not args.uygula:
        return 0

    async with get_session_factory()() as db:
        sayac = await uygula(db, sonuc)
        sayac.update(await isemirlerini_yaz(db, taslaklar, sonuc))
        # Türetilmiş "şu an" alanları (`devices.current_*`, `first_activation_date`)
        # tarihli tablolardan YENİDEN hesaplanır. Göç bunları doldurmuyordu ve
        # sonucu görünürdü: garanti başlangıcı `first_activation_date`'ten
        # geldiği için göçten gelen her cihazın RMA garanti kararı "belirsiz"
        # çıkıyordu. Ayrı bir elle adım olarak bırakmak, bir gün unutulacağı
        # anlamına gelirdi.
        from app.services import devices as cihaz_svc

        uzlasma = await cihaz_svc.uzlastir(db)
        sayac["uzlastirilan_cihaz"] = uzlasma["farkli"]
        await db.commit()

    print("\n" + "=" * 64)
    print("UYGULANDI")
    for ad, adet in sayac.items():
        print(f"  {ad:<18} {adet}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
