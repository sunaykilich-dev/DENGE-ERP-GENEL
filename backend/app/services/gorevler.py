"""Görev kartının ERP kaydına bağlantısı.

Bağlantı polimorfik (`entity` + `entity_id`). Bu dosya tek kayıt noktası:
hangi kayıt tiplerine bağlanılabilir, kartta nasıl yazılır, arayüzde hangi
adrese gider. Üçü ayrı yerlerde dursaydı yeni bir tip eklemek üç dosyayı
birden doğru değiştirmeyi gerektirirdi — biri unutulunca kart tıklanamaz ya
da etiketsiz görünürdü.

**Kaynak kayıt silinmiş olabilir.** Polimorfik bağlantıda veritabanı
bütünlüğü zorlamaz; bu yüzden etiket çözülürken kaydın varlığı kontrol edilir
ve yoksa kart bunu açıkça söyler. Sessizce boş bir etiket göstermek,
"bağlantı yok" ile "bağlantı kırık"ı aynı şeye çevirirdi.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    Device,
    MaintenanceContract,
    Order,
    PartnerSettlement,
    Quote,
    RmaCase,
    ServiceEquipment,
    ServiceOrder,
    SimCard,
    Vehicle,
    WorkOrder,
)


@dataclass(frozen=True)
class KayitTipi:
    kod: str
    ad: str
    model: type
    # Kartta görünen kısa etiket; ilk dolu alan kullanılır.
    alanlar: tuple[str, ...]
    # Arayüz adresi; `{id}` kaydın kimliğiyle değişir.
    yol: str


# `yol` arayüzün GERÇEK rotasıdır (bkz. `frontend/src/main.tsx`). Kimliğe
# göre derin bağlantısı olmayan ekranlar liste sayfasına gider — yanlış bir
# adres üretip 404'e düşürmektense listeye götürmek yeğdir.
KAYIT_TIPLERI: tuple[KayitTipi, ...] = (
    KayitTipi("isemri", "İş Emri", WorkOrder, ("wo_no",), "/is-emirleri"),
    KayitTipi("teklif", "Teklif", Quote, ("quote_no",), "/teklifler"),
    KayitTipi("siparis", "Sipariş", Order, ("order_no",), "/siparisler"),
    KayitTipi("rma", "RMA", RmaCase, ("rma_no",), "/rma"),
    KayitTipi("hesap", "Hesap", Account, ("title",), "/hesaplar/{id}"),
    KayitTipi("cihaz", "Cihaz", Device, ("imei", "serial_no"), "/cihazlar/{etiket}"),
    KayitTipi("arac", "Araç", Vehicle, ("plate",), "/araclar/{id}"),
    KayitTipi("hat", "Hat (SIM)", SimCard, ("msisdn", "iccid"), "/hatlar/{id}"),
    KayitTipi("hakedis", "Hak Ediş Dökümü", PartnerSettlement, ("period",), "/hakedis"),
    # --- Teknik servis (plan §1.11) -------------------------------------------
    # Görev uçlarında kayıt kapsamı bilerek uygulanmaz (api/gorevler.py); bu
    # yüzden etiket alanı KİŞİSEL VERİ ya da müşteri adı taşımaz: yalnız belge
    # numarası. Ekipmanın seri numarası bile yazılmaz (müşteri malı kütüğü):
    # alan listesi boş, kart "Ekipman #id" görünür. Kiralama, atölye ve eğitim
    # tipleri tabloları geldiği dalgada eklenir.
    KayitTipi("servis_isi", "Servis İşi", ServiceOrder, ("so_no",), "/servis-isleri/{id}"),
    KayitTipi("ekipman", "Ekipman", ServiceEquipment, (), "/servis-ekipman/{id}"),
    KayitTipi(
        "bakim_sozlesme",
        "Bakım Sözleşmesi",
        MaintenanceContract,
        ("contract_no",),
        "/bakim?sozlesme={id}",
    ),
)

_TIPE_GORE = {t.kod: t for t in KAYIT_TIPLERI}


def tip(kod: str) -> KayitTipi | None:
    return _TIPE_GORE.get(kod)


async def baglanti_cozumle(
    db: AsyncSession, ciftler: set[tuple[str, int]]
) -> dict[tuple[str, int], dict[str, str | bool]]:
    """(entity, entity_id) çiftlerini etiket + adrese çevirir.

    Kart listesi başına TEK sorgu düşsün diye tip bazında toplu okur; kart
    başına sorgu, elli kartlık bir panoda elli gidiş geliş demekti.
    """
    sonuc: dict[tuple[str, int], dict[str, str | bool]] = {}
    tipe_gore: dict[str, set[int]] = {}
    for kod, kimlik in ciftler:
        tipe_gore.setdefault(kod, set()).add(kimlik)

    for kod, kimlikler in tipe_gore.items():
        kt = _TIPE_GORE.get(kod)
        if kt is None:
            # Katalogdan çıkarılmış tip: kartı kaybetme, durumu söyle.
            for kimlik in kimlikler:
                sonuc[(kod, kimlik)] = {"ad": kod, "etiket": "—", "yol": "", "var": False}
            continue
        kayitlar = (await db.scalars(select(kt.model).where(kt.model.id.in_(kimlikler)))).all()
        bulunan = {k.id: k for k in kayitlar}
        for kimlik in kimlikler:
            kayit = bulunan.get(kimlik)
            if kayit is None:
                sonuc[(kod, kimlik)] = {
                    "ad": kt.ad,
                    "etiket": "kaynak kayıt silinmiş",
                    "yol": "",
                    "var": False,
                }
                continue
            etiket = next(
                (str(d) for a in kt.alanlar if (d := getattr(kayit, a, None))), f"#{kimlik}"
            )
            sonuc[(kod, kimlik)] = {
                "ad": kt.ad,
                "etiket": etiket,
                "yol": kt.yol.format(id=kimlik, etiket=etiket),
                "var": True,
            }
    return sonuc
