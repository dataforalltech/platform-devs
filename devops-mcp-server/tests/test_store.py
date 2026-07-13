"""Store canônico contra MySQL real (§16 / FID-02): CRUD das 5 entidades, upsert de
chave natural (environment por name / service config por service), soft-delete e
ISOLAMENTO por tenant."""

from __future__ import annotations

import pytest

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


# ── Artifacts (histórico append-only) ─────────────────────────────────────────
async def test_artifact_history_append_only(store_a):
    a1 = await store_a.save_artifact(
        kind="dockerfile", target="api", content="FROM python:3.12", tool="docker"
    )
    a2 = await store_a.save_artifact(
        kind="helm_chart", target="web", content="apiVersion: v2", spec={"replicas": 3}
    )
    assert isinstance(a1["id"], int) and a1["id"] != a2["id"]
    assert a1["content"] == "FROM python:3.12"  # texto livre, não JSON
    assert a2["spec"] == {"replicas": 3}  # JSON round-trip

    assert {a["id"] for a in await store_a.list_artifacts(kind="dockerfile")} == {a1["id"]}
    assert {a["id"] for a in await store_a.list_artifacts(target="web")} == {a2["id"]}
    assert len(await store_a.list_artifacts()) == 2

    got = await store_a.get_artifact(a1["id"])
    assert got is not None and got["kind"] == "dockerfile"

    assert await store_a.delete_artifact(a1["id"]) == 1
    assert await store_a.get_artifact(a1["id"]) is None
    assert len(await store_a.list_artifacts()) == 1


# ── Pipelines ─────────────────────────────────────────────────────────────────
async def test_pipeline_crud(store_a):
    saved = await store_a.save_pipeline(
        application="api", provider="github_actions", content={"stages": ["build", "test"]}
    )
    assert saved["id"] > 0
    assert saved["application"] == "api"
    assert saved["content"] == {"stages": ["build", "test"]}  # JSON round-trip

    got = await store_a.get_pipeline(saved["id"])
    assert got is not None and got["provider"] == "github_actions"

    updated = await store_a.update_pipeline(saved["id"], status="active", provider="gitlab_ci")
    assert updated is not None and updated["status"] == "active" and updated["provider"] == "gitlab_ci"

    assert len(await store_a.list_pipelines(application="api")) == 1
    assert await store_a.list_pipelines(status="active") != []

    assert await store_a.delete_pipeline(saved["id"]) == 1
    assert await store_a.get_pipeline(saved["id"]) is None
    assert await store_a.list_pipelines() == []


async def test_pipeline_get_missing_returns_none(store_a):
    assert await store_a.get_pipeline(999999) is None
    assert await store_a.update_pipeline(999999, status="x") is None
    assert await store_a.delete_pipeline(999999) == 0


# ── Deployments ───────────────────────────────────────────────────────────────
async def test_deployment_crud(store_a):
    saved = await store_a.save_deployment(
        application="api",
        environment="prod",
        version="v1.2.3",
        strategy="blue_green",
        notes="release",
        meta={"trigger": "manual"},
        status="pending",
    )
    assert saved["id"] > 0
    assert saved["strategy"] == "blue_green" and saved["version"] == "v1.2.3"
    assert saved["meta"] == {"trigger": "manual"}  # JSON round-trip

    updated = await store_a.update_deployment_status(saved["id"], "succeeded")
    assert updated["status"] == "succeeded"

    assert {d["id"] for d in await store_a.list_deployments(environment="prod")} == {saved["id"]}
    assert await store_a.list_deployments(application="api", status="succeeded") != []

    assert await store_a.delete_deployment(saved["id"]) == 1
    assert await store_a.get_deployment(saved["id"]) is None


# ── Environments (upsert por name) ────────────────────────────────────────────
async def test_environment_upsert_by_name(store_a):
    first = await store_a.set_environment("prod-cluster", "kubernetes", region="us-east-1", status="active")
    assert first["name"] == "prod-cluster"
    assert first["region"] == "us-east-1"

    # mesmo name → upsert (não duplica), sobrescreve kind/region/status
    second = await store_a.set_environment(
        "prod-cluster", "kubernetes", region="eu-west-1", status="draining"
    )
    assert second["region"] == "eu-west-1" and second["status"] == "draining"

    envs = await store_a.list_environments()
    assert len(envs) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_environment("prod-cluster")
    assert got is not None and got["region"] == "eu-west-1"
    assert await store_a.get_environment("inexistente") is None

    assert await store_a.delete_environment("prod-cluster") == 1
    assert await store_a.get_environment("prod-cluster") is None


# ── Service Configs (upsert por service) ──────────────────────────────────────
async def test_service_config_upsert_by_service(store_a):
    first = await store_a.set_service_config("svc", {"replicas": 2}, status="active")
    assert first["service"] == "svc"
    assert first["settings"] == {"replicas": 2}

    # mesmo service → upsert (não duplica), sobrescreve settings/status
    second = await store_a.set_service_config("svc", {"replicas": 5}, status="scaled")
    assert second["settings"] == {"replicas": 5} and second["status"] == "scaled"

    configs = await store_a.list_service_configs()
    assert len(configs) == 1  # ON DUPLICATE KEY: uma linha só

    got = await store_a.get_service_config("svc")
    assert got is not None and got["settings"] == {"replicas": 5}
    assert await store_a.get_service_config("inexistente") is None

    assert await store_a.delete_service_config("svc") == 1
    assert await store_a.get_service_config("svc") is None


# ── Isolamento por tenant (banco-por-tenant, dual-db) ─────────────────────────
async def test_tenant_isolation(store_a, store_b):
    await store_a.save_pipeline(application="only-in-a", provider="github_actions")
    await store_a.set_service_config("svc-a", {"x": 1})

    assert len(await store_a.list_pipelines()) == 1
    # o tenant B tem SEU PRÓPRIO banco → não enxerga dados do A
    assert await store_b.list_pipelines() == []
    assert await store_b.list_service_configs() == []
    assert await store_b.get_service_config("svc-a") is None
