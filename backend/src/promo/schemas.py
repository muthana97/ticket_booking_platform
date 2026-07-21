from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


DiscountKind = Literal["percentage", "flat"]


class PromoBase(BaseModel):
    code: str = Field(..., min_length=2, max_length=40)
    discount_kind: DiscountKind
    discount_value: float = Field(..., gt=0)
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    provider_id: Optional[int] = None
    trip_id: Optional[int] = None
    active: bool = True

    @field_validator("code")
    @classmethod
    def _upper_and_strip(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("discount_value")
    @classmethod
    def _cap_percentage(cls, v, info):
        # Percentage codes can't discount more than 100%. Flat codes are
        # unbounded here — the apply-time check clamps to the trip total.
        kind = info.data.get("discount_kind")
        if kind == "percentage" and v > 100:
            raise ValueError("Percentage discount cannot exceed 100%.")
        return v


class PromoCreate(PromoBase):
    pass


class PromoUpdate(BaseModel):
    """Partial update. Any omitted field is left as-is."""
    code: Optional[str] = Field(default=None, min_length=2, max_length=40)
    discount_kind: Optional[DiscountKind] = None
    discount_value: Optional[float] = Field(default=None, gt=0)
    max_redemptions: Optional[int] = Field(default=None, ge=0)  # 0 clears the cap
    provider_id: Optional[int] = None
    trip_id: Optional[int] = None
    active: Optional[bool] = None

    @field_validator("code")
    @classmethod
    def _upper_and_strip(cls, v):
        return v.strip().upper() if v is not None else v


class PromoOut(BaseModel):
    id: int
    code: str
    discount_kind: DiscountKind
    discount_value: float
    max_redemptions: Optional[int] = None
    redemption_count: int
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    trip_id: Optional[int] = None
    trip_label: Optional[str] = None  # e.g. "Trip #12 · Khartoum → Port Sudan"
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
