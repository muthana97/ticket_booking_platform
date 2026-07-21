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
    route_id: Optional[int] = None
    trip_id: Optional[int] = None
    start_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
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

    @field_validator("expires_at")
    @classmethod
    def _end_after_start(cls, v, info):
        start = info.data.get("start_at")
        if v is not None and start is not None and v <= start:
            raise ValueError("expires_at must be after start_at.")
        return v

    @field_validator("route_id", "trip_id")
    @classmethod
    def _scoped_needs_provider(cls, v, info):
        # Route- or trip-scoped promos MUST specify a provider — trip / route
        # id alone is ambiguous when combined with the provider filter at
        # apply time.
        if v is not None and not info.data.get("provider_id"):
            raise ValueError("route_id / trip_id requires provider_id.")
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
    route_id: Optional[int] = None
    trip_id: Optional[int] = None
    start_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
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
    route_id: Optional[int] = None
    route_label: Optional[str] = None  # e.g. "Khartoum → Port Sudan"
    trip_id: Optional[int] = None
    trip_label: Optional[str] = None   # e.g. "Trip #12 · Khartoum → Port Sudan"
    start_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
