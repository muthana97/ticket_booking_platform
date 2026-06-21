from src.finance.models import CommissionRule


def test_commission_rule_has_required_columns():
    cols = {c.name for c in CommissionRule.__table__.columns}
    assert cols == {
        "id", "scope", "provider_id", "route_id", "trip_id",
        "rate_kind", "rate_value", "created_at", "updated_at",
    }


def test_commission_rule_unique_constraint():
    cons = [c for c in CommissionRule.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"]
    assert len(cons) == 1
    names = {c.name for c in cons[0].columns}
    assert names == {"scope", "provider_id", "route_id", "trip_id"}


def test_commission_rule_insert_roundtrip(db):
    rule = CommissionRule(
        scope="global", rate_kind="percentage", rate_value=10.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    assert rule.id is not None
    assert rule.created_at is not None
