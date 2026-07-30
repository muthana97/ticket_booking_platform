from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from . import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def _credentials_exc():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Decode the JWT and load the User row. Role + status come from the DB —
    so admin promotions/blocks take effect immediately on the next request
    without re-issuing tokens.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise _credentials_exc()
    except JWTError:
        raise _credentials_exc()

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None:
        raise _credentials_exc()

    if user.status == "blocked":
        raise HTTPException(status_code=403, detail="Account blocked")
    return user


def require_active_provider(user: models.User = Depends(get_current_user)) -> models.User:
    """Active providers only. Pending providers are explicitly rejected with a
    helpful message so the UI can route them to the 'awaiting approval' screen."""
    if user.role != "provider":
        raise HTTPException(status_code=403, detail="Provider role required")
    if user.status == "pending":
        raise HTTPException(
            status_code=403,
            detail="Provider account awaiting admin approval.",
        )
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Provider account is not active.")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin" or user.status != "active":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def require_admin_or_care(user: models.User = Depends(get_current_user)) -> models.User:
    """Accepts both `admin` and `care_admin`. Used on read-mostly admin
    endpoints plus POST /admin/payments/{id}/confirm — the one mutation
    the restricted care-admin tier is allowed to make."""
    if user.role not in ("admin", "care_admin") or user.status != "active":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
