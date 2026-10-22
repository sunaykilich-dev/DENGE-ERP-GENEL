"""Eğitim, yetkinlik ve saha gözlemi (E08).

**Kişi = `users`** (ayrı personel tablosu AÇILMAZ, KD/E13 K-01): eğitimin
öznesi `users.id`'dir; birimi `user_units`'ten okunur. Girişsiz saha personeli
`users.giris_acik=false`, ayrılan personel `ayrilis_tarihi` doludur (E13).

**Hesaplanan, saklanmayan:** 30/60/90 takibi, belge geçerliliği, güncel
yetkinlik (`DISTINCT ON`), uyarılar. Yetkinlik değerlendirmesi SADECE EKLEME
(geçmiş kaybolmaz); düzeltme yeni satırdır.

**Gözlem sonucu sunucuda hesaplanır** (E08-05): kritik madde 0 → KRITIK, sonra
EKSIK_GOZLEM, ≥ eşik → BASARILI, değilse GELISIM_GEREKLI. Kritik İSG
uygunsuzluğu gözlem başına tek düzeltici faaliyet açar (`uq_tca_gozlem`);
kritik kriter ayrı tabloda tutulmaz, gözlemin `puan=0` kritik maddelerinden
türetilir.

Fiyat/maliyet alanı YOK. Kişisel performans ayrıntısı (gözlem notu, madde
puanı, aksiyon planı, kanıt, belge no) yalnız `egitim.detay` sahibine döner.
`training_observations.service_order_id` doğrudan bu çekirdekte (plan §6.2).
Durumlar `EGITIM_PLANI` ve `DUZELTICI_FAALIYET` makineleriyle ilerler.
"""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import (
    ActorMixin,
    PkMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    VersionedMixin,
)
from app.models.rbac import birim_check
from app.models.teknik_servis import SERVIS_TURLERI

EGITIM_KATEGORILERI = ("TEKNIK", "ISG", "KISISEL_GELISIM", "IS_SURECI")
PLAN_DURUMLARI = ("PLANLANDI", "ERTELENDI", "BASARISIZ_TEKRAR", "TAMAMLANDI", "IPTAL")
GOZLEM_ASAMALARI = (0, 30, 60, 90)
GOZLEM_SONUCLARI = ("KRITIK", "EKSIK_GOZLEM", "BASARILI", "GELISIM_GEREKLI")
# -1 = gözlenmedi (gerekçeli), 0 = yapmadı, 1 = kısmen, 2 = tam.
MADDE_PUANLARI = (-1, 0, 1, 2)
DUZELTICI_DURUMLARI = ("ACIK", "KAPATILDI")
DUZELTICI_KAPANIS_TURLERI = ("MANUEL", "OTOMATIK_GOZLEM")
YETKINLIK_KAYNAKLARI = ("GOZLEM", "SINAV", "YONETICI", "GOC")


def _in(sutun: str, degerler: tuple, *, bos: bool = False) -> str:
    liste = ", ".join(f"'{d}'" if isinstance(d, str) else str(d) for d in degerler)
    return f"{sutun} IS NULL OR {sutun} IN ({liste})" if bos else f"{sutun} IN ({liste})"


class TrainingCourse(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Eğitim kataloğu (kurs). Birim NULL = tüm birimler. Tohum migration'a
    YAZILMAZ (şirket içeriğidir); eski katalog göç betiğiyle gelir."""

    __tablename__ = "training_courses"
    __table_args__ = (
        UniqueConstraint("kod", name="uq_tc_kod"),
        UniqueConstraint("source_system", "source_ref", name="uq_tc_kaynak"),
        CheckConstraint(_in("kategori", EGITIM_KATEGORILERI), name="ck_tc_kategori"),
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_tc_birim"),
        CheckConstraint("sure_saat >= 0.5 AND sure_saat <= 24", name="ck_tc_sure"),
        CheckConstraint(
            "gozlem_esik_yuzde IS NULL OR (gozlem_esik_yuzde >= 0 AND gozlem_esik_yuzde <= 100)",
            name="ck_tc_esik",
        ),
        CheckConstraint(
            "sinav_gecme_puani IS NULL OR (sinav_gecme_puani >= 0 AND sinav_gecme_puani <= 100)",
            name="ck_tc_sinav",
        ),
        CheckConstraint(
            "yenileme_ay IS NULL OR (yenileme_ay >= 1 AND yenileme_ay <= 120)",
            name="ck_tc_yenileme",
        ),
    )

    kod: Mapped[str] = mapped_column(String(30))
    baslik: Mapped[str] = mapped_column(String(200))
    kategori: Mapped[str] = mapped_column(String(20))
    birim: Mapped[str | None] = mapped_column(String(20))
    sure_saat: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    zorunlu: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    neden: Mapped[str | None] = mapped_column(Text)
    hedef_davranis: Mapped[str | None] = mapped_column(Text)
    basari_olcutu: Mapped[str | None] = mapped_column(Text)
    gozlem_esik_yuzde: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    sinav_gecme_puani: Mapped[int | None] = mapped_column(Integer)
    yenileme_ay: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class TrainingCriterion(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin, SourceMixin):
    """Kursun gözlem maddesi. Silme ucu yok, yalnız pasifleme."""

    __tablename__ = "training_criteria"
    __table_args__ = (
        UniqueConstraint("course_id", "sira", name="uq_tcr_kurs_sira"),
        UniqueConstraint("source_system", "source_ref", name="uq_tcr_kaynak"),
        CheckConstraint("sira > 0", name="ck_tcr_sira"),
    )

    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="RESTRICT")
    )
    sira: Mapped[int] = mapped_column(Integer)
    metin: Mapped[str] = mapped_column(String(300))
    is_critical: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class TrainingSession(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Eğitim oturumu. İleri tarih kontrolü serviste (yerel gün, Clock).
    Katılımsız oturum yumuşak silinebilir; katılımlı oturum 409."""

    __tablename__ = "training_sessions"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_ts_kaynak"),
        CheckConstraint("sure_saat >= 0.5 AND sure_saat <= 24", name="ck_ts_sure"),
        Index("ix_ts_kurs_tarih", "course_id", "oturum_tarihi"),
    )

    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="RESTRICT")
    )
    oturum_tarihi: Mapped[date] = mapped_column(Date)
    egitmen_ad: Mapped[str | None] = mapped_column(String(120))
    egitmen_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    sure_saat: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    yer: Mapped[str | None] = mapped_column(String(200))
    notlar: Mapped[str | None] = mapped_column(Text)


class TrainingPlan(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Kişi + kurs + yıl eğitim planı (E08-02/04).

    Tekillik İPTAL'i dışlar: iptal edilen yıl yeniden planlanabilir (E08
    kontrol §2/3). Toplu planda mükerrer atlama indeks çıkarımıyla:
    `ON CONFLICT (user_id, course_id, plan_yili) WHERE NOT is_deleted AND
    status <> 'IPTAL' DO NOTHING`. TAMAMLANDI → PLANLANDI geri dönüşünde
    `completed_on/completed_session_id` NULL yapılır.
    """

    __tablename__ = "training_plans"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_tp_kaynak"),
        CheckConstraint(_in("status", PLAN_DURUMLARI), name="ck_tp_durum"),
        CheckConstraint(
            "status NOT IN ('ERTELENDI', 'IPTAL') OR durum_gerekcesi IS NOT NULL",
            name="ck_tp_gerekce",
        ),
        CheckConstraint("(status = 'TAMAMLANDI') = (completed_on IS NOT NULL)", name="ck_tp_tamam"),
        CheckConstraint("plan_yili >= 2020 AND plan_yili <= 2100", name="ck_tp_yil"),
        Index(
            "uq_tp_kisi_kurs_yil",
            "user_id",
            "course_id",
            "plan_yili",
            unique=True,
            postgresql_where=text("NOT is_deleted AND status <> 'IPTAL'"),
        ),
        Index("ix_tp_yil_durum", "plan_yili", "status"),
        Index("ix_tp_kisi", "user_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="RESTRICT")
    )
    plan_yili: Mapped[int] = mapped_column(Integer)
    hedef_tarih: Mapped[date] = mapped_column(Date)
    gelisim_hedefi: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'PLANLANDI'"), default="PLANLANDI"
    )
    durum_gerekcesi: Mapped[str | None] = mapped_column(String(500))
    onceki_hedef_tarih: Mapped[date | None] = mapped_column(Date)
    completed_on: Mapped[date | None] = mapped_column(Date)
    completed_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_sessions.id", ondelete="SET NULL")
    )


class TrainingAttendance(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin, SourceMixin):
    """Oturum katılımı. Düzeltme PATCH'tir, silme yok."""

    __tablename__ = "training_attendance"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_ta_oturum_kisi"),
        UniqueConstraint("source_system", "source_ref", name="uq_ta_kaynak"),
        CheckConstraint(
            "(on_puan IS NULL OR (on_puan >= 0 AND on_puan <= 100)) AND "
            "(son_puan IS NULL OR (son_puan >= 0 AND son_puan <= 100))",
            name="ck_ta_puan",
        ),
        Index("ix_ta_kisi", "user_id"),
    )

    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_sessions.id", ondelete="RESTRICT")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    katildi: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    on_puan: Mapped[int | None] = mapped_column(Integer)
    son_puan: Mapped[int | None] = mapped_column(Integer)
    notlar: Mapped[str | None] = mapped_column(Text)


class TrainingObservation(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Saha gözlemi (0/30/60/90 aşaması). Öz-gözlem 409 (servis). Birim,
    servis işinden anlık görüntüdür. İptal yumuşak: `cancel_*` birlikte."""

    __tablename__ = "training_observations"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_tob_kaynak"),
        CheckConstraint(_in("asama", GOZLEM_ASAMALARI), name="ck_tob_asama"),
        CheckConstraint(_in("sonuc", GOZLEM_SONUCLARI), name="ck_tob_sonuc"),
        CheckConstraint("(cancelled_at IS NULL) = (cancel_reason IS NULL)", name="ck_tob_iptal"),
        CheckConstraint("puan IS NULL OR (puan >= 0 AND puan <= 100)", name="ck_tob_puan"),
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_tob_birim"),
        CheckConstraint(
            "observer_user_id IS NULL OR observer_user_id <> user_id", name="ck_tob_oz_gozlem"
        ),
        Index("ix_tob_kisi_kurs_asama", "user_id", "course_id", "asama"),
        Index("ix_tob_servis", "service_order_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="RESTRICT")
    )
    plan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_plans.id", ondelete="SET NULL")
    )
    asama: Mapped[int] = mapped_column(SmallInteger)
    gozlem_tarihi: Mapped[date] = mapped_column(Date)
    observer_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Göç/gösterim için ad (eşleşmeyen eski gözlemci).
    gozlemci_ad: Mapped[str | None] = mapped_column(String(100))
    service_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_orders.id", ondelete="SET NULL")
    )
    birim: Mapped[str | None] = mapped_column(String(20))
    puan: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    sonuc: Mapped[str] = mapped_column(String(20))
    kritik: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    notlar: Mapped[str | None] = mapped_column(Text)
    aksiyon_plani: Mapped[str | None] = mapped_column(Text)
    sonraki_izleme: Mapped[date | None] = mapped_column(Date)
    # Personelin "Gördüm" onayı — geri alınamaz (E08-09).
    gordu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    personel_yorumu: Mapped[str | None] = mapped_column(String(900))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(300))


class TrainingObservationRating(Base, PkMixin, TimestampMixin):
    """Gözlemin madde puanı. Kritik madde kuralı serviste (tablo arası)."""

    __tablename__ = "training_observation_ratings"
    __table_args__ = (
        UniqueConstraint("observation_id", "criterion_id", name="uq_tor_gozlem_madde"),
        CheckConstraint(_in("puan", MADDE_PUANLARI), name="ck_tor_puan"),
        CheckConstraint("puan <> -1 OR gozlenmedi_gerekcesi IS NOT NULL", name="ck_tor_gozlenmedi"),
    )

    observation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_observations.id", ondelete="CASCADE")
    )
    criterion_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_criteria.id", ondelete="RESTRICT")
    )
    puan: Mapped[int] = mapped_column(SmallInteger)
    gozlenmedi_gerekcesi: Mapped[str | None] = mapped_column(String(300))


class TrainingCorrectiveAction(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Kritik İSG uygunsuzluğu düzeltici faaliyeti — gözlem başına tek (E08-07).

    Otomatik kapanış: aynı kişi+kursta kritik maddeleri 2 olan sonraki gözlem
    (`closing_observation_id`). Görev kartı etiketi kişisel alan İÇERMEZ.
    """

    __tablename__ = "training_corrective_actions"
    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_tca_gozlem"),
        CheckConstraint(_in("status", DUZELTICI_DURUMLARI), name="ck_tca_durum"),
        CheckConstraint(
            _in("kapanis_turu", DUZELTICI_KAPANIS_TURLERI, bos=True), name="ck_tca_kapanis_turu"
        ),
        CheckConstraint(
            "(status <> 'KAPATILDI' OR (kapanis_turu IS NOT NULL AND closed_at IS NOT NULL)) "
            "AND (kapanis_turu IS DISTINCT FROM 'MANUEL' "
            "OR length(trim(coalesce(kapanis_kaniti, ''))) > 0) "
            "AND (kapanis_turu IS DISTINCT FROM 'OTOMATIK_GOZLEM' "
            "OR closing_observation_id IS NOT NULL)",
            name="ck_tca_kapanis",
        ),
        Index("ix_tca_acik", "user_id", "course_id", postgresql_where=text("status = 'ACIK'")),
    )

    observation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_observations.id", ondelete="RESTRICT")
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="RESTRICT")
    )
    sorumlu_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    termin: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), server_default=text("'ACIK'"), default="ACIK")
    kapanis_turu: Mapped[str | None] = mapped_column(String(20))
    closing_observation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_observations.id", ondelete="SET NULL")
    )
    kapanis_kaniti: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class Competency(
    Base, PkMixin, TimestampMixin, ActorMixin, SoftDeleteMixin, VersionedMixin, SourceMixin
):
    """Yetkinlik kataloğu. Başka birimin yetkinliğine yazma 403 (E08-16)."""

    __tablename__ = "competencies"
    __table_args__ = (
        UniqueConstraint("kod", name="uq_cmp_kod"),
        UniqueConstraint("source_system", "source_ref", name="uq_cmp_kaynak"),
        CheckConstraint("onerilen_hedef >= 1 AND onerilen_hedef <= 4", name="ck_cmp_hedef"),
        CheckConstraint(birim_check("birim", bos_olabilir=True), name="ck_cmp_birim"),
    )

    kod: Mapped[str] = mapped_column(String(20))
    ad: Mapped[str] = mapped_column(String(150))
    birim: Mapped[str | None] = mapped_column(String(20))
    onerilen_hedef: Mapped[int] = mapped_column(SmallInteger, server_default=text("3"), default=3)
    is_critical: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )


class CompetencyAssessment(Base, PkMixin, TimestampMixin, ActorMixin, SourceMixin):
    """Yetkinlik değerlendirmesi — SADECE EKLEME (E08-03). Güncel seviye
    `DISTINCT ON (user_id, competency_id) ORDER BY degerlendirme_tarihi DESC,
    id DESC` ile okunur. Göç dışı kayıtta değerlendiren kimliği zorunlu."""

    __tablename__ = "competency_assessments"
    __table_args__ = (
        UniqueConstraint("source_system", "source_ref", name="uq_cas_kaynak"),
        CheckConstraint(
            "mevcut_seviye >= 1 AND mevcut_seviye <= 4 AND hedef_seviye >= 1 AND hedef_seviye <= 4",
            name="ck_cas_seviye",
        ),
        CheckConstraint(_in("kaynak", YETKINLIK_KAYNAKLARI), name="ck_cas_kaynak"),
        CheckConstraint(
            "kaynak = 'GOC' OR assessed_by_user_id IS NOT NULL", name="ck_cas_kanit_kaynak"
        ),
        CheckConstraint(
            "assessed_by_user_id IS NULL OR assessed_by_user_id <> user_id",
            name="ck_cas_oz_degerlendirme",
        ),
        Index(
            "ix_cas_son",
            "user_id",
            "competency_id",
            text("degerlendirme_tarihi DESC"),
            text("id DESC"),
        ),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    competency_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("competencies.id", ondelete="RESTRICT")
    )
    mevcut_seviye: Mapped[int] = mapped_column(SmallInteger)
    hedef_seviye: Mapped[int] = mapped_column(SmallInteger)
    degerlendirme_tarihi: Mapped[date] = mapped_column(Date)
    assessed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    assessed_by_ad: Mapped[str | None] = mapped_column(String(100))
    kanit: Mapped[str | None] = mapped_column(Text)
    kaynak: Mapped[str] = mapped_column(String(12))
    observation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_observations.id", ondelete="SET NULL")
    )
    sonraki_degerlendirme: Mapped[date | None] = mapped_column(Date)


class PersonnelCertificate(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Personel belgesi/sertifikası (E08-11). Geçerlilik hesaplanır; iptal
    yumuşak (`cancel_*` birlikte). Belge numarası üretilmez."""

    __tablename__ = "personnel_certificates"
    __table_args__ = (
        CheckConstraint(
            "gecerlilik_bitis IS NULL OR gecerlilik_bitis >= verilis_tarihi", name="ck_pc_aralik"
        ),
        CheckConstraint("(cancelled_at IS NULL) = (cancel_reason IS NULL)", name="ck_pc_iptal"),
        Index("ix_pc_bitis", "gecerlilik_bitis", postgresql_where=text("cancelled_at IS NULL")),
        Index("ix_pc_kisi", "user_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="SET NULL")
    )
    belge_adi: Mapped[str] = mapped_column(String(200))
    verilis_tarihi: Mapped[date] = mapped_column(Date)
    gecerlilik_bitis: Mapped[date | None] = mapped_column(Date)
    # Kişisel performans ayrıntısı: yalnız `egitim.detay`.
    belge_no: Mapped[str | None] = mapped_column(String(60))
    aciklama: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(300))


class CourseCompetency(Base, TimestampMixin):
    """Kurs ↔ yetkinlik bağı (E08-16 P3, TS-198; Dalga 3, D3-S).

    Bağ yalnız "yeniden değerlendir" listesini besler (K18): başarılı 90. gün
    gözlemi bağlı yetkinliği listeye düşürür; seviye KENDİLİĞİNDEN DEĞİŞMEZ.
    Kurs/yetkinlik silinirse bağ da düşer (CASCADE).
    """

    __tablename__ = "course_competencies"
    __table_args__ = (
        PrimaryKeyConstraint("course_id", "competency_id", name="pk_course_competencies"),
        Index("ix_ccmp_yetkinlik", "competency_id"),
    )

    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="CASCADE")
    )
    competency_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("competencies.id", ondelete="CASCADE")
    )


class ServiceCompetencyRequirement(Base, PkMixin, TimestampMixin, ActorMixin, VersionedMixin):
    """Servis işi türü → asgari yetkinlik eşlemesi (E08-22 P3, TS-198; D3-S).

    Atamada YALNIZ UYARI üretir (K11): eşik altındaki teknisyen yine atanır,
    yanıtta uyarı ve olay geçmişinde not olur. Eşleme boşsa uyarı yok.
    `course_id` önerilen eğitimdir (uyarı metninde gösterilir).
    """

    __tablename__ = "service_competency_requirements"
    __table_args__ = (
        UniqueConstraint("birim", "tur", "competency_id", name="uq_scr_birim_tur_yetkinlik"),
        CheckConstraint("min_seviye >= 1 AND min_seviye <= 4", name="ck_scr_seviye"),
        CheckConstraint(birim_check("birim"), name="ck_scr_birim"),
        CheckConstraint(_in("tur", SERVIS_TURLERI), name="ck_scr_tur"),
    )

    birim: Mapped[str] = mapped_column(String(20))
    tur: Mapped[str] = mapped_column(String(20))
    competency_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("competencies.id", ondelete="CASCADE")
    )
    min_seviye: Mapped[int] = mapped_column(SmallInteger)
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("training_courses.id", ondelete="SET NULL")
    )


__all__ = [
    "DUZELTICI_DURUMLARI",
    "DUZELTICI_KAPANIS_TURLERI",
    "EGITIM_KATEGORILERI",
    "GOZLEM_ASAMALARI",
    "GOZLEM_SONUCLARI",
    "MADDE_PUANLARI",
    "PLAN_DURUMLARI",
    "YETKINLIK_KAYNAKLARI",
    "Competency",
    "CompetencyAssessment",
    "CourseCompetency",
    "PersonnelCertificate",
    "ServiceCompetencyRequirement",
    "TrainingAttendance",
    "TrainingCorrectiveAction",
    "TrainingCourse",
    "TrainingCriterion",
    "TrainingObservation",
    "TrainingObservationRating",
    "TrainingPlan",
    "TrainingSession",
]
