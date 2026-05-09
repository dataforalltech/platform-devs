import pytest

from src.tools.policy_tool import get_compliance_policy, set_service_criticality
from src.tools.gate_tool import get_audit_gate_result
from src.tools.report_tool import list_audits
from src.tools.approval_tool import submit_audit_approval


def test_get_compliance_policy_dev(store, settings):
    """Testa obtenção de policy para dev."""
    result = get_compliance_policy(store, settings, env="dev")
    assert result["env"] == "dev"
    assert result["min_score"] == 0.5
    assert "required_checkers" in result


def test_get_compliance_policy_hml(store, settings):
    """Testa obtenção de policy para hml."""
    result = get_compliance_policy(store, settings, env="hml")
    assert result["env"] == "hml"
    assert result["min_score"] == 0.7


def test_get_compliance_policy_prod(store, settings):
    """Testa obtenção de policy para prod."""
    result = get_compliance_policy(store, settings, env="prod")
    assert result["env"] == "prod"
    assert result["min_score"] == 0.85


def test_set_service_criticality(store, settings):
    """Testa definição de criticidade."""
    result = set_service_criticality(
        store,
        settings,
        service="my-service",
        criticality="high",
        updated_by="admin",
    )
    assert result["success"] is True
    assert result["criticality"] == "high"

    criticality = store.get_service_criticality("my-service")
    assert criticality == "high"


def test_set_service_criticality_invalid(store, settings):
    """Testa rejeição de criticidade inválida."""
    result = set_service_criticality(
        store,
        settings,
        service="my-service",
        criticality="invalid",
        updated_by="admin",
    )
    assert "error" in result


def test_list_audits_empty(store, settings):
    """Testa listagem vazia de auditorias."""
    result = list_audits(store, settings)
    assert result["total"] == 0


def test_get_audit_gate_result_no_audit(store, settings):
    """Testa gate result quando não há auditoria."""
    result = get_audit_gate_result(store, settings, service="test", env="dev")
    assert result["passed"] is False
    assert result["reason"] == "no_audit_found"
