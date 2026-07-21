from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String

from ..database import Base


class PromoCode(Base):
    """
    Discount code minted by admin. Structure mirrors CommissionRule scoping
    (any / provider-scoped / trip-scoped) but with a redemption counter and
    an active flag so a code can be quickly turned off without deleting it.

    Redemption is counted at confirm_payment time (see admin.service). Locking
    a booking with a promo reserves the discount but doesn't increment; if
    the booking expires without confirming, the counter stays where it was.
    """

    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)

    # 'percentage' (0 < value <= 100 → percent off) or 'flat' (SDG value off).
    discount_kind = Column(String, nullable=False)
    discount_value = Column(Float, nullable=False)

    # Optional caps + scope. NULL columns = no restriction.
    max_redemptions = Column(Integer, nullable=True)
    redemption_count = Column(Integer, nullable=False, default=0)

    # Scope. When trip_id is set, provider_id is expected to match trip's
    # provider (enforced in service.resolve_and_price and at admin-write
    # time). Trip-only without provider_id would be ambiguous, so admin UI
    # never mints it.
    provider_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True, index=True)

    # Time window. Both nullable — a promo with no start_at is valid from the
    # moment it's created; no expires_at means it never expires.
    start_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
