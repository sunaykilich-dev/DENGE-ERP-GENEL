from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PkMixin, TimestampMixin, VersionedMixin
from app.models.rbac import Role, UserPermission, UserUnit

# Saha rolü bir YETKİ değil, İK olgusudur: atama listeleri buna bakar, yetki
# `Role`'e. Ünvan hiçbir kurala girmez ("Sistem Mühendisi" sahada teknisyen
# olabilir). Aynı tuple `permissions.SAHA_ROLLERI` ile eşit tutulur (sözlük
# tutarlılık testi).
SAHA_ROLLERI = ("SEF", "TEKNISYEN", "STAJYER", "OFIS", "YOK")
AYRILIS_NEDENLERI = ("ISTIFA", "FESIH", "EMEKLILIK", "SOZLESME_BITIMI", "DIGER")


class User(Base, PkMixin, TimestampMixin, VersionedMixin):
    """Kullanıcı = personel kartı (teknik servis plan §1.1, E13-05).

    Ayrı `personnel` tablosu AÇILMAZ: ikinci bir kimlik kaynağı, atamada,
    zaman kaydında ve eğitimde "hangi Ali Veli?" sorusunu geri getirirdi.
    Girişi olmayan saha personeli (stajyer, sahadaki usta) de bir `users`
    satırıdır; farkı `giris_acik=false` taşır.

    **`is_active` ile `giris_acik` AYRI anlamlardır** (E13-03):
    - `is_active` = kayıt canlı (işten ayrılınca false);
    - `giris_acik` = oturum açabilir mi.
    Personeli yeniden aktifleştirmek girişi AÇMAZ; giriş ayrıca ve geçici
    parolayla açılır. Tek bayrakla ikisini birlikte açmak, çıkışı yapılmış
    birinin eski parolasıyla geri girmesine kapı aralardı.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "uq_users_sicil_no",
            "sicil_no",
            unique=True,
            postgresql_where=text("sicil_no IS NOT NULL"),
        ),
        CheckConstraint(
            "saha_rolu IS NULL OR saha_rolu IN (" + ", ".join(f"'{r}'" for r in SAHA_ROLLERI) + ")",
            name="ck_users_saha_rolu",
        ),
        CheckConstraint(
            "ayrilis_nedeni IS NULL OR ayrilis_nedeni IN ("
            + ", ".join(f"'{n}'" for n in AYRILIS_NEDENLERI)
            + ")",
            name="ck_users_ayrilis_nedeni",
        ),
        # Ayrılış tarihi ve nedeni birlikte vardır ya da birlikte yoktur:
        # nedensiz çıkış raporda "bilinmiyor" sayısını sessizce şişirirdi.
        CheckConstraint(
            "(ayrilis_tarihi IS NULL) = (ayrilis_nedeni IS NULL)",
            name="ck_users_ayrilis",
        ),
        CheckConstraint(
            "yonetici_id IS NULL OR yonetici_id <> id", name="ck_users_yonetici_kendisi"
        ),
    )

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

    # --- Personel (teknik servis, E13 §2.2.1) ---------------------------------
    # Hepsi nullable ya da varsayılanlı: mevcut kullanıcılar etkilenmez,
    # birim/saha rolü göçte UYDURULMAZ.
    giris_acik: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    sicil_no: Mapped[str | None] = mapped_column(String(30))
    unvan: Mapped[str | None] = mapped_column(String(80))
    saha_rolu: Mapped[str | None] = mapped_column(String(12))
    ise_giris_tarihi: Mapped[date | None] = mapped_column(Date)
    ayrilis_tarihi: Mapped[date | None] = mapped_column(Date)
    ayrilis_nedeni: Mapped[str | None] = mapped_column(String(20))
    ayrilisi_yapan_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_users_ayrilisi_yapan")
    )
    # Döngü (A→B→A) servis katmanında engellenir; şemada yalnız "kendisi değil".
    yonetici_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", name="fk_users_yonetici")
    )
    # Yalnız `personel.yaz` sahibine döner (kişisel not).
    personel_notu: Mapped[str | None] = mapped_column(Text)
    parola_degismeli: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    gecici_parola_bitis: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parola_degisti_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    son_giris_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship(lazy="selectin")
    # Birim üyelikleri kullanıcıyla BİRLİKTE yüklenir: kapsam kontrolü her
    # istekte koşuyor (izin istisnalarıyla aynı gerekçe, N+1 yok).
    # `user_units.created_by` da users'a gittiği için yabancı anahtar açıkça
    # belirtilir.
    birimler: Mapped[list["UserUnit"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="UserUnit.user_id",
        order_by="UserUnit.birim",
    )
    # İstisnalar kullanıcıyla BİRLİKTE yüklenir: yetki kontrolü her istekte
    # koşuyor, ayrı sorgu N+1 üretirdi.
    # `user_permissions.veren_id` de users'a gittiği için (süreli vekâlet,
    # Dalga 4) yabancı anahtar açıkça belirtilir.
    izin_istisnalari: Mapped[list["UserPermission"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="UserPermission.user_id",
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

    def giris_yapabilir_mi(self) -> bool:
        """Oturum açabilir mi — kural BURADA, tek yerde (E13-02/03).

        `authenticate`, `login_mfa` ve `resolve_session` bunu çağırır. Kayıt
        canlı olsa bile (`is_active`) girişi kapatılmış personel giremez.
        """
        return bool(self.is_active) and bool(self.giris_acik)

    @property
    def birim_kodlari(self) -> list[str]:
        """Üyesi olduğu birim kodları, sıralı (kapsam yardımcılarının girdisi)."""
        return sorted(u.birim for u in self.birimler)

    @property
    def birincil_birim(self) -> str | None:
        return next((u.birim for u in self.birimler if u.is_primary), None)

    def has(self, permission_code: str) -> bool:
        """İzin var mı. Varsayılan DAİMA reddetmektir.

        Sıra: kullanıcıya özel istisna → rol. İstisna her iki yönde de
        kesindir; `allow=False` rolden gelen izni GERİ ALIR. Reddin rolün
        üstünde olması bilinçli: bir kişinin yetkisini kısmak, ona rol
        değiştirmekten daha sık ve daha acil bir ihtiyaç.
        """
        for ui in self._yururlukteki_istisnalar():
            if ui.permission_code == permission_code:
                return ui.allow
        return any(rp.permission_code == permission_code for rp in self.role.permissions)

    # Süreli vekâlet (Dalga 4): istisnanın yürürlükte olup olmadığı İSTEK
    # anına göre belirlenir. An `Clock`'tan gelir (`api/deps.py`
    # `izin_anini_ata(clock.now())`); model saat okumaz. Atanmamışsa süreli
    # satırlar sayılmaz (fail-closed), kalıcı istisnalar eskisi gibi çalışır.
    _izin_ani = None

    def izin_anini_ata(self, an: datetime | None) -> None:
        """Süreli istisnaların değerlendirileceği anı bağlar (istek başına)."""
        self._izin_ani = an

    def _yururlukteki_istisnalar(self) -> list["UserPermission"]:
        return [ui for ui in self.izin_istisnalari if ui.gecerli_mi(self._izin_ani)]

    def etkin_izinler(self) -> list[str]:
        """Bu kullanıcının GERÇEKTEN sahip olduğu izinler, sıralı.

        `has()` ile aynı kuraldan türer. Arayüz menüyü ve butonları bu listeye
        göre çiziyor; rolün ham izin listesini döndürmek, istisnayla verilen
        yetkinin menüde hiç görünmemesine ve geri alınan yetkinin tıklanınca
        403 vermesine yol açardı.
        """
        kodlar = {rp.permission_code for rp in self.role.permissions}
        for ui in self._yururlukteki_istisnalar():
            if ui.allow:
                kodlar.add(ui.permission_code)
            else:
                kodlar.discard(ui.permission_code)
        return sorted(kodlar)


# Oturumu açan istemci türü (G3.7): süreyi SUNUCU seçer (`services/auth.py`
# `OTURUM_SURELERI`); istemci yalnız ipucu verir.
ISTEMCI_TURLERI = ("MASAUSTU", "MOBIL")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("istemci IN ('MASAUSTU', 'MOBIL')", name="ck_sessions_istemci"),
    )

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    istemci: Mapped[str] = mapped_column(
        String(10), server_default=text("'MASAUSTU'"), default="MASAUSTU"
    )

    user: Mapped[User] = relationship(back_populates="sessions")
