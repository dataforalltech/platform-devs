"""Testes das tools de pipeline (src/tools/pipeline_tool.py).

Exercitam a lógica real de promoção/aprovação/rollback/gates contra um
FakePipelineStore in-memory. As chamadas ao GitHub (httpx) são mockadas.
"""

from __future__ import annotations

import httpx
import pytest

from src.tools import pipeline_tool
from src.tools.pipeline_tool import (
    _BRANCH_MAP,
    _create_pr,
    _find_service_for_repo,
    _gh_headers,
    _list_open_prs,
    _merge_pr,
    approve_promotion,
    block_service,
    get_pipeline,
    get_pipeline_overview,
    get_promotion_history,
    list_pipeline,
    promote_service,
    register_pipeline,
    rollback,
    set_pipeline_config,
    watch_prs,
)

from .conftest import FakeHTTPClient, FakeResponse


# ─────────────────────────────────────────────────────────────────────────── #
# register / get / list                                                        #
# ─────────────────────────────────────────────────────────────────────────── #
class TestRegisterGetList:
    def test_register_creates(self, store):
        result = register_pipeline(store, service="svc-a", repo="org/svc-a")
        assert result["action"] == "created"
        assert result["pipeline"]["service"] == "svc-a"
        assert result["pipeline"]["current_env"] == "dev"

    def test_register_updates_existing(self, registered_store):
        result = register_pipeline(
            registered_store, service="svc-a", repo="org/renamed", base_branch="trunk"
        )
        assert result["action"] == "updated"
        assert result["pipeline"]["repo"] == "org/renamed"
        assert result["pipeline"]["base_branch"] == "trunk"

    def test_get_pipeline_found(self, registered_store):
        result = get_pipeline(registered_store, service="svc-a")
        assert result["service"] == "svc-a"
        assert "recent_promotions" in result

    def test_get_pipeline_not_found(self, store):
        result = get_pipeline(store, service="ghost")
        assert result == {"error": "not_found", "service": "ghost"}

    def test_list_pipeline_empty(self, store):
        result = list_pipeline(store)
        assert result["total"] == 0
        assert result["pipelines"] == []
        assert result["filters"] == {"env": None, "status": None}

    def test_list_pipeline_filters_by_env(self, registered_store):
        registered_store.register_pipeline("svc-b", "org/svc-b")
        registered_store.update_pipeline_env("svc-b", "homol")
        result = list_pipeline(registered_store, env="homol")
        assert result["total"] == 1
        assert result["pipelines"][0]["service"] == "svc-b"

    def test_list_pipeline_filters_by_status(self, registered_store):
        registered_store.block_pipeline("svc-a", "manutenção", "admin")
        active = list_pipeline(registered_store, status="active")
        blocked = list_pipeline(registered_store, status="blocked")
        assert active["total"] == 0
        assert blocked["total"] == 1


# ─────────────────────────────────────────────────────────────────────────── #
# promote_service — caminhos de erro sem tocar GitHub                          #
# ─────────────────────────────────────────────────────────────────────────── #
class TestPromoteErrors:
    def test_service_not_found(self, store):
        result = promote_service(
            store, service="ghost", from_env="dev", to_env="homol", promoted_by="u"
        )
        assert result == {"error": "not_found", "service": "ghost", "can_promote": False}

    def test_blocked_service(self, registered_store):
        registered_store.block_pipeline("svc-a", "incident", "admin")
        result = promote_service(
            registered_store, service="svc-a", from_env="dev", to_env="homol", promoted_by="u"
        )
        assert result["error"] == "service_blocked"
        assert result["block_reason"] == "incident"
        assert result["can_promote"] is False

    def test_env_mismatch(self, registered_store):
        # svc-a está em dev; pedir homol->prod é mismatch
        result = promote_service(
            registered_store, service="svc-a", from_env="homol", to_env="prod", promoted_by="u"
        )
        assert result["error"] == "env_mismatch"
        assert result["current_env"] == "dev"
        assert result["requested_from_env"] == "homol"

    def test_failed_gates_block_promotion(self, registered_store):
        # gates_config default homol exige qa_tests, pr_approved, audit_compliance
        result = promote_service(
            registered_store, service="svc-a", from_env="dev", to_env="homol", promoted_by="u"
        )
        assert result["can_promote"] is False
        assert set(result["failed_gates"]) == {"qa_tests", "pr_approved", "audit_compliance"}

    def test_invalid_direction(self, registered_store):
        # gates_config vazio para 'prod' evita falha de gate; direção dev->prod é inválida
        set_pipeline_config(registered_store, "svc-a", {"prod": []})
        result = promote_service(
            registered_store, service="svc-a", from_env="dev", to_env="prod", promoted_by="u"
        )
        assert result["error"] == "invalid_direction"
        assert result["direction"] == "dev->prod"


# ─────────────────────────────────────────────────────────────────────────── #
# promote_service — com gates satisfeitos e GitHub mockado                     #
# ─────────────────────────────────────────────────────────────────────────── #
class TestPromoteWithGates:
    def _pass_all_homol_gates(self, store, service="svc-a"):
        for gate in ("qa_tests", "pr_approved", "audit_compliance"):
            store.upsert_gate(service, "dev", gate, True)

    def test_github_unavailable_registers_pending(self, registered_store):
        self._pass_all_homol_gates(registered_store)
        # sem token/org → _create_pr devolve unavailable → status pending
        result = promote_service(
            registered_store,
            service="svc-a",
            from_env="dev",
            to_env="homol",
            promoted_by="u",
            github_token="",
            github_org="",
        )
        assert result["promoted"] is True
        assert result["status"] == "pending"
        assert result["pr_number"] is None
        assert result["promotion_id"] == 1
        # promoção registrada no store
        promo = registered_store.get_promotion(1)
        assert promo["status"] == "pending"
        assert promo["to_env"] == "homol"

    def test_pr_created_waits_approval(self, registered_store, monkeypatch):
        self._pass_all_homol_gates(registered_store)
        fake = FakeHTTPClient(
            {"POST": FakeResponse(201, {"number": 77, "html_url": "https://gh/pr/77"})}
        )
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)

        result = promote_service(
            registered_store,
            service="svc-a",
            from_env="dev",
            to_env="homol",
            promoted_by="alice",
            reason="ship it",
            github_token="tok",
            github_org="org",
        )
        assert result["promoted"] is True
        assert result["status"] == "waiting_approval"
        assert result["pr_number"] == 77
        assert result["pr_url"] == "https://gh/pr/77"
        assert "approve_promotion" in result["message"]
        # o corpo do PR deve conter o reason
        assert "ship it" in fake.calls[0]["json"]["body"]

    def test_pr_creation_hard_error_returns_failed(self, registered_store, monkeypatch):
        self._pass_all_homol_gates(registered_store)
        fake = FakeHTTPClient({"POST": FakeResponse(500, text="boom")})
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)

        result = promote_service(
            registered_store,
            service="svc-a",
            from_env="dev",
            to_env="homol",
            promoted_by="u",
            github_token="tok",
            github_org="org",
        )
        assert result["promoted"] is False
        assert result["status"] == "failed"
        assert "HTTP 500" in result["error"]
        # nenhuma promoção deve ter sido registrada
        assert registered_store.get_promotion(1) is None


# ─────────────────────────────────────────────────────────────────────────── #
# approve_promotion                                                            #
# ─────────────────────────────────────────────────────────────────────────── #
class TestApprovePromotion:
    def _make_waiting_promo(self, store, pr_number=77, status="waiting_approval"):
        store.add_promotion(
            service="svc-a",
            from_env="dev",
            to_env="homol",
            promoted_by="u",
            reason=None,
            gates_snapshot={},
            deploy_ref="homol",
            status=status,
            pr_number=pr_number,
            pr_url="https://gh/pr/77",
        )
        return 1

    def test_promotion_not_found(self, store):
        result = approve_promotion(store, promotion_id=999, approved_by="a")
        assert result == {"error": "not_found", "promotion_id": 999}

    def test_invalid_status(self, registered_store):
        pid = self._make_waiting_promo(registered_store, status="approved")
        result = approve_promotion(registered_store, promotion_id=pid, approved_by="a")
        assert result["error"] == "invalid_status"
        assert result["current_status"] == "approved"

    def test_service_not_found_after_delete(self, store):
        pid = self._make_waiting_promo(store)  # promo existe mas svc-a não registrado
        result = approve_promotion(store, promotion_id=pid, approved_by="a")
        assert result["error"] == "service_not_found"

    def test_approve_without_github_updates_env(self, registered_store):
        # pending sem pr_number/token → não chama merge, apenas aprova e muda env
        pid = self._make_waiting_promo(registered_store, pr_number=None)
        result = approve_promotion(registered_store, promotion_id=pid, approved_by="bob")
        assert result["approved"] is True
        assert result["to_env"] == "homol"
        assert registered_store.get_pipeline("svc-a")["current_env"] == "homol"
        assert registered_store.get_promotion(pid)["status"] == "approved"

    def test_approve_with_merge_success(self, registered_store, monkeypatch):
        pid = self._make_waiting_promo(registered_store, pr_number=77)
        fake = FakeHTTPClient({"PUT": FakeResponse(200, {"sha": "deadbeef", "message": "Merged"})})
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)

        result = approve_promotion(
            registered_store,
            promotion_id=pid,
            approved_by="bob",
            github_token="tok",
            github_org="org",
        )
        assert result["approved"] is True
        assert result["merge_sha"] == "deadbeef"
        assert registered_store.get_pipeline("svc-a")["current_env"] == "homol"

    def test_approve_with_merge_failure_returns_not_approved(self, registered_store, monkeypatch):
        pid = self._make_waiting_promo(registered_store, pr_number=77)
        fake = FakeHTTPClient({"PUT": FakeResponse(405, text="not mergeable")})
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)

        result = approve_promotion(
            registered_store,
            promotion_id=pid,
            approved_by="bob",
            github_token="tok",
            github_org="org",
        )
        assert result["approved"] is False
        assert "HTTP 405" in result["error"]
        # env NÃO deve mudar quando o merge falha
        assert registered_store.get_pipeline("svc-a")["current_env"] == "dev"

    def test_approve_with_merge_unavailable_still_approves(self, registered_store, monkeypatch):
        pid = self._make_waiting_promo(registered_store, pr_number=77)

        def _raise_connect(*a, **k):
            raise httpx.ConnectError("no network")

        fake = FakeHTTPClient({})
        fake.put = _raise_connect  # type: ignore[assignment]
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)

        result = approve_promotion(
            registered_store,
            promotion_id=pid,
            approved_by="bob",
            github_token="tok",
            github_org="org",
        )
        # unavailable é tolerado: aprova e promove mesmo assim
        assert result["approved"] is True
        assert registered_store.get_pipeline("svc-a")["current_env"] == "homol"


# ─────────────────────────────────────────────────────────────────────────── #
# watch_prs                                                                    #
# ─────────────────────────────────────────────────────────────────────────── #
class TestWatchPRs:
    def test_github_not_configured(self, store):
        result = watch_prs(store, github_token="", github_org="")
        assert result["error"] == "github_not_configured"

    def test_no_repos_registered(self, store):
        result = watch_prs(store, github_token="tok", github_org="org")
        assert result["repos_checked"] == 0
        assert "Nenhum repo" in result["message"]

    def test_auto_merge_develop_when_no_qa_gate(self, registered_store, monkeypatch):
        # PR contra develop, sem gate qa_tests → auto-merge procede
        list_resp = FakeResponse(
            200,
            [
                {
                    "number": 5,
                    "title": "feat: x",
                    "html_url": "https://gh/pr/5",
                    "base": {"ref": "develop"},
                    "head": {"ref": "feature/x"},
                    "user": {"login": "dev"},
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        merge_resp = FakeResponse(200, {"sha": "cafe", "message": "Merged"})

        def _client(*a, **k):
            return FakeHTTPClient({"GET": list_resp, "PUT": merge_resp})

        monkeypatch.setattr(httpx, "Client", _client)

        result = watch_prs(registered_store, github_token="tok", github_org="org")
        assert result["repos_checked"] == 1
        assert result["auto_approved_count"] == 1
        assert result["auto_approved"][0]["merged"] is True
        assert result["auto_approved"][0]["merge_sha"] == "cafe"

    def test_develop_blocked_by_failed_qa_gate(self, registered_store, monkeypatch):
        registered_store.upsert_gate("svc-a", "dev", "qa_tests", False)
        list_resp = FakeResponse(
            200,
            [
                {
                    "number": 6,
                    "title": "feat: y",
                    "html_url": "https://gh/pr/6",
                    "base": {"ref": "develop"},
                    "head": {"ref": "feature/y"},
                    "user": {"login": "dev"},
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: FakeHTTPClient({"GET": list_resp}))

        result = watch_prs(registered_store, github_token="tok", github_org="org")
        assert result["auto_approved_count"] == 0
        assert result["waiting_human_count"] == 1
        assert result["waiting_human"][0]["reason"] == "qa_tests gate failed"

    def test_homol_pr_waits_for_human(self, registered_store, monkeypatch):
        list_resp = FakeResponse(
            200,
            [
                {
                    "number": 7,
                    "title": "release",
                    "html_url": "https://gh/pr/7",
                    "base": {"ref": "main"},
                    "head": {"ref": "homol"},
                    "user": {"login": "dev"},
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: FakeHTTPClient({"GET": list_resp}))

        result = watch_prs(
            registered_store, github_token="tok", github_org="org", repos=["org/svc-a"]
        )
        assert result["waiting_human_count"] == 1
        assert result["waiting_human"][0]["reason"] == "human approval required for homol/prod"

    def test_list_prs_error_collected(self, registered_store, monkeypatch):
        err_resp = FakeResponse(403, text="forbidden")
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: FakeHTTPClient({"GET": err_resp}))

        result = watch_prs(registered_store, github_token="tok", github_org="org")
        assert result["auto_approved_count"] == 0
        assert len(result["errors"]) == 1
        assert result["errors"][0]["repo"] == "test-org/svc-a"


# ─────────────────────────────────────────────────────────────────────────── #
# block / rollback / history / overview / config                              #
# ─────────────────────────────────────────────────────────────────────────── #
class TestBlockRollbackHistory:
    def test_block_not_found(self, store):
        assert block_service(store, "ghost", "r", "a") == {"error": "not_found", "service": "ghost"}

    def test_block_success(self, registered_store):
        result = block_service(registered_store, "svc-a", "manutenção", "admin")
        assert result["blocked"] is True
        assert result["pipeline"]["block_reason"] == "manutenção"

    def test_rollback_not_found(self, store):
        assert rollback(store, "ghost", "prod", "v1", "a") == {
            "error": "not_found",
            "service": "ghost",
        }

    def test_rollback_success(self, registered_store):
        result = rollback(
            registered_store,
            service="svc-a",
            env="prod",
            to_version="v1.2.3",
            rolled_back_by="ops",
        )
        assert result["rolled_back"] is True
        assert result["to_version"] == "v1.2.3"
        pipeline = registered_store.get_pipeline("svc-a")
        assert pipeline["current_env"] == "rollback"
        assert pipeline["current_version"] == "v1.2.3"
        promo = registered_store.get_promotion(result["promotion_id"])
        assert promo["to_env"] == "rollback"
        assert promo["status"] == "success"

    def test_promotion_history_empty(self, store):
        result = get_promotion_history(store)
        assert result["total"] == 0
        assert result["promotions"] == []

    def test_promotion_history_filter_and_limit(self, registered_store):
        for i in range(5):
            registered_store.add_promotion(
                service="svc-a",
                from_env="dev",
                to_env="homol",
                promoted_by="u",
                reason=f"r{i}",
                gates_snapshot={},
                deploy_ref="homol",
                status="pending",
            )
        registered_store.add_promotion(
            service="other",
            from_env="dev",
            to_env="homol",
            promoted_by="u",
            reason=None,
            gates_snapshot={},
            deploy_ref="homol",
            status="pending",
        )
        result = get_promotion_history(registered_store, service="svc-a", limit=3)
        assert result["total"] == 3
        assert all(p["service"] == "svc-a" for p in result["promotions"])
        # ordem decrescente: mais recente primeiro
        assert result["promotions"][0]["id"] > result["promotions"][-1]["id"]

    def test_overview(self, registered_store):
        registered_store.register_pipeline("svc-b", "org/svc-b")
        registered_store.block_pipeline("svc-b", "r", "a")
        registered_store.upsert_gate("svc-a", "dev", "qa_tests", False)
        result = get_pipeline_overview(registered_store)
        assert result["total_services"] == 2
        assert result["by_env"]["dev"]["total"] == 2
        assert result["by_env"]["dev"]["blocked"] == 1
        assert len(result["services_with_failed_gates"]) == 1

    def test_set_config_not_found(self, store):
        assert set_pipeline_config(store, "ghost", {"homol": []}) == {
            "error": "not_found",
            "service": "ghost",
        }

    def test_set_config_success(self, registered_store):
        result = set_pipeline_config(
            registered_store, "svc-a", {"homol": ["qa_tests"], "prod": ["security_scan"]}
        )
        assert result["updated"] is True
        assert result["pipeline"]["gates_config"]["homol"] == ["qa_tests"]


# ─────────────────────────────────────────────────────────────────────────── #
# helpers de GitHub (unitários)                                                #
# ─────────────────────────────────────────────────────────────────────────── #
class TestGitHubHelpers:
    def test_gh_headers(self):
        h = _gh_headers("abc")
        assert h["Authorization"] == "Bearer abc"
        assert h["Accept"] == "application/vnd.github+json"

    def test_branch_map_directions(self):
        assert _BRANCH_MAP["dev->homol"] == ("develop", "homol")
        assert _BRANCH_MAP["homol->prod"] == ("homol", "main")

    def test_create_pr_not_configured(self):
        result = _create_pr("", "", "repo", "develop", "homol", "t", "b")
        assert result["unavailable"] is True

    def test_create_pr_slug_from_bare_repo(self, monkeypatch):
        captured = {}

        class C(FakeHTTPClient):
            def post(self, url, **kwargs):
                captured["url"] = url
                return super().post(url, **kwargs)

        fake = C({"POST": FakeResponse(201, {"number": 1, "html_url": "u"})})
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)
        _create_pr("tok", "myorg", "bare-repo", "develop", "homol", "t", "b")
        assert captured["url"] == "https://api.github.com/repos/myorg/bare-repo/pulls"

    def test_create_pr_already_exists_422(self, monkeypatch):
        fake = FakeHTTPClient(
            {"POST": FakeResponse(422, {"errors": ["A pull request already exists"]})}
        )
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)
        result = _create_pr("tok", "org", "org/repo", "develop", "homol", "t", "b")
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_create_pr_connect_error(self, monkeypatch):
        def _client(*a, **k):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "Client", _client)
        result = _create_pr("tok", "org", "org/repo", "develop", "homol", "t", "b")
        assert result["unavailable"] is True

    def test_create_pr_generic_exception(self, monkeypatch):
        def _client(*a, **k):
            raise ValueError("weird")

        monkeypatch.setattr(httpx, "Client", _client)
        result = _create_pr("tok", "org", "org/repo", "develop", "homol", "t", "b")
        assert result["success"] is False
        assert "weird" in result["error"]

    def test_merge_pr_not_configured(self):
        assert _merge_pr("", "", "repo", 1)["unavailable"] is True

    def test_merge_pr_success(self, monkeypatch):
        fake = FakeHTTPClient({"PUT": FakeResponse(200, {"sha": "s1", "message": "ok"})})
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)
        result = _merge_pr("tok", "org", "org/repo", 3, "msg")
        assert result["success"] is True
        assert result["sha"] == "s1"

    def test_merge_pr_http_error(self, monkeypatch):
        fake = FakeHTTPClient({"PUT": FakeResponse(409, text="conflict")})
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake)
        result = _merge_pr("tok", "org", "org/repo", 3)
        assert result["success"] is False
        assert "HTTP 409" in result["error"]

    def test_merge_pr_connect_error(self, monkeypatch):
        def _client(*a, **k):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "Client", _client)
        assert _merge_pr("tok", "org", "org/repo", 3)["unavailable"] is True

    def test_merge_pr_generic_exception(self, monkeypatch):
        def _client(*a, **k):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(httpx, "Client", _client)
        result = _merge_pr("tok", "org", "org/repo", 3)
        assert "kaboom" in result["error"]

    def test_list_open_prs_success(self, monkeypatch):
        list_resp = FakeResponse(
            200,
            [
                {
                    "number": 1,
                    "title": "t",
                    "html_url": "u",
                    "base": {"ref": "develop"},
                    "head": {"ref": "f"},
                    "user": {"login": "dev"},
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: FakeHTTPClient({"GET": list_resp}))
        result = _list_open_prs("tok", "org", "org/repo")
        assert result["success"] is True
        assert result["prs"][0]["base_branch"] == "develop"

    def test_list_open_prs_http_error(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "Client", lambda *a, **k: FakeHTTPClient({"GET": FakeResponse(500, text="x")})
        )
        result = _list_open_prs("tok", "org", "org/repo")
        assert result["success"] is False

    def test_list_open_prs_connect_error(self, monkeypatch):
        def _client(*a, **k):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "Client", _client)
        assert _list_open_prs("tok", "org", "org/repo")["unavailable"] is True

    def test_list_open_prs_generic_exception(self, monkeypatch):
        def _client(*a, **k):
            raise KeyError("bad")

        monkeypatch.setattr(httpx, "Client", _client)
        assert _list_open_prs("tok", "org", "org/repo")["success"] is False

    def test_find_service_for_repo_full_slug(self, registered_store):
        assert _find_service_for_repo(registered_store, "test-org/svc-a") == "svc-a"

    def test_find_service_for_repo_bare_name(self, registered_store):
        assert _find_service_for_repo(registered_store, "svc-a") == "svc-a"

    def test_find_service_for_repo_none(self, store):
        assert _find_service_for_repo(store, "unknown/repo") is None


def test_module_exports_are_callable():
    """As tools reexportadas pelo pacote são as mesmas do módulo."""
    assert pipeline_tool.register_pipeline is register_pipeline
    assert callable(promote_service)


@pytest.mark.parametrize("direction", ["dev->homol", "homol->prod"])
def test_branch_map_has_both_directions(direction):
    assert direction in _BRANCH_MAP
