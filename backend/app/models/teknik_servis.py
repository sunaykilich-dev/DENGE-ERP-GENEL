"""Teknik servis iş emri çekirdeği (servis işi, olay geçmişi, bekleme, sonuç,
atama, müşteri onayı, zaman kaydı).

**Neden mobilite `work_orders` tablosu kullanılmadı** (00 §6.2, KD-01):
`settlements.donem_kapat`, uyarı merkezi ve panel `work_orders`/
`work_order_items` satırlarını hak ediş mantığıyla sayıyor; mobilite kaydı da
doğduğu an TAMAMLANDI. Servis işini oraya yazmak altın kayıt testini
(932 iş / 552.825,00 TL) kirletir ve plan/atama/bekleme akışını imkânsız
kılardı. Servis işi bu yüzden ayrı bir alandır; mobiliteye yalnız salt
okunur `work_order_id` köprüsüyle bakar ve oraya HİÇ yazmaz.

**Tek kaynak sözlükler** (plan §1.7): durum, tür, kategori, öncelik, kanal,
ilişki, sonuç, çözüm kanalı, onay türü, atama rolü, olay türü ve zaman
faaliyeti bu dosyadaki tuple'lardır; CHECK kısıtları da aynı tuple'dan
üretilir. Bekleme ve arıza nedeni ise TABLODUR (FK): SLA durdurma bayrağı ve
birim bazlı katalog veri olarak yönetilebilsin, sonradan CHECK→FK dönüşümü
gerekmesin (KD-14).

Durum geçişi YALNIZ `services/teknik_servis/is_emirleri.durum_degistir` ile
yapılır (`SERVIS_IS_EMRI` makinesi + `UC_HEDEFLERI` + kancalar); `status`
alanına doğrudan atama yasaktır.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    event,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.models.rbac import BIRIM_KODLARI, birim_check
from app.services import normalize as _normalize


def _in(sutun: str, degerler: tuple[str, ...] | frozenset[str], *, bos: bool = False) -> str:
    """`sutun IN ('A','B')` — CHECK ifadeleri tuple'dan üretilir, elle kopya yok."""
    liste = ", ".join(f"'{d}'" for d in sorted(degerler))
    ifade = f"{sutun} IN ({liste})"
    return f"{sutun} IS NULL OR {ifade}" if bos else ifade


# --- Sözlükler (plan §1.7) -----------------------------------------------------

# KARGODA ve TEST_KONTROL YOK: atölye ayrıntısı `workshop_records`'ta
# (KD-13). Servis işi atölyedeyken yalnız ATOLYEDE görünür.
SERVIS_DURUMLARI = (
    "MUSTERI_TALEBI",
    "PLANLAMADA",
    "PLANLANDI",
    "YOLA_CIKILDI",
    "SAHADA",
    "ISLEMDE",
    "ATOLYEDE",
    "BEKLEMEDE",
    "TAMAMLANDI",
    "KAPATILDI",
    "TEKRAR_ACILDI",
    "IPTAL",
)

# Durum grupları — rapor, panel, liste ve uyarı aynı kümeleri kullanır
# (E12-01). Elle yazılmış ikinci liste "sayı = liste" ilkesini bozardı.
_KAPALI = frozenset({"TAMAMLANDI", "KAPATILDI", "IPTAL"})
DURUM_GRUPLARI: dict[str, frozenset[str]] = {
    "KAPALI": _KAPALI,
    "ACIK": frozenset(SERVIS_DURUMLARI) - _KAPALI,
    "COZULDU": frozenset({"TAMAMLANDI", "KAPATILDI"}),
    "SAHA": frozenset({"YOLA_CIKILDI", "SAHADA", "ISLEMDE"}),
    "SAYAC_ACILABILIR": frozenset(SERVIS_DURUMLARI) - _KAPALI - {"BEKLEMEDE"},
}


def durum_grubu(durum: str) -> str:
    """Rapor grubu: COZULDU | IPTAL | ACIK (E12-01)."""
    if durum in DURUM_GRUPLARI["COZULDU"]:
        return "COZULDU"
    if durum == "IPTAL":
        return "IPTAL"
    return "ACIK"


# Tür → kategori kuralı `services/teknik_servis/is_emirleri.TUR_KURALLARI`'dadır;
# burada yalnız CHECK'in değer kümeleri durur.
SERVIS_TURLERI = (
    "ARIZA",
    "PLANSIZ_BAKIM",
    "DESTEK",
    "PB",
    "ATOLYE",
    "KURULUM",
    "TOPLAMA",
    "KESIF",
    "DEMONTAJ",
)
SERVIS_KATEGORILERI = ("GUNLUK_SERVIS", "PLANLI_BAKIM", "ATOLYE", "PROJE")
ONCELIKLER = ("KRITIK", "YUKSEK", "NORMAL")
TALEP_KANALLARI = (
    "TELEFON",
    "WHATSAPP",
    "EPOSTA",
    "SAHADA_BILDIRILDI",
    "BAKIM_OTOMATIK",
    "DIGER",
)
ILISKI_TURLERI = ("MUKERRER", "TEKRAR_ARIZA", "DEVAM", "BAKIM_BULGUSU")
# İşin açılışta bir kez dondurulan kapsam bilgisi (E14-17).
KAPSAM_DURUMLARI = ("SOZLESMELI", "GARANTILI", "KAPSAM_DISI", "BILINMIYOR")

SERVIS_SONUCLARI = ("COZULDU", "COZULEMEDI", "TEKRAR_GIDILECEK", "TEKLIF_SUNULACAK")
COZUM_KANALLARI = ("YERINDE", "UZAKTAN", "TELEFON", "ATOLYE")
# Sahada görülen seri/bölge kütükten farklıysa (E03-14); PB'de form tutar.
KUTUK_FARK_DURUMLARI = ("ACIK", "UYGULANDI", "YOK_SAYILDI")

ONAY_TURLERI = ("IMZA", "SOZLU", "BASILI_FORM", "ALINAMADI")
ATAMA_ROLLERI = ("SEF", "TEKNISYEN")

# Dalga 0'da sonraki dalgaların türleri de dahil (TEKLIF, SLA, PARCA, ATOLYE):
# CHECK sonradan genişletilmek zorunda kalmasın (autogenerate CHECK görmez).
OLAY_TURLERI = (
    "OLUSTUR",
    "DURUM",
    "ATAMA",
    "PLAN",
    "BEKLEME",
    "BEKLEME_BITTI",
    "SONUC",
    "NOT",
    "EK",
    "EK_SIL",
    "ONAY",
    "DUZELTME",
    "SERI",
    "ILISKI",
    "PARCA",
    "ATOLYE",
    "TEKLIF",
    "SLA",
)

# Zaman faaliyetleri (E09-D02 tek sözlük; ISCILIK YOK → SAHA, KD-24).
ZAMAN_FAALIYETLERI = ("YOL", "SAHA", "UZAKTAN", "ATOLYE", "TEST", "BEKLEME", "MOLA", "DIGER")
# Mola kişi-saate girmez (korunacak iş kararı: zaman takibi bordro değildir).
KISI_SAATE_DAHIL = frozenset(ZAMAN_FAALIYETLERI) - {"MOLA"}
ZAMAN_KAYNAKLARI = ("CANLI", "MANUEL", "KULLANICI_DUZELTMESI", "YONETICI_DUZELTMESI")
ZAMAN_KAPANIS_TURLERI = ("BITIR", "GECIS", "UNUTULDU", "YONETICI")
ZAMAN_IPTAL_TURLERI = ("GERI_ALINDI", "YONETICI_IPTAL", "KAYIT_IPTAL", "GOC_IPTAL", "GOC_CAKISMA")
SAHA_AKIS = {"YOLA_CIKTIM": "YOL", "SAHAYA_VARDIM": "SAHA"}

# Tohumlar (migration `bulk_insert` bunları yazar; değerler veri olarak
# yönetilir, kod yalnız ilk hâli taşır).
# (kod, ad, sla_durdurur, aciklama_zorunlu, sadece_sistem, sira)
VARSAYILAN_BEKLEME_NEDENLERI = (
    ("MALZEME", "Malzeme bekleniyor", False, False, False, 10),
    ("MUSTERI_ONAYI", "Müşteri onayı bekleniyor", True, False, False, 20),
    ("TEKLIF", "Teklif onayı bekleniyor", True, False, False, 30),
    ("MUSTERI_ERISIMI", "Müşteri/saha erişimi yok", True, False, False, 40),
    ("PERSONEL", "Personel bekleniyor", False, False, False, 50),
    ("BAKIM_UYGUNSUZLUK", "Bakım uygunsuzluğu giderilecek", False, False, True, 60),
    ("DIS_SERVIS", "Dış servis/üretici bekleniyor", False, False, False, 70),
    ("DIGER", "Diğer", False, True, False, 90),
)
VARSAYILAN_ARIZA_NEDENLERI = (
    "Güç/Besleme",
    "Kablo/Bağlantı",
    "Donanım Arızası",
    "Yazılım/Yapılandırma",
    "Kullanıcı Hatası",
    "Çevresel/Fiziksel Hasar",
    "Arıza Bulunamadı",
    "Diğer",
)

# --- SLA / operasyon sözlükleri (Dalga 2, E10; plan §1.7) -------------------
# SLA yalnız GUNLUK_SERVIS kategorisinde ölçülür (`ck_so_pb_sla`); PB'nin vadesi
# bakım döneminden, atölyenin çevrim süresi atölye kaydından gelir.
SLA_TAKVIM_TURLERI = ("7_24", "MESAI")
# İşte DONDURULAN sonuç (ilk TAMAMLANDI'da yazılır, yeniden açılışta silinmez).
SLA_SONUCLARI = ("ZAMANINDA", "ASILDI", "OLCULEMEDI")
# CANLI = açılışta damgalandı; GECIS = yürürlük anından önce açılmış işe yürürlük
# anından damga; GERIYE_DONUK = göç geri doldurması (rapor modu, E10-15).
SLA_KAYNAKLARI = ("CANLI", "GECIS", "GERIYE_DONUK")
GECIKME_NEDENLERI = (
    "MALZEME_TEDARIK",
    "MUSTERI_KAYNAKLI",
    "ULASIM",
    "PERSONEL_YETERSIZ",
    "YOGUNLUK",
    "TEKNIK_ZORLUK",
    "DIGER",
)
TEKRAR_ARIZA_TEYITLERI = ("AYNI_ARIZA", "FARKLI_ARIZA", "KULLANICI_HATASI")
# Ekranda gösterilen (HESAPLANAN, saklanmayan) SLA durumu — tek üretici
# `services/teknik_servis/sla.py`; istemcide SLA hesabı yoktur (E10-18).
SLA_DURUMLARI = (
    "ZAMANINDA",
    "RISKTE",
    "ASILDI",
    "DURDURULDU",
    "KARSILANDI",
    "KARSILANMADI",
    "OLCULEMEDI",
    "SLA_DISI_PB",
)
# Kalıcı bildirim kodları. KRITIK_ATANMAMIS YOK (E01-18'in hesaplanan uyarısı,
# plan §6.3); PB_VADE_GECTI E04 fonksiyonundan okunur.
SLA_UYARI_KODLARI = (
    "SLA_RISK",
    "SLA_ASILDI",
    "MUDAHALE_ASILDI",
    "BEKLEME_BITIS_GECTI",
    "PB_VADE_GECTI",
)
SLA_UYARI_ONEMLERI = ("BILGI", "UYARI", "KRITIK")
# Tohum (migration `bulk_insert`): (oncelik, cozum_saat). Müdahale hedefi
# tanımsız, takvim 7/24, birim NULL = tüm birimler (KD-23).
VARSAYILAN_SLA_POLITIKALARI = (("KRITIK", 12), ("YUKSEK", 24), ("NORMAL", 72))

# --- E-posta bildirimi (Dalga 3, E10-06 / TS-200) ----------------------------
EPOSTA_TURLERI = ("ANLIK", "GUNLUK_OZET")
EPOSTA_DURUMLARI = ("BEKLIYOR", "GONDERILDI", "BASARISIZ")
# Şema tavanı; işletme sınırı ayar `servis_eposta_deneme` (1–10).
EPOSTA_AZAMI_DENEME = 10
# Anlık e-posta üreten kalıcı bildirim kodları (E10-06 kuyruga_al).
EPOSTA_ANLIK_KODLAR = ("SLA_ASILDI", "MUDAHALE_ASILDI")

_SURE_ARALIGI = literal_column("tstzrange(started_at, ended_at, '[)')")
_ACIK_IS = "status NOT IN ('TAMAMLANDI', 'KAPATILDI', 'IPTAL') AND NOT is_deleted"


class ServiceSlaPolicy(Base, PkMixin, TimestampMixin, VersionedMixin):
    """SLA politikası (E10-01) — öncelik (+ isteğe bağlı birim) başına hedef.

    İşe açılışta DONDURULUR (`service_orders.sla_policy_id`, hedef dakikaları
    ve hedef anı): politika sonradan değişse de açık işin hedefi değişmez,
    yalnız öncelik/birim düzeltmesi yeniden damgalar (TS-081).

    **ActorMixin / SoftDeleteMixin YOK — bilinçli:** ikisi de `users`'a FK
    taşır; testlerin `TRUNCATE users ... CASCADE` temizliği tabloyu boşaltır
    ve migration tohumu kaybolurdu (`ServiceHoldReason` emsali). Kimin
    değiştirdiği denetim izindedir; kayıt silinmez, `is_active=false` olur.
    Kategori kırılımı ilk sürümde YOK (E10 kontrol B14).
    """

    __tablename__ = "service_sla_policies"
    __table_args__ = (
        CheckConstraint(_in("oncelik", ONCELIKLER), name="ck_slap_oncelik"),
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_slap_birim"),
        CheckConstraint("cozum_saat > 0", name="ck_slap_cozum_pozitif"),
        CheckConstraint(
            "mudahale_saat IS NULL OR mudahale_saat > 0", name="ck_slap_mudahale_pozitif"
        ),
        CheckConstraint(_in("takvim_turu", SLA_TAKVIM_TURLERI), name="ck_slap_takvim"),
        # İfade indeksi (COALESCE): UniqueConstraint ile yazılamaz.
        Index(
            "uq_slap_aktif",
            "oncelik",
            text("COALESCE(birim, '*')"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    oncelik: Mapped[str] = mapped_column(String(10))
    # NULL = tüm birimler; birim satırı varsa önce o seçilir (`sla.politika_bul`).
    birim: Mapped[str | None] = mapped_column(String(20))
    cozum_saat: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    # NULL = müdahale SLA'sı tanımsız (hedef damgalanmaz, "ölçülmedi" değil).
    mudahale_saat: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    takvim_turu: Mapped[str] = mapped_column(
        String(10), server_default=text("'7_24'"), default="7_24"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class ServiceOrder(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Servis işi (arıza, PB, kurulum, atölye ...).

    **Müşteri = hesap, lokasyon = `addresses(kind='TESIS')`** (plan §1.5).
    API ile açılan işte `customer_id` zorunlu; göçte eşleşmeyen satır ham
    metniyle (`customer_name_raw`, `location_raw`) gelir ve uydurma bağ
    kurulmaz (`ck_so_musteri`).

    **1 cihaz = 1 PB iş emri** şemada zorlanır: `uq_so_pb_cihaz_donem`
    (`contract_item_id`, `maintenance_period_id`) WHERE tur='PB'. Worker
    yeniden denemesi bu sayede idempotent (`ON CONFLICT DO NOTHING`).

    `first_completed_at` ilk TAMAMLANDI anıdır ve yeniden açılışta SİLİNMEZ:
    SLA sonucu ve "yeniden açılan iş" raporu bununla ölçülür (E12-02).
    `coverage_status/snapshot` açılışta bir kez yazılır, sonra değişmez
    (E14-17): sonradan değişen sözleşme geçmiş işin kapsamını yeniden yazmaz.

    Ekipman/sözleşme kalemi/bakım dönemi FK'leri kendi tablolarıyla birlikte
    sonraki migration'larda eklenir (`fk_so_ekipman`, `fk_so_sozlesme_kalemi`,
    `fk_so_bakim_donemi`).
    """

    __tablename__ = "service_orders"
    __table_args__ = (
        UniqueConstraint("so_no", name="uq_so_no"),
        UniqueConstraint("source_system", "source_ref", name="uq_so_kaynak"),
        CheckConstraint(birim_check("birim"), name="ck_so_birim"),
        CheckConstraint(_in("tur", SERVIS_TURLERI), name="ck_so_tur"),
        CheckConstraint(_in("kategori", SERVIS_KATEGORILERI), name="ck_so_kategori"),
        CheckConstraint(_in("oncelik", ONCELIKLER), name="ck_so_oncelik"),
        CheckConstraint(_in("status", SERVIS_DURUMLARI), name="ck_so_durum"),
        CheckConstraint(_in("talep_kanali", TALEP_KANALLARI, bos=True), name="ck_so_kanal"),
        CheckConstraint(_in("coverage_status", KAPSAM_DURUMLARI, bos=True), name="ck_so_kapsam"),
        # API ile açılan işte müşteri FK zorunlu; yalnız göç kaydı ham metinle gelebilir.
        CheckConstraint(
            "customer_id IS NOT NULL OR source_system IS NOT NULL", name="ck_so_musteri"
        ),
        CheckConstraint(
            "status <> 'IPTAL' OR cancel_reason IS NOT NULL", name="ck_so_iptal_gerekce"
        ),
        # Bağ ve türü birlikte vardır ya da birlikte yoktur; tür de sözlükten.
        CheckConstraint(
            "(iliskili_is_id IS NULL) = (iliski_turu IS NULL) AND ("
            + _in("iliski_turu", ILISKI_TURLERI, bos=True)
            + ")",
            name="ck_so_iliski",
        ),
        CheckConstraint("iliskili_is_id <> id", name="ck_so_kendine_bagli"),
        CheckConstraint(
            "first_completed_at IS NULL OR completed_at IS NULL "
            "OR completed_at >= first_completed_at",
            name="ck_so_ilk_cozum",
        ),
        CheckConstraint(
            "tur <> 'PB' OR (contract_item_id IS NOT NULL AND maintenance_period_id IS NOT NULL)",
            name="ck_so_pb_bag",
        ),
        CheckConstraint("reopen_count >= 0", name="ck_so_yeniden_acilma"),
        # --- Dalga 2: SLA (d2a000000001) -----------------------------------
        # PB ve atölye işine politika/hedef damgalanamaz (TS-081, E10-10). Bu iki
        # türe ya da bu türlerden geçiş yasak olduğundan kısıt güvenle şemada;
        # proje türleri (KURULUM…) servis katmanında damgalanmaz (tür
        # düzeltmesinde kanca hedefi temizler — CHECK flush'ı kırmasın diye).
        CheckConstraint(
            "tur NOT IN ('PB', 'ATOLYE') OR (sla_policy_id IS NULL AND cozum_hedef_at IS NULL)",
            name="ck_so_pb_sla",
        ),
        CheckConstraint(
            _in("sla_takvim_turu", SLA_TAKVIM_TURLERI, bos=True), name="ck_so_sla_takvim"
        ),
        CheckConstraint(_in("sla_sonuc", SLA_SONUCLARI, bos=True), name="ck_so_sla_sonuc"),
        CheckConstraint(_in("sla_kaynak", SLA_KAYNAKLARI, bos=True), name="ck_so_sla_kaynak"),
        CheckConstraint(
            _in("gecikme_nedeni", GECIKME_NEDENLERI, bos=True), name="ck_so_gecikme_neden"
        ),
        CheckConstraint(
            "gecikme_nedeni IS DISTINCT FROM 'DIGER' OR gecikme_aciklama IS NOT NULL",
            name="ck_so_gecikme_diger",
        ),
        CheckConstraint(
            _in("tekrar_ariza_teyit", TEKRAR_ARIZA_TEYITLERI, bos=True),
            name="ck_so_tekrar_teyit",
        ),
        # Atölye kaydının bileşik FK hedefi (`fk_atolye_servis_ekipman`, d2a000000002):
        # atölye kaydının ekipmanı işin ekipmanıyla aynı kalmaya ZORLANIR.
        UniqueConstraint("id", "equipment_id", name="uq_so_id_ekipman"),
        # Kiralama kurulum/toplama işi: kiralama + tür başına tek açık iş
        # (d2a000000007). TAMAMLANDI açık sayılır: yeniden açılabilir.
        Index(
            "uq_so_kiralama_tur_acik",
            "rental_id",
            "tur",
            unique=True,
            postgresql_where=text(
                "rental_id IS NOT NULL AND status NOT IN ('KAPATILDI', 'IPTAL') AND NOT is_deleted"
            ),
        ),
        Index("ix_so_sla_hedef", "cozum_hedef_at", postgresql_where=text(_ACIK_IS)),
        Index("ix_so_tekrar_aday", "tekrar_ariza_aday", postgresql_where=text("tekrar_ariza_aday")),
        Index(
            "uq_so_pb_cihaz_donem",
            "contract_item_id",
            "maintenance_period_id",
            unique=True,
            postgresql_where=text("tur = 'PB' AND NOT is_deleted"),
        ),
        Index("ix_so_durum_olusma", "status", "created_at"),
        Index("ix_so_kapanis", "closed_at"),
        Index("ix_so_birim_durum", "birim", "status"),
        Index("ix_so_musteri", "customer_id"),
        Index("ix_so_adres", "address_id"),
        Index("ix_so_ekipman", "equipment_id"),
        Index("ix_so_ilk_cozum", "first_completed_at"),
    )

    so_no: Mapped[str] = mapped_column(String(24))
    birim: Mapped[str] = mapped_column(String(20))
    tur: Mapped[str] = mapped_column(String(20))
    kategori: Mapped[str] = mapped_column(String(20))
    oncelik: Mapped[str] = mapped_column(
        String(10), server_default=text("'NORMAL'"), default="NORMAL"
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'MUSTERI_TALEBI'"), default="MUSTERI_TALEBI"
    )

    # --- Müşteri / lokasyon / irtibat (FK; ham metin yalnız göç izi) ----------
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    address_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("addresses.id", ondelete="SET NULL")
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="SET NULL")
    )
    customer_name_raw: Mapped[str | None] = mapped_column(String(250))
    location_raw: Mapped[str | None] = mapped_column(Text)
    # Kişisel veri (KVKK anonimleştirme kapsamında); olay geçmişine YAZILMAZ.
    iletisim_ad: Mapped[str | None] = mapped_column(String(120))
    iletisim_telefon: Mapped[str | None] = mapped_column(String(20))

    # --- Talep ------------------------------------------------------------
    talep_kanali: Mapped[str | None] = mapped_column(String(20))
    # Müşterinin bildirdiği an; göçte bilinmiyorsa NULL (uydurma tarih yok).
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proje: Mapped[str | None] = mapped_column(String(120))
    sistem: Mapped[str | None] = mapped_column(String(120))
    konu: Mapped[str] = mapped_column(String(200))
    aciklama: Mapped[str | None] = mapped_column(Text)

    # --- Yaşam döngüsü damgaları (yalnız durum_degistir yazar) ---------------
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    first_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    reopen_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)

    # --- Bağlar -------------------------------------------------------------
    iliskili_is_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="SET NULL")
    )
    iliski_turu: Mapped[str | None] = mapped_column(String(20))
    # Mobilite köprüsü — YALNIZ OKUNUR; servis kodu work_orders'a yazmaz.
    work_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("work_orders.id", ondelete="SET NULL")
    )
    rma_case_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("rma_cases.id", ondelete="SET NULL")
    )
    equipment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_equipment.id", ondelete="SET NULL", name="fk_so_ekipman"),
    )
    contract_item_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "maintenance_contract_items.id", ondelete="RESTRICT", name="fk_so_sozlesme_kalemi"
        ),
    )
    maintenance_period_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("maintenance_periods.id", ondelete="RESTRICT", name="fk_so_bakim_donemi"),
    )

    # --- Kapsam anlık görüntüsü (E14-17) ------------------------------------
    coverage_status: Mapped[str | None] = mapped_column(String(12))
    coverage_snapshot: Mapped[dict | None] = mapped_column(JSONB)

    # --- SLA (Dalga 2, E10-01; yalnız `services/teknik_servis/sla.py` yazar) ----
    # Hepsi NULL olabilir: SLA yürürlük anından önce açılan iş ve GUNLUK_SERVIS
    # dışı iş damgalanmaz (`servis_sla_yururluk_at`, KD-22).
    sla_policy_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("service_sla_policies.id", ondelete="RESTRICT", name="fk_so_sla_politikasi"),
    )
    # = açılış anı, Clock'tan (K1: elle girilen `reported_at` değil).
    sla_baslangic_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cozum_hedef_dk: Mapped[int | None] = mapped_column(Integer)
    mudahale_hedef_dk: Mapped[int | None] = mapped_column(Integer)
    sla_takvim_turu: Mapped[str | None] = mapped_column(String(10))
    # İlk damgalanan hedef bir daha değişmez; güncel hedef yalnız SLA durduran
    # bekleme bitince ve öncelik/birim düzeltmesinde ileri alınır (olayla).
    cozum_hedef_ilk_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cozum_hedef_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mudahale_hedef_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # İlk fiili müdahale (SAHA/UZAKTAN/ATOLYE/TEST faaliyeti ya da saha durumu).
    ilk_mudahale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # İlk TAMAMLANDI'da dondurulur; yeniden açılış SİLMEZ (E10 kontrol B3).
    sla_sonuc: Mapped[str | None] = mapped_column(String(12))
    sla_durdurulan_dk: Mapped[int | None] = mapped_column(Integer)
    sla_kaynak: Mapped[str | None] = mapped_column(String(14))
    gecikme_nedeni: Mapped[str | None] = mapped_column(String(30))
    gecikme_aciklama: Mapped[str | None] = mapped_column(String(300))
    # Tekrar arıza adayı (otomatik işaret) ve KAPATILDI'da kök neden teyidi (E10-04).
    tekrar_ariza_aday: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    tekrar_ariza_teyit: Mapped[str | None] = mapped_column(String(20))

    # --- Kiralama bağı (Dalga 2, E06-19; d2a000000007) --------------------------
    # Kurulum/toplama işi; `work_orders`'a hiçbir şey yazılmaz.
    # `use_alter`: quotes → service_orders → rentals → quotes döngüsü (metadata
    # sıralaması uyarı vermesin; migration'da FK zaten ayrı eklenir).
    rental_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("rentals.id", ondelete="SET NULL", name="fk_so_kiralama", use_alter=True),
    )

    seriler: Mapped[list["ServiceOrderSerial"]] = relationship(
        lazy="selectin",
        order_by="ServiceOrderSerial.id",
        foreign_keys="ServiceOrderSerial.service_order_id",
    )
    atamalar: Mapped[list["ServiceOrderAssignment"]] = relationship(
        lazy="selectin",
        order_by="ServiceOrderAssignment.id",
        foreign_keys="ServiceOrderAssignment.service_order_id",
    )


class ServiceOrderSerial(Base, PkMixin, TimestampMixin, ActorMixin):
    """Servis işinin seri numaraları — METİN (korunacak iş kararı).

    `seri_no` girildiği gibi (yalnız baş/son boşluk kırpılır), `seri_norm`
    tek normalizasyon fonksiyonunun çıktısıdır (`normalize_seri`, TS-011):
    baştaki sıfır ve `/-.` korunur, `i/ı/İ → I`. Mükerrer kontrolü, tekrar
    arıza ve kütük eşleşmesi yalnız `seri_norm` üzerinden yapılır.

    Seri değişince eski satır SİLİNMEZ, pasiflenir (`removed_at`): "bu işte
    önce hangi cihaz vardı" sorusu cevapsız kalmasın.
    """

    __tablename__ = "service_order_serials"
    __table_args__ = (
        Index(
            "uq_sos_aktif",
            "service_order_id",
            "seri_norm",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("is_active OR removed_at IS NOT NULL", name="ck_sos_pasif"),
        CheckConstraint("length(trim(seri_no)) > 0", name="ck_sos_seri_bos"),
        Index("ix_sos_seri_norm", "seri_norm"),
        Index("ix_sos_seri_trgm", text("seri_norm gin_trgm_ops"), postgresql_using="gin"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT"), index=True
    )
    seri_no: Mapped[str] = mapped_column(String(200))
    seri_norm: Mapped[str] = mapped_column(String(200))
    # Yalnız MOBILITE/ARAC_TAKIP'te ve kütükte bulunursa dolu; devices'a YAZILMAZ.
    device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class ServiceOrderEvent(Base, PkMixin):
    """Silinemez olay geçmişi (E01-04).

    **Yalnız PkMixin** — bilinçli istisna: tetikleyici (`trg_soe_salt_ekleme`)
    UPDATE ve DELETE'i reddeder; Timestamp/Versioned/SoftDelete mixin'leri
    güncelleme gerektirirdi. Zaman `olusma_zamani`'dır ve `Clock`'tan yazılır
    (FakeClock ile sınanabilsin; DB `now()` sınanamaz).

    `ozet` ve `veri` KİŞİSEL VERİ İÇERMEZ (irtibat adı/telefonu, imzalayan
    adı): tetikleyici yüzünden KVKK anonimleştirmesi bu satırları
    temizleyemez. Olay yazıcısı (`gecmis.olay_yaz`) bu alanları reddeder.
    `user_id` RESTRICT: canlıda kullanıcı silinmez; SET NULL bir UPDATE'e
    dönüşüp tetikleyiciye çarpardı.
    """

    __tablename__ = "service_order_events"
    __table_args__ = (
        CheckConstraint(_in("olay_turu", OLAY_TURLERI), name="ck_soe_tur"),
        Index("ix_soe_is_zaman", "service_order_id", "olusma_zamani"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    olay_turu: Mapped[str] = mapped_column(String(20))
    eski_durum: Mapped[str | None] = mapped_column(String(20))
    yeni_durum: Mapped[str | None] = mapped_column(String(20))
    ozet: Mapped[str] = mapped_column(String(500))
    veri: Mapped[dict | None] = mapped_column(JSONB)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    olusma_zamani: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ServiceHoldReason(Base, PkMixin, TimestampMixin, VersionedMixin):
    """Bekleme nedeni kataloğu (E10-03, KD-14) — tohumlu, `operasyon.yonet` düzenler.

    **Neden tablo, CHECK değil:** SLA'yı durdurup durdurmadığı nedenle birlikte
    tek kaynakta durmalı; CHECK ile kod listesi + ayrı bir bayrak sözlüğü iki
    yerde ayrışırdı. `sadece_sistem` nedenler (BAKIM_UYGUNSUZLUK) ekrandan
    seçilemez, yalnız servis fonksiyonu açar.

    **ActorMixin YOK — bilinçli:** testler her koşuda `users` tablosunu
    `TRUNCATE ... CASCADE` ile boşaltıyor; users'a FK'si olan tablo da
    boşalır ve migration tohumu kaybolurdu. Kim değiştirdi bilgisi denetim
    izindedir (`audit.log`). Silinmez; `is_active=false` ile kapanır.
    """

    __tablename__ = "service_hold_reasons"
    __table_args__ = (UniqueConstraint("kod", name="uq_shr_kod"),)

    kod: Mapped[str] = mapped_column(String(30))
    ad: Mapped[str] = mapped_column(String(80))
    sla_durdurur: Mapped[bool] = mapped_column(Boolean)
    aciklama_zorunlu: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    sadece_sistem: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    sira: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class ServiceHold(Base, PkMixin, TimestampMixin, VersionedMixin):
    """İş beklemesi (E01-05 + E10 ek kolonları).

    Tek aktif bekleme (`uq_hold_aktif`). `sla_durdurur` açılışta katalogdan
    DONDURULUR: katalog sonradan değişse de geçmiş beklemenin SLA etkisi
    değişmez. `onceki_durum`, `beklemeyi_bitir`'in döneceği durumdur.
    Satır silinmez; kapanış `released_at` + `sure_dk` ile izlenir.
    """

    __tablename__ = "service_holds"
    __table_args__ = (
        Index(
            "uq_hold_aktif",
            "service_order_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        CheckConstraint("released_at IS NULL OR released_at >= started_at", name="ck_hold_aralik"),
        CheckConstraint("(released_at IS NULL) = (sure_dk IS NULL)", name="ck_hold_sure"),
        CheckConstraint("neden <> 'DIGER' OR aciklama IS NOT NULL", name="ck_hold_diger_aciklama"),
        CheckConstraint(_in("onceki_durum", SERVIS_DURUMLARI), name="ck_hold_onceki_durum"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    neden: Mapped[str] = mapped_column(
        String(30), ForeignKey("service_hold_reasons.kod", ondelete="RESTRICT")
    )
    aciklama: Mapped[str | None] = mapped_column(String(500))
    onceki_durum: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Açılışta clock.now()'dan eski olamaz (servis 400).
    beklenen_bitis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_durdurur: Mapped[bool] = mapped_column(Boolean)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL = worker / otomatik kapanış.
    released_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    sure_dk: Mapped[int | None] = mapped_column(Integer)
    sla_kayma_dk: Mapped[int | None] = mapped_column(Integer)
    kapanis_notu: Mapped[str | None] = mapped_column(String(200))
    otomatik_kapandi: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # Dalga 2 (E07-14, d2a000000005): aktif TEKLIF beklemesine bağlı teklif.
    # Kabulde yalnız eşleşen bekleme kapanır; ikinci bir neden açılmaz.
    quote_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("quotes.id", ondelete="SET NULL", name="fk_hold_teklif")
    )


class ServiceFaultReason(Base, PkMixin, TimestampMixin, VersionedMixin):
    """Birim bazlı arıza nedeni kataloğu (E01-06) — `servis.tanim` düzenler.

    ActorMixin yok: `ServiceHoldReason` ile aynı gerekçe (tohum test
    temizliğinde kaybolmasın); değişiklik denetim izine yazılır.
    """

    __tablename__ = "service_fault_reasons"
    __table_args__ = (
        CheckConstraint(birim_check("birim"), name="ck_sfr_birim"),
        UniqueConstraint("birim", "ad", name="uq_sfr_birim_ad"),
    )

    birim: Mapped[str] = mapped_column(String(20))
    ad: Mapped[str] = mapped_column(String(80))
    sira: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class ServiceResult(Base, PkMixin, TimestampMixin, ActorMixin):
    """Ziyaret/işlem sonucu (E01-06).

    Sonuçsuz TAMAMLANDI yoktur; çözüm kanalı NOT NULL (raporun "uzaktan
    çözülen" oranı buna dayanır). Yeniden açılışta önceki sonuç SİLİNMEZ,
    `gecersiz_at` ile geçersiz kılınır.
    """

    __tablename__ = "service_results"
    __table_args__ = (
        CheckConstraint(_in("sonuc", SERVIS_SONUCLARI), name="ck_sr_sonuc"),
        CheckConstraint(_in("cozum_kanali", COZUM_KANALLARI), name="ck_sr_kanal"),
        CheckConstraint("length(trim(yapilan_islem)) > 0", name="ck_sr_islem_bos"),
        CheckConstraint(
            _in("kutuk_fark_durumu", KUTUK_FARK_DURUMLARI, bos=True), name="ck_sr_kutuk_fark"
        ),
        Index("ix_sr_is", "service_order_id"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    sonuc: Mapped[str] = mapped_column(String(20))
    cozum_kanali: Mapped[str] = mapped_column(String(10))
    yapilan_islem: Mapped[str] = mapped_column(Text)
    ariza_nedeni_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_fault_reasons.id", ondelete="RESTRICT")
    )
    # Sahada görülen seri/bölge kütükten farklıysa (E03-14; arızada tek kaynak).
    saha_seri_no: Mapped[str | None] = mapped_column(String(200))
    saha_bolge: Mapped[str | None] = mapped_column(String(120))
    kutuk_fark_durumu: Mapped[str | None] = mapped_column(String(12))
    gecersiz_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gecersiz_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class ServiceOrderAssignment(Base, PkMixin, TimestampMixin):
    """Kimlik bazlı çoklu atama (E01-12, TS-025).

    Eski sistem atamayı AD METNİ ile tutuyordu; kişi bazlı her sayı yanlıştı.
    Satır silinmez: çıkarılan kişi `removed_at` alır, atama geçmişi kalır
    (KENDI_ISLERI kapsamı yalnız AKTİF atamaya bakar). Tek sorumlu
    teknisyen (`uq_soa_tek_sorumlu`), sorumlu yalnız TEKNISYEN rolünde.
    """

    __tablename__ = "service_order_assignments"
    __table_args__ = (
        CheckConstraint(_in("rol", ATAMA_ROLLERI), name="ck_soa_rol"),
        CheckConstraint("NOT is_lead OR rol = 'TEKNISYEN'", name="ck_soa_sorumlu_teknisyen"),
        Index(
            "uq_soa_aktif",
            "service_order_id",
            "user_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index(
            "uq_soa_tek_sorumlu",
            "service_order_id",
            unique=True,
            postgresql_where=text("is_lead AND removed_at IS NULL"),
        ),
        Index("ix_soa_kullanici_aktif", "user_id", postgresql_where=text("removed_at IS NULL")),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    rol: Mapped[str] = mapped_column(String(10))
    is_lead: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class ServiceApproval(Base, PkMixin, TimestampMixin, ActorMixin):
    """Müşteri onayı — DEĞİŞMEZ (E01-08, E04-15).

    Yeni onay eskisini geçersiz kılar (`gecersiz_kilan_id` yeni satırda);
    eski satır değişmez. Ziyaret onayı tek transaction'da aynı müşteri +
    adres + gündeki işlere `onay_grubu` ile bağlanır (TS-036). İmza PNG'si
    mevcut `IMZA` ek türüyle tutulur (`MUSTERI_IMZASI` açılmaz).
    `approved_at` sunucu Clock'undan; istemciden alınmaz.
    """

    __tablename__ = "service_approvals"
    __table_args__ = (
        CheckConstraint(_in("tur", ONAY_TURLERI), name="ck_sa_tur"),
        CheckConstraint("tur NOT IN ('IMZA', 'BASILI_FORM') OR ek_id IS NOT NULL", name="ck_sa_ek"),
        CheckConstraint("tur <> 'ALINAMADI' OR eksik_nedeni IS NOT NULL", name="ck_sa_neden"),
        Index("ix_sa_is", "service_order_id"),
        Index("ix_sa_grup", "onay_grubu"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    tur: Mapped[str] = mapped_column(String(12))
    # Kişisel veri (KVKK anonimleştirme kapsamında).
    imzalayan_ad: Mapped[str | None] = mapped_column(String(120))
    imzalayan_unvan: Mapped[str | None] = mapped_column(String(80))
    ek_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    eksik_nedeni: Mapped[str | None] = mapped_column(String(300))
    gecersiz_kilan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_approvals.id", ondelete="SET NULL")
    )
    onay_grubu: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ServiceTimeEntry(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Saha zaman kaydı (E09-01) — bordro DEĞİL, iş süresi.

    **Kişi aynı anda iki yerde olamaz:** `ex_ste_kisi_cakisma` (yarı açık
    `[)` aralık: ardışık bölümler aynı saniyede bitip başlayabilir) ve kişi
    başına tek açık sayaç `uq_ste_acik_kisi`. Açık bölümün bitişi NULL =
    sonsuz; çalışan sayacın başlangıcından sonraya manuel kayıt girilemez.
    Servis katmanı yazmadan önce çakışanı sorgular ve okunur mesaj verir;
    kısıtlar yarış durumunun son savunmasıdır.

    **İptal = yumuşak silme** (`is_deleted` + `iptal_turu`), fiziksel silme
    yok. Kaydı düzelten kişi `updated_by`'dır (ayrı kolon açılmadı, E09 B16).
    `girildi_at` Clock'tandır: gecikmeli manuel kayıt ölçüsü FakeClock ile
    sınanabilsin (`created_at` DB saatidir).

    Kayıt yoksa iş "süre eksik"tir, 0 değil (korunacak iş kararı); bu tablo
    boşken hiçbir hesap 0 dakika üretmez.
    """

    __tablename__ = "service_time_entries"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_ste_kaynak"),
        CheckConstraint(_in("faaliyet", ZAMAN_FAALIYETLERI), name="ck_ste_faaliyet"),
        CheckConstraint(_in("kaynak", ZAMAN_KAYNAKLARI), name="ck_ste_kaynak"),
        CheckConstraint(
            _in("kapanis_turu", ZAMAN_KAPANIS_TURLERI, bos=True), name="ck_ste_kapanis"
        ),
        CheckConstraint(_in("iptal_turu", ZAMAN_IPTAL_TURLERI, bos=True), name="ck_ste_iptal_turu"),
        CheckConstraint(
            "faaliyet <> 'BEKLEME' OR bekleme_nedeni IS NOT NULL", name="ck_ste_bekleme_neden"
        ),
        CheckConstraint(
            "kaynak NOT IN ('KULLANICI_DUZELTMESI', 'YONETICI_DUZELTMESI') OR gerekce IS NOT NULL",
            name="ck_ste_duzeltme_gerekce",
        ),
        CheckConstraint(
            "iptal_turu NOT IN ('YONETICI_IPTAL', 'KAYIT_IPTAL') OR iptal_gerekcesi IS NOT NULL",
            name="ck_ste_iptal_gerekce",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_ste_aralik"),
        # 18 saatlik bölüm sınırı kod sabitidir, ayar değil (plan §1.9).
        CheckConstraint(
            "ended_at IS NULL OR ended_at <= started_at + interval '18 hours'",
            name="ck_ste_azami_sure",
        ),
        CheckConstraint(
            "ended_at IS NOT NULL OR kaynak = 'CANLI'", name="ck_ste_acik_yalniz_canli"
        ),
        CheckConstraint("is_deleted = (iptal_turu IS NOT NULL)", name="ck_ste_iptal"),
        CheckConstraint(
            "user_id IS NOT NULL "
            "OR (source_system IS NOT NULL AND kaynak_personel_adi IS NOT NULL)",
            name="ck_ste_kisi",
        ),
        Index(
            "uq_ste_acik_kisi",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL AND is_deleted = false"),
        ),
        ExcludeConstraint(
            ("user_id", "="),
            (_SURE_ARALIGI, "&&"),
            name="ex_ste_kisi_cakisma",
            using="gist",
            where=text("is_deleted = false AND user_id IS NOT NULL"),
        ),
        Index("ix_ste_is_baslangic", "service_order_id", "started_at"),
        Index("ix_ste_kisi_baslangic", "user_id", "started_at"),
        Index("ix_ste_girildi", "girildi_at"),
    )

    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="RESTRICT")
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT")
    )
    # Yalnız göç: eşleşmeyen eski ad metni (kişisel veri).
    kaynak_personel_adi: Mapped[str | None] = mapped_column(String(100))
    faaliyet: Mapped[str] = mapped_column(String(20))
    # Bekleme faaliyetinde neden — bekleme kataloğuyla aynı sözlük (FK).
    bekleme_nedeni: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("service_hold_reasons.kod", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Server default YOK: her INSERT kaynağını açıkça yazar.
    kaynak: Mapped[str] = mapped_column(String(24))
    kapanis_turu: Mapped[str | None] = mapped_column(String(16))
    gerekce: Mapped[str | None] = mapped_column(String(300))
    onceki_bolum_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_time_entries.id", ondelete="SET NULL")
    )
    girildi_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Serbest metin; GPS yok (KVKK, ürün kararı).
    konum_notu: Mapped[str | None] = mapped_column(String(200))
    aciklama: Mapped[str | None] = mapped_column(Text)
    iptal_turu: Mapped[str | None] = mapped_column(String(20))
    iptal_gerekcesi: Mapped[str | None] = mapped_column(String(300))


class ServiceAlert(Base, PkMixin, TimestampMixin):
    """Kalıcı SLA bildirimi (E10-05) — DAR olay günlüğü.

    **Rozet sayısı bu tablodan sayılmaz:** `uyarilar.topla` anlık hesaplar
    (canlı ilke "uyarılar hesaplanır"). Tablo yalnız "görüldü" işareti ve
    e-posta tekilliği içindir. Birim/müşteri denormalize EDİLMEZ (plan §6.3):
    kapsam okuma anında `service_orders` JOIN'iyle uygulanır, böylece iş
    birimi değişince bildirim yeni kapsamda görünür. Alıcı listesi
    saklanmaz. Yumuşak silme yok; eski satırları worker temizler.
    """

    __tablename__ = "service_alerts"
    __table_args__ = (
        CheckConstraint(_in("kod", SLA_UYARI_KODLARI), name="ck_salert_kod"),
        CheckConstraint(_in("onem", SLA_UYARI_ONEMLERI), name="ck_salert_onem"),
        CheckConstraint("kapanis_at IS NULL OR kapanis_at >= acilis_at", name="ck_salert_aralik"),
        # Aynı iş için aynı koddan tek AÇIK bildirim: 5 dakikalık üretim
        # tekrar koşsa da çoğalmaz (ON CONFLICT DO NOTHING).
        Index(
            "uq_salert_acik",
            "kod",
            "service_order_id",
            unique=True,
            postgresql_where=text("kapanis_at IS NULL"),
        ),
        Index("ix_salert_is", "service_order_id"),
        Index("ix_salert_acilis", "acilis_at"),
    )

    kod: Mapped[str] = mapped_column(String(30))
    service_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="CASCADE")
    )
    onem: Mapped[str] = mapped_column(String(10))
    # Kişisel veri içermez (iş no + kod); irtibat adı yazılmaz.
    baslik: Mapped[str] = mapped_column(String(200))
    acilis_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kapanis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kapanis_nedeni: Mapped[str | None] = mapped_column(String(30))


class ServiceAlertRead(Base):
    """Bildirimin kullanıcı tarafından görülmesi — tek INSERT … ON CONFLICT
    DO NOTHING; satır değişmez (E10-05)."""

    __tablename__ = "service_alert_reads"
    __table_args__ = (PrimaryKeyConstraint("alert_id", "user_id", name="pk_salert_okundu"),)

    alert_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_alerts.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    goruldu_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ServiceNotificationPref(Base, TimestampMixin):
    """Kullanıcının servis e-posta tercihi (E10-06, TS-200; Dalga 3, D3-S).

    Satır yoksa iki tercih de KAPALI sayılır (varsayılan e-posta yok). Yalnız
    kendi satırı okunur/yazılır (`/bildirim-tercihlerim`). Alıcı listesi
    saklanmaz; e-postayı kimin alacağı gönderim anında `servis.gor` + kapsam
    yardımcılarıyla hesaplanır (E10 K4).
    """

    __tablename__ = "service_notification_prefs"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    anlik_eposta: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    gunluk_ozet: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )


class ServiceMailOutbox(Base, PkMixin, TimestampMixin):
    """Servis e-posta giden kutusu (E10-06, TS-200; Dalga 3, D3-S).

    Tekillik şemada: aynı bildirim aynı kişiye bir kez (`uq_smo_anlik`), kişi
    başına günde bir özet (`uq_smo_ozet`) — worker kaç tur koşarsa koşsun.
    `son_hata`'ya SMTP parolası/kullanıcı adı YAZILMAZ (yalnız istisna sınıf
    adı + sunucu:port). Gövdede fiyat/maliyet ve iletişim telefonu yok.
    `alici` kişisel veridir: saklama süresi worker temizliğiyle sınırlıdır
    (KVKK). GERIYE_DONUK damgalı işe e-posta üretilmez (servis kuralı).
    """

    __tablename__ = "service_mail_outbox"
    __table_args__ = (
        CheckConstraint(_in("tur", EPOSTA_TURLERI), name="ck_smo_tur"),
        CheckConstraint(_in("durum", EPOSTA_DURUMLARI), name="ck_smo_durum"),
        CheckConstraint(f"deneme >= 0 AND deneme <= {EPOSTA_AZAMI_DENEME}", name="ck_smo_deneme"),
        CheckConstraint("tur <> 'GUNLUK_OZET' OR ozet_gunu IS NOT NULL", name="ck_smo_ozet_gunu"),
        CheckConstraint(
            "(durum = 'GONDERILDI') = (gonderildi_at IS NOT NULL)", name="ck_smo_gonderildi"
        ),
        Index(
            "uq_smo_anlik",
            "alert_id",
            "user_id",
            unique=True,
            postgresql_where=text("tur = 'ANLIK'"),
        ),
        Index(
            "uq_smo_ozet",
            "user_id",
            "ozet_gunu",
            unique=True,
            postgresql_where=text("tur = 'GUNLUK_OZET'"),
        ),
        Index("ix_smo_bekleyen", "created_at", postgresql_where=text("durum = 'BEKLIYOR'")),
    )

    tur: Mapped[str] = mapped_column(String(12))
    # Bildirim temizlenince (90 gün) satır kalır, bağ düşer.
    alert_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_alerts.id", ondelete="SET NULL")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    ozet_gunu: Mapped[date | None] = mapped_column(Date)
    alici: Mapped[str] = mapped_column(String(160))
    konu: Mapped[str] = mapped_column(String(200))
    govde: Mapped[str] = mapped_column(Text)
    durum: Mapped[str] = mapped_column(
        String(12), server_default=text("'BEKLIYOR'"), default="BEKLIYOR"
    )
    deneme: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    son_hata: Mapped[str | None] = mapped_column(String(300))
    gonderildi_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Seri anahtarı tek normalizasyon fonksiyonundan (TS-011 `normalize_seri`).
@event.listens_for(ServiceOrderSerial, "before_insert")
@event.listens_for(ServiceOrderSerial, "before_update")
def _seri_anahtari(_mapper, _connection, target: ServiceOrderSerial) -> None:
    target.seri_no = target.seri_no.strip()
    target.seri_norm = _normalize.normalize_seri(target.seri_no)


__all__ = [
    "ATAMA_ROLLERI",
    "BIRIM_KODLARI",
    "COZUM_KANALLARI",
    "DURUM_GRUPLARI",
    "EPOSTA_ANLIK_KODLAR",
    "EPOSTA_AZAMI_DENEME",
    "EPOSTA_DURUMLARI",
    "EPOSTA_TURLERI",
    "ServiceMailOutbox",
    "ServiceNotificationPref",
    "GECIKME_NEDENLERI",
    "ILISKI_TURLERI",
    "SLA_DURUMLARI",
    "SLA_KAYNAKLARI",
    "SLA_SONUCLARI",
    "SLA_TAKVIM_TURLERI",
    "SLA_UYARI_KODLARI",
    "SLA_UYARI_ONEMLERI",
    "TEKRAR_ARIZA_TEYITLERI",
    "VARSAYILAN_SLA_POLITIKALARI",
    "ServiceAlert",
    "ServiceAlertRead",
    "ServiceSlaPolicy",
    "KAPSAM_DURUMLARI",
    "KISI_SAATE_DAHIL",
    "KUTUK_FARK_DURUMLARI",
    "OLAY_TURLERI",
    "ONAY_TURLERI",
    "ONCELIKLER",
    "SAHA_AKIS",
    "SERVIS_DURUMLARI",
    "SERVIS_KATEGORILERI",
    "SERVIS_SONUCLARI",
    "SERVIS_TURLERI",
    "TALEP_KANALLARI",
    "VARSAYILAN_ARIZA_NEDENLERI",
    "VARSAYILAN_BEKLEME_NEDENLERI",
    "ZAMAN_FAALIYETLERI",
    "ZAMAN_IPTAL_TURLERI",
    "ZAMAN_KAPANIS_TURLERI",
    "ZAMAN_KAYNAKLARI",
    "ServiceApproval",
    "ServiceFaultReason",
    "ServiceHold",
    "ServiceHoldReason",
    "ServiceOrder",
    "ServiceOrderAssignment",
    "ServiceOrderEvent",
    "ServiceOrderSerial",
    "ServiceResult",
    "ServiceTimeEntry",
    "durum_grubu",
]
