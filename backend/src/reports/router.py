"""Provider-scoped self-service reports.

Thin wrapper over finance.reports.build_reports. Caller is always a
provider (enforced by require_active_provider). Access is further gated
by the caller's own can_view_reports capability — 403 with an actionable
detail string when off. by_provider arrays are trimmed from the response
since a single provider looking at their own data doesn't need them.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import models
from ..auth.dependencies import require_active_provider
from ..database import get_db
from ..finance import reports as finance_reports

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/mine")
def my_reports(
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    provider: models.User = Depends(require_active_provider),
):
    if not provider.can_view_reports:
        raise HTTPException(
            status_code=403,
            detail="Reports are not enabled for your account. Contact an administrator.",
        )
    if not from_ or not to:
        d_from, d_to = finance_reports.default_period()
        from_ = from_ or d_from
        to = to or d_to
    finance_reports.validate_period(from_, to)
    payload = finance_reports.build_reports(
        db, from_str=from_, to_str=to, provider_id=provider.id,
    )
    # Trim the by_provider arrays — meaningless for a single-provider view.
    payload["financial"].pop("by_provider", None)
    payload["operational"].pop("by_provider", None)
    return payload
