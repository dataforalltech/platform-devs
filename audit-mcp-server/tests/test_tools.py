from src.tools.approval_tool import submit_audit_approval
from src.tools.audit_tool import get_audit_status, run_audit
from src.tools.checklist_tool import get_compliance_checklist
from src.tools.gate_tool import get_audit_gate_result
from src.tools.policy_tool import get_compliance_policy, set_service_criticality
from src.tools.report_tool import get_audit_report, list_audits


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

    # O store atual não persiste criticidade: get_service_criticality sempre
    # retorna o default "medium" (ver AuditStore.get_service_criticality).
    criticality = store.get_service_criticality("my-service")
    assert criticality == "medium"


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


# --------------------------------------------------------------------------- #
# get_compliance_policy — caminhos de erro
# --------------------------------------------------------------------------- #


def test_get_compliance_policy_not_found(store, settings):
    """Env inexistente retorna NotFound."""
    result = get_compliance_policy(store, settings, env="staging")
    assert result["error"] == "NotFound"
    assert result["tool"] == "get_compliance_policy"


# --------------------------------------------------------------------------- #
# get_compliance_checklist
# --------------------------------------------------------------------------- #


def test_get_compliance_checklist(store, settings):
    """Checklist é montado a partir da policy do env."""
    result = get_compliance_checklist(store, settings, service="svc", repo="r", env="dev")
    assert result["service"] == "svc"
    assert result["env"] == "dev"
    assert result["min_score"] == 0.5
    assert result["checklist_items"] == len(result["checklist"])
    assert result["checklist_items"] > 0
    # required_checkers viram itens obrigatórios
    assert any(i["required"] and i["name"] == "has_src_dir" for i in result["checklist"])
    # ideal_checkers viram itens opcionais
    assert any(not i["required"] for i in result["checklist"])


def test_get_compliance_checklist_not_found(store, settings):
    """Env sem policy retorna NotFound."""
    result = get_compliance_checklist(store, settings, service="svc", repo="r", env="staging")
    assert result["error"] == "NotFound"


# --------------------------------------------------------------------------- #
# run_audit — fluxo completo (hermético via tmp_repo + fake store)
# --------------------------------------------------------------------------- #


def test_run_audit_repo_not_resolvable(store, settings):
    """Sem repo_path válido, run_audit falha com ValidationError."""
    result = run_audit(store, settings, service="svc", repo="ghost-repo", env="dev")
    assert result["error"] == "ValidationError"
    assert result["tool"] == "run_audit"


def test_run_audit_full_flow(store, settings, tmp_repo, monkeypatch):
    """run_audit roda todos os checkers e persiste a auditoria."""
    # LintChecker chama subprocess; sem ruff instalado no repo alvo ele
    # retorna passed=True. Forçamos o caminho "ruff não instalado" para manter
    # o teste hermético (sem depender do subprocess).
    monkeypatch.setattr(
        "src.checkers.lint_checker.LintChecker._run_ruff",
        staticmethod(lambda repo_path: (True, "ruff not installed (skipped)")),
    )
    result = run_audit(
        store,
        settings,
        service="svc",
        repo="r",
        env="dev",
        repo_path=str(tmp_repo),
    )
    assert result["audit_id"] == "audit_svc_dev"
    assert result["service"] == "svc"
    assert result["criticality"] == "medium"
    assert 0.0 <= result["score"] <= 1.0
    assert result["checklist_count"] > 0
    assert result["status"] in {"auto_approved", "pending_approval"}
    # a auditoria foi persistida no store
    stored = store.get_latest_audit("svc", "dev")
    assert stored is not None


def test_run_audit_auto_approves_high_score(store, settings, tmp_repo, monkeypatch):
    """Score alto em dev (>=0.70, criticality medium) auto-aprova."""
    monkeypatch.setattr(
        "src.checkers.lint_checker.LintChecker._run_ruff",
        staticmethod(lambda repo_path: (True, "ok")),
    )
    # Enriquecer o repo para maximizar o score.
    (tmp_repo / "CHANGELOG.md").write_text("# changelog", encoding="utf-8")
    (tmp_repo / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")
    (tmp_repo / ".env.example").write_text("FOO=bar", encoding="utf-8")
    (tmp_repo / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_repo / "README.md").write_text("# Repo\n## Environment variables\nFOO", encoding="utf-8")
    result = run_audit(
        store,
        settings,
        service="svc",
        repo="r",
        env="dev",
        repo_path=str(tmp_repo),
    )
    assert result["status"] == "auto_approved"
    assert result["approvals_required"] == 0


def test_run_audit_internal_error(store, settings, monkeypatch):
    """Exceção inesperada é capturada como InternalError."""

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("src.tools.audit_tool.RepoResolver", boom)
    result = run_audit(store, settings, service="s", repo="r", env="dev")
    assert result["error"] == "InternalError"
    assert "kaboom" in result["details"]


# --------------------------------------------------------------------------- #
# get_audit_status
# --------------------------------------------------------------------------- #


def test_get_audit_status_not_audited(store, settings):
    """Serviço sem auditoria retorna status not_audited."""
    result = get_audit_status(store, settings, service="none", env="dev")
    assert result["status"] == "not_audited"
    assert result["score"] is None


def test_get_audit_status_after_audit(store, settings):
    """Depois de criar auditoria, get_audit_status devolve os dados."""
    store.create_audit(
        service="svc",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.8,
        passed=True,
        status="approved",
        checklist={"items": [{"name": "x"}], "approvals": [{"approved_by": "a"}]},
    )
    result = get_audit_status(store, settings, service="svc", env="dev")
    assert result["audit_id"] == "audit_svc_dev"
    assert result["status"] == "approved"
    assert result["items_count"] == 1
    assert result["approvals_count"] == 1


# --------------------------------------------------------------------------- #
# submit_audit_approval
# --------------------------------------------------------------------------- #


def _seed_audit(store):
    return store.create_audit(
        service="svc",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.9,
        passed=True,
        status="pending_approval",
        checklist={},
    )


def test_submit_approval_approved(store, settings):
    """Aprovação muda status para approved."""
    audit_id = _seed_audit(store)
    result = submit_audit_approval(
        store,
        settings,
        audit_id=audit_id,
        approved_by="alice",
        decision="approved",
        role="lead",
    )
    assert result["status"] == "approved"
    assert result["approvals_count"] == 1
    assert store.get_audit(audit_id)["status"] == "approved"


def test_submit_approval_rejected(store, settings):
    """Rejeição muda status para rejected e passed=False."""
    audit_id = _seed_audit(store)
    result = submit_audit_approval(
        store,
        settings,
        audit_id=audit_id,
        approved_by="bob",
        decision="rejected",
    )
    assert result["status"] == "rejected"
    assert store.get_audit(audit_id)["passed"] is False


def test_submit_approval_audit_not_found(store, settings):
    """Auditoria inexistente retorna NotFound."""
    result = submit_audit_approval(
        store,
        settings,
        audit_id="audit_missing_dev",
        approved_by="x",
        decision="approved",
    )
    assert result["error"] == "NotFound"


def test_submit_approval_invalid_decision(store, settings):
    """Decisão inválida retorna ValidationError."""
    audit_id = _seed_audit(store)
    result = submit_audit_approval(
        store,
        settings,
        audit_id=audit_id,
        approved_by="x",
        decision="maybe",
    )
    assert result["error"] == "ValidationError"


# --------------------------------------------------------------------------- #
# get_audit_report + list_audits
# --------------------------------------------------------------------------- #


def test_get_audit_report_empty(store, settings):
    """Sem auditorias no período, o relatório vem zerado."""
    result = get_audit_report(store, settings)
    assert result["total_audits"] == 0
    assert result["average_score"] == 0.0


def test_get_audit_report_with_data(store, settings):
    """Relatório agrega por env/criticidade e calcula pass rate."""
    store.create_audit(
        service="a",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.9,
        passed=True,
        status="approved",
        checklist={},
    )
    store.create_audit(
        service="b",
        repo="r",
        env="prod",
        criticality="high",
        score=0.4,
        passed=False,
        status="rejected",
        checklist={},
    )
    result = get_audit_report(store, settings, period_days=365)
    assert result["total_audits"] == 2
    assert result["approved_count"] == 1
    assert result["rejected_count"] == 1
    assert "dev" in result["by_env"]
    assert "prod" in result["by_env"]
    assert result["pass_rate_pct"] == 50.0


def test_list_audits_with_results(store, settings):
    """list_audits devolve os campos resumidos por auditoria."""
    store.create_audit(
        service="a",
        repo="r",
        env="dev",
        criticality="medium",
        score=0.9,
        passed=True,
        status="approved",
        checklist={},
    )
    result = list_audits(store, settings)
    assert result["total"] == 1
    assert result["audits"][0]["audit_id"] == "audit_a_dev"
    assert result["audits"][0]["service"] == "a"


# --------------------------------------------------------------------------- #
# get_audit_gate_result — auditoria aprovada
# --------------------------------------------------------------------------- #


def test_get_audit_gate_result_passed(store, settings):
    """Gate passa quando a auditoria está aprovada."""
    store.create_audit(
        service="svc",
        repo="r",
        env="prod",
        criticality="high",
        score=0.95,
        passed=True,
        status="approved",
        checklist={},
    )
    result = get_audit_gate_result(store, settings, service="svc", env="prod")
    assert result["passed"] is True
    assert result["reason"] == "audit_approved"
    assert result["gate_type"] == "audit_compliance"
