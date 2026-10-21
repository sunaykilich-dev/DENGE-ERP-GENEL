from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PkMixin, TimestampMixin


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
