"""Sunucudan çalıştırılan yönetim komutları.

    python -m app.yonetim kilitliler             # kilitli hesapları listeler
    python -m app.yonetim kilit-ac <kullanıcı>   # kilidi açar
    python -m app.yonetim canliya-hazirla        # ÖNİZLEME
    python -m app.yonetim canliya-hazirla --uygula
    python -m app.yonetim test-verisi-temizle    # ÖNİZLEME
    python -m app.yonetim test-verisi-temizle --uygula
    python -m app.yonetim hat-durumu-duzelt      # ÖNİZLEME
    python -m app.yonetim hat-durumu-duzelt --uygula

`kilit-ac` neden var: giriş kilidi artık kendiliğinden açılmıyor, bir yönetici
açıyor. Yöneticinin kendisi kilitlenirse arayüzden açacak kimse kalmaz — bu
komut o çıkmazın tek çıkışı.

`hat-durumu-duzelt` neden var: içe aktarma cihazın İÇİNDE takılı bir hattı
"STOKTA" bırakabiliyor (`cihaz_sim_iccid` göçü durum yazmadığı için 2.413 hat
böyle kaldı). Depoda olmadığı KANITLI bir hattı stokta göstermek, "kaç boş
hattımız var" raporunu doğrudan yanlışlar.

`canliya-hazirla` neden var: geliştirme veritabanı canlıya taşınıyor (veri
orada oluşturulup doğrulandı) ama geliştirme KİMLİKLERİ taşınmamalı.

Sunucuya kabuk erişimi olan zaten her şeyi yapabilir; burada yeni bir yetki
açılmıyor.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.models import LoginAttempt, Session, SimCard, SimDeviceHistory, User
from app.services import auth as auth_service


async def _kilitliler() -> int:
    async with get_session_factory()() as db:
        adlar = await auth_service.kilitli_kullanicilar(db)
    if not adlar:
        print("Kilitli hesap yok.")
        return 0
    print(f"{len(adlar)} kilitli hesap:")
    for ad in adlar:
        print(f"  {ad}")
    return 0


async def _kilit_ac(kullanici: str) -> int:
    async with get_session_factory()() as db:
        acildi = await auth_service.kilidi_ac(db, kullanici)
        await db.commit()
    if not acildi:
        print(f"'{kullanici}' hesabında açık kilit yok.", file=sys.stderr)
        return 1
    print(f"'{kullanici}' hesabının kilidi açıldı.")
    return 0


async def _canliya_hazirla(yaz: bool) -> int:
    """Geliştirme veritabanını üretime almadan önce temizler.

    Veri (hesap, cihaz, araç, hat, iş emri) GELİŞTİRMEDE oluşturuldu ve
    doğrulandı; canlıya taşınacak olan odur. Taşınmaması gereken tek şey
    **geliştirme kimlikleri**: `app/seeds/dev.py` her rolden bir kullanıcıyı
    SABİT parolayla (`deneme1234`) açıyor. Bu kullanıcılar üretime giderse
    parolası herkesçe bilinen sekiz hesap doğar.

    Silinmezler, KAPATILIRLAR: `audit_logs` onlara işaret ediyor ve denetim
    izi silinmemeli. Parolaları tahmin edilemez bir değerle değiştirilir,
    MFA sırları düşürülür — hiçbir yoldan giriş yapılamaz.

    Yönetici hesabı korunur ama parolası yenilenir ve MFA'sı sıfırlanır:
    geliştirmede kurulan TOTP sırrı üretime taşınmamalı.
    """
    async with get_session_factory()() as db:
        kullanicilar = (await db.scalars(select(User))).all()
        demolar = [k for k in kullanicilar if k.username != "admin"]
        admin = next((k for k in kullanicilar if k.username == "admin"), None)
        oturum = len((await db.scalars(select(Session))).all())
        kilit = len((await db.scalars(select(LoginAttempt))).all())

        print("=" * 64)
        print("CANLIYA HAZIRLIK" + ("" if yaz else " — ÖNİZLEME"))
        print("=" * 64)
        print(f"  kapatılacak geliştirme kullanıcısı : {len(demolar)}")
        for k in demolar:
            print(f"      {k.username}")
        print(f"  düşürülecek oturum                 : {oturum}")
        print(f"  temizlenecek giriş kilidi sayacı   : {kilit}")
        print(f"  yönetici parolası                  : {'yenilenecek' if admin else 'YOK!'}")

        if not yaz:
            print("\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
            return 0

        for k in demolar:
            k.is_active = False
            k.mfa_enabled = False
            k.totp_secret = None
            # Silinmiyor (denetim izi işaret ediyor) ama parolası artık
            # kimsenin bilmediği bir değer.
            k.password_hash = auth_service.hash_password(secrets.token_urlsafe(32))

        yeni_parola = None
        if admin is not None:
            yeni_parola = secrets.token_urlsafe(12)
            admin.password_hash = auth_service.hash_password(yeni_parola)
            # Ekranda görünen parola kurulum parolasıdır: ilk girişte
            # değiştirilmesi zorunlu (TS-212). Süre sınırı konmaz — ilk kurulum
            # yöneticisiyle aynı (`seeds/dev.py`): komut ile ilk giriş arasındaki
            # süre bilinmez.
            admin.parola_degismeli = True
            admin.gecici_parola_bitis = None
            admin.mfa_enabled = False
            admin.totp_secret = None

        await db.execute(delete(Session))
        await db.execute(delete(LoginAttempt))
        await db.commit()

    print("\nUYGULANDI.")
    if yeni_parola:
        print("\n  YÖNETİCİ PAROLASI (BİR KEZ GÖRÜNÜR, ŞİMDİ KAYDEDİN):")
        print("      kullanıcı: admin")
        print(f"      parola   : {yeni_parola}")
        print("\n  İlk girişte parola değişimi ve iki adımlı doğrulama kurulumu çıkacak.")
    return 0


# Test verisinin işaretleri — hepsi SABİT, dışarıdan değer almaz.
# Gerçek veride bu desenlerden hiçbiri yok: unvanlar Excel'den geldi,
# IMEI'ler 8 ya da 3 ile başlıyor, plakalar gerçek, ICCID'ler operatörden.
_TEST_HESAP = (
    "title ilike 'AJANTEST%' or title ilike '%DOGRULAMA%' "
    "or title like '=%' or title like '+%' or title like '@%'"
)
# IMEI/seri alanına da yazılmış test kayıtları var: `notes` deseni onları
# kaçırıyordu. Gerçek IMEI daima RAKAM, gerçek seri numaraları BB05/BB06/AG09
# önekli — harfle başlayan bu önekler yalnız ajan verisinde geçiyor.
_TEST_CIHAZ = (
    "notes ilike '%AJANTEST%' or imei like '99000000000%' "
    "or imei ilike 'AJANTEST%' or imei ilike 'AJTGELECEK%' "
    "or serial_no ilike 'AJANTEST%'"
)
_TEST_ARAC = "plate like '34AJT%'"
_TEST_HAT = "iccid like '8990011234500000%' or plan_name ilike '%AJANTEST%'"
_TEST_KULLANICI = r"username like 'ajan\_%' or username like 'dogrula\_%'"

# Ticari kayitlar (teklif, siparis, abonelik, RMA, tahsilat) yalniz TEST
# HESABINA bagliysa ya da hicbir hesaba bagli degilse silinir.
#
# Eskiden bu tablolar KOSULSUZ bosaltiliyordu ("nasil olsa gercek kayit yok").
# Varsayim canliya cikisla birlikte cokuyor ve komut KURULUM.md kontrol
# listesinde: go-live'dan sonra calistiran biri butun teklif, siparis,
# abonelik, RMA ve tahsilati siler. Kapsam disinda kalan kayit SILINMEZ,
# "dokunulmayacak" olarak raporlanir.
_MUSTERI_TEST = "customer_id in (select id from t_hesap) or customer_id is null"
_HESAP_TEST = "account_id in (select id from t_hesap) or account_id is null"
# ÖKSÜZ iş emri: müşterisi, aracı VE montaj noktası olmayan, hiçbir hak ediş
# satırına bağlanmamış, GÖÇTEN GELMEMİŞ kayıt. Test kayıtlarının bağlı
# oldukları silindikten sonra geriye bunlar kalır.
#
# `source_system is null` ŞART: göçten gelen gerçek veride de bu duruma düşmüş
# üç iş emri var (G202607-01199, -01200, -01206). Onlar silinmez — düzeltilmesi
# gereken gerçek kayıtlar (bkz. KURULUM.md §12 kontrol listesi).
_OKSUZ_IS_EMRI = (
    "source_system is null and customer_id is null and vehicle_id is null "
    "and assigned_id is null "
    "and id not in (select coalesce(work_order_id, 0) from settlement_lines)"
)


async def _test_verisi_temizle(yaz: bool) -> int:
    """Geliştirme ve test sırasında oluşan SAHTE kayıtları siler.

    Ekranları ve uçları gerçek kullanıcı gibi deneyen testler arkalarında
    hesap, cihaz, araç, hat, iş emri, sipariş, teklif, abonelik ve parti
    bırakır. Bunlar canlıya giderse ekiple birlikte gerçek veriymiş gibi
    görünür; hak ediş ve MRR rakamlarını kirletir.

    **Hak ediş dökümlerine DOKUNULMAZ.** Silinecek hesaplardan birine bağlı
    döküm varsa komut hiçbir şey yazmadan durur: 552.825,00 TL'lik doğrulanmış
    rakam hiçbir temizlik uğruna riske atılmaz.

    Önizleme varsayılandır; yazmak için `--uygula`.
    """
    from sqlalchemy import text as sa_text

    async with get_session_factory()() as db:
        for tablo, kaynak, kosul in (
            ("t_hesap", "accounts", _TEST_HESAP),
            ("t_cihaz", "devices", _TEST_CIHAZ),
            ("t_arac", "vehicles", _TEST_ARAC),
            ("t_hat", "sim_cards", _TEST_HAT),
            ("t_kullanici", "users", _TEST_KULLANICI),
        ):
            # `drop ... if exists`: komut aynı oturumda ikinci kez koşarsa
            # (testler böyle yapıyor) geçici tablolar çakışırdı.
            await db.execute(sa_text(f"drop table if exists {tablo}"))
            await db.execute(
                sa_text(f"create temp table {tablo} as select id from {kaynak} where {kosul}")  # noqa: S608
            )

        async def say(sorgu: str) -> int:
            return int((await db.scalar(sa_text(sorgu))) or 0)

        sayimlar = {
            "hesap": await say("select count(*) from t_hesap"),
            "cihaz": await say("select count(*) from t_cihaz"),
            "araç": await say("select count(*) from t_arac"),
            "hat": await say("select count(*) from t_hat"),
            "sipariş": await say(f"select count(*) from orders where {_MUSTERI_TEST}"),  # noqa: S608
            "teklif": await say(f"select count(*) from quotes where {_MUSTERI_TEST}"),  # noqa: S608
            "abonelik": await say(f"select count(*) from subscriptions where {_MUSTERI_TEST}"),  # noqa: S608
            "RMA": await say(f"select count(*) from rma_cases where {_MUSTERI_TEST}"),  # noqa: S608
            "tahsilat": await say(f"select count(*) from payments where {_HESAP_TEST}"),  # noqa: S608
            "transfer": await say(
                "select count(*) from transfers where created_by in (select id from t_kullanici)"
            ),
            "içe aktarma partisi": await say(
                "select count(*) from import_batches"
                " where created_by in (select id from t_kullanici)"
            ),
        }
        sayimlar["öksüz iş emri"] = await say(
            f"select count(*) from work_orders where {_OKSUZ_IS_EMRI}"  # noqa: S608
        )
        sayimlar["test kullanıcısı"] = await say(
            f"select count(*) from users where {_TEST_KULLANICI}"  # noqa: S608
        )

        # Kapsam dışında kalan GERÇEK ticari kayıtlar: silinmez, sayılır.
        korunan = {
            "teklif": await say(f"select count(*) from quotes where not ({_MUSTERI_TEST})"),  # noqa: S608
            "sipariş": await say(f"select count(*) from orders where not ({_MUSTERI_TEST})"),  # noqa: S608
            "abonelik": await say(
                f"select count(*) from subscriptions where not ({_MUSTERI_TEST})"  # noqa: S608
            ),
            "RMA": await say(f"select count(*) from rma_cases where not ({_MUSTERI_TEST})"),  # noqa: S608
            "tahsilat": await say(f"select count(*) from payments where not ({_HESAP_TEST})"),  # noqa: S608
        }

        bagli_dokum = await say(
            "select count(*) from partner_settlements where partner_id in (select id from t_hesap)"
        )
        dokum_sayisi = await say("select count(*) from partner_settlements")
        brut = await db.scalar(
            sa_text("select coalesce(sum(gross_amount),0) from partner_settlements")
        )

        print("=" * 64)
        print("TEST VERİSİ TEMİZLİĞİ" + ("" if yaz else " — ÖNİZLEME"))
        print("=" * 64)
        for ad, adet in sayimlar.items():
            print(f"  silinecek {ad:<22}: {adet}")
        print(f"\n  DOKUNULMAYACAK hak ediş dökümü : {dokum_sayisi} / {brut} TL")
        if korunanlar := {a: n for a, n in korunan.items() if n}:
            print(
                "  DOKUNULMAYACAK gerçek kayıt   : "
                + ", ".join(f"{a} {n}" for a, n in sorted(korunanlar.items()))
            )

        if bagli_dokum:
            print(
                f"\nDURDURULDU: {bagli_dokum} hak ediş dökümü silinecek hesaplara bağlı. "
                "Hiçbir şey yazılmadı."
            )
            return 1

        if not yaz:
            print("\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
            return 0

        for komut in _TEMIZLIK_ADIMLARI:
            await db.execute(sa_text(komut))
        await db.commit()
        # Geçici tabloları bırakma: oturum uzun yaşıyorsa (test koşucusu)
        # sonraki TRUNCATE'ler bunların kilidinde bekler.
        for tablo in (
            "t_hesap",
            "t_cihaz",
            "t_arac",
            "t_hat",
            "t_kullanici",
            "t_siparis",
            "t_teklif",
            "t_abonelik",
            "t_transfer",
            "t_wo",
        ):
            await db.execute(sa_text(f"drop table if exists {tablo}"))
        await db.commit()

        yeni_brut = await db.scalar(
            sa_text("select coalesce(sum(gross_amount),0) from partner_settlements")
        )
        print(f"\nUYGULANDI. Hak ediş toplamı: {yeni_brut} TL (değişmemeli).")
    return 0


# Silme sırası FK'lere göre; her adım tek transaction içinde koşar.
_TEMIZLIK_ADIMLARI = (
    # Ticari kayıtlar KAPSAMLI silinir. Koşulsuz `delete from quotes` yazmak
    # canlıda bütün teklifleri silerdi; komut KURULUM.md kontrol listesinde.
    f"delete from payments where {_HESAP_TEST}",  # noqa: S608
    f"create temp table t_siparis as select id from orders where {_MUSTERI_TEST}",  # noqa: S608
    "delete from order_reservations where order_id in (select id from t_siparis)"
    " or order_line_id in (select id from order_lines"
    " where order_id in (select id from t_siparis))",
    "delete from order_lines where order_id in (select id from t_siparis)",
    "delete from orders where id in (select id from t_siparis)",
    f"create temp table t_teklif as select id from quotes where {_MUSTERI_TEST}",  # noqa: S608
    "delete from quote_lines where version_id in"
    " (select id from quote_versions where quote_id in (select id from t_teklif))",
    "update quotes set current_version_id = null where id in (select id from t_teklif)",
    "delete from quote_versions where quote_id in (select id from t_teklif)",
    "delete from quotes where id in (select id from t_teklif)",
    f"create temp table t_abonelik as select id from subscriptions where {_MUSTERI_TEST}",  # noqa: S608
    "delete from subscription_events where subscription_id in (select id from t_abonelik)",
    "delete from subscription_prices where subscription_id in (select id from t_abonelik)",
    "delete from subscriptions where id in (select id from t_abonelik)",
    f"delete from rma_cases where {_MUSTERI_TEST}",  # noqa: S608
    "create temp table t_transfer as select id from transfers"
    " where created_by in (select id from t_kullanici)",
    "delete from transfer_items where transfer_id in (select id from t_transfer)",
    "delete from transfers where id in (select id from t_transfer)",
    "delete from import_batches where created_by in (select id from t_kullanici)",
    "delete from device_status_history where device_id in (select id from t_cihaz)",
    "delete from device_custody_history where device_id in (select id from t_cihaz)",
    "delete from device_vehicle_assignments where device_id in (select id from t_cihaz)"
    " or vehicle_id in (select id from t_arac)",
    "delete from sim_device_history where device_id in (select id from t_cihaz)"
    " or sim_id in (select id from t_hat)",
    "delete from sim_plan_history where sim_id in (select id from t_hat)",
    "update devices set current_vehicle_id = null where current_vehicle_id in"
    " (select id from t_arac)",
    "delete from devices where id in (select id from t_cihaz)",
    "delete from vehicles where id in (select id from t_arac)",
    "delete from sim_cards where id in (select id from t_hat)",
    f"create temp table t_wo as select id from work_orders where {_OKSUZ_IS_EMRI}",  # noqa: S608
    "delete from work_order_items where work_order_id in (select id from t_wo)",
    "delete from device_vehicle_assignments where install_work_order_id in (select id from t_wo)"
    " or removal_work_order_id in (select id from t_wo)",
    "delete from work_orders where id in (select id from t_wo)",
    "delete from attachments where entity = 'accounts' and entity_id in (select id from t_hesap)",
    "delete from contacts where account_id in (select id from t_hesap)",
    "delete from partner_tariffs where partner_id in (select id from t_hesap)",
    "delete from installation_partners where account_id in (select id from t_hesap)",
    "update accounts set parent_dealer_id = null where parent_dealer_id in"
    " (select id from t_hesap)",
    "update vehicles set customer_id = null where customer_id in (select id from t_hesap)",
    "update devices set current_customer_id = null where current_customer_id in"
    " (select id from t_hesap)",
    "delete from accounts where id in (select id from t_hesap)",
    # Kullanıcılara işaret eden TÜM yabancı anahtarlar ON DELETE SET NULL
    # (sessions hariç: CASCADE). Elle temizlemeye gerek yok — veritabanı
    # kendisi boşaltır; denetim izi satırları KALIR, yalnız kim alanı boşalır.
    r"delete from login_attempts where username like 'ajan\_%' or username like 'dogrula\_%'",
    r"delete from users where username like 'ajan\_%' or username like 'dogrula\_%'",
)


async def hat_durumu_duzelt(db: AsyncSession, *, yaz: bool) -> int:
    """Cihazda TAKILI olduğu hâlde 'STOKTA' görünen hatları AKTİF yapar.

    Ölçüt kanıta dayanır, tahmine değil: hattın AÇIK bir cihaz dönemi varsa
    (`valid_to IS NULL`) o hat fiziksel olarak bir cihazın içindedir; depoda
    olamaz. Dönemi KAPANMIŞ hat bu ölçüte girmez — sökülmüş hat gerçekten
    depoya dönmüş olabilir.

    TERSİ YAPILMAZ. Cihazda olmayan AKTİF hat "yanlış" değil: operatörde açık
    duran, yani PARA YAKAN boştaki hat demek. Onları STOKTA'ya çekmek bu
    sinyali silerdi — hat kârlılığı raporunun görmesi gereken tam olarak bu.

    Düzeltilen satır sayısını döndürür.
    """
    takili = select(SimDeviceHistory.sim_id).where(SimDeviceHistory.valid_to.is_(None))
    hatalilar = (
        await db.scalars(select(SimCard).where(SimCard.status == "STOKTA", SimCard.id.in_(takili)))
    ).all()

    print("=" * 64)
    print("HAT DURUMU DÜZELTMESİ" + ("" if yaz else " — ÖNİZLEME"))
    print("=" * 64)
    print(f"  cihazda takılı ama 'STOKTA' görünen hat : {len(hatalilar)}")
    if hatalilar:
        kaynaklar: dict[str, int] = {}
        for h in hatalilar:
            kaynaklar[h.source_system or "—"] = kaynaklar.get(h.source_system or "—", 0) + 1
        for kaynak, adet in sorted(kaynaklar.items(), key=lambda x: -x[1]):
            print(f"    {kaynak:20}: {adet}")
        print(f"  örnek: {', '.join(h.msisdn or h.iccid for h in hatalilar[:3])}")

    if not yaz:
        print("\nÖNİZLEME — hiçbir şey yazılmadı. --uygula ekleyin.")
        return 0

    for h in hatalilar:
        h.status = "AKTIF"
    await db.commit()
    print(f"\nUYGULANDI. {len(hatalilar)} hat AKTİF yapıldı.")
    return len(hatalilar)


async def _hat_durumu_duzelt(yaz: bool) -> int:
    async with get_session_factory()() as db:
        await hat_durumu_duzelt(db, yaz=yaz)
    return 0


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Denge ERP yönetim komutları")
    altlar = ayristirici.add_subparsers(dest="komut", required=True)
    altlar.add_parser("kilitliler", help="Kilitli hesapları listele")
    ac = altlar.add_parser("kilit-ac", help="Bir hesabın giriş kilidini aç")
    ac.add_argument("kullanici")
    hazirla = altlar.add_parser(
        "canliya-hazirla", help="Geliştirme kimliklerini kapat, yönetici parolasını yenile"
    )
    hazirla.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    temizle = altlar.add_parser(
        "test-verisi-temizle", help="Test/deneme kayıtlarını siler (hak edişe dokunmaz)"
    )
    temizle.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    hat = altlar.add_parser(
        "hat-durumu-duzelt", help="Cihazda takılı olduğu hâlde 'STOKTA' görünen hatları düzeltir"
    )
    hat.add_argument("--uygula", action="store_true", help="Yazar; verilmezse önizler.")
    args = ayristirici.parse_args(argv)

    if args.komut == "kilitliler":
        return asyncio.run(_kilitliler())
    if args.komut == "canliya-hazirla":
        return asyncio.run(_canliya_hazirla(args.uygula))
    if args.komut == "test-verisi-temizle":
        return asyncio.run(_test_verisi_temizle(args.uygula))
    if args.komut == "hat-durumu-duzelt":
        return asyncio.run(_hat_durumu_duzelt(args.uygula))
    return asyncio.run(_kilit_ac(args.kullanici))


if __name__ == "__main__":
    sys.exit(main())
