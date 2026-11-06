"""Üretim yapılandırması kontrolü (plan §D13).

Bu kontrolün DEĞERİ, geliştirme varsayılanıyla üretime çıkmayı imkânsız
kılmasında. Testler tam olarak bunu çiviler: bir yer tutucu unutulursa
uygulama açılmamalı, doğru doldurulmuşsa hiç şikâyet etmemeli.
"""

import pytest

from app.config import AppConfig, uretim_kontrolu

PROD_TEMIZ = {
    "env": "prod",
    "secret_key": "a" * 64,
    "settings_enc_key": "b" * 64,
    "webhook_path_token": "c" * 32,
    "database_url": "postgresql+psycopg://dengeerp:Zk3-uzun-parola-yeter@db:5432/dengeerp",
    "public_base_url": "https://erp.dengemobil.com.tr",
}


def _config(**degisiklik) -> AppConfig:
    # `_env_file` boş: testin deponun .env'inden etkilenmemesi için.
    return AppConfig(_env_file=None, **{**PROD_TEMIZ, **degisiklik})


class TestUretimKontrolu:
    def test_temiz_yapilandirma_sorun_cikarmaz(self):
        assert uretim_kontrolu(_config()) == []

    def test_dev_ortaminda_hic_kontrol_yok(self):
        """Geliştirme makinesinde varsayılanlar zaten kullanılıyor."""
        assert uretim_kontrolu(_config(env="dev", secret_key="dev-secret-degistir")) == []

    @pytest.mark.parametrize(
        "alan,deger",
        [
            ("secret_key", "dev-secret-degistir"),
            ("secret_key", ""),
            ("settings_enc_key", "degistir-openssl-rand-hex-32"),
            ("settings_enc_key", ""),
            ("webhook_path_token", "dev-webhook-token"),
        ],
    )
    def test_gelistirme_degeri_yakalanir(self, alan, deger):
        sorunlar = uretim_kontrolu(_config(**{alan: deger}))
        assert any(alan.upper() in s for s in sorunlar), sorunlar

    def test_kisa_sir_yakalanir(self):
        """32 karakterin altı elle uydurulmuş bir paroladır."""
        sorunlar = uretim_kontrolu(_config(secret_key="kisa-ama-varsayilan-degil"))
        assert any("SECRET_KEY" in s and "kısa" in s for s in sorunlar), sorunlar

    def test_webhook_jetonunda_uzunluk_aranmaz(self):
        """Yol jetonu URL'de görünür; kısa olması tasarım gereği serbest."""
        assert uretim_kontrolu(_config(webhook_path_token="kisa123")) == []

    @pytest.mark.parametrize(
        "dsn",
        [
            "postgresql+psycopg://dengeerp:dengeerp@db:5432/dengeerp",
            "postgresql+psycopg://dengeerp:degistir-guclu-bir-parola@db:5432/dengeerp",
            "postgresql+psycopg://dengeerp@db:5432/dengeerp",  # parola yok
        ],
    )
    def test_zayif_db_parolasi_yakalanir(self, dsn):
        sorunlar = uretim_kontrolu(_config(database_url=dsn))
        assert any("DATABASE_URL" in s for s in sorunlar), sorunlar

    @pytest.mark.parametrize(
        "url",
        [
            "http://erp.dengemobil.com.tr",  # TLS yok
            "http://localhost:5173",
            "https://localhost:5173",
        ],
    )
    def test_public_base_url_gercek_ve_tls_olmali(self, url):
        """Teklif bağlantısı müşteriye gider: localhost açılmaz, HTTP'de jeton
        ağda açık gider."""
        sorunlar = uretim_kontrolu(_config(public_base_url=url))
        assert any("PUBLIC_BASE_URL" in s for s in sorunlar), sorunlar

    def test_tum_sorunlar_birlikte_raporlanir(self):
        """Tek tek düzeltip tekrar denemek yerine hepsi bir kerede görünmeli."""
        sorunlar = uretim_kontrolu(
            _config(
                secret_key="dev-secret-degistir",
                settings_enc_key="",
                webhook_path_token="dev-webhook-token",
                database_url="postgresql+psycopg://dengeerp:dengeerp@db:5432/dengeerp",
                public_base_url="http://localhost:5173",
            )
        )
        assert len(sorunlar) == 5, sorunlar


class TestAcilis:
    def test_bozuk_yapilandirmada_uygulama_acilmaz(self, monkeypatch):
        """Kontrolün `create_app`'e BAĞLI olduğunu çivileyen test.

        Fonksiyonun kendisi doğru çalışsa da çağrılmazsa hiçbir işe yaramaz;
        bir yeniden düzenleme bu satırı sessizce düşürebilir.
        """
        from app import main as main_modulu
        from app.config import YapilandirmaHatasi

        bozuk = _config(secret_key="dev-secret-degistir")
        monkeypatch.setattr(main_modulu, "get_config", lambda: bozuk)

        with pytest.raises(YapilandirmaHatasi, match="SECRET_KEY"):
            main_modulu.create_app()

    def test_temiz_yapilandirmada_acilir(self, monkeypatch):
        from app import main as main_modulu

        monkeypatch.setattr(main_modulu, "get_config", lambda: _config())
        app = main_modulu.create_app()
        # Üretimde API dokümanı kapalı olmalı (API yüzeyi sergilenmesin).
        assert app.openapi_url is None
        assert app.docs_url is None
