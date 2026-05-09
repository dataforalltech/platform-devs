import pytest

from src.db.store import AuditStore


def test_create_audit(store):
    """Testa criação de auditoria."""
    audit_id = store.create_audit(
        service="test-service",
        repo="test-repo",
        env="dev",
        criticality="medium",
        score=0.75,
        passed=True,
        status="approved",
        checklist={"items": []},
    )
    assert audit_id.startswith("audit_")
    assert len(audit_id) > 10


def test_get_audit(store):
    """Testa leitura de auditoria."""
    audit_id = store.create_audit(
        service="test",
        repo="test-repo",
        env="dev",
        criticality="low",
        score=0.8,
        passed=True,
        status="approved",
        checklist={},
    )
    audit = store.get_audit(audit_id)
    assert audit is not None
    assert audit["service"] == "test"
    assert audit["score"] == 0.8
    assert audit["passed"] is True


def test_add_audit_item(store):
    """Testa adição de itens do checklist."""
    audit_id = store.create_audit(
        service="test",
        repo="repo",
        env="dev",
        criticality="medium",
        score=0.0,
        passed=False,
        status="pending_approval",
        checklist={},
    )
    store.add_audit_item(
        audit_id=audit_id,
        category="structure",
        name="has_src_dir",
        required=True,
        passed=True,
    )
    items = store.get_audit_items(audit_id)
    assert len(items) == 1
    assert items[0]["name"] == "has_src_dir"


def test_service_criticality(store):
    """Testa criticidade de serviço."""
    store.set_service_criticality("my-service", "high", "admin")
    criticality = store.get_service_criticality("my-service")
    assert criticality == "high"

    default_criticality = store.get_service_criticality("unknown-service")
    assert default_criticality == "medium"
