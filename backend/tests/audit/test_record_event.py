from src.audit import service as audit_svc, models as audit_models
from src.auth import models as auth_models
from src.auth.utils import hash_password


def _seed_admin_and_provider(db):
    admin = auth_models.User(
        email="a@x.com", password_hash=hash_password("x"), full_name="Admin A",
        role="admin", status="active", email_verified=True,
    )
    prov = auth_models.User(
        email="p@x.com", password_hash=hash_password("x"), full_name="Prov P",
        role="provider", status="active", email_verified=True,
    )
    db.add_all([admin, prov]); db.commit(); db.refresh(admin); db.refresh(prov)
    return admin, prov


def test_record_event_inserts_row(db):
    admin, prov = _seed_admin_and_provider(db)
    audit_svc.record_event(
        db,
        actor_user_id=admin.id,
        provider_id=prov.id,
        event_type="trip_edited",
        summary="Admin A edited trip #47: price 500→600",
        target_type="trip",
        target_id=47,
        metadata={"before": {"price": 500}, "after": {"price": 600}},
    )
    db.commit()
    rows = db.query(audit_models.AuditEvent).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == admin.id
    assert row.provider_id == prov.id
    assert row.event_type == "trip_edited"
    assert row.summary.startswith("Admin A edited")
    assert row.target_type == "trip"
    assert row.target_id == 47
    assert row.metadata_ == {"before": {"price": 500}, "after": {"price": 600}}


def test_record_event_rolls_back_with_outer_transaction(db):
    """If the caller rolls back, the audit row must roll back too — spec §5.4."""
    admin, prov = _seed_admin_and_provider(db)
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )
    db.rollback()
    assert db.query(audit_models.AuditEvent).count() == 0


def test_record_event_swallows_exception(db, monkeypatch):
    """A bug in the audit code must NEVER break the caller.

    We force db.add to raise, then call record_event. It must not propagate."""
    admin, prov = _seed_admin_and_provider(db)

    real_add = db.add
    calls = {"add": 0}

    def _boom(obj):
        calls["add"] += 1
        # Only blow up on AuditEvent inserts; leave the seeded user alone.
        if isinstance(obj, audit_models.AuditEvent):
            raise RuntimeError("simulated audit failure")
        return real_add(obj)

    monkeypatch.setattr(db, "add", _boom)

    # Must not raise.
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )
    # And the outer session must still be usable for the caller's own commit.
    monkeypatch.setattr(db, "add", real_add)
    db.add(auth_models.User(
        email="post@x.com", password_hash=hash_password("x"), full_name="Post",
        role="customer", status="active", email_verified=True,
    ))
    db.commit()  # must not raise
    assert db.query(auth_models.User).filter_by(email="post@x.com").count() == 1


def test_record_event_savepoint_isolates_failure(db, monkeypatch):
    """Even when the audit insert fails, the SAVEPOINT protects the outer
    transaction — subsequent SQL in the same session still works."""
    admin, prov = _seed_admin_and_provider(db)

    # Simulate a broken audit insert
    def _bad_flush():
        raise RuntimeError("simulated flush failure")

    original_flush = db.flush

    def _flush_when_audit_pending(*a, **kw):
        pending = [o for o in db.new if isinstance(o, audit_models.AuditEvent)]
        if pending:
            raise RuntimeError("simulated audit flush failure")
        return original_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", _flush_when_audit_pending)
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )
    # Session is not poisoned:
    monkeypatch.setattr(db, "flush", original_flush)
    prov.full_name = "New Name"
    db.commit()
    db.refresh(prov)
    assert prov.full_name == "New Name"


def test_record_event_preserves_caller_dirty_state_on_audit_failure(db, monkeypatch):
    """The critical invariant: if the caller has UNFLUSHED mutations pending
    when record_event() is called, and the audit insert then fails, the
    caller's mutations MUST survive (not get silently swallowed by the
    savepoint rollback). This is what the pre-flush inside record_event
    protects against — begin_nested()'s scoped rollback would otherwise
    revert ANY dirty state that was flushed inside the savepoint's scope."""
    admin, prov = _seed_admin_and_provider(db)

    # Caller mutates something, does NOT flush.
    prov.full_name = "Renamed Before Audit"
    assert "full_name" in dict(db.dirty.pop().__mapper__.attrs) if False else True  # sanity: prov is dirty
    assert prov in db.dirty

    # Now audit inserts fail (simulate a broken insert at flush time).
    original_flush = db.flush

    def _flush_when_audit_pending(*a, **kw):
        pending = [o for o in db.new if isinstance(o, audit_models.AuditEvent)]
        if pending:
            raise RuntimeError("simulated audit flush failure")
        return original_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", _flush_when_audit_pending)
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )

    # Caller's mutation survives even though the audit failed.
    monkeypatch.setattr(db, "flush", original_flush)
    db.commit()
    db.refresh(prov)
    assert prov.full_name == "Renamed Before Audit", (
        "Caller's dirty state got silently reverted by the SAVEPOINT rollback — "
        "the pre-flush in record_event() should have scoped the savepoint's "
        "blast radius to the audit row only."
    )
