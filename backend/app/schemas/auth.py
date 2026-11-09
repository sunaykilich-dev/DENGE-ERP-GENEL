from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)
    # G3.7: istemci ipucu ("masaustu" | "mobil"). Süreyi sunucu seçer
    # (`services/auth.OTURUM_SURELERI`); bilinmeyen değer masaüstü sayılır.
    istemci: str | None = Field(default=None, max_length=20)


class RoleOut(BaseModel):
    code: str
    name: str
    scope: str
    # G3.8: rol yalnız ofis ağından girer (ayar `ofis_ag_listesi`).
    yalniz_ofis: bool = False
    version: int = 1
    ozellestirildi: bool = False

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: int
    full_name: str
    username: str
    email: str | None = None
    is_active: bool
    mfa_enabled: bool = False
    # Kurulum yapılmadıysa arayüz uygulamayı değil kurulum ekranını çizer.
    mfa_kurulumu_gerekli: bool = False
    role: RoleOut
    # Arayüz menüyü ve butonları buna göre kısar. Sunucu yine de her uçta
    # kendi kontrolünü yapar — bu liste yalnız görsel kolaylıktır.
    permissions: list[str] = []
    sees_cost: bool = False
    # Teknik servis (E13-05e): yalnız oturum/menü için gereken dört alan.
    # Personel alanları (sicil, ünvan, saha rolü, not) burada DEĞİL,
    # `PersonelOut`'tadır — giriş yanıtı kişisel veri taşımasın.
    giris_acik: bool = True
    parola_degismeli: bool = False
    birimler: list[str] = []
    birincil_birim: str | None = None
    # Şirket ayrımı (KARARLAR 2026-11-04 §1) — ön yüzle sözleşme: etkin şirket
    # kodu (oturumdan) ve seçilebilir şirket kodları. Oturum dışı (kullanıcı
    # listesi) yanıtta `aktif_sirket` boş, `sirketler` ham üyeliktir.
    aktif_sirket: str | None = None
    sirketler: list[str] = []
    # Rol testi tur 2 (2_menu B-12, KARARLAR 2026-11-04 §7.17): etkin şirkette
    # kullanıcının görebildiği birimler (`kapsam.gorunur_birimler`; TUMU =
    # şirketin bütün birimleri). Menü/kart birime bağlı bölümleri buna göre
    # gizler (POC yalnız TELEKOM'da). Oturum dışı yanıtta boş.
    gorunur_birimler: list[str] = []

    model_config = {"from_attributes": True}

    @classmethod
    def of(cls, user) -> "UserOut":
        from app.services import sirketler as sirket_svc
        from app.services.teknik_servis import kapsam as ts_kapsam

        codes = user.etkin_izinler()
        secilebilir = getattr(user, "_uye_sirketler", None)
        return cls(
            id=user.id,
            full_name=user.full_name,
            username=user.username,
            email=user.email,
            is_active=user.is_active,
            giris_acik=user.giris_acik,
            parola_degismeli=user.parola_degismeli,
            birimler=user.birim_kodlari,
            birincil_birim=user.birincil_birim,
            aktif_sirket=sirket_svc.aktif_sirket(user),
            sirketler=list(secilebilir) if secilebilir is not None else user.sirket_kodlari,
            gorunur_birimler=ts_kapsam.gorunur_birimler(user)
            if sirket_svc.aktif_sirket(user) is not None
            else [],
            mfa_enabled=user.mfa_enabled,
            # GİRİŞ yanıtı da bunu taşımak ZORUNDA: arayüz girişten sonra
            # kullanıcıyı bu yanıttan kuruyor, /auth/me'yi yalnız sayfa
            # yenilenince çağırıyor. Burası boş kalınca kullanıcı uygulamanın
            # içine düşüyor ve her isteği 403 alıyordu.
            mfa_kurulumu_gerekli=user.mfa_kurulumu_gerekli(),
            role=RoleOut.model_validate(user.role),
            permissions=codes,
            sees_cost="maliyet.gor" in codes,
        )


class KullaniciGuncellemeSonucu(UserOut):
    """`PATCH /api/kullanicilar/{id}` yanıtı: `parola_sifirla` istendiyse
    üretilen geçici parola YALNIZ burada ve yalnız bir kez döner."""

    gecici_parola: str | None = None
    gecici_parola_bitis: datetime | None = None


class LoginResult(BaseModel):
    # mfa_required True ise oturum AÇILMADI; istemci kodu /login/mfa'ya gönderir.
    mfa_required: bool = False
    pending_token: str | None = None
    user: UserOut | None = None


class MfaVerifyRequest(BaseModel):
    pending_token: str
    code: str = Field(min_length=6, max_length=10)
    # G3.7: oturum MFA adımında açıldığı için istemci ipucu burada da gelir.
    istemci: str | None = Field(default=None, max_length=20)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ParolaDegistirRequest(BaseModel):
    """Kullanıcının kendi parolasını değiştirmesi (TS-212). Uzunluk ve
    içerik kuralı serviste (`parola_kurali_hatalari`): tek kaynak, Türkçe
    mesaj; burada yalnız kaba sınır."""

    mevcut: str = Field(min_length=1, max_length=200)
    yeni: str = Field(min_length=1, max_length=200)


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9_.-]+$")
    email: str | None = Field(default=None, max_length=160)
    password: str = Field(min_length=8, max_length=200)
    role_code: str = Field(min_length=2, max_length=30)
    # Birim kapsamlı (KENDI_BIRIMI/KENDI_ISLERI) rolde en az bir birim ZORUNLU
    # (E13-11): birimsiz açılan şef hiçbir servis kaydı görmezdi ve bunu
    # kimse fark etmezdi. Sonraki birim değişiklikleri personel kartından.
    birimler: list[str] = Field(default_factory=list, max_length=5)
    birincil_birim: str | None = None
    # Şirket üyeliği (KARARLAR 2026-11-04 §1). Verilmezse birimlerden türetilir
    # (`services/sirketler.varsayilan_uyelik`, migration göçüyle aynı kural).
    sirketler: list[str] | None = Field(default=None, max_length=10)


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=160)
    role_code: str | None = Field(default=None, min_length=2, max_length=30)
    is_active: bool | None = None
    # Girişi açma/kapama yalnız kullanıcı yönetiminden (E13-03); kapatma bütün
    # oturumları düşürür (TS-007).
    giris_acik: bool | None = None
    # Yönetici parolası GEÇİCİDİR (TS-212): kullanıcı ilk girişte değiştirir,
    # 72 saat ve tek giriş geçerlidir.
    password: str | None = Field(default=None, min_length=8, max_length=200)
    # Sunucu tek seferlik parola üretir ve yanıtta BİR KEZ döner (denetimde yok).
    parola_sifirla: bool | None = None
    reset_mfa: bool | None = None  # admin: kullanıcının MFA'sını sıfırla (cihaz kaybı)
    # Şirket üyeliğini TAMAMEN değiştirir (None = dokunma). Açık oturumların
    # etkin şirketi bir sonraki istekte üyeliğe göre doğrulanır.
    sirketler: list[str] | None = Field(default=None, max_length=10)
    # İyimser kilitleme: istemci gördüğü sürümü geri gönderir.
    version: int | None = None
