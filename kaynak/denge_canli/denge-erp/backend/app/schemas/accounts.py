from pydantic import BaseModel, Field, field_validator

from app.models.account import BELGE_TIPLERI, SEGMENTLER
from app.services import normalize


class MontajNoktasiIn(BaseModel):
    document_type: str = "BELIRSIZ"
    billing_account_id: int | None = None
    km_unit_price: float | None = None

    @field_validator("document_type")
    @classmethod
    def _belge(cls, v: str) -> str:
        if v not in BELGE_TIPLERI:
            raise ValueError(f"Belge tipi {BELGE_TIPLERI} içinden olmalı")
        return v


class HesapIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    is_musteri: bool = False
    is_bayi: bool = False
    is_montaj_noktasi: bool = False
    is_tedarikci: bool = False
    parent_dealer_id: int | None = None
    tax_no: str | None = None
    tax_office: str | None = Field(default=None, max_length=80)
    iban: str | None = None
    segment: str | None = None
    region: str | None = Field(default=None, max_length=60)
    sales_rep_id: int | None = None
    email: str | None = Field(default=None, max_length=160)
    phone: str | None = None
    notes: str | None = None
    is_active: bool = True
    partner: MontajNoktasiIn | None = None

    @field_validator("tax_no")
    @classmethod
    def _vergi(cls, v: str | None) -> str | None:
        return normalize.normalize_tax_no(v) if v else None

    @field_validator("iban")
    @classmethod
    def _iban(cls, v: str | None) -> str | None:
        return normalize.normalize_iban(v) if v else None

    @field_validator("phone")
    @classmethod
    def _tel(cls, v: str | None) -> str | None:
        return normalize.normalize_msisdn(v) if v else None

    @field_validator("segment")
    @classmethod
    def _segment(cls, v: str | None) -> str | None:
        if v and v not in SEGMENTLER:
            raise ValueError(f"Segment {SEGMENTLER} içinden olmalı")
        return v


class HesapPatch(HesapIn):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    is_musteri: bool | None = None
    is_bayi: bool | None = None
    is_montaj_noktasi: bool | None = None
    is_tedarikci: bool | None = None
    is_active: bool | None = None
    version: int | None = None


class MontajNoktasiOut(BaseModel):
    document_type: str
    billing_account_id: int | None = None
    km_unit_price: float | None = None

    model_config = {"from_attributes": True}


class HesapOut(BaseModel):
    id: int
    title: str
    roller: list[str]
    is_musteri: bool
    is_bayi: bool
    is_montaj_noktasi: bool
    is_tedarikci: bool
    parent_dealer_id: int | None
    parent_dealer_title: str | None = None
    tax_no: str | None
    tax_office: str | None
    iban: str | None
    segment: str | None
    region: str | None
    sales_rep_id: int | None
    email: str | None
    phone: str | None
    notes: str | None
    is_active: bool
    version: int
    partner: MontajNoktasiOut | None = None
    # Hak ediş dökümü e-posta ile gönderilecek ve ödeme listesi IBAN'dan
    # üretilecek; eksikse D5 bloke olur. Listede görünür uyarı olarak taşınır.
    eksik_alanlar: list[str] = []

    model_config = {"from_attributes": True}


class MukerrerAday(BaseModel):
    id: int
    title: str
    benzerlik: float
    roller: list[str]
    tax_no: str | None = None
    phone: str | None = None
