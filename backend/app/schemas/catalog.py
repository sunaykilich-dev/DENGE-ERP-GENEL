from pydantic import BaseModel, Field, field_validator

from app.models.catalog import KIMLIK_TIPLERI, SEBEKE_TEKNOLOJILERI, URUN_TIPLERI
from app.permissions import SIRKETLER


class UrunIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    supplier_code: str | None = Field(default=None, max_length=60)
    name: str = Field(min_length=2, max_length=160)
    type: str = "CIHAZ_SERILI"
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    family: str | None = Field(default=None, max_length=60)
    identity_kind: str = "IMEI"
    requires_parent: bool = False
    channel_count: int | None = None
    supported_network_tech: list[str] | None = None
    warranty_months: int = 24
    is_112_approved: bool = False
    is_school_service_ready: bool = False
    vat_rate: float | None = None
    list_price: float | None = None
    currency: str = "TRY"
    notes: str | None = None
    is_active: bool = True
    # Şirket bazlı katalog (fcl000000001): `permissions.SIRKETLER` kodu ya da
    # null (= ORTAK ürün, her şirkette görünür). Gönderilmezse oluşturmada
    # etkin şirket yazılır.
    sirket: str | None = None

    @field_validator("sirket")
    @classmethod
    def _sirket(cls, v: str | None) -> str | None:
        if v is not None and v not in SIRKETLER:
            raise ValueError(f"Şirket {tuple(SIRKETLER)} içinden olmalı ya da boş (ortak)")
        return v

    @field_validator("type")
    @classmethod
    def _tip(cls, v: str) -> str:
        if v not in URUN_TIPLERI:
            raise ValueError(f"Ürün tipi {URUN_TIPLERI} içinden olmalı")
        return v

    @field_validator("identity_kind")
    @classmethod
    def _kimlik(cls, v: str) -> str:
        if v not in KIMLIK_TIPLERI:
            raise ValueError(f"Kimlik tipi {KIMLIK_TIPLERI} içinden olmalı")
        return v

    @field_validator("supported_network_tech")
    @classmethod
    def _sebeke(cls, v: list[str] | None) -> list[str] | None:
        if v:
            gecersiz = [t for t in v if t not in SEBEKE_TEKNOLOJILERI]
            if gecersiz:
                raise ValueError(f"Bilinmeyen şebeke teknolojisi: {gecersiz}")
        return v


class UrunPatch(UrunIn):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    type: str | None = None
    identity_kind: str | None = None
    version: int | None = None


class PaketKalemi(BaseModel):
    product_id: int
    product_code: str | None = None
    product_name: str | None = None
    quantity: int = 1
    price_share: float | None = None

    model_config = {"from_attributes": True}


class UrunOut(BaseModel):
    id: int
    code: str
    supplier_code: str | None
    name: str
    type: str
    brand: str | None
    model: str | None
    family: str | None
    identity_kind: str
    requires_parent: bool
    channel_count: int | None
    supported_network_tech: list[str] | None
    warranty_months: int
    is_112_approved: bool
    is_school_service_ready: bool
    vat_rate: float | None
    list_price: float | None
    currency: str
    notes: str | None
    is_active: bool
    version: int
    cover_attachment_id: int | None = None
    paket_kalemleri: list[PaketKalemi] = []
    # Serisiz üründe adet stoğu, serilide cihaz sayısı — liste ekranı
    # "elimde kaç tane var" sorusunu ürün kartından ayrı sormasın diye.
    stok_adedi: int | None = None
    # Yedek parça stok alanları (E11-12) — YALNIZ çıktıda. `UrunIn/UrunPatch`'e
    # eklenmez: `urun.yaz` ile `parca.yonet` atlanarak değiştirilemesinler
    # (yazma `PATCH /api/teknik-servis/parca/kartlar`).
    yedek_parca: bool = False
    birim: str | None = None
    min_stok: int | None = None
    # null = ORTAK ürün (her şirkette görünür).
    sirket: str | None = None

    model_config = {"from_attributes": True}
