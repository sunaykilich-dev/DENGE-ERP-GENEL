import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.api import accounts as accounts_api
from app.api import attachments as attachments_api
from app.api import audit_api, settings_api
from app.api import auth as auth_api
from app.api import bakim as bakim_api
from app.api import catalog as catalog_api
from app.api import devices as devices_api
from app.api import gorevler as gorevler_api
from app.api import imports as imports_api
from app.api import kvkk as kvkk_api
from app.api import lokasyonlar as lokasyonlar_api
from app.api import orders as orders_api
from app.api import payments as payments_api
from app.api import personel as personel_api
from app.api import pricing as pricing_api
from app.api import public_quotes as public_quotes_api
from app.api import purchasing as purchasing_api
from app.api import quotes as quotes_api
from app.api import reports as reports_api
from app.api import rma as rma_api
from app.api import search as search_api
from app.api import servis_ekipman as servis_ekipman_api
from app.api import servis_zaman as servis_zaman_api
from app.api import settlements as settlements_api
from app.api import sims as sims_api
from app.api import stock as stock_api
from app.api import subscriptions as subscriptions_api
from app.api import tariffs as tariffs_api
from app.api import teknik_servis as teknik_servis_api
from app.api import teknik_servis_ana_veri as teknik_servis_ana_veri_api
from app.api import teknik_servis_planlama as teknik_servis_planlama_api
from app.api import users as users_api
from app.api import vehicles as vehicles_api
from app.api import workorders as workorders_api
from app.config import YapilandirmaHatasi, get_config, uretim_kontrolu

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _omur(app: FastAPI):
    """Açılışta PDF motorunu ISITIR.

    WeasyPrint ilk çağrıda kendini, Pango'yu ve gömülü fontları yüklüyor.
    Ölçüldü: konteyner yeni kalktığında ilk teklif PDF'i **5,8 saniye**,
    sonrakiler 0,3 saniye. Bu bekleme her zaman ilk KULLANICIYA düşüyordu.

    Isıtma ayrı bir iş parçacığında ve arka planda koşar: açılışı geciktirmez,
    başarısız olursa uygulama yine açılır (PDF üretimi zaten kendi hatasını
    verir). Bu yüzden geniş `except` bilinçlidir.
    """
    import asyncio

    async def isit() -> None:
        try:
            from app.services.pdf import pdf_uret_async

            await pdf_uret_async("isinma.html")
            logging.getLogger("denge").info("PDF motoru hazır")
        except Exception as exc:  # noqa: BLE001 - ısınma başarısızlığı açılışı engellemez
            logging.getLogger("denge").warning("PDF ısıtma atlandı: %s", exc)

    gorev = asyncio.create_task(isit())
    yield
    gorev.cancel()


# Kısıt önekine göre kullanıcıya dönen mesaj. Kısıt ADI dışarı verilmez.
_KISIT_MESAJI = {
    "uq_": "Bu kayıt zaten var (benzersiz bir alan çakışıyor).",
    "fk_": "Bağlanmak istenen kayıt bulunamadı.",
    "ck_": "Girilen değer izin verilen aralığın/kümenin dışında.",
    "ex_": "Bu tarih aralığı mevcut bir dönemle çakışıyor.",
    "*": "İşlem veritabanı kuralına takıldı; girdiğiniz değerleri gözden geçirin.",
}


def create_app() -> FastAPI:
    config = get_config()
    # Üretim yapılandırması AÇILIŞTA doğrulanır: eksikse uygulama başlamaz.
    # Geliştirme varsayılanıyla çalışmaya devam eden bir ERP, "kurulum tamam"
    # görünür ve sorun ancak bir olaydan sonra fark edilirdi.
    if sorunlar := uretim_kontrolu(config):
        raise YapilandirmaHatasi(
            "Üretim yapılandırması eksik (.env):\n  - " + "\n  - ".join(sorunlar)
        )
    # MFA'yı kapatmak meşru bir tercih olabilir ama SESSİZ olmamalı: parola
    # çalındığında tek savunma budur. Açılışı engellemez, log'da bağırır.
    if not config.is_dev and not config.mfa_zorunlu:
        logging.getLogger("denge").warning(
            "DİKKAT: MFA_ZORUNLU kapalı — kullanıcılar iki adımlı doğrulama "
            "olmadan girebiliyor. Bilinçli bir tercih değilse .env'de açın."
        )
    # Prod'da API dokümanı kapalı — API yüzeyini sergilemesin.
    docs_kwargs = (
        {"docs_url": "/api/docs", "openapi_url": "/api/openapi.json"}
        if config.is_dev
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    # `denge` logger'ı uvicorn'un handler'ını kullanır ve INFO'da tutulur:
    # kök logger varsayılan WARNING olduğu için işletme mesajları (PDF motoru
    # hazır, worker nabzı, göç özetleri) sessizce kayboluyordu. Susan bir
    # uyarı uyarı değildir.
    denge_log = logging.getLogger("denge")
    denge_log.setLevel(logging.INFO)
    if not denge_log.handlers:
        el = logging.StreamHandler()
        el.setFormatter(logging.Formatter("%(levelname)-8s %(name)s %(message)s"))
        denge_log.addHandler(el)

    app = FastAPI(title="Denge Mobilite ERP", lifespan=_omur, **docs_kwargs)

    @app.exception_handler(StaleDataError)
    async def stale_data_handler(request: Request, exc: StaleDataError) -> JSONResponse:
        """İyimser kilitleme çarpışması (plan §3.3/1).

        SQLAlchemy UPDATE'e `WHERE version = :eski` eklediği için, kaydı arada
        başkası değiştirdiyse hiçbir satır etkilenmez ve bu hata atılır.
        Kullanıcıya sessiz veri kaybı yerine net bir çakışma mesajı döner.
        """
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Bu kaydı siz görüntülerken başka biri değiştirdi. "
                "Sayfayı yenileyip değişikliğinizi tekrar uygulayın."
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        """Veritabanı kısıt ihlali → 409, 500 değil.

        Kullanıcının girdiği veri bir kısıtı çiğnediğinde (aynı IMEI ikinci
        kez, olmayan hesaba referans, `qty >= 0` ihlali, izinli değer kümesi
        dışında bir durum) uygulama 500 veriyordu. Transaction zaten temiz
        geri alınıyor — yarım kayıt kalmıyor — ama kullanıcı "sistem çöktü"
        görüyor ve neyi düzelteceğini bilmiyor.

        Kısıt adı mesaja KONMAZ: şema iç bilgisidir. Log'a tam hata düşer.
        """
        logging.getLogger("denge").warning("kısıt ihlali %s: %s", request.url.path, exc.orig)
        ad = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": _KISIT_MESAJI.get(ad[:3], _KISIT_MESAJI["*"])},
        )

    @app.exception_handler(DataError)
    async def data_handler(request: Request, exc: DataError) -> JSONResponse:
        """Girilen değer kolona sığmıyor / tip dışı → 422.

        Ör. 16 karakterlik kimlik `varchar(15)` kolona, ya da bigint sınırını
        aşan bir id. Kullanıcı hatası; 500 değil.
        """
        logging.getLogger("denge").warning("veri hatası %s: %s", request.url.path, exc.orig)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Girilen değer beklenen biçimde ya da uzunlukta değil."},
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'",
        )
        # HSTS yalnız prod'da (dev'de HTTP kullanıldığı için tarayıcıyı kilitlemesin)
        if not config.is_dev:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    app.include_router(auth_api.router)
    app.include_router(users_api.router)
    app.include_router(accounts_api.router)
    app.include_router(catalog_api.router)
    app.include_router(devices_api.router)
    app.include_router(sims_api.router)
    app.include_router(vehicles_api.router)
    app.include_router(workorders_api.router)
    app.include_router(settlements_api.router)
    app.include_router(stock_api.router)
    app.include_router(quotes_api.router)
    app.include_router(orders_api.router)
    app.include_router(subscriptions_api.router)
    app.include_router(tariffs_api.router)
    app.include_router(pricing_api.router)
    app.include_router(payments_api.router)
    app.include_router(imports_api.router)
    app.include_router(rma_api.router)
    app.include_router(purchasing_api.router)
    app.include_router(reports_api.router)
    app.include_router(kvkk_api.router)
    # Oturumsuz: erişim yalnız jetona dayanır (bkz. public_quotes.py).
    app.include_router(public_quotes_api.router)
    app.include_router(search_api.router)
    app.include_router(settings_api.router)
    app.include_router(audit_api.router)
    app.include_router(attachments_api.router)
    app.include_router(gorevler_api.router)
    # --- Teknik servis (Dalga 0 + 1) --------------------------------------
    # Kayıt noktaları şema paketinde (D0-S) sabitlenir; uçları modül paketleri
    # kendi dosyalarına yazar, bu bloğa dokunmaz. Dalga 2+ routerları
    # (operasyon, atölye, kiralama, parça, maliyet, eğitim) D2-S ekler.
    app.include_router(personel_api.router)
    app.include_router(lokasyonlar_api.router)
    app.include_router(teknik_servis_ana_veri_api.router)
    app.include_router(teknik_servis_planlama_api.router)
    app.include_router(servis_ekipman_api.router)
    app.include_router(bakim_api.router)
    app.include_router(servis_zaman_api.router)
    # Genel `/api/teknik-servis/{...}` yolları alt önekli routerlardan SONRA:
    # `/isler/{id}` gibi bir kalıp `/planlama/...` yolunu yutmasın.
    app.include_router(teknik_servis_api.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "env": config.env}

    # Prod: frontend build'i (make build ile app/static'e kopyalanır) SPA olarak servis et.
    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        kok = STATIC_DIR.resolve()

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:
            """SPA yedek yolu — istenen yol STATIC_DIR'İN DIŞINA ÇIKAMAZ.

            `STATIC_DIR / full_path` tek başına yeterli değildi: yönlendirici
            `..%2f` dizilerini yol ayracı saymadığı için normalleştirmiyor,
            `pathlib` ise sonradan çözüyordu. Sonuç, kimlik doğrulaması
            gerektirmeyen keyfi dosya okuma:
            `GET /..%2f..%2f..%2fetc%2fpasswd` dosyayı döndürüyordu — müşteri
            vergi levhaları dahil (`var/files/...`).

            `resolve()` sembolik bağları da çözer; karşılaştırma ondan sonra
            yapılmalı, yoksa static içine konmuş bir bağ dışarı açılırdı.
            """
            if full_path:
                aday = (kok / full_path).resolve()
                if aday.is_relative_to(kok) and aday.is_file():
                    return FileResponse(aday)
            return FileResponse(kok / "index.html")

    return app


app = create_app()
