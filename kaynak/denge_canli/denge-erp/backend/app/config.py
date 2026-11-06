from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo kökündeki .env (backend/ CWD'sinden bağımsız). Docker'da dosya yoktur;
# değerler compose'un env_file'ından gerçek ortam değişkeni olarak gelir.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseSettings):
    """Altyapı yapılandırması (.env).

    Operasyonel ayarlar — stopaj/damga/KDV oranları, iskonto onay eşiği, kota
    uyarı yüzdeleri, garanti süresi, entegrasyon anahtarları — buraya DEĞİL,
    DB'deki `settings` tablosuna girer ve admin arayüzünden yönetilir.
    Brief §4.7'nin "tüm oranlar sabit kod değil, ayarlardan değiştirilebilir
    parametre olmalı" şartı bu ayrımla karşılanır.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://dengeerp:dengeerp@localhost:5432/dengeerp"
    # Geliştirme varsayılanı; üretimde bu değerle uygulama AÇILMAZ
    # (bkz. uretim_kontrolu).
    secret_key: str = "dev-secret-degistir"  # noqa: S105
    # DB'deki hassas ayarları (operatör/platform API anahtarı, SMTP parolası,
    # TOTP sırları) şifrelemek için. Boşsa secret_key'den türetilir. Prod'da
    # bağımsız güçlü bir değer verin; değiştirilirse eski şifreli değerler
    # çözülemez ve yeniden girilmeleri gerekir.
    settings_enc_key: str = ""
    # Teklif public linki (§4.9 online kabul) bu adrese göre üretilir.
    public_base_url: str = "http://localhost:5173"
    # Dosya ekleri, üretilen PDF'ler, içe aktarma hata raporları.
    files_dir: Path = _REPO_ROOT / "var" / "files"
    # Takip platformundan gelen webhook'un yol jetonu.
    webhook_path_token: str = "dev-webhook-token"  # noqa: S105
    # MFA zorunluysa kurulum yapmamış kullanıcı parolası doğru olsa da hiçbir
    # uca erişemez; oturumu yalnız kuruluma izin verir. Kapatmak bilinçli bir
    # karardır ve yalnız geliştirmede anlamlıdır.
    mfa_zorunlu: bool = True

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


# `.env.example` içindeki yer tutucular ve kodun kendi geliştirme
# varsayılanları. Bunlardan biriyle üretime çıkmak, "kurulum yapıldı"
# görünen ama oturum jetonu tahmin edilebilir bir sistem demektir.
_GELISTIRME_DEGERLERI = frozenset(
    {
        "dev-secret-degistir",
        "dev-webhook-token",
        "degistir-openssl-rand-hex-32",
        "degistir-openssl-rand-hex-16",
        "degistir-guclu-bir-parola",
        "dengeerp",
        "postgres",
        "parola",
        "password",
        "changeme",
    }
)

# Sır uzunluğu alt sınırı: `openssl rand -hex 32` 64 karakter üretir; 32
# karakterin altı elle uydurulmuş bir parola demektir.
_ASGARI_SIR_UZUNLUGU = 32


class YapilandirmaHatasi(RuntimeError):
    """Üretim yapılandırması eksik ya da geliştirme değeriyle kalmış."""


def _parola(database_url: str) -> str | None:
    """DSN'den parolayı çıkarır; ayrıştırılamazsa None."""
    from urllib.parse import urlsplit

    try:
        return urlsplit(database_url).password
    except ValueError:
        return None


def uretim_kontrolu(config: AppConfig) -> list[str]:
    """Üretimde kabul edilemez yapılandırmaların listesi (boşsa sorun yok).

    Kontrol AÇILIŞTA yapılır ve uygulamayı başlatmaz. Sessizce çalışan bir
    ERP'de bu değerlerin geliştirme varsayılanında kaldığı ancak bir olaydan
    sonra fark edilirdi: `secret_key` oturum jetonunu imzalar, `webhook_path_token`
    dışarıya açık yolun tek korumasıdır, `settings_enc_key` operatör API
    anahtarı ve TOTP sırlarını şifreler.
    """
    if config.is_dev:
        return []

    sorunlar: list[str] = []

    def _kontrol(ad: str, deger: str, *, uzunluk: bool = True) -> None:
        if not deger or deger in _GELISTIRME_DEGERLERI:
            sorunlar.append(f"{ad} geliştirme değerinde ya da boş.")
        elif uzunluk and len(deger) < _ASGARI_SIR_UZUNLUGU:
            sorunlar.append(f"{ad} çok kısa (en az {_ASGARI_SIR_UZUNLUGU} karakter).")

    _kontrol("SECRET_KEY", config.secret_key)
    _kontrol("SETTINGS_ENC_KEY", config.settings_enc_key)
    _kontrol("WEBHOOK_PATH_TOKEN", config.webhook_path_token, uzunluk=False)

    db_parola = _parola(config.database_url)
    if db_parola is None or db_parola in _GELISTIRME_DEGERLERI:
        sorunlar.append("DATABASE_URL parolası geliştirme değerinde ya da yok.")

    # Teklif public linki müşteriye gider; localhost ya da şifresiz HTTP
    # olursa müşteri linki açamaz ve jeton ağda açık gider.
    if not config.public_base_url.startswith("https://"):
        sorunlar.append("PUBLIC_BASE_URL https:// ile başlamalı.")
    elif "localhost" in config.public_base_url or "127.0.0.1" in config.public_base_url:
        sorunlar.append("PUBLIC_BASE_URL sunucunun gerçek alan adı olmalı.")

    return sorunlar


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
