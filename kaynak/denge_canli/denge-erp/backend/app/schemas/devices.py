from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.device import BTK_DURUMLARI, CIHAZ_ROLLERI
from app.services import normalize


class CihazIn(BaseModel):
    product_id: int
    imei: str | None = None
    serial_no: str | None = Field(default=None, max_length=40)
    parent_device_id: int | None = None
    channel_no: int | None = None
    device_role: str | None = None
    status: str = "STOKTA"
    btk_status: str = "GEREKMIYOR"
    notes: str | None = None

    @field_validator("imei")
    @classmethod
    def _imei(cls, v: str | None) -> str | None:
        return normalize.validate_imei(v) if v else None

    @field_validator("device_role")
    @classmethod
    def _rol(cls, v: str | None) -> str | None:
        if v and v not in CIHAZ_ROLLERI:
            raise ValueError(f"Cihaz rolü {CIHAZ_ROLLERI} içinden olmalı")
        return v

    @field_validator("btk_status")
    @classmethod
    def _btk(cls, v: str) -> str:
        if v not in BTK_DURUMLARI:
            raise ValueError(f"BTK durumu {BTK_DURUMLARI} içinden olmalı")
        return v


class DurumDegistirIn(BaseModel):
    to_status: str
    reason: str | None = Field(default=None, max_length=200)


class DurumGecmisi(BaseModel):
    from_status: str | None
    to_status: str
    reason: str | None
    changed_at: datetime
    changed_by: int | None

    model_config = {"from_attributes": True}


class HatOzeti(BaseModel):
    id: int
    iccid: str
    msisdn: str | None
    operator: str
    status: str
    plan_name: str | None
    data_allowance_mb: int | None
    data_used_mb: int | None
    enabled_network_tech: list[str] | None
    commitment_end_date: date | None

    model_config = {"from_attributes": True}


class CihazOut(BaseModel):
    id: int
    imei: str | None
    serial_no: str | None
    identity_kind: str
    kimlik: str
    is_identity_provisional: bool
    product_id: int
    product_code: str | None = None
    product_name: str | None = None
    product_family: str | None = None
    parent_device_id: int | None
    parent_kimlik: str | None = None
    channel_no: int | None
    device_role: str | None
    status: str
    sonraki_durumlar: list[str] = []
    btk_status: str
    first_activation_date: date | None
    warranty_end_date: date | None
    garanti_gecerli: bool | None = None
    notes: str | None
    version: int
    # Listede "bu IMEI hangi hatta, hangi araçta, kimde" tek bakışta görünsün
    # diye türetilmiş alanlardan doldurulur (bkz. devices.uzlastir).
    hat_msisdn: str | None = None
    hat_iccid: str | None = None
    arac_plaka: str | None = None
    musteri_unvan: str | None = None

    model_config = {"from_attributes": True}


class CihazKarti(CihazOut):
    """Kabul kriteri 1: bir IMEI yazıldığında tek ekranda her şey."""

    hat: HatOzeti | None = None
    alt_cihazlar: list[CihazOut] = []
    durum_gecmisi: list[DurumGecmisi] = []
    hat_baslangici_bilinmiyor: bool = False
    hat_gecmisi_adedi: int = 0
    ek_adedi: int = 0
