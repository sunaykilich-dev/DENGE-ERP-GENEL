from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import ActorMixin, PkMixin, TimestampMixin

# Teknik servis birim KODLARI — CHECK kısıtlarının tek kaynağı.
#
# Neden burada ve `permissions.BIRIMLER` değil: modeller `permissions`'ı
# import etmez (izin kataloğu seed ve API katmanının konusudur; model →
# permissions bağı döngüsel import riski taşır). Ad sözlüğü (kod → Türkçe
# etiket) `permissions.BIRIMLER`'de durur; iki yerin AYNI kod kümesini
# taşıdığı `tests/unit/test_servis_sozluk_tutarliligi.py` ile kilitlenir.
# Kod listesi kalıcıdır: değiştirmek bütün `ck_*_birim` kısıtlarının elle
# drop+create edilmesi demektir (autogenerate CHECK değişikliğini görmez).
BIRIM_KODLARI = ("GUVENLIK", "HABERLESME", "POC", "MOBILITE", "ARAC_TAKIP")


def birim_check(sutun: str, *, bos_olabilir: bool = False) -> str:
    """`<sutun> IN ('GUVENLIK', ...)` CHECK ifadesi — her tabloda aynı liste.

    Elle yazılan kopyalar zamanla ayrışırdı (bir tabloda POC unutulurdu);
    bütün `ck_*_birim` kısıtları bu fonksiyondan üretilir.
    """
    liste = ", ".join(f"'{b}'" for b in BIRIM_KODLARI)
    ifade = f"{sutun} IN ({liste})"
    return f"{sutun} IS NULL OR {ifade}" if bos_olabilir else ifade


class Permission(Base):
    """İzin kataloğu — kaynağı `app/permissions.py`, seed ile senkronlanır."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    module: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(200))


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class UserPermission(Base):
    """Kullanıcıya ÖZEL izin istisnası — rolün üstüne ekler ya da ondan çıkarır.

    Rol yetki modelinin omurgası; bu tablo istisnadır. `allow=True` rolde
    olmayan bir izni verir, `allow=False` rolden gelen bir izni geri alır.

    **Neden gerekli:** aynı roldeki bir kişiye tek bir ek yetki vermek için
    yeni bir rol açmak, zamanla rol enflasyonu üretiyor.

    **Neden tehlikeli:** aynı roldeki iki kişi farklı şeyler görür ve sebebini
    kimse hatırlamaz. Bu yüzden her istisna GEREKÇE taşır ve arayüzde
    "rolünden farklı" rozetiyle görünür.
    """

    __tablename__ = "user_permissions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )
    allow: Mapped[bool] = mapped_column(Boolean)
    gerekce: Mapped[str | None] = mapped_column(String(300))


class Role(Base, PkMixin, TimestampMixin):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    # Kayıt bazlı kapsam: TUMU | KENDI_MUSTERILERI (bkz. app/permissions.py)
    scope: Mapped[str] = mapped_column(String(30), server_default=text("'TUMU'"))
    # Sistem rolleri seed'den gelir; silinemez, kodu değiştirilemez.
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Yönetici izinlerini ELLE değiştirdiyse seed bu role artık dokunmaz.
    # Aksi halde her açılıştaki katalog senkronu düzenlemeyi geri alırdı ve
    # kimse neden geri geldiğini anlamazdı. Bedeli: koda YENİ bir izin
    # eklendiğinde özelleştirilmiş rollere kendiliğinden inmez — seed bunu
    # log'a UYARI olarak yazar (KVKK menüsü tam böyle sessizce kaybolmuştu).
    ozellestirildi: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    permissions: Mapped[list[RolePermission]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class UserUnit(Base, TimestampMixin, ActorMixin):
    """Kullanıcı–birim üyeliği (teknik servis birim kapsamı).

    **Neden ayrı tablo, `users.birim` kolonu değil:** aynı kişi Mobilite ve
    Araç Takip'te birlikte çalışıyor; tek kolon ikinci birimi kaybederdi.
    Üyelik çoklu, ama "birincil birim" tek (`uq_user_units_birincil`):
    ekranda varsayılan birim ve rapor kırılımı buna bakar.

    **Fail-closed:** `KENDI_BIRIMI`/`KENDI_ISLERI` kapsamlı rolde bu tabloda
    satırı olmayan kullanıcı HİÇBİR servis kaydı görmez (plan §1.2). Satır
    yokluğu "hepsi" anlamına gelseydi, birimi girilmemiş yeni bir şef bütün
    birimlerin işlerini görürdü.

    Değişiklik denetime yazılır ve kullanıcının oturumları düşürülür (kapsam
    değişti) — bunu servis katmanı (`s/personel.py`) yapar.
    """

    __tablename__ = "user_units"
    __table_args__ = (
        CheckConstraint(birim_check("birim"), name="ck_user_units_birim"),
        Index(
            "uq_user_units_birincil",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    birim: Mapped[str] = mapped_column(String(20), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
