from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


RateKind = Literal["percentage", "flat_per_seat"]
Scope = Literal["global", "provider", "provider_route", "trip"]


class GlobalUpsertIn(BaseModel):
    rate_kind: RateKind
    rate_value: float

    def validate_value(self) -> None:
        from fastapi import HTTPException
        if self.rate_kind == "percentage" and not (0 < self.rate_value <= 100):
            raise HTTPException(400, "Percentage rate must be > 0 and ≤ 100")
        if self.rate_kind == "flat_per_seat" and self.rate_value <= 0:
            raise HTTPException(400, "Flat rate must be > 0")


class OverrideCreateIn(BaseModel):
    scope: Literal["provider", "provider_route", "trip"]
    provider_id: int
    route_id: Optional[int] = None
    trip_id: Optional[int] = None
    rate_kind: RateKind
    rate_value: float

    def validate_shape(self) -> None:
        from fastapi import HTTPException
        if self.scope == "provider_route" and self.route_id is None:
            raise HTTPException(400, "route_id required for provider_route scope")
        if self.scope == "trip" and self.trip_id is None:
            raise HTTPException(400, "trip_id required for trip scope")
        if self.scope == "provider" and (self.route_id or self.trip_id):
            raise HTTPException(400, "route_id/trip_id not allowed for provider scope")
        if self.rate_kind == "percentage" and not (0 < self.rate_value <= 100):
            raise HTTPException(400, "Percentage rate must be > 0 and ≤ 100")
        if self.rate_kind == "flat_per_seat" and self.rate_value <= 0:
            raise HTTPException(400, "Flat rate must be > 0")


class OverrideUpdateIn(BaseModel):
    rate_kind: RateKind
    rate_value: float


class GlobalRuleOut(BaseModel):
    rate_kind: RateKind
    rate_value: float
    updated_at: datetime


class OverrideRuleOut(BaseModel):
    id: int
    scope: Scope
    provider_id: int
    provider_name: str
    route_id: Optional[int] = None
    route_label: Optional[str] = None
    trip_id: Optional[int] = None
    trip_label: Optional[str] = None
    rate_kind: RateKind
    rate_value: float
    updated_at: datetime


class CommissionsReadResponse(BaseModel):
    global_rule: Optional[GlobalRuleOut] = Field(default=None, alias="global")
    overrides: List[OverrideRuleOut]

    class Config:
        populate_by_name = True
