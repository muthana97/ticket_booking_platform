"""Report aggregations for /admin/reports.

Pure functions over a database session — no router concerns. Bucketing is
by confirmation date (Booking.confirmed_at). Spec:
docs/superpowers/specs/2026-06-23-reports-design.md
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session


def period_months(from_str: str, to_str: str) -> list[str]:
    """Inclusive list of YYYY-MM strings from `from_str` to `to_str`."""
    from_y, from_m = map(int, from_str.split("-"))
    to_y, to_m = map(int, to_str.split("-"))
    out = []
    y, m = from_y, from_m
    while (y, m) <= (to_y, to_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out
