from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PkMixin, TimestampMixin, VersionedMixin
from app.models.rbac import Role, UserPermission


class User(Base, PkMixin, TimestampMixin, VersionedMixin):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str | None] = mapped_column(String(160), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    # MFA (TOTP): totp_secret şifreli saklanır (app.crypto). mfa_enabled ancak
    # kullanıcı ilk kodu doğruladıktan sonra True olur (yarım kurulum kilitlemez).
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    totp_secret: Mapped[str | None] = mapped_column(String(200))

    # İleride bayi paneli eklenirse kullanıcı bir hesaba bağlanır ve yalnız o
    # hesabın kapsamını görür (plan §3.4). Bugün iç kullanıcılarda NULL.
    # FK hesaplar tablosu geldiğinde eklenecek — şimdilik salt sayı.
    account_id: Mapped[int | None] = mapped_column()

    role: Mapped[Role] = relationship(lazy="selectin")
    # İstisnalar kullanıcıyla BİRLİKTE yüklenir: yetki kontrolü her istekte
    # koşuyor, ayrı sorgu N+1 üretirdi.
    izin_istisnalari: Mapped[list["UserPermission"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def mfa_kurulumu_gerekli(self) -> bool:
        """MFA zorunluyken kurulmamışsa True.

        Kural BURADA, tek yerde. Daha önce `api/deps.py` ve `/auth/me` ayrı
        ayrı hesaplıyordu; `UserOut.of()` ise hiç hesaplamıyordu. Sonuç:
        GİRİŞ yanıtı bayrağı `false` döndürüyor, arayüz kullanıcıyı içeri
        alıyor ve ardından /me dışındaki HER istek 403 veriyordu. Kullanıcı
        eksiksiz bir menü görüp hiçbir şeyin açılmadığı bir ekranda kalıyordu.
        """
        from app.config import get_config

        return get_config().mfa_zorunlu and not self.mfa_enabled

    def has(self, permission_code: str) -> bool:
        """İzin var mı. Varsayılan DAİMA reddetmektir.

        Sıra: kullanıcıya özel istisna → rol. İstisna her iki yönde de
        kesindir; `allow=False` rolden gelen izni GERİ ALIR. Reddin rolün
        üstünde olması bilinçli: bir kişinin yetkisini kısmak, ona rol
        değiştirmekten daha sık ve daha acil bir ihtiyaç.
        """
        for ui in self.izin_istisnalari:
            if ui.permission_code == permission_code:
                return ui.allow
        return any(rp.permission_code == permission_code for rp in self.role.permissions)

    def etkin_izinler(self) -> list[str]:
        """Bu kullanıcının GERÇEKTEN sahip olduğu izinler, sıralı.

        `has()` ile aynı kuraldan türer. Arayüz menüyü ve butonları bu listeye
        göre çiziyor; rolün ham izin listesini döndürmek, istisnayla verilen
        yetkinin menüde hiç görünmemesine ve geri alınan yetkinin tıklanınca
        403 vermesine yol açardı.
        """
        kodlar = {rp.permission_code for rp in self.role.permissions}
        for ui in self.izin_istisnalari:
            if ui.allow:
                kodlar.add(ui.permission_code)
            else:
                kodlar.discard(ui.permission_code)
        return sorted(kodlar)


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")
