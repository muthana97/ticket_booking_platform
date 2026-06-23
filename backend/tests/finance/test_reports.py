import pytest
from src.finance.reports import period_months


def test_period_months_single_month():
    assert period_months("2026-06", "2026-06") == ["2026-06"]


def test_period_months_inclusive_range():
    assert period_months("2026-01", "2026-06") == [
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"
    ]


def test_period_months_spans_year():
    assert period_months("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02"
    ]
